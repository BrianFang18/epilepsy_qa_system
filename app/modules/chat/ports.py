from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from ...schemas import IndexedChunk


class RetrieverPort(Protocol):
    async def retrieve(self, query: str, *, top_k: int) -> list[IndexedChunk]:
        """Retrieve request-scoped evidence without persisting the query."""
        ...


class LLMStreamPort(Protocol):
    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        """Yield visible answer text only; never yield hidden reasoning."""
        ...

    async def close(self) -> None:
        """Release provider resources."""
        ...
