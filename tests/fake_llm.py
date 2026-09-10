"""A stand-in Anthropic client that exercises the REAL discovery loop without a
network call.

It is not a loose mock: it returns genuine ``anthropic.types.Message`` objects
(so ``resp.content``, block ``.type``/``.id``/``.name``/``.input`` and the
assistant-turn round-trip are the real thing), and it *validates every outgoing
request* the way the API would -- required params, ``tool_choice``, the tool
list, first message role, and that every ``tool_result`` block references a
``tool_use`` id from the immediately preceding assistant turn. A threading bug in
the loop makes a test fail here.
"""
from __future__ import annotations

from typing import Any

from anthropic.types import Message, TextBlock, ToolUseBlock

from cua.agent.tools import TOOL_NAMES, TOOLS


class FakeRequestError(AssertionError):
    pass


class _Messages:
    def __init__(self, outer: "FakeAnthropic") -> None:
        self._outer = outer

    def create(self, **kw: Any) -> Message:
        self._validate(kw)
        # snapshot the messages list -- the caller keeps mutating the same object
        self._outer.calls.append({**kw, "messages": list(kw["messages"])})
        step = self._outer._plan[self._outer._i]
        self._outer._i += 1

        blocks: list = []
        if step.get("say"):
            blocks.append(TextBlock(type="text", text=step["say"], citations=None))
        blocks.append(ToolUseBlock(
            type="tool_use", id=f"tu_{self._outer._i}",
            name=step["tool"], input=step.get("input", {})))
        return Message(
            id=f"msg_{self._outer._i}", content=blocks, model=kw["model"],
            role="assistant", stop_reason="tool_use", type="message",
            usage={"input_tokens": 100, "output_tokens": 20})

    @staticmethod
    def _validate(kw: dict) -> None:
        for req in ("model", "max_tokens", "system", "tools", "messages"):
            if req not in kw:
                raise FakeRequestError(f"request missing {req!r}")
        if kw["tool_choice"] != {"type": "any"}:
            raise FakeRequestError(f"unexpected tool_choice: {kw['tool_choice']}")
        if [t["name"] for t in kw["tools"]] != [t["name"] for t in TOOLS]:
            raise FakeRequestError("tool list does not match cua.agent.tools.TOOLS")
        msgs = kw["messages"]
        if not msgs or msgs[0]["role"] != "user":
            raise FakeRequestError("first message must be a user turn")
        for i, m in enumerate(msgs):
            content = m["content"]
            if m["role"] != "user" or not isinstance(content, list):
                continue
            tool_results = [b for b in content
                            if isinstance(b, dict) and b.get("type") == "tool_result"]
            if not tool_results:
                continue
            prev = msgs[i - 1]
            prev_ids = {b.id for b in prev["content"]
                        if getattr(b, "type", None) == "tool_use"}
            for tr in tool_results:
                if tr["tool_use_id"] not in prev_ids:
                    raise FakeRequestError(
                        f"tool_result {tr['tool_use_id']} has no matching tool_use "
                        f"in the preceding assistant turn")


class FakeAnthropic:
    """Constructed with a plan: a list of {tool, input, say?} the model 'decides'."""

    # mirror the real SDK's typed exceptions the loop catches
    RateLimitError = type("RateLimitError", (Exception,), {})
    APIStatusError = type("APIStatusError", (Exception,), {})

    def __init__(self, plan: list[dict]) -> None:
        assert all(s["tool"] in TOOL_NAMES for s in plan), "plan uses an unknown tool"
        self._plan = plan
        self._i = 0
        self.calls: list[dict] = []
        self.messages = _Messages(self)
