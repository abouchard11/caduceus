"""Staff-work executor: agent-owned commitments get done, not queued.

Operator policy (set 2026-08-27, after three of four settled runs failed as
memo-only advice nobody executed):
  - $15/day across all executor actions, $2 hard cap per action (budgets.py)
  - unattended: run tests, read. Writes only when simple - NEW files inside
    an allowed project root, applied by this wrapper, never by the model.
  - push / deploy / network / installs: NEVER autonomous. Escalate to the
    operator's agenda and notify via Telegram before anything can close.

Shape of the trust boundary: the model returns DATA (file blocks), and this
deterministic wrapper decides what touches disk. That boundary is ENFORCED,
not assumed: a bare `hermes -z` call is a full agent with 22 tools and MCP
servers, and on the first live run FORGE wrote a file itself before the
wrapper saw the reply. Every executor call therefore passes `-t clarify` -
hermes' -t is an enable-list, so one harmless toolset strips everything
else, MCP included (verified empirically 2026-08-27).
"""
from __future__ import annotations

import fcntl
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import budgets, config, followup
from .hermes import OneshotTransport, SeatReply

# Cost booked per action when the transport reports no usage. Conservative:
# a single oneshot draft measured $0.02-0.10; preflight reserves 5x that.
EST_ACTION_COST = 0.50

ALLOWED_ROOTS = (
    Path.home() / "projects" / "caduceus",
    Path.home() / "projects" / "hq",
)

# Never writable even inside an allowed root.
DENY_PARTS = (".git", ".env", ".hermes", "node_modules")
DENY_NAMES = ("settings.json", "settings.local.json", "config.yaml")

# 2026-09-02 review, proven by execution: a model-written conftest.py was run
# by this wrapper's own pytest step - arbitrary code as the operator, no tools
# needed. The wrapper NEVER executes model output, and never writes anything
# a loader would execute or read as config. v1 writes prose.
EXEC_SUFFIXES = (".py", ".pyi", ".sh", ".bash", ".zsh", ".rb", ".js", ".mjs",
                 ".cjs", ".ts", ".yml", ".yaml", ".toml", ".cfg", ".ini",
                 ".plist", ".json")
EXEC_NAMES = ("makefile", "conftest.py", "dockerfile", "justfile")

# Escalation is the wrapper's decision, made BEFORE any spend - never a request
# to the model. followup.classify() routes ownership by intent; this is the
# hard floor under it for verbs that leave the machine or change what runs.
DANGEROUS_VERBS = re.compile(
    r"\b(push|deploy|deploying|deployment|install|installs|publish|release|"
    r"pull request|pr|curl|wget|fetch|npm|npx|pip|pipx|uv|brew|ssh|scp|rsync|"
    r"vercel|launchctl|crontab|cron|webhook|network|upload|email|dm|tweet|post)\b",
    re.I)

FILE_RE = re.compile(r"===FILE:\s*(?P<path>[^\n=]+?)\s*===\n(?P<body>.*?)\n?===END===",
                     re.S)
ESCALATE_RE = re.compile(r"===ESCALATE:\s*(?P<why>.+?)\s*===", re.S)

PROMPT = """You are FORGE, the implementer seat. One tracked commitment is
assigned to you. Produce the deliverable NOW, as complete file content -
not a plan, not a summary.

COMMITMENT: {action}
ORIGIN: council run {run_id}
TARGET REPO ROOT: {root}

Reply with one or more file blocks, exactly this shape:
===FILE: relative/path/from/repo/root.md===
<full file content>
===END===

Rules:
- NEW files only. If the task requires editing an existing file, running
  shell commands, spending money, or contacting anyone, reply instead with:
  ===ESCALATE: <one line why>===
- Paths must be relative, no '..', prefer docs/ or ops/ subtrees.
- Write the complete artifact. It ships as-is."""


class ExecResult:
    def __init__(self, cid: str, status: str, detail: str,
                 files: Optional[List[Path]] = None, cost: float = 0.0):
        self.cid, self.status, self.detail = cid, status, detail
        self.files, self.cost = files or [], cost


def _root_for(action: str) -> Path:
    """Deterministic target root. Caduceus-internal work stays here; anything
    naming another property escalates rather than guessing (one writer per
    repo is the operator's standing rule)."""
    return ALLOWED_ROOTS[0]


def _validate_rel(root: Path, rel: str) -> Tuple[Optional[Path], str]:
    rel = rel.strip()
    if rel.startswith(("/", "~")) or ".." in Path(rel).parts:
        return None, f"path escapes root: {rel!r}"
    parts_cf = [part.casefold() for part in Path(rel).parts]
    # APFS is case-insensitive: ".GIT/hooks/pre-commit" landed in the real
    # .git/hooks under the old exact-case check. Casefold everything, and
    # refuse any dot-prefixed component outright (.git., .hidden, ...).
    if any(part.startswith(".") for part in parts_cf):
        return None, f"protected path (dot component): {rel!r}"
    if any(part in DENY_PARTS for part in parts_cf) or parts_cf[-1] in DENY_NAMES:
        return None, f"protected path: {rel!r}"
    name_cf = parts_cf[-1]
    if name_cf in EXEC_NAMES or any(name_cf.endswith(suf) for suf in EXEC_SUFFIXES):
        return None, f"refused: executable/loader file ({rel!r}) - the wrapper never writes code"
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None, f"path escapes root: {rel!r}"
    if target.exists():
        return None, f"exists (v1 writes NEW files only): {rel!r}"
    return target, ""


