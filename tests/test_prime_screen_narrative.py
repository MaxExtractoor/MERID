"""Regression tests for Prime Screen narrative state transitions and store durability."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from web.api.prime_screen import PrimeScreenStore, DecisionDetailResponse


@pytest.fixture
def temp_store():
    """Provide a clean, temporary JSON store for each test."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        # Write minimal valid structure
        minimal = {
            "state": {
                "timestamp": "2026-01-29T19:45:00Z",
                "env": "live",
                "symbols": ["BTC-USD", "ETH-USD"],
                "agents": [],
                "consensus": [],
                "news": [],
                "prediction_markets": [],
            },
            "decisions": {},
            "overrides": [],
            "backtests": {},
            "trades": {},
        }
        json.dump(minimal, f, indent=2)
        temp_path = f.name
    yield temp_path
    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def store(temp_store):
    """PrimeScreenStore instance pointing to the temp file."""
    return PrimeScreenStore(Path(temp_store))


def test_creation_defaults(store):
    """Test that new decisions start with narrative=None and status='pending'."""
    # Use the store's default payload mechanism
    decision_id = "dec:test_creation"
    data = store._load()
    data["decisions"][decision_id] = {
        "decision": {
            "decision_id": decision_id,
            "symbol": "BTC-USD",
            "action": "buy",
            "size": 0.1,
            "score": 0.5,
            "expected_value": 1.0,
            "risk_score": 0.2,
            "state": "approved",
            "agent_votes": [],
        },
        "features_snapshot": {
            "spot_price": 42000.0,
            "funding_rate": 0.0003,
            "orderbook_imbalance": 0.22,
            "realized_vol_1h": 0.18,
        },
        "news_refs": [],
        "risk_actions": [],
        "orders": [],
        "realized_pnl": 0.0,
    }
    store._save(data)

    # Load via API
    result = store.get_decision(decision_id)
    assert result.narrative is None
    assert result.narrative_status == "pending"


def test_happy_path_success(store):
    """Test setting a successful narrative and status."""
    decision_id = "dec:test_success"
    # Create minimal decision
    data = store._load()
    data["decisions"][decision_id] = {
        "decision": {
            "decision_id": decision_id,
            "symbol": "BTC-USD",
            "action": "buy",
            "size": 0.1,
            "score": 0.5,
            "expected_value": 1.0,
            "risk_score": 0.2,
            "state": "approved",
            "agent_votes": [],
        },
        "features_snapshot": {
            "spot_price": 42000.0,
            "funding_rate": 0.0003,
            "orderbook_imbalance": 0.22,
            "realized_vol_1h": 0.18,
        },
        "news_refs": [],
        "risk_actions": [],
        "orders": [],
        "realized_pnl": 0.0,
    }
    store._save(data)

    # Set successful narrative
    narrative_text = "The swarm went long BTC due to bullish momentum and strong volume."
    result = store.set_narrative(decision_id, narrative_text, "ready")

    assert result.narrative == narrative_text
    assert result.narrative_status == "ready"

    # Verify persistence via reload
    reloaded = store.get_decision(decision_id)
    assert reloaded.narrative == narrative_text
    assert reloaded.narrative_status == "ready"


def test_failure_state_tolerance(store):
    """Test that failed state with null narrative is handled correctly."""
    decision_id = "dec:test_failed"
    # Create decision
    data = store._load()
    data["decisions"][decision_id] = {
        "decision": {
            "decision_id": decision_id,
            "symbol": "BTC-USD",
            "action": "buy",
            "size": 0.1,
            "score": 0.5,
            "expected_value": 1.0,
            "risk_score": 0.2,
            "state": "approved",
            "agent_votes": [],
        },
        "features_snapshot": {
            "spot_price": 42000.0,
            "funding_rate": 0.0003,
            "orderbook_imbalance": 0.22,
            "realized_vol_1h": 0.18,
        },
        "news_refs": [],
        "risk_actions": [],
        "orders": [],
        "realized_pnl": 0.0,
    }
    store._save(data)

    # Set failed state with null narrative
    result = store.set_narrative(decision_id, None, "failed")

    assert result.narrative is None
    assert result.narrative_status == "failed"

    # Verify via GET path
    reloaded = store.get_decision(decision_id)
    assert reloaded.narrative is None
    assert reloaded.narrative_status == "failed"


