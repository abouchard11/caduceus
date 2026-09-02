"""Tests for the FINISHER planted-defect eval harness.

Why this exists: the 08-19 council made FINISHER's model provisional on
third-party recall evidence. Deterministic scoring means Claude never grades
Claude — the matcher below is the whole point, so it is tested harder than
most modules in this repo. Written before caduceus/eval_finisher.py exists;
this file must fail on import until that module is written (TDD, red first).
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from caduceus import eval_finisher as ef
from caduceus import cli


# ---------------------------------------------------------------- fixtures

def _write_item(d: Path, item_id: str, text: str) -> None:
    (d / f"{item_id}.md").write_text(text)


@pytest.fixture
def tmp_items(tmp_path):
    d = tmp_path / "items"
    d.mkdir()
    return d


# ---------------------------------------------------------------- 1. validate_set

def test_validate_set_valid_set_returns_empty():
    items = {"A-01": "The plan guarantees results."}
    key = {
        "A-01": {
            "class": "A", "seeded": True,
            "defects": [{"id": "d1", "kind": "self-contradiction",
                         "anchor": "guarantees results", "section": "Recommendation",
                         "keywords": [["guarantee"], ["contradict"]]}],
        }
    }
    assert ef.validate_set(items, key) == []


def test_validate_set_flags_missing_item():
    items = {}
    key = {"A-01": {"class": "A", "seeded": False, "defects": []}}
    problems = ef.validate_set(items, key)
    assert any("A-01" in p for p in problems)


def test_validate_set_flags_item_with_no_key_entry():
    items = {"A-99": "orphan item"}
    key = {}
    problems = ef.validate_set(items, key)
    assert any("A-99" in p for p in problems)


def test_validate_set_flags_seeded_with_zero_defects():
    items = {"A-01": "some text"}
    key = {"A-01": {"class": "A", "seeded": True, "defects": []}}
    problems = ef.validate_set(items, key)
    assert any("A-01" in p and "defect" in p.lower() for p in problems)


def test_validate_set_flags_anchor_not_in_text():
    items = {"A-01": "the text has nothing to do with it"}
    key = {
        "A-01": {"class": "A", "seeded": True,
                 "defects": [{"id": "d1", "kind": "self-contradiction",
                              "anchor": "not present anywhere", "section": "x",
                              "keywords": [["a"], ["b"]]}]}
    }
    problems = ef.validate_set(items, key)
    assert any("d1" in p or "A-01" in p for p in problems)


def test_validate_set_flags_unknown_kind():
    items = {"A-01": "anchor phrase here"}
    key = {
        "A-01": {"class": "A", "seeded": True,
                 "defects": [{"id": "d1", "kind": "not-a-real-kind",
                              "anchor": "anchor phrase here", "section": "x",
                              "keywords": [["a"], ["b"]]}]}
    }
    problems = ef.validate_set(items, key)
    assert any("kind" in p.lower() for p in problems)


# ---------------------------------------------------------------- 2. parse_findings

def test_parse_findings_bare_array():
    raw = '[{"location": "L1", "kind": "k", "description": "d", "confidence": 0.9}]'
    findings, err = ef.parse_findings(raw)
    assert err is False
    assert findings == [{"location": "L1", "kind": "k", "description": "d", "confidence": 0.9}]


def test_parse_findings_fenced_json():
    raw = 'Here you go:\n```json\n[{"location": "L1", "kind": "k", "description": "d", "confidence": 0.5}]\n```\nthanks'
    findings, err = ef.parse_findings(raw)
    assert err is False
    assert len(findings) == 1
    assert findings[0]["location"] == "L1"


def test_parse_findings_wrapped_object():
    raw = '{"findings": [{"location": "L1", "kind": "k", "description": "d", "confidence": 0.1}]}'
    findings, err = ef.parse_findings(raw)
    assert err is False
    assert len(findings) == 1


def test_parse_findings_garbage_is_zero_findings_and_error():
    raw = "I refuse to output JSON today, sorry."
    findings, err = ef.parse_findings(raw)
    assert findings == []
    assert err is True


# ---------------------------------------------------------------- 3. match

def _defect(anchor="the anchor phrase", kind="self-contradiction",
            keywords=(("guarantee",), ("contradict", "collapse"))):
    return {"id": "d1", "kind": kind, "anchor": anchor, "section": "x",
            "keywords": [list(k) for k in keywords]}


def test_match_kind_equal_without_any_keyword_is_false():
    """Amended 2026-09-02: `kind` equality no longer counts - candidates never
    emit the KINDS vocabulary, and a bare label with no explanation is not
    detection. (Was: anchor + kind equal -> True.)"""
    finding = {"location": "the anchor phrase is here", "kind": "self-contradiction",
               "description": "irrelevant"}
    assert ef.match(finding, _defect()) is False


def test_match_anchor_wrong_kind_both_keyword_sets_hit_is_true():
    finding = {"location": "the anchor phrase is here",
               "kind": "totally-different-kind",
               "description": "this is a guarantee that will contradict itself"}
    assert ef.match(finding, _defect()) is True


def test_match_anchor_absent_is_false():
    finding = {"location": "nothing relevant", "kind": "self-contradiction",
               "description": "this is a guarantee that will contradict"}
    assert ef.match(finding, _defect()) is False


def test_match_anchor_and_one_keyword_set_is_true():
    """Amended 2026-09-02: one keyword set suffices. Requiring every set made a
    verbatim quote of the seeded text with a correct explanation in the
    model's own words score as a miss. (Was: only one set -> False.)"""
    finding = {"location": "the anchor phrase is here",
               "kind": "totally-different-kind",
               "description": "this is a guarantee but nothing else matches"}
    assert ef.match(finding, _defect()) is True


