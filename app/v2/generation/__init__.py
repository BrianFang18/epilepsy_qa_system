"""V2 generation module: 医生风格生成器"""

from __future__ import annotations

from .prompts_v2 import (
    build_consultation_summary_prompt,
    build_doctor_consultation_prompt,
    build_emergency_detection_prompt,
    build_emr_generation_prompt,
)

__all__ = [
    "build_doctor_consultation_prompt",
    "build_emergency_detection_prompt",
    "build_consultation_summary_prompt",
    "build_emr_generation_prompt",
]
