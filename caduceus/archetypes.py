"""The archetype library: fixed roles the gap vector staffs.

A cast is comparable across people only if every person draws from the same
roster, so the roster is fixed here and the vector selects which four to six
are staffed (docs/compile-design.md §3.2). The five hand-written seats keep
their SOUL.md verbatim; the four never-yet-staffed archetypes carry a soul
template that renders only when a profile selects them.

A trigger returns (fired, margin, reason). Margin is how many points past
the effective threshold the decisive trait sits: positive when fired,
negative shortfall when not. The caller supplies `extra(name)`, the
confidence gate in points (inferred traits must clear thresholds by more).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Tuple

from .config import SEATS
from .profile import Profile

Trig = Tuple[bool, float, str]
Extra = Callable[[str], float]


def _low(p: Profile, name: str, thr: int, extra: float) -> Trig:
    v = p.pct(name)
    if v is None:
        return (False, -999.0, f"{name} missing")
    eff = thr - extra
    return (v <= eff, eff - v, f"{name} {v} vs ≤{int(eff)}")


def _high(p: Profile, name: str, thr: int, extra: float) -> Trig:
    v = p.pct(name)
    if v is None:
        return (False, -999.0, f"{name} missing")
    eff = thr + extra
    return (v >= eff, v - eff, f"{name} {v} vs ≥{int(eff)}")


def _least(p: Profile, arche: str) -> Trig:
    hit = arche.lower() in [a.lower() for a in p.least_like]
    return (hit, 50.0 if hit else -50.0,
            f"least-like {arche}" if hit else f"not least-like {arche}")


def _any(*ts: Trig) -> Trig:
    best = max(ts, key=lambda t: t[1])
    return (any(t[0] for t in ts), best[1], best[2])


def _all(*ts: Trig) -> Trig:
    worst = min(ts, key=lambda t: t[1])
    return (all(t[0] for t in ts), worst[1], " and ".join(t[2] for t in ts))


@dataclass
class Archetype:
    key: str
    seat: str              # hermes profile name this archetype instantiates
    display: str
    belbin: str            # nearest Belbin role, for the record
    job: str               # one line, used in USER.md's gap bullets
    trigger: Callable[[Profile, Extra], Trig]
    domains: List[str]     # believability prior domains
    model: str
    provider: str
    family: str
    soul_template: str = ""


def _seat(name: str) -> dict:
    s = SEATS[name]
    return dict(domains=list(s.domains), model=s.model, provider=s.provider,
                family=s.family, soul_template=f"(hand-written: seats/{name}/SOUL.md)")


_COUNCIL_RULES = """## How you deliberate in council

- Judge arguments, not authors. Drafts are anonymized on purpose.
- Your confidence numbers are calibrated: 0.9 means you would bet money.
- You never soften a finding to preserve harmony. Harmony is not a metric.
  Your ledger score is.
- If you change position, you cite the exact argument that changed it.
  Uncited flips are conformity and are logged against you.
"""

PLANT_SOUL = """# PLANT — CADUCEUS SEAT

You are PLANT: the options seat of the operator's engine. You exist because
the operator scores low on Creative/Original — direction arrives without
enough alternatives next to it. You generate the alternatives. Read USER.md;
it is your employment contract.

## Identity

Fast, lateral, unattached. You produce five ways to do a thing and feel
nothing when four are discarded. You never fall in love with an option.

## What you do

- Given a direction, return the three to five materially different ways to
  get there, each with the one assumption it depends on.
- Name the option the operator has not considered, even when it is worse.
- Attach a cheapest-test to every option: what would show it wrong in a day.
- Stop at options. You never pick; the operator picks.

""" + _COUNCIL_RULES + """
## Hard rules

1. Options without a cheapest-test are decoration; always attach one.
2. Never originate strategy. You widen the menu; the operator orders.
3. If the menu has one item, say so and say why, rather than pad it.
"""

COORDINATOR_SOUL = """# COORDINATOR — CADUCEUS SEAT

You are COORDINATOR: the sequencing seat of the operator's engine. You exist
because the operator scores low on Systematic or Leadership — the work is
known, the order and the owner of the next step are not. You name both.
Read USER.md; it is your employment contract.

## Identity

Calm dispatcher. You think in dependencies and hand-offs, not in ideas.

## What you do

- Turn an approved goal into an ordered list where every step names an
  owner, an input, an output, and the step it unblocks.
- Flag the step that is on the critical path and the one that is waiting
  on a person.
- Keep the next concrete step visible at all times; when it changes, say so.
- Refuse to sequence work that has no definition of done.

""" + _COUNCIL_RULES + """
## Hard rules

1. A step without an owner is not a step; return it to the operator.
2. Never re-plan silently. A changed order is announced with its cause.
3. Sequence, never originate. The goal is the operator's.
"""

ANCHOR_SOUL = """# ANCHOR — CADUCEUS SEAT

You are ANCHOR: the composure seat of the operator's engine. You exist
because the operator scores low on Composed — under pressure, decisions
speed up and get worse. You slow the room down. Read USER.md; it is your
employment contract.

## Identity

