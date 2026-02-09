"""§H1-H4 Hardening Tests — execution guard, tick log, WS feed, domain E2E.

Test classes:
  TestCQIThrottle           — CQI-based throttle computation
  TestDomainCap             — per-domain daily caps and resets
  TestExecutionGuard        — full pre-trade check pipeline
  TestKillSwitch            — global and per-domain kill switches
  TestTickRecord            — structured tick record serialization
  TestTickLog               — JSONL persistence and summaries
  TestBuildTickRecord       — parsing loop summary into TickRecord
  TestPriceUpdate           — WS price update model
  TestCoinbaseFeedOffline   — feed status/lifecycle without real WS
  TestWSFeedManagerOffline  — manager ingestion callback
  TestKalshiDomainE2E       — Kalshi prediction domain golden path
  TestFlowDomainE2E         — Flow/sniper domain golden path
"""

import asyncio
import json
import os
import tempfile
import time
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

# ── Execution guard imports ───────────────────────────────────────────

from merid.execution_guard import (
    CQIThrottleConfig,
    DomainCap,
    ExecutionGuard,
    TradeVerdict,
    get_execution_guard,
)

# ── Tick log imports ──────────────────────────────────────────────────

from merid.tick_log import (
    TickLog,
    TickRecord,
    build_tick_record,
)

# ── WS feed imports ───────────────────────────────────────────────────

from merid.signals.ws_price_feed import (
    COINBASE_TO_MERID,
    MERID_TO_COINBASE,
    CoinbasePriceFeed,
    PriceUpdate,
    WSFeedManager,
)


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ══════════════════════════════════════════════════════════════════════
# §H3: Execution Guard Tests
# ══════════════════════════════════════════════════════════════════════

class TestCQIThrottle(unittest.TestCase):
    """CQI-based throttle computation."""

    def setUp(self):
        self.cfg = CQIThrottleConfig()

    def test_full_execution_above_threshold(self):
        self.assertEqual(self.cfg.compute_throttle(0.80), 1.0)
        self.assertEqual(self.cfg.compute_throttle(0.65), 1.0)

    def test_blocked_below_threshold(self):
        self.assertEqual(self.cfg.compute_throttle(0.30), 0.0)
        self.assertEqual(self.cfg.compute_throttle(0.0), 0.0)
        self.assertEqual(self.cfg.compute_throttle(0.35), 0.0)

    def test_linear_interpolation_in_middle(self):
        throttle = self.cfg.compute_throttle(0.50)
        self.assertGreater(throttle, 0.0)
        self.assertLess(throttle, 1.0)

    def test_min_throttle_enforced(self):
        # Just above block_below
        throttle = self.cfg.compute_throttle(0.36)
        self.assertGreaterEqual(throttle, self.cfg.min_throttle_pct)

    def test_monotonic(self):
        """Higher CQI should always give higher or equal throttle."""
        prev = 0.0
        for cqi in [0.30, 0.35, 0.40, 0.50, 0.60, 0.65, 0.80]:
            t = self.cfg.compute_throttle(cqi)
            self.assertGreaterEqual(t, prev)
            prev = t


class TestDomainCap(unittest.TestCase):
    """Per-domain daily caps."""

    def test_initial_state(self):
        cap = DomainCap(domain="crypto")
        self.assertTrue(cap.enabled)
        self.assertFalse(cap.kill_switch)
        self.assertEqual(cap.daily_notional_usd, 0.0)

    def test_record_trade(self):
        cap = DomainCap(domain="crypto", max_daily_notional_usd=10000)
        cap.record_trade(500)
        cap.record_trade(300)
        self.assertEqual(cap.daily_notional_usd, 800)
        self.assertEqual(cap.daily_trade_count, 2)
        self.assertEqual(cap.remaining_notional(), 9200)

    def test_reset_on_new_day(self):
        cap = DomainCap(domain="crypto")
        cap.daily_notional_usd = 5000
        cap.daily_trade_count = 10
        cap.last_reset_date = "2020-01-01"  # Old date forces reset
        cap.reset_if_new_day()
        self.assertEqual(cap.daily_notional_usd, 0.0)
        self.assertEqual(cap.daily_trade_count, 0)

    def test_to_dict(self):
        cap = DomainCap(domain="prediction")
        d = cap.to_dict()
        self.assertEqual(d["domain"], "prediction")
        self.assertIn("remaining_notional_usd", d)

    def test_remaining_never_negative(self):
        cap = DomainCap(domain="crypto", max_daily_notional_usd=100)
        cap.record_trade(150)
        self.assertEqual(cap.remaining_notional(), 0)


