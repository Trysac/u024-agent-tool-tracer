"""Tests for MemorySink, JsonlSink and read_trace."""

from __future__ import annotations

import dataclasses
import itertools
import json
import warnings
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from agent_tool_tracer import JsonlSink, MemorySink, TraceEvent, Tracer, TracerError, read_trace

NL = chr(10)

BASE: dict[str, Any] = {
    "run_id": "r",
    "call_id": "1",
    "parent_id": None,
    "tool": "t",
    "started_at": 1.0,
    "duration_ms": 2.0,
    "status": "ok",
    "args": {},
    "result": None,
    "error_type": None,
    "cost": None,
    "tags": [],
}


def make_event(**changes: Any) -> TraceEvent:
    base = TraceEvent(
        run_id="r",
        call_id="1",
        parent_id=None,
        tool="t",
        started_at=1.0,
        duration_ms=2.0,
        status="ok",
        args={"a": 1},
        result="done",
        error_type=None,
        cost=None,
        tags=(),
    )
    return dataclasses.replace(base, **changes)


def line_for(**changes: Any) -> str:
    data = dict(BASE)
    data.update(changes)
    return json.dumps(data)


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text(NL.join(lines) + NL, encoding="utf-8")


def counter() -> Callable[[], str]:
    numbers = itertools.count(1)
    return lambda: str(next(numbers))


def test_memory_sink_keeps_the_last_events() -> None:
    sink = MemorySink(max_events=2)
    events = [make_event(call_id=str(index)) for index in range(3)]
    for event in events:
        sink(event)
    assert sink.events == events[1:]
    assert sink.dropped == 1


def test_memory_sink_events_is_a_copy() -> None:
    sink = MemorySink()
    sink(make_event())
    sink.events.clear()
    assert len(sink.events) == 1
    assert sink.dropped == 0


@pytest.mark.parametrize("value", [0, -1, True, "x"])
def test_memory_sink_rejects_bad_limits(value: Any) -> None:
    with pytest.raises(TracerError) as caught:
        MemorySink(max_events=value)
    assert caught.value.code == "invalid_argument"


