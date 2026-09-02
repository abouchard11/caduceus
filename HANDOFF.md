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
