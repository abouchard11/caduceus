# Spend Guard — Spec (FINISHER-owned, FORGE-implements)

**Status:** spec complete, awaiting `cad plan` / FORGE pickup
**Author:** FINISHER seat, 2026-08-22
**Trigger:** Bot Pack group-chat incident; Michael's indefinite-loop deep-research design (unbounded parallel agents = unbounded spend)

## 1. Problem, with measured numbers

The Bot Pack group (2026-08-22, 02:05–04:53 CDT) ran six seats in one room
against a one-line config fix. Measured from each profile's
`state.db → session_model_usage`:

| seat    | est. cost | input tokens | output tokens | api calls |
|---------|-----------|--------------|---------------|-----------|
| recon   | $6.597    | 4,185,166    | 143,234       | 218       |
| forge   | $5.130    | 7,431,049    | 147,760       | 296       |
| envoy   | $1.027    | 382,176      | 91,650        | 78        |
| finisher| $0.727    | 51,437       | 48,933        | 206       |
| sparring| $0.609    | 1,279,828    | 17,790        | 71        |
| hermes  | $0.194    | 4,399,786    | 66,215        | 111       |
| **total** | **$14.284** |          |               |           |

Operator reported ~$40 on the OpenRouter invoice for the night. The
estimate-vs-actual gap (~2.8x) is a design input, not a footnote:
`cost_status='estimated'` rows understate real billing. The guard must be
conservative by default.

Cost amplifier identified: forge accumulated **7.4M input tokens** —
group-room history is re-injected on every turn. Any multi-seat or long-history
pattern compounds cost on *input*, not output.

## 2. What already exists (verified — do not rebuild)

1. **Telemetry is free.** Every Hermes profile's `state.db` has
   `session_model_usage` with `api_call_count`, `input_tokens`,
   `output_tokens`, `cache_read_tokens`, `cache_write_tokens`,
   `reasoning_tokens`, `estimated_cost_usd`, `actual_cost_usd`,
   `cost_status`. PK: (session_id, model, billing_provider, ...).
   Read it; never instrument a parallel counter.
2. **Guard infrastructure exists.** `caduceus/guard.py`: stdin JSON hook,
   exit-2 + `{"decision":"block"}` to block, JSONL audit log at
   `~/.caduceus/guard.log.jsonl`, TTL'd approval tokens in
   `~/.caduceus/approvals/`, `config.py` path helpers. Wire into this;
   do not create a second guard.
3. **No native Hermes spend cap.** Checked: `config.yaml` has only
   `max_tokens: 8192` (per-completion output). Nothing enforces session,
   daily, or dollar ceilings. This guard is not duplication (AGENTS.md
   "Don't duplicate Hermes" satisfied).
4. **Hook limitation (verified).** The guard runs as `pre_tool_call` on
   `terminal|code_execution`. It CANNOT intercept model calls directly.
   A pure chat runaway (no tool calls) escapes it. Mitigation in §4 Layer C.

## 3. Requirements

R1. **Hard per-run ceiling.** Every `cad council` run and every caduceus-
    spawned multi-seat job gets a dollar budget at dispatch. Exceeding it
    aborts the run *before the next model call where the architecture
    allows*, and blocks all further tool calls where it does not.
R2. **Daily global ceiling** across all profiles. Warn at 80%, hard stop
    of autonomous (cron/council) runs at 100%.
R3. **Fail-closed for autonomous runs; fail-open-but-loud for the
    operator's interactive sessions.** Alex typing directly is never
    locked out — but an autonomous runaway is.
R4. **Operator overrides** via explicit `cad budget` commands, not by
    editing state. Two-person rule (existing token mechanism) for raising
    a ceiling mid-run.
R5. **Audit trail.** Every check, warn, and abort lands in the existing
    `guard.log.jsonl` with run id, session, cumulative spend, ceiling.
R6. **Stdlib only** (AGENTS.md), idempotent installs, tests green
    (`python3 -m pytest tests/ -q`).
R7. **Visibility:** `cad budget status` (current spend vs ceilings) and
    a spend row on `cad dashboard`.

## 4. Design — three layers

### Layer A: run budgets + guard consultation (R1, R5)

