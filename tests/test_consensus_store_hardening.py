"""Tests for consensus store hardening: validation, dedup, metrics, and load behavior.

Covers:
- Opinion validation (malformed rejection)
- Dedup within configurable window
- Store metrics surface (instrument counts, opinion volume, staleness)
- Load behavior (many opinions, many instruments)
"""

import os
import tempfile
import time

import pytest

from merid.prediction.consensus import (
    PredictionConsensusStore,
    PredictionInstrument,
    PredictionOpinion,
    PredictionPlan,
    ResolvedMarket,
)


@pytest.fixture
def store(tmp_path):
    """Create a fresh store with an in-memory-like temp DB for each test."""
    db_path = os.path.join(str(tmp_path), "test_consensus.db")
    return PredictionConsensusStore(db_path=db_path)


def _make_opinion(**kwargs) -> PredictionOpinion:
    defaults = {
        "agent_id": "test-agent",
        "agent_name": "TestAgent",
        "symbol": "PRED:KALSHI:TEST:YES",
        "probability": 0.60,
        "confidence": 0.70,
        "reasoning": "test reasoning",
        "signal_sources": ["test"],
        "horizon": "event",
    }
    defaults.update(kwargs)
    return PredictionOpinion(**defaults)


def _make_instrument(**kwargs) -> PredictionInstrument:
    defaults = {
        "symbol": "PRED:KALSHI:TEST:YES",
        "venue": "kalshi",
        "ticker": "TEST",
        "category": "macro",
        "title": "Test instrument",
        "market_implied_prob": 0.50,
        "status": "active",
        "last_refreshed": time.time(),
    }
    defaults.update(kwargs)
    return PredictionInstrument(**defaults)


# ── Validation Tests ──────────────────────────────────────────────────

class TestOpinionValidation:
    """Verify malformed opinions are rejected."""

    def test_rejects_empty_agent_id(self, store):
        op = _make_opinion(agent_id="")
        with pytest.raises(ValueError, match="agent_id is required"):
            store.add_opinion(op)

    def test_rejects_whitespace_agent_id(self, store):
        op = _make_opinion(agent_id="   ")
        with pytest.raises(ValueError, match="agent_id is required"):
            store.add_opinion(op)

    def test_rejects_empty_symbol(self, store):
        op = _make_opinion(symbol="")
        with pytest.raises(ValueError, match="symbol is required"):
            store.add_opinion(op)

    def test_rejects_probability_below_zero(self, store):
        op = _make_opinion(probability=-0.1)
        with pytest.raises(ValueError, match="probability must be 0"):
            store.add_opinion(op)

    def test_rejects_probability_above_one(self, store):
        op = _make_opinion(probability=1.5)
        with pytest.raises(ValueError, match="probability must be 0"):
            store.add_opinion(op)

    def test_rejects_confidence_below_zero(self, store):
        op = _make_opinion(confidence=-0.5)
        with pytest.raises(ValueError, match="confidence must be 0"):
            store.add_opinion(op)

    def test_rejects_confidence_above_one(self, store):
        op = _make_opinion(confidence=2.0)
        with pytest.raises(ValueError, match="confidence must be 0"):
            store.add_opinion(op)

    def test_rejects_invalid_horizon(self, store):
        op = _make_opinion(horizon="invalid")
        with pytest.raises(ValueError, match="horizon must be"):
            store.add_opinion(op)

    def test_accepts_valid_opinion(self, store):
        op = _make_opinion()
        result = store.add_opinion(op)
        assert result.id == op.id

    def test_accepts_boundary_probability_zero(self, store):
        op = _make_opinion(probability=0.0)
        result = store.add_opinion(op)
        assert result.probability == 0.0

    def test_accepts_boundary_probability_one(self, store):
        op = _make_opinion(probability=1.0, id="boundary-1")
        result = store.add_opinion(op)
        assert result.probability == 1.0

    def test_accepts_all_valid_horizons(self, store):
        for i, h in enumerate(["event", "short", "medium"]):
            op = _make_opinion(horizon=h, id=f"horizon-{i}", symbol=f"PRED:KALSHI:H{i}:YES")
            result = store.add_opinion(op)
            assert result.horizon == h

    def test_validate_opinion_returns_none_for_valid(self, store):
        op = _make_opinion()
        assert store.validate_opinion(op) is None


