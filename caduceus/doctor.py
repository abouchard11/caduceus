"""cad doctor: is the engine actually wired, or is this template theater?"""
from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import sqlite3
from pathlib import Path
from typing import List, Tuple

from . import brief, config
from .config import SEATS
from .hermes import ApiTransport
from .seatsetup import (hermes_bin, profile_dir, run_hermes,
                        scalar_in_top, tools_attached_sources)

OK, WARN, FAIL = "OK ", "WARN", "FAIL"

# The brief heading carries a DATE only, so age is measured from 00:00 of that
# date. With the 07:00 daily cron the maximum HEALTHY age is 31h (written 07:00
# day N, read 06:59 day N+1) - the old 30h threshold FAILed every morning in
# the 06:00-07:00 window on a live, healthy engine (seen 2026-09-02 06:44).
# A check that cries wolf daily is one the operator learns to ignore, which is
# exactly how the silent failure it exists to catch gets through. 36h clears
# the healthy window and still catches one missed run (>=55h).
STALE_BRIEF_HOURS = 36


def checks() -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []

    hb = hermes_bin()
    if hb:
        code, ver = run_hermes(["--version"], timeout=15)
        out.append((OK if code == 0 else WARN, "hermes binary",
                    f"{hb} ({ver.splitlines()[0][:60] if ver else 'version unknown'})"))
    else:
        out.append((FAIL, "hermes binary", "not on PATH - nothing will run"))

    cad = shutil.which("cad")
    out.append((OK if cad else WARN, "cad on PATH",
                cad or "not found - guard hook config needs an absolute path"))

    # seats (casting overrides applied - doctor checks what SHOULD be live)
    from .models import effective_seat
    for name in SEATS:
        seat = effective_seat(name)
        pd = profile_dir(name)
        if not pd.exists():
            out.append((FAIL, f"seat:{name}", "profile missing - run `cad init`"))
            continue
        soul = pd / "SOUL.md"
        soul_ok = soul.exists() and "CADUCEUS SEAT" in soul.read_text()
        cfg = pd / "config.yaml"
        cfg_text = cfg.read_text() if cfg.exists() else ""
        # model.default, never a whole-file substring: the cast model often
        # appears in unrelated blocks while default: says something else.
        cfg_ok = scalar_in_top(cfg_text, "model", "default") == seat.model
        live_provider = scalar_in_top(cfg_text, "model", "provider")
        provider_ok = live_provider == seat.provider
        bits = []
        bits.append("soul" if soul_ok else "SOUL-MISSING")
        bits.append(f"model={seat.model}" if cfg_ok else "MODEL-NOT-SET")
        if cfg_ok and not provider_ok:
            bits.append(f"PROVIDER={live_provider or 'unset'} (want "
                        f"{seat.provider}) - run `cad init`")
        if seat.provider == "openrouter":
            envp = pd / ".env"
            key_ok = envp.exists() and "OPENROUTER_API_KEY" in envp.read_text()
            bits.append("key" if key_ok else "NO-OPENROUTER-KEY")
            healthy = soul_ok and cfg_ok and provider_ok and key_ok
        else:
            healthy = soul_ok and cfg_ok and provider_ok
        # A tools-incapable seat only works while all three tool-definition
        # sources stay off. Nothing else notices when one comes back: the seat
        # keeps its soul, its model and its key, and 404s on every single call
        # ("No endpoints found that support tool use"). Same silent-failure
        # class as the 0.3.1 inherited-fallback incident, so it gets checked
        # every run rather than trusted because `cad init` once wrote it.
        live_tools: List[str] = []
        stale_strip = False
        if not seat.tools_capable:
            live_tools = tools_attached_sources(cfg.read_text() if cfg.exists() else "")
            bits.append(f"TOOLS-ATTACHED[{'; '.join(live_tools)}]"
                        if live_tools else "tools-stripped")
        elif cfg.exists() and not tools_attached_sources(cfg.read_text()):
            # the inverse regression: seat recast onto a tool-capable model
            # but the full no-tools lockdown is still in its profile. The
            # seat runs - just blind. (Found live on sparring 2026-08-26.)
            stale_strip = True
            bits.append(f"TOOLS-STRIPPED-STALE - {seat.model} takes tools but "
                        "the no-tools lockdown is still applied; run `cad "
                        "init` to restore")
        if live_tools:
            bits.append(f"- {seat.model} has no tool-capable endpoint; "
                        "run `cad init` to re-strip")
            status = FAIL
        elif stale_strip:
            status = WARN
        else:
            status = OK if healthy else WARN
        out.append((status, f"seat:{name}", " ".join(bits)))

    # gateways / api
    api = ApiTransport()
    up = [s.name for s in SEATS.values() if api.available(s)]
    if up:
        out.append((OK, "gateways", f"api_server answering: {', '.join(up)}"))
    else:
        out.append((WARN, "gateways",
                    "no seat gateways up - councils fall back to `hermes -z` "
                    "(works, just slower per call)"))

    # ledger
    try:
        from .ledger import Ledger
        led = Ledger()
        n = led.conn.execute("SELECT COUNT(*) FROM outcomes WHERE voided=0").fetchone()[0]
        runs = led.conn.execute("SELECT COUNT(*) FROM council_runs WHERE settled=0").fetchone()[0]
        led.close()
        msg = f"{n} outcomes recorded, {runs} unsettled runs"
        out.append((OK if n or not runs else OK, "ledger", msg))
        if runs > 5:
            out.append((WARN, "ledger hygiene",
                        f"{runs} unsettled council runs - settle them or the "
                        "believability weights stay flat"))
    except sqlite3.Error as e:
        out.append((FAIL, "ledger", f"sqlite error: {e}"))

    # guard - seat profiles only. The operator drives unguarded; agents don't.
    # (2026-08-19 incident: install_guard_hook() used to also target root
    # config.yaml, so this check has to watch for that regressing too.)
    guarded, unguarded = [], []
    for name in SEATS:
        cfg = profile_dir(name) / "config.yaml"
        if cfg.exists() and "cad guard hook" in cfg.read_text():
            guarded.append(name)
        else:
            unguarded.append(name)
    if guarded and not unguarded:
        out.append((OK, "guard hook", f"wired into {len(guarded)} seat profile(s) (fail_closed)"))
    elif guarded:
        out.append((WARN, "guard hook",
                    f"wired into {', '.join(guarded)}; missing from "
                    f"{', '.join(unguarded)} - run `cad init --guard-write` or "
                    "`cad guard install --write`"))
    else:
        out.append((WARN, "guard hook",
                    "not installed in any seat profile - run `cad init "
                    "--guard-write` or paste the block from `cad guard install`"))

    root_cfg = config.hermes_home() / "config.yaml"
    root_text = root_cfg.read_text() if root_cfg.exists() else ""
    root_hooks = [l for l in root_text.splitlines() if "cad guard hook" in l]
    if root_hooks and all("--only third-party" in l for l in root_hooks):
        # Deliberate (PR #17/18, rule R23): the operator stays unguarded for
        # their own work; only writes into repositories they do not own are
        # judged. A FULL guard in the root is the 2026-08-19 incident class.
        out.append((OK, "guard hook (root)",
                    "third-party-only hook (R23) - operator's own work stays unguarded"))
    elif root_hooks:
        out.append((FAIL, "guard hook (root)",
                    "guard hook found in root config.yaml - the operator's own "
                    "profile must stay unguarded; remove the hooks: block by hand"))
    from . import guard as g
    sample = g.evaluate("rm -rf /")
    out.append((OK if sample and sample.severity == "CRITICAL" else FAIL,
                "guard rules", f"{len(g.RULES)} rules loaded, rm -rf / -> "
                f"{sample.severity if sample else 'MISSED'}"))

    # cron
    cron_jobs = config.hermes_home() / "cron" / "jobs.json"
    if cron_jobs.exists():
        try:
            data = json.loads(cron_jobs.read_text() or "[]")
            jobs = data if isinstance(data, list) else data.get("jobs", [])
            cadjobs = [j for j in jobs if isinstance(j, dict)
                       and "caduceus" in str(j.get("name", ""))]
            # health, not existence: on 2026-08-26 the morning brief had
            # failed silently for 7 straight days (hermes drift_skip after a
            # global model change) while this row said OK on a job-count.
            sick = []
            for j in cadjobs:
                streak = int(j.get("failure_streak") or 0)
                if j.get("last_status") == "error" or streak > 0:
                    err = " ".join(str(j.get("last_error") or "").split())
                    m = re.search(r"\[([a-z_]+(?::[a-z_]+)?)\]", err)
                    sick.append((j.get("name", "?"), streak,
                                 m.group(1) if m else err[:40]))
            if not cadjobs:
                out.append((WARN, "cron",
                            f"no caduceus jobs of {len(jobs)} total - morning "
                            "brief not scheduled (cad init --cron)"))
            elif sick:
                worst = max(s[1] for s in sick)
                det = "; ".join(f"{n} dead ({streak} straight failures: {why})"
                                for n, streak, why in sick)
                out.append((FAIL if worst >= 3 else WARN, "cron",
                            f"{det} - the operator brief is NOT reaching the "
                            "operator; re-register: `hermes cron remove "
                            "<name>` then `cad init --cron`"))
            else:
                out.append((OK, "cron",
                            f"{len(cadjobs)} caduceus jobs healthy of "
                            f"{len(jobs)} total"))
        except Exception:
            out.append((WARN, "cron", "jobs.json unreadable"))
    else:
        out.append((WARN, "cron", "no jobs.json - morning brief not scheduled "
                    "(cad init --cron)"))

    # brief delivery - the artifact, not the job status. 2026-09-01: the cron
    # row above was itself a false green (last_status=ok, nothing written),
    # so this checks the one thing that actually matters: did the dated
    # section land in the file the operator reads at session start.
    age = brief.age_hours(brief.MORNING_HEADING)
    if age is None:
        out.append((FAIL, "brief delivery",
                    f"morning brief has never been written to {brief.pending_file()} "
                    "- run `cad brief --write`; the cron should do this daily "
                    "(cad init --cron)"))
    elif age > STALE_BRIEF_HOURS:
        date = brief.heading_date(brief.MORNING_HEADING)
        out.append((FAIL, "brief delivery",
                    f"morning brief stale: last dated {date} ({age:.0f}h ago) - "
                    "cron is not delivering; run `cad brief --write` and check "
                    "`hermes cron list`"))
    else:
        date = brief.heading_date(brief.MORNING_HEADING)
        out.append((OK, "brief delivery", f"morning brief delivered {date}"))

    # telegram bridge
    from . import telegram as tg
    ts = tg.load_settings()
    ready, problems = tg.settings_ready(ts)
    if ready:
        bots = [f"{k}→@{v}" for k, v in (ts.get("bots") or {}).items() if v]
        out.append((OK, "telegram", f"group set, {len(bots)} seat bots mapped"))
        missing_tokens = []
        for name, bot in (ts.get("bots") or {}).items():
            if bot:
                envp = profile_dir(name) / ".env"
                if not (envp.exists() and "TELEGRAM_BOT_TOKEN" in envp.read_text()):
                    missing_tokens.append(name)
        if missing_tokens:
            out.append((WARN, "telegram tokens",
                        f"missing TELEGRAM_BOT_TOKEN: {', '.join(missing_tokens)}"))
    else:
        out.append((WARN, "telegram",
                    "bridge not configured (optional) - cad telegram runbook"))

    # launchd - the seat-work executor (Mon/Thu 08:45, --live) and the nudge
    # run from ~/Library/LaunchAgents, not hermes cron. 2026-09-02: both had
    # fired and died with "cad: error: invalid choice: 'exec'" - the editable
    # install was on a checkout that predated the subcommand - and the failure
    # sat in /tmp/caduceus-*.err where nobody looked. Same silent class as the
    # cron row above; watch the artifact (the err log), not the schedule.
    ldir = Path(os.environ.get("CADUCEUS_LAUNCHD_DIR",
                               str(Path.home() / "Library" / "LaunchAgents")))
    plists = sorted(ldir.glob("*caduceus*.plist")) if ldir.exists() else []
    if plists:
        sick = []
        for pl in plists:
            try:
                with open(pl, "rb") as f:
                    data = plistlib.load(f)
            except Exception:
                continue
            label = str(data.get("Label", pl.stem))
            errp = data.get("StandardErrorPath")
            if errp and Path(str(errp)).exists():
                lines = [l for l in Path(str(errp)).read_text().splitlines() if l.strip()]
                last = lines[-1] if lines else ""
                if re.search(r"error|traceback|exception", last, re.I):
                    sick.append(f"{label}: {last[:90]}")
        if sick:
            out.append((WARN, "launchd",
                        "; ".join(sick) + " - last unattended run died. The "
                        "jobs call the editable install: check `git -C "
                        "~/projects/caduceus branch --show-current` is main, "
                        "then re-run the job's command by hand"))
        else:
            out.append((OK, "launchd",
                        f"{len(plists)} caduceus job(s) installed, err logs clean"))

    # env
    env = config.load_env()
    out.append((OK if len(env.get("CADUCEUS_API_KEY", "")) >= 16 else WARN,
                "api key", "present" if env.get("CADUCEUS_API_KEY") else
                "not generated yet (created on cad init)"))

    # compile (0.4.0): the profile is data, USER.md is generated from it. A
    # hand edit or a stale render is exactly the drift Decision 10 forbids.
    out.append(_profile_row())
    out.append(_loadout_row())
    return out