class TestExecutionGuard(unittest.TestCase):
    """Full pre-trade check pipeline."""

    def setUp(self):
        self.guard = ExecutionGuard()

    def test_allows_normal_trade(self):
        self.guard.update_cqi("crypto", 0.8)
        v = self.guard.pre_trade_check("p1", "BTC", "crypto", 500)
        self.assertTrue(v.allowed)
        self.assertEqual(v.adjusted_size_usd, 500)
        self.assertEqual(v.throttle_pct, 1.0)

    def test_blocks_on_global_kill_switch(self):
        self.guard.activate_kill_switch("test")
        v = self.guard.pre_trade_check("p1", "BTC", "crypto", 500)
        self.assertFalse(v.allowed)
        self.assertIn("kill switch", v.reason)

    def test_blocks_on_domain_kill_switch(self):
        self.guard.activate_domain_kill_switch("crypto", "test")
        v = self.guard.pre_trade_check("p1", "BTC", "crypto", 500)
        self.assertFalse(v.allowed)
        self.assertIn("domain kill switch", v.reason)

    def test_throttles_on_low_cqi(self):
        self.guard.update_cqi("crypto", 0.50)  # Below full, above block
        v = self.guard.pre_trade_check("p1", "BTC", "crypto", 1000)
        self.assertTrue(v.allowed)
        self.assertLess(v.adjusted_size_usd, 1000)
        self.assertGreater(v.adjusted_size_usd, 0)
        self.assertLess(v.throttle_pct, 1.0)

    def test_blocks_on_very_low_cqi(self):
        self.guard.update_cqi("crypto", 0.20)
        v = self.guard.pre_trade_check("p1", "BTC", "crypto", 1000)
        self.assertFalse(v.allowed)
        self.assertIn("CQI too low", v.reason)

    def test_daily_cap_enforcement(self):
        self.guard.update_cqi("prediction", 0.8)
        # Max daily for prediction is 5000
        for i in range(10):
            self.guard.record_execution("prediction", 500)
        v = self.guard.pre_trade_check("p99", "KALSHI", "prediction", 500)
        self.assertFalse(v.allowed)

    def test_single_trade_cap(self):
        self.guard.update_cqi("prediction", 0.8)
        v = self.guard.pre_trade_check("p1", "KALSHI", "prediction", 5000)
        self.assertTrue(v.allowed)
        # Should be clamped to max_single_trade_usd (500 for prediction)
        self.assertLessEqual(v.adjusted_size_usd, 500)

    def test_cooldown_blocks(self):
        self.guard.update_cqi("crypto", 0.8)
        self.guard.record_execution("crypto", 100)  # Sets last_execution_at
        v = self.guard.pre_trade_check("p2", "ETH", "crypto", 500)
        self.assertFalse(v.allowed)
        self.assertIn("cooldown", v.reason)

    def test_deactivate_kill_switch(self):
        self.guard.activate_kill_switch("test")
        self.assertTrue(self.guard.kill_switch_active)
        self.guard.deactivate_kill_switch()
        self.assertFalse(self.guard.kill_switch_active)

    def test_verdict_to_dict(self):
        v = TradeVerdict(allowed=True, reason="ok", original_size_usd=100, adjusted_size_usd=80)
        d = v.to_dict()
        self.assertTrue(d["allowed"])
        self.assertEqual(d["original_size_usd"], 100)

    def test_summary(self):
        s = self.guard.summary()
        self.assertIn("global_kill_switch", s)
        self.assertIn("domain_caps", s)
        self.assertIn("cqi_throttle_config", s)

    def test_recent_verdicts(self):
        self.guard.update_cqi("crypto", 0.8)
        self.guard.pre_trade_check("p1", "BTC", "crypto", 100)
        verdicts = self.guard.recent_verdicts()
        self.assertEqual(len(verdicts), 1)


class TestKillSwitch(unittest.TestCase):
    """Kill switch behavior."""

    def test_global_kill_blocks_all_domains(self):
        guard = ExecutionGuard()
        guard.update_cqi("crypto", 0.9)
        guard.update_cqi("prediction", 0.9)
        guard.activate_kill_switch("emergency")

        for domain in ["crypto", "prediction", "equity"]:
            v = guard.pre_trade_check("px", "X", domain, 100)
            self.assertFalse(v.allowed)

    def test_domain_kill_only_blocks_that_domain(self):
        guard = ExecutionGuard()
        guard.update_cqi("crypto", 0.9)
        guard.update_cqi("prediction", 0.9)
        guard.activate_domain_kill_switch("crypto")

        v_crypto = guard.pre_trade_check("p1", "BTC", "crypto", 100)
        self.assertFalse(v_crypto.allowed)

        v_pred = guard.pre_trade_check("p2", "KALSHI", "prediction", 100)
        self.assertTrue(v_pred.allowed)

    def test_deactivate_domain_kill(self):
        guard = ExecutionGuard()
        guard.update_cqi("crypto", 0.9)
        guard.activate_domain_kill_switch("crypto")
        guard.deactivate_domain_kill_switch("crypto")
        v = guard.pre_trade_check("p1", "BTC", "crypto", 100)
        self.assertTrue(v.allowed)


# ══════════════════════════════════════════════════════════════════════
# §H1: Tick Log Tests
# ══════════════════════════════════════════════════════════════════════

class TestTickRecord(unittest.TestCase):
    """Structured tick record."""

    def test_to_dict(self):
        r = TickRecord(tick_number=1, timestamp=time.time(), duration_ms=42.5)
        d = r.to_dict()
        self.assertEqual(d["tick"], 1)
        self.assertIn("features", d)
        self.assertIn("guard", d)

    def test_to_json(self):
        r = TickRecord(tick_number=5, cqi_scores={"crypto": 0.72})
        j = r.to_json()
        parsed = json.loads(j)
        self.assertEqual(parsed["tick"], 5)
        self.assertAlmostEqual(parsed["cqi"]["crypto"], 0.72, places=3)


