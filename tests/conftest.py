"""Shared fixtures. The integration tests need Chromium (or a system Chrome/Brave
via CUA_BROWSER_PATH) and run the mock app in-process -- no external services.
"""
from __future__ import annotations

import socket
from pathlib import Path

import pytest

from cua.policy.config import PolicyConfig
from cua.policy.redact import Redactor

REPO = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO / "policies/creditunion.yaml"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def mock_base_url() -> str:
    from mockapp.server import MockServer
    port = _free_port()
    srv = MockServer(port=port)
    srv._thread.start()
    yield srv.base_url
    srv.stop()


@pytest.fixture
def policy() -> PolicyConfig:
    return PolicyConfig.load(POLICY_PATH)


@pytest.fixture
def redactor(policy) -> Redactor:
    return Redactor(policy)


@pytest.fixture
def run_dir(tmp_path, redactor):
    from cua.evidence import RunDir
    return RunDir(tmp_path / "run", redactor)


@pytest.fixture
def surface():
    from cua.surface.web import WebSurface
    s = WebSurface(headless=True)
    yield s
    s.close()


@pytest.fixture
def capability(mock_base_url, policy, redactor, tmp_path):
    """Compile the lookup-savings-balance capability from a scripted run once."""
    import json

    from cua.agent.loop import run_scripted
    from cua.artifact.compiler import compile_capability
    from cua.evidence import RunDir
    from cua.surface.web import WebSurface

    script = json.loads((REPO / "demo/lookup_savings_balance.script.json").read_text())
    s = WebSurface(headless=True)
    rd = RunDir(tmp_path / "discover", redactor)
    try:
        trace = run_scripted(
            goal="look up member {{member_id}} and read their current savings balance",
            target_url=f"{mock_base_url}/login", surface=s, policy=policy,
            redactor=redactor, run_dir=rd, script=script,
            params_hint={"member_id": "100042", "username": "operator",
                         "password": "demo-pass"})
    finally:
        s.close()
    return compile_capability(
        trace, cap_id="lookup-savings-balance",
        name="Look up member savings balance",
        description="Look up a member and read the savings balance.",
        redactor=redactor)
