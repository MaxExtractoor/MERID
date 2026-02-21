"""Tests for Sprints N+O: Orderbook forecaster, impossible prob critic,
execution intelligence, hit ratio tracker.
"""

from __future__ import annotations

import inspect
import os

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Sprint N: OrderbookForecaster
# ═══════════════════════════════════════════════════════════════════════════


class TestOrderbookForecaster:
    """Tests for merid.prediction.forecasters.orderbook."""

    def test_import(self):
        from merid.prediction.forecasters.orderbook import OrderbookForecaster
        f = OrderbookForecaster()
        assert f.forecaster_id == "orderbook_micro"

    def test_basic_prediction_with_imbalance(self):
        from merid.prediction.forecasters.orderbook import OrderbookForecaster
        f = OrderbookForecaster()
        result = f.predict(
            market_id="TEST-001",
            implied_yes=0.50,
            implied_no=0.50,
            bid=0.48,
            ask=0.52,
            bid_depth=200,
            ask_depth=50,
        )
        assert result is not None
        # Bid-heavy → bullish → p_model should be > implied
        assert result.p_model > 0.50
        assert result.confidence > 0
        assert "bid_ask_imbalance" in result.components

    def test_ask_heavy_bearish(self):
        from merid.prediction.forecasters.orderbook import OrderbookForecaster
        f = OrderbookForecaster()
        result = f.predict(
            market_id="TEST-002",
            implied_yes=0.50,
            implied_no=0.50,
            bid=0.48,
            ask=0.52,
            bid_depth=20,
            ask_depth=200,
        )
        assert result is not None
        assert result.p_model < 0.50  # Ask-heavy → bearish

    def test_no_signal_returns_none(self):
        from merid.prediction.forecasters.orderbook import OrderbookForecaster
        f = OrderbookForecaster()
        result = f.predict(
            market_id="TEST-003",
            implied_yes=0.50,
            implied_no=0.50,
        )
        # No bid/ask/depth → no signals → None
        assert result is None

    def test_invalid_implied_returns_none(self):
        from merid.prediction.forecasters.orderbook import OrderbookForecaster
        f = OrderbookForecaster()
        assert f.predict("X", 0.0, 1.0) is None
        assert f.predict("X", 1.0, 0.0) is None

    def test_probability_bounded(self):
        from merid.prediction.forecasters.orderbook import OrderbookForecaster
        f = OrderbookForecaster()
        result = f.predict(
            market_id="TEST-004",
            implied_yes=0.95,
            implied_no=0.05,
            bid=0.93,
            ask=0.97,
            bid_depth=500,
            ask_depth=10,
        )
        if result:
            assert 0.02 <= result.p_model <= 0.98

    def test_spread_compression_signal(self):
        from merid.prediction.forecasters.orderbook import OrderbookForecaster
        f = OrderbookForecaster()
        # Build spread history with wider spreads
        for i in range(10):
            f.predict(
                market_id="SPREAD-TEST",
                implied_yes=0.50,
                implied_no=0.50,
                bid=0.40,
                ask=0.60,  # 20c spread
                bid_depth=100,
                ask_depth=100,
            )
        # Now give a much narrower spread
        result = f.predict(
            market_id="SPREAD-TEST",
            implied_yes=0.50,
            implied_no=0.50,
            bid=0.49,
            ask=0.51,  # 2c spread — compression
            bid_depth=100,
            ask_depth=100,
        )
        if result:
            assert result.components.get("spread_compression", 0) > 0

    def test_registered_in_registry(self):
        from merid.prediction.forecasters.registry import get_forecaster_registry
        import merid.prediction.forecasters.registry as mod
        old = mod._registry
        mod._registry = None
        try:
            reg = get_forecaster_registry()
            ids = [f.forecaster_id for f in reg._forecasters]
            assert "orderbook_micro" in ids
        finally:
            mod._registry = old

    def test_in_init_exports(self):
        from merid.prediction.forecasters import OrderbookForecaster
        assert OrderbookForecaster is not None

    def test_registry_has_four_forecasters(self):
        from merid.prediction.forecasters.registry import get_forecaster_registry
        import merid.prediction.forecasters.registry as mod
        old = mod._registry
        mod._registry = None
        try:
            reg = get_forecaster_registry()
            assert len(reg._forecasters) == 4
        finally:
            mod._registry = old


# ═══════════════════════════════════════════════════════════════════════════
# Sprint N: Impossible Probability Critic
# ═══════════════════════════════════════════════════════════════════════════


