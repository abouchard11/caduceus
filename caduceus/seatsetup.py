"""Seat provisioning: turns the seat definitions into real Hermes profiles.

Philosophy: configure Hermes, don't fork it. Every step is idempotent and
non-destructive - existing profiles are patched with timestamped backups,
never clobbered blind.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config
from .config import SEATS, Seat


def hermes_bin() -> Optional[str]:
    return shutil.which("hermes")


def run_hermes(args: List[str], timeout: int = 60) -> Tuple[int, str]:
    hb = hermes_bin()
    if not hb:
        return 127, "hermes binary not on PATH"
    try:
        p = subprocess.run([hb] + args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + "\n" + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"timeout running hermes {' '.join(args[:3])}"


def profile_dir(seat_name: str) -> Path:
    return config.hermes_home() / "profiles" / seat_name


def profile_exists(seat_name: str) -> bool:
    return profile_dir(seat_name).exists()


# ---------------------------------------------------------------- yaml patching
# Deliberately tiny line-based editor: replaces one TOP-LEVEL block. We do not
# parse YAML generically (stdlib-only, comment-preserving), we only need to
# swap the `model:` block and append missing top-level blocks.

def replace_top_block(text: str, key: str, new_block: str) -> str:
    lines = text.splitlines()
    out, i, replaced = [], 0, False
    while i < len(lines):
        line = lines[i]
        if re.match(rf"^{re.escape(key)}\s*:", line) and not replaced:
            out.append(new_block.rstrip("\n"))
            i += 1
            while i < len(lines) and (not lines[i].strip()
                                      or lines[i].startswith((" ", "\t"))
                                      or lines[i].lstrip().startswith("#")
                                      and lines[i].startswith(" ")):
                # consume the old block body (indented lines / blanks / indented comments)
                if lines[i].strip() and not lines[i].startswith((" ", "\t")):
                    break
                i += 1
            replaced = True
            continue
        out.append(line)
        i += 1
    if not replaced:
        out.append("")
        out.append(new_block.rstrip("\n"))
    return "\n".join(out) + "\n"


def has_top_block(text: str, key: str) -> bool:
    return re.search(rf"^{re.escape(key)}\s*:", text, re.MULTILINE) is not None


def model_block(seat: Seat) -> str:
    return (
        "model:\n"
        f"  default: {seat.model}\n"
        f"  provider: {seat.provider}\n"
        "  max_tokens: 8192\n"
    )


def fallback_block() -> str:
    # `hermes profile create --clone` copies the root profile's
    # fallback_providers block verbatim into every new seat. Left alone this
    # is a double hazard: (1) every seat silently reroutes to the SAME
    # fallback model on any primary hiccup, which - if it ever succeeds -
    # collapses the model-family heterogeneity Decision #4 requires without
    # anyone noticing; (2) that fallback target may be uncapped and far more
    # expensive than the seat's real casting (2026-08-19: a shared
    # anthropic/claude-opus-4.6 fallback 402'd requesting 128k tokens and its
    # raw billing error nearly became a council's headline recommendation).
    # Council seats must fail loud and attributably, not reroute in secret.
    return "fallback_providers: []\n"


def api_server_block(seat: Seat, key: str) -> str:
    return (
        "platforms:\n"
        "  api_server:\n"
        "    enabled: true\n"
        "    extra:\n"
        f"      key: \"{key}\"\n"
        "      host: \"127.0.0.1\"\n"
        f"      port: {seat.port}\n"
        "      max_concurrent_runs: 8\n"
    )


def hooks_block(guard_cmd: str) -> str:
    return (
        "hooks:\n"
        "  pre_tool_call:\n"
        "    - matcher: \"terminal|code_execution\"\n"
        f"      command: \"{guard_cmd}\"\n"
        "      timeout: 10\n"
        "      fail_closed: true\n"
        "hooks_auto_accept: true\n"
    )


def backup(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    b = path.with_suffix(path.suffix + f".bak.caduceus-{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, b)
    return b


# ---------------------------------------------------------------- provisioning

def create_profile(seat: Seat, log: List[str]) -> bool:
    if profile_exists(seat.name):
        log.append(f"[=] profile '{seat.name}' exists")
        return True
    code, out = run_hermes([
        "profile", "create", seat.name, "--clone", "--description", seat.role,
    ])
    if code == 0 or profile_exists(seat.name):
        log.append(f"[+] created profile '{seat.name}'")
        return True
    log.append(f"[!] profile create '{seat.name}' failed: {out[:200]}")
    return False


def install_soul(seat: Seat, log: List[str], force: bool = False) -> None:
    src = config.repo_root() / "seats" / seat.name / "SOUL.md"
    dst = profile_dir(seat.name) / "SOUL.md"
    if not src.exists():
        log.append(f"[!] missing seat soul source: {src}")
        return
    if dst.exists() and not force:
        existing = dst.read_text()
        if "CADUCEUS SEAT" in existing:
            log.append(f"[=] soul for '{seat.name}' already installed")
            return
        backup(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    log.append(f"[+] soul installed for '{seat.name}'")


def install_user_md(seat: Seat, log: List[str]) -> None:
    src = config.repo_root() / "seats" / "USER.md"
    dst = profile_dir(seat.name) / "USER.md"
    if not src.exists():
        return
    if dst.exists() and "CADUCEUS PRINCIPAL PROFILE" in dst.read_text():
        log.append(f"[=] USER.md for '{seat.name}' current")
        return
    if dst.exists():
        backup(dst)
    shutil.copy2(src, dst)
    log.append(f"[+] USER.md installed for '{seat.name}'")


def patch_profile_config(seat: Seat, api_key: str, log: List[str],
                         enable_api: bool = True) -> None:
    cfg = profile_dir(seat.name) / "config.yaml"
    if not cfg.exists():
        # minimal standalone config
        body = model_block(seat) + "\n" + fallback_block()
        if enable_api:
            body += "\n" + api_server_block(seat, api_key)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(body)
        log.append(f"[+] wrote fresh config for '{seat.name}'")
        return
    text = cfg.read_text()
    new_text = replace_top_block(text, "model", model_block(seat))
    new_text = replace_top_block(new_text, "fallback_providers", fallback_block())
    if enable_api and not has_top_block(new_text, "platforms"):
        new_text += "\n" + api_server_block(seat, api_key)
    if new_text != text:
        backup(cfg)
        cfg.write_text(new_text)
        log.append(f"[+] patched config for '{seat.name}' "
                   f"(model={seat.model} provider={seat.provider} port={seat.port})")
    else:
        log.append(f"[=] config for '{seat.name}' already correct")
    # sanity: openrouter seats need the key in the profile env
    if seat.provider == "openrouter":
        envp = profile_dir(seat.name) / ".env"
        has_key = envp.exists() and "OPENROUTER_API_KEY" in envp.read_text()
        if not has_key:
            root_env = config.hermes_home() / ".env"
            if root_env.exists() and "OPENROUTER_API_KEY" in root_env.read_text():
                # copy ONLY the openrouter line, not the whole secret store
                for line in root_env.read_text().splitlines():
                    if line.startswith("OPENROUTER_API_KEY"):
                        with open(envp, "a") as f:
                            f.write("\n" + line + "\n")
                        log.append(f"[+] copied OPENROUTER_API_KEY into '{seat.name}' env")
                        break
            else:
                log.append(f"[!] '{seat.name}' uses openrouter but no "
                           f"OPENROUTER_API_KEY found - seat will fail until set")


def install_skill(seat_names: List[str], log: List[str]) -> None:
    src = config.repo_root() / "skills" / "caduceus-council"
    if not src.exists():
        log.append("[!] skill source missing")
        return
    targets = [config.hermes_home() / "skills" / "productivity" / "caduceus-council"]
    for name in seat_names:
        targets.append(profile_dir(name) / "skills" / "productivity" / "caduceus-council")
    for dst in targets:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    log.append(f"[+] caduceus-council skill installed to {len(targets)} skill dirs")


def install_guard_hook(log: List[str], write: bool = False,
                       profiles: Optional[List[str]] = None) -> str:
    # Seat profiles only - never the operator's own root config.yaml. Alex
    # drives unguarded; agents don't. (2026-08-19 incident: this used to
    # prepend hermes_home()/config.yaml unconditionally, so `cad init
    # --guard-write` silently hooked the operator's daily-driver profile
    # alongside the seats. The root hook was pulled by hand mid-session;
    # it must not come back on the next re-run.)
    guard_cmd = f"{shutil.which('cad') or 'cad'} guard hook"
    snippet = hooks_block(guard_cmd)
    targets = [profile_dir(name) / "config.yaml" for name in (profiles or [])]
    if not write:
        log.append("[i] guard hook NOT written (pass --write). Add to config.yaml:")
        log.append(snippet)
        return snippet
    for cfg in targets:
        if not cfg.exists():
            continue
        text = cfg.read_text()
        if "cad guard hook" in text:
            log.append(f"[=] guard hook already present in {cfg}")
            continue
        if has_top_block(text, "hooks"):
            log.append(f"[!] {cfg} already has a hooks: block - merge manually:")
            log.append(snippet)
            continue
        backup(cfg)
        cfg.write_text(text.rstrip("\n") + "\n\n" + snippet)
        log.append(f"[+] guard hook appended to {cfg}")
    return snippet


CRON_JOBS = [
    {
        "name": "caduceus-morning-brief",
        "schedule": "0 7 * * *",
        "prompt": ("Run the caduceus-council skill's morning-brief procedure: "
                   "run `cad dashboard`, read ~/.caduceus/runs for unsettled "
                   "council runs, check `cad ledger runs`, then produce a "
                   "5-line brief: unsettled decisions, guard blocks in the last "
                   "24h, and the single most important thing to push today."),
    },
    {
        "name": "caduceus-weekly-ledger",
        "schedule": "0 8 * * 1",
        "prompt": ("Run `cad ledger show` and summarize seat believability "
                   "movement over the past week in 5 lines. Flag any seat "
                   "whose track record says its model should be up- or "
                   "down-graded, with the cost math."),
    },
]


def install_cron(log: List[str]) -> None:
    for job in CRON_JOBS:
        code, out = run_hermes([
            "cron", "create", job["schedule"], job["prompt"],
            "--name", job["name"],
        ])
        if code == 0:
            log.append(f"[+] cron '{job['name']}' registered")
        else:
            low = out.lower()
            if "exist" in low or "duplicate" in low:
                log.append(f"[=] cron '{job['name']}' already present")
            else:
                log.append(f"[!] cron '{job['name']}' failed: {out[:160]}")


def gateway_commands(seats: List[Seat]) -> List[str]:
    return [f"hermes -p {s.name} gateway install --start-now" for s in seats]


def init(seat_names: Optional[List[str]] = None, force_soul: bool = False,
         cron: bool = False, guard_write: bool = False,
         enable_api: bool = True) -> List[str]:
    log: List[str] = []
    if not hermes_bin():
        log.append("[!] FATAL: `hermes` not on PATH. Install Hermes Agent first.")
        return log
    api_key = config.ensure_api_key()
    names = seat_names or list(SEATS.keys())
    created = []
    for name in names:
        seat = SEATS[name]
        if create_profile(seat, log):
            install_soul(seat, log, force=force_soul)
            install_user_md(seat, log)
            patch_profile_config(seat, api_key, log, enable_api=enable_api)
            created.append(name)
    install_skill(created, log)
    install_guard_hook(log, write=guard_write, profiles=created)
    if cron:
        install_cron(log)
    else:
        log.append("[i] cron jobs skipped (pass --cron to register the morning "
                   "brief + weekly ledger digest)")
    log.append("")
    log.append("Seats provisioned. Optional always-on gateways (event-driven, "
               "$0 idle):")
    for cmd in gateway_commands([SEATS[n] for n in created]):
        log.append(f"    {cmd}")
    log.append("Then verify with: cad doctor")
    return log
