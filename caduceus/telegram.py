"""Telegram bridge: the council's observation deck and the operator's console.

Design ruling (2026-08-19, verified against Bot API 10.0 docs):
- Telegram is for COORDINATION and BROADCAST: task handoffs via command-
  mentions, final attributed positions, kanban/guard events, operator input.
- DELIBERATION stays inside the engine. Cross-exam drafts are anonymized by
  design; attributed Telegram messages would resurrect the conformity trap.
- Bot-to-bot mechanics (Bot API 10.0, May 2026): in groups a bot sees another
  bot's message only via command-mention (/cmd@TargetBot) or direct reply,
  and only when Bot-to-Bot Communication Mode is enabled in BotFather. An
  admin bot with bot-to-bot ON + privacy OFF sees everything (the K2 seat).
- SECURITY (non-negotiable, per Hermes SECURITY.md rule 2): every seat's
  telegram platform config carries an allowlist locked to the council group
  and the operator. No allowlist, no binding.
- Loop protection is OUR job per Telegram docs: reply-depth cap + dedup are
  encoded in the caduceus-council skill rules and enforced here for engine-
  originated posts (no engine post ever replies to a bot message).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config
from .config import SEATS

MAX_POST_CHARS = 900          # keep group messages phone-readable
BOT_REPLY_DEPTH_CAP = 2       # encoded in skill rules; engine never replies to bots


# ---------------------------------------------------------------- settings

def settings_path() -> Path:
    return config.caduceus_home() / "telegram.json"


def settings_template() -> Dict:
    return {
        "_instructions": (
            "Fill this in after the BotFather runbook (cad telegram runbook). "
            "group_chat_id is the supergroup id (starts with -100...). "
            "operator_user_id is Alex's numeric Telegram id. bots maps seat -> "
            "bot username WITHOUT @. Leave a seat out to route its posts "
            "through the default profile's bot."
        ),
        "group_chat_id": "",
        "operator_user_id": "",
        "bots": {name: "" for name in SEATS},
        "k2_admin_bot": "",
    }


def load_settings() -> Optional[Dict]:
    p = settings_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def ensure_settings_file() -> Path:
    p = settings_path()
    if not p.exists():
        p.write_text(json.dumps(settings_template(), indent=2))
    return p


def settings_ready(s: Optional[Dict]) -> Tuple[bool, List[str]]:
    problems = []
    if not s:
        return False, [f"no settings file - created template at {ensure_settings_file()}"]
    if not str(s.get("group_chat_id", "")).startswith("-100"):
        problems.append("group_chat_id missing or not a supergroup id (-100...)")
    if not str(s.get("operator_user_id", "")).strip():
        problems.append("operator_user_id missing")
    return (not problems), problems


# ---------------------------------------------------------------- config gen

def telegram_sub_block(seat_name: str, s: Dict) -> str:
    """The platforms.telegram sub-block for one seat profile (2-space base
    indent, ready to sit under an existing `platforms:` key)."""
    group = s["group_chat_id"]
    operator = s["operator_user_id"]
    peer_bots = [b for name, b in (s.get("bots") or {}).items()
                 if b and name != seat_name]
    if s.get("k2_admin_bot"):
        peer_bots.append(s["k2_admin_bot"])
    allow_from = [str(operator)] + sorted(set(peer_bots))
    allow_list = ", ".join(f'"{a}"' for a in allow_from)
    return (
        "  telegram:\n"
        "    enabled: true\n"
        "    extra:\n"
        f"      allowed_chats: [\"{group}\"]\n"
        f"      group_allowed_chats: [\"{group}\"]\n"
        f"      allow_from: [{allow_list}]\n"
        f"      group_allow_from: [{allow_list}]\n"
    )


def insert_into_platforms(text: str, sub_block: str) -> str:
    """Insert a telegram sub-block under an existing top-level platforms: key,
    or append a new platforms block. Never touches other sub-blocks."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.rstrip() == "platforms:":
            return "\n".join(lines[: i + 1] + sub_block.rstrip("\n").splitlines()
                             + lines[i + 1:]) + "\n"
    return text.rstrip("\n") + "\n\nplatforms:\n" + sub_block


def bind_seats(write: bool = False) -> List[str]:
    """Generate (and optionally write) each seat's telegram platform config."""
    from .seatsetup import backup, profile_dir, profile_exists
    log: List[str] = []
    s = load_settings()
    ok, problems = settings_ready(s)
    if not ok:
        log.append("[!] telegram settings not ready:")
        log.extend(f"    - {p}" for p in problems)
        log.append(f"    edit {settings_path()} then re-run")
        return log
    bots = s.get("bots") or {}
    for name in SEATS:
        bot = (bots.get(name) or "").strip().lstrip("@")
        if not bot:
            log.append(f"[=] {name}: no bot assigned - posts route via default profile")
            continue
        if not profile_exists(name):
            log.append(f"[!] {name}: profile missing - run `cad init` first")
            continue
        cfg = profile_dir(name) / "config.yaml"
        text = cfg.read_text() if cfg.exists() else ""
        if "telegram:" in text:
            log.append(f"[=] {name}: telegram already configured")
            continue
        new_text = insert_into_platforms(text, telegram_sub_block(name, s))
        if write:
            if cfg.exists():
                backup(cfg)
            cfg.write_text(new_text)
            envp = profile_dir(name) / ".env"
            has_token = envp.exists() and "TELEGRAM_BOT_TOKEN" in envp.read_text()
            log.append(f"[+] {name}: telegram bound to @{bot} "
                       f"({'token present' if has_token else 'ADD TELEGRAM_BOT_TOKEN to ' + str(envp)})")
            log.append(f"    restart to apply: hermes -p {name} gateway restart")
        else:
            log.append(f"[i] {name}: would bind @{bot} (pass --write to apply). Block:")
            log.append(telegram_sub_block(name, s))
    if write:
        log.append("[i] allowlists lock every seat to the council group + operator "
                   "+ sibling bots. Widen deliberately or not at all.")
    return log


