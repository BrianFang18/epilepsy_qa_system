"""Shared, dependency-free models for the corpus pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class CorpusError(Exception):
    """Base exception carrying a stable, non-sensitive error code."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class CorpusConfigError(CorpusError):
    """Raised when source configuration violates a pipeline invariant."""


class UrlSecurityError(CorpusError):
    """Raised before a request can escape the configured HTTPS hosts."""


class HttpRequestError(CorpusError):
    """Raised for permanent or exhausted HTTP failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message, code=code)
        self.status = status
        self.retryable = retryable


class XmlSecurityError(CorpusError):
    """Raised when XML contains a forbidden DTD/entity construct."""


class JatsValidationError(CorpusError):
    """Raised when an article is not usable JATS for this corpus."""


class LicenseRejectedError(CorpusError):
    """Raised when a per-article license does not pass the allowlist gate."""


class ManifestError(CorpusError):
    """Raised for malformed or unsafe manifest data."""


@dataclass(frozen=True, slots=True)
class ArticleCandidate:
    """Search metadata retained until a JATS article is downloaded."""

    pmcid: str
    pmid: str | None
    doi: str | None
    title: str
    abstract: str
    authors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LicenseDecision:
    """A successful, exact license classification."""

    spdx: str
    url: str
    declaration_sha256: str


@dataclass(frozen=True, slots=True)
class NormalizedArticle:
    """Validated metadata plus deterministic canonical bytes."""

    pmcid: str
    pmid: str | None
    doi: str | None
    title: str
    authors: tuple[str, ...]
    license: LicenseDecision
    canonical_bytes: bytes
    canonical_sha256: str


@dataclass(frozen=True, slots=True)
class FileArtifact:
    """Manifest-safe facts about one generated file."""

    path: str
    size: int
    sha256: str

    def to_dict(self) -> dict[str, str | int]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Digest returned after an atomic streamed download."""

    size: int
    sha256: str
    final_url: str


@dataclass(slots=True)
class ValidationReport:
    """Validation outcome designed for body-free JSON output."""

    ok: bool
    counts: dict[str, int] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "counts": dict(sorted(self.counts.items())), "errors": self.errors}
