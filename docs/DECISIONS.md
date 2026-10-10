# Decisions log

Dated, reasoned, in the open — argue with the ledger, not vibes. Append-only.

## 2026-08-19 — Founding decisions

1. **Alex gets no Shaper agent.** PrinciplesYou: he IS the Shaper (least-like:
   Implementer). The engine is his Implementer/Completer-Finisher layer. Seats
   sharpen, verify, execute; none originate strategy.
2. **No majority voting.** Implicit consensus: weight = believability(seat,
   domain) × confidence. Strongest dissent ships verbatim as a Minority
   Report. Uncited position flips are logged as conformity.
3. **Configure Hermes, don't fork it.** Profiles, kanban dispatcher, cron,
   gateways, hooks are Hermes-native. Caduceus adds deliberation,
   believability memory, and the guard. Anyone about to write a queue or
   scheduler in this repo: stop.
4. **Heterogeneity by construction.** Full council spans 4 model families;
   collapses trigger warnings. Same-family seats agree too easily.
5. **Guard is law.** CRITICAL = no override exists. HIGH = two-person rule,
   second person is a different model family or the operator. fail_closed.
6. **Unsettled advice never improves the ledger.** `cad ledger settle` is the
   compounding step; skipping it produces an expensive horoscope machine.
7. **Kill criterion, set day one:** pair engine must beat bare Hermes on 3
   real tasks within a week of first use, or we park it. (Precedent: the
   2026-07-29 ops-log warning against rebuilding K2 for its own sake.)
8. **Telegram = observation deck + operator console, never the deliberation
   bus.** Attributed group messages would break cross-exam anonymization and
   resurrect the conformity trap. Verified Bot API 10.0 mechanics support
   this split natively (command-mention/reply visibility only).
9. **Clean-room only re: Emanuel's tools.** Patterns are free; his license
   bars feeding his code to OpenAI/Anthropic systems. No vendored code.
10. **Repo stays private until the kill criterion passes.** The publish play
    ("I gave my AI staff a personality test") only works with receipts.

## 2026-10-10 — `cad compile`: the complement compiler (grilled, 16 decisions)

Full design: `docs/compile-design.md`. The grill (mattpocock `grilling`, run in hq)
settled these; Alex chose 11–13 himself and deferred the rest to the recommendation.

11. **Alex first, stranger-ready.** The profile is a data file (`seats/PROFILE.json`),
    never prose. A second person is a file swap. Nobody has asked for Caliber; no
    product work until someone does.
12. **Compile once; route live only after the kill criterion.** Loadouts are static
    per seat. Per-question routing is a post-criterion change.
13. **Canonical gap vector, PrinciplesYou taxonomy.** Trait → percentile, facets,
    source, confidence. Inferred traits must clear thresholds by 10 extra points.
14. **Scenario = domain.** The ten keyword domains plus `general`. Situations later.
15. **Loadout = 5 skills per seat per domain**, from a manifest of name+description
    scanned across four roots; static install capped at 15 per seat.
16. **Guard unchanged.** Loadout is reach; guard is refusal. Compile never writes a
    guard rule.
17. **Kill criterion:** beat the no-loadout council on 3 real settled paired runs
    within 14 days of first install, or park it and pull the loadout trees. Settle the
    8 open runs before measuring anything.
18. **Fixed archetype library, vector selects 4–6.** Alex's profile must compile to
    exactly the current five (golden test). The five hand-written souls stay verbatim.
19. **Compile never touches model casting.** `cad models set` stays the only way.
20. **Jev sits inside the harness, never as the harness.** Two slots: domain
    classification (keyword fallback; blend believability over the top two domains
    below 0.6 confidence) and offline skill scoring. Jev never picks a lead. First-party
    endpoint only. Steerability probe (E2) before any compiled council serves a stranger.
21. **Jev proposes, Alex disposes.** `LOADOUT-PROPOSAL.json` is machine-written;
    `LOADOUT.json` is the edited, versioned artifact that installs.
22. **Denylist of reach.** `seats/DENYLIST.json`: send, publish, pay, deploy, settings,
    secrets. Never compiled into any seat.
23. **Paired measurement.** Same question, arm A without loadouts, arm B with, both
    settled against the same reality. Rule pre-registered in the design §6.
24. **JSON, stdlib.** No YAML dependency enters this repo for a config file.