# ---------------------------------------------------------------- 4. score / aggregate

def _hand_built_key():
    return {
        "S-01": {
            "class": "A", "seeded": True,
            "defects": [
                {"id": "s1a", "kind": "self-contradiction", "anchor": "anchor-one",
                 "section": "x", "keywords": [["kw1"], ["kw2"]]},
                {"id": "s1b", "kind": "cost-mismatch", "anchor": "anchor-two",
                 "section": "x", "keywords": [["kw3"], ["kw4"]]},
            ],
        },
        "S-02": {
            "class": "A", "seeded": True,
            "defects": [
                {"id": "s2a", "kind": "verdict-bypass", "anchor": "anchor-three",
                 "section": "x", "keywords": [["kw5"], ["kw6"]]},
            ],
        },
        "C-01": {"class": "A", "seeded": False, "defects": []},
    }


def test_score_and_aggregate_single_pass_arithmetic():
    key = _hand_built_key()
    # findings catching 2 of 3 seeded defects, with one duplicate match and
    # one false positive, plus one false positive on the clean item.
    s01_findings = [
        {"location": "anchor-one here", "kind": "self-contradiction", "description": "kw1"},
        {"location": "anchor-one here", "kind": "self-contradiction", "description": "kw1"},  # duplicate -> FP
    ]
    s02_findings = [
        {"location": "anchor-three here", "kind": "verdict-bypass", "description": "kw5"},
    ]
    c01_findings = [
        {"location": "clean item noise", "kind": "self-contradiction", "description": ""},  # FP
    ]

    scores = [
        ef.score("S-01", s01_findings, key["S-01"]),
        ef.score("S-02", s02_findings, key["S-02"]),
        ef.score("C-01", c01_findings, key["C-01"]),
    ]

    agg = ef.aggregate(scores)
    assert agg["recall"] == pytest.approx(2 / 3)
    assert agg["precision"] == pytest.approx(2 / 3)
    assert agg["fp_rate"] == pytest.approx(1 / 1)


def test_aggregate_across_passes_mean_and_range():
    key = _hand_built_key()

    def pass_scores(n_catch_s01, n_fp_clean):
        s01_findings = []
        if n_catch_s01 >= 1:
            s01_findings.append({"location": "anchor-one here", "kind": "self-contradiction", "description": "kw1"})
        if n_catch_s01 >= 2:
            s01_findings.append({"location": "anchor-two here", "kind": "cost-mismatch", "description": "kw3"})
        s02_findings = [{"location": "anchor-three here", "kind": "verdict-bypass", "description": "kw5"}]
        c01_findings = [{"location": "noise", "kind": "self-contradiction", "description": ""}] * n_fp_clean
        return [
            ef.score("S-01", s01_findings, key["S-01"]),
            ef.score("S-02", s02_findings, key["S-02"]),
            ef.score("C-01", c01_findings, key["C-01"]),
        ]

    pass1 = pass_scores(1, 0)   # 2 of 3 caught, 0 clean FPs -> recall 2/3, fp_rate 0
    pass2 = pass_scores(2, 2)   # 3 of 3 caught, 2 clean FPs -> recall 3/3=1.0, fp_rate 2

    agg = ef.aggregate([pass1, pass2])
    assert agg["recall"]["mean"] == pytest.approx((2 / 3 + 1.0) / 2)
    assert agg["recall"]["min"] == pytest.approx(2 / 3)
    assert agg["recall"]["max"] == pytest.approx(1.0)
    assert agg["fp_rate"]["mean"] == pytest.approx((0 + 2) / 2)
    assert agg["fp_rate"]["min"] == pytest.approx(0)
    assert agg["fp_rate"]["max"] == pytest.approx(2)


