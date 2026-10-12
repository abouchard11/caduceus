"""seatsetup.py had zero coverage before the 2026-08-19 opus-4.6 incident -
exactly how a shared, inherited fallback_providers block went unnoticed
through `cad init` + `cad doctor` (both reported clean) until it 402'd
mid-council. These tests pin the fix: patch_profile_config must neutralize
whatever `hermes profile create --clone` copied in, every time, idempotently.
"""
import os

from caduceus import config, seatsetup
from caduceus.config import SEATS

# Shape of what `hermes profile create --clone` actually produced: the
# root profile's fallback_providers block, copied verbatim into every seat.
CLONED_CONFIG = """model:
  default: claude-opus-4.6
  provider: anthropic
fallback_providers:
  - provider: openrouter
    model: anthropic/claude-opus-4.6
database:
  journal_mode: wal
runtime:
  nofile_soft_limit: 4096
"""


def _cfg_path(seat):
    from caduceus import config
    p = config.hermes_home() / "profiles" / seat.name / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def test_patch_neutralizes_inherited_fallback():
    seat = SEATS["forge"]
    cfg = _cfg_path(seat)
    cfg.write_text(CLONED_CONFIG)

    log = []
    seatsetup.patch_profile_config(seat, "test-key", log, enable_api=False)

    text = cfg.read_text()
    assert "fallback_providers: []" in text
    assert "anthropic/claude-opus-4.6" not in text
    assert f"default: {seat.model}" in text
    assert f"provider: {seat.provider}" in text
    # untouched sibling blocks survive
    assert "journal_mode: wal" in text


def test_patch_is_idempotent():
    seat = SEATS["forge"]
    cfg = _cfg_path(seat)
    cfg.write_text(CLONED_CONFIG)

    log1, log2 = [], []
    seatsetup.patch_profile_config(seat, "test-key", log1, enable_api=False)
    seatsetup.patch_profile_config(seat, "test-key", log2, enable_api=False)

    assert any("patched config" in line for line in log1)
    assert any("already correct" in line for line in log2)
    # second pass must not duplicate the block or reintroduce opus
    text = cfg.read_text()
    assert text.count("fallback_providers:") == 1
    assert "opus" not in text.lower()


def test_fresh_config_ships_neutralized_fallback():
    """No existing config.yaml (first-ever provision): the written-from-
    scratch branch must also set fallback_providers explicitly, not rely on
    the key being merely absent."""
    seat = SEATS["envoy"]
    cfg = _cfg_path(seat)
    assert not cfg.exists()

    log = []
    seatsetup.patch_profile_config(seat, "test-key", log, enable_api=False)

    text = cfg.read_text()
    assert "fallback_providers: []" in text
    assert f"default: {seat.model}" in text


def test_model_block_caps_max_tokens():
    seat = SEATS["sparring"]  # the 405B seat - the most expensive to leave uncapped
    block = seatsetup.model_block(seat)
    assert "max_tokens:" in block


def test_all_seats_patch_cleanly_from_a_shared_clone():
    """Every seat clones from the SAME root profile, so every seat inherits
    the SAME dangerous fallback target. Confirm the patch clears it for all
    five, not just the one seat exercised above."""
    for name, seat in SEATS.items():
        cfg = _cfg_path(seat)
        cfg.write_text(CLONED_CONFIG)
        log = []
        seatsetup.patch_profile_config(seat, "test-key", log, enable_api=False)
        text = cfg.read_text()
        assert "fallback_providers: []" in text, f"{name} still has a live fallback"
        assert "opus" not in text.lower(), f"{name} still references opus"


# ---------------------------------------------------------------- guard hook
# 2026-08-19 incident #2: install_guard_hook() unconditionally targeted root
# config.yaml (the operator's own daily-driver Hermes profile) alongside the
# seat profiles. The operator drives unguarded; only seats get the hook. The
# root hook was pulled by hand mid-session - the next `cad init --guard-write`
# must not silently reintroduce it.

