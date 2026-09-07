from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from ...config import Settings
from ...modules.chat.errors import LLMUnavailableError
from ...modules.chat.safety import HiddenReasoningFilter

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionChunk, ChatCompletionMessageParam


class DeepSeekLLMStreamAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        client: Any | None = None,
    ) -> None:
        normalized_base_url = base_url.strip()
        normalized_api_key = api_key.strip()
        normalized_model = model.strip()
        parsed_url = urlparse(normalized_base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise RuntimeError(
                "CHAT_LLM_MODE=openai_compatible requires an explicit HTTP(S) backend endpoint"
            )
        placeholder_key = normalized_api_key.upper()
        if (
            not normalized_api_key
            or placeholder_key in {"EMPTY", "CHANGE_ME", "CHANGEME", "YOUR_API_KEY"}
            or placeholder_key.startswith("CHANGE_ME_")
        ):
            raise RuntimeError(
                "CHAT_LLM_MODE=openai_compatible requires a non-placeholder backend-only API key"
            )
        if not normalized_model:
            raise RuntimeError(
                "CHAT_LLM_MODE=openai_compatible requires an explicit provider model ID"
            )
        if client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise RuntimeError("Install the runtime dependency group to use DeepSeek") from exc
            client = AsyncOpenAI(
                api_key=normalized_api_key,
                base_url=normalized_base_url,
                timeout=timeout_seconds,
                max_retries=1,
            )
        self._model = normalized_model
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings) -> DeepSeekLLMStreamAdapter:
        return cls(
            base_url=settings.deepseek_base_url or "",
            api_key=settings.deepseek_api_key or "",
            model=settings.deepseek_model or "",
            timeout_seconds=settings.deepseek_timeout_seconds,
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        hidden_filter = HiddenReasoningFilter()
        try:
            provider_messages = cast(
                "Iterable[ChatCompletionMessageParam]",
                messages,
            )
            response = cast(
                "AsyncIterator[ChatCompletionChunk]",
                await self._client.chat.completions.create(
                    model=self._model,
                    messages=provider_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                ),
            )
            async for chunk in response:
                for choice in chunk.choices:
                    delta = choice.delta
                    # reasoning_content is intentionally ignored.
                    content = getattr(delta, "content", None)
                    if content:
                        visible = hidden_filter.feed(content)
                        if visible:
                            yield visible
            remaining = hidden_filter.finish()
            if remaining:
                yield remaining
        except Exception:
            raise LLMUnavailableError() from None

    async def close(self) -> None:
        await self._client.close()
