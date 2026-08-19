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
