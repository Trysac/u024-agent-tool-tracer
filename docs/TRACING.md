# Tracing tool calls

`agent_tool_tracer` records every tool call of an agent as a `TraceEvent` and sends it to a sink.
There is no backend and there are no runtime dependencies.

## Recording

- `Tracer.trace_tool(name=None, *, cost=None)` decorates sync and async functions. Positional
  arguments are bound to parameter names with `inspect.signature`; defaults are included.
  Generator and async generator functions raise `TypeError` at decoration time.
- `Tracer.span(tool, args=None)` is a context manager yielding a handle with `set_result` and
  `set_cost`. An exception inside the block is recorded and re-raised.
- Parent tracking uses `contextvars`, so it works across asyncio tasks (`asyncio.gather`) and
  threads started with a copied context (`contextvars.copy_context().run`). A plain thread
  without a copied context starts a new root.
- A failing sink never breaks the tool: one `RuntimeWarning` naming only the exception type is
  emitted and the tool result is returned.
- Exceptions are stored by class name only (`error_type`); messages are never stored.

## Sinks

- `MemorySink(max_events=10_000)` keeps the newest events and counts evictions in `dropped`.
- `JsonlSink(path, max_bytes=104_857_600)` appends one line per event and flushes. An event that
  would make the file larger than `max_bytes` is dropped and counted in `dropped`.
- `read_trace(path, *, max_line_bytes=1_048_576, max_events=1_000_000)` validates every line and
  raises `TracerError` with code `trace_format` and the offending `line`.

## Redaction and limits

Keys containing one of `DEFAULT_REDACT_KEYS` (case-insensitive substring) are replaced by
`[REDACTED]` at any depth, in arguments and results. **Values are not scanned for secrets**: a
secret placed under an innocuous key is stored. Pass your own `redact_keys` to extend the list.

After redaction, cycles become `[CYCLE]`, nesting deeper than `max_depth` becomes
`[MAX_DEPTH]`, `Decimal` and `datetime` become text, bytes become `<bytes N>` and other objects
are shown through `repr` cut to `max_value_chars`. Finally each argument value and the result
whose JSON text is longer than `max_value_chars` is cut and suffixed with
`...[truncated N chars]`.

## Mermaid

`to_mermaid(events, actor="Agent", show_args=False)` renders a `sequenceDiagram`. Participants
use fixed ids (`A`, `T1`, `T2`...), so tool names never become diagram syntax. Labels are cut to
60 code points first and then escaped (`#` as `#35;`, `;` as `#59;`, `%` as `#37;`, newlines as
a space), so an entity is never split.
