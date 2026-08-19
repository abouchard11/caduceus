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