# ── Dedup Tests ───────────────────────────────────────────────────────

class TestOpinionDedup:
    """Verify dedup prevents duplicate opinions within the window."""

    def test_dedup_blocks_rapid_duplicate(self, store):
        """Same agent+symbol within dedup window should not create a second row."""
        op1 = _make_opinion(id="op-1")
        op2 = _make_opinion(id="op-2")  # Same agent_id + symbol

        store.add_opinion(op1)
        store.add_opinion(op2)  # Should be silently deduped

        opinions = store.list_opinions(symbol="PRED:KALSHI:TEST:YES")
        assert len(opinions) == 1
        assert opinions[0].id == "op-1"

    def test_dedup_allows_different_agents(self, store):
        """Different agents on the same symbol should both be accepted."""
        op1 = _make_opinion(agent_id="agent-A", id="op-a")
        op2 = _make_opinion(agent_id="agent-B", id="op-b")

        store.add_opinion(op1)
        store.add_opinion(op2)

        opinions = store.list_opinions(symbol="PRED:KALSHI:TEST:YES")
        assert len(opinions) == 2

    def test_dedup_allows_different_symbols(self, store):
        """Same agent on different symbols should both be accepted."""
        op1 = _make_opinion(symbol="PRED:KALSHI:AAA:YES", id="op-1")
        op2 = _make_opinion(symbol="PRED:KALSHI:BBB:YES", id="op-2")

        store.add_opinion(op1)
        store.add_opinion(op2)

        all_opinions = store.list_opinions()
        assert len(all_opinions) == 2

    def test_dedup_allows_after_window_expires(self, store):
        """After the dedup window, a new opinion from the same agent+symbol should be accepted."""
        # Set a very short dedup window for testing
        store.OPINION_DEDUP_WINDOW = 0.1

        op1 = _make_opinion(id="op-old")
        store.add_opinion(op1)

        time.sleep(0.15)  # Wait for dedup window to expire

        op2 = _make_opinion(id="op-new")
        store.add_opinion(op2)

        opinions = store.list_opinions(symbol="PRED:KALSHI:TEST:YES")
        assert len(opinions) == 2

    def test_dedup_returns_opinion_without_error(self, store):
        """Deduped opinion should return normally (not raise)."""
        op1 = _make_opinion(id="op-1")
        op2 = _make_opinion(id="op-2")

        store.add_opinion(op1)
        result = store.add_opinion(op2)
        assert result.id == "op-2"  # Returns the opinion even though it wasn't inserted


# ── Store Metrics Tests ───────────────────────────────────────────────

