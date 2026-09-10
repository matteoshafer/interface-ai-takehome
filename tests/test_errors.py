"""The error taxonomy classifier -- synthetic observations, no browser."""
from __future__ import annotations

import pytest

from cua.artifact import library
from cua.artifact.schema import (ActionSpec, Capability, Entry, Provenance, Step,
                                 TargetApp)
from cua.replay.errors import classify
from cua.signals.dsl import UrlMatches
from cua.surface.base import AXNode, Observation


def _cap() -> Capability:
    return Capability(
        id="c", name="c", description="c",
        target=TargetApp(app_id="cu-coreadmin",
                         entry=Entry(url="http://x/login", url_pattern="/login")),
        policy_ref="p",
        steps=[Step(id="s1", intent="x", action=ActionSpec(type="wait"))],
        checkpoint=UrlMatches(pattern="/done"),
        known_outcomes=library.known_outcomes("cu-coreadmin"),
        recovery=library.recovery("cu-coreadmin"),
        provenance=Provenance(discovered_by_model="t", discovered_at="t",
                              trace_hash="t", raw_step_count=1))


def obs(**kw):
    d = dict(url="http://x/", title="t", nodes=[], text="", dialog=None,
             http_status=200)
    d.update(kw)
    return Observation(**d)


def test_business_outcome_member_not_found():
    o = obs(nodes=[AXNode(role="alert", name="No member found matching 'zzz'")],
            text="No member found matching 'zzz'")
    c = classify(_cap(), o)
    assert c.kind == "business_outcome" and c.name == "member_not_found"


def test_business_outcome_permission_denied():
    o = obs(text="Member 100999 is flagged restricted. Supervisor override required.")
    assert classify(_cap(), o).name == "permission_denied"


def test_recoverable_session_timeout():
    o = obs(url="http://x/login?expired=1", text="Your session has expired. Sign in.")
    c = classify(_cap(), o)
    assert c.kind == "recoverable" and c.name == "session_timeout"


def test_recoverable_maintenance_dialog():
    o = obs(dialog="System notice", text="Scheduled maintenance tonight 11 PM.")
    assert classify(_cap(), o).name == "maintenance_notice"


def test_hard_failure_app_error_and_unexpected_dialog():
    assert classify(_cap(), obs(http_status=500,
                                text="Application error CU-ADMIN-500")).error_class == "app_error"
    assert classify(_cap(), obs(dialog="Weird popup",
                                text="something")).error_class == "unexpected_dialog"


def test_clear_when_nothing_wrong():
    assert classify(_cap(), obs(text="Member 100042 - Jordan Rivera")).kind == "clear"
