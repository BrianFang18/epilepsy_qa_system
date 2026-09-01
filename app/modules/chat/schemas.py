from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EvidenceTier = Literal["A", "B", "C", "Unrated"]
TraceLevel = Literal["summary", "diagnostic"]


class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatHistoryItem] = Field(default_factory=list, max_length=12)
    trace_level: TraceLevel = "summary"


class Citation(BaseModel):
    id: str
    document_id: str
    title: str
    translated_title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    source_url: str | None = None
    evidence_tier: EvidenceTier = "Unrated"
    excerpt: str
    score: float


class PublicTraceEntry(BaseModel):
    node: str
    status: Literal["completed", "skipped", "blocked"] = "completed"
    count: int | None = Field(default=None, ge=0)
    duration_ms: float = Field(default=0.0, ge=0.0)


class ChatStreamEvent(BaseModel):
    event: Literal["meta", "status", "sources", "token", "safety", "done", "error"]
    data: dict[str, Any] = Field(default_factory=dict)


class ChatEventEnvelope(BaseModel):
    request_id: str
    session_id: str
    sequence: int = Field(ge=1)
    event: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)
