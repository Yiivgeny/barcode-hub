from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def response_body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class MethodDisabledError(AppError):
    status_code = 405
    code = "method_disabled"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedMediaTypeError(AppError):
    status_code = 415
    code = "unsupported_media_type"


class UnprocessableContentError(AppError):
    status_code = 422
    code = "unprocessable_content"


class ResourceTimeoutError(AppError):
    status_code = 504
    code = "resource_timeout"


class InternalServiceError(AppError):
    status_code = 500
    code = "internal_error"


def ensure_decode_method_enabled(method: str, enabled_methods: list[str]) -> None:
    if method.upper() not in {item.upper() for item in enabled_methods}:
        raise MethodDisabledError("This decode method is disabled.")

