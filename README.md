# Computer-Use Automation System

An LLM drives a legacy back-office web app once to accomplish a goal, the run is
compiled into a **typed, versioned capability artifact**, and that artifact is
then **replayed deterministically with no model in the loop** — with a real error
taxonomy, a human escalation/handoff seam, and safety guardrails.

```
goal ──▶ LLM discovery run ──▶ capability artifact ──▶ deterministic replay ──▶ result
 (once, model in the loop)      (typed, reviewable)     (no model; the prod path)   success | business outcome | failure
                                                              │
                                                     stuck / risky / unrecoverable ──▶ human takes over the live session ──▶ resume
```

- **Target surface**: a local mock **credit-union back-office admin** app
  (`mockapp/`) — server-rendered, table layouts, no test IDs, injectable runtime
  faults, and a second "tenant" variant. Stands in for "core banking screens
  with no API".
- **Perception/action**: the **accessibility tree** (role + accessible name) over
  CDP, with screenshot + viewport-ratio coordinates as the documented fallback.
  Chosen because it's the one representation legacy apps *and* desktop apps both
  expose. See `REPORT.md`.
- **LLM**: provider-agnostic — Claude (`anthropic`), or any OpenAI-compatible
  endpoint (**NVIDIA NIM**, OpenAI, Together, Groq, local vLLM). Used **only** for
  discovery; the provider is auto-detected from whichever API key is set. See
  `cua/agent/llm.py`.

## Setup

```bash
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# A browser for Playwright. Either let Playwright fetch Chromium:
python -m playwright install chromium
# ...or point at an installed Chromium-family browser (Chrome/Brave/Edge):
export CUA_BROWSER_PATH="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"

cp .env.example .env      # for the discovery run only — add ONE provider key
```

`cua discover` needs an LLM API key; it auto-detects the provider from whichever
of these is set in `.env` (override with `--provider`):

| provider | key | where |
|---|---|---|
| `anthropic` (default) | `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
| `nvidia` (NVIDIA NIM — trial credits) | `NVIDIA_API_KEY` | build.nvidia.com/settings/api-keys |
| `openai` | `OPENAI_API_KEY` | platform.openai.com/api-keys |

Replay, the catalog, the operator console, and the entire test suite run without
any key.

## Demo path

Every command below can start the mock app itself with `--serve-mock` (it binds
`127.0.0.1:5050`). To run it separately: `python -m mockapp`.

```bash
# 1. DISCOVERY — one real LLM-driven run against the live app -> a capability
python -m cua.cli discover \
  --goal "look up member {{member_id}} and read their current savings balance" \
  --param member_id=100042 \
  --id lookup-savings-balance --name "Look up member savings balance" \
  --serve-mock                 # add --provider nvidia to force a provider
# -> writes capabilities/lookup-savings-balance.json  + evidence/discovery-*/

# 2. REPLAY — deterministic, no LLM
python -m cua.cli replay capabilities/lookup-savings-balance.json \
  --param member_id=100042 --serve-mock
# -> SUCCESS  outputs={'savings_balance': 4215.67, 'member_status': 'Active'}

# a legitimate business outcome (not an error):
python -m cua.cli replay capabilities/lookup-savings-balance.json \
  --param member_id=999999 --serve-mock
# -> BUSINESS OUTCOME  member_not_found  data={'found': False}

# an injected runtime fault -> a clear, debuggable failure with evidence:
python -m cua.cli replay capabilities/lookup-savings-balance.json \
  --param member_id=100042 --inject error --serve-mock
# -> FAILURE  app_error  step=s06...   (screenshot + AX snapshot in evidence/)

# injected faults the replay recovers from on its own:
python -m cua.cli replay capabilities/lookup-savings-balance.json \
  --param member_id=100042 --inject dialog  --serve-mock     # dismisses an interstitial
python -m cua.cli replay capabilities/lookup-savings-balance.json \
  --param member_id=100042 --inject timeout --serve-mock     # re-authenticates

# 3. SAFETY — a capability with a risky/irreversible step
python -m cua.cli replay capabilities/open-savings-subaccount.json \
  --param member_id=100042 --param deposit=250.00 --serve-mock
# -> FAILURE  needs_approval  step=s12...   (blocked: capability is draft)
python -m cua.cli replay capabilities/open-savings-subaccount.json \
  --param member_id=100042 --param deposit=250.00 --approve --serve-mock
# -> SUCCESS  (account number redacted in every persisted artifact/log)

# 4. ESCALATION + HANDOFF (two terminals)
python -m cua.cli operator --queue evidence/_interventions            # terminal A
python -m cua.cli replay capabilities/lookup-savings-balance.json \
  --param member_id=100042 --inject error \
  --escalate-on-failure --operator-queue evidence/_interventions \
  --headed --serve-mock                                                # terminal B
# B pauses and files an intervention; open http://127.0.0.1:5051, fix the live
# browser window if needed, click "Resume automation" -> B restores position and finishes.
# demo/escalation_demo.py runs the whole handoff self-contained (auto-operator).

# 5. CROSS-TENANT REUSE — the same artifact, a second tenant, no re-recording
python -m cua.cli replay capabilities/lookup-savings-balance.json \
  --tenant west --param member_id=100042 --serve-mock
