"""Locator resolution and ordered fallback -- against the live mock app."""
from __future__ import annotations

import pytest

from cua.targeting.params import parameterize_target, render_target
from cua.targeting.resolver import resolve
from cua.targeting.selector import (Anchor, BBoxRatio, CellAt, RoleName, Target,
                                    TextContains)

pytestmark = pytest.mark.integration


def _login(surface, base):
    surface.goto(f"{base}/login")
    o = surface.observe()
    for role, name, val in [("textbox", "Username", "op"), ("textbox", "Password", "p")]:
        r = resolve(surface, Target(strategies=[RoleName(role=role, name=name)]), o)
        surface.fill(r.handle, val)
    r = resolve(surface, Target(strategies=[RoleName(role="button", name="Sign in")]), o)
    surface.click(r.handle)


def test_role_name_unique(surface, mock_base_url):
    _login(surface, mock_base_url)
    o = surface.observe()
    r = resolve(surface, Target(strategies=[
        RoleName(role="textbox", name="Member ID or name")]), o)
    assert r.ok and r.strategy.kind == "role_name"


def test_falls_through_to_anchor_when_name_wrong(surface, mock_base_url):
    _login(surface, mock_base_url)
    o = surface.observe()
    # wrong primary name -> must fall through to the label anchor
    t = Target(strategies=[
        RoleName(role="textbox", name="Totally wrong label"),
        Anchor(anchor_text="Member ID or name", control_role="textbox"),
    ])
    r = resolve(surface, t, o)
    assert r.ok and r.strategy.kind == "anchor" and r.strategy_index == 1


def test_cell_at_row_by_column(surface, mock_base_url):
    _login(surface, mock_base_url)
    surface.goto(f"{mock_base_url}/member/100042")
    o = surface.observe()
    r = resolve(surface, Target(strategies=[
        CellAt(row_anchor="Savings", column_header="Current balance")]), o)
    assert r.ok
    assert surface.read(r.handle).strip().startswith("$4215")


def test_missing_target_reports_missing(surface, mock_base_url):
    _login(surface, mock_base_url)
    o = surface.observe()
    r = resolve(surface, Target(strategies=[
        RoleName(role="button", name="Nonexistent")]), o)
    assert not r.ok and r.status == "missing"


def test_parameterize_then_render_roundtrip():
    t = Target(strategies=[Anchor(anchor_text="100042", control_role="link")])
    p = parameterize_target(t, {"member_id": "100042"})
    assert p.strategies[0].anchor_text == "{{ member_id }}"
    back = render_target(p, {"member_id": "999999"})
    assert back.strategies[0].anchor_text == "999999"
