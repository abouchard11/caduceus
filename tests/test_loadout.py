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