# ---------------------------------------------------------------- 5. build_messages

def test_build_messages_never_leaks_key_and_carries_soul_and_contract():
    item_text = "# Some artifact\n\nNothing suspicious here."
    soul_text = "You are FINISHER. UNIQUE-SOUL-MARKER-42."
    sentinel = "SENTINEL-ONLY-IN-KEY-98765"

    messages = ef.build_messages(item_text, soul_text)

    assert isinstance(messages, list)
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user"]
    system_content = messages[0]["content"]
    user_content = messages[1]["content"]

    assert "UNIQUE-SOUL-MARKER-42" in system_content
    assert "json" in system_content.lower()
    assert "location" in system_content.lower()
    assert "kind" in system_content.lower()
    assert user_content == item_text

    blob = json.dumps(messages)
    assert sentinel not in blob


# ---------------------------------------------------------------- 6. dry-run: no network

def test_dry_run_never_calls_urlopen(tmp_items, tmp_path, monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("urlopen must not be called in dry-run")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)

    _write_item(tmp_items, "A-01", "anchor phrase text here")
    key_path = tmp_path / "answers.json"
    key_path.write_text(json.dumps({
        "A-01": {"class": "A", "seeded": True,
                 "defects": [{"id": "d1", "kind": "self-contradiction",
                              "anchor": "anchor phrase", "section": "x",
                              "keywords": [["a"], ["b"]]}]}}))

    result = ef.run(
        items_dir=tmp_items, key_path=key_path, candidates=ef.CANDIDATES[:1],
        passes=2, dry_run=True, max_usd=25.0, out_dir=tmp_path / "out",
        soul_path=tmp_path / "SOUL.md",
    )
    assert result["dry_run"] is True
    assert result["packets"] == 1 * 1 * 2


# ---------------------------------------------------------------- 7. max_usd refusal

def test_max_usd_refusal_raises_before_any_network_call(tmp_items, tmp_path, monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("urlopen must not be called when refusing on cost")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)

    _write_item(tmp_items, "A-01", "anchor phrase text here " * 500)
    key_path = tmp_path / "answers.json"
    key_path.write_text(json.dumps({
        "A-01": {"class": "A", "seeded": True,
                 "defects": [{"id": "d1", "kind": "self-contradiction",
                              "anchor": "anchor phrase", "section": "x",
                              "keywords": [["a"], ["b"]]}]}}))

    with pytest.raises(SystemExit):
        ef.run(
            items_dir=tmp_items, key_path=key_path, candidates=ef.CANDIDATES,
            passes=2, dry_run=False, max_usd=0.0, out_dir=tmp_path / "out",
            soul_path=tmp_path / "SOUL.md",
        )


# ---------------------------------------------------------------- 8. estimate_cost fallback

def test_estimate_cost_falls_back_when_model_missing_from_prices():
    items = {"A-01": "x" * 400}
    candidates = [{"model": "some/unknown-model", "eligible": True, "role": "test"}]
    prices = {}  # empty market cache
    est = ef.estimate_cost(items, candidates, passes=1, prices=prices)
    per = est["per_candidate"]["some/unknown-model"]
    assert per["price_source"] == "fallback"
    assert per["cost_usd"] > 0


def test_estimate_cost_uses_market_price_when_present():
    items = {"A-01": "x" * 400}
    candidates = [{"model": "known/model", "eligible": True, "role": "test"}]
    prices = {"known/model": {"in_per_m": 1.0, "out_per_m": 2.0}}
    est = ef.estimate_cost(items, candidates, passes=1, prices=prices)
    per = est["per_candidate"]["known/model"]
    assert per["price_source"] == "market"


# ---------------------------------------------------------------- 9. decide

