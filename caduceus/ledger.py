"""Believability ledger: seat x domain track records.

Dalio's believability weighting without the ceremony:
- every settled outcome is a row (win / mixed / loss)
- believability(seat, domain) = Laplace-smoothed, recency-decayed win rate
- unseen (seat, domain) falls back to the seat's global score, then to 0.5

No Kendall's W, no RL. A SQLite table and honest arithmetic.
"""
from __future__ import annotations

import math
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import config

RESULT_SCORE = {"win": 1.0, "mixed": 0.5, "loss": 0.0}
HALF_LIFE_DAYS = 45.0          # a win 45 days ago counts half
PRIOR_WINS = 1.0               # Laplace prior: one phantom win...
PRIOR_N = 2.0                  # ...out of two phantom outcomes -> prior 0.5

SCHEMA = """
CREATE TABLE IF NOT EXISTS outcomes (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    seat TEXT NOT NULL,
    domain TEXT NOT NULL,
    result TEXT NOT NULL CHECK(result IN ('win','mixed','loss','pending')),
    task_ref TEXT,
    note TEXT,
    model TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_outcomes_seat ON outcomes(seat, domain);
CREATE TABLE IF NOT EXISTS council_runs (
    run_id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    domain TEXT NOT NULL,
    question TEXT NOT NULL,
    seats TEXT NOT NULL,
    memo_path TEXT,
    settled INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class Believability:
    seat: str
    domain: str
    score: float
    n_effective: float
    basis: str  # 'domain' | 'global' | 'prior'


class Ledger:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or config.ledger_db_path()
        self.conn = sqlite3.connect(str(self.path))
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """v0.1 databases lack the model-attribution column."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(outcomes)")}
        if "model" not in cols:
            self.conn.execute("ALTER TABLE outcomes ADD COLUMN model TEXT DEFAULT ''")

    # ------------------------------------------------------------ writes

    def record(self, seat: str, domain: str, result: str,
               task_ref: str = "", note: str = "", model: str = "") -> str:
        if result not in ("win", "mixed", "loss", "pending"):
            raise ValueError(f"bad result '{result}'")
        oid = uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO outcomes (id, ts, seat, domain, result, task_ref, note, model) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (oid, time.time(), seat.lower(), domain.lower(), result, task_ref,
             note, model),
        )
        self.conn.commit()
        return oid

    def register_run(self, run_id: str, domain: str, question: str,
                     seats: List[str], memo_path: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO council_runs "
            "(run_id, ts, domain, question, seats, memo_path, settled) "
            "VALUES (?,?,?,?,?,?,0)",
            (run_id, time.time(), domain, question[:500], ",".join(seats), memo_path),
        )
        self.conn.commit()

    def settle(self, run_id: str, winners: List[str], losers: List[str],
               mixed: List[str], note: str = "",
               models: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Human (or verifier gate) judges how a council's advice worked out.

        `models` maps seat -> model id that actually sat in the seat for this
        run, so outcomes are attributed to the model that earned them even
        after a recast."""
        row = self.conn.execute(
            "SELECT domain FROM council_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            raise SystemExit(f"unknown run_id '{run_id}' (see: cad ledger runs)")
        domain = row[0]
        models = models or {}
        out = {}
        for seat in winners:
            out[seat] = self.record(seat, domain, "win", run_id, note,
                                    model=models.get(seat, ""))
        for seat in mixed:
            out[seat] = self.record(seat, domain, "mixed", run_id, note,
                                    model=models.get(seat, ""))
        for seat in losers:
            out[seat] = self.record(seat, domain, "loss", run_id, note,
                                    model=models.get(seat, ""))
        self.conn.execute(
            "UPDATE council_runs SET settled=1 WHERE run_id=?", (run_id,)
        )
        self.conn.commit()
        return out

    # ------------------------------------------------------------ reads

    def _weighted(self, rows) -> (float, float):
        now = time.time()
        num, den = 0.0, 0.0
        for ts, result in rows:
            if result == "pending":
                continue
            age_days = max(0.0, (now - ts) / 86400.0)
            w = math.pow(0.5, age_days / HALF_LIFE_DAYS)
            num += w * RESULT_SCORE[result]
            den += w
        return num, den

    def believability(self, seat: str, domain: str) -> Believability:
        seat, domain = seat.lower(), domain.lower()
        rows = self.conn.execute(
            "SELECT ts, result FROM outcomes WHERE seat=? AND domain=?",
            (seat, domain),
        ).fetchall()
        num, den = self._weighted(rows)
        if den > 0.0:
            score = (num + PRIOR_WINS) / (den + PRIOR_N)
            return Believability(seat, domain, score, den, "domain")
        # fallback: seat-global
        rows = self.conn.execute(
            "SELECT ts, result FROM outcomes WHERE seat=?", (seat,)
        ).fetchall()
        num, den = self._weighted(rows)
        if den > 0.0:
            score = (num + PRIOR_WINS) / (den + PRIOR_N)
            return Believability(seat, domain, score, den, "global")
        return Believability(seat, domain, 0.5, 0.0, "prior")

    def table(self) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT seat, domain, COUNT(*) n, "
            "SUM(result='win') w, SUM(result='mixed') m, SUM(result='loss') l "
            "FROM outcomes WHERE result!='pending' "
            "GROUP BY seat, domain ORDER BY seat, n DESC"
        ).fetchall()
        out = []
        for seat, domain, n, w, m, l in rows:
            b = self.believability(seat, domain)
            out.append({
                "seat": seat, "domain": domain, "n": n,
                "win": w or 0, "mixed": m or 0, "loss": l or 0,
                "believability": round(b.score, 3), "basis": b.basis,
            })
        return out

    def runs(self, unsettled_only: bool = True) -> List[Dict]:
        q = ("SELECT run_id, ts, domain, question, seats, settled "
             "FROM council_runs ")
        if unsettled_only:
            q += "WHERE settled=0 "
        q += "ORDER BY ts DESC LIMIT 50"
        return [
            {"run_id": r[0], "ts": r[1], "domain": r[2],
             "question": r[3], "seats": r[4], "settled": bool(r[5])}
            for r in self.conn.execute(q).fetchall()
        ]

    def close(self):
        self.conn.close()
