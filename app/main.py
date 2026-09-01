from __future__ import annotations

import inspect
import logging
from contextlib import asynccontextmanager
from importlib import import_module
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from .api.v1.admin import router as admin_router
from .api.v1.chat import router as chat_router
from .config import Settings, get_settings
from .schemas import (
    AskRequest,
    AskResponse,
    IngestFileRequest,
    IngestResponse,
    IngestTextRequest,
    JudgeRequest,
    JudgeResponse,
    RagasEvalRequest,
    RagasEvalResponse,
)

logger = logging.getLogger(__name__)

_DEFAULT_APP_NAME = "Epilepsy Agentic RAG System"
_V2_MODULE = f"{__package__}.v2.api_v2"
_OPTIONAL_V2_MODULES = {f"{__package__}.v2", _V2_MODULE}


class _LazySettingsCORSMiddleware:
    """Resolve CORS settings on first HTTP use, never during app construction."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        configured_settings: Settings | None,
    ) -> None:
        self._app = app
        self._configured_settings = configured_settings
        self._delegate: ASGIApp | None = None
        self._delegate_lock = Lock()

    def _get_delegate(self) -> ASGIApp:
        delegate = self._delegate
        if delegate is not None:
            return delegate

        with self._delegate_lock:
            delegate = self._delegate
            if delegate is None:
                runtime_settings = self._configured_settings or get_settings()
                delegate = CORSMiddleware(
                    self._app,
                    allow_origins=list(runtime_settings.cors_origins),
                    allow_methods=["*"],
                    allow_headers=["*"],
                    allow_credentials=True,
                )
                self._delegate = delegate
        return delegate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        await self._get_delegate()(scope, receive, send)


def _is_production(settings: Settings) -> bool:
    return settings.environment.strip().casefold() in {"prod", "production"}


def _register_v2_router(application: FastAPI) -> bool:
    """Register V2 only when its route module is available.

    A missing optional V2 package is recoverable. Errors raised from inside an
    available V2 package are not: they must fail application creation/startup.
    """
    if getattr(application.state, "v2_router_registered", False):
        return True

    try:
        module = import_module(_V2_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name not in _OPTIONAL_V2_MODULES:
            raise
        logger.warning("V2 routes are enabled but unavailable: %s", exc)
        application.state.v2_router_available = False
        return False

    application.include_router(module.router)
    # Routes may be added during lifespan, after an early OpenAPI request.
    application.openapi_schema = None
    application.state.v2_router_available = True
    application.state.v2_router_registered = True
    return True


def _service_from(request: Request) -> Any:
    service = getattr(request.app.state, "service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Service is not initialized")
    return service


def _settings_from(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=503, detail="Settings are not initialized")
    return settings


def create_app(
    settings: Settings | None = None,
    service: Any | None = None,
    *,
    chat_service: Any | None = None,
    retriever: Any | None = None,
    llm: Any | None = None,
    admin_runtime: Any | None = None,
) -> FastAPI:
    """Build the ASGI app without constructing model or storage dependencies.

    Passing settings and a fake service keeps tests deterministic. When no
    service is injected, the production service is constructed inside lifespan.
    """
    configured_settings = settings or getattr(service, "settings", None)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        runtime_settings = configured_settings or get_settings()
        application.state.settings = runtime_settings
        application.title = runtime_settings.app_name

        if runtime_settings.enable_v2_workflow:
            _register_v2_router(application)

        if runtime_settings.seed_demo_data and _is_production(runtime_settings):
            raise RuntimeError("Demo data seeding is forbidden in production")

        runtime_admin = admin_runtime
        runtime_service = service
        runtime_chat_service = chat_service
        try:
            if runtime_admin is None and runtime_settings.enable_admin_api:
                # SQLAlchemy, Argon2 and MinIO stay behind startup.
                from .modules.admin.factory import build_admin_runtime

                runtime_admin = build_admin_runtime(runtime_settings)
            application.state.admin_service = (
                getattr(runtime_admin, "service", runtime_admin)
                if runtime_admin is not None
                else None
            )

            if runtime_service is None:
                # Keep all model imports and Qdrant initialization behind startup.
                from .service import EpilepsyAgentService

                runtime_service = EpilepsyAgentService(runtime_settings)

            application.state.service = runtime_service
            application.state.llm = getattr(runtime_service, "llm", None)
            application.state.retriever = getattr(runtime_service, "retriever", None)
            application.state.embedder = getattr(runtime_service, "embedder", None)

            legacy_retriever = getattr(runtime_service, "retriever", None)
            if runtime_chat_service is None and (
                retriever is not None or callable(getattr(legacy_retriever, "retrieve", None))
            ):
                # Keep LangGraph, OpenAI and V2 normalization imports behind startup.
                from .modules.chat.factory import build_chat_service

                runtime_chat_service = build_chat_service(
                    runtime_settings,
                    legacy_retriever=legacy_retriever,
                    retriever=retriever,
                    llm=llm,
                )
            application.state.chat_service = runtime_chat_service

            if runtime_settings.seed_demo_data:
                runtime_service.seed_demo_data()

            logger.info("Application startup complete")
            yield
        finally:
            try:
                if runtime_admin is not None and runtime_admin is not runtime_service:
                    close_admin = getattr(runtime_admin, "close", None)
                    if callable(close_admin):
                        result = close_admin()
                        if inspect.isawaitable(result):
                            await result
            finally:
                try:
                    if (
                        runtime_chat_service is not None
                        and runtime_chat_service is not runtime_service
                    ):
                        close_chat = getattr(runtime_chat_service, "close", None)
                        if callable(close_chat):
                            result = close_chat()
                            if inspect.isawaitable(result):
                                await result
                finally:
                    close = getattr(runtime_service, "close", None)
                    if callable(close):
                        result = close()
                        if inspect.isawaitable(result):
                            await result
            logger.info("Application shutdown")

    application = FastAPI(
        title=(configured_settings.app_name if configured_settings else _DEFAULT_APP_NAME),
        version="1.0.0",
        description=(
            "Agentic RAG for epilepsy specialist QA and retrieval. "
            "V2 adds doctor-style multi-turn consultation."
        ),
        lifespan=lifespan,
    )
    # These additive routers are independent of the optional V2 workflow flag.
    application.include_router(chat_router)
    application.include_router(admin_router)

    if configured_settings is not None:
        application.state.settings = configured_settings
        if configured_settings.enable_v2_workflow:
            _register_v2_router(application)

    application.add_middleware(
        _LazySettingsCORSMiddleware,
        configured_settings=configured_settings,
    )

    @application.get("/")
    def root(request: Request) -> dict[str, Any]:
        runtime_service = _service_from(request)
        runtime_settings = _settings_from(request)
        return {
            "message": runtime_settings.app_name,
            "kb_count": runtime_service.kb_count(),
        }

    @application.get("/health")
    def health(request: Request) -> dict[str, Any]:
        runtime_service = _service_from(request)
        runtime_settings = _settings_from(request)
        return {
            "status": "ok",
            "environment": runtime_settings.environment,
            "kb_count": runtime_service.kb_count(),
        }

    @application.get("/health/ready")
    def readiness(request: Request) -> dict[str, Any]:
        legacy_ready = getattr(request.app.state, "service", None) is not None
        chat_ready = getattr(request.app.state, "chat_service", None) is not None
        runtime_settings = getattr(request.app.state, "settings", None)
        admin_enabled = bool(runtime_settings is not None and runtime_settings.enable_admin_api)
        admin_ready = getattr(request.app.state, "admin_service", None) is not None
        dependencies_ready = legacy_ready and chat_ready and (not admin_enabled or admin_ready)
        return {
            "status": "ready" if dependencies_ready else "degraded",
            "legacy_ready": legacy_ready,
            "chat_ready": chat_ready,
            "admin_enabled": admin_enabled,
            "admin_ready": admin_ready,
        }

    @application.post("/v1/ask", response_model=AskResponse)
    def ask(request: AskRequest, http_request: Request) -> AskResponse:
        try:
            return _service_from(http_request).ask(request)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"ask failed: {exc}") from exc

    @application.post("/v1/ingest/text", response_model=IngestResponse)
    def ingest_text(request: IngestTextRequest, http_request: Request) -> IngestResponse:
        try:
            return _service_from(http_request).ingest_text(request)
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"ingest_text failed: {exc}") from exc

    @application.post("/v1/ingest/file", response_model=IngestResponse)
    def ingest_file(request: IngestFileRequest, http_request: Request) -> IngestResponse:
        try:
            return _service_from(http_request).ingest_file(request)
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"ingest_file failed: {exc}") from exc

    @application.post("/v1/ingest/clear")
    def ingest_clear(http_request: Request) -> dict[str, str]:
        _service_from(http_request).kb_clear()
        return {"status": "ok", "message": "knowledge base cleared"}

    @application.post(
        "/v1/eval/ragas",
        response_model=RagasEvalResponse,
        summary="Deterministic lexical context evaluation (legacy URL)",
    )
    def context_eval_compat(
        request: RagasEvalRequest,
        http_request: Request,
    ) -> RagasEvalResponse:
        try:
            return _service_from(http_request).evaluate_ragas(request)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail="context evaluation failed") from exc

    @application.post("/v1/eval/judge", response_model=JudgeResponse)
    def judge_eval(request: JudgeRequest, http_request: Request) -> JudgeResponse:
        try:
            return _service_from(http_request).run_judge(request)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"judge failed: {exc}") from exc

    return application


# Keep the existing ASGI entry point while deferring CORS settings until first
# HTTP use and service setup until the server enters lifespan.
app = create_app()
