"""Loadouts: Jev scores every skill against every seat×domain pair offline
(the second Jev slot), a proposal takes the top N per pair after the
denylist, and the answer cache means a rerun never re-spends. Install and
uninstall live in the same module and are tested further down."""
import json
from pathlib import Path

from caduceus import compile as comp, config, loadout, manifest, profile

ROOT = Path(__file__).resolve().parent.parent


def _cast():
    return comp.cast(profile.load(ROOT / "seats" / "PROFILE.json"))


def _entry(name, desc="d", cat="c"):
    return manifest.Entry(name=name, description=desc, root="r", path=f"/x/{name}/SKILL.md",
                          category=cat, user_invoked=False, sha256=("ab" * 32),
                          empty_description=not desc)


class ScoreClient:
    """Level 4 for names containing 'good', else level 1; counts calls and tokens."""

    def __init__(self):
        self.calls = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0}

    def ask(self, state, questions):
        self.calls += 1
        self.usage["input_tokens"] += 1000
        lvl = 4 if "good" in state["name"] else 1
        return {k: {"type": "score", "score": float(lvl), "confidence": 0.9,
                    "probabilities": {str(lvl): 1.0}} for k in questions}


def test_questions_cover_cast_times_domains():
    q = loadout.build_questions(_cast())
    assert len(q) == 5 * len(loadout.DOMAINS)
    assert loadout.DOMAINS == list(config.DOMAIN_KEYWORDS) + ["general"]
    assert q["finisher__review"]["type"] == "score"
    assert q["finisher__review"]["criteria"] == loadout.LEVELS and len(loadout.LEVELS) == 5
    assert "FINISHER" in q["finisher__review"]["instructions"]
    assert "review" in q["finisher__review"]["instructions"]


def test_score_and_propose_top_per_with_denylist(tmp_path):
    entries = [_entry("good-a"), _entry("good-b"), _entry("send-good"), _entry("meh")]
    cache = loadout.Cache(tmp_path / "cache.json")
    client = ScoreClient()
    sc = loadout.score_skills(entries, _cast(), client, cache)
    assert sc.calls == 4 and sc.est_usd > 0 and sc.stopped_reason == ""
    assert sc.by_skill["good-a"][("finisher", "review")] == (4.0, 0.9)
    deny = manifest.Denylist.load(ROOT)
    prop = loadout.propose(sc, _cast(), deny, per=2)
    assert prop["schema"] == "caduceus.loadout.v1" and prop["per"] == 2
    assert prop["cast_sha256"] == _cast().sha256
    names = [x["name"] for x in prop["seats"]["finisher"]["review"]]
    assert names == ["good-a", "good-b"]
    assert "send-good" in prop["denied"] and "meh" not in names
    assert set(prop["seats"]) == {"forge", "finisher", "recon", "sparring", "envoy"}
    assert set(prop["seats"]["forge"]) == set(loadout.DOMAINS)


def test_cache_hit_makes_zero_calls(tmp_path):
    entries = [_entry("good-a")]
    cache = loadout.Cache(tmp_path / "cache.json")
    loadout.score_skills(entries, _cast(), ScoreClient(), cache)
    cache.save()
    c2 = ScoreClient()
    sc = loadout.score_skills(entries, _cast(), c2, loadout.Cache(tmp_path / "cache.json"))
    assert c2.calls == 0 and sc.by_skill["good-a"][("forge", "general")] == (4.0, 0.9)


def test_cache_misses_when_description_changes(tmp_path):
    cache = loadout.Cache(tmp_path / "cache.json")
    loadout.score_skills([_entry("good-a")], _cast(), ScoreClient(), cache)
    cache.save()
    changed = manifest.Entry("good-a", "new text", "r", "/x/good-a/SKILL.md", "c", False, "cd" * 32, False)
    c2 = ScoreClient()
    loadout.score_skills([changed], _cast(), c2, loadout.Cache(tmp_path / "cache.json"))
    assert c2.calls == 1


def test_max_usd_stops(tmp_path):
    entries = [_entry(f"good-{i}") for i in range(50)]
    sc = loadout.score_skills(entries, _cast(), ScoreClient(), loadout.Cache(tmp_path / "c.json"),
                              max_usd=0.0001)
    assert sc.stopped_reason == "max_usd" and 0 < sc.calls < 50


