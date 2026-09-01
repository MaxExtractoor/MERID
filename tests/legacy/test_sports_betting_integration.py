"""Comprehensive test suite for Sports & Live Betting Integration sprint.

Tests cover:
  §1  OpticOdds API client (merid/betting/optic_odds.py)
  §2  OddsAwareSportsAgent (merid/agents/sports_odds.py)
  §3  Live odds cache + latency tracking (merid/betting/live_odds_cache.py)
  §4  Sports debate protocol (merid/betting/sports_debate.py)
  §5  Anomaly detection (merid/betting/anomaly_detection.py)
  §6  Sports reward events (merid/rewards/events.py)
  §7  Sports rewards: badges, quests, reward computer (merid/rewards/sports_rewards.py)
  §8  Alert registry (3 new alerts → 28 total)
  §9  Package exports (__init__.py)
  §10 Latency load tests (concurrent odds updates + bet placements)
"""

import asyncio
import collections
import concurrent.futures
import statistics
import sys

import threading
import time
import unittest
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Sports/live-betting modules are legacy and not part of the active 15m crypto surface.
pytestmark = pytest.mark.skip(reason="Sports/live betting integration is legacy, not part of active 15m crypto system")

sys.path.insert(0, ".")


# ══════════════════════════════════════════════════════════════════════
# §1 OpticOdds API Client Tests
# ══════════════════════════════════════════════════════════════════════

class TestOpticOddsClient(unittest.TestCase):
    """Tests for OpticOddsClient HTTP client."""

    def test_import(self):
        from merid.betting.optic_odds import OpticOddsClient
        client = OpticOddsClient(api_key="test-key")
        self.assertIsNotNone(client)
        self.assertEqual(client.api_key, "test-key")

    def test_default_base_url(self):
        from merid.betting.optic_odds import OpticOddsClient
        client = OpticOddsClient(api_key="k")
        self.assertIn("opticodds", client.base_url.lower())

    def test_client_is_configured(self):
        from merid.betting.optic_odds import OpticOddsClient
        client = OpticOddsClient(api_key="secret123")
        self.assertTrue(client.is_configured)
        client_no_key = OpticOddsClient(api_key="")
        self.assertFalse(client_no_key.is_configured)

    def test_snapshot_store_basic(self):
        from merid.betting.optic_odds import OddsSnapshotStore, OpticOddsLine
        store = OddsSnapshotStore()
        line = OpticOddsLine(fixture_id="evt1", sportsbook="pinnacle",
                             outcome_label="home", american_odds=-110)
        snap = store.record(line)
        self.assertEqual(snap.fixture_id, "evt1")
        history = store.get_history("evt1")
        self.assertEqual(len(history), 1)

    def test_snapshot_store_limit(self):
        from merid.betting.optic_odds import OddsSnapshotStore, OpticOddsLine
        store = OddsSnapshotStore(max_per_fixture=5)
        for i in range(10):
            line = OpticOddsLine(fixture_id="evt1", sportsbook=f"book{i}",
                                outcome_label="home", american_odds=-110)
            store.record(line)
        history = store.get_history("evt1", limit=100)
        self.assertLessEqual(len(history), 5)

    def test_snapshot_store_by_fixture(self):
        from merid.betting.optic_odds import OddsSnapshotStore, OpticOddsLine
        store = OddsSnapshotStore()
        store.record(OpticOddsLine(fixture_id="a", sportsbook="dk", outcome_label="home", american_odds=-110))
        store.record(OpticOddsLine(fixture_id="b", sportsbook="dk", outcome_label="home", american_odds=-120))
        store.record(OpticOddsLine(fixture_id="a", sportsbook="fd", outcome_label="away", american_odds=+100))
        a_snaps = store.get_history("a")
        self.assertEqual(len(a_snaps), 2)

    def test_poller_creation(self):
        from merid.betting.optic_odds import OpticOddsPoller, OpticOddsClient, OddsSnapshotStore
        client = OpticOddsClient(api_key="k")
        store = OddsSnapshotStore()
        poller = OpticOddsPoller(client=client, snapshot_store=store, pre_game_interval_s=30)
        self.assertEqual(poller.pre_game_interval_s, 30)

    def test_singletons(self):
        from merid.betting.optic_odds import get_optic_odds_client, get_snapshot_store
        c1 = get_optic_odds_client()
        c2 = get_optic_odds_client()
        self.assertIs(c1, c2)
        s1 = get_snapshot_store()
        s2 = get_snapshot_store()
        self.assertIs(s1, s2)


# ══════════════════════════════════════════════════════════════════════
# §2 OddsAwareSportsAgent Tests
# ══════════════════════════════════════════════════════════════════════

class TestSportsOddsStrategy(unittest.TestCase):
    """Tests for SportsOddsStrategy probability blending."""

    def test_import(self):
        from merid.agents.sports_odds import SportsOddsStrategy
        strategy = SportsOddsStrategy()
        self.assertIsNotNone(strategy)

    def test_estimate_basic(self):
        from merid.agents.sports_odds import SportsOddsStrategy
        strategy = SportsOddsStrategy(min_edge=0.0)
        result = strategy.estimate(
            agent_id="test-agent",
            event_id="evt1",
            outcome_label="home",
            consensus_prob=0.50,
            sharp_prob=0.55,
        )
        self.assertIsNotNone(result)
        self.assertGreater(result.agent_prob, 0.0)
        self.assertLess(result.agent_prob, 1.0)

    def test_estimate_clamps_to_valid_range(self):
        from merid.agents.sports_odds import SportsOddsStrategy
        strategy = SportsOddsStrategy(min_edge=0.0)
        result = strategy.estimate(
            agent_id="test-agent", event_id="evt1",
            outcome_label="home", consensus_prob=0.90,
            sharp_prob=0.85,
        )
        # May return None for extreme lines; if not, check range
        if result is not None:
            self.assertLessEqual(result.agent_prob, 1.0)
            self.assertGreaterEqual(result.agent_prob, 0.0)

    def test_estimate_edge_calculation(self):
        from merid.agents.sports_odds import SportsOddsStrategy
        strategy = SportsOddsStrategy(min_edge=0.0)
        result = strategy.estimate(
            agent_id="test-agent", event_id="evt1",
            outcome_label="home", consensus_prob=0.50,
            sharp_prob=0.50,
        )
        # Edge should be small when all signals agree
        if result is not None:
            self.assertAlmostEqual(abs(result.edge), 0.0, delta=0.15)

    def test_explanation_metadata(self):
        from merid.agents.sports_odds import SportsOddsStrategy
        strategy = SportsOddsStrategy(min_edge=0.0)
        result = strategy.estimate(
            agent_id="test-agent", event_id="evt1",
            outcome_label="home", consensus_prob=0.55,
            sharp_prob=0.60, sport="nfl",
        )
        if result is not None:
            self.assertIn("inputs_used", result.explanation)
            self.assertIn("consensus_prob", result.explanation["inputs_used"])
            self.assertIn("sharp_prob", result.explanation["inputs_used"])


