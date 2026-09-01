"""Bounded, evidence-grounded streaming chat module."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["ChatService"]


def __getattr__(name: str) -> Any:
    """Lazily expose runtime services without polluting lightweight imports."""
    if name == "ChatService":
        value = import_module(f"{__name__}.service").ChatService
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
