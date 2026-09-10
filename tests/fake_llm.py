"""A stand-in :class:`~cua.agent.llm.LLMClient` that drives the REAL discovery
loop from a fixed plan, without any network call.

It is not a loose mock -- it exercises the true transcript contract:

* the first entry is always a single ``context`` turn (goal + observation);
* every ``agent`` turn it emitted must reappear verbatim in the next call's
  transcript (the loop must be threading history correctly);
* every ``feedback`` entry must reference the ``call_id`` of the immediately
  preceding ``agent`` turn.

A threading bug in ``cua/agent/loop.py`` makes a test here fail. The only thing
it does not cover is the provider adapters' native message translation -- that is
covered separately by round-tripping a plan through the real adapters against
fake SDK clients (``test_llm_adapters.py``).
"""
from __future__ import annotations

from cua.agent.llm import AgentTurn, Transcript
from cua.agent.tools import TOOL_NAMES


class FakePlanError(AssertionError):
    pass


class FakeLLM:
    name = "fake"
    model = "fake-model-1"

    def __init__(self, plan: list[dict]) -> None:
        assert all(s["tool"] in TOOL_NAMES for s in plan), "plan uses an unknown tool"
        self._plan = plan
        self._i = 0
        self.seen: list[Transcript] = []

    def converse(self, system: str, transcript: Transcript) -> AgentTurn:
        if not system or "discovery agent" not in system.lower():
            raise FakePlanError("system prompt missing or wrong")
        self._validate(transcript)
        self.seen.append([dict(e) for e in transcript])

        step = self._plan[self._i]
        self._i += 1
        return AgentTurn(
            text=step.get("say", ""),
            tool=step["tool"],
            tool_input=step.get("input", {}),
            call_id=f"call_{self._i}",
            usage={"input_tokens": 200 + 20 * self._i, "output_tokens": 25},
        )

    def _validate(self, transcript: Transcript) -> None:
        if not transcript or transcript[0]["role"] != "context":
            raise FakePlanError("transcript must open with a context turn")
        prev_agent_call: str | None = None
        for i, e in enumerate(transcript):
            role = e["role"]
            if role == "agent":
                turn = e["turn"]
                if not isinstance(turn, AgentTurn):
                    raise FakePlanError(f"agent entry {i} is not an AgentTurn")
                prev_agent_call = turn.call_id
            elif role == "feedback":
                if e["call_id"] != prev_agent_call:
                    raise FakePlanError(
                        f"feedback at {i} refs {e['call_id']!r} but the preceding "
                        f"agent turn was {prev_agent_call!r}")
                if "observation" not in e or "result" not in e:
                    raise FakePlanError(f"feedback at {i} missing result/observation")
            elif role != "context":
                raise FakePlanError(f"unknown transcript role {role!r}")
        # the plan must not run past its end
        if self._i >= len(self._plan):
            raise FakePlanError("loop called the model more times than the plan allows")
