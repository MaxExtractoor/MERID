"""Tests for the betting domain: models, odds client, store, consensus, API.

Coverage:
  - §1 Data models: BettingEvent, BookOdds, BettingEventConsensus, LiveBetPlan, helpers
  - §2 OddsAPIClient: synthetic events, odds, vig removal, consensus computation
  - §3 BettingStore: CRUD for events, odds, opinions, plans, settlements
  - §4 Consensus aggregator: build_consensus, build_all_consensus, edges, stance
  - §5 Plan executability: edge/latency/state checks
  - §6 Betting metrics: win rate, ROI, PnL
  - §7 API endpoints: summary, live, events, plans, metrics, opinion, plan, settle
"""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

# ── §1 Data models ───────────────────────────────────────────────────

class TestBettingModels(unittest.TestCase):
    """Test data models: BettingEvent, BookOdds, Consensus, etc."""

    def test_american_to_decimal_positive(self):
        from merid.betting.models import american_to_decimal
        # +150 → 2.50
        self.assertAlmostEqual(american_to_decimal(150), 2.50)

    def test_american_to_decimal_negative(self):
        from merid.betting.models import american_to_decimal
        # -110 → 1.909...
        self.assertAlmostEqual(american_to_decimal(-110), 1.0 + 100 / 110, places=4)

    def test_american_to_decimal_zero(self):
        from merid.betting.models import american_to_decimal
        self.assertEqual(american_to_decimal(0), 1.0)

    def test_decimal_to_implied_prob(self):
        from merid.betting.models import decimal_to_implied_prob
        self.assertAlmostEqual(decimal_to_implied_prob(2.0), 0.50)
        self.assertAlmostEqual(decimal_to_implied_prob(0), 0.0)

    def test_remove_vig(self):
        from merid.betting.models import remove_vig
        probs = remove_vig([0.55, 0.55])  # 110% total
        self.assertAlmostEqual(sum(probs), 1.0, places=4)
        self.assertAlmostEqual(probs[0], 0.5, places=4)

    def test_remove_vig_empty(self):
        from merid.betting.models import remove_vig
        self.assertEqual(remove_vig([]), [])

    def test_betting_event_auto_id(self):
        from merid.betting.models import BettingEvent
        ev = BettingEvent(sport="nfl", title="Test Game")
        self.assertTrue(len(ev.id) > 0)
        self.assertTrue(ev.created_at > 0)

    def test_betting_event_to_dict(self):
        from merid.betting.models import BettingEvent, BettingOutcome
        ev = BettingEvent(
            id="test-1", sport="nba", league="NBA",
            title="Lakers vs Celtics", home_team="Lakers", away_team="Celtics",
            outcomes=[BettingOutcome(id="h", name="Lakers"), BettingOutcome(id="a", name="Celtics")],
        )
        d = ev.to_dict()
        self.assertEqual(d["id"], "test-1")
        self.assertEqual(d["sport"], "nba")
        self.assertEqual(len(d["outcomes"]), 2)

    def test_book_odds_auto_compute(self):
        from merid.betting.models import BookOdds
        bo = BookOdds(book="draftkings", outcome_id="h", american_odds=-110)
        self.assertGreater(bo.decimal_odds, 1.0)
        self.assertGreater(bo.raw_implied_prob, 0.0)

    def test_book_odds_from_decimal(self):
        from merid.betting.models import BookOdds
        bo = BookOdds(book="fanduel", outcome_id="h", decimal_odds=2.0)
        self.assertAlmostEqual(bo.raw_implied_prob, 0.5)

    def test_betting_outcome_auto_id(self):
        from merid.betting.models import BettingOutcome
        oc = BettingOutcome(name="Team A")
        self.assertTrue(len(oc.id) > 0)

    def test_odds_snapshot_to_dict(self):
        from merid.betting.models import OddsSnapshot
        snap = OddsSnapshot(event_id="ev-1", market_type="moneyline")
        d = snap.to_dict()
        self.assertEqual(d["event_id"], "ev-1")

    def test_live_bet_plan_auto_id(self):
        from merid.betting.models import LiveBetPlan
        plan = LiveBetPlan(event_id="ev-1", outcome_id="h")
        self.assertTrue(plan.id.startswith("bet-"))

    def test_live_bet_plan_to_dict(self):
        from merid.betting.models import LiveBetPlan
        plan = LiveBetPlan(id="bet-abc", event_id="ev-1", outcome_id="h", stake_usd=50)
        d = plan.to_dict()
        self.assertEqual(d["stake_usd"], 50)
        self.assertEqual(d["status"], "proposed")

    def test_settled_bet_to_dict(self):
        from merid.betting.models import SettledBet
        sb = SettledBet(bet_id="b1", event_id="ev-1", outcome_id="h",
                        stake_usd=100, placed_odds=2.0, result="won", pnl_usd=100)
        d = sb.to_dict()
        self.assertEqual(d["result"], "won")
        self.assertEqual(d["pnl_usd"], 100.0)

    def test_consensus_compute_edges(self):
        from merid.betting.models import BettingEventConsensus
        c = BettingEventConsensus(
            event_id="ev-1",
            sportsbook_consensus_prob={"h": 0.50, "a": 0.50},
            swarm_prob={"h": 0.60, "a": 0.40},
        )
        c.compute_edges()
        self.assertAlmostEqual(c.edge_vs_books["h"], 0.10, places=2)
        self.assertAlmostEqual(c.edge_vs_books["a"], -0.10, places=2)
        self.assertGreaterEqual(c.max_edge, 0.09)
        self.assertIn("strong", c.stance)

    def test_consensus_neutral_stance(self):
        from merid.betting.models import BettingEventConsensus
        c = BettingEventConsensus(
            event_id="ev-1",
            sportsbook_consensus_prob={"h": 0.50, "a": 0.50},
            swarm_prob={"h": 0.51, "a": 0.49},
        )
        c.compute_edges()
        self.assertEqual(c.stance, "neutral")

    def test_classify_betting_stance(self):
        from merid.betting.models import classify_betting_stance
        self.assertEqual(classify_betting_stance(0.01, {}, {}), "neutral")
        self.assertIn("weak", classify_betting_stance(0.05, {"h": 0.55}, {"h": 0.50}))
        self.assertIn("strong", classify_betting_stance(0.12, {"h": 0.62}, {"h": 0.50}))

    def test_event_state_enum(self):
        from merid.betting.models import EventState
        self.assertEqual(EventState.PRE, "pre")
        self.assertEqual(EventState.LIVE, "live")

    def test_market_type_enum(self):
        from merid.betting.models import MarketType
        self.assertEqual(MarketType.MONEYLINE, "moneyline")
        self.assertEqual(MarketType.SPREAD, "spread")


