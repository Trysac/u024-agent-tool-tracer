# agent-tool-tracer

[![PyPI version](https://img.shields.io/pypi/v/trysac-agent-tool-tracer)](https://pypi.org/project/trysac-agent-tool-tracer/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-agent-tool-tracer)](LICENSE)
[![CI](https://github.com/Trysac/u024-agent-tool-tracer/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u024-agent-tool-tracer/actions/workflows/ci.yml)

Trace every tool call of an agent with redacted arguments, results, timing, cost and errors to JSONL, and render runs as escaped Mermaid sequence diagrams

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-agent-tool-tracer
# or
uv add trysac-agent-tool-tracer
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import agent_tool_tracer

# normalize() trims surrounding whitespace and lower-cases the text.
print(agent_tool_tracer.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    agent_tool_tracer.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
