from __future__ import annotations

from collections.abc import Mapping
from io import BytesIO
from threading import Lock

from minio import Minio


class MinioObjectStorage:
    """Small synchronous MinIO adapter; network access occurs only per method call."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool,
        region: str | None = None,
    ) -> None:
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
        )
        self._bucket_lock = Lock()
        self._known_buckets: set[str] = set()

    def _ensure_bucket(self, bucket: str) -> None:
        if bucket in self._known_buckets:
            return
        with self._bucket_lock:
            if bucket in self._known_buckets:
                return
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)
            self._known_buckets.add(bucket)

    def put_bytes(
        self,
        *,
        bucket: str,
        object_key: str,
        data: bytes,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        self._ensure_bucket(bucket)
        self._client.put_object(
            bucket,
            object_key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
            metadata=dict(metadata or {}),
        )

    def download_file(self, *, bucket: str, object_key: str, destination: str) -> None:
        self._client.fget_object(bucket, object_key, destination)

    def delete_object(self, *, bucket: str, object_key: str) -> None:
        self._client.remove_object(bucket, object_key)

    def healthcheck(self, bucket: str) -> bool:
        return self._client.bucket_exists(bucket)
