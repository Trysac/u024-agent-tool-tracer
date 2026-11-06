"""Bounded work in serialization and receiver omission for methods."""

from __future__ import annotations

from agent_tool_tracer import MemorySink, Tracer


def test_huge_list_is_not_fully_walked() -> None:
    sink = MemorySink()
    tracer = Tracer(sink, max_value_chars=20)
    big = list(range(100_000))
    with tracer.span("t", {"v": big}):
        pass
    stored = sink.events[0].args["v"]
    assert isinstance(stored, str)
    assert "truncated" in stored


def test_huge_string_is_truncated() -> None:
    sink = MemorySink()
    tracer = Tracer(sink, max_value_chars=20)
    with tracer.span("t", {"v": "a" * 1_000_000}):
        pass
    assert sink.events[0].args["v"].startswith('"' + "a" * 19)


def test_wide_dict_is_truncated() -> None:
    sink = MemorySink()
    tracer = Tracer(sink, max_value_chars=20)
    with tracer.span("t", {"v": {str(i): i for i in range(50_000)}}):
        pass
    assert "truncated" in sink.events[0].args["v"]


def test_self_and_cls_are_not_recorded() -> None:
    sink = MemorySink()
    tracer = Tracer(sink)

    class Client:
        def __repr__(self) -> str:
            return "Client(key='hunter2')"

        @tracer.trace_tool()
        def call(self, x: int) -> int:
            return x

        @classmethod
        @tracer.trace_tool()
        def make(cls, x: int) -> int:
            return x

    Client().call(1)
    Client.make(2)
    assert sink.events[0].args == {"x": 1}
    assert sink.events[1].args == {"x": 2}
    assert "hunter2" not in repr(sink.events)
