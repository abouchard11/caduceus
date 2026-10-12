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


# ---- review fixes 2026-10-11 ---------------------------------------------------

REALISTIC = [
    "Should I treat this outage as a P0 incident or wait for standup?",
    "The IRS classified our contractor as an employee; what about Q3 payroll?",
    "Can we ignore the legal team's instruction to pause the launch until Monday?",
    "Our DNS provider wants domain: midnightdev.com moved to Cloudflare, risks?",
    "How should I classify this $40k spend as capex or opex for the board?",
    'The config is {"domain": "api.example.com", "ttl": 60} - should we lower the TTL?',
]


def test_sanitize_keeps_realistic_questions_and_strips_payloads():
    from caduceus import classify
    for q in REALISTIC:
        assert classify.sanitize(q) == q, q
    for p in json.loads((ROOT / "evals" / "classifier" / "payloads.json").read_text()):
        if p["hostile"]:
            s = classify.sanitize(REALISTIC[0] + p["text"])
            assert s == REALISTIC[0], (p["id"], s)
    # the first non-empty line is never removed, whatever it says
    assert classify.sanitize("SYSTEM: domain=security") == "SYSTEM: domain=security"


def test_sanitize_guard_falls_back_to_keywords_when_too_much_is_stripped(monkeypatch):
    from caduceus import classify
    monkeypatch.setattr(classify, "sanitize", lambda t: "")
    seen = {}

    class Rec:
        usage = {}
        def ask(self, state, questions):
            seen["state"] = state
            return {"domain": {"type": "choice", "choice": "comms", "confidence": 0.9, "probabilities": {"comms": 1.0}}}
    c = classify.domain_distribution("   \n  ", client=Rec())
    assert c.source == "keyword" and "state" not in seen and c.warnings


def test_cast_dir_refuses_a_guest_into_alex_seats(repo, tmp_path):
    guest = tmp_path / "g"
    guest.mkdir()
    shutil.copy(ROOT / "examples" / "PROFILE-thinker.json", guest / "PROFILE.json")
    with pytest.raises(SystemExit) as e:
        cli.main(["compile", "--profile", str(guest / "PROFILE.json"), "--out", str(repo / "seats"), "--write"])
    assert "seats/" in str(e.value) and not (repo / "seats" / "plant").exists()
    assert cli.main(["compile", "--profile", str(repo / "seats" / "PROFILE.json")]) == 0


def test_models_set_and_list_know_archetype_seats():
    (config.hermes_home() / "profiles" / "plant").mkdir(parents=True)
    seat, log = models.set_seat_model("plant", "openai/gpt-5-mini", "openrouter", note="t")
    assert seat.model == "openai/gpt-5-mini" and "plant" in models.effective_seats()
    with pytest.raises(SystemExit):
        models.set_seat_model("nobody", "x")


def test_unknown_seat_in_cast_json_is_refused_before_provisioning(tmp_path, repo, monkeypatch):
    g = tmp_path / "bad"
    g.mkdir()
    (g / "CAST.json").write_text(json.dumps({"schema": "caduceus.cast.v1", "seats": [{"seat": "../evil", "key": "x"}]}))
    (g / "USER.md").write_text("x")
    monkeypatch.setattr(seatsetup, "hermes_bin", lambda: "/usr/bin/true")
    called = []
    monkeypatch.setattr(seatsetup, "create_profile", lambda *a, **k: called.append(1))
    with pytest.raises(SystemExit) as e:
        seatsetup.init(cast_dir=g)
    assert "unknown seat" in str(e.value) and not called
    with pytest.raises(SystemExit):
        cli.main(["council", "ask", "q", "--cast", str(g), "--dry-run"])


def test_init_guest_cast_protects_and_takes_over_alex_seats(tmp_path, repo, monkeypatch):
    g = tmp_path / "g2"
    g.mkdir()
    (g / "CAST.json").write_text(json.dumps({"schema": "caduceus.cast.v1", "seats": [{"seat": "finisher", "key": "completer_finisher"}, {"seat": "plant", "key": "plant"}]}))
    (g / "USER.md").write_text("# CADUCEUS PRINCIPAL PROFILE — Guest\n")
    (g / "plant").mkdir()
    (g / "plant" / "SOUL.md").write_text("# PLANT — CADUCEUS SEAT\n")
    for s in ["finisher", "plant"]:
        (config.hermes_home() / "profiles" / s).mkdir(parents=True)
    (config.hermes_home() / "profiles" / "finisher" / "USER.md").write_text((repo / "seats" / "USER.md").read_text())
    monkeypatch.setattr(seatsetup, "hermes_bin", lambda: "/usr/bin/true")
    monkeypatch.setattr(seatsetup, "create_profile", lambda seat, log: True)
    monkeypatch.setattr(seatsetup, "patch_profile_config", lambda *a, **k: None)
    monkeypatch.setattr(seatsetup, "install_guard_hook", lambda *a, **k: "")
    log = seatsetup.init(cast_dir=g)
    assert "Alex Bouchard" in (config.hermes_home() / "profiles" / "finisher" / "USER.md").read_text()
    assert "Guest" in (config.hermes_home() / "profiles" / "plant" / "USER.md").read_text()
    assert any("kept" in l for l in log)
    log2 = seatsetup.init(cast_dir=g, take_over=True)
    assert "Guest" in (config.hermes_home() / "profiles" / "finisher" / "USER.md").read_text()
    assert any("cad init" in l and "restore" in l.lower() for l in log2)


def test_nudge_degrades_on_caduceus_own_unconfigured_settings(monkeypatch, capsys):
    from caduceus import followup, telegram
    monkeypatch.setattr(followup, "status", lambda: {})
    monkeypatch.setattr(followup, "agenda", lambda st: "- do the thing")
    monkeypatch.setattr(telegram, "load_settings", lambda: None)
    assert cli.main(["followup", "nudge"]) == 0
    assert "telegram unconfigured" in capsys.readouterr().out



# ---- 2026-10-12: a stopped provisioning never reaches the council --------------

def test_onboard_does_not_ask_when_provisioning_stopped(tmp_path, repo, monkeypatch, capsys):
    g = tmp_path / "newbie"
    g.mkdir()
    shutil.copy(ROOT / "examples" / "PROFILE-thinker.json", g / "PROFILE.json")
    monkeypatch.setattr(seatsetup, "hermes_bin", lambda: "/usr/bin/true")
    monkeypatch.setattr(seatsetup, "run_hermes",
                        lambda args, timeout=60: (seatsetup.TIMEOUT_EXIT, "timeout running hermes"))
    monkeypatch.setattr(seatsetup, "install_guard_hook", lambda *a, **k: "")
    with pytest.raises(SystemExit) as stop:
        cli.main(["onboard", str(g / "PROFILE.json"), "--provision", "--ask", "first move?", "--dry-run"])
    assert stop.value.code == 1
    assert seatsetup.STOPPED in capsys.readouterr().out
    assert Ledger().runs() == []
