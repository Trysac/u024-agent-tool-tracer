"""Trace every tool call of an agent with redacted JSONL and escaped Mermaid diagrams."""

from __future__ import annotations

from .errors import TracerError
from .mermaid import to_mermaid
from .model import TraceEvent
from .serialize import DEFAULT_REDACT_KEYS
from .sinks import JsonlSink, MemorySink, read_trace
from .tracer import SpanHandle, Tracer

__all__ = [
    "DEFAULT_REDACT_KEYS",
    "JsonlSink",
    "MemorySink",
    "SpanHandle",
    "TraceEvent",
    "Tracer",
    "TracerError",
    "__version__",
    "read_trace",
    "to_mermaid",
]

__version__ = "0.1.0"