def _cand_summary(recall_mean, recall_min, recall_max, precision=0.8, fp_rate=0.2,
                   cost=1.0, eligible=True, role="test"):
    return {
        "eligible": eligible, "role": role,
        "recall": {"mean": recall_mean, "min": recall_min, "max": recall_max},
        "precision": {"mean": precision, "min": precision, "max": precision},
        "fp_rate": {"mean": fp_rate, "min": fp_rate, "max": fp_rate},
        "cost_per_pass": cost,
    }


def test_decide_clear_winner():
    summary = {
        "incumbent": "anthropic/claude-sonnet-4.6",
        "candidates": {
            "anthropic/claude-sonnet-4.6": _cand_summary(0.60, 0.55, 0.65, cost=2.48, role="incumbent"),
            "anthropic/claude-sonnet-5": _cand_summary(0.90, 0.88, 0.92, cost=1.65),
        },
    }
    assert ef.decide(summary) == "anthropic/claude-sonnet-5"


def test_decide_tie_within_5_points_resolved_by_cost():
    summary = {
        "incumbent": "anthropic/claude-sonnet-4.6",
        "candidates": {
            "anthropic/claude-sonnet-4.6": _cand_summary(0.80, 0.79, 0.81, cost=2.48, role="incumbent"),
            "anthropic/claude-sonnet-5": _cand_summary(0.81, 0.80, 0.82, cost=1.65),
        },
    }
    # within 5 points, ranges don't overlap the 5pt band meaningfully but they
    # DO overlap each other here -> should be undecided per range-overlap rule
    result = ef.decide(summary)
    assert result in (
        "anthropic/claude-sonnet-5",
        "undecided: hold anthropic/claude-sonnet-4.6, add a third pass",
    )


def test_decide_tie_no_range_overlap_cheaper_wins():
    summary = {
        "incumbent": "anthropic/claude-sonnet-4.6",
        "candidates": {
            "anthropic/claude-sonnet-4.6": _cand_summary(0.80, 0.79, 0.80, cost=2.48, role="incumbent"),
            "anthropic/claude-sonnet-5": _cand_summary(0.82, 0.81, 0.83, cost=1.65),
        },
    }
    assert ef.decide(summary) == "anthropic/claude-sonnet-5"


def test_decide_overlapping_ranges_undecided():
    summary = {
        "incumbent": "anthropic/claude-sonnet-4.6",
        "candidates": {
            "anthropic/claude-sonnet-4.6": _cand_summary(0.80, 0.70, 0.90, cost=2.48, role="incumbent"),
            "anthropic/claude-sonnet-5": _cand_summary(0.82, 0.72, 0.92, cost=1.65),
        },
    }
    assert ef.decide(summary) == "undecided: hold anthropic/claude-sonnet-4.6, add a third pass"


# ---------------------------------------------------------------- 10. CLI dry-run

def test_cli_dry_run_returns_zero_no_network(tmp_items, tmp_path, monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("urlopen must not be called in CLI dry-run")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)

    _write_item(tmp_items, "A-01", "anchor phrase text here")
    key_path = tmp_path / "answers.json"
    key_path.write_text(json.dumps({
        "A-01": {"class": "A", "seeded": True,
                 "defects": [{"id": "d1", "kind": "self-contradiction",
                              "anchor": "anchor phrase", "section": "x",
                              "keywords": [["a"], ["b"]]}]}}))

    rc = cli.main(["eval", "finisher", "--dry-run",
                   "--items", str(tmp_items), "--key", str(key_path)])
    assert rc == 0


# ------------------------------------------------- mutation-found gaps (2026-09-02)
# Mutation testing the harness found two live paths the suite did not cover.
# Both changed behaviour with 26/26 still green, which is the definition of a
# test that cannot fail. Written after the fact, verified red under the mutant.

def test_decide_never_seats_an_ineligible_candidate():
    """THE hard rule: FINISHER must not share FORGE's family. qwen/* and
    deepseek/* run only as calibration baselines - if one posts the best
    recall in the whole eval, the rule must still refuse it. Deleting the
    eligibility filter previously left every test green while decide()
    happily returned qwen/qwen3.8-max."""
    def cand(elig, recall, cost, lo=None, hi=None):
        return {"eligible": elig, "cost_per_pass": cost,
                "recall": {"mean": recall, "min": lo if lo is not None else recall,
                           "max": hi if hi is not None else recall},
                "precision": {"mean": 0.9}, "fp_rate": {"mean": 0.0}}
    summary = {"incumbent": "anthropic/claude-sonnet-4.6", "candidates": {
        "qwen/qwen3.8-max": cand(False, 0.95, 0.4),            # best recall, cheapest
        "deepseek/deepseek-v4-pro-0813": cand(False, 0.90, 0.7),
        "anthropic/claude-sonnet-4.6": cand(True, 0.50, 2.5),
    }}
    verdict = ef.decide(summary)
    assert "qwen" not in verdict and "deepseek" not in verdict
    assert verdict == "anthropic/claude-sonnet-4.6"


