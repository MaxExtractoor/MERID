"""Tests for the flow domain — memecoins, whales, KOLs, snipers & MEV.

Covers:
  - TestFlowModels: Token, Entity, FlowEvent, enums, helpers
  - TestFlowIngestion: TokenDetector, WhaleTracker, KOLScanner, FlowIngestionService
  - TestFlowStore: SQLite CRUD for tokens, entities, events, opinions, plans, sniper orders/fills
  - TestFlowConsensus: build_token_consensus, build_all_consensus
  - TestFlowSniper: SniperExecutor simulation, routing, constraint checks
  - TestFlowRisk: FlowDomainRisk budgets, gates, throttle, halt
  - TestFlowMetrics: get_flow_metrics aggregation
  - TestFlowAPI: REST API endpoint tests
"""

import json
import os
import time
import unittest
from unittest.mock import patch

# ── Models ────────────────────────────────────────────────────────────

class TestFlowModels(unittest.TestCase):
    """Tests for flow domain models, enums, and helpers."""

    def test_chain_enum(self):
        from merid.flow.models import Chain
        self.assertEqual(Chain.SOLANA.value, "solana")
        self.assertEqual(Chain.ETHEREUM.value, "ethereum")
        self.assertEqual(Chain.BASE.value, "base")

    def test_entity_type_enum(self):
        from merid.flow.models import EntityType
        self.assertIn("whale", [e.value for e in EntityType])
        self.assertIn("kol", [e.value for e in EntityType])
        self.assertIn("deployer", [e.value for e in EntityType])

    def test_flow_event_type_enum(self):
        from merid.flow.models import FlowEventType
        self.assertIn("token_launch", [e.value for e in FlowEventType])
        self.assertIn("large_buy", [e.value for e in FlowEventType])
        self.assertIn("kol_mention", [e.value for e in FlowEventType])

    def test_flow_stance_enum(self):
        from merid.flow.models import FlowStance
        values = [s.value for s in FlowStance]
        self.assertIn("avoid", values)
        self.assertIn("spec_long", values)

    def test_mev_risk_tolerance_enum(self):
        from merid.flow.models import MevRiskTolerance
        self.assertEqual(MevRiskTolerance.LOW.value, "low")
        self.assertEqual(MevRiskTolerance.HIGH.value, "high")

    def test_plan_status_enum(self):
        from merid.flow.models import PlanStatus
        self.assertIn("proposed", [s.value for s in PlanStatus])
        self.assertIn("filled", [s.value for s in PlanStatus])

    def test_estimate_price_impact(self):
        from merid.flow.models import estimate_price_impact
        impact = estimate_price_impact(1000, 100_000)
        self.assertAlmostEqual(impact, 0.005, places=3)
        # Zero liquidity
        self.assertEqual(estimate_price_impact(1000, 0), 1.0)
        # Large trade
        self.assertLessEqual(estimate_price_impact(500_000, 100_000), 1.0)

    def test_classify_entity_quality(self):
        from merid.flow.models import classify_entity_quality
        self.assertEqual(classify_entity_quality(0, 0, 2), "unknown")
        self.assertEqual(classify_entity_quality(50_000, 0.70, 100), "elite")
        self.assertEqual(classify_entity_quality(5_000, 0.60, 50), "good")
        self.assertEqual(classify_entity_quality(100, 0.50, 20), "average")
        self.assertEqual(classify_entity_quality(-1000, 0.20, 30), "poor")

    def test_compute_flow_score(self):
        from merid.flow.models import compute_flow_score
        # Balanced
        score = compute_flow_score(2, 1, 1, 2, 1, 0, 5.0)
        self.assertGreater(score, 50)
        self.assertLessEqual(score, 100)
        # Bearish: lots of sells, LP removed
        score_bear = compute_flow_score(0, 5, 0, 0, 0, 3, 48.0)
        self.assertLess(score_bear, 50)
        # Clamped to [0, 100]
        score_max = compute_flow_score(10, 0, 5, 5, 5, 0, 0.5)
        self.assertLessEqual(score_max, 100)
        self.assertGreaterEqual(score_max, 0)

    def test_token_dataclass(self):
        from merid.flow.models import Token, LiquidityInfo
        tok = Token(symbol="TEST", name="TestCoin", chain="solana")
        self.assertTrue(tok.id.startswith("tok-"))
        self.assertEqual(tok.symbol, "TEST")
        d = tok.to_dict()
        self.assertIn("symbol", d)

    def test_token_age_hours(self):
        from merid.flow.models import Token
        tok = Token(first_lp_timestamp=time.time() - 7200)  # 2 hours ago
        self.assertAlmostEqual(tok.age_hours, 2.0, delta=0.1)

    def test_token_best_liquidity(self):
        from merid.flow.models import Token, LiquidityInfo
        tok = Token(
            liquidity=[
                LiquidityInfo(liquidity_usd=1000),
                LiquidityInfo(liquidity_usd=5000),
            ]
        )
        self.assertEqual(tok.best_liquidity_usd, 5000)

    def test_entity_dataclass(self):
        from merid.flow.models import Entity
        ent = Entity(address="abc123", entity_type="whale", label="Test Whale")
        self.assertTrue(ent.id.startswith("ent-"))
        self.assertEqual(ent.label, "Test Whale")
        d = ent.to_dict()
        self.assertIn("address", d)

    def test_entity_auto_quality(self):
        from merid.flow.models import Entity
        ent = Entity(historical_pnl_usd=100_000, hit_rate=0.70, trade_count=50)
        self.assertEqual(ent.quality, "elite")

    def test_flow_event_bullish_bearish(self):
        from merid.flow.models import FlowEvent, FlowEventType
        buy = FlowEvent(event_type=FlowEventType.LARGE_BUY.value)
        self.assertTrue(buy.is_bullish)
        self.assertFalse(buy.is_bearish)
        sell = FlowEvent(event_type=FlowEventType.LARGE_SELL.value)
        self.assertTrue(sell.is_bearish)
        self.assertFalse(sell.is_bullish)

    def test_flow_opinion_dataclass(self):
        from merid.flow.models import FlowOpinion
        op = FlowOpinion(agent_id="agent-1", token_id="tok-1", stance="spec_long")
        self.assertTrue(op.id.startswith("fop-"))
        d = op.to_dict()
        self.assertEqual(d["stance"], "spec_long")

    def test_meme_plan_dataclass(self):
        from merid.flow.models import MemePlan
        plan = MemePlan(token_id="tok-1", entry_size_usd=100)
        self.assertTrue(plan.id.startswith("mp-"))
        self.assertEqual(plan.status, "proposed")

    def test_whale_plan_dataclass(self):
        from merid.flow.models import WhalePlan
        plan = WhalePlan(token_id="tok-1", strategy="follow", entity_id="ent-1")
        self.assertTrue(plan.id.startswith("wp-"))

    def test_kol_plan_dataclass(self):
        from merid.flow.models import KOLPlan
        plan = KOLPlan(token_id="tok-1", kol_handle="@test")
        self.assertTrue(plan.id.startswith("kp-"))

    def test_sniper_order_dataclass(self):
        from merid.flow.models import SniperOrder
        order = SniperOrder(plan_id="mp-1", size_usd=50)
        self.assertTrue(order.id.startswith("snp-"))

    def test_sniper_fill_slippage(self):
        from merid.flow.models import SniperFill
        fill = SniperFill(
            order_id="snp-1", fill_price_usd=1.05, expected_price_usd=1.00,
        )
        self.assertAlmostEqual(fill.slippage_vs_plan, 500, delta=10)  # ~500 bps


