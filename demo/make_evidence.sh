#!/usr/bin/env bash
# Regenerate everything under evidence/. Starts the mock app in-process
# (--serve-mock); no external services.
#
# Discovery: if an LLM provider key is set in the environment (ANTHROPIC_API_KEY,
# NVIDIA_API_KEY or OPENAI_API_KEY), each capability is (re)discovered by a REAL
# model run. Otherwise it falls back to the offline scripted-discovery path,
# which drives the identical observe/act/record machinery with no model.
set -uo pipefail   # not -e: `replay` exits non-zero on an (expected) FAILURE outcome
cd "$(dirname "$0")/.."
PY=./venv/bin/python
E=evidence

have_key() { [ -n "${ANTHROPIC_API_KEY:-}" ] || [ -n "${NVIDIA_API_KEY:-}" ] || [ -n "${OPENAI_API_KEY:-}" ]; }
[ -f .env ] && set -a && . ./.env && set +a || true

rm -rf "$E"/discovery-* "$E"/replay-* "$E"/escalation-* "$E"/_interventions
mkdir -p "$E"

# lookup-savings-balance: a REAL LLM discovery run when a provider key is set,
# otherwise the offline scripted path.
if have_key; then
  MODE="real LLM"
  echo "## 1a. discovery — REAL LLM run (provider: ${CUA_LLM_PROVIDER:-auto})"
  $PY -m cua.cli discover \
    --goal "look up member {{member_id}} and read their current savings balance" \
    --param member_id=100042 --id lookup-savings-balance \
    --name "Look up member savings balance" \
    --description "Sign in, look up a member by id, open the record, and read the current savings balance." \
    --evidence-name "discovery-lookup-savings" --max-steps 18 --serve-mock \
    | grep -E "provider|outcome|capability"
else
  MODE="scripted (offline)"
  echo "## 1a. discovery — scripted, offline (no API key set)"
  $PY -m cua.cli discover --scripted demo/lookup_savings_balance.script.json \
    --goal "look up member {{member_id}} and read their current savings balance" \
    --param member_id=100042 --id lookup-savings-balance \
    --name "Look up member savings balance" \
    --description "Sign in, look up a member by id, open the record, and read the current savings balance and account status." \
    --evidence-name "discovery-lookup-savings" --serve-mock | grep -E "outcome|capability"
fi

# open-savings-subaccount: the risky multi-step flow, always via the scripted
# path so the safety demo is reproducible without depending on a rate-limited
# free-tier model completing a 12+ step run. See REPORT sec. 7.
echo "## 1b. discovery — open-savings-subaccount (scripted; risky-step safety demo)"
$PY -m cua.cli discover --scripted demo/open_subaccount.script.json \
  --goal "open a new Savings sub-account for member {{member_id}} with a {{deposit}} opening deposit and confirm it" \
  --param member_id=100042 --param deposit=250.00 --approve-risky \
  --id open-savings-subaccount --name "Open a Savings sub-account" \
  --description "Sign in, open a new Savings sub-account for a member with a given opening deposit, and confirm creation." \
  --evidence-name "discovery-open-subaccount" --serve-mock | grep -E "outcome|capability"

echo "## 2. deterministic replay — three result shapes + recovery + hard failure"
run() { echo "-- $1"; N=$1; shift; $PY -m cua.cli replay "$@" --evidence-name "replay-$N" --serve-mock 2>&1 | grep -E "SUCCESS|FAILURE|BUSINESS|evidence:"; }
run "success"                capabilities/lookup-savings-balance.json --param member_id=100042
run "business-not-found"     capabilities/lookup-savings-balance.json --param member_id=999999
run "business-permission"    capabilities/lookup-savings-balance.json --param member_id=100999
run "recovered-dialog"       capabilities/lookup-savings-balance.json --param member_id=100042 --inject dialog
run "recovered-timeout"      capabilities/lookup-savings-balance.json --param member_id=100042 --inject timeout
run "hard-failure-app-error" capabilities/lookup-savings-balance.json --param member_id=100042 --inject error
run "safety-risky-unapproved" capabilities/open-savings-subaccount.json --param member_id=100042 --param deposit=250.00
run "safety-risky-approved"   capabilities/open-savings-subaccount.json --param member_id=100042 --param deposit=250.00 --approve

echo "## 3. escalation + handoff"
$PY demo/escalation_demo.py

echo; echo "done ($MODE discovery) -> $E/"
