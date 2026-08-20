"""cad doctor: is the engine actually wired, or is this template theater?"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import List, Tuple

from . import config
from .config import SEATS
from .hermes import ApiTransport
from .seatsetup import hermes_bin, profile_dir, run_hermes

OK, WARN, FAIL = "OK ", "WARN", "FAIL"


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
        cfg_ok = cfg.exists() and seat.model in cfg.read_text()
        bits = []
        bits.append("soul" if soul_ok else "SOUL-MISSING")
        bits.append(f"model={seat.model}" if cfg_ok else "MODEL-NOT-SET")
        if seat.provider == "openrouter":
            envp = pd / ".env"
            key_ok = envp.exists() and "OPENROUTER_API_KEY" in envp.read_text()
            bits.append("key" if key_ok else "NO-OPENROUTER-KEY")
            status = OK if (soul_ok and cfg_ok and key_ok) else WARN
        else:
            status = OK if (soul_ok and cfg_ok) else WARN
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
        n = led.conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
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
    if root_cfg.exists() and "cad guard hook" in root_cfg.read_text():
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
            names = [j.get("name", "?") for j in jobs if isinstance(j, dict)]
            cadjobs = [n for n in names if n and "caduceus" in n]
            out.append((OK if cadjobs else WARN, "cron",
                        f"{len(cadjobs)} caduceus jobs of {len(names)} total"))
        except Exception:
            out.append((WARN, "cron", "jobs.json unreadable"))
    else:
        out.append((WARN, "cron", "no jobs.json - morning brief not scheduled "
                    "(cad init --cron)"))

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

    # env
    env = config.load_env()
    out.append((OK if len(env.get("CADUCEUS_API_KEY", "")) >= 16 else WARN,
                "api key", "present" if env.get("CADUCEUS_API_KEY") else
                "not generated yet (created on cad init)"))
    return out


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
