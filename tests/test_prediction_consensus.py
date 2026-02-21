"""Tests for prediction market consensus — §1–§8 of the Kalshi integration.

Covers:
  - PredictionConsensusStore: instruments, opinions, plans, resolved markets
  - Consensus summary: swarm_prob vs market_prob, edge, stance classification
  - Brier scores: per-agent, swarm vs market, calibration
  - Plan execution checks: edge-gated, time-gated
  - Brier degradation risk check
  - Category exposure summary
  - REST endpoints: /api/v1/prediction/consensus/summary, /metrics, POST opinion/plan/resolve
  - Notification on resolution
"""

import json
import os
import tempfile
import time
import unittest

# Ensure test DB is isolated
_TEST_DB = os.path.join(tempfile.gettempdir(), f"pred_consensus_test_{os.getpid()}.db")
os.environ["MERID_PRED_CONSENSUS_DB"] = _TEST_DB

from merid.prediction.consensus import (
    PredictionConsensusStore,
    PredictionInstrument,
    PredictionOpinion,
    PredictionPlan,
    ResolvedMarket,
    _make_pred_symbol,
    _parse_pred_symbol,
    STRONG_EDGE_THRESHOLD,
    WEAK_EDGE_THRESHOLD,
)


def _fresh_store() -> PredictionConsensusStore:
    """Create a fresh in-memory store for each test."""
    db = os.path.join(tempfile.gettempdir(), f"pred_test_{id(object())}.db")
    if os.path.exists(db):
        os.remove(db)
    return PredictionConsensusStore(db_path=db)


def _seed_instrument(store, ticker="FED-25MAR-T4.50", category="macro",
                     market_prob=0.65, volume=10000, outcome="YES",
                     status="active", expiry=None):
    symbol = _make_pred_symbol("kalshi", ticker, outcome)
    inst = PredictionInstrument(
        symbol=symbol, venue="kalshi", event_id=ticker.rsplit("-", 1)[0],
        ticker=ticker, outcome=outcome, category=category,
        title=f"Test: {ticker}", market_implied_prob=market_prob,
        volume=volume, status=status,
        expiry=expiry or (time.time() + 86400),
    )
    store.upsert_instrument(inst)
    return inst


def _seed_opinions(store, symbol, probs_and_confs):
    """probs_and_confs: list of (agent_id, probability, confidence)."""
    for agent_id, prob, conf in probs_and_confs:
        store.add_opinion(PredictionOpinion(
            agent_id=agent_id, agent_name=f"Agent-{agent_id}",
            symbol=symbol, probability=prob, confidence=conf,
            reasoning="test reasoning",
        ))


class TestSymbolHelpers(unittest.TestCase):
    def test_make_pred_symbol(self):
        s = _make_pred_symbol("kalshi", "FED-25MAR-T4.50", "YES")
        self.assertEqual(s, "PRED:KALSHI:FED-25MAR-T4.50:YES")

    def test_parse_pred_symbol(self):
        result = _parse_pred_symbol("PRED:KALSHI:FED-25MAR-T4.50:YES")
        self.assertEqual(result["venue"], "kalshi")
        self.assertEqual(result["ticker"], "FED-25MAR-T4.50")
        self.assertEqual(result["outcome"], "YES")

    def test_parse_invalid(self):
        self.assertIsNone(_parse_pred_symbol("BTC-USD"))
        self.assertIsNone(_parse_pred_symbol("PRED:KALSHI"))


class TestInstruments(unittest.TestCase):
    def setUp(self):
        self.store = _fresh_store()

    def test_upsert_and_get(self):
        inst = _seed_instrument(self.store)
        got = self.store.get_instrument(inst.symbol)
        self.assertIsNotNone(got)
        self.assertEqual(got.ticker, "FED-25MAR-T4.50")
        self.assertEqual(got.category, "macro")

    def test_list_instruments_filtered(self):
        _seed_instrument(self.store, "FED-25MAR-T4.50", "macro")
        _seed_instrument(self.store, "BTCUSD-25MAR-100K", "crypto")
        all_insts = self.store.list_instruments()
        self.assertEqual(len(all_insts), 2)
        macro_only = self.store.list_instruments(category="macro")
        self.assertEqual(len(macro_only), 1)

    def test_instrument_count(self):
        _seed_instrument(self.store, "A", "macro")
        _seed_instrument(self.store, "B", "crypto")
        _seed_instrument(self.store, "C", "politics", status="settled_yes")
        self.assertEqual(self.store.instrument_count(), 3)
        self.assertEqual(self.store.instrument_count(status="active"), 2)

    def test_upsert_updates(self):
        inst = _seed_instrument(self.store, market_prob=0.5)
        inst.market_implied_prob = 0.75
        self.store.upsert_instrument(inst)
        got = self.store.get_instrument(inst.symbol)
        self.assertAlmostEqual(got.market_implied_prob, 0.75)

    def test_to_dict(self):
        inst = _seed_instrument(self.store)
        d = inst.to_dict()
        self.assertEqual(d["asset_class"], "prediction")
        self.assertEqual(d["venue"], "kalshi")


