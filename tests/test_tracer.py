"""Tests for Tracer: decorator, span, parenting, failures and validation."""

from __future__ import annotations

import asyncio
import contextvars
import functools
import itertools
import threading
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest

from agent_tool_tracer import MemorySink, TraceEvent, Tracer, TracerError


class SeqClock:
    def __init__(self, values: list[float]) -> None:
        self._values: Iterator[float] = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def counter() -> Callable[[], str]:
    numbers = itertools.count(1)
    return lambda: str(next(numbers))


def make(**kwargs: Any) -> tuple[Tracer, MemorySink]:
    sink = MemorySink()
    options: dict[str, Any] = {
        "run_id": "run",
        "wall_clock": lambda: 1700000000.0,
        "id_factory": counter(),
    }
    options.update(kwargs)
    return Tracer(sink, **options), sink


def test_sync_and_async_tools_each_record_one_event() -> None:
    tracer, sink = make(clock=SeqClock([1.0, 1.25, 1.0, 1.25]))

    @tracer.trace_tool()
    def add(a: int, b: int = 2, *, scale: int = 1) -> int:
        return (a + b) * scale

    @tracer.trace_tool("fetch")
    async def fetch(url: str) -> dict[str, str]:
        return {"url": url}

    assert add(1, scale=3) == 9
    assert asyncio.run(fetch("u")) == {"url": "u"}
    first, second = sink.events
    assert first.tool == "add"
    assert first.args == {"a": 1, "b": 2, "scale": 3}
    assert first.result == 9
    assert first.status == "ok"
    assert first.duration_ms == 250.0
    assert first.error_type is None
    assert first.parent_id is None
    assert first.run_id == "run"
    assert first.call_id == "1"
    assert first.started_at == 1700000000.0
    assert first.tags == ()
    assert second.tool == "fetch"
    assert second.args == {"url": "u"}
    assert second.result == {"url": "u"}
    assert second.status == "ok"
    assert second.duration_ms == 250.0
    assert add.__name__ == "add"


def test_positional_arguments_are_bound_to_names() -> None:
    tracer, sink = make()

    @tracer.trace_tool()
    def add(a: int, b: int = 2, *rest: int, scale: int = 1, **extra: int) -> int:
        return (a + b) * scale

    add(5, 6, 7, scale=2, z=1)
    assert sink.events[0].args == {"a": 5, "b": 6, "rest": [7], "scale": 2, "extra": {"z": 1}}


def test_exception_is_recorded_without_message_and_reraised() -> None:
    tracer, sink = make()
    original = ValueError("super secret message")

    @tracer.trace_tool()
    def boom() -> None:
        raise original

    with pytest.raises(ValueError) as caught:
        boom()
    assert caught.value is original
    event = sink.events[0]
    assert event.status == "error"
    assert event.error_type == "ValueError"
    assert event.result is None
    assert "super secret message" not in repr(event)


def test_async_exception_is_recorded_and_reraised() -> None:
    tracer, sink = make()
    original = KeyError("hidden")

    @tracer.trace_tool()
    async def boom() -> None:
        raise original

    with pytest.raises(KeyError) as caught:
        asyncio.run(boom())
    assert caught.value is original
    assert sink.events[0].error_type == "KeyError"
    assert sink.events[0].status == "error"


def test_nested_call_records_parent_id() -> None:
    tracer, sink = make()

    @tracer.trace_tool()
    def inner() -> int:
        return 1

    @tracer.trace_tool()
    def outer() -> int:
        return inner() + inner()

    assert outer() == 2
    assert inner() == 1
    inner_events = [event for event in sink.events if event.tool == "inner"]
    outer_event = next(event for event in sink.events if event.tool == "outer")
    assert [event.parent_id for event in inner_events] == [
        outer_event.call_id,
        outer_event.call_id,
        None,
    ]
    assert outer_event.parent_id is None


