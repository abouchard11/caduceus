"""hermes_home() must resolve seats from the ROOT home, not a seat profile
subdir. Regression for the bug where `cad doctor`/`cad seats up` report
"profile missing" when run from inside a seat session (HERMES_HOME pointing
at ~/.hermes/profiles/<seat>)."""

from pathlib import Path

from caduceus import config


def test_hermes_home_strips_profile_subdir(tmp_path, monkeypatch):
    root = tmp_path / "hermes_root"
    monkeypatch.setenv("HERMES_HOME", str(root / "profiles" / "recon"))
    assert config.hermes_home() == root


def test_hermes_home_strips_any_seat_subdir(tmp_path, monkeypatch):
    root = tmp_path / "hermes_root"
    for seat in ("forge", "finisher", "sparring", "envoy", "recon"):
        monkeypatch.setenv("HERMES_HOME", str(root / "profiles" / seat))
        assert config.hermes_home() == root, f"seat {seat} did not normalize"


def test_hermes_home_passes_root_through(tmp_path, monkeypatch):
    root = tmp_path / "hermes_root"
    monkeypatch.setenv("HERMES_HOME", str(root))
    assert config.hermes_home() == root