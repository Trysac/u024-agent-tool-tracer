"""Render trace events as a Mermaid sequence diagram that tool output cannot break."""

from __future__ import annotations

import json
from collections.abc import Iterable

from .errors import TracerError
from .model import TraceEvent

__all__ = ["to_mermaid"]

_MAX_LABEL_CODE_POINTS = 60
_NEWLINES = frozenset(chr(code) for code in (10, 11, 12, 13, 28, 29, 30, 0x85, 0x2028, 0x2029))
_ENTITIES = {"#": "#35;", ";": "#59;", "%": "#37;"}


def _label(text: str) -> str:
    """Cut to 60 code points first, then escape, so an entity is never split."""
    out: list[str] = []
    previous = ""
    for char in text[:_MAX_LABEL_CODE_POINTS]:
        if char == chr(10) and previous == chr(13):
            previous = char
            continue
        previous = char
        if char in _NEWLINES:
            out.append(" ")
        else:
            out.append(_ENTITIES.get(char, char))
    return "".join(out)


def _call_text(event: TraceEvent, show_args: bool) -> str:
    if not show_args:
        return event.tool
    try:
        args_text = json.dumps(event.args, ensure_ascii=False, default=repr)
    except (TypeError, ValueError, RecursionError):
        args_text = "..."
    return f"{event.tool}({args_text})"


def to_mermaid(
    events: Iterable[TraceEvent],
    *,
    actor: str = "Agent",
    show_args: bool = False,
) -> str:
    """Render events as a Mermaid ``sequenceDiagram``.

    Participants get fixed ids (``A``, ``T1``, ``T2``...) so tool names never become syntax.
    Every label is cut to 60 code points and then escaped (``#`` ``;`` ``%`` and newlines).
    Events are drawn in start order. An empty list yields only the header line.
    """
    if not isinstance(actor, str):
        raise TracerError("actor must be a string", "invalid_argument")
    ordered = sorted(events, key=lambda event: event.started_at)
    lines = ["sequenceDiagram"]
    if ordered:
        participants: dict[str, int] = {}
        for event in ordered:
            if event.tool not in participants:
                participants[event.tool] = len(participants) + 1
        lines.append(f"participant A as {_label(actor)}")
        for tool, index in participants.items():
            lines.append(f"participant T{index} as {_label(tool)}")
        for event in ordered:
            index = participants[event.tool]
            lines.append(f"    A->>T{index}: {_label(_call_text(event, show_args))}")
            if event.status == "ok":
                lines.append(f"    T{index}-->>A: ok {float(event.duration_ms)} ms")
            else:
                kind = _label(event.error_type or "unknown")
                lines.append(f"    T{index}--xA: error {kind}")
    return chr(10).join(lines) + chr(10)
