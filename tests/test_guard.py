import json

from caduceus import guard


def payload(cmd):
    return {"hook_event_name": "pre_tool_call", "tool_name": "terminal",
            "tool_input": {"command": cmd}, "session_id": "t"}


def test_critical_blocks_always():
    code, out = guard.decide(payload("rm -rf /"))
    assert code == 2
    assert out["decision"] == "block"
    assert "CRITICAL" in out["reason"] or "No override" in out["reason"]


def test_critical_variants():
    for cmd in ["sudo rm -rf / --no-preserve-root",
                "mkfs.ext4 /dev/sda1",
                "dd if=/dev/zero of=/dev/disk0",
                "shutdown -h now"]:
        rule = guard.evaluate(cmd)
        assert rule is not None, cmd
        assert rule.severity in ("CRITICAL", "HIGH"), cmd


def test_high_held_then_token_flow():
    cmd = "git push --force origin main"
    code, out = guard.decide(payload(cmd))
    assert code == 2
    assert "Two-person" in out["reason"]
    # grant and retry
    guard.grant(cmd, grantor="finisher")
    code, out = guard.decide(payload(cmd))
    assert code == 0 and out is None
    # token was single-use
    code, out = guard.decide(payload(cmd))
    assert code == 2


def test_force_with_lease_not_flagged_as_force():
    rule = guard.evaluate("git push --force-with-lease origin main")
    assert rule is None or rule.severity != "HIGH"


def test_safe_commands_pass():
    for cmd in ["ls -la", "git status", "python3 -m pytest",
                "grep -r foo src/", "git push origin main",
                "rm notes.txt", "npm run build"]:
        code, out = guard.decide(payload(cmd))
        assert code == 0, cmd


def test_warn_annotates_but_allows():
    code, out = guard.decide(payload("chmod -R 777 ./public"))
    assert code == 0
    assert out and "context" in out


def test_nested_extraction():
    p = {"tool_input": {"args": {"command": "git reset --hard HEAD~5"}},
         "session_id": "t"}
    code, out = guard.decide(p)
    assert code == 2


def test_expired_token_rejected(monkeypatch):
    cmd = "git clean -fdx"
    guard.grant(cmd, grantor="alex", ttl=-1)
    assert guard.check_token(cmd) is None
    code, _ = guard.decide(payload(cmd))
    assert code == 2


def test_hook_main_protocol(capsys, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload("rm -rf ~"))))
    code = guard.hook_main()
    assert code == 2
    printed = capsys.readouterr().out
    assert json.loads(printed)["decision"] == "block"


def test_malformed_stdin_fails_open(monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert guard.hook_main() == 0
