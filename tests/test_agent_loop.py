"""The LLM discovery loop, run for real against the live mock app with a fake
provider-neutral client that validates the transcript contract on every call.

This proves everything in cua/agent/loop.py except the provider adapters'
native-message translation (covered by test_llm_adapters.py): transcript
threading, tool dispatch, finish/escalate handling, loop detection, max-steps,
and that the LLM path compiles to the SAME capability as the scripted path.
"""
from __future__ import annotations

import pytest

from cua.agent.loop import AgentConfig, run_discovery
from cua.artifact.compiler import compile_capability
from cua.evidence import RunDir
from cua.surface.web import WebSurface
from tests.fake_llm import FakeLLM

pytestmark = pytest.mark.integration

GOAL = "look up member {{member_id}} and read their current savings balance"
HINT = {"member_id": "100042", "username": "operator", "password": "demo-pass"}

# Same decisions as demo/lookup_savings_balance.script.json, as tool calls, so
# the LLM path and the scripted path must compile to the same artifact. One step
# carries assistant prose alongside the tool call.
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
    fake = FakeLLM(plan)
    try:
        trace = run_discovery(
            goal=GOAL, target_url=f"{mock_base_url}/login", surface=s, policy=policy,
            redactor=redactor, run_dir=rd, params_hint=HINT,
            config=AgentConfig(**cfg), llm=fake)
        return trace, fake
    finally:
        s.close()


def test_loop_completes_and_extracts_outputs(mock_base_url, policy, redactor, tmp_path):
    trace, _ = _run(PLAN, mock_base_url, policy, redactor, tmp_path)
    assert trace.outcome == "success"
    assert trace.reads["savings_balance"].value.strip() == "$4215.67"
    assert trace.reads["member_status"].value.strip() == "Active"


def test_transcript_grows_correctly(mock_base_url, policy, redactor, tmp_path):
    _, fake = _run(PLAN, mock_base_url, policy, redactor, tmp_path)
    assert len(fake.seen) == len(PLAN)
    # each call: 1 context + k*(agent + feedback) entries, k = call index
    assert [len(t) for t in fake.seen] == [1 + 2 * k for k in range(len(PLAN))]
    # the FakeLLM raised if any feedback mis-referenced a call_id


def test_llm_loop_produces_same_capability_as_scripted_path(
        mock_base_url, policy, redactor, tmp_path, capability):
    trace, _ = _run(PLAN, mock_base_url, policy, redactor, tmp_path)
    cap = compile_capability(trace, cap_id="lookup-savings-balance",
                             name="Look up member savings balance",
                             description="Look up a member and read the savings balance.",
                             redactor=redactor)
    a = cap.model_dump(exclude={"provenance"})
    b = capability.model_dump(exclude={"provenance"})
    assert a == b


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
    dests = ["/", "/members?q=a", "/members?q=b", "/members?q=c", "/members?q=d",
             "/members?q=e"]
    plan = [{"tool": "navigate", "input": {"url": f"{mock_base_url}{d}", "why": f"go {d}"}}
            for d in dests]
    trace, _ = _run(plan, mock_base_url, policy, redactor, tmp_path, max_steps=4)
    assert trace.outcome == "exhausted"
    assert len(trace.steps) == 4
