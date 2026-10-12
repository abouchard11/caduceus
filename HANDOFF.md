HANDOFF — 0.5.0, the cast flow (2026-10-11; read this block, then the blocks below)

Alex: "wire and unblock all road blocks … first-class and fully functional flow." Five blockers,
five changes, on main after PR #26: cast directories (a second person never writes into seats/),
archetype seats provisionable (`cad init --cast DIR`, `--take-over` guards Alex's seats), cast-aware
councils and `cad onboard`, the Jev classifier steerability gate measured and closed (sanitizer on
by default; raw Jev flipped 36–62% under a fake system line), doctor accepts the deliberate
third-party-only root hook (R23), `cad followup nudge` degrades without Telegram.
Live smoke recorded in docs/sessions/2026-10-11-cast-flow-smoke.md.

Still Alex's: send the demand probe (Gmail draft staged); settle pair 1's two arms and the drafting
run when it reports; day-14 report 2026-10-24; Telegram if he wants nudges pushed.

HANDOFF — state as of 2026-10-10 evening (read this block first; the compile-branch block and the 2026-09-01 state follow)

0.4.0 is on main (PR #19 merged 12725a6; PR #20 merged 64941fb). The launchd executor keeps calling
the editable install on main; `cad exec run` dry ran clean post-merge; 380 tests green on main.
Ledger backed up before the merge: ~/.caduceus/ledger.db.bak-0.4.0.

2026-10-12, provisioning fix: `hermes profile create` gets 240s (`seatsetup.CREATE_TIMEOUT`). If it
still leaves no profile, `cad init` stops before the next seat, names the seats not provisioned, and
exits 1; re-run once `hermes profile list` answers promptly. Cause: on 2026-10-11 hermes rebuilt its
Python environment at launch (68-85s) and the 60s default killed three creates in a row, each one
restarting the rebuild. The incident is pinned in tests/test_seatsetup.py.

Done today, in order:
1. `cad init` pushed the generated seats/USER.md into all five seat profiles (previous copies backed up).
2. TYPESAFE_API_KEY mirrored from ~/.hermes/.env into ~/.caduceus/env (mode 600). Live domain
   classification verified (source jev). From now on every live council question's text goes to
   TypeSafe for classification; context files never do; mock/dry runs never call it.
3. `cad compile manifest`: 763 skills across four roots. `cad compile propose`: 739 Jev calls,
   $0.20, 0 errors → seats/LOADOUT-PROPOSAL.json. Disposed into seats/LOADOUT.json (12 drops, each
   with its reason inside the file); the reach ones joined seats/DENYLIST.json.
4. `cad compile install`: 73 skills across 5 seats (cap 15). Hermes lists them as enabled.
   THE CLOCK STARTED 2026-10-10. Day 14 = 2026-10-24: `cad eval loadout report`.
5. First real pair: 20261010-180413-2e5e89 (-A no loadout, lead RECON; -B loadout, lead FINISHER; ≈$0.5).
   Both arms, independently: the first user is nobody yet. Next action is Alex's and is an
   external send: a 7-day, $0 demand probe to ~5 named peers who ALREADY hold a PrinciplesYou
   result ('export your result and I'll cast your agent staff for free, this week'). PASS only on
   revealed preference: unprompted continuation or referral, or a named commitment tied to a real
   upcoming task; compliments and a shared PDF do not count. Never serve a stranger's cast before
   the E2 steerability gate. Settle BOTH arms when the probe reports back.
6. Settled (Alex delegated the sheet, later the same evening): the merge gate (FINISHER+FORGE
   win), afe300 (unexecuted), 81f1ba (RECON win: X88 pre-registered as instructed), the Rule Map
   trio, 1758b8 and 0a05e3 (all unexecuted, zero weight, resettle if the advice later runs),
   383a56 (RECON mixed: no plugin filed, outbound never ran). Only pair 1's two arms remain open.
   Found and fixed on the way (PR #22): `cad ledger settle --winner a,b` used to store a seat named
   "a,b"; settle/resettle/record now split and validate names. The 2026-09-29 row that had a
   --note in the seat slot (run 20260929-233211-ea55cf) was re-settled on 2026-10-11 from its own
   recorded text: recon and sparring mixed. No malformed rows remain.
7. Demand probe drafted by ENVOY+SPARRING (run 20261010-215938-f356f5) and staged in
   hq/outputs/demand-probe-2026-10-10.md (the Drafts-app connector failed on its own side). The one
   message, the yes/maybe replies, the rules, the pass line and a five-row worksheet are there.
   What 0.4.0 can actually deliver to a stranger is a compiled cast as a document; the probe text
   promises exactly that. Recipients are Alex's: no record names a peer who holds a PrinciplesYou.

ALEX, still yours:
- Send the probe (five peers). Settle BOTH arms of pair 1 when it reports; day 14 report (2026-10-24).
- Pre-existing, not touched: `cad doctor` FAILs on the guard hook in your root Hermes config.yaml
  (the operator's profile must stay unguarded); `cad followup nudge` fails with Telegram unconfigured.
- Before a compiled council serves anyone but you: Jev steerability probe E2
  (hq/outputs/jev-usage-outline-2026-09-27-v2.md).

HANDOFF — compile branch, 2026-10-10 (read this block, then the 2026-09-01 state below)

Branch `feat/compile` (worktree `.claude/worktrees/compile`), NOT on main, NOT merged. Main is
untouched so the launchd executor keeps calling the editable install. 0.4.0. Suite green.

What landed (design `docs/compile-design.md`; plan `docs/superpowers/plans/2026-10-10-compile.md`;
ledger of rulings `docs/sessions/2026-10-10-compile-ledger.md`):
`cad compile [--write]` · `cad compile manifest|propose|install|uninstall|status` ·
`cad eval loadout "Q"` / `cad eval loadout report` · doctor rows `profile`, `loadout` · brief clock.

ALEX'S ACTIONS as written before the run (superseded by the block above; kept for the record):
1. Review and ship the PR. The 2026-08-19 USER.md is now generated from seats/PROFILE.json
   (same numbers, same contract block, prose regrouped); read the diff of seats/USER.md once.
2. Settle the 8 open council runs first (`cad ledger runs`). Decision 17: the loadout
   baseline is measured against a ledger of settled runs, not priors. `--unexecuted` for
   advice never tried.
3. Add `TYPESAFE_API_KEY=…` to `~/.caduceus/env` (never printed, never logged). Know what it
   turns on: every live council question's TEXT is sent to TypeSafe for domain classification;
   context files are not sent; mock/dry runs never call it. Without the key everything works on
   the keyword classifier and a hand-written loadout table.
4. `cad compile manifest && cad compile propose` (≈ under a dollar for the whole shelf; cached),
   edit `seats/LOADOUT-PROPOSAL.json` into `seats/LOADOUT.json`, `cad compile install`. That
   starts the 14-day clock.
5. For real decisions during those 14 days: `cad eval loadout "…" --context-file …`, then settle
   BOTH run ids when reality reports back. Day 14: `cad eval loadout report` → PASS keeps
   loadouts, PARK means `cad compile uninstall`.
Before any compiled council serves someone other than Alex: run the Jev steerability probe E2
(hq/outputs/jev-usage-outline-2026-09-27-v2.md); hostile-content steerability is untested.

HANDOFF — Caduceus state as of 2026-09-01
Read this first. It is the single source of truth for where things stand. Previous handoff was 2026-08-19 evening and went a full week stale; several of its claims were wrong by the time it was re-read (everything it listed as "unpushed" had shipped). Dates below are absolute for that reason.

What this project is
Caduceus: a five-seat AI decision council that runs on top of Hermes Agent. Alex is the Shaper (PrinciplesYou); the seats compensate his measured gaps. Seats deliberate independently, cross-examine anonymized drafts, and a believability-weighted synthesis picks a lead — no voting, dissent preserved as a Minority Report. `docs/DECISIONS.md` and `AGENTS.md` are load-bearing; read them before changing anything.

* Repo: github.com/abouchard11/caduceus (private) · local: ~/projects/caduceus
* Engine: stdlib-only Python. CLI = `cad` (installed editable via pip). Version 0.3.3.
* main = `a0b7131` (v0.3.3, PR #4), **fully pushed** — local and origin identical.

What landed since the 2026-08-19 handoff (all on origin/main)

* `5e15b92` 08-19 — v0.3.2: no-tools lockdown codified for tools-incapable seats.
* `e9fe43e` / `2fedee2` 08-19 — Field Notes 001 (seat casting) + seat-model evidence base (Perplexity deep research).
* `36722f6` 08-20 — PR #1: 2026-08-20 session note + IP record (Bouchard Breaker, not Caduceus data).
* `82dda87` 08-22 — permissive license replaced with a prospective proprietary notice.
* `5ad6739` 08-25 — PR #3: spend guard (per-run ceilings, daily cap, drift-calibrated), plus `hermes_home()` normalization when HERMES_HOME points at a seat profile, and a guard enforcing FINISHER≠FORGE family separation + council diversity.
* CHANGELOG still has no entry for the spend guard, the license change or the family guard (they landed on main without one). The 0.3.3 entry added here does NOT cover them — a catch-up entry is still owed.

Live engine state (`cad doctor`, 2026-08-26): 0 failures, 4 warnings. Hermes v0.20.5. Guard hook wired into all 5 seat profiles, 23 rules, `rm -rf /` → CRITICAL. 2 caduceus cron jobs. Warnings after the 0.3.3 fixes below: no gateways up (expected), telegram unconfigured (optional), 11 unsettled runs. All five seats green.

0.3.4 (2026-09-01) — THE 0.3.3 ALERTING FIX WAS HALF-WORKING. The re-registered LLM cron never
wrote the brief (timeout inside a delegate_task subagent; weekly job "ok" with nothing written), and
doctor's cron-status row could not see it. Now: `cad brief --write` is stdlib + deterministic, the
cron is `--no-agent` (script IS the job, no model, no spend), and doctor's "brief delivery" row checks
the dated section in ~/CLAUDE-PENDING-ACTIONS.md itself. Verified live 2026-09-01. The first real
brief surfaced an unexecuted 5-day-old commitment: file the $65 micro-entity US provisional
(run 20260827-025657-e55b18, followup 89356b82b722) — needs Alex.

0.3.5 (2026-09-01) — LEDGER NO LONGER SCORES NON-EXECUTION AS SEAT FAILURE. New `unexecuted`
outcome (zero weight, closes the run), `cad ledger resettle` (voids prior rows, history kept), and a
CHECK-constraint rebuild migration (backup: ~/.caduceus/ledger.db.bak-20260901-pre-unexecuted). The
four "never executed" losses ($100 run: envoy+finisher; feature flags: forge+finisher) re-settled as
unexecuted. Rule for future settlements: if the advice was never tried, `--unexecuted`, not `--loser`.

FINISHER EVAL — DESIGNED, NOT RUN (2026-09-02). `docs/finisher-eval-design.md`: 25 artifacts (13 seeded /
12 clean) across memos, guard verdicts, state records, and the existing 08-20 CLEAN/PLANTED premise set;
blind identical prompts; deterministic scoring (no judge model — Claude never grades Claude); decision rule
pre-registered (§7). Cost ≈ $9/pass, $18 for 2 passes. TWO GATES BEFORE IT RUNS, both Alex's: approve the
spend, and seed 3–4 defects himself blind to the harness author (§7 bias mitigation). Harness (`cad eval
finisher --dry-run`) is the next build step and spends nothing.

EXECUTOR WRITE PATH — ADVERSARIALLY REVIEWED 2026-09-02, TWO PROVEN EXPLOITS CLOSED, SIX FINDINGS OPEN.
`cad exec run --live --max 2` runs UNATTENDED from launchd Mon/Thu 08:45 (`~/Library/LaunchAgents/
dev.midnightdev.caduceus.exec.plist`) — it calls the editable install, so LEAVE MAIN CHECKED OUT. Review
(Opus, findings verified by execution) found: B1 a model-written conftest.py was executed by the wrapper's
own auto-pytest step; B2 deny lists were case-sensitive on APFS (".GIT/hooks/pre-commit" reached the real
.git/hooks); B3 the "-t clarify" tool lock was an unverified flag with no detection; S8 no lock, double
spend on overlap; S9 push/deploy/install/PR classified as staff work and reached the model. FIXED (0.3.6):
executable/loader suffixes refused, deny lists casefolded + dot-components refused, auto-pytest deleted
(the wrapper never executes model output), tree snapshot around the model call escalates on any
out-of-band write, flock single-flight, deterministic dangerous-verb floor before any spend.
STILL OPEN (do before trusting an unattended run with a NON-EMPTY queue — queue is empty today):
S4 $2/action cap is checked against a constant, never the actual cost; S5 daily household gate FAILS OPEN
when a profile state.db is unreadable; S6 DRIFT_MULTIPLIER not applied to executor spend (effective cap
~$37.5/day); S7 a failed/timed-out call books $0; S10 `_root_for` ignores the action (docstring false);
S11 docs/contracts/execution-run-contract.md mandates ops/run-guard.sh, a run ledger, a 3-abort breaker —
none exist; every execution to date is out of contract. Reviewer's one-line tests for each are in the
PR #11 body.

FINISHER EVAL — HARNESS BUILT 2026-09-02, NOT RUN, TWO GATES ARE ALEX'S. `cad eval finisher
[--dry-run] [--passes N] [--max-usd N]`. 30 real artifacts (18 seeded / 12 clean) in `evals/finisher/`,
rebuildable by `evals/finisher/build_items.py`; `answers.json` is the key and NEVER enters a prompt
(verified independently against all 30 items). Deterministic anchor+keyword scoring, so no judge model —
Claude never grades Claude. Decision rule pre-registered (design §7) and enforced in `decide()`:
ineligible candidates (qwen/*, deepseek/*) run as calibration baselines only and can NEVER take the
seat, whatever they score — the FINISHER-never-shares-FORGE's-family hard rule. REAL COST, measured by
dry-run: $2.62 for the full 2-pass x 6-candidate sweep (the design's $18 hand estimate was ~7x high).
GATES BEFORE RUNNING: (1) Alex approves the spend; (2) Alex seeds 3-4 defects himself, blind to the
harness author, so the set is not entirely Claude-authored (design §7 bias mitigation) — add them via
build_items.py and re-run it. Then `cad eval finisher --passes 2` and apply §7.

OPEN ITEMS (1 needs Alex's call; 2 and 3 resolved 2026-08-26)

0. **WHY ALEX NEVER SAW ANY OF THIS — root-caused and fixed 2026-08-26.** The morning-brief
cron had failed SILENTLY for 7 straight days: hermes `drift_skip` refused to run it after the
global model config changed (created under qwen3.7-plus/alibaba, global now gemini-3.7-flash),
and even a successful run delivered only to its own cron session log — the Telegram bridge
(the designed operator console) was never configured. `cad doctor` said cron [OK] the whole
time because it counted registered jobs, not their health. Fixed three ways: jobs re-registered
(fresh snapshot, drift cleared), brief prompts now write to ~/CLAUDE-PENDING-ACTIONS.md (which
every Claude session surfaces at start), and doctor now FAILs on failure_streak >= 3 naming the
fix. Settlement backlog delivered as ~/.caduceus/SETTLEMENT-2026-08-26.md — 5 pre-filled
verdicts awaiting Alex. The hermes-native "Morning briefing" job (google-workspace) is ALSO
dead 7 days (missing google_token.json, delivers to unconfigured telegram) — operator-side fix.


1. **The Decision #7 kill-criterion clock expired TODAY.** It started 2026-08-19: beat bare Hermes on 3 real tasks within a week, or park the engine. Four councils have run since (08-19, 08-20, 08-22, 08-23) — the work happened. But the ledger holds **1 settled outcome** against **11 unsettled runs**, and that one outcome is a *loss* (sparring, implementation, 0/0/1, score 0.346: "optimized a bad premise; nobody attacked the $100 target against $224k deal history"). On the ledger's own evidence the bar is not met. The honest reading is that settling was skipped, not that the engine failed — but that distinction is Alex's to make, and it cannot be made retroactively forever. Settle what is settleable or call the criterion.

2. **RESOLVED 2026-08-26 — casting drift had broken the family rule.** finisher had been recast to
`qwen/qwen3.8-27b` on 08-23 while forge sat on `qwen/qwen3.7-plus`; `heterogeneity_warnings()` flagged
*"FINISHER shares FORGE's family"* — the exact conformity failure the seat design exists to prevent.
Per Alex's call, finisher is now `anthropic/claude-sonnet-4.6` (the 08-19 council's own provisional
pick: recall 63% vs Sonnet 5's 50-51%, sycophancy 9.7). Hard rule satisfied. **Still owed:** the
planted-defect eval that council asked for as the permanence tiebreaker — 10-15 real Caduceus
artifacts with seeded defects, all candidates scored blind. Until it runs, 4.6 is provisional.

3. **RESOLVED — ENVOY.** Was `MODEL-NOT-SET` because its profile still said
`google/gemini-3.1-pro-preview` while casting said `qwen/qwen3.7-flash`; the casting-aware `cad init`
below fixed it. All five seats now green.

   Remaining, NOT a hard-rule break: the council spans 4 of 5 families — forge and envoy are both
   qwen. The 08-19 council routed this "forge-envoy dedup" onto its own evidence track. Envoy was
   deliberately set to a pennies model on 08-23, so this is a live tradeoff, not drift. Left alone.

THREE SILENT-FAILURE DEFECTS FOUND AND FIXED 2026-08-26 (v0.3.3)

1. **`cad init` fought `cad models set`.** `init()` iterated `SEATS` (shipped defaults) instead of
`effective_seat()`, so a routine re-run silently reverted every recast seat in the live profiles.
Found the hard way: running it during this session put forge back on the 401ing
`alibaba-coding-plan`, finisher back off its fresh recast, and sparring back on `hermes-4-405b` with
the no-tools lockdown re-applied. `casting.json` survived; only the profiles were clobbered.
Fixed + restored; `cad init` is now casting-aware.

2. **The no-tools lockdown never lifted.** `apply_no_tools()` was applied and removed by nothing, so
sparring ran blind for days after its recast onto tool-capable `google/gemini-3.7-flash`. The 0.3.2
CHANGELOG's claim that `cad models set` lifts it was false in the shipped code. New
`restore_tools()` is its exact inverse, applied only when the profile carries the FULL lockdown
signature on a tools-capable seat — an operator's own partial restrictions never match and are
never touched. Sparring's tools are back.

3. **`cad doctor`'s model row was a whole-file substring test.** It matched an incidental mention of
the cast model in an unrelated block while `model.default` said something else, and never checked
`provider` at all — so forge reported `[OK]` while pointed at a 401ing endpoint. Now reads
`model.default` + `model.provider` and names the fix.

MERGED — v0.3.3 landed on main 2026-08-26 evening (PR #4, merge a0b7131)

**116 tests green.** The editable-install `cad` CLI now runs it: doctor audits model.default +
provider, the tools lockdown in both directions, and cron health. Branch deleted after merge;
`pyproject` and origin are 0.3.3. Settlement sheet awaiting Alex: `~/.caduceus/SETTLEMENT-2026-08-26.md`
(5 pre-filled verdicts; also in ~/CLAUDE-PENDING-ACTIONS.md and the ⚖️ artifact).

Ledger state — 12 runs, 1 settled, 11 unsettled

* `20260823-224424-87364e` [strategy] Kiel's simulated swarm → real Caduceus/hermes/Graphiti stack. 4 seats, $0.376.
* `20260822-200125-27f347` [implementation] feature flags for gradual rollouts. 4 seats, $0.131.
* `20260820-210952-815711` [research] solo founder: open-source vs closed-and-sell. 4 seats, $0.098.
* `20260819-192012-65208e` [implementation] FINISHER seat + roster changes.
* `20260819-174310-c1e3f8` [review] case-study narrative.
* `20260819-172348-d50819` [implementation] MidnightDev's two private skills.
* `20260819-133940-5a1853` [implementation] productize Caduceus as IPIP-based SaaS.
* `20260819-123157-d54f01` — the clean $100 run. Settle when reality reports back.
* `20260819-132342-e54ae6` — the one SETTLED run (sparring loss).
* Never settle: `20260819-122812-e4ed43` (sparring 404 diagnostic), `20260819-115005-2ac9a3` (forge 401 diagnostic), `20260819-084035-cd968b` (the invalid 402 PassingWeather run).

Hard rules (do not violate)

* NEVER touch ~/projects/passingweather. Separate project, read-only embargo, another agent (Grok) is reviewing it.
* Never settle the three diagnostic/invalid runs above as real outcomes.
* No API keys/tokens in commits or logs. outputs/ stays gitignored. The only secret control is the content-based pre-commit scanner at `~/.claude/githooks/pre-commit`, reaching this repo through a **global** `core.hooksPath` — caduceus ships no `githooks/` dir of its own. Verify `git config --global core.hooksPath` still points there; a global hooksPath also means any repo-local `.git/hooks` here is silently ignored.
* Root ~/.hermes/config.yaml: don't add hooks (enforced by code + doctor FAIL), don't change its models. Its opus-4.6 fallback is Alex's daily-driver choice — flag concerns, don't edit.
* One writer per repo. If another agent/session is active in this tree, stop. (This bit 2026-08-19→26: two worktrees held overlapping uncommitted copies of the same v0.3.2 work.)
* Clean-room rule: patterns from Jeff Emanuel's flywheel are fair game; his code is not (license bars it).

Worktree hygiene

* `keen-moser-c37183` @ `5e15b92` — its work is merged; `5e15b92` is a verified ancestor of origin/main and the worktree is clean (`origin/main...branch` = 6/0). Safe to remove: `git worktree remove` + delete the branch.
* `frosty-antonelli-143bc8` @ `5ad6739` — holds the uncommitted doctor audit above. Keep until it lands.

Quick orientation commands

```
cad doctor
```

```
cad ledger runs
```

```
git -C ~/projects/caduceus log --oneline -8
```

Context that isn't in this repo

* PassingWeather (~/projects/passingweather): Alex's private wellness-notebook PWA, under independent review by Grok 4.6. Decision pending: cut to the letter / ship / park.
* Graphiti memory group for this project: `caduceus` (incident root causes and durable learnings live there).