def _profile_row() -> Tuple[str, str, str]:
    from . import compile as compile_mod, profile as profile_mod
    path = config.repo_root() / "seats" / "PROFILE.json"
    if not path.exists():
        return (WARN, "profile", f"no seats/PROFILE.json at {path.parent} - USER.md is hand-written")
    try:
        p = profile_mod.load(path)
        res = compile_mod.write_outputs(p, compile_mod.cast(p), config.repo_root(), write=False)
    except Exception as e:  # a broken profile is a warning, never a doctor crash
        return (WARN, "profile", f"PROFILE.json unreadable: {e}")
    stale = [k for k, v in res.items() if v != "unchanged"]
    if stale:
        return (WARN, "profile", f"{', '.join(stale)} stale vs PROFILE.json - run "
                                 "`cad compile --write` then `cad init`")
    repo_user = (config.repo_root() / "seats" / "USER.md").read_text()
    stale_seats = []
    for name in SEATS:
        copy = profile_dir(name) / "USER.md"
        if copy.exists() and copy.read_text() != repo_user:
            stale_seats.append(name)
    if stale_seats:
        return (WARN, "profile", f"seat copies stale ({', '.join(stale_seats)}) - run `cad init`")
    return (OK, "profile", f"USER.md and CAST.json match PROFILE.json (sha {p.sha256[:12]})")


