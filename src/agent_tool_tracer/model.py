"""The TraceEvent record and its JSON mapping."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from .errors import TracerError

__all__ = ["TraceEvent", "event_from_obj", "event_to_dict"]

_REQUIRED_FIELDS = (
    "run_id",
    "call_id",
    "parent_id",
    "tool",
    "started_at",
    "duration_ms",
    "status",
    "args",
    "result",
    "error_type",
    "cost",
    "tags",
)


@dataclass(frozen=True)
class TraceEvent:
    """One recorded tool call.

    Attributes:
        run_id: Identifier shared by all events of one tracer.
        call_id: Unique identifier of the call.
        parent_id: ``call_id`` of the enclosing call, if any.
        tool: Tool name.
        started_at: Wall clock start time in seconds.
        duration_ms: Duration in milliseconds measured with the monotonic clock.
        status: ``"ok"`` or ``"error"``.
        args: Redacted, JSON-safe arguments keyed by parameter name.
        result: Redacted, JSON-safe result (``None`` for failed calls).
        error_type: Exception class name for failed calls; the message is never stored.
        cost: Decimal cost as a string, if reported.
        tags: Free-form tags.
    """

    run_id: str
    call_id: str
    parent_id: str | None
    tool: str
    started_at: float
    duration_ms: float
    status: Literal["ok", "error"]
    args: dict[str, Any]
    result: Any
    error_type: str | None = None
    cost: str | None = None
    tags: tuple[str, ...] = ()


def event_to_dict(event: TraceEvent) -> dict[str, Any]:
    """Return the JSON-ready mapping of an event."""
    return {
        "run_id": event.run_id,
        "call_id": event.call_id,
        "parent_id": event.parent_id,
        "tool": event.tool,
        "started_at": event.started_at,
        "duration_ms": event.duration_ms,
        "status": event.status,
        "args": event.args,
        "result": event.result,
        "error_type": event.error_type,
        "cost": event.cost,
        "tags": list(event.tags),
    }


def _bad(message: str, line: int) -> TracerError:
    return TracerError(message, "trace_format", line=line)


def _text(obj: dict[str, Any], name: str, line: int) -> str:
    value = obj[name]
    if not isinstance(value, str):
        raise _bad(f"field '{name}' must be a string", line)
    return value


def _optional_text(obj: dict[str, Any], name: str, line: int) -> str | None:
    if obj[name] is None:
        return None
    return _text(obj, name, line)


def _number(obj: dict[str, Any], name: str, line: int) -> float:
    value = obj[name]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _bad(f"field '{name}' must be a number", line)
    try:
        number = float(value)
    except OverflowError:
        raise _bad(f"field '{name}' is out of range", line) from None
    if not math.isfinite(number):
        raise _bad(f"field '{name}' must be finite", line)
    return number


def event_from_obj(obj: Any, line: int) -> TraceEvent:
    """Validate a decoded JSON value and build an event, raising ``trace_format``."""
    if not isinstance(obj, dict):
        raise _bad("trace line is not a JSON object", line)
    for name in _REQUIRED_FIELDS:
        if name not in obj:
            raise _bad(f"missing field '{name}'", line)
    status_raw = obj["status"]
    if status_raw not in ("ok", "error"):
        raise _bad("field 'status' must be 'ok' or 'error'", line)
    status: Literal["ok", "error"] = "ok" if status_raw == "ok" else "error"
    args = obj["args"]
    if not isinstance(args, dict):
        raise _bad("field 'args' must be an object", line)
    tags = obj["tags"]
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise _bad("field 'tags' must be a list of strings", line)
    return TraceEvent(
        run_id=_text(obj, "run_id", line),
        call_id=_text(obj, "call_id", line),
        parent_id=_optional_text(obj, "parent_id", line),
        tool=_text(obj, "tool", line),
        started_at=_number(obj, "started_at", line),
        duration_ms=_number(obj, "duration_ms", line),
        status=status,
        args=args,
        result=obj["result"],
        error_type=_optional_text(obj, "error_type", line),
        cost=_optional_text(obj, "cost", line),
        tags=tuple(tags),
    )
