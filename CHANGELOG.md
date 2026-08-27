# Changelog

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
