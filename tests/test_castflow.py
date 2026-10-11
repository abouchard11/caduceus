"""0.5.0: a second person's cast is provisionable and askable. Archetype seats
(plant, coordinator, anchor, driver) resolve through effective_seat, provision
from a cast directory, keep Alex's USER.md unless --take-over, and run councils."""
import json
import shutil
from pathlib import Path

import pytest

from caduceus import cli, config, models, seatsetup
from caduceus.ledger import Ledger

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo(tmp_path, monkeypatch):
    dst = tmp_path / "repo"
    (dst / "seats").mkdir(parents=True)
    for f in ["PROFILE.json", "DENYLIST.json", "USER.md", "CAST.json"]:
        shutil.copy(ROOT / "seats" / f, dst / "seats" / f)
    for s in ["forge", "finisher", "recon", "sparring", "envoy"]:
        (dst / "seats" / s).mkdir()
        shutil.copy(ROOT / "seats" / s / "SOUL.md", dst / "seats" / s / "SOUL.md")
    shutil.copytree(ROOT / "skills", dst / "skills")
    monkeypatch.setenv("CADUCEUS_REPO", str(dst))
    return dst


@pytest.fixture
def guest(tmp_path, repo):
    g = tmp_path / "guest"
    g.mkdir()
    shutil.copy(ROOT / "examples" / "PROFILE-thinker.json", g / "PROFILE.json")
    assert cli.main(["compile", "--profile", str(g / "PROFILE.json"), "--write"]) == 0
    return g


def test_effective_seat_knows_archetype_seats_and_casting_overrides():
    s = models.effective_seat("plant")
    assert s.name == "plant" and s.provider == "openrouter" and s.port >= 8660 and s.tools_capable
    models.casting_path().write_text(json.dumps({"plant": {"model": "openai/gpt-5-mini", "provider": "openrouter"}}))
    s2 = models.effective_seat("plant")
    assert s2.model == "openai/gpt-5-mini" and s2.family == "openai"
    with pytest.raises(KeyError):
        models.effective_seat("nobody")


def test_seat_list_accepts_archetype_seats():
    names = [s.name for s in config.seat_list("plant,finisher")]
    assert names == ["plant", "finisher"]
    with pytest.raises(SystemExit):
        config.seat_list("nobody")


def test_cast_seat_names_reads_cast_json(guest):
    assert seatsetup.cast_seat_names(guest) == ["plant", "coordinator", "anchor", "driver"]
    assert seatsetup.cast_seat_names(config.repo_root() / "seats") == ["forge", "finisher", "recon", "sparring", "envoy"]


def test_install_soul_and_user_md_from_cast_dir(guest):
    pd = config.hermes_home() / "profiles" / "plant"
    pd.mkdir(parents=True)
    log = []
    seat = models.effective_seat("plant")
    seatsetup.install_soul(seat, log, src_dir=guest)
    seatsetup.install_user_md(seat, log, src=guest / "USER.md")
    assert "PLANT — CADUCEUS SEAT" in (pd / "SOUL.md").read_text()
    assert "Example Thinker" in (pd / "USER.md").read_text()


def test_guest_cast_keeps_alex_seats_unless_take_over(guest):
    # finisher belongs to Alex's cast; the guest's USER.md must not displace it silently
    pd = config.hermes_home() / "profiles" / "finisher"
    pd.mkdir(parents=True)
    (pd / "USER.md").write_text((config.repo_root() / "seats" / "USER.md").read_text())
    log = []
    seat = models.effective_seat("finisher")
    seatsetup.install_user_md(seat, log, src=guest / "USER.md", protect_alex=True)
    assert "Alex Bouchard" in (pd / "USER.md").read_text() and any("kept" in l for l in log)
    seatsetup.install_user_md(seat, log, src=guest / "USER.md", protect_alex=False)
    assert "Example Thinker" in (pd / "USER.md").read_text()
    assert any(p.name.startswith("USER.md.bak") for p in pd.iterdir())


def test_init_with_cast_dir_provisions_the_cast(guest, monkeypatch):
    created = []
    monkeypatch.setattr(seatsetup, "hermes_bin", lambda: "/usr/bin/true")
    monkeypatch.setattr(seatsetup, "create_profile", lambda seat, log: (created.append(seat.name),
                        (config.hermes_home() / "profiles" / seat.name).mkdir(parents=True, exist_ok=True), True)[-1])
    monkeypatch.setattr(seatsetup, "patch_profile_config", lambda *a, **k: None)
    monkeypatch.setattr(seatsetup, "install_guard_hook", lambda *a, **k: "")
    log = seatsetup.init(cast_dir=guest)
    assert created == ["plant", "coordinator", "anchor", "driver"]
    assert "Example Thinker" in (config.hermes_home() / "profiles" / "anchor" / "USER.md").read_text()
    assert "ANCHOR — CADUCEUS SEAT" in (config.hermes_home() / "profiles" / "anchor" / "SOUL.md").read_text()
    assert any("hermes -p plant gateway install" in l for l in log)


def test_council_ask_with_cast_runs_the_fired_seats(guest, capsys):
    assert cli.main(["council", "ask", "What should the Thinker do first?", "--cast", str(guest), "--dry-run"]) == 0
    out = capsys.readouterr().out
    runs = Ledger().runs()
    assert runs and runs[0]["seats"] == "plant,coordinator,anchor,driver"
    assert "cast:" in out and str(guest) in out


def test_onboard_compiles_and_asks(tmp_path, repo, capsys):
    g = tmp_path / "newbie"
    g.mkdir()
    shutil.copy(ROOT / "examples" / "PROFILE-thinker.json", g / "PROFILE.json")
    assert cli.main(["onboard", str(g / "PROFILE.json"), "--ask", "first move?", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert (g / "CAST.json").exists() and "Example Thinker" in out and "plant" in out
    assert "cad init --cast" in out
    assert Ledger().runs()[0]["seats"] == "plant,coordinator,anchor,driver"
