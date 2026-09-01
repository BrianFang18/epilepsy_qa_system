"""Explicit, resumable orchestration for the licensed Europe PMC corpus."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.corpus.config import SourceConfig
from app.corpus.discovery import EuropePmcDiscovery, pmcid_sort_key
from app.corpus.http import SafeHttpClient, validate_https_url
from app.corpus.jats import normalize_jats
from app.corpus.manifest import (
    artifact_for_file,
    assert_manifest_safe,
    atomic_write_bytes,
    deduplicate_records,
    read_manifest,
    record_files_match,
    relative_manifest_path,
    resolve_manifest_path,
    validate_manifest,
    validate_manifest_record,
    write_json_atomic,
    write_manifest_atomic,
)
from app.corpus.models import (
    ArticleCandidate,
    CorpusError,
    DownloadResult,
    LicenseRejectedError,
    ManifestError,
    NormalizedArticle,
    ValidationReport,
)

_ACTIVE_STATUSES = frozenset({"active", "normalized"})
_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PMCID_RE = re.compile(r"^PMC\d+$")


class PipelineHttpClient(Protocol):
    """Network seam used to keep pipeline tests completely offline."""

    def get_json(self, url: str) -> dict[str, Any]: ...

    def download_atomic(self, url: str, destination: Path) -> DownloadResult: ...


class CorpusPipelineError(CorpusError):
    """Raised when orchestration fails outside an individual article."""


@dataclass(frozen=True, slots=True)
class CorpusPipelinePaths:
    """Resolved output paths, all guaranteed to remain inside the repository."""

    repository_root: Path
    artifact_root: Path
    raw_root: Path
    canonical_root: Path
    manifest_path: Path
    summary_path: Path


@dataclass(frozen=True, slots=True)
class _Repair:
    candidate: ArticleCandidate
    aliases: tuple[dict[str, str | None], ...]
    original_record: dict[str, Any]


@dataclass(slots=True)
class _ResumeState:
    active: list[dict[str, Any]]
    inactive: list[dict[str, Any]]
    repairs: dict[str, _Repair]
    skipped_pmcids: set[str]


def build_http_client(config: SourceConfig) -> SafeHttpClient:
    """Build the production HTTPS client solely from the explicit source config."""

    return SafeHttpClient(
        allowed_hosts=config.allowed_hosts,
        allowed_redirect_hosts=config.allowed_redirect_hosts,
        user_agent=config.default_user_agent,
        requests_per_second=config.requests_per_second,
        timeout_seconds=config.timeout_seconds,
        max_response_bytes=config.max_response_bytes,
        chunk_bytes=config.download_chunk_bytes,
        max_retries=config.max_retries,
        backoff_base_seconds=config.backoff_base_seconds,
        backoff_max_seconds=config.backoff_max_seconds,
        jitter_seconds=config.jitter_seconds,
    )


def resolve_repository_path(repository_root: Path, value: Path) -> Path:
    """Resolve one path inside a real repository directory without following symlinks."""

    root_input = Path(repository_root)
    if root_input.is_symlink():
        raise ManifestError(
            "repository root cannot be a symlink",
            code="symlink_path_forbidden",
        )
    try:
        root = root_input.resolve(strict=True)
    except OSError as exc:
        raise ManifestError(
            "repository root cannot be resolved",
            code="invalid_repository_root",
        ) from exc
    if not root.is_dir():
        raise ManifestError(
            "repository root is not a directory",
            code="invalid_repository_root",
        )

    requested = Path(value)
    if ".." in requested.parts:
        raise ManifestError("path escapes repository root", code="path_escape")
    candidate = requested if requested.is_absolute() else root / requested
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ManifestError("path is outside repository root", code="path_escape") from exc

    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ManifestError(
                "symlinked repository paths are forbidden",
                code="symlink_path_forbidden",
            )

    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ManifestError("path escapes repository root", code="path_escape") from exc
    return resolved


def resolve_pipeline_paths(
    repository_root: Path,
    config: SourceConfig,
    *,
    manifest_path: Path | None = None,
    summary_path: Path | None = None,
    artifact_root: Path | None = None,
) -> CorpusPipelinePaths:
    """Apply the versioned default layout and enforce repository confinement."""

    root = resolve_repository_path(repository_root, Path("."))
    artifact_value = artifact_root or Path("data") / "corpus" / config.corpus_version
    manifest_value = (
        manifest_path
        if manifest_path is not None
        else Path("data") / "manifests" / f"{config.corpus_version}.jsonl"
    )
    if summary_path is None:
        if manifest_path is None:
            summary_value = Path("data") / "manifests" / f"{config.corpus_version}.summary.json"
        else:
            summary_value = Path(manifest_path).with_suffix(".summary.json")
    else:
        summary_value = summary_path

    resolved_artifact_root = resolve_repository_path(root, Path(artifact_value))
    return CorpusPipelinePaths(
        repository_root=root,
        artifact_root=resolved_artifact_root,
        raw_root=resolve_repository_path(root, resolved_artifact_root / "raw"),
        canonical_root=resolve_repository_path(root, resolved_artifact_root / "canonical"),
        manifest_path=resolve_repository_path(root, Path(manifest_value)),
        summary_path=resolve_repository_path(root, Path(summary_value)),
    )


def validate_corpus(
    repository_root: Path,
    config: SourceConfig,
    *,
    manifest_path: Path | None = None,
    summary_path: Path | None = None,
    artifact_root: Path | None = None,
    target: int | None = None,
) -> ValidationReport:
    """Validate one explicit corpus release without network or environment access."""

    resolved_target = _positive_int(target, config.target_count, code="invalid_target")
    if resolved_target > config.candidate_limit:
        raise CorpusPipelineError(
            "target exceeds the configured candidate limit",
            code="invalid_target",
        )
    paths = resolve_pipeline_paths(
        repository_root,
        config,
        manifest_path=manifest_path,
        summary_path=summary_path,
        artifact_root=artifact_root,
    )
    report = validate_manifest(
        paths.manifest_path,
        repository_root=paths.repository_root,
        config=config,
        target=resolved_target,
    )
    return _validate_selected_layout(report, paths)


def sync_corpus(
    repository_root: Path,
    config: SourceConfig,
    *,
    manifest_path: Path | None = None,
    summary_path: Path | None = None,
    artifact_root: Path | None = None,
    target: int | None = None,
    candidate_limit: int | None = None,
    client: PipelineHttpClient | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ValidationReport:
    """Discover, safely normalize, deduplicate, publish, and validate a corpus release."""

    try:
        return _sync_corpus(
            repository_root,
            config,
            manifest_path=manifest_path,
            summary_path=summary_path,
            artifact_root=artifact_root,
            target=target,
            candidate_limit=candidate_limit,
            client=client,
            clock=clock or _utc_now,
        )
    except CorpusError:
        raise
    except Exception as exc:
        raise CorpusPipelineError(
            "unexpected corpus pipeline failure",
            code="pipeline_unexpected_error",
        ) from exc


def _sync_corpus(
    repository_root: Path,
    config: SourceConfig,
    *,
    manifest_path: Path | None,
    summary_path: Path | None,
    artifact_root: Path | None,
    target: int | None,
    candidate_limit: int | None,
    client: PipelineHttpClient | None,
    clock: Callable[[], datetime],
) -> ValidationReport:
    resolved_target, resolved_limit = _resolve_limits(config, target, candidate_limit)
    paths = resolve_pipeline_paths(
        repository_root,
        config,
        manifest_path=manifest_path,
        summary_path=summary_path,
        artifact_root=artifact_root,
    )
    resume = _load_resume_state(paths, config)
    active = deduplicate_records(resume.active)

    if not resume.repairs and len(active) >= resolved_target:
        records = _combine_records(active, resume.inactive)
        return _publish_and_validate(
            records,
            paths=paths,
            config=config,
            target=resolved_target,
            candidate_limit=resolved_limit,
        )

    if len(resume.repairs) > resolved_limit:
        raise CorpusPipelineError(
            "candidate limit cannot cover required active repairs",
            code="candidate_limit_below_resume_repairs",
        )

    paths.raw_root.mkdir(parents=True, exist_ok=True)
    paths.canonical_root.mkdir(parents=True, exist_ok=True)
    http_client = client or build_http_client(config)
    candidates = EuropePmcDiscovery(config, http_client).discover(limit=resolved_limit)
    work = _merge_work(resume.repairs, candidates, resolved_limit)
    inactive = list(resume.inactive)
    pending_repairs = dict(resume.repairs)
    requested: set[str] = set()

    for candidate, required_repair, aliases in work:
        if candidate.pmcid in requested:
            continue
        if candidate.pmcid in resume.skipped_pmcids:
            continue
        if _pmcid_is_represented(candidate.pmcid, active) and not required_repair:
            continue
        if len(active) >= resolved_target and not required_repair:
            break
        requested.add(candidate.pmcid)
        record = _process_candidate(
            candidate,
            paths,
            config,
            http_client,
            clock,
            aliases=aliases,
        )
        if record["status"] in _ACTIVE_STATUSES:
            active.append(record)
            active = deduplicate_records(active)
        else:
            inactive.append(record)
        if required_repair:
            pending_repairs.pop(candidate.pmcid, None)
        checkpoint_records = _combine_records(active, inactive)
        checkpoint_records.extend(
            repair.original_record
            for repair in sorted(
                pending_repairs.values(),
                key=lambda item: pmcid_sort_key(item.candidate.pmcid),
            )
        )
        _write_checkpoint(
            checkpoint_records,
            manifest_path=paths.manifest_path,
            repository_root=paths.repository_root,
            config=config,
        )

    records = _combine_records(active, inactive)
    return _publish_and_validate(
        records,
        paths=paths,
        config=config,
        target=resolved_target,
        candidate_limit=resolved_limit,
    )


def _load_resume_state(
    paths: CorpusPipelinePaths,
    config: SourceConfig,
) -> _ResumeState:
    state = _ResumeState(active=[], inactive=[], repairs={}, skipped_pmcids=set())
    if not paths.manifest_path.exists():
        return state
    if not paths.manifest_path.is_file():
        raise ManifestError("manifest is not a regular file", code="manifest_read_failed")

    records = read_manifest(paths.manifest_path)
    seen_pmcids: set[str] = set()
    for raw_record in records:
        record = dict(raw_record)
        assert_manifest_safe(record)
        historical_config = _historical_config(record, config)
        validate_manifest_record(record, historical_config)
        _validate_record_paths(record, paths.repository_root)

        pmcid = str(record["pmcid"])
        if pmcid in seen_pmcids:
            raise ManifestError(
                "manifest contains repeated PMCID records",
                code="duplicate_manifest_pmcid",
            )
        seen_pmcids.add(pmcid)
        current = _versions_match(record, config)
        layout_matches = _record_matches_layout(record, paths)
        status = str(record["status"])
        if status in _ACTIVE_STATUSES:
            if (
                current
                and layout_matches
                and _active_record_reusable(record, paths.repository_root, config)
            ):
                state.active.append(record)
            else:
                state.repairs[pmcid] = _Repair(
                    candidate=_candidate_from_record(record),
                    aliases=_aliases_from_record(record),
                    original_record=record,
                )
        elif current:
            if not layout_matches:
                record["raw"] = None
            state.inactive.append(record)
            state.skipped_pmcids.add(pmcid)
    return state


def _historical_config(record: Mapping[str, Any], config: SourceConfig) -> SourceConfig:
    fields = ("schema_version", "corpus_version", "converter_version", "source_version")
    values: list[str] = []
    for field in fields:
        value = record.get(field)
        if not isinstance(value, str) or not value:
            raise ManifestError(
                "manifest version fields are malformed",
                code="schema_fields",
            )
        values.append(value)
    return replace(
        config,
        schema_version=values[0],
        corpus_version=values[1],
        converter_version=values[2],
        source_version=values[3],
    )


def _versions_match(record: Mapping[str, Any], config: SourceConfig) -> bool:
    return all(
        record.get(field) == expected
        for field, expected in (
            ("schema_version", config.schema_version),
            ("corpus_version", config.corpus_version),
            ("converter_version", config.converter_version),
            ("source_version", config.source_version),
        )
    )


def _validate_record_paths(record: Mapping[str, Any], repository_root: Path) -> None:
    for field in ("raw", "canonical"):
        artifact = record.get(field)
        if artifact is None:
            continue
        if not isinstance(artifact, Mapping):
            raise ManifestError("artifact is malformed", code="invalid_artifact")
        value = artifact.get("path")
        if not isinstance(value, str):
            raise ManifestError("artifact path is malformed", code="invalid_artifact")
        resolve_manifest_path(value, repository_root)


def _record_matches_layout(
    record: Mapping[str, Any],
    paths: CorpusPipelinePaths,
) -> bool:
    pmcid = record.get("pmcid")
    if not isinstance(pmcid, str) or not _PMCID_RE.fullmatch(pmcid):
        return False
    expected = {
        "raw": relative_manifest_path(
            paths.raw_root / f"{pmcid}.xml",
            paths.repository_root,
        ),
        "canonical": relative_manifest_path(
            paths.canonical_root / f"{pmcid}.md",
            paths.repository_root,
        ),
    }
    for field, expected_path in expected.items():
        artifact = record.get(field)
        if artifact is None:
            continue
        if not isinstance(artifact, Mapping) or artifact.get("path") != expected_path:
            return False
    return True


def _active_record_reusable(
    record: Mapping[str, Any],
    repository_root: Path,
    config: SourceConfig,
) -> bool:
    license_value = record.get("license")
    if not isinstance(license_value, Mapping):
        return False
    spdx = license_value.get("spdx")
    if not isinstance(spdx, str) or config.license_urls.get(spdx) != license_value.get("url"):
        return False
    if not record_files_match(record, repository_root):
        return False
    canonical = record.get("canonical")
    if not isinstance(canonical, Mapping) or not isinstance(canonical.get("path"), str):
        return False
    canonical_path = resolve_manifest_path(str(canonical["path"]), repository_root)
    return _canonical_body_present(canonical_path)


def _canonical_body_present(path: Path) -> bool:
    marker = b"\n## Body\n"
    pending = b""
    marker_found = False
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(65536):
                combined = pending + chunk
                if not marker_found:
                    marker_index = combined.find(marker)
                    if marker_index < 0:
                        pending = combined[-(len(marker) - 1) :]
                        continue
                    marker_found = True
                    combined = combined[marker_index + len(marker) :]
                if combined.strip():
                    return True
                pending = combined
    except OSError:
        return False
    return False


def _candidate_from_record(record: Mapping[str, Any]) -> ArticleCandidate:
    authors_value = record.get("authors")
    authors = (
        tuple(str(value) for value in authors_value) if isinstance(authors_value, list) else ()
    )
    return ArticleCandidate(
        pmcid=str(record["pmcid"]),
        pmid=_optional_string(record.get("pmid")),
        doi=_optional_string(record.get("doi")),
        title=str(record["title"]),
        abstract="",
        authors=authors,
    )


def _aliases_from_record(
    record: Mapping[str, Any],
) -> tuple[dict[str, str | None], ...]:
    aliases = record.get("aliases")
    if not isinstance(aliases, list):
        return ()
    return tuple(
        {
            "pmcid": _optional_string(alias.get("pmcid")),
            "pmid": _optional_string(alias.get("pmid")),
            "doi": _optional_string(alias.get("doi")),
        }
        for alias in aliases
        if isinstance(alias, Mapping)
    )


def _merge_work(
    repairs: Mapping[str, _Repair],
    discovered: Sequence[ArticleCandidate],
    candidate_limit: int,
) -> list[tuple[ArticleCandidate, bool, tuple[dict[str, str | None], ...]]]:
    work: list[tuple[ArticleCandidate, bool, tuple[dict[str, str | None], ...]]] = []
    represented: set[str] = set()
    for repair in sorted(
        repairs.values(),
        key=lambda item: pmcid_sort_key(item.candidate.pmcid),
    ):
        work.append((repair.candidate, True, repair.aliases))
        represented.add(repair.candidate.pmcid)
    for candidate in discovered:
        if candidate.pmcid in represented:
            continue
        if len(work) >= candidate_limit:
            break
        work.append((candidate, False, ()))
        represented.add(candidate.pmcid)
    return work


def _process_candidate(
    candidate: ArticleCandidate,
    paths: CorpusPipelinePaths,
    config: SourceConfig,
    client: PipelineHttpClient,
    clock: Callable[[], datetime],
    *,
    aliases: Sequence[Mapping[str, str | None]],
) -> dict[str, Any]:
    if not _PMCID_RE.fullmatch(candidate.pmcid):
        return _inactive_record(
            candidate,
            config,
            retrieved_at=_timestamp(clock),
            status="failed",
            error_code="invalid_pmcid",
            raw=None,
            aliases=aliases,
        )

    retrieved_at = _timestamp(clock)
    source_url = _full_text_url(config, candidate.pmcid)
    validate_https_url(source_url, config.allowed_hosts)
    raw_path = resolve_repository_path(
        paths.repository_root, paths.raw_root / f"{candidate.pmcid}.xml"
    )
    canonical_path = resolve_repository_path(
        paths.repository_root,
        paths.canonical_root / f"{candidate.pmcid}.md",
    )
    raw_artifact: dict[str, str | int] | None = None
    try:
        _remove_part(raw_path)
        _remove_part(canonical_path)
        canonical_path.unlink(missing_ok=True)
        result = client.download_atomic(source_url, raw_path)
        artifact = artifact_for_file(raw_path, paths.repository_root)
        if artifact.size <= 0:
            raise CorpusPipelineError("download is empty", code="empty_download")
        if result.size != artifact.size or result.sha256 != artifact.sha256:
            raise CorpusPipelineError(
                "download digest does not match the stored artifact",
                code="download_integrity_mismatch",
            )
        raw_artifact = artifact.to_dict()
        xml_bytes = _read_bounded(raw_path, config.max_response_bytes)
        normalized = normalize_jats(
            xml_bytes,
            expected_pmcid=candidate.pmcid,
            source_url=source_url,
            license_allowlist=config.license_urls,
            min_body_chars=config.min_body_chars,
            include_references=config.include_references,
        )
        atomic_write_bytes(canonical_path, normalized.canonical_bytes)
        canonical_artifact = artifact_for_file(canonical_path, paths.repository_root)
        return _active_record(
            normalized=normalized,
            config=config,
            retrieved_at=retrieved_at,
            raw=raw_artifact,
            canonical=canonical_artifact.to_dict(),
            aliases=aliases,
        )
    except LicenseRejectedError as exc:
        canonical_path.unlink(missing_ok=True)
        return _inactive_record(
            candidate,
            config,
            retrieved_at=retrieved_at,
            status="rejected",
            error_code=_stable_error_code(exc.code),
            raw=raw_artifact,
            aliases=aliases,
        )
    except CorpusError as exc:
        canonical_path.unlink(missing_ok=True)
        return _inactive_record(
            candidate,
            config,
            retrieved_at=retrieved_at,
            status="failed",
            error_code=_stable_error_code(exc.code),
            raw=raw_artifact,
            aliases=aliases,
        )
    except Exception:
        canonical_path.unlink(missing_ok=True)
        return _inactive_record(
            candidate,
            config,
            retrieved_at=retrieved_at,
            status="failed",
            error_code="unexpected_error",
            raw=raw_artifact,
            aliases=aliases,
        )
    finally:
        _remove_part(raw_path)
        _remove_part(canonical_path)


def _read_bounded(path: Path, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(65536):
                size += len(chunk)
                if size > limit:
                    raise CorpusPipelineError(
                        "download exceeds the configured byte limit",
                        code="response_too_large",
                    )
                chunks.append(chunk)
    except OSError as exc:
        raise CorpusPipelineError("cannot read raw artifact", code="artifact_read_failed") from exc
    return b"".join(chunks)


def _active_record(
    *,
    normalized: NormalizedArticle,
    config: SourceConfig,
    retrieved_at: str,
    raw: Mapping[str, str | int],
    canonical: Mapping[str, str | int],
    aliases: Sequence[Mapping[str, str | None]],
) -> dict[str, Any]:
    return {
        **_record_prefix(
            pmcid=normalized.pmcid,
            pmid=normalized.pmid,
            doi=normalized.doi,
            title=normalized.title,
            authors=normalized.authors,
            config=config,
            retrieved_at=retrieved_at,
        ),
        "license": {
            "spdx": normalized.license.spdx,
            "url": normalized.license.url,
            "declaration_sha256": normalized.license.declaration_sha256,
        },
        "raw": dict(raw),
        "canonical": dict(canonical),
        "partition": "demo_kb",
        "status": "active",
        "error_code": None,
        "aliases": [dict(alias) for alias in aliases],
    }


def _inactive_record(
    candidate: ArticleCandidate,
    config: SourceConfig,
    *,
    retrieved_at: str,
    status: str,
    error_code: str,
    raw: Mapping[str, str | int] | None,
    aliases: Sequence[Mapping[str, str | None]],
) -> dict[str, Any]:
    return {
        **_record_prefix(
            pmcid=candidate.pmcid,
            pmid=candidate.pmid,
            doi=candidate.doi,
            title=candidate.title or candidate.pmcid,
            authors=candidate.authors,
            config=config,
            retrieved_at=retrieved_at,
        ),
        "license": None,
        "raw": dict(raw) if raw is not None else None,
        "canonical": None,
        "partition": "demo_kb",
        "status": status,
        "error_code": error_code,
        "aliases": [dict(alias) for alias in aliases],
    }


def _record_prefix(
    *,
    pmcid: str,
    pmid: str | None,
    doi: str | None,
    title: str,
    authors: Sequence[str],
    config: SourceConfig,
    retrieved_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "corpus_version": config.corpus_version,
        "converter_version": config.converter_version,
        "source_version": config.source_version,
        "pmcid": pmcid,
        "pmid": pmid,
        "doi": doi,
        "title": title,
        "authors": list(authors),
        "source": _source_metadata(config, pmcid),
        "retrieved_at": retrieved_at,
    }


def _source_metadata(config: SourceConfig, pmcid: str) -> dict[str, str]:
    return {
        "provider": config.provider,
        "api_base": config.api_base,
        "full_text_url": _full_text_url(config, pmcid),
        "terms_url": config.terms_url,
        "copyright_url": config.copyright_url,
        "documentation_url": config.documentation_url,
    }


def _full_text_url(config: SourceConfig, pmcid: str) -> str:
    return f"{config.api_base}/{pmcid}/fullTextXML"


def _combine_records(
    active: Sequence[Mapping[str, Any]],
    inactive: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    deduplicated_active = deduplicate_records(active)
    represented = {value for record in deduplicated_active for value in _record_pmcids(record)}
    retained_inactive = [
        dict(record) for record in inactive if record.get("pmcid") not in represented
    ]
    return [*deduplicated_active, *retained_inactive]


def _record_pmcids(record: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    pmcid = record.get("pmcid")
    if isinstance(pmcid, str):
        values.add(pmcid)
    aliases = record.get("aliases")
    if isinstance(aliases, list):
        for alias in aliases:
            if isinstance(alias, Mapping) and isinstance(alias.get("pmcid"), str):
                values.add(str(alias["pmcid"]))
    return values


def _pmcid_is_represented(pmcid: str, records: Sequence[Mapping[str, Any]]) -> bool:
    return any(pmcid in _record_pmcids(record) for record in records)


def _write_checkpoint(
    records: Sequence[Mapping[str, Any]],
    *,
    manifest_path: Path,
    repository_root: Path,
    config: SourceConfig,
) -> None:
    normalized_records = [dict(record) for record in records]
    for record in normalized_records:
        historical_config = _historical_config(record, config)
        validate_manifest_record(record, historical_config)
        _validate_record_paths(record, repository_root)
    _write_manifest_preserving_interrupt(normalized_records, manifest_path)


def _write_manifest_preserving_interrupt(
    records: Sequence[Mapping[str, Any]],
    path: Path,
) -> None:
    try:
        write_manifest_atomic(records, path)
    except KeyboardInterrupt:
        _discard_part(path)
        raise


def _write_json_preserving_interrupt(value: Mapping[str, Any], path: Path) -> None:
    try:
        write_json_atomic(value, path)
    except KeyboardInterrupt:
        _discard_part(path)
        raise


def _discard_part(path: Path) -> None:
    try:
        path.with_name(f"{path.name}.part").unlink(missing_ok=True)
    except OSError:
        pass


def _cleanup_record_parts(
    records: Sequence[Mapping[str, Any]],
    repository_root: Path,
) -> None:
    for record in records:
        for field in ("raw", "canonical"):
            artifact = record.get(field)
            if not isinstance(artifact, Mapping) or not isinstance(artifact.get("path"), str):
                continue
            path = resolve_manifest_path(str(artifact["path"]), repository_root)
            _remove_part(path)


def _validate_selected_layout(
    report: ValidationReport,
    paths: CorpusPipelinePaths,
) -> ValidationReport:
    if not paths.manifest_path.is_file():
        return report
    try:
        records = read_manifest(paths.manifest_path)
    except ManifestError:
        return report
    existing = {
        (error.get("code"), error.get("line"), error.get("pmcid")) for error in report.errors
    }
    for line_number, record in enumerate(records, start=1):
        if _record_matches_layout(record, paths):
            continue
        pmcid = record.get("pmcid")
        error: dict[str, Any] = {
            "code": "artifact_root_mismatch",
            "line": line_number,
        }
        if isinstance(pmcid, str) and _PMCID_RE.fullmatch(pmcid):
            error["pmcid"] = pmcid
        key = (error["code"], error["line"], error.get("pmcid"))
        if key not in existing:
            report.errors.append(error)
            existing.add(key)
    report.ok = not report.errors
    return report


def _publish_and_validate(
    records: Sequence[Mapping[str, Any]],
    *,
    paths: CorpusPipelinePaths,
    config: SourceConfig,
    target: int,
    candidate_limit: int,
) -> ValidationReport:
    normalized_records = [dict(record) for record in records]
    for record in normalized_records:
        validate_manifest_record(record, config)
        _validate_record_paths(record, paths.repository_root)
        if not _record_matches_layout(record, paths):
            raise ManifestError(
                "artifact path does not match selected output root",
                code="artifact_root_mismatch",
            )
    _cleanup_record_parts(normalized_records, paths.repository_root)
    _remove_part(paths.manifest_path)
    _remove_part(paths.summary_path)
    _write_manifest_preserving_interrupt(normalized_records, paths.manifest_path)
    summary = _summary(
        normalized_records,
        paths=paths,
        config=config,
        target=target,
        candidate_limit=candidate_limit,
    )
    assert_manifest_safe(summary)
    _write_json_preserving_interrupt(summary, paths.summary_path)
    report = validate_manifest(
        paths.manifest_path,
        repository_root=paths.repository_root,
        config=config,
        target=target,
    )
    return _validate_selected_layout(report, paths)


def _summary(
    records: Sequence[Mapping[str, Any]],
    *,
    paths: CorpusPipelinePaths,
    config: SourceConfig,
    target: int,
    candidate_limit: int,
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    licenses: Counter[str] = Counter()
    for record in records:
        counts["records"] += 1
        status = str(record.get("status", "unknown"))
        counts[status] += 1
        aliases = record.get("aliases")
        if isinstance(aliases, list):
            counts["aliases"] += len(aliases)
        if status in _ACTIVE_STATUSES:
            counts["unique_normalized"] += 1
            license_value = record.get("license")
            if isinstance(license_value, Mapping) and isinstance(license_value.get("spdx"), str):
                licenses[str(license_value["spdx"])] += 1
    return {
        "schema_version": config.schema_version,
        "corpus_version": config.corpus_version,
        "converter_version": config.converter_version,
        "source_version": config.source_version,
        "target": target,
        "candidate_limit": candidate_limit,
        "manifest_path": relative_manifest_path(
            paths.manifest_path,
            paths.repository_root,
        ),
        "artifact_root": relative_manifest_path(
            paths.artifact_root,
            paths.repository_root,
        ),
        "counts": dict(sorted(counts.items())),
        "licenses": dict(sorted(licenses.items())),
    }


def _resolve_limits(
    config: SourceConfig,
    target: int | None,
    candidate_limit: int | None,
) -> tuple[int, int]:
    resolved_target = _positive_int(target, config.target_count, code="invalid_target")
    resolved_limit = _positive_int(
        candidate_limit,
        config.candidate_limit,
        code="invalid_candidate_limit",
    )
    if resolved_target > resolved_limit or resolved_limit > config.candidate_limit:
        raise CorpusPipelineError(
            "pipeline limits must satisfy target <= candidate_limit <= configured limit",
            code="invalid_candidate_limit",
        )
    return resolved_target, resolved_limit


def _positive_int(value: int | None, default: int, *, code: str) -> int:
    resolved = default if value is None else value
    if isinstance(resolved, bool) or not isinstance(resolved, int) or resolved <= 0:
        raise CorpusPipelineError("pipeline limit must be a positive integer", code=code)
    return resolved


def _timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if not isinstance(value, datetime):
        raise CorpusPipelineError("clock returned an invalid value", code="invalid_clock")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _remove_part(path: Path) -> None:
    try:
        path.with_name(f"{path.name}.part").unlink(missing_ok=True)
    except OSError as exc:
        raise CorpusPipelineError("cannot clean part file", code="part_cleanup_failed") from exc


def _stable_error_code(value: str) -> str:
    return value if _ERROR_CODE_RE.fullmatch(value) else "corpus_error"


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "CorpusPipelineError",
    "CorpusPipelinePaths",
    "PipelineHttpClient",
    "build_http_client",
    "resolve_pipeline_paths",
    "resolve_repository_path",
    "sync_corpus",
    "validate_corpus",
]
