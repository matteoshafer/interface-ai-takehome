"""System prompt + the text rendering of an Observation the agent reasons over."""
from __future__ import annotations

from cua.surface.base import Observation

SYSTEM = """\
You are the discovery agent of a computer-use automation system. You operate a \
legacy back-office web application for a US credit union by reading the \
ACCESSIBILITY view of the current screen and issuing ONE action per turn.

Rules:
- Work only from the OBSERVATION. Identify every control by the role and the \
quoted name shown there. Never guess a control that isn't listed.
- One tool call per turn. After each action you receive the new OBSERVATION.
- To move forward you usually: search for a record, open it, read or enter data, \
reach a confirmation screen.
- If the goal asks you to READ a value (a balance, a status), use read_value and \
give it a short snake_case label. Collect every value the goal asks for.
- Some actions are risky / irreversible (creating an account, posting a \
transaction, transferring funds). Do NOT perform them. Reaching the confirmation \
screen IS the goal; stop there and call finish.
- If you are stuck, looping, hit an unexpected error or dialog you cannot \
clearly resolve, or would need to take a risky action -- call escalate with a \
clear reason. Do not thrash.
- When the goal is fully met, call finish with the outputs you collected.

Be decisive and brief. You have a limited number of steps."""


def render_goal(goal: str, target: str, params_hint: dict | None) -> str:
    lines = [f"GOAL: {goal}", f"TARGET APPLICATION: {target}"]
    if params_hint:
        shown = {k: ("<provided>" if k in ("password", "username") else v)
                 for k, v in params_hint.items()}
        lines.append(f"INPUTS AVAILABLE TO YOU: {shown}")
        lines.append("When a field needs one of these inputs, type that exact value.")
    return "\n".join(lines)


def render_observation(obs: Observation, *, step: int, max_steps: int) -> str:
    out = [f"OBSERVATION (step {step}/{max_steps})",
           f"url: {obs.url}",
           f"title: {obs.title}"]
    if obs.http_status and obs.http_status >= 400:
        out.append(f"http_status: {obs.http_status}")
    if obs.dialog:
        out.append(f"!! A modal dialog is open: \"{obs.dialog}\" -- it may block other controls.")

    alerts = [n for n in obs.nodes if n.role in ("alert", "status")]
    if alerts:
        out.append("messages on screen:")
        for n in alerts:
            out.append(f'  - ({n.role}) "{n.name}"')

    out.append("controls and content:")
    for n in obs.nodes:
        if n.role in ("alert", "status"):
            continue
        bits = [f'[{n.role}]']
        if n.name:
            bits.append(f'"{n.name}"')
        if n.value:
            bits.append(f"= {n.value!r}")
        if n.states:
            bits.append(f"({','.join(n.states)})")
        if n.row_anchor and n.row_anchor != n.name:
            bits.append(f"<row: {n.row_anchor}>")
        out.append("  " + " ".join(bits))
    return "\n".join(out)
