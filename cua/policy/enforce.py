"""Enforce the allowlist and classify action risk.

Called at the single act seam -- ``cua.replay.engine`` and ``cua.agent.loop``
both route every action through :func:`check` before it touches the surface.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from cua.policy.config import PolicyConfig
from cua.surface.base import Action, ActionType


@dataclass
class Decision:
    verdict: str            # "allow" | "block" | "confirm"
    reason: str
    risky: bool = False

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"


def _origin_allowed(url: str, policy: PolicyConfig) -> bool:
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    return any(origin == o.rstrip("/") for o in policy.allowed_origins)


def _route_allowed(url: str, policy: PolicyConfig) -> bool:
    path = urlparse(url).path or "/"
    return any(fnmatch.fnmatch(path, pat) for pat in policy.allowed_routes)


def check(policy: PolicyConfig, action: Action, *, target_name: str | None = None,
          url: str | None = None) -> Decision:
    if action.type.value not in policy.allowed_actions and action.type not in (
            ActionType.FINISH, ActionType.ESCALATE):
        return Decision("block", f"action type '{action.type.value}' not in allowlist")

    if action.type == ActionType.NAVIGATE:
        dest = action.value or url or ""
        if not _origin_allowed(dest, policy):
            return Decision("block", f"origin not allowlisted: {dest}")
        if not _route_allowed(dest, policy):
            return Decision("block", f"route not allowlisted: {dest}")
        return Decision("allow", "navigation within allowlist")

    if action.type == ActionType.CLICK:
        name = target_name or (
            action.target.primary().name
            if action.target and hasattr(action.target.primary(), "name") else "")
        for pat in policy.risky_action_patterns:
            if re.search(pat, name or "", re.IGNORECASE):
                verdict = {"block": "block", "confirm": "confirm",
                           "flag": "allow"}[policy.risky_action_handling]
                return Decision(verdict,
                                f"risky control '{name}' matches /{pat}/ "
                                f"-> {policy.risky_action_handling}",
                                risky=True)
        return Decision("allow", f"safe click on '{name}'")

    return Decision("allow", f"{action.type.value} is a safe action")
