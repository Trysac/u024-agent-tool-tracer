# agent-tool-tracer

[![PyPI version](https://img.shields.io/pypi/v/trysac-agent-tool-tracer)](https://pypi.org/project/trysac-agent-tool-tracer/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-agent-tool-tracer)](LICENSE)
[![CI](https://github.com/Trysac/u024-agent-tool-tracer/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u024-agent-tool-tracer/actions/workflows/ci.yml)

Trace every tool call of an agent with redacted arguments, results, timing, cost and errors to JSONL, and render runs as escaped Mermaid sequence diagrams

## Problem

When an agent misbehaves, developers cannot see which tools it called, with what arguments, how long
each took and which call failed, and ad hoc print debugging leaks API keys into files. Full
observability platforms need a backend. This library records tool calls into bounded, redacted JSONL
and renders a run as a Mermaid sequence diagram that tool output cannot break.

## Install

```sh
pip install trysac-agent-tool-tracer
# or
uv add trysac-agent-tool-tracer
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
from pathlib import Path

from agent_tool_tracer import JsonlSink, Tracer, read_trace, to_mermaid

tracer = Tracer(JsonlSink(Path("trace.jsonl")))


@tracer.trace_tool()
def search(query: str, api_key: str) -> str:
    return f"results for {query}"


search("mermaid", api_key="secret")  # api_key is stored as "[REDACTED]"

events = read_trace(Path("trace.jsonl"))
print(to_mermaid(events))
```

Notes:

- Argument keys matching `api_key`, `token`, `secret`, `password`, `authorization`, `cookie` and
  similar are redacted by case-insensitive substring at any depth. **Values are not scanned for
  secrets**: a secret stored under an innocent key is written as is.
- For decorated methods the first parameter named `self` or `cls` is not recorded, because its repr
  could contain credentials.
- Stored values are bounded by `max_value_chars`, and conversion stops early once that budget is
  spent, so huge inputs are not fully walked.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
