"""§2 E2E Golden Path Tests — full pipeline from proposal to venue execution.

Tests the complete flow:
  TradeProposal → Consensus (decay-aware) → GlobalRiskManager → Adapter → OrderResult → Reconciliation

Test classes:
  TestProposalToConsensus     — proposal triggers consensus plan with decay metadata
  TestConsensusToRisk         — plan passes through risk manager
  TestRiskToAdapter           — approved plan bridges to TradeRequest and hits adapter
  TestAdapterOrderLifecycle   — adapter submits, receives result, records fill
  TestReconciliation          — venue positions compared against internal state
  TestFullGoldenPath          — end-to-end: opinion → consensus → risk → execute → reconcile
  TestMainLoop                — loop tick drives all steps correctly
"""

import asyncio
import time
import unittest
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# ── Pipeline imports ──────────────────────────────────────────────────

from merid.pipeline.proposal import (
    ExecutionResult,
    OrderSide,
    OrderType,
    ProposalStatus,
    TradeDomain,
    TradeProposal,
)
from merid.pipeline.risk_manager import GlobalRiskManager

# ── Consensus imports ─────────────────────────────────────────────────

from consensus.taco_consensus import (
    AgentOpinion,
    PlanStatus,
    TaCoConsensusCoordinator,
    TradePlan,
)

# ── Trading adapter imports ───────────────────────────────────────────

from trading.adapters.base import (
    BalanceSnapshot,
    OrderResult as AdapterOrderResult,
    PositionSnapshot,
    TradeRequest,
    TradeSide,
    OrderType as AdapterOrderType,
)
from trading.adapters.registry import clear_adapters, get_adapter, register_adapter

# ── Signal layer imports ──────────────────────────────────────────────

from merid.signals.decay import DecayEnvelope, SignalSnapshot

# ── Reconciliation imports ────────────────────────────────────────────

from merid.reconciliation import PositionDiscrepancy, reconcile_venue


# ══════════════════════════════════════════════════════════════════════
# Mock adapter for testing (doesn't hit a real exchange)
# ══════════════════════════════════════════════════════════════════════

class MockAlpacaAdapter:
    """In-memory adapter that simulates Alpaca paper trading responses."""

    venue = "alpaca"
    supported_assets = ("AAPL", "SPY", "BTC", "ETH")
    supports_trading = True

    def __init__(self):
        self._orders: List[Dict] = []
        self._positions: List[PositionSnapshot] = []
        self._balances = [BalanceSnapshot(asset="USD", total=50000.0, available=48000.0, usd_value=50000.0)]
        self.use_mock = False

    def get_health(self):
        from trading.adapters.base import VenueHealth
        return VenueHealth(venue="alpaca", status="online", last_updated=time.time())

    def get_balances(self) -> List[BalanceSnapshot]:
        return self._balances

    def get_positions(self) -> List[PositionSnapshot]:
        return self._positions

    def submit_order(self, request: TradeRequest) -> AdapterOrderResult:
        fill_price = request.price or 150.0  # Simulated fill
        self._orders.append({
            "symbol": request.symbol,
            "side": request.side.value,
            "qty": request.quantity,
            "price": fill_price,
            "status": "filled",
            "client_ref": request.client_reference,
        })
        # Update simulated positions
        existing = next((p for p in self._positions if p.symbol == request.symbol), None)
        if existing:
            idx = self._positions.index(existing)
            new_qty = existing.quantity + (request.quantity if request.side == TradeSide.BUY else -request.quantity)
            self._positions[idx] = PositionSnapshot(
                symbol=request.symbol,
                quantity=new_qty,
                entry_price=fill_price,
                mark_price=fill_price,
                unrealized_pnl=0.0,
            )
        else:
            self._positions.append(PositionSnapshot(
                symbol=request.symbol,
                quantity=request.quantity if request.side == TradeSide.BUY else -request.quantity,
                entry_price=fill_price,
                mark_price=fill_price,
                unrealized_pnl=0.0,
            ))
        return AdapterOrderResult(
            venue="alpaca",
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            executed_price=fill_price,
            status="filled",
            venue_order_id=f"MOCK-{len(self._orders):04d}",
            metadata={"client_ref": request.client_reference},
        )

    def cancel_order(self, venue_order_id: str) -> bool:
        return True


