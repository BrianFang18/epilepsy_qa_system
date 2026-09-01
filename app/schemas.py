"""
Schemas for the API endpoints. Pydantic 数据模型，用于定义API请求和响应的结构。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    literature = "literature"
    clinical = "clinical"
    both = "both"


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2, description="User question")
    user_id: str | None = None
    conversation_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    with_trace: bool = False


class SourceItem(BaseModel):
    chunk_id: str
    parent_id: str
    doc_id: str
    title: str
    doc_type: str
    score: float
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AskResponse(BaseModel):
    answer: str
    intent: IntentType
    sources: list[SourceItem] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    latency_ms: float


class IngestTextRequest(BaseModel):
    doc_id: str
    title: str
    text: str = Field(..., min_length=10)
    doc_type: Literal["literature", "clinical"] = "literature"
    source: str = "manual"
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestFileRequest(BaseModel):
    file_path: str
    doc_id: str | None = None
    title: str | None = None
    doc_type: Literal["literature", "clinical"] = "literature"
    source: str = "file"
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    inserted_parents: int
    inserted_children: int
    doc_id: str


class EvalSample(BaseModel):
    question: str
    ground_truth: str
    retrieved_contexts: list[str] = Field(default_factory=list)
    response: str = ""


class RagasEvalRequest(BaseModel):
    samples: list[EvalSample]


class RagasEvalResponse(BaseModel):
    metrics: dict[str, float]
    details: dict[str, Any] = Field(default_factory=dict)


class JudgeRequest(BaseModel):
    question: str
    answer: str
    references: list[str] = Field(default_factory=list)


class JudgeResponse(BaseModel):
    total_score: float
    safety_score: float
    professionalism_score: float
    factuality_score: float
    verdict: str
    rationale: str


class IndexedChunk(BaseModel):
    chunk_id: str
    parent_id: str
    doc_id: str
    title: str
    doc_type: str
    text: str
    parent_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    dense_vector: list[float] = Field(default_factory=list)
    sparse_vector: dict[int, float] = Field(default_factory=dict)
    score: float = 0.0
