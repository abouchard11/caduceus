"""Tests for the budgets module."""
import json
import pytest
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from caduceus import budgets, config


@pytest.fixture
def temp_budgets_dir(tmp_path):
    """Use a temporary directory for budget files."""
    budgets_dir = tmp_path / "budgets"
    budgets_dir.mkdir()
    with patch.object(budgets, 'budgets_dir', return_value=budgets_dir):
        with patch.object(budgets, 'budget_path', lambda run_id: budgets_dir / f"{run_id}.json"):
            yield budgets_dir


@pytest.fixture
def mock_state_db(tmp_path):
    """Mock a state.db file with spend data."""
    db_path = tmp_path / "state.db"
    # We'll mock the sqlite3.connect call instead of creating a real DB
    return db_path


def test_create_budget(temp_budgets_dir):
    """Test creating a budget record."""
    budget = budgets.create_budget(
        run_id="test-run-123",
        origin="council",
        seats=["forge", "finisher"],
        ceiling_usd=1.50,
        session_ids=["session-1", "session-2"]
    )
    
    assert budget.run_id == "test-run-123"
    assert budget.origin == "council"
    assert budget.seats == ["forge", "finisher"]
    assert budget.ceiling_usd == 1.50
    assert budget.session_ids == ["session-1", "session-2"]
    assert not budget.paused
    
    # Verify file was written
    budget_file = temp_budgets_dir / "test-run-123.json"
    assert budget_file.exists()
    
    # Verify file permissions
    assert (budget_file.stat().st_mode & 0o777) == 0o600


def test_load_budget(temp_budgets_dir):
    """Test loading a budget record."""
    # Create a budget
    budgets.create_budget(
        run_id="test-load-456",
        origin="plan",
        seats=["recon"],
        ceiling_usd=0.75,
        session_ids=["session-3"]
    )
    
    # Load it back
    loaded = budgets.load_budget("test-load-456")
    assert loaded is not None
    assert loaded.run_id == "test-load-456"
    assert loaded.origin == "plan"
    assert loaded.seats == ["recon"]
    assert loaded.ceiling_usd == 0.75
    assert loaded.session_ids == ["session-3"]


def test_load_budget_not_found(temp_budgets_dir):
    """Test loading a non-existent budget."""
    loaded = budgets.load_budget("nonexistent")
    assert loaded is None


def test_set_ceiling_lower(temp_budgets_dir):
    """Test lowering a ceiling (no grantor required)."""
    budgets.create_budget(
        run_id="test-lower",
        origin="council",
        seats=["forge"],
        ceiling_usd=2.00,
        session_ids=["session-1"]
    )
    
    success, msg = budgets.set_ceiling("test-lower", 1.00)
    assert success
    assert "updated" in msg
    
    # Verify the change
    loaded = budgets.load_budget("test-lower")
    assert loaded.ceiling_usd == 1.00


def test_set_ceiling_raise_requires_grantor(temp_budgets_dir):
    """Test that raising a ceiling requires a grantor."""
    budgets.create_budget(
        run_id="test-raise",
        origin="council",
        seats=["forge"],
        ceiling_usd=1.00,
        session_ids=["session-1"]
    )
    
    # Try to raise without grantor
    success, msg = budgets.set_ceiling("test-raise", 2.00)
    assert not success
    assert "grantor" in msg
    
    # Verify ceiling unchanged
    loaded = budgets.load_budget("test-raise")
    assert loaded.ceiling_usd == 1.00


def test_set_ceiling_raise_with_grantor(temp_budgets_dir):
    """Test raising a ceiling with a grantor."""
    budgets.create_budget(
        run_id="test-raise-grantor",
        origin="council",
        seats=["forge"],
        ceiling_usd=1.00,
        session_ids=["session-1"]
    )
    
    success, msg = budgets.set_ceiling("test-raise-grantor", 2.00, grantor="finisher")
    assert success
    assert "updated" in msg
    
    # Verify the change
    loaded = budgets.load_budget("test-raise-grantor")
    assert loaded.ceiling_usd == 2.00


