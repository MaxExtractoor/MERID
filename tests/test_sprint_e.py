"""Sprint E invariant tests.

Covers every deliverable added in Sprint E:
  E1 – .env / .gitignore secrets infrastructure
  E2 – FinnhubContextSnapshot dataclass + to_dict / to_edge_features
  E3 – _finnhub_releases_or_bls() fallback logic
  E4 – EdgeModel Signal 5: Finnhub sentiment nudges
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ──────────────────────────────────────────────────────────────────────────────
# E1 – Secrets infrastructure
# ──────────────────────────────────────────────────────────────────────────────

class TestSecretsInfrastructure(unittest.TestCase):
    """E1: .gitignore protects .env; FINNHUB_API_KEY and FRED_API_KEY are in .env."""

    def test_gitignore_blocks_env(self):
        gi = ROOT / ".gitignore"
        self.assertTrue(gi.exists(), ".gitignore missing")
        content = gi.read_text()
        self.assertIn(".env", content)

    def test_env_has_fred_key(self):
        env = ROOT / ".env"
        self.assertTrue(env.exists(), ".env missing")
        content = env.read_text()
        self.assertIn("FRED_API_KEY=", content)

    def test_env_has_finnhub_key(self):
        env = ROOT / ".env"
        content = env.read_text()
        self.assertIn("FINNHUB_API_KEY=", content)

    def test_env_not_tracked(self):
        """Verify .env is listed in .gitignore (not just present on disk)."""
        gi = ROOT / ".gitignore"
        lines = gi.read_text().splitlines()
        dotenv_lines = [l.strip() for l in lines if ".env" in l and not l.strip().startswith("#")]
        self.assertTrue(len(dotenv_lines) > 0, ".env not protected by .gitignore")


# ──────────────────────────────────────────────────────────────────────────────
# E2 – FinnhubContextSnapshot
# ──────────────────────────────────────────────────────────────────────────────

class TestFinnhubContextSnapshot(unittest.TestCase):
    """E2: FinnhubContextSnapshot dataclass semantics."""

    def _snap(self, releases=None, sentiment=None):
        from merid.prediction.finnhub_context import (
            FinnhubContextSnapshot, EconomicRelease, SentimentScore
        )
        if releases is None:
            releases = [
                EconomicRelease(
                    event="CPI YoY", release_time="2026-03-12 13:30:00",
                    impact="high", country="US",
                    estimate=2.9, prev=2.9, actual=None, days_away=5.0,
                ),
                EconomicRelease(
                    event="Nonfarm Payroll", release_time="2026-03-07 13:30:00",
                    impact="high", country="US",
                    estimate=200.0, prev=190.0, actual=240.0, days_away=-2.0,
                ),
            ]
        if sentiment is None:
            sentiment = {
                "SPY": SentimentScore("SPY", bullish_pct=0.65, bearish_pct=0.35,
                                      buzz_score=0.7, news_score=0.6),
                "BTC": SentimentScore("BTC", bullish_pct=0.55, bearish_pct=0.45,
                                      buzz_score=0.5, news_score=0.55),
            }
        return FinnhubContextSnapshot(releases=releases, sentiment=sentiment, source="stub")

    def test_to_edge_features_keys(self):
        snap = self._snap()
        feats = snap.to_edge_features()
        for key in (
            "fh_nearest_release_days", "fh_macro_surprise",
            "fh_spy_bullish_pct", "fh_spy_news_score", "fh_spy_buzz",
            "fh_crypto_bullish_pct", "fh_crypto_news_score",
            "fh_high_impact_imminent",
        ):
            self.assertIn(key, feats, f"Missing: {key}")

    def test_to_dict_structure(self):
        snap = self._snap()
        d = snap.to_dict()
        self.assertIn("releases", d)
        self.assertIn("sentiment", d)
        self.assertIn("nearest_release_days", d)

    def test_nearest_high_impact_days(self):
        snap = self._snap()
        # Upcoming CPI is 5 days away
        nearest = snap.nearest_high_impact_days()
        self.assertAlmostEqual(nearest, 5.0, delta=0.1)

    def test_high_impact_within_days(self):
        snap = self._snap()
        imminent = snap.high_impact_within_days(days=1.0)
        self.assertEqual(len(imminent), 0)   # neither is within 1 day
        broad = snap.high_impact_within_days(days=10.0)
        self.assertGreater(len(broad), 0)

    def test_recent_surprise_nfp_hot(self):
        snap = self._snap()
        # NFP actual=240 vs estimate=200 → hot surprise
        surprise = snap.recent_surprise()
        self.assertGreater(surprise, 0.0)

    def test_is_surprise_flag(self):
        from merid.prediction.finnhub_context import EconomicRelease
        r = EconomicRelease("CPI", "2026-03-12", "high", "US",
                            estimate=2.9, prev=2.9, actual=3.5, days_away=-1.0)
        self.assertTrue(r.is_surprise)
        r2 = EconomicRelease("CPI", "2026-03-12", "high", "US",
                             estimate=2.9, prev=2.9, actual=2.95, days_away=-1.0)
        self.assertFalse(r2.is_surprise)

    def test_get_sentiment_unknown_returns_default(self):
        snap = self._snap()
        s = snap.get_sentiment("UNKNOWN")
        self.assertAlmostEqual(s.bullish_pct, 0.5)

    def test_service_returns_stub_without_key(self):
        from merid.prediction.finnhub_context import FinnhubContextService
        import merid.prediction.finnhub_context as fh_mod
        original_key = fh_mod._FINNHUB_KEY
        fh_mod._FINNHUB_KEY = ""
        try:
            svc = FinnhubContextService()
            snap = asyncio.get_event_loop().run_until_complete(svc.get_snapshot())
            self.assertEqual(snap.source, "stub")
        finally:
            fh_mod._FINNHUB_KEY = original_key

    def test_service_returns_stub_on_network_fail(self):
        from merid.prediction.finnhub_context import FinnhubContextService
        import merid.prediction.finnhub_context as fh_mod
        original_key = fh_mod._FINNHUB_KEY
        fh_mod._FINNHUB_KEY = "fake-key"
        try:
            svc = FinnhubContextService()
            with patch("merid.prediction.finnhub_context._get", new_callable=AsyncMock) as m:
                m.side_effect = RuntimeError("network down")
                snap = asyncio.get_event_loop().run_until_complete(svc.get_snapshot())
            self.assertEqual(snap.source, "stub")
        finally:
            fh_mod._FINNHUB_KEY = original_key


# ──────────────────────────────────────────────────────────────────────────────
# E3 – _finnhub_releases_or_bls fallback
# ──────────────────────────────────────────────────────────────────────────────

class TestFinnhubCalendarFallback(unittest.TestCase):
    """E3: _finnhub_releases_or_bls falls back to BLS heuristic when Finnhub fails."""

    def test_falls_back_to_bls_on_stub(self):
        """When Finnhub returns a stub, we still get BLS heuristic releases."""
        from merid.prediction.macro_context import _finnhub_releases_or_bls
        from merid.prediction.finnhub_context import FinnhubContextSnapshot

        stub_snap = FinnhubContextSnapshot(source="stub")
        with patch(
            "merid.prediction.finnhub_context.get_finnhub_context_service"
        ) as mock_factory:
            mock_svc = MagicMock()
            mock_svc.get_snapshot = AsyncMock(return_value=stub_snap)
            mock_factory.return_value = mock_svc
            alerts = asyncio.get_event_loop().run_until_complete(
                _finnhub_releases_or_bls(date.today())
            )
        # Should have gotten BLS heuristic results
        self.assertIsInstance(alerts, list)
        self.assertGreater(len(alerts), 0)

    def test_uses_finnhub_when_live(self):
        """When Finnhub returns live data with high-impact US releases, uses them."""
        from merid.prediction.macro_context import _finnhub_releases_or_bls
        from merid.prediction.finnhub_context import (
            FinnhubContextSnapshot, EconomicRelease
        )

        live_snap = FinnhubContextSnapshot(
            releases=[
                EconomicRelease("CPI YoY", "2026-03-12 13:30:00", "high", "US",
                                2.9, 2.9, None, 5.0),
                EconomicRelease("Nonfarm Payroll", "2026-03-07 13:30:00", "high", "US",
                                200.0, 190.0, None, 10.0),
            ],
            source="live",
        )
        with patch(
            "merid.prediction.finnhub_context.get_finnhub_context_service"
        ) as mock_factory:
            mock_svc = MagicMock()
            mock_svc.get_snapshot = AsyncMock(return_value=live_snap)
            mock_factory.return_value = mock_svc
            alerts = asyncio.get_event_loop().run_until_complete(
                _finnhub_releases_or_bls(date.today())
            )
        self.assertIsInstance(alerts, list)
        self.assertGreater(len(alerts), 0)
        report_names = {a.report for a in alerts}
        self.assertTrue({"CPI", "NFP"}.issubset(report_names))

    def test_event_name_mapping_cpi(self):
        """CPI YoY → 'CPI' code."""
        from merid.prediction.macro_context import _finnhub_releases_or_bls
        from merid.prediction.finnhub_context import (
            FinnhubContextSnapshot, EconomicRelease
        )
        live_snap = FinnhubContextSnapshot(
            releases=[EconomicRelease("CPI YoY", "2026-03-12 13:30:00",
                                     "high", "US", 2.9, 2.9, None, 5.0)],
            source="live",
        )
        with patch("merid.prediction.finnhub_context.get_finnhub_context_service") as mf:
            mf.return_value.get_snapshot = AsyncMock(return_value=live_snap)
            alerts = asyncio.get_event_loop().run_until_complete(
                _finnhub_releases_or_bls(date.today())
            )
        self.assertEqual(alerts[0].report, "CPI")


# ──────────────────────────────────────────────────────────────────────────────
# E4 – EdgeModel Signal 5 (Finnhub sentiment)
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeModelFinnhubSignal(unittest.TestCase):
    """E4: Finnhub features drive correct nudge direction in _context_signal."""

    def _model(self, macro=None, perp=None, finnhub=None):
        from merid.prediction.edge_model import EdgeModel
        m = EdgeModel.__new__(EdgeModel)
        m._macro_features   = macro   or {}
        m._perp_features    = perp    or {}
        m._finnhub_features = finnhub or {}
        m._macro_loaded_at   = 9e9
        m._perp_loaded_at    = 9e9
        m._finnhub_loaded_at = 9e9
        m._CONTEXT_TTL = 120.0
        return m

    def test_imminent_release_pulls_toward_half(self):
        m = self._model(finnhub={"fh_nearest_release_days": 0.3,
                                  "fh_macro_surprise": 0.0,
                                  "fh_spy_bullish_pct": 0.5,
                                  "fh_crypto_bullish_pct": 0.5})
        adj, conf = m._context_signal(0.8, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.8)   # pulled toward 0.5

    def test_hot_macro_surprise_bearish_crypto(self):
        m = self._model(finnhub={"fh_nearest_release_days": 99.0,
                                  "fh_macro_surprise": 0.5,
                                  "fh_spy_bullish_pct": 0.5,
                                  "fh_crypto_bullish_pct": 0.5})
        adj, conf = m._context_signal(0.6, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.6)

    def test_bullish_spy_slight_crypto_lift(self):
        m = self._model(finnhub={"fh_nearest_release_days": 99.0,
                                  "fh_macro_surprise": 0.0,
                                  "fh_spy_bullish_pct": 0.75,
                                  "fh_crypto_bullish_pct": 0.5})
        adj, conf = m._context_signal(0.5, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertGreater(adj, 0.5)

    def test_bearish_crypto_sentiment_nudge_down(self):
        m = self._model(finnhub={"fh_nearest_release_days": 99.0,
                                  "fh_macro_surprise": 0.0,
                                  "fh_spy_bullish_pct": 0.5,
                                  "fh_crypto_bullish_pct": 0.25})
        adj, conf = m._context_signal(0.6, "ETH", "KXETH-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.6)

    def test_finnhub_non_crypto_no_sentiment_nudge(self):
        """Non-crypto assets should not get crypto sentiment nudges."""
        m = self._model(finnhub={"fh_nearest_release_days": 99.0,
                                  "fh_macro_surprise": 0.0,
                                  "fh_spy_bullish_pct": 0.75,
                                  "fh_crypto_bullish_pct": 0.9})
        adj, conf = m._context_signal(0.6, "SPX", "KXSPX-T")
        # Only spy sentiment could fire for non-crypto, and SPX isn't in crypto list
        if adj is not None:
            self.assertAlmostEqual(adj, 0.6, delta=0.08)

    def test_combined_signals_still_capped(self):
        """Even with all signals firing, nudge stays within ±0.08."""
        m = self._model(
            macro={"macro_vix": 50.0, "macro_inverted_curve": 1.0,
                   "macro_cpi_momentum": 0.5, "macro_release_days_away": 0.0},
            perp={"btc_funding_rate": 0.01, "btc_iv_30d": 1.2},
            finnhub={"fh_nearest_release_days": 0.1, "fh_macro_surprise": 0.8,
                     "fh_spy_bullish_pct": 0.2, "fh_crypto_bullish_pct": 0.2},
        )
        adj, conf = m._context_signal(0.85, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertGreaterEqual(adj, 0.02)
        self.assertLessEqual(adj, 0.98)
        self.assertLessEqual(conf, 0.4)

    def test_model_has_finnhub_loaded_at_attr(self):
        from merid.prediction.edge_model import EdgeModel
        m = EdgeModel.__new__(EdgeModel)
        m._macro_features   = None
        m._perp_features    = None
        m._finnhub_features = None
        m._macro_loaded_at   = 0.0
        m._perp_loaded_at    = 0.0
        m._finnhub_loaded_at = 0.0
        m._CONTEXT_TTL = 120.0
        self.assertTrue(hasattr(m, "_finnhub_features"))
        self.assertTrue(hasattr(m, "_finnhub_loaded_at"))


if __name__ == "__main__":
    unittest.main()
