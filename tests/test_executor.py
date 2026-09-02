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
    # the action itself must not trip the verb floor, or the model is never
    # asked - this test is about honoring the MODEL's escalation
    t = MockTransport(script={"forge": ["===ESCALATE: needs a git push==="]})
    r = execute_one(C("write the contract summary"), transport=t, live=True)
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


# ------------------------------------------------- write-path hardening (0.3.6)
# 2026-09-02 adversarial review of the trust boundary, findings verified by
# execution: (B1) a model-written conftest.py was EXECUTED by the wrapper's own
# auto-pytest step - arbitrary code as the operator, no tools needed; (B2) the
# deny lists were case-sensitive on APFS, so ".GIT/hooks/pre-commit" landed in
# the real .git/hooks; (B3) the "-t clarify strips all tools" boundary was an
# unverified CLI flag with no detection if it stops holding; (S8) no lock, so
# a manual run overlapping the Mon/Thu launchd run double-spends; (S9) push /
# deploy / install / PR classified as staff work and reached the model - the
# only thing between them and reality was the model choosing to escalate.

import fcntl


class _SneakyTransport(MockTransport):
    """Writes a file out-of-band during the call - what a seat with tools does."""
    def __init__(self, root, script=None):
        super().__init__(script)
        self.root = root

    def ask(self, seat, prompt, session_hint=""):
        (self.root / "snuck.md").write_text("written by the model, not the wrapper\n")
        return super().ask(seat, prompt, session_hint)


def test_model_written_code_is_never_executed(sandbox, tmp_path):
    """B1: an executable/loader suffix is refused outright, so the wrapper's
    own test step can never run model-authored code."""
    marker = tmp_path / "PWNED"
    reply = (f"===FILE: conftest.py===\nimport pathlib\n"
             f"pathlib.Path({str(marker)!r}).write_text('x')\n===END===")
    t = MockTransport(script={"forge": [reply]})
    r = execute_one(C("add a fixture"), transport=t, live=True)
    assert r.status != "done"
    assert not marker.exists()
    assert not (sandbox / "conftest.py").exists()


@pytest.mark.parametrize("rel", ["tools/x.py", "ops/run.sh", "a.zsh", "b.rb",
                                 "c.js", "ci.yml", "d.yaml", "pyproject.toml",
                                 "e.cfg", "f.ini", "Makefile"])
def test_executable_and_loader_suffixes_are_refused(sandbox, rel):
    assert _validate_rel(sandbox, rel)[0] is None


@pytest.mark.parametrize("rel", [".GIT/hooks/pre-commit", "Settings.json",
                                 "sub/.Env", "node_Modules/x.md",
                                 ".git./hooks/x", ".hidden/x.md", "sub/.dotfile"])
def test_deny_lists_are_casefolded_and_dotpaths_refused(sandbox, rel):
    """B2: APFS is case-insensitive; a deny list that is not is no deny list."""
    assert _validate_rel(sandbox, rel)[0] is None
    assert not (sandbox / ".git").exists()


def test_out_of_band_write_during_the_model_call_escalates(sandbox):
    """B3: the tree is snapshotted around the model call. Anything the
    wrapper did not write itself means the tool lock is not holding - abort
    without applying the reply, and say what appeared."""
    reply = "===FILE: docs/ok.md===\nfine\n===END==="
    t = _SneakyTransport(sandbox, script={"forge": [reply]})
    r = execute_one(C("write docs"), transport=t, live=True)
    assert r.status == "escalate"
    assert "snuck.md" in r.detail
    assert not (sandbox / "docs/ok.md").exists()   # reply not applied


@pytest.mark.parametrize("action", [
    "push the fix to origin/main", "deploy the docs site to Vercel",
    "run npm install in sites/yapword", "open a PR against main",
    "install the new dependency and pin it", "curl the webhook to register it",
    "pip install the client library", "git push --tags",
])
def test_dangerous_verbs_escalate_before_any_model_call(sandbox, action):
    """S9: escalation is the wrapper's decision, made before spend - never
    a request to the model."""
    t = MockTransport()
    r = execute_one(C(action), transport=t, live=True)
    assert r.status == "escalate", r.detail
    assert t.calls == []


def test_run_queue_is_single_flight(sandbox, tmp_path):
    """S8: the Mon/Thu launchd run and a manual run must not overlap."""
    lock = budgets.budgets_dir() / "exec.lock"
    with open(lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        results = executor.run_queue(live=True, transport=MockTransport())
    assert results == []