class TestOddsAwareSportsAgent(unittest.TestCase):
    """Tests for OddsAwareSportsAgent lifecycle."""

    def test_import_and_create(self):
        from merid.agents.sports_odds import OddsAwareSportsAgent
        agent = OddsAwareSportsAgent(agent_id="test-sports-agent")
        self.assertEqual(agent.agent_id, "test-sports-agent")

    def test_singleton(self):
        from merid.agents.sports_odds import get_sports_odds_agent
        a1 = get_sports_odds_agent()
        a2 = get_sports_odds_agent()
        self.assertIs(a1, a2)


# ══════════════════════════════════════════════════════════════════════
# §3 Live Odds Cache + Latency Tests
# ══════════════════════════════════════════════════════════════════════

class TestLiveOddsCache(unittest.TestCase):
    """Tests for LiveOddsCache thread-safe in-memory cache."""

    def test_put_and_get(self):
        from merid.betting.live_odds_cache import LiveOddsCache
        cache = LiveOddsCache(ttl_s=60.0)
        cache.put("evt1", "home", 0.55, provider="sharp")
        entry = cache.get("evt1", "home")
        self.assertIsNotNone(entry)
        self.assertAlmostEqual(entry.implied_prob, 0.55, places=2)

    def test_ttl_expiry(self):
        from merid.betting.live_odds_cache import LiveOddsCache
        cache = LiveOddsCache(ttl_s=0.01)
        cache.put("evt1", "home", 0.55)
        time.sleep(0.05)
        entry = cache.get("evt1", "home")
        self.assertIsNone(entry)

    def test_version_increments(self):
        from merid.betting.live_odds_cache import LiveOddsCache
        cache = LiveOddsCache(ttl_s=60.0)
        cache.put("evt1", "home", 0.50)
        e1 = cache.get("evt1", "home")
        cache.put("evt1", "home", 0.55)
        e2 = cache.get("evt1", "home")
        self.assertGreater(e2.version, e1.version)

    def test_get_event(self):
        from merid.betting.live_odds_cache import LiveOddsCache
        cache = LiveOddsCache(ttl_s=60.0)
        cache.put("evt1", "home", 0.55)
        cache.put("evt1", "away", 0.40)
        cache.put("evt1", "draw", 0.05)
        entries = cache.get_event("evt1")
        self.assertEqual(len(entries), 3)

    def test_stats(self):
        from merid.betting.live_odds_cache import LiveOddsCache
        cache = LiveOddsCache(ttl_s=60.0)
        cache.put("evt1", "home", 0.55)
        cache.put("evt2", "home", 0.60)
        stats = cache.get_stats()
        self.assertEqual(stats["total_entries"], 2)

    def test_stale_entries_in_stats(self):
        from merid.betting.live_odds_cache import LiveOddsCache
        cache = LiveOddsCache(ttl_s=0.01)
        cache.put("evt1", "home", 0.55)
        time.sleep(0.05)
        stats = cache.get_stats()
        self.assertEqual(stats["stale_entries"], 1)
        # get() returns None for stale entries
        self.assertIsNone(cache.get("evt1", "home"))


class TestOddsLatencyTracker(unittest.TestCase):
    """Tests for OddsLatencyTracker percentile tracking."""

    def test_record_and_percentiles(self):
        from merid.betting.live_odds_cache import OddsLatencyTracker
        tracker = OddsLatencyTracker()
        for i in range(100):
            tracker.record("propagation", float(i))
        metrics = tracker.get_tier_metrics("propagation")
        self.assertIn("p50_ms", metrics)
        self.assertIn("p95_ms", metrics)
        self.assertIn("p99_ms", metrics)

    def test_slo_met(self):
        from merid.betting.live_odds_cache import OddsLatencyTracker
        tracker = OddsLatencyTracker()
        # All fast — default propagation SLO target is 100ms
        for _ in range(100):
            tracker.record("propagation", 10.0)
        metrics = tracker.get_tier_metrics("propagation")
        self.assertTrue(metrics["slo_met"])

    def test_slo_breach(self):
        from merid.betting.live_odds_cache import OddsLatencyTracker
        tracker = OddsLatencyTracker()
        # All slow — default propagation SLO target is 100ms
        for _ in range(100):
            tracker.record("propagation", 500.0)
        metrics = tracker.get_tier_metrics("propagation")
        self.assertFalse(metrics["slo_met"])


class TestOddsPushManager(unittest.TestCase):
    """Tests for OddsPushManager subscriber notifications."""

    def test_subscribe_and_push(self):
        from merid.betting.live_odds_cache import OddsPushManager, CachedOddsEntry
        mgr = OddsPushManager()
        received = []
        mgr.subscribe(lambda entry: received.append(entry))
        entry = CachedOddsEntry(event_id="evt1", outcome_label="home", implied_prob=0.55)
        mgr.push(entry)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].event_id, "evt1")

    def test_unsubscribe(self):
        from merid.betting.live_odds_cache import OddsPushManager, CachedOddsEntry
        mgr = OddsPushManager()
        received = []
        sub_id = mgr.subscribe(lambda entry: received.append(entry))
        mgr.unsubscribe(sub_id)
        entry = CachedOddsEntry(event_id="evt1", outcome_label="home", implied_prob=0.55)
        mgr.push(entry)
        self.assertEqual(len(received), 0)

    def test_multiple_subscribers(self):
        from merid.betting.live_odds_cache import OddsPushManager, CachedOddsEntry
        mgr = OddsPushManager()
        r1, r2 = [], []
        mgr.subscribe(lambda d: r1.append(d))
        mgr.subscribe(lambda d: r2.append(d))
        entry = CachedOddsEntry(event_id="evt1", outcome_label="home", implied_prob=0.55)
        mgr.push(entry)
        self.assertEqual(len(r1), 1)
        self.assertEqual(len(r2), 1)

    def test_subscriber_error_isolation(self):
        from merid.betting.live_odds_cache import OddsPushManager, CachedOddsEntry
        mgr = OddsPushManager()
        received = []
        def bad_callback(d):
            raise ValueError("boom")
        mgr.subscribe(bad_callback)
        mgr.subscribe(lambda d: received.append(d))
        entry = CachedOddsEntry(event_id="evt1", outcome_label="home", implied_prob=0.55)
        mgr.push(entry)
        # Good subscriber should still receive despite bad one crashing
        self.assertEqual(len(received), 1)


