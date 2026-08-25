"""Destructive-command guard + two-person rule.

Wired into Hermes as a blocking pre_tool_call shell hook (fail_closed on the
terminal toolset). Pattern authorship is original; the *pattern* (guard hook +
peer approval for risky ops) follows the well-known dcg/slb approach.

Severity model:
  CRITICAL -> always blocked. No override. (rm -rf /, mkfs, fork bombs...)
  HIGH     -> blocked unless a valid two-person approval token exists.
  WARN     -> allowed, logged, reason annotated.

Two-person rule: `cad approve grant -- <command>` writes a short-TTL token
bound to the normalized command hash. The second "person" should be a human
or a DIFFERENT model family seat (FINISHER reviews FORGE's request).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import config
from . import budgets

TOKEN_TTL_SECONDS = 15 * 60

@dataclass(frozen=True)
class Rule:
    severity: str      # CRITICAL | HIGH | WARN
    name: str
    pattern: re.Pattern
    why: str


def _r(sev: str, name: str, rx: str, why: str) -> Rule:
    return Rule(sev, name, re.compile(rx, re.IGNORECASE), why)


RULES: List[Rule] = [
    # ------------------------------------------------ CRITICAL: no override
    _r("CRITICAL", "rm-root",
       r"\brm\b[^|;&]*\s(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)[a-z]*\s+(/|/\*|~|\$home\b|\.\.)(\s|$|/\*)",
       "recursive force-delete of root/home/parent"),
    _r("CRITICAL", "mkfs", r"\bmkfs(\.| )", "filesystem format"),
    _r("CRITICAL", "dd-device", r"\bdd\b[^|;&]*\bof=/dev/", "raw write to device"),
    _r("CRITICAL", "diskutil-erase", r"\bdiskutil\b.*\berase", "disk erase"),
    _r("CRITICAL", "fork-bomb", r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;", "fork bomb"),
    _r("CRITICAL", "chmod-root", r"\bchmod\b\s+(-[a-z]*r[a-z]*\s+)?[0-7]{3,4}\s+/(\s|$)", "permission bomb on /"),
    _r("CRITICAL", "shutdown", r"\b(shutdown|reboot|halt)\b(\s|$)", "host shutdown/reboot"),
    _r("CRITICAL", "hist-wipe", r"\b(history\s+-c|rm\b.*\.(bash|zsh)_history)", "history tampering"),
    _r("CRITICAL", "ssh-keys", r"\brm\b[^|;&]*(~|\$home)?/?\.ssh\b", "deleting ssh keys"),

    # ------------------------------------------------ HIGH: two-person token
    _r("HIGH", "rm-recursive",
       r"\brm\b[^|;&]*\s(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-[a-z]*r)[a-z]*\s+\S",
       "recursive delete"),
    _r("HIGH", "git-reset-hard", r"\bgit\b[^|;&]*\breset\b[^|;&]*--hard", "discards uncommitted work"),
    _r("HIGH", "git-clean", r"\bgit\b[^|;&]*\bclean\b[^|;&]*-[a-z]*f", "deletes untracked files"),
    _r("HIGH", "git-force-push",
       r"\bgit\b[^|;&]*\bpush\b[^|;&]*(--force(?!-with-lease)|\s-f\b)",
       "force push rewrites remote history"),
    _r("HIGH", "git-branch-D", r"\bgit\b[^|;&]*\bbranch\b[^|;&]*\s-D\s", "force-deletes branch"),
    _r("HIGH", "drop-table", r"\b(drop\s+(table|database|schema)|truncate\s+table)\b", "destructive SQL"),
    _r("HIGH", "curl-pipe-sh",
       r"\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba|z|da)?sh\b",
       "piping the internet into a shell"),
    _r("HIGH", "launchctl", r"\blaunchctl\b\s+(bootout|unload|remove)\b", "removing launch daemons"),
    _r("HIGH", "kill-broad", r"\b(kill\s+-9\s+-1|killall\s+-9?\s*\S+)", "broad process kill"),
    _r("HIGH", "sudo-rm", r"\bsudo\b[^|;&]*\brm\b", "privileged delete"),
    _r("HIGH", "crontab-wipe", r"\bcrontab\s+-r\b", "wipes crontab"),

    # ------------------------------------------------ WARN: allow + log
    _r("WARN", "pip-system", r"\bpip3?\s+install\b(?![^|;&]*--user)", "system-level package install"),
    _r("WARN", "chmod-777", r"\bchmod\b[^|;&]*777", "world-writable permissions"),
    _r("WARN", "env-dump", r"\b(printenv|env)\b\s*($|\|)", "environment dump may expose secrets"),
]

SEVERITY_RANK = {"CRITICAL": 3, "HIGH": 2, "WARN": 1}


def normalize_command(cmd: str) -> str:
    return re.sub(r"\s+", " ", cmd.strip())


def command_hash(cmd: str) -> str:
    return hashlib.sha256(normalize_command(cmd).encode()).hexdigest()[:16]


def evaluate(cmd: str) -> Optional[Rule]:
    """Return the highest-severity matching rule, or None."""
    best: Optional[Rule] = None
    for rule in RULES:
        if rule.pattern.search(cmd):
            if best is None or SEVERITY_RANK[rule.severity] > SEVERITY_RANK[best.severity]:
                best = rule
    return best


# ---------------------------------------------------------------- approvals

def token_path(cmd: str):
    return config.approvals_dir() / f"{command_hash(cmd)}.json"


def grant(cmd: str, grantor: str, ttl: int = TOKEN_TTL_SECONDS) -> Dict:
    tok = {
        "hash": command_hash(cmd),
        "command": normalize_command(cmd)[:500],
        "grantor": grantor,
        "granted_at": time.time(),
        "expires_at": time.time() + ttl,
    }
    p = token_path(cmd)
    p.write_text(json.dumps(tok, indent=2))
    os.chmod(p, 0o600)
    return tok


def check_token(cmd: str) -> Optional[Dict]:
    p = token_path(cmd)
    if not p.exists():
        return None
    try:
        tok = json.loads(p.read_text())
    except Exception:
        return None
    if tok.get("expires_at", 0) < time.time():
        try:
            p.unlink()
        except OSError:
            pass
        return None
    return tok


def consume_token(cmd: str) -> None:
    """One approval, one execution."""
    try:
        token_path(cmd).unlink()
    except OSError:
        pass


def list_tokens() -> List[Dict]:
    out = []
    for p in config.approvals_dir().glob("*.json"):
        try:
            tok = json.loads(p.read_text())
            tok["valid"] = tok.get("expires_at", 0) >= time.time()
            out.append(tok)
        except Exception:
            continue
    return out


# ---------------------------------------------------------------- hook entry

def _extract_commands(tool_input) -> List[str]:
    """Hermes terminal tool sends {'command': ...}; be defensive and scan
    every string value so renamed keys can't sneak past the guard."""
    cmds: List[str] = []
    if isinstance(tool_input, dict):
        for v in tool_input.values():
            if isinstance(v, str) and v.strip():
                cmds.append(v)
            elif isinstance(v, (dict, list)):
                cmds.extend(_extract_commands(v))
    elif isinstance(tool_input, list):
        for v in tool_input:
            cmds.extend(_extract_commands(v))
    elif isinstance(tool_input, str):
        cmds.append(tool_input)
    return cmds


