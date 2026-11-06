"""Package-level tests: public API surface, version, logging and error basics."""

from __future__ import annotations

import logging

import agent_tool_tracer
from agent_tool_tracer import TracerError


def test_public_api_is_exported() -> None:
    for name in agent_tool_tracer.__all__:
        assert hasattr(agent_tool_tracer, name)
    assert agent_tool_tracer.__version__ == "0.1.0"


def test_library_does_not_configure_logging() -> None:
    logger = logging.getLogger("agent_tool_tracer.tracer")
    assert any(isinstance(handler, logging.NullHandler) for handler in logger.handlers)
    sink_logger = logging.getLogger("agent_tool_tracer.sinks")
    assert any(isinstance(handler, logging.NullHandler) for handler in sink_logger.handlers)


def test_error_is_value_error_with_code_and_capped_message() -> None:
    error = TracerError("x" * 500, "invalid_argument")
    assert isinstance(error, ValueError)
    assert error.code == "invalid_argument"
    assert error.line is None
    assert len(str(error)) <= 200
    located = TracerError("bad", "trace_format", line=3)
    assert located.line == 3
