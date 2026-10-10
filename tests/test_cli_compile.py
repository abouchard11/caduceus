"""`cad compile …` and `cad eval loadout …` as the operator types them. The
repo root is redirected to a copy so --write never touches the checkout."""
import json
import shutil
from pathlib import Path

import pytest

from caduceus import cli, config, loadout

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo(tmp_path, monkeypatch):
    dst = tmp_path / "repo"
    (dst / "seats").mkdir(parents=True)
    for f in ["PROFILE.json", "DENYLIST.json", "USER.md", "CAST.json"]:
        shutil.copy(ROOT / "seats" / f, dst / "seats" / f)
    shutil.copytree(ROOT / "skills", dst / "skills")
    monkeypatch.setenv("CADUCEUS_REPO", str(dst))
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    return dst


def _skill_root(tmp_path, names):
    root = tmp_path / "skills-root"
    for n in names:
        d = root / "cat" / n
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {n}\ndescription: about {n}\n---\n")
    return root


def test_compile_prints_cast_and_is_current(repo, capsys):
    assert cli.main(["compile"]) == 0
    out = capsys.readouterr().out
    for s in ["forge", "finisher", "recon", "sparring", "envoy"]:
        assert s in out
    assert "USER.md: unchanged" in out and "CAST.json: unchanged" in out


def test_compile_write_regenerates_after_profile_edit(repo, capsys):
    p = repo / "seats" / "PROFILE.json"
    d = json.loads(p.read_text())
    d["notes"]["Modest 16"] = "edited"
    p.write_text(json.dumps(d, indent=2))
    cli.main(["compile"])
    assert "USER.md: would-write" in capsys.readouterr().out
    cli.main(["compile", "--write"])
    assert "USER.md: written" in capsys.readouterr().out
    assert "edited" in (repo / "seats" / "USER.md").read_text()
    cli.main(["compile", "--write"])
    assert "USER.md: unchanged" in capsys.readouterr().out


def test_manifest_command_writes_file(repo, tmp_path, capsys):
    root = _skill_root(tmp_path, ["alpha", "send-beta"])
    assert cli.main(["compile", "manifest", "--root", f"t={root}:3", "--roots-only"]) == 0
    out = capsys.readouterr().out
    m = json.loads(loadout.default_cache_path().parent.joinpath("skill-manifest.json").read_text())
    assert m["counts"] == {"t": 2} and "t: 2" in out and "denied: 1" in out


def test_propose_dry_run_without_key(repo, tmp_path, capsys):
    root = _skill_root(tmp_path, ["alpha"])
    cli.main(["compile", "manifest", "--root", f"t={root}:3", "--roots-only"])
    capsys.readouterr()
    assert cli.main(["compile", "propose", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "planned: 1" in out and "no network" in out
    assert not (repo / "seats" / "LOADOUT-PROPOSAL.json").exists()


def test_propose_without_key_exits_2(repo, tmp_path, capsys):
    root = _skill_root(tmp_path, ["alpha"])
    cli.main(["compile", "manifest", "--root", f"t={root}:3", "--roots-only"])
    with pytest.raises(SystemExit) as e:
        cli.main(["compile", "propose"])
    assert e.value.code == 2


def test_propose_needs_a_manifest(repo, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["compile", "propose", "--dry-run"])
    assert "manifest" in str(e.value)


def test_install_status_uninstall_commands(repo, tmp_path, capsys):
    (config.hermes_home() / "profiles" / "finisher").mkdir(parents=True)
    root = _skill_root(tmp_path, ["alpha"])
    cli.main(["compile", "manifest", "--root", f"t={root}:3", "--roots-only"])
    table = repo / "seats" / "LOADOUT.json"
    table.write_text(json.dumps({"schema": "caduceus.loadout.v1",
                                 "seats": {"finisher": {"review": ["alpha", "ghost"]}}}))
    capsys.readouterr()
    assert cli.main(["compile", "install"]) == 0
    out = capsys.readouterr().out
    assert "finisher: 1 in reach" in out and "ghost" in out and "clock started" in out
    assert cli.main(["compile", "status"]) == 0
    out = capsys.readouterr().out
    assert "finisher: 1" in out and "clock: day 0/14" in out
    assert cli.main(["compile", "uninstall"]) == 0
    assert "finisher: 1 removed" in capsys.readouterr().out


def test_install_without_table_exits_2(repo, tmp_path):
    root = _skill_root(tmp_path, ["alpha"])
    cli.main(["compile", "manifest", "--root", f"t={root}:3", "--roots-only"])
    with pytest.raises(SystemExit) as e:
        cli.main(["compile", "install"])
    assert e.value.code == 2


def test_eval_loadout_dry_run_and_report(repo, capsys):
    assert cli.main(["eval", "loadout", "dry question", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "pair:" in out and "-A" in out and "-B" in out and "settle BOTH" in out
    assert cli.main(["eval", "loadout", "report"]) == 0
    out = capsys.readouterr().out
    assert "pairs: 0" in out and "verdict: RUNNING" in out