class TestOpinions(unittest.TestCase):
    def setUp(self):
        self.store = _fresh_store()

    def test_add_and_list(self):
        inst = _seed_instrument(self.store)
        _seed_opinions(self.store, inst.symbol, [
            ("a1", 0.7, 0.8),
            ("a2", 0.4, 0.6),
        ])
        opinions = self.store.list_opinions(symbol=inst.symbol)
        self.assertEqual(len(opinions), 2)

    def test_list_all(self):
        inst1 = _seed_instrument(self.store, "A", "macro")
        inst2 = _seed_instrument(self.store, "B", "crypto")
        _seed_opinions(self.store, inst1.symbol, [("a1", 0.7, 0.8)])
        _seed_opinions(self.store, inst2.symbol, [("a2", 0.3, 0.6)])
        all_ops = self.store.list_opinions()
        self.assertEqual(len(all_ops), 2)

    def test_opinion_to_dict(self):
        op = PredictionOpinion(
            agent_id="a1", symbol="PRED:KALSHI:X:YES",
            probability=0.72, confidence=0.85,
            signal_sources=["news", "macro"],
        )
        d = op.to_dict()
        self.assertAlmostEqual(d["probability"], 0.72)
        self.assertEqual(d["signal_sources"], ["news", "macro"])


class TestPlans(unittest.TestCase):
    def setUp(self):
        self.store = _fresh_store()

    def test_add_and_list(self):
        inst = _seed_instrument(self.store)
        plan = PredictionPlan(
            symbol=inst.symbol, direction="yes",
            target_size_usd=200, max_edge_threshold=0.05,
            confidence=0.7, supporting_agents=["a1", "a2"],
        )
        self.store.add_plan(plan)
        plans = self.store.list_plans(symbol=inst.symbol)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].direction, "yes")

    def test_update_status(self):
        plan = PredictionPlan(symbol="SYM", direction="yes")
        self.store.add_plan(plan)
        self.assertTrue(self.store.update_plan_status(plan.id, "approved"))
        plans = self.store.list_plans(status="approved")
        self.assertEqual(len(plans), 1)

    def test_list_by_status(self):
        for status in ("proposed", "approved", "executing"):
            p = PredictionPlan(symbol="SYM", direction="yes", status=status)
            self.store.add_plan(p)
        self.assertEqual(len(self.store.list_plans(status="proposed")), 1)
        self.assertEqual(len(self.store.list_plans(status="approved")), 1)

    def test_plan_to_dict(self):
        plan = PredictionPlan(
            symbol="SYM", direction="no", target_size_usd=100,
            max_edge_threshold=0.05, supporting_agents=["a1"],
        )
        d = plan.to_dict()
        self.assertEqual(d["direction"], "no")
        self.assertEqual(d["supporting_agents"], ["a1"])


