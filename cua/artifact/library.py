"""Curated per-app libraries of known business outcomes and recoverable conditions.

Discovery finds the happy path. The exceptional-state catalogue is curated once
per vendor product and attached at compile time -- a human reviewer edits it.
This is deliberate: you cannot reliably *discover* every failure mode in one
successful run, and the brief explicitly allows a curated seam here.
"""
from __future__ import annotations

from cua.artifact.schema import KnownOutcome, Recovery, RecoveryHandler
from cua.signals.dsl import (AllOf, AnyOf, AxPresent, DialogOpen, TextMatches,
                             UrlMatches)
from cua.targeting.selector import RoleName, Target


def known_outcomes(app_id: str) -> list[KnownOutcome]:
    if app_id != "cu-coreadmin":
        return []
    return [
        KnownOutcome(
            name="member_not_found",
            description="The searched member id / name matched no record. A "
                        "legitimate answer the caller must handle, not an error.",
            detect=AnyOf(of=[
                AxPresent(role="alert", name_matches=r"[Nn]o member (found|exists)"),
                TextMatches(pattern=r"[Nn]o member (found|exists) (matching|with)"),
            ]),
            returns={"found": False},
            terminal=True,
        ),
        KnownOutcome(
            name="permission_denied",
            description="The member is flagged restricted / the operator lacks "
                        "rights. A business outcome: the caller may need a "
                        "supervisor override.",
            detect=AnyOf(of=[
                TextMatches(pattern=r"Permission denied"),
                TextMatches(pattern=r"flagged restricted"),
                AxPresent(role="heading", name_matches=r"Permission denied"),
            ]),
            returns={"permitted": False},
            terminal=True,
        ),
    ]


def recovery(app_id: str) -> list[Recovery]:
    if app_id != "cu-coreadmin":
        return []
    return [
        Recovery(
            name="session_timeout",
            description="Session expired mid-flow -> bounced to the login screen. "
                        "Re-authenticate and retry the step.",
            detect=AllOf(of=[
                UrlMatches(pattern=r"/login"),
                TextMatches(pattern=r"session has expired"),
            ]),
            handle=RecoveryHandler(type="reauth"),
            max_attempts=2,
        ),
        Recovery(
            name="maintenance_notice",
            description="An unscheduled 'system notice' interstitial. Acknowledge "
                        "it and carry on.",
            detect=AllOf(of=[
                DialogOpen(expected=True),
                TextMatches(pattern=r"[Ss]cheduled maintenance|System notice"),
            ]),
            handle=RecoveryHandler(
                type="dismiss_dialog",
                target=Target(strategies=[RoleName(role="button", name="Acknowledge")],
                              rationale="The interstitial's only affordance."),
            ),
            max_attempts=2,
        ),
        Recovery(
            name="transient_slow_load",
            description="A screen that has not finished rendering its expected "
                        "content yet. Wait once and re-check before failing.",
            detect=TextMatches(pattern=r"^\s*$"),  # empty body -> nothing rendered
            handle=RecoveryHandler(type="wait_retry", wait_ms=2500),
            max_attempts=2,
        ),
    ]
