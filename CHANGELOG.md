# Changelog

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
