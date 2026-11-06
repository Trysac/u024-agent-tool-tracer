"""Tracer: records tool calls made through a decorator or a context manager."""

from __future__ import annotations

import functools
import inspect
import logging
import time
import uuid
import warnings
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, TypeVar, cast

from .errors import TracerError, require_int
from .model import TraceEvent
from .serialize import DEFAULT_REDACT_KEYS, Sanitizer

__all__ = ["SpanHandle", "Tracer"]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

F = TypeVar("F", bound=Callable[..., Any])

_CURRENT: ContextVar[tuple[Tracer, str] | None] = ContextVar("att_current", default=None)


@dataclass(frozen=True, slots=True)
class _Call:
    tool: str
    call_id: str
    parent_id: str | None
    started_at: float
    t0: float
    token: Token[tuple[Tracer, str] | None]


def _uuid_hex() -> str:
    return uuid.uuid4().hex


def _default_name(fn: Any) -> str:
    return str(getattr(fn, "__name__", type(fn).__name__))


def _bind(
    signature: inspect.Signature | None, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Map call arguments to parameter names, falling back to raw args and kwargs."""
    if signature is not None:
        try:
            bound = signature.bind(*args, **kwargs)
        except TypeError:
            logger.debug("call arguments do not match the tool signature")
        else:
            bound.apply_defaults()
            arguments = dict(bound.arguments)
            first = next(iter(signature.parameters), None)
            if first in ("self", "cls"):
                # The receiver's repr may contain credentials that key redaction cannot see.
                arguments.pop(first, None)
            return arguments
    return {"args": list(args), "kwargs": dict(kwargs)}


class SpanHandle:
    """Handle yielded by :meth:`Tracer.span` to attach a result and a cost."""

    __slots__ = ("_cost", "_result")

    def __init__(self) -> None:
        self._result: Any = None
        self._cost: str | None = None

    def set_result(self, value: Any) -> None:
        """Record the result of the span."""
        self._result = value

    def set_cost(self, value: Decimal) -> None:
        """Record the cost of the span; ``value`` must be a ``Decimal``."""
        if not isinstance(value, Decimal):
            raise TracerError("cost must be a Decimal", "invalid_argument")
        self._cost = str(value)


class Tracer:
    """Records every tool call to a sink as a redacted, bounded :class:`TraceEvent`.

    Parent tracking uses ``contextvars``: it works for asyncio tasks and for threads started
    with a copied context. A failing sink never breaks the tool; it emits one
    ``RuntimeWarning`` that names only the exception type.
    """

    def __init__(
        self,
        sink: Callable[[TraceEvent], None],
        *,
        run_id: str | None = None,
        clock: Callable[[], float] = time.perf_counter,
        wall_clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] | None = None,
        redact_keys: Sequence[str] = DEFAULT_REDACT_KEYS,
        max_value_chars: int = 2000,
        max_depth: int = 32,
    ) -> None:
        if not callable(sink):
            raise TracerError("sink must be callable", "invalid_argument")
        max_chars = require_int(max_value_chars, "max_value_chars", 16)
        depth = require_int(max_depth, "max_depth", 1, 256)
        if isinstance(redact_keys, str) or not all(
            isinstance(key, str) and key for key in redact_keys
        ):
            raise TracerError("redact_keys must be non-empty strings", "invalid_argument")
        if run_id is not None and not isinstance(run_id, str):
            raise TracerError("run_id must be a string", "invalid_argument")
        self._sink = sink
        self._clock = clock
        self._wall_clock = wall_clock
        self._id_factory = id_factory if id_factory is not None else _uuid_hex
        self._run_id = run_id if run_id is not None else self._id_factory()
        self._sanitizer = Sanitizer(tuple(redact_keys), max_chars, depth)

    @property
    def run_id(self) -> str:
        """Identifier shared by every event of this tracer."""
        return self._run_id

    def trace_tool(
        self,
        name: str | None = None,
        *,
        cost: Callable[[Any], Decimal] | None = None,
    ) -> Callable[[F], F]:
        """Return a decorator that traces a sync or async function.

        Args:
            name: Tool name; defaults to the function name.
            cost: Optional callable computing a ``Decimal`` cost from the result.

        Raises:
            TracerError: ``invalid_argument`` if ``name`` is not a non-empty string.
            TypeError: at decoration time for generator and async generator functions.
        """
        if name is not None and (not isinstance(name, str) or not name):
            raise TracerError("name must be a non-empty string", "invalid_argument")

        def decorator(fn: F) -> F:
            if inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn):
                raise TypeError("generator functions cannot be traced")
            tool = name if name is not None else _default_name(fn)
            try:
                signature: inspect.Signature | None = inspect.signature(fn)
            except (TypeError, ValueError):
                signature = None
            if inspect.iscoroutinefunction(fn):
                return cast(F, self._wrap_async(fn, tool, signature, cost))
            return cast(F, self._wrap_sync(fn, tool, signature, cost))

        return decorator

    @contextmanager
    def span(self, tool: str, args: Mapping[str, Any] | None = None) -> Iterator[SpanHandle]:
        """Context manager recording one call named ``tool``.

        An exception raised inside the block is recorded as an error and re-raised.
        """
        if not isinstance(tool, str) or not tool:
            raise TracerError("tool must be a non-empty string", "invalid_argument")
        handle = SpanHandle()
        recorded: dict[Any, Any] = dict(args) if args is not None else {}
        call = self._begin(tool)
        try:
            yield handle
        except BaseException as exc:
            self._end(call, recorded, None, "error", type(exc).__name__, None)
            raise
        self._end(call, recorded, handle._result, "ok", None, handle._cost)

    def _wrap_sync(
        self,
        fn: Callable[..., Any],
        tool: str,
        signature: inspect.Signature | None,
        cost: Callable[[Any], Decimal] | None,
    ) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = _bind(signature, args, kwargs)
            call = self._begin(tool)
            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                self._end(call, bound, None, "error", type(exc).__name__, None)
                raise
            cost_text = self._cost_text(cost, result)
            self._end(call, bound, result, "ok", None, cost_text)
            return result

        return wrapper

    def _wrap_async(
        self,
        fn: Callable[..., Any],
        tool: str,
        signature: inspect.Signature | None,
        cost: Callable[[Any], Decimal] | None,
    ) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = _bind(signature, args, kwargs)
            call = self._begin(tool)
            try:
                result = await fn(*args, **kwargs)
            except BaseException as exc:
                self._end(call, bound, None, "error", type(exc).__name__, None)
                raise
            cost_text = self._cost_text(cost, result)
            self._end(call, bound, result, "ok", None, cost_text)
            return result

        return wrapper

    @staticmethod
    def _cost_text(cost: Callable[[Any], Decimal] | None, result: Any) -> str | None:
        if cost is None:
            return None
        try:
            value = cost(result)
            if not isinstance(value, Decimal):
                raise TypeError("cost must be a Decimal")
        except Exception as exc:
            warnings.warn(
                f"cost function failed: {type(exc).__name__}",
                RuntimeWarning,
                stacklevel=3,
            )
            return None
        return str(value)

    def _begin(self, tool: str) -> _Call:
        current = _CURRENT.get()
        parent_id = current[1] if current is not None and current[0] is self else None
        call_id = self._id_factory()
        started_at = float(self._wall_clock())
        t0 = self._clock()
        token = _CURRENT.set((self, call_id))
        return _Call(tool, call_id, parent_id, started_at, t0, token)

    def _end(
        self,
        call: _Call,
        args: Mapping[Any, Any],
        result: Any,
        status: Literal["ok", "error"],
        error_type: str | None,
        cost: str | None,
    ) -> None:
        duration_ms = (self._clock() - call.t0) * 1000.0
        try:
            _CURRENT.reset(call.token)
        except ValueError:
            logger.debug("trace context was finished in a different context")
        try:
            event = TraceEvent(
                run_id=self._run_id,
                call_id=call.call_id,
                parent_id=call.parent_id,
                tool=call.tool,
                started_at=call.started_at,
                duration_ms=float(duration_ms),
                status=status,
                args=self._sanitizer.mapping(args),
                result=self._sanitizer.value(result),
                error_type=error_type,
                cost=cost,
                tags=(),
            )
            self._sink(event)
        except Exception as exc:
            warnings.warn(
                f"trace sink failed: {type(exc).__name__}",
                RuntimeWarning,
                stacklevel=3,
            )
