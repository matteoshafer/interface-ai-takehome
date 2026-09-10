"""The structured result replay returns to its caller.

Three outcomes, kept distinct on purpose (the brief calls conflating them the
most common mistake):

* ``success``          -- checkpoint verified, ``outputs`` populated.
* ``business_outcome`` -- a declared, expected result the caller must handle
  ("no such member"). Not an error.
* ``failure``          -- something went wrong; ``error_class`` + ``failed_step``
  + ``expected`` / ``observed`` + an ``evidence_dir`` say what and where.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ErrorClass = Literal[
    "selector_missing", "selector_ambiguous", "precondition_failed",
    "postcondition_failed", "checkpoint_failed", "unexpected_dialog",
    "recovery_exhausted", "app_error", "timeout", "policy_blocked",
    "needs_approval", "bad_params",
]


class StepReport(BaseModel):
    index: int
    step_id: str
    intent: str
    action: str
    status: Literal["ok", "recovered", "failed", "skipped"]
    matched_strategy: Optional[str] = None      # e.g. "role_name" / "anchor"
    strategy_rank: Optional[int] = None         # 0 = primary; >0 = a fallback fired
    recoveries: List[str] = Field(default_factory=list)
    duration_ms: int = 0
    note: str = ""


class ReplayResult(BaseModel):
    outcome: Literal["success", "business_outcome", "failure"]
    capability_id: str
    capability_version: str
    params: Dict[str, Any] = Field(default_factory=dict)   # already redacted
    steps: List[StepReport] = Field(default_factory=list)
    duration_ms: int = 0

    # success
    outputs: Optional[Dict[str, Any]] = None

    # business_outcome
    business_outcome: Optional[str] = None
    business_data: Optional[Dict[str, Any]] = None
    at_step: Optional[str] = None

    # failure
    error_class: Optional[ErrorClass] = None
    failed_step: Optional[str] = None
    expected: Optional[str] = None
    observed: Optional[str] = None
    evidence_dir: Optional[str] = None

    def summary(self) -> str:
        if self.outcome == "success":
            return f"SUCCESS  outputs={self.outputs}"
        if self.outcome == "business_outcome":
            return (f"BUSINESS OUTCOME  {self.business_outcome}  "
                    f"data={self.business_data}  (at {self.at_step})")
        return (f"FAILURE  {self.error_class}  step={self.failed_step}\n"
                f"  expected: {self.expected}\n  observed: {self.observed}\n"
                f"  evidence: {self.evidence_dir}")