def test_every_finding_on_a_clean_item_is_a_false_positive():
    """Clean items exist only to measure false alarms; if findings on them
    stop counting, fp_rate collapses to 0 and the decision rule's
    fp_rate gate silently stops gating."""
    clean = {"seeded": False, "class": "A", "defects": []}
    findings = [{"location": "para 2", "kind": "cost-mismatch",
                 "description": f"invented defect {n}", "confidence": 0.8}
                for n in range(3)]
    s = ef.score("A-99", findings, clean)
    assert s["false_positives"] == 3
    assert s["caught"] == 0 and s["matched_findings"] == 0
    # and it must survive aggregation into fp_rate
    agg = ef.aggregate([s])
    assert agg["fp_rate"] == 3.0          # 3 findings / 1 clean item


def test_unmatched_findings_on_a_seeded_item_are_false_positives_too():
    seeded = {"seeded": True, "class": "B", "defects": [
        {"id": "d1", "kind": "verdict-bypass", "anchor": "rm -rf ~/",
         "section": "COMMAND", "keywords": [["home"], ["CRITICAL"]]}]}
    findings = [
        {"location": "COMMAND rm -rf ~/", "kind": "verdict-bypass",
         "description": "wipes home", "confidence": 0.9},          # match
        {"location": "RATIONALE", "kind": "cost-mismatch",
         "description": "unrelated invention", "confidence": 0.4},  # FP
    ]
    s = ef.score("B-99", findings, seeded)
    assert s["caught"] == 1 and s["matched_findings"] == 1 and s["false_positives"] == 1


# --------------------------------------------- matcher amendment (2026-09-02)
# First live smoke ($0.04, 3 calls): Sonnet 4.6 found seeded defect A-guarantee
# and quoted its anchor verbatim - "'Guaranteed validated results inside 90
# minutes' - 'validated' is undefined..." - and match() said NO. Two faults:
# models never use the KINDS vocabulary (they said definitional_gap /
# unverified_claim / policy_gap - zero overlap), so the `kind ==` path is dead;
# and requiring EVERY keyword set forced the model to explain WHY in the key
# author's words - which measures "phrases things like Claude", the exact bias
# this eval exists to avoid. Amended rule, pre-registered before any further
# spend: anchor present AND at least one keyword set hits. It raises recall
# for every candidate equally; section 7 ranks, so the comparison survives.

SMOKE_FINDING = {  # verbatim from the saved smoke run, item A-01
    "location": "Recommendation > proposed close copy (inline)",
    "kind": "definitional_gap",
    "description": ("'Guaranteed validated results inside 90 minutes' — 'validated' is "
                    "undefined. Validated by whom, against what standard, using what "
                    "method? For a non-technical buyer this phrase either means nothing "
                    "or implies a promise the operator may not be able to keep."),
    "confidence": 0.8,
}
A_GUARANTEE = {"id": "A-guarantee", "kind": "self-contradiction",
               "anchor": "guaranteed validated results", "section": "Recommendation",
               "keywords": [["guarantee"],
                            ["honest limits", "demo", "collapses", "overclaim", "contradict"]]}


def test_a_verbatim_quote_of_the_seeded_text_counts_as_caught():
    assert ef.match(SMOKE_FINDING, A_GUARANTEE)


def test_anchor_alone_is_not_enough():
    """Quoting the seeded line while saying nothing about it is not detection."""
    f = dict(SMOKE_FINDING, description="The close copy says 'guaranteed validated results'.",
             kind="style")
    d = dict(A_GUARANTEE, keywords=[["undefined", "promise", "overclaim"], ["zzz"]])
    assert not ef.match(f, d)


def test_kind_equality_no_longer_rescues_a_finding_without_keywords():
    f = {"location": "Recommendation", "kind": "self-contradiction",
         "description": "guaranteed validated results", "confidence": 0.9}
    d = dict(A_GUARANTEE, keywords=[["nope"], ["never"]])
    assert not ef.match(f, d)


