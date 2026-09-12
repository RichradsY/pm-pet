"""One nonblocking quota reader per bridge, independent from model activity."""
from datetime import datetime, timezone
import queue
import re
import threading
import time


def iso_at(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class QuotaScheduler:
    ACTIVE_SECONDS = 60
    IDLE_SECONDS = 300

    def __init__(self, reader, monotonic=time.monotonic, wall_clock=time.time):
        self.reader = reader
        self.clock = monotonic
        self.wall_clock = wall_clock
        self.results = queue.Queue(maxsize=1)
        self.worker = None
        self.cancel = None
        self.context = None
        self.last_fingerprint = None
        self.epoch = 0
        self.next_due = None
        self.last_success = None
        self.last_attempt = None
        self.failures = 0
        self.meta = {"mode": "paused", "intervalSeconds": None, "nextAttemptAt": None}

    def schedule(self, due, now):
        self.next_due = due
        self.meta["nextAttemptAt"] = iso_at(self.wall_clock() + max(0, due - now)) if due is not None else None

    def _read(self, context, epoch, cancellation):
        try:
            value = self.reader(context[0], cancel_event=cancellation)
        except Exception:
            # Never publish exception messages, server output, or auth details.
            value = {"status": "unavailable", "errorCode": "read_failed"}
        self.results.put((context, epoch, value))

    def tick(self, pets, binding):
        now = self.clock()
        enabled = [pet for pet in pets if pet.get("enabled")]
        visible = any(pet.get("quotaVisible") for pet in enabled)
        active = any((pet.get("turnState") or {}).get("status") == "running" and not pet.get("question") for pet in enabled)
        interval = self.ACTIVE_SECONDS if active else self.IDLE_SECONDS
        fingerprint = (binding or {}).get("fingerprint")
        valid = isinstance(fingerprint, str) and bool(re.fullmatch(r"[0-9a-f]{64}", fingerprint))
        context = (fingerprint, binding.get("observedAt")) if valid and visible else None
        # Invalidate a worker before consuming it if account evidence or visibility changed.
        if context != self.context:
            self.epoch += 1
            if self.cancel:
                self.cancel.set()
            self.context = context
            self.failures = 0
            self.meta.pop("errorCode", None)
            if context and context[0] != self.last_fingerprint:
                self.last_success = None
                self.meta.pop("lastSuccessAt", None)
                self.last_fingerprint = context[0]
            self.meta["mode"] = "automatic" if context else "paused" if not visible else "waiting_for_account"
            # A new account check warrants one read; restoring the same context
            # still respects the global minimum interval across hidden/visible.
            minimum = self.last_attempt + 10 if self.last_attempt is not None else now
            if context and self.last_success is not None:
                minimum = max(minimum, self.last_success + self.ACTIVE_SECONDS)
            self.schedule(max(now, minimum) if context else None, now)
        elif not context:
            self.meta["mode"] = "paused" if not visible else "waiting_for_account"

        value = None
        try:
            completed_context, epoch, result = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            if self.worker:
                self.worker.join(timeout=0)
            self.worker = None
            self.cancel = None
            if completed_context == context and epoch == self.epoch and context:
                value = result
                if result.get("status") == "ok" and result.get("accountFingerprint") == context[0]:
                    self.failures = 0
                    self.last_success = now
                    self.meta.update(mode="automatic", lastSuccessAt=result.get("observedAt"))
                    self.meta.pop("errorCode", None)
                    self.schedule(now + interval, now)
                else:
                    self.failures += 1
                    code = result.get("errorCode", "read_failed")
                    self.meta.update(mode="error", errorCode=code)
                    self.schedule(now + max(interval, min(1800, 60 * 2 ** min(self.failures - 1, 5))), now)

        previous_interval = self.meta.get("intervalSeconds")
        self.meta["intervalSeconds"] = interval if context else None
        if context and previous_interval is not None and previous_interval != interval and self.last_success is not None and not self.failures:
            self.schedule(max(now, self.last_success + interval), now)
        if context and self.worker is None and self.next_due is not None and now >= self.next_due:
            self.last_attempt = now
            self.meta.update(mode="refreshing", lastAttemptAt=iso_at(self.wall_clock()), nextAttemptAt=None)
            self.next_due = None
            self.cancel = threading.Event()
            self.worker = threading.Thread(target=self._read, args=(context, self.epoch, self.cancel), daemon=True)
            self.worker.start()
        return value, dict(self.meta)

    def close(self):
        if self.cancel:
            self.cancel.set()
        if self.worker:
            self.worker.join(timeout=8)