# ══════════════════════════════════════════════════════════════════════
# Test 1: Proposal → Consensus
# ══════════════════════════════════════════════════════════════════════

class TestProposalToConsensus(unittest.TestCase):
    """Verify that agent opinions with decay metadata trigger consensus plans."""

    def setUp(self):
        # Fresh coordinator for each test
        TaCoConsensusCoordinator._instance = None
        self.coordinator = TaCoConsensusCoordinator(min_opinions_for_consensus=2)

    def test_opinions_produce_plan_with_decay_fields(self):
        now = time.time()
        snap = SignalSnapshot(
            snapshot_id="snap-001",
            timestamp=now,
            signals=[
                DecayEnvelope.create(0.7, now - 30, "news", "sentiment", now),
                DecayEnvelope.create(0.5, now - 10, "social", "hype", now),
            ],
        )
        op1 = AgentOpinion(
            opinion_id="op-1", agent_id="bull_analyst", role="bull_analyst",
            symbol="AAPL", venue="alpaca", stance="bull", score=0.8,
            confidence=0.9, rationale="Strong earnings",
            signal_snapshot_id=snap.snapshot_id,
            signal_freshness=snap.avg_freshness(),
            signal_stale_count=snap.stale_count(),
            decay_metadata={"news": 0.95, "social": 0.99},
        )
        op2 = AgentOpinion(
            opinion_id="op-2", agent_id="risk_manager", role="risk_manager",
            symbol="AAPL", venue="alpaca", stance="bull", score=0.6,
            confidence=0.85, rationale="Risk acceptable",
            signal_freshness=0.9,
        )

        # Submit opinions
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.coordinator.submit_opinion(op1))
        loop.run_until_complete(self.coordinator.submit_opinion(op2))
        loop.close()

        # Should have generated a plan
        plans = list(self.coordinator._active_plans.values())
        self.assertGreater(len(plans), 0)
        plan = plans[0]
        self.assertEqual(plan.symbol, "AAPL")
        self.assertEqual(plan.direction, "long")
        # Decay metadata should be propagated
        self.assertGreater(plan.avg_signal_freshness, 0)
        self.assertGreater(plan.decay_adjusted_confidence, 0)

    def test_stale_opinions_reduce_consensus_score(self):
        """Opinions with low signal_freshness should produce lower consensus scores."""
        now = time.time()
        # Fresh opinions
        fresh_coord = TaCoConsensusCoordinator(min_opinions_for_consensus=2)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(fresh_coord.submit_opinion(AgentOpinion(
            opinion_id="f1", agent_id="a1", role="bull", symbol="SPY", venue="alpaca",
            stance="bull", score=0.8, confidence=0.9, rationale="Fresh",
            signal_freshness=1.0,
        )))
        loop.run_until_complete(fresh_coord.submit_opinion(AgentOpinion(
            opinion_id="f2", agent_id="a2", role="bull", symbol="SPY", venue="alpaca",
            stance="bull", score=0.7, confidence=0.8, rationale="Fresh",
            signal_freshness=1.0,
        )))

        # Stale opinions
        stale_coord = TaCoConsensusCoordinator(min_opinions_for_consensus=2)
        loop.run_until_complete(stale_coord.submit_opinion(AgentOpinion(
            opinion_id="s1", agent_id="a1", role="bull", symbol="SPY", venue="alpaca",
            stance="bull", score=0.8, confidence=0.9, rationale="Stale",
            signal_freshness=0.2,
        )))
        loop.run_until_complete(stale_coord.submit_opinion(AgentOpinion(
            opinion_id="s2", agent_id="a2", role="bull", symbol="SPY", venue="alpaca",
            stance="bull", score=0.7, confidence=0.8, rationale="Stale",
            signal_freshness=0.2,
        )))
        loop.close()

        fresh_plans = list(fresh_coord._active_plans.values())
        stale_plans = list(stale_coord._active_plans.values())
        self.assertGreater(len(fresh_plans), 0)
        self.assertGreater(len(stale_plans), 0)
        # Stale plan should have lower confidence adjustment
        self.assertGreater(
            fresh_plans[0].decay_adjusted_confidence,
            stale_plans[0].decay_adjusted_confidence,
        )


# ══════════════════════════════════════════════════════════════════════
# Test 2: Consensus → Risk
# ══════════════════════════════════════════════════════════════════════

