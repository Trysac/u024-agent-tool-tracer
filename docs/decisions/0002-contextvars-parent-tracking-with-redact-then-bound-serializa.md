# Contextvars parent tracking with redact-then-bound serialization

Status: accepted (generated, pending human review)

## Context

Developers need to see which tools an agent called, with which arguments, how long each took and which failed, without a tracing backend and without leaking API keys into trace files. Tool output is untrusted and must not be able to break a rendered diagram, and trace files and in-memory stores must be bounded.

## Decision

Record calls through a decorator and a span context manager. Track the parent call with a module-level ContextVar so asyncio tasks and copied-context threads inherit it. Sanitize every argument and result in a fixed order: redact keys by case-insensitive substring, replace cycles and excessive depth, convert Decimal, datetime, bytes and other objects, then cut any value whose JSON text exceeds max_value_chars. Sinks are bounded (MemorySink evicts the oldest, JsonlSink drops events past max_bytes) and count what they lose. A failing sink only produces a RuntimeWarning naming the exception type. Mermaid output uses fixed participant ids and labels that are cut first and escaped second.

## Consequences

The library works offline with zero dependencies and tool names or outputs cannot inject Mermaid syntax. Values are not scanned for secrets, so secrets under innocuous keys are stored; this is documented. Threads started without a copied context begin new root calls. Per-value truncation turns an oversized value into a string, so its original type is lost in the trace. Drops and warnings keep tools running but mean a trace can be incomplete, which callers can detect through the dropped counters.