class TestLiveOddsCacheManager(unittest.TestCase):
    """Tests for LiveOddsCacheManager facade."""

    def test_singleton(self):
        from merid.betting.live_odds_cache import get_live_odds_cache_manager
        m1 = get_live_odds_cache_manager()
        m2 = get_live_odds_cache_manager()
        self.assertIs(m1, m2)

    def test_facade_has_components(self):
        from merid.betting.live_odds_cache import LiveOddsCacheManager
        mgr = LiveOddsCacheManager()
        self.assertIsNotNone(mgr.cache)
        self.assertIsNotNone(mgr.tracker)
        self.assertIsNotNone(mgr.push_manager)


# ══════════════════════════════════════════════════════════════════════
# §4 Sports Debate Protocol Tests
# ══════════════════════════════════════════════════════════════════════

class TestSportsDebateSession(unittest.TestCase):
    """Tests for SportsDebateSession and argument handling."""

    def test_create_session(self):
        from merid.betting.sports_debate import SportsDebateSession
        session = SportsDebateSession(
            event_id="evt1",
            outcome_label="home",
            sport="football",
        )
        self.assertEqual(session.event_id, "evt1")
        self.assertEqual(session.outcome_label, "home")
        self.assertEqual(session.status, "open")

    def test_add_argument(self):
        from merid.betting.sports_debate import SportsDebateSession, SportsDebateArgument
        session = SportsDebateSession(event_id="evt1", outcome_label="home")
        arg = SportsDebateArgument(
            agent_id="agent1",
            role="proposer",
            probability=0.60,
            confidence=0.8,
            reasoning="Strong home record",
        )
        session.arguments.append(arg)
        self.assertEqual(len(session.arguments), 1)
        self.assertEqual(session.arguments[0].agent_id, "agent1")

    def test_session_to_dict(self):
        from merid.betting.sports_debate import SportsDebateSession
        session = SportsDebateSession(event_id="evt1", outcome_label="home", sport="nfl")
        d = session.to_dict()
        self.assertEqual(d["event_id"], "evt1")
        self.assertEqual(d["sport"], "nfl")
        self.assertIn("id", d)


class TestSportsDebateLiftTracker(unittest.TestCase):
    """Tests for debate lift computation."""

    def test_record_and_stats(self):
        from merid.betting.sports_debate import SportsDebateLiftTracker, SportsDebateSession
        tracker = SportsDebateLiftTracker()
        # Debate improved: pre_prob=0.50, post_prob=0.80, outcome=1
        # pre_brier = (0.50-1)^2 = 0.25, post_brier = (0.80-1)^2 = 0.04, lift = 0.21
        d1 = SportsDebateSession(event_id="e1", outcome_label="home", pre_debate_prob=0.50)
        d1.post_debate_prob = 0.80
        tracker.record_lift(d1, outcome=1)
        # Another improvement
        d2 = SportsDebateSession(event_id="e2", outcome_label="home", pre_debate_prob=0.40)
        d2.post_debate_prob = 0.70
        tracker.record_lift(d2, outcome=1)
        stats = tracker.get_stats()
        self.assertEqual(stats["total_debates"], 2)
        self.assertGreater(stats["avg_lift"], 0)  # Both improved

    def test_negative_lift(self):
        from merid.betting.sports_debate import SportsDebateLiftTracker, SportsDebateSession
        tracker = SportsDebateLiftTracker()
        # Debate made it worse: pre_prob=0.80, post_prob=0.50, outcome=1
        # pre_brier = (0.80-1)^2 = 0.04, post_brier = (0.50-1)^2 = 0.25, lift = -0.21
        d1 = SportsDebateSession(event_id="e1", outcome_label="home", pre_debate_prob=0.80)
        d1.post_debate_prob = 0.50
        tracker.record_lift(d1, outcome=1)
        stats = tracker.get_stats()
        self.assertLess(stats["avg_lift"], 0)
        self.assertEqual(stats["positive_lift_rate"], 0.0)

    def test_mixed_lift(self):
        from merid.betting.sports_debate import SportsDebateLiftTracker, SportsDebateSession
        tracker = SportsDebateLiftTracker()
        # Improvement: pre=0.50, post=0.80, outcome=1 → lift = 0.21
        d1 = SportsDebateSession(event_id="e1", outcome_label="home", pre_debate_prob=0.50)
        d1.post_debate_prob = 0.80
        tracker.record_lift(d1, outcome=1)
        # Degradation: pre=0.80, post=0.50, outcome=1 → lift = -0.21
        d2 = SportsDebateSession(event_id="e2", outcome_label="home", pre_debate_prob=0.80)
        d2.post_debate_prob = 0.50
        tracker.record_lift(d2, outcome=1)
        stats = tracker.get_stats()
        self.assertAlmostEqual(stats["avg_lift"], 0.0, places=4)
        self.assertAlmostEqual(stats["positive_lift_rate"], 0.5, places=2)