def test_guard_hook_never_touches_root_config():
    from caduceus import config

    root_cfg = config.hermes_home() / "config.yaml"
    root_cfg.write_text("model:\n  default: claude-opus-4.6\n")

    log = []
    seatsetup.install_guard_hook(log, write=True, profiles=["forge", "finisher"])

    text = root_cfg.read_text()
    assert "cad guard hook" not in text
    assert "hooks:" not in text
    assert text == "model:\n  default: claude-opus-4.6\n"


def test_guard_hook_writes_only_to_named_seat_profiles():
    seat = SEATS["forge"]
    cfg = _cfg_path(seat)
    cfg.write_text("model:\n  default: qwen3.7-plus\n")

    log = []
    seatsetup.install_guard_hook(log, write=True, profiles=["forge"])

    text = cfg.read_text()
    assert "cad guard hook" in text
    assert any("forge" in line and "config.yaml" in line for line in log)
    assert not any("hermes_home" in line.lower() and "profiles" not in line
                   for line in log)


def test_guard_hook_write_with_no_profiles_touches_nothing():
    """write=True but no profiles given (e.g. `cad init` with zero seats
    provisioned this run) must be a no-op, never fall back to root."""
    from caduceus import config

    root_cfg = config.hermes_home() / "config.yaml"
    root_cfg.write_text("model:\n  default: claude-opus-4.6\n")

    log = []
    seatsetup.install_guard_hook(log, write=True, profiles=None)

    assert root_cfg.read_text() == "model:\n  default: claude-opus-4.6\n"


# ---------------------------------------------------------------- no-tools seats
# 2026-08-19 incident #3: SPARRING (nousresearch/hermes-4-405b) 404'd on every
# call - "No endpoints found that support tool use". NO OpenRouter endpoint for
# that model takes the `tools` parameter, and Hermes attaches tool definitions
# to every request. The fix (disable every toolset, tool_search, and the
# inherited MCP servers) was applied BY HAND to the profile, so a from-scratch
# `cad init` would have regressed the 404. These tests pin it into the code.

# Faithful shape of a freshly cloned seat profile: the dangerous blocks live
# next to sibling keys that must survive the patch.
CLONED_CONFIG_FULL = """model:
  default: claude-opus-4.6
  provider: anthropic
fallback_providers:
  - provider: openrouter
    model: anthropic/claude-opus-4.6
database:
  journal_mode: wal
agent:
  max_turns: 500
  verbose: false
  reasoning_effort: medium
  personalities: {}
terminal:
  backend: ssh
  timeout: 180
platform_toolsets:
  cli:
    - bfl
    - browser
    - terminal
    - web
  telegram:
    - hermes-telegram
mcp_servers:
  graphiti:
    command: /Users/sashalabbe/.local/bin/uv
    args:
      - run
      - --directory
      - /Users/sashalabbe/dev/graphiti/mcp_server
    enabled: true
  wisprflow:
    url: https://api.wisprflow.ai/connect/mcp
runtime:
  nofile_soft_limit: 4096
"""


def test_sparring_is_declared_tools_incapable():
    """SPARRING is the seat with no tool-capable endpoint. Every other seat
    runs a model that takes tool definitions normally."""
    assert SEATS["sparring"].tools_capable is False
    for name, seat in SEATS.items():
        if name != "sparring":
            assert seat.tools_capable is True, f"{name} should be tools-capable"


def test_declared_capability_matches_the_model_registry():
    """The per-seat flag and the model-level registry must not drift: a seat
    cast on a known tools-incapable model must be flagged, and vice versa."""
    from caduceus import config

    for name, seat in SEATS.items():
        assert seat.tools_capable is config.model_tools_capable(seat.model), (
            f"{name}: tools_capable={seat.tools_capable} but model "
            f"{seat.model} registry says {config.model_tools_capable(seat.model)}"
        )


