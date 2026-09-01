from __future__ import annotations

from functools import partial
from typing import Any

from anyio import to_thread

from ...schemas import IndexedChunk, IntentType


class LegacyRetrieverAdapter:
    """Async port around the existing synchronous retriever during migration."""

    def __init__(self, retriever: Any) -> None:
        self._retriever = retriever

    async def retrieve(self, query: str, *, top_k: int) -> list[IndexedChunk]:
        call = partial(self._retriever.retrieve, query, IntentType.both, top_k)
        return await to_thread.run_sync(call)