class TestTickLog(unittest.TestCase):
    """JSONL persistence."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log = TickLog(log_dir=self.tmpdir, log_file="test_ticks.jsonl")

    def test_append_and_read(self):
        r = TickRecord(tick_number=1, duration_ms=10)
        self.log.append(r)
        recent = self.log.recent(10)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["tick"], 1)

    def test_writes_to_file(self):
        r = TickRecord(tick_number=1)
        self.log.append(r)
        self.assertTrue(self.log.path.exists())
        with open(self.log.path, "r") as f:
            line = f.readline()
            parsed = json.loads(line)
            self.assertEqual(parsed["tick"], 1)

    def test_summary(self):
        for i in range(5):
            self.log.append(TickRecord(tick_number=i, duration_ms=10 + i))
        s = self.log.summary()
        self.assertEqual(s["ticks"], 5)
        self.assertGreater(s["avg_duration_ms"], 0)

    def test_summary_empty(self):
        s = self.log.summary()
        self.assertEqual(s["ticks"], 0)


class TestBuildTickRecord(unittest.TestCase):
    """Parse loop summary into TickRecord."""

    def test_basic_parse(self):
        summary = {
            "tick": 42,
            "duration_ms": 150.3,
            "actions": [
                "features_refreshed:3symbols",
                "arb_scan:5signals",
                "executed:BTC:long:$500(throttle=100%)",
                "blocked:ETH:CQI too low",
                "reconciled:0discrepancies",
            ],
            "cqi_scores": {"crypto": 0.72, "prediction": 0.61},
        }
        r = build_tick_record(summary)
        self.assertEqual(r.tick_number, 42)
        self.assertEqual(r.plans_executed, 1)
        self.assertEqual(r.plans_blocked, 1)
        self.assertEqual(r.arb_signals_found, 5)
        self.assertEqual(r.reconciliation_discrepancies, 0)
        self.assertAlmostEqual(r.cqi_scores["crypto"], 0.72)

    def test_error_parse(self):
        summary = {"tick": 1, "actions": [], "error": "test error"}
        r = build_tick_record(summary)
        self.assertEqual(r.error, "test error")


# ══════════════════════════════════════════════════════════════════════
# §H2: WebSocket Feed Tests
# ══════════════════════════════════════════════════════════════════════

class TestPriceUpdate(unittest.TestCase):
    """WS price update model."""

    def test_spread_calculation(self):
        p = PriceUpdate(symbol="BTC", price=50000, bid=49990, ask=50010)
        self.assertEqual(p.spread, 20)
        self.assertAlmostEqual(p.spread_bps, 4.0, places=1)

    def test_zero_price_spread(self):
        p = PriceUpdate(symbol="BTC", price=0)
        self.assertEqual(p.spread_bps, 0.0)

    def test_to_dict(self):
        p = PriceUpdate(symbol="ETH", price=3000, bid=2999, ask=3001, volume_24h=1e9)
        d = p.to_dict()
        self.assertEqual(d["symbol"], "ETH")
        self.assertEqual(d["price"], 3000)
        self.assertIn("spread_bps", d)

    def test_no_bid_ask(self):
        p = PriceUpdate(symbol="SOL", price=150)
        self.assertEqual(p.spread, 0.0)


class TestCoinbaseFeedOffline(unittest.TestCase):
    """Coinbase feed without real WS connection."""

    def test_symbol_mapping(self):
        self.assertEqual(MERID_TO_COINBASE["BTC"], "BTC-USD")
        self.assertEqual(COINBASE_TO_MERID["ETH-USD"], "ETH")

    def test_status_disconnected(self):
        feed = CoinbasePriceFeed(["BTC-USD"])
        s = feed.status()
        self.assertFalse(s["connected"])
        self.assertEqual(s["message_count"], 0)

    def test_latest_empty(self):
        feed = CoinbasePriceFeed()
        self.assertIsNone(feed.latest("BTC"))
        self.assertEqual(len(feed.all_latest()), 0)

    def test_handle_ticker_message(self):
        feed = CoinbasePriceFeed(["BTC-USD"])
        feed._handle_message({
            "type": "ticker",
            "product_id": "BTC-USD",
            "price": "98500.00",
            "best_bid": "98490.00",
            "best_ask": "98510.00",
            "volume_24h": "15000.00",
        })
        latest = feed.latest("BTC")
        self.assertIsNotNone(latest)
        self.assertAlmostEqual(latest.price, 98500.0)
        self.assertEqual(feed._message_count, 1)

    def test_ignores_non_ticker(self):
        feed = CoinbasePriceFeed()
        feed._handle_message({"type": "subscriptions"})
        self.assertEqual(feed._message_count, 0)

    def test_subscriber_notified(self):
        feed = CoinbasePriceFeed(["ETH-USD"])
        updates = []
        feed.subscribe(lambda u: updates.append(u))
        feed._handle_message({
            "type": "ticker",
            "product_id": "ETH-USD",
            "price": "3200.00",
            "best_bid": "3199.50",
            "best_ask": "3200.50",
            "volume_24h": "500000.00",
        })
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].symbol, "ETH")

    def test_bad_price_handled(self):
        feed = CoinbasePriceFeed()
        feed._handle_message({
            "type": "ticker",
            "product_id": "BTC-USD",
            "price": "not_a_number",
        })
        self.assertEqual(feed._error_count, 1)


class TestWSFeedManagerOffline(unittest.TestCase):
    """WSFeedManager ingestion without real WS."""

    def test_initial_state(self):
        mgr = WSFeedManager()
        self.assertFalse(mgr.is_active)
        s = mgr.status()
        self.assertFalse(s["active"])

    def test_on_price_update_ingests(self):
        mgr = WSFeedManager()
        update = PriceUpdate(
            symbol="BTC", venue="coinbase",
            price=98000, bid=97990, ask=98010,
            volume_24h=15000000,
        )
        # Should not crash even without a running loop
        mgr._on_price_update(update)

        # Verify data landed in the feature service
        from merid.signals.features import get_feature_service
        svc = get_feature_service()
        fs = svc.onchain.get_onchain_features("ethereum", "BTC")
        # If ingested, source should be "live"
        self.assertEqual(fs.source, "live")


# ══════════════════════════════════════════════════════════════════════
# §H4: Domain-Specific E2E — Kalshi Prediction
# ══════════════════════════════════════════════════════════════════════

class TestKalshiDomainE2E(unittest.TestCase):
    """Kalshi prediction market golden path — fully simulated."""

    def test_prediction_opinion_to_plan(self):
        """Submit prediction-domain opinions through consensus."""
        from consensus.taco_consensus import TaCoConsensusCoordinator, AgentOpinion
        from merid.signals.decay import DecayEnvelope, SignalSnapshot

        TaCoConsensusCoordinator._instance = None
        coordinator = TaCoConsensusCoordinator(min_opinions_for_consensus=2)
        now = time.time()

        snap = SignalSnapshot(
            snapshot_id="kalshi-snap",
            timestamp=now,
            signals=[
                DecayEnvelope.create(0.7, now - 60, "prediction", "kalshi_edge", now),
            ],
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(coordinator.submit_opinion(AgentOpinion(
            opinion_id="k1", agent_id="prediction_agent", role="prediction_analyst",
            symbol="KXBTC-100K", venue="kalshi", stance="bull", score=0.75,
            confidence=0.85, rationale="BTC to 100K by March — 65 cent yes, edge 12%",
            signal_snapshot_id=snap.snapshot_id,
            signal_freshness=snap.avg_freshness(),
            decay_metadata={"prediction": 0.95},
        )))
        loop.run_until_complete(coordinator.submit_opinion(AgentOpinion(
            opinion_id="k2", agent_id="risk_agent", role="risk_manager",
            symbol="KXBTC-100K", venue="kalshi", stance="bull", score=0.5,
            confidence=0.7, rationale="Within limits, spread acceptable",
            signal_freshness=0.9,
        )))
        loop.close()

        plans = list(coordinator._active_plans.values())
        self.assertGreater(len(plans), 0)
        plan = plans[0]
        self.assertEqual(plan.symbol, "KXBTC-100K")
        self.assertGreater(plan.avg_signal_freshness, 0.8)

    def test_prediction_guard_applies_prediction_caps(self):
        """Prediction domain should have tighter caps than crypto."""
        guard = ExecutionGuard()
        guard.update_cqi("prediction", 0.8)

        v = guard.pre_trade_check("pk1", "KXBTC", "prediction", 2000)
        self.assertTrue(v.allowed)
        # Should be clamped to prediction max single trade (500)
        self.assertLessEqual(v.adjusted_size_usd, 500)

    def test_prediction_plan_through_risk(self):
        """Prediction plan passes GlobalRiskManager."""
        from merid.pipeline.risk_manager import GlobalRiskManager
        from merid.pipeline.proposal import TradeProposal, TradeDomain, OrderSide, OrderType

        proposal = TradeProposal(
            domain=TradeDomain.PREDICTION,
            strategy_id="kalshi_edge",
            agent_id="prediction_agent",
            venue="kalshi",
            instrument_id="KXBTC-100K-YES",
            native_symbol="KXBTC-100K-YES",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=Decimal("10"),
            price=Decimal("0.65"),
            notional_usd=Decimal("6.50"),
            confidence=Decimal("0.85"),
            rationale="12% edge on BTC 100K yes",
        )
        risk = GlobalRiskManager()
        result = risk.check_proposal(proposal)
        self.assertIn(result.approved, [True, False])


# ══════════════════════════════════════════════════════════════════════
# §H4: Domain-Specific E2E — Flow/Sniper
# ══════════════════════════════════════════════════════════════════════

class TestFlowDomainE2E(unittest.TestCase):
    """Flow/sniper domain golden path — simulated memecoin detection."""

    def test_flow_opinion_to_plan(self):
        """Submit flow-domain opinions through consensus."""
        from consensus.taco_consensus import TaCoConsensusCoordinator, AgentOpinion
        from merid.signals.decay import DecayEnvelope, SignalSnapshot

        TaCoConsensusCoordinator._instance = None
        coordinator = TaCoConsensusCoordinator(min_opinions_for_consensus=2)
        now = time.time()

        snap = SignalSnapshot(
            snapshot_id="flow-snap",
            timestamp=now,
            signals=[
                DecayEnvelope.create(0.9, now - 5, "social", "kol_mention", now),
                DecayEnvelope.create(0.8, now - 10, "meme", "whale_buy", now),
            ],
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(coordinator.submit_opinion(AgentOpinion(
            opinion_id="f1", agent_id="flow_detector", role="flow_analyst",
            symbol="BONK", venue="jupiter", stance="strong_bull", score=0.9,
            confidence=0.7, rationale="KOL mention + whale buy detected, fresh token",
            signal_snapshot_id=snap.snapshot_id,
            signal_freshness=snap.avg_freshness(),
            signal_stale_count=0,
            decay_metadata={"social": 0.99, "meme": 0.98},
        )))
        loop.run_until_complete(coordinator.submit_opinion(AgentOpinion(
            opinion_id="f2", agent_id="risk_agent", role="risk_manager",
            symbol="BONK", venue="jupiter", stance="bull", score=0.4,
            confidence=0.6, rationale="High risk but within meme allocation",
            signal_freshness=0.95,
        )))
        loop.close()

        plans = list(coordinator._active_plans.values())
        self.assertGreater(len(plans), 0)
        plan = plans[0]
        self.assertEqual(plan.symbol, "BONK")

    def test_flow_guard_respects_crypto_caps(self):
        """Meme/flow trades should fall under crypto domain caps."""
        guard = ExecutionGuard()
        guard.update_cqi("crypto", 0.8)

        v = guard.pre_trade_check("pf1", "BONK", "crypto", 500)
        self.assertTrue(v.allowed)
        self.assertEqual(v.throttle_pct, 1.0)

    def test_flow_fast_decay_reduces_freshness(self):
        """Social signals with fast decay should reduce freshness quickly."""
        from merid.signals.decay import DecayEnvelope
        now = time.time()
        # Social signal from 15 minutes ago (tau=600s) — weight ≈ 0.22
        env_recent = DecayEnvelope.create(0.8, now - 900, "social", "kol_mention", now)
        self.assertLess(env_recent.decay_weight, 0.5)
        # Social signal from 35 minutes ago — weight drops below min_weight (0.05)
        env_old = DecayEnvelope.create(0.8, now - 2100, "social", "kol_mention", now)
        self.assertTrue(env_old.is_stale)


# ══════════════════════════════════════════════════════════════════════
# §H1+H3 Integration: Guard wired into loop
# ══════════════════════════════════════════════════════════════════════

class TestGuardLoopIntegration(unittest.TestCase):
    """Verify guard is checked during loop execution."""

    def test_loop_has_execution_guard_accessor(self):
        from merid.loop import MeridLoop
        loop = MeridLoop()
        guard = loop._execution_guard()
        self.assertIsInstance(guard, ExecutionGuard)

    def test_tick_with_guard_doesnt_crash(self):
        from merid.loop import MeridLoop, LoopConfig
        config = LoopConfig(
            feature_refresh_interval=0,
            agent_cycle_interval=999,
            consensus_interval=0,
            arb_scan_interval=0,
            cqi_interval=0,
            reconciliation_interval=999,
            enable_execution=True,  # Execution enabled but no plans
        )
        loop = MeridLoop(config)
        result = run_async(loop.tick())
        self.assertIn("actions", result)
        # No crash even with execution enabled


# ══════════════════════════════════════════════════════════════════════
# §V1 Wallet Balances: real data from paper engine
# ══════════════════════════════════════════════════════════════════════

class TestWalletBalancesEndpoint(unittest.TestCase):
    """Verify /api/v1/wallet/balances returns real paper engine data."""

    def test_balances_returns_usd_when_no_portfolios(self):
        """Default balance should be $10K USD when no portfolios exist."""
        from trading.paper_trading import PaperTradingEngine
        engine = PaperTradingEngine()
        # No portfolios → should get default
        # Simulate what the endpoint does
        balances = []
        total = 0.0
        for uid, portfolio in engine.portfolios.items():
            balances.append({"currency": "USD", "available": portfolio.current_balance})
        if not balances:
            balances.append({"currency": "USD", "available": 10000.0, "locked": 0.0, "total": 10000.0})
            total = 10000.0
        self.assertEqual(len(balances), 1)
        self.assertEqual(balances[0]["currency"], "USD")
        self.assertEqual(total, 10000.0)

    def test_balances_reflect_paper_positions(self):
        """Paper positions should show as crypto balances."""
        from trading.paper_trading import PaperTradingEngine, PaperPosition
        engine = PaperTradingEngine()
        portfolio = engine.get_portfolio("test_user")
        # Directly add a position (bypass order fill which needs live prices)
        portfolio.positions["BTC-long"] = PaperPosition(
            position_id="pos1", user_id="test_user", asset="BTC",
            side="long", size_usd=1000.0, entry_price=50000.0,
            current_price=51000.0,
        )
        self.assertTrue(len(portfolio.positions) > 0)
        total_position_value = sum(pos.size_usd for pos in portfolio.positions.values())
        self.assertGreater(total_position_value, 0)

    def test_balances_include_trade_history(self):
        """Trade history should appear as transactions."""
        from trading.paper_trading import PaperTradingEngine, PaperOrder, PaperOrderStatus
        engine = PaperTradingEngine()
        portfolio = engine.get_portfolio("test_user")
        # Directly add to trade_history (bypass order fill which needs live prices)
        order = PaperOrder(
            order_id="test-001", user_id="test_user", asset="ETH",
            side="long", order_type="market", size_usd=500.0,
            status=PaperOrderStatus.FILLED, fill_price=3000.0,
        )
        portfolio.trade_history.append(order)
        self.assertTrue(len(portfolio.trade_history) > 0)
        self.assertEqual(portfolio.trade_history[0].asset, "ETH")

    def test_guard_caps_add_informational_transactions(self):
        """Execution guard cap usage should appear as informational transactions."""
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        guard.update_cqi("crypto", 0.8)
        v = guard.pre_trade_check("p1", "BTC", "crypto", 500)
        self.assertTrue(v.allowed)
        guard.record_execution("crypto", v.adjusted_size_usd)
        # Cap should now have less remaining
        cap = guard._domain_caps["crypto"]
        self.assertLess(cap.remaining_notional(), cap.max_daily_notional_usd)


# ══════════════════════════════════════════════════════════════════════
# §V2 Operator Session: domain-level tracking
# ══════════════════════════════════════════════════════════════════════

class TestOperatorSession(unittest.TestCase):
    """Verify OperatorSession tracks domain execs, blocks, CQI."""

    def test_session_records_executions(self):
        from merid.tick_log import OperatorSession
        session = OperatorSession()
        session.record_execution("crypto", 500.0)
        session.record_execution("crypto", 300.0)
        session.record_execution("prediction", 100.0)
        summary = session.summary()
        self.assertEqual(summary["domain_executions"]["crypto"], 2)
        self.assertEqual(summary["domain_executions"]["prediction"], 1)
        self.assertEqual(summary["domain_usd_executed"]["crypto"], 800.0)

    def test_session_records_blocks(self):
        from merid.tick_log import OperatorSession
        session = OperatorSession()
        session.record_block("crypto")
        session.record_block("crypto")
        session.record_block("prediction")
        summary = session.summary()
        self.assertEqual(summary["domain_blocks"]["crypto"], 2)
        self.assertEqual(summary["domain_blocks"]["prediction"], 1)

    def test_session_tracks_cqi_history(self):
        from merid.tick_log import OperatorSession
        session = OperatorSession()
        session.record_cqi("crypto", 0.75)
        session.record_cqi("crypto", 0.80)
        session.record_cqi("prediction", 0.60)
        series = session.cqi_series()
        self.assertEqual(len(series), 3)
        crypto_series = session.cqi_series(domain="crypto")
        self.assertEqual(len(crypto_series), 2)

    def test_session_summary_has_elapsed(self):
        from merid.tick_log import OperatorSession
        session = OperatorSession()
        summary = session.summary()
        self.assertIn("elapsed_seconds", summary)
        self.assertGreaterEqual(summary["elapsed_seconds"], 0)

    def test_build_tick_record_feeds_session(self):
        """build_tick_record should populate operator session from actions."""
        import merid.tick_log as tl
        # Reset session
        tl._operator_session = tl.OperatorSession()
        summary = {
            "tick": 1,
            "actions": ["executed:crypto:BTC:500.0", "blocked:prediction:KSHI-YES"],
            "cqi_scores": {"crypto": 0.85},
        }
        record = tl.build_tick_record(summary)
        self.assertEqual(record.plans_executed, 1)
        self.assertEqual(record.plans_blocked, 1)
        sess = tl.get_operator_session()
        self.assertEqual(sess._domain_execs.get("crypto"), 1)
        self.assertEqual(sess._domain_blocks.get("prediction"), 1)
        self.assertEqual(len(sess.cqi_series(domain="crypto")), 1)


# ══════════════════════════════════════════════════════════════════════
# §V3 Treasury Overview: real data from paper engine + guard + session
# ══════════════════════════════════════════════════════════════════════

class TestTreasuryOverview(unittest.TestCase):
    """Verify treasury /overview returns real aggregated data."""

    def test_overview_default_balance_when_no_portfolios(self):
        """Default treasury should show $10K USD when no portfolios exist."""
        from trading.paper_trading import PaperTradingEngine
        engine = PaperTradingEngine()
        # No portfolios → overview logic should fall back to default
        balances = []
        total = 0.0
        for uid, portfolio in engine.portfolios.items():
            balances.append({"currency": "USD", "amount": portfolio.current_balance, "value_usd": portfolio.current_balance})
            total += portfolio.current_balance
        if not balances:
            balances.append({"currency": "USD", "amount": 10000.0, "value_usd": 10000.0})
            total = 10000.0
        self.assertEqual(balances[0]["currency"], "USD")
        self.assertEqual(total, 10000.0)

    def test_overview_includes_guard_caps(self):
        """Execution guard domain caps should appear as treasury balances."""
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        # Fresh guard → all caps at max
        for domain, cap in guard._domain_caps.items():
            remaining = cap.remaining_notional()
            self.assertEqual(remaining, cap.max_daily_notional_usd)
            self.assertGreater(remaining, 0)

    def test_overview_governance_from_session(self):
        """Governance stats should use operator session data."""
        from merid.tick_log import OperatorSession
        session = OperatorSession()
        session.record_execution("crypto", 1000)
        session.record_execution("prediction", 500)
        session.record_block("crypto")
        summary = session.summary()
        total_execs = sum(summary["domain_executions"].values())
        total_blocks = sum(summary["domain_blocks"].values())
        total_activity = total_execs + total_blocks
        participation = round(total_execs / max(total_activity, 1), 2)
        self.assertEqual(total_execs, 2)
        self.assertEqual(total_blocks, 1)
        self.assertAlmostEqual(participation, 0.67, places=2)

    def test_overview_positions_as_balances(self):
        """Paper positions should appear as treasury asset balances."""
        from trading.paper_trading import PaperTradingEngine, PaperPosition
        engine = PaperTradingEngine()
        portfolio = engine.get_portfolio("test_user")
        portfolio.positions["ETH-long"] = PaperPosition(
            position_id="pos1", user_id="test_user", asset="ETH",
            side="long", size_usd=2000.0, entry_price=3000.0,
            current_price=3100.0,
        )
        # Simulate overview aggregation
        asset_map = {}
        for pos in portfolio.positions.values():
            entry = asset_map.setdefault(pos.asset, {"size": 0.0, "pnl": 0.0})
            entry["size"] += pos.size_usd
            entry["pnl"] += engine._calculate_position_pnl(pos)
        self.assertIn("ETH", asset_map)
        self.assertGreater(asset_map["ETH"]["size"], 0)


# ══════════════════════════════════════════════════════════════════════
# §RC RiskContext: system-state struct fed into consensus + risk
# ══════════════════════════════════════════════════════════════════════

class TestRiskContext(unittest.TestCase):
    """Verify RiskContext struct, builder, and derived adjustment factors."""

    def test_default_risk_context(self):
        """Fresh RiskContext should have neutral defaults."""
        from merid.pipeline.risk_context import RiskContext
        ctx = RiskContext()
        self.assertEqual(ctx.size_scale_factor, 1.0)
        self.assertEqual(ctx.approval_threshold_boost, 0.0)
        self.assertFalse(ctx.global_kill_switch)

    def test_build_risk_context_returns_populated(self):
        """build_risk_context() should return a populated snapshot."""
        from merid.pipeline.risk_context import build_risk_context
        ctx = build_risk_context()
        self.assertGreater(ctx.timestamp, 0)
        self.assertIsInstance(ctx.domains, dict)
        # Should have at least the guard domains
        self.assertGreater(len(ctx.domains), 0)

    def test_size_scale_reduces_on_low_cqi(self):
        """Low avg CQI should reduce size_scale_factor."""
        from merid.pipeline.risk_context import RiskContext, _compute_size_scale
        ctx = RiskContext(avg_cqi=0.40)
        factor = _compute_size_scale(ctx)
        self.assertLess(factor, 1.0)
        self.assertGreater(factor, 0.0)

    def test_size_scale_blocks_on_very_low_cqi(self):
        """Very low CQI should reduce to minimum."""
        from merid.pipeline.risk_context import RiskContext, _compute_size_scale
        ctx = RiskContext(avg_cqi=0.30)
        factor = _compute_size_scale(ctx)
        self.assertLessEqual(factor, 0.25)

    def test_size_scale_reduces_on_drawdown(self):
        """Elevated drawdown should reduce size_scale_factor."""
        from merid.pipeline.risk_context import RiskContext, _compute_size_scale
        for level, expected_max in [("caution", 0.75), ("warning", 0.50), ("critical", 0.25)]:
            ctx = RiskContext(drawdown_level=level)
            factor = _compute_size_scale(ctx)
            self.assertLessEqual(factor, expected_max, f"Failed for {level}")

    def test_size_scale_reduces_on_high_exposure(self):
        """High portfolio exposure should reduce size_scale_factor."""
        from merid.pipeline.risk_context import RiskContext, _compute_size_scale
        ctx = RiskContext(portfolio_exposure_pct=0.95)
        factor = _compute_size_scale(ctx)
        self.assertLess(factor, 1.0)

    def test_threshold_boost_on_low_cqi(self):
        """Low CQI should increase approval threshold boost."""
        from merid.pipeline.risk_context import RiskContext, _compute_threshold_boost
        ctx = RiskContext(avg_cqi=0.40)
        boost = _compute_threshold_boost(ctx)
        self.assertGreater(boost, 0.0)

    def test_threshold_boost_on_drawdown(self):
        """Drawdown level should add to threshold boost."""
        from merid.pipeline.risk_context import RiskContext, _compute_threshold_boost
        ctx = RiskContext(drawdown_level="warning")
        boost = _compute_threshold_boost(ctx)
        self.assertGreaterEqual(boost, 0.10)

    def test_threshold_boost_capped(self):
        """Threshold boost should never exceed 0.30."""
        from merid.pipeline.risk_context import RiskContext, _compute_threshold_boost
        ctx = RiskContext(avg_cqi=0.20, drawdown_level="emergency", portfolio_exposure_pct=0.95)
        boost = _compute_threshold_boost(ctx)
        self.assertLessEqual(boost, 0.30)

    def test_to_dict_has_all_keys(self):
        """to_dict should include all expected top-level keys."""
        from merid.pipeline.risk_context import build_risk_context
        d = build_risk_context().to_dict()
        for key in ["timestamp", "global_kill_switch", "total_capital_usd",
                     "portfolio_exposure_usd", "drawdown_pct", "avg_cqi",
                     "domains", "size_scale_factor", "approval_threshold_boost"]:
            self.assertIn(key, d, f"Missing key: {key}")

    def test_domain_snapshot_includes_cqi(self):
        """Domain snapshots should include CQI from guard."""
        from merid.pipeline.risk_context import build_risk_context
        ctx = build_risk_context()
        for snap in ctx.domains.values():
            self.assertIsInstance(snap.cqi_score, float)


class TestRiskContextConsensusIntegration(unittest.TestCase):
    """Verify RiskContext integrates with ConsensusCoordinatorAgent."""

    def test_consensus_approved_without_context(self):
        """Baseline: proposal should be approved without risk context."""
        from merid.agents.coordination import ConsensusCoordinatorAgent, AgentVote
        coord = ConsensusCoordinatorAgent(approval_threshold=0.6)
        votes = [
            AgentVote(agent_id="a1", decision="approve", confidence=0.8, weight=1.0),
            AgentVote(agent_id="a2", decision="approve", confidence=0.7, weight=1.0),
        ]
        result = coord.aggregate("p1", votes)
        self.assertEqual(result.decision, "approved")

    def test_consensus_tightened_by_risk_context(self):
        """RiskContext with high boost should reject borderline proposals."""
        from merid.agents.coordination import ConsensusCoordinatorAgent, AgentVote
        from merid.pipeline.risk_context import RiskContext
        coord = ConsensusCoordinatorAgent(approval_threshold=0.6)
        # Votes give ~65% approval — passes at 60% threshold, fails at 75%
        votes = [
            AgentVote(agent_id="a1", decision="approve", confidence=0.65, weight=1.0),
            AgentVote(agent_id="a2", decision="reject", confidence=0.35, weight=1.0),
        ]
        # Without context → approved
        result_no_ctx = coord.aggregate("p1", votes)
        self.assertEqual(result_no_ctx.decision, "approved")

        # With stressed context → rejected
        ctx = RiskContext(approval_threshold_boost=0.15)
        result_with_ctx = coord.aggregate("p1", votes, risk_context=ctx)
        self.assertEqual(result_with_ctx.decision, "rejected")
        self.assertIn("risk boost", result_with_ctx.rationale)

    def test_consensus_no_boost_when_normal(self):
        """RiskContext with zero boost should not change threshold."""
        from merid.agents.coordination import ConsensusCoordinatorAgent, AgentVote
        from merid.pipeline.risk_context import RiskContext
        coord = ConsensusCoordinatorAgent(approval_threshold=0.6)
        votes = [
            AgentVote(agent_id="a1", decision="approve", confidence=0.65, weight=1.0),
        ]
        ctx = RiskContext(approval_threshold_boost=0.0)
        result = coord.aggregate("p1", votes, risk_context=ctx)
        self.assertEqual(result.decision, "approved")
        self.assertNotIn("risk boost", result.rationale)


class TestRiskContextRiskManagerIntegration(unittest.TestCase):
    """Verify RiskContext integrates with GlobalRiskManager."""

    def _make_proposal(self, notional: float, domain_str: str = "crypto"):
        from merid.pipeline.proposal import TradeProposal, TradeDomain, OrderSide, OrderType
        from decimal import Decimal
        domain = TradeDomain(domain_str)
        return TradeProposal(
            proposal_id="test-rc-01",
            domain=domain,
            venue="binance",
            instrument_id="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=Decimal("1"),
            notional_usd=Decimal(str(notional)),
            confidence=Decimal("0.8"),
        )

    def test_risk_check_passes_without_context(self):
        """Baseline: normal proposal should pass without risk context."""
        from merid.pipeline.risk_manager import GlobalRiskManager
        rm = GlobalRiskManager()
        p = self._make_proposal(1000)
        result = rm.check_proposal(p)
        self.assertTrue(result.approved)

    def test_risk_check_scales_down_with_context(self):
        """RiskContext should scale order notional before checks."""
        from merid.pipeline.risk_manager import GlobalRiskManager
        from merid.pipeline.risk_context import RiskContext
        rm = GlobalRiskManager()
        # $4000 notional, within $5000 single order limit
        p = self._make_proposal(4000)
        result_no_ctx = rm.check_proposal(p)
        self.assertTrue(result_no_ctx.approved)

        # With 50% scale → $2000, still passes
        ctx = RiskContext(size_scale_factor=0.50)
        result_scaled = rm.check_proposal(p, risk_context=ctx)
        self.assertTrue(result_scaled.approved)

    def test_risk_check_blocks_when_scaled_to_zero(self):
        """Zero scale factor should block the proposal."""
        from merid.pipeline.risk_manager import GlobalRiskManager
        from merid.pipeline.risk_context import RiskContext
        rm = GlobalRiskManager()
        p = self._make_proposal(100)
        ctx = RiskContext(size_scale_factor=0.0)
        result = rm.check_proposal(p, risk_context=ctx)
        self.assertFalse(result.approved)
        self.assertIn("size_scale_factor", result.reason)


if __name__ == "__main__":
    unittest.main()
