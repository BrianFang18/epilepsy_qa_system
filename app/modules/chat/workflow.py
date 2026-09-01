"""Compatibility import for the single typed chat graph.

New code should import :mod:`app.modules.chat.graph` directly.
"""

from .graph import ChatGraph, ChatGraphState

__all__ = ["ChatGraph", "ChatGraphState"]
