from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

JobStatus = Literal["queued", "running", "retry_wait", "succeeded", "failed", "canceled"]
JobStage = Literal["fetch", "parse", "chunk", "embed", "index", "finalize"]
DocumentStatus = Literal["uploaded", "queued", "processing", "active", "failed", "canceled"]
EvaluationSuite = Literal["smoke", "retrieval", "generation", "safety", "full"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: SecretStr = Field(min_length=8, max_length=256)


class AdminUserResponse(BaseModel):
    id: str
    username: str


class AdminSessionResponse(BaseModel):
    user: AdminUserResponse
    expires_at: datetime


class IngestionJobResponse(BaseModel):
    id: str
    document_id: str
    status: JobStatus
    stage: JobStage
    progress: int
    attempts: int
    max_attempts: int
    inserted_parents: int
    inserted_children: int
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DocumentResponse(BaseModel):
    id: str
    filename: str
    title: str
    doc_type: Literal["literature", "clinical"]
    media_type: str
    size_bytes: int
    content_sha256: str
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None = None
    latest_ingestion_job: IngestionJobResponse | None = None


class DocumentUploadResponse(BaseModel):
    document: DocumentResponse
    ingestion_job: IngestionJobResponse
    deduplicated: bool


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


class EvaluationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    suite: EvaluationSuite = "full"


class EvaluationJobResponse(BaseModel):
    id: str
    name: str
    suite: EvaluationSuite
    status: JobStatus
    progress: int
    attempts: int
    max_attempts: int
    aggregate_metrics: dict[str, float] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class EvaluationListResponse(BaseModel):
    items: list[EvaluationJobResponse]
    total: int


class EvaluationSummaryResponse(BaseModel):
    total: int
    status_counts: dict[str, int]
    latest_metrics: dict[str, float]
    latest_completed_at: datetime | None = None