# ── §2 OddsAPIClient ─────────────────────────────────────────────────

class TestOddsAPIClient(unittest.TestCase):
    """Test odds ingestion client: synthetic events, odds, vig removal."""

    def test_synthetic_events(self):
        from merid.betting.odds_client import OddsAPIClient
        client = OddsAPIClient()
        events = client.fetch_events()
        self.assertGreater(len(events), 0)
        self.assertTrue(all(e.id for e in events))

    def test_synthetic_events_sport_filter(self):
        from merid.betting.odds_client import OddsAPIClient
        client = OddsAPIClient()
        nba = client.fetch_events("nba")
        self.assertTrue(all(e.sport == "nba" for e in nba))

    def test_synthetic_odds(self):
        from merid.betting.odds_client import OddsAPIClient
        client = OddsAPIClient()
        snap = client.fetch_odds("nfl-sb-2026")
        self.assertIsNotNone(snap)
        self.assertEqual(snap.event_id, "nfl-sb-2026")
        self.assertGreater(len(snap.book_odds), 0)

    def test_synthetic_odds_consensus_prob(self):
        from merid.betting.odds_client import OddsAPIClient
        client = OddsAPIClient()
        snap = client.fetch_odds("nfl-sb-2026")
        # Consensus probs should sum to ~1 after vig removal
        total = sum(snap.consensus_prob.values())
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_synthetic_odds_sharp_prob(self):
        from merid.betting.odds_client import OddsAPIClient
        client = OddsAPIClient()
        snap = client.fetch_odds("nfl-sb-2026")
        # NFL event has pinnacle → sharp probs should exist
        if snap.sharp_prob:
            total = sum(snap.sharp_prob.values())
            self.assertAlmostEqual(total, 1.0, places=2)

    def test_synthetic_odds_best_odds(self):
        from merid.betting.odds_client import OddsAPIClient
        client = OddsAPIClient()
        snap = client.fetch_odds("nba-lal-bos")
        self.assertGreater(len(snap.best_odds), 0)

    def test_fetch_all_odds(self):
        from merid.betting.odds_client import OddsAPIClient
        client = OddsAPIClient()
        results = client.fetch_all_odds()
        self.assertGreater(len(results), 0)
        for ev, snap in results:
            self.assertEqual(ev.id, snap.event_id)

    def test_unknown_event_returns_none(self):
        from merid.betting.odds_client import OddsAPIClient
        client = OddsAPIClient()
        snap = client.fetch_odds("nonexistent-event")
        self.assertIsNone(snap)

    def test_is_configured_false_without_key(self):
        from merid.betting.odds_client import OddsAPIClient
        client = OddsAPIClient(api_key="")
        self.assertFalse(client.is_configured)

    def test_is_configured_true_with_key(self):
        from merid.betting.odds_client import OddsAPIClient
        client = OddsAPIClient(api_key="test-key")
        self.assertTrue(client.is_configured)


