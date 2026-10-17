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


# ----------------------------------------------------------- cron health (0.3.3)
# 2026-08-26: the morning brief had silently failed for SEVEN consecutive
# days (hermes drift_skip: global model config changed after job creation)
# while doctor reported cron [OK] because it only counted registered jobs.
# The operator asked "how come I didn't have alerts about them?" - because
# the alerting layer was dead and the health check that should have said so
# was a job-count. Same silent-failure class as everything else in 0.3.3.

import json as _json


def _write_cron_jobs(jobs):
    p = config.hermes_home() / "cron"
    p.mkdir(parents=True, exist_ok=True)
    (p / "jobs.json").write_text(_json.dumps(jobs))


def test_cron_fails_loud_when_a_caduceus_job_is_dead():
    _make_all_seat_profiles()
    _write_cron_jobs([
        {"name": "caduceus-morning-brief", "enabled": True,
         "last_status": "error", "failure_streak": 7,
         "last_error": "RuntimeError: [drift_skip:silent] Skipped to prevent "
                       "unintended spend: global inference config drifted"},
        {"name": "caduceus-weekly-ledger", "enabled": True,
         "last_status": "ok", "failure_streak": 0},
    ])

    status, detail = _row(doctor.checks(), "cron")

    assert status == doctor.FAIL
    assert "caduceus-morning-brief" in detail
    assert "7" in detail
    assert "drift_skip" in detail
    assert "cad init --cron" in detail  # the fix, named


def test_cron_warns_on_a_single_failure():
    _make_all_seat_profiles()
    _write_cron_jobs([
        {"name": "caduceus-morning-brief", "enabled": True,
         "last_status": "error", "failure_streak": 1,
         "last_error": "timeout"},
        {"name": "caduceus-weekly-ledger", "enabled": True,
         "last_status": "ok", "failure_streak": 0},
    ])

    status, detail = _row(doctor.checks(), "cron")

    assert status == doctor.WARN
    assert "caduceus-morning-brief" in detail


def test_cron_ok_when_jobs_are_healthy():
    _make_all_seat_profiles()
    _write_cron_jobs([
        {"name": "caduceus-morning-brief", "enabled": True,
         "last_status": "ok", "failure_streak": 0},
        {"name": "caduceus-weekly-ledger", "enabled": True,
         "last_status": "ok", "failure_streak": 0},
    ])

    status, detail = _row(doctor.checks(), "cron")

    assert status == doctor.OK


# ------------------------------------------------------ brief delivery (0.3.4)
# 2026-09-01: the cron-health row above was itself a false green - the weekly
# job said last_status=ok and had written nothing. Delivery is the artifact:
# doctor reads the dated section in the operator's pending-actions file.

from caduceus import brief as _brief


def _pending_file(monkeypatch, tmp_path, text=None):
    p = tmp_path / "PENDING.md"
    monkeypatch.setenv(_brief.PENDING_ENV, str(p))
    if text is not None:
        p.write_text(text)
    return p


def test_brief_delivery_fails_when_never_written(monkeypatch, tmp_path):
    _make_all_seat_profiles()
    _pending_file(monkeypatch, tmp_path, "# pending\n\n## 1. thing\n")

    status, detail = _row(doctor.checks(), "brief delivery")

    assert status == doctor.FAIL
    assert "never" in detail
    assert "cad brief --write" in detail


def test_brief_delivery_fails_when_stale(monkeypatch, tmp_path):
    _make_all_seat_profiles()
    _pending_file(monkeypatch, tmp_path,
                  "# pending\n\n## Caduceus morning brief (2026-08-20)\n\nold\n")

    status, detail = _row(doctor.checks(), "brief delivery")

    assert status == doctor.FAIL
    assert "2026-08-20" in detail
    assert "cad brief --write" in detail


def test_brief_delivery_ok_when_fresh(monkeypatch, tmp_path):
    _make_all_seat_profiles()
    import datetime as dt
    today = dt.date.today().isoformat()
    _pending_file(monkeypatch, tmp_path,
                  f"# pending\n\n## Caduceus morning brief ({today})\n\nfresh\n")

    status, detail = _row(doctor.checks(), "brief delivery")

    assert status == doctor.OK
    assert today in detail


# ------------------------------------------------------- launchd health (0.3.6)
# 2026-09-02: dev.midnightdev.caduceus.exec and .nudge (launchd, Mon/Thu) had
# both fired and died with "cad: error: invalid choice: 'exec'" - the editable
# install was on a checkout that predated the subcommand. The failure sat in
# /tmp/caduceus-*.err and nobody looked. doctor watched hermes cron (0.3.3)
# but not launchd, so the seat-work executor was dead and doctor said nothing.