class TestConsensusSummary(unittest.TestCase):
    def setUp(self):
        self.store = _fresh_store()

    def test_strong_yes_stance(self):
        inst = _seed_instrument(self.store, market_prob=0.50)
        _seed_opinions(self.store, inst.symbol, [
            ("a1", 0.80, 0.9),
            ("a2", 0.75, 0.8),
        ])
        summaries = self.store.get_consensus_summary()
        self.assertEqual(len(summaries), 1)
        s = summaries[0]
        self.assertEqual(s["stance"], "strong_yes")
        self.assertGreater(s["edge"], STRONG_EDGE_THRESHOLD)

    def test_weak_no_stance(self):
        inst = _seed_instrument(self.store, market_prob=0.60)
        _seed_opinions(self.store, inst.symbol, [
            ("a1", 0.53, 0.7),
            ("a2", 0.50, 0.6),
        ])
        summaries = self.store.get_consensus_summary()
        s = summaries[0]
        self.assertEqual(s["stance"], "weak_no")

    def test_neutral_stance(self):
        inst = _seed_instrument(self.store, market_prob=0.50)
        _seed_opinions(self.store, inst.symbol, [
            ("a1", 0.51, 0.8),
            ("a2", 0.49, 0.8),
        ])
        summaries = self.store.get_consensus_summary()
        s = summaries[0]
        self.assertEqual(s["stance"], "neutral")

    def test_agent_counts(self):
        inst = _seed_instrument(self.store, market_prob=0.50)
        _seed_opinions(self.store, inst.symbol, [
            ("a1", 0.70, 0.8),  # yes
            ("a2", 0.65, 0.7),  # yes
            ("a3", 0.30, 0.6),  # no
        ])
        summaries = self.store.get_consensus_summary()
        s = summaries[0]
        self.assertEqual(s["supporting_agents"], 2)
        self.assertEqual(s["opposing_agents"], 1)

    def test_plan_counts_in_summary(self):
        inst = _seed_instrument(self.store)
        self.store.add_plan(PredictionPlan(symbol=inst.symbol, status="proposed"))
        self.store.add_plan(PredictionPlan(symbol=inst.symbol, status="approved"))
        self.store.add_plan(PredictionPlan(symbol=inst.symbol, status="executing"))
        summaries = self.store.get_consensus_summary()
        plans = summaries[0]["active_plans"]
        self.assertEqual(plans["proposed"], 1)
        self.assertEqual(plans["approved"], 1)
        self.assertEqual(plans["executing"], 1)

    def test_category_filter(self):
        _seed_instrument(self.store, "A", "macro")
        _seed_instrument(self.store, "B", "crypto")
        macro = self.store.get_consensus_summary(category="macro")
        self.assertEqual(len(macro), 1)
        self.assertEqual(macro[0]["category"], "macro")

    def test_no_opinions_defaults(self):
        _seed_instrument(self.store, market_prob=0.60)
        summaries = self.store.get_consensus_summary()
        s = summaries[0]
        # swarm_prob defaults to 0.5 when no opinions
        self.assertAlmostEqual(s["swarm_prob"], 0.5)
        self.assertEqual(s["stance"], "weak_no")

    def test_multi_market(self):
        for ticker in ["A", "B", "C", "D"]:
            _seed_instrument(self.store, ticker, "macro")
        summaries = self.store.get_consensus_summary()
        self.assertEqual(len(summaries), 4)


class TestResolvedMarkets(unittest.TestCase):
    def setUp(self):
        self.store = _fresh_store()

    def test_record_resolution(self):
        inst = _seed_instrument(self.store)
        rm = ResolvedMarket(symbol=inst.symbol, outcome=1, pnl_usd=50.0)
        self.store.record_resolution(rm)
        resolved = self.store.list_resolved()
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].outcome, 1)
        # Instrument should be settled
        updated = self.store.get_instrument(inst.symbol)
        self.assertEqual(updated.status, "settled_yes")

    def test_resolved_no(self):
        inst = _seed_instrument(self.store)
        self.store.record_resolution(ResolvedMarket(symbol=inst.symbol, outcome=0))
        updated = self.store.get_instrument(inst.symbol)
        self.assertEqual(updated.status, "settled_no")


