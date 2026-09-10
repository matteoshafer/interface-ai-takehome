# Design write-up

## 1. Architecture

One Python process, four commands (`discover`, `replay`, `catalog`, `operator`).
The spine is a single seam — **`Surface`** (`cua/surface/base.py`) — that
everything else is written against:

```
Surface.observe() -> Observation          # normalized a11y snapshot + page signals
Surface.locate(strategy, obs) -> handle   # resolve one targeting strategy
Surface.click / fill / select / read / press_key / screenshot
```

Above that seam nothing imports Playwright. The agent loop, the artifact schema,
the replay engine, the policy layer and the signal DSL all speak only
`Observation`, `Action`, `Selector` and `Signal`. `WebSurface` is the only
implementation; a legacy-frameset or desktop surface is a new class behind the
same contract (§4).

**Key decisions and trade-offs**

- **Accessibility tree, not DOM/CSS.** The brief's targets have no clean DOM, no
  test IDs, and are often not web at all. The a11y tree (role + accessible name)
  is the one representation legacy web apps *and* native desktop apps both
  expose, and it is close to what a human operator perceives. Playwright removed
  `page.accessibility`, so `WebSurface` reads the tree straight over CDP
  (`Accessibility.getFullAXTree`) and folds Chrome's layout-table noise out.
  Cost: the a11y name of a control can be ambiguous or empty in a bad legacy
  app — handled by the ordered fallback strategy (§3) and, ultimately, by
  screenshot coordinates.
- **The model runs exactly once, in `discover`.** Its only product is a
  `RunTrace`. `replay` never constructs an `anthropic` client. This is the
  record-once / replay-many thesis and it's what makes the capability cheap and
  auditable.
- **A compiler between the transcript and the capability.** `RunTrace ->
  Capability` (`cua/artifact/compiler.py`) drops every model message, keeps the
  causal actions, infers typed parameters/outputs, derives checkpoints from
  observations the agent actually saw, and attaches a curated exceptional-state
  catalogue. The artifact is a reviewable document, not a serialized transcript.
- **Flat files, no services.** Capabilities and evidence are JSON on disk in
  version control. Queues, workers and a tenant registry are explicitly *not*
  built — the abstractions are shaped so they could be, which is what the brief
  asked for.
- **One predicate language.** `cua/signals/dsl.py` (`url_matches`, `ax_present`,
  `text_matches`, `dialog_open`, `http_status`, `all_of/any_of/not`) is evaluated
  by one function and reused for step pre/post-conditions, the success
  checkpoint, and the `detect` clause of every business outcome and recovery.
  This keeps the schema small and the replay engine uniform.
- **Provider-agnostic discovery.** The brief makes the LLM provider a free
  choice. `cua/agent/llm.py` is the seam: the loop keeps a neutral transcript
  (context / agent-turn / feedback) and an adapter translates it to the
  provider's native shape. Two adapters — `AnthropicClient` (`tool_use` blocks)
  and `OpenAICompatClient` (`tool_calls`, covering **NVIDIA NIM**, OpenAI,
  Together, Groq, local vLLM). The provider is auto-detected from whichever key
  is set. Nothing else in the system knows which model ran.

## 2. Artifact schema

`cua/artifact/schema.py`. A capability is written as a **contract an agent can
call**, not a macro:

