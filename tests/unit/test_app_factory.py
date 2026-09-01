"""Regression tests for side-effect-free imports and the ASGI app factory."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import _register_v2_router, create_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CUSTOM_ORIGIN = "https://epilepsy-ui.example.test"
_LOCALHOST_ORIGIN = "http://localhost:5173"


def _route_paths(application: FastAPI) -> list[str]:
    """Return paths from both direct routes and FastAPI's nested included routers."""
    paths: list[str] = []
    pending = list(application.routes)
    while pending:
        route = pending.pop()
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.append(path)
        nested = getattr(route, "routes", None)
        if nested:
            pending.extend(nested)
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            pending.extend(original_router.routes)
    return paths


@pytest.fixture(autouse=True)
def _isolate_get_settings_cache():
    """Prevent environment-derived settings from leaking between app factory tests."""
    main_module.get_settings.cache_clear()
    yield
    main_module.get_settings.cache_clear()


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "X-Test-Header",
        },
    )


def _assert_exact_cors_policy(client: TestClient) -> None:
    allowed = _preflight(client, _CUSTOM_ORIGIN)
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == _CUSTOM_ORIGIN
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert allowed.headers["access-control-allow-origin"] != "*"
    assert "PATCH" in allowed.headers["access-control-allow-methods"]
    assert "x-test-header" in allowed.headers["access-control-allow-headers"].lower()

    denied = _preflight(client, _LOCALHOST_ORIGIN)
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_import_app_main_does_not_load_heavy_services_or_use_network(tmp_path: Path) -> None:
    """A fresh import must not construct service/model/storage dependencies."""
    script = r"""
import socket
import sys

sys.path.insert(0, sys.argv[1])


def deny_network(*args, **kwargs):
    raise AssertionError("network access attempted during import")


socket.create_connection = deny_network
socket.socket.connect = deny_network

import app.main  # noqa: E402
from app.config import get_settings  # noqa: E402

cache_info = get_settings.cache_info()
assert cache_info.hits == 0, cache_info
assert cache_info.misses == 0, cache_info
assert cache_info.currsize == 0, cache_info

blocked = (
    "app.service",
    "app.v2",
    "FlagEmbedding",
    "openai",
    "qdrant_client",
)
unexpected = [
    name
    for name in sys.modules
    if any(name == item or name.startswith(f"{item}.") for item in blocked)
]
assert not unexpected, unexpected
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(PROJECT_ROOT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_default_create_app_resolves_cors_from_environment_lazily(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CORS_ORIGINS", f'["{_CUSTOM_ORIGIN}"]')

    application = create_app()
    assert main_module.get_settings.cache_info().currsize == 0

    client = TestClient(application)
    try:
        _assert_exact_cors_policy(client)
        assert main_module.get_settings.cache_info().currsize == 1

        main_module.get_settings.cache_clear()
        assert main_module.get_settings.cache_info().currsize == 0

        _assert_exact_cors_policy(client)
        assert main_module.get_settings.cache_info().currsize == 0
    finally:
        client.close()


def test_explicit_settings_drive_cors_without_global_settings_cache(
    settings_factory,
) -> None:
    settings = settings_factory(cors_origins=[_CUSTOM_ORIGIN])
    application = create_app(settings=settings)

    client = TestClient(application)
    try:
        _assert_exact_cors_policy(client)
    finally:
        client.close()

    assert main_module.get_settings.cache_info().currsize == 0


def test_create_app_keeps_health_root_and_v1_compatible(
    settings_factory,
    fake_service_factory,
) -> None:
    settings = settings_factory()
    service = fake_service_factory(settings)
    application = create_app(settings=settings, service=service)

    assert isinstance(main_module.app, FastAPI)
    route_paths = set(_route_paths(application))
    assert {
        "/",
        "/health",
        "/health/ready",
        "/api/v1/chat/stream",
        "/v1/ask",
        "/v1/ingest/text",
        "/v1/ingest/file",
        "/v1/ingest/clear",
        "/v1/eval/ragas",
        "/v1/eval/judge",
    } <= route_paths

    with TestClient(application) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {
            "status": "ok",
            "environment": "test",
            "kb_count": 0,
        }

        root = client.get("/")
        assert root.status_code == 200
        assert root.json() == {"message": "Epilepsy QA Test", "kb_count": 0}

        ask = client.post("/v1/ask", json={"question": "测试问题"})
        assert ask.status_code == 200
        assert ask.json()["answer"] == "fake:测试问题"

    assert service.closed is True


def test_production_never_seeds_demo_data(
    settings_factory,
    fake_service_factory,
) -> None:
    settings = settings_factory(
        environment="production",
        seed_demo_data=True,
        use_qdrant=True,
    )
    service = fake_service_factory(settings)
    application = create_app(settings=settings, service=service)

    with pytest.raises(RuntimeError, match="forbidden in production"):
        with TestClient(application):
            pass

    assert service.seed_calls == 0


def test_v2_router_registers_once_when_enabled(
    settings_factory,
    fake_service_factory,
) -> None:
    settings = settings_factory(enable_v2_workflow=True)
    service = fake_service_factory(settings)
    application = create_app(settings=settings, service=service)

    assert _route_paths(application).count("/v2/normalize") == 1
    with TestClient(application) as client:
        assert _route_paths(application).count("/v2/normalize") == 1
        response = client.post("/v2/normalize", json={"input": "我脑阔痛"})
        assert response.status_code == 200
        assert "头痛" in response.json()["normalized"]


def test_v2_router_is_absent_when_disabled(settings_factory, fake_service_factory) -> None:
    settings = settings_factory(enable_v2_workflow=False)
    application = create_app(settings=settings, service=fake_service_factory(settings))

    route_paths = _route_paths(application)
    assert all(not path.startswith("/v2") for path in route_paths)
    assert "/api/v1/chat/stream" in route_paths


def test_v2_router_tolerates_only_the_known_missing_module(monkeypatch) -> None:
    application = FastAPI()

    def missing_v2(_name: str):
        raise ModuleNotFoundError("V2 is absent", name=main_module._V2_MODULE)

    monkeypatch.setattr(main_module, "import_module", missing_v2)

    assert _register_v2_router(application) is False
    assert application.state.v2_router_available is False


def test_v2_router_does_not_hide_unknown_import_errors(monkeypatch) -> None:
    application = FastAPI()

    def missing_transitive_dependency(_name: str):
        raise ModuleNotFoundError(
            "Unexpected dependency is absent",
            name="unexpected_dependency",
        )

    monkeypatch.setattr(main_module, "import_module", missing_transitive_dependency)

    with pytest.raises(ModuleNotFoundError, match="Unexpected dependency"):
        _register_v2_router(application)