def test_pause_resume_budget(temp_budgets_dir):
    """Test pausing and resuming a budget."""
    budgets.create_budget(
        run_id="test-pause",
        origin="council",
        seats=["forge"],
        ceiling_usd=1.00,
        session_ids=["session-1"]
    )
    
    # Pause
    assert budgets.pause_budget("test-pause")
    loaded = budgets.load_budget("test-pause")
    assert loaded.paused
    
    # Resume
    assert budgets.resume_budget("test-pause")
    loaded = budgets.load_budget("test-pause")
    assert not loaded.paused


def test_pause_budget_not_found(temp_budgets_dir):
    """Test pausing a non-existent budget."""
    assert not budgets.pause_budget("nonexistent")


def test_list_active_budgets(temp_budgets_dir):
    """Test listing active budgets."""
    # Create multiple budgets
    budgets.create_budget("run-1", "council", ["forge"], 1.00, ["s1"])
    budgets.create_budget("run-2", "plan", ["recon"], 0.50, ["s2"])
    
    active = budgets.list_active_budgets()
    assert len(active) == 2
    run_ids = {b.run_id for b in active}
    assert "run-1" in run_ids
    assert "run-2" in run_ids


def test_find_budget_for_session(temp_budgets_dir):
    """Test finding a budget by session ID."""
    budgets.create_budget("run-1", "council", ["forge"], 1.00, ["session-abc", "session-def"])
    budgets.create_budget("run-2", "plan", ["recon"], 0.50, ["session-xyz"])
    
    # Find by session
    found = budgets.find_budget_for_session("session-abc")
    assert found is not None
    assert found.run_id == "run-1"
    
    found = budgets.find_budget_for_session("session-xyz")
    assert found is not None
    assert found.run_id == "run-2"
    
    # Not found
    found = budgets.find_budget_for_session("session-nonexistent")
    assert found is None


def test_effective_spend_drift_multiplier():
    """Test the drift multiplier calculation."""
    # $1.00 estimated becomes $2.50 effective
    assert budgets.effective_spend(1.00) == 2.50
    
    # $0.50 estimated becomes $1.25 effective
    assert budgets.effective_spend(0.50) == 1.25
    
    # $0.00 stays $0.00
    assert budgets.effective_spend(0.00) == 0.00


def test_check_budget_ok(temp_budgets_dir):
    """Test budget check when under ceiling."""
    budgets.create_budget("run-ok", "council", ["forge"], 10.00, ["session-1"])
    
    with patch.object(budgets, 'aggregate_run_spend', return_value=1.00):
        status, spend, ceiling = budgets.check_budget("run-ok")
        assert status == "ok"
        assert spend == 2.50  # 1.00 * 2.5 drift multiplier
        assert ceiling == 10.00


def test_check_budget_warn(temp_budgets_dir):
    """Test budget check when at 80% of ceiling."""
    budgets.create_budget("run-warn", "council", ["forge"], 10.00, ["session-1"])
    
    # 80% of $10.00 = $8.00, so estimated = $8.00 / 2.5 = $3.20
    with patch.object(budgets, 'aggregate_run_spend', return_value=3.20):
        status, spend, ceiling = budgets.check_budget("run-warn")
        assert status == "warn"
        assert spend == 8.00  # 3.20 * 2.5
        assert ceiling == 10.00


def test_check_budget_block(temp_budgets_dir):
    """Test budget check when at or over ceiling."""
    budgets.create_budget("run-block", "council", ["forge"], 10.00, ["session-1"])
    
    # At ceiling: $10.00 effective = $4.00 estimated
    with patch.object(budgets, 'aggregate_run_spend', return_value=4.00):
        status, spend, ceiling = budgets.check_budget("run-block")
        assert status == "block"
        assert spend == 10.00
        assert ceiling == 10.00
    
    # Over ceiling: $12.00 effective = $4.80 estimated
    with patch.object(budgets, 'aggregate_run_spend', return_value=4.80):
        status, spend, ceiling = budgets.check_budget("run-block")
        assert status == "block"
        assert spend == 12.00
        assert ceiling == 10.00