import plistlib


def _launchd_dir(monkeypatch, tmp_path):
    d = tmp_path / "LaunchAgents"
    d.mkdir()
    monkeypatch.setenv("CADUCEUS_LAUNCHD_DIR", str(d))
    return d


def _plist(d, label, err_path, out_path=None):
    p = d / f"{label}.plist"
    job = {"Label": label,
           "ProgramArguments": ["/bin/zsh", "-lc", "cad exec run --live"],
           "StandardErrorPath": str(err_path),
           "StartCalendarInterval": [{"Hour": 8, "Minute": 45, "Weekday": 1}]}
    if out_path is not None:
        job["StandardOutPath"] = str(out_path)
    with open(p, "wb") as f:
        plistlib.dump(job, f)
    return p


def test_launchd_warns_when_a_caduceus_job_last_died(monkeypatch, tmp_path):
    _make_all_seat_profiles()
    d = _launchd_dir(monkeypatch, tmp_path)
    err = tmp_path / "caduceus-exec.err"
    err.write_text("usage: cad [-h]\ncad: error: argument cmd: invalid choice: 'exec'\n")
    _plist(d, "dev.midnightdev.caduceus.exec", err)

    status, detail = _row(doctor.checks(), "launchd")

    assert status == doctor.WARN
    assert "caduceus.exec" in detail
    assert "invalid choice: 'exec'" in detail
    assert "main" in detail            # the fix: the editable install must be on main


def test_launchd_ok_when_err_logs_are_clean(monkeypatch, tmp_path):
    _make_all_seat_profiles()
    d = _launchd_dir(monkeypatch, tmp_path)
    err = tmp_path / "caduceus-exec.err"
    err.write_text("")
    _plist(d, "dev.midnightdev.caduceus.exec", err)

    status, detail = _row(doctor.checks(), "launchd")

    assert status == doctor.OK
    assert "1 caduceus job" in detail


def test_launchd_warns_on_the_exec_failed_summary_in_stderr(monkeypatch, tmp_path):
    _make_all_seat_profiles()
    d = _launchd_dir(monkeypatch, tmp_path)
    err = tmp_path / "caduceus-exec.err"
    err.write_text("FAILED: executor transport unavailable - hermes binary not found (hermes); "
                   "2 of 2 selected item(s) failed at the transport\n")
    _plist(d, "dev.midnightdev.caduceus.exec", err)

    status, detail = _row(doctor.checks(), "launchd")

    assert status == doctor.WARN
    assert "transport unavailable" in detail
    assert "scheduler path" in detail   # the PATH hint, not the editable-install hint


def test_launchd_warns_on_a_failed_summary_in_stdout(monkeypatch, tmp_path):
    _make_all_seat_profiles()
    d = _launchd_dir(monkeypatch, tmp_path)
    err = tmp_path / "caduceus-nudge.err"
    err.write_text("")
    out = tmp_path / "caduceus-nudge.log"
    out.write_text("FAILED: hermes not on PATH\n")
    _plist(d, "dev.midnightdev.caduceus.nudge", err, out)

    status, detail = _row(doctor.checks(), "launchd")

    assert status == doctor.WARN
    assert "hermes not on PATH" in detail
    assert "scheduler path" in detail


def test_launchd_ignores_the_word_error_inside_a_stdout_item_line(monkeypatch, tmp_path):
    _make_all_seat_profiles()
    d = _launchd_dir(monkeypatch, tmp_path)
    err = tmp_path / "caduceus-exec.err"
    err.write_text("")
    out = tmp_path / "caduceus-exec.log"
    out.write_text("  [abc123] done: wrote notes on the error budget\n")
    _plist(d, "dev.midnightdev.caduceus.exec", err, out)

    status, _ = _row(doctor.checks(), "launchd")

    assert status == doctor.OK


def test_launchd_row_absent_when_no_jobs_installed(monkeypatch, tmp_path):
    _make_all_seat_profiles()
    _launchd_dir(monkeypatch, tmp_path)

    assert _row(doctor.checks(), "launchd") is None


