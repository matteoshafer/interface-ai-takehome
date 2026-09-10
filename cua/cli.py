"""Command-line entrypoint.

    python -m cua.cli discover --goal "..." [--param k=v ...]
    python -m cua.cli replay capabilities/<id>.json --param k=v [...]
    python -m cua.cli catalog [--json] [--invoke <id> --param k=v ...]
    python -m cua.cli operator [--queue DIR] [--port 5051]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from cua.artifact import store
from cua.artifact.compiler import compile_capability
from cua.evidence import RunDir
from cua.policy.config import PolicyConfig
from cua.policy.redact import Redactor

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "evidence"
DEFAULT_QUEUE = EVIDENCE / "_interventions"


def _kv(pairs: list[str]) -> dict:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"bad --param {p!r}, expected k=v")
        k, v = p.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_root(kind: str, args) -> Path:
    name = getattr(args, "evidence_name", None)
    return EVIDENCE / (name or f"{kind}-{_ts()}")


def _maybe_mock(args) -> Optional[object]:
    if not getattr(args, "serve_mock", False):
        return None
    from mockapp.server import MockServer
    srv = MockServer(port=int(os.environ.get("CUA_MOCKAPP_PORT", "5050")))
    srv._thread.start()
    time.sleep(0.6)
    print(f" * mock app serving at {srv.base_url}")
    return srv


# --------------------------------------------------------------------------- #
def cmd_discover(args) -> int:
    load_dotenv(REPO / ".env")
    policy = PolicyConfig.load(args.policy)
    redactor = Redactor(policy)
    target = args.target or os.environ.get("CUA_MOCKAPP_URL", "http://localhost:5050")
    model = args.model or os.environ.get("CUA_DISCOVERY_MODEL", "claude-sonnet-5")
    params_hint = _kv(args.param)
    for k in ("username", "password"):
        env = os.environ.get(f"CUA_APP_{k.upper()}")
        if env and k not in params_hint:
            params_hint[k] = env
    params_hint.setdefault("username", os.environ.get("CUA_APP_USERNAME", "operator"))
    params_hint.setdefault("password", os.environ.get("CUA_APP_PASSWORD", "demo-pass"))

    if not args.scripted and not (os.environ.get("ANTHROPIC_API_KEY")
                                 or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("error: `cua discover` needs an LLM. Set ANTHROPIC_API_KEY in .env "
              "(https://console.anthropic.com -> API Keys), or use --scripted "
              "<actions.json> for an offline run.", file=sys.stderr)
        return 3

    run_dir = RunDir(_run_root("discovery", args), redactor)
    mock = _maybe_mock(args)
    from cua.surface.web import WebSurface
    from cua.agent.loop import AgentConfig, run_discovery, run_scripted

    surface = WebSurface(headless=not args.headed)
    # By default discovery routes a risky action to a human (here: deny -> the
    # agent stops at the review screen). --approve-risky stands in for an
    # operator who approved it live, so the risky step is recorded.
    on_confirm = (lambda ctx: True) if args.approve_risky else (lambda ctx: False)
    try:
        if args.scripted:
            script = json.loads(Path(args.scripted).read_text())
            trace = run_scripted(goal=args.goal, target_url=target, surface=surface,
                                 policy=policy, redactor=redactor, run_dir=run_dir,
                                 script=script, params_hint=params_hint,
                                 on_confirm=on_confirm)
        else:
            trace = run_discovery(
                goal=args.goal, target_url=target, surface=surface, policy=policy,
                redactor=redactor, run_dir=run_dir,
                config=AgentConfig(model=model, max_steps=args.max_steps),
                params_hint=params_hint, on_confirm=on_confirm)
    finally:
        surface.close()
        if mock:
            mock.stop()

    print(f"\ndiscovery outcome: {trace.outcome}")
    print(f"evidence: {run_dir.root}")
    if trace.outcome != "success":
        print(f"reason: {trace.summary}")
        return 2

    cap = compile_capability(
        trace, cap_id=args.id, name=args.name or args.goal[:60],
        description=args.description or args.goal,
        app_id=args.app_id, redactor=redactor)
    path = store.save(cap, args.out or store.DEFAULT_DIR)
    run_dir.write_json("capability.json", cap.model_dump(mode="json"))
    print(f"capability: {path}  (v{cap.version}, {len(cap.steps)} steps, "
          f"{len(cap.parameters)} params, {len(cap.outputs)} outputs)")
    print(f"outputs discovered: {trace.outputs}")
    return 0


# --------------------------------------------------------------------------- #
def cmd_replay(args) -> int:
    load_dotenv(REPO / ".env")
    cap = store.load(args.capability)
    policy_path = args.policy or (REPO / cap.policy_ref)
    policy = PolicyConfig.load(policy_path)
    redactor = Redactor(policy)
    params = _kv(args.param)
    for k in ("username", "password"):
        env = os.environ.get(f"CUA_APP_{k.upper()}")
        if any(p.name == k for p in cap.parameters) and k not in params:
            params[k] = env or ("operator" if k == "username" else "demo-pass")

    if args.approve:
        cap.approval.state = "approved"
        cap.approval.approved_by = "cli --approve"

    run_dir = RunDir(_run_root("replay", args), redactor)
    mock = _maybe_mock(args)
    origin = os.environ.get("CUA_MOCKAPP_URL", "http://localhost:5050")

    inject_before = {}
    if args.inject:
        cond, _, step_id = args.inject.partition("@")
        if not step_id:
            # default: before the last navigating step, so the injected
            # condition manifests on a screen the flow actually loads
            navs = [s.id for s in cap.steps
                    if s.phase == "main" and s.action.type in ("click", "navigate")]
            step_id = navs[-1] if navs else cap.steps[-1].id
        inject_before[step_id] = cond
        print(f" * will inject '{cond}' before step {step_id}")

    from cua.surface.web import WebSurface
    surface = WebSurface(headless=not args.headed)

    on_escalate = None
    if args.escalate_on_failure:
        from cua.escalation.session import SessionManager
        session_mgr = SessionManager(surface, run_dir=run_dir,
                                     queue_dir=args.operator_queue or DEFAULT_QUEUE,
                                     wait_timeout=args.escalate_timeout)

        def on_escalate(ctx: dict) -> str:
            return session_mgr.escalate(
                kind="risky_action" if ctx.get("reason") == "risky_action"
                else "replay_failure",
                reason=ctx.get("policy") or ctx.get("observed") or ctx.get("reason", ""),
                capability=cap.id, step=ctx.get("step"))

    from cua.replay.engine import replay
    try:
        result = replay(cap, params, policy=policy, surface=surface, run_dir=run_dir,
                        redactor=redactor, on_escalate=on_escalate,
                        inject_before=inject_before, origin=origin)
    finally:
        surface.close()
        if mock:
            mock.stop()

    print("\n" + redactor.text(result.summary()))
    print(f"evidence: {run_dir.root}")
    strat = [f"{s.step_id}:{s.matched_strategy}#{s.strategy_rank}"
             for s in result.steps if s.matched_strategy]
    if strat:
        print("targeting: " + "  ".join(strat))
    return {"success": 0, "business_outcome": 0, "failure": 1}[result.outcome]


# --------------------------------------------------------------------------- #
def cmd_catalog(args) -> int:
    caps = store.load_all(args.dir or store.DEFAULT_DIR)
    if args.invoke:
        cap = next((c for c in caps if c.id == args.invoke), None)
        if not cap:
            raise SystemExit(f"no capability {args.invoke!r}")
        rep_args = argparse.Namespace(
            capability=str(store.path_for(cap, args.dir or store.DEFAULT_DIR)),
            param=args.param, policy=None, approve=args.approve, headed=False,
            serve_mock=args.serve_mock, inject=None, operator_queue=None,
            escalate_on_failure=False, escalate_timeout=None)
        return cmd_replay(rep_args)
    if args.json:
        print(json.dumps([c.contract() for c in caps], indent=2))
        return 0
    for c in caps:
        ct = c.contract()
        req = ", ".join(ct["input_schema"]["required"])
        outs = ", ".join(ct["output_schema"]["properties"])
        print(f"{c.id}  v{c.version}  [{c.approval.state}]")
        print(f"    {c.description}")
        print(f"    in: ({req})   out: ({outs})")
        if c.known_outcomes:
            print(f"    outcomes: {', '.join(k.name for k in c.known_outcomes)}")
    return 0


def cmd_operator(args) -> int:
    from cua.escalation.console import create_console
    app = create_console(args.queue or DEFAULT_QUEUE)
    port = int(args.port or os.environ.get("CUA_OPERATOR_PORT", "5051"))
    print(f" * operator console on http://127.0.0.1:{port}  (queue: {args.queue or DEFAULT_QUEUE})")
    from werkzeug.serving import make_server
    make_server("127.0.0.1", port, app, threaded=True).serve_forever()
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cua")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="LLM-driven discovery run -> capability")
    d.add_argument("--goal", required=True)
    d.add_argument("--target")
    d.add_argument("--policy", default=str(REPO / "policies/creditunion.yaml"))
    d.add_argument("--param", action="append", default=[])
    d.add_argument("--id", default="capability")
    d.add_argument("--name", default="")
    d.add_argument("--description", default="")
    d.add_argument("--app-id", default="cu-coreadmin")
    d.add_argument("--out", default=None)
    d.add_argument("--model", default=None)
    d.add_argument("--max-steps", type=int, default=22)
    d.add_argument("--headed", action="store_true")
    d.add_argument("--serve-mock", action="store_true")
    d.add_argument("--scripted", default=None,
                   help="offline: JSON list of actions instead of the LLM")
    d.add_argument("--approve-risky", action="store_true",
                   help="stand in for an operator approving risky actions during discovery")
    d.add_argument("--evidence-name", default=None,
                   help="fixed name for the evidence/ run directory")
    d.set_defaults(func=cmd_discover)

    r = sub.add_parser("replay", help="deterministic replay of a capability (no LLM)")
    r.add_argument("capability")
    r.add_argument("--param", action="append", default=[])
    r.add_argument("--policy", default=None)
    r.add_argument("--approve", action="store_true",
                   help="treat the capability as approved for this run")
    r.add_argument("--headed", action="store_true")
    r.add_argument("--serve-mock", action="store_true")
    r.add_argument("--inject", default=None,
                   help="fault to inject, e.g. 'slow' or 'dialog@s04_open_member'")
    r.add_argument("--escalate-on-failure", action="store_true")
    r.add_argument("--operator-queue", default=None)
    r.add_argument("--escalate-timeout", type=float, default=None)
    r.add_argument("--evidence-name", default=None,
                   help="fixed name for the evidence/ run directory")
    r.set_defaults(func=cmd_replay)

    c = sub.add_parser("catalog", help="list / invoke saved capabilities")
    c.add_argument("--dir", default=None)
    c.add_argument("--json", action="store_true")
    c.add_argument("--invoke", default=None)
    c.add_argument("--param", action="append", default=[])
    c.add_argument("--approve", action="store_true")
    c.add_argument("--serve-mock", action="store_true")
    c.set_defaults(func=cmd_catalog)

    o = sub.add_parser("operator", help="run the operator console")
    o.add_argument("--queue", default=None)
    o.add_argument("--port", default=None)
    o.set_defaults(func=cmd_operator)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
