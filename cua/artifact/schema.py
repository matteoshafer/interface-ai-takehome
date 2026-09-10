"""The capability artifact -- the focal point of the design.

A capability is what the model *discovers once* and what an AI agent *invokes
many times* in production. So it is written as a contract, not a macro:

* ``parameters`` / ``outputs`` are typed and carry a sensitivity tag -- a calling
  agent knows exactly what to pass and what it gets back, and redaction reads the
  same tags.
* every ``Step`` targets its control through an ordered
  :class:`~cua.targeting.selector.Target` (strategies, strongest first) and
  carries the human-written ``target_rationale`` the brief asks for.
* the "did it work?" questions -- step ``pre``/``post``, the overall
  ``checkpoint``, and the ``detect`` clauses of ``known_outcomes`` and
  ``recovery`` -- are all one reusable :data:`~cua.signals.dsl.Signal` predicate.
* ``known_outcomes`` (expected business results), ``recovery`` (bounded
  auto-handling) and everything-else (hard failure) are distinguished *in the
  schema*, not guessed at runtime.
* the artifact is versioned, keyed by ``app_id`` (not tenant), and reviewable by
  both a human and a machine.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from cua.signals.dsl import Signal
from cua.targeting.selector import Target

SCHEMA_VERSION = "1.0"

Sensitivity = Literal["none", "pii", "secret"]


class ParamError(ValueError):
    """Raised when replay inputs don't satisfy the parameter contract."""


# --------------------------------------------------------------------------- #
# inputs / outputs
# --------------------------------------------------------------------------- #
class Parameter(BaseModel):
    name: str
    type: Literal["string", "number", "boolean"] = "string"
    required: bool = True
    pattern: Optional[str] = None          # regex, full-match, for string params
    description: str = ""
    sensitivity: Sensitivity = "none"
    example: Optional[str] = None


class ReadSpec(BaseModel):
    """How replay re-extracts one output value deterministically."""
    target: Target
    extract: Optional[str] = None          # regex; group(1) if present, else group(0)
    cast: Literal["string", "number", "boolean"] = "string"


class Output(BaseModel):
    name: str
    type: Literal["string", "number", "boolean", "object", "array"] = "string"
    description: str = ""
    source_step: str                       # id of the READ step that produced it
    read: ReadSpec
    sensitivity: Sensitivity = "none"


# --------------------------------------------------------------------------- #
# steps
# --------------------------------------------------------------------------- #
class ActionSpec(BaseModel):
    type: Literal["navigate", "click", "type", "select", "press_key", "read", "wait"]
    value_ref: Optional[str] = None        # "{{ param }}" or a literal, for type/select/navigate
    key: Optional[str] = None              # for press_key
    ms: Optional[int] = None               # for wait


class Step(BaseModel):
    id: str
    intent: str                            # human-readable purpose (NOT model reasoning)
    action: ActionSpec
    target: Optional[Target] = None        # None for navigate / wait / press_key
    target_rationale: str = ""             # why this targeting is robust (brief 3.2)
    risk: Literal["safe", "risky"] = "safe"
    # "auth" steps are re-executed by the reauth recovery handler after a
    # session timeout; "main" steps carry the actual task.
    phase: Literal["auth", "main"] = "main"
    pre: Optional[Signal] = None
    post: Optional[Signal] = None
    timeout_ms: int = 8000


# --------------------------------------------------------------------------- #
# outcomes / recovery
# --------------------------------------------------------------------------- #
class KnownOutcome(BaseModel):
    """An expected *business* result. Not an error -- the caller needs to know."""
    name: str
    detect: Signal
    returns: Dict[str, Any] = Field(default_factory=dict)
    terminal: bool = True
    description: str = ""


class RecoveryHandler(BaseModel):
    type: Literal["dismiss_dialog", "wait_retry", "reauth"]
    target: Optional[Target] = None        # for dismiss_dialog
    wait_ms: int = 1500


class Recovery(BaseModel):
    """A recoverable runtime condition + the bounded action that clears it."""
    name: str
    detect: Signal
    handle: RecoveryHandler
    max_attempts: int = 2
    description: str = ""


