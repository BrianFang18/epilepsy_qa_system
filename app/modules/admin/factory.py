from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine

from app.config import Settings
from app.infrastructure.database.repositories import AdminRepository, ManagementRepository
from app.infrastructure.database.session import create_database_runtime
from app.infrastructure.object_storage.minio import MinioObjectStorage

from .service import AdminService


@dataclass(slots=True)
class AdminRuntime:
    service: AdminService
    engine: Engine

    def close(self) -> None:
        self.engine.dispose()


def build_admin_runtime(settings: Settings) -> AdminRuntime:
    engine, session_factory = create_database_runtime(
        settings.database_url,
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
    )
    storage = MinioObjectStorage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key.get_secret_value(),
        secret_key=settings.minio_secret_key.get_secret_value(),
        secure=settings.minio_secure,
        region=settings.minio_region,
    )
    service = AdminService(
        admin_repository=AdminRepository(session_factory),
        management_repository=ManagementRepository(session_factory),
        object_storage=storage,
        object_bucket=settings.minio_documents_bucket,
        session_ttl_seconds=settings.admin_session_ttl_seconds,
        cookie_name=settings.admin_session_cookie_name,
        cookie_secure=settings.admin_cookie_secure,
        max_upload_bytes=settings.admin_max_upload_bytes,
        ingestion_max_attempts=settings.worker_max_attempts,
        evaluation_max_attempts=settings.evaluation_max_attempts,
        parser_version=settings.ingestion_parser_version,
        chunker_version=settings.ingestion_chunker_version,
        embedder_version=settings.embed_model_name,
        index_version=settings.ingestion_index_version,
    )

    username = settings.admin_bootstrap_username
    password = settings.admin_bootstrap_password
    if (username is None) != (password is None):
        engine.dispose()
        raise RuntimeError(
            "ADMIN_BOOTSTRAP_USERNAME and ADMIN_BOOTSTRAP_PASSWORD must be configured together"
        )
    if username is not None and password is not None:
        service.ensure_bootstrap_user(username, password.get_secret_value())

    return AdminRuntime(service=service, engine=engine)
