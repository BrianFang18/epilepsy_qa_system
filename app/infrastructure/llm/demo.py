from __future__ import annotations

import re
from collections.abc import AsyncIterator

from ...utils import simple_tokenize

_CITATION_BLOCK = re.compile(
    r"^\[(C\d+)\]\s+([^\n]+)\n(.*?)(?=^\[C\d+\]\s+|\Z)",
    re.MULTILINE | re.DOTALL,
)
_WHITESPACE = re.compile(r"\s+")
_HAN = re.compile(r"[\u3400-\u9fff]")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "can",
    "do",
    "during",
    "how",
    "i",
    "is",
    "my",
    "or",
    "should",
    "the",
    "what",
}


class DeterministicEvidenceLLMStreamAdapter:
    """Render lexically related excerpts without pretending to be an LLM."""

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        del temperature, max_tokens
        question = next(
            (item.get("content", "") for item in reversed(messages) if item.get("role") == "user"),
            "",
        )
        system_text = "\n".join(
            item.get("content", "") for item in messages if item.get("role") == "system"
        )
        evidence = system_text.split("Evidence:\n", 1)[-1] if "Evidence:\n" in system_text else ""
        parsed = [
            (citation_id, title.strip(), _WHITESPACE.sub(" ", body).strip())
            for citation_id, title, body in _CITATION_BLOCK.findall(evidence)
            if body.strip()
        ]
        query_tokens = {token for token in simple_tokenize(question) if token not in _STOPWORDS}
        ranked: list[tuple[int, int, tuple[str, str, str]]] = []
        for position, block in enumerate(parsed):
            citation_id, title, body = block
            overlap = len(query_tokens & set(simple_tokenize(f"{title} {body}")))
            if overlap > 0:
                ranked.append((-overlap, position, (citation_id, title, body)))
        blocks = [item[2] for item in sorted(ranked)[:3]]

        is_chinese = "Answer in Chinese because" in system_text or (
            "Answer in English because" not in system_text and bool(_HAN.search(question))
        )
        if is_chinese:
            heading = "【确定性 Demo 模式】以下内容不是大语言模型生成，而是从已检索到的本地证据中直接摘取："
            rows = [f"- {body[:500]} [{citation_id}]" for citation_id, _title, body in blocks]
            footer = "如需模型进行自然语言归纳，请配置 CHAT_LLM_MODE=openai_compatible。"
        else:
            heading = (
                "[Deterministic demo mode] This is not an LLM-generated answer. "
                "It directly shows excerpts from the retrieved local evidence:"
            )
            rows = [f"- {body[:500]} [{citation_id}]" for citation_id, _title, body in blocks]
            footer = "Configure CHAT_LLM_MODE=openai_compatible to enable model-based synthesis."

        if not rows:
            rows = [
                "- 检索结果与问题没有足够的词法重叠，Demo 模式不展示无关摘录。"
                if is_chinese
                else (
                    "- The retrieved results had insufficient lexical overlap; "
                    "demo mode will not display unrelated excerpts."
                )
            ]
        yield "\n\n".join((heading, "\n".join(rows), footer))

    async def close(self) -> None:
        return None