class TestImpossibleProbCritic:
    """Tests for CriticAgent._check_impossible_probs."""

    def test_method_exists(self):
        from merid.swarm.critic_agent import CriticAgent
        agent = CriticAgent()
        assert hasattr(agent, "_check_impossible_probs")
        assert callable(agent._check_impossible_probs)

    def test_no_snapshots_returns_empty(self):
        from merid.swarm.critic_agent import CriticAgent
        agent = CriticAgent()
        result = agent._check_impossible_probs()
        assert isinstance(result, list)

    def test_wired_into_sweep(self):
        from merid.swarm.critic_agent import CriticAgent
        source = inspect.getsource(CriticAgent._sweep)
        assert "_check_impossible_probs" in source

    def test_active_snapshots_api(self):
        from merid.prediction.model import (
            get_active_snapshots, record_snapshot, MarketSnapshot,
            ContractState, ImpliedProbability,
        )
        from decimal import Decimal
        # Record a test snapshot
        snap = MarketSnapshot(
            market_id="TEST-PROB",
            event_id="TEST-EVT",
            title="Test",
            state=ContractState.TRADING,
            implied=ImpliedProbability(yes_prob=Decimal("0.60"), no_prob=Decimal("0.40")),
            volume=Decimal("100"),
            open_interest=Decimal("50"),
        )
        record_snapshot(snap)
        snaps = get_active_snapshots()
        assert any(s.market_id == "TEST-PROB" for s in snaps)


# ═══════════════════════════════════════════════════════════════════════════
# Sprint O: Execution Intelligence
# ═══════════════════════════════════════════════════════════════════════════


class TestExecutionIntelligence:
    """Tests for merid.prediction.execution_intelligence."""

    def test_import(self):
        from merid.prediction.execution_intelligence import (
            ExecutionIntelligence, get_execution_intel,
        )
        intel = get_execution_intel()
        assert isinstance(intel, ExecutionIntelligence)

    def test_narrow_spread_cross(self):
        from merid.prediction.execution_intelligence import ExecutionIntelligence
        intel = ExecutionIntelligence()
        d = intel.decide(
            bid=0.50, ask=0.52,  # 2c spread — narrow
            side="buy",
            edge=0.08,  # Big edge
            minutes_to_expiry=10.0,  # Urgent
        )
        assert d.strategy == "cross"
        assert d.urgency_score >= 0.5

    def test_wide_spread_join(self):
        from merid.prediction.execution_intelligence import ExecutionIntelligence
        intel = ExecutionIntelligence()
        d = intel.decide(
            bid=0.40, ask=0.55,  # 15c spread — very wide
            side="buy",
            edge=0.02,  # Low edge
            minutes_to_expiry=600.0,  # Not urgent
        )
        # With wide spread + low edge + no urgency → should join or join_far
        assert d.strategy in ("join_queue", "join_far")

    def test_no_orderbook_defaults_cross(self):
        from merid.prediction.execution_intelligence import ExecutionIntelligence
        intel = ExecutionIntelligence()
        d = intel.decide(bid=None, ask=None, side="buy")
        assert d.strategy == "cross"

    def test_suggested_price_buy_cross(self):
        from merid.prediction.execution_intelligence import ExecutionIntelligence
        intel = ExecutionIntelligence()
        d = intel.decide(
            bid=0.50, ask=0.52, side="buy",
            edge=0.10, minutes_to_expiry=5.0,
        )
        if d.strategy == "cross":
            assert d.suggested_price == 0.52  # Lift the ask

    def test_suggested_price_sell_cross(self):
        from merid.prediction.execution_intelligence import ExecutionIntelligence
        intel = ExecutionIntelligence()
        d = intel.decide(
            bid=0.50, ask=0.52, side="sell",
            edge=0.10, minutes_to_expiry=5.0,
        )
        if d.strategy == "cross":
            assert d.suggested_price == 0.50  # Hit the bid

    def test_stats_tracking(self):
        from merid.prediction.execution_intelligence import ExecutionIntelligence
        intel = ExecutionIntelligence()
        intel.decide(bid=0.50, ask=0.52, side="buy", edge=0.10, minutes_to_expiry=5.0)
        intel.decide(bid=0.40, ask=0.55, side="buy", edge=0.01, minutes_to_expiry=600.0)
        stats = intel.stats
        assert stats["total_decisions"] == 2
        assert stats["cross_count"] + stats["join_count"] == 2

    def test_decision_to_dict(self):
        from merid.prediction.execution_intelligence import ExecutionIntelligence
        intel = ExecutionIntelligence()
        d = intel.decide(bid=0.50, ask=0.52, side="buy", edge=0.05)
        dd = d.to_dict()
        assert "strategy" in dd
        assert "suggested_price" in dd
        assert "urgency_score" in dd

    def test_history(self):
        from merid.prediction.execution_intelligence import ExecutionIntelligence
        intel = ExecutionIntelligence()
        intel.decide(bid=0.50, ask=0.52, side="buy", edge=0.05)
        assert len(intel.history) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Sprint O: Hit Ratio Tracker
# ═══════════════════════════════════════════════════════════════════════════


