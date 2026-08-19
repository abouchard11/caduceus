import time

from caduceus.ledger import Ledger


def test_prior_is_half():
    led = Ledger()
    b = led.believability("forge", "implementation")
    assert abs(b.score - 0.5) < 1e-9
    assert b.basis == "prior"
    led.close()


def test_wins_raise_losses_lower():
    led = Ledger()
    for _ in range(5):
        led.record("finisher", "review", "win")
    hi = led.believability("finisher", "review").score
    for _ in range(5):
        led.record("sparring", "review", "loss")
    lo = led.believability("sparring", "review").score
    assert hi > 0.7
    assert lo < 0.3
    assert hi > lo
    led.close()


def test_global_fallback():
    led = Ledger()
    led.record("recon", "research", "win")
    led.record("recon", "research", "win")
    b = led.believability("recon", "never-seen-domain")
    assert b.basis == "global"
    assert b.score > 0.5
    led.close()


def test_recency_decay():
    led = Ledger()
    led.record("forge", "infra", "loss")
    # backdate the loss far beyond several half-lives
    led.conn.execute("UPDATE outcomes SET ts=? WHERE seat='forge'",
                     (time.time() - 400 * 86400,))
    led.conn.commit()
    b = led.believability("forge", "infra")
    # ancient loss barely moves the prior
    assert b.score > 0.4
    led.close()


def test_settle_flow():
    led = Ledger()
    led.register_run("run-1", "strategy", "pivot?", ["forge", "sparring"], "/tmp/m.md")
    assert any(r["run_id"] == "run-1" for r in led.runs())
    led.settle("run-1", winners=["sparring"], losers=["forge"], mixed=[])
    assert not any(r["run_id"] == "run-1" for r in led.runs(unsettled_only=True))
    assert led.believability("sparring", "strategy").score > \
           led.believability("forge", "strategy").score
    led.close()


def test_pending_ignored_in_score():
    led = Ledger()
    led.record("envoy", "comms", "pending")
    b = led.believability("envoy", "comms")
    assert b.basis == "prior"
    led.close()