# -> SUCCESS  (Westland FCU relabels the search field; overlays/west/*.json
#    is the only thing that changed -- see demo/tenant_overlay_demo.py for the
#    full 3-way comparison, incl. what happens with NO overlay at all)

# 6. CATALOG — saved capabilities as an agent-invocable tool surface
python -m cua.cli catalog                      # human-readable
python -m cua.cli catalog --json               # tool/function schemas
python -m cua.cli catalog --invoke lookup-savings-balance --param member_id=100042 --serve-mock
```

## Robustness matrix

Every branch of the error taxonomy (`REPORT.md` sec. 3), with the exact command
that reproduces it and where its evidence lives:

| result | error_class / outcome | reproduce | evidence |
|---|---|---|---|
| success | — | `replay lookup-savings-balance.json --param member_id=100042` | `evidence/replay-success/` |
| business outcome | `member_not_found` | `... --param member_id=999999` | `evidence/replay-business-not-found/` |
| business outcome | `permission_denied` | `... --param member_id=100999` | `evidence/replay-business-permission/` |
| recovered → success | `maintenance_notice` (dialog) | `... --param member_id=100042 --inject dialog` | `evidence/replay-recovered-dialog/` |
| recovered → success | `session_timeout` (re-auth) | `... --param member_id=100042 --inject timeout` | `evidence/replay-recovered-timeout/` |
| hard failure | `app_error` (HTTP 500) | `... --param member_id=100042 --inject error` | `evidence/replay-hard-failure-app-error/` (screenshot + AX snapshot) |
| hard failure | `bad_params` | `... --param member_id=abc` | fails before touching the UI |
| hard failure | `needs_approval` | `replay open-savings-subaccount.json ... ` (no `--approve`) | `evidence/replay-safety-risky-unapproved/` |
| hard failure | `action_failed` | a resolved-but-unusable control (e.g. `select`/`read` against a `bbox_ratio`-only match) | `tests/test_targeting.py`, `cua/surface/web.py` |
| escalation | `replay_failure` → human resumes | `demo/escalation_demo.py` | `evidence/escalation-handoff/` |
| drift signal | fall-through to a weaker locator strategy | `demo/tenant_overlay_demo.py` (unmodified capability vs. a relabeled tenant) | `evidence/replay-tenant-west-no-overlay/` |

`checkpoint_failed` and `unexpected_dialog` are exercised directly in
`tests/test_errors.py` (synthetic observations) and `tests/test_compile_replay.py`
(live). `selector_missing`/`selector_ambiguous` share the resolver code path
tested in `tests/test_targeting.py`. `precondition_failed`, `policy_blocked`,
`timeout`, and `recovery_exhausted` all raise through the same single `_Fail(...)`
call site each of the rows above already exercises — they are reachable, typed
outcomes rather than separately demonstrated scenarios.

## Running without live services

`replay` needs the mock app (local, `--serve-mock` starts it in-process) but
**never** the LLM. The test suite runs the mock app in-process too:

```bash
pytest -m "not integration"     # 33 unit tests, no browser (~0.5s)
pytest -m integration           # 25 tests, needs a browser (~100s)
```

`tests/test_llm_adapters.py` round-trips the neutral transcript through both real
provider adapters against fake SDK clients (native request shape + response
parse). `tests/test_agent_loop.py` runs the **real discovery loop** end to end
against a fake `LLMClient` that validates the transcript contract on every call,
exercises every stopping condition, and asserts the LLM path compiles to the
*same* artifact as the scripted path. The only thing not covered is the literal
provider network call.

`demo/make_evidence.sh` regenerates everything under `evidence/`. If a provider
key is set it does a **real `cua discover` run** for `lookup-savings-balance`
(the committed evidence was produced this way — `deepseek-ai/deepseek-v4-pro-0813`
via NVIDIA NIM); otherwise it falls back to the offline **scripted-discovery**
path. Both drive the identical observe/act/record machinery.

## Layout

```
cua/
  surface/      perceive + act seam (Surface protocol; WebSurface = CDP a11y tree)
  signals/      typed predicate DSL over an Observation (dsl + evaluate)
  targeting/    ordered, robustness-ranked locator strategies + resolver
  policy/       allowlist enforcement, risk classification, redaction
  agent/        the LLM observe->decide->act loop (+ an offline scripted driver)
  artifact/     the capability schema (focal point), compiler, store, curated library,
                tenant_overlay.py (cross-tenant reuse: merge, never re-record)
  replay/       deterministic engine, error taxonomy, result contract
  escalation/   session manager, intervention queue, control ledger, operator console
  cli.py        discover | replay | catalog | operator
mockapp/        the legacy credit-union admin proxy target (+ a `?tenant=west` variant)
capabilities/   compiled artifacts
overlays/       <tenant>/<capability id>.json — per-tenant deltas, not re-recordings
policies/       creditunion.yaml — the allowlist + risk + redaction config
evidence/       discovery + replay + escalation + cross-tenant run evidence
demo/           scripted action lists, escalation + cross-tenant-reuse demo scripts
```

## Demo video

`evidence/demo.mp4` — a ~88s walkthrough (problem → discovery → artifact →
replay's three result shapes → cross-tenant reuse → escalation handoff), built
with Remotion from the real evidence screenshots. Source + build instructions
in `demo/video/`.

See `REPORT.md` for the design, the schema, the determinism/error model, the
heterogeneity & multi-tenant story, and what was deliberately cut.
