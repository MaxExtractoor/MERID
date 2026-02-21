"""Tests for the Signal Layer — decay, features, arbs, drift, CQI, store, API.

Test classes:
  TestDecayMath           — core decay utilities
  TestDecayEnvelope       — envelope creation and freshness
  TestSignalSnapshot      — snapshot aggregation
  TestNewsFeatures        — news feature service with decay
  TestMacroFeatures       — macro feature service
  TestOnChainFeatures     — on-chain feature service
  TestSocialFeatures      — social feature service with fast decay
  TestFeatureService      — unified feature facade + snapshot builder
  TestDislocationScanner  — arb/dislocation detection
  TestArbPlan             — arb plan TTL and validity
  TestSignalStore         — SQLite persistence
  TestDriftDetector       — drift metrics and CQI computation
  TestCQI                 — Consensus Quality Index classification
  TestSignalLayerAPI      — REST API endpoints
"""

import math
import time
import unittest
from unittest.mock import patch

# ── §1 Decay math tests ──────────────────────────────────────────────

from merid.signals.decay import (
    DecayConfig,
    DecayEnvelope,
    SignalDomain,
    SignalSnapshot,
    decay_weight,
    decay_weight_at,
    decay_weight_from_config,
    filter_fresh,
    get_decay_config,
    is_stale,
    weighted_average,
    weighted_sum,
    DEFAULT_DECAY_CONFIGS,
)


class TestDecayMath(unittest.TestCase):
    """Core decay math: exponential decay, clamping, cutoff."""

    def test_fresh_signal_weight_is_one(self):
        self.assertAlmostEqual(decay_weight(0, tau_seconds=3600), 1.0)

    def test_at_tau_weight_is_approx_037(self):
        w = decay_weight(3600, tau_seconds=3600)
        self.assertAlmostEqual(w, math.exp(-1), places=3)

    def test_very_old_signal_hits_min_weight(self):
        w = decay_weight(50000, tau_seconds=3600, min_weight=0.05, max_age_seconds=86400)
        self.assertGreaterEqual(w, 0.05)

    def test_beyond_max_age_returns_zero(self):
        w = decay_weight(100000, tau_seconds=3600, max_age_seconds=86400)
        self.assertEqual(w, 0.0)

    def test_negative_age_returns_one(self):
        self.assertEqual(decay_weight(-100, tau_seconds=3600), 1.0)

    def test_decay_monotonically_decreasing(self):
        weights = [decay_weight(i * 100, tau_seconds=1000) for i in range(10)]
        for i in range(1, len(weights)):
            self.assertLessEqual(weights[i], weights[i - 1])

    def test_min_weight_floor(self):
        w = decay_weight(20000, tau_seconds=1000, min_weight=0.10, max_age_seconds=50000)
        self.assertGreaterEqual(w, 0.10)

    def test_from_config(self):
        cfg = DecayConfig(domain="test", tau_seconds=600, min_weight=0.05, max_age_seconds=7200)
        w = decay_weight_from_config(600, cfg)
        self.assertAlmostEqual(w, math.exp(-1), places=3)

    def test_config_to_dict(self):
        cfg = DecayConfig(domain="social", tau_seconds=600)
        d = cfg.to_dict()
        self.assertEqual(d["domain"], "social")
        self.assertEqual(d["tau_seconds"], 600)

    def test_default_configs_exist_for_all_domains(self):
        for domain in SignalDomain:
            cfg = get_decay_config(domain.value)
            self.assertEqual(cfg.domain, domain.value)
            self.assertGreater(cfg.tau_seconds, 0)

    def test_social_decays_faster_than_macro(self):
        social_cfg = get_decay_config("social")
        macro_cfg = get_decay_config("macro")
        self.assertLess(social_cfg.tau_seconds, macro_cfg.tau_seconds)

    def test_arb_decays_fastest(self):
        arb_cfg = get_decay_config("arb")
        for domain in SignalDomain:
            if domain.value != "arb":
                other = get_decay_config(domain.value)
                self.assertLessEqual(arb_cfg.tau_seconds, other.tau_seconds)

    def test_decay_weight_at_timestamp(self):
        now = time.time()
        w = decay_weight_at(now - 600, "social", now)
        self.assertGreater(w, 0)
        self.assertLess(w, 1.0)

    def test_is_stale_for_old_signal(self):
        now = time.time()
        self.assertTrue(is_stale(now - 100000, "news", now))

    def test_is_not_stale_for_fresh_signal(self):
        now = time.time()
        self.assertFalse(is_stale(now - 1, "macro", now))


