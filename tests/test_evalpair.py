"""Paired evaluation: the same question runs twice, arm A without loadouts
and arm B with, both registered under one pair id so the ledger settles each
run as usual and the report derives the pair outcome. The pre-registered
rule (docs/compile-design.md §6) is computed here and nowhere else."""
import time

import pytest

from caduceus import config, evalpair, loadout
from caduceus.config import SEATS
from caduceus.council import Council
from caduceus.hermes import MockTransport
from caduceus.ledger import Ledger

EMPTY = {"schema": "caduceus.loadout.v1", "seats": {}}


def _factory():
    return Council(ledger=Ledger(), transport="mock", mock=MockTransport())


def test_pair_registers_two_runs_with_leads():
    for s in ["forge", "finisher"]:
        (config.hermes_home() / "profiles" / s).mkdir(parents=True, exist_ok=True)
    pr = evalpair.run_pair("q?", [SEATS["forge"], SEATS["finisher"]], "", dry_run=True,
                           table=EMPTY, cast=None, mani=None, council_factory=_factory)
    pairs = Ledger().pairs()
    assert pr.pair_id in pairs and set(pairs[pr.pair_id]) == {"A-dry", "B-dry"}
    assert pairs[pr.pair_id]["A-dry"]["lead"] in ("forge", "finisher")
    assert pr.a.run_id == f"{pr.pair_id}-A" and pr.b.run_id == f"{pr.pair_id}-B"
    assert pr.a.question == pr.b.question == "q?"