# ---------------------------------------------------------------- posting

def post(text: str, seat: Optional[str] = None,
         settings: Optional[Dict] = None, timeout: int = 30) -> Tuple[bool, str]:
    """Post to the council group as a seat's bot (or the default profile).
    Engine posts are NEVER replies to bot messages - loop-safe by shape."""
    s = settings or load_settings()
    ok, problems = settings_ready(s)
    if not ok:
        return False, "; ".join(problems)
    hermes = shutil.which("hermes")
    if not hermes:
        return False, "hermes not on PATH"
    text = text if len(text) <= MAX_POST_CHARS else text[: MAX_POST_CHARS - 20] + "\n[truncated]"
    cmd = [hermes]
    if seat:
        cmd += ["-p", seat]
    cmd += ["send", "--to", f"telegram:{s['group_chat_id']}", text]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 0:
            return True, ""
        return False, (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[:200]
    except subprocess.TimeoutExpired:
        return False, "send timeout"
    except Exception as e:  # never let broadcast break a council
        return False, str(e)[:200]


def broadcast_result(result, settings: Optional[Dict] = None) -> List[str]:
    """Post a finished council's attributed outcome to the group."""
    log = []
    s = settings or load_settings()
    ok, _ = settings_ready(s)
    if not ok:
        return ["telegram not configured - skipped broadcast"]
    # each seat posts its own final position, as itself when it has a bot
    bots = (s.get("bots") or {})
    finals = {}
    for rnd in sorted(result.rounds.keys()):
        for d in result.rounds[rnd]:
            if d.parse_ok or d.position:
                finals[d.seat] = d
    for name, d in finals.items():
        line = (f"[{name.upper()}] conf {d.confidence:.2f} - "
                f"{(d.recommendation or d.position)[:400]}")
        okp, err = post(line, seat=name if bots.get(name) else None, settings=s)
        log.append(f"{name}: {'posted' if okp else 'FAILED ' + err}")
        time.sleep(0.3)  # gentle on rate limits
    if result.winner:
        summary = (f"COUNCIL {result.run_id} [{result.domain}] -> lead "
                   f"{result.winner.seat.upper()}: "
                   f"{(result.winner.recommendation or result.winner.position)[:300]}")
        if result.dissent:
            summary += (f"\nMINORITY ({result.dissent.seat.upper()}): "
                        f"{(result.dissent.recommendation or result.dissent.position)[:200]}")
        summary += f"\nsettle: cad ledger settle {result.run_id} --winner <seat>"
        okp, err = post(summary, seat=None, settings=s)
        log.append(f"summary: {'posted' if okp else 'FAILED ' + err}")
    return log


# ---------------------------------------------------------------- runbook

RUNBOOK = """CADUCEUS TELEGRAM RUNBOOK (operator or Hermes-on-the-Mac, ~15 min)

1. In Telegram, open @BotFather. /newbot five times:
     CaduceusForge_bot, CaduceusFinisher_bot, CaduceusRecon_bot,
     CadSparring_bot, CaduceusEnvoy_bot
   Save each token. Tokens NEVER leave this machine.

2. For EACH bot in BotFather -> /mybots -> Bot Settings:
     - enable Bot-to-Bot Communication Mode  (Bot API 10.0 feature)
     - Group Privacy: leave ON for seat bots (they should only hear
       command-mentions, replies, and the operator)

3. Your existing main Hermes bot (K2) is the group's eyes:
     - Bot-to-Bot Communication Mode: ON
     - Group Privacy: OFF   (admin firehose - sees all seats + humans)

4. Create supergroup "Caduceus Council". Add yourself, the 5 seat bots,
   and the K2 bot. Promote the K2 bot to admin.

5. Get ids: send one message in the group, then visit
   https://api.telegram.org/bot<K2_TOKEN>/getUpdates
   -> chat id (-100...) and your numeric user id.

6. On the Mac:
     - put each seat's token in ~/.hermes/profiles/<seat>/.env as
       TELEGRAM_BOT_TOKEN=...
     - fill ~/.caduceus/telegram.json (created by `cad telegram init`)
       with the group id, your user id, and the bot usernames
     - cad telegram init --write
     - restart seat gateways: hermes -p <seat> gateway restart

7. Verify: cad telegram test "council online" && cad doctor

ETIQUETTE (enforced via the caduceus-council skill):
  - seat-to-seat handoffs use command-mentions: /task@CaduceusForge_bot ...
  - reply-depth cap on bot-to-bot chains: 2. Then stop and summarize.
  - deliberation drafts NEVER go to the group - councils stay anonymized
    inside the engine; only final attributed positions are posted.
"""
