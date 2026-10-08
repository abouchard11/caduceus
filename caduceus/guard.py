"""Destructive-command guard + two-person rule.

Wired into Hermes as a blocking pre_tool_call shell hook (fail_closed on the
terminal toolset). Pattern authorship is original; the *pattern* (guard hook +
peer approval for risky ops) follows the well-known dcg/slb approach.

Severity model:
  CRITICAL -> always blocked. No override. (rm -rf /, mkfs, fork bombs...)
  HIGH     -> blocked unless a valid two-person approval token exists.
  WARN     -> allowed, logged, reason annotated.

Third-party repositories (CRITICAL, not a pattern): a push, or a GitHub write
through `gh` or the REST API, aimed at a repository the operator does not own
is blocked. See `third_party_violation`.

Two-person rule: `cad approve grant -- <command>` writes a short-TTL token
bound to the normalized command hash. The second "person" should be a human
or a DIFFERENT model family seat (FINISHER reviews FORGE's request).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
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


def evaluate(cmd: str, cwd: Optional[str] = None) -> Optional[Rule]:
    """Return the highest-severity matching rule, or None.

    `cwd` is the directory the command starts in (the hook payload carries it);
    the third-party rule needs it to read a clone's remotes.
    """
    best: Optional[Rule] = None
    for rule in RULES:
        if rule.pattern.search(cmd):
            if best is None or SEVERITY_RANK[rule.severity] > SEVERITY_RANK[best.severity]:
                best = rule
    if best is None or best.severity != "CRITICAL":
        if third_party_violation(cmd, cwd):
            best = THIRD_PARTY
    return best


# ------------------------------------------------- third-party repositories
#
# Alex, 2026-10-08: "I do not want Hermes touching stuff like this."
#
# On 2026-09-25 a seat squashed and force-pushed the branch behind his pull
# request in typescript-eslint, and a Hermes session commented on that pull
# request asking for review. The push used --force-with-lease, which the
# git-force-push rule exempts on purpose, so nothing here saw it. Other agents
# added to the same thread, and a maintainer closed the replacement pull
# request as an AI-policy violation on 2026-10-07.
#
# What is blocked: `git push`, and writes through `gh` or the GitHub REST API,
# when the target is a repository he does not own. A fork of his counts as
# third-party when the same clone has a remote for somebody else's repository
# of the same name: pushing to that fork is how an upstream pull request
# changes. Reading is never blocked, and neither is local work in a clone.
#
# Not covered: `gh api graphql` mutations, pushes by SSH host alias, and
# anything done in a browser. This stops an agent that means well, not one
# that is trying to get around it.

OWN_GITHUB_OWNERS = ("abouchard11",)

THIRD_PARTY = _r("CRITICAL", "third-party-repo", r"(?!)",
                 "it writes to a GitHub repository Alex does not own")

_GIT_GLOBAL_OPTS = r"(?:\s+(?:-C\s+(?:'[^']*'|\"[^\"]*\"|\S+)|-c\s+\S+|--[\w-]+(?:=\S+)?))*"
_GIT_PUSH = re.compile(r"\bgit(?P<pre>" + _GIT_GLOBAL_OPTS + r")\s+push\b(?P<post>.*)", re.S)
_GIT_C = re.compile(r"\s-C\s+(?P<path>'[^']*'|\"[^\"]*\"|\S+)")
_CD = re.compile(r"^(?:builtin\s+)?cd\s+(?:--\s+)?(?P<path>'[^']*'|\"[^\"]*\"|\S+)")
_GH_WRITE = re.compile(
    r"\bgh\s+(?:pr\s+(?:create|comment|edit|close|reopen|ready|review|merge|update-branch|lock|unlock)"
    r"|issue\s+(?:create|comment|edit|close|reopen|delete|lock|unlock|pin|unpin|transfer|develop)"
    r"|release\s+(?:create|edit|delete|upload))\b")
_GH_API = re.compile(r"\bgh\s+api\b")
_WRITE_METHOD = re.compile(r"(?:\s-X\s*|--(?:method|request)[=\s]+)['\"]?(?:POST|PATCH|PUT|DELETE)\b", re.I)
_READ_METHOD = re.compile(r"(?:\s-X\s*|--(?:method|request)[=\s]+)['\"]?(?:GET|HEAD)\b", re.I)
_GH_FIELD = re.compile(r"\s(?:-f|-F|--field|--raw-field|--input)\b")
_CURL_BODY = re.compile(r"\s(?:-d|--data(?:-raw|-binary|-urlencode)?|--json|-F|--form|-T|--upload-file)\b")
_REPO_FLAG = re.compile(
    r"(?:\s-R\s*|--repo[=\s]+|\bGH_REPO=)['\"]?(?:https?://github\.com/|git@github\.com:)?"
    r"(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)")
_GITHUB_URL = re.compile(
    r"(?<!api\.)github\.com[/:](?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?(?=$|[/\s'\"#?])", re.I)
_API_REPO = re.compile(r"(?:^|[\s'\"/])repos/(?P<owner>[\w.{}:-]+)/(?P<repo>[\w.{}:-]+)")
_PUSH_VALUE_FLAGS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


def _owned(owner: str) -> bool:
    return owner.lower() in OWN_GITHUB_OWNERS


def _segments(cmd: str) -> List[str]:
    """Split on && || ; | and newlines, outside quotes."""
    out, buf, quote, i = [], [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif cmd.startswith(("&&", "||"), i):
            out.append("".join(buf))
            buf = []
            i += 1
        elif ch in ";|\n":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return [seg.strip().lstrip("({ ").strip() for seg in out if seg.strip()]


def _path(base: Optional[str], raw: str) -> Optional[str]:
    raw = os.path.expanduser(raw.strip("'\""))
    if raw == "-":
        return None
    if os.path.isabs(raw):
        return raw
    return os.path.join(base, raw) if base else None


def _remotes(directory: Optional[str]) -> Dict[str, Tuple[str, str]]:
    """GitHub remotes of the clone at `directory`: name -> (owner, repo)."""
    if not directory or not os.path.isdir(directory):
        return {}
    try:
        res = subprocess.run(["git", "-C", directory, "remote", "-v"],
                             capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return {}
    found: Dict[str, Tuple[str, str]] = {}
    for line in res.stdout.splitlines() if res.returncode == 0 else []:
        parts = line.split()
        if len(parts) < 2 or parts[0] in found:
            continue
        m = _GITHUB_URL.search(parts[1])
        if m:
            found[parts[0]] = (m.group("owner"), m.group("repo"))
    return found


def _foreign_repo_names(remotes: Dict[str, Tuple[str, str]]) -> set:
    return {repo.lower() for owner, repo in remotes.values() if not _owned(owner)}


def _push_hits_third_party(seg: str, cur: Optional[str]) -> bool:
    m = _GIT_PUSH.search(seg)
    if not m:
        return False
    c = _GIT_C.search(m.group("pre"))
    directory = _path(cur, c.group("path")) if c else cur
    try:
        tokens = shlex.split(m.group("post"))
    except ValueError:
        tokens = m.group("post").split()
    positional, skip = [], False
    for tok in tokens:
        if skip:
            skip = False
        elif tok in _PUSH_VALUE_FLAGS:
            skip = True
        elif not tok.startswith("-"):
            positional.append(tok)
    target = positional[0] if positional else None
    remotes = _remotes(directory)
    foreign = _foreign_repo_names(remotes)
    url = _GITHUB_URL.search(target) if target else None
    if url:
        return not _owned(url.group("owner")) or url.group("repo").lower() in foreign
    if not foreign:
        return False
    if target is None:
        return True     # a bare push in a clone with somebody else's remote: name the remote
    if target not in remotes:
        return False
    owner, repo = remotes[target]
    return not _owned(owner) or repo.lower() in foreign


def _gh_hits_third_party(seg: str, cur: Optional[str]) -> bool:
    is_api = bool(_GH_API.search(seg)) and bool(
        _WRITE_METHOD.search(seg) or (_GH_FIELD.search(seg) and not _READ_METHOD.search(seg)))
    is_verb = bool(_GH_WRITE.search(seg))
    if not (is_api or is_verb):
        return False
    named = _REPO_FLAG.search(seg)
    if not named and is_api:
        named = _API_REPO.search(seg)
        if named is None:
            return False        # not a repository endpoint
        if re.search(r"[{:]", named.group("owner")):
            named = None        # {owner}/{repo}: gh fills it in from the clone
    if not named and is_verb:
        named = _GITHUB_URL.search(seg)
    if named:
        return not _owned(named.group("owner"))
    return bool(_foreign_repo_names(_remotes(cur)))


def _curl_hits_third_party(seg: str) -> bool:
    if not re.search(r"\bcurl\b", seg) or "api.github.com" not in seg:
        return False
    if not (_WRITE_METHOD.search(seg) or _CURL_BODY.search(seg)):
        return False
    named = _API_REPO.search(seg)
    return bool(named) and not _owned(named.group("owner"))


def third_party_violation(cmd: str, cwd: Optional[str] = None) -> bool:
    """True when `cmd` pushes to, or writes through GitHub to, a repository
    the operator does not own. Follows `cd` through the command."""
    try:
        cur = cwd if cwd and os.path.isabs(cwd) else None
        for seg in _segments(cmd):
            moved = _CD.match(seg)
            if moved:
                cur = _path(cur, moved.group("path"))
                continue
            if (_gh_hits_third_party(seg, cur) or _push_hits_third_party(seg, cur)
                    or _curl_hits_third_party(seg)):
                return True
        return False
    except Exception as exc:    # a parsing bug must not take every seat's shell down
        _log({"action": "error", "rule": "third-party-repo", "error": repr(exc)[:200]})
        return False


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


THIRD_PARTY_REASON = (
    "[caduceus-guard] BLOCKED (third-party-repo): this command writes to a GitHub "
    "repository Alex does not own. Alex's rule, 2026-10-08: Hermes does not push to, "
    "comment on, edit or open pull requests or issues in other people's repositories, "
    "and does not push to his forks that back them. No approval exists for this and "
    "no other route is acceptable. Stop and tell Alex what you were going to do.")


def decide(payload: Dict, only: Optional[str] = None) -> Tuple[int, Optional[Dict]]:
    """Core decision: returns (exit_code, stdout_json|None).

    exit 2 + {"decision":"block"} => Hermes blocks the tool call.
    exit 0 + None                 => allowed.

    only="third-party" applies the third-party rule and nothing else: no
    destructive-command rules, no budget. That is the hook for the operator's
    own profile, which he drives unguarded by choice (see seatsetup).
    """
    tool_input = payload.get("tool_input") or {}
    session = payload.get("session_id", "")
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
    if only == "third-party":
        for cmd in _extract_commands(tool_input):
            if third_party_violation(cmd, cwd):
                _log({"action": "block", "rule": THIRD_PARTY.name, "severity": "CRITICAL",
                      "cmd": normalize_command(cmd)[:300], "session": session})
                return 2, {"decision": "block", "reason": THIRD_PARTY_REASON}
        return 0, None
    verdicts = []
    for cmd in _extract_commands(tool_input):
        rule = evaluate(cmd, cwd)
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
        if rule is THIRD_PARTY:
            return 2, {"decision": "block", "reason": THIRD_PARTY_REASON}
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


def hook_main(only: Optional[str] = None) -> int:
    """stdin: Hermes hook JSON. stdout: decision JSON. Exit 2 blocks."""
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # malformed input: fail open here; fail_closed in config covers crashes
    code, out = decide(payload, only=only)
    if out is not None:
        sys.stdout.write(json.dumps(out))
    return code