def _log(event: Dict) -> None:
    event["ts"] = time.time()
    try:
        with open(config.guard_log_path(), "a") as f:
            f.write(json.dumps(event) + "\n")
    except OSError:
        pass


def decide(payload: Dict) -> Tuple[int, Optional[Dict]]:
    """Core decision: returns (exit_code, stdout_json|None).

    exit 2 + {"decision":"block"} => Hermes blocks the tool call.
    exit 0 + None                 => allowed.
    """
    tool_input = payload.get("tool_input") or {}
    session = payload.get("session_id", "")
    verdicts = []
    for cmd in _extract_commands(tool_input):
        rule = evaluate(cmd)
        if rule is None:
            continue
        verdicts.append((rule, cmd))

    # Check budget before pattern matching (spec: budget is the primary choke point)
    budget = budgets.find_budget_for_session(session) if session else None
    budget_warn_context = None
    if budget:
        status, spend, ceiling = budgets.check_budget(budget.run_id)
        if status == "block":
            _log({
                "action": "block-budget",
                "run_id": budget.run_id,
                "spend": spend,
                "ceiling": ceiling,
                "session": session,
            })
            return 2, {
                "decision": "block",
                "reason": f"[caduceus-budget] BLOCKED: run {budget.run_id} exceeded ceiling. "
                         f"Spend ${spend:.4f} >= ceiling ${ceiling:.2f}. "
                         f"Raise ceiling with: cad budget set --run {budget.run_id} --ceiling <usd>"
            }
        elif status == "warn":
            _log({
                "action": "warn-budget",
                "run_id": budget.run_id,
                "spend": spend,
                "ceiling": ceiling,
                "session": session,
            })
            # F4 fix: capture warning context to return to model
            budget_warn_context = (
                f"[caduceus-budget] WARNING: run {budget.run_id} approaching ceiling. "
                f"Spend ${spend:.4f} / ${ceiling:.2f} ({spend/ceiling*100:.0f}%). "
                f"Consider wrapping up soon."
            )

    if not verdicts:
        # F4 fix: return budget warning context if we have one
        if budget_warn_context:
            return 0, {"context": budget_warn_context}
        return 0, None

    # highest severity wins
    verdicts.sort(key=lambda rc: -SEVERITY_RANK[rc[0].severity])
    rule, cmd = verdicts[0]

    if rule.severity == "CRITICAL":
        _log({"action": "block", "rule": rule.name, "severity": "CRITICAL",
              "cmd": normalize_command(cmd)[:300], "session": session})
        return 2, {"decision": "block", "reason":
                   f"[caduceus-guard] BLOCKED ({rule.name}): {rule.why}. "
                   f"No override exists for CRITICAL commands. Find another way."}

    if rule.severity == "HIGH":
        tok = check_token(cmd)
        if tok:
            consume_token(cmd)
            _log({"action": "allow-approved", "rule": rule.name, "severity": "HIGH",
                  "cmd": normalize_command(cmd)[:300], "grantor": tok.get("grantor"),
                  "session": session})
            return 0, None
        h = command_hash(cmd)
        _log({"action": "block-pending-approval", "rule": rule.name,
              "severity": "HIGH", "hash": h,
              "cmd": normalize_command(cmd)[:300], "session": session})
        return 2, {"decision": "block", "reason":
                   f"[caduceus-guard] HELD ({rule.name}): {rule.why}. "
                   f"Two-person rule applies. A DIFFERENT seat or the operator must run: "
                   f"cad approve grant --grantor <seat|alex> -- {normalize_command(cmd)[:200]} "
                   f"(hash {h}, token valid {TOKEN_TTL_SECONDS//60}m, single use). "
                   f"Do not retry until approved."}

    _log({"action": "warn", "rule": rule.name, "severity": "WARN",
          "cmd": normalize_command(cmd)[:300], "session": session})
    return 0, {"context": f"[caduceus-guard] note ({rule.name}): {rule.why}"}


def hook_main() -> int:
    """stdin: Hermes hook JSON. stdout: decision JSON. Exit 2 blocks."""
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # malformed input: fail open here; fail_closed in config covers crashes
    code, out = decide(payload)
    if out is not None:
        sys.stdout.write(json.dumps(out))
    return code
