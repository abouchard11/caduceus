# Inventor's Conception Record

**Inventor:** Alex Bouchard (DBA MidnightDev)
**Date of record:** 2026-08-20
**Date of conception:** 2026-08-20 (chain begins 2026-08-19; see Derivation Chain)
**Context:** Independent work on the author's own projects — `caduceus` (five-seat AI decision council) and the `agentic-graph-orchestration` skill. Not performed under, during, or in connection with services for any client.

> Contemporaneous record. Written the day of conception to fix date and context.
> Not legal advice; prepared by the inventor for his own file and for counsel.

---

## 1. Subject Matter Conceived

A mediated message architecture for a **fixed, declared roster** of heterogeneous LLM agents wired
into a **loop graph** (cycles permitted), with the following elements:

1. **Declared topology.** The set of agents and the set of permitted edges are fixed at design time.
   No agent spawns another at runtime. The executed graph is the declared graph.

2. **Mandatory mediation.** No direct agent-to-agent edge exists. Every message crosses a
   deterministic mediator ("breaker") outside any model's context.

3. **Content-blind mediator.** The breaker does not read, parse, or classify message content.
   It strips metadata, routes by content-derived identifier (hash), enforces the declared edge
   set, and logs traversals. Because it never interprets content, it presents no injection
   surface reachable through content. Blindness is the security property, not a limitation.

4. **Co-located sighted sentry with one-bit output.** Beside the breaker at the gate sits an
   inspector that *does* read content. It additionally holds the provenance chain — what the
   prior node received — enabling drift/mutation detection by comparison, which no receiving
   agent can perform from the current message alone. Its only output is a binary pass/block
   verdict. Its capability surface is one bit, so it can be granted visibility that would be
   unsafe to grant an agent, and its compromise fails open on one artifact without breaching
   topology guarantees. The classifier is therefore **outside** the trusted computing base.

5. **Graph-wide quarantine by opaque identifier.** A sentry verdict blacklists the identifier
   across the entire graph. The breaker enforces the blacklist without ever learning why the
   artifact was flagged. One detection immunizes the whole graph. Detection is distributed;
   enforcement is centralized; **comprehension is never centralized**.

6. **Static pre-flight verification.** Because the roster and edges are declared, reachability
   analysis over the whole graph is decidable before execution (polynomial time on a static
   graph), permitting isolation properties to be proven rather than monitored.

Corollary properties observed at conception: the enforcement kernel stays small enough to be
verifiable precisely *because* semantic work was moved out of it (TCB minimization); a long-running
loop grows cheaper as cleared identifiers skip sentry inspection; provenance can be held as a hash
chain of constant size per hop with full content retained only for a comparison window.

## 2. Derivation Chain (as it actually occurred)

1. 2026-08-19/20 — defect found in the author's own `agentic-graph-orchestration` skill: verifier
   gates that could never fire (unreachable) versus gates firing on the wrong property (Goodhart).
   Led to a reachability requirement on graph nodes.
2. Read a third-party paper on self-propagating "mind virus" behavior across multi-agent systems.
   Considered breakers as interruption points.
3. Reasoned by analogy to an electrical transformer — sought **galvanic isolation** between agent
   contexts — and to a torrent: chunked, hashed, manifest-held content reassembled by hardcode.
4. Recognized that the mediator must be **blind** for the isolation to be meaningful, and that
   semantic inspection therefore belongs to a separate co-located component with a one-bit output.
   This is the element believed novel.
5. Recognized graph-wide quarantine by hash follows from blind-but-identifying mediation.

## 3. Prior Art — Discovered AFTER Conception, Recorded for Candor

**Sequence matters and is recorded precisely.** The subject matter in §1 was conceived independently,
through the derivation chain in §2, **before** any of the art below was known to the inventor. None
of it informed the conception.

- **Conception:** 2026-08-20, chain beginning 2026-08-19 (§2). Elements 1–5 were reached from the
  electrical-transformer and torrent analogies and from a defect in the inventor's own skill code.