# ── Ingestion ─────────────────────────────────────────────────────────

class TestFlowIngestion(unittest.TestCase):
    """Tests for ingestion services."""

    def test_token_detector_synthetic(self):
        from merid.flow.ingestion import TokenDetector
        detector = TokenDetector()
        results = detector.detect_new_tokens()
        self.assertGreater(len(results), 0)
        tok, events = results[0]
        self.assertTrue(tok.id.startswith("tok-"))
        self.assertGreater(len(events), 0)

    def test_token_detector_chain_filter(self):
        from merid.flow.ingestion import TokenDetector
        detector = TokenDetector()
        sol_results = detector.detect_new_tokens(chain="solana")
        for tok, _ in sol_results:
            self.assertEqual(tok.chain, "solana")

    def test_whale_tracker_entities(self):
        from merid.flow.ingestion import WhaleTracker
        tracker = WhaleTracker()
        entities = tracker.get_tracked_entities()
        self.assertGreater(len(entities), 0)
        types = {e.entity_type for e in entities}
        self.assertIn("whale", types)

    def test_whale_tracker_entity_filter(self):
        from merid.flow.ingestion import WhaleTracker
        tracker = WhaleTracker()
        kols = tracker.get_tracked_entities(entity_type="kol")
        for e in kols:
            self.assertEqual(e.entity_type, "kol")

    def test_whale_tracker_flows(self):
        from merid.flow.ingestion import WhaleTracker, TokenDetector
        detector = TokenDetector()
        tokens = [t for t, _ in detector.detect_new_tokens()]
        tracker = WhaleTracker()
        entities = tracker.get_tracked_entities()
        events = tracker.get_recent_flows(tokens, entities, since_hours=168)
        self.assertGreater(len(events), 0)

    def test_kol_scanner_entities(self):
        from merid.flow.ingestion import KOLScanner
        scanner = KOLScanner()
        kols = scanner.get_kol_entities()
        self.assertGreater(len(kols), 0)
        for k in kols:
            self.assertEqual(k.entity_type, "kol")

    def test_kol_scanner_events(self):
        from merid.flow.ingestion import KOLScanner, TokenDetector
        detector = TokenDetector()
        tokens = [t for t, _ in detector.detect_new_tokens()]
        scanner = KOLScanner()
        kols = scanner.get_kol_entities()
        events = scanner.get_kol_events(tokens, kols, since_hours=168)
        self.assertGreater(len(events), 0)

    def test_ingestion_service_ingest_all(self):
        from merid.flow.ingestion import FlowIngestionService
        svc = FlowIngestionService()
        data = svc.ingest_all()
        self.assertIn("tokens", data)
        self.assertIn("entities", data)
        self.assertIn("events", data)
        self.assertGreater(data["token_count"], 0)
        self.assertGreater(data["entity_count"], 0)
        self.assertGreater(data["event_count"], 0)
        self.assertEqual(data["source"], "synthetic")

    def test_ingestion_service_chain_filter(self):
        from merid.flow.ingestion import FlowIngestionService
        svc = FlowIngestionService()
        data = svc.ingest_all(chain="ethereum")
        for tok in data["tokens"]:
            self.assertEqual(tok.chain, "ethereum")


