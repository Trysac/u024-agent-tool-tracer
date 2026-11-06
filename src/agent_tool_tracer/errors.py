"""Typed errors raised by agent_tool_tracer."""

from __future__ import annotations

from typing import Literal

__all__ = ["ErrorCode", "TracerError", "require_int"]

ErrorCode = Literal["trace_format", "invalid_argument"]

_MAX_MESSAGE_CHARS = 200


class TracerError(ValueError):
    """Base error of the library.

    Attributes:
        code: Stable machine-readable error code.
        line: One-based line number for ``trace_format`` errors, otherwise ``None``.
    """

    def __init__(self, message: str, code: ErrorCode, *, line: int | None = None) -> None:
        super().__init__(message[:_MAX_MESSAGE_CHARS])
        self.code: ErrorCode = code
        self.line: int | None = line


def require_int(value: object, name: str, minimum: int, maximum: int | None = None) -> int:
    """Return ``value`` if it is an int within bounds, else raise ``invalid_argument``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TracerError(f"{name} must be an integer", "invalid_argument")
    if value < minimum or (maximum is not None and value > maximum):
        raise TracerError(f"{name} is out of range", "invalid_argument")
    return value
