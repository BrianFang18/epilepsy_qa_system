from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class ObjectStorage(Protocol):
    def put_bytes(
        self,
        *,
        bucket: str,
        object_key: str,
        data: bytes,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> None: ...

    def download_file(self, *, bucket: str, object_key: str, destination: str) -> None: ...

    def delete_object(self, *, bucket: str, object_key: str) -> None: ...

    def healthcheck(self, bucket: str) -> bool: ...