def test_pair_restores_state_on_failure(monkeypatch):
    calls = {"n": 0}

    class Boom(Council):
        def run(self, *a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("arm B exploded")
            return super().run(*a, **k)

    seen = []
    monkeypatch.setattr(evalpair, "_install", lambda *a, **k: seen.append("install"))
    monkeypatch.setattr(evalpair, "_uninstall", lambda *a, **k: seen.append("uninstall"))
    monkeypatch.setattr(evalpair, "_was_installed", lambda: True)
    with pytest.raises(RuntimeError):
        evalpair.run_pair("q", [SEATS["forge"], SEATS["finisher"]], "", dry_run=False,
                          table={"schema": "caduceus.loadout.v1", "seats": {"finisher": {"review": ["x"]}}},
                          cast=object(), mani=object(),
                          council_factory=lambda: Boom(ledger=Ledger(), transport="mock",
                                                        mock=MockTransport()))
    # uninstall for arm A, install for arm B, and the restore-to-installed in finally
    assert seen == ["uninstall", "install", "install"]


def test_pair_restores_to_uninstalled(monkeypatch):
    seen = []
    monkeypatch.setattr(evalpair, "_install", lambda *a, **k: seen.append("install"))
    monkeypatch.setattr(evalpair, "_uninstall", lambda *a, **k: seen.append("uninstall"))
    monkeypatch.setattr(evalpair, "_was_installed", lambda: False)
    evalpair.run_pair("q", [SEATS["forge"], SEATS["finisher"]], "", dry_run=False, table=EMPTY,
                      cast=None, mani=None, council_factory=_factory)
    assert seen == ["uninstall", "install", "uninstall"]


def _seed_pairs(L, n, b_wins=True, ts=None):
    for i in range(n):
        L.register_run(f"a{i}", "review", "q", ["forge"], pair_id=f"p{i}", arm="A", lead="forge")
        L.register_run(f"b{i}", "review", "q", ["forge"], pair_id=f"p{i}", arm="B", lead="finisher")
        if b_wins:
            L.settle(f"a{i}", winners=[], losers=["forge"], mixed=[])
            L.settle(f"b{i}", winners=["finisher"], losers=[], mixed=[])
        else:
            L.settle(f"a{i}", winners=["forge"], losers=[], mixed=[])
            L.settle(f"b{i}", winners=[], losers=["finisher"], mixed=[])
        if ts is not None:
            L.conn.execute("UPDATE council_runs SET ts=? WHERE run_id IN (?, ?)", (ts, f"a{i}", f"b{i}"))
            L.conn.commit()


def test_report_rule_pass_and_running():
    L = Ledger()
    t0 = time.time() - 15 * 86400
    _seed_pairs(L, 3, ts=t0 + 86400)          # pairs ran on day 1 of the window
    loadout.mark_first_install(ts=t0)
    r = evalpair.report(L)
    assert r["pairs"] == 3 and r["b_wins"] == 3 and r["a_wins"] == 0 and r["ties"] == 0
    assert r["verdict"] == "PASS" and r["days"] >= 14
    loadout.mark_first_install(ts=time.time() - 3 * 86400, force=True)
    assert evalpair.report(L)["verdict"] == "RUNNING"


def test_report_rule_park():
    L = Ledger()
    t0 = time.time() - 20 * 86400
    _seed_pairs(L, 3, b_wins=False, ts=t0 + 86400)
    loadout.mark_first_install(ts=t0)
    r = evalpair.report(L)
    assert r["a_wins"] == 3 and r["verdict"] == "PARK"


def test_report_counts_unsettled_and_ties():
    L = Ledger()
    L.register_run("a", "review", "q", ["forge"], pair_id="p", arm="A", lead="forge")
    L.register_run("b", "review", "q", ["forge"], pair_id="p", arm="B", lead="forge")
    r = evalpair.report(L)
    assert r["pairs"] == 1 and r["unsettled"] == 1 and r["verdict"] == "RUNNING" and r["days"] is None
    L.settle("a", winners=["forge"], losers=[], mixed=[])
    L.settle("b", winners=["forge"], losers=[], mixed=[])
    r = evalpair.report(L)
    assert r["ties"] == 1 and r["unsettled"] == 0


def test_report_excludes_dry_pairs():
    L = Ledger()
    L.register_run("a", "review", "q", ["forge"], pair_id="p", arm="A-dry", lead="forge")
    L.register_run("b", "review", "q", ["forge"], pair_id="p", arm="B-dry", lead="forge")
    assert evalpair.report(L)["pairs"] == 0


# ---- review fixes 2026-10-10 --------------------------------------------------

def test_dry_run_touches_no_installs_and_no_clock(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(evalpair, "_install", lambda *a, **k: seen.append("install"))
    monkeypatch.setattr(evalpair, "_uninstall", lambda *a, **k: seen.append("uninstall"))
    evalpair.run_pair("q", [SEATS["forge"], SEATS["finisher"]], "", dry_run=True, table=EMPTY,
                      cast=None, mani=None, council_factory=_factory)
    assert seen == [] and loadout.first_install_ts() is None


def test_dry_run_with_real_table_never_installs(tmp_path):
    from caduceus import compile as comp, manifest, profile
    from pathlib import Path
    root = tmp_path / "skills"
    d = root / "cat" / "alpha"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: alpha\ndescription: d\n---\n")
    mani = manifest.scan(roots=[("t", root, 3)])
    cast = comp.cast(profile.load(Path(__file__).resolve().parent.parent / "seats" / "PROFILE.json"))
    (config.hermes_home() / "profiles" / "finisher").mkdir(parents=True)
    table = {"schema": "caduceus.loadout.v1", "seats": {"finisher": {"review": ["alpha"]}}}
    evalpair.run_pair("q", [SEATS["forge"], SEATS["finisher"]], "", dry_run=True, table=table,
                      cast=cast, mani=mani, council_factory=_factory)
    assert not (config.hermes_home() / "profiles" / "finisher" / "skills").exists()
    assert loadout.first_install_ts() is None


def test_refuses_when_installed_and_cannot_restore(monkeypatch):
    seen = []
    monkeypatch.setattr(evalpair, "_install", lambda *a, **k: seen.append("install"))
    monkeypatch.setattr(evalpair, "_uninstall", lambda *a, **k: seen.append("uninstall"))
    monkeypatch.setattr(evalpair, "_was_installed", lambda: True)
    table = {"schema": "caduceus.loadout.v1", "seats": {"finisher": {"review": ["alpha"]}}}
    with pytest.raises(evalpair.PairError):
        evalpair.run_pair("q", [SEATS["forge"], SEATS["finisher"]], "", dry_run=False, table=table,
                          cast=None, mani=None, council_factory=_factory)
    assert seen == []


def test_report_counts_only_pairs_inside_the_window():
    L = Ledger()
    t0 = time.time() - 30 * 86400
    _seed_pairs(L, 3, ts=t0 + 86400)
    loadout.mark_first_install(ts=t0, force=True)
    # pair p2 started on day 20: outside the 14-day window
    L.conn.execute("UPDATE council_runs SET ts=? WHERE run_id IN ('a2','b2')", (t0 + 20 * 86400,))
    L.conn.commit()
    r = evalpair.report(L)
    assert r["pairs"] == 2 and r["b_wins"] == 2 and r["late_pairs"] == 1
    assert r["verdict"] == "PARK"          # 2 < 3 wins inside the window
    L.conn.execute("UPDATE council_runs SET ts=? WHERE run_id IN ('a2','b2')", (t0 + 2 * 86400,))
    L.conn.commit()
    r = evalpair.report(L)
    assert r["pairs"] == 3 and r["late_pairs"] == 0 and r["verdict"] == "PASS"