# ── Store ─────────────────────────────────────────────────────────────

class TestFlowStore(unittest.TestCase):
    """Tests for FlowStore SQLite persistence."""

    def setUp(self):
        from merid.flow.store import FlowStore
        self.store = FlowStore(db_path=":memory:")

    def test_upsert_and_get_token(self):
        from merid.flow.models import Token
        tok = Token(symbol="BONK", name="Bonk", chain="solana", contract_address="abc123")
        self.store.upsert_token(tok)
        got = self.store.get_token(tok.id)
        self.assertIsNotNone(got)
        self.assertEqual(got.symbol, "BONK")

    def test_list_tokens(self):
        from merid.flow.models import Token
        self.store.upsert_token(Token(symbol="A", chain="solana"))
        self.store.upsert_token(Token(symbol="B", chain="ethereum"))
        all_tokens = self.store.list_tokens()
        self.assertEqual(len(all_tokens), 2)
        sol_tokens = self.store.list_tokens(chain="solana")
        self.assertEqual(len(sol_tokens), 1)

    def test_upsert_and_get_entity(self):
        from merid.flow.models import Entity
        ent = Entity(address="whale-1", entity_type="whale", label="Big Whale")
        self.store.upsert_entity(ent)
        got = self.store.get_entity(ent.id)
        self.assertIsNotNone(got)
        self.assertEqual(got.label, "Big Whale")

    def test_list_entities_by_type(self):
        from merid.flow.models import Entity
        self.store.upsert_entity(Entity(address="w1", entity_type="whale"))
        self.store.upsert_entity(Entity(address="k1", entity_type="kol"))
        whales = self.store.list_entities(entity_type="whale")
        self.assertEqual(len(whales), 1)

    def test_add_and_list_events(self):
        from merid.flow.models import FlowEvent
        ev = FlowEvent(event_type="large_buy", token_id="tok-1", size_usd=50000)
        self.store.add_event(ev)
        events = self.store.list_events(token_id="tok-1", since_hours=1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].size_usd, 50000)

    def test_add_and_list_opinions(self):
        from merid.flow.models import FlowOpinion
        op = FlowOpinion(agent_id="a1", token_id="tok-1", stance="spec_long", confidence=0.8)
        self.store.add_opinion(op)
        opinions = self.store.list_opinions("tok-1")
        self.assertEqual(len(opinions), 1)
        self.assertEqual(opinions[0].stance, "spec_long")

    def test_meme_plan_crud(self):
        from merid.flow.models import MemePlan
        plan = MemePlan(token_id="tok-1", entry_size_usd=50)
        self.store.add_meme_plan(plan)
        plans = self.store.list_meme_plans()
        self.assertEqual(len(plans), 1)
        self.store.update_plan_status(plan.id, "meme", "approved")
        plans = self.store.list_meme_plans(status="approved")
        self.assertEqual(len(plans), 1)

    def test_whale_plan_crud(self):
        from merid.flow.models import WhalePlan
        plan = WhalePlan(token_id="tok-1", strategy="follow", entity_id="ent-1")
        self.store.add_whale_plan(plan)
        plans = self.store.list_whale_plans()
        self.assertEqual(len(plans), 1)

    def test_kol_plan_crud(self):
        from merid.flow.models import KOLPlan
        plan = KOLPlan(token_id="tok-1", kol_handle="@test")
        self.store.add_kol_plan(plan)
        plans = self.store.list_kol_plans()
        self.assertEqual(len(plans), 1)

    def test_sniper_order_and_fill(self):
        from merid.flow.models import SniperOrder, SniperFill
        order = SniperOrder(plan_id="mp-1", token_id="tok-1", size_usd=50)
        self.store.add_sniper_order(order)
        orders = self.store.list_sniper_orders()
        self.assertEqual(len(orders), 1)

        fill = SniperFill(order_id=order.id, plan_id="mp-1", token_id="tok-1",
                          filled_size_usd=50, success=True)
        self.store.add_sniper_fill(fill)
        fills = self.store.list_sniper_fills()
        self.assertEqual(len(fills), 1)


