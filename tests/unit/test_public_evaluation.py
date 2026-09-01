"""Tests for the isolated, aggregate-only public evaluation pipeline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from io import StringIO
from pathlib import Path
from typing import Any, cast
from urllib.request import Request
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.evaluation.public import (
    PUBLIC_CHAT_ENDPOINT,
    PublicEvalDataset,
    PublicEvalManifest,
    PublicEvalSample,
    PublicEvaluationError,
    SafetyExpectations,
    SampleObservation,
    aggregate_metrics,
    assert_aggregate_only,
    build_aggregate_result,
    load_public_dataset,
    parse_chat_sse,
    resolve_public_eval_path,
    run_public_evaluation,
)
from app.modules.chat.schemas import ChatRequest
from scripts.run_public_evaluation import main as run_cli

_REQUEST_ID = "00000000-0000-4000-8000-000000000001"
_TIMESTAMP = "2025-01-01T00:00:00Z"
_RESULT_KEYS = {
    "run",
    "dataset",
    "time",
    "endpoint",
    "parameters",
    "counts",
    "error_code_counts",
    "metrics",
    "latency",
}


def _safety_payload(expected_action: str = "answer") -> dict[str, object]:
    return {
        "expected_action": expected_action,
        "required_event_codes": [],
        "forbidden_patterns": [],
        "require_disclaimer": False,
        "forbid_reasoning": True,
    }


def _sample_payload(
    sample_id: str = "sample-one",
    *,
    suites: Sequence[str] = ("retrieval", "generation", "safety"),
) -> dict[str, object]:
    return {
        "id": sample_id,
        "suites": list(suites),
        "question": "What does the public evidence say?",
        "reference_answer": "A concise public reference.",
        "relevant_document_ids": ["doc-1"],
        "tags": ["public"],
        "safety_expectations": _safety_payload(),
    }


def _write_public_dataset(
    repo: Path,
    *,
    records: Sequence[Mapping[str, object]] | None = None,
    manifest_overrides: Mapping[str, object] | None = None,
) -> tuple[Path, Path]:
    public_root = repo / "public_eval"
    public_root.mkdir(parents=True)
    selected_records = list(records) if records is not None else [_sample_payload()]
    samples_bytes = (
        "\n".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            for record in selected_records
        )
        + "\n"
    ).encode()
    samples_path = public_root / "samples.jsonl"
    samples_path.write_bytes(samples_bytes)
    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "dataset_version": "public-v1",
        "samples_sha256": hashlib.sha256(samples_bytes).hexdigest(),
        "license": "CC-BY-4.0",
        "provenance": "Synthetic public unit-test fixture",
        "target_endpoint": PUBLIC_CHAT_ENDPOINT,
        "seed": 7,
    }
    if manifest_overrides is not None:
        manifest.update(manifest_overrides)
    manifest_path = public_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return manifest_path, samples_path


def _expect_public_error(code: str, function: Any, /, *args: Any, **kwargs: Any) -> None:
    with pytest.raises(PublicEvaluationError) as caught:
        function(*args, **kwargs)
    assert caught.value.code == code


def _expectations(
    expected_action: str = "answer",
    *,
    required_event_codes: tuple[str, ...] = (),
    forbidden_patterns: tuple[str, ...] = (),
    require_disclaimer: bool = False,
    forbid_reasoning: bool = True,
) -> SafetyExpectations:
    return SafetyExpectations(
        expected_action=cast(Any, expected_action),
        required_event_codes=required_event_codes,
        forbidden_patterns=forbidden_patterns,
        require_disclaimer=require_disclaimer,
        forbid_reasoning=forbid_reasoning,
    )


def _sample(
    sample_id: str,
    *,
    suites: tuple[str, ...] = ("safety",),
    expectations: SafetyExpectations | None = None,
    reference_answer: str | None = None,
    relevant_document_ids: tuple[str, ...] = (),
) -> PublicEvalSample:
    return PublicEvalSample(
        id=sample_id,
        suites=suites,
        question=f"Public question for {sample_id}",
        safety_expectations=expectations or _expectations(),
        reference_answer=reference_answer,
        relevant_document_ids=relevant_document_ids,
    )


def _manifest(samples_hash: str = "a" * 64) -> PublicEvalManifest:
    return PublicEvalManifest(
        schema_version="1.0",
        dataset_version="public-v1",
        samples_sha256=samples_hash,
        license="CC-BY-4.0",
        provenance="Synthetic public unit-test fixture",
        target_endpoint=PUBLIC_CHAT_ENDPOINT,
        seed=7,
    )


def _dataset(*samples: PublicEvalSample) -> PublicEvalDataset:
    return PublicEvalDataset(manifest=_manifest(), samples=samples)


def _frame(
    session_id: str,
    sequence: int,
    event: str,
    data: Mapping[str, object],
    *,
    request_id: str = _REQUEST_ID,
) -> bytes:
    envelope = {
        "request_id": request_id,
        "session_id": session_id,
        "sequence": sequence,
        "event": event,
        "timestamp": _TIMESTAMP,
        "data": dict(data),
    }
    payload = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    return f"id: {request_id}:{sequence}\nevent: {event}\ndata: {payload}\n\n".encode()


def _successful_stream(session_id: str) -> bytes:
    return b"".join(
        [
            _frame(session_id, 1, "meta", {"stream_version": "1"}),
            _frame(session_id, 2, "status", {"stage": "retrieval"}),
            _frame(
                session_id,
                3,
                "sources",
                {"citations": [{"document_id": "doc-1"}]},
            ),
            _frame(session_id, 4, "token", {"content": "public response"}),
            _frame(session_id, 5, "done", {"finish_reason": "stop"}),
        ]
    )


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        content_type: str = "application/json",
    ) -> None:
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._body = body
        self._offset = 0
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self._body) - self._offset
        end = min(self._offset + amount, len(self._body))
        chunk = self._body[self._offset : end]
        self._offset = end
        return chunk

    def close(self) -> None:
        self.closed = True


class ContractHTTP:
    """Fake transport that refuses every request outside the two public endpoints."""

    def __init__(self) -> None:
        self.requests: list[Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: Request, *, timeout: float) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        method = request.get_method()
        if len(self.requests) == 1:
            assert method == "GET"
            assert request.full_url == "https://product.invalid/health/ready"
            assert request.data is None
            return FakeResponse(b'{"status":"ready","chat_ready":true}')
        if len(self.requests) == 2:
            assert method == "POST"
            assert request.full_url == "https://product.invalid/api/v1/chat/stream"
            request_data = request.data
            assert isinstance(request_data, bytes)
            payload = json.loads(request_data.decode())
            assert set(payload) == {"session_id", "message", "history", "trace_level"}
            session_id = cast(str, payload["session_id"])
            UUID(session_id)
            return FakeResponse(
                _successful_stream(session_id),
                content_type="text/event-stream; charset=utf-8",
            )
        raise AssertionError("public evaluation attempted an unexpected HTTP request")


class NoHTTP:
    def __call__(self, *_args: object, **_kwargs: object) -> FakeResponse:
        raise AssertionError("dry-run must not perform HTTP")


def test_loads_only_valid_public_paths_and_verified_hash(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    manifest_path, samples_path = _write_public_dataset(repo)

    dataset = load_public_dataset(repo)

    assert dataset.manifest.samples_sha256 == hashlib.sha256(samples_path.read_bytes()).hexdigest()
    assert [sample.id for sample in dataset.samples] == ["sample-one"]
    assert resolve_public_eval_path(repo, manifest_path, kind="manifest") == manifest_path
    assert resolve_public_eval_path(repo, samples_path, kind="samples") == samples_path


def test_rejects_public_samples_hash_mismatch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_public_dataset(repo, manifest_overrides={"samples_sha256": "0" * 64})

    _expect_public_error("SAMPLES_HASH_MISMATCH", load_public_dataset, repo)


def test_rejects_duplicate_sample_ids(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    duplicate = _sample_payload("duplicate-id")
    _write_public_dataset(repo, records=[duplicate, duplicate])

    _expect_public_error("SAMPLE_ID_DUPLICATE", load_public_dataset, repo)


def test_rejects_duplicate_json_object_keys(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    manifest_path, samples_path = _write_public_dataset(repo)
    samples_hash = hashlib.sha256(samples_path.read_bytes()).hexdigest()
    manifest_path.write_text(
        "{"
        '"schema_version":"1.0",'
        '"dataset_version":"public-v1",'
        f'"samples_sha256":"{samples_hash}",'
        '"license":"CC-BY-4.0",'
        '"provenance":"fixture",'
        f'"target_endpoint":"{PUBLIC_CHAT_ENDPOINT}",'
        '"seed":7,"seed":8'
        "}",
        encoding="utf-8",
    )

    _expect_public_error("MANIFEST_JSON_INVALID", load_public_dataset, repo)


@pytest.mark.parametrize(
    ("location", "expected_code"),
    [("manifest", "MANIFEST_SCHEMA_INVALID"), ("sample", "SAMPLE_SCHEMA_INVALID")],
)
def test_rejects_extra_public_schema_fields(
    tmp_path: Path,
    location: str,
    expected_code: str,
) -> None:
    repo = tmp_path / "repo"
    if location == "manifest":
        _write_public_dataset(repo, manifest_overrides={"unexpected": True})
    else:
        record = _sample_payload()
        record["unexpected"] = True
        _write_public_dataset(repo, records=[record])

    _expect_public_error(expected_code, load_public_dataset, repo)


def test_rejects_path_escape_and_denied_path_names(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_public_dataset(repo)
    (repo / "outside.jsonl").write_text("{}\n", encoding="utf-8")

    _expect_public_error(
        "PUBLIC_PATH_SYMLINK_ESCAPE",
        resolve_public_eval_path,
        repo,
        "public_eval/../outside.jsonl",
        kind="samples",
    )
    _expect_public_error(
        "PUBLIC_PATH_DENIED",
        resolve_public_eval_path,
        repo,
        "public_eval/data/samples.jsonl",
        kind="samples",
    )


def test_rejects_symlink_even_when_target_stays_public(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _, samples_path = _write_public_dataset(repo)
    linked_path = samples_path.with_name("linked.jsonl")
    linked_path.symlink_to(samples_path.name)

    _expect_public_error(
        "PUBLIC_PATH_SYMLINK_ESCAPE",
        resolve_public_eval_path,
        repo,
        linked_path,
        kind="samples",
    )


def test_sse_parser_accepts_arbitrary_byte_fragmentation_and_done() -> None:
    session_id = "00000000-0000-4000-8000-000000000002"
    stream = b"".join(
        [
            _frame(session_id, 1, "meta", {"stream_version": "1"}),
            _frame(session_id, 2, "status", {"stage": "retrieval"}),
            _frame(
                session_id,
                3,
                "sources",
                {
                    "citations": [
                        {"document_id": "doc-2"},
                        {"document_id": "doc-2"},
                        {"document_id": "doc-1"},
                    ]
                },
            ),
            _frame(session_id, 4, "token", {"content": "公"}),
            _frame(session_id, 5, "token", {"content": "开 answer"}),
            _frame(session_id, 6, "safety", {"code": "PUBLIC_SAFE"}),
            _frame(session_id, 7, "done", {"finish_reason": "stop"}),
        ]
    )

    result = parse_chat_sse(
        (stream[index : index + 1] for index in range(len(stream))),
        expected_session_id=session_id,
    )

    assert result.terminal_event == "done"
    assert result.answer == "公开 answer"
    assert result.source_document_ids == ("doc-2", "doc-1")
    assert result.event_codes == frozenset({"PUBLIC_SAFE"})
    assert result.finish_reason == "stop"
    assert result.error_code is None
    assert result.sources_received is True


def test_sse_parser_accepts_terminal_error_and_sanitizes_code() -> None:
    session_id = "00000000-0000-4000-8000-000000000003"
    stream = b"".join(
        [
            _frame(session_id, 1, "meta", {"stream_version": "1"}),
            _frame(session_id, 2, "error", {"code": "unsafe detail"}),
        ]
    )

    result = parse_chat_sse([stream], expected_session_id=session_id)

    assert result.terminal_event == "error"
    assert result.error_code == "UPSTREAM_ERROR"
    assert result.event_codes == frozenset({"UPSTREAM_ERROR"})
    assert result.sources_received is False


@pytest.mark.parametrize(
    ("event", "data"),
    [("token", {"content": "too early"}), ("done", {"finish_reason": "stop"})],
)
def test_sse_parser_rejects_events_before_sources(
    event: str,
    data: Mapping[str, object],
) -> None:
    session_id = "00000000-0000-4000-8000-000000000004"
    stream = b"".join(
        [
            _frame(session_id, 1, "meta", {"stream_version": "1"}),
            _frame(session_id, 2, event, data),
        ]
    )

    _expect_public_error(
        "SSE_EVENT_ORDER_INVALID",
        parse_chat_sse,
        [stream],
        expected_session_id=session_id,
    )


def test_http_runner_uses_only_readiness_and_real_chat_contract() -> None:
    sample = _sample(
        "http-contract",
        suites=("retrieval", "generation", "safety"),
        reference_answer="public response",
        relevant_document_ids=("doc-1",),
    )
    transport = ContractHTTP()

    result = run_public_evaluation(
        _dataset(sample),
        base_url="https://product.invalid",
        model_id="model-public",
        retriever_id="retriever-public",
        build_id="build-public",
        top_k=9,
        timeout_seconds=3.0,
        opener=transport,
    )

    assert [request.get_method() for request in transport.requests] == ["GET", "POST"]
    assert transport.timeouts == [3.0, 3.0]
    post = transport.requests[1]
    post_data = post.data
    assert isinstance(post_data, bytes)
    payload = json.loads(post_data.decode())
    assert payload == {
        "session_id": payload["session_id"],
        "message": sample.question,
        "history": [],
        "trace_level": "summary",
    }
    headers = {name.casefold(): value for name, value in post.header_items()}
    assert headers["accept"] == "text/event-stream"
    assert headers["content-type"] == "application/json"
    assert cast(dict[str, object], result["parameters"])["metric_top_k"] == 9
    assert cast(dict[str, object], result["counts"])["successful"] == 1


def test_retrieval_generation_and_safety_metrics_are_exact() -> None:
    sample = _sample(
        "exact-metrics",
        suites=("retrieval", "generation", "safety"),
        expectations=_expectations(
            required_event_codes=("SAFE_ONE", "SAFE_TWO"),
            forbidden_patterns=("forbidden",),
        ),
        reference_answer="alpha gamma",
        relevant_document_ids=("doc-1", "doc-2"),
    )
    observation = SampleObservation(
        completed=True,
        generation_success=True,
        error_code=None,
        latency_ms=10.0,
        answer="alpha beta",
        source_document_ids=("doc-2", "irrelevant", "doc-2", "doc-1"),
        event_codes=frozenset({"SAFE_ONE"}),
        finish_reason="stop",
        sources_received=True,
    )

    metrics = aggregate_metrics([sample], [observation], top_k=2)

    assert metrics["retrieval"] == {
        "recall_at_k": {"value": 0.5, "denominator": 1},
        "precision_at_k": {"value": 0.5, "denominator": 1},
        "mrr": {"value": 1.0, "denominator": 1},
        "ndcg": {"value": 0.613147, "denominator": 1},
    }
    assert metrics["generation"] == {
        "token_f1": {"value": 0.5, "denominator": 1},
        "jaccard": {"value": 0.333333, "denominator": 1},
        "answer_nonempty_rate": {"value": 1.0, "denominator": 1},
    }
    assert metrics["safety"] == {
        "expected_action_accuracy": {"value": 1.0, "denominator": 1},
        "required_event_recall": {"value": 0.5, "denominator": 2},
        "forbidden_pattern_pass_rate": {"value": 1.0, "denominator": 1},
        "disclaimer_rate": {"value": 0.0, "denominator": 0},
        "reasoning_leakage_pass_rate": {"value": 1.0, "denominator": 1},
        "emergency_recall": {"value": 0.0, "denominator": 0},
        "unsafe_advice_block_rate": {"value": 0.0, "denominator": 0},
        "no_evidence_refusal_rate": {"value": 0.0, "denominator": 0},
    }


def test_all_safety_action_branches_and_optional_checks() -> None:
    cases = [
        (
            "answer",
            _expectations(),
            SampleObservation(
                completed=True,
                generation_success=True,
                error_code=None,
                latency_ms=1.0,
                answer="ordinary public answer",
                finish_reason="stop",
            ),
        ),
        (
            "emergency",
            _expectations(
                "emergency",
                required_event_codes=("EMERGENCY_DETECTED",),
                require_disclaimer=True,
            ),
            SampleObservation(
                completed=True,
                generation_success=False,
                error_code=None,
                latency_ms=1.0,
                answer="请立即处理，并咨询医生。",
                event_codes=frozenset({"EMERGENCY_DETECTED"}),
                finish_reason="emergency",
            ),
        ),
        (
            "unsafe",
            _expectations(
                "unsafe_advice_block",
                required_event_codes=("DIRECT_DIAGNOSIS_BLOCKED",),
                forbidden_patterns=("take this dose",),
            ),
            SampleObservation(
                completed=True,
                generation_success=False,
                error_code=None,
                latency_ms=1.0,
                answer="I cannot provide an individual diagnosis.",
                event_codes=frozenset({"DIRECT_DIAGNOSIS_BLOCKED"}),
                finish_reason="blocked",
            ),
        ),
        (
            "no-evidence",
            _expectations(
                "no_evidence_refusal",
                required_event_codes=("INSUFFICIENT_EVIDENCE",),
            ),
            SampleObservation(
                completed=True,
                generation_success=False,
                error_code=None,
                latency_ms=1.0,
                answer="There is insufficient evidence.",
                event_codes=frozenset({"INSUFFICIENT_EVIDENCE"}),
                finish_reason="insufficient_evidence",
            ),
        ),
    ]
    samples = [_sample(name, expectations=expectations) for name, expectations, _ in cases]
    observations = [observation for _, _, observation in cases]

    safety = aggregate_metrics(samples, observations, top_k=5)["safety"]

    assert safety["expected_action_accuracy"] == {"value": 1.0, "denominator": 4}
    assert safety["required_event_recall"] == {"value": 1.0, "denominator": 3}
    assert safety["forbidden_pattern_pass_rate"] == {"value": 1.0, "denominator": 1}
    assert safety["disclaimer_rate"] == {"value": 1.0, "denominator": 1}
    assert safety["reasoning_leakage_pass_rate"] == {"value": 1.0, "denominator": 4}
    assert safety["emergency_recall"] == {"value": 1.0, "denominator": 1}
    assert safety["unsafe_advice_block_rate"] == {"value": 1.0, "denominator": 1}
    assert safety["no_evidence_refusal_rate"] == {"value": 1.0, "denominator": 1}


def test_metric_zero_denominators_are_explicit() -> None:
    metrics = aggregate_metrics([], [], top_k=5)

    for suite in metrics.values():
        for metric in suite.values():
            assert metric == {"value": 0.0, "denominator": 0}


def test_result_is_aggregate_only_and_metric_cutoff_is_honestly_named() -> None:
    sample = _sample(
        "aggregate-sample",
        suites=("generation",),
        reference_answer="sensitive reference phrase",
    )
    observation = SampleObservation(
        completed=True,
        generation_success=True,
        error_code=None,
        latency_ms=12.5,
        answer="sensitive generated phrase",
        finish_reason="stop",
    )
    result = build_aggregate_result(
        _dataset(sample),
        [observation],
        model_id="model-public",
        retriever_id="retriever-public",
        build_id="build-public",
        top_k=7,
        timeout_seconds=2.0,
        concurrency=1,
        dry_run=False,
        started_at="2025-01-01T00:00:00.000Z",
        completed_at="2025-01-01T00:00:01.000Z",
    )

    assert set(result) == _RESULT_KEYS
    assert result["parameters"] == {
        "metric_top_k": 7,
        "timeout_seconds": 2.0,
        "concurrency": 1,
        "seed": 7,
        "dry_run": False,
    }
    reference_answer = sample.reference_answer
    assert reference_answer is not None
    serialized = json.dumps(result, ensure_ascii=False)
    assert sample.id not in serialized
    assert sample.question not in serialized
    assert reference_answer not in serialized
    assert observation.answer not in serialized
    assert_aggregate_only(
        result,
        sensitive_texts=(
            sample.id,
            sample.question,
            reference_answer,
            observation.answer,
        ),
    )

    _expect_public_error(
        "AGGREGATE_ONLY_VIOLATION",
        assert_aggregate_only,
        {**result, "metrics": {"question": "leaked"}},
    )
    _expect_public_error(
        "AGGREGATE_ONLY_VIOLATION",
        assert_aggregate_only,
        {**result, "endpoint": sample.question},
        sensitive_texts=(sample.question,),
    )
    _expect_public_error(
        "AGGREGATE_ONLY_VIOLATION",
        assert_aggregate_only,
        {**result, "latency": {"mean_ms": float("nan")}},
    )


def test_dry_run_performs_zero_http_requests() -> None:
    sample = _sample("dry-run", suites=("retrieval", "generation", "safety"))

    result = run_public_evaluation(
        _dataset(sample),
        base_url="https://product.invalid",
        model_id="model-public",
        retriever_id="retriever-public",
        build_id="build-public",
        top_k=4,
        dry_run=True,
        opener=NoHTTP(),
    )

    assert result["counts"] == {
        "samples": 1,
        "successful": 0,
        "failed": 0,
        "generation_successful": 0,
    }
    assert result["latency"] == {
        "count": 0,
        "mean_ms": 0.0,
        "p50_ms": 0.0,
        "p95_ms": 0.0,
    }
    for suite in cast(dict[str, dict[str, dict[str, float | int]]], result["metrics"]).values():
        for metric in suite.values():
            assert metric["denominator"] == 0
            assert metric["value"] == 0.0


def _cli_arguments(*, dry_run: bool = True) -> list[str]:
    arguments = [
        "--base-url",
        "https://product.invalid",
        "--model-id",
        "model-public",
        "--retriever-id",
        "retriever-public",
        "--build-id",
        "build-public",
        "--top-k",
        "8",
    ]
    if dry_run:
        arguments.append("--dry-run")
    return arguments


def test_cli_dry_run_succeeds_with_aggregate_only_json(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_public_dataset(repo)
    stdout = StringIO()
    stderr = StringIO()

    exit_code = run_cli(
        _cli_arguments(),
        repo_root=repo,
        opener=NoHTTP(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert set(payload) == _RESULT_KEYS
    assert payload["parameters"]["metric_top_k"] == 8
    assert "sample-one" not in stdout.getvalue()
    assert "What does the public evidence say?" not in stdout.getvalue()


def test_cli_reports_stable_public_error_without_internal_detail(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_public_dataset(repo, manifest_overrides={"samples_sha256": "0" * 64})
    stdout = StringIO()
    stderr = StringIO()

    exit_code = run_cli(
        _cli_arguments(),
        repo_root=repo,
        opener=NoHTTP(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == '{"error_code":"SAMPLES_HASH_MISMATCH"}\n'


@pytest.mark.parametrize(
    ("extra_field", "value"),
    [("question", "ignored alias"), ("top_k", 5)],
)
def test_chat_request_rejects_fields_outside_real_contract(
    extra_field: str,
    value: object,
) -> None:
    payload: dict[str, object] = {
        "session_id": "00000000-0000-4000-8000-000000000005",
        "message": "public question",
        "history": [],
        "trace_level": "summary",
        extra_field: value,
    }

    with pytest.raises(ValidationError) as caught:
        ChatRequest.model_validate(payload)

    assert [(error["type"], error["loc"]) for error in caught.value.errors(include_url=False)] == [
        ("extra_forbidden", (extra_field,))
    ]
