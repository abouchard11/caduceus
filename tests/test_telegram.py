import json

from caduceus import telegram
from caduceus.config import SEATS
from caduceus.council import Draft
from caduceus.council import CouncilResult


def valid_settings():
    return {
        "group_chat_id": "-1001234567890",
        "operator_user_id": "111222333",
        "bots": {"forge": "CaduceusForge_bot", "finisher": "CaduceusFinisher_bot",
                 "recon": "", "sparring": "CadSparring_bot", "envoy": ""},
        "k2_admin_bot": "AlexK2_bot",
    }


def write_settings(s):
    telegram.settings_path().write_text(json.dumps(s))


def test_settings_validation():
    ok, problems = telegram.settings_ready(None)
    assert not ok and problems
    s = valid_settings()
    ok, problems = telegram.settings_ready(s)
    assert ok and not problems
    s["group_chat_id"] = "12345"  # not a supergroup id
    ok, problems = telegram.settings_ready(s)
    assert not ok


def test_sub_block_allowlists_and_peers():
    s = valid_settings()
    block = telegram.telegram_sub_block("forge", s)
    assert 'allowed_chats: ["-1001234567890"]' in block
    assert '"111222333"' in block                      # operator
    assert "CaduceusFinisher_bot" in block             # peer bot
    assert "CaduceusForge_bot" not in block            # never self
    assert "AlexK2_bot" in block                       # admin eyes


def test_insert_preserves_existing_platforms():
    existing = (
        "model:\n  default: x\n  provider: y\n\n"
        "platforms:\n  api_server:\n    enabled: true\n    extra:\n      port: 8651\n"
    )
    out = telegram.insert_into_platforms(existing, telegram.telegram_sub_block("forge", valid_settings()))
    assert out.count("platforms:") == 1
    assert "api_server:" in out and "telegram:" in out
    # telegram block sits inside the same platforms block (before api_server)
    assert out.index("platforms:") < out.index("telegram:") < out.index("api_server:")


def test_insert_appends_when_absent():
    out = telegram.insert_into_platforms("model:\n  default: x\n",
                                         telegram.telegram_sub_block("envoy", valid_settings()))
    assert "platforms:\n  telegram:" in out


def test_post_requires_settings():
    ok, err = telegram.post("hello")
    assert not ok and err


def test_broadcast_result_attribution(monkeypatch):
    write_settings(valid_settings())
    calls = []

    def fake_post(text, seat=None, settings=None, timeout=30):
        calls.append({"seat": seat, "text": text})
        return True, ""

    monkeypatch.setattr(telegram, "post", fake_post)
    monkeypatch.setattr(telegram.time, "sleep", lambda s: None)
    w = Draft("finisher", 2, "block it", 0.9, ["a"], [], "block release")
    d = Draft("sparring", 2, "ship it", 0.8, ["b"], [], "ship to canary")
    result = CouncilResult(
        run_id="r1", question="q", domain="review", mode="full",
        seats=["finisher", "sparring"], rounds={2: [w, d]},
        weights={"finisher": 0.6, "sparring": 0.4},
        ranked=[("finisher", 0.6), ("sparring", 0.4)],
        winner=w, dissent=d, conformity_flags=[], memo_path="",
        elapsed_s=1.0, transport_used={},
    )
    log = telegram.broadcast_result(result)
    # finisher has a bot -> posts as itself; sparring has a bot too
    seat_posts = [c for c in calls if c["seat"] in ("finisher", "sparring")]
    assert len(seat_posts) == 2
    summary = [c for c in calls if c["seat"] is None]
    assert summary and "MINORITY" in summary[0]["text"]
    assert all("posted" in line or "summary" in line for line in log)


def test_engine_posts_never_reply():
    # loop-safety by shape: the post() command builder has no reply flag at all
    import inspect
    src = inspect.getsource(telegram.post)
    assert "reply" not in src.lower()


def test_bind_seats_dry_run_without_profiles():
    write_settings(valid_settings())
    log = telegram.bind_seats(write=False)
    joined = "\n".join(log)
    assert "profile missing" in joined or "would bind" in joined
    # seats without bots route through default profile
    assert any("no bot assigned" in line for line in log)
