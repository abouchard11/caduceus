# Caduceus architecture

## Thesis

Alex's PrinciplesYou profile: Shaper. Creative 94, Determined 98, Composed 99;
Organized 26, Detail-Oriented 34, Empathetic 41; least-like archetype:
Implementer. The engine is the staff he doesn't have: implementation,
verification, evidence, stress-testing, tone — with a decision protocol that
resists the two documented multi-agent failure modes: conformity collapse
(sycophantic convergence) and unweighted democracy (expertise drowned by
noise).

## Layering — configure Hermes, add only what's missing

```
┌─ OPERATOR (Alex) ── goals, final calls, ledger settlement ─┐
│                                                            │
│  CADUCEUS (this repo, ~2K lines stdlib Python)             │
│    council.py   deliberation protocol (the new thing)      │
│    ledger.py    believability memory  (the new thing)      │
│    guard.py     hard command policy   (the new thing)      │
│    dashboard.py status board                               │
│    seatsetup.py provisioning (writes INTO hermes, below)   │
│                                                            │
│  HERMES AGENT (Nous) — already installed, we configure it  │
│    profiles   = seat identities (SOUL.md, model, skills)   │
│    kanban     = durable work queue + dispatcher + swarm    │
│    cron       = recurring loops (morning brief, digests)   │
│    gateway    = resident seats + api_server (OpenAI-compat)│
│    hooks      = pre_tool_call guard attachment (blocking)  │
│    memory     = per-seat session memory, MEMORY.md         │
└────────────────────────────────────────────────────────────┘
```

Anti-goals: no queue, no scheduler, no memory system, no sandbox of our own.
Hermes ships all four. Duplication is drift.

## The council protocol

Derived from consensus-free multi-agent debate findings (Free-MAD
arXiv:2509.11035 — trajectory over final vote; Roundtable arXiv:2509.16839 —
confidence-weighted aggregation; collective-bias phase transitions
arXiv:2608.02827) applied with a machete: no RL, no Kendall's W, nothing that
needs a GPU to make a decision.

1. **Independent round.** Same brief to every seat, zero cross-visibility.
   Structural anti-conformity beats prompted anti-conformity.
2. **Quick gate (HCP-style).** FORGE+FINISHER only, for cheap questions.
   Agreement (jaccard ≥ 0.35 on recommendation, both confidence ≥ 0.6) →
   early stop. Disagreement → auto-escalate to the full council.
3. **Cross-examination.** Each seat sees rival drafts ANONYMIZED and
   shuffled (judge arguments, not authors/brands). Must attack before
   revising. A position change without a cited cause = conformity flag.
4. **Synthesis without voting.** weight(seat) = believability(seat, domain)
   × stated confidence. Top weight leads the memo; the strongest
   disagreeing position ships verbatim as the Minority Report. Unanimity is
   labeled suspicious in the memo itself.

## The believability ledger

`score = (Σ decayed_wins + 1) / (Σ decayed_outcomes + 2)` — Laplace prior
0.5, exponential recency decay (45-day half-life), domain-level with
seat-global fallback. Moves ONLY via `cad ledger settle/record` — i.e. when
reality, not another model, grades the advice. This is Dalio's
believability-weighting reduced to a table and honest arithmetic, and it is
the engine's long-term moat: after 90 days the weights encode which model
family is actually good at what, per domain, for YOUR work.

## The guard

23 original pattern rules, three tiers. CRITICAL = no override exists (the
operator can still run things in a terminal himself; agents cannot).
HIGH = two-person rule: single-use, 15-minute, SHA256-command-bound token
granted by the operator or by FINISHER (`cad council review-command`) — a
different model family than the requester, by design. WARN = allow + log +
annotate. Wired as a Hermes `pre_tool_call` hook with `fail_closed: true`:
if the guard crashes, the tool call is blocked, not waved through.

One rule is not a pattern. **Third-party repositories** (CRITICAL, added
2026-10-08 on the operator's word: "I do not want Hermes touching stuff like
this"): `git push`, and writes through `gh` or the GitHub REST API, are blocked
when the target is a repository the operator does not own. The target comes
from `--repo`, a URL, or the remotes of the clone the command runs in (the hook
payload's `cwd`, followed through any `cd`). One of his forks counts as
third-party when the same clone has a remote for somebody else's repository of
the same name, because pushing to that fork is how an upstream pull request
changes. Reading is never blocked. Not covered: `gh api graphql` mutations, SSH
host aliases, a browser.

The operator's own profile runs no destructive-command guard, by his choice
(`seatsetup.install_guard_hook`). It runs this one rule alone:
`cad guard hook --only third-party`.

## Transports

ApiTransport (per-seat gateway, OpenAI-compatible, session continuity,
loopback + bearer key) → OneshotTransport (`hermes -p <seat> -z`, stateless,
zero-config fallback) → MockTransport (tests, --dry-run). Auto-selection per
seat per call. One session id per seat — api_server is last-writer-wins
within a session.

## Failure modes we accept in v1

- Agreement detection is lexical (jaccard), not semantic. Cheap, wrong
  sometimes, always visible in the memo. Upgrade path: FINISHER judges
  agreement (costs a call).
- `cad plan` dependency links print for manual `hermes kanban link` wiring.
- Ledger settlement is manual. The kanban verifier-gate hook
  (`kanban_task_completed`) is the designed auto-settle path; deferred to v1.1.
- Seat model ids are pinned in config.py; OpenRouter deprecations require a
  one-line change (doctor will surface the provider error).
