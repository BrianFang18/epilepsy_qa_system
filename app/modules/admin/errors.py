from __future__ import annotations


class AdminError(Exception):
    """Base class for expected admin application errors."""


class AuthenticationFailed(AdminError):
    pass


class AdminNotFound(AdminError):
    pass


class AdminConflict(AdminError):
    pass


class UploadRejected(AdminError):
    def __init__(self, detail: str, *, status_code: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