def test_parent_id_survives_asyncio_gather() -> None:
    tracer, sink = make()

    @tracer.trace_tool()
    async def leaf(n: int) -> int:
        await asyncio.sleep(0)
        return n

    @tracer.trace_tool()
    async def root() -> list[int]:
        return list(await asyncio.gather(leaf(1), leaf(2)))

    assert asyncio.run(root()) == [1, 2]
    root_event = next(event for event in sink.events if event.tool == "root")
    leaves = [event for event in sink.events if event.tool == "leaf"]
    assert len(leaves) == 2
    assert all(event.parent_id == root_event.call_id for event in leaves)


def test_parent_id_across_thread_with_copied_context() -> None:
    tracer, sink = make()

    @tracer.trace_tool()
    def child() -> None:
        return None

    @tracer.trace_tool()
    def parent() -> None:
        context = contextvars.copy_context()
        thread = threading.Thread(target=context.run, args=(child,))
        thread.start()
        thread.join()

    parent()
    parent_event = next(event for event in sink.events if event.tool == "parent")
    child_event = next(event for event in sink.events if event.tool == "child")
    assert child_event.parent_id == parent_event.call_id


def test_other_tracers_do_not_leak_parents() -> None:
    first, _ = make()
    second, second_sink = make()

    @second.trace_tool()
    def inner() -> None:
        return None

    @first.trace_tool()
    def outer() -> None:
        inner()

    outer()
    assert second_sink.events[0].parent_id is None


def test_span_records_result_cost_and_args() -> None:
    tracer, sink = make(clock=SeqClock([1.0, 1.25]))
    with tracer.span("lookup", {"q": "x"}) as handle:
        handle.set_result({"rows": 3})
        handle.set_cost(Decimal("0.25"))
    event = sink.events[0]
    assert event.tool == "lookup"
    assert event.args == {"q": "x"}
    assert event.result == {"rows": 3}
    assert event.cost == "0.25"
    assert event.status == "ok"
    assert event.duration_ms == 250.0


def test_span_without_args_and_exception_inside_span() -> None:
    tracer, sink = make()
    with pytest.raises(KeyError), tracer.span("t") as handle:
        handle.set_result(1)
        raise KeyError("private detail")
    event = sink.events[0]
    assert event.args == {}
    assert event.status == "error"
    assert event.error_type == "KeyError"
    assert event.result is None
    assert "private detail" not in repr(event)


def test_span_validation() -> None:
    tracer, sink = make()
    with pytest.raises(TracerError) as caught, tracer.span(""):
        pass
    assert caught.value.code == "invalid_argument"
    with pytest.raises(TracerError), tracer.span(5):  # type: ignore[arg-type]
        pass
    with tracer.span("ok") as handle, pytest.raises(TracerError) as bad_cost:
        handle.set_cost(1.5)  # type: ignore[arg-type]
    assert bad_cost.value.code == "invalid_argument"
    assert len(sink.events) == 1


def test_span_finished_in_another_context_still_records() -> None:
    tracer, sink = make()
    manager = tracer.span("t")
    contextvars.copy_context().run(manager.__enter__)
    manager.__exit__(None, None, None)
    assert len(sink.events) == 1


def test_generator_functions_are_rejected_at_decoration() -> None:
    tracer, _ = make()

    def gen() -> Iterator[int]:
        yield 1

    async def agen() -> Any:
        yield 1

    with pytest.raises(TypeError):
        tracer.trace_tool()(gen)
    with pytest.raises(TypeError):
        tracer.trace_tool()(agen)


def test_invalid_tool_name() -> None:
    tracer, _ = make()
    with pytest.raises(TracerError) as caught:
        tracer.trace_tool(5)  # type: ignore[arg-type]
    assert caught.value.code == "invalid_argument"
    with pytest.raises(TracerError):
        tracer.trace_tool("")


def test_signature_mismatch_is_recorded_with_raw_arguments() -> None:
    tracer, sink = make()

    @tracer.trace_tool()
    def one(a: int) -> int:
        return a

    with pytest.raises(TypeError):
        one(1, 2)  # type: ignore[call-arg]
    event = sink.events[0]
    assert event.status == "error"
    assert event.error_type == "TypeError"
    assert event.args == {"args": [1, 2], "kwargs": {}}