# ── §3 BettingStore ───────────────────────────────────────────────────

class TestBettingStore(unittest.TestCase):
    """Test SQLite persistence: events, odds, opinions, plans, settlements."""

    def setUp(self):
        from merid.betting.store import BettingStore
        self.store = BettingStore(db_path=":memory:")

    def _make_event(self, eid="ev-1", sport="nfl", state="pre"):
        from merid.betting.models import BettingEvent, BettingOutcome
        return BettingEvent(
            id=eid, sport=sport, league="NFL", title="Test Game",
            home_team="Home", away_team="Away", state=state,
            outcomes=[
                BettingOutcome(id=f"{eid}-h", name="Home"),
                BettingOutcome(id=f"{eid}-a", name="Away"),
            ],
        )

    def test_upsert_and_get_event(self):
        ev = self._make_event()
        self.store.upsert_event(ev)
        got = self.store.get_event("ev-1")
        self.assertIsNotNone(got)
        self.assertEqual(got.sport, "nfl")
        self.assertEqual(len(got.outcomes), 2)

    def test_list_events(self):
        self.store.upsert_event(self._make_event("ev-1", "nfl"))
        self.store.upsert_event(self._make_event("ev-2", "nba"))
        all_events = self.store.list_events()
        self.assertEqual(len(all_events), 2)
        nba = self.store.list_events(sport="nba")
        self.assertEqual(len(nba), 1)

    def test_event_count(self):
        self.store.upsert_event(self._make_event("ev-1", state="pre"))
        self.store.upsert_event(self._make_event("ev-2", state="live"))
        self.assertEqual(self.store.event_count(), 2)
        self.assertEqual(self.store.event_count(state="live"), 1)

    def test_store_and_get_odds(self):
        from merid.betting.models import OddsSnapshot, BookOdds
        snap = OddsSnapshot(
            event_id="ev-1", market_type="moneyline",
            book_odds=[BookOdds(book="dk", outcome_id="h", american_odds=-110)],
            consensus_prob={"h": 0.52, "a": 0.48},
        )
        self.store.store_odds_snapshot(snap)
        got = self.store.get_latest_odds("ev-1")
        self.assertIsNotNone(got)
        self.assertEqual(got.event_id, "ev-1")
        self.assertAlmostEqual(got.consensus_prob["h"], 0.52)

    def test_add_and_list_swarm_opinions(self):
        oid = self.store.add_swarm_opinion(
            agent_id="agent-1", event_id="ev-1", outcome_id="h",
            probability=0.65, confidence=0.8, reasoning="Strong home team"
        )
        self.assertTrue(len(oid) > 0)
        opinions = self.store.list_swarm_opinions("ev-1")
        self.assertEqual(len(opinions), 1)
        self.assertAlmostEqual(opinions[0]["probability"], 0.65)

    def test_add_and_list_plans(self):
        from merid.betting.models import LiveBetPlan
        plan = LiveBetPlan(event_id="ev-1", outcome_id="h", stake_usd=50)
        self.store.add_plan(plan)
        plans = self.store.list_plans(event_id="ev-1")
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].stake_usd, 50)

    def test_update_plan_status(self):
        from merid.betting.models import LiveBetPlan
        plan = LiveBetPlan(id="plan-1", event_id="ev-1", outcome_id="h")
        self.store.add_plan(plan)
        self.assertTrue(self.store.update_plan_status("plan-1", "approved"))
        plans = self.store.list_plans(status="approved")
        self.assertEqual(len(plans), 1)

    def test_settle_bet(self):
        from merid.betting.models import SettledBet
        sb = SettledBet(bet_id="b1", event_id="ev-1", outcome_id="h",
                        stake_usd=100, placed_odds=2.0, result="won", pnl_usd=100)
        self.store.settle_bet(sb)
        settled = self.store.list_settled()
        self.assertEqual(len(settled), 1)
        self.assertEqual(settled[0].result, "won")

    def test_get_event_missing(self):
        self.assertIsNone(self.store.get_event("nonexistent"))