def test_recast_recomputes_tools_capability():
    """`cad models set sparring <tool-capable-model>` must lift the lockdown
    flag - otherwise the seat stays lobotomized forever with no way back
    except hand-editing the profile."""
    from caduceus import models

    models.save_casting({"sparring": {"model": "qwen/qwen3.7-plus",
                                      "provider": "openrouter"}})
    assert models.effective_seat("sparring").tools_capable is True

    models.save_casting({"forge": {"model": "nousresearch/hermes-4-405b",
                                   "provider": "openrouter"}})
    assert models.effective_seat("forge").tools_capable is False


def test_patch_strips_tools_for_incapable_seat():
    seat = SEATS["sparring"]
    cfg = _cfg_path(seat)
    cfg.write_text(CLONED_CONFIG_FULL)

    log = []
    seatsetup.patch_profile_config(seat, "test-key", log, enable_api=False)
    text = cfg.read_text()

    # 1. every CLI toolset disabled, tool_search included
    assert "disabled_toolsets:" in text
    for toolset in ("tool_search", "terminal", "code_execution", "web",
                    "browser", "memory", "skills", "delegation"):
        assert f"    - {toolset}\n" in text, f"{toolset} not disabled"
    # 2. the tool_search switch itself
    assert 'enabled: "off"' in text
    # 3. inherited MCP servers off (they inject tool definitions too)
    assert text.count("enabled: false") == 2
    assert "enabled: true" not in text
    # sibling keys inside the patched blocks survive
    assert "max_turns: 500" in text
    assert "personalities: {}" in text
    assert "command: /Users/sashalabbe/.local/bin/uv" in text
    assert "url: https://api.wisprflow.ai/connect/mcp" in text
    assert "journal_mode: wal" in text
    assert "nofile_soft_limit: 4096" in text
    # and a backup was taken before mutating
    assert list(cfg.parent.glob("config.yaml.bak.caduceus-*"))


def test_patch_leaves_tools_alone_for_capable_seats():
    """Only the incapable seat gets the lockdown. FORGE must keep its tools -
    it is the implementer; a silent toolset strip would make it useless."""
    for name in ("forge", "finisher", "recon", "envoy"):
        seat = SEATS[name]
        cfg = _cfg_path(seat)
        cfg.write_text(CLONED_CONFIG_FULL)

        seatsetup.patch_profile_config(seat, "test-key", [], enable_api=False)
        text = cfg.read_text()

        assert "disabled_toolsets:" not in text, f"{name} lost its toolsets"
        assert 'enabled: "off"' not in text
        assert "enabled: false" not in text
        assert "enabled: true" in text     # graphiti untouched


def test_no_tools_patch_is_idempotent():
    seat = SEATS["sparring"]
    cfg = _cfg_path(seat)
    cfg.write_text(CLONED_CONFIG_FULL)

    log1, log2 = [], []
    seatsetup.patch_profile_config(seat, "test-key", log1, enable_api=False)
    first = cfg.read_text()
    seatsetup.patch_profile_config(seat, "test-key", log2, enable_api=False)
    second = cfg.read_text()

    assert any("patched config" in line for line in log1)
    assert any("already correct" in line for line in log2)
    assert first == second
    # no duplicated keys - duplicate YAML keys silently drop the earlier one
    assert first.count("disabled_toolsets:") == 1
    assert first.count("\nagent:") == 1
    assert first.count("\ntools:") == 1
    assert first.count("enabled: false") == 2


def test_fresh_config_for_incapable_seat_ships_locked_down():
    """First-ever provision (no config.yaml yet) must also ship the no-tools
    blocks - the 404 does not care which code path wrote the profile."""
    seat = SEATS["sparring"]
    cfg = _cfg_path(seat)
    assert not cfg.exists()

    seatsetup.patch_profile_config(seat, "test-key", [], enable_api=False)
    text = cfg.read_text()

    assert "    - terminal\n" in text
    assert "    - tool_search\n" in text
    assert 'enabled: "off"' in text
    assert f"default: {seat.model}" in text
    # nothing to disable, so no empty mcp_servers stub
    assert "mcp_servers:" not in text