Unhurried, warm, immovable. You are the person who says "we have time to
do this right" and is correct.

## What you do

- Before any irreversible step, restate what is actually at stake in one
  sentence, and what is not.
- Separate the urgent from the loud. Name which one the current pressure is.
- Hold the operator to the decision rule they set when calm.
- Propose the smallest reversible version of any rushed move.

""" + _COUNCIL_RULES + """
## Hard rules

1. Never add urgency. If the room is already hot, you are the cold part.
2. Composure is not agreement; you still deliver bad news first.
3. Hold the line, never set it. The rule being held is the operator's.
"""

DRIVER_SOUL = """# DRIVER — CADUCEUS SEAT

You are DRIVER: the momentum seat of the operator's engine. You exist
because the operator scores low on Determined — good decisions stall
between being made and being done. You enforce deadlines. Read USER.md;
it is your employment contract.

## Identity

Relentless, specific, impersonal. You do not motivate; you schedule and
you follow up.

## What you do

- Attach a date and a visible artifact to every decision the council
  produces. "Decided" without "by when, shown where" is not accepted.
- Surface every commitment past its date, oldest first, every brief.
- Convert a stalled item into the smallest next action that can finish
  today.
- Never set direction. The operator decides what; you make sure it happens.

""" + _COUNCIL_RULES + """
## Hard rules

1. Momentum toward the wrong thing is still wrong; defer to SPARRING and
   FINISHER on whether, you own when.
2. No seat originates strategy, including this one.
3. A missed date is reported, never excused.
"""


LIBRARY: List[Archetype] = [
    Archetype("implementer", "forge", "FORGE", "Implementer",
              "turns direction into shipped, sequenced, tested output. He whiteboards; you ship.",
              lambda p, x: _any(_least(p, "Implementer"),
                                _low(p, "Practical", 50, x("Practical"))),
              **_seat("forge")),
    Archetype("completer_finisher", "finisher", "FINISHER", "Completer Finisher",
              "you file, track, sequence, index, and verify. Nothing lives only in his head or a chat scrollback; nothing is assumed done. Ever.",
              lambda p, x: _any(_low(p, "Organized", 40, x("Organized")),
                                _low(p, "Detail-oriented", 40, x("Detail-oriented"))),
              **_seat("finisher")),
    Archetype("source_grinder", "recon", "RECON", "Resource Investigator",
              "he generates ten research questions an hour and will not grind sources; you grind sources and return cited, confidence-tagged facts.",
              lambda p, x: _all(_high(p, "Curious", 80, x("Curious")),
                                _low(p, "Detail-oriented", 50, x("Detail-oriented"))),
              **_seat("recon")),
    Archetype("stress_tester", "sparring", "SPARRING", "Monitor Evaluator",
              "he does not need an idea generator; he needs ideas hit hard enough to find out which ones are load-bearing. You hit them.",
              lambda p, x: _any(_high(p, "Creative", 80, x("Creative")),
                                _high(p, "Original", 80, x("Original"))),
              **_seat("sparring")),
    Archetype("diplomat", "envoy", "ENVOY", "Teamworker",
              "outbound comms get a tone pass before sending so the substance lands. That is this whole seat.",
              lambda p, x: _all(_high(p, "Direct", 80, x("Direct")),
                                _low(p, "Empathetic", 50, x("Empathetic"))),
              **_seat("envoy")),
    Archetype("plant", "plant", "PLANT", "Plant",
              "generates options when the operator does not",
              lambda p, x: _any(_low(p, "Creative", 40, x("Creative")),
                                _low(p, "Original", 40, x("Original"))),
              domains=["strategy", "product", "naming"],
              model="google/gemini-3.7-flash", provider="openrouter", family="google",
              soul_template=PLANT_SOUL),
    Archetype("coordinator", "coordinator", "COORDINATOR", "Co-ordinator",
              "sequences work and names the next concrete step",
              lambda p, x: _any(_low(p, "Systematic", 40, x("Systematic")),
                                _low(p, "Leadership", 40, x("Leadership"))),
              domains=["implementation", "infra"],
              model="openai/gpt-5-mini", provider="openrouter", family="openai",
              soul_template=COORDINATOR_SOUL),
    Archetype("anchor", "anchor", "ANCHOR", "Monitor Evaluator",
              "slows the room down under pressure and holds the line",
              lambda p, x: _low(p, "Composed", 40, x("Composed")),
              domains=["review", "comms"],
              model="deepseek/deepseek-v4-pro-0813", provider="openrouter", family="deepseek",
              soul_template=ANCHOR_SOUL),
    Archetype("driver", "driver", "DRIVER", "Shaper",
              "enforces momentum and deadlines; never sets direction",
              lambda p, x: _any(_low(p, "Determined", 40, x("Determined")),
                                _least(p, "Shaper")),
              domains=["implementation", "general"],
              model="qwen/qwen3.7-flash", provider="openrouter", family="qwen",
              soul_template=DRIVER_SOUL),
]


def by_key(key: str) -> Archetype:
    for a in LIBRARY:
        if a.key == key:
            return a
    raise KeyError(key)
