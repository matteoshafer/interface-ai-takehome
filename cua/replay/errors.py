"""The error taxonomy classifier.

Given the current observation, decide which of four things we're looking at:

* ``business_outcome`` -- matches a declared :class:`KnownOutcome`. Terminal,
  structured, *not* an error.
* ``recoverable``      -- matches a declared :class:`Recovery`. The engine applies
  the bounded handler and retries the step.
* ``hard_failure``     -- an app error screen or an undeclared modal dialog:
  conditions we can detect generically but must not push through.
* ``clear``            -- nothing wrong; proceed.

Kept as pure functions over (capability, observation) so it is exhaustively
unit-testable with synthetic observations and no browser.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

from cua.artifact.schema import Capability, KnownOutcome, Recovery
from cua.signals.evaluate import evaluate
from cua.surface.base import Observation

_APP_ERROR_TEXT = re.compile(r"(application error|unexpected error|CU-ADMIN-500)", re.I)


@dataclass
class Classification:
    kind: Literal["business_outcome", "recoverable", "hard_failure", "clear"]
    detail: str = ""
    name: Optional[str] = None
    outcome: Optional[KnownOutcome] = None
    recovery: Optional[Recovery] = None
    error_class: Optional[str] = None


def classify(cap: Capability, obs: Observation) -> Classification:
    # 1. Declared business outcomes win -- they're the expected answer.
    for ko in cap.known_outcomes:
        if evaluate(ko.detect, obs).value:
            return Classification("business_outcome", f"matched known outcome {ko.name!r}",
                                  name=ko.name, outcome=ko)

    # 2. Declared recoverable conditions.
    for rc in cap.recovery:
        if evaluate(rc.detect, obs).value:
            return Classification("recoverable", f"matched recovery {rc.name!r}",
                                  name=rc.name, recovery=rc)

    # 3. Generic hard failures we can detect without the artifact's help.
    if obs.http_status is not None and obs.http_status >= 500:
        return Classification("hard_failure", f"HTTP {obs.http_status}",
                              error_class="app_error")
    if _APP_ERROR_TEXT.search(obs.text or ""):
        return Classification("hard_failure", "app error screen text",
                              error_class="app_error")
    if obs.dialog:
        return Classification("hard_failure",
                              f"undeclared modal dialog: {obs.dialog!r}",
                              error_class="unexpected_dialog")

    return Classification("clear")
