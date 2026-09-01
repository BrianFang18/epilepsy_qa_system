"""Shared pytest configuration and isolated test fixtures."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# tests/conftest.py -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class FakeService:
    """Small service double that never loads models, storage, or network clients."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.llm = object()
        self.retriever = object()
        self.embedder = object()
        self.closed = False
        self.seed_calls = 0

    def kb_count(self) -> int:
        return 0

    def seed_demo_data(self) -> None:
        self.seed_calls += 1

    def ask(self, request: Any) -> Any:
        from app.schemas import AskResponse, IntentType

        return AskResponse(
            answer=f"fake:{request.question}",
            intent=IntentType.clinical,
            latency_ms=0.0,
        )

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def settings_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build Settings without reading the repository .env or using real endpoints."""
    from app.config import Settings

    monkeypatch.chdir(tmp_path)

    def build(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "app_name": "Epilepsy QA Test",
            "environment": "test",
            "enable_v2_workflow": False,
            "seed_demo_data": False,
            "mock_mode": True,
            "llm_api_base": "http://127.0.0.1:9/v1",
            "llm_api_key": "test-only",
            "use_qdrant": False,
            "qdrant_url": "http://127.0.0.1:9",
            "embed_model_path": str(tmp_path / "models" / "bge-m3"),
            "reranker_model_path": str(tmp_path / "models" / "bge-reranker"),
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return build


@pytest.fixture
def fake_service_factory():
    """Create fake services bound to a test-specific Settings instance."""

    def build(settings: Any) -> FakeService:
        return FakeService(settings)

    return build
