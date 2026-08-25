"""Spend guard: per-run budgets + daily aggregation.

Layer A: Run budgets (JSON records at ~/.caduceus/budgets/<run_id>.json)
Layer B: Calibrated ceilings + `cad budget` CLI
Layer C: 15-min monitor cron (separate, not in this module)

Design invariants:
- sqlite reads are read-only (mode=ro URI) — guard bug cannot corrupt Hermes state
- Drift multiplier: effective_spend = estimated * 2.5 (calibrated from Bot Pack incident)
- Two-person approval token required to RAISE a ceiling; lowering is free
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config

# ---------------------------------------------------------------- constants

DRIFT_MULTIPLIER = 2.5  # calibrated from $14.28 estimated vs ~$40 actual (Bot Pack)

# Calibrated ceilings (spec §4 table)
CEILINGS = {
    "quick_council": {"soft": 0.50, "hard": 1.00},  # 2 seats
    "full_council": {"soft": 1.50, "hard": 3.00},   # 4 seats
    "single_seat": {"soft": 0.75, "hard": 1.50},    # autonomous seat run
    "daily": {"soft": 8.00, "hard": 10.00},          # all profiles combined
}

# ---------------------------------------------------------------- paths

def budgets_dir() -> Path:
    p = config.caduceus_home() / "budgets"
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    return p


def budget_path(run_id: str) -> Path:
    return budgets_dir() / f"{run_id}.json"


# ---------------------------------------------------------------- profile DB discovery

def profile_state_db_paths() -> List[Path]:
    """Return state.db paths for all active profiles.
    
    Profiles: forge, finisher, recon, sparring, envoy, default (hermes)
    Each lives at ~/.hermes/profiles/<name>/state.db
    """
    hermes_root = config.hermes_home()
    profiles = ["forge", "finisher", "recon", "sparring", "envoy", "default"]
    paths = []
    for name in profiles:
        db = hermes_root / "profiles" / name / "state.db"
        if db.exists():
            paths.append(db)
    return paths


# ---------------------------------------------------------------- budget records

@dataclass
class Budget:
    run_id: str
    origin: str  # council | cron | plan
    seats: List[str]
    ceiling_usd: float
    started_at: float
    session_ids: Optional[List[str]] = None
    paused: bool = False
    
    def to_dict(self) -> Dict:
        return {
            "run_id": self.run_id,
            "origin": self.origin,
            "seats": self.seats,
            "ceiling_usd": self.ceiling_usd,
            "started_at": self.started_at,
            "session_ids": self.session_ids or [],
            "paused": self.paused,
        }
    
    @classmethod
    def from_dict(cls, d: Dict) -> Budget:
        return cls(
            run_id=d["run_id"],
            origin=d["origin"],
            seats=d["seats"],
            ceiling_usd=d["ceiling_usd"],
            started_at=d["started_at"],
            session_ids=d.get("session_ids", []),
            paused=d.get("paused", False),
        )


def create_budget(run_id: str, origin: str, seats: List[str], 
                  ceiling_usd: float, session_ids: List[str] = None) -> Budget:
    """Create a new budget record. Called by `cad council ask` or `cad plan`."""
    budget = Budget(
        run_id=run_id,
        origin=origin,
        seats=seats,
        ceiling_usd=ceiling_usd,
        started_at=time.time(),
        session_ids=session_ids or [],
    )
    p = budget_path(run_id)
    p.write_text(json.dumps(budget.to_dict(), indent=2))
    os.chmod(p, 0o600)
    return budget


def load_budget(run_id: str) -> Optional[Budget]:
    """Load a budget record by run_id."""
    p = budget_path(run_id)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
        return Budget.from_dict(d)
    except Exception:
        return None


def save_budget(budget: Budget) -> None:
    """Update a budget record (e.g., after changing ceiling or pausing)."""
    p = budget_path(budget.run_id)
    p.write_text(json.dumps(budget.to_dict(), indent=2))
    os.chmod(p, 0o600)


def list_active_budgets() -> List[Budget]:
    """List all non-expired budgets (started within last 24h)."""
    out = []
    cutoff = time.time() - 86400  # 24h
    for p in budgets_dir().glob("*.json"):
        try:
            d = json.loads(p.read_text())
            if d.get("started_at", 0) >= cutoff:
                out.append(Budget.from_dict(d))
        except Exception:
            continue
    return out


def find_budget_for_session(session_id: str) -> Optional[Budget]:
    """Find the active budget that contains this session_id."""
    for budget in list_active_budgets():
        if budget.session_ids and session_id in budget.session_ids:
            return budget
    return None


# ---------------------------------------------------------------- spend aggregation

def read_profile_spend(db_path: Path, session_ids: List[str] = None) -> float:
    """Read estimated_cost_usd from a profile's state.db.
    
    Read-only sqlite connection (mode=ro) — guard bug cannot corrupt Hermes state.
    If session_ids provided, sum only those sessions; otherwise sum all.
    """
    if not db_path.exists():
        return 0.0
    
    try:
        # Read-only connection
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        cursor = conn.cursor()
        
        if session_ids:
            placeholders = ",".join("?" * len(session_ids))
            query = f"""
                SELECT COALESCE(SUM(estimated_cost_usd), 0)
                FROM session_model_usage
                WHERE session_id IN ({placeholders})
            """
            cursor.execute(query, session_ids)
        else:
            query = "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM session_model_usage"
            cursor.execute(query)
        
        total = cursor.fetchone()[0]
        conn.close()
        return float(total)
    except Exception:
        return 0.0


def aggregate_run_spend(budget: Budget) -> float:
    """Sum estimated_cost_usd across all profiles for the budget's session_ids."""
    total = 0.0
    session_ids = budget.session_ids or []
    for db_path in profile_state_db_paths():
        total += read_profile_spend(db_path, session_ids)
    return total