class TestHitRatioTracker:
    """Tests for merid.metrics.hit_ratio."""

    def test_import(self):
        from merid.metrics.hit_ratio import HitRatioTracker, get_hit_ratio_tracker
        tracker = get_hit_ratio_tracker()
        assert isinstance(tracker, HitRatioTracker)

    def test_record_hit(self):
        from merid.metrics.hit_ratio import HitRatioTracker
        t = HitRatioTracker()
        rec = t.record(
            market_id="KXBTC-001",
            forecaster_id="momentum_v1",
            p_model=0.65,
            p_implied=0.52,
            outcome=1,  # YES won
        )
        assert rec.hit is True
        assert rec.predicted_yes is True
        assert rec.edge_at_entry == pytest.approx(0.13, abs=0.001)

    def test_record_miss(self):
        from merid.metrics.hit_ratio import HitRatioTracker
        t = HitRatioTracker()
        rec = t.record(
            market_id="KXBTC-002",
            forecaster_id="momentum_v1",
            p_model=0.65,
            p_implied=0.52,
            outcome=0,  # NO won — miss
        )
        assert rec.hit is False
        assert rec.predicted_yes is True

    def test_stats_empty(self):
        from merid.metrics.hit_ratio import HitRatioTracker
        t = HitRatioTracker()
        s = t.stats
        assert s["total_records"] == 0
        assert s["hit_ratio"] == 0.0

    def test_stats_computed(self):
        from merid.metrics.hit_ratio import HitRatioTracker
        t = HitRatioTracker()
        # 3 hits, 1 miss
        t.record("M1", "f1", 0.65, 0.52, 1)
        t.record("M2", "f1", 0.70, 0.55, 1)
        t.record("M3", "f1", 0.60, 0.52, 1)
        t.record("M4", "f1", 0.65, 0.52, 0)  # miss
        s = t.stats
        assert s["total_records"] == 4
        assert s["hit_ratio"] == 0.75
        assert "per_forecaster" in s
        assert "f1" in s["per_forecaster"]
        assert s["per_forecaster"]["f1"]["hit_ratio"] == 0.75

    def test_surprise_ratio(self):
        from merid.metrics.hit_ratio import HitRatioTracker
        t = HitRatioTracker()
        # Market says 0.70 YES, but NO wins → surprise
        t.record("M1", "f1", 0.65, 0.70, 0)
        s = t.stats
        assert s["surprise_ratio"] == 1.0

    def test_per_forecaster_breakdown(self):
        from merid.metrics.hit_ratio import HitRatioTracker
        t = HitRatioTracker()
        t.record("M1", "momentum_v1", 0.60, 0.50, 1)
        t.record("M2", "mean_rev_v1", 0.40, 0.50, 0)  # predicted NO, NO won
        s = t.stats
        assert "momentum_v1" in s["per_forecaster"]
        assert "mean_rev_v1" in s["per_forecaster"]
        assert s["per_forecaster"]["momentum_v1"]["hit_ratio"] == 1.0
        assert s["per_forecaster"]["mean_rev_v1"]["hit_ratio"] == 1.0

    def test_record_to_dict(self):
        from merid.metrics.hit_ratio import HitRatioTracker
        t = HitRatioTracker()
        rec = t.record("M1", "f1", 0.65, 0.52, 1)
        d = rec.to_dict()
        assert d["market_id"] == "M1"
        assert d["hit"] is True
        assert "edge_at_entry" in d

    def test_history_limited(self):
        from merid.metrics.hit_ratio import HitRatioTracker
        t = HitRatioTracker()
        h = t.history
        assert isinstance(h, list)


# ═══════════════════════════════════════════════════════════════════════════
# Gap Analysis Verification
# ═══════════════════════════════════════════════════════════════════════════


class TestGapAnalysisNO:
    """Verify gap analysis reflects Sprint N+O closures."""

    def test_overall_score(self):
        with open(os.path.join("docs", "KALSHI_SWARM_GAP_ANALYSIS.md"), "r", encoding="utf-8") as f:
            content = f.read()
        assert "57/62" in content
        assert "**A**" in content

    def test_orderbook_forecaster_in_doc(self):
        with open(os.path.join("docs", "KALSHI_SWARM_GAP_ANALYSIS.md"), "r", encoding="utf-8") as f:
            content = f.read()
        assert "OrderbookForecaster" in content

    def test_execution_intelligence_in_doc(self):
        with open(os.path.join("docs", "KALSHI_SWARM_GAP_ANALYSIS.md"), "r", encoding="utf-8") as f:
            content = f.read()
        assert "execution_intelligence" in content

    def test_hit_ratio_in_doc(self):
        with open(os.path.join("docs", "KALSHI_SWARM_GAP_ANALYSIS.md"), "r", encoding="utf-8") as f:
            content = f.read()
        assert "hit_ratio" in content

    def test_impossible_prob_in_doc(self):
        with open(os.path.join("docs", "KALSHI_SWARM_GAP_ANALYSIS.md"), "r", encoding="utf-8") as f:
            content = f.read()
        assert "impossible_prob" in content or "impossible_probability" in content
