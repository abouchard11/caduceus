"""cad doctor's guard-hook row was checking the wrong place (root config.yaml)
even after seatsetup.install_guard_hook() was fixed to only patch seat
profiles. Left alone, doctor would forever WARN "not in root config.yaml"
on a correctly-guarded install, and would stay silent if the hook ever
regressed back into the operator's own root profile - exactly the
2026-08-19 incident this file exists to prevent a repeat of.
"""
from caduceus import config, doctor
from caduceus.config import SEATS
from caduceus.seatsetup import profile_dir


def _row(rows, name):
    for status, label, detail in rows:
        if label == name:
            return status, detail
    return None


def _make_all_seat_profiles():
    for name in SEATS:
        pd = profile_dir(name)
        pd.mkdir(parents=True, exist_ok=True)
        (pd / "SOUL.md").write_text("CADUCEUS SEAT\n")


def test_guard_hook_ok_when_all_seats_guarded_and_root_clean():
    _make_all_seat_profiles()
    for name in SEATS:
        cfg = profile_dir(name) / "config.yaml"
        cfg.write_text("model:\n  default: x\n\nhooks:\n  # cad guard hook\n")
    config.hermes_home().mkdir(parents=True, exist_ok=True)
    (config.hermes_home() / "config.yaml").write_text("model:\n  default: claude-opus-4.6\n")

    rows = doctor.checks()

    status, detail = _row(rows, "guard hook")
    assert status == doctor.OK
    assert "seat profile" in detail
    assert _row(rows, "guard hook (root)") is None


def test_guard_hook_warns_when_some_seats_unguarded():
    _make_all_seat_profiles()
    names = list(SEATS)
    for name in names[:2]:
        (profile_dir(name) / "config.yaml").write_text("hooks:\n  # cad guard hook\n")
    for name in names[2:]:
        (profile_dir(name) / "config.yaml").write_text("model:\n  default: x\n")

    rows = doctor.checks()

    status, detail = _row(rows, "guard hook")
    assert status == doctor.WARN
    assert names[0] in detail and names[-1] in detail


def test_guard_hook_fails_if_root_config_is_hooked():
    """The operator drives unguarded - a hook in root config.yaml is a
    regression of the exact 2026-08-19 incident, not a healthy state."""
    _make_all_seat_profiles()
    for name in SEATS:
        (profile_dir(name) / "config.yaml").write_text("hooks:\n  # cad guard hook\n")
    config.hermes_home().mkdir(parents=True, exist_ok=True)
    (config.hermes_home() / "config.yaml").write_text(
        "model:\n  default: claude-opus-4.6\n\nhooks:\n  # cad guard hook\n"
    )

    rows = doctor.checks()

    status, detail = _row(rows, "guard hook (root)")
    assert status == doctor.FAIL
    assert "unguarded" in detail


# --------------------------------------------------------------- tools stripping
# 2026-08-19: SPARRING (nousresearch/hermes-4-405b) 404'd every single call -
# "No endpoints found that support tool use" - because Hermes attaches tool
# definitions from three independent sources. v0.3.2 taught `cad init` to
# strip all three for a tools-incapable seat; these tests exist because
# nothing was watching whether the strip STAYED applied. A hand edit, a
# `hermes` upgrade rewriting the profile, or a newly shipped CLI toolset
# silently re-arms the 404 - and both init and doctor used to report clean.

import re

from caduceus import seatsetup


def _incapable_seat():
    return next(s for s in SEATS.values() if not s.tools_capable)


def _capable_seat():
    return next(s for s in SEATS.values() if s.tools_capable)