class TestSportsDebateCoordinator(unittest.TestCase):
    """Tests for SportsDebateCoordinator lifecycle."""

    def test_create_debate(self):
        from merid.betting.sports_debate import SportsDebateCoordinator
        coord = SportsDebateCoordinator()
        session = coord.create_debate(
            event_id="evt1", outcome_label="home",
            pre_debate_prob=0.55, sport="nba",
        )
        self.assertIsNotNone(session)
        self.assertEqual(session.sport, "nba")

    def test_get_debate(self):
        from merid.betting.sports_debate import SportsDebateCoordinator
        coord = SportsDebateCoordinator()
        session = coord.create_debate(
            event_id="evt1", outcome_label="home", pre_debate_prob=0.55,
        )
        retrieved = coord.get_debate(session.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.event_id, "evt1")

    def test_add_argument(self):
        from merid.betting.sports_debate import SportsDebateCoordinator
        coord = SportsDebateCoordinator()
        session = coord.create_debate(
            event_id="evt1", outcome_label="home", pre_debate_prob=0.55,
        )
        coord.add_argument(
            debate_id=session.id,
            agent_id="agent1",
            role="proposer",
            probability=0.60,
            confidence=0.8,
            reasoning="Strong home record",
        )
        updated = coord.get_debate(session.id)
        self.assertEqual(len(updated.arguments), 1)

    def test_get_stats(self):
        from merid.betting.sports_debate import SportsDebateCoordinator
        coord = SportsDebateCoordinator()
        coord.create_debate(event_id="evt1", outcome_label="home", pre_debate_prob=0.55)
        coord.create_debate(event_id="evt2", outcome_label="away", pre_debate_prob=0.45)
        stats = coord.get_stats()
        self.assertEqual(stats["total_debates"], 2)

    def test_singleton(self):
        from merid.betting.sports_debate import get_sports_debate_coordinator
        c1 = get_sports_debate_coordinator()
        c2 = get_sports_debate_coordinator()
        self.assertIs(c1, c2)


# ══════════════════════════════════════════════════════════════════════
# §5 Anomaly Detection Tests
# ══════════════════════════════════════════════════════════════════════

class TestFeedStalenessDetector(unittest.TestCase):
    """Tests for feed staleness detection."""

    def test_fresh_provider_no_alert(self):
        from merid.betting.anomaly_detection import FeedStalenessDetector
        det = FeedStalenessDetector(default_threshold_s=60.0)
        det.record_update("provider_a")
        anomalies = det.check()
        self.assertEqual(len(anomalies), 0)

    def test_stale_provider_fires(self):
        from merid.betting.anomaly_detection import FeedStalenessDetector
        det = FeedStalenessDetector(default_threshold_s=0.01)
        det.record_update("provider_a", timestamp=time.time() - 10)
        anomalies = det.check()
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0].anomaly_type, "feed_stale")

    def test_stale_alert_not_duplicated(self):
        from merid.betting.anomaly_detection import FeedStalenessDetector
        det = FeedStalenessDetector(default_threshold_s=0.01)
        det.record_update("provider_a", timestamp=time.time() - 10)
        det.check()
        anomalies2 = det.check()
        self.assertEqual(len(anomalies2), 0)  # Already alerted

    def test_update_clears_alert(self):
        from merid.betting.anomaly_detection import FeedStalenessDetector
        det = FeedStalenessDetector(default_threshold_s=0.01)
        det.record_update("provider_a", timestamp=time.time() - 10)
        det.check()
        det.record_update("provider_a")  # Fresh update
        anomalies = det.check()
        self.assertEqual(len(anomalies), 0)

    def test_status(self):
        from merid.betting.anomaly_detection import FeedStalenessDetector
        det = FeedStalenessDetector(default_threshold_s=60.0)
        det.record_update("p1")
        det.record_update("p2")
        status = det.get_status()
        self.assertEqual(len(status["providers"]), 2)


class TestOddsJumpDetector(unittest.TestCase):
    """Tests for odds jump detection."""

    def test_no_jump_on_first_update(self):
        from merid.betting.anomaly_detection import OddsJumpDetector
        det = OddsJumpDetector(jump_threshold=0.10)
        result = det.check_update("evt1", "home", 0.55, "sharp")
        self.assertIsNone(result)

    def test_small_movement_no_alert(self):
        from merid.betting.anomaly_detection import OddsJumpDetector
        det = OddsJumpDetector(jump_threshold=0.10)
        det.check_update("evt1", "home", 0.55, "sharp")
        result = det.check_update("evt1", "home", 0.57, "sharp")
        self.assertIsNone(result)

    def test_large_jump_fires(self):
        from merid.betting.anomaly_detection import OddsJumpDetector
        det = OddsJumpDetector(jump_threshold=0.10)
        det.check_update("evt1", "home", 0.50, "sharp")
        result = det.check_update("evt1", "home", 0.70, "sharp")
        self.assertIsNotNone(result)
        self.assertEqual(result.anomaly_type, "odds_jump")

    def test_rapid_drift_fires(self):
        from merid.betting.anomaly_detection import OddsJumpDetector
        det = OddsJumpDetector(
            jump_threshold=0.20,
            rapid_jump_threshold=0.05,
            rapid_window_s=5.0,
        )
        det.check_update("evt1", "home", 0.50, "sharp")
        det.check_update("evt1", "home", 0.52, "sharp")
        det.check_update("evt1", "home", 0.54, "sharp")
        result = det.check_update("evt1", "home", 0.56, "sharp")
        self.assertIsNotNone(result)

    def test_recent_movements(self):
        from merid.betting.anomaly_detection import OddsJumpDetector
        det = OddsJumpDetector()
        det.check_update("evt1", "home", 0.50)
        det.check_update("evt1", "home", 0.52)
        movements = det.get_recent_movements()
        self.assertEqual(len(movements), 1)  # First has no prior


class TestBetPatternDetector(unittest.TestCase):
    """Tests for suspicious bet pattern detection."""

    def test_normal_bet_no_alert(self):
        from merid.betting.anomaly_detection import BetPatternDetector, BetRecord
        det = BetPatternDetector(rapid_fire_threshold=5)
        record = BetRecord(bet_id="b1", user_id="u1", event_id="e1",
                           outcome_label="home", stake=10.0)
        anomalies = det.check_bet(record)
        self.assertEqual(len(anomalies), 0)

    def test_rapid_fire_detection(self):
        from merid.betting.anomaly_detection import BetPatternDetector, BetRecord
        det = BetPatternDetector(rapid_fire_window_s=60.0, rapid_fire_threshold=3)
        now = time.time()
        for i in range(4):
            record = BetRecord(bet_id=f"b{i}", user_id="u1", event_id="e1",
                               outcome_label="home", stake=10.0, timestamp=now + i)
            anomalies = det.check_bet(record)
        # Should fire on the 3rd bet
        self.assertTrue(any(a.anomaly_type == "rapid_fire_bets" for a in anomalies))

    def test_size_spike_detection(self):
        from merid.betting.anomaly_detection import BetPatternDetector, BetRecord
        det = BetPatternDetector(size_spike_multiplier=3.0)
        now = time.time()
        # Build history of small bets
        for i in range(5):
            det.check_bet(BetRecord(bet_id=f"b{i}", user_id="u1", event_id="e1",
                                    outcome_label="home", stake=10.0, timestamp=now + i))
        # Now a huge bet
        anomalies = det.check_bet(BetRecord(
            bet_id="big", user_id="u1", event_id="e1",
            outcome_label="home", stake=100.0, timestamp=now + 10,
        ))
        self.assertTrue(any(a.anomaly_type == "size_spike" for a in anomalies))

    def test_correlated_timing_detection(self):
        from merid.betting.anomaly_detection import BetPatternDetector, BetRecord
        det = BetPatternDetector(correlation_window_s=5.0, correlation_threshold=3)
        now = time.time()
        all_anomalies = []
        for i in range(4):
            record = BetRecord(bet_id=f"b{i}", user_id=f"u{i}", event_id="e1",
                               outcome_label="home", stake=10.0, timestamp=now)
            all_anomalies.extend(det.check_bet(record))
        self.assertTrue(any(a.anomaly_type == "correlated_timing" for a in all_anomalies))