# --------------------------------------------- brief staleness window (0.3.7)
# 2026-09-02 06:44: doctor FAILed "morning brief stale: last dated 2026-09-01
# (31h ago)" on a completely healthy engine - scheduler alive, last_status ok,
# next run 07:00, 16 minutes away. The heading carries a DATE only, so age is
# measured from 00:00 of that date; with a 07:00 daily cron the maximum HEALTHY
# age is 31h (written 07:00 day N, checked 06:59 day N+1). The 30h threshold
# therefore cried wolf every morning between 06:00 and 07:00. A check that
# false-alarms daily is a check the operator learns to ignore - which is how
# the silent failure it exists to catch gets through.

def test_brief_delivery_ok_in_the_hour_before_the_cron_fires(monkeypatch, tmp_path):
    """The 06:00-07:00 window on a healthy engine: yesterday's brief, next run
    imminent. 31h old and CORRECT."""
    _make_all_seat_profiles()
    _pending_file(monkeypatch, tmp_path,
                  "# pending\n\n## Caduceus morning brief (2026-09-01)\n\nbody\n")
    monkeypatch.setattr(_brief, "age_hours",
                        lambda *a, **k: 31.0)

    status, detail = _row(doctor.checks(), "brief delivery")

    assert status == doctor.OK, detail


def test_brief_delivery_fails_when_a_scheduled_run_was_actually_missed(monkeypatch, tmp_path):
    """One missed 07:00 run puts the brief at >=55h. That must still FAIL -
    widening the window must not blind the check."""
    _make_all_seat_profiles()
    _pending_file(monkeypatch, tmp_path,
                  "# pending\n\n## Caduceus morning brief (2026-08-31)\n\nbody\n")
    monkeypatch.setattr(_brief, "age_hours", lambda *a, **k: 55.0)

    status, detail = _row(doctor.checks(), "brief delivery")

    assert status == doctor.FAIL
    assert "cad brief --write" in detail


# ---- compile rows (0.4.0) ----------------------------------------------------

def _repo_copy(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent
    dst = tmp_path / "repo"
    (dst / "seats").mkdir(parents=True)
    for f in ["PROFILE.json", "DENYLIST.json", "USER.md", "CAST.json"]:
        shutil.copy(src / "seats" / f, dst / "seats" / f)
    monkeypatch.setenv("CADUCEUS_REPO", str(dst))
    return dst


def test_profile_row_ok_then_warn_when_user_md_stale(tmp_path, monkeypatch):
    repo = _repo_copy(tmp_path, monkeypatch)
    status, detail = _row(doctor.checks(), "profile")
    assert status == doctor.OK and "USER.md" in detail
    (repo / "seats" / "USER.md").write_text("hand edited\n")
    status, detail = _row(doctor.checks(), "profile")
    assert status == doctor.WARN and "cad compile --write" in detail


def test_profile_row_warns_without_profile(tmp_path, monkeypatch):
    repo = _repo_copy(tmp_path, monkeypatch)
    (repo / "seats" / "PROFILE.json").unlink()
    status, detail = _row(doctor.checks(), "profile")
    assert status == doctor.WARN and "PROFILE.json" in detail


def test_loadout_row_not_installed_then_clock(tmp_path, monkeypatch):
    _repo_copy(tmp_path, monkeypatch)
    from caduceus import loadout
    status, detail = _row(doctor.checks(), "loadout")
    assert status == doctor.OK and "not installed" in detail
    loadout.mark_first_install()
    status, detail = _row(doctor.checks(), "loadout")
    assert status == doctor.OK and "day 0/14" in detail and "RUNNING" in detail


def test_profile_row_warns_when_a_seat_copy_is_stale(tmp_path, monkeypatch):
    _repo_copy(tmp_path, monkeypatch)
    pd = profile_dir("finisher")
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "USER.md").write_text("# CADUCEUS PRINCIPAL PROFILE — stale copy\n")
    status, detail = _row(doctor.checks(), "profile")
    assert status == doctor.WARN and "cad init" in detail and "finisher" in detail


# ------------------------------------------------- scheduler PATH (would a job find hermes?)
# A job started by the system scheduler does not get the PATH the operator's
# interactive shell has, so a `hermes` that resolves fine at the prompt can be
# invisible to a scheduled `cad` command. The row compares where hermes
# resolves here with where a scheduler-started job would look. Read-only.
#
# The binary lookup is mocked: nothing here depends on, or touches, the real
# environment, and the launchd directory is always an isolated tmp dir.

import os
import shutil

import pytest

HOME_BIN = "/home/someone/.local/bin"
HOME_HERMES = HOME_BIN + "/hermes"