class TestDecayEnvelope(unittest.TestCase):
    """DecayEnvelope wraps values with decay metadata."""

    def test_create_fresh_envelope(self):
        now = time.time()
        env = DecayEnvelope.create(0.75, now - 10, "news", "test", now)
        self.assertGreater(env.decay_weight, 0.9)
        self.assertAlmostEqual(env.raw_value, 0.75)
        self.assertFalse(env.is_stale)

    def test_create_stale_envelope(self):
        now = time.time()
        env = DecayEnvelope.create(0.5, now - 50000, "social", "test", now)
        self.assertTrue(env.is_stale)
        self.assertEqual(env.decay_weight, 0.0)  # beyond max_age for social

    def test_value_is_raw_times_weight(self):
        now = time.time()
        env = DecayEnvelope.create(1.0, now, "news", "test", now)
        self.assertAlmostEqual(env.value, env.raw_value * env.decay_weight, places=4)

    def test_to_dict_has_all_fields(self):
        env = DecayEnvelope.create(0.5, time.time(), "news", "sentiment")
        d = env.to_dict()
        for key in ["value", "raw_value", "timestamp", "age_seconds", "decay_weight", "domain", "label", "is_stale"]:
            self.assertIn(key, d)

    def test_envelope_with_metadata(self):
        env = DecayEnvelope.create(1.0, time.time(), "macro", "cpi", metadata={"release": "2026-02"})
        self.assertEqual(env.metadata["release"], "2026-02")