| Part | What it carries | Why shaped this way |
|---|---|---|
| `target` | `app_id` (vendor product), `tenant_id` (nullable), `entry` URL + `url_pattern` | Keyed by the **product**, not the tenant — one recording generalizes; per-tenant deltas are overlays (§4), not re-records. |
| `parameters[]` | name, type, `required`, regex `pattern`, `sensitivity` (`none`/`pii`/`secret`), `example` | The agent knows exactly what to pass; `validate_params` enforces it before the browser opens; redaction reads the same `sensitivity` tag. Secrets carry no `example`. |
| `outputs[]` | name, type, `source_step`, `read` (a `ReadSpec`: target + `extract` regex + `cast`), `sensitivity` | The agent knows exactly what it gets back and its shape. |
| `steps[]` | `intent` (human text, **not** model reasoning), `action`, `target` (ordered strategies), **`target_rationale`**, `risk`, `phase` (`auth`/`main`), `pre`/`post` signals | `target_rationale` is the "reasoning about robustness" the brief asks for. `phase` lets the re-auth recovery replay just the login steps. |
| `checkpoint` | one `Signal` | Asserted after the last step — proof we reached the goal state, not that a click "worked". |
| `known_outcomes[]` | name, `detect` signal, `returns` shape, `terminal` | **Expected business results** ("no such member"), returned structured — never an error. |
| `recovery[]` | name, `detect` signal, `handle` (`dismiss_dialog`/`wait_retry`/`reauth`), `max_attempts` | **Recoverable** runtime conditions, bounded. |
| `approval` | `draft` / `approved` (+ who) | Gates unattended replay of risky steps (§6). |
| `provenance` | model, timestamp, **`trace_hash`** (sha256 of the redacted trace), raw step count, optional stability | Reviewable lineage without storing the transcript. |

**Locator strategies are ordered, strongest first** (`cua/targeting/selector.py`):
`cell_at` (row × column, for data-grid values) → `role_name` → `anchor`
("the control in the row/section labelled X", for legacy inputs that share a role
and have no name) → `text` → `bbox_ratio` (viewport-fraction click point,
captured at record time). Replay records which one matched (§4 drift signal). The
compiler parameterises locator strings (`.../row for 100042` →
`{{ member_id }}`) and **strips value-based strategies that would bake regulated
data into the artifact** — a read of an account number keeps only its
row-anchor/coordinate locators.

Design is deliberately conservative where inference is uncertain: `known_outcomes`
and `recovery` come from a **curated per-app library** (`cua/artifact/library.py`)
merged in at compile time, because you cannot reliably discover every failure
mode in one happy-path run — the brief explicitly allows this seam.

## 3. Determinism & error handling

**Determinism.** No model calls. `validate_params` runs first. Each step:
render `{{param}}` into the locator → resolve strategies **in order**, and a
`missing` *or* `ambiguous` match is a hard failure (never "click the first one")
→ wait for DOM-settle plus the step's `pre`/`post` predicate (no fixed sleeps) →
act → verify. Same inputs ⇒ same steps ⇒ same outputs; outputs are re-extracted
via their declared `ReadSpec`.

**Error taxonomy** (`cua/replay/errors.py`, pure functions over
`(capability, observation)`, exhaustively unit-tested with synthetic
observations). After every action the new observation is classified:

- **business outcome** — matches a declared `known_outcomes[].detect`. Returns
  `ReplayResult(outcome="business_outcome", name, data, at_step)`. Terminal, not
  an error. *e.g. `member_not_found` → `{found: false}`.*
- **recoverable** — matches a declared `recovery[].detect`. Apply the bounded
  handler and re-attempt the step: `dismiss_dialog` (click a known control),
  `wait_retry` (backoff), `reauth` (re-run `phase=auth` steps **and replay the
  prior steps to restore navigation position**, then retry).
- **hard failure** — an app error screen (HTTP ≥ 500 or error text) or an
  **undeclared** modal. Stop, capture a screenshot + full AX snapshot + step
  context to `evidence/`, return
  `ReplayResult(outcome="failure", error_class, failed_step, expected, observed,
  evidence_dir)`.
- **clear** — proceed.

The result contract is a three-way discriminated union — `success{outputs}` /
`business_outcome{name,data}` / `failure{…}` — so the caller can't confuse "no
such member" with "the automation broke". `error_class` values:
`selector_missing/ambiguous`, `precondition/postcondition_failed`,
`checkpoint_failed`, `unexpected_dialog`, `app_error`, `recovery_exhausted`,
`needs_approval`, `policy_blocked`, `bad_params`.

