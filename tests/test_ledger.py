import time

from caduceus.ledger import Ledger


def test_prior_is_half():
    led = Ledger()
    b = led.believability("forge", "implementation")
    assert abs(b.score - 0.5) < 1e-9
    assert b.basis == "prior"
    led.close()


def test_wins_raise_losses_lower():
    led = Ledger()
    for _ in range(5):
        led.record("finisher", "review", "win")
    hi = led.believability("finisher", "review").score
    for _ in range(5):
        led.record("sparring", "review", "loss")
    lo = led.believability("sparring", "review").score
    assert hi > 0.7
    assert lo < 0.3
    assert hi > lo
    led.close()


def test_global_fallback():
    led = Ledger()
    led.record("recon", "research", "win")
    led.record("recon", "research", "win")
    b = led.believability("recon", "never-seen-domain")
    assert b.basis == "global"
    assert b.score > 0.5
    led.close()


def test_recency_decay():
    led = Ledger()
    led.record("forge", "infra", "loss")
    # backdate the loss far beyond several half-lives
    led.conn.execute("UPDATE outcomes SET ts=? WHERE seat='forge'",
                     (time.time() - 400 * 86400,))
    led.conn.commit()
    b = led.believability("forge", "infra")
    # ancient loss barely moves the prior
    assert b.score > 0.4
    led.close()


def test_settle_flow():
    led = Ledger()
    led.register_run("run-1", "strategy", "pivot?", ["forge", "sparring"], "/tmp/m.md")
    assert any(r["run_id"] == "run-1" for r in led.runs())
    led.settle("run-1", winners=["sparring"], losers=["forge"], mixed=[])
    assert not any(r["run_id"] == "run-1" for r in led.runs(unsettled_only=True))
    assert led.believability("sparring", "strategy").score > \
           led.believability("forge", "strategy").score
    led.close()


def test_pending_ignored_in_score():
    led = Ledger()
    led.record("envoy", "comms", "pending")
    b = led.believability("envoy", "comms")
    assert b.basis == "prior"
    led.close()


# ------------------------------------------------------- unexecuted (0.3.5)
# 2026-09-01: 4 of the 8 losses recorded 08-26..08-27 carried "never executed"
# notes - the operator did not act on the advice, and the ledger scored that
# as the SEAT being wrong. FINISHER sat at 0.261 (0/0/2) built entirely from
# advice nobody tried, on runs where it was not even the lead. Those weights
# pick every future council's lead. followup.py (PR #5) separates "not tried"
# from "tried and wrong" going forward; the ledger needs an outcome that
# records non-execution WITHOUT moving believability, and a way to re-settle
# the four rows already scored wrong - preserving history, never deleting.

import sqlite3

from caduceus import cli, config


def _run(led, rid="20260901-000000-aaaaaa", domain="implementation"):
    led.register_run(rid, domain, "Should we?", ["forge", "finisher"])
    return rid


def test_unexecuted_is_recorded_but_moves_no_weight():
    led = Ledger()
    rid = _run(led)
    led.settle(rid, winners=[], losers=[], mixed=[], unexecuted=["forge"],
               note="never tried")
    b = led.believability("forge", "implementation")
    assert abs(b.score - 0.5) < 1e-9 and b.basis == "prior"
    row = next(r for r in led.table() if r["seat"] == "forge")
    assert row["unexecuted"] == 1 and row["loss"] == 0 and row["win"] == 0
    assert led.runs(unsettled_only=True) == []          # run is closed
    led.close()


def test_unexecuted_leaves_an_existing_score_untouched():
    led = Ledger()
    led.record("forge", "implementation", "win")
    before = led.believability("forge", "implementation").score
    rid = _run(led)
    led.settle(rid, winners=[], losers=[], mixed=[], unexecuted=["forge"])
    assert abs(led.believability("forge", "implementation").score - before) < 1e-9
    led.close()


def test_resettle_voids_prior_rows_and_keeps_history():
    led = Ledger()
    rid = _run(led)
    led.settle(rid, winners=[], losers=["forge", "finisher"], mixed=[],
               note="scored as loss by mistake")
    assert led.believability("finisher", "implementation").score < 0.5

    led.resettle(rid, winners=[], losers=[], mixed=[],
                 unexecuted=["forge", "finisher"], note="never executed")

    assert led.believability("finisher", "implementation").basis == "prior"
    rows = led.conn.execute(
        "SELECT result, voided FROM outcomes WHERE task_ref=? ORDER BY ts", (rid,)
    ).fetchall()
    assert ("loss", 1) in rows and ("unexecuted", 0) in rows   # history kept
    assert len(rows) == 4
    table = {r["seat"]: r for r in led.table()}
    assert table["finisher"]["loss"] == 0 and table["finisher"]["unexecuted"] == 1
    assert led.runs(unsettled_only=True) == []
    led.close()


def test_resettle_refuses_an_unknown_run():
    led = Ledger()
    import pytest
    with pytest.raises(SystemExit):
        led.resettle("nope", [], [], [], ["forge"], "x")
    led.close()