class TestSignalSnapshot(unittest.TestCase):
    """SignalSnapshot groups driver signals for opinion/plan metadata."""

    def _make_snapshot(self):
        now = time.time()
        signals = [
            DecayEnvelope.create(0.7, now - 60, "news", "news_sent", now),
            DecayEnvelope.create(0.3, now - 5, "social", "social_sent", now),
            DecayEnvelope.create(0.5, now - 7200, "macro", "macro_cpi", now),
        ]
        return SignalSnapshot(snapshot_id="test-snap", timestamp=now, signals=signals)

    def test_avg_freshness(self):
        snap = self._make_snapshot()
        f = snap.avg_freshness()
        self.assertGreater(f, 0)
        self.assertLessEqual(f, 1.0)

    def test_stale_count(self):
        snap = self._make_snapshot()
        self.assertIsInstance(snap.stale_count(), int)

    def test_freshest_signal(self):
        snap = self._make_snapshot()
        freshest = snap.freshest_signal()
        self.assertIsNotNone(freshest)
        for s in snap.signals:
            self.assertGreaterEqual(freshest.decay_weight, s.decay_weight)

    def test_stalest_signal(self):
        snap = self._make_snapshot()
        stalest = snap.stalest_signal()
        self.assertIsNotNone(stalest)

    def test_empty_snapshot(self):
        snap = SignalSnapshot()
        self.assertEqual(snap.avg_freshness(), 0.0)
        self.assertIsNone(snap.freshest_signal())

    def test_to_dict(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        self.assertIn("signal_count", d)
        self.assertIn("avg_freshness", d)
        self.assertEqual(d["signal_count"], 3)


class TestWeightedAggregation(unittest.TestCase):

    def test_weighted_average(self):
        now = time.time()
        envs = [
            DecayEnvelope.create(1.0, now, "news", "a", now),
            DecayEnvelope.create(0.0, now, "news", "b", now),
        ]
        avg = weighted_average(envs)
        self.assertAlmostEqual(avg, 0.5, places=2)

    def test_weighted_sum(self):
        now = time.time()
        envs = [
            DecayEnvelope.create(1.0, now, "news", "a", now),
            DecayEnvelope.create(2.0, now, "news", "b", now),
        ]
        total = weighted_sum(envs)
        self.assertAlmostEqual(total, 3.0, places=1)

    def test_filter_fresh(self):
        now = time.time()
        envs = [
            DecayEnvelope.create(1.0, now, "news", "a", now),
            DecayEnvelope.create(1.0, now - 100000, "social", "b", now),
        ]
        fresh = filter_fresh(envs)
        self.assertEqual(len(fresh), 1)

    def test_empty_weighted_average(self):
        self.assertEqual(weighted_average([]), 0.0)


# ── §2 Feature service tests ─────────────────────────────────────────

from merid.signals.features import (
    FeatureService,
    FeatureSet,
    NewsFeatureService,
    MacroFeatureService,
    OnChainFeatureService,
    SocialFeatureService,
)


class TestNewsFeatures(unittest.TestCase):

    def test_synthetic_features_return_feature_set(self):
        svc = NewsFeatureService()
        fs = svc.get_news_features("BTC")
        self.assertIsInstance(fs, FeatureSet)
        self.assertEqual(fs.domain, "news")
        self.assertIn("sentiment", fs.features)
        self.assertIn("article_count", fs.features)

    def test_ingested_data_preferred(self):
        svc = NewsFeatureService()
        now = time.time()
        svc.ingest("ETH", 0.8, "ETH bullish", now - 60)
        svc.ingest("ETH", 0.6, "ETH rally", now - 30)
        fs = svc.get_news_features("ETH", now=now)
        self.assertEqual(fs.source, "live")
        sent = fs.features["sentiment"]
        self.assertGreater(sent.raw_value, 0)

    def test_feature_set_to_dict(self):
        svc = NewsFeatureService()
        fs = svc.get_news_features("SOL")
        d = fs.to_dict()
        self.assertIn("features", d)
        self.assertIn("avg_freshness", d)

    def test_avg_freshness_decreases_with_age(self):
        svc = NewsFeatureService()
        now = time.time()
        svc.ingest("OLD", 0.5, "old news", now - 10000)
        fs = svc.get_news_features("OLD", now=now)
        self.assertLess(fs.avg_freshness(), 0.9)


class TestMacroFeatures(unittest.TestCase):

    def test_synthetic_macro(self):
        svc = MacroFeatureService()
        fs = svc.get_macro_features()
        self.assertEqual(fs.domain, "macro")
        self.assertIn("surprise_avg", fs.features)

    def test_ingested_macro(self):
        svc = MacroFeatureService()
        now = time.time()
        svc.ingest("cpi", 1.5, "CPI beat", now - 3600)
        fs = svc.get_macro_features("cpi", now=now)
        self.assertEqual(fs.source, "live")


class TestOnChainFeatures(unittest.TestCase):

    def test_synthetic_onchain(self):
        svc = OnChainFeatureService()
        fs = svc.get_onchain_features("ethereum", "ETH")
        self.assertEqual(fs.domain, "onchain")
        self.assertIn("whale_flow_usd", fs.features)

    def test_ingested_onchain(self):
        svc = OnChainFeatureService()
        now = time.time()
        svc.ingest("solana", "SOL", {"whale_flow_usd": 100000, "tvl_change_pct": 2.5}, now - 300)
        fs = svc.get_onchain_features("solana", "SOL", now=now)
        self.assertEqual(fs.source, "live")


class TestSocialFeatures(unittest.TestCase):

    def test_synthetic_social(self):
        svc = SocialFeatureService()
        fs = svc.get_social_features("DOGE")
        self.assertEqual(fs.domain, "social")
        self.assertIn("sentiment", fs.features)
        self.assertIn("attention_score", fs.features)
        self.assertIn("hype_spike", fs.features)
        self.assertIn("kol_ratio", fs.features)

    def test_hype_spike_detection(self):
        svc = SocialFeatureService()
        now = time.time()
        # Inject many positive social signals
        for i in range(10):
            svc.ingest("HYPE", 0.8, 500, 50000, True, now - i * 10)
        fs = svc.get_social_features("HYPE", window_seconds=300, now=now)
        hype = fs.features["hype_spike"]
        self.assertEqual(hype.raw_value, 1.0)

    def test_kol_ratio(self):
        svc = SocialFeatureService()
        now = time.time()
        svc.ingest("KOL", 0.5, 100, 50000, True, now - 10)
        svc.ingest("KOL", 0.3, 50, 500, False, now - 20)
        fs = svc.get_social_features("KOL", now=now)
        kol = fs.features["kol_ratio"]
        self.assertGreater(kol.raw_value, 0)

    def test_social_decay_is_fast(self):
        svc = SocialFeatureService()
        now = time.time()
        svc.ingest("DECAY", 0.9, 100, 1000, False, now - 3000)  # 50 min ago
        fs = svc.get_social_features("DECAY", now=now)
        sent = fs.features["sentiment"]
        # Social tau = 600s, so 3000s = 5*tau → very decayed
        self.assertLess(sent.decay_weight, 0.1)


class TestFeatureService(unittest.TestCase):

    def test_unified_facade(self):
        svc = FeatureService()
        news = svc.get_news_features("BTC")
        self.assertIsInstance(news, FeatureSet)
        social = svc.get_social_features("BTC")
        self.assertIsInstance(social, FeatureSet)

    def test_build_snapshot(self):
        svc = FeatureService()
        snap = svc.build_snapshot("ETH")
        self.assertIsInstance(snap, SignalSnapshot)
        self.assertGreater(len(snap.signals), 0)
        self.assertIn("news", snap.summary)
        self.assertIn("social", snap.summary)

    def test_snapshot_to_dict(self):
        svc = FeatureService()
        snap = svc.build_snapshot("SOL")
        d = snap.to_dict()
        self.assertIn("signals", d)
        self.assertIn("avg_freshness", d)


# ── §4 Arb/Dislocation tests ─────────────────────────────────────────

from merid.signals.arbitrage import (
    ArbLeg,
    ArbPlan,
    ArbType,
    DislocationScanner,
    DislocationSignal,
    DislocationStatus,
    VenuePrice,
)


class TestDislocationScanner(unittest.TestCase):

    def _make_scanner(self):
        return DislocationScanner(min_gross_edge_bps=10.0, default_ttl=120.0)

    def test_ingest_price(self):
        scanner = self._make_scanner()
        scanner.ingest_price(VenuePrice(venue="binance", symbol="BTC", bid=43000, ask=43010, mid=43005))
        self.assertIn("BTC", scanner._prices)

    def test_no_arb_with_single_venue(self):
        scanner = self._make_scanner()
        scanner.ingest_price(VenuePrice(venue="binance", symbol="BTC", bid=43000, ask=43010, mid=43005))
        signals = scanner.scan()
        self.assertEqual(len(signals), 0)

    def test_detect_dislocation(self):
        scanner = self._make_scanner()
        now = time.time()
        scanner.ingest_price(VenuePrice(venue="binance", symbol="BTC", bid=43000, ask=43010, mid=43005, timestamp=now, liquidity_usd=100000, fees_bps=10))
        scanner.ingest_price(VenuePrice(venue="coinbase", symbol="BTC", bid=43100, ask=43110, mid=43105, timestamp=now, liquidity_usd=100000, fees_bps=15))
        signals = scanner.scan(now)
        self.assertGreater(len(signals), 0)
        sig = signals[0]
        self.assertGreater(sig.gross_edge_bps, 0)

    def test_signal_expiration(self):
        scanner = self._make_scanner()
        now = time.time()
        sig = DislocationSignal(detected_at=now - 200, ttl_seconds=120)
        self.assertTrue(sig.is_expired(now))
        self.assertFalse(sig.is_actionable(now))

    def test_signal_to_dict(self):
        sig = DislocationSignal(symbol="ETH", gross_edge_bps=25, net_edge_bps=15)
        d = sig.to_dict()
        self.assertEqual(d["symbol"], "ETH")
        self.assertIn("is_actionable", d)
        self.assertIn("decay_weight", d)

    def test_synthetic_scan(self):
        scanner = self._make_scanner()
        signals = scanner.synthetic_scan()
        # May or may not find arbs depending on random prices
        self.assertIsInstance(signals, list)

    def test_metrics(self):
        scanner = self._make_scanner()
        m = scanner.get_metrics()
        self.assertIn("total_signals", m)
        self.assertIn("active_signals", m)

    def test_stale_prices_ignored(self):
        scanner = self._make_scanner()
        now = time.time()
        scanner.ingest_price(VenuePrice(venue="a", symbol="X", bid=100, ask=101, mid=100.5, timestamp=now - 600))
        scanner.ingest_price(VenuePrice(venue="b", symbol="X", bid=110, ask=111, mid=110.5, timestamp=now - 600))
        signals = scanner.scan(now)
        self.assertEqual(len(signals), 0)  # prices too old


class TestArbPlan(unittest.TestCase):

    def test_plan_valid_within_ttl(self):
        now = time.time()
        plan = ArbPlan(created_at=now, ttl_seconds=120, min_required_edge_bps=10, expected_edge_bps=20)
        self.assertTrue(plan.is_valid(20, now))

    def test_plan_invalid_after_ttl(self):
        now = time.time()
        plan = ArbPlan(created_at=now - 200, ttl_seconds=120)
        self.assertFalse(plan.is_valid(20, now))

    def test_plan_invalid_below_edge(self):
        now = time.time()
        plan = ArbPlan(created_at=now, ttl_seconds=120, min_required_edge_bps=10)
        self.assertFalse(plan.is_valid(5, now))

    def test_plan_expire(self):
        plan = ArbPlan()
        plan.expire()
        self.assertEqual(plan.status, "expired")

    def test_build_arb_plan(self):
        scanner = DislocationScanner()
        now = time.time()
        sig = DislocationSignal(
            symbol="BTC", detected_at=now, ttl_seconds=120,
            net_edge_bps=30, min_edge_bps=10,
            venues=[
                VenuePrice(venue="a", symbol="BTC", bid=43000, ask=43010, mid=43005),
                VenuePrice(venue="b", symbol="BTC", bid=43100, ask=43110, mid=43105),
            ],
        )
        plan = scanner.build_arb_plan(sig, size_usd=5000)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.legs), 2)
        self.assertEqual(plan.total_size_usd, 5000)

    def test_validate_plans_expires_old(self):
        scanner = DislocationScanner()
        now = time.time()
        plan = ArbPlan(created_at=now - 300, ttl_seconds=120, status="proposed")
        scanner._plans.append(plan)
        scanner.validate_plans(now)
        self.assertEqual(plan.status, "expired")


