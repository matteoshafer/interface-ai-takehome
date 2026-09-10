"""Parameterise / render the string fields of a Target.

At compile time, a locator string that exactly equals a supplied input value is
rewritten to ``{{ name }}`` -- so "open the row for 100042" becomes "open the row
for {{ member_id }}". At replay time the reverse substitution runs before
resolution, so the same capability targets a different record.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from cua.targeting.selector import Target

_FIELDS = ("name", "anchor_text", "control_name", "row_anchor", "column_header",
           "text", "contains")


def parameterize_target(target: Target, params: Dict[str, Any]) -> Target:
    lookup = {str(v): k for k, v in params.items() if v not in (None, "")}
    data = target.model_dump()
    for strat in data["strategies"]:
        for f in _FIELDS:
            if strat.get(f) in lookup:
                strat[f] = f"{{{{ {lookup[strat[f]]} }}}}"
    return Target.model_validate(data)


def sanitize_target(target: Target, redactor) -> Target:
    """Drop any strategy that would bake regulated data (an SSN, an account
    number) into the artifact as a locator string. A value-based strategy
    (role+name on the value itself, or a text match) is removed; position-based
    strategies (cell_at, anchor, bbox) survive. If every strategy is value-based
    the primary is kept with its name redacted, so review still flags it."""
    if redactor is None:
        return target
    data = target.model_dump()
    kept = []
    for strat in data["strategies"]:
        vals = [strat.get(f) for f in ("name", "text", "contains")
                if isinstance(strat.get(f), str)]
        if any(redactor.text(v) != v for v in vals):
            continue  # value-based locator on sensitive data -> drop
        kept.append(strat)
    if not kept:
        first = data["strategies"][0]
        for f in ("name", "text", "contains"):
            if isinstance(first.get(f), str):
                first[f] = redactor.text(first[f])
        kept = [first]
    data["strategies"] = kept
    data["rationale"] = redactor.text(data.get("rationale", ""))
    return Target.model_validate(data)


def render_target(target: Target, params: Dict[str, Any]) -> Target:
    def sub(s: str) -> str:
        return re.sub(r"\{\{\s*(\w+)\s*\}\}",
                      lambda m: str(params.get(m.group(1), m.group(0))), s)

    data = target.model_dump()
    for strat in data["strategies"]:
        for f in _FIELDS:
            if isinstance(strat.get(f), str) and "{{" in strat[f]:
                strat[f] = sub(strat[f])
    return Target.model_validate(data)