def test_disabled_toolsets_covers_toolsets_the_profile_declares():
    """Hermes ships new toolsets over time. Any CLI toolset the profile itself
    declares must be disabled too, not just the ones hardcoded here - a single
    missed toolset re-attaches tool definitions and the 404 is back."""
    cfg_text = CLONED_CONFIG_FULL.replace("    - web\n", "    - web\n    - newfangled\n")
    seat = SEATS["sparring"]
    cfg = _cfg_path(seat)
    cfg.write_text(cfg_text)

    seatsetup.patch_profile_config(seat, "test-key", [], enable_api=False)
    text = cfg.read_text()

    # once in platform_toolsets (where it came from), once in disabled_toolsets
    assert text.count("    - newfangled\n") == 2
    # telegram-only toolsets are irrelevant to a CLI oneshot; don't touch them
    assert text.count("    - hermes-telegram\n") == 1


def test_patch_is_a_noop_on_the_hand_fixed_profile():
    """The 2026-08-19 hand fix is the reference implementation. Running the
    code against a profile already in that exact state must change nothing -
    if this fails, `cad init` and the operator disagree about the fix."""
    seat = SEATS["sparring"]
    cfg = _cfg_path(seat)
    hand_fixed = f"""model:
  default: {seat.model}
  provider: {seat.provider}
  max_tokens: 8192
fallback_providers: []
database:
  journal_mode: wal
agent:
  max_turns: 500
  disabled_toolsets:
    - tool_search
    - bfl
    - browser
    - clarify
    - code_execution
    - computer_use
    - cronjob
    - delegation
    - file
    - image_gen
    - kanban
    - memory
    - session_search
    - skills
    - terminal
    - todo
    - tts
    - vision
    - web
    - x_search
  verbose: false
  reasoning_effort: medium
  personalities: {{}}
platform_toolsets:
  cli:
    - bfl
    - browser
    - clarify
    - code_execution
    - computer_use
    - cronjob
    - delegation
    - file
    - image_gen
    - kanban
    - memory
    - session_search
    - skills
    - terminal
    - todo
    - tts
    - vision
    - web
    - x_search
mcp_servers:
  graphiti:
    url: http://127.0.0.1:8000/mcp
    enabled: false
  wisprflow:
    url: https://api.wisprflow.ai/connect/mcp
    enabled: false
tools:
  tool_search:
    enabled: "off"
"""
    cfg.write_text(hand_fixed)

    log = []
    seatsetup.patch_profile_config(seat, "test-key", log, enable_api=False)

    assert cfg.read_text() == hand_fixed
    assert any("already correct" in line for line in log)


# ------------------------------------------------------------- un-strip (0.3.3)
# 2026-08-26: sparring had been recast OFF hermes-4-405b onto a tool-capable
# model (google/gemini-3.7-flash) days earlier, yet its profile was still
# fully stripped - 20 disabled toolsets, tool_search off, both MCP servers
# dead. patch_profile_config() only ever ADDED the lockdown; nothing lifted
# it, so the 0.3.2 CHANGELOG's "cad models set lifts the lockdown" claim was
# false in the shipped code. The lockdown must come off exactly when the
# profile carries OUR full signature and the seat is tools-capable - and
# never touch an operator's own partial toolset restrictions.

def _capable_seat_ss():
    return next(s for s in SEATS.values() if s.tools_capable)


UNSTRIP_BASE = """model:
  default: {model}
  provider: {provider}
  max_tokens: 8192
fallback_providers: []
agent:
  max_turns: 500
  verbose: false
mcp_servers:
  graphiti:
    command: docker
    enabled: true
  wisprflow:
    command: npx
    enabled: true
"""