# ── §5 SignalStore tests ──────────────────────────────────────────────

from merid.signals.store import SignalStore


class TestSignalStore(unittest.TestCase):

    def setUp(self):
        self.store = SignalStore(db_path=":memory:")

    def test_store_and_get_features(self):
        self.store.store_feature_snapshot({
            "symbol": "BTC", "domain": "news",
            "features": {"sentiment": 0.7}, "source": "live", "avg_freshness": 0.9,
        })
        rows = self.store.get_latest_features("BTC", "news")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "BTC")

    def test_store_and_get_snapshot(self):
        self.store.store_snapshot({
            "snapshot_id": "snap-1", "symbol": "ETH",
            "avg_freshness": 0.8, "stale_count": 0, "signal_count": 3,
        }, "opinion-1")
        rows = self.store.get_snapshots("opinion-1")
        self.assertEqual(len(rows), 1)

    def test_store_and_list_arb_signals(self):
        self.store.store_arb_signal({
            "signal_id": "arb-1", "domain": "crypto_cex", "arb_type": "pure_arb",
            "symbol": "BTC", "venues": [], "gross_edge_bps": 25,
            "net_edge_bps": 15, "edge_usd": 7.5, "status": "active",
            "detected_at": time.time(),
        })
        rows = self.store.list_arb_signals("active")
        self.assertEqual(len(rows), 1)

    def test_store_and_list_arb_plans(self):
        self.store.store_arb_plan({
            "plan_id": "plan-1", "signal_id": "arb-1", "domain": "crypto_cex",
            "arb_type": "pure_arb", "symbol": "BTC", "legs": [],
            "total_size_usd": 1000, "status": "proposed",
            "created_at": time.time(),
        })
        rows = self.store.list_arb_plans()
        self.assertEqual(len(rows), 1)

    def test_store_and_get_drift_metrics(self):
        self.store.store_drift_metric({
            "domain": "crypto", "window": "24h", "brier_score": 0.15,
            "decay_discipline": 0.8, "timestamp": time.time(),
        })
        rows = self.store.get_drift_metrics("crypto")
        self.assertEqual(len(rows), 1)

    def test_store_and_get_cqi(self):
        self.store.store_cqi({
            "domain": "crypto", "quality_index": 0.72, "band": "good",
            "brier_component": 0.8, "pnl_component": 0.6,
            "drift_component": 0.7, "decay_component": 0.75,
            "timestamp": time.time(),
        })
        rows = self.store.get_latest_cqi("crypto")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["quality_index"], 0.72)

    def test_cqi_history(self):
        now = time.time()
        for i in range(5):
            self.store.store_cqi({
                "domain": "prediction", "quality_index": 0.5 + i * 0.05,
                "band": "neutral", "timestamp": now + i,
            })
        history = self.store.get_cqi_history("prediction")
        self.assertEqual(len(history), 5)

    def test_signal_metrics(self):
        m = self.store.get_signal_metrics()
        self.assertIn("feature_snapshots", m)
        self.assertIn("arb_signals_total", m)
        self.assertIn("cqi_entries", m)


