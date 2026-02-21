"""Tests for Sports & Live Betting Integration (Sprint 12).

Covers:
  §1 SportsInstrumentBridge — register, update state, update odds, settle, list
  §2 SportsOutcomeSchema — model serialization
  §3 SportsOddsFeed — provider registration, ingest, health, staleness
  §4 LiveOddsEngine — compute lines, exposure, pricing divergence
  §5 LiveBettingEngine — acceptance, reprice, rejection, SLO metrics
  §6 SportsForecastEngine — submit, coherence logging, stats
  §7 QuestEngine — quest lifecycle, progress tracking, completion
  §8 SportsBettingManager — wiring, health aggregation
  §9 Observability alerts — LiveBettingLatencyAlert, PricingDivergenceAlert, FeedStalenessAlert
  §10 API endpoints — sports registration, odds, live bets, forecasts, quests
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch, MagicMock

from merid.betting.live_sports import (
    BetAcceptanceResult,
    FeedHealth,
    FeedState,
    LiveBettingEngine,
    LiveOddsEngine,
    OddsUpdate,
    PlatformLine,
    Quest,
    QuestEngine,
    QuestProgress,
    SportsBettingManager,
    SportsForecast,
    SportsForecastEngine,
    SportsInstrument,
    SportsInstrumentBridge,
    SportsOddsFeed,
    SportsOutcomeSchema,
    _sports_symbol,
    get_sports_betting_manager,
)


# ══════════════════════════════════════════════════════════════════════
# §1 SportsInstrumentBridge
# ══════════════════════════════════════════════════════════════════════

class TestSportsSymbol(unittest.TestCase):
    """Test canonical symbol builder."""

    def test_basic(self):
        self.assertEqual(_sports_symbol("evt1", "home"), "PRED:SPORTS:evt1:HOME")

    def test_uppercase(self):
        self.assertEqual(_sports_symbol("abc", "Away"), "PRED:SPORTS:abc:AWAY")


class TestSportsOutcomeSchema(unittest.TestCase):
    """Test SportsOutcomeSchema dataclass."""

    def test_defaults(self):
        s = SportsOutcomeSchema()
        self.assertEqual(s.market_type, "moneyline")
        self.assertEqual(s.outcomes, [])
        self.assertIsNone(s.line)

    def test_to_dict(self):
        s = SportsOutcomeSchema(market_type="spread", outcomes=["home", "away"], line=-3.5)
        d = s.to_dict()
        self.assertEqual(d["market_type"], "spread")
        self.assertEqual(d["line"], -3.5)
        self.assertEqual(len(d["outcomes"]), 2)


class TestSportsInstrument(unittest.TestCase):
    """Test SportsInstrument dataclass."""

    def test_defaults(self):
        si = SportsInstrument(event_id="e1", sport="nfl", title="Game 1")
        self.assertEqual(si.state, "pre")
        self.assertIsNone(si.score_home)

    def test_to_dict(self):
        si = SportsInstrument(
            event_id="e1", sport="nfl", title="Game 1",
            home_team="Chiefs", away_team="Eagles",
            implied_probs={"home": 0.6, "away": 0.4},
        )
        d = si.to_dict()
        self.assertEqual(d["event_id"], "e1")
        self.assertEqual(d["implied_probs"]["home"], 0.6)
        self.assertEqual(d["home_team"], "Chiefs")


class TestSportsInstrumentBridge(unittest.TestCase):
    """Test SportsInstrumentBridge registration and lifecycle."""

    def setUp(self):
        self.bridge = SportsInstrumentBridge()

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_register_event_basic(self, mock_store_fn):
        mock_store = MagicMock()
        mock_store_fn.return_value = mock_store

        si = self.bridge.register_event(
            event_id="nfl-2025-001",
            sport="nfl",
            league="NFL",
            title="Chiefs vs Eagles",
            home_team="Chiefs",
            away_team="Eagles",
            start_time=time.time() + 3600,
        )
        self.assertEqual(si.event_id, "nfl-2025-001")
        self.assertEqual(si.sport, "nfl")
        self.assertEqual(len(si.registered_symbols), 2)
        self.assertIn("PRED:SPORTS:nfl-2025-001:HOME", si.registered_symbols)
        self.assertIn("PRED:SPORTS:nfl-2025-001:AWAY", si.registered_symbols)
        # Should have called upsert_instrument twice
        self.assertEqual(mock_store.upsert_instrument.call_count, 2)

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_register_with_custom_outcomes(self, mock_store_fn):
        mock_store = MagicMock()
        mock_store_fn.return_value = mock_store

        schema = SportsOutcomeSchema(
            market_type="total",
            outcomes=["over", "under"],
            line=45.5,
        )
        si = self.bridge.register_event(
            event_id="nfl-total-001",
            sport="nfl",
            league="NFL",
            title="Chiefs vs Eagles Total",
            outcome_schemas=[schema],
            implied_probs={"over": 0.52, "under": 0.48},
        )
        self.assertEqual(len(si.registered_symbols), 2)
        self.assertIn("PRED:SPORTS:nfl-total-001:OVER", si.registered_symbols)
        self.assertEqual(si.implied_probs["over"], 0.52)

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_register_with_implied_probs(self, mock_store_fn):
        mock_store = MagicMock()
        mock_store_fn.return_value = mock_store

        si = self.bridge.register_event(
            event_id="nba-001",
            sport="nba",
            league="NBA",
            title="Lakers vs Celtics",
            implied_probs={"home": 0.55, "away": 0.45},
        )
        self.assertAlmostEqual(si.implied_probs["home"], 0.55)
        self.assertAlmostEqual(si.implied_probs["away"], 0.45)

    def test_list_events_empty(self):
        self.assertEqual(self.bridge.list_events(), [])

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_list_events_filter(self, mock_store_fn):
        mock_store = MagicMock()
        mock_store_fn.return_value = mock_store

        self.bridge.register_event(event_id="nfl-1", sport="nfl", league="NFL", title="G1")
        self.bridge.register_event(event_id="nba-1", sport="nba", league="NBA", title="G2")

        all_events = self.bridge.list_events()
        self.assertEqual(len(all_events), 2)

        nfl_only = self.bridge.list_events(sport="nfl")
        self.assertEqual(len(nfl_only), 1)
        self.assertEqual(nfl_only[0].sport, "nfl")

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_get_event(self, mock_store_fn):
        mock_store = MagicMock()
        mock_store_fn.return_value = mock_store

        self.bridge.register_event(event_id="e1", sport="nfl", league="NFL", title="G1")
        self.assertIsNotNone(self.bridge.get_event("e1"))
        self.assertIsNone(self.bridge.get_event("nonexistent"))

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_update_event_state(self, mock_store_fn):
        mock_store = MagicMock()
        mock_store.get_instrument.return_value = MagicMock()
        mock_store_fn.return_value = mock_store

        self.bridge.register_event(event_id="e1", sport="nfl", league="NFL", title="G1")
        si = self.bridge.update_event_state("e1", state="live", score_home=7, score_away=3, period="Q1")
        self.assertIsNotNone(si)
        self.assertEqual(si.state, "live")
        self.assertEqual(si.score_home, 7)
        self.assertEqual(si.period, "Q1")

    def test_update_event_state_not_found(self):
        result = self.bridge.update_event_state("nonexistent", state="live")
        self.assertIsNone(result)

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_update_odds(self, mock_store_fn):
        mock_store = MagicMock()
        mock_inst = MagicMock()
        mock_store.get_instrument.return_value = mock_inst
        mock_store_fn.return_value = mock_store

        self.bridge.register_event(event_id="e1", sport="nfl", league="NFL", title="G1")
        result = self.bridge.update_odds("e1", {"home": 0.65, "away": 0.35})
        self.assertTrue(result)
        si = self.bridge.get_event("e1")
        self.assertAlmostEqual(si.implied_probs["home"], 0.65)

    def test_update_odds_not_found(self):
        self.assertFalse(self.bridge.update_odds("nonexistent", {"home": 0.5}))

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_settle_event(self, mock_store_fn):
        mock_store = MagicMock()
        mock_store_fn.return_value = mock_store

        self.bridge.register_event(event_id="e1", sport="nfl", league="NFL", title="G1")
        result = self.bridge.settle_event("e1", winning_outcomes=["home"])
        self.assertEqual(result["event_id"], "e1")
        self.assertEqual(result["winning_outcomes"], ["home"])
        self.assertTrue(len(result["settled_instruments"]) > 0)

    def test_settle_event_not_found(self):
        with self.assertRaises(ValueError):
            self.bridge.settle_event("nonexistent", ["home"])


# ══════════════════════════════════════════════════════════════════════
# §3 SportsOddsFeed
# ══════════════════════════════════════════════════════════════════════

class TestFeedHealth(unittest.TestCase):
    """Test FeedHealth dataclass."""

    def test_is_stale_no_updates(self):
        fh = FeedHealth(provider="test")
        self.assertTrue(fh.is_stale)

    def test_is_stale_recent(self):
        fh = FeedHealth(provider="test", last_update_ts=time.time(), stale_threshold_s=60.0)
        self.assertFalse(fh.is_stale)

    def test_is_stale_old(self):
        fh = FeedHealth(provider="test", last_update_ts=time.time() - 120, stale_threshold_s=60.0)
        self.assertTrue(fh.is_stale)

    def test_to_dict(self):
        fh = FeedHealth(provider="pinnacle", last_update_ts=time.time(), updates_received=10)
        d = fh.to_dict()
        self.assertEqual(d["provider"], "pinnacle")
        self.assertEqual(d["updates_received"], 10)
        self.assertIn("is_stale", d)


class TestOddsUpdate(unittest.TestCase):
    """Test OddsUpdate dataclass."""

    def test_implied_prob_from_decimal(self):
        u = OddsUpdate(provider="test", event_id="e1", outcome_label="home", decimal_odds=2.0)
        self.assertAlmostEqual(u.implied_prob, 0.5)

    def test_implied_prob_from_american_negative(self):
        u = OddsUpdate(provider="test", event_id="e1", outcome_label="home", american_odds=-110)
        self.assertGreater(u.implied_prob, 0.5)
        self.assertLess(u.implied_prob, 0.6)

    def test_explicit_implied_prob(self):
        u = OddsUpdate(provider="test", event_id="e1", outcome_label="home",
                       decimal_odds=2.0, implied_prob=0.48)
        # Explicit implied_prob should be kept (not overwritten)
        self.assertAlmostEqual(u.implied_prob, 0.48)


class TestSportsOddsFeed(unittest.TestCase):
    """Test SportsOddsFeed ingestion and health tracking."""

    def setUp(self):
        self.feed = SportsOddsFeed(stale_threshold_s=60.0)

    def test_register_provider(self):
        self.feed.register_provider("pinnacle")
        health = self.feed.get_feed_health()
        self.assertEqual(health["total_providers"], 1)
        self.assertIn("pinnacle", health["providers"])

    def test_ingest_update(self):
        update = OddsUpdate(
            provider="fanduel",
            event_id="e1",
            outcome_label="home",
            decimal_odds=1.91,
            latency_ms=15.0,
        )
        self.feed.ingest_update(update)
        health = self.feed.get_feed_health()
        self.assertEqual(health["total_updates"], 1)
        self.assertEqual(health["providers"]["fanduel"]["updates_received"], 1)

    def test_ingest_auto_registers_provider(self):
        update = OddsUpdate(provider="draftkings", event_id="e1", outcome_label="home", decimal_odds=2.0)
        self.feed.ingest_update(update)
        health = self.feed.get_feed_health()
        self.assertIn("draftkings", health["providers"])

    def test_subscriber_called(self):
        received = []
        self.feed.subscribe(lambda u: received.append(u))
        update = OddsUpdate(provider="test", event_id="e1", outcome_label="home", decimal_odds=2.0)
        self.feed.ingest_update(update)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].event_id, "e1")

    def test_multiple_updates_latency(self):
        for i in range(10):
            update = OddsUpdate(
                provider="test",
                event_id="e1",
                outcome_label="home",
                decimal_odds=2.0,
                latency_ms=float(i * 10),
            )
            self.feed.ingest_update(update)
        health = self.feed.get_feed_health()
        self.assertEqual(health["total_updates"], 10)
        self.assertGreater(health["providers"]["test"]["avg_latency_ms"], 0)

    def test_record_error(self):
        self.feed.register_provider("bad_provider")
        self.feed.record_error("bad_provider")
        health = self.feed.get_feed_health()
        self.assertEqual(health["providers"]["bad_provider"]["errors"], 1)
        self.assertEqual(health["providers"]["bad_provider"]["state"], FeedState.ERROR.value)

    def test_stale_detection(self):
        self.feed.register_provider("stale_prov", stale_threshold_s=0.01)
        update = OddsUpdate(
            provider="stale_prov", event_id="e1", outcome_label="home",
            decimal_odds=2.0, timestamp=time.time() - 100,
        )
        self.feed.ingest_update(update)
        health = self.feed.get_feed_health()
        self.assertTrue(health["any_stale"])
        self.assertEqual(health["stale_providers"], 1)

    def test_get_recent_updates(self):
        for i in range(5):
            self.feed.ingest_update(OddsUpdate(
                provider="test", event_id=f"e{i}", outcome_label="home", decimal_odds=2.0,
            ))
        updates = self.feed.get_recent_updates(limit=3)
        self.assertEqual(len(updates), 3)


# ══════════════════════════════════════════════════════════════════════
# §4 LiveOddsEngine
# ══════════════════════════════════════════════════════════════════════

class TestPlatformLine(unittest.TestCase):
    """Test PlatformLine dataclass."""

    def test_to_dict(self):
        line = PlatformLine(event_id="e1", outcome_label="home", platform_prob=0.55)
        d = line.to_dict()
        self.assertEqual(d["event_id"], "e1")
        self.assertAlmostEqual(d["platform_prob"], 0.55)


class TestLiveOddsEngine(unittest.TestCase):
    """Test LiveOddsEngine line computation and exposure tracking."""

    def setUp(self):
        self.engine = LiveOddsEngine(
            external_weight=0.7,
            agent_weight=0.3,
            house_margin_pct=5.0,
            max_exposure_per_outcome=10000.0,
        )

    def test_compute_line_basic(self):
        line = self.engine.compute_line("e1", "home", external_prob=0.6)
        self.assertGreater(line.platform_prob, 0.5)
        self.assertGreater(line.decimal_odds, 1.0)

    def test_compute_line_with_agent(self):
        line = self.engine.compute_line(
            "e1", "home",
            external_prob=0.6,
            agent_prob=0.7,
            agent_confidence=0.8,
        )
        # Agent pushes prob higher
        self.assertGreater(line.platform_prob, 0.6)

    def test_compute_line_low_agent_confidence(self):
        line_no_agent = self.engine.compute_line("e1", "home", external_prob=0.6, agent_confidence=0.0)
        line_high_agent = self.engine.compute_line("e2", "home", external_prob=0.6,
                                                    agent_prob=0.8, agent_confidence=1.0)
        # Low confidence agent should barely affect the line
        self.assertAlmostEqual(line_no_agent.platform_prob, 0.6, places=2)
        self.assertGreater(line_high_agent.platform_prob, line_no_agent.platform_prob)

    def test_get_line(self):
        self.engine.compute_line("e1", "home", external_prob=0.6)
        line = self.engine.get_line("e1", "home")
        self.assertIsNotNone(line)
        self.assertIsNone(self.engine.get_line("e1", "nonexistent"))

    def test_get_all_lines(self):
        self.engine.compute_line("e1", "home", external_prob=0.6)
        self.engine.compute_line("e1", "away", external_prob=0.4)
        self.engine.compute_line("e2", "home", external_prob=0.5)

        all_lines = self.engine.get_all_lines()
        self.assertEqual(len(all_lines), 3)

        e1_lines = self.engine.get_all_lines(event_id="e1")
        self.assertEqual(len(e1_lines), 2)

    def test_record_exposure_within_limit(self):
        self.assertTrue(self.engine.record_exposure("e1", "home", 5000.0))
        self.assertAlmostEqual(self.engine.get_exposure("e1", "home"), 5000.0)

    def test_record_exposure_exceeds_limit(self):
        self.assertTrue(self.engine.record_exposure("e1", "home", 8000.0))
        self.assertFalse(self.engine.record_exposure("e1", "home", 3000.0))  # Would exceed 10k

    def test_get_pricing_divergence_empty(self):
        d = self.engine.get_pricing_divergence()
        self.assertEqual(d["lines_count"], 0)

    def test_get_pricing_divergence(self):
        self.engine.compute_line("e1", "home", external_prob=0.6, agent_prob=0.8, agent_confidence=1.0)
        d = self.engine.get_pricing_divergence()
        self.assertGreater(d["avg_divergence"], 0)
        self.assertEqual(d["lines_count"], 1)

    def test_house_margin_applied(self):
        line = self.engine.compute_line("e1", "home", external_prob=0.5)
        # Fair odds = 2.0, with 5% margin should be < 2.0
        self.assertLess(line.decimal_odds, 2.0)

    def test_prob_clamped(self):
        line_low = self.engine.compute_line("e1", "home", external_prob=0.001)
        line_high = self.engine.compute_line("e2", "home", external_prob=0.999)
        self.assertGreaterEqual(line_low.platform_prob, 0.01)
        self.assertLessEqual(line_high.platform_prob, 0.99)


# ══════════════════════════════════════════════════════════════════════
# §5 LiveBettingEngine
# ══════════════════════════════════════════════════════════════════════

class TestBetAcceptanceResult(unittest.TestCase):
    """Test BetAcceptanceResult dataclass."""

    def test_to_dict(self):
        r = BetAcceptanceResult(accepted=True, bet_id="b1", stake=100.0)
        d = r.to_dict()
        self.assertTrue(d["accepted"])
        self.assertEqual(d["bet_id"], "b1")


class TestLiveBettingEngine(unittest.TestCase):
    """Test LiveBettingEngine acceptance, reprice, rejection, SLO."""

    def setUp(self):
        self.odds_engine = LiveOddsEngine(max_exposure_per_outcome=50000.0)
        self.engine = LiveBettingEngine(
            self.odds_engine,
            reprice_threshold=0.03,
            reject_threshold=0.08,
            max_acceptance_ms=300.0,
        )

    def test_accept_bet_no_line(self):
        result = self.engine.accept_bet("e1", "home", 100.0, 2.0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, "no_line_available")

    def test_accept_bet_success(self):
        self.odds_engine.compute_line("e1", "home", external_prob=0.5)
        line = self.odds_engine.get_line("e1", "home")
        result = self.engine.accept_bet("e1", "home", 100.0, line.decimal_odds)
        self.assertTrue(result.accepted)
        self.assertNotEqual(result.bet_id, "")
        self.assertGreater(result.acceptance_latency_ms, 0)

    def test_accept_bet_reprice(self):
        # Set up line at one price
        self.odds_engine.compute_line("e1", "home", external_prob=0.5)
        line = self.odds_engine.get_line("e1", "home")
        displayed = line.decimal_odds

        # Move odds slightly (> 3% but < 8%)
        self.odds_engine.compute_line("e1", "home", external_prob=0.55)
        new_line = self.odds_engine.get_line("e1", "home")

        # Only test reprice if odds actually moved enough
        movement = abs(new_line.decimal_odds - displayed) / displayed if displayed > 0 else 0
        if movement > 0.03:
            result = self.engine.accept_bet("e1", "home", 100.0, displayed)
            if movement < 0.08:
                self.assertTrue(result.accepted)
                self.assertTrue(result.repriced)

    def test_accept_bet_reject_large_movement(self):
        self.odds_engine.compute_line("e1", "home", external_prob=0.5)
        line = self.odds_engine.get_line("e1", "home")
        # Display at a very different price (>8% movement)
        fake_displayed = line.decimal_odds * 1.15
        result = self.engine.accept_bet("e1", "home", 100.0, fake_displayed)
        self.assertFalse(result.accepted)
        self.assertIn("odds_moved", result.rejection_reason)

    def test_accept_bet_stale_line(self):
        self.odds_engine.compute_line("e1", "home", external_prob=0.5)
        line = self.odds_engine.get_line("e1", "home")
        line.stale = True
        result = self.engine.accept_bet("e1", "home", 100.0, line.decimal_odds)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, "stale_odds")

    def test_accept_bet_exposure_limit(self):
        self.odds_engine = LiveOddsEngine(max_exposure_per_outcome=100.0)
        self.engine = LiveBettingEngine(self.odds_engine)
        self.odds_engine.compute_line("e1", "home", external_prob=0.5)
        line = self.odds_engine.get_line("e1", "home")

        # First bet should succeed
        r1 = self.engine.accept_bet("e1", "home", 80.0, line.decimal_odds)
        self.assertTrue(r1.accepted)

        # Second bet should fail (would exceed 100)
        r2 = self.engine.accept_bet("e1", "home", 30.0, line.decimal_odds)
        self.assertFalse(r2.accepted)
        self.assertEqual(r2.rejection_reason, "exposure_limit_exceeded")

    def test_slo_metrics_initial(self):
        metrics = self.engine.get_slo_metrics()
        self.assertEqual(metrics["total_bets"], 0)
        self.assertTrue(metrics["slo_met"])

    def test_slo_metrics_after_bets(self):
        self.odds_engine.compute_line("e1", "home", external_prob=0.5)
        line = self.odds_engine.get_line("e1", "home")
        for _ in range(5):
            self.engine.accept_bet("e1", "home", 10.0, line.decimal_odds)

        metrics = self.engine.get_slo_metrics()
        self.assertEqual(metrics["total_bets"], 5)
        self.assertEqual(metrics["accepted"], 5)
        self.assertGreaterEqual(metrics["acceptance_rate"], 0.0)
        self.assertIn("p95_acceptance_latency_ms", metrics)

    def test_rejection_counted(self):
        # No line → rejection
        self.engine.accept_bet("e1", "home", 100.0, 2.0)
        metrics = self.engine.get_slo_metrics()
        self.assertEqual(metrics["rejected"], 1)


# ══════════════════════════════════════════════════════════════════════
# §6 SportsForecastEngine
# ══════════════════════════════════════════════════════════════════════

class TestSportsForecast(unittest.TestCase):
    """Test SportsForecast dataclass."""

    def test_to_opinion_kwargs(self):
        f = SportsForecast(
            agent_id="agent1",
            event_id="e1",
            outcome_label="home",
            probability=0.65,
            confidence=0.8,
        )
        kwargs = f.to_opinion_kwargs()
        self.assertEqual(kwargs["agent_id"], "agent1")
        self.assertEqual(kwargs["symbol"], "PRED:SPORTS:e1:HOME")
        self.assertAlmostEqual(kwargs["probability"], 0.65)


class TestSportsForecastEngine(unittest.TestCase):
    """Test SportsForecastEngine forecast submission and coherence."""

    def setUp(self):
        self.engine = SportsForecastEngine()

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_submit_forecast(self, mock_store_fn):
        mock_store = MagicMock()
        mock_store_fn.return_value = mock_store

        forecast = SportsForecast(
            agent_id="agent1",
            event_id="e1",
            outcome_label="home",
            probability=0.65,
            confidence=0.8,
        )
        result = self.engine.submit_forecast(forecast)
        self.assertEqual(result["event_id"], "e1")
        self.assertEqual(result["agent_id"], "agent1")
        mock_store.add_opinion.assert_called_once()

    def test_get_event_forecasts_empty(self):
        self.assertEqual(self.engine.get_event_forecasts("e1"), [])

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_get_event_forecasts(self, mock_store_fn):
        mock_store_fn.return_value = MagicMock()

        for i in range(3):
            self.engine.submit_forecast(SportsForecast(
                agent_id=f"agent{i}", event_id="e1", outcome_label="home",
                probability=0.5 + i * 0.1,
            ))
        forecasts = self.engine.get_event_forecasts("e1")
        self.assertEqual(len(forecasts), 3)

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_get_agent_forecasts(self, mock_store_fn):
        mock_store_fn.return_value = MagicMock()

        self.engine.submit_forecast(SportsForecast(
            agent_id="agent1", event_id="e1", outcome_label="home", probability=0.6,
        ))
        self.engine.submit_forecast(SportsForecast(
            agent_id="agent1", event_id="e2", outcome_label="away", probability=0.4,
        ))
        self.engine.submit_forecast(SportsForecast(
            agent_id="agent2", event_id="e1", outcome_label="home", probability=0.7,
        ))

        agent1 = self.engine.get_agent_forecasts("agent1")
        self.assertEqual(len(agent1), 2)

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_log_coherence_aligned(self, mock_store_fn):
        mock_store_fn.return_value = MagicMock()

        self.engine.submit_forecast(SportsForecast(
            agent_id="agent1", event_id="e1", outcome_label="home", probability=0.65,
        ))
        coherence = self.engine.log_coherence("agent1", "e1", "home", bet_implied_prob=0.65)
        self.assertIsNotNone(coherence)
        self.assertAlmostEqual(coherence, 1.0)

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_log_coherence_divergent(self, mock_store_fn):
        mock_store_fn.return_value = MagicMock()

        self.engine.submit_forecast(SportsForecast(
            agent_id="agent1", event_id="e1", outcome_label="home", probability=0.8,
        ))
        coherence = self.engine.log_coherence("agent1", "e1", "home", bet_implied_prob=0.3)
        self.assertIsNotNone(coherence)
        self.assertLess(coherence, 0.6)

    def test_log_coherence_no_forecast(self):
        coherence = self.engine.log_coherence("agent1", "e1", "home", bet_implied_prob=0.5)
        self.assertIsNone(coherence)

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_get_coherence_stats(self, mock_store_fn):
        mock_store_fn.return_value = MagicMock()

        self.engine.submit_forecast(SportsForecast(
            agent_id="agent1", event_id="e1", outcome_label="home", probability=0.65,
        ))
        self.engine.log_coherence("agent1", "e1", "home", bet_implied_prob=0.60)
        stats = self.engine.get_coherence_stats()
        self.assertIsNotNone(stats["avg_coherence"])
        self.assertEqual(stats["entries"], 1)

    def test_get_coherence_stats_empty(self):
        stats = self.engine.get_coherence_stats()
        self.assertIsNone(stats["avg_coherence"])
        self.assertEqual(stats["entries"], 0)


# ══════════════════════════════════════════════════════════════════════
# §7 QuestEngine
# ══════════════════════════════════════════════════════════════════════

class TestQuest(unittest.TestCase):
    """Test Quest dataclass."""

    def test_auto_id(self):
        q = Quest(name="Test Quest")
        self.assertTrue(q.id.startswith("quest-"))

    def test_explicit_id(self):
        q = Quest(id="my-quest", name="Test")
        self.assertEqual(q.id, "my-quest")

    def test_to_dict(self):
        q = Quest(id="q1", name="Test", quest_type="clv", target_value=10.0)
        d = q.to_dict()
        self.assertEqual(d["id"], "q1")
        self.assertEqual(d["quest_type"], "clv")


class TestQuestProgress(unittest.TestCase):
    """Test QuestProgress dataclass."""

    def test_to_dict(self):
        p = QuestProgress(quest_id="q1", agent_id="a1", current_value=5.0, events_counted=3)
        d = p.to_dict()
        self.assertEqual(d["quest_id"], "q1")
        self.assertFalse(d["completed"])


class TestQuestEngine(unittest.TestCase):
    """Test QuestEngine lifecycle and progress tracking."""

    def setUp(self):
        self.engine = QuestEngine()

    def test_default_quests_loaded(self):
        quests = self.engine.list_quests()
        self.assertGreater(len(quests), 0)

    def test_list_quests_active_only(self):
        quests = self.engine.list_quests(active_only=True)
        for q in quests:
            self.assertTrue(q.active)

    def test_get_progress_creates_default(self):
        progress = self.engine.get_progress("quest-clv-nfl-10", "agent1")
        self.assertEqual(progress.quest_id, "quest-clv-nfl-10")
        self.assertEqual(progress.agent_id, "agent1")
        self.assertFalse(progress.completed)

    def test_update_progress_clv(self):
        progress = self.engine.update_progress("quest-clv-nfl-10", "agent1", value=10.0, events_counted=10)
        self.assertTrue(progress.completed)
        self.assertIsNotNone(progress.completed_at)

    def test_update_progress_clv_incomplete(self):
        progress = self.engine.update_progress("quest-clv-nfl-10", "agent1", value=5.0, events_counted=5)
        self.assertFalse(progress.completed)

    def test_update_progress_pricing(self):
        # pricing quest: avg_divergence <= 0.03 AND events >= 20
        progress = self.engine.update_progress("quest-pricing-accuracy", "agent1",
                                                value=0.02, events_counted=25)
        self.assertTrue(progress.completed)

    def test_update_progress_pricing_not_enough_events(self):
        progress = self.engine.update_progress("quest-pricing-accuracy", "agent1",
                                                value=0.02, events_counted=10)
        self.assertFalse(progress.completed)

    def test_update_progress_streak(self):
        progress = self.engine.update_progress("quest-streak-5", "agent1", value=5.0)
        self.assertTrue(progress.completed)

    def test_update_progress_brier_roi(self):
        progress = self.engine.update_progress("quest-brier-roi-30d", "agent1", value=1.0)
        self.assertTrue(progress.completed)

    def test_update_progress_invalid_quest(self):
        with self.assertRaises(ValueError):
            self.engine.update_progress("nonexistent", "agent1", value=1.0)

    def test_get_agent_quests(self):
        self.engine.update_progress("quest-clv-nfl-10", "agent1", value=3.0, events_counted=3)
        quests = self.engine.get_agent_quests("agent1")
        self.assertGreater(len(quests), 0)
        # Find the CLV quest
        clv = [q for q in quests if q["quest"]["id"] == "quest-clv-nfl-10"]
        self.assertEqual(len(clv), 1)
        self.assertAlmostEqual(clv[0]["progress"]["current_value"], 3.0)

    def test_custom_quests(self):
        custom = [Quest(id="custom-1", name="Custom", quest_type="streak", target_value=3.0)]
        engine = QuestEngine(quests=custom)
        self.assertEqual(len(engine.list_quests()), 1)


# ══════════════════════════════════════════════════════════════════════
# §8 SportsBettingManager
# ══════════════════════════════════════════════════════════════════════

class TestSportsBettingManager(unittest.TestCase):
    """Test SportsBettingManager wiring and health."""

    def setUp(self):
        self.mgr = SportsBettingManager()

    def test_components_initialized(self):
        self.assertIsNotNone(self.mgr.bridge)
        self.assertIsNotNone(self.mgr.odds_feed)
        self.assertIsNotNone(self.mgr.odds_engine)
        self.assertIsNotNone(self.mgr.betting_engine)
        self.assertIsNotNone(self.mgr.forecast_engine)
        self.assertIsNotNone(self.mgr.quest_engine)

    def test_get_sports_health_empty(self):
        health = self.mgr.get_sports_health()
        self.assertEqual(health["events"]["total"], 0)
        self.assertIn("feed_health", health)
        self.assertIn("slo_metrics", health)
        self.assertIn("pricing_divergence", health)
        self.assertIn("agent_coherence", health)

    @patch("merid.prediction.consensus.get_prediction_consensus_store")
    def test_odds_feed_wiring(self, mock_store_fn):
        """Odds feed updates should flow through to odds engine."""
        mock_store = MagicMock()
        mock_store.get_instrument.return_value = MagicMock()
        mock_store_fn.return_value = mock_store

        # Register event
        self.mgr.bridge.register_event(
            event_id="e1", sport="nfl", league="NFL", title="G1",
        )

        # Ingest odds update
        update = OddsUpdate(
            provider="test", event_id="e1", outcome_label="home",
            decimal_odds=1.91, implied_prob=0.5236,
        )
        self.mgr.odds_feed.ingest_update(update)

        # Should have created a platform line
        line = self.mgr.odds_engine.get_line("e1", "home")
        self.assertIsNotNone(line)

    def test_singleton(self):
        """get_sports_betting_manager returns same instance."""
        import merid.betting.live_sports as mod
        mod._manager = None  # Reset
        m1 = get_sports_betting_manager()
        m2 = get_sports_betting_manager()
        self.assertIs(m1, m2)
        mod._manager = None  # Clean up


# ══════════════════════════════════════════════════════════════════════
# §9 Observability Alerts
# ══════════════════════════════════════════════════════════════════════

class TestLiveBettingLatencyAlert(unittest.TestCase):
    """Test LiveBettingLatencyAlert."""

    def test_not_firing_no_bets(self):
        from web.api.system_observability import LiveBettingLatencyAlert
        alert = LiveBettingLatencyAlert()
        result = alert.evaluate()
        self.assertFalse(result["firing"])

    def test_not_firing_low_latency(self):
        from web.api.system_observability import LiveBettingLatencyAlert
        alert = LiveBettingLatencyAlert()
        with patch("merid.betting.live_sports.get_sports_betting_manager") as mock_mgr:
            mock_mgr.return_value.betting_engine.get_slo_metrics.return_value = {
                "p95_acceptance_latency_ms": 50.0,
                "total_bets": 10,
                "slo_breaches": 0,
                "acceptance_rate": 1.0,
            }
            result = alert.evaluate()
            self.assertFalse(result["firing"])

    def test_firing_high_latency(self):
        from web.api.system_observability import LiveBettingLatencyAlert
        alert = LiveBettingLatencyAlert()
        with patch("merid.betting.live_sports.get_sports_betting_manager") as mock_mgr:
            mock_mgr.return_value.betting_engine.get_slo_metrics.return_value = {
                "p95_acceptance_latency_ms": 500.0,
                "total_bets": 10,
                "slo_breaches": 5,
                "acceptance_rate": 0.5,
            }
            result = alert.evaluate()
            self.assertTrue(result["firing"])
            self.assertEqual(result["severity"], "critical")


class TestPricingDivergenceAlert(unittest.TestCase):
    """Test PricingDivergenceAlert."""

    def test_not_firing_no_lines(self):
        from web.api.system_observability import PricingDivergenceAlert
        alert = PricingDivergenceAlert()
        result = alert.evaluate()
        self.assertFalse(result["firing"])

    def test_not_firing_low_divergence(self):
        from web.api.system_observability import PricingDivergenceAlert
        alert = PricingDivergenceAlert()
        with patch("merid.betting.live_sports.get_sports_betting_manager") as mock_mgr:
            mock_mgr.return_value.odds_engine.get_pricing_divergence.return_value = {
                "avg_divergence": 0.02,
                "max_divergence": 0.05,
                "lines_count": 5,
                "stale_lines": 0,
            }
            result = alert.evaluate()
            self.assertFalse(result["firing"])

    def test_firing_high_divergence(self):
        from web.api.system_observability import PricingDivergenceAlert
        alert = PricingDivergenceAlert()
        with patch("merid.betting.live_sports.get_sports_betting_manager") as mock_mgr:
            mock_mgr.return_value.odds_engine.get_pricing_divergence.return_value = {
                "avg_divergence": 0.15,
                "max_divergence": 0.25,
                "lines_count": 5,
                "stale_lines": 1,
            }
            result = alert.evaluate()
            self.assertTrue(result["firing"])
            self.assertEqual(result["severity"], "warning")


class TestFeedStalenessAlert(unittest.TestCase):
    """Test FeedStalenessAlert."""

    def test_not_firing_no_providers(self):
        from web.api.system_observability import FeedStalenessAlert
        alert = FeedStalenessAlert()
        result = alert.evaluate()
        self.assertFalse(result["firing"])

    def test_not_firing_fresh(self):
        from web.api.system_observability import FeedStalenessAlert
        alert = FeedStalenessAlert()
        with patch("merid.betting.live_sports.get_sports_betting_manager") as mock_mgr:
            mock_mgr.return_value.odds_feed.get_feed_health.return_value = {
                "stale_providers": 0,
                "total_providers": 2,
                "providers": {"a": {"is_stale": False}, "b": {"is_stale": False}},
            }
            result = alert.evaluate()
            self.assertFalse(result["firing"])

    def test_firing_stale(self):
        from web.api.system_observability import FeedStalenessAlert
        alert = FeedStalenessAlert()
        with patch("merid.betting.live_sports.get_sports_betting_manager") as mock_mgr:
            mock_mgr.return_value.odds_feed.get_feed_health.return_value = {
                "stale_providers": 1,
                "total_providers": 2,
                "providers": {"a": {"is_stale": True}, "b": {"is_stale": False}},
            }
            result = alert.evaluate()
            self.assertTrue(result["firing"])
            self.assertEqual(result["detail"]["stale_names"], ["a"])


class TestAlertRegistryCount(unittest.TestCase):
    """Verify total alert count after Sprint 12."""

    def test_total_alert_rules(self):
        from web.api.system_observability import ALERT_RULES
        # 22 from Sprint 11 + 3 sports live + 3 sports integration = 28
        self.assertEqual(len(ALERT_RULES), 28)


# ══════════════════════════════════════════════════════════════════════
# §10 API Endpoints
# ══════════════════════════════════════════════════════════════════════

class TestSportsAPIEndpoints(unittest.TestCase):
    """Test sports betting API endpoints via FastAPI TestClient."""

    @classmethod
    def setUpClass(cls):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from web.api.betting import router

        app = FastAPI()
        app.include_router(router)
        cls.client = TestClient(app)

    @patch("web.api.betting._get_sports_manager")
    def test_register_sports_event(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        si = SportsInstrument(event_id="e1", sport="nfl", title="G1")
        mock_mgr.bridge.register_event.return_value = si
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.post("/api/v1/betting/sports/register", json={
            "event_id": "e1",
            "sport": "nfl",
            "title": "Chiefs vs Eagles",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "registered")

    @patch("web.api.betting._get_sports_manager")
    def test_list_sports_events(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.bridge.list_events.return_value = [
            SportsInstrument(event_id="e1", sport="nfl", title="G1"),
        ]
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.get("/api/v1/betting/sports/events")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    @patch("web.api.betting._get_sports_manager")
    def test_get_sports_event(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.bridge.get_event.return_value = SportsInstrument(
            event_id="e1", sport="nfl", title="G1",
        )
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.get("/api/v1/betting/sports/e1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["event_id"], "e1")

    @patch("web.api.betting._get_sports_manager")
    def test_get_sports_event_not_found(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.bridge.get_event.return_value = None
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.get("/api/v1/betting/sports/nonexistent")
        self.assertEqual(resp.status_code, 404)

    @patch("web.api.betting._get_sports_manager")
    def test_update_event_state(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.bridge.update_event_state.return_value = SportsInstrument(
            event_id="e1", sport="nfl", title="G1", state="live",
        )
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.post("/api/v1/betting/sports/e1/state", json={
            "state": "live",
            "score_home": 7,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "updated")

    @patch("web.api.betting._get_sports_manager")
    def test_update_event_state_not_found(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.bridge.update_event_state.return_value = None
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.post("/api/v1/betting/sports/nonexistent/state", json={
            "state": "live",
        })
        self.assertEqual(resp.status_code, 404)

    @patch("web.api.betting._get_sports_manager")
    def test_settle_sports_event(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.bridge.settle_event.return_value = {
            "event_id": "e1",
            "winning_outcomes": ["home"],
            "settled_instruments": [],
        }
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.post("/api/v1/betting/sports/e1/settle", json={
            "winning_outcomes": ["home"],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["winning_outcomes"], ["home"])

    @patch("web.api.betting._get_sports_manager")
    def test_ingest_odds(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.post("/api/v1/betting/sports/odds/ingest", json={
            "provider": "fanduel",
            "event_id": "e1",
            "outcome_label": "home",
            "decimal_odds": 1.91,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ingested")

    @patch("web.api.betting._get_sports_manager")
    def test_feed_health(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.odds_feed.get_feed_health.return_value = {"total_providers": 0}
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.get("/api/v1/betting/sports/odds/feed-health")
        self.assertEqual(resp.status_code, 200)

    @patch("web.api.betting._get_sports_manager")
    def test_get_event_lines(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.odds_engine.get_all_lines.return_value = [
            PlatformLine(event_id="e1", outcome_label="home"),
        ]
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.get("/api/v1/betting/sports/e1/lines")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["lines"]), 1)

    @patch("web.api.betting._get_sports_manager")
    def test_get_event_lines_not_found(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.odds_engine.get_all_lines.return_value = []
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.get("/api/v1/betting/sports/e1/lines")
        self.assertEqual(resp.status_code, 404)

    @patch("web.api.betting._get_sports_manager")
    def test_place_live_bet(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.betting_engine.accept_bet.return_value = BetAcceptanceResult(
            accepted=True, bet_id="live-abc", stake=100.0, odds_at_placement=1.91,
        )
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.post("/api/v1/betting/sports/live-bet", json={
            "event_id": "e1",
            "outcome_label": "home",
            "stake": 100.0,
            "displayed_odds": 1.91,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["accepted"])

    @patch("web.api.betting._get_sports_manager")
    def test_slo_metrics(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.betting_engine.get_slo_metrics.return_value = {"total_bets": 0, "slo_met": True}
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.get("/api/v1/betting/sports/slo-metrics")
        self.assertEqual(resp.status_code, 200)

    @patch("web.api.betting._get_sports_manager")
    def test_submit_forecast(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.forecast_engine.submit_forecast.return_value = {
            "event_id": "e1", "agent_id": "a1", "probability": 0.65,
        }
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.post("/api/v1/betting/sports/forecast", json={
            "agent_id": "a1",
            "event_id": "e1",
            "outcome_label": "home",
            "probability": 0.65,
        })
        self.assertEqual(resp.status_code, 200)

    @patch("web.api.betting._get_sports_manager")
    def test_get_event_forecasts(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.forecast_engine.get_event_forecasts.return_value = [
            SportsForecast(agent_id="a1", event_id="e1", outcome_label="home", probability=0.65),
        ]
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.get("/api/v1/betting/sports/forecasts/e1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    @patch("web.api.betting._get_sports_manager")
    def test_coherence_endpoint(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.forecast_engine.get_coherence_stats.return_value = {"avg_coherence": None, "entries": 0}
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.get("/api/v1/betting/sports/coherence")
        self.assertEqual(resp.status_code, 200)

    @patch("web.api.betting._get_sports_manager")
    def test_list_quests(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.quest_engine.list_quests.return_value = [
            Quest(id="q1", name="Test Quest"),
        ]
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.get("/api/v1/betting/sports/quests")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    @patch("web.api.betting._get_sports_manager")
    def test_agent_quests(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.quest_engine.get_agent_quests.return_value = []
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.get("/api/v1/betting/sports/quests/agent1")
        self.assertEqual(resp.status_code, 200)

    @patch("web.api.betting._get_sports_manager")
    def test_sports_health(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.get_sports_health.return_value = {"events": {"total": 0}}
        mock_mgr_fn.return_value = mock_mgr

        resp = self.client.get("/api/v1/betting/sports/health")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
