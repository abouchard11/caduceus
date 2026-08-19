# First run — 15 minutes to a live council

Prereqs: Hermes Agent installed (`hermes --version` works), OpenRouter key in
`~/.hermes/.env` (`OPENROUTER_API_KEY=...`). Your Alibaba coding plan stays
the FORGE spine; the other seats ride OpenRouter.

## 1. Install (2 min)

```bash
cd ~/projects/caduceus
pip3 install -e . --break-system-packages
cad doctor        # expect FAILs - seats don't exist yet. That's honest.
```

## 2. Provision the seats (3 min)

```bash
cad init
```

What it does (idempotent, timestamped backups on any file it touches):
- `hermes profile create <seat> --clone --description "<role>"` × 5
- installs each seat's SOUL.md + the shared USER.md (your psychometric
  compensation map)
- patches each profile's `model:` block (FORGE=qwen3.7-plus/coding-plan,
  FINISHER=claude-sonnet-5, RECON=deepseek-v4-pro, SPARRING=hermes-4-405b,
  ENVOY=qwen3.7-flash) and adds a per-seat api_server block (ports 8651-8655,
  loopback only, shared key in `~/.caduceus/env`)
- copies ONLY the `OPENROUTER_API_KEY` line into seat envs that need it
- installs the `caduceus-council` skill into root + seat skill dirs
- prints the guard-hook block (not written until you say so)

## 3. Wire the guard (2 min)

```bash
cad guard test -- "rm -rf ~"        # see it catch things
cad init --guard-write               # appends hooks: block to config.yaml(s)
```

If a config already has a `hooks:` block it will NOT auto-merge — it prints
the snippet and you paste it. Deliberate.

## 4. First real council (5 min)

```bash
cad council ask "Should I ship Rabbithole this week or park it?" --quick
```

Quick mode runs FORGE + FINISHER; if they disagree it auto-escalates to the
full four-family council. Read the memo it prints — including the Minority
Report. Then, in a few days, when you know how it played out:

```bash
cad ledger settle <run_id> --winner <seat-that-was-right>
```

## 5. Optional: always-on staff (3 min)

```bash
cad seats up            # prints the launchd install commands
cad seats up --yes      # actually installs per-seat gateways
cad init --cron         # 7am brief + Monday ledger digest
cad dashboard --open
```

Gateways make seats resident (faster councils, session continuity) but
`hermes -z` fallback means everything works without them. Idle cost either
way: $0 — nothing calls a model until an event does.

## Troubleshooting

- `cad doctor` is the source of truth. Every FAIL line names its fix.
- Seat call fails with provider error → that seat's profile `.env` lacks
  `OPENROUTER_API_KEY`, or the model id changed. Both are one-line fixes in
  `~/.hermes/profiles/<seat>/`.
- Council slow → gateways down, so it's spawning `hermes -z` processes.
  `cad seats up --yes`.
- Port conflict on 8651-8655 → edit the seat's port in
  `caduceus/config.py` AND the profile's config.yaml, re-run `cad doctor`.
