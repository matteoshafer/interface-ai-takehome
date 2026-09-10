"""Build a robust multi-strategy Target from a control the agent named by
role + accessible name.

Used in two places, and it must produce the *same* Target in both so replay
reproduces discovery:

* the discovery loop, to resolve the agent's action and to record what matched;
* the compiler, to write the Target into the capability artifact.
"""
from __future__ import annotations

from typing import Optional

from cua.surface.base import Observation
from cua.targeting.selector import (Anchor, BBoxRatio, CellAt, RoleName, Target,
                                    TextContains)

# roles where a nearby label is the stable anchor (the control has no name of its own)
_INPUT_ROLES = {"textbox", "combobox", "checkbox", "radio", "listbox", "spinbutton"}


def target_from_parts(*, role: str, name: str, nth: int = 0,
                      row_anchor: Optional[str] = None,
                      column_header: Optional[str] = None,
                      bbox_ratio: Optional[tuple[float, float]] = None,
                      rationale: str = "") -> Target:
    """Build the same Target as :func:`synthesize_target`, from recorded parts
    (no live surface). Used by the compiler."""
    strategies: list = []
    # For a value in a data grid, (row x column) is the most robust locator and
    # does not depend on the value itself -- essential for parameterised replay.
    if row_anchor and column_header and role in ("cell", "columnheader", "rowheader"):
        strategies.append(CellAt(row_anchor=row_anchor, column_header=column_header))
    strategies.append(RoleName(role=role, name=name, exact=True, nth=nth))
    anchor_text = name or row_anchor
    if anchor_text and (role in _INPUT_ROLES or row_anchor):
        strategies.append(Anchor(anchor_text=row_anchor or anchor_text,
                                 control_role=role))
    if name:
        strategies.append(TextContains(text=name, role=role))
    if bbox_ratio is not None:
        strategies.append(BBoxRatio(x=round(bbox_ratio[0], 4),
                                    y=round(bbox_ratio[1], 4),
                                    note="viewport-fraction fallback captured at "
                                         "record time"))
    return Target(strategies=strategies,
                  rationale=rationale or _rationale(role, name, len(strategies)))


def _rationale(role: str, name: str, n: int) -> str:
    return (
        f"Primary: accessibility role '{role}' + name '{name}' -- stable across "
        f"restyle/markup changes and matches what an operator sees. "
        + ("Fallback: the labelling text, for legacy rows where inputs share a "
           "role and carry no name. " if n > 2 else "")
        + "Last resort: viewport-fraction click point, valid only while the "
          "layout is fixed.")


def synthesize_target(surface, obs: Observation, *, role: str, name: str,
                      nth: int = 0, row_anchor: Optional[str] = None,
                      column_header: Optional[str] = None,
                      rationale: str = "") -> Target:
    strategies: list = []
    if row_anchor and column_header and role in ("cell", "columnheader", "rowheader"):
        strategies.append(CellAt(row_anchor=row_anchor, column_header=column_header))
    strategies.append(RoleName(role=role, name=name, exact=True, nth=nth))

    anchor_text = name or row_anchor
    if anchor_text and (role in _INPUT_ROLES or row_anchor):
        strategies.append(Anchor(anchor_text=row_anchor or anchor_text,
                                 control_role=role))

    if name:
        strategies.append(TextContains(text=name, role=role))

    center = _center_ratio(surface, RoleName(role=role, name=name, nth=nth))
    if center is not None:
        strategies.append(BBoxRatio(x=round(center[0], 4), y=round(center[1], 4),
                                    note="viewport-fraction fallback captured at "
                                         "record time"))

    if not rationale:
        rationale = (
            f"Primary: accessibility role '{role}' + name '{name}' -- stable across "
            f"restyle/markup changes and matches what an operator sees. "
            + ("Fallback: the labelling text, for legacy rows where inputs share a "
               "role and carry no name. " if len(strategies) > 2 else "")
            + "Last resort: viewport-fraction click point, valid only while the "
              "layout is fixed.")

    return Target(strategies=strategies, rationale=rationale)


def _center_ratio(surface, strat: RoleName):
    try:
        loc = surface.page.get_by_role(strat.role, name=strat.name, exact=strat.exact)
        if loc.count() == 0:
            return None
        box = loc.nth(strat.nth).bounding_box()
        if not box:
            return None
        w, h = surface._viewport
        return ((box["x"] + box["width"] / 2) / w,
                (box["y"] + box["height"] / 2) / h)
    except Exception:
        return None
