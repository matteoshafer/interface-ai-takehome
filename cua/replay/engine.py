"""Deterministic replay -- the production execution path. No LLM.

Given a saved :class:`Capability` and a set of input parameters, re-run the
recorded steps with stable targeting, classify every observation against the
error taxonomy, verify the checkpoint, and return a structured
:class:`~cua.replay.result.ReplayResult`.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from cua.artifact.schema import Capability, ParamError, Step
from cua.evidence import RunDir
from cua.policy.config import PolicyConfig
from cua.policy.enforce import check as policy_check
from cua.policy.redact import Redactor
from cua.replay.errors import Classification, classify
from cua.replay.result import ReplayResult, StepReport
from cua.signals.evaluate import evaluate
from cua.surface.base import Observation, Surface
from cua.targeting.params import render_target
from cua.targeting.resolver import resolve

# on_escalate(context: dict) -> "resume" | "abort"
EscalateFn = Callable[[Dict[str, Any]], str]


class _Fail(Exception):
    def __init__(self, error_class: str, step: Optional[str], expected: str,
                 observed: str) -> None:
        super().__init__(f"{error_class} at {step}")
        self.error_class = error_class
        self.step = step
        self.expected = expected
        self.observed = observed


def _obs_digest(obs: Observation) -> str:
    heads = [n.name for n in obs.nodes if n.role == "heading"][:2]
    alerts = [n.name for n in obs.nodes if n.role in ("alert", "status")][:2]
    return (f"url={obs.url} status={obs.http_status} title={obs.title!r} "
            f"headings={heads} alerts={alerts} dialog={obs.dialog!r}")


class ReplayEngine:
    def __init__(self, cap: Capability, policy: PolicyConfig, *,
                 surface: Surface, run_dir: RunDir, redactor: Redactor,
                 on_escalate: Optional[EscalateFn] = None,
                 inject_before: Optional[Dict[str, str]] = None,
                 origin: str = "") -> None:
        self.cap = cap
        self.policy = policy
        self.surface = surface
        self.run = run_dir
        self.redactor = redactor
        self.on_escalate = on_escalate
        self.inject_before = inject_before or {}   # {step_id: condition}
        self.origin = origin.rstrip("/")
        self._reads: Dict[str, str] = {}
        self._obs_by_step: Dict[str, Observation] = {}
        self._operator_handled: set[str] = set()   # steps a human performed live

    # ------------------------------------------------------------------ #
    def run_replay(self, params: Dict[str, Any]) -> ReplayResult:
        t0 = time.time()
        base = dict(capability_id=self.cap.id,
                    capability_version=self.cap.version)
        try:
            resolved = self.cap.validate_params(params)
        except ParamError as e:
            self.run.event("bad_params", error=str(e))
            return ReplayResult(outcome="failure", error_class="bad_params",
                                expected="valid parameters per the capability contract",
                                observed=str(e), **base)

        red_params = self.redactor.value({
            p.name: ("<supplied>" if p.sensitivity == "secret" else resolved.get(p.name))
            for p in self.cap.parameters if p.name in resolved
        })
        self.run.event("replay_start", capability=self.cap.id,
                       version=self.cap.version, params=red_params)

        reports: list[StepReport] = []
        try:
            entry = self.cap.render_template(self.cap.target.entry.url, resolved)
            self.surface.goto(entry)
            obs = self.surface.observe()
            self.run.event("entry", url=obs.url, digest=_obs_digest(obs))

            for i, step in enumerate(self.cap.steps):
                cond = self.inject_before.get(step.id)
                if cond and self.origin and hasattr(self.surface, "side_effect_get"):
                    self.surface.side_effect_get(f"{self.origin}/_inject/{cond}")
                    self.run.event("fault_injected", before_step=step.id, condition=cond)
                attempts = 0
                while True:
                    attempts += 1
                    try:
                        rep = self._run_step(i, step, resolved)
                        break
                    except _BusinessSignal as b:
                        return self._business(b.cls, reports, b.at_step, t0, base)
                    except _Fail as f:
                        # A hard failure we couldn't auto-recover from: route it to
                        # a human if one is available, then retry once on resume.
                        if (self.on_escalate is None or attempts > 2
                                or f.error_class in ("bad_params", "policy_blocked",
                                                     "needs_approval")):
                            raise
                        decision = self._escalate_hard(f, step)
                        if decision != "resume":
                            raise
                        # Operator handed control back. Re-establish the
                        # navigation position (their data fixes persist; their
                        # navigation is safely redone), then retry the step.
                        self._restore_position(i, resolved)
                reports.append(rep)

            final = self.surface.observe()
            self._obs_by_step["__final__"] = final

            # a business outcome may only become visible at the end
            cls = classify(self.cap, final)
            if cls.kind == "business_outcome":
                return self._business(cls, reports, "__final__", t0, base)

            chk = evaluate(self.cap.checkpoint, final)
            self.run.event("checkpoint", passed=chk.value, trace=chk.trace)
            if not chk.value:
                raise _Fail("checkpoint_failed", "checkpoint",
                            "; ".join(chk.trace), _obs_digest(final))

            outputs = self._extract_outputs()
            self.run.event("replay_success", outputs=outputs)
            res = ReplayResult(outcome="success", outputs=outputs, steps=reports,
                               params=red_params,
                               duration_ms=int((time.time() - t0) * 1000), **base)
            self.run.write_json("result.json", res)
            return res

        except _Fail as f:
            return self._failure(f, reports, red_params, t0, base)

    # ------------------------------------------------------------------ #
    def _run_step(self, index: int, step: Step, params: Dict[str, Any]) -> StepReport:
        started = time.time()
        rep = StepReport(index=index, step_id=step.id, intent=step.intent,
                         action=step.action.type, status="ok")
        recovery_budget = {r.name: r.max_attempts for r in self.cap.recovery}
        loop_guard = 0

        while True:
            loop_guard += 1
            if loop_guard > 6:
                raise _Fail("recovery_exhausted", step.id,
                            "step to complete within a bounded number of retries",
                            "too many recovery/handoff cycles without progress")
            obs = self.surface.observe()

            cls = classify(self.cap, obs)
            if cls.kind == "business_outcome":
                raise _BusinessSignal(cls, step.id)
            if cls.kind == "hard_failure":
                raise _Fail(cls.error_class or "app_error", step.id,
                            "no error condition", cls.detail)
            if cls.kind == "recoverable":
                if recovery_budget.get(cls.name, 0) <= 0:
                    raise _Fail("recovery_exhausted", step.id,
                                f"recover from {cls.name}", cls.detail)
                recovery_budget[cls.name] -= 1
                self._apply_recovery(cls, params, index)
                rep.recoveries.append(cls.name)
                rep.status = "recovered"
                continue

            # If a recovery -- or a human handoff -- has already put us at (or
            # past) this step's target state, the step is done; don't repeat it.
            done_externally = rep.recoveries or step.id in self._operator_handled
            if done_externally and step.post is not None and evaluate(step.post, obs).value:
                rep.duration_ms = int((time.time() - started) * 1000)
                rep.note = ("satisfied after operator handoff"
                            if step.id in self._operator_handled
                            else "satisfied after recovery")
                self.run.event("step", index=index, id=step.id, intent=step.intent,
                               action=step.action.type, recoveries=rep.recoveries,
                               note=rep.note, digest=_obs_digest(obs))
                return rep

            if step.pre is not None:
                pre = evaluate(step.pre, obs)
                if not pre.value:
                    raise _Fail("precondition_failed", step.id,
                                "; ".join(pre.trace), _obs_digest(obs))

            try:
                matched = self._act(step, obs, params)
            except _Escalated as e:
                if e.decision == "abort":
                    raise _Fail("policy_blocked", step.id, e.expected, "operator aborted")
                # operator took control of the live session and performed this
                # (risky) step by hand -- don't repeat the action.
                self._operator_handled.add(step.id)
                rep.recoveries.append("operator_handoff")
                continue
            rep.matched_strategy = matched[0]
            rep.strategy_rank = matched[1]

            after = self.surface.observe()
            self._obs_by_step[step.id] = after

            cls2 = classify(self.cap, after)
            if cls2.kind == "business_outcome":
                raise _BusinessSignal(cls2, step.id)
            if cls2.kind == "hard_failure":
                raise _Fail(cls2.error_class or "app_error", step.id,
                            "no error condition", cls2.detail)
            if cls2.kind == "recoverable":
                if recovery_budget.get(cls2.name, 0) <= 0:
                    raise _Fail("recovery_exhausted", step.id,
                                f"recover from {cls2.name}", cls2.detail)
                recovery_budget[cls2.name] -= 1
                self._apply_recovery(cls2, params, index)
                rep.recoveries.append(cls2.name)
                rep.status = "recovered"
                continue  # re-attempt the whole step now that state is restored

            if step.post is not None:
                post = evaluate(step.post, after)
                if not post.value:
                    raise _Fail("postcondition_failed", step.id,
                                "; ".join(post.trace), _obs_digest(after))

            rep.duration_ms = int((time.time() - started) * 1000)
            self.run.event("step", index=index, id=step.id, intent=step.intent,
                           action=step.action.type, matched=rep.matched_strategy,
                           rank=rep.strategy_rank, recoveries=rep.recoveries,
                           digest=_obs_digest(after))
            return rep

    # ------------------------------------------------------------------ #
    def _act(self, step: Step, obs: Observation, params: Dict[str, Any]):
        a = step.action
        if a.type == "navigate":
            url = self.cap.render_template(a.value_ref or "", params)
            dec = policy_check(self.policy, _mk_action("navigate", value=url), url=url)
            if not dec.allowed:
                raise _Fail("policy_blocked", step.id, "navigation on allowlist", dec.reason)
            self.surface.goto(url)
            return ("navigate", None)
        if a.type == "wait":
            time.sleep((a.ms or 500) / 1000.0)
            return ("wait", None)
        if a.type == "press_key":
            self.surface.press_key(a.key or "Enter")
            return ("press_key", None)

        # everything else needs a resolved target
        tgt = render_target(step.target, params)
        r = resolve(self.surface, tgt, obs)
        if not r.ok:
            raise _Fail(f"selector_{r.status}", step.id,
                        f"a unique control for step {step.id}",
                        f"{r.status} via {r.detail}")

        target_name = ""
        prim = tgt.primary()
        if hasattr(prim, "name"):
            target_name = prim.name

        dec = policy_check(self.policy, _mk_action(a.type),
                           target_name=target_name, url=obs.url)
        if dec.verdict == "block":
            raise _Fail("policy_blocked", step.id, "action on allowlist", dec.reason)
        if dec.verdict == "confirm":
            approved = (self.cap.approval.state == "approved" and step.risk == "risky")
            if not approved:
                ctx = {"reason": "risky_action", "step": step.id,
                       "intent": step.intent, "control": target_name,
                       "policy": dec.reason, "url": obs.url}
                self._escalate_or_fail(ctx, step,
                                       expected="approved capability + risky-marked step")

        if a.type == "click":
            self.surface.click(r.handle)
        elif a.type == "type":
            self.surface.fill(r.handle, self.cap.render_value(a.value_ref, params))
        elif a.type == "select":
            self.surface.select_option(r.handle, self.cap.render_value(a.value_ref, params))
        elif a.type == "read":
            self._reads[step.id] = self.surface.read(r.handle)
        else:
            raise _Fail("policy_blocked", step.id, "known action type", f"unknown: {a.type}")

        return (r.strategy.kind if r.strategy else "?", r.strategy_index)

    def _restore_position(self, upto_index: int, params: Dict[str, Any]) -> None:
        entry = self.cap.render_template(self.cap.target.entry.url, params)
        self.surface.goto(entry)
        for s in self.cap.steps[:upto_index]:
            obs = self.surface.observe()
            try:
                self._act(s, obs, params)
            except _Fail:
                break
        self.run.event("position_restored", upto_step=upto_index)

    def _escalate_hard(self, f: "_Fail", step: Step) -> str:
        try:
            self.surface.screenshot(self.run.screenshot(f"escalation_{step.id}.png"))
        except Exception:
            pass
        ctx = {"reason": "replay_failure", "step": step.id, "intent": step.intent,
               "error_class": f.error_class, "expected": f.expected,
               "observed": f.observed}
        self.run.event("escalation_raised", **ctx)
        decision = self.on_escalate(ctx)
        self.run.event("escalation_resolved", decision=decision, step=step.id)
        return decision

    def _escalate_or_fail(self, ctx: dict, step: Step, *, expected: str) -> None:
        self.run.event("escalation_raised", **ctx)
        if self.on_escalate is None:
            raise _Fail("needs_approval", step.id, expected, ctx.get("policy", ""))
        shot = self.run.screenshot(f"escalation_{step.id}.png")
        try:
            self.surface.screenshot(shot)
        except Exception:
            pass
        decision = self.on_escalate({**ctx, "screenshot": shot})
        self.run.event("escalation_resolved", decision=decision, step=step.id)
        raise _Escalated(decision, expected)

    def _apply_recovery(self, cls: Classification, params: Dict[str, Any],
                        upto_index: int) -> None:
        rc = cls.recovery
        self.run.event("recovery", name=rc.name, type=rc.handle.type,
                       replays_steps=upto_index if rc.handle.type == "reauth" else 0)
        if rc.handle.type == "wait_retry":
            time.sleep(rc.handle.wait_ms / 1000.0)
        elif rc.handle.type == "dismiss_dialog":
            obs = self.surface.observe()
            r = resolve(self.surface, render_target(rc.handle.target, params), obs)
            if r.ok:
                self.surface.click(r.handle)
            else:
                time.sleep(rc.handle.wait_ms / 1000.0)
        elif rc.handle.type == "reauth":
            # Re-authenticate AND replay every prior step to restore the
            # navigation position the timeout threw away.
            entry = self.cap.render_template(self.cap.target.entry.url, params)
            self.surface.goto(entry)
            for s in self.cap.steps[:upto_index]:
                obs = self.surface.observe()
                self._act(s, obs, params)

    # ------------------------------------------------------------------ #
    def _extract_outputs(self) -> Dict[str, Any]:
        import re
        out: Dict[str, Any] = {}
        for o in self.cap.outputs:
            raw = self._reads.get(o.source_step, "")
            val: Any = raw
            if o.read.extract:
                m = re.search(o.read.extract, raw)
                if m:
                    val = m.group(1) if m.groups() else m.group(0)
            if o.read.cast == "number":
                try:
                    val = float(str(val).replace(",", "").replace("$", ""))
                except ValueError:
                    pass
            elif o.read.cast == "boolean":
                val = str(val).strip().lower() in ("1", "true", "yes")
            # The caller (a trusted agent) gets the real value; redaction is
            # applied only when this result is written to evidence (RunDir).
            out[o.name] = "<redacted>" if o.sensitivity == "secret" else val
        return out

    def _business(self, cls: Classification, reports, at_step, t0, base) -> ReplayResult:
        data = dict(cls.outcome.returns)
        self.run.event("business_outcome", name=cls.name, data=data, at_step=at_step)
        res = ReplayResult(outcome="business_outcome", business_outcome=cls.name,
                           business_data=data, at_step=at_step, steps=reports,
                           duration_ms=int((time.time() - t0) * 1000), **base)
        self.run.write_json("result.json", res)
        return res

    def _failure(self, f: _Fail, reports, red_params, t0, base) -> ReplayResult:
        if reports:
            reports[-1].status = "failed"
        try:
            obs = self.surface.observe()
            self.surface.screenshot(self.run.screenshot())
            self.run.write_json("observation.json", {
                "url": obs.url, "title": obs.title, "http_status": obs.http_status,
                "dialog": obs.dialog,
                "nodes": [f"{n.role}: {n.name}" for n in obs.nodes],
                "text": obs.text,
            })
        except Exception:
            pass
        self.run.event("replay_failure", error_class=f.error_class, step=f.step,
                       expected=f.expected, observed=f.observed)
        res = ReplayResult(outcome="failure", error_class=f.error_class,
                           failed_step=f.step, expected=f.expected, observed=f.observed,
                           evidence_dir=str(self.run.root), steps=reports,
                           params=red_params,
                           duration_ms=int((time.time() - t0) * 1000), **base)
        self.run.write_json("result.json", res)
        return res


class _Escalated(Exception):
    def __init__(self, decision: str, expected: str) -> None:
        self.decision = decision
        self.expected = expected


class _BusinessSignal(Exception):
    def __init__(self, cls: Classification, at_step: str) -> None:
        self.cls = cls
        self.at_step = at_step


def _mk_action(kind: str, value: Optional[str] = None):
    from cua.surface.base import Action, ActionType
    return Action(type=ActionType(kind), value=value)


def replay(cap: Capability, params: Dict[str, Any], *, policy: PolicyConfig,
           surface: Surface, run_dir: RunDir, redactor: Redactor,
           on_escalate: Optional[EscalateFn] = None,
           inject_before: Optional[Dict[str, str]] = None,
           origin: str = "") -> ReplayResult:
    eng = ReplayEngine(cap, policy, surface=surface, run_dir=run_dir,
                       redactor=redactor, on_escalate=on_escalate,
                       inject_before=inject_before, origin=origin)
    return eng.run_replay(params)
