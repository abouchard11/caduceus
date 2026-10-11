"""`cad ledger settle --winner finisher,forge` must settle two seats, never a
seat literally named "finisher,forge". 2026-10-10: eight runs were settled
with comma lists and the ledger grew rows for seats that do not exist. Seat
names are validated against SEATS and the run's registered seats, which also
stops a --note typed into the seat slot (one such row exists from 09-29)."""
import pytest

from caduceus import cli
from caduceus.ledger import Ledger


def _run(L, run_id="r1", seats=("forge", "finisher", "recon", "sparring")):
    L.register_run(run_id, "review", "q", list(seats))


def _rows(L, run_id):
    return sorted(L.conn.execute(
        "SELECT seat, result FROM outcomes WHERE task_ref=? AND voided=0", (run_id,)).fetchall())


def test_settle_splits_comma_lists(capsys):
    L = Ledger(); _run(L); L.close()
    assert cli.main(["ledger", "settle", "r1", "--winner", "finisher,forge", "--unexecuted", "recon, sparring"]) == 0
    L = Ledger()
    assert _rows(L, "r1") == [("finisher", "win"), ("forge", "win"), ("recon", "unexecuted"), ("sparring", "unexecuted")]
    assert "finisher,forge" not in capsys.readouterr().out


def test_settle_rejects_unknown_seat_before_writing():
    L = Ledger(); _run(L); L.close()
    with pytest.raises(SystemExit) as e:
        cli.main(["ledger", "settle", "r1", "--winner", "recon's plan held on 499 reads"])
    assert "unknown seat" in str(e.value)
    L = Ledger()
    assert _rows(L, "r1") == [] and L.runs()[0]["settled"] is False


def test_resettle_splits_and_voids_bad_rows():
    L = Ledger(); _run(L)
    L.record("finisher,forge", "review", "win", task_ref="r1")      # the 2026-10-10 mistake, as data
    L.conn.execute("UPDATE council_runs SET settled=1 WHERE run_id='r1'"); L.conn.commit(); L.close()
    assert cli.main(["ledger", "resettle", "r1", "--winner", "finisher,forge"]) == 0
    L = Ledger()
    assert _rows(L, "r1") == [("finisher", "win"), ("forge", "win")]
    assert L.conn.execute("SELECT COUNT(*) FROM outcomes WHERE task_ref='r1' AND voided=1").fetchone()[0] == 1


def test_record_rejects_unknown_seat():
    with pytest.raises(SystemExit) as e:
        cli.main(["ledger", "record", "fini sher", "review", "win"])
    assert "unknown seat" in str(e.value)
