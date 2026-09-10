"""SessionManager -- owns the one live surface and mediates control transfer.

Control-transfer model:

* The surface (a single headed browser context) is long-lived and owned here.
* Automation runs only while ``ledger.holder == "automation"``.
* On escalation the manager writes an :class:`InterventionRequest` carrying full
  context, cedes the token to the operator, and blocks polling the queue.
* The operator drives the **same** window, then clicks Resume/Abort in the
  console; the manager records their note, reclaims the token, and returns the
  decision so the run can continue or stop.

Nothing about the browser session is torn down or recreated across the handoff.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from cua.escalation.intervention import (InterventionRequest, InterventionResponse,
                                         Queue)
from cua.escalation.ledger import ControlLedger
from cua.evidence import RunDir


class SessionManager:
    def __init__(self, surface, *, run_dir: RunDir, queue_dir: str | Path,
                 wait_timeout: Optional[float] = None) -> None:
        self.surface = surface
        self.run = run_dir
        self.queue = Queue(queue_dir)
        self.ledger = ControlLedger(run_dir.path("control_ledger.jsonl"))
        self.wait_timeout = wait_timeout

    def escalate(self, *, kind: str, reason: str, capability: Optional[str] = None,
                 goal: Optional[str] = None, step: Optional[str] = None) -> str:
        """Raise an intervention, hand the live session to a human, block until
        they resume or abort. Returns ``"resume"`` or ``"abort"``."""
        obs = self.surface.observe()
        shot = str(self.run.path(f"intervention_{kind}.png"))
        try:
            self.surface.screenshot(shot)
        except Exception:
            shot = None

        digest = (f"url={obs.url} title={obs.title!r} "
                  f"headings={[n.name for n in obs.nodes if n.role == 'heading'][:3]} "
                  f"dialog={obs.dialog!r} http={obs.http_status}")

        req = InterventionRequest(
            kind=kind, reason=reason, url=obs.url, capability=capability,
            goal=goal, step=step, ax_digest=digest, screenshot=shot,
            run_dir=str(self.run.root))
        self.queue.submit(req)
        self.ledger.cede_to_operator(f"{kind}: {reason}")
        self.run.event("control_ceded", request_id=req.id, intervention_kind=kind,
                       reason=reason, digest=digest)

        resp: InterventionResponse = self.queue.wait(
            req.id, timeout=self.wait_timeout)

        before = digest
        after = self.surface.observe()
        after_digest = (f"url={after.url} headings="
                        f"{[n.name for n in after.nodes if n.role == 'heading'][:3]}")
        self.ledger.reclaim(f"operator {resp.decision}: {resp.note or '-'}")
        self.run.event("control_reclaimed", request_id=req.id,
                       decision=resp.decision, operator_note=resp.note,
                       state_before=before, state_after=after_digest)
        self.run.write_json(f"intervention_{req.id}.json", {
            "request": req.model_dump(), "response": resp.model_dump(),
            "state_before": before, "state_after": after_digest,
        })
        return resp.decision
