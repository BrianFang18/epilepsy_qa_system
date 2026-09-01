from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial
from typing import Annotated, Literal, TypeVar

import anyio
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)

from app.modules.admin.errors import (
    AdminConflict,
    AdminNotFound,
    AuthenticationFailed,
    UploadRejected,
)
from app.modules.admin.ports import AdminApplication
from app.modules.admin.schemas import (
    AdminSessionResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    EvaluationCreateRequest,
    EvaluationJobResponse,
    EvaluationListResponse,
    EvaluationSummaryResponse,
    IngestionJobResponse,
    LoginRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
T = TypeVar("T")


def _service_from(request: Request) -> AdminApplication:
    service = getattr(request.app.state, "admin_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Admin service is not enabled")
    return service


def _call(action: Callable[[], T]) -> T:
    try:
        return action()
    except AuthenticationFailed as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AdminNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdminConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Admin request failed")
        raise HTTPException(status_code=500, detail="Admin operation failed") from exc


def _session_token(request: Request, service: AdminApplication) -> str:
    token = request.cookies.get(service.cookie_name, "")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    return token


def _require_admin(
    request: Request,
    service: Annotated[AdminApplication, Depends(_service_from)],
) -> AdminSessionResponse:
    token = _session_token(request, service)
    return _call(lambda: service.current_session(token))


@router.post("/session", response_model=AdminSessionResponse)
def login(
    payload: LoginRequest,
    response: Response,
    service: Annotated[AdminApplication, Depends(_service_from)],
) -> AdminSessionResponse:
    grant = _call(lambda: service.login(payload.username, payload.password.get_secret_value()))
    response.set_cookie(
        key=service.cookie_name,
        value=grant.token,
        max_age=service.cookie_max_age,
        expires=grant.session.expires_at,
        path="/api/v1/admin",
        secure=service.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return grant.session


@router.get("/session", response_model=AdminSessionResponse)
def current_session(
    session: Annotated[AdminSessionResponse, Depends(_require_admin)],
    response: Response,
) -> AdminSessionResponse:
    response.headers["Cache-Control"] = "no-store"
    return session


@router.delete("/session", status_code=204, response_class=Response, response_model=None)
def logout(
    request: Request,
    response: Response,
    service: Annotated[AdminApplication, Depends(_service_from)],
) -> None:
    token = request.cookies.get(service.cookie_name, "")
    if token:
        _call(lambda: service.logout(token))
    response.delete_cookie(
        key=service.cookie_name,
        path="/api/v1/admin",
        secure=service.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(
                status_code=413,
                detail="Uploaded file exceeds the configured size limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/documents", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: Annotated[UploadFile, File()],
    session: Annotated[AdminSessionResponse, Depends(_require_admin)],
    service: Annotated[AdminApplication, Depends(_service_from)],
    title: Annotated[str | None, Form(max_length=255)] = None,
    doc_type: Annotated[Literal["literature", "clinical"], Form()] = "literature",
) -> DocumentUploadResponse:
    try:
        data = await _read_limited(file, service.max_upload_bytes)
        operation = partial(
            service.upload_document,
            filename=file.filename or "",
            content_type=file.content_type,
            data=data,
            title=title,
            doc_type=doc_type,
            created_by_id=session.user.id,
        )
        return await anyio.to_thread.run_sync(lambda: _call(operation))
    finally:
        await file.close()


@router.get("/documents", response_model=DocumentListResponse)
def list_documents(
    _: Annotated[AdminSessionResponse, Depends(_require_admin)],
    service: Annotated[AdminApplication, Depends(_service_from)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    return _call(lambda: service.list_documents(limit=limit, offset=offset))


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: str,
    _: Annotated[AdminSessionResponse, Depends(_require_admin)],
    service: Annotated[AdminApplication, Depends(_service_from)],
) -> DocumentResponse:
    return _call(lambda: service.get_document(document_id))


@router.get("/ingestion-jobs/{job_id}", response_model=IngestionJobResponse)
def get_ingestion_job(
    job_id: str,
    _: Annotated[AdminSessionResponse, Depends(_require_admin)],
    service: Annotated[AdminApplication, Depends(_service_from)],
) -> IngestionJobResponse:
    return _call(lambda: service.get_ingestion_job(job_id))


@router.post("/ingestion-jobs/{job_id}/retry", response_model=IngestionJobResponse)
def retry_ingestion_job(
    job_id: str,
    _: Annotated[AdminSessionResponse, Depends(_require_admin)],
    service: Annotated[AdminApplication, Depends(_service_from)],
) -> IngestionJobResponse:
    return _call(lambda: service.retry_ingestion_job(job_id))


@router.post("/ingestion-jobs/{job_id}/cancel", response_model=IngestionJobResponse)
def cancel_ingestion_job(
    job_id: str,
    _: Annotated[AdminSessionResponse, Depends(_require_admin)],
    service: Annotated[AdminApplication, Depends(_service_from)],
) -> IngestionJobResponse:
    return _call(lambda: service.cancel_ingestion_job(job_id))


@router.post("/evaluations", response_model=EvaluationJobResponse, status_code=202)
def create_evaluation(
    payload: EvaluationCreateRequest,
    session: Annotated[AdminSessionResponse, Depends(_require_admin)],
    service: Annotated[AdminApplication, Depends(_service_from)],
) -> EvaluationJobResponse:
    return _call(
        lambda: service.create_evaluation(
            name=payload.name,
            suite=payload.suite,
            requested_by_id=session.user.id,
        )
    )


@router.get("/evaluations", response_model=EvaluationListResponse)
def list_evaluations(
    _: Annotated[AdminSessionResponse, Depends(_require_admin)],
    service: Annotated[AdminApplication, Depends(_service_from)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvaluationListResponse:
    return _call(lambda: service.list_evaluations(limit=limit, offset=offset))


@router.get("/evaluations/summary", response_model=EvaluationSummaryResponse)
def evaluation_summary(
    _: Annotated[AdminSessionResponse, Depends(_require_admin)],
    service: Annotated[AdminApplication, Depends(_service_from)],
) -> EvaluationSummaryResponse:
    return _call(service.evaluation_summary)


@router.get("/evaluations/{job_id}", response_model=EvaluationJobResponse)
def get_evaluation(
    job_id: str,
    _: Annotated[AdminSessionResponse, Depends(_require_admin)],
    service: Annotated[AdminApplication, Depends(_service_from)],
) -> EvaluationJobResponse:
    return _call(lambda: service.get_evaluation(job_id))
