"""Loadouts: which skills sit next to each seat's twitch finger.

Proposal half (Jev's second slot, docs/compile-design.md §4.2): every skill
in the manifest is one Jev state; the questions are one Score per
(seat × domain) pair in the cast. Scores are cached by (skill sha, cast sha)
so a rerun never re-spends. The proposal is machine-written; the table that
installs is the one Alex edits (Decision 21).

Install half (§5): a static copy of each seat's capped union into
$HERMES_HOME/profiles/<seat>/skills/loadout/<skill>/, recorded so uninstall
removes exactly what compile put there and nothing hand-installed.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from . import archetypes, config, jev
from .compile import Cast
from .manifest import Denylist, Entry, Manifest

PROPOSAL_SCHEMA = "caduceus.loadout.v1"
LEVELS = ["irrelevant", "rarely useful", "sometimes useful", "often useful", "essential"]
DOMAINS = list(config.DOMAIN_KEYWORDS) + ["general"]
CACHE_VERSION = "v1"


# ---------------------------------------------------------------- questions

def build_questions(cast: Cast) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for s in cast.seats:
        job = archetypes.by_key(s.key).job
        for d in DOMAINS:
            out[f"{s.seat}__{d}"] = {
                "type": "score",
                "instructions": (f"How useful is this skill to the {s.display} seat ({job}) "
                                 f"when the council question is in the '{d}' domain "
                                 f"({config.DOMAIN_DESCRIPTIONS[d]})?"),
                "criteria": list(LEVELS),
            }
    return out


# ---------------------------------------------------------------- cache

class Cache:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: Dict[str, dict] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except ValueError:
                self.data = {}
        self.dirty = False

    def get(self, key: str) -> Optional[dict]:
        return self.data.get(key)

    def put(self, key: str, answers: dict) -> None:
        self.data[key] = answers
        self.dirty = True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data))
        self.dirty = False


def default_cache_path() -> Path:
    return config.caduceus_home() / "loadout-cache.json"


def cache_key(entry: Entry, cast: Cast) -> str:
    return hashlib.sha256(f"{entry.name}|{entry.sha256}|{cast.sha256}|{CACHE_VERSION}".encode()).hexdigest()


# ---------------------------------------------------------------- scoring

@dataclass
class Scores:
    by_skill: Dict[str, Dict[Tuple[str, str], Tuple[float, float]]] = field(default_factory=dict)
    paths: Dict[str, str] = field(default_factory=dict)
    calls: int = 0
    planned: int = 0
    cached: int = 0
    usage: Dict[str, int] = field(default_factory=dict)
    est_usd: float = 0.0
    stopped_reason: str = ""
    errors: List[str] = field(default_factory=list)


def _parse(answers: dict) -> Dict[Tuple[str, str], Tuple[float, float]]:
    out: Dict[Tuple[str, str], Tuple[float, float]] = {}
    for qid, a in answers.items():
        if "__" not in qid or not isinstance(a, dict):
            continue
        seat, domain = qid.split("__", 1)
        score = a.get("score")
        if score is None:
            probs = a.get("probabilities") or {}
            score = sum(int(k) * float(v) for k, v in probs.items()) if probs else None
        if score is None:
            raise ValueError(f"{qid}: no score")
        out[(seat, domain)] = (float(score), float(a.get("confidence", 0.0)))
    if not out:
        raise ValueError("no seat__domain answers")
    return out


def score_skills(entries: Iterable[Entry], cast: Cast, client, cache: Cache,
                 max_usd: float = 1.0, dry_run: bool = False) -> Scores:
    questions = build_questions(cast)
    sc = Scores()
    for e in entries:
        sc.paths[e.name] = e.path
        key = cache_key(e, cast)
        answers = cache.get(key)
        if answers is None:
            if dry_run:
                sc.planned += 1
                continue
            sc.est_usd = jev.estimate_usd(getattr(client, "usage", {}) or {})
            if sc.est_usd > max_usd:
                sc.stopped_reason = "max_usd"
                break
            state = {"name": e.name, "description": e.description, "category": e.category}
            try:
                answers = client.ask(state, questions)
            except jev.JevError as ex:
                sc.errors.append(f"{e.name}: JevError: {ex}")
                continue
            sc.calls += 1
            cache.put(key, answers)
        else:
            sc.cached += 1
        try:
            sc.by_skill[e.name] = _parse(answers)
        except (ValueError, TypeError) as ex:
            sc.errors.append(f"{e.name}: bad answer: {ex}")
            cache.data.pop(key, None)
    sc.usage = dict(getattr(client, "usage", {}) or {})
    sc.est_usd = jev.estimate_usd(sc.usage)
    return sc


# ---------------------------------------------------------------- proposal

def propose(scores: Scores, cast: Cast, deny: Denylist, per: int = 5) -> dict:
    denied = sorted(n for n in scores.by_skill if deny.denies(n))
    seats: Dict[str, Dict[str, list]] = {}
    for s in cast.seats:
        seats[s.seat] = {}
        for d in DOMAINS:
            cands = []
            for name, m in scores.by_skill.items():
                if name in denied or (s.seat, d) not in m:
                    continue
                score, conf = m[(s.seat, d)]
                cands.append((name, score, conf))
            cands.sort(key=lambda c: (-c[1], -c[2], c[0]))
            seats[s.seat][d] = [{"name": n, "score": round(sc_, 3), "confidence": round(cf, 3),
                                 "path": scores.paths.get(n, "")}
                                for n, sc_, cf in cands[:per]]
    return {"schema": PROPOSAL_SCHEMA, "cast_sha256": cast.sha256, "per": per,
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "seats": seats,
            "denied": denied, "stopped_reason": scores.stopped_reason,
            "errors": list(scores.errors), "calls": scores.calls, "cached": scores.cached,
            "est_usd": round(scores.est_usd, 4)}
