"""Redaction, conversion and truncation of arbitrary values into JSON-safe data."""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

__all__ = ["DEFAULT_REDACT_KEYS", "Sanitizer"]

DEFAULT_REDACT_KEYS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "cookie",
    "credential",
    "private_key",
    "session",
)

REDACTED = "[REDACTED]"
CYCLE = "[CYCLE]"
MAX_DEPTH = "[MAX_DEPTH]"


def safe_text(value: Any, limit: int) -> str:
    """Return ``str(value)`` cut to ``limit`` characters, never raising."""
    try:
        text = str(value)
    except Exception:
        text = "<unprintable " + type(value).__name__ + ">"
    return text[:limit]


def safe_repr(value: Any, limit: int) -> str:
    """Return ``repr(value)`` cut to ``limit`` characters, never raising."""
    try:
        text = repr(value)
    except Exception:
        text = "<unrepresentable " + type(value).__name__ + ">"
    return text[:limit]


def _sort_key(item: Any) -> str:
    return json.dumps(item, ensure_ascii=False)


class Sanitizer:
    """Turns arbitrary Python values into redacted, bounded, JSON-safe data.

    Keys are redacted by case-insensitive substring match at any depth. Values are never
    scanned for secrets.
    """

    def __init__(self, redact_keys: Sequence[str], max_value_chars: int, max_depth: int) -> None:
        self._redact = tuple(key.lower() for key in redact_keys)
        self._max_chars = max_value_chars
        self._max_depth = max_depth
        # Remaining number of nodes to convert; every node adds at least one character
        # to the JSON text, so once it is spent the text is already over the limit.
        self._budget = max_value_chars + 1

    def is_secret(self, key: str) -> bool:
        """Return True when ``key`` contains one of the redaction substrings."""
        lowered = key.lower()
        return any(part in lowered for part in self._redact)

    def mapping(self, values: Mapping[Any, Any]) -> dict[str, Any]:
        """Sanitize a mapping of named values (for example tool arguments)."""
        out: dict[str, Any] = {}
        for raw_key, value in values.items():
            key = self._key(raw_key)
            out[key] = REDACTED if self.is_secret(key) else self.value(value)
        return out

    def value(self, value: Any) -> Any:
        """Sanitize one value and cut it when its JSON text exceeds the limit."""
        try:
            self._budget = self._max_chars + 1
            converted = self._convert(value, 0, set())
            text = json.dumps(converted, ensure_ascii=False)
        except Exception:
            return "<unserializable " + type(value).__name__ + ">"
        if len(text) <= self._max_chars:
            return converted
        cut = len(text) - self._max_chars
        return f"{text[: self._max_chars]}...[truncated {cut} chars]"

    def _key(self, raw_key: Any) -> str:
        text = raw_key if isinstance(raw_key, str) else safe_text(raw_key, self._max_chars)
        return text[: self._max_chars]

    def _convert(self, value: Any, depth: int, path: set[int]) -> Any:
        self._budget -= 1
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return float(value) if math.isfinite(value) else repr(float(value))
        if isinstance(value, str):
            return str.__str__(value) if type(value) is not str else value
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dt.date | dt.time):
            return value.isoformat()
        if isinstance(value, bytes | bytearray):
            return f"<bytes {len(value)}>"
        if isinstance(value, memoryview):
            return f"<bytes {value.nbytes}>"
        if isinstance(value, Mapping | list | tuple | set | frozenset):
            return self._convert_container(value, depth, path)
        return safe_repr(value, self._max_chars)

    def _convert_container(self, value: Any, depth: int, path: set[int]) -> Any:
        if id(value) in path:
            return CYCLE
        if depth >= self._max_depth:
            return MAX_DEPTH
        path.add(id(value))
        try:
            if isinstance(value, Mapping):
                out: dict[str, Any] = {}
                for raw_key, item in value.items():
                    key = self._key(raw_key)
                    if self.is_secret(key):
                        out[key] = REDACTED
                    else:
                        out[key] = self._convert(item, depth + 1, path)
                return out
            items = []
            for item in value:
                items.append(self._convert(item, depth + 1, path))
            if isinstance(value, set | frozenset):
                items.sort(key=_sort_key)
            return items
        finally:
            path.discard(id(value))
