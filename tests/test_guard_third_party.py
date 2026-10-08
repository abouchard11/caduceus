"""Third-party repository rule.

Alex, 2026-10-08: "I do not want Hermes touching stuff like this." - after a
seat force-pushed (with --force-with-lease, which the force-push rule exempts)
and commented on his pull request in typescript-eslint.
"""
import io
import json
import subprocess
import sys

import pytest

from caduceus import guard


def payload(cmd, cwd=None):
    p = {"hook_event_name": "pre_tool_call", "tool_name": "terminal",
         "tool_input": {"command": cmd}, "session_id": "t"}
    if cwd is not None:
        p["cwd"] = str(cwd)
    return p


def clone(tmp_path, name, **remotes):
    d = tmp_path / name
    d.mkdir()
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    for remote, url in remotes.items():
        subprocess.run(["git", "-C", str(d), "remote", "add", remote, url], check=True)
    return d


@pytest.fixture
def fork(tmp_path):
    """A fork that backs an upstream pull request."""
    return clone(tmp_path, "typescript-eslint",
                 origin="https://github.com/abouchard11/typescript-eslint.git",
                 upstream="https://github.com/typescript-eslint/typescript-eslint.git")


@pytest.fixture
def own(tmp_path):
    return clone(tmp_path, "dozen", origin="https://github.com/abouchard11/dozen.git")


@pytest.fixture
def infra(tmp_path):
    """Upstream checkout that also pushes to a repo of Alex's own."""
    return clone(tmp_path, "graphiti",
                 origin="https://github.com/getzep/graphiti.git",
                 fork="git@github.com:abouchard11/graphiti.git",
                 backup="https://github.com/abouchard11/graphiti-local.git")


def blocked(cmd, cwd=None):
    code, out = guard.decide(payload(cmd, cwd))
    return code == 2 and out["decision"] == "block" and "third-party" in out["reason"]


def allowed(cmd, cwd=None):
    code, _ = guard.decide(payload(cmd, cwd))
    return code == 0


# ------------------------------------------------------------ explicit targets

@pytest.mark.parametrize("cmd", [
    "gh pr comment 12889 --repo typescript-eslint/typescript-eslint --body 'Re-requesting review'",
    "gh pr edit 12889 -R typescript-eslint/typescript-eslint --base some-branch",
    "gh pr create --repo typescript-eslint/typescript-eslint --head abouchard11:feat/x --title t --body b",
    "gh pr close 12889 --repo=typescript-eslint/typescript-eslint",
    "gh pr review 116 --repo ActivityWatch/aw-client --approve",
    "gh pr comment https://github.com/ActivityWatch/aw-client/pull/116 --body 'Re-verified'",
    "gh issue comment 11694 --repo typescript-eslint/typescript-eslint --body hi",
    "gh issue create -R dabit3/jev-experiments --title t --body b",
    "gh api -X POST repos/typescript-eslint/typescript-eslint/issues/12889/comments -f body=hi",
    "gh api --method PATCH /repos/typescript-eslint/typescript-eslint/pulls/12889 -f base=main",
    "gh api repos/typescript-eslint/typescript-eslint/pulls/12889/requested_reviewers -f 'reviewers[]=someone'",
    "curl -X POST https://api.github.com/repos/getzep/graphiti/issues/1697/comments -d '{\"body\":\"hi\"}'",
    "git push https://github.com/typescript-eslint/typescript-eslint.git main",
])
def test_writes_to_repos_alex_does_not_own_are_blocked(cmd):
    assert blocked(cmd), cmd


@pytest.mark.parametrize("cmd", [
    "gh pr comment 22 --repo abouchard11/dozen --body done",
    "gh pr create --repo abouchard11/caduceus --title t --body b",
    "gh pr merge 22 -R AbouChard11/dozen --squash",
    "gh api -X POST repos/abouchard11/hq/issues/1/comments -f body=hi",
    "gh issue create --repo abouchard11/hq --title t --body b",
])
def test_writes_to_his_own_repos_pass(cmd):
    assert allowed(cmd), cmd


@pytest.mark.parametrize("cmd", [
    "gh pr view 12978 --repo typescript-eslint/typescript-eslint --json state",
    "gh pr list --repo typescript-eslint/typescript-eslint --author abouchard11",
    "gh pr checks 116 --repo ActivityWatch/aw-client",
    "gh pr diff 12978 -R typescript-eslint/typescript-eslint",
    "gh issue view 11694 --repo typescript-eslint/typescript-eslint --comments",
    "gh api repos/typescript-eslint/typescript-eslint/pulls/12978",
    "gh api -X GET search/issues -f q='author:abouchard11 type:pr'",
    "gh api repos/typescript-eslint/typescript-eslint/issues/12978/timeline --paginate --jq '.[].event'",
    "curl -s https://api.github.com/repos/getzep/graphiti/pulls/1949",
    "git clone https://github.com/typescript-eslint/typescript-eslint.git",
])
def test_reading_other_peoples_repos_passes(cmd):
    assert allowed(cmd), cmd


# ------------------------------------------------- targets resolved from the clone

def test_the_incident_force_push_to_the_fork_behind_an_upstream_pr(fork):
    cmd = f"cd {fork} && git push --force-with-lease origin feat/await-thenable-maybe-promise-arrays"
    assert blocked(cmd)


