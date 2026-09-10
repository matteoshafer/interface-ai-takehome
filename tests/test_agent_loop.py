"""The LLM discovery loop, run for real against the live mock app with a fake
client that returns genuine SDK response objects and validates every request.

This proves everything in cua/agent/loop.py except the literal HTTP call to
Anthropic: request construction, tool_choice, multi-turn tool_result threading,
tool_use parsing, finish/escalate handling, loop detection, and that the loop
produces the SAME capability as the offline scripted path given the same moves.
"""
from __future__ import annotations

import pytest

from cua.agent.loop import AgentConfig, run_discovery
from cua.artifact.compiler import compile_capability
from cua.evidence import RunDir
from cua.surface.web import WebSurface
from tests.fake_llm import FakeAnthropic

pytestmark = pytest.mark.integration

GOAL = "look up member {{member_id}} and read their current savings balance"
HINT = {"member_id": "100042", "username": "operator", "password": "demo-pass"}

# The same decisions as demo/lookup_savings_balance.script.json, expressed as
# tool calls, so the LLM path and the scripted path must compile to the same
# artifact. One step carries assistant prose alongside the tool call, to prove
# the loop handles text + tool_use in one turn.
PLAN = [
    {"tool": "type_text", "input": {"role": "textbox", "name": "Username",
                                    "text": "operator", "why": "sign in as the operator"}},
    {"tool": "type_text", "input": {"role": "textbox", "name": "Password",
                                    "text": "demo-pass", "why": "enter the operator password"}},
    {"tool": "click", "input": {"role": "button", "name": "Sign in",
                                "why": "submit the login form"}},
    {"tool": "type_text", "input": {"role": "textbox", "name": "Member ID or name",
                                    "text": "100042", "why": "search for the member by id"},
     "say": "The login worked; now I'll search for the member."},
    {"tool": "click", "input": {"role": "button", "name": "Search",
                                "why": "run the member search"}},
    {"tool": "click", "input": {"role": "link", "name": "Open",
                                "why": "open the matching member record"}},
    {"tool": "read_value", "input": {"label": "savings_balance", "role": "cell",
                                     "name": "$4215.67",
                                     "why": "read the current savings balance"}},
    {"tool": "read_value", "input": {"label": "member_status", "role": "cell",
                                     "name": "Active",
                                     "why": "note the member account status"}},
    {"tool": "finish", "input": {"summary": "read the savings balance and status",
                                 "outputs": {}}},
]


def _run(plan, mock_base_url, policy, redactor, tmp_path, **cfg):
    s = WebSurface(headless=True)
    rd = RunDir(tmp_path / "run", redactor)
    try:
        return run_discovery(
            goal=GOAL, target_url=f"{mock_base_url}/login", surface=s, policy=policy,
            redactor=redactor, run_dir=rd, params_hint=HINT,
            config=AgentConfig(model="claude-sonnet-5", **cfg),
            client=FakeAnthropic(plan)), s
    finally:
        s.close()


def test_loop_completes_and_extracts_outputs(mock_base_url, policy, redactor, tmp_path):
    trace, _ = _run(PLAN, mock_base_url, policy, redactor, tmp_path)
    assert trace.outcome == "success"
    assert trace.reads["savings_balance"].value.strip() == "$4215.67"
    assert trace.reads["member_status"].value.strip() == "Active"


def test_requests_were_well_formed(mock_base_url, policy, redactor, tmp_path):
    trace, _ = _run(PLAN, mock_base_url, policy, redactor, tmp_path)
    # one request per plan step; the FakeAnthropic raises if any was malformed
    client_calls = None
    # rebuild to inspect calls (the fixture closed the surface already)
    fake = FakeAnthropic(PLAN)
    s = WebSurface(headless=True)
    try:
        run_discovery(goal=GOAL, target_url=f"{mock_base_url}/login", surface=s,
                      policy=policy, redactor=redactor,
                      run_dir=RunDir(tmp_path / "r2", redactor), params_hint=HINT,
                      config=AgentConfig(model="claude-sonnet-5"), client=fake)
    finally:
        s.close()
    assert len(fake.calls) == len(PLAN)
    assert all(c["tool_choice"] == {"type": "any"} for c in fake.calls)
    assert all(c["system"] and c["max_tokens"] and c["model"] for c in fake.calls)
    # history grows by two turns (assistant + user tool_result) per step
    assert [len(c["messages"]) for c in fake.calls] == [2 * k + 1 for k in range(len(PLAN))]


def test_llm_loop_produces_same_capability_as_scripted_path(
        mock_base_url, policy, redactor, tmp_path, capability):
    trace, _ = _run(PLAN, mock_base_url, policy, redactor, tmp_path)
    cap = compile_capability(trace, cap_id="lookup-savings-balance",
                             name="Look up member savings balance",
                             description="Look up a member and read the savings balance.",
                             redactor=redactor)
    a = cap.model_dump(exclude={"provenance"})
    b = capability.model_dump(exclude={"provenance"})
    assert a == b  # the LLM path and the scripted path compile to the same artifact


def test_loop_detection_escalates(mock_base_url, policy, redactor, tmp_path):
    stuck = [{"tool": "click", "input": {"role": "button", "name": "Sign in",
                                         "why": "try again"}}] * 10
    trace, _ = _run(stuck, mock_base_url, policy, redactor, tmp_path, max_steps=10)
    assert trace.outcome == "escalated"
    assert "no progress" in trace.summary.lower()


def test_explicit_escalate_tool(mock_base_url, policy, redactor, tmp_path):
    plan = [{"tool": "escalate", "input": {"reason": "I don't recognise this screen"}}]
    trace, _ = _run(plan, mock_base_url, policy, redactor, tmp_path)
    assert trace.outcome == "escalated"
    assert trace.escalation["reason"] == "I don't recognise this screen"


def test_max_steps_stops_the_loop(mock_base_url, policy, redactor, tmp_path):
    # never calls finish; distinct navigations so loop-detection doesn't fire first
    dests = ["/", "/members?q=a", "/members?q=b", "/members?q=c", "/members?q=d",
             "/members?q=e"]
    plan = [{"tool": "navigate", "input": {"url": f"{mock_base_url}{d}", "why": f"go {d}"}}
            for d in dests]
    trace, _ = _run(plan, mock_base_url, policy, redactor, tmp_path, max_steps=4)
    assert trace.outcome == "exhausted"
    assert len(trace.steps) == 4
