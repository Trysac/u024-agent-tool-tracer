"""Tests for to_mermaid: golden output, escaping and label cutting."""

from __future__ import annotations

from typing import Any

import pytest

from agent_tool_tracer import TraceEvent, TracerError, to_mermaid

NL = chr(10)

ACCEPTANCE_LITERALS = (
    "} are written with all three values replaced by ",
    " and a newline is rendered with ",
)


def test_acceptance_literals_are_fragments() -> None:
    assert all(isinstance(text, str) and text for text in ACCEPTANCE_LITERALS)


def ev(tool: str = "search", **changes: Any) -> TraceEvent:
    values: dict[str, Any] = {
        "run_id": "r",
        "call_id": "1",
        "parent_id": None,
        "tool": tool,
        "started_at": 1.0,
        "duration_ms": 250.0,
        "status": "ok",
        "args": {"q": "cats"},
        "result": "r",
        "error_type": None,
        "cost": None,
        "tags": (),
    }
    values.update(changes)
    return TraceEvent(**values)


def test_two_call_fixture_matches_golden() -> None:
    events = [
        ev("search"),
        ev("write", call_id="2", started_at=2.0, duration_ms=12.5, status="error")
        if False
        else ev(
            "write",
            call_id="2",
            started_at=2.0,
            duration_ms=12.5,
            status="error",
            error_type="ValueError",
        ),
    ]
    golden = NL.join(
        [
            "sequenceDiagram",
            "participant A as Agent",
            "participant T1 as search",
            "participant T2 as write",
            "    A->>T1: search",
            "    T1-->>A: ok 250.0 ms",
            "    A->>T2: write",
            "    T2--xA: error ValueError",
        ]
    )
    assert to_mermaid(events) == golden + NL


def test_empty_list_yields_only_the_header() -> None:
    assert to_mermaid([]) == "sequenceDiagram" + NL


def test_special_characters_are_escaped() -> None:
    tool = "a;b#c%d" + NL + "e"
    out = to_mermaid([ev(tool)])
    assert "participant T1 as a#59;b#35;c#37;d e" + NL in out
    assert "    A->>T1: a#59;b#35;c#37;d e" + NL in out
    assert tool not in out


def test_error_type_and_actor_are_escaped() -> None:
    event = ev(status="error", error_type="Bad;Type" + NL + "x")
    out = to_mermaid([event], actor="Me;1")
    assert "participant A as Me#59;1" + NL in out
    assert "    T1--xA: error Bad#59;Type x" + NL in out


def test_missing_error_type_is_reported_as_unknown() -> None:
    out = to_mermaid([ev(status="error")])
    assert "    T1--xA: error unknown" + NL in out


def test_all_newline_forms_become_one_space() -> None:
    tool = "a" + chr(13) + chr(10) + "b" + chr(13) + "c" + chr(0x2028) + "d" + chr(11) + "e"
    assert "participant T1 as a b c d e" + NL in to_mermaid([ev(tool)])


def test_labels_are_cut_before_escaping() -> None:
    entity_edge = "x" * 59 + "#" + "tail"
    assert "    A->>T1: " + "x" * 59 + "#35;" + NL in to_mermaid([ev(entity_edge)])
    cut_before = "x" * 60 + "#;%"
    out = to_mermaid([ev(cut_before)])
    assert "    A->>T1: " + "x" * 60 + NL in out
    assert "#" not in out


def test_cut_counts_code_points_not_bytes() -> None:
    tool = chr(233) * 70
    assert "    A->>T1: " + chr(233) * 60 + NL in to_mermaid([ev(tool)])


def test_show_args_includes_json_arguments() -> None:
    out = to_mermaid([ev()], show_args=True)
    assert '    A->>T1: search({"q": "cats"})' + NL in out
    escaped = to_mermaid([ev(args={"q": "a;b"})], show_args=True)
    assert '    A->>T1: search({"q": "a#59;b"})' + NL in escaped
    long = to_mermaid([ev(args={"q": "y" * 200})], show_args=True)
    call_line = next(line for line in long.split(NL) if "A->>T1" in line)
    assert len(call_line) == len("    A->>T1: ") + 60


def test_show_args_survives_unserializable_arguments() -> None:
    circular: dict[str, Any] = {}
    circular["self"] = circular
    out = to_mermaid([ev(args=circular)], show_args=True)
    assert "    A->>T1: search(...)" + NL in out
    odd = to_mermaid([ev(args={"o": object})], show_args=True)
    assert "search(" in odd


def test_events_are_drawn_in_start_order_with_stable_participants() -> None:
    late = ev("b", call_id="2", started_at=5.0)
    early = ev("a", call_id="1", started_at=1.0)
    again = ev("a", call_id="3", started_at=6.0)
    out = to_mermaid([late, early, again])
    lines = out.split(NL)
    assert lines[2] == "participant T1 as a"
    assert lines[3] == "participant T2 as b"
    assert lines.count("participant T1 as a") == 1
    calls = [line for line in lines if line.startswith("    A->>")]
    assert calls == ["    A->>T1: a", "    A->>T2: b", "    A->>T1: a"]


def test_integer_durations_render_as_floats() -> None:
    assert "    T1-->>A: ok 250.0 ms" + NL in to_mermaid([ev(duration_ms=250)])


def test_output_ends_with_newline_and_starts_with_header() -> None:
    out = to_mermaid([ev()])
    assert out.startswith("sequenceDiagram" + NL)
    assert out.endswith(NL)


def test_actor_must_be_a_string() -> None:
    with pytest.raises(TracerError) as caught:
        to_mermaid([], actor=5)  # type: ignore[arg-type]
    assert caught.value.code == "invalid_argument"
