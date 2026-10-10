"""Casting: the gap vector selects archetypes; the five hand-written seats
are the golden output for Alex's own profile. Synthetic vectors exercise the
unstaffed archetypes, the fill-to-four floor, the cap-at-six ceiling, and the
confidence gate that makes inferred gaps cast weaker than measured ones."""
import json
from pathlib import Path

from caduceus import archetypes, compile as comp, profile

ROOT = Path(__file__).resolve().parent.parent


def _p(tmp_path, traits, least_like=()):
    body = {"schema": "caduceus.profile.v1", "person": {"name": "x", "handle": "x"},
            "archetypes": {"best": "", "secondary": [], "least_like": list(least_like)},
            "traits": {k: ({"pct": v} if isinstance(v, int) else v) for k, v in traits.items()}}
    p = tmp_path / "P.json"
    p.write_text(json.dumps(body))
    return profile.load(p)


def test_golden_alex_is_the_five():
    p = profile.load(ROOT / "seats" / "PROFILE.json")
    c = comp.cast(p)
    assert [s.seat for s in c.seats] == ["forge", "finisher", "recon", "sparring", "envoy"]
    assert all(s.fired for s in c.seats)
    # forge and envoy share the qwen family: a warning is expected and never blocks
    assert any('qwen' in w for w in c.warnings)


def test_fill_to_four_when_nothing_fires(tmp_path):
    p = _p(tmp_path, {"Organized": 80, "Detail-oriented": 80, "Curious": 50, "Creative": 50,
                      "Original": 50, "Direct": 50, "Empathetic": 80, "Practical": 80,
                      "Systematic": 80, "Leadership": 80, "Composed": 80, "Determined": 80})
    c = comp.cast(p)
    assert len(c.seats) == 4 and not any(s.fired for s in c.seats)


def test_cap_at_six_keeps_largest_margin(tmp_path):
    p = _p(tmp_path, {"Organized": 10, "Detail-oriented": 10, "Curious": 95, "Creative": 10,
                      "Original": 10, "Direct": 95, "Empathetic": 10, "Practical": 10,
                      "Systematic": 10, "Leadership": 10, "Composed": 10, "Determined": 10},
           least_like=["Implementer", "Shaper"])
    c = comp.cast(p)
    assert len(c.seats) == 6 and all(s.fired for s in c.seats)


def test_confidence_gate_needs_ten_more(tmp_path):
    p = _p(tmp_path, {"Organized": {"pct": 38, "confidence": 0.5}, "Detail-oriented": 80})
    keys = {s.key for s in comp.cast(p).seats if s.fired}
    assert "completer_finisher" not in keys
    p2 = _p(tmp_path, {"Organized": {"pct": 28, "confidence": 0.5}, "Detail-oriented": 80})
    assert "completer_finisher" in {s.key for s in comp.cast(p2).seats if s.fired}


def test_synthetic_fires_unstaffed(tmp_path):
    p = _p(tmp_path, {"Creative": 20, "Systematic": 20, "Composed": 20, "Determined": 20})
    keys = {s.key for s in comp.cast(p).seats if s.fired}
    assert {"plant", "coordinator", "anchor", "driver"} <= keys


def test_library_has_nine_unique_seats():
    seats = [a.seat for a in archetypes.LIBRARY]
    assert len(seats) == 9 and len(set(seats)) == 9
    assert all(a.soul_template.strip() for a in archetypes.LIBRARY)


def test_seat_for_existing_and_fabricated():
    assert comp.seat_for("completer_finisher").name == "finisher"
    s = comp.seat_for("anchor")
    assert s.name == "anchor" and s.provider == "openrouter" and s.domains


def test_cast_json_shape():
    p = profile.load(ROOT / "seats" / "PROFILE.json")
    j = comp.cast(p).to_json()
    assert j["schema"] == "caduceus.cast.v1" and len(j["cast_sha256"]) == 64
    assert {"key", "seat", "display", "fired", "margin", "reason"} <= set(j["seats"][0])
