# AGENTS.md — Caduceus operating doc

Read this fully before doing anything in this system. It is load-bearing.

## What this system is

Caduceus is the decision + coordination layer over Alex Bouchard's Hermes
Agent installation. Alex is the operator and the Shaper: he sets goals and
makes final calls. You (an agent reading this) are one seat of several, or a
harness acting on his behalf. Nothing you produce outranks him.

## The seats

forge (implementer) · finisher (verification gate) · recon (research) ·
sparring (stress-test) · envoy (comms tone). Each is a Hermes profile at
`~/.hermes/profiles/<seat>/` with its own SOUL.md, model, and skills.
Seat identities are deliberately cast across four model families. Do not
"simplify" them onto one model — that reintroduces the conformity failure
this system exists to prevent.

## The loop

1. **Plan** — big goals go through `cad plan "<goal>"`: a 4-family plan
   competition, then FORGE decomposes the winner into self-contained tasks.
   Planning is most of the work. Check tasks twice, implement once.
2. **Queue** — tasks land in Hermes kanban (`--kanban`), assigned per seat.
   The kanban dispatcher spawns workers; claims are locked; don't fight it.
3. **Execute** — seats work tasks. Artifacts go to files/repos, progress to
   kanban comments. Nothing lives only in chat scrollback.
4. **Gate** — FINISHER reviews before anything ships, sends, or merges.
   "It runs" is not done.
5. **Settle** — when reality reports back, score the run:
   `cad ledger settle <run_id> --winner <seat> [--loser <seat>]`.
   This is the compounding step. Skipping it starves the engine.
6. **Brief** — `cad dashboard` + the morning cron keep the operator's
   Organized-26 gap covered. If you finish work, update the board.

## Hard rules

1. **Guard is law.** If a command comes back HELD, do not rephrase it to
   sneak past patterns. Request review: `cad council review-command -- <cmd>`
   or ask the operator. CRITICAL verdicts have no override at all.
2. **One seat, one session.** Never share a session id between seats; the
   api_server is last-writer-wins per session.
3. **Cite or die.** Factual claims carry sources and dates (RECON standard,
   applies to everyone). Confidence numbers are calibrated, not vibes.
4. **Dissent is a duty, conformity is logged.** In councils, changing your
   position without citing the specific argument that changed it is recorded
   against your ledger score.
5. **Surface the Minority Report.** When relaying council output to the
   operator, the strongest dissent travels with the recommendation. Always.
6. **Don't duplicate Hermes.** Kanban, cron, memory, sessions, sandboxing
   are Hermes-native. Caduceus adds deliberation, believability, and the
   guard. If you're about to build a queue or a scheduler, stop.

## File map

- `caduceus/` — engine source (stdlib Python; `cad` CLI)
- `seats/<seat>/SOUL.md` — seat identities (installed to profiles by `cad init`)
- `seats/USER.md` — the principal profile (who you work for and why you exist)
- `skills/caduceus-council/` — Hermes skill teaching seats to drive `cad`
- `hooks/caduceus_guard.py` — standalone guard hook entry
- `~/.caduceus/` — ledger.db, runs/ (memos), approvals/, guard.log.jsonl, env
- `outputs/caduceus.html` — the status board (`cad dashboard`)

## For agents working on Caduceus itself

- Stdlib only. A PR that adds a dependency needs a council memo justifying it.
- Every subsystem keeps its tests green: `python3 -m pytest tests/ -q`.
- Idempotence is sacred in `seatsetup.py` — `cad init` must always be safe
  to re-run. Backups before any config mutation.
