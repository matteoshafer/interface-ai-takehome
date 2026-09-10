"""Escalation + handoff demo, self-contained (auto-operator responds after a beat).

Runs a replay that hits a hard failure (injected HTTP 500), routes an
intervention request to the operator queue with full context, waits while an
'operator' takes control, then resumes and completes the run -- all on the SAME
live browser session. Writes evidence to evidence/escalation-handoff/.
"""
from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

from cua.artifact import store
from cua.escalation.intervention import InterventionResponse, Queue
from cua.escalation.session import SessionManager
from cua.evidence import RunDir
from cua.policy.config import PolicyConfig
from cua.policy.redact import Redactor
from cua.replay.engine import replay
from cua.surface.web import WebSurface
from mockapp.server import MockServer

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "evidence/escalation-handoff"
QDIR = OUT / "queue"


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    cap = store.load(REPO / "capabilities/lookup-savings-balance.json")
    policy = PolicyConfig.load(REPO / "policies/creditunion.yaml")
    red = Redactor(policy)
    run_dir = RunDir(OUT, red)
    nav = [s.id for s in cap.steps
           if s.phase == "main" and s.action.type == "click"][-1]

    def auto_operator() -> None:
        q = Queue(QDIR)
        for _ in range(120):
            reqs = q.open_requests()
            if reqs:
                r = reqs[0]
                print(f"  [operator] intervention {r.id}: {r.kind} -- {r.reason}")
                print(f"  [operator] context: {r.ax_digest[:100]}")
                time.sleep(1.0)  # 'operator works in the live browser window'
                q.respond(InterventionResponse(
                    id=r.id, decision="resume",
                    note="Cleared the error and returned to the member record."))
                print("  [operator] handed control back")
                return
            time.sleep(0.25)

    with MockServer(port=5050):
        threading.Thread(target=auto_operator, daemon=True).start()
        s = WebSurface(headless=True)
        mgr = SessionManager(s, run_dir=run_dir, queue_dir=QDIR, wait_timeout=40)
        try:
            res = replay(
                cap, {"member_id": "100042", "username": "operator",
                      "password": "demo-pass"},
                policy=policy, surface=s, run_dir=run_dir, redactor=red,
                origin="http://localhost:5050", inject_before={nav: "error"},
                on_escalate=lambda ctx: mgr.escalate(
                    kind="replay_failure", reason=ctx.get("observed", ""),
                    capability=cap.id, step=ctx.get("step")))
        finally:
            s.close()

    print(f"  result: {res.summary().splitlines()[0]}")
    print("  control ledger: "
          + " -> ".join(f"{e.holder}({e.reason[:24]})" for e in mgr.ledger.events))


if __name__ == "__main__":
    main()
