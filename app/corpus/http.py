"""Bounded, HTTPS-only HTTP transport with retry and atomic streaming."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.corpus.models import DownloadResult, HttpRequestError, UrlSecurityError


class Transport(Protocol):
    """Small seam used by unit tests to avoid all network access."""

    def open(self, request: urllib.request.Request, timeout: float) -> Any: ...


class _RetrySignal(Exception):
    def __init__(self, error: HttpRequestError, retry_after: float | None = None) -> None:
        super().__init__(str(error))
        self.error = error
        self.retry_after = retry_after


def validate_https_url(url: str, allowed_hosts: frozenset[str]) -> str:
    """Return a normalized host or reject credentials, HTTP, and unknown hosts."""

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UrlSecurityError("malformed request URL", code="invalid_url") from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https":
        raise UrlSecurityError("only HTTPS corpus requests are allowed", code="non_https_url")
    if not host or host not in allowed_hosts:
        raise UrlSecurityError("request host is not allowlisted", code="host_not_allowed")
    if parsed.username or parsed.password:
        raise UrlSecurityError("URL credentials are forbidden", code="url_credentials_forbidden")
    if port not in (None, 443):
        raise UrlSecurityError("only the standard HTTPS port is allowed", code="port_not_allowed")
    if parsed.fragment:
        raise UrlSecurityError("request URL fragments are forbidden", code="url_fragment_forbidden")
    return host


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str]) -> None:
        super().__init__()
        self._allowed_hosts = allowed_hosts

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Any:
        validate_https_url(newurl, self._allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibTransport:
    """Production transport with redirect checks before urllib follows a hop."""

    def __init__(self, allowed_redirect_hosts: frozenset[str]) -> None:
        self._opener = urllib.request.build_opener(
            _ValidatingRedirectHandler(allowed_redirect_hosts)
        )

    def open(self, request: urllib.request.Request, timeout: float) -> Any:
        return self._opener.open(request, timeout=timeout)


class SafeHttpClient:
    """Rate-limited GET client implementing bounded retry and stream limits."""

    _NETWORK_EXCEPTIONS = (
        urllib.error.URLError,
        TimeoutError,
        ConnectionError,
        http.client.IncompleteRead,
    )

    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str],
        allowed_redirect_hosts: frozenset[str],
        user_agent: str,
        requests_per_second: float,
        timeout_seconds: float,
        max_response_bytes: int,
        chunk_bytes: int,
        max_retries: int,
        backoff_base_seconds: float,
        backoff_max_seconds: float,
        jitter_seconds: float,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("user_agent cannot be empty")
        self.allowed_hosts = allowed_hosts
        self.allowed_redirect_hosts = allowed_redirect_hosts
        self.user_agent = user_agent.strip()
        self.requests_per_second = requests_per_second
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.chunk_bytes = chunk_bytes
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self.jitter_seconds = jitter_seconds
        self.transport = transport or UrllibTransport(allowed_redirect_hosts)
        self._sleep = sleep
        self._monotonic = monotonic
        self._random_value = random_value
        self._last_request_started: float | None = None

    def get_json(self, url: str) -> dict[str, Any]:
        payload = self.get_bytes(url)
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpRequestError(
                "REST response is not valid UTF-8 JSON",
                code="invalid_json_response",
            ) from exc
        if not isinstance(parsed, dict):
            raise HttpRequestError(
                "REST JSON response root must be an object",
                code="invalid_json_response",
            )
        return parsed

    def get_bytes(self, url: str) -> bytes:
        validate_https_url(url, self.allowed_hosts)

        def operation() -> bytes:
            response = self._open_once(url)
            try:
                self._reject_oversized_content_length(response)
                chunks: list[bytes] = []
                size = 0
                while True:
                    try:
                        chunk = response.read(self.chunk_bytes)
                    except self._NETWORK_EXCEPTIONS as exc:
                        raise self._network_retry(exc) from exc
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_response_bytes:
                        raise HttpRequestError(
                            "response exceeded configured byte limit",
                            code="response_too_large",
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
            finally:
                response.close()

        return self._with_retries(operation)

    def download_atomic(self, url: str, destination: Path) -> DownloadResult:
        """Stream to ``<destination>.part`` and rename only after full success."""

        validate_https_url(url, self.allowed_hosts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        part_path = destination.with_name(f"{destination.name}.part")
        part_path.unlink(missing_ok=True)

        def operation() -> DownloadResult:
            response = self._open_once(url)
            final_url = self._response_url(response, url)
            digest = hashlib.sha256()
            size = 0
            try:
                self._reject_oversized_content_length(response)
                try:
                    output = part_path.open("wb")
                except OSError as exc:
                    raise HttpRequestError(
                        "cannot create download part file",
                        code="part_file_open_failed",
                    ) from exc
                with output:
                    while True:
                        try:
                            chunk = response.read(self.chunk_bytes)
                        except self._NETWORK_EXCEPTIONS as exc:
                            raise self._network_retry(exc) from exc
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > self.max_response_bytes:
                            raise HttpRequestError(
                                "full text exceeded configured byte limit",
                                code="response_too_large",
                            )
                        try:
                            output.write(chunk)
                        except OSError as exc:
                            raise HttpRequestError(
                                "cannot write download part file",
                                code="part_file_write_failed",
                            ) from exc
                        digest.update(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(part_path, destination)
                return DownloadResult(size=size, sha256=digest.hexdigest(), final_url=final_url)
            except Exception:
                part_path.unlink(missing_ok=True)
                raise
            finally:
                response.close()

        try:
            return self._with_retries(operation)
        except Exception:
            part_path.unlink(missing_ok=True)
            raise

    def _open_once(self, url: str) -> Any:
        self._throttle()
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, application/xml;q=0.9, text/xml;q=0.9",
                "User-Agent": self.user_agent,
            },
            method="GET",
        )
        try:
            response = self.transport.open(request, timeout=self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            retry_after = self._retry_after(exc.headers)
            status = int(exc.code)
            exc.close()
            self._raise_for_status(status, retry_after)
            raise AssertionError("unreachable") from exc
        except self._NETWORK_EXCEPTIONS as exc:
            raise self._network_retry(exc) from exc

        status = self._response_status(response)
        if not 200 <= status < 300:
            retry_after = self._retry_after(getattr(response, "headers", None))
            response.close()
            self._raise_for_status(status, retry_after)
        try:
            self._validate_final_url(url, self._response_url(response, url))
        except Exception:
            response.close()
            raise
        return response

    def _with_retries(self, operation: Callable[[], Any]) -> Any:
        for attempt in range(self.max_retries + 1):
            try:
                return operation()
            except _RetrySignal as signal:
                if attempt >= self.max_retries:
                    error = signal.error
                    raise HttpRequestError(
                        "retry budget exhausted",
                        code="http_retry_exhausted",
                        status=error.status,
                        retryable=True,
                    ) from error
                delay = signal.retry_after
                if delay is None:
                    delay = min(
                        self.backoff_base_seconds * (2**attempt),
                        self.backoff_max_seconds,
                    )
                    delay += self._random_value() * self.jitter_seconds
                self._sleep(max(0.0, min(delay, self.backoff_max_seconds)))
        raise AssertionError("retry loop must return or raise")

    def _raise_for_status(self, status: int, retry_after: float | None) -> None:
        if status in {408, 429} or 500 <= status <= 599:
            error = HttpRequestError(
                f"retryable HTTP status {status}",
                code=f"http_{status}",
                status=status,
                retryable=True,
            )
            raise _RetrySignal(error, retry_after if status == 429 else None)
        raise HttpRequestError(
            f"permanent HTTP status {status}",
            code=f"http_{status}",
            status=status,
        )

    def _network_retry(self, exc: BaseException) -> _RetrySignal:
        error = HttpRequestError(
            f"transient network failure: {type(exc).__name__}",
            code="network_error",
            retryable=True,
        )
        return _RetrySignal(error)

    def _throttle(self) -> None:
        interval = 1.0 / self.requests_per_second
        now = self._monotonic()
        if self._last_request_started is not None:
            remaining = self._last_request_started + interval - now
            if remaining > 0:
                self._sleep(remaining)
                now = self._monotonic()
        self._last_request_started = now

    def _validate_final_url(self, original_url: str, final_url: str) -> None:
        original_host = validate_https_url(original_url, self.allowed_hosts)
        final_allowed = self.allowed_hosts | self.allowed_redirect_hosts
        final_host = validate_https_url(final_url, final_allowed)
        if final_host != original_host and final_host not in self.allowed_redirect_hosts:
            raise UrlSecurityError(
                "redirect final host is not allowlisted",
                code="redirect_host_not_allowed",
            )

    def _reject_oversized_content_length(self, response: Any) -> None:
        value = self._header(getattr(response, "headers", None), "Content-Length")
        if value is None:
            return
        try:
            length = int(value)
        except (TypeError, ValueError):
            return
        if length > self.max_response_bytes:
            raise HttpRequestError(
                "declared response size exceeds configured byte limit",
                code="response_too_large",
            )

    @staticmethod
    def _response_status(response: Any) -> int:
        status = getattr(response, "status", None)
        if status is None:
            getter = getattr(response, "getcode", None)
            status = getter() if callable(getter) else None
        if not isinstance(status, int):
            raise HttpRequestError("response has no HTTP status", code="invalid_http_response")
        return status

    @staticmethod
    def _response_url(response: Any, fallback: str) -> str:
        getter = getattr(response, "geturl", None)
        value = getter() if callable(getter) else fallback
        return value if isinstance(value, str) else fallback

    @staticmethod
    def _header(headers: Any, name: str) -> str | None:
        if headers is None:
            return None
        if isinstance(headers, Mapping):
            value = headers.get(name) or headers.get(name.lower())
        else:
            getter = getattr(headers, "get", None)
            value = getter(name) if callable(getter) else None
        return str(value) if value is not None else None

    @classmethod
    def _retry_after(cls, headers: Any) -> float | None:
        value = cls._header(headers, "Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                when = parsedate_to_datetime(value)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
                return max(0.0, (when - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None
