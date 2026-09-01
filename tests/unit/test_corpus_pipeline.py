from __future__ import annotations

import hashlib
import io
import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.corpus.config import SourceConfig, load_source_config
from app.corpus.discovery import EuropePmcDiscovery
from app.corpus.http import SafeHttpClient
from app.corpus.jats import normalize_jats, strip_doctype
from app.corpus.manifest import deduplicate_records, read_manifest, write_manifest_atomic
from app.corpus.models import (
    DownloadResult,
    HttpRequestError,
    ManifestError,
    UrlSecurityError,
    ValidationReport,
    XmlSecurityError,
)
from app.corpus.pipeline import (
    CorpusPipelineError,
    resolve_pipeline_paths,
    sync_corpus,
    validate_corpus,
)
from scripts import corpus_pipeline as pipeline_cli

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "corpus_sources.json"
_NOW = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
_REQUIRED_MANIFEST_FIELDS = {
    "schema_version",
    "corpus_version",
    "converter_version",
    "source_version",
    "pmcid",
    "pmid",
    "doi",
    "title",
    "authors",
    "source",
    "retrieved_at",
    "license",
    "raw",
    "canonical",
    "partition",
    "status",
    "error_code",
    "aliases",
}
_CC_BY = """
<license license-type="open-access"
         xlink:href="https://creativecommons.org/licenses/by/4.0/">
  <license-p>Creative Commons Attribution International License 4.0</license-p>
</license>
"""
_CC0 = """
<license license-type="open-access"
         xlink:href="https://creativecommons.org/publicdomain/zero/1.0/">
  <license-p>CC0 1.0 Universal</license-p>
</license>
"""


@pytest.fixture
def source_config() -> SourceConfig:
    base = load_source_config(_CONFIG_PATH)
    return replace(
        base,
        corpus_version="test_corpus_v1",
        target_count=1,
        candidate_limit=5,
        candidate_margin=4,
        page_size=2,
        max_discovery_pages=5,
        max_retries=2,
        backoff_base_seconds=1.0,
        backoff_max_seconds=10.0,
        jitter_seconds=0.0,
        min_body_chars=80,
    )


class FakeResponse:
    def __init__(
        self,
        payload: bytes,
        *,
        status: int = 200,
        url: str = "https://www.ebi.ac.uk/resource",
        headers: Mapping[str, str] | None = None,
        fail_after_reads: int | None = None,
    ) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self._stream = io.BytesIO(payload)
        self._url = url
        self._reads = 0
        self._fail_after_reads = fail_after_reads
        self.closed = False

    def read(self, size: int) -> bytes:
        if self._fail_after_reads is not None and self._reads >= self._fail_after_reads:
            raise urllib.error.URLError("offline test failure")
        self._reads += 1
        return self._stream.read(size)

    def close(self) -> None:
        self.closed = True

    def geturl(self) -> str:
        return self._url


class QueueTransport:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, timeout: float) -> Any:
        del timeout
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeJsonClient:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = list(pages)
        self.urls: list[str] = []

    def get_json(self, url: str) -> dict[str, Any]:
        self.urls.append(url)
        return self.pages.pop(0)


class FakePipelineClient:
    def __init__(
        self,
        pages: list[dict[str, Any]],
        documents: Mapping[str, bytes | BaseException],
    ) -> None:
        self.pages = list(pages)
        self.documents = dict(documents)
        self.discovery_urls: list[str] = []
        self.download_urls: list[str] = []

    def get_json(self, url: str) -> dict[str, Any]:
        self.discovery_urls.append(url)
        if not self.pages:
            raise AssertionError("unexpected discovery request")
        return self.pages.pop(0)

    def download_atomic(self, url: str, destination: Path) -> DownloadResult:
        self.download_urls.append(url)
        pmcid = url.rstrip("/").split("/")[-2]
        value = self.documents[pmcid]
        part = destination.with_name(f"{destination.name}.part")
        part.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, BaseException):
            part.write_bytes(b"partial-body-that-must-be-removed")
            raise value
        part.write_bytes(value)
        part.replace(destination)
        digest = hashlib.sha256(value).hexdigest()
        return DownloadResult(size=len(value), sha256=digest, final_url=url)


