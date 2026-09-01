"""Cursor-based Europe PMC discovery with client-side epilepsy filtering."""

from __future__ import annotations

import re
from typing import Any, Protocol
from urllib.parse import urlencode

from app.corpus.config import SourceConfig
from app.corpus.models import ArticleCandidate, HttpRequestError

_PMCID_RE = re.compile(r"^PMC(\d+)$", re.IGNORECASE)


class JsonClient(Protocol):
    def get_json(self, url: str) -> dict[str, Any]: ...


class EuropePmcDiscovery:
    def __init__(self, config: SourceConfig, client: JsonClient) -> None:
        self.config = config
        self.client = client

    def discover(self, limit: int | None = None) -> list[ArticleCandidate]:
        candidate_limit = limit or self.config.candidate_limit
        if candidate_limit <= 0:
            raise ValueError("candidate limit must be positive")
        cursor = "*"
        seen_cursors: set[str] = set()
        candidates: dict[str, ArticleCandidate] = {}

        for _page in range(self.config.max_discovery_pages):
            if cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
            payload = self.client.get_json(self._search_url(cursor))
            results = self._results(payload)
            for raw in results:
                candidate = self._candidate(raw)
                if candidate is None or not self._keyword_match(candidate):
                    continue
                candidates.setdefault(candidate.pmcid, candidate)
                if len(candidates) >= candidate_limit:
                    break
            if len(candidates) >= candidate_limit:
                break
            next_cursor = payload.get("nextCursorMark")
            if not isinstance(next_cursor, str) or not next_cursor or not results:
                break
            cursor = next_cursor

        return sorted(candidates.values(), key=lambda item: pmcid_sort_key(item.pmcid))[
            :candidate_limit
        ]

    def _search_url(self, cursor: str) -> str:
        params = [
            ("query", self.config.query),
            ("format", "json"),
            ("resultType", "core"),
            ("pageSize", str(self.config.page_size)),
            ("cursorMark", cursor),
        ]
        return f"{self.config.api_base}/search?{urlencode(params)}"

    @staticmethod
    def _results(payload: dict[str, Any]) -> list[dict[str, Any]]:
        result_list = payload.get("resultList")
        if not isinstance(result_list, dict):
            raise HttpRequestError(
                "search response lacks resultList",
                code="invalid_search_response",
            )
        results = result_list.get("result")
        if not isinstance(results, list):
            raise HttpRequestError(
                "search response lacks result array",
                code="invalid_search_response",
            )
        return [item for item in results if isinstance(item, dict)]

    @staticmethod
    def _candidate(raw: dict[str, Any]) -> ArticleCandidate | None:
        pmcid_value = raw.get("pmcid")
        if not isinstance(pmcid_value, str):
            return None
        match = _PMCID_RE.fullmatch(pmcid_value.strip())
        if match is None:
            return None
        pmcid = f"PMC{int(match.group(1))}"
        title = _clean_text(raw.get("title"))
        abstract = _clean_text(raw.get("abstractText"))
        if not title and not abstract:
            return None
        return ArticleCandidate(
            pmcid=pmcid,
            pmid=_optional_id(raw.get("pmid")),
            doi=_optional_doi(raw.get("doi")),
            title=title,
            abstract=abstract,
            authors=_authors(raw.get("authorList")),
        )

    def _keyword_match(self, candidate: ArticleCandidate) -> bool:
        haystack = f"{candidate.title}\n{candidate.abstract}".casefold()
        return any(keyword in haystack for keyword in self.config.keywords)


def pmcid_sort_key(pmcid: str) -> tuple[int, str]:
    match = _PMCID_RE.fullmatch(pmcid)
    if match is None:
        return (2**63 - 1, pmcid)
    return (int(match.group(1)), pmcid)


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _optional_id(value: object) -> str | None:
    cleaned = _clean_text(value)
    return cleaned or None


def _optional_doi(value: object) -> str | None:
    cleaned = _clean_text(value).lower()
    return cleaned or None


def _authors(value: object) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()
    raw_authors = value.get("author")
    if not isinstance(raw_authors, list):
        return ()
    names: list[str] = []
    for raw in raw_authors:
        if not isinstance(raw, dict):
            continue
        name = _clean_text(raw.get("fullName"))
        if not name:
            first = _clean_text(raw.get("firstName"))
            last = _clean_text(raw.get("lastName"))
            name = " ".join(part for part in (first, last) if part)
        if name and "@" not in name and name not in names:
            names.append(name)
    return tuple(names)
