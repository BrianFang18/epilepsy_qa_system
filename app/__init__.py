"""Application package with side-effect-free imports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["v2"]


def __getattr__(name: str) -> Any:
    """Preserve ``from app import v2`` without eagerly importing V2."""
    if name == "v2":
        module = import_module(f"{__name__}.v2")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
