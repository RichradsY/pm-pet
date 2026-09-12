"""Read Codex CLI quota without model calls, transcript scans, or credential reads.

This opens its own short-lived App Server and uses the CLI's existing auth context.
It does not attach to Codex Desktop or prove that Desktop uses the same account.
Call from one shared background worker; never call separately for every Pet.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import threading
import time
from typing import Any


SOURCE = "codex-cli-app-server"


class QuotaReadError(Exception):
    """An intentionally sanitized failure with no raw server/auth output."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _window(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not _number(raw.get("usedPercent")):
        return None
    duration = raw.get("windowDurationMins")
    if not _number(duration) or duration <= 0 or int(duration) != duration:
        return None
    remaining = max(0.0, min(100.0, 100.0 - raw["usedPercent"]))
    # Match the UI's round-then-colour rule, including .5 values.
    display = int(math.floor(remaining + 0.5))
    reset = raw.get("resetsAt")
    return {
        "windowDurationMins": int(duration),
        "usedPercent": raw["usedPercent"],
        "remainingPercent": remaining,
        "displayPercent": display,
        "color": "red" if display <= 20 else "orange" if display <= 69 else "green",
        "resetsAt": int(reset) if _number(reset) and reset >= 0 else None,
    }


def normalize_rate_limits(result: Any) -> dict[str, Any]:
    """Keep separate buckets and classify windows by duration, never slot name.

    Only the general ``codex`` bucket feeds the default Pet allowance. A
    model-specific 5h limit must not invent a general 5h allowance. The legacy
    view is a fallback only when the map is absent/null, as specified by Codex.
    """
    if not isinstance(result, dict):
        raise QuotaReadError("invalid_response")
    mapped = result.get("rateLimitsByLimitId")
    if isinstance(mapped, dict):
        raw_buckets = mapped
    else:
        legacy = result.get("rateLimits")
        if not isinstance(legacy, dict):
            raise QuotaReadError("invalid_response")
        raw_buckets = {legacy.get("limitId") or "codex": legacy}

    buckets = {}
    for limit_id, raw in raw_buckets.items():
        if not isinstance(limit_id, str) or not isinstance(raw, dict):
            continue
        windows = {}
        other_windows = []
        for slot in ("primary", "secondary"):
            value = _window(raw.get(slot))
            if value is None:
                continue
            key = {300: "five", 10080: "week"}.get(value["windowDurationMins"])
            if key is not None:
                windows[key] = value
            else:
                other_windows.append(value)
        buckets[limit_id] = {"windows": windows, "otherWindows": other_windows}

    selected = buckets.get("codex")
    return {
        "selectedLimitId": "codex" if selected is not None else None,
        "windows": selected["windows"] if selected is not None else {},
        "buckets": buckets,
    }


class _ReadOnlyAppServer:
    def __init__(self, binary: str, timeout: float):
        self.deadline = time.monotonic() + timeout
        self.messages: queue.Queue[Any] = queue.Queue(maxsize=64)
        self.process = subprocess.Popen(
            [binary, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            start_new_session=True,
        )
        self.reader = threading.Thread(target=self._consume, daemon=True)
        self.reader.start()

    def _consume(self) -> None:
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(message, dict):
                    try:
                        self.messages.put_nowait(message)
                    except queue.Full:
                        # No turn is started/subscribed. A flood cannot grow memory.
                        pass
        except (OSError, UnicodeError):
            pass
        finally:
            try:
                self.messages.put_nowait(None)
            except queue.Full:
                pass

    def send(self, message: dict[str, Any]) -> None:
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise QuotaReadError("server_unavailable") from None

    def request(self, request_id: int, method: str, params: Any) -> dict[str, Any]:
        if method not in {"initialize", "account/read", "account/rateLimits/read"}:
            raise QuotaReadError("method_not_allowed")
        self.send({"id": request_id, "method": method, "params": params})
        while True:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise QuotaReadError("timeout")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty:
                raise QuotaReadError("timeout") from None
            if message is None:
                raise QuotaReadError("server_unavailable")
            if message.get("method") and "id" in message:
                # Decline auth refresh/attestation or any other server request.
                # This client never supplies secrets or answers user approvals.
                self.send({"id": message["id"], "error": {
                    "code": -32601, "message": "Read-only quota client does not handle server requests"
                }})
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                code = error.get("code") if isinstance(error, dict) else None
                description = str(error.get("message", "")).lower() if isinstance(error, dict) else ""
                if code == -32601:
                    raise QuotaReadError("unsupported")
                if any(word in description for word in ("unauthorized", "401", "not logged", "authentication")):
                    raise QuotaReadError("auth_required")
                if any(word in description for word in ("429", "rate limit", "too many requests")):
                    raise QuotaReadError("rate_limited")
                raise QuotaReadError("read_failed")
            if not isinstance(message.get("result"), dict):
                raise QuotaReadError("invalid_response")
            return message["result"]

    def close(self) -> None:
        try:
            self.process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            # A distinct process group only contains this reader's server children.
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=2)
        self.reader.join(timeout=0.2)
        self.process.stdout.close()


