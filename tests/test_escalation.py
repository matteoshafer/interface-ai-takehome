"""Intervention queue + the control-transfer round-trip."""
from __future__ import annotations

import threading
import time

import pytest

from cua.escalation.intervention import (InterventionRequest, InterventionResponse,
                                         Queue)
from cua.escalation.ledger import ControlLedger


def test_queue_submit_open_respond_wait(tmp_path):
    q = Queue(tmp_path / "q")
    req = q.submit(InterventionRequest(kind="risky_action", reason="confirm create"))
    assert [r.id for r in q.open_requests()] == [req.id]

    def operator():
        time.sleep(0.3)
        q.respond(InterventionResponse(id=req.id, decision="resume", note="did it"))

    threading.Thread(target=operator, daemon=True).start()
    resp = q.wait(req.id, poll=0.1, timeout=5)
    assert resp.decision == "resume" and resp.note == "did it"
    assert q.open_requests() == []  # resolved -> no longer open


def test_ledger_tracks_control_custody(tmp_path):
    led = ControlLedger(tmp_path / "ledger.jsonl")
    assert led.holder == "automation"
    led.cede_to_operator("stuck: dead end")
    assert led.holder == "operator"
    led.reclaim("operator resumed")
    assert led.holder == "automation"
    assert [e.holder for e in led.events] == ["automation", "operator", "automation"]


@pytest.mark.integration
def test_session_manager_handoff_completes_run(capability, policy, redactor,
                                               tmp_path, mock_base_url):
    from cua.evidence import RunDir
    from cua.escalation.session import SessionManager
    from cua.replay.engine import replay
    from cua.surface.web import WebSurface

    qdir = tmp_path / "queue"
    rd = RunDir(tmp_path / "run", redactor)

    def auto_operator():
        q = Queue(qdir)
        for _ in range(80):
            reqs = q.open_requests()
            if reqs:
                q.respond(InterventionResponse(
                    id=reqs[0].id, decision="resume",
                    note="Recovered the session by hand."))
                return
            time.sleep(0.25)

    threading.Thread(target=auto_operator, daemon=True).start()
    s = WebSurface(headless=True)
    mgr = SessionManager(s, run_dir=rd, queue_dir=qdir, wait_timeout=30)
    nav = [st.id for st in capability.steps
           if st.phase == "main" and st.action.type == "click"][-1]
    try:
        r = replay(capability, {"member_id": "100042", "username": "operator",
                                "password": "demo-pass"},
                   policy=policy, surface=s, run_dir=rd, redactor=redactor,
                   origin=mock_base_url, inject_before={nav: "error"},
                   on_escalate=lambda ctx: mgr.escalate(
                       kind="replay_failure", reason=ctx.get("observed", ""),
                       capability=capability.id, step=ctx.get("step")))
    finally:
        s.close()

    assert r.outcome == "success"
    assert [e.holder for e in mgr.ledger.events] == ["automation", "operator", "automation"]