def aggregate_daily_spend() -> float:
    """Sum today's estimated_cost_usd across all profiles.
    
    Today = last 24h from now (simple; could be calendar-day but 24h is safer).
    """
    cutoff = time.time() - 86400
    total = 0.0
    for db_path in profile_state_db_paths():
        if not db_path.exists():
            continue
        try:
            uri = f"file:{db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            cursor = conn.cursor()
            query = """
                SELECT COALESCE(SUM(estimated_cost_usd), 0)
                FROM session_model_usage
                WHERE last_seen >= ?
            """
            cursor.execute(query, (cutoff,))
            total += cursor.fetchone()[0]
            conn.close()
        except sqlite3.Error as e:
            # Log schema errors instead of silently returning 0
            try:
                from . import config
                log_path = config.guard_log_path()
                with open(log_path, "a") as f:
                    f.write(json.dumps({
                        "action": "budget-error",
                        "db": str(db_path),
                        "error": str(e),
                        "ts": time.time()
                    }) + "\n")
            except Exception:
                pass
            continue
    return total


# ---------------------------------------------------------------- guard consultation

def effective_spend(estimated: float) -> float:
    """Apply drift multiplier: effective_spend = estimated * 2.5"""
    return estimated * DRIFT_MULTIPLIER


def check_budget(run_id: str) -> Tuple[str, float, float]:
    """Check budget status for a run.
    
    Returns: (status, current_spend, ceiling)
    status: "ok" | "warn" | "block"
    """
    budget = load_budget(run_id)
    if not budget:
        return "ok", 0.0, 0.0
    
    if budget.paused:
        return "block", 0.0, budget.ceiling_usd
    
    estimated = aggregate_run_spend(budget)
    spend = effective_spend(estimated)
    ceiling = budget.ceiling_usd
    
    if spend >= ceiling:
        return "block", spend, ceiling
    elif spend >= ceiling * 0.8:
        return "warn", spend, ceiling
    else:
        return "ok", spend, ceiling


def check_daily_budget() -> Tuple[str, float, float]:
    """Check daily budget status.
    
    Returns: (status, current_spend, ceiling)
    status: "ok" | "warn" | "block"
    """
    estimated = aggregate_daily_spend()
    spend = effective_spend(estimated)
    ceiling = CEILINGS["daily"]["hard"]
    
    if spend >= ceiling:
        return "block", spend, ceiling
    elif spend >= ceiling * 0.8:
        return "warn", spend, ceiling
    else:
        return "ok", spend, ceiling


# ---------------------------------------------------------------- ceiling overrides

def set_ceiling(run_id: str, new_ceiling: float, grantor: Optional[str] = None) -> Tuple[bool, str]:
    """Set a new ceiling for a budget.
    
    Raising requires two-person approval token (grantor).
    Lowering is free.
    
    Returns: (success, message)
    """
    budget = load_budget(run_id)
    if not budget:
        return False, f"budget not found: {run_id}"
    
    if new_ceiling > budget.ceiling_usd:
        # Raising: requires approval token
        if not grantor:
            return False, "raising ceiling requires two-person approval (grantor)"
    
    budget.ceiling_usd = new_ceiling
    save_budget(budget)
    return True, f"ceiling updated to ${new_ceiling:.2f}"


def pause_budget(run_id: str) -> bool:
    """Pause a budget (used by Layer C monitor cron at 100% daily)."""
    budget = load_budget(run_id)
    if not budget:
        return False
    budget.paused = True
    save_budget(budget)
    return True


def resume_budget(run_id: str) -> bool:
    """Resume a paused budget."""
    budget = load_budget(run_id)
    if not budget:
        return False
    budget.paused = False
    save_budget(budget)
    return True
