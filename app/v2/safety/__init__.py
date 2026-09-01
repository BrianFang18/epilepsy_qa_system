"""V2 safety module: 安全护栏"""

from __future__ import annotations

from .guard_v2 import EmergencyDetector, SafetyGuardV2, get_safety_guard

__all__ = [
    "EmergencyDetector",
    "SafetyGuardV2",
    "get_safety_guard",
]
