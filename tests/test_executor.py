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


# ------------------------------------------- a run that cannot start is not a success
# A scheduled `cad exec run --live` whose transport cannot run (the hermes
# binary is not found) printed one `error: transport: ...` line per selected
# item and exited 0, so the scheduler recorded a success while nothing ran.
#
# Exit-status contract, tested below:
#   exit 0  queue empty; dry run; any live run where an item was handled, ran
#           or failed for its own reasons (including a partial run)
#   exit 1  a live run that did no work because the transport could not run:
#           the binary is missing, or every selected item failed at the
#           transport. One FAILED line on stderr names the cause once.
#
# Nothing here can start a real process: transports are injected, or point at
# an absolute path that does not exist, and the Telegram receipt is stubbed.

from caduceus import cli, config, followup, hermes
from caduceus.hermes import OneshotTransport, SeatReply

MISSING_BIN = "/nonexistent-dir-for-tests/hermes"


def _queue(*actions):
    """Pending agent-owned commitments in the isolated ledger; returns ids."""
    f = followup.Followups()
    ids = [f.open("20261001-000000-abcdef", a, seat="forge", owner="agent", kind="do")
           for a in actions]
    f.close_conn()
    return ids


def _pending_ids():
    f = followup.Followups()
    try:
        return {c.id: c for c in f.pending()}
    finally:
        f.close_conn()


def _ok(text):
    return SeatReply("forge", text, True, "scripted")


def _fail(error):
    return SeatReply("forge", "", False, "scripted", error=error)


class _Scripted:
    """Stands in for OneshotTransport: canned replies, never spawns anything."""
    def __init__(self, replies):
        self.replies = list(replies)

    def ask(self, seat, prompt, session_hint=""):
        return self.replies.pop(0)


def _no_receipt(monkeypatch):
    monkeypatch.setattr(executor, "_notify", lambda results: None)


def _use_scripted(monkeypatch, *replies):
    _no_receipt(monkeypatch)
    t = _Scripted(replies)
    monkeypatch.setattr(executor, "OneshotTransport", lambda extra_args=None: t)
    return t


def _use_missing_binary(monkeypatch):
    """The real OneshotTransport, pointed at a binary that cannot exist."""
    _no_receipt(monkeypatch)
    monkeypatch.setattr(
        executor, "OneshotTransport",
        lambda extra_args=None: OneshotTransport(hermes_bin=MISSING_BIN,
                                                 extra_args=extra_args))


# -- the transport says whether it could start at all

def test_oneshot_marks_a_missing_binary_as_unavailable():
    reply = OneshotTransport(hermes_bin=MISSING_BIN).ask(config.SEATS["forge"], "hi")
    assert not reply.ok
    assert reply.unavailable
    assert "binary not found" in reply.error


def test_oneshot_call_that_started_and_failed_is_not_unavailable(monkeypatch):
    import subprocess

    def ran_and_failed(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="auth rejected")

    monkeypatch.setattr(hermes.subprocess, "run", ran_and_failed)
    reply = OneshotTransport(hermes_bin=MISSING_BIN).ask(config.SEATS["forge"], "hi")
    assert not reply.ok
    assert not reply.unavailable
    assert "auth rejected" in reply.error


def test_a_missing_binary_surfaces_on_the_exec_result(sandbox):
    r = execute_one(C("draft the glossary"),
                    transport=OneshotTransport(hermes_bin=MISSING_BIN), live=True)
    assert r.status == "error"
    assert r.unavailable
    assert "binary not found" in r.detail


# -- which result sets count as "the transport could not run"

_FAILING = [
    # every selected item failed at the transport
    [("error", "transport: timeout after 600s", False)],
    [("error", "transport: exit 1, empty output", False),
     ("error", "transport: exit 1, empty output", False)],
    # the binary is missing: that stands whatever else was selected
    [("error", "transport: hermes binary not found (hermes)", True),
     ("error", "transport: hermes binary not found (hermes)", True)],
    [("escalate", "'push' leaves the machine", False),
     ("error", "transport: hermes binary not found (hermes)", True)],
]
_FINE = [
    [],                                                         # nothing to do
    [("dry-run", "would draft", False)],
    [("done", "wrote docs/a.md", False), ("done", "wrote docs/b.md", False)],
    [("done", "wrote docs/a.md", False),                        # some ran, one
     ("error", "transport: timeout after 600s", False)],        # failed on its own
    [("escalate", "model escalated", False),
     ("error", "transport: timeout after 600s", False)],
    [("blocked", "pre-flight: daily cap", False),
     ("blocked", "pre-flight: daily cap", False)],
    [("escalate", "'deploy' leaves the machine", False)],
]


def _results(spec):
    return [ExecResult("id%d" % i, status, detail, unavailable=un)
            for i, (status, detail, un) in enumerate(spec)]


@pytest.mark.parametrize("spec", _FAILING)
def test_transport_failure_is_reported(spec):
    assert executor.transport_failure(_results(spec))


