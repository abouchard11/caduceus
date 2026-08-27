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

# Columns added after v1. SQLite ALTER TABLE ADD COLUMN is safe and idempotent
# when guarded, so migration is a no-op on an already-migrated db.
MIGRATIONS = (
    ("owner", "TEXT NOT NULL DEFAULT 'operator'"),
    ("kind", "TEXT NOT NULL DEFAULT 'do'"),
    ("options", "TEXT DEFAULT ''"),
)

# ------------------------------------------------------------- ownership
#
# The operator is the Shaper; the seats are staff. An action reaches him only
# when it genuinely needs executive ownership - money, an outward-facing act,
# something irreversible, or a fork in direction only he can pick. Everything
# else is staff work and must not be handed to a person measured Organized 26.
# Deterministic on purpose: the orchestrator is plain Python by design, and a
# model deciding what to escalate is a model deciding its own leash.

_SPEND = ("buy", "purchase", "pay", "invoice", "charge", "subscribe",
          "upgrade plan", "budget", "$")
_OUTWARD = ("send", "email", "dm ", "post to", "publish", "tweet", "reply to",
            "reach out", "outreach", "contact", "pitch", "negotiat", "announce")
_IRREVERSIBLE = ("delete", "drop table", "revoke", "rotate", "force-push",
                 "force push", "migrate production", "deprecate", "shut down",
                 "terminate", "rm -rf")
_DIRECTION = ("decide", "choose", "pick ", "whether", "prioriti",
              "strategy", "roadmap", "kill the", "kill it", "park it",
              "which product", "which one", "go/no-go")
_LEGAL = ("patent", "trademark", " nda ", "counsel", "public disclosure",
          "sign the contract", "legal review", "open-source license",
          "license the", "assign ip", "ip assignment")


def classify(action: str) -> tuple:
    """-> (owner, kind, reason). owner: agent|operator. kind: do|decide."""
    a = " " + action.lower() + " "

    def hit(words):
        return next((w.strip() for w in words if w in a), None)

    w = hit(_SPEND)
    if w:
        return ("operator", "decide", f"spends money ({w})")
    w = hit(_LEGAL)
    if w:
        return ("operator", "decide", f"legal/IP exposure ({w})")
    w = hit(_IRREVERSIBLE)
    if w:
        return ("operator", "decide", f"irreversible ({w})")
    w = hit(_OUTWARD)
    if w:
        return ("operator", "decide", f"outward-facing ({w})")
    w = hit(_DIRECTION)
    if w:
        return ("operator", "decide", f"direction call ({w})")
    return ("agent", "do", "staff work - no executive ownership needed")


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
    owner: str = "operator"
    kind: str = "do"
    options: str = ""

    @property
    def age_days(self) -> float:
        end = self.closed_ts if self.closed_ts else time.time()
        return max(0.0, (end - self.created_ts) / 86400.0)


class Followups:
    def __init__(self, path=None):
        self.path = path or config.ledger_db_path()
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(commitments)")}
        for col, decl in MIGRATIONS:
            if col not in have:
                self.conn.execute(f"ALTER TABLE commitments ADD COLUMN {col} {decl}")
        self.conn.commit()

    def open(self, run_id: str, action: str, seat: str = "",
             owner: str = "", kind: str = "", options: str = "") -> str:
        cid = uuid.uuid4().hex[:12]
        action = action.strip()[:500]
        if not owner or not kind:
            o, k, _ = classify(action)
            owner, kind = owner or o, kind or k
        self.conn.execute(
            "INSERT INTO commitments (id, run_id, action, seat, created_ts, state,"
            " owner, kind, options) VALUES (?,?,?,?,?, 'pending', ?,?,?)",
            (cid, run_id, action, seat, time.time(), owner, kind, options[:500]),
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
            "SELECT id, run_id, action, seat, created_ts, state, closed_ts, note,"
            f" owner, kind, options FROM commitments {where}", args
        ).fetchall()
        return [Commitment(*r) for r in rows]

    def pending(self) -> List[Commitment]:
        return self._rows("WHERE state='pending' ORDER BY created_ts ASC")

    def all(self) -> List[Commitment]:
        return self._rows("ORDER BY created_ts DESC")

    def retriage(self) -> int:
        """Re-classify pending rows with the current classifier. Rows created
        before ownership existed all defaulted to 'operator', which is exactly
        the failure mode this module exists to remove."""
        n = 0
        for c in self.pending():
            owner, kind, _ = classify(c.action)
            if owner != c.owner or kind != c.kind:
                self.conn.execute(
                    "UPDATE commitments SET owner=?, kind=? WHERE id=?",
                    (owner, kind, c.id))
                n += 1
        self.conn.commit()
        return n

    def split(self, cid: str, parts: List[str]) -> List[str]:
        """Replace one compound commitment with atomic ones. A paragraph is not
        a task; 'knowing the specific thing to do' starts here."""
        rows = self._rows("WHERE id=?", (cid,))
        if not rows:
            return []
        src = rows[0]
        new = [self.open(src.run_id, part, seat=src.seat) for part in parts if part.strip()]
        if new:
            self.close(cid, "dropped", note=f"split into {len(new)} atomic actions")
        return new

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


def guard_escalations(limit: int = 5) -> List[Dict]:
    """Guard/budget blocks that were logged and never surfaced to anyone.

    CRITICAL, HIGH and budget blocks all previously terminated in
    ~/.caduceus/guard.log.jsonl. A block nobody sees is a decision nobody
    makes, which is the same failure as a memo nobody reads."""
    import json
    out = []
    path = config.caduceus_home() / "guard.log.jsonl"
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        act = str(d.get("action", ""))
        sev = str(d.get("severity", ""))
        if "block" in act or sev in ("CRITICAL", "HIGH"):
            out.append(d)
    return out[-limit:]


def agenda(st: Dict, escalations: Optional[List[Dict]] = None) -> str:
    """The operator's view: decisions first, staff work collapsed to a count.

    He is the Shaper; the seats are staff. Anything an agent can do must not
    reach him as a task - only as a number he can ignore."""
    acts, runs = st["unexecuted"], st["unsettled"]
    mine = [c for c in acts if c.owner == "operator"]
    staff = [c for c in acts if c.owner != "operator"]
    esc = escalations if escalations is not None else guard_escalations()

    if not mine and not runs and not esc:
        line = f"CADUCEUS - nothing needs you."
        if staff:
            line += f" {len(staff)} item(s) queued for the seats."
        return line

    out = ["CADUCEUS - needs you"]
    if mine:
        out.append(f"\nDECIDE ({len(mine)}):")
        for c in mine:
            out.append(f"  [{c.id}] {int(c.age_days)}d - {c.action[:100]}")
            if c.options:
                out.append(f"      options: {c.options[:120]}")
        out.append("  cad followup done <id> | drop <id> --note why")
    if runs:
        out.append(f"\nGRADE ({len(runs)}) - reality reported, was the call right?")
        for r in runs[:5]:
            out.append(f"  {r['run_id']}  {r['question'][:66]}")
        out.append("  cad ledger settle <run_id> --winner <seat> --loser <seat>")
    if esc:
        out.append(f"\nBLOCKED ({len(esc)}) - guard/budget stopped something:")
        for d in esc:
            what = d.get("rule") or d.get("action") or "?"
            extra = ""
            if d.get("spend") is not None and d.get("ceiling"):
                extra = f" ${d['spend']:.2f} vs ${d['ceiling']:.2f} ceiling"
            out.append(f"  {what}{extra}")
    if staff:
        out.append(f"\n({len(staff)} staff item(s) queued - not yours)")
    return "\n".join(out)


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