def _result(
    pmcid: str,
    *,
    doi: str | None = None,
    title: str = "Epilepsy cohort",
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "pmcid": pmcid,
        "pmid": pmcid.removeprefix("PMC"),
        "title": title,
        "abstractText": "Seizure outcomes in an epilepsy cohort.",
        "authorList": {"author": [{"fullName": "Ada Researcher"}]},
    }
    if doi is not None:
        value["doi"] = doi
    return value


def _page(
    results: list[dict[str, Any]],
    *,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"resultList": {"result": results}}
    if next_cursor is not None:
        payload["nextCursorMark"] = next_cursor
    return payload


def _jats(
    pmcid: str,
    *,
    license_xml: str = _CC_BY,
    doi: str | None = None,
    title: str = "Epilepsy Study",
    body_marker: str = "CLINICAL_BODY_SENTINEL",
    prefix: bytes = b"",
) -> bytes:
    doi_xml = f'<article-id pub-id-type="doi">{doi}</article-id>' if doi else ""
    body = f"{body_marker} seizure evidence " + ("safe clinical prose " * 40)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <front>
    <article-meta>
      <article-id pub-id-type="pmc">{pmcid}</article-id>
      <article-id pub-id-type="pmid">{pmcid.removeprefix('PMC')}</article-id>
      {doi_xml}
      <title-group><article-title>{title}</article-title></title-group>
      <contrib-group>
        <contrib contrib-type="author"><name><surname>Lovelace</surname>
        <given-names>Ada</given-names></name></contrib>
      </contrib-group>
      <permissions>{license_xml}</permissions>
      <abstract><p>Epilepsy abstract suitable for discovery.</p></abstract>
    </article-meta>
  </front>
  <body><sec><title>Results</title><p>{body}</p></sec></body>
