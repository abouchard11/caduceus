"""Seat provisioning: turns the seat definitions into real Hermes profiles.

Philosophy: configure Hermes, don't fork it. Every step is idempotent and
non-destructive - existing profiles are patched with timestamped backups,
never clobbered blind.
"""
from __future__ import annotations

import os
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


# ---------------------------------------------------------------- nested yaml
# The editor above swaps whole TOP-LEVEL blocks. Stripping tools needs the
# opposite: reach INSIDE `agent:`, `tools:` and `mcp_servers:` and change one
# child while every sibling key (max_turns, an MCP server's command/args) is
# preserved. Still line-based and comment-safe - we never round-trip YAML.
# Assumption: hermes writes nested mappings with a uniform indent (2 spaces);
# the actual indent is detected per block and reused when writing.

def _top_bounds(lines: List[str], key: str) -> Optional[Tuple[int, int]]:
    """(header index, end of body exclusive) for a top-level `key:` block."""
    for i, line in enumerate(lines):
        if re.match(rf"^{re.escape(key)}\s*:", line):
            j, last = i + 1, i + 1
            while j < len(lines):
                if not lines[j].strip():
                    j += 1
                    continue
                if lines[j].startswith((" ", "\t")):
                    j += 1
                    last = j
                    continue
                break
            return i, last
    return None


def _indent_of(line: str) -> str:
    return line[:len(line) - len(line.lstrip())]


def _body_indent(lines: List[str], start: int, end: int) -> str:
    for i in range(start, end):
        if lines[i].strip() and lines[i].startswith((" ", "\t")):
            return _indent_of(lines[i])
    return "  "


def _child_bounds(lines: List[str], start: int, end: int, child: str,
                  indent: str) -> Optional[Tuple[int, int]]:
    """Bounds of `<indent><child>:` and its deeper-indented body, in-block."""
    pat = re.compile(rf"^{indent}{re.escape(child)}\s*:")
    for i in range(start, end):
        if pat.match(lines[i]) and _indent_of(lines[i]) == indent:
            j, last = i + 1, i + 1
            while j < end:
                if not lines[j].strip():
                    j += 1
                    continue
                if len(_indent_of(lines[j])) > len(indent):
                    j += 1
                    last = j
                    continue
                break
            return i, last
    return None


def _reindent(template: List[str], indent: str) -> List[str]:
    """Retab lines written at the canonical 2-space depth to `indent`."""
    if indent == "  ":
        return list(template)
    out = []
    for line in template:
        depth = len(_indent_of(line)) // 2
        out.append(indent * depth + line.lstrip())
    return out


def child_keys(text: str, top_key: str) -> List[str]:
    """Direct child mapping keys of a top-level block, in file order."""
    lines = text.splitlines()
    bounds = _top_bounds(lines, top_key)
    if not bounds:
        return []
    header, end = bounds
    indent = _body_indent(lines, header + 1, end)
    pat = re.compile(rf"^{indent}([A-Za-z0-9_.\-]+)\s*:")
    out = []
    for i in range(header + 1, end):
        m = pat.match(lines[i])
        if m and _indent_of(lines[i]) == indent:
            out.append(m.group(1))
    return out


def list_items(text: str, top_key: str, child_key: str) -> List[str]:
    """Values of a `top_key: / child_key: / - item` list. [] when absent."""
    lines = text.splitlines()
    bounds = _top_bounds(lines, top_key)
    if not bounds:
        return []
    header, end = bounds
    indent = _body_indent(lines, header + 1, end)
    cb = _child_bounds(lines, header + 1, end, child_key, indent)
    if not cb:
        return []
    out = []
    for i in range(cb[0] + 1, cb[1]):
        s = lines[i].strip()
        if s.startswith("- "):
            out.append(s[2:].strip())
    return out