- **Prior art first became known:** 2026-08-20, *later the same day*, via a commissioned multi-agent
  research sweep run expressly to find it. The blind-mediator / one-bit-sentry split (element 4) was
  conceived **after that sweep began** and was therefore never evaluated against it.
- **No claim of precedence is made.** Under the AIA the United States is first-inventor-to-file, and
  independent conception does not overcome an earlier printed publication. This record establishes
  **independent derivation and ownership context only**, not priority.

The sweep surfaced:

- **Information flow control:** Denning lattice model (1976); Myers & Liskov DIFC/DLM (1997);
  Jif; Flume; HiStar; Secure Program Partitioning (SOSP 2001).
- **Separation kernels:** ARINC 653 / MILS (typed ports, static channel configuration, no direct
  partition-to-partition path); seL4 machine-checked information-flow proof (IEEE S&P 2013).
- **Access-control models:** Brewer–Nash "Chinese Wall" (1989); Anderson reference monitor (1972).
- **LLM-agent runtime IFC:** CaMeL (arXiv 2503.18813, Google DeepMind, Mar 2025); Fides
  (2505.23643, Microsoft, May 2025); AirGapAgent (CCS 2024); MNC (2608.01719, 3 Aug 2026).
- **Static analysis of agent graphs:** Agentproof (arXiv 2603.20356, Mar 2026 — control-flow
  checks, explicitly excludes information-flow and inter-agent isolation); AgentFlow
  (2607.01640, Jul 2026 — taint analysis, over-approximating).
- **Constrained inter-agent messaging:** PatchBoard (2605.29313, May 2026).
- **Patent:** US 12,536,328 B1 (granted 2026-01-27), "Privacy-gated decentralized multi-agent
  artificial intelligence architecture."
- **Ensemble diversity:** Krogh & Vedelsby (1994); Ueda & Nakano (1996); Kish design effect
  (1965); Ho random subspace (1998); Breiman random forests (2001); Kohli, "Nine Judges, Two
  Effective Votes" (arXiv 2605.29800, May 2026).

### Distinctions noted at conception

Against **US 12,536,328 B1** (independent claims 1, 11, 19 read 2026-08-20): its hub *detects and
replaces each instance of PII with a hashed identifier* — it reads content to classify, placing the
label assigner inside the trust root. Its bus broadcasts *"without centralized routing logic"* and
its pods *self-select relevant envelopes by applying a local relevance classifier* — emergent
topology. Its compliance side-car evaluates the outbound *draft response*, not inter-agent traffic.
The architecture recorded here is the inverse on each: blind mediator, centralized routing over a
declared topology, inspection on inter-agent edges. *Dependent claims and any pending continuations
have not been analyzed; this is not a freedom-to-operate opinion.*

Against **CaMeL / Fides / MNC**: runtime enforcement with the labeling component in the trusted
path; no pre-deployment artifact. Against **Agentproof**: static analysis of declared topology, but
control-flow only, expressly not information-flow or isolation.

**Believed novel:** the blind-mediator / sighted-one-bit-sentry split placing the semantic
classifier outside the TCB, combined with graph-wide quarantine by opaque identifier, over a
declared fixed-roster loop topology.

## 4. Not Yet Reduced to Practice

No implementation exists as of this date. The load-bearing quantitative claim — that partitioning
evidence across agents raises effective independence (n_eff) — is **unmeasured**, and no source was
found in either direction. Per the inventor's own standing practice (see the MB/LMB examiner brief,
which gates filing on bench validation), measurement precedes any filing decision.

## 5. Ownership

Conceived independently, on the inventor's own equipment and projects, outside the performance of
services for any client. No client confidential information contributed to the conception. To the
extent any agreement reserves "broadly applicable technical patterns" and "methodologies and general
knowledge" to the inventor, this subject matter falls there.

---

*Record created 2026-08-20 by Alex Bouchard. Session transcript and research outputs retained.*
