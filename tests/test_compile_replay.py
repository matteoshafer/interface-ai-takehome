"""End-to-end: scripted discovery -> compile -> deterministic replay, covering
all three result shapes and the recovery / hard-failure paths.
"""
from __future__ import annotations

import pytest

from cua.evidence import RunDir
from cua.replay.engine import replay
from cua.surface.web import WebSurface

pytestmark = pytest.mark.integration

CREDS = {"username": "operator", "password": "demo-pass"}


def _replay(cap, params, policy, redactor, tmp_path, base, **kw):
    s = WebSurface(headless=True)
    rd = RunDir(tmp_path / "replay", redactor)
    try:
        return replay(cap, params, policy=policy, surface=s, run_dir=rd,
                      redactor=redactor, origin=base, **kw)
    finally:
        s.close()


def test_compiled_capability_shape(capability):
    assert capability.parameters[0].name == "member_id"
    assert {o.name for o in capability.outputs} == {"savings_balance", "member_status"}
    assert any(s.action.value_ref == "{{ member_id }}" for s in capability.steps)
    # secrets are typed as secret and never carry an example value
    secret = [p for p in capability.parameters if p.sensitivity == "secret"]
    assert secret and all(p.example is None for p in secret)


def test_replay_success_with_outputs(capability, policy, redactor, tmp_path, mock_base_url):
    r = _replay(capability, {"member_id": "100042", **CREDS}, policy, redactor,
                tmp_path, mock_base_url)
    assert r.outcome == "success"
    assert r.outputs["savings_balance"] == 4215.67
    assert r.outputs["member_status"] == "Active"


def test_replay_parameterised_other_member(capability, policy, redactor, tmp_path,
                                           mock_base_url):
    r = _replay(capability, {"member_id": "100500", **CREDS}, policy, redactor,
                tmp_path, mock_base_url)
    assert r.outcome == "success"
    assert isinstance(r.outputs["savings_balance"], float)


def test_replay_member_not_found_is_business_outcome(capability, policy, redactor,
                                                     tmp_path, mock_base_url):
    r = _replay(capability, {"member_id": "999999", **CREDS}, policy, redactor,
                tmp_path, mock_base_url)
    assert r.outcome == "business_outcome"
    assert r.business_outcome == "member_not_found"
    assert r.business_data == {"found": False}


def test_replay_permission_denied_is_business_outcome(capability, policy, redactor,
                                                      tmp_path, mock_base_url):
    r = _replay(capability, {"member_id": "100999", **CREDS}, policy, redactor,
                tmp_path, mock_base_url)
    assert r.outcome == "business_outcome"
    assert r.business_outcome == "permission_denied"


def test_replay_bad_param_fails_before_touching_the_ui(capability, policy, redactor,
                                                       tmp_path, mock_base_url):
    r = _replay(capability, {"member_id": "not-an-id", **CREDS}, policy, redactor,
                tmp_path, mock_base_url)
    assert r.outcome == "failure" and r.error_class == "bad_params"
    assert not r.steps


def test_replay_recovers_from_injected_dialog(capability, policy, redactor, tmp_path,
                                              mock_base_url):
    nav = [s.id for s in capability.steps
           if s.phase == "main" and s.action.type == "click"][-1]
    r = _replay(capability, {"member_id": "100042", **CREDS}, policy, redactor,
                tmp_path, mock_base_url, inject_before={nav: "dialog"})
    assert r.outcome == "success"
    assert any("maintenance_notice" in s.recoveries for s in r.steps)


def test_replay_recovers_from_session_timeout(capability, policy, redactor, tmp_path,
                                              mock_base_url):
    nav = [s.id for s in capability.steps
           if s.phase == "main" and s.action.type == "click"][-1]
    r = _replay(capability, {"member_id": "100042", **CREDS}, policy, redactor,
                tmp_path, mock_base_url, inject_before={nav: "timeout"})
    assert r.outcome == "success"


def test_replay_hard_failure_reports_debuggable_context(capability, policy, redactor,
                                                        tmp_path, mock_base_url):
    nav = [s.id for s in capability.steps
           if s.phase == "main" and s.action.type == "click"][-1]
    r = _replay(capability, {"member_id": "100042", **CREDS}, policy, redactor,
                tmp_path, mock_base_url, inject_before={nav: "error"})
    assert r.outcome == "failure"
    assert r.error_class == "app_error"
    assert r.failed_step == nav
    assert r.evidence_dir and r.expected and r.observed
