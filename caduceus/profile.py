"""Gap vector: the person as data.

seats/PROFILE.json is the source of truth that USER.md is rendered from and
the cast is computed from. Trait and facet names follow PrinciplesYou's
published taxonomy (data/principlesyou.json); any instrument can map into it.
Unknown names warn and never fail: the archetype library only needs the
names it triggers on. A name given twice with different numbers is an error,
never a silent preference.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

SCHEMA = "caduceus.profile.v1"
DATA = Path(__file__).resolve().parent / "data" / "principlesyou.json"


class ProfileError(ValueError):
    pass


def norm(name: str) -> str:
    """Case-, hyphen- and whitespace-insensitive key: 'Detail-Oriented' == 'detail oriented'."""
    return " ".join(str(name).replace("-", " ").replace("_", " ").lower().split())


def taxonomy() -> Dict[str, List[str]]:
    """{norm(trait): [norm(facet), ...]}; independent dimensions map to []."""
    d = json.loads(DATA.read_text())
    known = {norm(t): [norm(f) for f in fs] for t, fs in d["traits"].items()}
    for i in d["independent"]:
        known[norm(i)] = []
    return known


@dataclass
class Profile:
    raw: dict
    pcts: Dict[str, int]
    confs: Dict[str, float]
    sha256: str
    warnings: List[str] = field(default_factory=list)

    def pct(self, name: str) -> Optional[int]:
        return self.pcts.get(norm(name))

    def confidence(self, name: str) -> float:
        return self.confs.get(norm(name), 1.0)

    @property
    def least_like(self) -> List[str]:
        return list(self.raw.get("archetypes", {}).get("least_like", []))

    @property
    def best_archetype(self) -> str:
        return str(self.raw.get("archetypes", {}).get("best", ""))

    @property
    def secondary(self) -> List[str]:
        return list(self.raw.get("archetypes", {}).get("secondary", []))

    @property
    def person(self) -> dict:
        return dict(self.raw.get("person", {}))

    @property
    def notes(self) -> Dict[str, str]:
        return dict(self.raw.get("notes", {}))

    @property
    def instrument(self) -> dict:
        return dict(self.raw.get("instrument", {}))


def _pct(v, where: str) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 100:
        raise ProfileError(f"{where}: pct must be 0-100, got {v!r}")
    return int(v)


def load(path: Path) -> Profile:
    text = Path(path).read_text()
    try:
        raw = json.loads(text)
    except ValueError as e:
        raise ProfileError(f"{path}: not valid JSON ({e})")
    if raw.get("schema") != SCHEMA:
        raise ProfileError(f"{path}: schema must be {SCHEMA!r}, got {raw.get('schema')!r}")
    known = taxonomy()
    all_known = set(known) | {f for fs in known.values() for f in fs}
    pcts: Dict[str, int] = {}
    confs: Dict[str, float] = {}
    warnings: List[str] = []

    def put(name: str, pct: int, conf: float, where: str) -> None:
        k = norm(name)
        if k in pcts and pcts[k] != pct:
            raise ProfileError(f"{where}: '{name}' given twice with different values "
                               f"({pcts[k]} and {pct})")
        pcts[k] = pct
        confs[k] = min(confs.get(k, conf), conf)
        if k not in all_known:
            warnings.append(f"unknown trait/facet '{name}' (not in the PrinciplesYou taxonomy)")

    traits = raw.get("traits", {})
    if not isinstance(traits, dict) or not traits:
        raise ProfileError(f"{path}: 'traits' must be a non-empty object")
    for name, entry in traits.items():
        if not isinstance(entry, dict):
            raise ProfileError(f"traits.{name}: must be an object with 'pct'")
        try:
            conf = float(entry.get("confidence", 1.0))
        except (TypeError, ValueError):
            raise ProfileError(f"traits.{name}: confidence must be a number 0-1")
        if not 0.0 <= conf <= 1.0:
            raise ProfileError(f"traits.{name}: confidence must be 0-1, got {conf}")
        if "pct" in entry:
            put(name, _pct(entry["pct"], f"traits.{name}"), conf, f"traits.{name}")
        facets = entry.get("facets", {})
        if not isinstance(facets, dict):
            raise ProfileError(f"traits.{name}.facets: must be an object")
        for fname, fv in facets.items():
            where = f"traits.{name}.facets.{fname}"
            put(fname, _pct(fv, where), conf, where)
    return Profile(raw=raw, pcts=pcts, confs=confs,
                   sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                   warnings=warnings)
