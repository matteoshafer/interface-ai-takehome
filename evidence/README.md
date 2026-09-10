# Evidence

Regenerate all of this with `bash demo/make_evidence.sh` (starts the mock app
in-process; no API key needed — see the note on discovery below).

Every file here has passed through the redactor: no raw SSN, account number, or
credential appears in any artifact or log.

## Discovery

| dir | how |
|---|---|
| `discovery-scripted-lookup-savings/` | goal → run → `capabilities/lookup-savings-balance.json` |
| `discovery-scripted-open-subaccount/` | goal → run → `capabilities/open-savings-subaccount.json` (has a risky step) |

Each holds `run.jsonl` (structured step-by-step log), `discovery_trace.json`
(redacted trace, decoupled from any model transcript), `capability.json` (the
compiled artifact), and `step_NN.png` screenshots.

> These discovery runs use the **offline scripted driver** (`cua discover
> --scripted demo/*.script.json`) so the whole pipeline reproduces without an
> API key. It exercises the identical observe → act → record machinery as the
> LLM loop. To produce the real LLM discovery evidence, run the `cua discover`
> command in `README.md` with `ANTHROPIC_API_KEY` set — it writes an equivalent
> `evidence/discovery-*/` directory.

## Replay (deterministic, no LLM)

| dir | scenario | outcome |
|---|---|---|
| `replay-success/` | member 100042 | `success` — outputs `{savings_balance: 4215.67, member_status: "Active"}` |
| `replay-business-not-found/` | member 999999 | `business_outcome: member_not_found` |
| `replay-business-permission/` | member 100999 (restricted) | `business_outcome: permission_denied` |
| `replay-recovered-dialog/` | `--inject dialog` | recovered (`maintenance_notice` → dismissed) → `success` |
| `replay-recovered-timeout/` | `--inject timeout` | recovered (`session_timeout` → re-auth + position restore) → `success` |
| `replay-hard-failure-app-error/` | `--inject error` | `failure: app_error` — see `failure.png` + `observation.json` |
| `replay-safety-risky-unapproved/` | risky step, draft capability | `failure: needs_approval` at the risky step |
| `replay-safety-risky-approved/` | risky step, `--approve` | `success` — new account number redacted in every output |

Each holds `run.jsonl`, `result.json` (the structured result contract), and — on
failure — `failure.png` + `observation.json` (full AX snapshot + page text).

## Escalation & handoff

`escalation-handoff/` — a replay hits an injected HTTP 500, files an intervention
request with full context, an operator takes control of the **same live browser
session**, resumes, and the run completes. See `run.jsonl`,
`control_ledger.jsonl` (`automation → operator → automation`),
`intervention_*.json` (request + operator note + before/after state), and
`intervention_replay_failure.png`.
