"""Manifest serialization, deterministic deduplication, and release validation."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from app.corpus.config import SourceConfig
from app.corpus.discovery import pmcid_sort_key
from app.corpus.models import FileArtifact, ManifestError, ValidationReport

_ACTIVE_STATUSES = {"active", "normalized"}
_ALLOWED_STATUSES = _ACTIVE_STATUSES | {"failed", "rejected"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PMCID_RE = re.compile(r"^PMC\d+$")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_SECRET_VALUE_RE = re.compile(
    r"(?:\bbearer\s+[A-Za-z0-9._~-]+|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\b(?:api[_-]?key|token|secret|password|cookie)\s*[=:]\s*\S+)",
    re.IGNORECASE,
)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_FORBIDDEN_KEYS = {
    "abstract",
    "authorization",
    "body",
    "content",
    "cookie",
    "full_text",
    "markdown",
    "object_key",
    "password",
    "raw_text",
    "secret",
    "text",
    "token",
}
_REQUIRED_FIELDS = {
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
_SOURCE_FIELDS = {
    "provider",
    "api_base",
    "full_text_url",
    "terms_url",
    "copyright_url",
    "documentation_url",
}
_ARTIFACT_FIELDS = {"path", "size", "sha256"}
_LICENSE_FIELDS = {"spdx", "url", "declaration_sha256"}
_ALIAS_FIELDS = {"pmcid", "pmid", "doi"}


def read_manifest(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ManifestError(
                        f"manifest line {line_number} is invalid JSON",
                        code="manifest_invalid_json",
                    ) from exc
                if not isinstance(value, dict):
                    raise ManifestError(
                        f"manifest line {line_number} is not an object",
                        code="manifest_invalid_record",
                    )
                records.append(value)
    except OSError as exc:
        raise ManifestError("cannot read manifest", code="manifest_read_failed") from exc
    return records


def write_manifest_atomic(records: Sequence[Mapping[str, Any]], path: Path) -> None:
    sorted_records = sorted(records, key=_record_sort_key)
    lines = [
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for record in sorted_records
    ]
    payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    atomic_write_bytes(path, payload)


def write_json_atomic(value: Mapping[str, Any], path: Path) -> None:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    atomic_write_bytes(path, payload)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part_path = path.with_name(f"{path.name}.part")
    part_path.unlink(missing_ok=True)
    try:
        with part_path.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(part_path, path)
    except Exception:
        part_path.unlink(missing_ok=True)
        raise


def artifact_for_file(path: Path, repository_root: Path) -> FileArtifact:
    size, sha256 = hash_file(path)
    relative = relative_manifest_path(path, repository_root)
    return FileArtifact(path=relative, size=size, sha256=sha256)


def hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def relative_manifest_path(path: Path, repository_root: Path) -> str:
    root = repository_root.resolve()
    try:
        relative = path.resolve().relative_to(root)
    except ValueError as exc:
        raise ManifestError(
            "generated file is outside repository root",
            code="path_escape",
        ) from exc
    value = relative.as_posix()
    _safe_path_parts(value)
    return value


def resolve_manifest_path(value: str, repository_root: Path) -> Path:
    parts = _safe_path_parts(value)
    if repository_root.is_symlink():
        raise ManifestError(
            "repository root cannot be a symlink",
            code="symlink_path_forbidden",
        )
    root = repository_root.resolve()
    unresolved = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ManifestError(
                "manifest path contains a symlink",
                code="symlink_path_forbidden",
            )
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ManifestError("manifest path escapes repository root", code="path_escape") from exc
    return candidate


def deduplicate_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Collapse connected ID/raw/canonical duplicate groups to the lowest PMCID."""

    normalized = [copy.deepcopy(dict(record)) for record in records]
    if not normalized:
        return []
    parent = list(range(len(normalized)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    owners: dict[tuple[str, str], int] = {}
    for index, record in enumerate(normalized):
        for key in _dedupe_keys(record):
            previous = owners.setdefault(key, index)
            union(previous, index)

    groups: dict[int, list[int]] = {}
    for index in range(len(normalized)):
        groups.setdefault(find(index), []).append(index)

    winners: list[dict[str, Any]] = []
    for indices in groups.values():
        winner_index = min(indices, key=lambda value: _record_sort_key(normalized[value]))
        winner = normalized[winner_index]
        aliases = _existing_aliases(winner)
        for index in indices:
            if index == winner_index:
                continue
            aliases.extend(_record_aliases(normalized[index]))
        winner["aliases"] = _unique_aliases(aliases, winner.get("pmcid"))
        winners.append(winner)
    return sorted(winners, key=_record_sort_key)


def validate_manifest(
    manifest_path: Path,
    *,
    repository_root: Path,
    config: SourceConfig,
    target: int,
) -> ValidationReport:
    """Validate release gates without returning or printing canonical body text."""

    counts: Counter[str] = Counter()
    errors: list[dict[str, Any]] = []
    if target <= 0:
        return ValidationReport(
            ok=False,
            counts={"records": 0, "unique_normalized": 0, "target": target},
            errors=[{"code": "invalid_target"}],
        )
    if not manifest_path.is_file():
        return ValidationReport(
            ok=False,
            counts={"records": 0, "unique_normalized": 0, "target": target},
            errors=[{"code": "manifest_missing"}],
        )
    try:
        records = read_manifest(manifest_path)
    except ManifestError as exc:
        return ValidationReport(
            ok=False,
            counts={"records": 0, "unique_normalized": 0, "target": target},
            errors=[{"code": exc.code}],
        )

    seen_pmcids: set[str] = set()
    seen_external_ids: dict[tuple[str, str], str] = {}
    seen_raw_hashes: dict[str, str] = {}
    seen_canonical_hashes: dict[str, str] = {}
    for line_number, record in enumerate(records, start=1):
        counts["records"] += 1
        pmcid = record.get("pmcid")
        safe_pmcid = pmcid if isinstance(pmcid, str) and _PMCID_RE.fullmatch(pmcid) else None
        try:
            assert_manifest_safe(record)
            _validate_record_shape(record, config)
        except ManifestError as exc:
            errors.append(_error(exc.code, line_number, safe_pmcid))
            continue

        pmcid_value = str(record["pmcid"])
        if pmcid_value in seen_pmcids:
            errors.append(_error("duplicate_manifest_pmcid", line_number, safe_pmcid))
            continue
        seen_pmcids.add(pmcid_value)

        status = str(record["status"])
        counts[status] += 1
        aliases = record["aliases"]
        if isinstance(aliases, list):
            counts["aliases"] += len(aliases)
        if status not in _ACTIVE_STATUSES:
            continue

        license_value = record["license"]
        assert isinstance(license_value, dict)
        spdx = license_value["spdx"]
        expected_url = config.license_urls.get(str(spdx))
        if expected_url is None or license_value.get("url") != expected_url:
            errors.append(_error("license_not_allowlisted", line_number, safe_pmcid))

        identifiers = _record_identifier_pairs(record)
        for identifier in identifiers:
            previous = seen_external_ids.setdefault(identifier, str(record["pmcid"]))
            if previous != record["pmcid"]:
                errors.append(_error("duplicate_external_id", line_number, safe_pmcid))

        raw = record["raw"]
        canonical = record["canonical"]
        assert isinstance(raw, dict) and isinstance(canonical, dict)
        raw_hash = str(raw["sha256"])
        canonical_hash = str(canonical["sha256"])
        previous_raw = seen_raw_hashes.setdefault(raw_hash, str(record["pmcid"]))
        if previous_raw != record["pmcid"]:
            errors.append(_error("duplicate_raw_hash", line_number, safe_pmcid))
        previous_canonical = seen_canonical_hashes.setdefault(canonical_hash, str(record["pmcid"]))
        if previous_canonical != record["pmcid"]:
            errors.append(_error("duplicate_canonical_hash", line_number, safe_pmcid))

        _validate_artifact(
            raw,
            repository_root,
            line_number,
            safe_pmcid,
            errors,
            canonical=False,
        )
        _validate_artifact(
            canonical,
            repository_root,
            line_number,
            safe_pmcid,
            errors,
            canonical=True,
        )

    counts["unique_normalized"] = len(seen_canonical_hashes)
    counts["target"] = target
    if counts["unique_normalized"] < target:
        errors.append({"code": "target_not_met"})
    return ValidationReport(ok=not errors, counts=dict(counts), errors=errors)


def validate_manifest_record(record: Mapping[str, Any], config: SourceConfig) -> None:
    """Validate one body-free record before it is trusted or serialized."""

    assert_manifest_safe(record)
    _validate_record_shape(dict(record), config)


def assert_manifest_safe(value: Any) -> None:
    """Reject body fields, credentials, object keys, and local absolute paths."""

    def walk(current: Any, key_path: tuple[str, ...]) -> None:
        if isinstance(current, Mapping):
            for raw_key, child in current.items():
                key = str(raw_key)
                normalized_key = key.casefold().replace("-", "_")
                if normalized_key in _FORBIDDEN_KEYS:
                    raise ManifestError(
                        "manifest contains a forbidden field",
                        code="manifest_forbidden_field",
                    )
                walk(child, (*key_path, key))
            return
        if isinstance(current, list):
            for child in current:
                walk(child, key_path)
            return
        if not isinstance(current, str):
            return
        if _SECRET_VALUE_RE.search(current) or _JWT_RE.search(current):
            raise ManifestError("manifest contains secret-like data", code="manifest_secret")
        parsed = urlsplit(current)
        if parsed.scheme in {"http", "https"}:
            sensitive_names = {
                key.casefold() for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
            }
            if sensitive_names & {"token", "api_key", "apikey", "key", "cookie", "secret"}:
                raise ManifestError("manifest URL contains a secret", code="manifest_secret")
            return
        if current.startswith(("/home/", "/Users/", "\\\\")) or _WINDOWS_ABSOLUTE_RE.match(current):
            raise ManifestError(
                "manifest contains an absolute local path",
                code="absolute_path_forbidden",
            )

    walk(value, ())


def record_files_match(record: Mapping[str, Any], repository_root: Path) -> bool:
    if record.get("status") not in _ACTIVE_STATUSES:
        return False
    try:
        for field in ("raw", "canonical"):
            artifact = record.get(field)
            if not isinstance(artifact, Mapping):
                return False
            path = artifact.get("path")
            expected_size = artifact.get("size")
            expected_hash = artifact.get("sha256")
            if not isinstance(path, str):
                return False
            local_path = resolve_manifest_path(path, repository_root)
            actual_size, actual_hash = hash_file(local_path)
            if actual_size != expected_size or actual_hash != expected_hash:
                return False
        return True
    except (ManifestError, OSError):
        return False


def _validate_record_shape(record: dict[str, Any], config: SourceConfig) -> None:
    if set(record) != _REQUIRED_FIELDS:
        raise ManifestError("manifest record fields do not match schema", code="schema_fields")
    expected_versions = {
        "schema_version": config.schema_version,
        "corpus_version": config.corpus_version,
        "converter_version": config.converter_version,
        "source_version": config.source_version,
    }
    for field, expected in expected_versions.items():
        if record.get(field) != expected:
            raise ManifestError("manifest version does not match config", code="version_mismatch")
    pmcid = record.get("pmcid")
    if not isinstance(pmcid, str) or not _PMCID_RE.fullmatch(pmcid):
        raise ManifestError("manifest PMCID is invalid", code="invalid_pmcid")
    for field in ("pmid", "doi"):
        if record.get(field) is not None and not isinstance(record.get(field), str):
            raise ManifestError("manifest identifier is invalid", code="invalid_identifier")
    if not isinstance(record.get("title"), str) or not record["title"].strip():
        raise ManifestError("manifest title is invalid", code="invalid_title")
    authors = record.get("authors")
    if not isinstance(authors, list) or not all(
        isinstance(author, str) and author.strip() and "@" not in author for author in authors
    ):
        raise ManifestError("manifest authors are invalid", code="invalid_authors")
    source = record.get("source")
    if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
        raise ManifestError("manifest source is invalid", code="invalid_source")
    expected_full_text = f"{config.api_base}/{pmcid}/fullTextXML"
    expected_source = {
        "provider": config.provider,
        "api_base": config.api_base,
        "full_text_url": expected_full_text,
        "terms_url": config.terms_url,
        "copyright_url": config.copyright_url,
        "documentation_url": config.documentation_url,
    }
    if source != expected_source:
        raise ManifestError("manifest source does not match policy", code="source_mismatch")
    retrieved_at = record.get("retrieved_at")
    if not isinstance(retrieved_at, str):
        raise ManifestError("retrieved_at is invalid", code="invalid_retrieved_at")
    try:
        datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestError("retrieved_at is invalid", code="invalid_retrieved_at") from exc
    if record.get("partition") != "demo_kb":
        raise ManifestError("partition must be demo_kb", code="invalid_partition")
    status = record.get("status")
    if status not in _ALLOWED_STATUSES:
        raise ManifestError("manifest status is invalid", code="invalid_status")
    aliases = record.get("aliases")
    if not isinstance(aliases, list):
        raise ManifestError("aliases must be a list", code="invalid_aliases")
    for alias in aliases:
        if not isinstance(alias, dict) or set(alias) != _ALIAS_FIELDS:
            raise ManifestError("alias is invalid", code="invalid_aliases")
        if not any(alias.get(field) for field in _ALIAS_FIELDS):
            raise ManifestError("alias is empty", code="invalid_aliases")
    if status in _ACTIVE_STATUSES:
        if record.get("error_code") is not None:
            raise ManifestError("active record has an error", code="invalid_error_code")
        _validate_artifact_shape(record.get("raw"))
        _validate_artifact_shape(record.get("canonical"))
        license_value = record.get("license")
        if not isinstance(license_value, dict) or set(license_value) != _LICENSE_FIELDS:
            raise ManifestError("active license is invalid", code="invalid_license")
        if not _SHA256_RE.fullmatch(str(license_value.get("declaration_sha256", ""))):
            raise ManifestError("license declaration hash is invalid", code="invalid_license")
    else:
        if not isinstance(record.get("error_code"), str) or not record["error_code"]:
            raise ManifestError("failed record lacks error code", code="invalid_error_code")
        if record.get("canonical") is not None:
            raise ManifestError("failed record cannot have canonical file", code="invalid_artifact")
        if record.get("license") is not None:
            raise ManifestError(
                "failed record cannot have accepted license", code="invalid_license"
            )
        raw = record.get("raw")
        if raw is not None:
            _validate_artifact_shape(raw)


def _validate_artifact_shape(value: object) -> None:
    if not isinstance(value, dict) or set(value) != _ARTIFACT_FIELDS:
        raise ManifestError("file artifact does not match schema", code="invalid_artifact")
    if not isinstance(value.get("path"), str):
        raise ManifestError("artifact path is invalid", code="invalid_artifact")
    size = value.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ManifestError("artifact size is invalid", code="invalid_artifact")
    if not _SHA256_RE.fullmatch(str(value.get("sha256", ""))):
        raise ManifestError("artifact hash is invalid", code="invalid_artifact")


def _validate_artifact(
    artifact: Mapping[str, Any],
    repository_root: Path,
    line_number: int,
    pmcid: str | None,
    errors: list[dict[str, Any]],
    *,
    canonical: bool,
) -> None:
    try:
        path = resolve_manifest_path(str(artifact["path"]), repository_root)
    except ManifestError as exc:
        errors.append(_error(exc.code, line_number, pmcid))
        return
    if not path.is_file():
        errors.append(_error("artifact_missing", line_number, pmcid))
        return
    try:
        size, sha256, body_present = _inspect_file(path, check_body=canonical)
    except OSError:
        errors.append(_error("artifact_read_failed", line_number, pmcid))
        return
    if size != artifact["size"]:
        errors.append(_error("artifact_size_mismatch", line_number, pmcid))
    if sha256 != artifact["sha256"]:
        errors.append(_error("artifact_hash_mismatch", line_number, pmcid))
    if canonical and not body_present:
        errors.append(_error("canonical_body_empty", line_number, pmcid))


def _inspect_file(path: Path, *, check_body: bool) -> tuple[int, str, bool]:
    digest = hashlib.sha256()
    size = 0
    marker = b"\n## Body\n"
    pending = b""
    marker_found = not check_body
    body_present = not check_body
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            size += len(chunk)
            digest.update(chunk)
            if body_present:
                continue
            combined = pending + chunk
            if not marker_found:
                marker_index = combined.find(marker)
                if marker_index >= 0:
                    marker_found = True
                    remainder = combined[marker_index + len(marker) :]
                    pending = remainder
                    if remainder.strip():
                        body_present = True
                else:
                    pending = combined[-(len(marker) - 1) :]
            elif combined.strip():
                body_present = True
    return size, digest.hexdigest(), body_present


def _safe_path_parts(value: str) -> tuple[str, ...]:
    if not value or "\\" in value or _WINDOWS_ABSOLUTE_RE.match(value):
        raise ManifestError("manifest path is invalid", code="path_escape")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestError("manifest path escapes repository root", code="path_escape")
    return path.parts


def _dedupe_keys(record: Mapping[str, Any]) -> Iterable[tuple[str, str]]:
    for field in ("pmcid", "pmid", "doi"):
        value = record.get(field)
        if isinstance(value, str) and value:
            yield (field, value.casefold())
    for field in ("raw", "canonical"):
        value = record.get(field)
        if isinstance(value, Mapping):
            sha256 = value.get("sha256")
            if isinstance(sha256, str) and sha256:
                yield (f"{field}_sha256", sha256)


def _record_identifier_pairs(record: Mapping[str, Any]) -> list[tuple[str, str]]:
    identifiers: list[tuple[str, str]] = []
    for field in ("pmcid", "pmid", "doi"):
        value = record.get(field)
        if isinstance(value, str) and value:
            identifiers.append((field, value.casefold()))
    aliases = record.get("aliases")
    if isinstance(aliases, list):
        for alias in aliases:
            if not isinstance(alias, Mapping):
                continue
            for field in ("pmcid", "pmid", "doi"):
                value = alias.get(field)
                if isinstance(value, str) and value:
                    identifiers.append((field, value.casefold()))
    return identifiers


def _record_aliases(record: Mapping[str, Any]) -> list[dict[str, str | None]]:
    aliases = _existing_aliases(record)
    aliases.append(
        {
            "pmcid": _optional_string(record.get("pmcid")),
            "pmid": _optional_string(record.get("pmid")),
            "doi": _optional_string(record.get("doi")),
        }
    )
    return aliases


def _existing_aliases(record: Mapping[str, Any]) -> list[dict[str, str | None]]:
    aliases = record.get("aliases")
    if not isinstance(aliases, list):
        return []
    output: list[dict[str, str | None]] = []
    for alias in aliases:
        if isinstance(alias, Mapping):
            output.append(
                {
                    "pmcid": _optional_string(alias.get("pmcid")),
                    "pmid": _optional_string(alias.get("pmid")),
                    "doi": _optional_string(alias.get("doi")),
                }
            )
    return output


def _unique_aliases(
    aliases: Sequence[Mapping[str, str | None]], winner_pmcid: object
) -> list[dict[str, str | None]]:
    unique: dict[tuple[str, str, str], dict[str, str | None]] = {}
    for alias in aliases:
        pmcid = alias.get("pmcid")
        if pmcid == winner_pmcid:
            continue
        normalized = {
            "pmcid": pmcid,
            "pmid": alias.get("pmid"),
            "doi": alias.get("doi"),
        }
        key = (
            (normalized["pmcid"] or "").casefold(),
            (normalized["pmid"] or "").casefold(),
            (normalized["doi"] or "").casefold(),
        )
        if any(key):
            unique[key] = normalized
    return sorted(
        unique.values(),
        key=lambda alias: pmcid_sort_key(alias["pmcid"] or "")
        + (alias["pmid"] or "", alias["doi"] or ""),
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _record_sort_key(record: Mapping[str, Any]) -> tuple[tuple[int, str], str]:
    pmcid = record.get("pmcid")
    normalized = pmcid if isinstance(pmcid, str) else ""
    return (pmcid_sort_key(normalized), str(record.get("status", "")))


def _error(code: str, line: int, pmcid: str | None) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "line": line}
    if pmcid is not None:
        value["pmcid"] = pmcid
    return value
