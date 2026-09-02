"""cad brief: deterministic operator brief. stdlib only, no model in the path.

2026-09-01: the LLM-driven morning-brief cron had NEVER once written its
deliverable. Its last run died on a 1040s idle timeout inside a subagent it
spawned via delegate_task; the weekly job reported last_status=ok on 08-31
and had ALSO written nothing. The cron-health check added in 0.3.3 was a
false green of exactly the class it was built to catch - it read job status,
and the only thing that actually matters is whether the section landed in
the file the operator reads at session start.

So delivery cannot depend on a model finishing a run. This module gathers
facts with stdlib only (followup.status(), the ledger, hermes cron's
jobs.json, the guard log) and renders the section itself - deterministic,
cheap, and impossible to time out. The cron runs `cad brief --write` with
--no-agent (see seatsetup.CRON_JOBS): no prompt, no subagent, no spend.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

from . import config

PENDING_ENV = "CADUCEUS_PENDING_FILE"

MORNING_HEADING = "## Caduceus morning brief"
WEEKLY_HEADING = "## Caduceus weekly ledger"

_HEADING_DATE_RE = re.compile(r"^(.*)\((\d{4}-\d{2}-\d{2})\)\s*$")


def pending_file() -> Path:
    """Where the brief is delivered. Read at CALL time, never at import time -
    tests set CADUCEUS_PENDING_FILE per-test and expect it to take effect."""
    override = os.environ.get(PENDING_ENV)
    if override:
        return Path(override)
    return Path.home() / "CLAUDE-PENDING-ACTIONS.md"


# ---------------------------------------------------------------- section editing
#
# Deliberately tiny: replace one "## " section (identified by a heading-prefix
# match) with a new one, leaving every other byte of the file untouched. No
# generic markdown parsing - we only ever touch our own section.

def replace_section(text: str, heading_prefix: str, new_section: str) -> str:
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if line.rstrip("\n").startswith(heading_prefix):
            start = i
            break
    if start is None:
        body = text.rstrip("\n")
        if body:
            return body + "\n\n" + new_section.rstrip("\n") + "\n"
        return new_section.rstrip("\n") + "\n"

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break

    new_lines = lines[:start] + [new_section.rstrip("\n") + "\n"] + lines[end:]
    out = "".join(new_lines)
    return out.rstrip("\n") + "\n"


def write(section: str, heading_prefix: str, path: Optional[Path] = None) -> Path:
    p = path or pending_file()
    text = p.read_text() if p.exists() else ""
    out = replace_section(text, heading_prefix, section)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(out)
    return p


def heading_date(heading_prefix: str, path: Optional[Path] = None) -> Optional[str]:
    """The YYYY-MM-DD string on the section's heading line, or None if the
    file or section is missing, or the heading carries no parseable date."""
    p = path or pending_file()
    if not p.exists():
        return None
    for line in p.read_text().splitlines():
        if line.startswith(heading_prefix):
            m = _HEADING_DATE_RE.match(line.strip())
            return m.group(2) if m else None
    return None


def age_hours(heading_prefix: str, now: Optional[dt.datetime] = None,
              path: Optional[Path] = None) -> Optional[float]:
    date_str = heading_date(heading_prefix, path=path)
    if date_str is None:
        return None
    try:
        heading_dt = dt.datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    now = now or dt.datetime.now()
    return (now - heading_dt).total_seconds() / 3600.0


# ---------------------------------------------------------------- gather

def gather(now: Optional[dt.datetime] = None) -> Dict:
    from . import followup
    from .ledger import Ledger

    st = followup.status()
    unsettled = st["unsettled"]
    unexecuted = st["unexecuted"]

    dead_cron = []
    jobs_path = config.hermes_home() / "cron" / "jobs.json"
    if jobs_path.exists():
        try:
            data = json.loads(jobs_path.read_text() or "[]")
            jobs = data if isinstance(data, list) else data.get("jobs", [])
        except Exception:
            jobs = []
        for j in jobs:
            if not isinstance(j, dict):
                continue
            name = str(j.get("name", ""))
            if "caduceus" not in name:
                continue
            streak = int(j.get("failure_streak") or 0)
            if j.get("last_status") == "error" or streak > 0:
                err = " ".join(str(j.get("last_error") or "").split())[:80]
                dead_cron.append({"name": name, "streak": streak, "error": err})

    now = now or dt.datetime.now()
    cutoff = now.timestamp() - 86400
    guard_blocks_24h = 0
    glog = config.guard_log_path()
    if glog.exists():
        for line in glog.read_text().splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                ts = float(d.get("ts"))
            except Exception:
                continue
            if ts >= cutoff:
                guard_blocks_24h += 1

    led = Ledger()
    try:
        ledger_rows = led.table()
    finally:
        led.close()

    return {
        "unsettled": unsettled,
        "unexecuted": unexecuted,
        "dead_cron": dead_cron,
        "guard_blocks_24h": guard_blocks_24h,
        "ledger": ledger_rows,
    }


# ---------------------------------------------------------------- render

def render_morning(facts: Dict, now: Optional[dt.datetime] = None) -> str:
    now = now or dt.datetime.now()
    unsettled = facts["unsettled"]
    unexecuted = facts["unexecuted"]
    dead_cron = facts["dead_cron"]
    guard_blocks = facts["guard_blocks_24h"]

    lines = [f"{MORNING_HEADING} ({now.date().isoformat()})", ""]

    if not unsettled and not unexecuted and not dead_cron and not guard_blocks:
        lines.append("Nothing open - no unsettled runs, no unexecuted commitments, "
                     "cron healthy, 0 guard blocks in 24h.")
        return "\n".join(lines) + "\n"

    if unsettled:
        lines.append(f"### Ungraded decisions ({len(unsettled)})")
        for r in unsettled:
            q = str(r.get("question", ""))[:70]
            rid = r.get("run_id")
            dom = r.get("domain")
            lines.append(f"- {rid} [{dom}] {q}"
                         f" - `cad ledger settle {rid} --winner <seat>`")
        lines.append("")

    if unexecuted:
        lines.append(f"### Unexecuted commitments ({len(unexecuted)})")
        for c in unexecuted:
            action = str(c.action)[:70]
            lines.append(f"- [{c.id}] ({int(c.age_days)}d) {c.run_id}: {action}"
                         f" - `cad followup done {c.id}` / `cad followup drop {c.id}`")
        lines.append("")

    if dead_cron:
        lines.append(f"### Dead cron jobs ({len(dead_cron)})")
        for j in dead_cron:
            lines.append(f"- {j['name']} (streak {j['streak']}): {j['error']}")
        lines.append("")

    lines.append(f"Guard blocks in last 24h: {guard_blocks}")
    lines.append("")

    # Single most important item: oldest unsettled run, else oldest unexecuted
    # commitment. Both are already ordered oldest-first by their sources.
    if unsettled:
        top = unsettled[-1]  # runs() is DESC by ts; oldest is last
        lines.append(f"MOST IMPORTANT: settle `{top.get('run_id')}` "
                     f"({str(top.get('question', ''))[:70]})")
    elif unexecuted:
        top = unexecuted[0]  # pending() is ASC by created_ts; oldest is first
        lines.append(f"MOST IMPORTANT: [{top.id}] {str(top.action)[:70]} "
                     f"({int(top.age_days)}d old)")

    return "\n".join(lines) + "\n"


def render_weekly(facts: Dict, now: Optional[dt.datetime] = None) -> str:
    now = now or dt.datetime.now()
    ledger_rows = facts["ledger"]
    unsettled = facts["unsettled"]
    unexecuted = facts["unexecuted"]

    lines = [f"{WEEKLY_HEADING} ({now.date().isoformat()})", ""]

    if not ledger_rows:
        lines.append("No outcomes recorded yet.")
    else:
        lines.append("| seat | domain | w | m | l | u | believability |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for row in ledger_rows:
            lines.append(f"| {row['seat']} | {row['domain']} | {row['win']} | "
                         f"{row['mixed']} | {row['loss']} | {row['unexecuted']} | "
                         f"{row['believability']} |")

    lines.append("")
    lines.append(f"Unsettled runs: {len(unsettled)}")
    lines.append(f"Unexecuted commitments: {len(unexecuted)}")

    return "\n".join(lines) + "\n"
