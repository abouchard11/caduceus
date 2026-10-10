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
from .manifest import Denylist, Entry, Manifest, safe_name

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
                 max_usd: float = 1.0, dry_run: bool = False, save_every: int = 25) -> Scores:
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
            if save_every and sc.calls % save_every == 0:
                cache.save()        # an interrupt never discards paid answers
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


# ---------------------------------------------------------------- install

RECORD = ".caduceus-loadout.json"
INSTALL_DIR = "loadout"
# Never copied into a seat: a skill directory is third-party content and may
# carry its author's local state (security review 2026-10-10).
COPY_IGNORE = (".git", ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "node_modules",
               "__pycache__", ".DS_Store")


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def state_path() -> Path:
    return config.caduceus_home() / "compile-state.json"


def _read_state() -> dict:
    p = state_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except ValueError:
            return {}
    return {}


def mark_first_install(ts: Optional[float] = None, force: bool = False) -> float:
    st = _read_state()
    if st.get("first_install_ts") is None or force:
        st["first_install_ts"] = float(ts if ts is not None else time.time())
        state_path().write_text(json.dumps(st, indent=1))
    return float(st["first_install_ts"])


def first_install_ts() -> Optional[float]:
    v = _read_state().get("first_install_ts")
    return float(v) if v is not None else None


def load_table(path: Path) -> dict:
    """A LOADOUT.json or LOADOUT-PROPOSAL.json; items normalised to names."""
    d = json.loads(Path(path).read_text())
    seats: Dict[str, Dict[str, List[str]]] = {}
    for seat, doms in (d.get("seats") or {}).items():
        seats[seat] = {}
        for dom, items in (doms or {}).items():
            names: List[str] = []
            for it in items or []:
                name = it if isinstance(it, str) else (it or {}).get("name", "")
                if name and name not in names:
                    names.append(name)
            seats[seat][dom] = names
    return {"schema": d.get("schema", PROPOSAL_SCHEMA), "cast_sha256": d.get("cast_sha256", ""),
            "per": d.get("per"), "seats": seats}


def table_sha256(table: dict) -> str:
    return hashlib.sha256(json.dumps(table.get("seats", {}), sort_keys=True).encode()).hexdigest()


def plan_install(table: dict, cast: Cast, cap: int = 15) -> Dict[str, List[str]]:
    """Per seat: the union of its per-domain lists, the seat's own prior
    domains first (SEATS order), then the remaining domains in table order,
    de-duplicated, capped."""
    plan: Dict[str, List[str]] = {}
    seats = table.get("seats", {})
    for s in cast.seats:
        doms = seats.get(s.seat, {}) or {}
        priors = list(config.SEATS[s.seat].domains) if s.seat in config.SEATS else []
        order = [d for d in priors if d in doms] + [d for d in doms if d not in priors]
        names: List[str] = []
        for d in order:
            for n in doms.get(d, []):
                if n not in names:
                    names.append(n)
        plan[s.seat] = names[:cap]
    return plan


def _profile_dir(seat: str) -> Path:
    return config.hermes_home() / "profiles" / seat


def _record_path(seat: str) -> Path:
    return _profile_dir(seat) / "skills" / INSTALL_DIR / RECORD


def _read_record(seat: str) -> Optional[dict]:
    p = _record_path(seat)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except ValueError:
        return None


def install(table: dict, cast: Cast, mani: Manifest, cap: int = 15,
            log: Optional[List[str]] = None) -> Dict[str, dict]:
    import shutil
    log = log if log is not None else []
    plan = plan_install(table, cast, cap)
    by_name = mani.by_name()
    out: Dict[str, dict] = {}
    any_installed = False
    for seat, names in plan.items():
        res: dict = {"installed": [], "missing": [], "removed": [], "skipped": None}
        out[seat] = res
        pd = _profile_dir(seat)
        if not pd.is_dir():
            res["skipped"] = "profile missing"
            log.append(f"[=] {seat}: profile missing, loadout skipped")
            continue
        dest_root = pd / "skills" / INSTALL_DIR
        prior = (_read_record(seat) or {}).get("installed", {})
        if names or prior:
            dest_root.mkdir(parents=True, exist_ok=True)
        record: Dict[str, str] = {}
        for name in names:
            e = by_name.get(name) if safe_name(name) else None
            src = Path(e.path).parent if e else None
            if src is None or not src.is_dir() or not (src / "SKILL.md").exists():
                res["missing"].append(name)
                continue
            dst = dest_root / name
            if not _inside(dst, dest_root) or dst.resolve().parent != dest_root.resolve():
                res["missing"].append(name)
                continue
            if dst.is_symlink() or dst.exists():
                shutil.rmtree(dst) if dst.is_dir() and not dst.is_symlink() else dst.unlink()
            shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns(*COPY_IGNORE))
            record[name] = e.sha256
            res["installed"].append(name)
        for stale in prior:
            d = dest_root / stale
            if (stale not in record and safe_name(stale) and _inside(d, dest_root)
                    and d.is_dir() and not d.is_symlink()):
                shutil.rmtree(d)
                res["removed"].append(stale)
        if record:
            _record_path(seat).write_text(json.dumps({
                "installed": record, "ts": time.time(), "table_sha256": table_sha256(table),
                "cast_sha256": cast.sha256}, indent=1))
        elif _record_path(seat).exists():
            _record_path(seat).unlink()   # nothing in reach any more: no record to uninstall
        any_installed = any_installed or bool(record)
        log.append(f"[+] {seat}: {len(record)} skills in reach"
                   + (f", missing {res['missing']}" if res["missing"] else ""))
    if any_installed:
        mark_first_install()
    return out


def _seats_with_records() -> List[str]:
    root = config.hermes_home() / "profiles"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "skills" / INSTALL_DIR / RECORD).exists())


def uninstall(log: Optional[List[str]] = None) -> Dict[str, int]:
    """Remove exactly what install recorded, per seat. Hand-placed directories
    under skills/loadout/ and everything outside it are left alone."""
    import shutil
    log = log if log is not None else []
    out: Dict[str, int] = {}
    for seat in _seats_with_records():
        rec = _read_record(seat) or {}
        root = _profile_dir(seat) / "skills" / INSTALL_DIR
        n = 0
        for name in rec.get("installed", {}):
            d = root / name
            if not safe_name(name) or not _inside(d, root) or d.resolve().parent != root.resolve():
                continue   # a tampered record never reaches outside skills/loadout/
            if d.is_dir() and not d.is_symlink():
                shutil.rmtree(d)
                n += 1
        _record_path(seat).unlink()
        out[seat] = n
        log.append(f"[-] {seat}: {n} loadout skills removed")
    return out


def status() -> dict:
    seats: Dict[str, dict] = {}
    for seat in sorted(set(config.SEATS) | set(_seats_with_records())):
        rec = _read_record(seat) or {}
        seats[seat] = {"installed": len(rec.get("installed", {})),
                       "table_sha256": rec.get("table_sha256", ""),
                       "cast_sha256": rec.get("cast_sha256", ""),
                       "ts": rec.get("ts")}
    return {"seats": seats, "first_install_ts": first_install_ts()}
