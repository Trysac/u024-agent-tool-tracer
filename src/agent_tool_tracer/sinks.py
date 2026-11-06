"""Bounded sinks for trace events and a strict JSONL reader."""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from pathlib import Path

from .errors import TracerError, require_int
from .model import TraceEvent, event_from_obj, event_to_dict

__all__ = ["JsonlSink", "MemorySink", "read_trace"]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class MemorySink:
    """In-memory sink keeping the most recent ``max_events`` events."""

    def __init__(self, max_events: int = 10_000) -> None:
        require_int(max_events, "max_events", 1)
        self._events: deque[TraceEvent] = deque(maxlen=max_events)
        self._dropped = 0
        self._lock = threading.Lock()

    @property
    def events(self) -> list[TraceEvent]:
        """A copy of the retained events, oldest first."""
        with self._lock:
            return list(self._events)

    @property
    def dropped(self) -> int:
        """Number of old events evicted because the sink was full."""
        return self._dropped

    def __call__(self, event: TraceEvent) -> None:
        with self._lock:
            if len(self._events) == self._events.maxlen:
                self._dropped += 1
            self._events.append(event)


class JsonlSink:
    """Appends one JSON line per event to a file, never growing it past ``max_bytes``.

    An event whose line would make the file larger than ``max_bytes`` is dropped and
    counted in :attr:`dropped`.
    """

    def __init__(self, path: Path | str, max_bytes: int = 104_857_600) -> None:
        require_int(max_bytes, "max_bytes", 1)
        self._path = Path(path)
        self._max_bytes = max_bytes
        self._dropped = 0
        self._lock = threading.Lock()

    @property
    def dropped(self) -> int:
        """Number of events dropped because of the size limit."""
        return self._dropped

    def __call__(self, event: TraceEvent) -> None:
        try:
            text = json.dumps(
                event_to_dict(event),
                ensure_ascii=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError, RecursionError):
            raise TracerError("event is not JSON serializable", "invalid_argument") from None
        line = (text + chr(10)).encode("ascii")
        with self._lock:
            try:
                size = self._path.stat().st_size
            except FileNotFoundError:
                size = 0
            if size + len(line) > self._max_bytes:
                self._dropped += 1
                logger.debug("trace event dropped: size limit reached")
                return
            with self._path.open("ab") as handle:
                handle.write(line)
                handle.flush()


def read_trace(
    path: Path | str,
    *,
    max_line_bytes: int = 1_048_576,
    max_events: int = 1_000_000,
) -> list[TraceEvent]:
    """Read a JSONL trace written by :class:`JsonlSink`.

    Blank lines are skipped. Any malformed line, a line longer than ``max_line_bytes`` or
    more than ``max_events`` events raises ``TracerError`` with code ``trace_format`` and the
    one-based ``line`` number. I/O errors such as a missing file propagate as ``OSError``.
    """
    require_int(max_line_bytes, "max_line_bytes", 1)
    require_int(max_events, "max_events", 1)
    events: list[TraceEvent] = []
    line_no = 0
    with Path(path).open("rb") as handle:
        while True:
            raw = handle.readline(max_line_bytes + 2)
            if not raw:
                break
            line_no += 1
            content = raw[:-1] if raw.endswith(b"\n") else raw
            if content.endswith(b"\r"):
                content = content[:-1]
            if len(content) > max_line_bytes:
                raise TracerError("trace line exceeds the size limit", "trace_format", line=line_no)
            if not content.strip():
                continue
            if len(events) >= max_events:
                raise TracerError("trace has too many events", "trace_format", line=line_no)
            try:
                obj = json.loads(content.decode("utf-8"))
            except (ValueError, RecursionError):
                raise TracerError(
                    "trace line is not valid JSON", "trace_format", line=line_no
                ) from None
            events.append(event_from_obj(obj, line_no))
    return events
