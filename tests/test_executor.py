"""Executor policy gates: the wrapper, not the model, owns the disk."""
import time
import pytest

from caduceus import budgets, executor
from caduceus.executor import ExecResult, _validate_rel, execute_one
from caduceus.hermes import MockTransport


class C:  # minimal commitment stand-in
    def __init__(self, action, cid="cid123", run_id="run-x"):
        self.id, self.action, self.run_id = cid, action, run_id
        self.owner, self.kind, self.seat = "agent", "do", "forge"
        self.created_ts, self.state = time.time(), "pending"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(executor, "ALLOWED_ROOTS", (root,))
    # isolate spend ledger + generous caps
    monkeypatch.setattr(budgets, "budgets_dir", lambda: tmp_path)
    monkeypatch.setattr(budgets, "check_daily_budget", lambda: ("ok", 0.0, 10.0))
    return root


def test_path_validation_blocks_escape_and_protected(sandbox):
    assert _validate_rel(sandbox, "../evil.md")[0] is None
    assert _validate_rel(sandbox, "/abs.md")[0] is None
    assert _validate_rel(sandbox, ".git/hook.md")[0] is None
    assert _validate_rel(sandbox, "sub/.env")[0] is None
    ok, err = _validate_rel(sandbox, "docs/new.md")
    assert ok is not None and not err


def test_existing_file_is_never_overwritten(sandbox):
    (sandbox / "docs").mkdir()
    (sandbox / "docs/x.md").write_text("original")
    assert _validate_rel(sandbox, "docs/x.md")[0] is None


def test_per_action_cap_blocks_before_any_model_call(sandbox, monkeypatch):
    monkeypatch.setattr(executor, "EST_ACTION_COST", 99.0)
    t = MockTransport()
    r = execute_one(C("write docs"), transport=t, live=True)
    assert r.status == "blocked" and "per-action cap" in r.detail
    assert t.calls == []  # fail-closed BEFORE spend


def test_daily_cap_blocks(sandbox, monkeypatch):
    budgets.record_execution_spend("prior", 14.9)
    t = MockTransport()
    r = execute_one(C("write docs"), transport=t, live=True)
    assert r.status == "blocked" and "daily cap" in r.detail
    assert t.calls == []


def test_file_block_is_written(sandbox):
    reply = "===FILE: docs/contract.md===\n# The Contract\nbody\n===END==="
    t = MockTransport(script={"forge": [reply]})
    r = execute_one(C("write the contract"), transport=t, live=True)
    assert r.status == "done", r.detail
    assert (sandbox / "docs/contract.md").read_text() == "# The Contract\nbody\n"


def test_model_escalation_is_honored(sandbox):
    t = MockTransport(script={"forge": ["===ESCALATE: needs a git push==="]})
    r = execute_one(C("push the fix"), transport=t, live=True)
    assert r.status == "escalate" and "git push" in r.detail


def test_partial_failure_reverts_all_writes(sandbox):
    reply = ("===FILE: docs/a.md===\nA\n===END===\n"
             "===FILE: ../escape.md===\nB\n===END===")
    t = MockTransport(script={"forge": [reply]})
    r = execute_one(C("two files"), transport=t, live=True)
    assert r.status == "escalate"
    assert not (sandbox / "docs/a.md").exists()  # reverted


def test_no_blocks_no_escalation_escalates(sandbox):
    t = MockTransport(script={"forge": ["here is a plan: step 1..."]})
    r = execute_one(C("do a thing"), transport=t, live=True)
    assert r.status == "escalate"


def test_default_transport_is_tool_locked(monkeypatch):
    """The first live run proved a bare seat writes files itself. The
    executor's default transport must carry the -t clarify lockdown."""
    captured = {}
    import caduceus.executor as ex

    class FakeT:
        def __init__(self, extra_args=None, **kw):
            captured["extra"] = extra_args
        def ask(self, *a, **k):
            raise RuntimeError("stop here")

    monkeypatch.setattr(ex, "OneshotTransport", FakeT)
    monkeypatch.setattr(budgets, "preflight_execution", lambda est: (True, "ok"))
    try:
        execute_one(C("anything"), transport=None, live=True)
    except RuntimeError:
        pass
    assert captured["extra"] == ["-t", "clarify"]
