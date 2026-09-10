"""The perceive/act seam.

Everything above this line (agent loop, artifact schema, replay engine, policy)
is written against these types and never imports Playwright. A new surface --
a legacy frameset, a native desktop app -- is a new ``Surface`` implementation
with the same contract; the recorded artifact and the replay engine do not
change. That is the property Section 3.7 of the brief asks for.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

from cua.targeting.selector import Strategy, Target


@dataclass(frozen=True)
class AXNode:
    """One node of the normalized accessibility snapshot."""
    role: str
    name: str
    value: Optional[str] = None
    states: tuple[str, ...] = ()
    # x, y, w, h in CSS pixels; None when the surface can't report geometry.
    bbox: Optional[tuple[float, float, float, float]] = None
    # Text of the first cell of the containing table row, when the node sits in
    # a data grid -- the anchor legacy layouts actually keep stable.
    row_anchor: Optional[str] = None
    # Column header text for a cell in a data grid (row x column addressing).
    column_header: Optional[str] = None


@dataclass
class Observation:
    """What the agent (or the replay checkpoint evaluator) sees at one instant."""
    url: str
    title: str
    nodes: list[AXNode]
    text: str = ""                     # concatenated visible text, for text matching
    dialog: Optional[str] = None       # accessible name of an open modal, if any
    viewport: tuple[int, int] = (1280, 800)
    screenshot_path: Optional[str] = None
    http_status: Optional[int] = None

    def nodes_by_role(self, role: str) -> list[AXNode]:
        return [n for n in self.nodes if n.role == role]

    def has(self, role: str, name_substr: str) -> bool:
        s = name_substr.lower()
        return any(n.role == role and s in n.name.lower() for n in self.nodes)


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"       # pick an <option> in a listbox/combobox
    PRESS_KEY = "press_key"
    READ = "read"           # extract text/value from a control -> output
    WAIT = "wait"
    FINISH = "finish"       # discovery only: goal reached, here are the outputs
    ESCALATE = "escalate"   # discovery only: stuck, hand to a human


SAFE_ACTIONS = {ActionType.NAVIGATE, ActionType.TYPE, ActionType.SELECT,
                ActionType.READ, ActionType.WAIT, ActionType.PRESS_KEY}


@dataclass
class Action:
    type: ActionType
    target: Optional[Target] = None
    value: Optional[str] = None
    note: Optional[str] = None          # agent's stated intent / operator note
    # discovery convenience: the agent names a control by role+name and the
    # recorder expands it into a full multi-strategy Target.
    pick_role: Optional[str] = None
    pick_name: Optional[str] = None


@dataclass
class LocateResult:
    status: str                         # "unique" | "ambiguous" | "missing"
    strategy: Optional[Strategy] = None
    handle: object = None               # opaque, surface-specific
    count: int = 0


@dataclass
class ActionResult:
    ok: bool
    observation: Observation
    matched_strategy: Optional[Strategy] = None
    error: Optional[str] = None
    extracted: Optional[str] = None     # for READ actions


@runtime_checkable
class Surface(Protocol):
    """The full contract a surface must satisfy."""

    def goto(self, url: str) -> None: ...

    def observe(self) -> Observation: ...

    def locate(self, strategy: Strategy, obs: Observation) -> LocateResult: ...

    def click(self, handle: object) -> None: ...

    def fill(self, handle: object, text: str) -> None: ...

    def select_option(self, handle: object, value: str) -> None: ...

    def read(self, handle: object) -> str: ...

    def press_key(self, key: str) -> None: ...

    def click_point(self, x_ratio: float, y_ratio: float) -> None: ...

    def screenshot(self, path: str) -> str: ...

    def current_url(self) -> str: ...

    def close(self) -> None: ...