def test_check_budget_paused(temp_budgets_dir):
    """Test budget check when paused."""
    budgets.create_budget("run-paused", "council", ["forge"], 10.00, ["session-1"])
    budgets.pause_budget("run-paused")
    
    status, spend, ceiling = budgets.check_budget("run-paused")
    assert status == "block"
    assert spend == 0.00
    assert ceiling == 10.00


def test_check_daily_budget_ok():
    """Test daily budget check when under ceiling."""
    with patch.object(budgets, 'aggregate_daily_spend', return_value=1.00):
        status, spend, ceiling = budgets.check_daily_budget()
        assert status == "ok"
        assert spend == 2.50  # 1.00 * 2.5
        assert ceiling == 100.00  # default daily ceiling (raised from 10.00 on 2026-09-30 by operator instruction)


def test_check_daily_budget_warn():
    """Test daily budget check when at 80% of ceiling."""
    # 80% of $100.00 = $80.00, so estimated = $80.00 / 2.5 = $32.00
    with patch.object(budgets, 'aggregate_daily_spend', return_value=32.00):
        status, spend, ceiling = budgets.check_daily_budget()
        assert status == "warn"
        assert spend == 80.00
        assert ceiling == 100.00


def test_check_daily_budget_block():
    """Test daily budget check when at or over ceiling."""
    # At ceiling: $100.00 effective = $40.00 estimated
    with patch.object(budgets, 'aggregate_daily_spend', return_value=40.00):
        status, spend, ceiling = budgets.check_daily_budget()
        assert status == "block"
        assert spend == 100.00
        assert ceiling == 100.00


def test_aggregate_run_spend():
    """Test aggregating spend across multiple profiles."""
    budget = budgets.Budget(
        run_id="test-agg",
        origin="council",
        seats=["forge", "finisher"],
        ceiling_usd=5.00,
        started_at=0.0,
        session_ids=["session-1", "session-2"]
    )
    
    # Mock profile_state_db_paths to return two paths
    with patch.object(budgets, 'profile_state_db_paths', return_value=[
        Path("/fake/path1/state.db"),
        Path("/fake/path2/state.db")
    ]):
        # Mock read_profile_spend to return different values
        def mock_read_spend(db_path, session_ids):
            if "path1" in str(db_path):
                return 1.50
            else:
                return 2.00
        
        with patch.object(budgets, 'read_profile_spend', side_effect=mock_read_spend):
            total = budgets.aggregate_run_spend(budget)
            assert total == 3.50  # 1.50 + 2.00


def test_read_profile_spend_with_sessions(tmp_path):
    """Test reading spend for specific sessions."""
    # Use a real file so Path.exists() returns True
    db_path = tmp_path / "state.db"
    db_path.write_bytes(b"")
    session_ids = ["session-1", "session-2"]
    
    # Mock sqlite3.connect
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (2.50,)
    mock_conn.cursor.return_value = mock_cursor
    
    with patch('caduceus.budgets.sqlite3.connect', return_value=mock_conn) as mock_connect:
        spend = budgets.read_profile_spend(db_path, session_ids)
        assert spend == 2.50
        
        # Verify read-only URI was used
        mock_connect.assert_called_once()
        call_args = mock_connect.call_args
        assert "mode=ro" in call_args[0][0]


def test_read_profile_spend_no_db():
    """Test reading spend when DB doesn't exist."""
    db_path = Path("/nonexistent/state.db")
    spend = budgets.read_profile_spend(db_path, ["session-1"])
    assert spend == 0.00


