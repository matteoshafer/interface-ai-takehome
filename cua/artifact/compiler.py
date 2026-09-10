"""Compile a successful :class:`RunTrace` into a replayable :class:`Capability`.

The compiler is where "a transcript" becomes "a capability":

* it keeps only the causal, resolved actions -- no model messages, no reasoning;
* it infers typed parameters by matching typed values against the known inputs;
* it infers typed outputs from every ``read_value`` the agent performed;
* it derives per-step post-conditions and one overall checkpoint from the
  observations the agent actually saw;
* it attaches the curated known-outcome / recovery catalogue for the app.

Anything uncertain is written conservatively and is meant to be reviewed.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from cua.agent.trace import RunTrace, TraceStep
from cua.artifact import library
from cua.artifact.schema import (ActionSpec, Approval, Capability, Entry,
                                 KnownOutcome, Output, Parameter, Provenance,
                                 ReadSpec, Step, TargetApp, trace_hash)
from cua.policy.redact import Redactor
from cua.signals.dsl import AllOf, AxPresent, Signal, UrlMatches
from cua.targeting.params import parameterize_target, sanitize_target
from cua.targeting.synthesize import target_from_parts

_SECRET_PARAMS = {"username", "password", "token", "pin"}
_ACTIONABLE = {"navigate", "click", "type_text", "select_option", "read_value",
               "press_key"}


def _path_pattern(url: str) -> str:
    path = urlparse(url).path or "/"
    # turn concrete record ids into a wildcard so the pattern generalises
    path = re.sub(r"/\d{3,}", r"/\\d+", path)
    return "^" + re.escape(path).replace(re.escape(r"\d+"), r"\d+") + r"(\?|$)"


def _guess_param_type(value: str) -> tuple[str, Optional[str]]:
    if re.fullmatch(r"\d+", value):
        # numeric identifier: constrain to a digit string of a plausible length
        lo, hi = max(3, len(value) - 2), len(value) + 3
        return "string", rf"^\d{{{lo},{hi}}}$"
    return "string", None


def _value_ref(raw: str, params: dict) -> str:
    for k, v in params.items():
        if v is not None and str(v) == raw:
            return f"{{{{ {k} }}}}"
    return raw


def _number_like(v: str) -> bool:
    """True only when the whole value is a currency / plain number -- not merely
    'contains a digit' (an account number like 20-100042-52 is not a number)."""
    return bool(re.fullmatch(r"\s*\$?\s*-?[\d,]+(\.\d+)?\s*", v or ""))


def _heading_signal(h: str) -> AxPresent:
    """Keep the stable part of a heading: cut at the first separator, turn
    concrete ids into ``\\d+``. "Member 100042 - Jordan Rivera" -> "^Member \\d+"."""
    head = re.split(r"\s+[—–:-]\s+", h, maxsplit=1)[0].strip()[:40]
    pat = "^" + re.sub(r"\d+", r"\\d+", re.escape(head))
    return AxPresent(role="heading", name_matches=pat)


def _post_condition(ts: TraceStep) -> Optional[Signal]:
    ob = ts.obs_after
    if not ob:
        return None
    clauses: list[Signal] = [UrlMatches(pattern=_path_pattern(ob.url))]
    if ob.headings:
        clauses.append(_heading_signal(ob.headings[0]))
    return AllOf(of=clauses) if len(clauses) > 1 else clauses[0]


def compile_capability(
    trace: RunTrace, *, cap_id: str, name: str, description: str,
    app_id: str = "cu-coreadmin", tenant_id: Optional[str] = None,
    policy_ref: str = "policies/creditunion.yaml", version: str = "0.1.0",
    redactor: Optional[Redactor] = None,
) -> Capability:
    if trace.outcome != "success":
        raise ValueError(f"cannot compile a {trace.outcome!r} run")

    params_hint = trace.params_hint or {}

    # ---- parameters -------------------------------------------------
    used_keys: set[str] = set()
    for ts in trace.steps:
        if ts.tool == "type_text":
            raw = ts.tool_input.get("text", "")
            for k, v in params_hint.items():
                if v is not None and str(v) == raw:
                    used_keys.add(k)
        if ts.tool == "navigate":
            for k, v in params_hint.items():
                if v is not None and str(v) in ts.tool_input.get("url", ""):
                    used_keys.add(k)

    parameters: list[Parameter] = []
    for k in params_hint:
        if k not in used_keys:
            continue
        if k in _SECRET_PARAMS:
            parameters.append(Parameter(
                name=k, type="string", required=True, sensitivity="secret",
                description=f"Operator {k}; supplied per invocation, never stored."))
        else:
            ptype, pattern = _guess_param_type(str(params_hint[k]))
            parameters.append(Parameter(
                name=k, type=ptype, required=True, pattern=pattern,
                description=f"Input '{k}' for this capability.",
                example=str(params_hint[k]),
                sensitivity="pii" if "id" in k or "member" in k else "none"))

    resolved_params = {p.name: params_hint.get(p.name) for p in parameters}
    # locator strings are only rewritten for non-secret inputs
    locator_params = {p.name: params_hint.get(p.name) for p in parameters
                      if p.sensitivity != "secret"}

    # ---- steps ---------------------------------------------------
    steps: list[Step] = []
    read_step_ids: dict[str, str] = {}
    n = 0
    for ts in trace.steps:
        if ts.tool not in _ACTIONABLE or ts.error:
            continue
        if ts.tool != "navigate" and not ts.resolved:
            continue
        n += 1
        sid = f"s{n:02d}_{re.sub(r'[^a-z0-9]+', '_', (ts.intent or ts.tool).lower())[:24].strip('_')}"
        phase = "auth" if any(k in _SECRET_PARAMS and str(params_hint[k]) ==
                              ts.tool_input.get("text", "")
                              for k in params_hint) or (
            ts.tool == "click" and ts.target_name == "Sign in") else "main"

        if ts.tool == "navigate":
            url = ts.tool_input.get("url", "")
            for k, v in resolved_params.items():
                if v is not None:
                    url = url.replace(str(v), f"{{{{ {k} }}}}")
            act = ActionSpec(type="navigate", value_ref=url)
            target = None
        elif ts.tool == "press_key":
            act = ActionSpec(type="press_key", key=ts.tool_input.get("key", "Enter"))
            target = None
        else:
            kind = {"click": "click", "type_text": "type",
                    "select_option": "select", "read_value": "read"}[ts.tool]
            value_ref = None
            if ts.tool == "type_text":
                value_ref = _value_ref(ts.tool_input.get("text", ""), resolved_params)
            elif ts.tool == "select_option":
                value_ref = _value_ref(ts.tool_input.get("value", ""), resolved_params)
            act = ActionSpec(type=kind, value_ref=value_ref)
            target = target_from_parts(role=ts.target_role or "", name=ts.target_name or "",
                                       nth=ts.target_nth, row_anchor=ts.row_anchor,
                                       column_header=ts.column_header,
                                       bbox_ratio=ts.bbox_ratio)
            target = sanitize_target(parameterize_target(target, locator_params),
                                     redactor)

        risk = "risky" if (ts.policy_decision or "").startswith("confirm") else "safe"
        step = Step(
            id=sid, intent=ts.intent or ts.tool, action=act, target=target,
            target_rationale=target.rationale if target else "",
            risk=risk, phase=phase, post=_post_condition(ts),
            timeout_ms=8000,
        )
        steps.append(step)
        if ts.tool == "read_value":
            label = ts.tool_input.get("label") or ts.target_name or sid
            read_step_ids[label] = sid

    # ---- outputs ------------------------------------------------
    outputs: list[Output] = []
    for label, rec in trace.reads.items():
        sid = read_step_ids.get(label)
        if not sid:
            continue
        num = _number_like(rec.value)
        sensitive = bool(redactor and redactor.text(rec.value) != rec.value)
        if sensitive:
            num = False
        outputs.append(Output(
            name=label,
            type="number" if num else "string",
            sensitivity="pii" if sensitive else "none",
            description=(
                f"Value at the '{rec.column_header}' column of the '{rec.row_anchor}' row."
                if rec.row_anchor and rec.column_header else
                f"Value in the '{rec.row_anchor}' row." if rec.row_anchor else
                f"Value read from the '{rec.target_name}' field."),
            source_step=sid,
            read=ReadSpec(
                target=sanitize_target(parameterize_target(
                    target_from_parts(role=rec.target_role, name=rec.target_name,
                                      row_anchor=rec.row_anchor,
                                      column_header=rec.column_header),
                    locator_params), redactor),
                extract=r"([\d,]+\.?\d*)" if num else None,
                cast="number" if num else "string",
            ),
        ))

    # ---- checkpoint --------------------------------------------
    last_obs = next((s.obs_after for s in reversed(trace.steps) if s.obs_after), None)
    chk_clauses: list[Signal] = []
    if last_obs:
        chk_clauses.append(UrlMatches(pattern=_path_pattern(last_obs.url)))
        if last_obs.headings:
            chk_clauses.append(_heading_signal(last_obs.headings[0]))
    checkpoint: Signal = (AllOf(of=chk_clauses) if len(chk_clauses) > 1
                          else (chk_clauses[0] if chk_clauses
                                else UrlMatches(pattern=r".")))

    # ---- envelope ---------------------------------------------
    first_act = next((s for s in trace.steps
                      if s.tool in _ACTIONABLE and not s.error and s.obs_before), None)
    if first_act and first_act.obs_before:
        u = urlparse(first_act.obs_before.url)
        entry_url = f"{u.scheme}://{u.netloc}{u.path}"
    else:
        entry_url = trace.target
    entry_pattern = _path_pattern(entry_url)

    public = trace.to_public(redactor) if redactor else {}
    th = trace_hash(json.dumps(public, sort_keys=True)) if redactor else "unhashed"

    return Capability(
        id=cap_id, version=version, name=name, description=description,
        target=TargetApp(app_id=app_id, tenant_id=tenant_id,
                         entry=Entry(url=entry_url, url_pattern=entry_pattern)),
        policy_ref=policy_ref,
        parameters=parameters,
        outputs=outputs,
        steps=steps,
        checkpoint=checkpoint,
        known_outcomes=library.known_outcomes(app_id),
        recovery=library.recovery(app_id),
        approval=Approval(state="draft"),
        provenance=Provenance(
            discovered_by_model=trace.model,
            discovered_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            trace_hash=th,
            raw_step_count=len(trace.steps),
        ),
    )
