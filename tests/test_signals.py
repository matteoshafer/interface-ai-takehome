"""Signal DSL evaluator -- table-driven over synthetic Observations, no browser."""
from __future__ import annotations

import pytest

from cua.signals.dsl import (AllOf, AnyOf, AxPresent, DialogOpen, HttpStatus, Not,
                             TextMatches, UrlMatches)
from cua.signals.evaluate import evaluate
from cua.surface.base import AXNode, Observation


def obs(**kw):
    base = dict(url="http://x/member/42", title="t", nodes=[], text="", dialog=None,
               http_status=200)
    base.update(kw)
    return Observation(**base)


def test_url_matches_against_path_and_full():
    o = obs(url="http://localhost:5050/member/42?x=1")
    assert evaluate(UrlMatches(pattern=r"^/member/\d+"), o).value
    assert evaluate(UrlMatches(pattern=r"member/42\?x=1"), o).value
    assert not evaluate(UrlMatches(pattern=r"^/login"), o).value


def test_ax_present_and_absent():
    o = obs(nodes=[AXNode(role="heading", name="Confirmation"),
                   AXNode(role="alert", name="No member found matching 'zzz'")])
    assert evaluate(AxPresent(role="heading", name_matches="Confirm"), o).value
    assert evaluate(AxPresent(role="alert", name_matches=r"[Nn]o member found"), o).value
    assert not evaluate(AxPresent(role="button", name_matches="Save"), o).value


def test_text_and_dialog_and_status():
    o = obs(text="Your session has expired. Please sign in.", dialog="System notice",
            http_status=503)
    assert evaluate(TextMatches(pattern="session has expired"), o).value
    assert evaluate(DialogOpen(expected=True), o).value
    assert not evaluate(DialogOpen(expected=False), o).value
    assert evaluate(HttpStatus(gte=500), o).value
    assert not evaluate(HttpStatus(lt=400), o).value


def test_boolean_composition():
    o = obs(url="http://x/member/42", nodes=[AXNode(role="heading", name="Member 42")])
    sig = AllOf(of=[UrlMatches(pattern=r"/member/\d+"),
                    AnyOf(of=[AxPresent(role="heading", name_matches="Member"),
                              AxPresent(role="heading", name_matches="Nope")]),
                    Not(of=DialogOpen(expected=True))])
    assert evaluate(sig, o).value


def test_failure_trace_is_populated():
    o = obs(url="http://x/login")
    r = evaluate(AllOf(of=[UrlMatches(pattern=r"/member"),
                           AxPresent(role="heading", name_matches="X")]), o)
    assert not r.value
    assert r.trace  # debuggable: which leaves were checked
