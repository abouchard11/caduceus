import json
from pathlib import Path

from caduceus import config
from caduceus.config import SEATS
from caduceus.council import Council, extract_json, jaccard, pair_agrees, parse_draft
from caduceus.hermes import MockTransport, SeatReply
from caduceus.ledger import Ledger


def D(position, rec, conf=0.8, **kw):
    base = {"position": position, "confidence": conf, "key_points": ["a"],
            "risks": ["r"], "recommendation": rec}
    base.update(kw)
    return json.dumps(base)


def test_extract_json_fenced_and_messy():
    assert extract_json('```json\n{"a": 1}\n```')["a"] == 1
    assert extract_json('preamble {"a": {"b": 2}} trailing')["a"]["b"] == 2
    assert extract_json("no json here") is None


def test_parse_draft_defensive():
    r = SeatReply("forge", "totally unstructured prose answer", True, "mock")
    d = parse_draft(r, 1)
    assert d.parse_ok is False
    assert d.position  # kept the text
    r2 = SeatReply("forge", D("ship it", "ship now", conf=3.0), True, "mock")
    d2 = parse_draft(r2, 1)
    assert d2.confidence == 1.0  # clamped


def test_quick_agreement_early_stops():
    script = {
        "forge": [D("Ship the feature now, polish later", "ship the feature now")],
        "finisher": [D("Ship the feature now with a smoke test", "ship the feature now")],
    }
    mock = MockTransport(script)
    c = Council(ledger=Ledger(), transport="mock", mock=mock)
    seats = [SEATS["forge"], SEATS["finisher"]]
    res = c.run("ship or wait?", seats, quick=True)
    assert res.mode == "quick"
    assert 2 not in res.rounds            # no cross-exam round
    assert len(mock.calls) == 2           # exactly two seat calls
    assert res.winner is not None


def test_quick_disagreement_escalates_to_full():
    script = {
        "forge": [D("Ship now", "ship immediately"),
                  D("Ship now", "ship immediately")],
        "finisher": [D("Do not ship, coverage is a lie", "block release until tests exist"),
                     D("Do not ship", "block release until tests exist")],
        "recon": [D("Data says defects spike on rushed releases", "delay one week"),
                  D("Same", "delay one week")],
        "sparring": [D("Shipping broken builds trust down", "ship to 5% canary only"),
                     D("Canary", "ship to 5% canary only")],
    }
    mock = MockTransport(script)
    c = Council(ledger=Ledger(), transport="mock", mock=mock)
    seats = [SEATS["forge"], SEATS["finisher"]]
    res = c.run("ship or wait?", seats, quick=True, escalate=True)
    assert res.mode == "quick->full"
    assert set(res.seats) == set(config.FULL_COUNCIL)
    assert 2 in res.rounds                # cross-exam happened
    assert res.memo_path and Path(res.memo_path).exists()


def test_full_council_memo_has_minority_report():
    script = {
        "forge": [D("Rewrite in place", "refactor incrementally", 0.9),
                  D("Rewrite in place", "refactor incrementally", 0.9)],
        "finisher": [D("Incremental is safer", "refactor incrementally", 0.85),
                     D("Incremental", "refactor incrementally", 0.85)],
        "recon": [D("Industry data favors strangler pattern", "refactor incrementally", 0.7),
                  D("Same", "refactor incrementally", 0.7)],
        "sparring": [D("Everyone is wrong: the module should be deleted",
                       "delete the module entirely and buy a vendor solution", 0.8),
                     D("Delete it", "delete the module entirely and buy a vendor solution", 0.8)],
    }
    mock = MockTransport(script)
    led = Ledger()
    c = Council(ledger=led, transport="mock", mock=mock)
    seats = [SEATS[n] for n in config.FULL_COUNCIL]
    res = c.run("what do we do with the legacy module?", seats)
    memo = Path(res.memo_path).read_text()
    assert "Minority Report" in memo
    assert res.dissent is not None
    assert res.dissent.seat == "sparring"
    # run registered for settlement
    assert any(r["run_id"] == res.run_id for r in led.runs())


def test_conformity_flag_on_uncited_flip():
    flip = D("Actually agree now", "refactor incrementally", 0.8,
             changed=True, changed_because="")
    script = {
        "forge": [D("Rewrite", "big-bang rewrite", 0.9), flip],
        "finisher": [D("Incremental", "refactor incrementally", 0.9),
                     D("Incremental", "refactor incrementally", 0.9,
                       changed=False)],
        "recon": [D("Neutral", "gather more data", 0.6),
                  D("Neutral", "gather more data", 0.6)],
        "sparring": [D("Delete it", "delete the module", 0.7),
                     D("Delete it", "delete the module", 0.7)],
    }
    mock = MockTransport(script)
    c = Council(ledger=Ledger(), transport="mock", mock=mock)
    seats = [SEATS[n] for n in config.FULL_COUNCIL]
    res = c.run("rewrite?", seats)
    assert any("forge" in f for f in res.conformity_flags)


def test_believability_weights_rank_winner():
    led = Ledger()
    for _ in range(6):
        led.record("finisher", "review", "win")
    for _ in range(6):
        led.record("sparring", "review", "loss")
    script = {
        "forge": [D("A", "adopt plan A", 0.7), D("A", "adopt plan A", 0.7)],
        "finisher": [D("B is correct", "adopt plan B", 0.7),
                     D("B", "adopt plan B", 0.7)],
        "recon": [D("Neutral", "either works", 0.4),
                  D("Neutral", "either works", 0.4)],
        "sparring": [D("C obviously", "adopt plan C", 0.99),
                     D("C", "adopt plan C", 0.99)],
    }
    mock = MockTransport(script)
    c = Council(ledger=led, transport="mock", mock=mock)
    seats = [SEATS[n] for n in config.FULL_COUNCIL]
    res = c.run("review the release plan", seats, domain="review")
    # finisher's track record should beat sparring's confidence theater
    assert res.ranked[0][0] == "finisher"


def test_agreement_math():
    a = parse_draft(SeatReply("a", D("ship the feature now", "ship the feature now"), True, "mock"), 1)
    b = parse_draft(SeatReply("b", D("ship the feature now please", "ship the feature now today"), True, "mock"), 1)
    assert pair_agrees(a, b)
    c_ = parse_draft(SeatReply("c", D("block everything", "halt and audit"), True, "mock"), 1)
    assert not pair_agrees(a, c_)
    assert jaccard("", "x") == 0.0
