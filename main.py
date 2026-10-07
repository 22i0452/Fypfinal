"""
Root entry point for Module 1 — Urdu Medical Receptionist Agent.

Usage
-----
    python main.py              # Launch GUI (default)
    python main.py --no-ui      # Terminal-only mode
    python main.py --calibrate  # Terminal mode + mic calibration
    python -m receptionist      # Same as python main.py
"""

from __future__ import annotations

from receptionist.main import main


if __name__ == "__main__":
    main()