# ------------------------------------------- resilience + resume (2026-09-02)
# The first full sweep ran 44 minutes, then died on KeyError: 'choices' - one
# OpenRouter reply that was not a completion - and lost EVERY prior call,
# because results were only written at the end and the bad payload was never
# logged. ~$1.50 of calls, gone. A 360-call instrument must survive one bad
# reply, persist as it goes, and resume without re-spending.

import io, json as _json, urllib.error


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_choicesless_200_becomes_a_recorded_error_not_a_crash(monkeypatch):
    payload = _json.dumps({"error": {"message": "rate limited", "code": 429}}).encode()
    monkeypatch.setattr(ef.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    text, usage = ef.call_openrouter("x/y", [{"role": "user", "content": "hi"}], "k")
    assert text == ""
    assert usage.get("error") and "rate limited" in _json.dumps(usage["error"])
    assert usage.get("cost") is None


def test_http_error_becomes_a_recorded_error_not_a_crash(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 503, "unavailable", {}, io.BytesIO(b'{"error":"down"}'))
    monkeypatch.setattr(ef.urllib.request, "urlopen", boom)
    text, usage = ef.call_openrouter("x/y", [{"role": "user", "content": "hi"}], "k")
    assert text == "" and "503" in _json.dumps(usage["error"])


def _tiny_set(tmp_path):
    items = tmp_path / "items"; items.mkdir()
    (items / "S-01.md").write_text("alpha anchor-one beta\n")
    (items / "C-01.md").write_text("nothing here\n")
    key = {"S-01": {"class": "A", "seeded": True, "defects": [
                {"id": "d", "kind": "cost-mismatch", "anchor": "anchor-one",
                 "section": "x", "keywords": [["kw1"], ["kw2"]]}]},
           "C-01": {"class": "A", "seeded": False, "defects": []}}
    kp = tmp_path / "answers.json"; kp.write_text(_json.dumps(key))
    (tmp_path / "SOUL.md").write_text("soul\n")
    return items, kp, tmp_path / "SOUL.md"


def test_run_persists_every_call_and_skips_error_calls_in_scoring(tmp_path, monkeypatch):
    items, kp, soul = _tiny_set(tmp_path)
    calls = []
    def fake(model, messages, key, timeout=120):
        calls.append(model)
        if len(calls) == 1:                       # first call: provider error
            return "", {"error": {"message": "rate limited"}, "cost": None}
        return '[{"location":"anchor-one","kind":"k","description":"kw1","confidence":1}]', {"cost": 0.001}
    monkeypatch.setattr(ef, "call_openrouter", fake)
    monkeypatch.setattr(ef, "openrouter_key", lambda: "k")
    cands = [{"model": "a/b", "eligible": True, "role": "r"}]
    out = tmp_path / "out"
    r = ef.run(items, kp, cands, passes=1, dry_run=False, max_usd=5, out_dir=out, soul_path=soul)
    jsonl = list(out.glob("*.calls.jsonl"))
    assert len(jsonl) == 1
    lines = [_json.loads(l) for l in jsonl[0].read_text().splitlines()]
    assert len(lines) == 2                                  # both calls persisted
    assert lines[0]["call_error"] is True and lines[1]["call_error"] is False
    assert r["summary"]["candidates"]["a/b"]["errors"] == 1
    # the errored call is NOT scored as a miss - it never reached the model
    assert r["summary"]["candidates"]["a/b"]["scored_items"] == 1


def test_resume_reuses_recorded_calls_and_never_respends(tmp_path, monkeypatch):
    items, kp, soul = _tiny_set(tmp_path)
    good = '[{"location":"anchor-one","kind":"k","description":"kw1","confidence":1}]'
    n = {"calls": 0}
    def fake(model, messages, key, timeout=120):
        n["calls"] += 1
        return good, {"cost": 0.001}
    monkeypatch.setattr(ef, "call_openrouter", fake)
    monkeypatch.setattr(ef, "openrouter_key", lambda: "k")
    cands = [{"model": "a/b", "eligible": True, "role": "r"}]
    out = tmp_path / "out"
    ef.run(items, kp, cands, passes=1, dry_run=False, max_usd=5, out_dir=out, soul_path=soul)
    assert n["calls"] == 2
    prior = next(out.glob("*.calls.jsonl"))
    n["calls"] = 0
    r = ef.run(items, kp, cands, passes=1, dry_run=False, max_usd=5, out_dir=out, soul_path=soul,
               resume=prior)
    assert n["calls"] == 0                                   # nothing re-spent
    assert r["summary"]["candidates"]["a/b"]["recall"]["mean"] == 1.0   # prior results still count
