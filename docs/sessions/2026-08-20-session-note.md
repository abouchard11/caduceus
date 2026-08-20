# Session note — 2026-08-20

Long session. Most of it was **not** Caduceus work. Recorded here so the history is accounted for
and so the next Caduceus session doesn't inherit conclusions that were never about Caduceus.

## What actually happened to Caduceus: nothing

No code changed. No seats were recast. No runs were settled. The engine is exactly as the
2026-08-19 HANDOFF left it.

## What the session was really about

A separate project — **Bouchard Breaker**, a three-terminal edge primitive for agent graphs
(`~/projects/bouchard-breaker`, Graphiti group `bouchard-breaker`). It originated in the
`agentic-graph-orchestration` skill, not here. Its IP record is parked in `docs/ip/` for the commit
timestamp only; see `docs/ip/README.md`.

## Findings that DO bear on Caduceus

Two, and both are uncomfortable enough to write down.

**1. The one settled ledger row is a loss, and it is a correlated-error loss.**
`sparring | implementation | loss`, with the operator's own note: *"optimized a bad premise; nobody
attacked the $100 target against $224k deal history."* Five seats across four model families,
structural anti-conformity, mandatory cross-examination — and the single graded outcome is the
council collectively failing to challenge the frame. That is n=1 and proves nothing statistically.
It is also the only empirical evidence in the building, and it points against DECISIONS #4
(heterogeneity by construction). Nobody had looked at it.

**2. "It beat solo drafts twice" is not in the ledger.** That claim lives in `~/.claude/CLAUDE.md`
as operator self-report. It should not be cited as evidence for the engine until something is
actually settled against a comparison.

**Related, from outside research:** measured mean pairwise error correlation across a nine-model,
seven-vendor LLM judge panel was ~0.39, giving ~2 effective independent votes at k=9 — and the
paper's own headline was that the best single judge matched or beat the full panel in every
condition (Kohli, arXiv 2605.29800). Same-family vs cross-family was a weak predictor of
independence. If that generalizes, cross-family seat casting is a weaker decorrelation lever than
DECISIONS #4 assumes.

## Correction issued

A research agent **fabricated** the claim that `caduceus/ledger.py` is "cross-seat, agent-influenced"
and constitutes a covert channel between seats. It is false — settlement runs through
`Ledger.settle()` driven by the operator via CLI, auto-settle is deferred to v1.1 per
ARCHITECTURE.md, and the table held one manually entered row. The claim was repeated to the operator
before being verified. A correction episode was written to Graphiti group `caduceus`.

## Still open (unchanged from the 2026-08-19 HANDOFF)

- DECISIONS #7 kill-criterion clock: beat bare Hermes on 3 real tasks by **2026-08-26**.
- 1 settleable run: `20260819-123157-d54f01`. Three diagnostic/invalid runs must never be settled.
- Push to GitHub — being done now, via this PR.

## Tooling

`claude-patent-creator` was installed and repaired this session (unpinned `mcp` ceiling took 2.0.0,
which removed `mcp.server.fastmcp`; `setup` exits 0 on failure; its printed registration command
pointed at a Python without the dependencies). MPEP index built — 52,694 chunks. MCP registered and
verified connected. Not Caduceus-related, but it is global tooling state.