# ── Consensus ─────────────────────────────────────────────────────────

class TestFlowConsensus(unittest.TestCase):
    """Tests for consensus aggregation in FlowStore."""

    def setUp(self):
        from merid.flow.store import FlowStore
        from merid.flow.models import Token, Entity, FlowEvent, FlowOpinion, MemePlan
        self.store = FlowStore(db_path=":memory:")

        # Seed a token
        self.tok = Token(symbol="BONK", name="Bonk", chain="solana",
                         total_liquidity_usd=2_000_000,
                         first_lp_timestamp=time.time() - 3600)
        self.store.upsert_token(self.tok)

        # Seed events
        self.store.add_event(FlowEvent(
            event_type="large_buy", token_id=self.tok.id,
            entity_type="whale", size_usd=50000,
        ))
        self.store.add_event(FlowEvent(
            event_type="kol_buy", token_id=self.tok.id,
            entity_type="kol", size_usd=10000,
        ))
        self.store.add_event(FlowEvent(
            event_type="lp_added", token_id=self.tok.id,
            size_usd=100000,
        ))

        # Seed opinion
        self.store.add_opinion(FlowOpinion(
            agent_id="a1", token_id=self.tok.id,
            stance="spec_long", confidence=0.8,
        ))

        # Seed plan
        self.store.add_meme_plan(MemePlan(token_id=self.tok.id, entry_size_usd=50))

    def test_build_token_consensus(self):
        c = self.store.build_token_consensus(self.tok.id)
        self.assertEqual(c["symbol"], "BONK")
        self.assertGreater(c["flow_score"], 50)
        self.assertEqual(c["event_summary"]["whale_buys"], 1)
        self.assertEqual(c["event_summary"]["kol_buys"], 1)
        self.assertEqual(c["opinion_summary"]["total"], 1)
        self.assertEqual(c["opinion_summary"]["dominant_stance"], "spec_long")
        self.assertEqual(c["plan_summary"]["meme_plans"], 1)

    def test_build_all_consensus(self):
        results = self.store.build_all_consensus()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["symbol"], "BONK")

    def test_consensus_missing_token(self):
        c = self.store.build_token_consensus("nonexistent")
        self.assertEqual(c, {})

    def test_consensus_chain_filter(self):
        results = self.store.build_all_consensus(chain="ethereum")
        self.assertEqual(len(results), 0)  # BONK is solana


