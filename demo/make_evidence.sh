#!/usr/bin/env bash
# Regenerate the /evidence/ set. Runs the mock app in-process (--serve-mock).
# The discovery step here is the OFFLINE scripted path (no LLM) so this script
# is reproducible without an API key; replace it with the real `cua discover`
# (see README) to produce the LLM discovery evidence the brief asks for.
set -uo pipefail   # not -e: replay exits non-zero on a (expected) FAILURE outcome
cd "$(dirname "$0")/.."
PY=./venv/bin/python
E=evidence

rm -rf "$E"/discovery-* "$E"/replay-* "$E"/escalation-* "$E"/_interventions
mkdir -p "$E"

echo "## 1. discovery (scripted, offline) -> capability"
$PY -m cua.cli discover --scripted demo/lookup_savings_balance.script.json \
  --goal "look up member {{member_id}} and read their current savings balance" \
  --param member_id=100042 --id lookup-savings-balance \
  --name "Look up member savings balance" \
  --description "Sign in, look up a member by id, open the record, and read the current savings balance and account status." \
  --evidence-name discovery-scripted-lookup-savings --serve-mock | grep -E "outcome|capability"

$PY -m cua.cli discover --scripted demo/open_subaccount.script.json \
  --goal "open a new Savings sub-account for member {{member_id}} with a {{deposit}} opening deposit and confirm it" \
  --param member_id=100042 --param deposit=250.00 --approve-risky \
  --id open-savings-subaccount --name "Open a Savings sub-account" \
  --description "Sign in, open a new Savings sub-account for a member with a given opening deposit, and confirm creation." \
  --evidence-name discovery-scripted-open-subaccount --serve-mock | grep -E "outcome|capability"

echo "## 2. deterministic replay -- the three result shapes + recovery + hard failure"
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

echo; echo "done -> $E/"