def test_plain_push_to_that_fork_is_blocked_too(fork):
    assert blocked(f"cd {fork} && git push origin feat/x")
    assert blocked(f"cd {fork} && git push -u origin feat/x")
    assert blocked(f"cd {fork} && git push")
    assert blocked(f"git -C {fork} push origin feat/x")
    assert blocked("git push origin feat/x", cwd=fork)
    assert blocked(f"cd {fork} && git add -A && git commit -m wip && git push origin HEAD")


def test_gh_without_a_repo_flag_is_judged_by_the_clone(fork, own):
    assert blocked("gh pr comment 12889 --body 'Re-requesting review'", cwd=fork)
    assert blocked(f"cd {fork} && gh pr create --fill")
    assert blocked(f"cd {fork} && gh api -X POST repos/{{owner}}/{{repo}}/issues/1/comments -f body=x")
    assert allowed("gh pr comment 22 --body done", cwd=own)
    assert allowed(f"cd {own} && gh pr create --fill")


def test_an_explicit_own_repo_flag_wins_inside_a_fork_clone(fork):
    assert allowed("gh pr comment 1 --repo abouchard11/typescript-eslint --body note", cwd=fork)


def test_his_own_repos_push_normally(own):
    assert allowed(f"cd {own} && git push origin main")
    assert allowed(f"cd {own} && git push")
    assert allowed("git push -u origin feat/x", cwd=own)


def test_upstream_checkout_that_also_pushes_to_his_own_repo(infra):
    assert allowed(f"cd {infra} && git push backup main")          # abouchard11/graphiti-local
    assert blocked(f"cd {infra} && git push fork feat/x")          # abouchard11/graphiti backs getzep PRs
    assert blocked(f"cd {infra} && git push origin feat/x")        # getzep/graphiti itself
    assert blocked(f"cd {infra} && git push")                      # ambiguous: name the remote


def test_local_work_in_a_fork_clone_is_not_blocked(fork):
    for cmd in ["git status", "git fetch upstream", "git log --oneline -5",
                "git commit -m 'wip'", "git checkout -b feat/y", "pnpm test"]:
        assert allowed(f"cd {fork} && {cmd}"), cmd


def test_cd_later_in_the_command_is_followed(fork, own):
    assert blocked(f"cd {own} && git status && cd {fork} && git push origin feat/x")
    assert allowed(f"cd {fork} && git status && cd {own} && git push origin main")


def test_unknown_directory_does_not_block():
    assert allowed("cd /nonexistent/place && git push origin main")
    assert allowed("git push origin main")          # no cwd in the payload, nothing to judge


# ------------------------------------------------------------------- semantics

def test_no_token_overrides_it(fork):
    cmd = f"cd {fork} && git push origin feat/x"
    guard.grant(cmd, grantor="finisher")
    try:
        assert blocked(cmd)
    finally:
        guard.consume_token(cmd)


def test_the_block_message_does_not_invite_a_workaround(fork):
    _, out = guard.decide(payload(f"cd {fork} && git push origin feat/x"))
    assert "Find another way" not in out["reason"]
    assert "Alex" in out["reason"]


def test_a_destructive_critical_still_reports_itself():
    _, out = guard.decide(payload("rm -rf / ; gh pr comment 1 --repo typescript-eslint/typescript-eslint -b x"))
    assert "rm-root" in out["reason"]


def test_evaluate_reports_the_rule_for_cad_guard_test(fork):
    rule = guard.evaluate(f"cd {fork} && git push origin feat/x")
    assert rule is not None and rule.severity == "CRITICAL" and rule.name == "third-party-repo"


# ------------------------------------------- the operator's own profile: this rule only

def test_only_third_party_skips_the_destructive_rules(fork):
    code, out = guard.decide(payload("rm -rf build"), only="third-party")
    assert code == 0 and out is None
    code, out = guard.decide(payload("git push --force origin main"), only="third-party")
    assert code == 0 and out is None
    code, out = guard.decide(payload(f"cd {fork} && git push origin feat/x"), only="third-party")
    assert code == 2 and "third-party" in out["reason"]


def test_hook_main_only_flag(fork, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload("rm -rf build"))))
    assert guard.hook_main(only="third-party") == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        payload("gh pr comment 1 --body x", cwd=fork))))
    assert guard.hook_main(only="third-party") == 2
    assert "third-party" in capsys.readouterr().out


# ------------------------------------------------------------- near misses

def test_commands_that_only_look_like_a_push_or_a_write(fork):
    for cmd in ["git stash push -m wip", "git log --grep push", "git config push.default simple",
                "gh pr view 1 --json comments", "gh pr checkout 12889", "gh pr status",
                "gh repo view typescript-eslint/typescript-eslint", "gh run list"]:
        assert allowed(f"cd {fork} && {cmd}"), cmd


def test_separators_inside_a_quoted_body_do_not_hide_the_repo_flag():
    assert blocked("gh pr comment 1 --body 'fixed; see a | b && c' --repo typescript-eslint/typescript-eslint")
    assert allowed("gh pr comment 1 --body 'fixed; see a | b && c' --repo abouchard11/dozen")


def test_gh_repo_env_names_the_target():
    assert blocked("GH_REPO=typescript-eslint/typescript-eslint gh pr comment 1 --body x")


def test_subshell_and_relative_cd(fork):
    assert blocked(f"(cd {fork} && git push origin feat/x)")
    assert blocked(f"cd {fork.parent} && cd typescript-eslint && git push origin feat/x")
