from __future__ import annotations


class ChatRuntimeError(RuntimeError):
    """Base error with a stable, client-safe public code."""

    code = "CHAT_INTERNAL_ERROR"


class RetrievalUnavailableError(ChatRuntimeError):
    code = "RETRIEVAL_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("Retrieval is unavailable")


class LLMUnavailableError(ChatRuntimeError):
    code = "LLM_UPSTREAM_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("Language model streaming is unavailable")
