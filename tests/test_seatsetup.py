"""seatsetup.py had zero coverage before the 2026-08-19 opus-4.6 incident -
exactly how a shared, inherited fallback_providers block went unnoticed
through `cad init` + `cad doctor` (both reported clean) until it 402'd
mid-council. These tests pin the fix: patch_profile_config must neutralize
whatever `hermes profile create --clone` copied in, every time, idempotently.
"""
from caduceus import seatsetup
from caduceus.config import SEATS

# Shape of what `hermes profile create --clone` actually produced: the
# root profile's fallback_providers block, copied verbatim into every seat.
CLONED_CONFIG = """model:
  default: claude-opus-4.6
  provider: anthropic
fallback_providers:
  - provider: openrouter
    model: anthropic/claude-opus-4.6
database:
  journal_mode: wal
runtime:
  nofile_soft_limit: 4096
"""


def _cfg_path(seat):
    from caduceus import config
    p = config.hermes_home() / "profiles" / seat.name / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def test_patch_neutralizes_inherited_fallback():
    seat = SEATS["forge"]
    cfg = _cfg_path(seat)
    cfg.write_text(CLONED_CONFIG)

    log = []
    seatsetup.patch_profile_config(seat, "test-key", log, enable_api=False)

    text = cfg.read_text()
    assert "fallback_providers: []" in text
    assert "anthropic/claude-opus-4.6" not in text
    assert f"default: {seat.model}" in text
    assert f"provider: {seat.provider}" in text
    # untouched sibling blocks survive
    assert "journal_mode: wal" in text


def test_patch_is_idempotent():
    seat = SEATS["forge"]
    cfg = _cfg_path(seat)
    cfg.write_text(CLONED_CONFIG)

    log1, log2 = [], []
    seatsetup.patch_profile_config(seat, "test-key", log1, enable_api=False)
    seatsetup.patch_profile_config(seat, "test-key", log2, enable_api=False)

    assert any("patched config" in line for line in log1)
    assert any("already correct" in line for line in log2)
    # second pass must not duplicate the block or reintroduce opus
    text = cfg.read_text()
    assert text.count("fallback_providers:") == 1
    assert "opus" not in text.lower()


def test_fresh_config_ships_neutralized_fallback():
    """No existing config.yaml (first-ever provision): the written-from-
    scratch branch must also set fallback_providers explicitly, not rely on
    the key being merely absent."""
    seat = SEATS["envoy"]
    cfg = _cfg_path(seat)
    assert not cfg.exists()

    log = []
    seatsetup.patch_profile_config(seat, "test-key", log, enable_api=False)

    text = cfg.read_text()
    assert "fallback_providers: []" in text
    assert f"default: {seat.model}" in text


def test_model_block_caps_max_tokens():
    seat = SEATS["sparring"]  # the 405B seat - the most expensive to leave uncapped
    block = seatsetup.model_block(seat)
    assert "max_tokens:" in block


def test_all_seats_patch_cleanly_from_a_shared_clone():
    """Every seat clones from the SAME root profile, so every seat inherits
    the SAME dangerous fallback target. Confirm the patch clears it for all
    five, not just the one seat exercised above."""
    for name, seat in SEATS.items():
        cfg = _cfg_path(seat)
        cfg.write_text(CLONED_CONFIG)
        log = []
        seatsetup.patch_profile_config(seat, "test-key", log, enable_api=False)
        text = cfg.read_text()
        assert "fallback_providers: []" in text, f"{name} still has a live fallback"
        assert "opus" not in text.lower(), f"{name} still references opus"
