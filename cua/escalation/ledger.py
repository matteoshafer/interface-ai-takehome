"""Append-only record of who holds control of the live session, and why.

The one authoritative answer to "who is (or should be) in control right now" --
the seam the brief calls out. Automation acts only while it holds the token.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

Holder = Literal["automation", "operator"]


@dataclass
class ControlEvent:
    t: float
    holder: Holder
    reason: str


class ControlLedger:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = Path(path) if path else None
        self.events: list[ControlEvent] = []
        self._append("automation", "run started")

    @property
    def holder(self) -> Holder:
        return self.events[-1].holder

    def _append(self, holder: Holder, reason: str) -> None:
        ev = ControlEvent(t=time.time(), holder=holder, reason=reason)
        self.events.append(ev)
        if self._path:
            with self._path.open("a") as fh:
                fh.write(json.dumps(ev.__dict__) + "\n")

    def cede_to_operator(self, reason: str) -> None:
        self._append("operator", reason)

    def reclaim(self, reason: str = "operator handed back") -> None:
        self._append("automation", reason)
