# ⚕ Caduceus

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23503124.svg)](https://doi.org/10.5281/zenodo.23503124)

**A multi-seat decision engine on Hermes Agent. Multiple snakes, one spine.**

The operator is the Shaper — vision, goals, final calls. The seats are staff,
cast to compensate the operator's measured gaps (PrinciplesYou: Organized 26,
Detail-Oriented 34, Empathetic 41) and cast across **four different model
families on purpose**, because same-family agents agree too easily.

Caduceus doesn't reinvent Hermes' infrastructure. Hermes already ships
profiles, a kanban dispatcher, cron, gateways, and hooks. Caduceus configures
those and adds the layer Hermes doesn't have: **a deliberation protocol with
a memory of who was right.**

## What it adds

| Piece | What it does |
|---|---|
| **Council** | Implicit-consensus deliberation: independent drafts → anonymized cross-examination → believability-weighted synthesis. No voting. Dissent is preserved as a Minority Report. Uncited position flips are logged as conformity. |
| **Believability ledger** | SQLite track record per seat × domain, Laplace-smoothed with 45-day half-life recency decay. Weights future councils. Only moves when you `settle` runs against reality. |
| **Guard** | Blocking `pre_tool_call` hook. CRITICAL commands (rm -rf /, mkfs, fork bombs) have no override. HIGH commands (force push, git reset --hard, DROP TABLE) need a second party — the two-person rule, where the second person is a *different model family* (FINISHER) or the operator. |
| **Seats** | Five Hermes profiles with psychometrically-derived souls: FORGE (implementer), FINISHER (verification gate), RECON (evidence), SPARRING (stress-test), ENVOY (tone pass). |
| **Dashboard** | One self-contained HTML status board: seats, ledger, recent memos, guard events, kanban snapshot. |

## The seats

| Seat | Model | Family | Job |
|---|---|---|---|
| FORGE | qwen3.7-plus (coding plan) | qwen | build + sequence |
| FINISHER | claude-sonnet-5 | anthropic | verify + gate + approve risky commands |
| RECON | deepseek-v4-pro | deepseek | research, cited + confidence-graded |
| SPARRING | hermes-4-405b | nous | attack plans, extend ideas, dissent |
| ENVOY | qwen3.7-flash | qwen | outbound tone pass, costs pennies |

Idle cost: **$0.** Everything is event-driven — councils, cron ticks, kanban
dispatch. "Always-on staff" without always-on burn.

## Install

```bash
cd ~/projects/caduceus
pip3 install -e . --break-system-packages   # stdlib-only package, adds `cad`
cad init                    # creates the 5 hermes profiles, souls, skill
cad init --cron             # + morning brief & weekly ledger digest
cad init --guard-write      # + wire the guard hook into config.yaml
cad doctor                  # verify everything end to end
```

## Use

```bash
# decisions
cad council ask "Ship Rabbithole now or keep polishing?" --quick
cad council ask "BIG QUESTION" --context-file notes.md      # full 4-family council

# the Emanuel loop: plan competition -> decomposition -> kanban
cad plan "Launch the CRE deal engine v1" --kanban

# risky command held by the guard? two-person rule:
cad council review-command -- git push --force origin main

# close the loop (this is what makes the engine compound)
cad ledger runs
cad ledger settle <run_id> --winner finisher --loser sparring
cad ledger show

# status
cad doctor && cad dashboard --open && cad seats status

# compile: profile -> cast -> USER.md; skills next to each seat's twitch finger
cad compile --write && cad init                              # after editing seats/PROFILE.json
cad compile manifest && cad compile propose                  # Jev scores the shelf -> LOADOUT-PROPOSAL.json
cad compile install && cad eval loadout "QUESTION"           # paired A/B against the kill criterion
```

## Design positions (deliberate, argue with the ledger)

1. **No majority voting.** Voting homogenizes; weighting by track record ×
   confidence keeps a correct minority alive. The memo always carries the
   strongest dissent.
2. **Heterogeneous by construction.** The full council spans 4 model
   families; a `heterogeneity_warnings` check nags you if you collapse it.
3. **The operator outranks the output.** Councils advise. Alex decides.
   `cad ledger settle` is the operator scoring reality back into the system.
4. **Configure Hermes, don't fork it.** Profiles, kanban, cron, gateways,
   hooks are Hermes-native. Caduceus is ~2K lines of stdlib Python on top.
5. **Unsettled advice never improves the ledger.** If you don't score
   outcomes, you've built a very expensive horoscope machine.

## Provenance

Deliberation protocol informed by consensus-free multi-agent debate research
(Free-MAD, arXiv:2509.11035; Roundtable Policy, arXiv:2509.16839) and
believability-weighted decision-making (Dalio). Workflow patterns (task
decomposition first, shared substrate over central orchestration, two-person
rule, command guards) follow the agentic-coding-flywheel school — clean-room
reimplementation, no third-party code vendored.

## Rights

**Apache License 2.0.** See [LICENSE](LICENSE).