- New `caduceus/budgets.py`. A run budget = JSON record at
  `~/.caduceus/budgets/<run_id>.json`: run_id, origin (council|cron|plan),
  seats involved, ceiling_usd, started_at, per-check cumulative spend
  (recomputed by summing `estimated_cost_usd` from the participating
  profiles' `session_model_usage` for the run's session ids — read-only
  sqlite queries, no new writes into Hermes' DBs).
- `cad council ask` writes the budget record at dispatch before the first
  seat turn. `cad plan` decomposition likewise.
- `guard.py::decide()` gains one step: before returning allow, look up the
  active budget for the calling session; if cumulative spend >= ceiling,
  return exit-2 block with a message naming run_id, spend, and ceiling.
  Since runaway loops hit tools constantly, this is an effective choke
  point even though it cannot see model calls themselves.
- Soft warning at 80% of run ceiling: allow + context note (existing WARN
  channel), logged.

### Layer B: calibrated ceilings (R1, R2)

Defaults derived from the incident table above, where a *healthy* quick
council should be a fraction of what the pathological run cost:

| scope                          | soft warn | hard stop |
|--------------------------------|-----------|-----------|
| quick council (2 seats)        | $0.50     | $1.00     |
| full council (4 seats)         | $1.50     | $3.00     |
| single autonomous seat run     | $0.75     | $1.50     |
| daily, all profiles combined   | $8.00     | $10.00    |

All overridable: `cad budget set --run <id> --ceiling <usd>` requires a
two-person approval token (existing HIGH-severity path in guard.py) when
raising; lowering is free. Operator may set ceilings to `off` for an
interactive session — logged as an override event.

### Layer C: the monitor cron (R2, gap from §2.4)

- New cron job (Hermes-native cron — do not build a scheduler), every
  15 minutes: aggregate today's `estimated_cost_usd` across all six
  profiles' `state.db`; aggregate active run budgets.
- At 80% of daily ceiling: warn to the operator's home channel.
- At 100%: pause autonomous caduceus runs (set `paused` flag on active
  budget records; guard reads it) and report. Does NOT kill the gateway
  or operator sessions (R3).
- This layer is the only defense against a pure-chat runaway (no tool
  calls); 15 min of exposure at observed worst-case rates (~$0.50/min
  during the incident) caps worst-case overshoot at ~$7.50. Document this
  residual risk; tightening the interval is a one-line change.

### Estimate-drift policy (the $40 vs $14.28 gap)

Apply a conservative multiplier to estimated cost when comparing against
ceilings: `effective_spend = estimated * 2.5` until actuals prove
otherwise. Calibrate quarterly against OpenRouter invoices. If the
OpenRouter credit-usage API is reachable with existing keys, poll it in
Layer C and prefer `actual_cost_usd`. (FORGE to verify API availability
during implementation; not verified at spec time.)

## 5. Out of scope

- Per-model pricing tables (Hermes already computes estimates).
- Rate-limit handling (Hermes-native).
- OpenRouter account-level credit caps (set those in the OpenRouter UI —
  recommended as a belt-and-suspenders backstop independent of this guard).

## 6. Definition of done

1. `pytest tests/test_budgets.py` green: budget record lifecycle, guard
   consultation (allow/warn/block paths), daily aggregation math, drift
   multiplier, override token flow.
2. Manual drill: seed a budget with a $0.01 ceiling, run a terminal
   command in a session bound to it → expect guard block with run id.
3. `cad doctor` reports guard + budget wiring healthy.
4. `cad dashboard` shows today's spend vs daily ceiling.
5. One real council run end-to-end with budgets active; spend row present
   in `guard.log.jsonl`.
6. FINISHER review passes before merge (this seat gates, does not build).

## 7. Handoff

FORGE implements. Known landmines for the implementer:
- `session_model_usage` lives in each PROFILE's state.db; path resolution
  must survive a seat's `HERMES_HOME` pointing at its own profile
  (`config.hermes_home()` already handles this — reuse it).
- sqlite reads must be read-only (`mode=ro` URI) so a guard bug can never
  corrupt Hermes state.
- Hook timeout is 10s (see hooks/caduceus_guard.py header) — six sqlite
  reads per tool call is fine; do not add network calls to the hook path.
  OpenRouter polling belongs in Layer C cron, never in the hook.
