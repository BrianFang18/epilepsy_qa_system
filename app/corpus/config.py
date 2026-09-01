"""Strict loading for the checked-in Europe PMC corpus source policy."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.corpus.models import CorpusConfigError

OFFICIAL_API_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
OFFICIAL_QUERY = "((TITLE_ABS:epilepsy) OR (TITLE_ABS:seizure)) AND OPEN_ACCESS:Y AND IN_EPMC:Y"
OFFICIAL_TERMS_URL = "https://europepmc.org/PrivacyNotice"
OFFICIAL_COPYRIGHT_URL = "https://europepmc.org/Copyright"
OFFICIAL_DOCUMENTATION_URL = "https://europepmc.org/RestfulWebService"
OFFICIAL_API_HOSTS = frozenset({"www.ebi.ac.uk", "ebi.ac.uk"})


@dataclass(frozen=True, slots=True)
class LicenseRule:
    spdx: str
    url: str


@dataclass(frozen=True, slots=True)
class SourceConfig:
    schema_version: str
    corpus_version: str
    converter_version: str
    source_version: str
    provider: str
    api_base: str
    query: str
    keywords: tuple[str, ...]
    allowed_hosts: frozenset[str]
    allowed_redirect_hosts: frozenset[str]
    requests_per_second: float
    timeout_seconds: float
    max_response_bytes: int
    download_chunk_bytes: int
    page_size: int
    max_discovery_pages: int
    candidate_limit: int
    candidate_margin: int
    target_count: int
    max_retries: int
    backoff_base_seconds: float
    backoff_max_seconds: float
    jitter_seconds: float
    min_body_chars: int
    include_references: bool
    repository_url: str
    default_user_agent: str
    terms_url: str
    copyright_url: str
    documentation_url: str
    license_allowlist: tuple[LicenseRule, ...]
    gate_notice: str

    @property
    def license_urls(self) -> dict[str, str]:
        return {rule.spdx: rule.url for rule in self.license_allowlist}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> SourceConfig:
        licenses_raw = _list(raw, "license_allowlist")
        licenses: list[LicenseRule] = []
        for index, value in enumerate(licenses_raw):
            if not isinstance(value, Mapping):
                raise _config_error(f"license_allowlist[{index}] must be an object")
            spdx = _string(value, "spdx")
            url = _https_url(_string(value, "url"), f"license_allowlist[{index}].url")
            licenses.append(LicenseRule(spdx=spdx, url=url))

        allowed_hosts = frozenset(host.lower() for host in _string_list(raw, "allowed_hosts"))
        redirect_hosts = frozenset(
            host.lower() for host in _string_list(raw, "allowed_redirect_hosts")
        )
        api_base = _https_url(_string(raw, "api_base"), "api_base").rstrip("/")
        query = _string(raw, "query")
        terms_url = _https_url(_string(raw, "terms_url"), "terms_url")
        copyright_url = _https_url(_string(raw, "copyright_url"), "copyright_url")
        documentation_url = _https_url(_string(raw, "documentation_url"), "documentation_url")
        repository_url = _https_url(_string(raw, "repository_url"), "repository_url")
        default_user_agent = _string(raw, "default_user_agent")

        config = cls(
            schema_version=_string(raw, "schema_version"),
            corpus_version=_string(raw, "corpus_version"),
            converter_version=_string(raw, "converter_version"),
            source_version=_string(raw, "source_version"),
            provider=_string(raw, "provider"),
            api_base=api_base,
            query=query,
            keywords=tuple(word.casefold() for word in _string_list(raw, "keywords")),
            allowed_hosts=allowed_hosts,
            allowed_redirect_hosts=redirect_hosts,
            requests_per_second=_positive_number(raw, "requests_per_second"),
            timeout_seconds=_positive_number(raw, "timeout_seconds"),
            max_response_bytes=_positive_int(raw, "max_response_bytes"),
            download_chunk_bytes=_positive_int(raw, "download_chunk_bytes"),
            page_size=_positive_int(raw, "page_size"),
            max_discovery_pages=_positive_int(raw, "max_discovery_pages"),
            candidate_limit=_positive_int(raw, "candidate_limit"),
            candidate_margin=_positive_int(raw, "candidate_margin"),
            target_count=_positive_int(raw, "target_count"),
            max_retries=_nonnegative_int(raw, "max_retries"),
            backoff_base_seconds=_positive_number(raw, "backoff_base_seconds"),
            backoff_max_seconds=_positive_number(raw, "backoff_max_seconds"),
            jitter_seconds=_nonnegative_number(raw, "jitter_seconds"),
            min_body_chars=_positive_int(raw, "min_body_chars"),
            include_references=_boolean(raw, "include_references"),
            repository_url=repository_url,
            default_user_agent=default_user_agent,
            terms_url=terms_url,
            copyright_url=copyright_url,
            documentation_url=documentation_url,
            license_allowlist=tuple(licenses),
            gate_notice=_string(raw, "gate_notice"),
        )
        config._validate_policy()
        return config

    def _validate_policy(self) -> None:
        if self.api_base != OFFICIAL_API_BASE:
            raise _config_error("api_base must be the official Europe PMC production REST base")
        if self.query != OFFICIAL_QUERY:
            raise _config_error("query must match the fixed checked-in epilepsy query")
        if not self.allowed_hosts or not self.allowed_hosts <= OFFICIAL_API_HOSTS:
            raise _config_error("allowed_hosts must contain only official EBI API hosts")
        if not self.allowed_redirect_hosts <= OFFICIAL_API_HOSTS:
            raise _config_error("allowed_redirect_hosts must contain only official EBI API hosts")
        if urlsplit(self.api_base).hostname not in self.allowed_hosts:
            raise _config_error("api_base host is not in allowed_hosts")
        if self.terms_url != OFFICIAL_TERMS_URL:
            raise _config_error("terms_url must be the checked-in Europe PMC privacy terms URL")
        if self.copyright_url != OFFICIAL_COPYRIGHT_URL:
            raise _config_error("copyright_url must be the checked-in Europe PMC copyright URL")
        if self.documentation_url != OFFICIAL_DOCUMENTATION_URL:
            raise _config_error("documentation_url must be the checked-in REST documentation URL")
        if self.target_count > self.candidate_limit:
            raise _config_error("candidate_limit must be at least target_count")
        if self.candidate_limit < self.target_count + self.candidate_margin:
            raise _config_error("candidate_limit must preserve the configured candidate margin")
        if not 1 <= self.page_size <= 1000:
            raise _config_error("page_size must be between 1 and 1000")
        if self.download_chunk_bytes > self.max_response_bytes:
            raise _config_error("download_chunk_bytes cannot exceed max_response_bytes")
        if self.backoff_max_seconds < self.backoff_base_seconds:
            raise _config_error("backoff_max_seconds cannot be less than the base")
        if not self.license_allowlist:
            raise _config_error("license_allowlist cannot be empty")
        spdx_values = [rule.spdx for rule in self.license_allowlist]
        if len(spdx_values) != len(set(spdx_values)):
            raise _config_error("license_allowlist contains duplicate SPDX identifiers")
        expected = {
            "CC0-1.0",
            "CC-BY-2.0",
            "CC-BY-2.5",
            "CC-BY-3.0",
            "CC-BY-4.0",
        }
        if set(spdx_values) != expected:
            raise _config_error("license_allowlist must be the commercial-friendly policy set")
        if "@" in self.default_user_agent:
            raise _config_error("default_user_agent must not hard-code an email address")
        if self.repository_url not in self.default_user_agent:
            raise _config_error("default_user_agent must include repository_url")


def load_source_config(path: Path) -> SourceConfig:
    """Load JSON without consulting dotenv files or application settings."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _config_error(f"cannot load source configuration: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise _config_error("source configuration root must be an object")
    return SourceConfig.from_mapping(raw)


def _config_error(message: str) -> CorpusConfigError:
    return CorpusConfigError(message, code="invalid_source_config")


def _string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _config_error(f"{key} must be a non-empty string")
    return value.strip()


def _list(raw: Mapping[str, Any], key: str) -> list[Any]:
    value = raw.get(key)
    if not isinstance(value, list) or not value:
        raise _config_error(f"{key} must be a non-empty list")
    return value


def _string_list(raw: Mapping[str, Any], key: str) -> list[str]:
    values = _list(raw, key)
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise _config_error(f"{key} must contain only non-empty strings")
    return [value.strip() for value in values]


def _positive_int(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _config_error(f"{key} must be a positive integer")
    return value


def _nonnegative_int(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _config_error(f"{key} must be a non-negative integer")
    return value


def _positive_number(raw: Mapping[str, Any], key: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise _config_error(f"{key} must be a positive number")
    return float(value)


def _nonnegative_number(raw: Mapping[str, Any], key: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise _config_error(f"{key} must be a non-negative number")
    return float(value)


def _boolean(raw: Mapping[str, Any], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise _config_error(f"{key} must be a boolean")
    return value


def _https_url(value: str, field: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise _config_error(f"{field} must be an HTTPS URL without credentials")
    return value
