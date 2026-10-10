"""The person as data: seats/PROFILE.json is the source of truth USER.md is
rendered from. These tests pin the loader's contract: names are tolerant
(case, hyphens, spaces), unknown traits warn but never fail, bad numbers fail,
and a facet given twice with different values is a hard error rather than a
silent preference."""
import json
from pathlib import Path

import pytest

from caduceus import profile

ROOT = Path(__file__).resolve().parent.parent


def _write(tmp_path, body):
    p = tmp_path / "PROFILE.json"
    p.write_text(json.dumps(body))
    return p


GOOD = {"schema": "caduceus.profile.v1",
        "person": {"name": "T", "handle": "t"},
        "archetypes": {"best": "Shaper", "secondary": [], "least_like": ["Implementer"]},
        "traits": {"Composed": {"pct": 99, "facets": {"Calm": 98}},
                   "Organized": {"pct": 26},
                   "Detail-Oriented": {"pct": 34, "confidence": 0.5}}}


def test_load_and_lookup(tmp_path):
    p = profile.load(_write(tmp_path, GOOD))
    assert p.pct("Composed") == 99 and p.pct("calm") == 98
    assert p.pct("detail-oriented") == 34 and p.pct("Detail oriented") == 34
    assert p.pct("Humorous") is None
    assert p.confidence("Detail-Oriented") == 0.5 and p.confidence("Organized") == 1.0
    assert p.least_like == ["Implementer"] and p.best_archetype == "Shaper"
    assert len(p.sha256) == 64 and p.warnings == []


def test_unknown_trait_warns_not_fails(tmp_path):
    body = dict(GOOD)
    body["traits"] = dict(GOOD["traits"], Moxie={"pct": 50})
    p = profile.load(_write(tmp_path, body))
    assert any("Moxie" in w for w in p.warnings)


def test_bad_pct_fails(tmp_path):
    body = dict(GOOD)
    body["traits"] = {"Organized": {"pct": 126}}
    with pytest.raises(profile.ProfileError):
        profile.load(_write(tmp_path, body))


def test_wrong_schema_fails(tmp_path):
    body = dict(GOOD)
    body["schema"] = "something.else"
    with pytest.raises(profile.ProfileError):
        profile.load(_write(tmp_path, body))


def test_conflicting_facet_raises(tmp_path):
    body = dict(GOOD)
    body["traits"] = {"Composed": {"pct": 99, "facets": {"Calm": 98}}, "Calm": {"pct": 50}}
    with pytest.raises(profile.ProfileError):
        profile.load(_write(tmp_path, body))


def test_same_value_twice_is_tolerated(tmp_path):
    body = dict(GOOD)
    body["traits"] = {"Composed": {"pct": 99, "facets": {"Calm": 98}}, "Calm": {"pct": 98}}
    assert profile.load(_write(tmp_path, body)).pct("Calm") == 98


def test_alex_profile_loads_clean():
    p = profile.load(ROOT / "seats" / "PROFILE.json")
    assert p.pct("Organized") == 26 and p.pct("Direct") == 94 and p.warnings == []
    assert p.best_archetype == "Shaper" and "Implementer" in p.least_like


def test_taxonomy_is_twelve_by_three_plus_five():
    t = profile.taxonomy()
    traits = {k: v for k, v in t.items() if v}
    independent = [k for k, v in t.items() if not v]
    assert len(traits) == 12 and all(len(v) == 3 for v in traits.values())
    assert len(independent) == 5


def test_non_numeric_confidence_is_profile_error(tmp_path):
    body = dict(GOOD)
    body["traits"] = {"Organized": {"pct": 26, "confidence": "high"}}
    with pytest.raises(profile.ProfileError):
        profile.load(_write(tmp_path, body))
