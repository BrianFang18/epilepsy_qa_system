from __future__ import annotations

from typing import Any

from ...config import Settings
from ...infrastructure.llm.deepseek import DeepSeekLLMStreamAdapter
from ...infrastructure.llm.demo import DeterministicEvidenceLLMStreamAdapter
from ...infrastructure.retrieval.legacy import LegacyRetrieverAdapter
from .ports import LLMStreamPort, RetrieverPort
from .service import ChatService


def build_chat_service(
    settings: Settings,
    *,
    legacy_retriever: Any | None = None,
    retriever: RetrieverPort | None = None,
    llm: LLMStreamPort | None = None,
) -> ChatService:
    """Build chat with either an explicit test port, honest demo, or real provider."""

    retriever_port = retriever
    if retriever_port is None:
        if legacy_retriever is None:
            raise RuntimeError("A retriever is required for chat startup")
        retriever_port = LegacyRetrieverAdapter(legacy_retriever)

    if llm is not None:
        llm_port = llm
    elif settings.chat_llm_mode == "demo":
        llm_port = DeterministicEvidenceLLMStreamAdapter()
    elif settings.chat_llm_mode == "openai_compatible":
        # Construction validates that a non-placeholder backend-only key exists.
        llm_port = DeepSeekLLMStreamAdapter.from_settings(settings)
    else:  # pragma: no cover - Settings validates the literal before startup.
        raise RuntimeError(f"Unsupported CHAT_LLM_MODE: {settings.chat_llm_mode}")

    return ChatService(settings=settings, retriever=retriever_port, llm=llm_port)
