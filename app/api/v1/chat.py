from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from ...modules.chat.errors import ChatRuntimeError
from ...modules.chat.schemas import ChatEventEnvelope, ChatRequest, ChatStreamEvent

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ChatServiceLike(Protocol):
    def stream(self, request: ChatRequest) -> AsyncIterator[ChatStreamEvent]: ...


def _get_chat_service(request: Request) -> ChatServiceLike:
    service = getattr(request.app.state, "chat_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CHAT_NOT_READY"},
        )
    return service


def _encode_sse(envelope: ChatEventEnvelope) -> str:
    payload = json.dumps(
        envelope.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    )
    return f"event: {envelope.event}\nid: {envelope.request_id}:{envelope.sequence}\ndata: {payload}\n\n"


async def _close_stream(stream: Any) -> None:
    close = getattr(stream, "aclose", None)
    if callable(close):
        with suppress(Exception):
            await close()


async def stream_sse(
    *,
    http_request: Request,
    chat_request: ChatRequest,
    chat_service: ChatServiceLike,
) -> AsyncIterator[str]:
    if await http_request.is_disconnected():
        return

    request_id = str(uuid.uuid4())
    sequence = 0
    domain_stream = chat_service.stream(chat_request)
    try:
        async for internal in domain_stream:
            if await http_request.is_disconnected():
                await _close_stream(domain_stream)
                return
            sequence += 1
            yield _encode_sse(
                ChatEventEnvelope(
                    request_id=request_id,
                    session_id=str(chat_request.session_id),
                    sequence=sequence,
                    event=internal.event,
                    data=internal.data,
                )
            )
    except asyncio.CancelledError:
        await _close_stream(domain_stream)
        raise
    except Exception as exc:
        sequence += 1
        code = exc.code if isinstance(exc, ChatRuntimeError) else "CHAT_INTERNAL_ERROR"
        yield _encode_sse(
            ChatEventEnvelope(
                request_id=request_id,
                session_id=str(chat_request.session_id),
                sequence=sequence,
                event="error",
                data={"code": code, "support_id": str(uuid.uuid4())},
            )
        )
    finally:
        await _close_stream(domain_stream)


@router.post("/stream")
async def stream_chat(chat_request: ChatRequest, request: Request) -> StreamingResponse:
    if chat_request.trace_level == "diagnostic":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "DIAGNOSTIC_TRACE_REQUIRES_ADMIN"},
        )
    service = _get_chat_service(request)
    return StreamingResponse(
        stream_sse(http_request=request, chat_request=chat_request, chat_service=service),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
