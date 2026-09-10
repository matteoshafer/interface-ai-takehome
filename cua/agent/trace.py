"""The raw record of a discovery run.

Kept deliberately separate from the compiled :class:`Capability`: the trace has
the model's turn-by-turn behaviour and raw field values (needed in-memory to
infer which typed value was which parameter); the capability has only the
reusable flow. The trace written to ``evidence/`` is redacted; the in-memory
object the compiler reads is not.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ObsBrief:
    url: str
    title: str
    http_status: Optional[int]
    dialog: Optional[str]
    headings: list[str]
    alerts: list[str]
    node_count: int

    @classmethod
    def of(cls, obs) -> "ObsBrief":
        return cls(
            url=obs.url, title=obs.title, http_status=obs.http_status,
            dialog=obs.dialog,
            headings=[n.name for n in obs.nodes if n.role == "heading"],
            alerts=[f"{n.role}: {n.name}" for n in obs.nodes
                    if n.role in ("alert", "status")],
            node_count=len(obs.nodes),
        )


@dataclass
class TraceStep:
    index: int
    tool: str
    tool_input: dict
    intent: str = ""
    target_role: Optional[str] = None
    target_name: Optional[str] = None
    target_nth: int = 0
    resolved: bool = False
    matched_strategy: Optional[str] = None
    strategy_index: Optional[int] = None
    bbox_ratio: Optional[tuple[float, float]] = None
    row_anchor: Optional[str] = None
    column_header: Optional[str] = None
    obs_before: Optional[ObsBrief] = None
    obs_after: Optional[ObsBrief] = None
    policy_decision: Optional[str] = None
    error: Optional[str] = None
    note: str = ""


@dataclass
class ReadRecord:
    label: str
    value: str
    target_role: str
    target_name: str
    step_index: int
    row_anchor: Optional[str] = None
    column_header: Optional[str] = None


@dataclass
class RunTrace:
    goal: str
    target: str
    model: str
    policy_ref: str
    params_hint: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    steps: list[TraceStep] = field(default_factory=list)
    reads: dict[str, ReadRecord] = field(default_factory=dict)
    outcome: str = "exhausted"          # success | escalated | exhausted | failed | aborted
    outputs: dict = field(default_factory=dict)
    summary: str = ""
    escalation: Optional[dict] = None

    def to_public(self, redactor) -> dict:
        """Redacted, disk-safe view for evidence/."""
        def rr(v):
            return redactor.value(v)
        return {
            "goal": self.goal, "target": self.target, "model": self.model,
            "policy_ref": self.policy_ref,
            "params_hint": {k: ("<secret>" if k in ("password", "username")
                                else rr(v)) for k, v in self.params_hint.items()},
            "started_at": self.started_at, "finished_at": self.finished_at,
            "outcome": self.outcome, "summary": rr(self.summary),
            "outputs": rr(self.outputs),
            "escalation": rr(self.escalation) if self.escalation else None,
            "steps": [
                {
                    "index": s.index, "tool": s.tool, "intent": rr(s.intent),
                    "target": (f"{s.target_role}:{s.target_name}"
                               if s.target_role else None),
                    "tool_input": rr({k: v for k, v in s.tool_input.items()
                                      if k != "text"}
                                     | ({"text": "<redacted>"} if "text" in s.tool_input
                                        else {})),
                    "resolved": s.resolved, "matched_strategy": s.matched_strategy,
                    "strategy_index": s.strategy_index,
                    "policy_decision": s.policy_decision,
                    "error": rr(s.error) if s.error else None,
                    "obs_after": rr(s.obs_after.__dict__) if s.obs_after else None,
                }
                for s in self.steps
            ],
        }
