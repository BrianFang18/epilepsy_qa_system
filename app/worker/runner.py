from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from typing import Any, NoReturn, Protocol

from app.infrastructure.database.models import EvaluationJob, IngestionJob
from app.infrastructure.database.repositories import ManagementRepository
from app.infrastructure.object_storage.ports import ObjectStorage

logger = logging.getLogger(__name__)

EVALUATION_NOT_CONFIGURED = "EVALUATION_NOT_CONFIGURED"
_PERMANENT_ERROR_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,127}")


class ChunkParser(Protocol):
    def parse_to_chunks(
        self,
        file_path: str,
        doc_id: str,
        title: str | None = None,
        doc_type: str = "literature",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[list[Any], list[Any]]: ...


class ChunkIndexer(Protocol):
    def index_child_chunks(self, chunks: list[Any]) -> int: ...

    def activate_managed_document(
        self,
        *,
        managed_document_id: str,
        content_sha256: str,
        expected_points: int,
    ) -> None: ...

    def delete_managed_document(self, *, managed_document_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    aggregate_metrics: Mapping[str, float]
    private_result_bucket: str | None = None
    private_result_object_key: str | None = None


EvaluationHandler = Callable[[EvaluationJob], EvaluationResult]


class PermanentEvaluationError(RuntimeError):
    """A sanitized evaluation failure that must never enter retry_wait."""

    def __init__(self, error_code: str) -> None:
        if _PERMANENT_ERROR_CODE_PATTERN.fullmatch(error_code) is None:
            raise ValueError("Permanent evaluation error codes must be sanitized constants")
        self.error_code = error_code
        super().__init__(error_code)


def evaluation_not_configured_handler(_job: EvaluationJob) -> NoReturn:
    """Fail closed until a controlled evaluation data source is explicitly wired."""
    raise PermanentEvaluationError(EVALUATION_NOT_CONFIGURED)


class LeaseLost(RuntimeError):
    pass


class JobCanceled(RuntimeError):
    pass


class ManagedDocumentCleanupError(RuntimeError):
    """A sanitized retryable failure raised when point compensation fails."""


class WorkerRunner:
    def __init__(
        self,
        *,
        worker_id: str,
        repository: ManagementRepository,
        object_storage: ObjectStorage,
        parser: ChunkParser,
        indexer: ChunkIndexer,
        lease_seconds: int,
        heartbeat_seconds: int,
        retry_base_seconds: int,
        poll_seconds: float,
        evaluation_handler: EvaluationHandler | None = None,
    ) -> None:
        self.worker_id = worker_id
        self._repository = repository
        self._objects = object_storage
        self._parser = parser
        self._indexer = indexer
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = min(heartbeat_seconds, max(5, lease_seconds // 2))
        self._retry_base_seconds = retry_base_seconds
        self._poll_seconds = poll_seconds
        self._evaluation_handler = evaluation_handler

    def run_once(self) -> bool:
        self._repository.heartbeat_worker(
            worker_id=self.worker_id,
            status="running",
            metadata={"queue": "postgresql"},
        )
        ingestion_job = self._repository.claim_ingestion_job(
            worker_id=self.worker_id,
            lease_seconds=self._lease_seconds,
        )
        if ingestion_job is not None:
            self._process_ingestion(ingestion_job)
            return True

        if self._evaluation_handler is not None:
            evaluation_job = self._repository.claim_evaluation_job(
                worker_id=self.worker_id,
                lease_seconds=self._lease_seconds,
            )
            if evaluation_job is not None:
                self._process_evaluation(evaluation_job)
                return True
        return False

    def run_forever(self, stop_event: Event) -> None:
        while not stop_event.is_set():
            processed = self.run_once()
            if not processed:
                stop_event.wait(self._poll_seconds)

    def stop(self) -> None:
        self._repository.heartbeat_worker(
            worker_id=self.worker_id,
            status="stopped",
            metadata={"queue": "postgresql"},
        )

    def _process_ingestion(self, job: IngestionJob) -> None:
        try:
            with self._lease_heartbeat(job.id, evaluation=False):
                self._execute_ingestion(job)
        except JobCanceled:
            self._repository.cancel_running_ingestion_job(
                job_id=job.id,
                worker_id=self.worker_id,
            )
        except LeaseLost:
            # A stale owner must not broadly delete points that may already belong
            # to a reclaiming worker. Staging remains query-invisible and the new
            # owner reruns the idempotent sequence.
            logger.warning("Worker lost ingestion lease for job %s", job.id)
        except Exception as exc:
            logger.exception("Ingestion job %s failed", job.id)
            retryable = not isinstance(exc, ValueError | UnicodeError | FileNotFoundError)
            delay = self._retry_base_seconds * max(1, 2 ** max(0, job.attempts - 1))
            self._repository.fail_ingestion_job(
                job_id=job.id,
                worker_id=self.worker_id,
                error_code=self._error_code(exc),
                error_message="Document processing failed",
                retryable=retryable,
                retry_delay_seconds=delay,
            )

    def _execute_ingestion(self, job: IngestionJob) -> None:
        document = self._repository.get_document(job.document_id)
        if document is None:
            raise ValueError("Document record is missing")

        points_may_exist = False
        try:
            self._advance(job.id, "fetch", 5)
            self._check_canceled(job.id)
            suffix = Path(document.filename).suffix.casefold()
            with TemporaryDirectory(prefix="epilepsy-ingest-") as temporary_directory:
                source_path = str(Path(temporary_directory) / f"source{suffix}")
                self._objects.download_file(
                    bucket=document.object_bucket,
                    object_key=document.object_key,
                    destination=source_path,
                )
                self._advance(job.id, "parse", 20)
                self._check_canceled(job.id)
                parents, children = self._parser.parse_to_chunks(
                    file_path=source_path,
                    doc_id=document.id,
                    title=document.title,
                    doc_type=document.doc_type,
                    metadata={
                        "managed_document_id": document.id,
                        "content_sha256": document.content_sha256,
                        "index_visibility": "staging",
                        "original_filename": document.filename,
                    },
                )
                if not children:
                    raise ValueError("Parser produced no indexable chunks")
                self._advance(job.id, "chunk", 45)
                self._check_canceled(job.id)
                self._advance(job.id, "embed", 60)
                self._check_canceled(job.id)
                self._advance(job.id, "index", 75)

                # Reclaimed attempts remove only this document's prior residue.
                # Other content and older active versions remain available.
                self._indexer.delete_managed_document(managed_document_id=document.id)
                self._check_canceled(job.id)
                points_may_exist = True
                inserted_children = self._indexer.index_child_chunks(children)
                if inserted_children != len(children):
                    raise ValueError("Indexer did not persist every generated child chunk")

            # An upsert can be non-interruptible. Observe cancellation and lease
            # ownership after it returns, while the new points are still staging.
            self._check_canceled(job.id)
            self._advance(job.id, "finalize", 95)
            self._check_canceled(job.id)
            self._indexer.activate_managed_document(
                managed_document_id=document.id,
                content_sha256=document.content_sha256,
                expected_points=inserted_children,
            )

            # Qdrant activation and PostgreSQL completion are intentionally not
            # presented as one transaction. Both sides are idempotent so a
            # reclaimed job can rerun after a crash at this boundary.
            completed = self._repository.complete_ingestion_job(
                job_id=job.id,
                worker_id=self.worker_id,
                inserted_parents=len(parents),
                inserted_children=inserted_children,
            )
            if not completed:
                raise LeaseLost("Unable to finalize ingestion job")
        except Exception as exc:
            if points_may_exist and not isinstance(exc, LeaseLost):
                try:
                    self._indexer.delete_managed_document(managed_document_id=document.id)
                except Exception as cleanup_exc:
                    if isinstance(exc, JobCanceled):
                        # Staging remains invisible even if best-effort deletion is
                        # unavailable, so honor the terminal cancellation.
                        logger.exception(
                            "Canceled ingestion point cleanup failed for job %s",
                            job.id,
                        )
                    else:
                        raise ManagedDocumentCleanupError(
                            "Managed document point cleanup failed"
                        ) from cleanup_exc
            raise

    def _process_evaluation(self, job: EvaluationJob) -> None:
        if self._evaluation_handler is None:
            return
        try:
            with self._lease_heartbeat(job.id, evaluation=True):
                result = self._evaluation_handler(job)
                metrics = self._validate_evaluation_metrics(result.aggregate_metrics)
                completed = self._repository.complete_evaluation_job(
                    job_id=job.id,
                    worker_id=self.worker_id,
                    aggregate_metrics=metrics,
                    private_result_bucket=result.private_result_bucket,
                    private_result_object_key=result.private_result_object_key,
                )
                if not completed:
                    raise LeaseLost("Unable to finalize evaluation job")
        except LeaseLost:
            logger.warning("Worker lost evaluation lease for job %s", job.id)
        except Exception as exc:
            logger.exception("Evaluation job %s failed", job.id)
            delay = self._retry_base_seconds * max(1, 2 ** max(0, job.attempts - 1))
            if isinstance(exc, PermanentEvaluationError):
                error_code = exc.error_code
                retryable = False
            else:
                error_code = self._error_code(exc)
                retryable = True
            self._repository.fail_evaluation_job(
                job_id=job.id,
                worker_id=self.worker_id,
                error_code=error_code,
                error_message="Evaluation processing failed",
                retryable=retryable,
                retry_delay_seconds=delay,
            )

    @staticmethod
    def _validate_evaluation_metrics(metrics: Mapping[str, float]) -> Mapping[str, float]:
        if not metrics:
            raise ValueError("Evaluation metrics must not be empty")
        for key, value in metrics.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("Evaluation metrics contain an invalid key")
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(float(value))
            ):
                raise ValueError("Evaluation metrics contain a non-finite numeric value")
        return metrics

    def _advance(self, job_id: str, stage: str, progress: int) -> None:
        updated = self._repository.set_ingestion_stage(
            job_id=job_id,
            worker_id=self.worker_id,
            stage=stage,
            progress=progress,
        )
        if not updated:
            raise LeaseLost("Unable to update ingestion stage")

    def _check_canceled(self, job_id: str) -> None:
        if not self._repository.ingestion_cancel_requested(job_id, self.worker_id):
            return
        current = self._repository.get_ingestion_job(job_id)
        if current is None or current.status != "running" or current.lease_owner != self.worker_id:
            raise LeaseLost("Ingestion lease is no longer owned by this worker")
        raise JobCanceled("Ingestion cancellation requested")

    @contextmanager
    def _lease_heartbeat(self, job_id: str, *, evaluation: bool) -> Iterator[None]:
        stopped = Event()

        def maintain() -> None:
            while not stopped.wait(self._heartbeat_seconds):
                if evaluation:
                    maintained = self._repository.heartbeat_evaluation_job(
                        job_id=job_id,
                        worker_id=self.worker_id,
                        lease_seconds=self._lease_seconds,
                    )
                else:
                    maintained = self._repository.heartbeat_ingestion_job(
                        job_id=job_id,
                        worker_id=self.worker_id,
                        lease_seconds=self._lease_seconds,
                    )
                if not maintained:
                    return

        thread = Thread(target=maintain, name=f"lease-{job_id[:8]}", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join(timeout=max(1.0, self._heartbeat_seconds / 2))

    @staticmethod
    def _error_code(exc: Exception) -> str:
        name = exc.__class__.__name__
        return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()[:128]