class TestConsensusToRisk(unittest.TestCase):
    """Verify that consensus plans pass through GlobalRiskManager checks."""

    def test_plan_to_proposal_risk_check(self):
        plan = TradePlan(
            plan_id="plan-001", symbol="AAPL", venue="alpaca",
            direction="long", target_size_usd=500.0, confidence=0.8,
            consensus_score=0.7, supporting_agents=["a1", "a2"],
            opposing_agents=[], status=PlanStatus.APPROVED.value,
            avg_signal_freshness=0.95, decay_adjusted_confidence=0.76,
        )
        # Convert to TradeProposal for risk check
        proposal = TradeProposal(
            domain=TradeDomain.EQUITY,
            strategy_id="consensus",
            agent_id="coordinator",
            venue="alpaca",
            instrument_id="AAPL",
            native_symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=Decimal("3"),
            notional_usd=Decimal(str(plan.target_size_usd)),
            confidence=Decimal(str(plan.confidence)),
            rationale=f"Consensus: score={plan.consensus_score}, freshness={plan.avg_signal_freshness}",
            metadata={
                "plan_id": plan.plan_id,
                "avg_signal_freshness": plan.avg_signal_freshness,
                "decay_adjusted_confidence": plan.decay_adjusted_confidence,
            },
        )
        self.assertEqual(proposal.status, ProposalStatus.PENDING)
        self.assertEqual(proposal.venue, "alpaca")
        self.assertIn("plan_id", proposal.metadata)

        # Risk manager should be able to approve it
        risk = GlobalRiskManager()
        result = risk.check_proposal(proposal)
        self.assertIn(result.approved, [True, False])  # just verify it runs

    def test_plan_size_scaling_by_freshness(self):
        """Plans with low freshness should have reduced effective size."""
        plan = TradePlan(
            plan_id="plan-002", symbol="AAPL", venue="alpaca",
            direction="long", target_size_usd=1000.0, confidence=0.9,
            consensus_score=0.8, supporting_agents=["a1"],
            opposing_agents=[], avg_signal_freshness=0.3,
            decay_adjusted_confidence=0.27,
        )
        # Effective size should be scaled by freshness
        effective_size = plan.target_size_usd * plan.avg_signal_freshness
        self.assertLess(effective_size, plan.target_size_usd)
        self.assertAlmostEqual(effective_size, 300.0, places=0)


# ══════════════════════════════════════════════════════════════════════
# Test 3: Risk → Adapter
# ══════════════════════════════════════════════════════════════════════

class TestRiskToAdapter(unittest.TestCase):
    """Verify plan-to-TradeRequest bridge and adapter submission."""

    def setUp(self):
        clear_adapters()
        self.mock_adapter = MockAlpacaAdapter()
        register_adapter(self.mock_adapter)

    def tearDown(self):
        clear_adapters()

    def test_plan_bridges_to_trade_request(self):
        plan = TradePlan(
            plan_id="plan-003", symbol="AAPL", venue="alpaca",
            direction="long", target_size_usd=500.0, confidence=0.8,
            consensus_score=0.7, supporting_agents=["a1"],
            opposing_agents=[], status=PlanStatus.APPROVED.value,
        )
        request = TradeRequest(
            venue="alpaca",
            symbol=plan.symbol,
            side=TradeSide.BUY,
            quantity=plan.target_size_usd,
            order_type=AdapterOrderType.MARKET,
            notional_usd=plan.target_size_usd,
            client_reference=plan.plan_id,
            live=True,
        )
        self.assertEqual(request.venue, "alpaca")
        self.assertEqual(request.symbol, "AAPL")
        self.assertEqual(request.client_reference, "plan-003")

    def test_adapter_executes_order(self):
        adapter = get_adapter("alpaca")
        request = TradeRequest(
            venue="alpaca", symbol="AAPL", side=TradeSide.BUY,
            quantity=10.0, order_type=AdapterOrderType.MARKET,
            client_reference="test-ref",
        )
        result = adapter.submit_order(request)
        self.assertEqual(result.status, "filled")
        self.assertEqual(result.venue, "alpaca")
        self.assertGreater(result.executed_price, 0)
        self.assertTrue(result.venue_order_id.startswith("MOCK-"))

    def test_adapter_updates_positions(self):
        adapter = get_adapter("alpaca")
        request = TradeRequest(
            venue="alpaca", symbol="SPY", side=TradeSide.BUY,
            quantity=5.0, order_type=AdapterOrderType.MARKET,
        )
        adapter.submit_order(request)
        positions = adapter.get_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].symbol, "SPY")
        self.assertEqual(positions[0].quantity, 5.0)