def test_restore_tools_is_the_inverse_of_apply_no_tools():
    seat = _capable_seat_ss()
    base = UNSTRIP_BASE.format(model=seat.model, provider=seat.provider)
    stripped = seatsetup.apply_no_tools(base)
    restored = seatsetup.restore_tools(stripped)

    assert seatsetup.list_items(restored, "agent", "disabled_toolsets") == []
    assert "disabled_toolsets" not in restored
    assert seatsetup.scalar_in_child(restored, "tools", "tool_search",
                                     "enabled") == "on"
    for server in ("graphiti", "wisprflow"):
        assert seatsetup.scalar_in_child(restored, "mcp_servers", server,
                                         "enabled") == "true"
    # siblings survive both directions
    assert "max_turns: 500" in restored
    assert "command: docker" in restored


def test_patch_profile_config_lifts_stale_lockdown_for_capable_seat():
    seat = _capable_seat_ss()
    pd = seatsetup.profile_dir(seat.name)
    pd.mkdir(parents=True, exist_ok=True)
    cfg = pd / "config.yaml"
    cfg.write_text(seatsetup.apply_no_tools(
        UNSTRIP_BASE.format(model=seat.model, provider=seat.provider)))

    log = []
    seatsetup.patch_profile_config(seat, "k" * 20, log, enable_api=False)

    text = cfg.read_text()
    assert seatsetup.tools_attached_sources(text)  # sources live again
    assert "disabled_toolsets" not in text
    assert seatsetup.scalar_in_child(text, "mcp_servers", "graphiti",
                                     "enabled") == "true"
    assert any("restored" in l for l in log)


def test_patch_profile_config_leaves_partial_restrictions_alone():
    """An operator's own toolset choices are NOT our lockdown signature -
    a partial strip must survive `cad init` byte-for-byte in those blocks."""
    seat = _capable_seat_ss()
    pd = seatsetup.profile_dir(seat.name)
    pd.mkdir(parents=True, exist_ok=True)
    cfg = pd / "config.yaml"
    custom = (UNSTRIP_BASE.format(model=seat.model, provider=seat.provider)
              + "  disabled_toolsets:\n    - terminal\n")
    # move the custom list under agent: properly
    custom = seatsetup.set_child_block(
        UNSTRIP_BASE.format(model=seat.model, provider=seat.provider),
        "agent", "disabled_toolsets",
        ["  disabled_toolsets:", "    - terminal"])
    custom = seatsetup.set_scalar_in_child(
        custom, "mcp_servers", "wisprflow", "enabled", "false")
    cfg.write_text(custom)

    log = []
    seatsetup.patch_profile_config(seat, "k" * 20, log, enable_api=False)

    text = cfg.read_text()
    assert seatsetup.list_items(text, "agent", "disabled_toolsets") == ["terminal"]
    assert seatsetup.scalar_in_child(text, "mcp_servers", "wisprflow",
                                     "enabled") == "false"
    assert not any("restored" in l for l in log)


# --------------------------------------------------- init honors casting (0.3.3)
# 2026-08-26 regression, caused live: `cad init` iterated SEATS (the SHIPPED
# defaults) instead of effective_seat(), so a routine re-run silently reverted
# every recast seat in the live Hermes profiles - forge back onto the
# alibaba-coding-plan provider that 401s, finisher off a just-made recast, and
# sparring back onto hermes-4-405b complete with a re-applied no-tools
# lockdown. casting.json survived; only the profiles were clobbered. `cad
# init` must never fight `cad models set`.