def test_budget_serialization():
    """Test budget to_dict and from_dict."""
    budget = budgets.Budget(
        run_id="test-serial",
        origin="council",
        seats=["forge", "finisher"],
        ceiling_usd=3.50,
        started_at=1234567890.0,
        session_ids=["session-1"],
        paused=True
    )
    
    # Serialize
    d = budget.to_dict()
    assert d["run_id"] == "test-serial"
    assert d["origin"] == "council"
    assert d["seats"] == ["forge", "finisher"]
    assert d["ceiling_usd"] == 3.50
    assert d["started_at"] == 1234567890.0
    assert d["session_ids"] == ["session-1"]
    assert d["paused"] is True
    
    # Deserialize
    restored = budgets.Budget.from_dict(d)
    assert restored.run_id == budget.run_id
    assert restored.origin == budget.origin
    assert restored.seats == budget.seats
    assert restored.ceiling_usd == budget.ceiling_usd
    assert restored.started_at == budget.started_at
    assert restored.session_ids == budget.session_ids
    assert restored.paused == budget.paused


def test_integration_real_sqlite_schema(tmp_path, monkeypatch):
    """F5: Integration test with real SQLite schema to catch column name bugs.
    
    This test creates a real SQLite database with the actual session_model_usage
    schema (including last_seen, not last_used) and verifies that spend aggregation
    works correctly without mocking.
    """
    import sqlite3
    
    # Create a fake profile state.db with real schema
    profile_dir = tmp_path / "profiles" / "forge"
    profile_dir.mkdir(parents=True)
    db_path = profile_dir / "state.db"
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Real schema from Hermes state.db (verified via PRAGMA table_info)
    cursor.execute("""
        CREATE TABLE session_model_usage (
            session_id TEXT,
            model TEXT,
            billing_provider TEXT,
            billing_base_url TEXT,
            billing_mode TEXT,
            task TEXT,
            api_call_count INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read_tokens INTEGER,
            cache_write_tokens INTEGER,
            reasoning_tokens INTEGER,
            estimated_cost_usd REAL,
            actual_cost_usd REAL,
            cost_status TEXT,
            cost_source TEXT,
            first_seen INTEGER,
            last_seen INTEGER
        )
    """)
    
    # Insert test data with recent timestamps
    now = time.time()
    recent = now - 3600  # 1 hour ago
    old = now - 90000    # 25 hours ago (outside 24h window)
    
    cursor.execute("""
        INSERT INTO session_model_usage VALUES (
            'session-1', 'qwen3.7-plus', 'openrouter', '', '', 'council',
            10, 1000, 500, 0, 0, 0, 0.05, NULL, 'estimated', 'openrouter',
            ?, ?
        )
    """, (recent, recent))
    
    cursor.execute("""
        INSERT INTO session_model_usage VALUES (
            'session-2', 'qwen3.7-plus', 'openrouter', '', '', 'council',
            5, 500, 250, 0, 0, 0, 0.03, NULL, 'estimated', 'openrouter',
            ?, ?
        )
    """, (recent, recent))
    
    # Old entry that should NOT be counted in daily aggregation
    cursor.execute("""
        INSERT INTO session_model_usage VALUES (
            'session-old', 'qwen3.7-plus', 'openrouter', '', '', 'council',
            20, 2000, 1000, 0, 0, 0, 0.10, NULL, 'estimated', 'openrouter',
            ?, ?
        )
    """, (old, old))
    
    conn.commit()
    conn.close()
    
    # Monkeypatch profile_state_db_paths to return our test DB
    monkeypatch.setattr(budgets, 'profile_state_db_paths', lambda: [db_path])
    
    # Test read_profile_spend with specific sessions
    spend = budgets.read_profile_spend(db_path, ['session-1', 'session-2'])
    assert abs(spend - 0.08) < 0.001, f"Expected 0.08, got {spend}"
    
    # Test aggregate_daily_spend (should only count recent entries, not old)
    daily = budgets.aggregate_daily_spend()
    assert abs(daily - 0.08) < 0.001, f"Expected 0.08 (recent only), got {daily}"
    
    # Verify the old entry is excluded
    all_spend = budgets.read_profile_spend(db_path, None)
    assert abs(all_spend - 0.18) < 0.001, f"Expected 0.18 (all entries), got {all_spend}"
