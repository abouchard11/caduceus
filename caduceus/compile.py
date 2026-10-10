"""`cad compile`: profile → cast (and, in later tasks, USER.md and loadouts).

The casting rule (docs/compile-design.md §3.3): evaluate every archetype's
trigger; fired ones are staffed; fill to four by smallest shortfall; cap at
six by largest margin; keep library order so casts read the same way for
everyone. Heterogeneity warnings print, never block.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import List

from . import archetypes, config
from .config import Seat, heterogeneity_warnings
from .profile import Profile

CAST_MIN, CAST_MAX = 4, 6
CONFIDENCE_GATE, GATE_EXTRA = 0.7, 10.0
CAST_SCHEMA = "caduceus.cast.v1"


@dataclass
class CastSeat:
    key: str
    seat: str
    display: str
    fired: bool
    margin: float
    reason: str


@dataclass
class Cast:
    profile_sha256: str
    seats: List[CastSeat]
    warnings: List[str] = field(default_factory=list)
    generated: str = ""

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps([s.seat for s in self.seats]).encode()).hexdigest()

    def to_json(self) -> dict:
        return {"schema": CAST_SCHEMA, "profile_sha256": self.profile_sha256,
                "cast_sha256": self.sha256, "generated": self.generated,
                "seats": [asdict(s) for s in self.seats], "warnings": list(self.warnings)}


def seat_for(key: str) -> Seat:
    """The Seat an archetype instantiates: the real SEATS entry when the
    profile exists, else a fabricated one from the library defaults (never
    applied to an existing seat: compile does not touch model casting)."""
    a = archetypes.by_key(key)
    if a.seat in config.SEATS:
        return config.SEATS[a.seat]
    return Seat(name=a.seat, display=a.display, role=a.job, model=a.model,
                provider=a.provider, family=a.family, temperature_hint="balanced",
                port=8660 + archetypes.LIBRARY.index(a), domains=list(a.domains))


def cast(p: Profile) -> Cast:
    def extra(name: str) -> float:
        return GATE_EXTRA if p.confidence(name) < CONFIDENCE_GATE else 0.0

    rows: List[CastSeat] = []
    for a in archetypes.LIBRARY:
        fired, margin, reason = a.trigger(p, extra)
        rows.append(CastSeat(a.key, a.seat, a.display, fired, round(margin, 1), reason))
    chosen = [r for r in rows if r.fired]
    if len(chosen) < CAST_MIN:
        fill = sorted((r for r in rows if not r.fired), key=lambda r: -r.margin)
        chosen += fill[:CAST_MIN - len(chosen)]
    if len(chosen) > CAST_MAX:
        chosen = sorted(chosen, key=lambda r: -r.margin)[:CAST_MAX]
    order = {a.key: i for i, a in enumerate(archetypes.LIBRARY)}
    chosen.sort(key=lambda r: order[r.key])
    warns = heterogeneity_warnings([seat_for(r.key) for r in chosen])
    return Cast(profile_sha256=p.sha256, seats=chosen, warnings=list(warns),
                generated=time.strftime("%Y-%m-%dT%H:%M:%S"))
