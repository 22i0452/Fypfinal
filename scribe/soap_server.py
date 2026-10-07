"""Compatibility wrapper for the former standalone Module 2 (scribe) server."""
from __future__ import annotations

import sys
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app, create_app  # noqa: E402


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")


__all__ = ["app", "create_app"]