# ── §4 Consensus aggregator ──────────────────────────────────────────

class TestBettingConsensus(unittest.TestCase):
    """Test consensus building: sportsbook + swarm merge, edges, stance."""

    def setUp(self):
        from merid.betting.store import BettingStore
        self.store = BettingStore(db_path=":memory:")

    def _seed_event_with_odds(self):
        from merid.betting.models import BettingEvent, BettingOutcome, OddsSnapshot, BookOdds
        ev = BettingEvent(
            id="ev-1", sport="nfl", league="NFL", title="Test",
            home_team="Home", away_team="Away",
            outcomes=[
                BettingOutcome(id="ev-1-h", name="Home"),
                BettingOutcome(id="ev-1-a", name="Away"),
            ],
        )
        self.store.upsert_event(ev)
        snap = OddsSnapshot(
            event_id="ev-1", market_type="moneyline",
            book_odds=[
                BookOdds(book="dk", outcome_id="ev-1-h", american_odds=-110),
                BookOdds(book="dk", outcome_id="ev-1-a", american_odds=-110),
            ],
            consensus_prob={"ev-1-h": 0.50, "ev-1-a": 0.50},
        )
        self.store.store_odds_snapshot(snap)
        return ev

    def test_build_consensus_basic(self):
        self._seed_event_with_odds()
        c = self.store.build_consensus("ev-1")
        self.assertIsNotNone(c)
        self.assertEqual(c.event_id, "ev-1")
        self.assertIn("ev-1-h", c.sportsbook_consensus_prob)

    def test_build_consensus_with_swarm(self):
        self._seed_event_with_odds()
        self.store.add_swarm_opinion("agent-1", "ev-1", "ev-1-h", 0.70, 0.9)
        self.store.add_swarm_opinion("agent-2", "ev-1", "ev-1-h", 0.60, 0.7)
        c = self.store.build_consensus("ev-1")
        self.assertGreater(c.swarm_prob.get("ev-1-h", 0), 0.5)
        self.assertEqual(c.swarm_opinion_count, 2)

    def test_build_consensus_edges(self):
        self._seed_event_with_odds()
        self.store.add_swarm_opinion("agent-1", "ev-1", "ev-1-h", 0.65, 0.9)
        c = self.store.build_consensus("ev-1")
        self.assertGreater(c.max_edge, 0)
        self.assertIn(c.stance, ["strong_yes", "weak_yes", "neutral", "weak_no", "strong_no"])

    def test_build_consensus_missing_event(self):
        self.assertIsNone(self.store.build_consensus("nonexistent"))

    def test_build_all_consensus(self):
        self._seed_event_with_odds()
        from merid.betting.models import BettingEvent, BettingOutcome
        ev2 = BettingEvent(
            id="ev-2", sport="nba", league="NBA", title="Test 2",
            outcomes=[BettingOutcome(id="ev-2-h", name="Home"), BettingOutcome(id="ev-2-a", name="Away")],
        )
        self.store.upsert_event(ev2)
        all_c = self.store.build_all_consensus()
        self.assertEqual(len(all_c), 2)

    def test_build_all_consensus_sport_filter(self):
        self._seed_event_with_odds()
        nfl = self.store.build_all_consensus(sport="nfl")
        nba = self.store.build_all_consensus(sport="nba")
        self.assertEqual(len(nfl), 1)
        self.assertEqual(len(nba), 0)

    def test_consensus_to_dict(self):
        self._seed_event_with_odds()
        c = self.store.build_consensus("ev-1")
        d = c.to_dict()
        self.assertIn("event_id", d)
        self.assertIn("sportsbook_consensus_prob", d)
        self.assertIn("stance", d)

    def test_consensus_supporting_opposing(self):
        self._seed_event_with_odds()
        self.store.add_swarm_opinion("agent-1", "ev-1", "ev-1-h", 0.70, 0.9)
        self.store.add_swarm_opinion("agent-2", "ev-1", "ev-1-h", 0.30, 0.5)
        c = self.store.build_consensus("ev-1")
        self.assertEqual(c.swarm_supporting_agents, 1)
        self.assertEqual(c.swarm_opposing_agents, 1)