def set_child_block(text: str, top_key: str, child_key: str,
                    template: List[str]) -> str:
    """Replace-in-place (or append) one child block under a top-level key.
    `template` is the full child block written at 2-space indentation."""
    lines = text.splitlines()
    bounds = _top_bounds(lines, top_key)
    if not bounds:
        body = "\n".join(template)
        return text.rstrip("\n") + f"\n{top_key}:\n{body}\n"
    header, end = bounds
    indent = _body_indent(lines, header + 1, end)
    block = _reindent(template, indent)
    cb = _child_bounds(lines, header + 1, end, child_key, indent)
    if cb:
        out = lines[:cb[0]] + block + lines[cb[1]:]
    else:
        out = lines[:end] + block + lines[end:]
    return "\n".join(out) + "\n"


def set_scalar_in_child(text: str, top_key: str, child_key: str,
                        scalar_key: str, value: str) -> str:
    """Set `top_key: / child_key: / scalar_key: value`, creating the block or
    the child as needed and leaving every sibling key untouched."""
    lines = text.splitlines()
    bounds = _top_bounds(lines, top_key)
    if not bounds:
        return (text.rstrip("\n")
                + f"\n{top_key}:\n  {child_key}:\n    {scalar_key}: {value}\n")
    header, end = bounds
    indent = _body_indent(lines, header + 1, end)
    cb = _child_bounds(lines, header + 1, end, child_key, indent)
    if not cb:
        block = [f"{indent}{child_key}:", f"{indent * 2}{scalar_key}: {value}"]
        return "\n".join(lines[:end] + block + lines[end:]) + "\n"
    ci, cend = cb
    pat = re.compile(rf"^{indent * 2}{re.escape(scalar_key)}\s*:")
    for i in range(ci + 1, cend):
        if pat.match(lines[i]) and _indent_of(lines[i]) == indent * 2:
            lines[i] = f"{indent * 2}{scalar_key}: {value}"
            return "\n".join(lines) + "\n"
    out = lines[:cend] + [f"{indent * 2}{scalar_key}: {value}"] + lines[cend:]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- no-tools seats
# 2026-08-19: SPARRING (nousresearch/hermes-4-405b) 404'd every call - "No
# endpoints found that support tool use". No OpenRouter endpoint for any 405B
# Hermes takes the `tools` parameter, and Hermes attaches tool definitions to
# every request from three independent sources: the platform toolsets, the
# tool_search index, and each enabled MCP server. All three must be off or the
# 404 comes straight back - each failure only names the source still standing.
# This was hand-patched into the profile first; codified here so that a
# from-scratch `cad init` (or a profile deletion) cannot regress it.

CLI_TOOLSETS = [
    "bfl", "browser", "clarify", "code_execution", "computer_use", "cronjob",
    "delegation", "file", "image_gen", "kanban", "memory", "session_search",
    "skills", "terminal", "todo", "tts", "vision", "web", "x_search",
]


def no_tools_toolsets(text: str) -> List[str]:
    """Toolsets to disable: the known CLI set, unioned with whatever CLI
    toolsets this profile itself declares (Hermes ships new ones over time and
    a single missed toolset re-attaches tool definitions)."""
    declared = list_items(text, "platform_toolsets", "cli")
    return ["tool_search"] + sorted(set(CLI_TOOLSETS) | set(declared))


def apply_no_tools(text: str) -> str:
    """Strip every tool-definition source from a seat config. Idempotent."""
    template = ["  disabled_toolsets:"]
    template += [f"    - {name}" for name in no_tools_toolsets(text)]
    out = set_child_block(text, "agent", "disabled_toolsets", template)
    out = set_scalar_in_child(out, "tools", "tool_search", "enabled", '"off"')
    for server in child_keys(out, "mcp_servers"):
        out = set_scalar_in_child(out, "mcp_servers", server, "enabled", "false")
    return out


def scalar_in_top(text: str, top_key: str, scalar_key: str) -> Optional[str]:
    """Read `top_key: / scalar_key:` - one level, unlike scalar_in_child.
    Exists because a whole-file substring test is not a config check: the
    cast model can appear in an unrelated block (auxiliary.vision.model, a
    provider registry) while `model.default` says something else entirely.
    2026-08-26: that false [OK] hid forge sitting on a 401ing provider."""
    lines = text.splitlines()
    bounds = _top_bounds(lines, top_key)
    if not bounds:
        return None
    header, end = bounds
    indent = _body_indent(lines, header + 1, end)
    pat = re.compile(rf"^{indent}{re.escape(scalar_key)}\s*:\s*(.*)$")
    for i in range(header + 1, end):
        m = pat.match(lines[i])
        if m and _indent_of(lines[i]) == indent:
            return m.group(1).strip().strip('"').strip("'")
    return None


