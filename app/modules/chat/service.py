from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from ...config import Settings
from .errors import LLMUnavailableError
from .graph import ChatGraph
from .ports import LLMStreamPort, RetrieverPort
from .safety import DISCLAIMER, HiddenReasoningFilter, SafeSegmentBuffer, sanitize_segment
from .schemas import ChatRequest, ChatStreamEvent


class ChatService:
    def __init__(self, settings: Settings, retriever: RetrieverPort, llm: LLMStreamPort) -> None:
        self._settings = settings
        self._llm = llm
        self._graph = ChatGraph(settings, retriever)

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
        yield ChatStreamEvent(
            event="meta",
            data={"stream_version": "1", "trace_level": request.trace_level},
        )
        history = [item.model_dump() for item in request.history]
        state = await self._graph.run(message=request.message, history=history)

        for entry in state.get("trace", []):
            yield ChatStreamEvent(event="status", data=entry.model_dump(mode="json"))

        citations = state.get("citations", [])
        yield ChatStreamEvent(
            event="sources",
            data={"citations": [citation.model_dump(mode="json") for citation in citations]},
        )

        action = state.get("action", "refuse")
        if action == "emergency":
            yield ChatStreamEvent(
                event="safety",
                data={
                    "level": "critical",
                    "code": "EMERGENCY_DETECTED",
                    "categories": state.get("emergency_categories", []),
                },
            )
            yield ChatStreamEvent(event="token", data={"content": state.get("local_answer", "")})
            yield ChatStreamEvent(
                event="done", data={"finish_reason": "emergency", "citation_count": 0}
            )
            return

        if action != "generate" or not citations:
            yield ChatStreamEvent(
                event="safety", data={"level": "info", "code": "INSUFFICIENT_EVIDENCE"}
            )
            yield ChatStreamEvent(event="token", data={"content": state.get("local_answer", "")})
            yield ChatStreamEvent(
                event="done", data={"finish_reason": "insufficient_evidence", "citation_count": 0}
            )
            return

        allowed_ids = {citation.id for citation in citations}
        hidden_filter = HiddenReasoningFilter()
        segment_buffer = SafeSegmentBuffer()
        emitted_chars = 0
        emitted_codes: set[str] = set()
        try:
            async for raw_chunk in self._llm.stream(
                state.get("generation_messages", []),
                temperature=self._settings.llm_temperature,
                max_tokens=self._settings.llm_max_tokens,
            ):
                visible = hidden_filter.feed(raw_chunk)
                for segment in segment_buffer.feed(visible):
                    sanitized, codes = sanitize_segment(segment, allowed_ids)
                    for code in codes:
                        if code not in emitted_codes:
                            emitted_codes.add(code)
                            yield ChatStreamEvent(
                                event="safety", data={"level": "warning", "code": code}
                            )
                    if sanitized:
                        emitted_chars += len(sanitized)
                        yield ChatStreamEvent(event="token", data={"content": sanitized})
        except asyncio.CancelledError:
            raise
        except LLMUnavailableError:
            raise
        except Exception:
            raise LLMUnavailableError() from None

        trailing = hidden_filter.finish()
        segments = segment_buffer.feed(trailing)
        remaining = segment_buffer.finish()
        if remaining:
            segments.append(remaining)
        for segment in segments:
            sanitized, codes = sanitize_segment(segment, allowed_ids)
            for code in codes:
                if code not in emitted_codes:
                    emitted_codes.add(code)
                    yield ChatStreamEvent(event="safety", data={"level": "warning", "code": code})
            if sanitized:
                emitted_chars += len(sanitized)
                yield ChatStreamEvent(event="token", data={"content": sanitized})

        if emitted_chars == 0:
            raise LLMUnavailableError()
        yield ChatStreamEvent(event="token", data={"content": f"\n\n{DISCLAIMER}"})
        yield ChatStreamEvent(
            event="done",
            data={
                "finish_reason": "stop",
                "citation_count": len(citations),
                "safety_adjustments": len(emitted_codes),
            },
        )

    async def close(self) -> None:
        await self._llm.close()
