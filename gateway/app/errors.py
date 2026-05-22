"""OpenAI-style error helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def error_body(
    message: str,
    *,
    error_type: str = "server_error",
    code: str | None = None,
    param: str | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        "error": {
            "message": message,
            "type": error_type,
            "code": code,
            "param": param,
        }
    }


@dataclass
class AppError(RuntimeError):
    message: str
    status_code: int = 500
    error_type: str = "server_error"
    code: str | None = None
    param: str | None = None

    def __str__(self) -> str:
        return self.message

    def body(self) -> dict[str, dict[str, Any]]:
        return error_body(
            self.message,
            error_type=self.error_type,
            code=self.code,
            param=self.param,
        )