# ── Sniper ────────────────────────────────────────────────────────────

class TestFlowSniper(unittest.TestCase):
    """Tests for SniperExecutor."""

    def setUp(self):
        from merid.flow.sniper import SniperExecutor
        from merid.flow.models import Token, LiquidityInfo, SniperOrder
        self.sniper = SniperExecutor()
        self.token = Token(
            symbol="BONK", chain="solana",
            total_liquidity_usd=2_000_000,
            liquidity=[LiquidityInfo(liquidity_usd=2_000_000, price_usd=0.00002)],
        )
        self.order = SniperOrder(
            plan_id="mp-1", token_id=self.token.id, token_symbol="BONK",
            chain="solana", size_usd=100,
            max_slippage_bps=300, max_price_impact=0.05,
            min_liquidity_usd=10000, max_gas_usd=5.0,
            mev_risk_tolerance="low",
        )

    def test_route_selection_low_mev(self):
        route = self.sniper.select_route("solana", "low", 100)
        self.assertIsNotNone(route)
        # Should prefer MEV-protected on solana
        self.assertIn(route.route_type, ("mev_protected", "private_tx"))

    def test_route_selection_high_mev(self):
        route = self.sniper.select_route("solana", "high", 100)
        self.assertIsNotNone(route)
        self.assertEqual(route.route_type, "standard")

    def test_route_selection_unknown_chain(self):
        route = self.sniper.select_route("unknown_chain", "low", 100)
        self.assertIsNone(route)

    def test_simulate_passes(self):
        sim = self.sniper.simulate(self.order, self.token)
        self.assertTrue(sim.passed)
        self.assertGreater(sim.estimated_output_tokens, 0)

    def test_simulate_fails_low_liquidity(self):
        from merid.flow.models import Token, LiquidityInfo, SniperOrder
        low_liq_token = Token(
            symbol="RUG", chain="solana",
            liquidity=[LiquidityInfo(liquidity_usd=500, price_usd=0.001)],
            total_liquidity_usd=500,
        )
        order = SniperOrder(
            plan_id="mp-2", chain="solana", size_usd=100,
            min_liquidity_usd=10000,
        )
        sim = self.sniper.simulate(order, low_liq_token)
        self.assertFalse(sim.passed)
        self.assertIn("Insufficient liquidity", sim.reason)

    def test_simulate_fails_high_impact(self):
        from merid.flow.models import Token, LiquidityInfo, SniperOrder
        thin_token = Token(
            symbol="THIN", chain="solana",
            liquidity=[LiquidityInfo(liquidity_usd=15000, price_usd=0.01)],
            total_liquidity_usd=15000,
        )
        order = SniperOrder(
            plan_id="mp-3", chain="solana", size_usd=5000,
            min_liquidity_usd=10000, max_price_impact=0.01,
        )
        sim = self.sniper.simulate(order, thin_token)
        self.assertFalse(sim.passed)
        self.assertIn("Price impact too high", sim.reason)

    def test_execute_simulated(self):
        fill = self.sniper.execute(self.order, self.token)
        self.assertTrue(fill.success)
        self.assertGreater(fill.filled_size_usd, 0)
        self.assertTrue(fill.tx_hash.startswith("sim-"))

    def test_execute_fails_on_constraint(self):
        from merid.flow.models import Token, LiquidityInfo, SniperOrder
        bad_token = Token(
            symbol="BAD", chain="solana",
            liquidity=[LiquidityInfo(liquidity_usd=100)],
            total_liquidity_usd=100,
        )
        order = SniperOrder(plan_id="mp-4", chain="solana", size_usd=100, min_liquidity_usd=10000)
        fill = self.sniper.execute(order, bad_token)
        self.assertFalse(fill.success)
        self.assertIn("Insufficient liquidity", fill.error)

    def test_route_health_check(self):
        health = self.sniper.check_route_health("solana")
        self.assertEqual(health["chain"], "solana")
        self.assertGreater(health["total_count"], 0)
        self.assertTrue(health["has_mev_protection"])