def test_callable_without_signature_and_partial_names() -> None:
    tracer, sink = make()

    class Odd:
        __signature__ = "nope"

        def __call__(self, x: int) -> int:
            return x

    def add(a: int, b: int) -> int:
        return a + b

    wrapped = tracer.trace_tool("odd")(Odd())
    assert wrapped(4) == 4
    partial = tracer.trace_tool()(functools.partial(add, 1))
    assert partial(2) == 3
    assert sink.events[0].args == {"args": [4], "kwargs": {}}
    assert sink.events[1].tool == "partial"
    assert sink.events[1].args == {"b": 2}


def test_cost_callable_sets_cost_text() -> None:
    tracer, sink = make()

    @tracer.trace_tool(cost=lambda result: Decimal("0.5") * result)
    def work(n: int) -> int:
        return n

    work(3)
    assert sink.events[0].cost == "1.5"


def test_failing_or_invalid_cost_warns_and_keeps_result() -> None:
    tracer, sink = make()

    def broken(result: Any) -> Decimal:
        raise RuntimeError("cost detail")

    @tracer.trace_tool(cost=broken)
    def first() -> int:
        return 1

    @tracer.trace_tool(cost=lambda result: 1.5)  # type: ignore[arg-type, return-value]
    def second() -> int:
        return 2

    with pytest.warns(RuntimeWarning) as record:
        assert first() == 1
        assert second() == 2
    assert len(record) == 2
    assert "RuntimeError" in str(record[0].message)
    assert "cost detail" not in str(record[0].message)
    assert [event.cost for event in sink.events] == [None, None]


def test_failing_sink_warns_once_and_returns_result() -> None:
    def broken(event: TraceEvent) -> None:
        raise RuntimeError("sink detail")

    tracer = Tracer(broken)

    @tracer.trace_tool()
    def work() -> int:
        return 7

    with pytest.warns(RuntimeWarning) as record:
        assert work() == 7
    assert len(record) == 1
    assert "RuntimeError" in str(record[0].message)
    assert "sink detail" not in str(record[0].message)


def test_failing_sink_does_not_mask_tool_exception() -> None:
    def broken(event: TraceEvent) -> None:
        raise RuntimeError("sink detail")

    tracer = Tracer(broken)
    original = ValueError("tool failed")

    @tracer.trace_tool()
    def work() -> None:
        raise original

    with pytest.warns(RuntimeWarning) as record, pytest.raises(ValueError) as caught:
        work()
    assert caught.value is original
    assert len(record) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_value_chars": 15},
        {"max_value_chars": True},
        {"max_depth": 0},
        {"max_depth": 257},
        {"redact_keys": "token"},
        {"redact_keys": ("",)},
        {"redact_keys": (5,)},
        {"run_id": 5},
    ],
)
def test_invalid_constructor_arguments(kwargs: dict[str, Any]) -> None:
    with pytest.raises(TracerError) as caught:
        Tracer(MemorySink(), **kwargs)
    assert caught.value.code == "invalid_argument"


def test_non_callable_sink_is_rejected() -> None:
    with pytest.raises(TracerError) as caught:
        Tracer("nope")  # type: ignore[arg-type]
    assert caught.value.code == "invalid_argument"


def test_minimum_max_value_chars_is_accepted() -> None:
    Tracer(MemorySink(), max_value_chars=16)


def test_default_ids_and_clocks() -> None:
    sink = MemorySink()
    tracer = Tracer(sink)

    @tracer.trace_tool()
    def work() -> int:
        return 1

    work()
    work()
    first, second = sink.events
    assert len(tracer.run_id) == 32
    assert first.run_id == second.run_id == tracer.run_id
    assert len(first.call_id) == 32
    assert first.call_id != second.call_id
    assert first.duration_ms >= 0.0
    assert first.started_at > 0.0


def test_run_id_defaults_to_id_factory() -> None:
    tracer, sink = make(run_id=None)
    assert tracer.run_id == "1"

    @tracer.trace_tool()
    def work() -> None:
        return None

    work()
    assert sink.events[0].call_id == "2"
