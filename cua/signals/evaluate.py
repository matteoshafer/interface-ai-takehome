"""Evaluate a :mod:`cua.signals.dsl` predicate against an Observation."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from cua.surface.base import Observation


@dataclass
class SignalResult:
    value: bool
    detail: str = ""
    # human-readable trace of which leaves passed/failed, for debuggable failures
    trace: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.value


def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE)


def evaluate(sig, obs: Observation) -> SignalResult:
    k = sig.kind

    if k == "url_matches":
        u = obs.url or ""
        p = urlparse(u)
        path_q = p.path + (("?" + p.query) if p.query else "")
        rx = _rx(sig.pattern)
        ok = bool(rx.search(u) or rx.search(path_q) or rx.search(p.path))
        return SignalResult(ok, f"url {'~' if ok else '!~'} /{sig.pattern}/",
                            [f"url_matches(/{sig.pattern}/)={ok} [{path_q}]"])

    if k == "text_matches":
        ok = bool(_rx(sig.pattern).search(obs.text or ""))
        return SignalResult(ok, f"page text {'~' if ok else '!~'} /{sig.pattern}/",
                            [f"text_matches(/{sig.pattern}/)={ok}"])

    if k in ("ax_present", "ax_absent"):
        name_rx = _rx(sig.name_matches) if sig.name_matches else None
        hit = any(
            n.role == sig.role and (name_rx is None or name_rx.search(n.name or ""))
            for n in obs.nodes
        )
        ok = hit if k == "ax_present" else not hit
        want = "present" if k == "ax_present" else "absent"
        return SignalResult(
            ok, f"{sig.role}"
                + (f" name~/{sig.name_matches}/" if sig.name_matches else "")
                + f" {want}: {ok}",
            [f"{k}({sig.role},{sig.name_matches})={ok}"])

    if k == "dialog_open":
        ok = (obs.dialog is not None) == sig.expected
        return SignalResult(ok, f"dialog_open={obs.dialog is not None} "
                                f"(want {sig.expected})",
                            [f"dialog_open={obs.dialog is not None}"])

    if k == "http_status":
        st = obs.http_status
        if st is None:
            return SignalResult(False, "http_status unknown", ["http_status=None"])
        ok = True
        if sig.eq is not None:
            ok = ok and st == sig.eq
        if sig.lt is not None:
            ok = ok and st < sig.lt
        if sig.gte is not None:
            ok = ok and st >= sig.gte
        return SignalResult(ok, f"http_status={st}", [f"http_status={st} ok={ok}"])

    if k == "all_of":
        subs = [evaluate(s, obs) for s in sig.of]
        ok = all(s.value for s in subs)
        tr = [t for s in subs for t in s.trace]
        return SignalResult(ok, "all_of: " + ("pass" if ok else "fail"), tr)

    if k == "any_of":
        subs = [evaluate(s, obs) for s in sig.of]
        ok = any(s.value for s in subs)
        tr = [t for s in subs for t in s.trace]
        return SignalResult(ok, "any_of: " + ("pass" if ok else "fail"), tr)

    if k == "not":
        sub = evaluate(sig.of, obs)
        return SignalResult(not sub.value, "not: " + ("pass" if not sub.value else "fail"),
                            [f"not({t})" for t in sub.trace])

    raise ValueError(f"unknown signal kind: {k!r}")
