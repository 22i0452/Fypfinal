"""
main.py — Entry point for the Urdu Medical Receptionist Agent.

Usage
-----
    python main.py                 # from repo root (thin wrapper)
    python -m receptionist         # package entry
    python -m receptionist --no-ui
    python -m receptionist --calibrate
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def main() -> None:
    no_ui     = "--no-ui"    in sys.argv
    calibrate = "--calibrate" in sys.argv

    if no_ui or calibrate:
        from .agent import ReceptionistAgent
        agent = ReceptionistAgent(calibrate_mic=calibrate)
        agent.run()
    else:
        from .ui import launch_ui
        launch_ui()


if __name__ == "__main__":
    main()