def scalar_in_child(text: str, top_key: str, child_key: str,
                    scalar_key: str) -> Optional[str]:
    """Read `top_key: / child_key: / scalar_key:`. None when any level is
    absent. Quotes are stripped - hermes writes `enabled: "off"` here but
    `enabled: false` under mcp_servers, and both must read the same way."""
    lines = text.splitlines()
    bounds = _top_bounds(lines, top_key)
    if not bounds:
        return None
    header, end = bounds
    indent = _body_indent(lines, header + 1, end)
    cb = _child_bounds(lines, header + 1, end, child_key, indent)
    if not cb:
        return None
    pat = re.compile(rf"^{indent * 2}{re.escape(scalar_key)}\s*:\s*(.*)$")
    for i in range(cb[0] + 1, cb[1]):
        m = pat.match(lines[i])
        if m and _indent_of(lines[i]) == indent * 2:
            return m.group(1).strip().strip('"').strip("'")
    return None


def tools_attached_sources(text: str) -> List[str]:
    """Which tool-definition sources are STILL live in a seat config - the
    inverse of apply_no_tools(). Empty list means fully stripped.

    Read this as the audit half of the 404 fix: apply_no_tools() writes the
    three blocks, this proves they are all still there. Any single survivor
    puts tool definitions back on the wire, so each source is reported
    separately and by name - the OpenRouter 404 only ever names one at a time.
    """
    live: List[str] = []

    disabled = set(list_items(text, "agent", "disabled_toolsets"))
    if not disabled:
        live.append("agent.disabled_toolsets absent")
    else:
        missing = [t for t in no_tools_toolsets(text) if t not in disabled]
        if missing:
            shown = ",".join(missing[:3])
            if len(missing) > 3:
                shown += f",+{len(missing) - 3} more"
            live.append(f"agent.disabled_toolsets missing {shown}")

    if (scalar_in_child(text, "tools", "tool_search", "enabled") or "").lower() != "off":
        live.append("tools.tool_search on")

    hot = [s for s in child_keys(text, "mcp_servers")
           if (scalar_in_child(text, "mcp_servers", s, "enabled")
               or "true").lower() != "false"]
    if hot:
        live.append("mcp_servers enabled: " + ",".join(hot))

    return live


def drop_child_block(text: str, top_key: str, child_key: str) -> str:
    """Delete one child block (header + body) under a top-level key. No-op
    when either level is absent. Sibling keys are untouched."""
    lines = text.splitlines()
    bounds = _top_bounds(lines, top_key)
    if not bounds:
        return text
    header, end = bounds
    indent = _body_indent(lines, header + 1, end)
    cb = _child_bounds(lines, header + 1, end, child_key, indent)
    if not cb:
        return text
    return "\n".join(lines[:cb[0]] + lines[cb[1]:]) + "\n"


