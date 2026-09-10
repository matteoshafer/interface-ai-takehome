"""Allowlist enforcement, risk classification, and redaction."""
from __future__ import annotations

from cua.policy.config import PolicyConfig
from cua.policy.enforce import check
from cua.policy.redact import Redactor
from cua.surface.base import Action, ActionType
from cua.targeting.selector import RoleName, Target


def _policy() -> PolicyConfig:
    return PolicyConfig(
        allowed_origins=["http://localhost:5050"],
        allowed_routes=["/", "/login", "/member/*"],
        risky_action_patterns=[r"(?i)\b(confirm and create|transfer|delete)\b"],
        risky_action_handling="confirm",
        redaction={"patterns": [r"\b\d{3}-\d{2}-\d{4}\b"],
                   "field_names": ["password", "ssn"]},
    )


def test_navigation_allowlist():
    p = _policy()
    assert check(p, Action(type=ActionType.NAVIGATE, value="http://localhost:5050/member/42")).allowed
    assert not check(p, Action(type=ActionType.NAVIGATE, value="http://evil.com/x")).allowed
    assert not check(p, Action(type=ActionType.NAVIGATE, value="http://localhost:5050/admin")).allowed


def test_action_type_allowlist():
    p = _policy()
    p.allowed_actions = ["navigate", "click", "read"]
    assert check(p, Action(type=ActionType.CLICK),
                 target_name="Open").allowed
    assert check(p, Action(type=ActionType.TYPE)).verdict == "block"


def test_risky_action_requires_confirmation():
    p = _policy()
    safe = check(p, Action(type=ActionType.CLICK), target_name="Search")
    risky = check(p, Action(type=ActionType.CLICK),
                  target_name="Confirm and create account")
    assert safe.allowed and not safe.risky
    assert risky.verdict == "confirm" and risky.risky


def test_redaction_by_pattern_and_field_is_stable():
    r = Redactor(_policy())
    a = r.text("SSN on file: 312-91-9369 today")
    b = r.text("also 312-91-9369")
    assert "312-91-9369" not in a
    assert a.split("today")[0].strip().split()[-1] == b.split()[-1]  # same token
    doc = r.value({"password": "hunter2", "note": "ok", "ssn": "111-22-3333"})
    assert doc["password"].startswith("<redacted:") and doc["note"] == "ok"
    assert doc["ssn"].startswith("<redacted:")
