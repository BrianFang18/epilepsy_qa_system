FROM python:3.11.11-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv

RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv "${VIRTUAL_ENV}"

ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
WORKDIR /build

COPY pyproject.toml requirements.txt ./
COPY app ./app

# requirements.txt deliberately installs .[runtime]. The shared API/worker/migrate
# image therefore contains Qdrant, LLM, embedding, and parser dependencies; the
# model-dependent worker is still opt-in at Compose runtime. Validate the resolved
# environment before removing installers that are unnecessary in the final image.
RUN python -m pip install \
        "pip==26.2.1" \
        "setuptools==84.0.0" \
        "wheel==0.48.0" \
    && python -m pip install --requirement requirements.txt \
    && python -m pip check \
    && python -m pip uninstall --yes pip wheel

FROM python:3.11.11-slim-bookworm AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/home/appuser \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libgomp supports the CPU model runtime. The parser has a pypdf fallback, while
# poppler/tesseract keep the declared document runtime usable without curl.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        libglib2.0-0 \
        libgomp1 \
        poppler-utils \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid appuser --create-home --shell /usr/sbin/nologin appuser

WORKDIR /srv/app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser alembic.ini ./alembic.ini

# Compose supplies PostgreSQL bootstrap components to the shared image. Build a
# correctly escaped SQLAlchemy URL before importing Settings in every role.
COPY --chmod=0555 <<PY /opt/container/with-database-url
#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from urllib.parse import quote


def main() -> None:
    if not os.environ.get("DATABASE_URL"):
        names = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise SystemExit(f"missing database environment variables: {', '.join(missing)}")
        user = quote(os.environ["POSTGRES_USER"], safe="")
        password = quote(os.environ["POSTGRES_PASSWORD"], safe="")
        database = quote(os.environ["POSTGRES_DB"], safe="")
        os.environ["DATABASE_URL"] = (
            f"postgresql+psycopg://{user}:{password}@postgres:5432/{database}"
        )
    if len(sys.argv) < 2:
        raise SystemExit("with-database-url requires a command")
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
PY

# app.main's legacy LLM honors MOCK_MODE, while its streaming chat adapter does
# not. This container-only bridge injects that existing deterministic mock into
# the stream port so the development API needs no fabricated provider key.
COPY --chmod=0555 <<PY /opt/container/serve-existing-mock
#!/usr/bin/env python3
from __future__ import annotations


class ExistingMockStreamPort:
    def __init__(self, client: object) -> None:
        self._client = client

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ):
        yield self._client.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def close(self) -> None:
        return None


def main() -> None:
    import uvicorn

    from app.config import get_settings
    from app.llm.llm_client import LLMClient
    from app.main import create_app

    settings = get_settings()
    if not settings.mock_mode:
        raise RuntimeError(
            "the default container API requires MOCK_MODE=true; use app.main:app only "
            "when a real streaming LLM provider is configured"
        )
    llm = ExistingMockStreamPort(LLMClient(settings))
    application = create_app(settings=settings, llm=llm)
    uvicorn.run(application, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
PY

USER appuser

EXPOSE 8010
STOPSIGNAL SIGTERM

CMD ["/opt/container/with-database-url", "/opt/container/serve-existing-mock"]