def restore_tools(text: str) -> str:
    """Exact inverse of apply_no_tools(): put every tool-definition source
    back. Only ever called when the profile carries the FULL lockdown
    signature (tools_attached_sources() == []) on a tools-capable seat -
    i.e. when the strip is provably ours, left behind by a recast off a
    tools-incapable model. Partial, operator-authored restrictions never
    match the signature and are never touched.

    2026-08-26: sparring sat blind for days after its recast to
    google/gemini-3.7-flash because this function did not exist - the 0.3.2
    CHANGELOG promised the lift, the code only ever applied the strip.
    """
    out = drop_child_block(text, "agent", "disabled_toolsets")
    out = set_scalar_in_child(out, "tools", "tool_search", "enabled", '"on"')
    for server in child_keys(out, "mcp_servers"):
        out = set_scalar_in_child(out, "mcp_servers", server, "enabled", "true")
    return out


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
        if not seat.tools_capable:
            body = apply_no_tools(body)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(body)
        log.append(f"[+] wrote fresh config for '{seat.name}'")
        return
    text = cfg.read_text()
    new_text = replace_top_block(text, "model", model_block(seat))
    new_text = replace_top_block(new_text, "fallback_providers", fallback_block())
    if enable_api and not has_top_block(new_text, "platforms"):
        new_text += "\n" + api_server_block(seat, api_key)
    lifted = False
    if not seat.tools_capable:
        new_text = apply_no_tools(new_text)
    elif not tools_attached_sources(new_text):
        # the FULL lockdown signature on a tools-capable seat is OUR strip,
        # left behind by a recast off a tools-incapable model - lift it.
        # Anything short of the full signature is an operator's own toolset
        # restriction and survives `cad init` untouched.
        new_text = restore_tools(new_text)
        lifted = True
    if new_text != text:
        backup(cfg)
        cfg.write_text(new_text)
        log.append(f"[+] patched config for '{seat.name}' "
                   f"(model={seat.model} provider={seat.provider} port={seat.port})")
        if not seat.tools_capable:
            log.append(f"[+] tools stripped for '{seat.name}' - {seat.model} has "
                       "no tool-capable endpoint (toolsets, tool_search, mcp)")
        if lifted:
            log.append(f"[+] tools restored for '{seat.name}' - {seat.model} "
                       "takes tools; stale no-tools lockdown lifted "
                       "(toolsets, tool_search, mcp)")
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


# WHY these jobs carry a script and no prompt (2026-09-01):
#
# The old prompt-driven morning-brief cron had NEVER once written its
# deliverable. Its last run died on a 1040s idle timeout inside a subagent it
# spawned via delegate_task - a full-agent cron burning the operator's spend
# on subagents he never asked for, in a job whose entire purpose was to
# summarize things that were already sitting in the ledger and cron logs.
# The weekly job wasn't dying, either: it reported last_status=ok and had
# ALSO written nothing, because "ok" only meant the model finished a turn,
# not that it did the file edit it was told to do.
#
# `cad brief` is stdlib and writes the section itself - deterministic, cheap,
# and structurally incapable of an idle timeout. So the cron job is no
# longer a prompt at all: it is a shell script that shells out to `cad brief
# --write`, registered with --no-agent so hermes runs the script directly
# and never puts a model in the delivery path.
CRON_JOBS = [
    {
        "name": "caduceus-morning-brief",
        "schedule": "0 7 * * *",
        "script": "caduceus-morning-brief.sh",
        "argv": "brief --write",
    },
    {
        "name": "caduceus-weekly-ledger",
        "schedule": "0 8 * * 1",
        "script": "caduceus-weekly-ledger.sh",
        "argv": "brief --weekly --write",
    },
]


def install_cron(log: List[str]) -> None:
    cad = shutil.which("cad") or "cad"
    scripts_dir = config.hermes_home() / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for job in CRON_JOBS:
        script_path = scripts_dir / job["script"]
        script_path.write_text(
            "#!/bin/bash\n"
            "# caduceus: written by `cad init --cron`. The script IS the "
            "cron job (--no-agent).\n"
            f'exec "{cad}" {job["argv"]}\n'
        )
        os.chmod(script_path, 0o755)

        code, out = run_hermes([
            "cron", "create", job["schedule"],
            "--name", job["name"],
            "--script", job["script"],
            "--no-agent",
            "--deliver", "local",
        ])
        if code == 0:
            log.append(f"[+] cron '{job['name']}' registered ({script_path})")
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
    from .models import effective_seat  # late import: avoids cycle at load
    for name in names:
        # effective_seat, NOT SEATS[name]: `cad init` must never fight
        # `cad models set`. (2026-08-26: it did - a routine re-run reverted
        # every recast seat in the live profiles, putting forge back on a
        # provider that 401s and re-applying sparring's no-tools lockdown.)
        seat = effective_seat(name)
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
