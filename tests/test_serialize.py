"""Serialization behavior, observed through events recorded by Tracer."""

from __future__ import annotations

import enum
import json
import types
from collections.abc import Iterator, Mapping
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from agent_tool_tracer import MemorySink, TraceEvent, Tracer


def record(args: dict[Any, Any] | None = None, result: Any = None, **options: Any) -> TraceEvent:
    sink = MemorySink()
    tracer = Tracer(sink, **options)
    with tracer.span("t", args) as handle:
        handle.set_result(result)
    return sink.events[0]


def test_keys_are_redacted_at_any_depth() -> None:
    args = {"Authorization": "x", "nested": [{"API_KEY": "y"}], "my_token_id": "z"}
    event = record(args)
    assert event.args == {
        "Authorization": "[REDACTED]",
        "nested": [{"API_KEY": "[REDACTED]"}],
        "my_token_id": "[REDACTED]",
    }


def test_result_keys_are_redacted() -> None:
    event = record(result={"password": "p", "ok": 1, "deep": ({"Cookie": "c"},)})
    assert event.result == {
        "password": "[REDACTED]",
        "ok": 1,
        "deep": [{"Cookie": "[REDACTED]"}],
    }


def test_decorated_parameter_named_like_a_secret_is_redacted() -> None:
    sink = MemorySink()
    tracer = Tracer(sink)

    @tracer.trace_tool()
    def call(api_key: str, n: int) -> int:
        return n

    call("value-1", 2)
    assert sink.events[0].args == {"api_key": "[REDACTED]", "n": 2}


def test_custom_redact_keys_replace_the_defaults() -> None:
    event = record({"pin": 1, "token": 2}, redact_keys=("PIN",))
    assert event.args == {"pin": "[REDACTED]", "token": 2}


def test_values_are_not_scanned_for_secrets() -> None:
    event = record({"note": "Bearer abc"})
    assert event.args == {"note": "Bearer abc"}


def test_long_string_is_truncated_with_count() -> None:
    value = "x" * 28
    event = record({"v": value}, max_value_chars=20)
    assert event.args["v"] == '"' + "x" * 19 + "...[truncated 10 chars]"


def test_value_at_exact_limit_is_not_truncated() -> None:
    event = record({"v": "x" * 18}, max_value_chars=20)
    assert event.args["v"] == "x" * 18


def test_long_list_and_result_are_truncated_by_json_text() -> None:
    value = list(range(30))
    text = json.dumps(value)
    expected = text[:20] + f"...[truncated {len(text) - 20} chars]"
    event = record({"v": value}, result=value, max_value_chars=20)
    assert event.args["v"] == expected
    assert event.result == expected


def test_cycles_are_marked() -> None:
    cyc: list[Any] = []
    cyc.append(cyc)
    assert record({"v": cyc}, max_value_chars=20).args["v"] == ["[CYCLE]"]
    mapping: dict[str, Any] = {}
    mapping["self"] = mapping
    assert record({"v": mapping}, max_value_chars=20).args["v"] == {"self": "[CYCLE]"}


def test_shared_reference_is_not_a_cycle() -> None:
    shared = [1]
    assert record({"v": [shared, shared]}).args["v"] == [[1], [1]]


def test_depth_deeper_than_32_is_marked() -> None:
    value: Any = "leaf"
    for _ in range(40):
        value = [value]
    out = record({"v": value}, max_value_chars=10_000).args["v"]
    for _ in range(32):
        out = out[0]
    assert out == "[MAX_DEPTH]"


def test_custom_max_depth() -> None:
    event = record({"v": [[[1]]]}, max_depth=2)
    assert event.args["v"] == [["[MAX_DEPTH]"]]


def test_decimal_and_datetime_are_converted() -> None:
    event = record(
        {"d": Decimal("1.5"), "when": datetime(2026, 1, 2, tzinfo=timezone.utc)},
    )
    assert event.args == {"d": "1.5", "when": "2026-01-02T00:00:00+00:00"}
    assert record({"d": Decimal("1.5")}, max_value_chars=20).args == {"d": "1.5"}
    assert record({"a": date(2026, 1, 2), "b": time(1, 2, 3)}).args == {
        "a": "2026-01-02",
        "b": "01:02:03",
    }


def test_bytes_are_summarized() -> None:
    event = record({"a": b"abc", "b": bytearray(5), "c": memoryview(b"ab")})
    assert event.args == {"a": "<bytes 3>", "b": "<bytes 5>", "c": "<bytes 2>"}


class Color(enum.IntEnum):
    RED = 1


class Name(str, enum.Enum):
    ALPHA = "alpha"


def test_enums_and_non_finite_floats() -> None:
    event = record(
        {"c": Color.RED, "n": Name.ALPHA, "a": float("nan"), "b": float("inf"), "c2": -1e999}
    )
    assert event.args == {"c": 1, "n": "alpha", "a": "nan", "b": "inf", "c2": "-inf"}
    assert type(event.args["n"]) is str
    assert type(event.args["c"]) is int


def test_scalars_pass_through() -> None:
    event = record({"a": None, "b": True, "c": 3, "d": 1.5, "e": "s"})
    assert event.args == {"a": None, "b": True, "c": 3, "d": 1.5, "e": "s"}


def test_non_string_keys_are_stringified() -> None:
    event = record({"v": {1: "a", None: "b"}})
    assert event.args["v"] == {"1": "a", "None": "b"}
    assert record({1: "x"}).args == {"1": "x"}


def test_key_with_failing_str_is_replaced() -> None:
    class BadStr:
        def __str__(self) -> str:
            raise RuntimeError("no")

    event = record({"v": {BadStr(): 1}})
    assert event.args["v"] == {"<unprintable BadStr>": 1}


def test_sets_tuples_and_mapping_proxies() -> None:
    event = record(
        {
            "s": {3, 1, 2},
            "f": frozenset({"b", "a"}),
            "t": (1, (2, 3)),
            "m": types.MappingProxyType({"k": 1}),
        }
    )
    assert event.args == {"s": [1, 2, 3], "f": ["a", "b"], "t": [1, [2, 3]], "m": {"k": 1}}


class Plain:
    def __repr__(self) -> str:
        return "Plain<1>"


class Long:
    def __repr__(self) -> str:
        return "R" * 100


class BadRepr:
    def __repr__(self) -> str:
        raise RuntimeError("no")


class Broken(Mapping[str, int]):
    def __getitem__(self, key: str) -> int:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError("no")

    def __len__(self) -> int:
        return 0


def test_other_objects_use_repr() -> None:
    assert record({"v": Plain()}).args["v"] == "Plain<1>"


def test_long_repr_is_cut_then_truncated() -> None:
    out = record({"v": Long()}, max_value_chars=50).args["v"]
    assert out == '"' + "R" * 49 + "...[truncated 2 chars]"


def test_failing_repr_and_failing_mapping_do_not_break_recording() -> None:
    event = record({"a": BadRepr(), "b": Broken()})
    assert event.args == {"a": "<unrepresentable BadRepr>", "b": "<unserializable Broken>"}