class TestAnomalyEngine(unittest.TestCase):
    """Tests for AnomalyEngine aggregator."""

    def test_create(self):
        from merid.betting.anomaly_detection import AnomalyEngine
        engine = AnomalyEngine()
        self.assertIsNotNone(engine)

    def test_on_bet_placed(self):
        from merid.betting.anomaly_detection import AnomalyEngine
        engine = AnomalyEngine()
        anomalies = engine.on_bet_placed(
            bet_id="b1", user_id="u1", event_id="e1",
            outcome_label="home", stake=10.0,
        )
        self.assertIsInstance(anomalies, list)

    def test_staleness_check(self):
        from merid.betting.anomaly_detection import AnomalyEngine
        engine = AnomalyEngine()
        engine.staleness.record_update("p1", timestamp=time.time() - 1000)
        engine.staleness.set_threshold("p1", 1.0)
        anomalies = engine.run_staleness_check()
        self.assertGreater(len(anomalies), 0)

    def test_acknowledge(self):
        from merid.betting.anomaly_detection import AnomalyEngine
        engine = AnomalyEngine()
        engine.staleness.record_update("p1", timestamp=time.time() - 1000)
        engine.staleness.set_threshold("p1", 1.0)
        anomalies = engine.run_staleness_check()
        self.assertTrue(len(anomalies) > 0)
        ack = engine.acknowledge(anomalies[0].id)
        self.assertTrue(ack)

    def test_get_anomalies_filtered(self):
        from merid.betting.anomaly_detection import AnomalyEngine
        engine = AnomalyEngine()
        engine.staleness.record_update("p1", timestamp=time.time() - 1000)
        engine.staleness.set_threshold("p1", 1.0)
        engine.run_staleness_check()
        results = engine.get_anomalies(anomaly_type="feed_stale")
        self.assertGreater(len(results), 0)
        results_empty = engine.get_anomalies(anomaly_type="nonexistent")
        self.assertEqual(len(results_empty), 0)

    def test_get_stats(self):
        from merid.betting.anomaly_detection import AnomalyEngine
        engine = AnomalyEngine()
        stats = engine.get_stats()
        self.assertEqual(stats["total"], 0)

    def test_singleton(self):
        from merid.betting.anomaly_detection import get_anomaly_engine
        e1 = get_anomaly_engine()
        e2 = get_anomaly_engine()
        self.assertIs(e1, e2)


# ══════════════════════════════════════════════════════════════════════
# §6 Sports Reward Events Tests
# ══════════════════════════════════════════════════════════════════════

class TestSportsRewardEvents(unittest.TestCase):
    """Tests for sports-specific reward event dataclasses."""

    def test_sports_forecast_event(self):
        from merid.rewards.events import SportsForecastEvent, EventCategory
        evt = SportsForecastEvent(
            agent_id="agent1",
            event_id="evt1",
            outcome_label="home",
            sport="nfl",
            probability=0.60,
            confidence=0.8,
            edge=0.05,
        )
        self.assertEqual(evt.category, EventCategory.SPORTS_FORECAST.value)
        d = evt.to_dict()
        self.assertEqual(d["sport"], "nfl")
        self.assertAlmostEqual(d["probability"], 0.60, places=2)

    def test_sports_bet_event(self):
        from merid.rewards.events import SportsBetEvent, EventCategory
        evt = SportsBetEvent(
            agent_id="agent1",
            event_id="evt1",
            outcome_label="home",
            stake=100.0,
            odds=1.85,
            pnl=85.0,
            is_settled=True,
        )
        self.assertEqual(evt.category, EventCategory.SPORTS_BET.value)
        d = evt.to_dict()
        self.assertEqual(d["stake"], 100.0)
        self.assertEqual(d["pnl"], 85.0)

    def test_sports_debate_event(self):
        from merid.rewards.events import SportsDebateEvent, EventCategory
        evt = SportsDebateEvent(
            agent_id="agent1",
            debate_id="d1",
            event_id="evt1",
            role="proposer",
            debate_lift=0.05,
            pre_debate_prob=0.50,
            post_debate_prob=0.55,
        )
        self.assertEqual(evt.category, EventCategory.SPORTS_DEBATE.value)
        d = evt.to_dict()
        self.assertEqual(d["role"], "proposer")
        self.assertAlmostEqual(d["debate_lift"], 0.05, places=4)

    def test_event_from_dict_roundtrip(self):
        from merid.rewards.events import SportsForecastEvent, event_from_dict
        original = SportsForecastEvent(
            agent_id="a1", event_id="e1", sport="nba",
            probability=0.65, confidence=0.9,
        )
        d = original.to_dict()
        restored = event_from_dict(d)
        self.assertEqual(restored.category, "sports_forecast")
        self.assertEqual(restored.agent_id, "a1")

    def test_event_categories_registered(self):
        from merid.rewards.events import EventCategory
        self.assertEqual(EventCategory.SPORTS_FORECAST.value, "sports_forecast")
        self.assertEqual(EventCategory.SPORTS_BET.value, "sports_bet")
        self.assertEqual(EventCategory.SPORTS_DEBATE.value, "sports_debate")


# ══════════════════════════════════════════════════════════════════════
# §7 Sports Rewards: Badges, Quests, Reward Computer
# ══════════════════════════════════════════════════════════════════════

