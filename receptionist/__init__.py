"""Module 1 — Urdu AI Receptionist (voice intake and booking)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent import ReceptionistAgent as ReceptionistAgent

__all__ = ["ReceptionistAgent"]


def __getattr__(name: str) -> Any:
    if name == "ReceptionistAgent":
        from .agent import ReceptionistAgent

        return ReceptionistAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