LEGACY_SCHEMA = """
CREATE TABLE outcomes (
    id TEXT PRIMARY KEY, ts REAL NOT NULL, seat TEXT NOT NULL, domain TEXT NOT NULL,
    result TEXT NOT NULL CHECK(result IN ('win','mixed','loss','pending')),
    task_ref TEXT DEFAULT '', note TEXT DEFAULT '', model TEXT DEFAULT ''
);
CREATE INDEX idx_outcomes_seat ON outcomes(seat, domain);
CREATE TABLE council_runs (
    run_id TEXT PRIMARY KEY, ts REAL NOT NULL, domain TEXT NOT NULL, question TEXT,
    seats TEXT, memo_path TEXT, settled INTEGER NOT NULL DEFAULT 0
);
"""


def test_migration_rebuilds_legacy_check_constraint(tmp_path):
    """The live DB was created with CHECK(result IN win/mixed/loss/pending).
    SQLite cannot ALTER a CHECK; the migration must rebuild the table and
    keep every existing row byte-for-byte."""
    p = tmp_path / "legacy.db"
    c = sqlite3.connect(str(p))
    c.executescript(LEGACY_SCHEMA)
    c.execute("INSERT INTO outcomes VALUES ('old1', ?, 'forge', 'review', 'loss', 'r1', 'n', 'm')", (time.time() - 86400,))
    c.execute("INSERT INTO council_runs VALUES ('r1', ?, 'review', 'q', 'forge', '', 1)", (time.time() - 86400,))
    c.execute("INSERT INTO outcomes VALUES ('old2', ?, 'recon', 'review', 'win', NULL, NULL, NULL)", (time.time() - 3600,))
    c.commit(); c.close()

    led = Ledger(path=p)
    led.record("forge", "review", "unexecuted", task_ref="r2")   # would violate the old CHECK
    kept = led.conn.execute("SELECT id, result, note, model FROM outcomes WHERE id='old1'").fetchone()
    assert kept == ("old1", "loss", "n", "m")
    assert led.conn.execute("SELECT voided FROM outcomes WHERE id='old1'").fetchone() == (0,)
    # NULLs in legacy rows coalesce instead of crashing the copy
    assert led.conn.execute("SELECT note, model FROM outcomes WHERE id='old2'").fetchone() == ("", "")
    # the index must survive the rebuild (rename keeps it on the legacy table otherwise)
    assert led.conn.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_outcomes_seat'").fetchone()
    assert led.believability("forge", "review").score < 0.5      # old loss still counts
    led.close()
    # idempotent: reopening must not rebuild again or lose rows
    led2 = Ledger(path=p)
    assert led2.conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 3
    led2.close()


def test_migration_tolerates_a_stray_legacy_table(tmp_path):
    """An aborted earlier attempt can leave outcomes_legacy behind; that must
    not brick every future open with a raw OperationalError."""
    p = tmp_path / "stray.db"
    c = sqlite3.connect(str(p)); c.executescript(LEGACY_SCHEMA)
    c.execute("CREATE TABLE outcomes_legacy (x INTEGER)"); c.commit(); c.close()
    led = Ledger(path=p)
    led.record("forge", "review", "unexecuted")
    led.close()


def test_cli_resettle_unknown_run_exits_nonzero():
    import pytest
    with pytest.raises(SystemExit):
        cli.main(["ledger", "resettle", "nope", "--unexecuted", "forge"])


def test_cli_record_accepts_unexecuted(capsys):
    assert cli.main(["ledger", "record", "forge", "review", "unexecuted", "--note", "n"]) == 0
    led = Ledger()
    assert led.believability("forge", "review").basis == "prior"
    led.close()


def test_value_report_ignores_voided_and_unexecuted_rows():
    """cad models value ($ per win) must not double-count a resettled run or
    count non-execution as an outcome - it read raw outcomes rows."""
    from caduceus import models
    led = Ledger()
    rid = _run(led, domain="review")
    led.settle(rid, winners=["finisher"], losers=[], mixed=[], note="wrong")
    led.resettle(rid, winners=[], losers=["finisher"], mixed=[], unexecuted=[], note="corrected")
    rid2 = _run(led, rid="20260901-000000-cccccc", domain="review")
    led.settle(rid2, winners=[], losers=[], mixed=[], unexecuted=["finisher"])
    rows = {r["seat"]: r for r in models.value_report(led)}
    assert rows["finisher"]["win"] == 0 and rows["finisher"]["loss"] == 1
    assert rows["finisher"]["n"] == 1
    led.close()


def test_cli_settle_and_resettle_accept_unexecuted(capsys):
    led = Ledger(); rid = _run(led); led.close()
    assert cli.main(["ledger", "settle", rid, "--loser", "forge", "--note", "oops"]) == 0
    assert cli.main(["ledger", "resettle", rid, "--unexecuted", "forge",
                     "--note", "never executed"]) == 0
    assert cli.main(["ledger", "show"]) == 0
    out = capsys.readouterr().out
    assert "w/m/l/u" in out and "0/0/0/1" in out         # header AND the row
    led = Ledger()
    assert led.believability("forge", "implementation").basis == "prior"
    led.close()
