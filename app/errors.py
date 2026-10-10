from typing import Any


class AppError(Exception):
    """An error with a stable machine-readable code, rendered as the API error envelope."""

    status_code: int = 400
    code: str = "BAD_REQUEST"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvalidFileError(AppError):
    status_code = 400
    code = "INVALID_FILE"


class FileTooLargeError(AppError):
    status_code = 413
    code = "FILE_TOO_LARGE"


class UnsupportedFileTypeError(AppError):
    status_code = 415
    code = "UNSUPPORTED_FILE_TYPE"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class FileNotReadyError(AppError):
    status_code = 409
    code = "FILE_NOT_READY"


class ProcessingFailedError(AppError):
    status_code = 422
    code = "PROCESSING_FAILED"


class DatasetError(Exception):
    """The upload was accepted but its contents cannot be processed; the file is marked FAILED."""
