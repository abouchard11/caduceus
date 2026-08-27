"""Follow-through tracker: the loop between advice and reality.

The failure this exists for (recorded 2026-08-26, ledger run
20260819-123157): the council emitted a memo, nobody acted on it, and seven
days later the operator had no recollection of the recommendation. The advice
did not fail in the market - it never reached the market.

Two loops, both previously open:
  1. EXECUTION  - was the lead recommendation ever acted on?
  2. SETTLEMENT - once acted on (or abandoned), was it right?

A council run is only finished when both are closed. This module tracks loop
1; ledger.settle() closes loop 2. Nothing here nags about a decision the
operator has already answered.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import config

STATES = ("pending", "done", "dropped")

# Diagnostic / invalid runs. Standing operator rule: these are NEVER settled as
# real outcomes. They are excluded from every nudge by default - a reminder that
# can never be closed teaches the operator to ignore reminders, which is the
# exact failure this module exists to fix. Matched by run_id prefix.
DIAGNOSTIC_RUNS = (
    "20260819-122812",
    "20260819-115005",
    "20260819-084035",
)


def _is_diagnostic(run_id: str) -> bool:
    return any(run_id.startswith(p) for p in DIAGNOSTIC_RUNS)

SCHEMA = """
CREATE TABLE IF NOT EXISTS commitments (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    action TEXT NOT NULL,
    seat TEXT NOT NULL DEFAULT '',
    created_ts REAL NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','done','dropped')),
    closed_ts REAL,
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_commit_state ON commitments(state);
"""


@dataclass
class Commitment:
    id: str
    run_id: str
    action: str
    seat: str
    created_ts: float
    state: str
    closed_ts: Optional[float]
    note: str

    @property
    def age_days(self) -> float:
        end = self.closed_ts if self.closed_ts else time.time()
        return max(0.0, (end - self.created_ts) / 86400.0)


class Followups:
    def __init__(self, path=None):
        self.path = path or config.ledger_db_path()
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def open(self, run_id: str, action: str, seat: str = "") -> str:
        cid = uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO commitments (id, run_id, action, seat, created_ts, state)"
            " VALUES (?,?,?,?,?, 'pending')",
            (cid, run_id, action.strip()[:500], seat, time.time()),
        )
        self.conn.commit()
        return cid

    def close(self, cid: str, state: str, note: str = "") -> bool:
        if state not in ("done", "dropped"):
            raise ValueError("state must be done or dropped")
        cur = self.conn.execute(
            "UPDATE commitments SET state=?, closed_ts=?, note=? WHERE id=? AND state='pending'",
            (state, time.time(), note[:500], cid),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def _rows(self, where: str, args=()) -> List[Commitment]:
        rows = self.conn.execute(
            "SELECT id, run_id, action, seat, created_ts, state, closed_ts, note"
            f" FROM commitments {where}", args
        ).fetchall()
        return [Commitment(*r) for r in rows]

    def pending(self) -> List[Commitment]:
        return self._rows("WHERE state='pending' ORDER BY created_ts ASC")

    def all(self) -> List[Commitment]:
        return self._rows("ORDER BY created_ts DESC")

    def close_conn(self):
        self.conn.close()


# ------------------------------------------------------------- the nudge

def status(exclude_runs: Optional[List[str]] = None) -> Dict:
    """Both open loops, in one shape. Diagnostic runs are always excluded."""
    from .ledger import Ledger
    extra = set(exclude_runs or [])

    def skip(rid: str) -> bool:
        return _is_diagnostic(rid) or rid in extra

    f = Followups()
    acts = [c for c in f.pending() if not skip(c.run_id)]
    f.close_conn()

    led = Ledger()
    runs = [r for r in led.runs(unsettled_only=True) if not skip(r["run_id"])]
    led.close()
    return {"unexecuted": acts, "unsettled": runs}


def render(st: Dict) -> str:
    """Phone-readable. Says nothing when there is nothing to say."""
    acts, runs = st["unexecuted"], st["unsettled"]
    if not acts and not runs:
        return ""
    out = ["CADUCEUS — open loops"]
    if acts:
        out.append(f"\nNot done yet ({len(acts)}):")
        for c in acts[:5]:
            out.append(f"  [{c.id}] {int(c.age_days)}d · {c.action[:90]}")
        out.append("  close: cad followup done <id>   (or: drop <id>)")
    if runs:
        out.append(f"\nUngraded decisions ({len(runs)}):")
        for r in runs[:5]:
            out.append(f"  {r['run_id']}  {r['question'][:70]}")
        out.append("  grade: cad ledger settle <run_id> --winner <seat> --loser <seat>")
    return "\n".join(out)
