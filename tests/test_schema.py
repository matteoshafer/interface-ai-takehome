"""Capability contract: parameter validation, templating, agent-facing schema."""
from __future__ import annotations

import pytest

from cua.artifact.schema import (ActionSpec, Capability, Entry, ParamError,
                                 Parameter, Provenance, Step, TargetApp)
from cua.signals.dsl import UrlMatches


def _cap(**over) -> Capability:
    d = dict(
        id="c", name="c", description="c",
        target=TargetApp(app_id="a", entry=Entry(url="http://x/m/{{member_id}}",
                                                 url_pattern="/m")),
        policy_ref="p",
        parameters=[
            Parameter(name="member_id", type="string", pattern=r"^\d{4,9}$"),
            Parameter(name="dry_run", type="boolean", required=False),
        ],
        steps=[Step(id="s1", intent="x", action=ActionSpec(type="wait"))],
        checkpoint=UrlMatches(pattern="/done"),
        provenance=Provenance(discovered_by_model="t", discovered_at="t",
                              trace_hash="t", raw_step_count=1))
    d.update(over)
    return Capability(**d)


def test_validate_params_ok_and_coercion():
    r = _cap().validate_params({"member_id": "100042", "dry_run": "yes"})
    assert r == {"member_id": "100042", "dry_run": True}


def test_validate_params_missing_required():
    with pytest.raises(ParamError):
        _cap().validate_params({})


def test_validate_params_pattern_violation():
    with pytest.raises(ParamError):
        _cap().validate_params({"member_id": "abc"})


def test_validate_params_rejects_unknown():
    with pytest.raises(ParamError):
        _cap().validate_params({"member_id": "100042", "bogus": 1})


def test_render_template_and_value():
    c = _cap()
    assert c.render_template("http://x/m/{{member_id}}", {"member_id": "42"}) == "http://x/m/42"
    assert c.render_value("{{ member_id }}", {"member_id": "42"}) == "42"
    assert c.render_value("literal", {}) == "literal"


def test_contract_shape_for_agents():
    ct = _cap().contract()
    assert ct["name"] == "c"
    assert ct["input_schema"]["required"] == ["member_id"]
    assert ct["input_schema"]["properties"]["member_id"]["pattern"] == r"^\d{4,9}$"


def test_roundtrip_json():
    c = _cap()
    assert Capability.model_validate_json(c.model_dump_json()).id == "c"