def test_init_writes_the_cast_model_not_the_shipped_default(monkeypatch):
    from caduceus import models
    seat_name = "forge"
    shipped = SEATS[seat_name]
    # pre-create every profile dir so init() never shells out to hermes
    for n in SEATS:
        seatsetup.profile_dir(n).mkdir(parents=True, exist_ok=True)
    models.save_casting({seat_name: {
        "model": "anthropic/claude-sonnet-4.6", "provider": "openrouter",
        "family": "anthropic",
    }})

    seatsetup.init(seat_names=[seat_name])

    text = (seatsetup.profile_dir(seat_name) / "config.yaml").read_text()
    assert seatsetup.scalar_in_top(text, "model", "default") == \
        "anthropic/claude-sonnet-4.6"
    assert seatsetup.scalar_in_top(text, "model", "provider") == "openrouter"
    assert shipped.model != "anthropic/claude-sonnet-4.6"  # guard the fixture


def test_init_leaves_uncast_seats_on_their_shipped_default(monkeypatch):
    for n in SEATS:
        seatsetup.profile_dir(n).mkdir(parents=True, exist_ok=True)
    from caduceus import models
    models.save_casting({})

    seatsetup.init(seat_names=["recon"])

    text = (seatsetup.profile_dir("recon") / "config.yaml").read_text()
    assert seatsetup.scalar_in_top(text, "model", "default") == SEATS["recon"].model


# ------------------------------------------------- no-agent brief cron (0.3.4)
# The brief cron must not have a model in its delivery path: hermes runs the
# script AS the job (--script + --no-agent) and delivers stdout verbatim.

def test_install_cron_registers_no_agent_script_jobs(monkeypatch):
    calls = []

    def fake_run(args, timeout=60):
        calls.append(args)
        return 0, "created"

    monkeypatch.setattr(seatsetup, "run_hermes", fake_run)
    log = []
    seatsetup.install_cron(log)

    names = {a[a.index("--name") + 1] for a in calls}
    assert {"caduceus-morning-brief", "caduceus-weekly-ledger"} <= names
    for a in calls:
        assert "--no-agent" in a and "--script" in a
        assert not any("Run the caduceus-council" in x for x in a)  # no prompt
    scripts = config.hermes_home() / "scripts"
    morning = scripts / "caduceus-morning-brief.sh"
    weekly = scripts / "caduceus-weekly-ledger.sh"
    assert morning.exists() and weekly.exists()
    assert "brief --write" in morning.read_text()
    assert "brief --weekly --write" in weekly.read_text()
    assert os.access(morning, os.X_OK)


# ---- review fix 2026-10-10: cad init pushes a regenerated USER.md -----------

def test_install_user_md_overwrites_changed_content(tmp_path, monkeypatch):
    from pathlib import Path
    repo = tmp_path / "repo"
    (repo / "seats").mkdir(parents=True)
    (repo / "seats" / "USER.md").write_text("# CADUCEUS PRINCIPAL PROFILE — new\n")
    monkeypatch.setenv("CADUCEUS_REPO", str(repo))
    seat = SEATS["finisher"]
    pd = config.hermes_home() / "profiles" / seat.name
    pd.mkdir(parents=True)
    (pd / "USER.md").write_text("# CADUCEUS PRINCIPAL PROFILE — old\n")
    log = []
    seatsetup.install_user_md(seat, log)
    assert (pd / "USER.md").read_text() == "# CADUCEUS PRINCIPAL PROFILE — new\n"
    assert any(p.name.startswith("USER.md.bak.caduceus-") for p in pd.iterdir())
    assert any("updated" in l for l in log)
    log2 = []
    seatsetup.install_user_md(seat, log2)
    assert any("current" in l for l in log2)


# ------------------------------------- provisioning stops on a create timeout
# 2026-10-11, caused live: a guest cast was provisioned while hermes had to
# rebuild its Python environment at launch (the first cloned seat changed the
# plugin set). The rebuild ran 68-85s. `hermes profile create` was killed at
# the 60s default, init() moved on to the next seat, and each next create
# started the same rebuild from zero: three timeouts, 29 orphaned hermes
# environments, no profiles. A create that runs out of time means hermes is
# busy with something the next create would only restart, so init() stops.