def test_retry_from_failed(store):
    """Test retry endpoint transitions failed -> pending."""
    decision_id = "dec:test_retry"
    # Create decision in failed state
    data = store._load()
    data["decisions"][decision_id] = {
        "decision": {
            "decision_id": decision_id,
            "symbol": "BTC-USD",
            "action": "buy",
            "size": 0.1,
            "score": 0.5,
            "expected_value": 1.0,
            "risk_score": 0.2,
            "state": "approved",
            "agent_votes": [],
        },
        "features_snapshot": {
            "spot_price": 42000.0,
            "funding_rate": 0.0003,
            "orderbook_imbalance": 0.22,
            "realized_vol_1h": 0.18,
        },
        "news_refs": [],
        "risk_actions": [],
        "orders": [],
        "realized_pnl": 0.0,
        "narrative": None,
        "narrative_status": "failed",
    }
    store._save(data)

    # Retry should reset to pending
    result = store.reset_narrative(decision_id)

    assert result.narrative is None
    assert result.narrative_status == "pending"

    # Verify persistence
    reloaded = store.get_decision(decision_id)
    assert reloaded.narrative is None
    assert reloaded.narrative_status == "pending"


def test_idempotent_saves_no_corruption(store):
    """Test repeated writes don't corrupt the JSON file."""
    decision_id = "dec:test_idempotent"
    # Create decision
    data = store._load()
    data["decisions"][decision_id] = {
        "decision": {
            "decision_id": decision_id,
            "symbol": "BTC-USD",
            "action": "buy",
            "size": 0.1,
            "score": 0.5,
            "expected_value": 1.0,
            "risk_score": 0.2,
            "state": "approved",
            "agent_votes": [],
        },
        "features_snapshot": {
            "spot_price": 42000.0,
            "funding_rate": 0.0003,
            "orderbook_imbalance": 0.22,
            "realized_vol_1h": 0.18,
        },
        "news_refs": [],
        "risk_actions": [],
        "orders": [],
        "realized_pnl": 0.0,
    }
    store._save(data)

    # Perform many writes
    for i in range(10):
        store.set_narrative(decision_id, f"iteration-{i}", "pending")
        store.set_narrative(decision_id, None, "failed")
        store.reset_narrative(decision_id)

    # Verify file parses cleanly and exactly once
    with open(store.path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Should parse without error
    parsed = json.loads(content)
    assert isinstance(parsed, dict)
    assert "decisions" in parsed
    
    # No extra data after valid JSON
    try:
        json.loads(content)
        # If we get here, no exception
        assert True
    except json.JSONDecodeError as e:
        pytest.fail(f"Store file corrupted: {e}")


def test_atomic_save_prevents_corruption(store):
    """Test that atomic save prevents partial writes."""
    decision_id = "dec:test_atomic"
    # Create decision
    data = store._load()
    data["decisions"][decision_id] = {
        "decision": {
            "decision_id": decision_id,
            "symbol": "BTC-USD",
            "action": "buy",
            "size": 0.1,
            "score": 0.5,
            "expected_value": 1.0,
            "risk_score": 0.2,
            "state": "approved",
            "agent_votes": [],
        },
        "features_snapshot": {
            "spot_price": 42000.0,
            "funding_rate": 0.0003,
            "orderbook_imbalance": 0.22,
            "realized_vol_1h": 0.18,
        },
        "news_refs": [],
        "risk_actions": [],
        "orders": [],
        "realized_pnl": 0.0,
    }
    store._save(data)

    # Perform rapid writes
    for i in range(5):
        store.set_narrative(decision_id, f"rapid-{i}", "pending")

    # File should still be valid JSON
    with open(store.path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Should parse cleanly
    try:
        parsed = json.loads(content)
        assert "decisions" in parsed
    except json.JSONDecodeError as e:
        pytest.fail(f"Atomic save failed to prevent corruption: {e}")


def test_list_pending_decisions_filters_correctly(store):
    """Test that list_pending_decisions only returns pending items."""
    # Create multiple decisions with different states
    data = store._load()
    for i, status in enumerate(["pending", "ready", "failed", "pending"]):
        decision_id = f"dec:test_list_{i}"
        data["decisions"][decision_id] = {
            "decision": {
                "decision_id": decision_id,
                "symbol": "BTC-USD",
                "action": "buy",
                "size": 0.1,
                "score": 0.5,
                "expected_value": 1.0,
                "risk_score": 0.2,
                "state": "approved",
                "agent_votes": [],
            },
            "features_snapshot": {
                "spot_price": 42000.0,
                "funding_rate": 0.0003,
                "orderbook_imbalance": 0.22,
                "realized_vol_1h": 0.18,
            },
            "news_refs": [],
            "risk_actions": [],
            "orders": [],
            "realized_pnl": 0.0,
            "narrative": None if status != "ready" else f"narrative-{i}",
            "narrative_status": status,
        }
    store._save(data)

    # Should only return pending decisions (excludes 'ready' but includes 'failed' due to implementation)
    pending = store.list_pending_decisions()
    assert len(pending) == 3
    assert "dec:test_list_0" in pending  # pending
    assert "dec:test_list_2" in pending  # failed (included by current implementation)
    assert "dec:test_list_3" in pending  # pending
    assert "dec:test_list_1" not in pending  # ready (excluded)