# ── §5 Plan executability ────────────────────────────────────────────

class TestPlanExecutability(unittest.TestCase):
    """Test edge/latency/state guards for bet plan execution."""

    def setUp(self):
        from merid.betting.store import BettingStore
        self.store = BettingStore(db_path=":memory:")

    def _seed(self):
        from merid.betting.models import BettingEvent, BettingOutcome, OddsSnapshot, BookOdds, LiveBetPlan
        ev = BettingEvent(
            id="ev-1", sport="nfl", title="Test",
            outcomes=[BettingOutcome(id="h", name="Home"), BettingOutcome(id="a", name="Away")],
        )
        self.store.upsert_event(ev)
        snap = OddsSnapshot(
            event_id="ev-1", market_type="moneyline",
            book_odds=[
                BookOdds(book="dk", outcome_id="h", american_odds=-110),
                BookOdds(book="dk", outcome_id="a", american_odds=-110),
            ],
            consensus_prob={"h": 0.50, "a": 0.50},
        )
        self.store.store_odds_snapshot(snap)
        # Add swarm opinion that creates edge
        self.store.add_swarm_opinion("agent-1", "ev-1", "h", 0.65, 0.9)
        return ev

    def test_plan_executable_with_edge(self):
        self._seed()
        from merid.betting.models import LiveBetPlan
        plan = LiveBetPlan(event_id="ev-1", outcome_id="h", min_edge_vs_books=0.03)
        result = self.store.check_plan_executable(plan)
        self.assertTrue(result["executable"])

    def test_plan_not_executable_insufficient_edge(self):
        self._seed()
        from merid.betting.models import LiveBetPlan
        plan = LiveBetPlan(event_id="ev-1", outcome_id="h", min_edge_vs_books=0.50)
        result = self.store.check_plan_executable(plan)
        self.assertFalse(result["executable"])

    def test_plan_not_executable_missing_event(self):
        from merid.betting.models import LiveBetPlan
        plan = LiveBetPlan(event_id="nonexistent", outcome_id="h")
        result = self.store.check_plan_executable(plan)
        self.assertFalse(result["executable"])
        self.assertIn("not found", result["reason"])

    def test_plan_not_executable_final_event(self):
        from merid.betting.models import BettingEvent, BettingOutcome, LiveBetPlan
        ev = BettingEvent(id="fin-1", sport="nfl", title="Final", state="final",
                          outcomes=[BettingOutcome(id="h", name="Home")])
        self.store.upsert_event(ev)
        plan = LiveBetPlan(event_id="fin-1", outcome_id="h")
        result = self.store.check_plan_executable(plan)
        self.assertFalse(result["executable"])
        self.assertIn("final", result["reason"])


# ── §6 Betting metrics ───────────────────────────────────────────────

