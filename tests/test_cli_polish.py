"""Reviewer minors promoted on 2026-10-11 because they touch daily use:
`cad ledger runs` shows which pair and arm a run belongs to (settling BOTH
arms needs it), `cad compile` prints the USER.md diff it would write, and the
new ledger-opening call sites close their handle."""
import json
import shutil
from pathlib import Path

import pytest

from caduceus import cli
from caduceus.ledger import Ledger

ROOT = Path(__file__).resolve().parent.parent


def test_ledger_runs_shows_pair_and_arm(capsys):
    L = Ledger()
    L.register_run("p-A", "review", "q", ["forge"], pair_id="p", arm="A", lead="forge")
    L.register_run("p-B", "review", "q", ["forge"], pair_id="p", arm="B", lead="finisher")
    L.register_run("solo", "review", "q", ["forge"])
    L.close()
    cli.main(["ledger", "runs"])
    out = capsys.readouterr().out
    assert "p-A  [review]  pair p arm A  lead forge" in out.replace("  ", " ").replace(" ", " ") or "pair p arm A" in out
    assert "pair p arm B" in out and "lead finisher" in out
    solo_line = [l for l in out.splitlines() if "solo" in l][0]
    assert "pair" not in solo_line


@pytest.fixture
def repo(tmp_path, monkeypatch):
    dst = tmp_path / "repo"
    (dst / "seats").mkdir(parents=True)
    for f in ["PROFILE.json", "DENYLIST.json", "USER.md", "CAST.json"]:
        shutil.copy(ROOT / "seats" / f, dst / "seats" / f)
    monkeypatch.setenv("CADUCEUS_REPO", str(dst))
    return dst


def test_compile_prints_user_md_diff_when_stale(repo, capsys):
    p = repo / "seats" / "PROFILE.json"
    d = json.loads(p.read_text())
    d["notes"]["Modest 16"] = "edited for the diff test"
    p.write_text(json.dumps(d, indent=2))
    cli.main(["compile"])
    out = capsys.readouterr().out
    assert "USER.md: would-write" in out
    assert "+- Modest 16 — edited for the diff test" in out and "--- seats/USER.md" in out


def test_ledger_handles_are_closed(monkeypatch):
    opened = []
    real_init = Ledger.__init__
    real_close = Ledger.close

    def init(self, *a, **k):
        real_init(self, *a, **k)
        opened.append(self)
        self._closed_by_test = False

    def close(self):
        self._closed_by_test = True
        real_close(self)

    monkeypatch.setattr(Ledger, "__init__", init)
    monkeypatch.setattr(Ledger, "close", close)
    from caduceus import brief, doctor, loadout
    loadout.mark_first_install()
    brief.gather()
    doctor._loadout_row()
    cli.main(["eval", "loadout", "report"])
    assert len(opened) >= 3 and all(getattr(L, "_closed_by_test", False) for L in opened)