# ── §6 Drift / CQI tests ─────────────────────────────────────────────

from merid.signals.drift import (
    ConsensusQualityIndex,
    DomainDriftMetric,
    DriftDetector,
    classify_band,
)


class TestDriftDetector(unittest.TestCase):

    def test_record_and_compute_drift(self):
        det = DriftDetector()
        now = time.time()
        for i in range(20):
            det.record_outcome("crypto", 0.6, 1.0, 10.0, 0.8, now - i * 60)
        drift = det.compute_drift("crypto", now=now)
        self.assertEqual(drift.domain, "crypto")
        self.assertEqual(drift.trade_count, 20)
        self.assertGreater(drift.brier_score, 0)

    def test_empty_drift(self):
        det = DriftDetector()
        drift = det.compute_drift("empty")
        self.assertEqual(drift.trade_count, 0)

    def test_decay_discipline(self):
        det = DriftDetector()
        now = time.time()
        # 10 fresh, 10 stale
        for i in range(10):
            det.record_outcome("mixed", 0.5, 1.0, 5.0, 0.8, now - i * 10)  # fresh
        for i in range(10):
            det.record_outcome("mixed", 0.5, 0.0, -5.0, 0.1, now - i * 10)  # stale
        drift = det.compute_drift("mixed", now=now)
        self.assertAlmostEqual(drift.stale_trade_pct, 0.5, places=1)

    def test_psi_computation(self):
        det = DriftDetector()
        det.set_feature_baseline("crypto", {"sentiment": 0.5, "volume": 1000})
        psi = det.compute_psi("crypto", {"sentiment": 0.6, "volume": 1200})
        self.assertGreaterEqual(psi, 0)

    def test_psi_no_drift(self):
        det = DriftDetector()
        det.set_feature_baseline("crypto", {"sentiment": 0.5})
        psi = det.compute_psi("crypto", {"sentiment": 0.5})
        self.assertAlmostEqual(psi, 0, places=3)


