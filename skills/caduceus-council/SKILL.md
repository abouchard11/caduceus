---
name: caduceus-council
description: "Run multi-seat council deliberations, the believability ledger, the two-person command rule, and the Caduceus dashboard via the `cad` CLI. Use for big decisions, plan competitions, risky-command approvals, and morning briefs."
version: 1.0.0
author: MidnightDev
license: Apache-2.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Council, Decisions, MultiAgent, Ledger, Guard, Caduceus]
---

# Caduceus Council

Caduceus is the decision layer over this Hermes installation. Five seats
(FORGE, FINISHER, RECON, SPARRING, ENVOY) deliberate with implicit consensus:
independent drafts, anonymized cross-examination, believability-weighted
synthesis, and a preserved Minority Report. The operator (Alex) is the
Shaper and outranks every output.

## When to use

- The operator asks for a decision, a plan, a review, or "what do the seats
  think" - run a council instead of answering alone.
- A shell command got HELD by the guard - run the two-person review.
- Morning brief / status - regenerate the dashboard and read the ledger.

## Commands

Quick decision (cheap pair, auto-escalates on disagreement):

    cad council ask "Should we ship X now or refactor Y first?" --quick

Full council (4 heterogeneous model families):

    cad council ask "QUESTION" --context-file notes.md

Plan competition then decomposition (optionally straight into kanban):

    cad plan "GOAL" --kanban

Risky command held by the guard (two-person rule, FINISHER is reviewer):

    cad council review-command -- git push --force origin main

Ledger (believability only moves when runs get settled):

    cad ledger runs                # what awaits judgment
    cad ledger settle RUN_ID --winner finisher --loser sparring
    cad ledger show                # seat x domain scores

Status:

    cad doctor                     # is the engine wired
    cad dashboard                  # regenerate HTML status board
    cad seats status               # per-seat gateway + model

## Telegram council group (when configured)

The supergroup is the observation deck and the operator's console — NOT the
deliberation channel. Etiquette, enforced:

1. Seat-to-seat handoffs use command-mentions (`/task@CaduceusForge_bot ...`)
   or direct replies — that is the only way another seat bot hears you
   (Bot API 10.0 bot-to-bot rules).
2. Reply-depth cap on bot-to-bot chains: **2**. Past that, stop, summarize
   in one message, and tag the operator.
3. Deliberation drafts NEVER go to the group. Councils run anonymized inside
   the engine; only final attributed positions are posted (`--live`).
4. Dedup before acting: if a command-mention duplicates work already in the
   kanban or a live council, say so in one line instead of doing it twice.
5. The operator's messages outrank any bot's. Always.

Useful commands: `cad telegram runbook` (setup), `cad telegram init --write`
(bind seats), `cad telegram test`, `cad council ask "..." --live`.

## Rules for agents using this skill

1. Read the memo it prints (path in output). The Minority Report section is
   load-bearing - surface it to the operator, never just the winner.
2. After reality tests a council's advice, SETTLE THE RUN. Unsettled runs
   are flagged by `cad doctor` and the morning brief.
3. Never bypass a guard HELD verdict by rephrasing the command. Request the
   review or ask the operator.
4. Councils cost tokens: default to `--quick` for small decisions; full
   council for irreversible or expensive ones.