class TestBrierScores(unittest.TestCase):
    def setUp(self):
        self.store = _fresh_store()

    def test_no_resolved_returns_none(self):
        brier = self.store.compute_brier_scores()
        self.assertIsNone(brier["swarm_brier"])
        self.assertEqual(brier["resolved_count"], 0)

    def test_perfect_prediction(self):
        """Agent predicts 1.0 for YES and outcome is YES → Brier = 0."""
        inst = _seed_instrument(self.store, market_prob=0.50)
        _seed_opinions(self.store, inst.symbol, [("a1", 1.0, 1.0)])
        self.store.record_resolution(ResolvedMarket(
            symbol=inst.symbol, outcome=1, pnl_usd=100.0,
        ))
        brier = self.store.compute_brier_scores()
        self.assertAlmostEqual(brier["swarm_brier"], 0.0, places=3)

    def test_worst_prediction(self):
        """Agent predicts 0.0 for YES but outcome is YES → Brier = 1."""
        inst = _seed_instrument(self.store, market_prob=0.50)
        _seed_opinions(self.store, inst.symbol, [("a1", 0.0, 1.0)])
        self.store.record_resolution(ResolvedMarket(
            symbol=inst.symbol, outcome=1, pnl_usd=-100.0,
        ))
        brier = self.store.compute_brier_scores()
        self.assertAlmostEqual(brier["swarm_brier"], 1.0, places=3)

    def test_swarm_vs_market(self):
        """Swarm closer to truth than market → swarm_vs_market = 'better'."""
        inst = _seed_instrument(self.store, market_prob=0.30)
        _seed_opinions(self.store, inst.symbol, [("a1", 0.90, 1.0)])
        self.store.record_resolution(ResolvedMarket(
            symbol=inst.symbol, outcome=1,
        ))
        brier = self.store.compute_brier_scores()
        self.assertEqual(brier["swarm_vs_market"], "better")
        self.assertLess(brier["swarm_brier"], brier["market_brier"])

    def test_agent_ranking(self):
        """Multiple agents with different accuracy → correct ranking."""
        inst = _seed_instrument(self.store, market_prob=0.50)
        _seed_opinions(self.store, inst.symbol, [
            ("good_agent", 0.90, 1.0),
            ("bad_agent", 0.20, 1.0),
        ])
        self.store.record_resolution(ResolvedMarket(symbol=inst.symbol, outcome=1))
        brier = self.store.compute_brier_scores()
        ranking = brier["agent_ranking"]
        self.assertEqual(ranking[0]["agent_id"], "good_agent")
        self.assertLess(ranking[0]["brier"], ranking[1]["brier"])

    def test_calibration_buckets(self):
        """Calibration data has 10 buckets."""
        inst = _seed_instrument(self.store, market_prob=0.50)
        _seed_opinions(self.store, inst.symbol, [("a1", 0.70, 1.0)])
        self.store.record_resolution(ResolvedMarket(symbol=inst.symbol, outcome=1))
        brier = self.store.compute_brier_scores()
        self.assertEqual(len(brier["calibration"]), 10)

    def test_total_pnl(self):
        for i, pnl in enumerate([50.0, -20.0, 30.0]):
            inst = _seed_instrument(self.store, f"MKT-{i}", market_prob=0.50)
            _seed_opinions(self.store, inst.symbol, [("a1", 0.60, 0.8)])
            self.store.record_resolution(ResolvedMarket(
                symbol=inst.symbol, outcome=1, pnl_usd=pnl,
            ))
        brier = self.store.compute_brier_scores()
        self.assertAlmostEqual(brier["total_pnl_usd"], 60.0)


class TestPlanExecution(unittest.TestCase):
    def setUp(self):
        self.store = _fresh_store()

    def test_executable_when_edge_above_threshold(self):
        inst = _seed_instrument(self.store, market_prob=0.50)
        _seed_opinions(self.store, inst.symbol, [("a1", 0.80, 1.0)])
        plan = PredictionPlan(
            symbol=inst.symbol, direction="yes",
            max_edge_threshold=0.05,
        )
        self.store.add_plan(plan)
        result = self.store.check_plan_executable(plan)
        self.assertTrue(result["executable"])
        self.assertGreater(result["edge"], 0.05)

    def test_not_executable_when_edge_below_threshold(self):
        inst = _seed_instrument(self.store, market_prob=0.50)
        _seed_opinions(self.store, inst.symbol, [("a1", 0.52, 1.0)])
        plan = PredictionPlan(
            symbol=inst.symbol, direction="yes",
            max_edge_threshold=0.05,
        )
        self.store.add_plan(plan)
        result = self.store.check_plan_executable(plan)
        self.assertFalse(result["executable"])
        self.assertIn("threshold", result["reason"])

    def test_not_executable_near_expiry(self):
        inst = _seed_instrument(self.store, market_prob=0.50,
                                expiry=time.time() + 1800)  # 30 min
        _seed_opinions(self.store, inst.symbol, [("a1", 0.90, 1.0)])
        plan = PredictionPlan(
            symbol=inst.symbol, direction="yes",
            max_edge_threshold=0.05,
            cutoff_hours_before_expiry=1.0,
        )
        self.store.add_plan(plan)
        result = self.store.check_plan_executable(plan)
        self.assertFalse(result["executable"])
        self.assertIn("expiry", result["reason"])

    def test_not_executable_settled(self):
        inst = _seed_instrument(self.store, status="settled_yes")
        plan = PredictionPlan(symbol=inst.symbol, direction="yes")
        self.store.add_plan(plan)
        result = self.store.check_plan_executable(plan)
        self.assertFalse(result["executable"])

    def test_not_executable_missing_instrument(self):
        plan = PredictionPlan(symbol="PRED:KALSHI:MISSING:YES", direction="yes")
        self.store.add_plan(plan)
        result = self.store.check_plan_executable(plan)
        self.assertFalse(result["executable"])