class TestCQI(unittest.TestCase):

    def test_compute_cqi(self):
        det = DriftDetector()
        now = time.time()
        for i in range(20):
            det.record_outcome("test", 0.7, 1.0, 20.0, 0.85, now - i * 60)
        cqi = det.compute_cqi("test", now=now)
        self.assertIsInstance(cqi, ConsensusQualityIndex)
        self.assertGreater(cqi.quality_index, 0)
        self.assertIn(cqi.band, ("good", "neutral", "poor"))

    def test_classify_band_good(self):
        self.assertEqual(classify_band(0.75), "good")

    def test_classify_band_neutral(self):
        self.assertEqual(classify_band(0.50), "neutral")

    def test_classify_band_poor(self):
        self.assertEqual(classify_band(0.20), "poor")

    def test_cqi_to_dict(self):
        cqi = ConsensusQualityIndex(domain="crypto", quality_index=0.72, band="good")
        d = cqi.to_dict()
        self.assertEqual(d["band"], "good")
        self.assertIn("components", d)

    def test_risk_adjustments_poor_cqi(self):
        det = DriftDetector()
        now = time.time()
        # All bad predictions, stale signals
        for i in range(20):
            det.record_outcome("bad", 0.9, 0.0, -50.0, 0.1, now - i * 60)
        det.compute_cqi("bad", now=now)
        adj = det.get_risk_adjustments("bad")
        self.assertLess(adj["size_multiplier"], 1.0)

    def test_risk_adjustments_no_data(self):
        det = DriftDetector()
        adj = det.get_risk_adjustments("unknown")
        self.assertEqual(adj["size_multiplier"], 1.0)

    def test_all_cqi(self):
        det = DriftDetector()
        now = time.time()
        for d in ["crypto", "prediction"]:
            for i in range(10):
                det.record_outcome(d, 0.6, 1.0, 10.0, 0.7, now - i * 60)
            det.compute_cqi(d, now=now)
        all_cqi = det.get_all_cqi()
        self.assertEqual(len(all_cqi), 2)

    def test_drift_history(self):
        det = DriftDetector()
        now = time.time()
        for i in range(5):
            for j in range(5):
                det.record_outcome("hist", 0.5, 1.0, 5.0, 0.6, now - j * 60)
            det.compute_drift("hist", now=now + i)
        history = det.get_drift_history("hist")
        self.assertEqual(len(history), 5)

    def test_summary(self):
        det = DriftDetector()
        det.record_outcome("crypto", 0.5, 1.0, 10, 0.8)
        s = det.summary()
        self.assertIn("domains_tracked", s)
        self.assertIn("crypto", s["domains_tracked"])