def _loadout_row() -> Tuple[str, str, str]:
    from . import evalpair, loadout
    from .ledger import Ledger
    try:
        st = loadout.status()
        t0 = st["first_install_ts"]
        if t0 is None:
            return (OK, "loadout", "not installed (clock not started)")
        n = sum(s["installed"] for s in st["seats"].values())
        k = sum(1 for s in st["seats"].values() if s["installed"])
        led = Ledger()
        try:
            r = evalpair.report(led)
        finally:
            led.close()
        days = int(r["days"]) if r["days"] is not None else 0
        detail = (f"{n} skills across {k} seats; day {days}/{evalpair.RULE_DAYS}; pairs {r['pairs']} "
                  f"(B {r['b_wins']} / A {r['a_wins']}, {r['unsettled']} unsettled); {r['verdict']}")
        return (WARN if r["verdict"] == "PARK" else OK, "loadout", detail)
    except Exception as e:
        return (WARN, "loadout", f"status unreadable: {e}")


def render(rows: List[Tuple[str, str, str]]) -> str:
    lines = ["caduceus doctor", "=" * 60]
    fails = warns = 0
    for status, name, detail in rows:
        lines.append(f"[{status}] {name:<16} {detail}")
        fails += status == FAIL
        warns += status == WARN
    lines.append("=" * 60)
    if fails:
        lines.append(f"{fails} failure(s), {warns} warning(s) - engine NOT ready")
    elif warns:
        lines.append(f"0 failures, {warns} warning(s) - engine runs; sharpen the edges")
    else:
        lines.append("all green - go make something")
    return "\n".join(lines)


def exit_code(rows: List[Tuple[str, str, str]]) -> int:
    return 1 if any(r[0] == FAIL for r in rows) else 0