def test_dry_run_makes_no_calls(tmp_path):
    c = ScoreClient()
    sc = loadout.score_skills([_entry("a"), _entry("b")], _cast(), c,
                              loadout.Cache(tmp_path / "c.json"), dry_run=True)
    assert c.calls == 0 and sc.calls == 0 and sc.planned == 2 and sc.by_skill == {}


def test_bad_answer_for_one_skill_is_skipped_not_fatal(tmp_path):
    class Flaky(ScoreClient):
        def ask(self, state, questions):
            if state["name"] == "bad":
                from caduceus.jev import JevError
                raise JevError("boom")
            return super().ask(state, questions)
    sc = loadout.score_skills([_entry("good-a"), _entry("bad")], _cast(), Flaky(),
                              loadout.Cache(tmp_path / "c.json"))
    assert "good-a" in sc.by_skill and "bad" not in sc.by_skill and sc.errors == ["bad: JevError: boom"]


# ---- Task 9: install / uninstall / status / clock ---------------------------

def _mani_with(tmp_path, names):
    root = tmp_path / "skills"
    for n in names:
        d = root / "cat" / n
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {n}\ndescription: x\n---\n")
        (d / "extra.md").write_text("payload")
    return manifest.scan(roots=[("t", root, 3)])


def _profile_dirs():
    for s in ["forge", "finisher", "recon", "sparring", "envoy"]:
        (config.hermes_home() / "profiles" / s).mkdir(parents=True, exist_ok=True)


def _table(seats):
    return {"schema": "caduceus.loadout.v1", "seats": seats}


def test_load_table_accepts_strings_and_objects(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(_table({"finisher": {"review": ["a", {"name": "b", "score": 3}]}})))
    t = loadout.load_table(p)
    assert t["seats"]["finisher"]["review"] == ["a", "b"]


def test_plan_install_precedence_and_cap():
    table = _table({"finisher": {
        "general": [f"g{i}" for i in range(5)], "review": [f"r{i}" for i in range(5)],
        "testing": [f"t{i}" for i in range(5)], "comms": [f"c{i}" for i in range(5)]}})
    plan = loadout.plan_install(table, _cast(), cap=12)
    assert plan["finisher"][:5] == [f"r{i}" for i in range(5)]      # finisher's first prior domain
    assert plan["finisher"][5:10] == [f"t{i}" for i in range(5)]    # then testing (also a prior)
    assert len(plan["finisher"]) == 12 and "c4" not in plan["finisher"]
    assert plan.get("forge", []) == []


def test_plan_install_dedups_across_domains():
    table = _table({"finisher": {"review": ["a", "b"], "testing": ["b", "c"]}})
    assert loadout.plan_install(table, _cast(), cap=15)["finisher"] == ["a", "b", "c"]


def test_install_uninstall_only_recorded(tmp_path):
    _profile_dirs()
    mani = _mani_with(tmp_path, ["r0", "r1"])
    res = loadout.install(_table({"finisher": {"review": ["r0", "r1", "ghost"]}}), _cast(), mani)
    pd = config.hermes_home() / "profiles" / "finisher" / "skills"
    assert (pd / "loadout" / "r0" / "SKILL.md").exists() and (pd / "loadout" / "r0" / "extra.md").exists()
    assert res["finisher"]["installed"] == ["r0", "r1"] and res["finisher"]["missing"] == ["ghost"]
    rec = json.loads((pd / "loadout" / loadout.RECORD).read_text())
    assert set(rec["installed"]) == {"r0", "r1"} and len(rec["installed"]["r0"]) == 64
    (pd / "productivity" / "hand").mkdir(parents=True)
    (pd / "productivity" / "hand" / "SKILL.md").write_text("x")
    (pd / "loadout" / "manual").mkdir(parents=True)
    assert loadout.first_install_ts() is not None
    removed = loadout.uninstall()
    assert removed == {"finisher": 2}
    assert not (pd / "loadout" / "r0").exists() and (pd / "loadout" / "manual").exists()
    assert (pd / "productivity" / "hand" / "SKILL.md").exists()
    assert not (pd / "loadout" / loadout.RECORD).exists()
    assert loadout.uninstall() == {}


def test_install_is_idempotent_and_refreshes_changed_source(tmp_path):
    _profile_dirs()
    mani = _mani_with(tmp_path, ["r0"])
    t = _table({"finisher": {"review": ["r0"]}})
    loadout.install(t, _cast(), mani)
    (tmp_path / "skills" / "cat" / "r0" / "SKILL.md").write_text("---\nname: r0\ndescription: changed\n---\n")
    mani2 = manifest.scan(roots=[("t", tmp_path / "skills", 3)])
    res = loadout.install(t, _cast(), mani2)
    pd = config.hermes_home() / "profiles" / "finisher" / "skills" / "loadout"
    assert "changed" in (pd / "r0" / "SKILL.md").read_text() and res["finisher"]["installed"] == ["r0"]