class TestDomainDriftMetric(unittest.TestCase):

    def test_stale_trade_pct(self):
        m = DomainDriftMetric(stale_trade_count=3, fresh_trade_count=7)
        self.assertAlmostEqual(m.stale_trade_pct, 0.3)

    def test_to_dict(self):
        m = DomainDriftMetric(domain="crypto", brier_score=0.15)
        d = m.to_dict()
        self.assertEqual(d["domain"], "crypto")
        self.assertIn("decay_discipline", d)


# ── §8 API tests ──────────────────────────────────────────────────────

from fastapi.testclient import TestClient


class TestSignalLayerAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from web.api.signal_layer_api import signal_layer_router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(signal_layer_router)
        cls.client = TestClient(app)

    def test_get_features(self):
        r = self.client.get("/api/v1/signal-layer/features/BTC")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("news", data)
        self.assertIn("social", data)
        self.assertIn("onchain", data)

    def test_get_social(self):
        r = self.client.get("/api/v1/signal-layer/social/DOGE")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("features", data)
        self.assertEqual(data["domain"], "social")

    def test_get_macro(self):
        r = self.client.get("/api/v1/signal-layer/macro")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["domain"], "macro")

    def test_get_onchain(self):
        r = self.client.get("/api/v1/signal-layer/onchain/ethereum/ETH")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["domain"], "onchain")

    def test_get_snapshot(self):
        r = self.client.get("/api/v1/signal-layer/snapshot/SOL")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("signals", data)
        self.assertIn("avg_freshness", data)

    def test_get_arbs(self):
        r = self.client.get("/api/v1/signal-layer/arbs")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("signals", data)
        self.assertIn("metrics", data)

    def test_get_arb_plans(self):
        r = self.client.get("/api/v1/signal-layer/arb-plans")
        self.assertEqual(r.status_code, 200)
        self.assertIn("plans", r.json())

    def test_scan_arbs(self):
        r = self.client.post("/api/v1/signal-layer/scan-arbs")
        self.assertEqual(r.status_code, 200)
        self.assertIn("status", r.json())

    def test_get_cqi(self):
        r = self.client.get("/api/v1/signal-layer/cqi")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("domains", data)

    def test_get_cqi_domain(self):
        # Trigger CQI computation first
        self.client.post("/api/v1/signal-layer/compute-cqi?domain=crypto")
        r = self.client.get("/api/v1/signal-layer/cqi/crypto")
        self.assertEqual(r.status_code, 200)
        self.assertIn("history", r.json())

    def test_compute_cqi(self):
        r = self.client.post("/api/v1/signal-layer/compute-cqi?domain=prediction")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("cqi", data)

    def test_get_drift(self):
        r = self.client.get("/api/v1/signal-layer/drift")
        self.assertEqual(r.status_code, 200)

    def test_get_decay_configs(self):
        r = self.client.get("/api/v1/signal-layer/decay-configs")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("news", data)
        self.assertIn("social", data)
        self.assertIn("arb", data)

    def test_get_metrics(self):
        r = self.client.get("/api/v1/signal-layer/metrics")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("store", data)
        self.assertIn("arb", data)
        self.assertIn("drift", data)


if __name__ == "__main__":
    unittest.main()