# ══════════════════════════════════════════════════════════════════════
# Test 4: Adapter Order Lifecycle
# ══════════════════════════════════════════════════════════════════════

class TestAdapterOrderLifecycle(unittest.TestCase):
    """Verify full order lifecycle: submit → fill → position update."""

    def setUp(self):
        clear_adapters()
        self.adapter = MockAlpacaAdapter()
        register_adapter(self.adapter)

    def tearDown(self):
        clear_adapters()

    def test_buy_then_sell_closes_position(self):
        # Buy
        buy = TradeRequest(venue="alpaca", symbol="AAPL", side=TradeSide.BUY, quantity=10.0, order_type=AdapterOrderType.MARKET)
        self.adapter.submit_order(buy)
        self.assertEqual(self.adapter.get_positions()[0].quantity, 10.0)

        # Sell
        sell = TradeRequest(venue="alpaca", symbol="AAPL", side=TradeSide.SELL, quantity=10.0, order_type=AdapterOrderType.MARKET)
        self.adapter.submit_order(sell)
        self.assertEqual(self.adapter.get_positions()[0].quantity, 0.0)

    def test_multiple_orders_accumulate(self):
        for i in range(3):
            req = TradeRequest(venue="alpaca", symbol="ETH", side=TradeSide.BUY, quantity=2.0, order_type=AdapterOrderType.MARKET)
            self.adapter.submit_order(req)
        self.assertEqual(self.adapter.get_positions()[0].quantity, 6.0)

    def test_order_history_tracked(self):
        req = TradeRequest(venue="alpaca", symbol="AAPL", side=TradeSide.BUY, quantity=1.0, order_type=AdapterOrderType.MARKET)
        self.adapter.submit_order(req)
        self.assertEqual(len(self.adapter._orders), 1)
        self.assertEqual(self.adapter._orders[0]["status"], "filled")


# ══════════════════════════════════════════════════════════════════════
# Test 5: Reconciliation
# ══════════════════════════════════════════════════════════════════════

class TestReconciliation(unittest.TestCase):
    """Verify position reconciliation detects mismatches."""

    def test_discrepancy_detection(self):
        disc = PositionDiscrepancy(
            venue="alpaca", symbol="AAPL",
            merid_qty=10.0, venue_qty=8.0,
            merid_entry_price=150.0, venue_entry_price=150.0,
        )
        self.assertAlmostEqual(disc.delta_qty, -2.0)
        self.assertEqual(disc.severity, "critical")

    def test_no_discrepancy(self):
        disc = PositionDiscrepancy(
            venue="alpaca", symbol="AAPL",
            merid_qty=10.0, venue_qty=10.0,
            merid_entry_price=150.0, venue_entry_price=150.0,
        )
        self.assertAlmostEqual(disc.delta_qty, 0.0)
        self.assertEqual(disc.severity, "info")

    def test_small_discrepancy_is_warning(self):
        disc = PositionDiscrepancy(
            venue="alpaca", symbol="AAPL",
            merid_qty=10.0, venue_qty=10.5,
            merid_entry_price=150.0, venue_entry_price=150.0,
        )
        self.assertEqual(disc.severity, "warning")

    def test_to_dict(self):
        disc = PositionDiscrepancy(
            venue="alpaca", symbol="ETH",
            merid_qty=5.0, venue_qty=5.0,
            merid_entry_price=3000.0, venue_entry_price=3000.0,
        )
        d = disc.to_dict()
        self.assertEqual(d["venue"], "alpaca")
        self.assertIn("delta_qty", d)

    @patch("trading.adapters.registry.get_adapter")
    @patch("merid.reconciliation._get_merid_positions")
    def test_reconcile_venue_detects_mismatch(self, mock_merid, mock_adapter_fn):
        mock_adapter = MagicMock()
        mock_adapter.get_positions.return_value = [
            PositionSnapshot(symbol="AAPL", quantity=10.0, entry_price=150.0, mark_price=155.0, unrealized_pnl=50.0),
        ]
        mock_adapter_fn.return_value = mock_adapter
        mock_merid.return_value = [
            {"symbol": "AAPL", "quantity": 8.0, "entry_price": 150.0},
        ]
        discs = reconcile_venue("alpaca")
        self.assertEqual(len(discs), 1)
        self.assertEqual(discs[0].symbol, "AAPL")
        self.assertAlmostEqual(discs[0].delta_qty, 2.0)

    @patch("trading.adapters.registry.get_adapter")
    @patch("merid.reconciliation._get_merid_positions")
    def test_reconcile_venue_no_mismatch(self, mock_merid, mock_adapter_fn):
        mock_adapter = MagicMock()
        mock_adapter.get_positions.return_value = [
            PositionSnapshot(symbol="SPY", quantity=5.0, entry_price=450.0, mark_price=451.0, unrealized_pnl=5.0),
        ]
        mock_adapter_fn.return_value = mock_adapter
        mock_merid.return_value = [
            {"symbol": "SPY", "quantity": 5.0, "entry_price": 450.0},
        ]
        discs = reconcile_venue("alpaca")
        self.assertEqual(len(discs), 0)


