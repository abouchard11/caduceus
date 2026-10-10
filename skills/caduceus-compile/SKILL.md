---
name: caduceus-compile
description: "Compile the operator's gap vector into a seat cast, a generated USER.md, and per-seat skill loadouts, then run paired A/B councils against the loadout kill criterion. Use when seats/PROFILE.json changes, when skills land on this machine, when a real decision comes up while the clock runs, or when asked whether loadouts earn their keep."
version: 0.1.0
author: MidnightDev
license: Proprietary
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Compile, Loadout, Cast, Caduceus, Jev]
---

# Caduceus Compile

`cad compile` turns `seats/PROFILE.json` (the person as data) into `seats/CAST.json`,
`seats/USER.md`, and installed `skills/loadout/` trees in each seat's Hermes profile.
`cad eval loadout` runs one question twice, arm A without loadouts and arm B with, so
the ledger can settle both. Design and decisions: `docs/compile-design.md`.

## Steps, by trigger

**The profile changed.** `cad compile` shows the cast and whether USER.md is stale;
`cad compile --write` regenerates; `cad init` pushes USER.md into the seats. Done when
`cad doctor` shows the `profile` row OK.

**Skills landed on this machine.** `cad compile manifest`, then `cad compile propose`
(Jev scores the shelf; needs `TYPESAFE_API_KEY` in `~/.caduceus/env`, under a dollar).
Edit `seats/LOADOUT-PROPOSAL.json` into `seats/LOADOUT.json`, then `cad compile install`.
Done when `cad compile status` lists the seats' counts and the clock has started.

**A real decision while the clock runs.** `cad eval loadout "QUESTION" --context-file F`.
Done when both run ids are in `cad ledger runs`. Later, settle both arms or neither.

**Day 14.** `cad eval loadout report`. PASS keeps the loadouts; PARK means
`cad compile uninstall`, and the loadouts stay out until the shelf changes.

## Rules

1. Edit the JSON, never `seats/USER.md`; the doctor `profile` row catches drift.
2. The proposal is machine-written. The table you install is the one you read first.
3. A pair settles as two runs. One settled arm teaches the ledger nothing about the pair.
4. No key, no proposal. A hand-written `seats/LOADOUT.json` always installs.
5. Adding `TYPESAFE_API_KEY` sends each council question's text to TypeSafe for
   classification. Context files never leave the machine. Mock and dry runs never call it.
