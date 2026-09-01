from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ...schemas import IndexedChunk
from .schemas import Citation, EvidenceTier

_VALID_TIERS = {"A", "B", "C", "Unrated"}


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _authors_from(metadata: dict[str, Any]) -> list[str]:
    raw = metadata.get("authors", [])
    if isinstance(raw, str):
        normalized = raw.replace("；", ";")
        separator = ";" if ";" in normalized else ","
        return [part.strip() for part in normalized.split(separator) if part.strip()]
    if isinstance(raw, Iterable) and not isinstance(raw, bytes | dict):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _year_from(metadata: dict[str, Any]) -> int | None:
    raw = metadata.get("year")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        year = int(raw)
    except (TypeError, ValueError):
        return None
    return year if 1000 <= year <= 9999 else None


def _tier_from(metadata: dict[str, Any]) -> EvidenceTier:
    raw = str(metadata.get("evidence_tier", "Unrated")).strip()
    normalized = raw.upper() if raw.upper() in {"A", "B", "C"} else raw.title()
    if normalized not in _VALID_TIERS:
        return "Unrated"
    return normalized  # type: ignore[return-value]


def _source_url_from(metadata: dict[str, Any]) -> str | None:
    for key in ("source_url", "url", "doi_url"):
        candidate = _clean_optional_text(metadata.get(key))
        if candidate and candidate.lower().startswith(("https://", "http://")):
            return candidate
    return None


def build_evidence_bundle(
    chunks: list[IndexedChunk],
    *,
    max_context_chars: int,
    max_excerpt_chars: int,
) -> tuple[list[IndexedChunk], list[Citation], str]:
    """Build prompt evidence and citations from the same bounded chunk set."""

    used_chunks: list[IndexedChunk] = []
    citations: list[Citation] = []
    rows: list[str] = []
    consumed = 0

    for chunk in chunks:
        evidence = (chunk.parent_text or chunk.text).strip().replace("\x00", " ")
        excerpt = chunk.text.strip().replace("\x00", " ")
        if not evidence or not excerpt:
            continue

        citation_id = f"C{len(citations) + 1}"
        row = f"[{citation_id}] {chunk.title}\n{evidence}\n"
        if consumed + len(row) > max_context_chars:
            if rows:
                break
            available = max(max_context_chars - len(citation_id) - len(chunk.title) - 6, 1)
            evidence = evidence[:available]
            row = f"[{citation_id}] {chunk.title}\n{evidence}\n"

        metadata = chunk.metadata or {}
        citations.append(
            Citation(
                id=citation_id,
                document_id=chunk.doc_id,
                title=chunk.title,
                translated_title=_clean_optional_text(metadata.get("translated_title")),
                authors=_authors_from(metadata),
                year=_year_from(metadata),
                source_url=_source_url_from(metadata),
                evidence_tier=_tier_from(metadata),
                excerpt=excerpt[:max_excerpt_chars],
                score=float(chunk.score),
            )
        )
        used_chunks.append(chunk)
        rows.append(row)
        consumed += len(row)

    return used_chunks, citations, "\n".join(rows)
