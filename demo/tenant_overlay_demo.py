"""Cross-tenant reuse demo (REPORT.md sec. 4 / brief sec. 3.7, sec. 8).

`lookup-savings-balance` was recorded once against the base app
(`?tenant=core`, the default). This script replays that SAME artifact against
a second, differently-branded tenant (`?tenant=west` -- Westland FCU relabels
the member-search field from "Member ID" to "Account Holder #") three ways:

1. unmodified, against the base (core) tenant                  -- the control
2. unmodified, against west, with NO overlay                    -- what
   "reuse without re-recording" looks like before you add anything
3. with a small overlay applied, patching only the relabeled field

Run (2) shows the ordered-locator design degrading gracefully rather than
breaking: the relabeled field makes the primary `role_name` strategy miss, so
resolution falls through to the last-resort `bbox_ratio` strategy -- still
correct, but on the weakest, most position-dependent strategy. That
fall-through is exactly the "sustained fall-through to a weaker strategy"
drift signal described in REPORT.md sec. 4. Run (3) shows the overlay
restoring rank-0 semantic targeting. Neither run re-records the capability.

The overlay is (re)derived from whatever `capabilities/lookup-savings-balance.json`
currently holds (`build_west_overlay`, below) and saved to
`overlays/west/lookup-savings-balance.json` -- not hand-maintained -- because
the compiler names steps from the discovering model's own phrasing, which
shifts between re-discovery runs even when the target screen didn't change.
Locating the step by what it targets, rather than trusting last time's step
id, is what keeps the overlay valid across that churn.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from cua.artifact import store
from cua.artifact.tenant_overlay import (StepOverride, TenantOverlay, apply_overlay,
                                         find_step_by_target_name, save_overlay)
from cua.evidence import RunDir
from cua.policy.config import PolicyConfig
from cua.policy.redact import Redactor
from cua.replay.engine import replay
from cua.surface.web import WebSurface
from cua.targeting.selector import RoleName, Target
from mockapp.server import MockServer

REPO = Path(__file__).resolve().parent.parent
CAP_ID = "lookup-savings-balance"
PARAMS = {"member_id": "100042", "username": "operator", "password": "demo-pass"}


def build_west_overlay(cap) -> TenantOverlay:
    """Derive the west overlay from whatever capability is currently on disk,
    rather than trusting a step id hardcoded when it was last discovered --
    the compiler names steps from the model's own phrasing, which shifts
    between discovery runs even though the app didn't change. Locating the
    step by what it targets (the "Member ID" search field) keeps the overlay
    valid across re-discovery, as long as the target screen itself is stable."""
    step_id = find_step_by_target_name(cap, "Member ID", action_type="type")
    return TenantOverlay(
        app_id=cap.target.app_id, tenant_id="west", base_capability_id=cap.id,
        description=(
            "Westland FCU ServiceDesk relabels the member-search field; the "
            "record grid, headings, and URLs are otherwise identical to the "
            "base app, so only the search step's target needs an override."),
        entry_suffix="?tenant=west",
        step_overrides={step_id: StepOverride(
            target=Target(strategies=[
                RoleName(role="textbox", name="Account Holder # or name",
                         exact=True, nth=0)],
                rationale=("West relabels the search field from 'Member ID' to "
                          "'Account Holder #' (mockapp TENANTS['west']"
                          ".member_label); the base role_name/anchor strategies "
                          "were recorded against the 'Member ID' label.")),
            note="'Member ID or name' -> 'Account Holder # or name' on this tenant.",
        )},
    )


def _run(label: str, cap, evidence_name: str, policy, redactor):
    out = REPO / "evidence" / evidence_name
    if out.exists():
        shutil.rmtree(out)
    run_dir = RunDir(out, redactor)
    s = WebSurface(headless=True)
    try:
        r = replay(cap, PARAMS, policy=policy, surface=s, run_dir=run_dir,
                  redactor=redactor, origin="http://localhost:5050")
    finally:
        s.close()
    ranks = [f"{st.step_id}:{st.matched_strategy}#{st.strategy_rank}"
             for st in r.steps if st.matched_strategy]
    print(f"\n[{label}]")
    print(" ", r.summary().splitlines()[0])
    print("  targeting:", "  ".join(ranks))
    print("  evidence:", out)
    return r


def main() -> None:
    policy = PolicyConfig.load(REPO / "policies/creditunion.yaml")
    redactor = Redactor(policy)

    base = store.load(REPO / f"capabilities/{CAP_ID}.json")

    west_no_overlay = store.load(REPO / f"capabilities/{CAP_ID}.json")
    west_no_overlay.target.entry.url += "?tenant=west"

    overlay = build_west_overlay(base)
    saved = save_overlay(overlay, REPO / "overlays")
    print(f"(re)generated {saved} for the current {CAP_ID}.json "
          f"(step {next(iter(overlay.step_overrides))})")
    west_with_overlay = apply_overlay(base, overlay)

    with MockServer(port=5050):
        r1 = _run("1. base capability x core tenant (control)",
                  base, "replay-tenant-core", policy, redactor)
        r2 = _run("2. base capability x west tenant, NO overlay",
                  west_no_overlay, "replay-tenant-west-no-overlay", policy, redactor)
        r3 = _run("3. base capability + overlay x west tenant",
                  west_with_overlay, "replay-tenant-west", policy, redactor)

    search_step = next(iter(overlay.step_overrides))

    def rank_of(r):
        return next((st.strategy_rank for st in r.steps
                    if st.step_id == search_step), None)

    print(f"\nsummary: the search-field step's ({search_step}) matched-strategy rank")
    print(f"  core, no overlay:   rank {rank_of(r1)}  (role_name)")
    print(f"  west, no overlay:   rank {rank_of(r2)}  "
          f"(fell through to bbox_ratio -- the drift signal)")
    print(f"  west, with overlay: rank {rank_of(r3)}  (role_name restored)")
    assert r1.outcome == r2.outcome == r3.outcome == "success"
    assert rank_of(r1) == 0
    assert rank_of(r2) > 0
    assert rank_of(r3) == 0
    print("\nall three replays succeeded; the overlay is the only thing that "
          "changed between (2) and (3).")


if __name__ == "__main__":
    main()
