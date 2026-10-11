# Changelog

## 0.5.0 — 2026-10-11
The cast flow for a second person (design `docs/compile-design.md` §11, decisions 25–27).
- A cast is a directory: `cad compile --profile P [--out DIR]` writes CAST.json, USER.md and
  rendered archetype souls beside the profile, never into Alex's `seats/`. `examples/` is a
  complete cast directory for the synthetic Thinker.
- Archetype seats (plant, coordinator, anchor, driver) resolve through `effective_seat`, accept
  casting overrides, and provision with `cad init --cast DIR`; a guest cast keeps Alex's USER.md
  in shared seats unless `--take-over` (backed up, reversible with `cad init`).
- `cad council ask --cast DIR` runs a cast's seats; `cad onboard PROFILE.json [--provision]
  [--ask Q]` is the one-verb path for a new person.
- Jev domain classifier: `cad eval classifier` (pre-registered, `docs/classifier-steer-design.md`)
  measured raw Jev as steerable (fake system line flipped the domain 56–62% of trials); the
  sanitizer took every hostile class to 0 flips and is now on by default. Context files never
  reached Jev; this closes the one live-input slot.
- Doctor: the root `--only third-party` guard hook (R23) is OK, a full root guard still FAILs.
- `cad followup nudge` prints the agenda and exits 0 when Telegram is unconfigured.
- Ledger CLI: settle/resettle/record split comma seat lists and validate names (0.4.x fix, PR #22);
  `cad ledger runs` shows pair/arm/lead; `cad compile` prints the USER.md diff.

## 0.4.0 — 2026-10-10
`cad compile`: the complement compiler (design `docs/compile-design.md`, decisions 11–24).
- `seats/PROFILE.json` is the person as data (PrinciplesYou taxonomy, any instrument maps
  in); `seats/USER.md` is generated from it, operating contract byte-identical; `seats/CAST.json`
  records the cast. Golden test: Alex's profile compiles to exactly the five seats.
- Archetype library of nine fixed roles; the vector staffs four to six. Four never-staffed
  archetypes (plant, coordinator, anchor, driver) carry soul templates.
- Jev (TypeSafe System One) in two bounded slots, never as synthesis: domain classification
  with keyword fallback and a believability blend below 0.6 confidence; offline skill scoring
  for loadout proposals. First-party endpoint, 1 MB body cap, range-checked answers, cost
  recorded in the memo, no egress on mock or dry runs.
- Skill manifest across four roots (`~/.claude/skills`, plugin cache, `~/.hermes/skills`,
  `skills/`) with a denylist of reach (`seats/DENYLIST.json`): send, publish, pay, deploy,
  settings, secrets never enter a seat.
- Static loadout install into `profiles/<seat>/skills/loadout/`, recorded and reversible,
  capped at 15 per seat; names validated as single path components, containment checked,
  symlinks preserved, secrets skipped.
- `cad eval loadout`: paired A/B councils under one pair id; `council_runs` gains `pair_id`,
  `arm`, `lead`; the pre-registered rule (3 B-wins and B > A at day 14) is computed by
  `cad eval loadout report` and never settles anything itself.
- Doctor rows `profile` and `loadout`; the morning brief carries the clock.
- Still owed from 0.3.3–0.3.5: changelog lines for the spend guard, the license change and
  the family guard (they landed on main without one).

## 0.3.6 — 2026-09-02
Adversarial review of the executor's write path (the seat-work executor runs
UNATTENDED from launchd, Mon/Thu 08:45, `--live`). Findings verified by
execution, not reading. Two were proven code-execution paths:
- B1: a model-written `conftest.py` was EXECUTED by the wrapper's own
  auto-pytest step — arbitrary code as the operator, no tools needed, so the
  `-t clarify` tool lock was irrelevant. Fixed: the wrapper never executes
  model output (auto-pytest deleted) and refuses every executable or loader
  suffix (`.py .sh .js .yml .toml .json …`, `Makefile`, `conftest.py`).
- B2: deny lists were case-sensitive on a case-insensitive filesystem —
  `.GIT/hooks/pre-commit` landed in the real `.git/hooks`. Fixed: casefolded
  deny lists, and any dot-prefixed path component is refused outright.
- B3: the `-t clarify` boundary was an unverified CLI flag with no detection
  if it stopped holding. Fixed: the tree is snapshotted around the model call;
  any file the wrapper did not write itself escalates and the reply is not
  applied — an invariant that does not depend on hermes' `-t` semantics.
- S8: no lock, so a manual run overlapping the launchd run double-spent.
  Fixed: `flock` single-flight on `exec.lock`; a second run returns empty.
- S9: push / deploy / install / PR / curl classified as staff work and reached
  the model — the only thing between them and reality was the model choosing
  to escalate. Fixed: a deterministic dangerous-verb floor escalates BEFORE
  any spend, no model consulted. Errs toward escalation ("release notes"
  trips "release") — a false positive lands on the operator's agenda, never
  silently.
- New doctor row: launchd jobs watched by their err log (both caduceus jobs
  had died silently with `invalid choice: 'exec'`).
- 28 new tests (179 total). Still open, budget/contract-class, listed in
  HANDOFF: S4 per-action cap vs actual cost, S5 daily gate fails open on an
  unreadable DB, S6 drift multiplier, S7 failed calls book $0, S10, S11.

## 0.3.5 — 2026-09-01
The ledger was scoring the operator's non-execution as the seats' failure.
4 of the 8 losses recorded 08-26..08-27 carried "never executed" notes: the
council's advice was never tried, and the ledger recorded that as the seat
being wrong. FINISHER sat at 0.261 (0/0/2) built entirely from untried advice
on runs where it was not even the lead — and those weights pick every future
council's lead. `followup.py` (#5) separates "not tried" from "tried and
wrong" going forward; the ledger could not express it.
- New `unexecuted` outcome: recorded per seat and run, closes the run, and
  carries ZERO weight in believability. `cad ledger settle … --unexecuted
  <seat>`. Shown as the `u` column in `cad ledger show` and the weekly brief.
- New `cad ledger resettle <run> …`: voids every prior outcome for the run
  (new `voided` column — history is kept, never deleted) and settles it again.
- Schema migration: SQLite cannot ALTER a CHECK, so the first open rebuilds
  `outcomes` in one transaction (rename → recreate → copy → drop), keeping
  every row byte-for-byte; idempotent on re-open. Tested against a
  legacy-constraint DB, and the test proven able to fail (a mutant that skips
  the rebuild turns it red).
- `n` in `Ledger.table()` now counts scored rows only (w+m+l).
- 7 new tests (143 total). Live: the four never-executed losses re-settled as
  `unexecuted` (backup at `~/.caduceus/ledger.db.bak-20260901-pre-unexecuted`).

## 0.3.4 — 2026-09-01
The 0.3.3 alerting fix was half-working, and its own health check could not
tell. The LLM-driven morning-brief cron had NEVER once written its
deliverable: its last run died on a 1040s idle timeout inside a subagent it
spawned via `delegate_task` (on the operator's spend), and the weekly job
reported `last_status=ok` on 08-31 having written nothing. So the cron-health
row added in 0.3.3 was a false green of exactly the class it was built to
catch — it read job status, and the only thing that matters is whether the
section landed in the file the operator reads.
- New `cad brief [--weekly] [--write]` (`caduceus/brief.py`): the operator
  brief is now DETERMINISTIC — stdlib gathers unsettled runs and unexecuted
  commitments (`followup.status()`), dead caduceus cron jobs, guard blocks in
  24h, and the ledger table, renders the section itself, and writes it into
  `~/CLAUDE-PENDING-ACTIONS.md` (the file surfaced at every Claude session
  start). Every item names its verb. No model in the path: nothing to time
  out, nothing to delegate, nothing to spend.
- Cron jobs are now `--script … --no-agent`: hermes runs
  `~/.hermes/scripts/caduceus-*.sh` AS the job and delivers stdout verbatim.
  `cad init --cron` writes the scripts and registers the jobs. No prompt.
- `cad doctor` gained a "brief delivery" row that checks the ARTIFACT: FAIL
  if the dated section was never written or is >30h old, naming
  `cad brief --write`. The 0.3.3 cron-status row stays as a secondary signal.
- `Ledger.register_run()` `memo_path` now defaults to `""`.
- 11 new tests (136 total). Verified live: section written by hand, then
  deleted and re-written by the no-agent cron on a triggered run.

## Unversioned — 2026-08-29 (PR #5, recorded 2026-09-02)
Landed on main without a CHANGELOG entry; recorded here so the log matches
history.
- `followup.py`: the loop between advice and reality. A council run is only
  finished when two loops close — was the lead recommendation acted on, and
  was it right. `ledger.settle()` closed the second; `cad followup
  list|open|done|drop` tracks the first. Prompted by run 20260819-123157:
  the memo was never acted on and the operator had no recollection of it.
- Ownership routing: `cad followup agenda|triage|split|nudge` — the operator's
  agenda shows only decisions that need a human.
- `executor.py`: agent-owned commitments execute behind a pre-flight,
  tool-locked gate ($15/day, $2 per action via `budgets.py`; unattended runs
  read and test, write only NEW files under an allowed root; push/deploy/
  network/installs never autonomous). The model returns data, a deterministic
  wrapper decides what touches disk — every call passes `-t clarify` because
  on the first live run FORGE wrote a file before the wrapper saw the reply.
- `docs/contracts/execution-run-contract.md`, `docs/flag-lifecycle-ledger.md`.

## 0.3.3 — 2026-08-26
Three silent-failure defects, all in the same family as the 0.3.1 inherited
fallback and the 0.3.2 tools lockdown: the config on disk drifted from the
config the engine believed it had, and nothing said so.
- **`cad init` fought `cad models set`.** `init()` iterated `SEATS` (the
  SHIPPED defaults) instead of `effective_seat()`, so a routine re-run
  silently reverted every recast seat in the live Hermes profiles — forge
  back onto the `alibaba-coding-plan` provider that 401s, finisher off a
  just-made recast, sparring back onto `hermes-4-405b` with its no-tools
  lockdown re-applied. `casting.json` survived; only the profiles were
  clobbered. Caught live on 2026-08-26 by running it.
- **The no-tools lockdown never lifted.** `apply_no_tools()` was applied when
  a seat was tools-incapable and removed by nothing, so sparring sat fully
  stripped (20 toolsets, tool_search off, both MCP servers dead) for days
  after its recast onto `google/gemini-3.7-flash` — running blind on a model
  that takes tools. The 0.3.2 note claiming `cad models set` lifts the
  lockdown was false in the shipped code. New `restore_tools()` is the exact
  inverse of `apply_no_tools()`, applied only when the profile carries the
  FULL lockdown signature on a tools-capable seat; a partial, operator-authored
  restriction never matches the signature and is never touched.
- **`cad doctor`'s model row was a whole-file substring test.** `seat.model in
  cfg.read_text()` matched an incidental mention in an unrelated block
  (`auxiliary.vision.model`, a provider registry) while `model.default` said
  something else, and `provider` was never checked at all — so forge reported
  `[OK]` while pointed at a 401ing endpoint. Now reads `model.default` and
  `model.provider` via the new `scalar_in_top()` reader, and names the fix.
- `cad doctor` also audits the tools lockdown in both directions now: a
  tools-incapable seat FAILs with `TOOLS-ATTACHED[...]` naming every live
  source, and a tools-capable seat WARNs with `TOOLS-STRIPPED-STALE` when a
  stale lockdown is still applied. Built on `tools_attached_sources()`, the
  inverse of the writer, so writer and verifier cannot drift apart.
- 14 new tests (113 total). Each regression shape is covered independently and
  the suite was mutation-tested — a no-op verifier and a disabled check both
  turn it red.
Operational note: the family rule was restored the same day. finisher had been
recast to `qwen/qwen3.8-27b` on 08-23 while forge was `qwen/qwen3.7-plus` —
`heterogeneity_warnings()` flagged "FINISHER shares FORGE's family", the exact
conformity failure the seat design exists to prevent. finisher is now
`anthropic/claude-sonnet-4.6`, the 08-19 council's own provisional pick. The
planted-defect eval that council asked for is still owed.

## Unversioned — 2026-08-22 → 2026-08-25 (recorded 2026-09-02)
Landed on main without a CHANGELOG entry; recorded here so the log matches
history.
- `82dda87` 08-22: permissive license replaced with a prospective proprietary
  notice ("PROPRIETARY — NO LICENSE GRANTED").
- `5ad6739` 08-25 (PR #3): spend guard — per-run ceilings and a daily cap,
  drift-calibrated (`budgets.py`); `hermes_home()` normalized when
  HERMES_HOME points at a seat profile; `heterogeneity_warnings()` enforces
  FINISHER≠FORGE family separation and flags duplicate families, and
  `cad models set` warns on the same at recast time.

## 0.3.2 — 2026-08-19
Codifies the third 2026-08-19 incident, which until now lived only as a hand
edit in `~/.hermes/profiles/sparring/config.yaml`: deleting that profile and
re-running `cad init` would have restored the 404.
- SPARRING (`nousresearch/hermes-4-405b`) has NO tool-capable endpoint on
  OpenRouter, and Hermes attaches tool definitions to every request from three
  independent sources: platform toolsets, the tool_search index, and each
  enabled MCP server. All three must be off — each 404 only names the source
  still standing, so fixing one at a time reads like the fix failed.
- New `Seat.tools_capable` flag (+ `config.TOOLS_INCAPABLE_MODELS` /
  `model_tools_capable()`); `patch_profile_config()` now writes
  `agent.disabled_toolsets`, `tools.tool_search.enabled: "off"` and
  `enabled: false` on every inherited MCP server for tools-incapable seats,
  idempotently. Tools-capable seats are left exactly as found — the lockdown is
  never applied in reverse, so an operator's own toolset choices survive.
- `models.effective_seat()` recomputes `tools_capable` from the model, so
  `cad models set sparring <tool-capable-model>` lifts the lockdown instead of
  leaving the seat stripped with no way back but hand-editing the profile.
- The top-level-block editor could not do this without destroying sibling keys
  (`agent.max_turns`, an MCP server's `command`/`args`), so seatsetup gained
  nested line-based editors: `set_child_block`, `set_scalar_in_child`,
  `child_keys`, `list_items`. Still stdlib-only, still comment-preserving.
- The disabled-toolset list is the known CLI set unioned with whatever
  `platform_toolsets.cli` the profile itself declares: Hermes ships new
  toolsets over time and one missed toolset brings the 404 straight back.
- 9 new tests (71 total), including a no-op pin against the exact hand-fixed
  profile shape. Verified live A/B on a throwaway cloned profile: HTTP 404
  before the patch, a real answer after it, `[=] already correct` on re-run,
  and byte-identical output against the real sparring config.

## 0.3.1 — 2026-08-19
Post-mortem of run 20260819-084035-cd968b (first live council): two seats
returned a raw OpenRouter HTTP 402 as prose and it became the memo's lead
recommendation. Three defects, all fixed:
- `hermes profile create --clone` copies the root profile's
  `fallback_providers` (a shared anthropic/claude-opus-4.6) into every seat:
  silent same-model failover that breaks family heterogeneity and, once the
  account has credits, silently bills at Opus prices. `cad init` now
  neutralizes it (`fallback_providers: []`) — seats fail loud, never reroute.
- The seat config patcher dropped the root's `max_tokens` cap while swapping
  the model block, so fallback calls reserved Hermes' 128k default.
  `model_block()` now always writes `max_tokens: 8192`.
- Council synthesis rescued unparseable text as a position, letting provider
  error prose outrank real drafts on a fresh ledger (all seats tied at the
  0.5 prior). Added a provider-error filter: 402/429/quota/billing text is
  recorded as a seat error, excluded from weighting, lead, and dissent.
- New: tests/test_seatsetup.py (provisioning had zero coverage — how all of
  this shipped) + incident-pinning tests in test_council.py. 56 tests.
Operational note: FINISHER's Minority Report correctly flagged the garbage
drafts in the live run. The dissent channel worked before the fix existed.

## 0.3.0 — 2026-08-19
- Telegram council bridge: `cad telegram runbook|init|test`, `--live` broadcasts
  on councils and plans. Verified against Bot API 10.0 (May 2026) bot-to-bot
  mechanics: command-mention/reply visibility only; K2 admin bot is the firehose.
- Design ruling: deliberation stays anonymized inside the engine; Telegram is
  coordination, broadcast, and the operator console. Allowlists mandatory.
- Doctor checks for telegram settings + per-seat bot tokens.

## 0.2.0 — 2026-08-19
- `cad models scan` — live OpenRouter market vs seat casting: promos, batch
  twins, price cliffs, blended-cost candidates (3:1 input weighting).
- `cad models set` — one-line seat recast with Hermes profile patching and
  family-collapse warnings. `cad models value` — $ per win by seat/model.
- Ledger outcomes carry model attribution; council memos carry cost footers.
- Market finding of record: google/gemini-3.7-flash 75% launch promo —
  recommended RECON swap; Gemini "Flash" no longer means budget.

## 0.1.0 — 2026-08-19
- Core engine: council deliberation (independent round → anonymized
  cross-exam → believability-weighted synthesis, no voting, Minority Reports),
  believability ledger (seat × domain, Laplace + 45-day half-life decay),
  destructive-command guard (23 rules, three tiers, two-person rule with
  single-use tokens), five psychometrically-cast seat souls, Hermes profile
  provisioning, HTML dashboard, caduceus-council skill, doctor.
- Stdlib-only Python. Configures Hermes (profiles, kanban, cron, gateways,
  hooks) rather than duplicating it.
