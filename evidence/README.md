# Evidence

Regenerate with `bash demo/make_evidence.sh` (starts the mock app in-process).
Every file here has passed through the redactor — no raw SSN, account number, or
credential appears in any artifact or log.

## Discovery

| dir | how | -> capability |
|---|---|---|
| `discovery-lookup-savings/` | **real LLM run** — `deepseek-ai/deepseek-v4-pro-0813` via NVIDIA NIM | `lookup-savings-balance.json` |
| `discovery-open-subaccount/` | scripted-discovery path (the risky-step safety demo; see `REPORT.md` §7) | `open-savings-subaccount.json` |

Each dir holds `run.jsonl` (structured step log), `discovery_trace.json` (redacted
trace, decoupled from the model transcript), `capability.json`, and `step_NN.png`.
The real run's `run.jsonl` shows `discovery_start` naming the provider/model and a
`model_turn` line per step with token usage.

`make_evidence.sh` uses a real `cua discover` for `lookup-savings-balance`
whenever a provider key (`ANTHROPIC_API_KEY` / `NVIDIA_API_KEY` / `OPENAI_API_KEY`)
is in the environment, and the offline scripted path otherwise — both drive the
identical observe/act/record machinery.

## Replay (deterministic, no LLM)

| dir | scenario | outcome |
|---|---|---|
| `replay-success/` | member 100042 | `success` — `{savings_balance: 4215.67}` |
| `replay-business-not-found/` | member 999999 | `business_outcome: member_not_found` |
| `replay-business-permission/` | member 100999 (restricted) | `business_outcome: permission_denied` |
| `replay-recovered-dialog/` | `--inject dialog` | recovered (`maintenance_notice`) → `success` |
| `replay-recovered-timeout/` | `--inject timeout` | recovered (`session_timeout` → re-auth) → `success` |
| `replay-hard-failure-app-error/` | `--inject error` | `failure: app_error` — `failure.png` + `observation.json` |
| `replay-safety-risky-unapproved/` | risky step, draft capability | `failure: needs_approval` |
| `replay-safety-risky-approved/` | risky step, `--approve` | `success` — new account number redacted |

Each holds `run.jsonl`, `result.json` (the structured result contract), and — on
failure — `failure.png` + `observation.json` (full AX snapshot + page text).

## Cross-tenant reuse (`demo/tenant_overlay_demo.py`)

`lookup-savings-balance` was recorded once. These three replay it, unmodified,
against a second tenant (`?tenant=west` — Westland FCU relabels the
member-search field from "Member ID" to "Account Holder #") to show reuse
without re-recording, and what the drift signal looks like before you add
anything:

| dir | run | search-field targeting |
|---|---|---|
| `replay-tenant-core/` | base capability, base (core) tenant — the control | `role_name` (rank 0) |
| `replay-tenant-west-no-overlay/` | base capability, **west**, no overlay | falls through to `bbox_ratio` (rank 3) — the drift signal |
| `replay-tenant-west/` | base capability **+ `overlays/west/lookup-savings-balance.json`**, west | `role_name` restored (rank 0) |

All three return the identical output (`{savings_balance: 4215.67}`); only the
targeting robustness differs. The overlay (a single `step_overrides` entry, no
re-recording) is what moves the search step from rank 3 back to rank 0.

## Escalation & handoff

`escalation-handoff/` — a replay hits an injected HTTP 500, files an intervention
with full context, an operator takes control of the **same live browser session**,
resumes, and the run completes. See `run.jsonl`, `control_ledger.jsonl`
(`automation → operator → automation`), `intervention_*.json` (request + operator
note + before/after state), and the screenshots.

## Demo video

`demo.mp4` — a ~75s Remotion walkthrough built from these screenshots.
