"""Policy config: the allowlist + risk rules + redaction rules for a target app.

Loaded from YAML (see ``policies/creditunion.yaml``) and referenced by every
capability. The same config object governs both the discovery run and every
replay, so the agent can never do in discovery what replay would refuse.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Literal

import yaml
from pydantic import BaseModel, Field


class RedactionConfig(BaseModel):
    # regexes matched against every string before it is persisted anywhere
    patterns: List[str] = Field(default_factory=list)
    # parameter / output / form-field names whose *values* must never be stored raw
    field_names: List[str] = Field(default_factory=list)


class PolicyConfig(BaseModel):
    allowed_origins: List[str]
    allowed_routes: List[str] = Field(default_factory=lambda: ["**"])
    allowed_actions: List[str] = Field(
        default_factory=lambda: ["navigate", "click", "type", "select",
                                 "press_key", "read", "wait"])
    # accessible-name regexes that mark a click as risky / irreversible
    risky_action_patterns: List[str] = Field(default_factory=list)
    risky_action_handling: Literal["block", "confirm", "flag"] = "confirm"
    redaction: RedactionConfig = Field(default_factory=RedactionConfig)

    @classmethod
    def load(cls, path: str | Path) -> "PolicyConfig":
        data = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(data)
