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
    result TEXT NOT NULL CHECK(result IN ('win','mixed','loss','pending','unexecuted')),
    task_ref TEXT,
    note TEXT,
    model TEXT DEFAULT '',
    voided INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_outcomes_seat ON outcomes(seat, domain);
CREATE TABLE IF NOT EXISTS council_runs (
    run_id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    domain TEXT NOT NULL,
    question TEXT NOT NULL,
    seats TEXT NOT NULL,
    memo_path TEXT,
    settled INTEGER NOT NULL DEFAULT 0,
    pair_id TEXT DEFAULT '',
    arm TEXT DEFAULT '',
    lead TEXT DEFAULT ''
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
        """v0.1 databases lack the model-attribution column.

        v0.3.5 (2026-09-01): 4 of the 8 losses recorded 08-26..08-27 carried
        "never executed" notes - the operator did not act on the advice, and
        the ledger scored that as the SEAT being wrong. FINISHER sat at 0.261
        (0/0/2) built entirely from advice nobody tried, on runs where it was
        not even the lead - and those weights pick every future council's
        lead. This migration (a) adds `voided`, so a wrongly-scored row can be
        corrected without deleting history, and (b) rebuilds the CHECK
        constraint to admit an 'unexecuted' result that records non-execution
        WITHOUT moving believability. SQLite can't ALTER a CHECK, so the
        rebuild renames the table, recreates it from SCHEMA, and copies rows
        across inside one transaction. Idempotent: a live table already
        admitting 'unexecuted' is left alone.
        """
        # v0.4.0 (2026-10-10): paired evaluation (cad eval loadout) tags each
        # run with the pair it belongs to, which arm it was, and the lead seat
        # the synthesis picked, so settlement stays per run and the pair
        # report is derived. Placed before the outcomes early-return below so
        # an already-rebuilt database still gains these columns.
        rcols = {r[1] for r in self.conn.execute("PRAGMA table_info(council_runs)")}
        for col in ("pair_id", "arm", "lead"):
            if col not in rcols:
                self.conn.execute(f"ALTER TABLE council_runs ADD COLUMN {col} TEXT DEFAULT ''")

        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(outcomes)")}
        if "model" not in cols:
            self.conn.execute("ALTER TABLE outcomes ADD COLUMN model TEXT DEFAULT ''")
        if "voided" not in cols:
            self.conn.execute(
                "ALTER TABLE outcomes ADD COLUMN voided INTEGER NOT NULL DEFAULT 0")

        ddl_row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='outcomes'"
        ).fetchone()
        ddl = ddl_row[0] if ddl_row else ""
        if "unexecuted" in ddl:
            return  # already rebuilt - nothing to do

        self.conn.executescript(
            "BEGIN;"
            # an aborted earlier attempt can leave the scratch table behind;
            # without this every future open dies on the RENAME below
            "DROP TABLE IF EXISTS outcomes_legacy;"
            "DROP INDEX IF EXISTS idx_outcomes_seat;"
            "ALTER TABLE outcomes RENAME TO outcomes_legacy;"
            + SCHEMA +
            "INSERT INTO outcomes (id, ts, seat, domain, result, task_ref, note, model, voided) "
            "SELECT id, ts, seat, domain, result, task_ref, COALESCE(note,''), "
            "COALESCE(model,''), COALESCE(voided,0) FROM outcomes_legacy;"
            "DROP TABLE outcomes_legacy;"
            "COMMIT;"
        )

    # ------------------------------------------------------------ writes

    def record(self, seat: str, domain: str, result: str,
               task_ref: str = "", note: str = "", model: str = "",
               commit: bool = True) -> str:
        # 'unexecuted' records that the operator never acted on the advice -
        # distinct from 'loss', which means the advice was tried and wrong.
        # See _migrate() for why that distinction earned its own result.
        if result not in ("win", "mixed", "loss", "pending", "unexecuted"):
            raise ValueError(f"bad result '{result}'")
        oid = uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO outcomes (id, ts, seat, domain, result, task_ref, note, model) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (oid, time.time(), seat.lower(), domain.lower(), result, task_ref,
             note, model),
        )
        if commit:
            self.conn.commit()
        return oid

    def register_run(self, run_id: str, domain: str, question: str,
                     seats: List[str], memo_path: str = "",
                     pair_id: str = "", arm: str = "", lead: str = "") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO council_runs "
            "(run_id, ts, domain, question, seats, memo_path, settled, pair_id, arm, lead) "
            "VALUES (?,?,?,?,?,?,0,?,?,?)",
            (run_id, time.time(), domain, question[:500], ",".join(seats), memo_path,
             pair_id or "", arm or "", (lead or "").lower()),
        )
        self.conn.commit()

    def settle(self, run_id: str, winners: List[str], losers: List[str],
               mixed: List[str], unexecuted: Optional[List[str]] = None,
               note: str = "",
               models: Optional[Dict[str, str]] = None,
               commit: bool = True) -> Dict[str, str]:
        """Human (or verifier gate) judges how a council's advice worked out.

        `models` maps seat -> model id that actually sat in the seat for this
        run, so outcomes are attributed to the model that earned them even
        after a recast. `unexecuted` marks seats whose advice was never
        acted on - recorded for the audit trail but never scored (see
        _weighted())."""
        row = self.conn.execute(
            "SELECT domain FROM council_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            raise SystemExit(f"unknown run_id '{run_id}' (see: cad ledger runs)")
        domain = row[0]
        models = models or {}
        unexecuted = unexecuted or []
        out = {}
        for seat in winners:
            out[seat] = self.record(seat, domain, "win", run_id, note,
                                    model=models.get(seat, ""), commit=False)
        for seat in mixed:
            out[seat] = self.record(seat, domain, "mixed", run_id, note,
                                    model=models.get(seat, ""), commit=False)
        for seat in losers:
            out[seat] = self.record(seat, domain, "loss", run_id, note,
                                    model=models.get(seat, ""), commit=False)
        for seat in unexecuted:
            out[seat] = self.record(seat, domain, "unexecuted", run_id, note,
                                    model=models.get(seat, ""), commit=False)
        self.conn.execute(
            "UPDATE council_runs SET settled=1 WHERE run_id=?", (run_id,)
        )
        if commit:
            self.conn.commit()
        return out

    def resettle(self, run_id: str, winners: List[str], losers: List[str],
                 mixed: List[str], unexecuted: Optional[List[str]] = None,
                 note: str = "", models: Optional[Dict[str, str]] = None
                 ) -> Dict[str, str]:
        """Correct a run that was already settled wrong - void the prior
        outcomes (never delete: the ledger is an audit instrument) and
        settle it again, in ONE transaction: a crash between the void and
        the re-record must roll back to the pre-resettle state, never leave
        a run with its evidence voided and nothing recorded.

        Contract: voids EVERY non-voided row carrying this run_id as
        task_ref - wins included, and any row hand-written with
        `cad ledger record --ref <run_id>`. On a run never settled it behaves
        exactly like settle(). Raises SystemExit for an unknown run_id."""
        row = self.conn.execute(
            "SELECT domain FROM council_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            raise SystemExit(f"unknown run_id '{run_id}' (see: cad ledger runs)")
        self.conn.execute(
            "UPDATE outcomes SET voided=1 WHERE task_ref=? AND voided=0", (run_id,)
        )
        out = self.settle(run_id, winners, losers, mixed, unexecuted=unexecuted,
                          note=note, models=models, commit=False)
        self.conn.commit()
        return out

    # ------------------------------------------------------------ reads

    def _weighted(self, rows) -> (float, float):
        now = time.time()
        num, den = 0.0, 0.0
        for ts, result in rows:
            if result in ("pending", "unexecuted"):
                continue
            age_days = max(0.0, (now - ts) / 86400.0)
            w = math.pow(0.5, age_days / HALF_LIFE_DAYS)
            num += w * RESULT_SCORE[result]
            den += w
        return num, den

    def believability(self, seat: str, domain: str) -> Believability:
        seat, domain = seat.lower(), domain.lower()
        rows = self.conn.execute(
            "SELECT ts, result FROM outcomes WHERE seat=? AND domain=? AND voided=0",
            (seat, domain),
        ).fetchall()
        num, den = self._weighted(rows)
        if den > 0.0:
            score = (num + PRIOR_WINS) / (den + PRIOR_N)
            return Believability(seat, domain, score, den, "domain")
        # fallback: seat-global
        rows = self.conn.execute(
            "SELECT ts, result FROM outcomes WHERE seat=? AND voided=0", (seat,)
        ).fetchall()
        num, den = self._weighted(rows)
        if den > 0.0:
            score = (num + PRIOR_WINS) / (den + PRIOR_N)
            return Believability(seat, domain, score, den, "global")
        return Believability(seat, domain, 0.5, 0.0, "prior")

    def table(self) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT seat, domain, "
            "SUM(result='win') w, SUM(result='mixed') m, SUM(result='loss') l, "
            "SUM(result='unexecuted') u "
            "FROM outcomes WHERE result!='pending' AND voided=0 "
            "GROUP BY seat, domain ORDER BY seat, (w + m + l) DESC"
        ).fetchall()
        out = []
        for seat, domain, w, m, l, u in rows:
            b = self.believability(seat, domain)
            out.append({
                "seat": seat, "domain": domain, "n": (w or 0) + (m or 0) + (l or 0),
                "win": w or 0, "mixed": m or 0, "loss": l or 0, "unexecuted": u or 0,
                "believability": round(b.score, 3), "basis": b.basis,
            })
        return out

    _RUN_COLS = "run_id, ts, domain, question, seats, settled, pair_id, arm, lead"

    @staticmethod
    def _run_row(r) -> Dict:
        return {"run_id": r[0], "ts": r[1], "domain": r[2], "question": r[3],
                "seats": r[4], "settled": bool(r[5]), "pair_id": r[6] or "",
                "arm": r[7] or "", "lead": r[8] or ""}

    def runs(self, unsettled_only: bool = True) -> List[Dict]:
        q = f"SELECT {self._RUN_COLS} FROM council_runs "
        if unsettled_only:
            q += "WHERE settled=0 "
        q += "ORDER BY ts DESC LIMIT 50"
        return [self._run_row(r) for r in self.conn.execute(q).fetchall()]

    def pairs(self) -> Dict[str, Dict[str, Dict]]:
        """pair_id -> {arm: run row} for every run registered by a paired
        evaluation. Arms are whatever was registered ('A', 'B', 'A-dry', ...);
        the report decides which ones count."""
        out: Dict[str, Dict[str, Dict]] = {}
        q = f"SELECT {self._RUN_COLS} FROM council_runs WHERE pair_id != '' ORDER BY ts"
        for r in self.conn.execute(q).fetchall():
            row = self._run_row(r)
            out.setdefault(row["pair_id"], {})[row["arm"]] = row
        return out

    def lead_outcome(self, run_id: str) -> Optional[str]:
        """The latest non-voided result recorded for this run's lead seat, or
        None when the run is unknown, has no lead, or is not settled for it."""
        row = self.conn.execute(
            "SELECT lead FROM council_runs WHERE run_id=?", (run_id,)).fetchone()
        if not row or not row[0]:
            return None
        res = self.conn.execute(
            "SELECT result FROM outcomes WHERE task_ref=? AND seat=? AND voided=0 "
            "ORDER BY ts DESC LIMIT 1", (run_id, row[0].lower())).fetchone()
        return res[0] if res else None

    def close(self):
        self.conn.close()