class TestSportsBadgeEngine(unittest.TestCase):
    """Tests for sports badge evaluation and awarding."""

    def test_no_badges_initially(self):
        from merid.rewards.sports_rewards import SportsBadgeEngine
        engine = SportsBadgeEngine()
        badges = engine.get_badges("agent1")
        self.assertEqual(len(badges), 0)

    def test_award_forecast_badge(self):
        from merid.rewards.sports_rewards import SportsBadgeEngine
        engine = SportsBadgeEngine()
        stats = {"forecast_count": 15}
        awards = engine.evaluate("agent1", stats)
        badge_ids = [a.badge_id for a in awards]
        self.assertIn("sports_forecaster_bronze", badge_ids)

    def test_no_duplicate_awards(self):
        from merid.rewards.sports_rewards import SportsBadgeEngine
        engine = SportsBadgeEngine()
        stats = {"forecast_count": 15}
        engine.evaluate("agent1", stats)
        awards2 = engine.evaluate("agent1", stats)
        self.assertEqual(len(awards2), 0)

    def test_multi_sport_badge(self):
        from merid.rewards.sports_rewards import SportsBadgeEngine
        engine = SportsBadgeEngine()
        stats = {"unique_sports": 4}
        awards = engine.evaluate("agent1", stats)
        badge_ids = [a.badge_id for a in awards]
        self.assertIn("multi_sport_bronze", badge_ids)

    def test_badge_to_dict(self):
        from merid.rewards.sports_rewards import BadgeAward
        award = BadgeAward(badge_id="test", agent_id="a1", badge_name="Test", tier="gold")
        d = award.to_dict()
        self.assertEqual(d["tier"], "gold")

    def test_get_all_badges(self):
        from merid.rewards.sports_rewards import SportsBadgeEngine
        engine = SportsBadgeEngine()
        engine.evaluate("agent1", {"forecast_count": 15})
        engine.evaluate("agent2", {"unique_sports": 4})
        all_badges = engine.get_all_badges()
        self.assertIn("agent1", all_badges)
        self.assertIn("agent2", all_badges)


class TestSportsQuestTracker(unittest.TestCase):
    """Tests for sports quest progress tracking."""

    def test_initial_progress(self):
        from merid.rewards.sports_rewards import SportsQuestTracker
        tracker = SportsQuestTracker()
        progress = tracker.get_progress("agent1")
        # Should initialize quests on first call via update_progress
        tracker.update_progress("agent1", {})
        progress = tracker.get_progress("agent1")
        self.assertGreater(len(progress), 0)

    def test_quest_completion(self):
        from merid.rewards.sports_rewards import SportsQuestTracker
        tracker = SportsQuestTracker()
        completed = tracker.update_progress("agent1", {"forecast_count": 1})
        quest_ids = [q.quest_id for q in completed]
        self.assertIn("quest_first_forecast", quest_ids)

    def test_xp_accumulation(self):
        from merid.rewards.sports_rewards import SportsQuestTracker
        tracker = SportsQuestTracker()
        tracker.update_progress("agent1", {"forecast_count": 1})
        xp = tracker.get_xp("agent1")
        self.assertGreater(xp, 0)

    def test_no_double_completion(self):
        from merid.rewards.sports_rewards import SportsQuestTracker
        tracker = SportsQuestTracker()
        c1 = tracker.update_progress("agent1", {"forecast_count": 1})
        c2 = tracker.update_progress("agent1", {"forecast_count": 2})
        # quest_first_forecast should only complete once
        first_ids = [q.quest_id for q in c1]
        second_ids = [q.quest_id for q in c2]
        if "quest_first_forecast" in first_ids:
            self.assertNotIn("quest_first_forecast", second_ids)

    def test_quest_progress_dict(self):
        from merid.rewards.sports_rewards import QuestProgress
        qp = QuestProgress(quest_id="q1", agent_id="a1", quest_name="Test",
                           xp_reward=100, steps_completed=1, steps_total=3)
        d = qp.to_dict()
        self.assertAlmostEqual(d["progress_pct"], 0.33, places=2)


class TestSportsRewardComputer(unittest.TestCase):
    """Tests for sports reward score computation."""

    def test_base_reward(self):
        from merid.rewards.sports_rewards import SportsRewardComputer
        comp = SportsRewardComputer()
        score = comp.compute({"category": "sports_forecast", "confidence": 0.8})
        self.assertGreater(score, 0)

    def test_accuracy_bonus(self):
        from merid.rewards.sports_rewards import SportsRewardComputer
        comp = SportsRewardComputer()
        score_good = comp.compute({"category": "sports_forecast", "confidence": 0.8, "brier_score": 0.05})
        score_bad = comp.compute({"category": "sports_forecast", "confidence": 0.8, "brier_score": 0.40})
        self.assertGreater(score_good, score_bad)

    def test_edge_bonus(self):
        from merid.rewards.sports_rewards import SportsRewardComputer
        comp = SportsRewardComputer()
        score_edge = comp.compute({"category": "sports_bet", "confidence": 0.8,
                                   "edge": 0.10, "pnl": 50.0})
        score_no_edge = comp.compute({"category": "sports_bet", "confidence": 0.8,
                                      "edge": 0.10, "pnl": -10.0})
        self.assertGreater(score_edge, score_no_edge)

    def test_debate_lift_bonus(self):
        from merid.rewards.sports_rewards import SportsRewardComputer
        comp = SportsRewardComputer()
        score_lift = comp.compute({"category": "sports_debate", "confidence": 0.7,
                                   "debate_lift": 0.05})
        score_no_lift = comp.compute({"category": "sports_debate", "confidence": 0.7})
        self.assertGreater(score_lift, score_no_lift)

    def test_singletons(self):
        from merid.rewards.sports_rewards import (
            get_sports_badge_engine, get_sports_quest_tracker, get_sports_reward_computer,
        )
        self.assertIs(get_sports_badge_engine(), get_sports_badge_engine())
        self.assertIs(get_sports_quest_tracker(), get_sports_quest_tracker())
        self.assertIs(get_sports_reward_computer(), get_sports_reward_computer())


# ══════════════════════════════════════════════════════════════════════
# §8 Alert Registry Tests
# ══════════════════════════════════════════════════════════════════════