class TestBrierDegradation(unittest.TestCase):
    def setUp(self):
        self.store = _fresh_store()

    def test_insufficient_data(self):
        result = self.store.check_brier_degradation()
        self.assertFalse(result["degraded"])
        self.assertEqual(result["recommendation"], "none")

    def test_good_brier(self):
        # Seed 5 resolved markets with good predictions
        for i in range(5):
            inst = _seed_instrument(self.store, f"MKT-{i}", market_prob=0.50)
            _seed_opinions(self.store, inst.symbol, [("a1", 0.90, 1.0)])
            self.store.record_resolution(ResolvedMarket(
                symbol=inst.symbol, outcome=1,
            ))
        result = self.store.check_brier_degradation(threshold=0.35)
        self.assertFalse(result["degraded"])
        self.assertEqual(result["recommendation"], "none")

    def test_degraded_brier(self):
        # Seed 5 resolved markets with bad predictions
        for i in range(5):
            inst = _seed_instrument(self.store, f"MKT-{i}", market_prob=0.80)
            _seed_opinions(self.store, inst.symbol, [("a1", 0.10, 1.0)])
            self.store.record_resolution(ResolvedMarket(
                symbol=inst.symbol, outcome=1,
            ))
        result = self.store.check_brier_degradation(threshold=0.35)
        self.assertTrue(result["degraded"])
        self.assertIn(result["recommendation"], ("throttle", "pause"))


class TestCategoryExposure(unittest.TestCase):
    def setUp(self):
        self.store = _fresh_store()

    def test_category_summary(self):
        _seed_instrument(self.store, "A", "macro")
        _seed_instrument(self.store, "B", "macro")
        _seed_instrument(self.store, "C", "crypto")
        inst_a = self.store.list_instruments(category="macro")[0]
        self.store.add_plan(PredictionPlan(
            symbol=inst_a.symbol, status="executing",
        ))
        summary = self.store.get_category_exposure_summary()
        self.assertEqual(summary["macro"]["instruments"], 2)
        self.assertEqual(summary["macro"]["executing_plans"], 1)
        self.assertEqual(summary["crypto"]["instruments"], 1)