# ── Risk ──────────────────────────────────────────────────────────────

class TestFlowRisk(unittest.TestCase):
    """Tests for FlowDomainRisk."""

    def setUp(self):
        from merid.flow.risk import FlowDomainRisk, FlowRiskConfig
        self.risk = FlowDomainRisk(config=FlowRiskConfig(
            max_domain_notional_usd=2500,
            max_daily_loss_usd=500,
            max_per_token_usd=200,
            throttle_loss_trigger_usd=300,
            halt_loss_trigger_usd=500,
            min_flow_score=30,
            min_domain_hit_rate=0.35,
        ))

    def test_check_plan_allowed(self):
        result = self.risk.check_plan("meme", "tok-1", "", 50, flow_score=60)
        self.assertTrue(result.allowed)

    def test_check_plan_halted(self):
        self.risk.state.is_halted = True
        self.risk.state.halt_reason = "Manual halt"
        result = self.risk.check_plan("meme", "tok-1", "", 50, flow_score=60)
        self.assertFalse(result.allowed)
        self.assertIn("halted", result.reason.lower())

    def test_check_plan_domain_exposure(self):
        self.risk.state.domain_exposure_usd = 2400
        result = self.risk.check_plan("meme", "tok-1", "", 200, flow_score=60)
        self.assertFalse(result.allowed)
        self.assertIn("exposure", result.reason.lower())

    def test_check_plan_per_token_limit(self):
        self.risk.state.per_token_exposure["tok-1"] = 190
        result = self.risk.check_plan("meme", "tok-1", "", 20, flow_score=60)
        self.assertFalse(result.allowed)
        self.assertIn("Per-token", result.reason)

    def test_check_plan_low_flow_score(self):
        result = self.risk.check_plan("meme", "tok-1", "", 50, flow_score=10)
        self.assertFalse(result.allowed)
        self.assertIn("Flow score", result.reason)

    def test_check_plan_low_hit_rate(self):
        result = self.risk.check_plan("meme", "tok-1", "", 50, flow_score=60, domain_hit_rate=0.10)
        self.assertFalse(result.allowed)
        self.assertIn("hit rate", result.reason.lower())

    def test_throttle_on_loss(self):
        self.risk.state.daily_loss_usd = 350  # > 300 trigger
        result = self.risk.check_plan("meme", "tok-1", "", 100, flow_score=60)
        self.assertTrue(result.allowed)
        self.assertTrue(self.risk.state.is_throttled)
        self.assertLess(result.adjusted_size_usd, 100)

    def test_halt_on_large_loss(self):
        self.risk.state.daily_loss_usd = 500
        result = self.risk.check_plan("meme", "tok-1", "", 50, flow_score=60)
        self.assertFalse(result.allowed)
        self.assertTrue(self.risk.state.is_halted)

    def test_record_fill_and_exit(self):
        self.risk.record_fill("tok-1", "ent-1", 100)
        self.assertEqual(self.risk.state.domain_exposure_usd, 100)
        self.assertEqual(self.risk.state.per_token_exposure["tok-1"], 100)

        self.risk.record_exit("tok-1", "ent-1", 100, -50)
        self.assertEqual(self.risk.state.domain_exposure_usd, 0)
        self.assertEqual(self.risk.state.daily_loss_usd, 50)

    def test_resume(self):
        self.risk.state.is_halted = True
        self.risk.state.halt_reason = "test"
        self.risk.resume()
        self.assertFalse(self.risk.state.is_halted)

    def test_reset_daily(self):
        self.risk.state.daily_loss_usd = 400
        self.risk.state.is_throttled = True
        self.risk.reset_daily()
        self.assertEqual(self.risk.state.daily_loss_usd, 0)
        self.assertFalse(self.risk.state.is_throttled)

    def test_get_status(self):
        status = self.risk.get_status()
        self.assertIn("config", status)
        self.assertIn("state", status)
        self.assertIn("utilization_pct", status)


# ── Metrics ───────────────────────────────────────────────────────────

