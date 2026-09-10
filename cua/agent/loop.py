"""The goal-driven agent loop: observe -> decide (LLM) -> act, against a live
surface, until the goal is met or a stopping condition fires.

This is the ONE place a model is in the decision loop. Its product is a
:class:`RunTrace`, which the compiler turns into a replayable capability.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from cua.agent.llm import AgentTurn, LLMClient, Transcript, build_client
from cua.agent.prompt import SYSTEM, render_goal, render_observation
from cua.agent.trace import ObsBrief, ReadRecord, RunTrace, TraceStep
from cua.evidence import RunDir
from cua.policy.config import PolicyConfig
from cua.policy.enforce import check as policy_check
from cua.policy.redact import Redactor
from cua.surface.base import Action, ActionType, Observation
from cua.targeting.resolver import resolve
from cua.targeting.synthesize import synthesize_target

ConfirmFn = Callable[[dict], bool]


@dataclass
class AgentConfig:
    model: str = "claude-sonnet-5"
    max_steps: int = 22
    max_tokens: int = 1500
    provider: Optional[str] = None      # None -> auto-detect from env keys


class _Discovery:
    def __init__(self, *, goal: str, target_url: str, surface, policy: PolicyConfig,
                 redactor: Redactor, run_dir: RunDir, config: AgentConfig,
                 params_hint: Optional[dict], on_confirm: Optional[ConfirmFn],
                 llm: Optional[LLMClient] = None) -> None:
        self.goal = goal
        self.target_url = target_url
        self.s = surface
        self.policy = policy
        self.red = redactor
        self.run = run_dir
        self.cfg = config
        self.params_hint = params_hint or {}
        self.on_confirm = on_confirm
        # `llm` is injectable so the loop can run against a fake in tests. A real
        # one is built lazily (only when there's actually a model in the loop).
        self._llm = llm
        self.trace = RunTrace(goal=goal, target=target_url, model=config.model,
                              policy_ref="", params_hint=self.params_hint)

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = build_client(provider=self.cfg.provider,
                                     model=self.cfg.model or None,
                                     max_tokens=self.cfg.max_tokens)
            self.cfg.model = self._llm.model
        return self._llm

    # ------------------------------------------------------------------ #
    def execute(self) -> RunTrace:
        self.s.goto(self.target_url)
        transcript: Transcript = []
        goal_msg = render_goal(self.goal, self.target_url, self.params_hint)
        pending: Optional[tuple[str, str]] = None   # (call_id, result text)
        fps: list = []
        self.run.event("discovery_start", provider=self.llm.name,
                       model=self.llm.model, goal=self.goal)

        for step in range(1, self.cfg.max_steps + 1):
            obs = self.s.observe()
            try:
                self.s.screenshot(str(self.run.path(f"step_{step:02d}.png")))
            except Exception:
                pass
            self.run.event("observe", step=step, url=obs.url, title=obs.title,
                           dialog=obs.dialog, http_status=obs.http_status,
                           headings=[n.name for n in obs.nodes if n.role == "heading"])
            rendered = render_observation(obs, step=step, max_steps=self.cfg.max_steps)

            if step == 1:
                transcript.append({"role": "context",
                                   "text": f"{goal_msg}\n\n{rendered}"})
            elif pending is not None:
                transcript.append({"role": "feedback", "call_id": pending[0],
                                   "result": pending[1], "observation": rendered})
            else:  # previous turn produced no tool call
                transcript.append({"role": "context",
                                   "text": "Call exactly one tool to proceed.\n\n"
                                           + rendered})

            turn: AgentTurn = self.llm.converse(SYSTEM, transcript)
            transcript.append({"role": "agent", "turn": turn})
            if turn.usage:
                self.run.event("model_turn", step=step, tool=turn.tool,
                               **turn.usage)
            if not turn.tool:
                pending = None
                continue

            pending = (turn.call_id, "")
            name, inp = turn.tool, dict(turn.tool_input or {})
            ts = TraceStep(index=step, tool=name, tool_input=dict(inp),
                           intent=inp.get("why") or inp.get("reason") or "",
                           obs_before=ObsBrief.of(obs))

            if name == "finish":
                self.trace.outcome = "success"
                self.trace.outputs = inp.get("outputs") or {
                    k: v.value for k, v in self.trace.reads.items()}
                self.trace.summary = inp.get("summary", "")
                self.trace.steps.append(ts)
                self.run.event("finish", summary=self.trace.summary,
                               outputs=self.trace.outputs)
                break

            if name == "escalate":
                self.trace.outcome = "escalated"
                self.trace.summary = inp.get("reason", "")
                self.trace.escalation = {"reason": inp.get("reason", ""),
                                         "step": step, "url": obs.url}
                ts.note = "escalate"
                self.trace.steps.append(ts)
                self.run.event("escalate", reason=inp.get("reason", ""), step=step)
                break

            result = self._act(name, inp, obs, ts)
            pending = (turn.call_id, result)
            self.trace.steps.append(ts)

            fp = (obs.url, name, inp.get("name"), inp.get("url"))
            fps.append(fp)
            if len(fps) >= 4 and len(set(fps[-4:])) == 1:
                self.trace.outcome = "escalated"
                self.trace.summary = "no progress: same action repeated with no state change"
                self.trace.escalation = {"reason": self.trace.summary, "step": step,
                                         "url": obs.url}
                self.run.event("stuck", step=step, fingerprint=str(fp))
                break
        else:
            self.trace.outcome = "exhausted"
            self.run.event("exhausted", steps=self.cfg.max_steps)

        self.trace.finished_at = time.time()
        self.run.write_json("discovery_trace.json", self.trace.to_public(self.red))
        return self.trace

    # ------------------------------------------------------------------ #
    def _act(self, name: str, inp: dict, obs: Observation, ts: TraceStep) -> str:
        if name == "navigate":
            url = inp.get("url", "")
            dec = policy_check(self.policy, Action(type=ActionType.NAVIGATE, value=url),
                               url=url)
            ts.policy_decision = dec.verdict
            if not dec.allowed:
                ts.error = dec.reason
                return f"BLOCKED BY POLICY: {dec.reason}"
            self.s.goto(url)
            after = self.s.observe()
            ts.obs_after = ObsBrief.of(after)
            return f"navigated. now at {after.url} ({after.title})"

        if name == "press_key":
            self.s.press_key(inp.get("key", "Enter"))
            after = self.s.observe()
            ts.obs_after = ObsBrief.of(after)
            return f"key pressed. now at {after.url}"

        role, nm = inp.get("role", ""), inp.get("name", "")
        nth = int(inp.get("nth", 0) or 0)
        ts.target_role, ts.target_name, ts.target_nth = role, nm, nth
        match_node = next((n for n in obs.nodes
                           if n.role == role and n.name == nm), None)
        row_anchor = match_node.row_anchor if match_node else None
        column_header = match_node.column_header if match_node else None
        ts.row_anchor, ts.column_header = row_anchor, column_header

        target = synthesize_target(self.s, obs, role=role, name=nm, nth=nth,
                                   row_anchor=row_anchor, column_header=column_header)
        r = resolve(self.s, target, obs)
        if not r.ok:
            ts.error = f"target {role}:{nm} -> {r.status} ({r.detail})"
            return (f'NOT FOUND: {role} "{nm}" resolved as {r.status}. '
                    f"Re-read the OBSERVATION and use an exact role + name.")
        ts.resolved = True
        ts.matched_strategy = r.strategy.kind if r.strategy else None
        ts.strategy_index = r.strategy_index
        for st in target.strategies:
            if st.kind == "bbox_ratio":
                ts.bbox_ratio = (st.x, st.y)

        act_type = {"click": ActionType.CLICK, "type_text": ActionType.TYPE,
                    "select_option": ActionType.SELECT,
                    "read_value": ActionType.READ}[name]
        dec = policy_check(self.policy, Action(type=act_type), target_name=nm,
                           url=obs.url)
        ts.policy_decision = dec.verdict
        if dec.verdict == "block":
            ts.error = dec.reason
            return f"BLOCKED BY POLICY: {dec.reason}"
        if dec.verdict == "confirm":
            ctx = {"reason": "risky_action", "control": nm, "intent": ts.intent,
                   "url": obs.url, "policy": dec.reason}
            approved = bool(self.on_confirm and self.on_confirm(ctx))
            ts.policy_decision = f"confirm:{'approved' if approved else 'denied'}"
            self.run.event("risky_action", control=nm, approved=approved,
                           reason=dec.reason)
            if not approved:
                ts.error = "risky action not approved"
                return ("RISKY ACTION BLOCKED: creating/confirming an account is "
                        "irreversible and needs a human. Stop at the review screen "
                        "and call finish, or call escalate.")

        try:
            if name == "click":
                self.s.click(r.handle)
            elif name == "type_text":
                self.s.fill(r.handle, inp.get("text", ""))
            elif name == "select_option":
                self.s.select_option(r.handle, inp.get("value", ""))
            elif name == "read_value":
                val = self.s.read(r.handle)
                label = inp.get("label") or nm
                self.trace.reads[label] = ReadRecord(
                    label=label, value=val, target_role=role, target_name=nm,
                    step_index=ts.index, row_anchor=row_anchor,
                    column_header=column_header)
                ts.note = f"read {label}"
                after = self.s.observe()
                ts.obs_after = ObsBrief.of(after)
                return f'read {label} = "{val}"'
        except Exception as e:
            ts.error = f"{type(e).__name__}: {e}"
            return f"ACTION FAILED: {type(e).__name__}: {e}"

        after = self.s.observe()
        ts.obs_after = ObsBrief.of(after)
        note = ""
        if after.dialog:
            note = f' A dialog appeared: "{after.dialog}".'
        return f"ok. now at {after.url} ({after.title}).{note}"


def run_discovery(*, goal: str, target_url: str, surface, policy: PolicyConfig,
                  redactor: Redactor, run_dir: RunDir, config: AgentConfig,
                  params_hint: Optional[dict] = None,
                  on_confirm: Optional[ConfirmFn] = None,
                  llm: Optional[LLMClient] = None) -> RunTrace:
    return _Discovery(goal=goal, target_url=target_url, surface=surface,
                      policy=policy, redactor=redactor, run_dir=run_dir,
                      config=config, params_hint=params_hint,
                      on_confirm=on_confirm, llm=llm).execute()


def run_scripted(*, goal: str, target_url: str, surface, policy: PolicyConfig,
                 redactor: Redactor, run_dir: RunDir, script: list[dict],
                 params_hint: Optional[dict] = None,
                 on_confirm: Optional[ConfirmFn] = None) -> RunTrace:
    """Drive the SAME observe/act/record machinery from a fixed action list
    instead of the model. No LLM. Used for offline tests and CI so the
    compiler + replay path can be exercised without an API key.

    Each script entry is ``{"tool": <name>, ...tool_input}``; a ``finish`` /
    ``escalate`` entry ends the run.
    """
    d = _Discovery(goal=goal, target_url=target_url, surface=surface, policy=policy,
                   redactor=redactor, run_dir=run_dir, config=AgentConfig(model="scripted"),
                   params_hint=params_hint, on_confirm=on_confirm)
    d.s.goto(target_url)
    for i, entry in enumerate(script, 1):
        name = entry["tool"]
        inp = {k: v for k, v in entry.items() if k != "tool"}
        obs = d.s.observe()
        try:
            d.s.screenshot(str(run_dir.path(f"step_{i:02d}.png")))
        except Exception:
            pass
        d.run.event("observe", step=i, url=obs.url, title=obs.title,
                    dialog=obs.dialog, scripted=True)
        ts = TraceStep(index=i, tool=name, tool_input=dict(inp),
                       intent=inp.get("why", ""), obs_before=ObsBrief.of(obs))
        if name == "finish":
            d.trace.outcome = "success"
            d.trace.outputs = inp.get("outputs") or {
                k: v.value for k, v in d.trace.reads.items()}
            d.trace.summary = inp.get("summary", "scripted run")
            d.trace.steps.append(ts)
            break
        if name == "escalate":
            d.trace.outcome = "escalated"
            d.trace.escalation = {"reason": inp.get("reason", ""), "step": i}
            d.trace.steps.append(ts)
            break
        d._act(name, inp, obs, ts)
        d.trace.steps.append(ts)
    d.trace.finished_at = time.time()
    d.run.write_json("discovery_trace.json", d.trace.to_public(redactor))
    return d.trace
