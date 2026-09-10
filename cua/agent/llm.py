"""Provider-neutral LLM adapter for the discovery loop.

The loop keeps a *neutral transcript* (a list of context / agent-turn / feedback
entries) and asks a client to produce the next :class:`AgentTurn`. Each adapter
translates that transcript into its provider's native message shape on every
call — the API is stateless, we resend the whole history anyway, so rebuilding it
each turn keeps the adapters simple and side-effect free.

Two adapters ship:

* :class:`AnthropicClient` — Claude via the ``anthropic`` SDK (``tool_use`` blocks).
* :class:`OpenAICompatClient` — any OpenAI-compatible chat-completions endpoint
  (``tool_calls``). Covers **NVIDIA NIM** (``build.nvidia.com`` /
  ``integrate.api.nvidia.com``), OpenAI, Together, Groq, a local vLLM, etc.

The provider is a free choice under the brief ("LLM provider / model … your
call"); this is the seam that keeps that choice from touching the rest of the
system.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from cua.agent.tools import TOOLS


@dataclass
class AgentTurn:
    """One decision from the model: optional prose + exactly one tool call."""
    text: str
    tool: str
    tool_input: dict
    call_id: str
    usage: dict = field(default_factory=dict)


# Neutral transcript entries the loop builds:
#   {"role": "context",  "text": <goal + first observation>}
#   {"role": "agent",    "turn": AgentTurn}
#   {"role": "feedback", "call_id": str, "result": str, "observation": str}
Transcript = list[dict]


class LLMClient(Protocol):
    name: str
    model: str

    def converse(self, system: str, transcript: Transcript) -> AgentTurn: ...


# --------------------------------------------------------------------------- #
# tool-schema conversion
# --------------------------------------------------------------------------- #
def _openai_tools() -> list[dict]:
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": t["input_schema"]}}
            for t in TOOLS]


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #
class AnthropicClient:
    name = "anthropic"

    def __init__(self, model: str, *, max_tokens: int = 1500,
                 client: Optional[Any] = None) -> None:
        self.model = model
        self.max_tokens = max_tokens
        if client is not None:
            self._c = client
        else:
            import anthropic
            self._c = anthropic.Anthropic()

    def _messages(self, transcript: Transcript) -> list[dict]:
        msgs: list[dict] = []
        for e in transcript:
            if e["role"] == "context":
                msgs.append({"role": "user", "content": e["text"]})
            elif e["role"] == "agent":
                t: AgentTurn = e["turn"]
                content: list[dict] = []
                if t.text:
                    content.append({"type": "text", "text": t.text})
                content.append({"type": "tool_use", "id": t.call_id,
                                "name": t.tool, "input": t.tool_input})
                msgs.append({"role": "assistant", "content": content})
            elif e["role"] == "feedback":
                msgs.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": e["call_id"],
                     "content": e["result"]},
                    {"type": "text", "text": e["observation"]},
                ]})
        return msgs

    def converse(self, system: str, transcript: Transcript) -> AgentTurn:
        import anthropic
        last: Exception | None = None
        for attempt in range(4):
            try:
                resp = self._c.messages.create(
                    model=self.model, max_tokens=self.max_tokens, system=system,
                    tools=TOOLS, tool_choice={"type": "any"},
                    messages=self._messages(transcript))
                break
            except anthropic.RateLimitError as e:
                last = e
                time.sleep(2 ** attempt)
            except anthropic.APIStatusError as e:
                last = e
                if getattr(e, "status_code", 500) >= 500:
                    time.sleep(2 ** attempt)
                else:
                    raise
        else:
            raise RuntimeError(f"anthropic call failed after retries: {last}")

        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        tu = next((b for b in resp.content if b.type == "tool_use"), None)
        if tu is None:
            return AgentTurn(text=text, tool="", tool_input={}, call_id="")
        u = getattr(resp, "usage", None)
        usage = {"input_tokens": getattr(u, "input_tokens", 0),
                 "output_tokens": getattr(u, "output_tokens", 0)} if u else {}
        return AgentTurn(text=text, tool=tu.name, tool_input=dict(tu.input or {}),
                         call_id=tu.id, usage=usage)


# --------------------------------------------------------------------------- #
# OpenAI-compatible (NVIDIA NIM, OpenAI, Together, Groq, local vLLM, …)
# --------------------------------------------------------------------------- #
class OpenAICompatClient:
    name = "openai_compat"

    def __init__(self, model: str, *, base_url: str, api_key: str,
                 max_tokens: int = 1500, tool_choice: str = "required",
                 client: Optional[Any] = None) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self._tool_choice = tool_choice
        if client is not None:
            self._c = client
        else:
            from openai import OpenAI
            self._c = OpenAI(base_url=base_url, api_key=api_key)

    def _messages(self, system: str, transcript: Transcript) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": system}]
        for e in transcript:
            if e["role"] == "context":
                msgs.append({"role": "user", "content": e["text"]})
            elif e["role"] == "agent":
                t: AgentTurn = e["turn"]
                msgs.append({
                    "role": "assistant",
                    "content": t.text or None,
                    "tool_calls": [{
                        "id": t.call_id, "type": "function",
                        "function": {"name": t.tool,
                                     "arguments": json.dumps(t.tool_input)},
                    }],
                })
            elif e["role"] == "feedback":
                msgs.append({"role": "tool", "tool_call_id": e["call_id"],
                             "content": e["result"]})
                msgs.append({"role": "user", "content": e["observation"]})
        return msgs

    def converse(self, system: str, transcript: Transcript) -> AgentTurn:
        import openai
        last: Exception | None = None
        for attempt in range(4):
            try:
                resp = self._c.chat.completions.create(
                    model=self.model, max_tokens=self.max_tokens,
                    messages=self._messages(system, transcript),
                    tools=_openai_tools(), tool_choice=self._tool_choice)
                break
            except (openai.RateLimitError, openai.APIStatusError) as e:
                last = e
                code = getattr(e, "status_code", 500) or 500
                if isinstance(e, openai.RateLimitError) or code >= 500:
                    time.sleep(2 ** attempt)
                else:
                    raise
        else:
            raise RuntimeError(f"openai-compat call failed after retries: {last}")

        msg = resp.choices[0].message
        text = (msg.content or "").strip()
        calls = msg.tool_calls or []
        if not calls:
            return AgentTurn(text=text, tool="", tool_input={}, call_id="")
        call = calls[0]
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        u = getattr(resp, "usage", None)
        usage = {"input_tokens": getattr(u, "prompt_tokens", 0),
                 "output_tokens": getattr(u, "completion_tokens", 0)} if u else {}
        return AgentTurn(text=text, tool=call.function.name, tool_input=args,
                         call_id=call.id or f"call_{int(time.time()*1000)}",
                         usage=usage)


# --------------------------------------------------------------------------- #
# factory
# --------------------------------------------------------------------------- #
_NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"

PROVIDERS = {
    "anthropic": {
        "default_model": "claude-sonnet-5",
        "key_env": ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"],
    },
    "nvidia": {
        "default_model": "meta/llama-3.3-70b-instruct",
        "key_env": ["NVIDIA_API_KEY"],
        "base_url": _NVIDIA_BASE,
    },
    "openai": {
        "default_model": "gpt-4o",
        "key_env": ["OPENAI_API_KEY"],
        "base_url": "https://api.openai.com/v1",
    },
}


def detect_provider() -> str:
    """Pick a provider from whichever key is present. Env var CUA_LLM_PROVIDER wins."""
    forced = os.environ.get("CUA_LLM_PROVIDER")
    if forced:
        return forced
    for name, spec in PROVIDERS.items():
        if any(os.environ.get(k) for k in spec["key_env"]):
            return name
    return "anthropic"


def build_client(*, provider: Optional[str] = None, model: Optional[str] = None,
                 max_tokens: int = 1500) -> LLMClient:
    provider = provider or detect_provider()
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; "
                         f"expected one of {sorted(PROVIDERS)}")
    spec = PROVIDERS[provider]
    model = model or os.environ.get("CUA_DISCOVERY_MODEL") or spec["default_model"]

    if provider == "anthropic":
        return AnthropicClient(model, max_tokens=max_tokens)

    key = next((os.environ[k] for k in spec["key_env"] if os.environ.get(k)), None)
    if not key:
        raise RuntimeError(
            f"provider {provider!r} needs one of {spec['key_env']} set")
    base_url = os.environ.get("CUA_LLM_BASE_URL") or spec["base_url"]
    tool_choice = os.environ.get("CUA_LLM_TOOL_CHOICE", "required")
    return OpenAICompatClient(model, base_url=base_url, api_key=key,
                              max_tokens=max_tokens, tool_choice=tool_choice)
