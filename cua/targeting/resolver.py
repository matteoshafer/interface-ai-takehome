"""Try a Target's strategies in order; report what matched (or why nothing did).

The engine treats a non-``unique`` resolution as a hard failure -- acting on an
ambiguous or missing control is exactly the "blindly proceeding" the brief warns
against. The ``matched`` strategy index is logged for every step so that
sustained fall-through to weaker strategies becomes a per-tenant drift signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from cua.surface.base import LocateResult, Observation, Surface
from cua.targeting.selector import Strategy, Target


@dataclass
class Resolution:
    status: str                       # "unique" | "ambiguous" | "missing"
    handle: object = None
    strategy_index: Optional[int] = None
    strategy: Optional[Strategy] = None
    tried: int = 0
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "unique"


def resolve(surface: Surface, target: Target, obs: Observation) -> Resolution:
    best: Optional[Resolution] = None
    for i, strat in enumerate(target.strategies):
        try:
            r: LocateResult = surface.locate(strat, obs)
        except Exception as e:  # a surface-level failure for this strategy only
            r = LocateResult(status="missing", strategy=strat, count=0)
            detail = f"{type(e).__name__}: {e}"
        else:
            detail = ""
        if r.status == "unique":
            return Resolution(status="unique", handle=r.handle, strategy_index=i,
                              strategy=strat, tried=i + 1,
                              detail=f"matched by {strat.kind}")
        cand = Resolution(status=r.status, strategy_index=i, strategy=strat,
                          tried=i + 1,
                          detail=detail or f"{strat.kind}: {r.status} ({r.count})")
        # Prefer to surface an "ambiguous" over a "missing" when debugging.
        if best is None or (best.status == "missing" and cand.status == "ambiguous"):
            best = cand
    return best or Resolution(status="missing", detail="no strategies")
