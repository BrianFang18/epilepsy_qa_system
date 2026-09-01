from __future__ import annotations

from typing import Any

from ...config import Settings
from ...infrastructure.llm.deepseek import DeepSeekLLMStreamAdapter
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
    """Build the production chat slice or use explicitly injected test ports."""

    retriever_port = retriever
    if retriever_port is None:
        if legacy_retriever is None:
            raise RuntimeError("A retriever is required for chat startup")
        retriever_port = LegacyRetrieverAdapter(legacy_retriever)

    llm_port = llm or DeepSeekLLMStreamAdapter.from_settings(settings)
    return ChatService(settings=settings, retriever=retriever_port, llm=llm_port)
