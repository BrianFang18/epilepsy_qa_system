from __future__ import annotations

import re
from dataclasses import dataclass, field

DISCLAIMER = "免责声明：本系统仅提供循证健康信息，不能替代医生面诊、诊断或处方。"

_CITATION = re.compile(r"\[C(\d+)\]")
_DIRECT_DIAGNOSIS = re.compile(
    r"(?:你|您)(?:就是|已经|患有|得了|确诊为)|(?:可以|能够)确诊(?:为)?",
    re.IGNORECASE,
)
_DIRECT_MEDICATION = re.compile(
    r"(?:建议|请|你|您).{0,8}(?:自行)?(?:停药|停用|加量|减量|换药|改药|调整剂量)",
    re.IGNORECASE,
)
_INDIVIDUAL_DOSE = re.compile(
    r"(?:你|您).{0,20}\b\d+(?:\.\d+)?\s*(?:mg|毫克|g|克)(?:/次|每日|一天)?",
    re.IGNORECASE,
)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;\n])")


def sanitize_segment(text: str, allowed_citation_ids: set[str]) -> tuple[str, list[str]]:
    codes: list[str] = []

    def replace_citation(match: re.Match[str]) -> str:
        citation_id = f"C{match.group(1)}"
        if citation_id in allowed_citation_ids:
            return f"[{citation_id}]"
        codes.append("INVALID_CITATION_REMOVED")
        return ""

    sanitized = _CITATION.sub(replace_citation, text)
    if _DIRECT_DIAGNOSIS.search(sanitized):
        codes.append("DIRECT_DIAGNOSIS_BLOCKED")
        sanitized = "现有信息不能用于确定诊断，需由神经科医生结合病史和检查进行评估。"
    elif _DIRECT_MEDICATION.search(sanitized) or _INDIVIDUAL_DOSE.search(sanitized):
        codes.append("INDIVIDUAL_MEDICATION_ADVICE_BLOCKED")
        sanitized = "请勿自行停药、换药或调整剂量，具体用药应由神经科医生决定。"
    return sanitized, codes


class HiddenReasoningFilter:
    """Remove <think> blocks even when tags are split across stream chunks."""

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    @staticmethod
    def _partial_suffix(value: str, tag: str) -> int:
        for size in range(min(len(value), len(tag) - 1), 0, -1):
            if value[-size:].casefold() == tag[:size].casefold():
                return size
        return 0

    def feed(self, value: str) -> str:
        self._buffer += value
        output: list[str] = []
        while self._buffer:
            target = self._CLOSE if self._inside else self._OPEN
            index = self._buffer.casefold().find(target)
            if index >= 0:
                if not self._inside:
                    output.append(self._buffer[:index])
                self._buffer = self._buffer[index + len(target) :]
                self._inside = not self._inside
                continue
            keep = self._partial_suffix(self._buffer, target)
            ready = self._buffer[:-keep] if keep else self._buffer
            if not self._inside:
                output.append(ready)
            self._buffer = self._buffer[-keep:] if keep else ""
            break
        return "".join(output)

    def finish(self) -> str:
        if self._inside:
            self._buffer = ""
            return ""
        remaining = self._buffer
        self._buffer = ""
        return remaining


@dataclass
class SafeSegmentBuffer:
    max_chars: int = 240
    _buffer: str = field(default="", init=False)

    def feed(self, value: str) -> list[str]:
        self._buffer += value
        parts = _SENTENCE_BOUNDARY.split(self._buffer)
        if len(parts) > 1:
            self._buffer = parts.pop()
        ready = [part for part in parts if part]
        while len(self._buffer) >= self.max_chars:
            ready.append(self._buffer[: self.max_chars])
            self._buffer = self._buffer[self.max_chars :]
        return ready

    def finish(self) -> str:
        remaining = self._buffer
        self._buffer = ""
        return remaining
