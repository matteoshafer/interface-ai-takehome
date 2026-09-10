"""Surface-agnostic, robustness-ranked element targeting.

A recorded step does not store "a CSS selector". It stores an ordered list of
*strategies*, strongest first. Replay tries them in order and records which one
actually matched -- that record is the drift signal (see REPORT sec. 4).

Strategy order, and the reasoning behind it:

1. ``role_name``   -- the accessibility role + accessible name. Survives markup
   changes, styling, and DOM reshuffles; it is what a human operator perceives.
2. ``anchor``      -- "the control in the row/section anchored by this text".
   For legacy table layouts where many inputs share a role and have no name of
   their own, the stable thing is the neighbouring label text.
3. ``text``        -- visible text match, optionally constrained by role. Weaker:
   text can appear more than once.
4. ``bbox_ratio``  -- click a point expressed as a fraction of the viewport.
   Last resort; only meaningful when the layout is fixed. This is the seam where
   a screenshot-only / OCR surface plugs in.
"""
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class RoleName(BaseModel):
    kind: Literal["role_name"] = "role_name"
    role: str
    name: str
    exact: bool = True
    nth: int = 0  # which match to take when the name is legitimately non-unique


class Anchor(BaseModel):
    kind: Literal["anchor"] = "anchor"
    anchor_text: str          # nearby stable text (a label, a row header)
    control_role: str         # role of the control to act on
    control_name: Optional[str] = None


class TextContains(BaseModel):
    kind: Literal["text"] = "text"
    text: str
    role: Optional[str] = None


class CellAt(BaseModel):
    kind: Literal["cell_at"] = "cell_at"
    row_anchor: str           # text identifying the row (its first / header cell)
    column_header: str        # text of the column header
    contains: Optional[str] = None   # optional sanity check on the cell's text


class BBoxRatio(BaseModel):
    kind: Literal["bbox_ratio"] = "bbox_ratio"
    x: float  # 0..1 fraction of viewport width
    y: float  # 0..1 fraction of viewport height
    note: str = ""


Strategy = Annotated[
    Union[RoleName, CellAt, Anchor, TextContains, BBoxRatio],
    Field(discriminator="kind"),
]


class Target(BaseModel):
    """An ordered set of strategies for one control, plus why this order is robust."""
    strategies: List[Strategy] = Field(min_length=1)
    rationale: str = ""

    def primary(self) -> Strategy:
        return self.strategies[0]
