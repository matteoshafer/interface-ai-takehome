"""Tenant overlays: reuse one capability across institutions running the same
vendor product, instead of re-recording per tenant.

The brief's framing (Section 3.7 / REPORT.md Section 4): hundreds of tenants run
~20 apps each, and many share the same underlying vendor product, configured,
branded, and versioned differently. A capability is recorded once against the
*product* (``app_id``, ``tenant_id: null``); a small, explicit overlay carries
only what one tenant's install does differently -- a relabeled field, an
inserted step, a different confirmation heading. Replay deep-merges base +
overlay; nothing about the base capability is re-recorded or duplicated.

This is deliberately the smallest thing that could work: no tenant registry, no
auto-detection of which overlay applies, no versioned compatibility matrix --
just a named JSON file the caller points at (``--tenant west``, which resolves
to ``overlays/west/<capability id>.json`` by convention, or an explicit
``--overlay`` path). A real system would add a lookup service in front of this;
that's exactly the scaling infrastructure the brief says not to build
prematurely. This module is the seam it would plug into.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from cua.artifact.schema import Capability, Step
from cua.signals.dsl import Signal
from cua.targeting.selector import Target

OVERLAY_SCHEMA_VERSION = "1.0"
DEFAULT_OVERLAY_DIR = Path("overlays")


class StepOverride(BaseModel):
    """What changes about one existing step for this tenant. Only the fields
    set here are replaced; everything else on the base step carries over."""
    target: Optional[Target] = None
    value_ref: Optional[str] = None
    risk: Optional[Literal["safe", "risky"]] = None
    post: Optional[Signal] = None
    note: str = ""          # why this override exists -- for the human reviewer


class InsertedStep(BaseModel):
    """A step this tenant's flow has that the base capability doesn't (e.g. an
    extra branch-selection screen). Inserted immediately after ``after``."""
    after: str
    step: Step
    note: str = ""


class TenantOverlay(BaseModel):
    schema_version: str = OVERLAY_SCHEMA_VERSION
    app_id: str
    tenant_id: str
    base_capability_id: str
    description: str = ""
    # appended to the base capability's entry URL verbatim, e.g. "?tenant=west"
    entry_suffix: str = ""
    step_overrides: Dict[str, StepOverride] = Field(default_factory=dict)
    insert_steps: List[InsertedStep] = Field(default_factory=list)
    checkpoint: Optional[Signal] = None   # replace the base checkpoint, if this
                                          # tenant's confirmation screen differs


class OverlayMismatch(ValueError):
    """The overlay doesn't target the capability it was given."""


def apply_overlay(cap: Capability, overlay: TenantOverlay) -> Capability:
    """Deep-merge ``overlay`` onto ``cap``. Returns a NEW Capability; the base
    artifact on disk is never modified. Unknown step ids in the overlay (e.g.
    the base capability was re-recorded and step ids changed) raise loudly
    rather than silently no-op -- a stale overlay should fail fast."""
    if overlay.app_id != cap.target.app_id:
        raise OverlayMismatch(
            f"overlay is for app_id {overlay.app_id!r}, capability is "
            f"{cap.target.app_id!r}")
    if overlay.base_capability_id != cap.id:
        raise OverlayMismatch(
            f"overlay targets capability {overlay.base_capability_id!r}, "
            f"got {cap.id!r}")

    data = cap.model_dump(mode="json")
    data["target"]["tenant_id"] = overlay.tenant_id
    if overlay.entry_suffix:
        data["target"]["entry"]["url"] += overlay.entry_suffix

    by_id = {s["id"]: s for s in data["steps"]}
    unknown = set(overlay.step_overrides) - set(by_id)
    if unknown:
        raise OverlayMismatch(f"overlay overrides unknown step id(s): {unknown}")
    for step_id, ov in overlay.step_overrides.items():
        step = by_id[step_id]
        if ov.target is not None:
            step["target"] = ov.target.model_dump(mode="json")
        if ov.value_ref is not None:
            step["action"]["value_ref"] = ov.value_ref
        if ov.risk is not None:
            step["risk"] = ov.risk
        if ov.post is not None:
            step["post"] = ov.post.model_dump(mode="json")

    unknown_after = {ins.after for ins in overlay.insert_steps} - set(by_id)
    if unknown_after:
        raise OverlayMismatch(
            f"overlay inserts after unknown step id(s): {unknown_after}")
    for ins in sorted(overlay.insert_steps, key=lambda i: i.after):
        idx = next(i for i, s in enumerate(data["steps"]) if s["id"] == ins.after)
        data["steps"].insert(idx + 1, ins.step.model_dump(mode="json"))

    if overlay.checkpoint is not None:
        data["checkpoint"] = overlay.checkpoint.model_dump(mode="json")

    data["version"] = f"{cap.version}+{overlay.tenant_id}"
    merged = Capability.model_validate(data)
    return merged


def find_step_by_target_name(cap: Capability, name_substr: str, *,
                             action_type: Optional[str] = None) -> str:
    """Locate a step by what its primary locator targets (e.g. a control whose
    accessible name contains "Member ID"), rather than by the compiler-assigned
    step id -- which is derived from the discovering model's phrasing of its
    own `why` and is not stable across re-discovery runs. This is how an
    overlay stays valid even if the base capability gets re-recorded with
    differently-worded step ids, as long as the target screen didn't change."""
    needle = name_substr.lower()
    hits = []
    for s in cap.steps:
        if action_type and s.action.type != action_type:
            continue
        if s.target is None:
            continue
        prim = s.target.strategies[0]
        if needle in (getattr(prim, "name", "") or "").lower():
            hits.append(s.id)
    if not hits:
        raise OverlayMismatch(
            f"no step's primary target name contains {name_substr!r}"
            + (f" (action_type={action_type})" if action_type else ""))
    if len(hits) > 1:
        raise OverlayMismatch(
            f"ambiguous: steps {hits} all target a name containing {name_substr!r}")
    return hits[0]


def overlay_path(tenant_id: str, capability_id: str,
                 root: str | Path = DEFAULT_OVERLAY_DIR) -> Path:
    return Path(root) / tenant_id / f"{capability_id}.json"


def load_overlay(path: str | Path) -> TenantOverlay:
    return TenantOverlay.model_validate_json(Path(path).read_text())


def save_overlay(overlay: TenantOverlay, root: str | Path = DEFAULT_OVERLAY_DIR) -> Path:
    p = overlay_path(overlay.tenant_id, overlay.base_capability_id, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(overlay.model_dump_json(indent=2) + "\n")
    return p
