#!/usr/bin/env python3
"""Locate the developer launcher without modifying the host environment."""
import os
from pathlib import Path
import sys

checkout = Path(os.environ["PM_PET_HOME"]).expanduser() if os.environ.get("PM_PET_HOME") else Path(__file__).resolve().parents[4]
launcher = checkout / "scripts" / "pm-pet.py"
if not launcher.is_file():
    print("PM Pet launcher not found. Set PM_PET_HOME to its source checkout.", file=sys.stderr)
    raise SystemExit(1)
os.execv(sys.executable, [sys.executable, str(launcher), *sys.argv[1:]])