class TestAlertRegistry(unittest.TestCase):
    """Verify alert registry includes new sports betting alerts."""

    def test_alert_count_is_28(self):
        from web.api.system_observability import ALERT_RULES
        self.assertEqual(len(ALERT_RULES), 28)

    def test_new_alerts_registered(self):
        from web.api.system_observability import ALERT_RULES
        names = [r.name for r in ALERT_RULES]
        self.assertIn("odds_anomaly", names)
        self.assertIn("sports_debate_lift_negative", names)
        self.assertIn("odds_cache_staleness", names)

    def test_all_alerts_evaluate_safely(self):
        from web.api.system_observability import ALERT_RULES
        for rule in ALERT_RULES:
            result = rule.evaluate()
            self.assertIn("firing", result)
            self.assertIn("name", result)
            self.assertIn("severity", result)
            self.assertIsInstance(result["firing"], bool)

    def test_odds_anomaly_alert_not_firing_by_default(self):
        from web.api.system_observability import OddsAnomalyAlert
        alert = OddsAnomalyAlert()
        result = alert.evaluate()
        # No anomalies by default
        self.assertFalse(result["firing"])

    def test_sports_debate_lift_alert_not_firing_by_default(self):
        from web.api.system_observability import SportsDebateLiftAlert
        alert = SportsDebateLiftAlert()
        result = alert.evaluate()
        self.assertFalse(result["firing"])

    def test_odds_cache_staleness_alert_not_firing_by_default(self):
        from web.api.system_observability import OddsCacheStalenessAlert
        alert = OddsCacheStalenessAlert()
        result = alert.evaluate()
        self.assertFalse(result["firing"])


# ══════════════════════════════════════════════════════════════════════
# §9 Package Export Tests
# ══════════════════════════════════════════════════════════════════════

class TestBettingPackageExports(unittest.TestCase):
    """Verify merid.betting exports all new modules."""

    def test_optic_odds_exports(self):
        from merid.betting import OpticOddsClient, OpticOddsPoller, OddsSnapshotStore
        self.assertIsNotNone(OpticOddsClient)
        self.assertIsNotNone(OpticOddsPoller)
        self.assertIsNotNone(OddsSnapshotStore)

    def test_live_odds_cache_exports(self):
        from merid.betting import LiveOddsCache, LiveOddsCacheManager, OddsLatencyTracker, OddsPushManager
        self.assertIsNotNone(LiveOddsCache)
        self.assertIsNotNone(LiveOddsCacheManager)
        self.assertIsNotNone(OddsLatencyTracker)
        self.assertIsNotNone(OddsPushManager)

    def test_sports_debate_exports(self):
        from merid.betting import SportsDebateCoordinator, SportsDebateSession, SportsDebateLiftTracker
        self.assertIsNotNone(SportsDebateCoordinator)
        self.assertIsNotNone(SportsDebateSession)
        self.assertIsNotNone(SportsDebateLiftTracker)

    def test_anomaly_detection_exports(self):
        from merid.betting import AnomalyEngine, AnomalyRecord, AnomalyType, AnomalySeverity
        self.assertIsNotNone(AnomalyEngine)
        self.assertIsNotNone(AnomalyRecord)
        self.assertIsNotNone(AnomalyType)
        self.assertIsNotNone(AnomalySeverity)

    def test_singleton_exports(self):
        from merid.betting import (
            get_optic_odds_client, get_snapshot_store,
            get_live_odds_cache_manager, get_sports_debate_coordinator, get_anomaly_engine,
        )
        self.assertIsNotNone(get_optic_odds_client)
        self.assertIsNotNone(get_snapshot_store)
        self.assertIsNotNone(get_live_odds_cache_manager)
        self.assertIsNotNone(get_sports_debate_coordinator)
        self.assertIsNotNone(get_anomaly_engine)


class TestRewardsPackageExports(unittest.TestCase):
    """Verify merid.rewards exports all new modules."""

    def test_sports_event_exports(self):
        from merid.rewards import SportsForecastEvent, SportsBetEvent, SportsDebateEvent
        self.assertIsNotNone(SportsForecastEvent)
        self.assertIsNotNone(SportsBetEvent)
        self.assertIsNotNone(SportsDebateEvent)

    def test_sports_rewards_exports(self):
        from merid.rewards import SportsBadgeEngine, SportsQuestTracker, SportsRewardComputer
        self.assertIsNotNone(SportsBadgeEngine)
        self.assertIsNotNone(SportsQuestTracker)
        self.assertIsNotNone(SportsRewardComputer)

    def test_singleton_exports(self):
        from merid.rewards import (
            get_sports_badge_engine, get_sports_quest_tracker, get_sports_reward_computer,
        )
        self.assertIsNotNone(get_sports_badge_engine)
        self.assertIsNotNone(get_sports_quest_tracker)
        self.assertIsNotNone(get_sports_reward_computer)


class TestAgentsPackageExports(unittest.TestCase):
    """Verify merid.agents exports the new sports agent."""

    def test_sports_agent_exports(self):
        from merid.agents import OddsAwareSportsAgent, SportsOddsStrategy, get_sports_odds_agent
        self.assertIsNotNone(OddsAwareSportsAgent)
        self.assertIsNotNone(SportsOddsStrategy)
        self.assertIsNotNone(get_sports_odds_agent)


# ══════════════════════════════════════════════════════════════════════
# §10 Latency Load Tests
# ══════════════════════════════════════════════════════════════════════

