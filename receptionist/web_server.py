"""Deprecated launcher.

Receptionist desk now runs on the main Medflow port:

    python -m uvicorn app.main:app
    http://127.0.0.1:8000/Receptionist
"""
from __future__ import annotations


def main() -> None:
    print("[Receptionist Web] The desk UI is now served by the main Medflow app.")
    print("[Receptionist Web] Start: python -m uvicorn app.main:app")
    print("[Receptionist Web] Open:  http://127.0.0.1:8000/Receptionist")


if __name__ == "__main__":
    main()
