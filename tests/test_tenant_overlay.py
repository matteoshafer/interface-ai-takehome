"""TenantOverlay merge (pure) and a live cross-tenant replay (integration)."""
from __future__ import annotations

import pytest

from cua.artifact.schema import ActionSpec, Capability, Entry, Provenance, Step, TargetApp
from cua.artifact.tenant_overlay import (InsertedStep, OverlayMismatch, StepOverride,
                                         TenantOverlay, apply_overlay,
                                         find_step_by_target_name)
from cua.signals.dsl import AxPresent, UrlMatches
from cua.targeting.selector import RoleName, Target


def _cap() -> Capability:
    return Capability(
        id="c", name="c", description="c",
        target=TargetApp(app_id="cu-coreadmin",
                         entry=Entry(url="http://x/login", url_pattern="/login")),
        policy_ref="p",
        steps=[
            Step(id="s1", intent="search", action=ActionSpec(type="type"),
                target=Target(strategies=[RoleName(role="textbox", name="Member ID")])),
            Step(id="s2", intent="submit", action=ActionSpec(type="click"),
                target=Target(strategies=[RoleName(role="button", name="Search")])),
        ],
        checkpoint=UrlMatches(pattern="/done"),
        provenance=Provenance(discovered_by_model="t", discovered_at="t",
                              trace_hash="t", raw_step_count=2))


def test_merge_overrides_a_step_target_and_tags_the_tenant():
    cap = _cap()
    overlay = TenantOverlay(
        app_id="cu-coreadmin", tenant_id="west", base_capability_id="c",
        entry_suffix="?tenant=west",
        step_overrides={"s1": StepOverride(
            target=Target(strategies=[RoleName(role="textbox", name="Account Holder #")]))})

    merged = apply_overlay(cap, overlay)

    assert merged.target.tenant_id == "west"
    assert merged.target.entry.url == "http://x/login?tenant=west"
    assert merged.steps[0].target.strategies[0].name == "Account Holder #"
    assert merged.version == f"{cap.version}+west"
    # the base artifact object itself is untouched
    assert cap.target.tenant_id is None
    assert cap.steps[0].target.strategies[0].name == "Member ID"


def test_merge_can_insert_a_step_and_replace_the_checkpoint():
    cap = _cap()
    overlay = TenantOverlay(
        app_id="cu-coreadmin", tenant_id="west", base_capability_id="c",
        insert_steps=[InsertedStep(
            after="s2",
            step=Step(id="s2b", intent="pick a branch",
                      action=ActionSpec(type="select"),
                      target=Target(strategies=[RoleName(role="combobox", name="Home branch")])))],
        checkpoint=AxPresent(role="heading", name_matches="Confirmed"))

    merged = apply_overlay(cap, overlay)

    assert [s.id for s in merged.steps] == ["s1", "s2", "s2b"]
    assert merged.checkpoint.kind == "ax_present"


def test_merge_rejects_wrong_app_or_capability():
    cap = _cap()
    with pytest.raises(OverlayMismatch):
        apply_overlay(cap, TenantOverlay(app_id="other-app", tenant_id="west",
                                         base_capability_id="c"))
    with pytest.raises(OverlayMismatch):
        apply_overlay(cap, TenantOverlay(app_id="cu-coreadmin", tenant_id="west",
                                         base_capability_id="not-c"))


def test_find_step_by_target_name_survives_step_id_renaming():
    """The whole point: locate a step by what it targets, not by its
    compiler-assigned id -- which shifts across re-discovery runs even when
    the target screen is unchanged."""
    cap = _cap()
    assert find_step_by_target_name(cap, "Member ID", action_type="type") == "s1"
    assert find_step_by_target_name(cap, "member id") == "s1"  # case-insensitive

    renamed = cap.model_copy(deep=True)
    renamed.steps[0] = renamed.steps[0].model_copy(update={"id": "totally_different_id"})
    assert find_step_by_target_name(renamed, "Member ID") == "totally_different_id"

    with pytest.raises(OverlayMismatch, match="no step"):
        find_step_by_target_name(cap, "Nonexistent Field")


def test_merge_rejects_unknown_step_ids():
    cap = _cap()
    with pytest.raises(OverlayMismatch):
        apply_overlay(cap, TenantOverlay(
            app_id="cu-coreadmin", tenant_id="west", base_capability_id="c",
            step_overrides={"nope": StepOverride(risk="risky")}))
    with pytest.raises(OverlayMismatch):
        apply_overlay(cap, TenantOverlay(
            app_id="cu-coreadmin", tenant_id="west", base_capability_id="c",
            insert_steps=[InsertedStep(after="nope",
                                       step=Step(id="x", intent="x",
                                                action=ActionSpec(type="wait")))]))


# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_cross_tenant_replay_degrades_then_recovers_with_overlay(
        mock_base_url, policy, redactor, tmp_path, capability):
    """The real point of this feature: the SAME artifact, unmodified, still
    works against a relabeled tenant (falls through to the weakest locator
    strategy -- the drift signal) and a small overlay restores rank-0
    targeting. No re-recording either way."""
    from cua.artifact.tenant_overlay import apply_overlay
    from cua.evidence import RunDir
    from cua.replay.engine import replay
    from cua.surface.web import WebSurface

    def run(cap):
        s = WebSurface(headless=True)
        rd = RunDir(tmp_path / f"run-{id(cap)}", redactor)
        try:
            return replay(cap, {"member_id": "100042", "username": "operator",
                                "password": "demo-pass"},
                         policy=policy, surface=s, run_dir=rd, redactor=redactor,
                         origin=mock_base_url)
        finally:
            s.close()

    search_step = next(s.id for s in capability.steps
                       if s.action.type == "type" and s.phase == "main")

    west_no_overlay = capability.model_copy(deep=True)
    west_no_overlay.target.entry.url += "?tenant=west"
    r_no_overlay = run(west_no_overlay)
    assert r_no_overlay.outcome == "success"
    rank_no_overlay = next(st.strategy_rank for st in r_no_overlay.steps
                          if st.step_id == search_step)
    assert rank_no_overlay is not None and rank_no_overlay > 0  # fell through

    overlay = TenantOverlay(
        app_id=capability.target.app_id, tenant_id="west",
        base_capability_id=capability.id, entry_suffix="?tenant=west",
        step_overrides={search_step: StepOverride(target=Target(strategies=[
            RoleName(role="textbox", name="Account Holder # or name")]))})
    merged = apply_overlay(capability, overlay)
    r_overlay = run(merged)
    assert r_overlay.outcome == "success"
    rank_overlay = next(st.strategy_rank for st in r_overlay.steps
                        if st.step_id == search_step)
    assert rank_overlay == 0
    assert r_overlay.outputs == r_no_overlay.outputs
