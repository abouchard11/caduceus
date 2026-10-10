"""Paired evaluation: does a loadout earn its keep?

The same question runs twice with the same seats and context: arm A with the
loadout trees uninstalled, arm B with them installed. Both runs register
under one pair id; the operator settles each run exactly as always, and the
report derives the pair outcome from the lead seats' settled results. The
kill rule is pre-registered here (docs/compile-design.md §6, Decision 17/23)
and evaluated at day RULE_DAYS after the first install.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from . import loadout
from .config import Seat
from .council import CouncilResult
from .ledger import Ledger

RULE_DAYS = 14
RULE_WINS = 3


@dataclass
class PairResult:
    pair_id: str
    a: CouncilResult
    b: CouncilResult


# Seams, so the pairing logic is testable without touching profiles.
def _install(table: dict, cast, mani) -> None:
    if cast is None or mani is None or not (table or {}).get("seats"):
        return
    loadout.install(table, cast, mani)


def _uninstall() -> None:
    loadout.uninstall()


def _was_installed() -> bool:
    return any(s["installed"] > 0 for s in loadout.status()["seats"].values())


def run_pair(question: str, seats: List[Seat], context: str, dry_run: bool, table: dict,
             cast, mani, council_factory: Callable[[], object],
             before_run: Optional[Callable[[str, List[Seat]], None]] = None,
             quick: bool = False) -> PairResult:
    pair_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    suffix = "-dry" if dry_run else ""
    was = _was_installed()
    try:
        _uninstall()
        a_id = f"{pair_id}-A"
        if before_run:
            before_run(a_id, seats)
        a = council_factory().run(question, seats, context=context, quick=quick,
                                  run_id=a_id, pair_id=pair_id, arm="A" + suffix)
        _install(table, cast, mani)
        b_id = f"{pair_id}-B"
        if before_run:
            before_run(b_id, seats)
        b = council_factory().run(question, seats, context=context, quick=quick,
                                  run_id=b_id, pair_id=pair_id, arm="B" + suffix)
    finally:
        # Leave the seats the way we found them, whatever happened above.
        if was:
            _install(table, cast, mani)
        else:
            _uninstall()
    return PairResult(pair_id, a, b)


def report(ledger: Ledger, now: Optional[float] = None) -> Dict:
    now = now or time.time()
    pairs = {pid: v for pid, v in ledger.pairs().items() if "A" in v and "B" in v}
    b_wins = a_wins = ties = unsettled = 0
    rows: List[Dict] = []
    for pid, v in sorted(pairs.items()):
        a, b = v["A"], v["B"]
        if not (a["settled"] and b["settled"]):
            unsettled += 1
            rows.append({"pair_id": pid, "outcome": "unsettled", "question": a["question"][:80]})
            continue
        la, lb = ledger.lead_outcome(a["run_id"]), ledger.lead_outcome(b["run_id"])
        if lb == "win" and la != "win":
            b_wins += 1
            outcome = "B"
        elif la == "win" and lb != "win":
            a_wins += 1
            outcome = "A"
        else:
            ties += 1
            outcome = "tie"
        rows.append({"pair_id": pid, "outcome": outcome, "a": la, "b": lb,
                     "question": a["question"][:80]})
    t0 = loadout.first_install_ts()
    days = (now - t0) / 86400.0 if t0 else None
    if days is None or days < RULE_DAYS:
        verdict = "RUNNING"
    elif b_wins >= RULE_WINS and b_wins > a_wins:
        verdict = "PASS"
    else:
        verdict = "PARK"
    return {"pairs": len(pairs), "b_wins": b_wins, "a_wins": a_wins, "ties": ties,
            "unsettled": unsettled, "days": days, "verdict": verdict, "rows": rows,
            "rule": f"PASS if B-wins >= {RULE_WINS} and B-wins > A-wins at day {RULE_DAYS}"}