class TestStoreMetrics:
    """Verify get_store_metrics returns correct operational data."""

    def test_empty_store_metrics(self, store):
        metrics = store.get_store_metrics()
        assert metrics["instruments"]["total"] == 0
        assert metrics["opinions"]["total"] == 0
        assert metrics["resolved"]["total"] == 0
        assert metrics["plans"] == {}

    def test_metrics_after_adding_instruments(self, store):
        store.upsert_instrument(_make_instrument(symbol="PRED:KALSHI:A:YES"))
        store.upsert_instrument(_make_instrument(symbol="PRED:KALSHI:B:YES"))
        store.upsert_instrument(_make_instrument(symbol="PRED:KALSHI:C:YES", status="closed"))

        metrics = store.get_store_metrics()
        assert metrics["instruments"]["total"] == 3
        assert metrics["instruments"]["by_status"]["active"] == 2
        assert metrics["instruments"]["by_status"]["closed"] == 1

    def test_metrics_after_adding_opinions(self, store):
        store.add_opinion(_make_opinion(id="op-1", symbol="PRED:KALSHI:A:YES"))
        store.add_opinion(_make_opinion(id="op-2", symbol="PRED:KALSHI:B:YES", agent_id="agent-2"))

        metrics = store.get_store_metrics()
        assert metrics["opinions"]["total"] == 2
        assert metrics["opinions"]["last_1h"] == 2
        assert metrics["opinions"]["last_24h"] == 2
        assert metrics["opinions"]["active_agents"] == 2

    def test_metrics_staleness_fresh(self, store):
        """Recently added opinions should not be marked stale."""
        store.add_opinion(_make_opinion())

        metrics = store.get_store_metrics()
        assert metrics["opinions"]["stale"] is False
        assert metrics["opinions"]["newest_age_s"] is not None
        assert metrics["opinions"]["newest_age_s"] < 5  # Should be very fresh

    def test_metrics_instrument_staleness(self, store):
        store.upsert_instrument(_make_instrument())

        metrics = store.get_store_metrics()
        assert metrics["instruments"]["stale"] is False
        assert metrics["instruments"]["newest_refresh_age_s"] is not None
        assert metrics["instruments"]["newest_refresh_age_s"] < 5

    def test_metrics_resolved_count(self, store):
        store.upsert_instrument(_make_instrument(symbol="PRED:KALSHI:R:YES"))
        store.record_resolution(ResolvedMarket(symbol="PRED:KALSHI:R:YES", outcome=1))

        metrics = store.get_store_metrics()
        assert metrics["resolved"]["total"] == 1

    def test_metrics_plans_by_status(self, store):
        store.add_plan(PredictionPlan(symbol="PRED:KALSHI:P:YES", status="proposed"))
        store.add_plan(PredictionPlan(id="plan-2", symbol="PRED:KALSHI:P:YES", status="executing"))

        metrics = store.get_store_metrics()
        assert metrics["plans"]["proposed"] == 1
        assert metrics["plans"]["executing"] == 1


# ── Load Behavior Tests ──────────────────────────────────────────────

class TestLoadBehavior:
    """Verify store handles realistic load without errors."""

    def test_many_instruments(self, store):
        """Store should handle 100+ instruments without issue."""
        for i in range(100):
            store.upsert_instrument(_make_instrument(
                symbol=f"PRED:KALSHI:LOAD{i}:YES",
                ticker=f"LOAD{i}",
            ))

        assert store.instrument_count() == 100
        assert store.instrument_count(status="active") == 100

    def test_many_opinions_different_agents(self, store):
        """Store should handle opinions from many different agents."""
        for i in range(50):
            store.add_opinion(_make_opinion(
                id=f"load-op-{i}",
                agent_id=f"agent-{i}",
                symbol=f"PRED:KALSHI:LOAD{i % 10}:YES",
            ))

        opinions = store.list_opinions(limit=100)
        assert len(opinions) == 50

    def test_metrics_under_load(self, store):
        """Metrics should still be fast with populated store."""
        for i in range(50):
            store.upsert_instrument(_make_instrument(
                symbol=f"PRED:KALSHI:M{i}:YES",
                ticker=f"M{i}",
            ))
        for i in range(50):
            store.add_opinion(_make_opinion(
                id=f"m-op-{i}",
                agent_id=f"agent-{i % 5}",
                symbol=f"PRED:KALSHI:M{i % 50}:YES",
            ))

        t0 = time.monotonic()
        metrics = store.get_store_metrics()
        elapsed_ms = (time.monotonic() - t0) * 1000

        assert metrics["instruments"]["total"] == 50
        assert metrics["opinions"]["total"] == 50
        assert elapsed_ms < 500  # Should be fast even with 100 rows

    def test_consensus_summary_under_load(self, store):
        """Consensus summary should work with many instruments and opinions."""
        for i in range(20):
            store.upsert_instrument(_make_instrument(
                symbol=f"PRED:KALSHI:CS{i}:YES",
                ticker=f"CS{i}",
            ))
        for i in range(20):
            store.add_opinion(_make_opinion(
                id=f"cs-op-{i}",
                agent_id=f"agent-{i % 3}",
                symbol=f"PRED:KALSHI:CS{i % 20}:YES",
            ))

        summary = store.get_consensus_summary()
        assert len(summary) == 20
        for item in summary:
            assert "swarm_prob" in item
            assert "edge" in item
            assert "stance" in item
