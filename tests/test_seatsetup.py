"""seatsetup.py had zero coverage before the 2026-08-19 opus-4.6 incident -
exactly how a shared, inherited fallback_providers block went unnoticed
through `cad init` + `cad doctor` (both reported clean) until it 402'd
mid-council. These tests pin the fix: patch_profile_config must neutralize
whatever `hermes profile create --clone` copied in, every time, idempotently.
"""
from caduceus import seatsetup
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
