"""The operator brief must be deterministic and its delivery must be the
artifact, not the job status.

2026-09-01: the LLM-driven morning-brief cron had never once written its
deliverable. Its last run died on a 1040s idle timeout inside a subagent it
spawned via delegate_task; the weekly job reported last_status=ok on 08-31
and had ALSO written nothing. So the cron-health check added in 0.3.3 was a
false green of exactly the class it was built to catch - it read job status,
and the only thing that matters is whether the section landed in the file.
`cad brief` is stdlib and writes the section itself; the cron runs it with
--no-agent so no model sits in the delivery path.
"""
import datetime as dt
import json
import os

from caduceus import brief, config
from caduceus.ledger import Ledger


def _pending(tmp_path, monkeypatch, text=None):
    p = tmp_path / "CLAUDE-PENDING-ACTIONS.md"
    monkeypatch.setenv(brief.PENDING_ENV, str(p))
    if text is not None:
        p.write_text(text)
    return p


OTHER = ("# Claude Code — Pending User Actions\n\n## 1. Disconnect connectors\n\n"
         "- [ ] Notion\n\n---\n\n## 2. Something else\n\n- [ ] item\n")


def test_replace_section_touches_only_that_section():
    text = OTHER + "\n## Caduceus morning brief (2026-08-30)\n\nold body\n\n## 9. After\n\ntail\n"
    out = brief.replace_section(text, brief.MORNING_HEADING,
                                "## Caduceus morning brief (2026-09-01)\n\nnew body\n")
    assert "old body" not in out
    assert "new body" in out
    assert out.count("## Caduceus morning brief") == 1
    assert "## 1. Disconnect connectors" in out and "- [ ] Notion" in out
    assert "## 9. After\n\ntail" in out


def test_replace_section_appends_when_missing():
    out = brief.replace_section(OTHER, brief.MORNING_HEADING,
                                "## Caduceus morning brief (2026-09-01)\n\nbody\n")
    assert out.startswith(OTHER.rstrip("\n"))
    assert out.rstrip().endswith("body")


def test_write_creates_file_and_is_idempotent(tmp_path, monkeypatch):
    p = _pending(tmp_path, monkeypatch)
    assert not p.exists()
    brief.write("## Caduceus morning brief (2026-09-01)\n\nfirst\n", brief.MORNING_HEADING)
    brief.write("## Caduceus morning brief (2026-09-01)\n\nsecond\n", brief.MORNING_HEADING)
    text = p.read_text()
    assert text.count("## Caduceus morning brief") == 1
    assert "second" in text and "first" not in text


def test_morning_brief_names_unsettled_runs_and_dead_cron(tmp_path, monkeypatch):
    led = Ledger()
    led.register_run("20260901-000000-abc123", "strategy", "Should we do X?", ["forge", "recon"])
    led.close()
    cron = config.hermes_home() / "cron"
    cron.mkdir(parents=True, exist_ok=True)
    (cron / "jobs.json").write_text(json.dumps([
        {"name": "caduceus-morning-brief", "last_status": "error", "failure_streak": 3,
         "last_error": "TimeoutError: idle for 1040s"},
    ]))
    now = dt.datetime(2026, 9, 1, 7, 0)

    text = brief.render_morning(brief.gather(now=now), now=now)

    assert text.startswith("## Caduceus morning brief (2026-09-01)")
    assert "20260901-000000-abc123" in text
    assert "caduceus-morning-brief" in text and "3" in text
    assert "cad ledger settle" in text          # every item names its verb


def test_morning_brief_is_quiet_when_nothing_is_open(tmp_path, monkeypatch):
    now = dt.datetime(2026, 9, 1, 7, 0)
    text = brief.render_morning(brief.gather(now=now), now=now)
    assert "nothing open" in text.lower()
    assert text.startswith("## Caduceus morning brief (2026-09-01)")


def test_freshness_reads_the_heading_date(tmp_path, monkeypatch):
    p = _pending(tmp_path, monkeypatch,
                 OTHER + "\n## Caduceus morning brief (2026-08-30)\n\nbody\n")
    now = dt.datetime(2026, 9, 1, 7, 0)
    age = brief.age_hours(brief.MORNING_HEADING, now=now)
    assert age is not None and 40 < age < 60      # 08-30 -> 09-01 07:00
    assert brief.age_hours(brief.WEEKLY_HEADING, now=now) is None


def test_weekly_brief_carries_ledger_table(tmp_path, monkeypatch):
    led = Ledger()
    led.record("recon", "strategy", "win", note="x")
    led.close()
    now = dt.datetime(2026, 9, 1, 8, 0)
    text = brief.render_weekly(brief.gather(now=now), now=now)
    assert text.startswith("## Caduceus weekly ledger (2026-09-01)")
    assert "recon" in text and "strategy" in text
