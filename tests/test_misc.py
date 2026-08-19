import pytest

from caduceus import config, dashboard
from caduceus.config import classify_domain, heterogeneity_warnings, seat_list, SEATS


def test_classify_domain():
    assert classify_domain("fix the TypeScript type error in the schema") == "types"
    assert classify_domain("draft an email reply, watch the tone") == "comms"
    assert classify_domain("random gibberish zzz") == "general"


def test_seat_list_validates():
    assert [s.name for s in seat_list("forge, finisher")] == ["forge", "finisher"]
    with pytest.raises(SystemExit):
        seat_list("forge,ghost")


def test_heterogeneity_warning():
    warns = heterogeneity_warnings([SEATS["forge"], SEATS["envoy"]])  # both qwen
    assert warns
    assert not heterogeneity_warnings([SEATS["forge"], SEATS["finisher"]])


def test_seat_families_are_heterogeneous_by_design():
    fams = {SEATS[n].family for n in config.FULL_COUNCIL}
    assert len(fams) == 4, "full council must span 4 model families"


def test_env_roundtrip():
    config.write_env({"CADUCEUS_API_KEY": "x" * 32})
    assert config.load_env()["CADUCEUS_API_KEY"] == "x" * 32
    key = config.ensure_api_key()
    assert len(key) >= 16


def test_dashboard_builds_on_empty_state(tmp_path):
    html = dashboard.build()
    assert "CADUCEUS" in html
    assert "FINISHER" in html
    out = dashboard.write(tmp_path / "d.html")
    assert out.exists()


def test_ports_unique():
    ports = [s.port for s in SEATS.values()]
    assert len(ports) == len(set(ports))