class TestFlowMetrics(unittest.TestCase):
    """Tests for FlowStore.get_flow_metrics."""

    def setUp(self):
        from merid.flow.store import FlowStore
        self.store = FlowStore(db_path=":memory:")

    def test_empty_metrics(self):
        m = self.store.get_flow_metrics()
        self.assertEqual(m["tokens_tracked"], 0)
        self.assertEqual(m["entities_tracked"], 0)

    def test_metrics_with_data(self):
        from merid.flow.models import Token, Entity, FlowEvent, SniperFill
        self.store.upsert_token(Token(symbol="A", chain="solana"))
        self.store.upsert_entity(Entity(address="w1", entity_type="whale"))
        self.store.upsert_entity(Entity(address="k1", entity_type="kol"))
        self.store.add_event(FlowEvent(event_type="large_buy", token_id="tok-1"))
        self.store.add_sniper_fill(SniperFill(
            order_id="snp-1", filled_size_usd=100, success=True,
            actual_slippage_bps=50, latency_ms=200,
        ))

        m = self.store.get_flow_metrics()
        self.assertEqual(m["tokens_tracked"], 1)
        self.assertEqual(m["entities_tracked"], 2)
        self.assertEqual(m["whale_count"], 1)
        self.assertEqual(m["kol_count"], 1)
        self.assertEqual(m["sniper"]["total_fills"], 1)
        self.assertEqual(m["sniper"]["success_rate"], 1.0)


# ── API ───────────────────────────────────────────────────────────────

class TestFlowAPI(unittest.TestCase):
    """Tests for flow REST API endpoints."""

    @classmethod
    def setUpClass(cls):
        from merid.flow.store import FlowStore
        cls._store = FlowStore(db_path=":memory:")

    def setUp(self):
        from fastapi.testclient import TestClient
        from web.api.flow_api import flow_router, _get_store
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(flow_router)

        # Override store dependency
        def override_store():
            return self.__class__._store

        import web.api.flow_api as api_mod
        self._original_get_store = api_mod._get_store
        api_mod._get_store = override_store

        self.client = TestClient(app)

    def tearDown(self):
        import web.api.flow_api as api_mod
        api_mod._get_store = self._original_get_store

    def test_radar_stub(self):
        resp = self.client.get("/api/v1/flow/radar")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("tokens", data)
        self.assertIn("source", data)

    def test_tokens_stub(self):
        resp = self.client.get("/api/v1/flow/tokens")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("tokens", data)

    def test_entities_stub(self):
        resp = self.client.get("/api/v1/flow/entities")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("entities", data)

    def test_events_stub(self):
        resp = self.client.get("/api/v1/flow/events")
        self.assertEqual(resp.status_code, 200)

    def test_plans_empty(self):
        resp = self.client.get("/api/v1/flow/plans")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("meme_plans", data)

    def test_sniper_status(self):
        resp = self.client.get("/api/v1/flow/sniper/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("route_health", data)

    def test_sniper_fills_empty(self):
        resp = self.client.get("/api/v1/flow/sniper/fills")
        self.assertEqual(resp.status_code, 200)

    def test_risk_status(self):
        resp = self.client.get("/api/v1/flow/risk")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("state", data)

    def test_metrics(self):
        resp = self.client.get("/api/v1/flow/metrics")
        self.assertEqual(resp.status_code, 200)

    def test_submit_opinion(self):
        resp = self.client.post("/api/v1/flow/opinion", json={
            "agent_id": "agent-1", "token_id": "tok-test",
            "stance": "spec_long", "confidence": 0.8,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_submit_meme_plan(self):
        resp = self.client.post("/api/v1/flow/plan/meme", json={
            "token_id": "tok-test", "entry_size_usd": 50,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["plan_type"], "meme")

    def test_submit_whale_plan(self):
        resp = self.client.post("/api/v1/flow/plan/whale", json={
            "token_id": "tok-test", "strategy": "follow",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["plan_type"], "whale")

    def test_submit_kol_plan(self):
        resp = self.client.post("/api/v1/flow/plan/kol", json={
            "token_id": "tok-test", "kol_handle": "@test",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["plan_type"], "kol")

    def test_ingest(self):
        resp = self.client.post("/api/v1/flow/ingest")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertGreater(data["tokens_ingested"], 0)

    def test_risk_resume(self):
        resp = self.client.post("/api/v1/flow/risk/resume")
        self.assertEqual(resp.status_code, 200)

    def test_token_consensus_404(self):
        resp = self.client.get("/api/v1/flow/token/nonexistent")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
