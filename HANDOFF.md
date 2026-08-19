HANDOFF — Caduceus state as of 2026-08-19 (evening)
Read this first. It is the single source of truth for where things stand. Updated by the Claude Code session that closed out the v0.3.1 handoff tasks (guard-hook fix + first clean council run).

What this project is
Caduceus: a five-seat AI decision council that runs on top of Hermes Agent. Alex is the Shaper (PrinciplesYou); the seats compensate his measured gaps. Seats deliberate independently, cross-examine anonymized drafts, and a believability-weighted synthesis picks a lead — no voting, dissent preserved as a Minority Report. `docs/DECISIONS.md` and `AGENTS.md` are load-bearing; read them before changing anything.

* Repo: github.com/abouchard11/caduceus (private) · local: ~/projects/caduceus
* Engine: stdlib-only Python. CLI = `cad` (installed editable via pip).
* Seats: forge (qwen3.7-plus/alibaba-coding-plan), finisher (claude-sonnet-5), recon (deepseek-v4-pro), sparring (hermes-4-405b), envoy (qwen3.7-flash). All OpenRouter except forge. Key lives in ~/.hermes/.env (OPENROUTER_API_KEY).

What happened today (both waves)

Morning (Cowork session, v0.3.1 / commit 8c05c38): first live council 402'd because `hermes profile create --clone` had copied the root profile's uncapped opus-4.6 `fallback_providers` into every seat. Fixed: `cad init` writes `fallback_providers: []` + `max_tokens: 8192`; council.py filters provider-error text out of weighting/lead/dissent.

Afternoon (this session, commit 6091845 — NOT pushed):
* **Guard-hook fix (TDD):** `install_guard_hook()` no longer targets root `~/.hermes/config.yaml` — seat profiles only. The operator drives unguarded; agents don't. `cad doctor`'s guard check was also inverted: it now checks the 5 seat configs (OK when all guarded) and FAILs loudly if the hook ever regresses into root. 6 new tests; suite is 62 passed.
* **Cost tracking was silently empty** on every council run: `~/.caduceus/models_cache.json` had never been seeded (council never fetches pricing itself — offline-safe by design). Fixed by running `cad models scan`. Cache has a 24h TTL; if `costs: {}` shows up again, re-run `cad models scan`.
* **First CLEAN council run** of the $100-revenue question: `20260819-123157-d54f01` (seats finisher, recon, envoy · 142.8s · $0.096 total · zero errors, zero 402 text). Lead ENVOY: warm-DM a $150 "pay after you see it" off-market Class C buyer list to 3 verified CRE contacts, after confirming a live payment rail. FINISHER dissent preserved: confirm payment mechanism + data access in writing BEFORE any outreach. **This run starts the Decision #7 kill-criterion clock (2026-08-19): beat bare Hermes on 3 real tasks within a week, or park the engine.**

Open blockers (operator-side, in priority order)

1. **FORGE is down.** `alibaba-coding-plan` returns `HTTP 401: invalid access token or token expired` on every call (reproduced with `hermes -p forge -z "..."`). The provider auths with DASHSCOPE_API_KEY in ~/.hermes/.env — key present but rejected, so it's expired/revoked or the Qwen Coding Plan subscription lapsed. Alex must re-issue at modelstudio.console.alibabacloud.com or renew the plan. Until then, quick mode (`--quick` = FORGE+FINISHER) cannot work; use `--seats finisher,recon,envoy`.
2. **SPARRING 404s on OpenRouter:** `No endpoints found that support tool use. Try disabling "clarify"` (hermes-4-405b routing). Separate from FORGE's issue. Likely fix: provider-routing config or disabling tool use for oneshot calls — uninvestigated.
3. **Push to GitHub** once Alex approves (git push stays operator-side). Two local commits ahead: 8c05c38 (v0.3.1) and 6091845 (guard-hook fix).

Ledger state (4 unsettled runs — only ONE is settleable)

* `20260819-123157-d54f01` — the clean $100 run. Settle this when reality reports back: `cad ledger settle 20260819-123157-d54f01 --winner <seat>`.
* `20260819-122812-e4ed43` — diagnostic (sparring 404'd, costs empty). Do not settle.
* `20260819-115005-2ac9a3` — diagnostic (forge 401'd, single-seat memo). Do not settle.
* `20260819-084035-cd968b` — the INVALID 402 run (PassingWeather question). NEVER settle. The PassingWeather question itself is still unanswered — re-ask it once Grok's review verdict is in, if still wanted.

Hard rules (do not violate)

* NEVER touch ~/projects/passingweather. Separate project, read-only embargo, another agent (Grok) is reviewing it.
* Never settle the three diagnostic/invalid runs above as real outcomes.
* No API keys/tokens in commits or logs. outputs/ stays gitignored. The `githooks/pre-commit` scanner is the only secret control — verify it fires on commit.
* Root ~/.hermes/config.yaml: don't add hooks (now enforced by code + doctor FAIL), don't change its models. Its opus-4.6 fallback is Alex's daily-driver choice — flag concerns, don't edit.
* One writer per repo. If another agent/session is active in this tree, stop.
* Clean-room rule: patterns from Jeff Emanuel's flywheel are fair game; his code is not (license bars it).

Optional hardening, only if Alex asks: seat gateways (`cad seats up`), cron briefs (`cad init --cron`), Telegram bridge (`cad telegram runbook`).

Quick orientation commands

```
cd ~/projects/caduceus
cad doctor                 # health; every FAIL names its fix
git log --oneline -5       # 6091845 = guard-hook fix (unpushed)
ls -t ~/.caduceus/runs/    # council memos, newest first
cad ledger runs            # unsettled decisions
```

Context that isn't in this repo

* PassingWeather (~/projects/passingweather): Alex's private wellness-notebook PWA, under independent review by Grok 4.6. Decision pending: cut to the letter / ship / park. Its verdict may become the council's next real task.
* Graphiti memory group for this project: `caduceus` (incident root causes and durable learnings live there).