def read_codex_quota(codex_binary: str | None = None, timeout: float = 15) -> dict[str, Any]:
    """Fetch one fresh CLI-account snapshot; caller owns cadence and last-good state.

    Returns ``status='ok'`` with ``observedAt`` only after a successful API read.
    On failure, ``status='unavailable'`` and a safe ``errorCode`` are returned;
    no fabricated zero/full quota or new success timestamp is emitted. Auth files
    are never read by this module; Codex manages its own existing authentication.
    """
    base = {"source": SOURCE, "accountScope": "cli", "desktopAccountVerified": False}
    binary = codex_binary or shutil.which("codex")
    if binary is None:
        candidate = Path.home() / ".local" / "bin" / "codex"
        binary = str(candidate) if candidate.is_file() else None
    if binary is None:
        return {**base, "status": "unavailable", "errorCode": "codex_not_found"}
    if not _number(timeout) or timeout <= 0:
        return {**base, "status": "unavailable", "errorCode": "invalid_timeout"}
    server = None
    try:
        server = _ReadOnlyAppServer(binary, min(timeout, 60))
        server.request(1, "initialize", {"clientInfo": {"name": "pm_pet_quota", "version": "0.1.0"}})
        server.send({"method": "initialized", "params": {}})
        account = server.request(2, "account/read", {"refreshToken": False}).get("account")
        if not isinstance(account, dict):
            raise QuotaReadError("auth_required")
        if account.get("type") != "chatgpt":
            raise QuotaReadError("unsupported_account")
        # Do not retain/export email, plan, tokens, or an invented account identity.
        del account
        normalized = normalize_rate_limits(server.request(3, "account/rateLimits/read", None))
        return {
            **base,
            "status": "ok",
            "observedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            **normalized,
        }
    except QuotaReadError as error:
        return {**base, "status": "unavailable", "errorCode": error.code}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {**base, "status": "unavailable", "errorCode": "server_unavailable"}
    finally:
        if server is not None:
            server.close()


def main() -> int:
    """CLI diagnostics intentionally omit usage values and identifying account data."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", required=True,
                        help="Read live CLI quota once and print metadata only")
    parser.add_argument("--codex", help="Optional explicit Codex binary")
    args = parser.parse_args()
    result = read_codex_quota(args.codex)
    summary = {key: result[key] for key in
               ("status", "source", "accountScope", "desktopAccountVerified", "errorCode")
               if key in result}
    if result["status"] == "ok":
        summary.update({
            "authType": "chatgpt",
            "selectedLimitId": result["selectedLimitId"],
            "buckets": {limit_id: {
                "durations": sorted(value["windowDurationMins"] for value in bucket["windows"].values()),
                "otherDurations": sorted(value["windowDurationMins"] for value in bucket["otherWindows"]),
            } for limit_id, bucket in result["buckets"].items()},
        })
    print(json.dumps(summary))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