def test_missing_skill_source_skipped(tmp_path):
    _profile_dirs()
    mani = _mani_with(tmp_path, ["r0"])
    import shutil
    shutil.rmtree(tmp_path / "skills" / "cat" / "r0")
    res = loadout.install(_table({"finisher": {"review": ["r0"]}}), _cast(), mani)
    assert res["finisher"]["installed"] == [] and res["finisher"]["missing"] == ["r0"]


def test_install_skips_absent_profile(tmp_path):
    mani = _mani_with(tmp_path, ["r0"])
    res = loadout.install(_table({"finisher": {"review": ["r0"]}}), _cast(), mani)
    assert res["finisher"]["skipped"] == "profile missing" and res["finisher"]["installed"] == []
    assert loadout.first_install_ts() is None


def test_status_and_clock(tmp_path):
    _profile_dirs()
    mani = _mani_with(tmp_path, ["r0"])
    assert loadout.status()["first_install_ts"] is None
    loadout.install(_table({"finisher": {"review": ["r0"]}}), _cast(), mani)
    st = loadout.status()
    assert st["seats"]["finisher"]["installed"] == 1 and st["seats"]["forge"]["installed"] == 0
    t0 = st["first_install_ts"]
    assert t0 is not None
    loadout.install(_table({"finisher": {"review": ["r0"]}}), _cast(), mani)
    assert loadout.first_install_ts() == t0                      # never moves on its own
    loadout.mark_first_install(ts=123.0, force=True)
    assert loadout.first_install_ts() == 123.0


# ---- security review 2026-10-10: names are untrusted path components -------

def test_install_rejects_traversal_names(tmp_path):
    _profile_dirs()
    mani = _mani_with(tmp_path, ["r0"])
    outside = config.hermes_home() / "profiles" / "finisher" / "skills" / "productivity"
    outside.mkdir(parents=True)
    (outside / "keep.txt").write_text("x")
    res = loadout.install(_table({"finisher": {"review": ["../productivity", "r0", ".", "..", "a/b"]}}),
                          _cast(), mani)
    assert res["finisher"]["installed"] == ["r0"]
    assert set(res["finisher"]["missing"]) == {"../productivity", ".", "..", "a/b"}
    assert (outside / "keep.txt").exists()


def test_uninstall_ignores_bad_record_keys(tmp_path):
    _profile_dirs()
    pd = config.hermes_home() / "profiles" / "finisher" / "skills"
    (pd / "loadout").mkdir(parents=True)
    (pd / "productivity" / "victim").mkdir(parents=True)
    (pd / "loadout" / loadout.RECORD).write_text(json.dumps(
        {"installed": {"../productivity/victim": "0" * 64, "..": "0" * 64}}))
    assert loadout.uninstall() == {"finisher": 0}
    assert (pd / "productivity" / "victim").is_dir()


def test_copy_preserves_symlinks_and_skips_secrets(tmp_path):
    _profile_dirs()
    root = tmp_path / "skills"
    d = root / "cat" / "linky"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: linky\ndescription: d\n---\n")
    secret = tmp_path / "outside-secret.txt"
    secret.write_text("TOP")
    (d / "link.txt").symlink_to(secret)
    (d / ".env").write_text("KEY=1")
    (d / "cert.pem").write_text("pem")
    mani = manifest.scan(roots=[("t", root, 3)])
    loadout.install(_table({"finisher": {"review": ["linky"]}}), _cast(), mani)
    dst = config.hermes_home() / "profiles" / "finisher" / "skills" / "loadout" / "linky"
    assert (dst / "link.txt").is_symlink()
    assert not (dst / ".env").exists() and not (dst / "cert.pem").exists()


def test_cache_saves_periodically_during_scoring(tmp_path):
    cache = loadout.Cache(tmp_path / "c.json")
    loadout.score_skills([_entry(f"good-{i}") for i in range(5)], _cast(), ScoreClient(), cache,
                         save_every=2)
    assert (tmp_path / "c.json").exists() and len(json.loads((tmp_path / "c.json").read_text())) >= 4