**UI drift** is secondary here (these UIs are stable) but the ordered-strategy
model handles it: replay logs the matched strategy rank per step, so sustained
fall-through from `role_name` to `anchor`/`bbox` is a machine-readable signal
that a screen changed.

Evidence for every scenario is in `evidence/` — including
`replay-hard-failure-app-error/` (screenshot + `observation.json`) and
`replay-business-not-found/`.

## 4. Heterogeneity & multi-tenant

**Surface abstraction.** The recorded flow references only `Selector` and
`Signal`. "How we perceive/act" lives entirely in a `Surface` implementation.
- *Legacy frameset web app*: a `Surface` that flattens the frame tree into one
  `Observation` and, where the a11y tree is empty (non-semantic markup), falls
  back to OCR over a screenshot — the `bbox_ratio` strategy already in the schema
  is the join point.
- *Native desktop app*: a `Surface` over the OS accessibility API (UIA / AX).
  Role + name + the `anchor` and `cell_at` strategies all carry over unchanged;
  only `locate` and the act primitives are re-implemented.
The replay engine, schema, policy and error taxonomy do not change.

**Multi-tenant reuse.** Capabilities are keyed by `app_id`, not tenant
(`tenant_id: null` = the base). A `TenantOverlay` (designed, not built) is
`{app_id, tenant_id, version_range, overrides: {step_id: {target_append |
value_ref | risk}, checkpoint?, policy_ref?}}`; replay merges base + overlay. So
a tenant that renames "Member ID" to "Account holder #" or inserts one extra
interstitial (both present in the mock's `?tenant=west` variant) needs a small
overlay, not a re-recording.

**Drift detection & management.** Replay already records, per step, the matched
strategy rank; extend that with an AX-structure fingerprint of the entry screen
stored in `provenance.stability`. Sustained fall-through for one tenant → flag
"specialize this capability for tenant X". Entry-fingerprint mismatch beyond the
overlay's `version_range` → route that tenant to re-discovery. None of this
needs per-tenant infrastructure — it's signal emitted by the normal replay path.

## 5. Escalation & handoff

`cua/escalation/`. Triggers: the discovery agent is stuck (loop / dead-end /
max-steps — detected by a repeated (url, action) fingerprint), a replay hard
failure with a human available, or a risky step on an unapproved capability.

**Detect & route.** `SessionManager.escalate()` captures the live observation +
a screenshot, writes an `InterventionRequest` (capability, goal, step,
`ax_digest`, screenshot path, reason) to a file-backed queue, records the
transfer in an append-only **`ControlLedger`**, and blocks polling for a
response.

**Take control of the *same* session.** The `Surface` owns one long-lived headed
browser context; it is never torn down. The operator works in the window that is
already open — same page, same cookies, same DOM. The console
(`cua/escalation/console.py`, `operator` command) is a bare Flask page that
lists open requests, shows the context bundle + screenshot, and offers **Resume**
(with a free-text "what I did" note) / **Abort**.

**Hand back.** On Resume the `SessionManager` records the operator's note + a
before/after state digest into evidence, reclaims the token in the ledger, and
returns `"resume"`. The engine then **re-establishes navigation position** (the
operator's data changes persist; their navigation is safely redone) and retries
the step. A risky step the operator performed by hand is marked done — its action
is not repeated. `evidence/escalation-handoff/` shows a full round-trip:
`automation → operator (HTTP 500) → automation`, run completed.

**Mocked, and stated as such**: the console UI is deliberately minimal (a real
product is a co-browsing view). The *mechanism* — pause, cede on the same
session, ledger, resume, capture — is real.

## 6. Safety

`cua/policy/` + `policies/creditunion.yaml`, enforced at the single act seam so
**discovery and replay obey the identical policy**.

- **Allowlist**: `allowed_origins`, `allowed_routes` (path globs),
  `allowed_actions`. A navigation or action outside it is blocked — in discovery
  the agent gets an error observation and adapts; in replay it's a
  `policy_blocked` failure.
- **Risky vs. safe**: navigate/read/type/select/wait are safe; a click whose
  target's accessible name matches `risky_action_patterns` (`confirm and
  create`, `transfer`, `delete`, …) is risky. In **discovery** a risky action
  routes to an operator confirmation (default: deny → the agent stops at the
  review screen). In **replay** it is refused unless the capability's
  `approval.state == "approved"` *and* the step is `risk: risky` — otherwise
  `needs_approval` (or an escalation if an operator is wired). Rationale:
  irreversible back-office writes must never execute unattended on their first
  run.
- **Data handling**: a `Redactor` runs over **every** object before it is written
  to an artifact, log, trace or evidence file. Regex patterns (SSN, internal
  account numbers) and field names (`password`, `ssn`, `token`, …) are replaced
  with a stable `<redacted:HASH>` token — stable so a reviewer can still see "the
  same value recurs" without it being recoverable. Secret parameters are stored
  as `<supplied>`; the transcript is stored only as a `trace_hash`. The compiler
  additionally refuses to bake a redactable value into a locator string or its
  rationale. A test asserts no raw SSN/account-number pattern appears anywhere
  under `capabilities/` or `evidence/`.

**Limits**: redaction is pattern + field-name based — a novel PII format not in
the config passes through until added. Screenshots are captured but not yet
region-masked (a real deployment would blur the bbox of any node whose
role/name hits a sensitivity rule — the geometry is already available). The
allowlist is per-app, not per-role.

## 7. Cuts

Deliberately not built, each at a clean, documented seam:

- **The second capability's discovery.** `lookup-savings-balance` is a **real
  LLM run** — `deepseek-ai/deepseek-v4-pro-0813` via NVIDIA NIM, evidence in
  `evidence/discovery-lookup-savings/`, and the resulting artifact replays green
  across all eight scenarios. `open-savings-subaccount` (the risky-step safety
  demo, 12+ steps) is recorded via the offline **scripted-discovery** path
  instead — the free-tier model is rate-limited enough that a long run there is
  flaky, and the scripted path drives the *identical* observe/act/record
  machinery. Everything not covered by the one real run is covered by tests:
  `tests/test_llm_adapters.py` round-trips the transcript through both provider
  adapters against fake SDK clients; `tests/test_agent_loop.py` runs the real
  loop with a fake `LLMClient` that validates the transcript contract, exercises
  every stopping condition, and shows the LLM path compiles to the same artifact
  as the scripted path.
- **Model quirks are left in, not hand-fixed.** The DeepSeek run clicked *Search*
  once before entering the query, then navigated straight to
  `/members?q={{ member_id }}` — a redundant step and a clever recovery. The
  compiler recorded the path faithfully; replay verifies it. Curating it away
  would have made the artifact look better and the demonstration less honest.
- **Legacy-frameset and desktop surfaces**: design only (§4); `WebSurface` is the
  reference implementation.
- **Multi-tenant**: the schema (`app_id`/`tenant_id`), the `TenantOverlay` model
  and one variant app (`?tenant=west`) exist; the overlay merge and a tenant
  registry are not built.
- **Operator console**: real queue + control-transfer mechanism, minimal UI.
- **Assisted single-step LLM fallback on replay failure**, **confidence/approval
  scoring from multi-run stability**, and **route canonicalization** are sketched
  in the schema (`provenance.stability`, `approval`) but not implemented.
- **Queues / workers / persistence**: single process, JSON on disk.

**What I'd do next, in order**: (1) the `TenantOverlay` merge + the `west`
variant demo end-to-end; (2) multi-run stability scoring feeding an
`draft→approved` gate; (3) a bounded, policy-checked single-step LLM recovery on
replay failure, recorded as evidence.