class TestBettingMetrics(unittest.TestCase):
    """Test win rate, ROI, PnL, plan counts."""

    def setUp(self):
        from merid.betting.store import BettingStore
        self.store = BettingStore(db_path=":memory:")

    def test_empty_metrics(self):
        m = self.store.get_betting_metrics()
        self.assertEqual(m["total_bets"], 0)
        self.assertEqual(m["win_rate"], 0.0)
        self.assertEqual(m["roi"], 0.0)

    def test_metrics_with_settlements(self):
        from merid.betting.models import SettledBet
        self.store.settle_bet(SettledBet(bet_id="b1", event_id="ev-1", outcome_id="h",
                                         stake_usd=100, placed_odds=2.0, result="won", pnl_usd=100))
        self.store.settle_bet(SettledBet(bet_id="b2", event_id="ev-1", outcome_id="a",
                                         stake_usd=100, placed_odds=2.0, result="lost", pnl_usd=-100))
        m = self.store.get_betting_metrics()
        self.assertEqual(m["total_bets"], 2)
        self.assertEqual(m["wins"], 1)
        self.assertEqual(m["losses"], 1)
        self.assertAlmostEqual(m["win_rate"], 0.5)
        self.assertAlmostEqual(m["total_pnl_usd"], 0.0)

    def test_metrics_roi(self):
        from merid.betting.models import SettledBet
        self.store.settle_bet(SettledBet(bet_id="b1", event_id="ev-1", outcome_id="h",
                                         stake_usd=100, placed_odds=3.0, result="won", pnl_usd=200))
        m = self.store.get_betting_metrics()
        self.assertAlmostEqual(m["roi"], 2.0)  # 200/100


# ── §7 API endpoints ─────────────────────────────────────────────────

