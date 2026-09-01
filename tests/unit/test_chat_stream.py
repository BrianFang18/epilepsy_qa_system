from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.v1.chat import stream_sse
from app.infrastructure.llm.deepseek import DeepSeekLLMStreamAdapter
from app.main import create_app
from app.modules.chat.schemas import ChatRequest, ChatStreamEvent
from app.modules.chat.service import ChatService
from app.schemas import IndexedChunk


class FakeRetriever:
    def __init__(self, chunks: list[IndexedChunk]) -> None:
        self.chunks = chunks
        self.calls = 0

    async def retrieve(self, query: str, *, top_k: int) -> list[IndexedChunk]:
        self.calls += 1
        return self.chunks[:top_k]


class FakeLLM:
    def __init__(self, chunks: list[str] | None = None, error: Exception | None = None) -> None:
        self.chunks = chunks or []
        self.error = error
        self.calls = 0
        self.closed = False

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        for chunk in self.chunks:
            yield chunk

    async def close(self) -> None:
        self.closed = True


class StaticChatService:
    def __init__(self, events: list[ChatStreamEvent] | None = None, error: Exception | None = None):
        self.events = events or []
        self.error = error
        self.closed = False

    async def stream(self, _request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
        for event in self.events:
            yield event
        if self.error is not None:
            raise self.error

    async def close(self) -> None:
        self.closed = True


def _indexed_chunk() -> IndexedChunk:
    return IndexedChunk(
        chunk_id="arbitrary/chunk:id",
        parent_id="parent-1",
        doc_id="doc-1",
        title="Epilepsy evidence",
        doc_type="literature",
        text="发作时应记录持续时间，并按急症标准及时求助。",
        parent_text="可靠资料建议记录发作持续时间，持续发作时应启动急救流程。",
        metadata={
            "translated_title": "癫痫证据",
            "authors": ["A. Author"],
            "year": 2024,
            "source_url": "https://example.invalid/evidence",
            "evidence_tier": "A",
        },
        score=0.91,
    )


def _request(message: str = "发作时该记录什么？", **overrides: Any) -> ChatRequest:
    values: dict[str, Any] = {
        "session_id": uuid4(),
        "message": message,
        "history": [],
        "trace_level": "summary",
    }
    values.update(overrides)
    return ChatRequest(**values)


async def _collect_service_events(
    service: ChatService, request: ChatRequest
) -> list[ChatStreamEvent]:
    return [event async for event in service.stream(request)]


def _parse_sse(body: str) -> list[dict[str, Any]]:
    envelopes: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        data_line = next((line for line in block.splitlines() if line.startswith("data: ")), None)
        if data_line:
            envelopes.append(json.loads(data_line.removeprefix("data: ")))
    return envelopes


def test_sse_normal_order_sequence_headers_and_sources_before_tokens(
    settings_factory,
    fake_service_factory,
) -> None:
    settings = settings_factory()
    retriever = FakeRetriever([_indexed_chunk()])
    llm = FakeLLM(["根据当前证据，应记录持续时间[C1]。"])
    chat_service = ChatService(settings=settings, retriever=retriever, llm=llm)
    application = create_app(
        settings=settings,
        service=fake_service_factory(settings),
        chat_service=chat_service,
    )

    with TestClient(application) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={"session_id": str(uuid4()), "message": "发作时该记录什么？"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert "根据当前证据" in response.text

    envelopes = _parse_sse(response.text)
    assert [item["sequence"] for item in envelopes] == list(range(1, len(envelopes) + 1))
    assert len({item["request_id"] for item in envelopes}) == 1
    assert all(UUID(item["request_id"]) for item in envelopes)
    assert all(
        item["event"] in {"meta", "status", "sources", "token", "safety", "done", "error"}
        for item in envelopes
    )
    event_names = [item["event"] for item in envelopes]
    assert event_names[0] == "meta"
    assert event_names.index("sources") < event_names.index("token")
    assert event_names[-1] == "done"
    source = next(item for item in envelopes if item["event"] == "sources")
    citation = source["data"]["citations"][0]
    assert citation == {
        "id": "C1",
        "document_id": "doc-1",
        "title": "Epilepsy evidence",
        "translated_title": "癫痫证据",
        "authors": ["A. Author"],
        "year": 2024,
        "source_url": "https://example.invalid/evidence",
        "evidence_tier": "A",
        "excerpt": "发作时应记录持续时间，并按急症标准及时求助。",
        "score": 0.91,
    }


@pytest.mark.asyncio
async def test_no_evidence_refuses_without_calling_llm(settings_factory) -> None:
    retriever = FakeRetriever([])
    llm = FakeLLM(["must not be used"])
    service = ChatService(settings=settings_factory(), retriever=retriever, llm=llm)

    events = await _collect_service_events(service, _request())

    assert llm.calls == 0
    assert next(event for event in events if event.event == "sources").data == {"citations": []}
    assert any(
        event.event == "safety" and event.data["code"] == "INSUFFICIENT_EVIDENCE"
        for event in events
    )
    text = "".join(event.data["content"] for event in events if event.event == "token")
    assert "没有足够证据" in text


@pytest.mark.asyncio
async def test_emergency_guidance_skips_retrieval_and_llm(settings_factory) -> None:
    retriever = FakeRetriever([_indexed_chunk()])
    llm = FakeLLM(["must not be used"])
    service = ChatService(settings=settings_factory(), retriever=retriever, llm=llm)

    events = await _collect_service_events(
        service,
        _request("患者抽搐已经持续超过5分钟，而且叫不醒"),
    )

    assert retriever.calls == 0
    assert llm.calls == 0
    text = "".join(event.data["content"] for event in events if event.event == "token")
    assert "立即呼叫急救" in text
    assert "120" in text
    assert "不要往口中塞任何物品" in text


class FakeOpenAIStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> FakeOpenAIStream:
        return self

    async def __anext__(self) -> Any:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class FakeCompletions:
    def __init__(self, response: FakeOpenAIStream) -> None:
        self.response = response

    async def create(self, **_kwargs: Any) -> FakeOpenAIStream:
        return self.response


class FakeAsyncOpenAI:
    def __init__(self, chunks: list[Any]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(FakeOpenAIStream(chunks)))
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _openai_chunk(*, content: str | None, reasoning: str | None = None) -> Any:
    delta = SimpleNamespace(content=content, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


@pytest.mark.asyncio
async def test_deepseek_adapter_never_emits_reasoning_or_cross_chunk_think() -> None:
    client = FakeAsyncOpenAI(
        [
            _openai_chunk(content=None, reasoning="PRIVATE_REASONING"),
            _openai_chunk(content="公开前<thi"),
            _openai_chunk(content="nk>PRIVATE_THINK</th"),
            _openai_chunk(content="ink>公开后。"),
        ]
    )
    adapter = DeepSeekLLMStreamAdapter(
        base_url="https://example.invalid/v1",
        api_key="test-only",
        model="fake",
        timeout_seconds=1.0,
        client=client,
    )

    visible = "".join(
        [
            item
            async for item in adapter.stream(
                [{"role": "user", "content": "test"}],
                temperature=0.0,
                max_tokens=20,
            )
        ]
    )

    assert visible == "公开前公开后。"
    assert "PRIVATE_REASONING" not in visible
    assert "PRIVATE_THINK" not in visible


@pytest.mark.asyncio
async def test_invalid_citation_is_removed_and_safety_event_is_emitted(settings_factory) -> None:
    service = ChatService(
        settings=settings_factory(),
        retriever=FakeRetriever([_indexed_chunk()]),
        llm=FakeLLM(["无效引用[C99]不得出现，有效引用[C1]可以保留。"]),
    )

    events = await _collect_service_events(service, _request())
    text = "".join(event.data["content"] for event in events if event.event == "token")

    assert "C99" not in text
    assert "[C1]" in text
    assert any(
        event.event == "safety" and event.data["code"] == "INVALID_CITATION_REMOVED"
        for event in events
    )


def test_upstream_error_is_safe_and_contains_only_public_error_fields(
    settings_factory,
    fake_service_factory,
) -> None:
    settings = settings_factory()
    secret = "sk-private-key /home/private/path upstream-body"
    chat_service = StaticChatService(
        events=[ChatStreamEvent(event="meta", data={"stream_version": "1"})],
        error=RuntimeError(secret),
    )
    application = create_app(
        settings=settings,
        service=fake_service_factory(settings),
        chat_service=chat_service,
    )

    with TestClient(application) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={"session_id": str(uuid4()), "message": "test"},
        )

    envelopes = _parse_sse(response.text)
    error = envelopes[-1]
    assert error["event"] == "error"
    assert set(error["data"]) == {"code", "support_id"}
    assert error["data"]["code"] == "CHAT_INTERNAL_ERROR"
    UUID(error["data"]["support_id"])
    assert secret not in response.text
    assert "private" not in response.text


class FakeRequestConnection:
    def __init__(self, answers: list[bool] | None = None) -> None:
        self.answers = list(answers or [False])

    async def is_disconnected(self) -> bool:
        if len(self.answers) > 1:
            return self.answers.pop(0)
        return self.answers[0]


class CountingChatService:
    def __init__(self) -> None:
        self.stream_calls = 0

    def stream(self, _request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
        self.stream_calls += 1

        async def events() -> AsyncIterator[ChatStreamEvent]:
            yield ChatStreamEvent(event="done", data={})

        return events()


@pytest.mark.asyncio
async def test_already_disconnected_request_does_not_start_chat() -> None:
    chat = CountingChatService()
    output = [
        item
        async for item in stream_sse(
            http_request=FakeRequestConnection([True]),  # type: ignore[arg-type]
            chat_request=_request(),
            chat_service=chat,
        )
    ]

    assert output == []
    assert chat.stream_calls == 0


class BlockingChatService:
    def __init__(self) -> None:
        self.closed = False
        self.block = asyncio.Event()

    async def stream(self, _request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
        try:
            yield ChatStreamEvent(event="meta", data={})
            await self.block.wait()
        finally:
            self.closed = True


@pytest.mark.asyncio
async def test_cancellation_closes_active_domain_stream() -> None:
    service = BlockingChatService()
    stream = cast(
        AsyncGenerator[str, None],
        stream_sse(
            http_request=FakeRequestConnection([False]),  # type: ignore[arg-type]
            chat_request=_request(),
            chat_service=service,
        ),
    )
    await anext(stream)
    pending: asyncio.Future[str] = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    with suppress(StopAsyncIteration):
        await stream.aclose()

    assert service.closed is True


@pytest.mark.parametrize(
    "payload",
    [
        {"history": [{"role": "user", "content": "x"}] * 13},
        {"history": [{"role": "system", "content": "x"}]},
        {"history": [{"role": "user", "content": "x" * 4001}]},
    ],
)
def test_history_boundaries_are_rejected(
    payload: dict[str, Any],
    settings_factory,
    fake_service_factory,
) -> None:
    settings = settings_factory()
    application = create_app(
        settings=settings,
        service=fake_service_factory(settings),
        chat_service=StaticChatService(),
    )
    request_body = {"session_id": str(uuid4()), "message": "test", **payload}

    with TestClient(application) as client:
        response = client.post("/api/v1/chat/stream", json=request_body)

    assert response.status_code == 422


def test_anonymous_diagnostic_trace_is_forbidden(
    settings_factory,
    fake_service_factory,
) -> None:
    settings = settings_factory()
    application = create_app(
        settings=settings,
        service=fake_service_factory(settings),
        chat_service=StaticChatService(),
    )

    with TestClient(application) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={
                "session_id": str(uuid4()),
                "message": "test",
                "trace_level": "diagnostic",
            },
        )

    assert response.status_code == 403