class TestRESTEndpoints(unittest.TestCase):
    """Test API endpoints via FastAPI test client."""

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
            from web.api.prediction_consensus_api import router
            from fastapi import FastAPI
            app = FastAPI()
            app.include_router(router)
            cls.client = TestClient(app)
            cls.available = True
        except Exception:
            cls.available = False

    def setUp(self):
        if not self.available:
            self.skipTest("FastAPI test client unavailable")

    def test_consensus_summary_stub_fallback(self):
        resp = self.client.get("/api/v1/prediction/consensus/summary")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("symbols", data)

    def test_metrics_stub_fallback(self):
        resp = self.client.get("/api/v1/prediction/metrics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("brier", data)

    def test_opinions_endpoint(self):
        resp = self.client.get("/api/v1/prediction/consensus/opinions")
        self.assertEqual(resp.status_code, 200)

    def test_plans_endpoint(self):
        resp = self.client.get("/api/v1/prediction/consensus/plans")
        self.assertEqual(resp.status_code, 200)

    def test_instruments_endpoint(self):
        resp = self.client.get("/api/v1/prediction/consensus/instruments")
        self.assertEqual(resp.status_code, 200)

    def test_submit_opinion(self):
        resp = self.client.post("/api/v1/prediction/consensus/opinions", json={
            "agent_id": "test-agent",
            "symbol": "PRED:KALSHI:TEST:YES",
            "probability": 0.75,
            "confidence": 0.8,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")

    def test_submit_opinion_invalid_prob(self):
        resp = self.client.post("/api/v1/prediction/consensus/opinions", json={
            "agent_id": "test-agent",
            "symbol": "PRED:KALSHI:TEST:YES",
            "probability": 1.5,
            "confidence": 0.8,
        })
        self.assertEqual(resp.status_code, 400)

    def test_submit_plan(self):
        resp = self.client.post("/api/v1/prediction/consensus/plans", json={
            "symbol": "PRED:KALSHI:TEST:YES",
            "direction": "yes",
            "target_size_usd": 200.0,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")

    def test_resolve_market(self):
        resp = self.client.post("/api/v1/prediction/consensus/resolve", json={
            "symbol": "PRED:KALSHI:TEST:YES",
            "outcome": 1,
            "pnl_usd": 42.50,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["resolved"]["outcome"], 1)

    def test_resolve_invalid_outcome(self):
        resp = self.client.post("/api/v1/prediction/consensus/resolve", json={
            "symbol": "PRED:KALSHI:TEST:YES",
            "outcome": 2,
        })
        self.assertEqual(resp.status_code, 400)


class TestGoldenPath(unittest.TestCase):
    """End-to-end: seed → opinions → consensus → plan → execute check → resolve → Brier."""

    def test_full_lifecycle(self):
        store = _fresh_store()

        # 1. Register instrument
        inst = _seed_instrument(store, "FOMC-25MAR", "macro", market_prob=0.60)

        # 2. Agents submit opinions
        _seed_opinions(store, inst.symbol, [
            ("macro-analyst", 0.80, 0.9),
            ("quant-model", 0.75, 0.85),
            ("news-agent", 0.70, 0.7),
            ("contrarian", 0.40, 0.5),
        ])

        # 3. Check consensus summary
        summaries = store.get_consensus_summary()
        self.assertEqual(len(summaries), 1)
        s = summaries[0]
        self.assertGreater(s["swarm_prob"], 0.60)
        self.assertGreater(s["edge"], 0)
        self.assertIn(s["stance"], ("strong_yes", "weak_yes"))
        self.assertEqual(s["supporting_agents"], 3)
        self.assertEqual(s["opposing_agents"], 1)

        # 4. Create a plan
        plan = PredictionPlan(
            symbol=inst.symbol, direction="yes",
            target_size_usd=200.0, max_edge_threshold=0.05,
            confidence=0.75, supporting_agents=["macro-analyst", "quant-model", "news-agent"],
            opposing_agents=["contrarian"],
        )
        store.add_plan(plan)

        # 5. Check plan is executable
        result = store.check_plan_executable(plan)
        self.assertTrue(result["executable"])

        # 6. Approve and execute
        store.update_plan_status(plan.id, "approved")
        store.update_plan_status(plan.id, "executing")

        # 7. Market resolves YES
        store.record_resolution(ResolvedMarket(
            symbol=inst.symbol, outcome=1, pnl_usd=75.0,
        ))

        # 8. Compute Brier scores
        brier = store.compute_brier_scores()
        self.assertIsNotNone(brier["swarm_brier"])
        self.assertLess(brier["swarm_brier"], 0.15)  # Good prediction
        self.assertEqual(brier["resolved_count"], 1)
        self.assertAlmostEqual(brier["total_pnl_usd"], 75.0)

        # 9. Close plan
        store.update_plan_status(plan.id, "closed")
        plans = store.list_plans(status="closed")
        self.assertEqual(len(plans), 1)


class TestAggregateSwarmProb(unittest.TestCase):
    def test_weighted_average(self):
        """Confidence-weighted average: high-confidence opinion dominates."""
        store = _fresh_store()
        ops = [
            PredictionOpinion(agent_id="a1", probability=0.90, confidence=0.9),
            PredictionOpinion(agent_id="a2", probability=0.10, confidence=0.1),
        ]
        result = store._aggregate_swarm_prob(ops)
        # (0.90*0.9 + 0.10*0.1) / (0.9+0.1) = 0.82
        self.assertAlmostEqual(result, 0.82, places=2)

    def test_empty_opinions(self):
        store = _fresh_store()
        result = store._aggregate_swarm_prob([])
        self.assertAlmostEqual(result, 0.5)

    def test_zero_confidence(self):
        store = _fresh_store()
        ops = [
            PredictionOpinion(agent_id="a1", probability=0.70, confidence=0.0),
            PredictionOpinion(agent_id="a2", probability=0.30, confidence=0.0),
        ]
        result = store._aggregate_swarm_prob(ops)
        self.assertAlmostEqual(result, 0.50, places=2)


class TestStanceClassification(unittest.TestCase):
    def test_strong_yes(self):
        self.assertEqual(
            PredictionConsensusStore._classify_stance(0.15), "strong_yes"
        )

    def test_weak_yes(self):
        self.assertEqual(
            PredictionConsensusStore._classify_stance(0.05), "weak_yes"
        )

    def test_neutral(self):
        self.assertEqual(
            PredictionConsensusStore._classify_stance(0.01), "neutral"
        )

    def test_weak_no(self):
        self.assertEqual(
            PredictionConsensusStore._classify_stance(-0.05), "weak_no"
        )

    def test_strong_no(self):
        self.assertEqual(
            PredictionConsensusStore._classify_stance(-0.15), "strong_no"
        )


if __name__ == "__main__":
    unittest.main()