def test_jsonl_round_trip_equals_events(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    memory = MemorySink()
    jsonl = JsonlSink(path)

    def both(event: TraceEvent) -> None:
        memory(event)
        jsonl(event)

    tracer = Tracer(both, run_id="run", id_factory=counter(), wall_clock=lambda: 1700000000.5)

    @tracer.trace_tool(cost=lambda result: Decimal("0.5"))
    def child(x: int) -> dict[str, Any]:
        return {"v": [x, "caf" + chr(233)], "t": (1, 2)}

    @tracer.trace_tool()
    def parent() -> None:
        child(1)
        raise ValueError("x")

    with pytest.raises(ValueError):
        parent()
    assert read_trace(path) == memory.events
    assert len(memory.events) == 2
    assert jsonl.dropped == 0
    assert path.read_text(encoding="utf-8").count(NL) == 2


def test_jsonl_sink_accepts_string_paths(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    JsonlSink(str(path))(make_event())
    assert read_trace(str(path)) == [make_event()]


def test_corrupt_line_two_raises_trace_format(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    JsonlSink(path)(make_event())
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json" + NL)
    with pytest.raises(TracerError) as caught:
        read_trace(path)
    assert caught.value.code == "trace_format"
    assert caught.value.line == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", 5),
        ("call_id", None),
        ("parent_id", 5),
        ("tool", []),
        ("started_at", "x"),
        ("started_at", True),
        ("duration_ms", None),
        ("status", "weird"),
        ("args", []),
        ("error_type", 3),
        ("cost", 3),
        ("tags", "x"),
        ("tags", [1]),
        ("tags", None),
        ("started_at", 10**400),
        ("duration_ms", float("nan")),
    ],
)
def test_bad_field_values_are_rejected(tmp_path: Path, field: str, value: Any) -> None:
    path = tmp_path / "t.jsonl"
    write_lines(path, [line_for(), line_for(**{field: value})])
    with pytest.raises(TracerError) as caught:
        read_trace(path)
    assert caught.value.code == "trace_format"
    assert caught.value.line == 2


@pytest.mark.parametrize("field", list(BASE))
def test_missing_fields_are_rejected(tmp_path: Path, field: str) -> None:
    path = tmp_path / "t.jsonl"
    data = {key: value for key, value in BASE.items() if key != field}
    write_lines(path, [json.dumps(data)])
    with pytest.raises(TracerError) as caught:
        read_trace(path)
    assert caught.value.line == 1
    assert field in str(caught.value)


def test_non_object_and_invalid_utf8_lines_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    write_lines(path, ["[1]"])
    with pytest.raises(TracerError) as caught:
        read_trace(path)
    assert caught.value.code == "trace_format"
    path.write_bytes(bytes([0xFF, 0xFE]) + bytes([10]))
    with pytest.raises(TracerError) as caught_bytes:
        read_trace(path)
    assert caught_bytes.value.line == 1


def test_deeply_nested_json_is_rejected_not_crashed(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text("[" * 100_000 + "]" * 100_000 + NL)
    with pytest.raises(TracerError) as caught:
        read_trace(path)
    assert caught.value.code == "trace_format"


def test_line_size_limit(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    line = line_for()
    size = len(line.encode("utf-8"))
    write_lines(path, [line])
    assert len(read_trace(path, max_line_bytes=size)) == 1
    with pytest.raises(TracerError) as caught:
        read_trace(path, max_line_bytes=size - 1)
    assert caught.value.code == "trace_format"
    assert caught.value.line == 1
    with pytest.raises(TracerError):
        read_trace(path, max_line_bytes=10)
    path.write_text(line, encoding="utf-8")
    assert len(read_trace(path, max_line_bytes=size)) == 1
    with pytest.raises(TracerError):
        read_trace(path, max_line_bytes=size - 1)


def test_event_count_limit(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    write_lines(path, [line_for(), line_for(call_id="2")])
    assert len(read_trace(path, max_events=2)) == 2
    with pytest.raises(TracerError) as caught:
        read_trace(path, max_events=1)
    assert caught.value.code == "trace_format"
    assert caught.value.line == 2


def test_blank_lines_are_skipped_but_counted(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text(NL + line_for() + NL + NL + "oops" + NL, encoding="utf-8")
    with pytest.raises(TracerError) as caught:
        read_trace(path)
    assert caught.value.line == 4
    path.write_text(NL + line_for() + NL + NL, encoding="utf-8")
    assert len(read_trace(path)) == 1


def test_crlf_lines_and_empty_files(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_bytes((line_for() + chr(13) + chr(10)).encode("utf-8"))
    assert len(read_trace(path)) == 1
    path.write_bytes(b"")
    assert read_trace(path) == []


@pytest.mark.parametrize("name", ["max_line_bytes", "max_events"])
def test_read_trace_rejects_bad_limits(tmp_path: Path, name: str) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text("")
    with pytest.raises(TracerError) as caught:
        read_trace(path, **{name: 0})
    assert caught.value.code == "invalid_argument"


def test_read_trace_missing_file_propagates_os_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_trace(tmp_path / "missing.jsonl")


def test_jsonl_sink_drops_events_that_would_pass_max_bytes(tmp_path: Path) -> None:
    probe_path = tmp_path / "probe.jsonl"
    JsonlSink(probe_path)(make_event())
    size = probe_path.stat().st_size
    path = tmp_path / "t.jsonl"
    sink = JsonlSink(path, max_bytes=2 * size)
    for _ in range(3):
        sink(make_event())
    assert sink.dropped == 1
    assert path.stat().st_size == 2 * size
    assert len(read_trace(path)) == 2


def test_jsonl_sink_boundaries(tmp_path: Path) -> None:
    probe_path = tmp_path / "probe.jsonl"
    JsonlSink(probe_path)(make_event())
    size = probe_path.stat().st_size
    exact = JsonlSink(tmp_path / "exact.jsonl", max_bytes=size)
    exact(make_event())
    exact(make_event())
    assert exact.dropped == 1
    small = JsonlSink(tmp_path / "small.jsonl", max_bytes=size - 1)
    small(make_event())
    assert small.dropped == 1
    assert not (tmp_path / "small.jsonl").exists()
    existing = tmp_path / "existing.jsonl"
    existing.write_bytes(b"x" * size)
    preloaded = JsonlSink(existing, max_bytes=size + 1)
    preloaded(make_event())
    assert preloaded.dropped == 1


def test_dropping_through_a_tracer_is_silent(tmp_path: Path) -> None:
    sink = JsonlSink(tmp_path / "t.jsonl", max_bytes=5)
    tracer = Tracer(sink)

    @tracer.trace_tool()
    def work() -> int:
        return 1

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert work() == 1
    assert sink.dropped == 1


def test_unserializable_events_raise_invalid_argument(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    sink = JsonlSink(path)
    circular: dict[str, Any] = {}
    circular["self"] = circular
    for event in (
        make_event(args={"o": object()}),
        make_event(duration_ms=float("nan")),
        make_event(args=circular),
    ):
        with pytest.raises(TracerError) as caught:
            sink(event)
        assert caught.value.code == "invalid_argument"
    assert not path.exists()


def test_jsonl_sink_rejects_bad_max_bytes(tmp_path: Path) -> None:
    with pytest.raises(TracerError) as caught:
        JsonlSink(tmp_path / "t.jsonl", max_bytes=0)
    assert caught.value.code == "invalid_argument"


def test_write_failure_becomes_a_warning_through_the_tracer(tmp_path: Path) -> None:
    tracer = Tracer(JsonlSink(tmp_path / "missing" / "t.jsonl"))

    @tracer.trace_tool()
    def work() -> int:
        return 5

    with pytest.warns(RuntimeWarning) as record:
        assert work() == 5
    assert len(record) == 1
    assert "FileNotFoundError" in str(record[0].message)