@pytest.mark.parametrize("spec", _FINE)
def test_other_outcomes_keep_the_existing_contract(spec):
    assert executor.transport_failure(_results(spec)) == ""


def test_transport_failure_names_a_shared_cause_once():
    cause = "hermes binary not found (hermes)"
    msg = executor.transport_failure(_results([
        ("error", "transport: " + cause, True), ("error", "transport: " + cause, True)]))
    assert msg.count(cause) == 1
    assert "2 of 2" in msg


def test_transport_failure_names_each_distinct_cause_once():
    msg = executor.transport_failure(_results([
        ("error", "transport: timeout after 600s", False),
        ("error", "transport: exit 1, empty output", False),
        ("error", "transport: timeout after 600s", False)]))
    assert msg.count("timeout after 600s") == 1
    assert msg.count("exit 1, empty output") == 1


# -- the command: exit status and the summary line

def test_exec_run_live_exits_nonzero_when_hermes_is_missing(sandbox, monkeypatch, capsys):
    ids = _queue("draft the glossary", "draft the style guide")
    _use_missing_binary(monkeypatch)

    with pytest.raises(SystemExit) as stop:
        cli.main(["exec", "run", "--live", "--max", "2"])

    assert stop.value.code == 1
    out, err = capsys.readouterr()
    for cid in ids:                                   # per-item lines still print
        assert f"[{cid}] error: transport: hermes binary not found" in out
    failed = [l for l in err.splitlines() if l.startswith("FAILED")]
    assert len(failed) == 1
    assert failed[0].count("hermes binary not found") == 1   # the cause, once
    # nothing was claimed, closed or flipped: both items are still queued
    pending = _pending_ids()
    assert all(i in pending and pending[i].owner == "agent" for i in ids)


def test_exec_run_live_exits_nonzero_when_every_item_fails_at_the_transport(
        sandbox, monkeypatch, capsys):
    _queue("draft the glossary", "draft the style guide")
    _use_scripted(monkeypatch, _fail("timeout after 600s"), _fail("timeout after 600s"))

    with pytest.raises(SystemExit) as stop:
        cli.main(["exec", "run", "--live"])

    assert stop.value.code == 1
    out, err = capsys.readouterr()
    assert out.count("error: transport: timeout after 600s") == 2
    assert err.count("timeout after 600s") == 1


def test_exec_run_live_exits_nonzero_for_a_missing_binary_beside_an_escalated_item(
        sandbox, monkeypatch, capsys):
    ids = _queue("push the notes to origin", "draft the glossary")
    _use_missing_binary(monkeypatch)

    with pytest.raises(SystemExit) as stop:
        cli.main(["exec", "run", "--live"])

    assert stop.value.code == 1
    out, err = capsys.readouterr()
    assert f"[{ids[0]}] escalate:" in out
    assert f"[{ids[1]}] error: transport: hermes binary not found" in out
    assert "1 of 2" in err


def test_exec_run_exit_stays_zero_when_the_queue_is_empty(sandbox, monkeypatch, capsys):
    _no_receipt(monkeypatch)
    assert cli.main(["exec", "run", "--live"]) == 0
    assert "staff queue empty" in capsys.readouterr().out


def test_exec_run_exit_stays_zero_for_a_dry_run(sandbox, monkeypatch, capsys):
    _queue("draft the glossary")
    _no_receipt(monkeypatch)

    def no_transport(*a, **k):
        raise AssertionError("a dry run must not build a transport")

    monkeypatch.setattr(executor, "OneshotTransport", no_transport)
    assert cli.main(["exec", "run"]) == 0
    out = capsys.readouterr().out
    assert "dry-run" in out


def test_exec_run_exit_stays_zero_when_every_item_is_escalated(sandbox, monkeypatch, capsys):
    _queue("push the notes to origin", "deploy the docs site")
    _no_receipt(monkeypatch)

    def no_transport(*a, **k):
        raise AssertionError("escalation is decided before any transport")

    monkeypatch.setattr(executor, "OneshotTransport", no_transport)
    assert cli.main(["exec", "run", "--live"]) == 0
    captured = capsys.readouterr()
    assert captured.out.count("escalate:") == 2
    assert "FAILED" not in captured.err


def test_exec_run_exit_stays_zero_when_some_items_ran(sandbox, monkeypatch, capsys):
    """One item done, one failed at the transport on its own: the existing
    contract is exit 0, with the failure on that item's line."""
    _queue("draft the glossary", "draft the style guide")
    _use_scripted(monkeypatch,
                  _ok("===FILE: docs/glossary.md===\nterms\n===END==="),
                  _fail("timeout after 600s"))

    assert cli.main(["exec", "run", "--live"]) == 0

    captured = capsys.readouterr()
    assert "done:" in captured.out
    assert "error: transport: timeout after 600s" in captured.out
    assert "FAILED" not in captured.err
    assert (sandbox / "docs/glossary.md").exists()
