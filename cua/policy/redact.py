"""Redaction applied to everything before it is written to disk.

Regulated financial data must not land in artifacts, logs, traces or evidence.
A matched value is replaced by a stable token ``<redacted:HASH>`` -- stable so a
reviewer can still see "the same SSN appears in step 2 and the checkpoint" without
the value ever being recoverable.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from cua.policy.config import PolicyConfig


def _tok(value: str) -> str:
    h = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"<redacted:{h}>"


class Redactor:
    def __init__(self, policy: PolicyConfig) -> None:
        self._patterns = [re.compile(p) for p in policy.redaction.patterns]
        self._fields = {f.lower() for f in policy.redaction.field_names}

    def text(self, s: str) -> str:
        if not isinstance(s, str):
            return s
        for rx in self._patterns:
            s = rx.sub(lambda m: _tok(m.group(0)), s)
        return s

    def field(self, name: str, value: Any) -> Any:
        """Redact a value because of *what field it is*, regardless of shape."""
        if name and name.lower() in self._fields and isinstance(value, str) and value:
            return _tok(value)
        return self.value(value)

    def value(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.text(obj)
        if isinstance(obj, dict):
            return {k: self.field(str(k), v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return type(obj)(self.value(v) for v in obj)
        return obj

    def is_sensitive_field(self, name: str) -> bool:
        return bool(name) and name.lower() in self._fields