def _fake_hermes(monkeypatch, result):
    calls = []

    def fake_run(args, timeout=60):
        calls.append((list(args), timeout))
        return result(args)

    monkeypatch.setattr(seatsetup, "hermes_bin", lambda: "/usr/bin/true")
    monkeypatch.setattr(seatsetup, "run_hermes", fake_run)
    return calls


def _creates(calls):
    return [a[2] for a, _ in calls if a[:2] == ["profile", "create"]]


def test_profile_create_gets_the_long_timeout(monkeypatch):
    calls = _fake_hermes(monkeypatch, lambda args: (0, ""))
    assert seatsetup.create_profile(SEATS["forge"], [])
    assert calls[0][1] == seatsetup.CREATE_TIMEOUT
    assert seatsetup.CREATE_TIMEOUT >= 240


def test_run_hermes_reports_a_timeout_as_timeout_exit(monkeypatch):
    import subprocess

    def expire(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(seatsetup, "hermes_bin", lambda: "/usr/bin/true")
    monkeypatch.setattr(seatsetup.subprocess, "run", expire)
    code, out = seatsetup.run_hermes(["profile", "list"], timeout=1)
    assert code == seatsetup.TIMEOUT_EXIT and "timeout" in out


def test_init_stops_at_a_create_timeout_instead_of_trying_the_next_seat(monkeypatch):
    calls = _fake_hermes(monkeypatch, lambda args: (seatsetup.TIMEOUT_EXIT, "timeout running hermes"))
    log = seatsetup.init(seat_names=["forge", "recon", "envoy"])
    assert _creates(calls) == ["forge"]
    assert seatsetup.stopped(log)
    stop = next(l for l in log if l.startswith(seatsetup.STOPPED))
    assert "forge" in stop and "recon" in stop and "envoy" in stop
    assert not any(l.startswith("Seats provisioned") for l in log)


def test_init_keeps_the_seats_finished_before_the_timeout(monkeypatch):
    def result(args):
        if args[:2] == ["profile", "create"] and args[2] == "forge":
            seatsetup.profile_dir("forge").mkdir(parents=True, exist_ok=True)
            return (0, "")
        return (seatsetup.TIMEOUT_EXIT, "timeout running hermes")

    calls = _fake_hermes(monkeypatch, result)
    log = seatsetup.init(seat_names=["forge", "recon", "envoy"])
    assert _creates(calls) == ["forge", "recon"]
    assert (seatsetup.profile_dir("forge") / "config.yaml").exists()
    stop = next(l for l in log if l.startswith(seatsetup.STOPPED))
    assert "recon" in stop and "envoy" in stop and "forge" not in stop


def test_a_create_that_times_out_after_making_the_profile_still_counts(monkeypatch):
    def result(args):
        if args[:2] == ["profile", "create"]:
            seatsetup.profile_dir(args[2]).mkdir(parents=True, exist_ok=True)
        return (seatsetup.TIMEOUT_EXIT, "timeout running hermes")

    calls = _fake_hermes(monkeypatch, result)
    log = seatsetup.init(seat_names=["forge", "recon"])
    assert _creates(calls) == ["forge", "recon"]
    assert not seatsetup.stopped(log)


def test_a_plain_create_failure_still_moves_to_the_next_seat(monkeypatch):
    calls = _fake_hermes(monkeypatch, lambda args: (1, "boom"))
    log = seatsetup.init(seat_names=["forge", "recon"])
    assert _creates(calls) == ["forge", "recon"]
    assert not seatsetup.stopped(log)
    assert any("profile create 'forge' failed" in l for l in log)


def test_cad_init_exits_nonzero_when_provisioning_stopped(monkeypatch, capsys):
    import pytest
    from caduceus import cli
    _fake_hermes(monkeypatch, lambda args: (seatsetup.TIMEOUT_EXIT, "timeout running hermes"))
    with pytest.raises(SystemExit) as stop:
        cli.main(["init", "--seats", "forge,recon"])
    assert stop.value.code == 1
    assert seatsetup.STOPPED in capsys.readouterr().out
