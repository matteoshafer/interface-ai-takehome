"""Run evidence: a per-run directory with a structured JSONL log plus richer
signals (screenshots, AX snapshots) captured on failure.

Everything written here passes through the :class:`~cua.policy.redact.Redactor`
first -- no regulated data reaches disk.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Optional

from cua.policy.redact import Redactor


def _plain(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _plain(v) for k, v in asdict(obj).items()}
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


class RunDir:
    def __init__(self, root: str | Path, redactor: Optional[Redactor] = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._redactor = redactor
        self._log = self.root / "run.jsonl"
        self._t0 = time.time()

    def _redact(self, obj: Any) -> Any:
        obj = _plain(obj)
        return self._redactor.value(obj) if self._redactor else obj

    def event(self, kind: str, /, **fields: Any) -> None:
        rec = {"t_ms": int((time.time() - self._t0) * 1000), "kind": kind,
               **self._redact(fields)}
        with self._log.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")

    def write_json(self, name: str, obj: Any) -> Path:
        p = self.root / name
        p.write_text(json.dumps(self._redact(obj), indent=2) + "\n")
        return p

    def screenshot(self, name: str = "failure.png") -> str:
        return str(self.root / name)

    def path(self, name: str) -> Path:
        return self.root / name