</article>
""".encode()
    if not prefix:
        return xml
    declaration_end = xml.index(b"?>") + 2
    return xml[:declaration_end] + b"\n" + prefix + xml[declaration_end + 1 :]


def _clock() -> datetime:
    return _NOW


def _make_repo(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    repository.mkdir()
    return repository


def _http_error(status: int, *, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        "https://www.ebi.ac.uk/resource",
        status,
        "offline test status",
        headers,
        io.BytesIO(b""),
    )


def _safe_client(
    source_config: SourceConfig,
    transport: QueueTransport,
    sleeps: list[float] | None = None,
    *,
    max_retries: int | None = None,
) -> SafeHttpClient:
    observed_sleeps = sleeps if sleeps is not None else []
    ticks = iter(float(value) for value in range(0, 1000, 10))
    return SafeHttpClient(
        allowed_hosts=source_config.allowed_hosts,
        allowed_redirect_hosts=source_config.allowed_redirect_hosts,
        user_agent=source_config.default_user_agent,
        requests_per_second=source_config.requests_per_second,
        timeout_seconds=source_config.timeout_seconds,
        max_response_bytes=source_config.max_response_bytes,
        chunk_bytes=32,
        max_retries=source_config.max_retries if max_retries is None else max_retries,
        backoff_base_seconds=source_config.backoff_base_seconds,
        backoff_max_seconds=source_config.backoff_max_seconds,
        jitter_seconds=0.0,
        transport=transport,
        sleep=observed_sleeps.append,
        monotonic=lambda: next(ticks),
        random_value=lambda: 0.0,
    )


def test_cursor_discovery_is_bounded_filtered_and_deterministic(
    source_config: SourceConfig,
) -> None:
    client = FakeJsonClient(
        [
            _page(
                [
                    _result("PMC20"),
                    {
                        **_result("PMC99", title="Unrelated cardiology"),
                        "abstractText": "Cardiac outcomes only.",
                    },
                ],
                next_cursor="next+value",
            ),
            _page([_result("PMC3"), _result("PMC20")]),
        ]
    )

    candidates = EuropePmcDiscovery(source_config, client).discover(limit=3)

    assert [candidate.pmcid for candidate in candidates] == ["PMC3", "PMC20"]
    assert parse_qs(urlsplit(client.urls[0]).query)["cursorMark"] == ["*"]
    assert parse_qs(urlsplit(client.urls[1]).query)["cursorMark"] == ["next+value"]
    assert all(url.startswith(f"{source_config.api_base}/search?") for url in client.urls)


def test_http_retries_429_retry_after_and_5xx_backoff(
    source_config: SourceConfig,
) -> None:
    transport = QueueTransport(
        [
            _http_error(429, retry_after="7"),
            _http_error(503),
            FakeResponse(b"ok"),
        ]
    )
    sleeps: list[float] = []
    client = _safe_client(source_config, transport, sleeps)

    assert client.get_bytes("https://www.ebi.ac.uk/resource") == b"ok"
    assert sleeps == [7.0, 2.0]
    assert len(transport.requests) == 3


def test_http_rejects_unallowlisted_redirect_final_host(
    source_config: SourceConfig,
) -> None:
    transport = QueueTransport([FakeResponse(b"body", url="https://attacker.invalid/fullTextXML")])
    client = _safe_client(source_config, transport)

    with pytest.raises(UrlSecurityError) as raised:
        client.get_bytes("https://www.ebi.ac.uk/resource")

    assert raised.value.code == "host_not_allowed"


def test_atomic_download_removes_part_after_stream_failure(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    response = FakeResponse(b"partial payload", fail_after_reads=1)
    client = _safe_client(source_config, QueueTransport([response]), max_retries=0)
    destination = tmp_path / "article.xml"

    with pytest.raises(HttpRequestError) as raised:
        client.download_atomic("https://www.ebi.ac.uk/resource", destination)

    assert raised.value.code == "http_retry_exhausted"
    assert not destination.exists()
    assert not (tmp_path / "article.xml.part").exists()


@pytest.mark.parametrize(
    ("license_xml", "expected_spdx"),
    [(_CC_BY, "CC-BY-4.0"), (_CC0, "CC0-1.0")],
)
def test_commercial_friendly_licenses_pass(
    source_config: SourceConfig,
    license_xml: str,
    expected_spdx: str,
) -> None:
    article = normalize_jats(
        _jats("PMC1", license_xml=license_xml),
        expected_pmcid="PMC1",
        source_url=f"{source_config.api_base}/PMC1/fullTextXML",
        license_allowlist=source_config.license_urls,
        min_body_chars=source_config.min_body_chars,
    )

    assert article.license.spdx == expected_spdx


@pytest.mark.parametrize(
    "license_xml",
    [
        "<license><license-p>Creative Commons BY-NC 4.0</license-p></license>",
        "<license><license-p>Creative Commons BY-ND 4.0</license-p></license>",
        "<license><license-p>Creative Commons BY-SA 4.0</license-p></license>",
        "<license><license-p>Custom license for this publisher</license-p></license>",
        "",
    ],
)
def test_restrictive_custom_and_missing_licenses_are_rejected(
    source_config: SourceConfig,
    license_xml: str,
) -> None:
    from app.corpus.models import LicenseRejectedError

    with pytest.raises(LicenseRejectedError):
        normalize_jats(
            _jats("PMC1", license_xml=license_xml),
            expected_pmcid="PMC1",
            source_url=f"{source_config.api_base}/PMC1/fullTextXML",
            license_allowlist=source_config.license_urls,
            min_body_chars=source_config.min_body_chars,
        )


def test_external_doctype_is_stripped_but_entities_and_internal_subset_are_rejected(
    source_config: SourceConfig,
) -> None:
    external = b'<!DOCTYPE article SYSTEM "https://example.invalid/jats.dtd">\n'
    normalized = normalize_jats(
        _jats("PMC1", prefix=external),
        expected_pmcid="PMC1",
        source_url=f"{source_config.api_base}/PMC1/fullTextXML",
        license_allowlist=source_config.license_urls,
        min_body_chars=source_config.min_body_chars,
    )
    assert normalized.pmcid == "PMC1"
    assert b"DOCTYPE" not in strip_doctype(_jats("PMC1", prefix=external))

    with pytest.raises(XmlSecurityError) as entity_error:
        strip_doctype(b'<!DOCTYPE article [<!ENTITY xxe "value">]><article/>')
    with pytest.raises(XmlSecurityError) as subset_error:
        strip_doctype(b"<!DOCTYPE article [<!ELEMENT article ANY>]><article/>")

    assert entity_error.value.code == "xml_entity_forbidden"
    assert subset_error.value.code == "xml_internal_subset_forbidden"


def test_canonical_output_is_byte_deterministic(source_config: SourceConfig) -> None:
    first = normalize_jats(
        _jats("PMC7", doi="10.1000/ABC"),
        expected_pmcid="PMC7",
        source_url=f"{source_config.api_base}/PMC7/fullTextXML",
        license_allowlist=source_config.license_urls,
        min_body_chars=source_config.min_body_chars,
    )
    second = normalize_jats(
        _jats("PMC7", doi="10.1000/ABC"),
        expected_pmcid="PMC7",
        source_url=f"{source_config.api_base}/PMC7/fullTextXML",
        license_allowlist=source_config.license_urls,
        min_body_chars=source_config.min_body_chars,
    )

    assert first.canonical_bytes == second.canonical_bytes
    assert first.canonical_sha256 == second.canonical_sha256
    assert first.doi == "10.1000/abc"
    assert first.authors == ("Ada Lovelace",)
    assert first.canonical_bytes.endswith(b"\n")


def test_output_paths_reject_escape_and_symlink(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    repository = _make_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ManifestError) as escaped:
        resolve_pipeline_paths(repository, source_config, artifact_root=outside)
    assert escaped.value.code == "path_escape"

    link = repository / "linked"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ManifestError) as symlinked:
        resolve_pipeline_paths(repository, source_config, artifact_root=link / "artifacts")
    assert symlinked.value.code == "symlink_path_forbidden"


def test_active_only_dedupe_adds_aliases_and_keeps_rejected_audit(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    repository = _make_repo(tmp_path)
    config = replace(source_config, target_count=2)
    shared_doi = "10.1000/shared"
    client = FakePipelineClient(
        [_page([_result("PMC1"), _result("PMC2"), _result("PMC3")])],
        {
            "PMC1": _jats("PMC1", doi=shared_doi),
            "PMC2": _jats("PMC2", doi=shared_doi),
            "PMC3": _jats(
                "PMC3",
                doi=shared_doi,
                license_xml=(
                    "<license><license-p>Creative Commons BY-NC 4.0</license-p></license>"
                ),
            ),
        },
    )

    report = sync_corpus(
        repository,
        config,
        target=2,
        candidate_limit=3,
        client=client,
        clock=_clock,
    )
    paths = resolve_pipeline_paths(repository, config)
    records = read_manifest(paths.manifest_path)

    assert not report.ok
    assert report.errors == [{"code": "target_not_met"}]
    assert len(records) == 2
    active = next(record for record in records if record["status"] == "active")
    rejected = next(record for record in records if record["status"] == "rejected")
    assert active["pmcid"] == "PMC1"
    assert active["aliases"] == [{"pmcid": "PMC2", "pmid": "2", "doi": shared_doi}]
    assert rejected["pmcid"] == "PMC3"
    assert rejected["canonical"] is None


def test_deduplicate_records_is_transitive_and_deterministic() -> None:
    records: list[dict[str, Any]] = [
        {
            "pmcid": "PMC30",
            "pmid": "300",
            "doi": None,
            "raw": {"sha256": "a" * 64},
            "canonical": {"sha256": "b" * 64},
            "aliases": [],
            "status": "active",
        },
        {
            "pmcid": "PMC20",
            "pmid": "200",
            "doi": "10.1/shared",
            "raw": {"sha256": "c" * 64},
            "canonical": {"sha256": "d" * 64},
            "aliases": [],
            "status": "active",
        },
        {
            "pmcid": "PMC10",
            "pmid": "300",
            "doi": "10.1/shared",
            "raw": {"sha256": "e" * 64},
            "canonical": {"sha256": "f" * 64},
            "aliases": [],
            "status": "active",
        },
    ]

    output = deduplicate_records(records)

    assert [record["pmcid"] for record in output] == ["PMC10"]
    assert [alias["pmcid"] for alias in output[0]["aliases"]] == ["PMC20", "PMC30"]


def test_resume_has_zero_network_then_redownloads_corrupt_and_stale_active(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    repository = _make_repo(tmp_path)
    page = _page([_result("PMC1")])
    first_client = FakePipelineClient([page], {"PMC1": _jats("PMC1")})
    first_report = sync_corpus(
        repository,
        source_config,
        candidate_limit=1,
        client=first_client,
        clock=_clock,
    )
    assert first_report.ok

    no_network = FakePipelineClient([], {})
    resumed = sync_corpus(
        repository,
        source_config,
        candidate_limit=1,
        client=no_network,
        clock=_clock,
    )
    assert resumed.ok
    assert no_network.discovery_urls == []
    assert no_network.download_urls == []

    paths = resolve_pipeline_paths(repository, source_config)
    record = read_manifest(paths.manifest_path)[0]
    raw_path = repository / record["raw"]["path"]
    raw_path.write_bytes(b"corrupt")
    repair_client = FakePipelineClient([page], {"PMC1": _jats("PMC1")})
    repaired = sync_corpus(
        repository,
        source_config,
        candidate_limit=1,
        client=repair_client,
        clock=_clock,
    )
    assert repaired.ok
    assert repair_client.download_urls == [f"{source_config.api_base}/PMC1/fullTextXML"]

    stale_record = read_manifest(paths.manifest_path)[0]
    stale_record["converter_version"] = "stale-converter"
    write_manifest_atomic([stale_record], paths.manifest_path)
    stale_client = FakePipelineClient([page], {"PMC1": _jats("PMC1")})
    refreshed = sync_corpus(
        repository,
        source_config,
        candidate_limit=1,
        client=stale_client,
        clock=_clock,
    )
    assert refreshed.ok
    assert len(stale_client.download_urls) == 1
    assert read_manifest(paths.manifest_path)[0]["converter_version"] == (
        source_config.converter_version
    )


def test_rejected_and_failed_records_keep_only_safe_raw_and_are_not_redownloaded(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    repository = _make_repo(tmp_path)
    client = FakePipelineClient(
        [_page([_result("PMC10"), _result("PMC11"), _result("PMC12")])],
        {
            "PMC10": _jats(
                "PMC10",
                license_xml=(
                    "<license><license-p>Creative Commons BY-ND 4.0</license-p></license>"
                ),
            ),
            "PMC11": HttpRequestError("offline", code="http_503"),
            "PMC12": RuntimeError("sensitive exception text"),
        },
    )

    report = sync_corpus(
        repository,
        source_config,
        target=1,
        candidate_limit=3,
        client=client,
        clock=_clock,
    )
    paths = resolve_pipeline_paths(repository, source_config)
    records = read_manifest(paths.manifest_path)
    by_pmcid = {record["pmcid"]: record for record in records}

    assert not report.ok
    assert by_pmcid["PMC10"]["status"] == "rejected"
    assert by_pmcid["PMC10"]["error_code"] == "license_prohibited"
    assert by_pmcid["PMC10"]["raw"] is not None
    assert by_pmcid["PMC10"]["canonical"] is None
    assert by_pmcid["PMC11"]["status"] == "failed"
    assert by_pmcid["PMC11"]["error_code"] == "http_503"
    assert by_pmcid["PMC11"]["raw"] is None
    assert by_pmcid["PMC12"]["error_code"] == "unexpected_error"
    assert not list(paths.raw_root.glob("*.part"))
    assert not list(paths.canonical_root.glob("*.part"))

    resumed_client = FakePipelineClient(
        [_page([_result("PMC10"), _result("PMC11"), _result("PMC12")])],
        {},
    )
    resumed = sync_corpus(
        repository,
        source_config,
        target=1,
        candidate_limit=3,
        client=resumed_client,
        clock=_clock,
    )
    assert not resumed.ok
    assert resumed_client.download_urls == []


def test_target_gate_can_be_raised_without_network(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    repository = _make_repo(tmp_path)
    client = FakePipelineClient([_page([_result("PMC1")])], {"PMC1": _jats("PMC1")})
    assert sync_corpus(
        repository,
        source_config,
        target=1,
        candidate_limit=1,
        client=client,
        clock=_clock,
    ).ok

    higher_gate = validate_corpus(repository, source_config, target=2)

    assert not higher_gate.ok
    assert {error["code"] for error in higher_gate.errors} == {"target_not_met"}
    assert higher_gate.counts["unique_normalized"] == 1
    assert higher_gate.counts["target"] == 2


@pytest.mark.parametrize(
    ("target", "candidate_limit", "code"),
    [
        (0, 1, "invalid_target"),
        (True, 1, "invalid_target"),
        (1, 0, "invalid_candidate_limit"),
        (2, 1, "invalid_candidate_limit"),
        (1, 6, "invalid_candidate_limit"),
    ],
)
def test_explicit_limits_are_strict_positive_integers_and_bounded(
    source_config: SourceConfig,
    tmp_path: Path,
    target: Any,
    candidate_limit: Any,
    code: str,
) -> None:
    repository = _make_repo(tmp_path)

    with pytest.raises(CorpusPipelineError) as raised:
        sync_corpus(
            repository,
            source_config,
            target=target,
            candidate_limit=candidate_limit,
            client=FakePipelineClient([], {}),
            clock=_clock,
        )

    assert raised.value.code == code


def test_manifest_and_summary_are_metadata_only_and_repository_relative(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    repository = _make_repo(tmp_path)
    sentinel = "VERY_PRIVATE_BODY_SENTINEL"
    client = FakePipelineClient(
        [_page([_result("PMC42")])],
        {"PMC42": _jats("PMC42", body_marker=sentinel)},
    )

    report = sync_corpus(
        repository,
        source_config,
        candidate_limit=1,
        client=client,
        clock=_clock,
    )
    paths = resolve_pipeline_paths(repository, source_config)
    manifest_text = paths.manifest_path.read_text(encoding="utf-8")
    summary_text = paths.summary_path.read_text(encoding="utf-8")
    record = json.loads(manifest_text)
    summary = json.loads(summary_text)

    assert report.ok
    assert set(record) == _REQUIRED_MANIFEST_FIELDS
    assert record["source"]["full_text_url"] == (f"{source_config.api_base}/PMC42/fullTextXML")
    assert not Path(record["raw"]["path"]).is_absolute()
    assert not Path(record["canonical"]["path"]).is_absolute()
    assert sentinel not in manifest_text
    assert sentinel not in summary_text
    assert "sensitive exception text" not in manifest_text
    assert "/home/" not in manifest_text + summary_text
    assert summary["counts"]["unique_normalized"] == 1
    assert summary["manifest_path"] == (f"data/manifests/{source_config.corpus_version}.jsonl")


def test_existing_malformed_or_unsafe_manifest_fails_closed_before_network(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    repository = _make_repo(tmp_path)
    initial = FakePipelineClient([_page([_result("PMC1")])], {"PMC1": _jats("PMC1")})
    assert sync_corpus(
        repository,
        source_config,
        candidate_limit=1,
        client=initial,
        clock=_clock,
    ).ok
    paths = resolve_pipeline_paths(repository, source_config)
    original = read_manifest(paths.manifest_path)[0]

    unsafe = dict(original)
    unsafe["body"] = "must never be trusted"
    write_manifest_atomic([unsafe], paths.manifest_path)
    no_network = FakePipelineClient([], {})
    with pytest.raises(ManifestError) as forbidden:
        sync_corpus(
            repository,
            source_config,
            candidate_limit=1,
            client=no_network,
            clock=_clock,
        )
    assert forbidden.value.code == "manifest_forbidden_field"
    assert no_network.discovery_urls == []

    escaped = dict(original)
    escaped["raw"] = {**escaped["raw"], "path": "../escape.xml"}
    write_manifest_atomic([escaped], paths.manifest_path)
    with pytest.raises(ManifestError) as path_error:
        sync_corpus(
            repository,
            source_config,
            candidate_limit=1,
            client=no_network,
            clock=_clock,
        )
    assert path_error.value.code == "path_escape"
    assert no_network.discovery_urls == []


def _write_cli_config(repository: Path) -> Path:
    raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    raw.update(
        {
            "corpus_version": "cli_test_corpus",
            "candidate_limit": 2,
            "candidate_margin": 1,
            "target_count": 1,
            "min_body_chars": 80,
        }
    )
    path = repository / "source.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_cli_sync_and_validate_emit_only_compact_report_and_gate_exit_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _make_repo(tmp_path)
    _write_cli_config(repository)
    success = ValidationReport(ok=True, counts={"target": 1}, errors=[])
    monkeypatch.setattr(pipeline_cli, "sync_corpus", lambda *args, **kwargs: success)

    sync_exit = pipeline_cli.main(
        [
            "sync",
            "--repo-root",
            str(repository),
            "--config",
            "source.json",
            "--manifest",
            "output/corpus.jsonl",
            "--summary",
            "output/corpus.summary.json",
            "--artifact-root",
            "output/artifacts",
            "--target",
            "1",
            "--candidate-limit",
            "2",
        ]
    )
    sync_output = capsys.readouterr()

    assert sync_exit == 0
    assert sync_output.err == ""
    assert sync_output.out == '{"counts":{"target":1},"errors":[],"ok":true}\n'

    missing_exit = pipeline_cli.main(
        [
            "validate",
            "--repo-root",
            str(repository),
            "--config",
            "source.json",
            "--manifest",
            "output/missing.jsonl",
            "--summary",
            "output/unused.summary.json",
            "--artifact-root",
            "output/artifacts",
            "--target",
            "1",
        ]
    )
    missing_output = capsys.readouterr()

    assert missing_exit == 2
    assert missing_output.err == ""
    parsed = json.loads(missing_output.out)
    assert parsed["ok"] is False
    assert parsed["errors"] == [{"code": "manifest_missing"}]


def test_cli_operational_error_is_stable_and_stderr_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _make_repo(tmp_path)
    _write_cli_config(repository)

    def fail(*args: Any, **kwargs: Any) -> ValidationReport:
        del args, kwargs
        raise CorpusPipelineError("sensitive detail", code="stable_test_error")

    monkeypatch.setattr(pipeline_cli, "sync_corpus", fail)
    exit_code = pipeline_cli.main(
        [
            "sync",
            "--repo-root",
            str(repository),
            "--config",
            "source.json",
            "--manifest",
            "output/corpus.jsonl",
            "--summary",
            "output/corpus.summary.json",
            "--artifact-root",
            "output/artifacts",
            "--target",
            "1",
            "--candidate-limit",
            "2",
        ]
    )
    output = capsys.readouterr()

    assert exit_code == 2
    assert output.out == ""
    assert output.err == '{"error":"stable_test_error"}\n'
    assert "sensitive detail" not in output.err


def test_keyboard_interrupt_checkpoints_completed_records_for_resume(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    repository = _make_repo(tmp_path)
    page = _page([_result("PMC1"), _result("PMC2")])
    interrupted_client = FakePipelineClient(
        [page],
        {
            "PMC1": _jats("PMC1"),
            "PMC2": KeyboardInterrupt(),
        },
    )

    with pytest.raises(KeyboardInterrupt):
        sync_corpus(
            repository,
            source_config,
            target=2,
            candidate_limit=2,
            client=interrupted_client,
            clock=_clock,
        )

    paths = resolve_pipeline_paths(repository, source_config)
    checkpoint = read_manifest(paths.manifest_path)
    assert [record["pmcid"] for record in checkpoint] == ["PMC1"]
    assert not list(paths.raw_root.glob("*.part"))
    assert not list(paths.canonical_root.glob("*.part"))

    resumed_client = FakePipelineClient(
        [page],
        {"PMC2": _jats("PMC2")},
    )
    report = sync_corpus(
        repository,
        source_config,
        target=2,
        candidate_limit=2,
        client=resumed_client,
        clock=_clock,
    )

    assert report.ok
    assert resumed_client.download_urls == [f"{source_config.api_base}/PMC2/fullTextXML"]


def test_repairing_deduplicated_winner_preserves_aliases(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    repository = _make_repo(tmp_path)
    shared_doi = "10.1000/repair-alias"
    initial = FakePipelineClient(
        [_page([_result("PMC1"), _result("PMC2")])],
        {
            "PMC1": _jats("PMC1", doi=shared_doi),
            "PMC2": _jats("PMC2", doi=shared_doi),
        },
    )
    initial_report = sync_corpus(
        repository,
        source_config,
        target=2,
        candidate_limit=2,
        client=initial,
        clock=_clock,
    )
    assert not initial_report.ok

    paths = resolve_pipeline_paths(repository, source_config)
    winner = read_manifest(paths.manifest_path)[0]
    assert winner["aliases"][0]["pmcid"] == "PMC2"
    (repository / winner["raw"]["path"]).write_bytes(b"corrupt")

    repair = FakePipelineClient(
        [_page([_result("PMC1")])],
        {"PMC1": _jats("PMC1", doi=shared_doi)},
    )
    repaired = sync_corpus(
        repository,
        source_config,
        target=1,
        candidate_limit=1,
        client=repair,
        clock=_clock,
    )
    repaired_winner = read_manifest(paths.manifest_path)[0]

    assert repaired.ok
    assert repaired_winner["aliases"] == winner["aliases"]
    assert repair.download_urls == [f"{source_config.api_base}/PMC1/fullTextXML"]


def test_explicit_artifact_root_is_validated_and_migrated_by_redownload(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    repository = _make_repo(tmp_path)
    first_root = Path("generated/first")
    second_root = Path("generated/second")
    first = FakePipelineClient(
        [_page([_result("PMC1")])],
        {"PMC1": _jats("PMC1")},
    )
    assert sync_corpus(
        repository,
        source_config,
        artifact_root=first_root,
        candidate_limit=1,
        client=first,
        clock=_clock,
    ).ok

    mismatched = validate_corpus(
        repository,
        source_config,
        artifact_root=second_root,
    )
    assert not mismatched.ok
    assert "artifact_root_mismatch" in {error["code"] for error in mismatched.errors}

    second = FakePipelineClient(
        [_page([_result("PMC1")])],
        {"PMC1": _jats("PMC1")},
    )
    migrated = sync_corpus(
        repository,
        source_config,
        artifact_root=second_root,
        candidate_limit=1,
        client=second,
        clock=_clock,
    )
    paths = resolve_pipeline_paths(
        repository,
        source_config,
        artifact_root=second_root,
    )
    record = read_manifest(paths.manifest_path)[0]

    assert migrated.ok
    assert len(second.download_urls) == 1
    assert record["raw"]["path"].startswith("generated/second/raw/")
    assert record["canonical"]["path"].startswith("generated/second/canonical/")


def test_resume_and_validate_reject_manifest_artifact_symlink(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    repository = _make_repo(tmp_path)
    initial = FakePipelineClient(
        [_page([_result("PMC1")])],
        {"PMC1": _jats("PMC1")},
    )
    assert sync_corpus(
        repository,
        source_config,
        candidate_limit=1,
        client=initial,
        clock=_clock,
    ).ok
    paths = resolve_pipeline_paths(repository, source_config)
    record = read_manifest(paths.manifest_path)[0]
    raw_path = repository / record["raw"]["path"]
    real_path = raw_path.with_name("PMC1.real.xml")
    raw_path.replace(real_path)
    raw_path.symlink_to(real_path.name)

    report = validate_corpus(repository, source_config)
    assert not report.ok
    assert "symlink_path_forbidden" in {error["code"] for error in report.errors}

    no_network = FakePipelineClient([], {})
    with pytest.raises(ManifestError) as raised:
        sync_corpus(
            repository,
            source_config,
            candidate_limit=1,
            client=no_network,
            clock=_clock,
        )
    assert raised.value.code == "symlink_path_forbidden"
    assert no_network.discovery_urls == []


def test_zero_network_resume_cleans_stale_part_files(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    repository = _make_repo(tmp_path)
    first = FakePipelineClient(
        [_page([_result("PMC1")])],
        {"PMC1": _jats("PMC1")},
    )
    assert sync_corpus(
        repository,
        source_config,
        candidate_limit=1,
        client=first,
        clock=_clock,
    ).ok
    paths = resolve_pipeline_paths(repository, source_config)
    record = read_manifest(paths.manifest_path)[0]
    touched_paths = [
        repository / record["raw"]["path"],
        repository / record["canonical"]["path"],
        paths.manifest_path,
        paths.summary_path,
    ]
    for path in touched_paths:
        path.with_name(f"{path.name}.part").write_bytes(b"stale")

    no_network = FakePipelineClient([], {})
    report = sync_corpus(
        repository,
        source_config,
        candidate_limit=1,
        client=no_network,
        clock=_clock,
    )

    assert report.ok
    assert no_network.discovery_urls == []
    assert no_network.download_urls == []
    assert all(not path.with_name(f"{path.name}.part").exists() for path in touched_paths)


def test_cli_argument_errors_use_stable_stderr_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = pipeline_cli.main(["sync", "--target", "not-an-integer"])
    output = capsys.readouterr()

    assert exit_code == 2
    assert output.out == ""
    assert output.err == '{"error":"invalid_cli_arguments"}\n'


def test_validate_rejects_duplicate_pmcid_before_next_sync(
    source_config: SourceConfig,
    tmp_path: Path,
) -> None:
    repository = _make_repo(tmp_path)
    initial = FakePipelineClient(
        [_page([_result("PMC1")])],
        {"PMC1": _jats("PMC1")},
    )
    assert sync_corpus(
        repository,
        source_config,
        candidate_limit=1,
        client=initial,
        clock=_clock,
    ).ok
    paths = resolve_pipeline_paths(repository, source_config)
    record = read_manifest(paths.manifest_path)[0]
    write_manifest_atomic([record, record], paths.manifest_path)

    report = validate_corpus(repository, source_config)

    assert not report.ok
    assert "duplicate_manifest_pmcid" in {error["code"] for error in report.errors}
    no_network = FakePipelineClient([], {})
    with pytest.raises(ManifestError) as raised:
        sync_corpus(
            repository,
            source_config,
            candidate_limit=1,
            client=no_network,
            clock=_clock,
        )
    assert raised.value.code == "duplicate_manifest_pmcid"
    assert no_network.discovery_urls == []
