from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

SessionFactory = Callable[[], Session]


def create_database_runtime(
    database_url: str,
    *,
    echo: bool = False,
    pool_size: int = 5,
) -> tuple[Engine, sessionmaker[Session]]:
    """Create a lazy SQLAlchemy engine and a non-expiring session factory."""
    options: dict[str, Any] = {
        "echo": echo,
        "future": True,
        "pool_pre_ping": True,
    }
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            options["poolclass"] = StaticPool
    else:
        options["pool_size"] = pool_size

    engine = create_engine(database_url, **options)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return engine, factory