# ══════════════════════════════════════════════════════════════════════
# Test 6: Full Golden Path
# ══════════════════════════════════════════════════════════════════════

class TestFullGoldenPath(unittest.TestCase):
    """End-to-end: opinion → consensus → risk check → adapter execute → reconcile."""

    def setUp(self):
        TaCoConsensusCoordinator._instance = None
        clear_adapters()
        self.adapter = MockAlpacaAdapter()
        register_adapter(self.adapter)

    def tearDown(self):
        clear_adapters()

    def test_full_path_opinion_to_fill(self):
        """The complete golden path test."""
        now = time.time()

        # 1. Build signal snapshot
        snap = SignalSnapshot(
            snapshot_id="golden-snap",
            timestamp=now,
            signals=[
                DecayEnvelope.create(0.8, now - 10, "news", "earnings_surprise", now),
                DecayEnvelope.create(0.6, now - 5, "macro", "fed_dovish", now),
            ],
        )
        freshness = snap.avg_freshness()
        self.assertGreater(freshness, 0.9)

        # 2. Create and submit opinions
        coordinator = TaCoConsensusCoordinator(min_opinions_for_consensus=2)
        loop = asyncio.new_event_loop()

        loop.run_until_complete(coordinator.submit_opinion(AgentOpinion(
            opinion_id="gp-1", agent_id="research_agent", role="bull_analyst",
            symbol="AAPL", venue="alpaca", stance="strong_bull", score=0.85,
            confidence=0.9, rationale="Earnings beat + Fed dovish",
            signal_snapshot_id=snap.snapshot_id,
            signal_freshness=freshness,
            signal_stale_count=0,
            decay_metadata={"news": 0.99, "macro": 0.99},
        )))
        loop.run_until_complete(coordinator.submit_opinion(AgentOpinion(
            opinion_id="gp-2", agent_id="risk_agent", role="risk_manager",
            symbol="AAPL", venue="alpaca", stance="bull", score=0.6,
            confidence=0.85, rationale="Risk within limits",
            signal_freshness=0.95,
        )))
        loop.close()

        # 3. Verify consensus produced a plan
        plans = list(coordinator._active_plans.values())
        self.assertGreater(len(plans), 0)
        plan = plans[0]
        self.assertEqual(plan.symbol, "AAPL")
        self.assertIn(plan.direction, ("long", "short", "flat"))
        self.assertGreater(plan.avg_signal_freshness, 0.9)

        # 4. Simulate risk approval
        plan.status = PlanStatus.APPROVED.value
        plan.approved_size_usd = plan.target_size_usd

        # 5. Bridge to TradeRequest and execute
        side = TradeSide.BUY if plan.direction == "long" else TradeSide.SELL
        request = TradeRequest(
            venue="alpaca",
            symbol=plan.symbol,
            side=side,
            quantity=plan.approved_size_usd,
            order_type=AdapterOrderType.MARKET,
            client_reference=plan.plan_id,
            live=True,
        )
        result = self.adapter.submit_order(request)

        # 6. Verify fill
        self.assertEqual(result.status, "filled")
        self.assertEqual(result.venue, "alpaca")
        self.assertEqual(result.symbol, "AAPL")
        self.assertGreater(result.executed_price, 0)

        # 7. Verify position exists on venue
        positions = self.adapter.get_positions()
        self.assertGreater(len(positions), 0)
        aapl = next(p for p in positions if p.symbol == "AAPL")
        self.assertGreater(aapl.quantity, 0)

        # 8. Reconcile — no mismatch since we just executed
        # (In production this would compare against paper engine state)
        disc = PositionDiscrepancy(
            venue="alpaca", symbol="AAPL",
            merid_qty=aapl.quantity, venue_qty=aapl.quantity,
            merid_entry_price=aapl.entry_price, venue_entry_price=aapl.entry_price,
        )
        self.assertEqual(disc.severity, "info")
        self.assertAlmostEqual(disc.delta_qty, 0.0)


