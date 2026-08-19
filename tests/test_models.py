import json
import time

from caduceus import config, models
from caduceus.config import SEATS
from caduceus.ledger import Ledger

NOW = time.time()

FIXTURE = [
    # current RECON model
    {"id": "deepseek/deepseek-v4-pro-0813", "context_length": 1048576,
     "created": NOW - 10 * 86400,
     "pricing": {"prompt": "0.00000066", "completion": "0.00000198",
                 "overrides": [{"utc_start": 1000, "utc_end": 100,
                                "prompt": "0.0000003", "completion": "0.000001"}]}},
    # fresh promo-priced rival (the gemini-3.7-flash shape)
    {"id": "google/gemini-3.7-flash", "context_length": 1048576,
     "created": NOW - 6 * 86400,
     "pricing": {"prompt": "0.000000375", "completion": "0.000001875"}},
    {"id": "google/gemini-3.7-flash:batch", "context_length": 1048576,
     "created": NOW - 6 * 86400,
     "pricing": {"prompt": "0.0000001875", "completion": "0.0000009375"}},
    # ENVOY's model with a price cliff at 32K
    {"id": "qwen/qwen3.7-flash", "context_length": 1000000,
     "created": NOW - 200 * 86400,
     "pricing": {"prompt": "0.00000003", "completion": "0.00000013",
                 "overrides": [{"min_prompt_tokens": 32000,
                                "prompt": "0.0000001",
                                "completion": "0.0000004"}]}},
    # FINISHER + others so seat_report has entries
    {"id": "anthropic/claude-sonnet-5", "context_length": 1000000,
     "created": NOW - 60 * 86400,
     "pricing": {"prompt": "0.000002", "completion": "0.00001"}},
    {"id": "nousresearch/hermes-4-405b", "context_length": 131072,
     "created": NOW - 300 * 86400,
     "pricing": {"prompt": "0.000001", "completion": "0.000003"}},
    # a free trial with expiration
    {"id": "nvidia/nemotron-nano:free", "context_length": 131072,
     "created": NOW - 5 * 86400, "expiration_date": "2026-08-24",
     "pricing": {"prompt": "0", "completion": "0"}},
    # image model that must be excluded from candidates
    {"id": "google/gemini-3-pro-image", "context_length": 131072,
     "created": NOW - 5 * 86400,
     "pricing": {"prompt": "0.000002", "completion": "0.000012"}},
]


def market():
    return models.normalize(FIXTURE)


def test_normalize_extracts_cliffs_and_batch():
    m = market()
    q = m["qwen/qwen3.7-flash"]
    assert q["cliffs"][0]["min_prompt_tokens"] == 32000
    assert m["google/gemini-3.7-flash:batch"]["base_of_batch"] == "google/gemini-3.7-flash"
    ds = m["deepseek/deepseek-v4-pro-0813"]
    assert any(c.get("time_window") for c in ds["cliffs"])


def test_seat_report_finds_cheaper_and_twin():
    rows = {r["seat"]: r for r in models.seat_report(market())}
    recon = rows["recon"]
    cheaper_ids = [c["id"] for c in recon["cheaper"]]
    assert "google/gemini-3.7-flash" in cheaper_ids
    assert "google/gemini-3-pro-image" not in cheaper_ids  # media excluded
    envoy = rows["envoy"]
    assert any("cliff" in n for n in envoy["notes"])
    # forge is on a prepaid non-openrouter provider -> informational note
    assert any("prepaid" in n for n in rows["forge"]["notes"])


def test_promo_candidates_flags_fresh_and_free():
    promos = models.promo_candidates(market())
    ids = [m["id"] for m in promos]
    assert "google/gemini-3.7-flash" in ids
    assert "nvidia/nemotron-nano:free" in ids
    assert "google/gemini-3-pro-image" not in ids


def test_casting_roundtrip_and_effective_seat():
    assert models.effective_seat("recon").model == SEATS["recon"].model
    seat, log = models.set_seat_model("recon", "google/gemini-3.7-flash",
                                      note="promo")
    assert seat.model == "google/gemini-3.7-flash"
    assert seat.family == "google"
    assert models.effective_seat("recon").model == "google/gemini-3.7-flash"
    # previous casting preserved for rollback context
    assert models.load_casting()["recon"]["previous"]["model"] == SEATS["recon"].model
    # unaffected seat untouched
    assert models.effective_seat("finisher").model == SEATS["finisher"].model


def test_recast_warns_on_family_collapse():
    models.set_seat_model("finisher", "qwen/qwen3.8-27b")
    models.set_seat_model("recon", "qwen/qwen3.5-27b")
    _, log = models.set_seat_model("sparring", "qwen/qwen3.5-9b")
    assert any("conformity trap" in line for line in log)


def test_estimate_cost():
    m = market()
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 100_000}
    est = models.estimate_cost(usage, "google/gemini-3.7-flash", m)
    assert abs(est - (0.375 + 0.1875)) < 1e-6
    assert models.estimate_cost(usage, "unknown/model", m) is None
    assert models.estimate_cost({}, "google/gemini-3.7-flash", m) is None


def test_market_cache_roundtrip():
    cache = config.caduceus_home() / "models_cache.json"
    cache.write_text(json.dumps({"fetched_at": time.time(), "data": FIXTURE}))
    m = models.market_from_cache()
    assert m and "google/gemini-3.7-flash" in m
    data, fetched = models.fetch_market()  # served from cache, no network
    assert len(data) == len(FIXTURE)


def test_value_report_attributes_models():
    led = Ledger()
    led.record("recon", "research", "win", model="google/gemini-3.7-flash")
    led.record("recon", "research", "loss", model="deepseek/deepseek-v4-pro-0813")
    rows = models.value_report(led)
    by_model = {r["model"]: r for r in rows if r["seat"] == "recon"}
    assert by_model["google/gemini-3.7-flash"]["win"] == 1
    assert by_model["deepseek/deepseek-v4-pro-0813"]["loss"] == 1
    led.close()


def test_ledger_migration_from_v01_schema(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE outcomes (id TEXT PRIMARY KEY, ts REAL NOT NULL,
            seat TEXT NOT NULL, domain TEXT NOT NULL, result TEXT NOT NULL,
            task_ref TEXT, note TEXT);
        CREATE TABLE council_runs (run_id TEXT PRIMARY KEY, ts REAL NOT NULL,
            domain TEXT NOT NULL, question TEXT NOT NULL, seats TEXT NOT NULL,
            memo_path TEXT, settled INTEGER NOT NULL DEFAULT 0);
        INSERT INTO outcomes VALUES ('x', 1.0, 'forge', 'infra', 'win', '', '');
    """)
    conn.commit(); conn.close()
    led = Ledger(path=db)   # must migrate without error
    led.record("forge", "infra", "win", model="qwen3.7-plus")
    assert led.believability("forge", "infra").score > 0.5
    led.close()