# --------------------------------------------------------------------------- #
# envelope
# --------------------------------------------------------------------------- #
class Entry(BaseModel):
    url: str                               # concrete, may contain {{param}}
    url_pattern: str                       # regex the entry screen URL must match


class TargetApp(BaseModel):
    surface_type: Literal["web"] = "web"
    app_id: str                            # the vendor product identity
    tenant_id: Optional[str] = None        # None => tenant-agnostic base capability
    entry: Entry


class Approval(BaseModel):
    state: Literal["draft", "approved"] = "draft"
    approved_by: Optional[str] = None
    note: str = ""


class Provenance(BaseModel):
    discovered_by_model: str
    discovered_at: str
    trace_hash: str                        # sha256 of the redacted discovery trace
    raw_step_count: int
    stability: Optional[Dict[str, Any]] = None


class Capability(BaseModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    version: str = "0.1.0"
    name: str
    description: str
    target: TargetApp
    policy_ref: str
    parameters: List[Parameter] = Field(default_factory=list)
    outputs: List[Output] = Field(default_factory=list)
    steps: List[Step]
    checkpoint: Signal
    known_outcomes: List[KnownOutcome] = Field(default_factory=list)
    recovery: List[Recovery] = Field(default_factory=list)
    approval: Approval = Field(default_factory=Approval)
    provenance: Provenance

    # ---- parameter contract ------------------------------------------
    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        resolved: Dict[str, Any] = {}
        for p in self.parameters:
            if p.name not in params or params[p.name] is None:
                if p.required:
                    raise ParamError(f"missing required parameter: {p.name!r}")
                continue
            raw = params[p.name]
            try:
                if p.type == "number":
                    val: Any = float(raw)
                elif p.type == "boolean":
                    val = raw if isinstance(raw, bool) else str(raw).lower() in (
                        "1", "true", "yes")
                else:
                    val = str(raw)
                    if p.pattern and not re.fullmatch(p.pattern, val):
                        raise ParamError(
                            f"parameter {p.name!r}={val!r} does not match /{p.pattern}/")
            except (TypeError, ValueError) as e:
                raise ParamError(f"parameter {p.name!r}: {e}") from e
            resolved[p.name] = val
        extra = set(params) - {p.name for p in self.parameters}
        if extra:
            raise ParamError(f"unknown parameter(s): {sorted(extra)}")
        return resolved

    def render_template(self, s: str, params: Dict[str, Any]) -> str:
        """Substitute every ``{{ name }}`` in an arbitrary string (e.g. entry URL)."""
        def sub(m: "re.Match") -> str:
            key = m.group(1)
            if key not in params:
                raise ParamError(f"template references unknown parameter {key!r}")
            v = params[key]
            return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
        return re.sub(r"\{\{\s*(\w+)\s*\}\}", sub, s)

    def render_value(self, value_ref: Optional[str], params: Dict[str, Any]) -> str:
        """Resolve a step's ``value_ref`` -- ``{{ name }}`` -> param, else literal."""
        if value_ref is None:
            return ""
        m = re.fullmatch(r"\s*\{\{\s*(\w+)\s*\}\}\s*", value_ref)
        if m:
            key = m.group(1)
            if key not in params:
                raise ParamError(f"step references unknown parameter {key!r}")
            v = params[key]
            return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
        return value_ref

    # ---- agent-facing contract (catalog / tool schema) -------------
    def contract(self) -> Dict[str, Any]:
        def jtype(t: str) -> str:
            return {"number": "number", "boolean": "boolean"}.get(t, "string")

        return {
            "name": self.id,
            "version": self.version,
            "summary": self.description,
            "approval": self.approval.state,
            "input_schema": {
                "type": "object",
                "properties": {
                    p.name: {"type": jtype(p.type), "description": p.description,
                             **({"pattern": p.pattern} if p.pattern else {})}
                    for p in self.parameters
                },
                "required": [p.name for p in self.parameters if p.required],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    o.name: {"type": o.type, "description": o.description}
                    for o in self.outputs
                },
            },
            "known_outcomes": [
                {"name": k.name, "description": k.description, "returns": k.returns}
                for k in self.known_outcomes
            ],
        }


def trace_hash(redacted_trace_json: str) -> str:
    return hashlib.sha256(redacted_trace_json.encode("utf-8")).hexdigest()
