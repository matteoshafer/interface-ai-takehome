"""The intervention request/response envelope and its file-backed queue.

A file queue (a directory of JSON) is deliberately the simplest thing that gives
a real seam: the automation process writes a request and blocks polling for a
response; a separate operator-console process (or a human with an editor) writes
the response. Swap the directory for a real queue/table without touching either
side's logic.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class InterventionRequest(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    created_at: str = Field(default_factory=_now)
    kind: str                       # discovery_stuck | replay_failure | risky_action
    reason: str
    url: str = ""
    capability: Optional[str] = None
    goal: Optional[str] = None
    step: Optional[str] = None
    ax_digest: str = ""
    screenshot: Optional[str] = None
    run_dir: Optional[str] = None
    status: str = "open"            # open | resolved


class InterventionResponse(BaseModel):
    id: str
    decision: str                   # resume | abort
    note: str = ""                  # what the operator did / decided
    operator: str = "operator"
    resolved_at: str = Field(default_factory=_now)


class Queue:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _req(self, rid: str) -> Path:
        return self.root / f"{rid}.request.json"

    def _resp(self, rid: str) -> Path:
        return self.root / f"{rid}.response.json"

    def submit(self, req: InterventionRequest) -> InterventionRequest:
        self._req(req.id).write_text(req.model_dump_json(indent=2))
        return req

    def open_requests(self) -> list[InterventionRequest]:
        out = []
        for p in sorted(self.root.glob("*.request.json")):
            req = InterventionRequest.model_validate_json(p.read_text())
            if not self._resp(req.id).exists():
                out.append(req)
        return out

    def get(self, rid: str) -> Optional[InterventionRequest]:
        p = self._req(rid)
        return InterventionRequest.model_validate_json(p.read_text()) if p.exists() else None

    def respond(self, resp: InterventionResponse) -> None:
        self._resp(resp.id).write_text(resp.model_dump_json(indent=2))

    def response(self, rid: str) -> Optional[InterventionResponse]:
        p = self._resp(rid)
        return InterventionResponse.model_validate_json(p.read_text()) if p.exists() else None

    def wait(self, rid: str, *, poll: float = 1.0,
             timeout: Optional[float] = None) -> InterventionResponse:
        start = time.time()
        while True:
            r = self.response(rid)
            if r is not None:
                return r
            if timeout is not None and time.time() - start > timeout:
                raise TimeoutError(f"no operator response for {rid} within {timeout}s")
            time.sleep(poll)
