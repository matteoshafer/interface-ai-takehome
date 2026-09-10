"""The provider adapters: verify each one translates the neutral transcript into
its provider's native message shape, sends a well-formed request, and parses the
native response back into an AgentTurn. Fake SDK clients, no network.
"""
from __future__ import annotations

import json

import pytest

from cua.agent.llm import (AgentTurn, AnthropicClient, OpenAICompatClient,
                           build_client)
from cua.agent.tools import TOOLS

SYSTEM = "You are the discovery agent ..."

TRANSCRIPT = [
    {"role": "context", "text": "GOAL: x\n\nOBSERVATION ..."},
    {"role": "agent", "turn": AgentTurn(text="ok", tool="click",
                                        tool_input={"role": "button", "name": "Go",
                                                    "why": "advance"},
                                        call_id="c1")},
    {"role": "feedback", "call_id": "c1", "result": "ok. now at /next",
     "observation": "OBSERVATION 2 ..."},
]


# --- Anthropic -----------------------------------------------------------
class _FakeAnthropicMessages:
    def __init__(self, outer):
        self._o = outer

    def create(self, **kw):
        self._o.requests.append(kw)
        from anthropic.types import Message, TextBlock, ToolUseBlock
        return Message(
            id="msg_1", model=kw["model"], role="assistant", type="message",
            stop_reason="tool_use",
            usage={"input_tokens": 50, "output_tokens": 10},
            content=[TextBlock(type="text", text="searching", citations=None),
                     ToolUseBlock(type="tool_use", id="tu_9", name="type_text",
                                  input={"role": "textbox", "name": "Q",
                                         "text": "100042", "why": "search"})])


class _FakeAnthropic:
    RateLimitError = type("RateLimitError", (Exception,), {})
    APIStatusError = type("APIStatusError", (Exception,), {})

    def __init__(self):
        self.requests = []
        self.messages = _FakeAnthropicMessages(self)


def test_anthropic_adapter_request_and_parse():
    fake = _FakeAnthropic()
    c = AnthropicClient("claude-sonnet-5", client=fake)
    turn = c.converse(SYSTEM, TRANSCRIPT)

    req = fake.requests[0]
    assert req["system"] == SYSTEM
    assert req["tool_choice"] == {"type": "any"}
    assert [t["name"] for t in req["tools"]] == [t["name"] for t in TOOLS]

    msgs = req["messages"]
    assert msgs[0] == {"role": "user", "content": TRANSCRIPT[0]["text"]}
    # agent turn -> assistant with a text block + a tool_use block
    assert msgs[1]["role"] == "assistant"
    kinds = [b["type"] for b in msgs[1]["content"]]
    assert kinds == ["text", "tool_use"]
    assert msgs[1]["content"][1]["id"] == "c1"
    # feedback -> user with tool_result (matching id) + text
    assert msgs[2]["content"][0]["type"] == "tool_result"
    assert msgs[2]["content"][0]["tool_use_id"] == "c1"

    assert turn.tool == "type_text"
    assert turn.tool_input["text"] == "100042"
    assert turn.call_id == "tu_9"
    assert turn.usage == {"input_tokens": 50, "output_tokens": 10}


# --- OpenAI-compatible (NVIDIA / OpenAI / vLLM) -------------------------
class _Msg:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls


class _Call:
    def __init__(self, cid, name, args):
        self.id = cid
        self.type = "function"
        self.function = type("F", (), {"name": name, "arguments": args})()


class _FakeCompletions:
    def __init__(self, outer):
        self._o = outer

    def create(self, **kw):
        self._o.requests.append(kw)
        choice = type("Ch", (), {"message": _Msg(
            "searching", [_Call("call_9", "type_text",
                                json.dumps({"role": "textbox", "name": "Q",
                                            "text": "100042", "why": "search"}))])})()
        return type("Resp", (), {
            "choices": [choice],
            "usage": type("U", (), {"prompt_tokens": 60, "completion_tokens": 12})(),
        })()


class _FakeOpenAI:
    RateLimitError = type("RateLimitError", (Exception,), {})
    APIStatusError = type("APIStatusError", (Exception,), {})

    def __init__(self):
        self.requests = []
        self.chat = type("C", (), {"completions": _FakeCompletions(self)})()


def test_openai_compat_adapter_request_and_parse():
    fake = _FakeOpenAI()
    c = OpenAICompatClient("meta/llama-3.3-70b-instruct",
                           base_url="https://integrate.api.nvidia.com/v1",
                           api_key="nvapi-x", client=fake, tool_choice="required")
    turn = c.converse(SYSTEM, TRANSCRIPT)

    req = fake.requests[0]
    assert req["tool_choice"] == "required"
    assert req["tools"][0]["type"] == "function"
    assert req["tools"][0]["function"]["name"] == TOOLS[0]["name"]

    msgs = req["messages"]
    assert msgs[0] == {"role": "system", "content": SYSTEM}
    assert msgs[1] == {"role": "user", "content": TRANSCRIPT[0]["text"]}
    # agent turn -> assistant with tool_calls
    assert msgs[2]["role"] == "assistant"
    tc = msgs[2]["tool_calls"][0]
    assert tc["id"] == "c1" and tc["function"]["name"] == "click"
    assert json.loads(tc["function"]["arguments"])["name"] == "Go"
    # feedback -> tool message (matching id) + user observation
    assert msgs[3] == {"role": "tool", "tool_call_id": "c1", "content": "ok. now at /next"}
    assert msgs[4] == {"role": "user", "content": "OBSERVATION 2 ..."}

    assert turn.tool == "type_text"
    assert turn.tool_input["text"] == "100042"
    assert turn.call_id == "call_9"
    assert turn.usage == {"input_tokens": 60, "output_tokens": 12}


# --- factory -----------------------------------------------------------
def test_build_client_selects_provider_from_env(monkeypatch):
    monkeypatch.delenv("CUA_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CUA_DISCOVERY_MODEL", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    c = build_client()
    assert isinstance(c, OpenAICompatClient)
    assert c.model == "deepseek-ai/deepseek-v4-pro-0813"  # nvidia default


def test_build_client_forced_provider_without_key_errors(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("CUA_LLM_PROVIDER", "nvidia")
    with pytest.raises(RuntimeError):
        build_client()