class TestBettingAPI(unittest.TestCase):
    """Test REST API endpoints via FastAPI TestClient."""

    @classmethod
    def setUpClass(cls):
        from merid.betting.store import BettingStore
        cls.store = BettingStore(db_path=":memory:")

    def _get_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from web.api.betting_consensus_api import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    @patch("web.api.betting_consensus_api._get_store")
    @patch("web.api.betting_consensus_api._get_odds_client")
    def test_summary_stub_fallback(self, mock_client, mock_store):
        mock_store.return_value = None
        mock_client.return_value = None
        client = self._get_client()
        resp = client.get("/api/v1/betting/consensus/summary")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("events", data)
        self.assertTrue(data.get("_stub"))

    @patch("web.api.betting_consensus_api._get_store")
    def test_summary_with_store(self, mock_store):
        mock_store.return_value = self.store
        # Seed an event
        from merid.betting.models import BettingEvent, BettingOutcome
        ev = BettingEvent(
            id="api-ev-1", sport="nfl", title="API Test",
            outcomes=[BettingOutcome(id="h", name="Home"), BettingOutcome(id="a", name="Away")],
        )
        self.store.upsert_event(ev)

        # Patch _ensure_events_seeded to not re-seed
        import web.api.betting_consensus_api as api_mod
        api_mod._seeded = True

        client = self._get_client()
        resp = client.get("/api/v1/betting/consensus/summary")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreater(data["count"], 0)

    @patch("web.api.betting_consensus_api._get_store")
    def test_live_consensus_not_found(self, mock_store):
        from merid.betting.store import BettingStore
        mock_store.return_value = BettingStore(db_path=":memory:")
        client = self._get_client()
        resp = client.get("/api/v1/betting/consensus/live/nonexistent")
        self.assertEqual(resp.status_code, 404)

    @patch("web.api.betting_consensus_api._get_store")
    def test_metrics_stub(self, mock_store):
        mock_store.return_value = None
        client = self._get_client()
        resp = client.get("/api/v1/betting/consensus/metrics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("_stub"))

    @patch("web.api.betting_consensus_api._get_store")
    def test_submit_opinion(self, mock_store):
        mock_store.return_value = self.store
        client = self._get_client()
        resp = client.post("/api/v1/betting/consensus/opinion", json={
            "agent_id": "agent-1", "event_id": "ev-1",
            "outcome_id": "h", "probability": 0.65,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    @patch("web.api.betting_consensus_api._get_store")
    def test_submit_opinion_invalid_prob(self, mock_store):
        mock_store.return_value = self.store
        client = self._get_client()
        resp = client.post("/api/v1/betting/consensus/opinion", json={
            "agent_id": "agent-1", "event_id": "ev-1",
            "outcome_id": "h", "probability": 1.5,
        })
        self.assertEqual(resp.status_code, 400)

    @patch("web.api.betting_consensus_api._get_store")
    def test_submit_plan(self, mock_store):
        mock_store.return_value = self.store
        client = self._get_client()
        resp = client.post("/api/v1/betting/consensus/plan", json={
            "event_id": "ev-1", "outcome_id": "h",
            "outcome_name": "Home", "stake_usd": 50,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("plan", resp.json())

    @patch("web.api.betting_consensus_api._get_store")
    def test_plans_list(self, mock_store):
        mock_store.return_value = self.store
        client = self._get_client()
        resp = client.get("/api/v1/betting/consensus/plans")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("plans", resp.json())

    @patch("web.api.betting_consensus_api._get_store")
    def test_settle_bet_endpoint(self, mock_store):
        mock_store.return_value = self.store
        client = self._get_client()
        resp = client.post("/api/v1/betting/consensus/settle", json={
            "bet_id": "b99", "event_id": "ev-1", "outcome_id": "h",
            "stake_usd": 100, "placed_odds": 2.0,
            "result": "won", "pnl_usd": 100,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    @patch("web.api.betting_consensus_api._get_store")
    def test_settle_bet_invalid_result(self, mock_store):
        mock_store.return_value = self.store
        client = self._get_client()
        resp = client.post("/api/v1/betting/consensus/settle", json={
            "bet_id": "b-bad", "event_id": "ev-1", "outcome_id": "h",
            "stake_usd": 100, "placed_odds": 2.0,
            "result": "invalid", "pnl_usd": 0,
        })
        self.assertEqual(resp.status_code, 400)

    @patch("web.api.betting_consensus_api._get_store")
    @patch("web.api.betting_consensus_api._get_odds_client")
    def test_ingest_endpoint(self, mock_client, mock_store):
        from merid.betting.odds_client import OddsAPIClient
        mock_store.return_value = self.store
        mock_client.return_value = OddsAPIClient()  # synthetic
        client = self._get_client()
        resp = client.post("/api/v1/betting/consensus/ingest")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["source"], "synthetic")
        self.assertGreater(data["events_ingested"], 0)


# ── §8 Odds computation helper ───────────────────────────────────────

class TestOddsComputation(unittest.TestCase):
    """Test _compute_consensus and related helpers."""

    def test_compute_consensus_basic(self):
        from merid.betting.odds_client import _compute_consensus
        from merid.betting.models import BookOdds
        odds = [
            BookOdds(book="dk", outcome_id="h", american_odds=-110),
            BookOdds(book="dk", outcome_id="a", american_odds=-110),
            BookOdds(book="fd", outcome_id="h", american_odds=-105),
            BookOdds(book="fd", outcome_id="a", american_odds=-115),
        ]
        consensus, sharp, best = _compute_consensus(odds, ["h", "a"])
        self.assertAlmostEqual(sum(consensus.values()), 1.0, places=2)
        self.assertIn("h", best)
        self.assertIn("a", best)

    def test_compute_consensus_with_sharp(self):
        from merid.betting.odds_client import _compute_consensus
        from merid.betting.models import BookOdds
        odds = [
            BookOdds(book="pinnacle", outcome_id="h", american_odds=-104),
            BookOdds(book="pinnacle", outcome_id="a", american_odds=-106),
            BookOdds(book="draftkings", outcome_id="h", american_odds=-110),
            BookOdds(book="draftkings", outcome_id="a", american_odds=-110),
        ]
        consensus, sharp, best = _compute_consensus(odds, ["h", "a"])
        # Sharp probs should exist (Pinnacle)
        self.assertIn("h", sharp)
        self.assertAlmostEqual(sum(sharp.values()), 1.0, places=2)


if __name__ == "__main__":
    unittest.main()