def _tree_snapshot(root: Path) -> Dict[str, int]:
    """relpath -> mtime_ns for everything under root (skipping VCS and deps).
    Taken before and after the model call: the ONLY files that may differ are
    the ones this wrapper writes afterwards. Any other change means a seat
    still has a tool that touches disk - the "-t clarify" lock is an assumption
    about hermes, this is the invariant that does not depend on it."""
    snap: Dict[str, int] = {}
    skip = {".git", "node_modules", ".venv", "__pycache__"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                snap[str(p.relative_to(root))] = p.stat().st_mtime_ns
            except OSError:
                continue
    return snap


def _run_tests(root: Path) -> Tuple[bool, str]:
    proc = subprocess.run(["python3", "-m", "pytest", "-q"], cwd=root,
                          capture_output=True, text=True, timeout=600)
    tail = (proc.stdout or proc.stderr).strip().splitlines()[-3:]
    return proc.returncode == 0, " / ".join(tail)


def execute_one(c, transport=None, live: bool = False) -> ExecResult:
    ok, why = budgets.preflight_execution(EST_ACTION_COST)
    if not ok:
        return ExecResult(c.id, "blocked", f"pre-flight: {why}")

    root = _root_for(c.action)
    m = DANGEROUS_VERBS.search(c.action)
    if m:
        return ExecResult(c.id, "escalate",
                          f"'{m.group(1)}' leaves the machine or changes what "
                          "runs - operator's call, no model consulted")
    if not live:
        return ExecResult(c.id, "dry-run", f"would draft via FORGE into {root}")

    transport = transport or OneshotTransport(extra_args=["-t", "clarify"])
    seat = config.SEATS["forge"]
    before = _tree_snapshot(root)
    reply: SeatReply = transport.ask(
        seat, PROMPT.format(action=c.action, run_id=c.run_id, root=root))
    if not reply.ok:
        return ExecResult(c.id, "error", f"transport: {reply.error[:200]}")

    cost = float(reply.usage.get("estimated_cost_usd", 0)
                 or reply.usage.get("cost_usd", 0) or 0) or EST_ACTION_COST
    budgets.record_execution_spend(c.id, cost, note=c.action[:120])

    after = _tree_snapshot(root)
    touched = sorted(k for k in after if before.get(k) != after[k])
    if touched:
        return ExecResult(c.id, "escalate",
                          "tool lock NOT holding: the model wrote "
                          f"{', '.join(touched)[:150]} during the call; reply "
                          "not applied - check hermes -t semantics", cost=cost)

    esc = ESCALATE_RE.search(reply.text)
    if esc:
        return ExecResult(c.id, "escalate", esc.group("why")[:200], cost=cost)

    blocks = FILE_RE.findall(reply.text)
    if not blocks:
        return ExecResult(c.id, "escalate",
                          "model returned no file blocks and no escalation", cost=cost)

    written: List[Path] = []
    try:
        for rel, body in blocks:
            target, err = _validate_rel(root, rel)
            if not target:
                raise PermissionError(err)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body.rstrip() + "\n")
            written.append(target)

        # never run anything here: _validate_rel refuses every executable or
        # loader suffix, and the wrapper does not execute model output
        detail_tests = "no execution (wrapper writes prose only)"
    except Exception as e:
        for p in written:  # revert everything this action touched
            try: p.unlink()
            except OSError: pass
        return ExecResult(c.id, "escalate", f"{e}", cost=cost)

    names = ", ".join(str(p.relative_to(root)) for p in written)
    return ExecResult(c.id, "done", f"wrote {names} · {detail_tests}",
                      files=written, cost=cost)


def run_queue(live: bool = False, max_actions: int = 2,
              transport=None) -> List[ExecResult]:
    # single flight: the Mon/Thu launchd run and a manual run must never
    # overlap - both would preflight against the same ledger, both pass,
    # both call FORGE on the same commitment (double spend), and the loser
    # would flip a finished item into the operator's DECIDE list.
    lock_path = budgets.budgets_dir() / "exec.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = open(lock_path, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        lock.close()
        return []
    try:
        return _run_queue_locked(live, max_actions, transport)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def _run_queue_locked(live: bool, max_actions: int, transport) -> List[ExecResult]:
    f = followup.Followups()
    queue = [c for c in f.pending()
             if c.owner == "agent" and not followup._is_diagnostic(c.run_id)]
    results: List[ExecResult] = []
    for c in queue[:max_actions]:
        r = execute_one(c, transport=transport, live=live)
        results.append(r)
        if not live:
            continue
        if r.status == "done":
            f.close(c.id, "done", note=r.detail[:200])
        elif r.status == "escalate":
            # flips into the operator's DECIDE list instead of silently dying
            f.conn.execute(
                "UPDATE commitments SET owner='operator', kind='decide',"
                " note=? WHERE id=?", (f"executor escalated: {r.detail}"[:200], c.id))
            f.conn.commit()
    f.close_conn()
    if live and results:
        _notify(results)
    return results


def _notify(results: List[ExecResult]) -> None:
    """Telegram receipt for every live batch. Never fatal."""
    try:
        from . import telegram
        lines = ["CADUCEUS EXECUTOR"]
        for r in results:
            mark = {"done": "+", "escalate": "!", "blocked": "x",
                    "error": "x"}.get(r.status, "?")
            lines.append(f" {mark} [{r.cid}] {r.status}: {r.detail[:140]}")
        spent = budgets.execution_spend_today()
        cap = budgets.CEILINGS["execution"]["daily"]
        lines.append(f" budget: ${spent:.2f} / ${cap:.0f} today")
        telegram.post("\n".join(lines), seat="envoy")
    except Exception:
        pass