BASE_CFG = """model:
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


def _write_seat(seat, text):
    """Give one seat a full, otherwise-healthy profile (soul + key + config)."""
    pd = profile_dir(seat.name)
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "SOUL.md").write_text("CADUCEUS SEAT\n")
    (pd / ".env").write_text("OPENROUTER_API_KEY=sk-test\n")
    (pd / "config.yaml").write_text(text)


def _stripped_cfg(seat):
    """Exactly what `cad init` writes for a tools-incapable seat. Pinning the
    doctor check against the real writer means writer/verifier drift fails."""
    return seatsetup.apply_no_tools(
        BASE_CFG.format(model=seat.model, provider=seat.provider))


def test_tools_incapable_seat_reports_stripped_when_all_three_sources_off():
    _make_all_seat_profiles()
    seat = _incapable_seat()
    _write_seat(seat, _stripped_cfg(seat))

    status, detail = _row(doctor.checks(), f"seat:{seat.name}")

    assert status == doctor.OK
    assert "tools-stripped" in detail
    assert "TOOLS-ATTACHED" not in detail


def test_tools_attached_when_disabled_toolsets_block_is_gone():
    """Regression shape 1: the whole `agent.disabled_toolsets` block dropped
    (a `hermes` upgrade rewriting the profile does exactly this)."""
    _make_all_seat_profiles()
    seat = _incapable_seat()
    broken = re.sub(r"\n  disabled_toolsets:(?:\n    - .*)*",
                    "", _stripped_cfg(seat))
    assert "disabled_toolsets" not in broken
    _write_seat(seat, broken)

    status, detail = _row(doctor.checks(), f"seat:{seat.name}")

    assert status == doctor.FAIL
    assert "TOOLS-ATTACHED" in detail
    assert "disabled_toolsets" in detail
    assert "cad init" in detail


def test_tools_attached_when_a_single_toolset_is_missing_from_the_list():
    """Regression shape 1b: the block survives but one toolset is absent -
    a newly shipped CLI toolset, or a hand edit trimming the list. One live
    toolset is enough to re-arm the 404."""
    _make_all_seat_profiles()
    seat = _incapable_seat()
    broken = _stripped_cfg(seat).replace("    - terminal\n", "")
    _write_seat(seat, broken)

    status, detail = _row(doctor.checks(), f"seat:{seat.name}")

    assert status == doctor.FAIL
    assert "TOOLS-ATTACHED" in detail
    assert "terminal" in detail
    assert "cad init" in detail


def test_tools_attached_when_tool_search_is_re_enabled():
    """Regression shape 2: `tools.tool_search.enabled` flipped back on."""
    _make_all_seat_profiles()
    seat = _incapable_seat()
    broken = seatsetup.set_scalar_in_child(
        _stripped_cfg(seat), "tools", "tool_search", "enabled", '"on"')
    _write_seat(seat, broken)

    status, detail = _row(doctor.checks(), f"seat:{seat.name}")

    assert status == doctor.FAIL
    assert "TOOLS-ATTACHED" in detail
    assert "tool_search" in detail
    assert "cad init" in detail


def test_tools_attached_when_one_mcp_server_is_re_enabled():
    """Regression shape 3: a single MCP server flipped back to enabled: true.
    The other server staying off must not mask it."""
    _make_all_seat_profiles()
    seat = _incapable_seat()
    broken = seatsetup.set_scalar_in_child(
        _stripped_cfg(seat), "mcp_servers", "graphiti", "enabled", "true")
    _write_seat(seat, broken)

    status, detail = _row(doctor.checks(), f"seat:{seat.name}")

    assert status == doctor.FAIL
    assert "TOOLS-ATTACHED" in detail
    assert "graphiti" in detail
    assert "wisprflow" not in detail
    assert "cad init" in detail


def test_tools_capable_seat_is_not_checked_at_all():
    """A tools-capable seat keeps its tools on purpose: it must never be
    reported either way, however its toolsets are configured."""
    _make_all_seat_profiles()
    seat = _capable_seat()
    _write_seat(seat, BASE_CFG.format(model=seat.model, provider=seat.provider))

    status, detail = _row(doctor.checks(), f"seat:{seat.name}")

    assert "tools-stripped" not in detail
    assert "TOOLS-ATTACHED" not in detail
    assert status != doctor.FAIL


def test_tools_capable_seat_warns_when_lockdown_is_stale():
    """The inverse regression (found live 2026-08-26): a seat recast from a
    tools-incapable model onto a capable one, with the full lockdown still
    sitting in its profile. The seat runs but is blind. WARN, name the fix."""
    _make_all_seat_profiles()
    seat = _capable_seat()
    _write_seat(seat, seatsetup.apply_no_tools(
        BASE_CFG.format(model=seat.model, provider=seat.provider)))

    status, detail = _row(doctor.checks(), f"seat:{seat.name}")

    assert status == doctor.WARN
    assert "TOOLS-STRIPPED-STALE" in detail
    assert "cad init" in detail


def test_seat_model_row_reads_model_default_not_any_substring():
    """2026-08-26: forge's live config had `model.default: qwen3.7-plus` on
    the alibaba provider that 401s, while the cast model `qwen/qwen3.7-plus`
    appeared incidentally in an unrelated block further down the file. The
    whole-file substring check reported [OK]. It must read model.default."""
    _make_all_seat_profiles()
    seat = _capable_seat()
    _write_seat(seat, (
        "model:\n"
        "  default: some-other-model\n"
        f"  provider: {seat.provider}\n"
        "auxiliary:\n"
        "  vision:\n"
        f"    model: {seat.model}\n"   # incidental mention, NOT the seat model
    ))

    status, detail = _row(doctor.checks(), f"seat:{seat.name}")

    assert "MODEL-NOT-SET" in detail
    assert status == doctor.WARN


def test_seat_model_row_flags_a_wrong_provider():
    """Right model, wrong provider is how forge sat on a 401ing endpoint."""
    _make_all_seat_profiles()
    seat = _capable_seat()
    wrong = "not-" + seat.provider
    _write_seat(seat, (
        "model:\n"
        f"  default: {seat.model}\n"
        f"  provider: {wrong}\n"
    ))

    status, detail = _row(doctor.checks(), f"seat:{seat.name}")

    assert "PROVIDER" in detail and wrong in detail
    assert seat.provider in detail  # names what it wants, per the FAIL-names-fix rule
    assert status == doctor.WARN