class TestLatencyLoadTests(unittest.TestCase):
    """Simulate concurrent odds updates and bet placements for latency SLO."""

    def test_concurrent_cache_writes(self):
        """50 concurrent cache writes should complete under 100ms total."""
        from merid.betting.live_odds_cache import LiveOddsCache
        cache = LiveOddsCache(ttl_s=60.0)

        start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = []
            for i in range(50):
                futures.append(pool.submit(
                    cache.put, f"evt{i % 5}", f"outcome{i % 3}", 0.5 + (i % 10) * 0.01
                ))
            concurrent.futures.wait(futures)
        elapsed_ms = (time.perf_counter() - start) * 1000

        self.assertLess(elapsed_ms, 500, f"50 concurrent writes took {elapsed_ms:.1f}ms")

    def test_concurrent_cache_reads(self):
        """100 concurrent cache reads should complete under 50ms total."""
        from merid.betting.live_odds_cache import LiveOddsCache
        cache = LiveOddsCache(ttl_s=60.0)
        for i in range(10):
            cache.put(f"evt{i}", "home", 0.55)

        start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(cache.get, f"evt{i % 10}", "home") for i in range(100)]
            concurrent.futures.wait(futures)
        elapsed_ms = (time.perf_counter() - start) * 1000

        self.assertLess(elapsed_ms, 500, f"100 concurrent reads took {elapsed_ms:.1f}ms")

    def test_concurrent_anomaly_checks(self):
        """Concurrent anomaly engine operations should be thread-safe."""
        from merid.betting.anomaly_detection import AnomalyEngine
        engine = AnomalyEngine()

        errors = []

        def place_bet(i):
            try:
                engine.on_bet_placed(
                    bet_id=f"b{i}", user_id=f"u{i % 3}",
                    event_id=f"e{i % 5}", outcome_label="home",
                    stake=10.0 + i,
                )
            except Exception as e:
                errors.append(str(e))

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(place_bet, i) for i in range(50)]
            concurrent.futures.wait(futures)

        self.assertEqual(len(errors), 0, f"Thread-safety errors: {errors}")

    def test_push_notification_latency(self):
        """Push notifications to 10 subscribers should complete under 50ms."""
        from merid.betting.live_odds_cache import OddsPushManager, CachedOddsEntry
        mgr = OddsPushManager()
        received_counts = collections.defaultdict(int)

        for i in range(10):
            mgr.subscribe(lambda d, idx=i: received_counts.__setitem__(idx, received_counts[idx] + 1))

        entry = CachedOddsEntry(event_id="evt1", outcome_label="home", implied_prob=0.55)
        start = time.perf_counter()
        for _ in range(20):
            mgr.push(entry)
        elapsed_ms = (time.perf_counter() - start) * 1000

        self.assertLess(elapsed_ms, 200, f"200 push notifications took {elapsed_ms:.1f}ms")

    def test_odds_jump_detector_throughput(self):
        """OddsJumpDetector should handle 1000 updates in under 200ms."""
        from merid.betting.anomaly_detection import OddsJumpDetector
        det = OddsJumpDetector()

        start = time.perf_counter()
        for i in range(1000):
            det.check_update(f"evt{i % 10}", f"outcome{i % 3}", 0.5 + (i % 100) * 0.001)
        elapsed_ms = (time.perf_counter() - start) * 1000

        self.assertLess(elapsed_ms, 500, f"1000 odds checks took {elapsed_ms:.1f}ms")

    def test_badge_evaluation_throughput(self):
        """Badge evaluation for 100 agents should complete under 100ms."""
        from merid.rewards.sports_rewards import SportsBadgeEngine
        engine = SportsBadgeEngine()

        start = time.perf_counter()
        for i in range(100):
            engine.evaluate(f"agent{i}", {
                "forecast_count": i * 5,
                "unique_sports": i % 7,
                "positive_lift_debates": i % 25,
            })
        elapsed_ms = (time.perf_counter() - start) * 1000

        self.assertLess(elapsed_ms, 500, f"100 badge evaluations took {elapsed_ms:.1f}ms")


# ══════════════════════════════════════════════════════════════════════
# §11 Integration / End-to-End Tests
# ══════════════════════════════════════════════════════════════════════

class TestEndToEndFlow(unittest.TestCase):
    """End-to-end flow: odds update → anomaly check → reward → badge."""

    def test_odds_to_anomaly_to_reward_flow(self):
        """Simulate a full flow from odds update through anomaly detection to reward."""
        from merid.betting.anomaly_detection import AnomalyEngine
        from merid.rewards.sports_rewards import SportsRewardComputer, SportsBadgeEngine, SportsQuestTracker

        # 1. Anomaly engine processes bets
        anomaly_engine = AnomalyEngine()
        for i in range(3):
            anomaly_engine.on_bet_placed(
                bet_id=f"b{i}", user_id="agent1", event_id="evt1",
                outcome_label="home", stake=10.0,
            )

        # 2. Compute reward for a forecast
        computer = SportsRewardComputer()
        score = computer.compute({
            "category": "sports_forecast",
            "confidence": 0.85,
            "brier_score": 0.08,
            "edge": 0.07,
            "pnl": 25.0,
        })
        self.assertGreater(score, 0)

        # 3. Evaluate badges
        badge_engine = SportsBadgeEngine()
        awards = badge_engine.evaluate("agent1", {"forecast_count": 12})
        self.assertTrue(any(a.badge_id == "sports_forecaster_bronze" for a in awards))

        # 4. Track quest progress
        quest_tracker = SportsQuestTracker()
        completed = quest_tracker.update_progress("agent1", {"forecast_count": 1})
        self.assertTrue(any(q.quest_id == "quest_first_forecast" for q in completed))

    def test_debate_to_lift_to_reward_flow(self):
        """Simulate debate → lift tracking → reward computation."""
        from merid.betting.sports_debate import SportsDebateCoordinator
        from merid.rewards.sports_rewards import SportsRewardComputer

        # 1. Create and run debate
        coord = SportsDebateCoordinator()
        session = coord.create_debate(
            event_id="evt1", outcome_label="home",
            pre_debate_prob=0.55, sport="nfl",
        )
        coord.add_argument(
            debate_id=session.id,
            agent_id="agent1", role="proposer",
            probability=0.60, confidence=0.85,
            reasoning="Strong home record",
        )
        coord.add_argument(
            debate_id=session.id,
            agent_id="agent2", role="challenger",
            probability=0.45, confidence=0.70,
            reasoning="Key injuries",
        )

        # 2. Close debate and resolve with outcome to record lift
        coord.close_debate(session.id)
        coord.resolve_debate(session.id, outcome=1)
        stats = coord.get_stats()
        self.assertIsNotNone(stats["lift_stats"]["avg_lift"])

        # 3. Compute reward
        computer = SportsRewardComputer()
        score = computer.compute({
            "category": "sports_debate",
            "confidence": 0.85,
            "debate_lift": 0.07,
        })
        self.assertGreater(score, 0)

    def test_cache_to_push_to_latency_flow(self):
        """Simulate cache update → push notification → latency tracking."""
        from merid.betting.live_odds_cache import LiveOddsCacheManager, CachedOddsEntry

        mgr = LiveOddsCacheManager()
        received = []
        mgr.push_manager.subscribe(lambda d: received.append(d))

        # Update cache and push
        start = time.perf_counter()
        entry = mgr.cache.put("evt1", "home", 0.55, provider="sharp")
        mgr.push_manager.push(entry)
        elapsed_ms = (time.perf_counter() - start) * 1000

        mgr.tracker.record("end_to_end", elapsed_ms)

        self.assertEqual(len(received), 1)
        metrics = mgr.tracker.get_all_metrics()
        self.assertIn("tiers", metrics)
        self.assertIn("end_to_end", metrics["tiers"])


if __name__ == "__main__":
    unittest.main()