def _hermes_at(monkeypatch, where):
    """hermes lives at `where` (or nowhere). A bare lookup is this environment;
    a lookup with path= finds it only if that PATH lists its directory."""
    real = shutil.which

    def which(cmd, mode=os.F_OK | os.X_OK, path=None):
        if cmd != "hermes":
            return real(cmd, mode=mode, path=path)
        if where is None:
            return None
        if path is None:
            return where
        return where if os.path.dirname(where) in path.split(os.pathsep) else None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(doctor, "run_hermes", lambda *a, **k: (0, "hermes test-double"))


def _job(d, label, path=None):
    """An installed caduceus job; `path` is its EnvironmentVariables PATH, if any."""
    data = {"Label": label,
            "ProgramArguments": ["/bin/zsh", "-lc", "cad exec run --live"]}
    if path is not None:
        data["EnvironmentVariables"] = {"PATH": path}
    with open(d / f"{label}.plist", "wb") as f:
        plistlib.dump(data, f)


def _sched(rows):
    row = _row(rows, "scheduler path")
    assert row is not None, "no `scheduler path` row"
    return row


def test_scheduler_path_warns_when_hermes_is_only_on_the_shell_path(monkeypatch, tmp_path):
    _make_all_seat_profiles()
    _launchd_dir(monkeypatch, tmp_path)
    _hermes_at(monkeypatch, HOME_HERMES)

    status, detail = _sched(doctor.checks())

    assert status == doctor.WARN
    assert HOME_BIN in detail                      # the directory that would need adding
    assert "/usr/bin" in detail                    # and what the scheduler-like PATH was


@pytest.mark.parametrize("where", ["/opt/homebrew/bin/hermes", "/usr/local/bin/hermes",
                                   "/usr/bin/hermes"])
def test_scheduler_path_ok_when_hermes_is_in_a_standard_directory(monkeypatch, tmp_path, where):
    _make_all_seat_profiles()
    _launchd_dir(monkeypatch, tmp_path)
    _hermes_at(monkeypatch, where)

    status, detail = _sched(doctor.checks())

    assert status == doctor.OK
    assert where in detail


def test_scheduler_path_row_absent_when_hermes_is_not_installed(monkeypatch, tmp_path):
    """The `hermes binary` row already FAILs for this; no second complaint."""
    _make_all_seat_profiles()
    _launchd_dir(monkeypatch, tmp_path)
    _hermes_at(monkeypatch, None)

    rows = doctor.checks()

    assert _row(rows, "scheduler path") is None
    assert _row(rows, "hermes binary")[0] == doctor.FAIL


def test_scheduler_path_names_the_installed_jobs_that_cannot_find_hermes(monkeypatch, tmp_path):
    _make_all_seat_profiles()
    d = _launchd_dir(monkeypatch, tmp_path)
    _job(d, "example.caduceus.exec")
    _job(d, "example.caduceus.nudge")
    _hermes_at(monkeypatch, HOME_HERMES)

    status, detail = _sched(doctor.checks())

    assert status == doctor.WARN
    assert "example.caduceus.exec" in detail and "example.caduceus.nudge" in detail
    assert HOME_BIN in detail


def test_scheduler_path_ok_when_the_job_declares_the_directory(monkeypatch, tmp_path):
    """The natural fix must turn the row green: a job's own PATH counts."""
    _make_all_seat_profiles()
    d = _launchd_dir(monkeypatch, tmp_path)
    _job(d, "example.caduceus.exec", path=HOME_BIN + ":/usr/bin")
    _hermes_at(monkeypatch, HOME_HERMES)

    status, detail = _sched(doctor.checks())

    assert status == doctor.OK, detail


def test_scheduler_path_blames_only_the_job_that_lacks_the_directory(monkeypatch, tmp_path):
    _make_all_seat_profiles()
    d = _launchd_dir(monkeypatch, tmp_path)
    _job(d, "example.caduceus.exec", path=HOME_BIN)
    _job(d, "example.caduceus.nudge")
    _hermes_at(monkeypatch, HOME_HERMES)

    status, detail = _sched(doctor.checks())

    assert status == doctor.WARN
    assert "example.caduceus.nudge" in detail
    assert "example.caduceus.exec" not in detail


def test_scheduler_path_check_changes_nothing(monkeypatch, tmp_path):
    _make_all_seat_profiles()
    d = _launchd_dir(monkeypatch, tmp_path)
    _job(d, "example.caduceus.exec")
    _hermes_at(monkeypatch, HOME_HERMES)
    before = {p.name: p.read_bytes() for p in d.iterdir()}

    doctor.checks()

    assert {p.name: p.read_bytes() for p in d.iterdir()} == before
