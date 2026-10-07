"""Backward-compatible startup wrapper for the canonical MedFlowAI app."""
from __future__ import annotations

import uvicorn

from app.main import app, create_app


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")


__all__ = ["app", "create_app"]