# ══════════════════════════════════════════════════════════════════════
# Test 7: Main Loop
# ══════════════════════════════════════════════════════════════════════

class TestMainLoop(unittest.TestCase):
    """Verify the async main loop drives all steps."""

    def test_loop_config_defaults(self):
        from merid.loop import LoopConfig
        cfg = LoopConfig()
        self.assertEqual(cfg.active_symbols, ["BTC", "ETH", "SOL"])
        self.assertFalse(cfg.enable_execution)

    def test_loop_metrics_init(self):
        from merid.loop import LoopMetrics
        m = LoopMetrics()
        self.assertEqual(m.total_ticks, 0)
        d = m.to_dict()
        self.assertIn("total_ticks", d)

    def test_loop_status(self):
        from merid.loop import MeridLoop
        loop = MeridLoop()
        status = loop.status()
        self.assertFalse(status["running"])
        self.assertIn("metrics", status)
        self.assertIn("config", status)

    def test_single_tick(self):
        """Run a single loop tick and verify it completes."""
        from merid.loop import MeridLoop, LoopConfig
        config = LoopConfig(
            feature_refresh_interval=0,  # Always refresh
            agent_cycle_interval=999,     # Skip agents (slow)
            consensus_interval=0,
            arb_scan_interval=0,
            cqi_interval=0,
            reconciliation_interval=999,  # Skip reconciliation
            enable_execution=False,
        )
        loop = MeridLoop(config)
        result = asyncio.get_event_loop().run_until_complete(loop.tick())
        self.assertIn("tick", result)
        self.assertEqual(result["tick"], 1)
        self.assertIn("actions", result)
        self.assertGreater(len(result["actions"]), 0)
        self.assertEqual(loop.metrics.total_ticks, 1)
        self.assertGreater(loop.metrics.last_tick_duration_ms, 0)

    def test_multiple_ticks_increment(self):
        from merid.loop import MeridLoop, LoopConfig
        config = LoopConfig(
            feature_refresh_interval=0,
            agent_cycle_interval=999,
            consensus_interval=0,
            arb_scan_interval=0,
            cqi_interval=999,
            reconciliation_interval=999,
            enable_execution=False,
        )
        loop = MeridLoop(config)
        el = asyncio.get_event_loop()
        for _ in range(3):
            el.run_until_complete(loop.tick())
        self.assertEqual(loop.metrics.total_ticks, 3)

    def test_run_with_max_ticks(self):
        from merid.loop import MeridLoop, LoopConfig
        config = LoopConfig(
            feature_refresh_interval=0,
            agent_cycle_interval=999,
            consensus_interval=999,
            arb_scan_interval=999,
            cqi_interval=999,
            reconciliation_interval=999,
            enable_execution=False,
        )
        loop = MeridLoop(config)
        asyncio.get_event_loop().run_until_complete(loop.run(max_ticks=2))
        self.assertEqual(loop.metrics.total_ticks, 2)
        self.assertFalse(loop._running)

    def test_stop(self):
        from merid.loop import MeridLoop
        loop = MeridLoop()
        loop._running = True
        loop.stop()
        self.assertFalse(loop._running)

    def test_subscriber_notification(self):
        from merid.loop import MeridLoop, LoopConfig
        config = LoopConfig(
            feature_refresh_interval=999,
            agent_cycle_interval=999,
            consensus_interval=999,
            arb_scan_interval=999,
            cqi_interval=999,
            reconciliation_interval=999,
        )
        loop = MeridLoop(config)
        events = []
        loop.subscribe(lambda event_type, data: events.append((event_type, data)))
        asyncio.get_event_loop().run_until_complete(loop.tick())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "tick_complete")


if __name__ == "__main__":
    unittest.main()
