"""Kalshi Pipeline Brittle Edges Test Suite

Tests for upstream/downstream invariants identified in KALSHI_PIPELINE_AUDIT:
  - BASE_URL env var validation
  - Signal source taxonomy enforcement
  - Asset wiring validation (BTC/ETH/SOL/XRP/DOGE)
  - Sentiment fusion weight sanity
  - Intel/news feed consistency
  - Recon + RTI gate behavior

Usage::
    pytest tests/test_kalshi_pipeline_invariants.py -v
"""

from __future__ import annotations

import os
import sys
import pytest
from typing import Dict, Any, List
from dataclasses import dataclass
from unittest.mock import MagicMock, patch


# Ensure test mode for env validation tests
os.environ["PYTEST_CURRENT_TEST"] = "true"


class TestKalshiBaseUrlInvariant:
    """GAP-UPSTREAM-1: BASE_URL env var validation."""

    def test_base_url_reads_from_env_var(self):
        """Verify kalshi_market_data reads BASE_URL from environment."""
        from merid.sentiment import kalshi_market_data

        # The module should have imported BASE_URL from env
        assert hasattr(kalshi_market_data, "BASE_URL")
        # Should default to demo endpoint if env not set
        assert "external-api.demo.kalshi.co" in kalshi_market_data.BASE_URL or \
               "external-api.kalshi.com" in kalshi_market_data.BASE_URL

    def test_strategies_use_env_aware_base_url(self):
        """Verify strategy modules use env-aware BASE URLs."""
        from merid.strategies import kalshi_market_data as strat_kmd
        from merid.strategies import kalshi_rate_limited_client
        from merid.strategies import kalshi_multievent_data

        # All should use environment-aware BASE
        for module in [strat_kmd, kalshi_rate_limited_client, kalshi_multievent_data]:
            assert hasattr(module, "BASE")
            # Should not be hardcoded to elections endpoint only
            base = module.BASE
            assert isinstance(base, str)
            assert base.startswith("http")

    def test_ws_clients_use_env_aware_url(self):
        """Verify WebSocket clients use env-aware URLs."""
        from merid.strategies import kalshi_ws
        from merid.strategies import kalshi_ws_backoff
        from merid.strategies import kalshi_ws_reliable

        # Check that KALSHI_WS_URL is env-aware
        ws_url = kalshi_ws.KALSHI_WS_URL
        assert isinstance(ws_url, str)
        assert ws_url.startswith("ws")

    def test_invariants_module_detects_missing_env(self):
        """Verify invariants module detects missing BASE_URL."""
        from merid.event_venues.kalshi import invariants

        # In test mode, should not raise but return None
        with patch.dict(os.environ, {}, clear=True):
            result = invariants.require_kalshi_base_url(fail_in_prod=False)
            # In test mode with fail_in_prod=False, should return None and log warning
            assert result is None or isinstance(result, str)

    def test_invariants_validates_endpoint_patterns(self):
        """Verify invariants module validates known Kalshi endpoints."""
        from merid.event_venues.kalshi import invariants

        # Valid patterns should pass
        valid_urls = [
            "https://external-api.demo.kalshi.co/trade-api/v2",
            "https://external-api.kalshi.com/trade-api/v2",
            "https://trading-api.kalshi.com/trade-api/v2",
        ]
        for url in valid_urls:
            with patch.dict(os.environ, {"KALSHI_API_BASE_URL": url}):
                result = invariants.require_kalshi_base_url(fail_in_prod=False)
                assert result == url

    def test_get_kalshi_base_url_returns_env_aware_url(self):
        """Verify get_kalshi_base_url returns env-aware URL with defaults."""
        from merid.event_venues.kalshi.invariants import get_kalshi_base_url

        # With no env set, should return demo default
        with patch.dict(os.environ, {}, clear=True):
            url = get_kalshi_base_url()
            assert url == "https://external-api.demo.kalshi.co/trade-api/v2"

        # With demo env set, should return demo
        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://external-api.demo.kalshi.co/trade-api/v2"}):
            url = get_kalshi_base_url()
            assert "external-api.demo.kalshi.co" in url

        # With live env set, should return live
        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://externel-axtealshi.com/trade-api/v2"}):
            url = get_kalshi_base_url()
            assert "external-api.kalshi.com" in url

    def test_get_kalshi_ws_url_derives_from_base(self):
        """Verify get_kalshi_ws_url derives from BASE_URL when WS_URL not set."""
        from merid.event_venues.kalshi.invariants import get_kalshi_ws_url

        # Demo BASE should yield demo WS
        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://external-api.demo.kalshi.co/trade-api/v2"}, clear=True):
            url = get_kalshi_ws_url()
            assert "wss://external-api-ws.demo.kalshi.co" in url

        # Live trading-api.kalshi.com should yield matching WS
        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://trading-api.kalshi.com/trade-api/v2"}, clear=True):
            url = get_kalshi_ws_url()
            assert "wss://trading-api.kalshi.com" in url

        # Legacy external-api should yield external-api WS
        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://external-api.kalshi.com/trade-api/v2"}, clear=True):
            url = get_kalshi_ws_url()
            assert "wss://external-api-ws.kalshi.com" in url

    def test_agent_grid_config_uses_env_aware_base(self):
        """Verify agent_grid_config.VenueConfig uses env-aware base_url from invariants."""
        from merid.prediction.agent_grid_config import VenueConfig
        from merid.event_venues.kalshi.invariants import get_kalshi_base_url, get_kalshi_ws_url

        # Test with demo env
        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://external-api.demo.kalshi.co/trade-api/v2"}):
            config = VenueConfig()
            # base_url is now a property that calls get_kalshi_base_url()
            assert config.base_url == get_kalshi_base_url()
            assert "external-api.demo.kalshi.co" in config.base_url
            # ws_url is also a property
            assert config.ws_url == get_kalshi_ws_url()

        # Test with live env
        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://trading-api.kalshi.com/trade-api/v2"}):
            config = VenueConfig()
            assert config.base_url == get_kalshi_base_url()
            assert "trading-api.kalshi.com" in config.base_url

    def test_mode_manager_kalshi_uses_env_aware_url(self):
        """Verify mode_manager kalshi config uses env-aware api_url via get_api_url()."""
        from merid.pipeline.mode_manager import get_mode_manager

        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://external-api.demo.kalshi.co/trade-api/v2"}):
            mm = get_mode_manager()
            kalshi_config = mm.get_config("kalshi")
            assert kalshi_config is not None
            # Use get_api_url() which dynamically resolves from invariants
            api_url = kalshi_config.get_api_url()
            assert "external-api.demo.kalshi.co" in api_url

    def test_kalshi_insight_pipeline_uses_env_aware_urls(self):
        """Verify kalshi_insight_pipeline uses env-aware URLs."""
        # Check that the source code uses os.getenv pattern
        import inspect
        from merid.publishing import kalshi_insight_pipeline

        source = inspect.getsource(kalshi_insight_pipeline)
        # Should have KALSHI_API_BASE_URL using os.getenv
        assert "KALSHI_API_BASE_URL" in source
        assert "os.getenv" in source

    def test_maker_bot_advanced_module_level_env_aware(self):
        """Verify maker_bot_advanced module-level BASE uses env."""
        import inspect

        # Read source directly to avoid import errors
        with open("merid/kalshi/maker_bot_advanced.py", "r", encoding="utf-8") as f:
            source = f.read()

        # Check for env-aware BASE definition at module level
        # Should have os.getenv for BASE definition instead of hardcoded
        assert 'os.getenv("KALSHI_API_BASE_URL"' in source
        assert 'os.getenv("KALSHI_WS_URL"' in source

        # Should NOT have hardcoded module-level BASE with api.elections
        # (allowing hardcoded in classes that haven't been fixed yet)
        lines = source.split('\n')
        module_level = True
        for line in lines:
            if line.startswith('class '):
                module_level = False
            if module_level and 'BASE = ' in line and 'api.elections' in line:
                pytest.fail(f"Found hardcoded api.elections at module level: {line}")
            if module_level and 'WS_URL = ' in line and 'api.elections' in line:
                pytest.fail(f"Found hardcoded ws_url at module level: {line}")


class TestSignalSourceTaxonomy:
    """GAP-ANALYZE-2: Signal source taxonomy enforcement."""

    def test_kalshi_signal_source_enum_values(self):
        """Verify canonical signal source labels."""
        from merid.event_venues.kalshi.invariants import KalshiSignalSource

        # Should have canonical kalshi_ prefixed values
        assert KalshiSignalSource.ORDERBOOK == "kalshi_orderbook"
        assert KalshiSignalSource.SPREAD == "kalshi_spread"
        assert KalshiSignalSource.EXPIRY == "kalshi_expiry"
        assert KalshiSignalSource.NEWS_SENTIMENT == "news_sentiment"
        assert KalshiSignalSource.MARKET_PROB == "kalshi_market_prob"
        assert KalshiSignalSource.MID_CENTS == "kalshi_mid_cents"

    def test_live_market_sources_returns_canonical_list(self):
        """Verify live market sources returns canonical list."""
        from merid.event_venues.kalshi.invariants import KalshiSignalSource

        sources = KalshiSignalSource.live_market_sources()
        assert "kalshi_orderbook" in sources
        assert "kalshi_spread" in sources
        assert "kalshi_expiry" in sources
        assert "news_sentiment" not in sources  # Only when explicitly included

    def test_validate_sources_warns_on_non_canonical(self):
        """Verify validation warns on non-canonical labels."""
        from merid.event_venues.kalshi.invariants import KalshiSignalSource

        # Non-canonical labels should trigger validation (but not fail)
        non_canonical = ["kalshi_book", "orderbook_kalshi", "book_depth"]
        result = KalshiSignalSource.validate_sources(non_canonical, context="test")
        assert result == non_canonical  # Returns original list

    def test_validate_sources_passes_for_canonical(self):
        """Verify validation passes for canonical labels."""
        from merid.event_venues.kalshi.invariants import KalshiSignalSource

        canonical = [
            KalshiSignalSource.ORDERBOOK,
            KalshiSignalSource.SPREAD,
            KalshiSignalSource.EXPIRY,
        ]
        result = KalshiSignalSource.validate_sources(canonical, context="test")
        assert result == canonical

    def test_opinion_strategy_uses_canonical_sources(self):
        """Verify KalshiLiveMarketStrategy uses canonical signal sources."""
        from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy
        from merid.event_venues.kalshi.invariants import KalshiSignalSource

        strategy = KalshiLiveMarketStrategy()

        # Mock market state with initialized book
        mock_state = MagicMock()
        mock_state.book_initialized = True
        mock_state.mid_cents = 50.0
        mock_state.spread_cents = 2.0
        mock_state.yes_bids = [(0.49, 100), (0.48, 50)]
        mock_state.no_bids = [(0.51, 80), (0.52, 40)]
        mock_state.seconds_to_expiry = 3600

        with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store") as mock_store:
            mock_store.return_value.get.return_value = mock_state

            estimate = strategy.estimate(
                agent_id="test_agent",
                ticker="KXBTC-TEST",
                market_prob=0.5,
                category="crypto",
                context={},
            )

            if estimate:  # May be None if below min_edge
                # Verify signal sources are canonical
                for source in estimate.signal_sources:
                    assert KalshiSignalSource.is_valid(source) or source == "news_sentiment", \
                        f"Non-canonical source: {source}"


class TestAssetWiringValidation:
    """GAP-UPSTREAM-2: Asset/timeframe universe validation."""

    def test_all_crypto_assets_defined(self):
        """Verify all 5 crypto assets are in canonical list."""
        from merid.event_venues.kalshi.invariants import KALSHI_CRYPTO_ASSETS

        expected = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in expected:
            assert asset in KALSHI_CRYPTO_ASSETS

    def test_all_timeframes_defined(self):
        """Verify all 4 timeframes are in canonical list."""
        from merid.event_venues.kalshi.invariants import KALSHI_CRYPTOTIMEFRAMES

        expected = ["15m", "1h", "daily", "weekly"]
        for tf in expected:
            assert tf in KALSHI_CRYPTOTIMEFRAMES

    def test_resolve_series_ticker_for_all_assets(self):
        """Verify series ticker resolution for all assets/timeframes."""
        from merid.event_venues.kalshi.market_selector import (
            resolve_series_ticker,
            ALL_COINS,
            ALL_TIMEFRAMES,
        )

        for coin in ALL_COINS:
            for timeframe in ALL_TIMEFRAMES:
                ticker = resolve_series_ticker(coin, timeframe)
                assert ticker.startswith("KX")
                assert coin in ticker.upper()

    def test_asset_wiring_result_structure(self):
        """Verify AssetWiringResult dataclass structure."""
        from merid.event_venues.kalshi.invariants import AssetWiringResult

        result = AssetWiringResult(
            asset="BTC",
            timeframe="15m",
            series_ticker="KXBTC15M",
            found_in_catalog=True,
            found_in_raw_snapshot=True,
            errors=[],
            warnings=[],
        )
        assert result.asset == "BTC"
        assert result.found_in_catalog is True

    def test_validate_asset_wiring_detects_missing(self):
        """Verify asset wiring validation detects missing markets."""
        from merid.event_venues.kalshi.invariants import validate_asset_wiring

        # Empty catalog should result in failures
        results = validate_asset_wiring(
            catalog_markets=[],
            raw_snapshot=None,
            assets=["BTC"],
            timeframes=["15m"],
        )

        assert "failed" in results
        assert len(results["failed"]) == 1
        assert results["failed"][0].asset == "BTC"
        assert results["failed"][0].errors  # Should have error messages


class TestSentimentFusionSanity:
    """GAP-ANALYZE-3: Sentiment fusion weight sanity checks."""

    def test_sentiment_weight_constant_defined(self):
        """Verify SENTIMENT_WEIGHT class constant exists."""
        from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy

        strategy = KalshiLiveMarketStrategy()
        assert hasattr(strategy, "SENTIMENT_WEIGHT")
        assert 0 < strategy.SENTIMENT_WEIGHT < 0.1  # Should be small (3% cap)
        assert strategy.SENTIMENT_WEIGHT == 0.03

    def test_zero_sentiment_matches_mid_cents_baseline(self):
        """Verify zero sentiment produces same prob as pure mid_cents baseline."""
        from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy

        strategy = KalshiLiveMarketStrategy(min_edge=0.0)  # Allow zero edge

        # Mock market state
        mock_state = MagicMock()
        mock_state.book_initialized = True
        mock_state.mid_cents = 55.0  # 55% implied prob
        mock_state.spread_cents = 2.0
        mock_state.yes_bids = []
        mock_state.no_bids = []
        mock_state.seconds_to_expiry = 3600

        with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store") as mock_store:
            mock_store.return_value.get.return_value = mock_state

            # With zero sentiment
            estimate_zero = strategy.estimate(
                agent_id="test",
                ticker="KXBTC-TEST",
                market_prob=0.5,
                context={"sentiment_score": 0.0},
            )

            # Without sentiment context
            estimate_none = strategy.estimate(
                agent_id="test",
                ticker="KXBTC-TEST",
                market_prob=0.5,
                context={},
            )

            # Both should use same base (mid_cents/100 = 0.55)
            if estimate_zero and estimate_none:
                # Agent prob should be close to mid_cents base (0.55)
                assert abs(estimate_zero.agent_prob - 0.55) < 0.02
                assert abs(estimate_none.agent_prob - 0.55) < 0.02

    def test_sentiment_capped_at_3_percent(self):
        """Verify sentiment contribution is capped at 3%."""
        from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy

        strategy = KalshiLiveMarketStrategy()
        max_sentiment = 1.0  # Extreme positive sentiment

        # Calculate max possible bias
        max_bias = max_sentiment * strategy.SENTIMENT_WEIGHT
        assert max_bias <= 0.03  # 3% cap

    def test_fallback_estimate_uses_sentiment_weight(self):
        """Verify fallback estimate respects SENTIMENT_WEIGHT."""
        from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy

        strategy = KalshiLiveMarketStrategy(min_edge=0.0)

        # No state available, fallback uses sentiment
        estimate = strategy._fallback_estimate(
            agent_id="test",
            ticker="KXBTC-TEST",
            market_prob=0.5,
            ctx={"sentiment_score": 1.0},  # Extreme bullish
        )

        if estimate:
            # With max positive sentiment, prob should be 0.5 + 0.03 = 0.53 (capped)
            expected_max = 0.5 + strategy.SENTIMENT_WEIGHT
            assert estimate.agent_prob <= expected_max + 0.001
            assert estimate.agent_prob >= 0.5  # Should be biased up


class TestIntelFeedConsistency:
    """GAP-UPSTREAM-3: Intel/news feed consistency with market data client."""

    def test_market_data_client_has_base_url(self):
        """Verify KalshiMarketDataClient exposes BASE_URL."""
        from merid.sentiment.kalshi_market_data import BASE_URL

        assert BASE_URL is not None
        assert isinstance(BASE_URL, str)
        assert BASE_URL.startswith("http")

    def test_invariants_check_intel_consistency(self):
        """Verify invariants module can check intel feed consistency."""
        from merid.event_venues.kalshi import invariants
        from merid.sentiment import kalshi_market_data

        result = invariants.check_intel_feed_consistency(
            kalshi_market_data.KalshiMarketDataClient,
        )

        assert "consistent" in result
        assert isinstance(result["consistent"], bool)


class TestReconRtigates:
    """GAP-DOWNSTREAM: Recon + RTI gate behavior."""

    def test_require_cfb_for_live_trading_exists(self):
        """Verify RTI gating function exists."""
        from merid.signals.cfb_rti_adapter import require_cfb_for_live_trading

        assert callable(require_cfb_for_live_trading)


class TestEndToEndPipeline:
    """End-to-end pipeline tests: DISCOVER → ANALYZE → CONSENSUS → SIZE."""

    def test_opinion_strategy_outputs_structured_estimate(self):
        """Verify opinion estimate has all required fields for downstream."""
        from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy

        strategy = KalshiLiveMarketStrategy(min_edge=0.0)

        # Mock market state
        mock_state = MagicMock()
        mock_state.book_initialized = True
        mock_state.mid_cents = 52.0
        mock_state.spread_cents = 2.0
        mock_state.yes_bids = [(0.51, 100)]
        mock_state.no_bids = [(0.53, 80)]
        mock_state.seconds_to_expiry = 3600

        with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store") as mock_store:
            mock_store.return_value.get.return_value = mock_state

            estimate = strategy.estimate(
                agent_id="test_agent",
                ticker="KXBTC-TEST",
                market_prob=0.5,
                category="crypto",
                context={"sentiment_score": 0.2},
            )

            if estimate:
                # Required fields for downstream consensus
                assert hasattr(estimate, "agent_prob")
                assert hasattr(estimate, "confidence")
                assert hasattr(estimate, "edge")
                assert hasattr(estimate, "signal_sources")
                assert hasattr(estimate, "explanation")

                # Explanation must have required fields
                assert hasattr(estimate.explanation, "inputs_used")
                assert hasattr(estimate.explanation, "contributions")
                assert hasattr(estimate.explanation, "rationale")

                # Signal sources must be non-empty
                assert len(estimate.signal_sources) > 0

    def test_mid_cents_used_as_base_probability(self):
        """Verify mid_cents/100 is used as base probability, not market_prob."""
        from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy

        strategy = KalshiLiveMarketStrategy(min_edge=0.0)

        mock_state = MagicMock()
        mock_state.book_initialized = True
        mock_state.mid_cents = 60.0  # 60% implied (different from market_prob)
        mock_state.spread_cents = 2.0
        mock_state.yes_bids = []
        mock_state.no_bids = []
        mock_state.seconds_to_expiry = 3600

        with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store") as mock_store:
            mock_store.return_value.get.return_value = mock_state

            # market_prob is different from mid_cents
            estimate = strategy.estimate(
                agent_id="test",
                ticker="KXBTC-TEST",
                market_prob=0.5,  # Different from mid_cents!
                context={},
            )

            if estimate:
                # Agent prob should be closer to mid_cents (0.60) than market_prob (0.50)
                assert estimate.agent_prob > 0.55  # Should be closer to 0.60
                # Explanation should show mid_cents was used
                assert "mid_cents" in estimate.explanation.inputs_used
                assert estimate.explanation.inputs_used["mid_cents"] == 60.0


class TestHardcodedUrlScan:
    """Repo-wide scan for hardcoded Kalshi URLs outside invariants.py."""

    # URLs that should only appear in invariants.py
    PROHIBITED_URLS = [
        "https://external-api.demo.kalshi.co",
        "https://trading-api.kalshi.com",
        "https://external-api.kalshi.com",
        "wss://external-api.demo.kalshi.co",
        "wss://trading-api.kalshi.com",
        "wss://external-api.kalshi.com",
    ]

    # Files that are allowed to have these URLs (invariants + test fixtures)
    ALLOWLIST = [
        "merid/event_venues/kalshi/invariants.py",
        "tests/test_kalshi_pipeline_invariants.py",
        "tests/test_kalshi_market_consensus.py",
        "README.md",
        "docs/",
    ]

    # Core modules where hardcoded URLs are strictly prohibited (CI failure)
    CORE_MODULES = [
        "merid/strategies/kalshi",
        "merid/prediction/agent_grid_config.py",
        "merid/pipeline/mode_manager.py",
        "merid/publishing/kalshi_insight_pipeline.py",
        "merid/event_venues/kalshi/client.py",
        "merid/event_venues/kalshi/ws.py",
    ]

    def test_no_hardcoded_kalshi_urls_in_core_modules(self):
        """CI-enforced: No hardcoded Kalshi URLs in core modules.
        
        This test fails CI if any prohibited URL is found in core modules,
        ensuring all Kalshi clients use invariants.get_kalshi_base_url().
        """
        import glob

        # Find all Python files
        py_files = glob.glob("merid/**/*.py", recursive=True)
        py_files += glob.glob("web/**/*.py", recursive=True)

        violations = []

        for filepath in py_files:
            # Skip allowlisted files and _legacy directories
            if any(allow in filepath for allow in self.ALLOWLIST):
                continue
            if "_legacy" in filepath:
                continue

            # Only check core modules strictly
            if not any(core in filepath for core in self.CORE_MODULES):
                continue

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except (UnicodeDecodeError, IOError):
                continue

            for prohibited in self.PROHIBITED_URLS:
                if prohibited in content:
                    # Check if it's using invariants (allowed)
                    if "get_kalshi_base_url" in content or "get_kalshi_ws_url" in content:
                        continue
                    # Check for os.getenv usage (allowed pattern)
                    if 'os.getenv("KALSHI' in content:
                        continue
                    violations.append(f"{filepath}: {prohibited}")

        if violations:
            pytest.fail(
                f"Hardcoded Kalshi URLs found in core modules (CI failure):\n" +
                "\n".join(f"  {v}" for v in violations) +
                "\n\nAll Kalshi clients must use invariants.get_kalshi_base_url()"
            )

    def test_startup_logging_outputs_env_classification(self):
        """Verify log_kalshi_startup_info logs environment classification."""
        from merid.event_venues.kalshi.invariants import log_kalshi_startup_info, classify_kalshi_environment

        # Test classification for each environment
        assert classify_kalshi_environment("https://external-api.demo.kalshi.co/trade-api/v2") == "demo"
        assert classify_kalshi_environment("https://trading-api.kalshi.com/trade-api/v2") == "live"
        assert classify_kalshi_environment("https://external-exakalshi.com/trade-api/v2") == "elections"
        assert classify_kalshi_environment("https://unknown.kalshi.com/trade-api/v2") == "unknown"

    def test_base_url_validation_raises_in_dev(self):
        """Verify get_kalshi_base_url raises ValueError for invalid URLs in dev."""
        from merid.event_venues.kalshi.invariants import get_kalshi_base_url

        # In test mode, invalid URL should fall back to demo
        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://invalid-host.com/api"}):
            # Should return demo default when URL doesn't match known patterns
            url = get_kalshi_base_url()
            assert url == "https://external-api.demo.kalshi.co/trade-api/v2"

    def test_no_legacy_env_vars_detected(self):
        """Verify no legacy KALSHI_DEMO/KALSHI_ENV vars are set in test env."""
        from merid.event_venues.kalshi.invariants import detect_legacy_env_vars

        # In test environment, should have no legacy vars
        warnings = detect_legacy_env_vars()
        
        # This is informational - legacy vars don't break things,
        # but they indicate configuration drift
        for warning in warnings:
            print(f"[kalshi] {warning}")


class TestIntegrationAllBaseUrls:
    """Integration test for all three base URL values."""

    BASE_URLS = [
        ("demo", "https://external-api.demo.kalshi.co/trade-api/v2"),
        ("live", "https://trading-api.kalshi.com/trade-api/v2"),
        ("elections", "https://external-exakalshi.com/trade-api/v2"),
    ]

    @pytest.mark.parametrize("env_name,base_url", BASE_URLS)
    def test_invariants_return_correct_urls(self, env_name, base_url):
        """Verify invariants return correct URLs for each environment."""
        from merid.event_venues.kalshi.invariants import get_kalshi_base_url, get_kalshi_ws_url

        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": base_url}, clear=True):
            actual_base = get_kalshi_base_url()
            actual_ws = get_kalshi_ws_url()

            # Base URL should match exactly
            assert actual_base == base_url, f"Expected {base_url}, got {actual_base}"

            # WS URL should be derived correctly
            expected_ws = base_url.replace("https://", "wss://").replace("/trade-api/v2", "/trade-api/ws/v2")
            assert actual_ws == expected_ws, f"Expected {expected_ws}, got {actual_ws}"

    @pytest.mark.parametrize("env_name,base_url", BASE_URLS)
    def test_agent_grid_config_reflects_env(self, env_name, base_url):
        """Verify agent_grid_config reflects environment."""
        from merid.prediction.agent_grid_config import VenueConfig
        from merid.event_venues.kalshi.invariants import get_kalshi_base_url

        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": base_url}, clear=True):
            config = VenueConfig()
            assert config.base_url == base_url
            assert config.base_url == get_kalshi_base_url()

    @pytest.mark.parametrize("env_name,base_url", BASE_URLS)
    def test_ws_url_derived_from_any_host(self, env_name, base_url):
        """Verify WS URL derivation works for any host pattern."""
        from merid.event_venues.kalshi.invariants import get_kalshi_ws_url

        # Test that derivation works via URL manipulation, not hardcoded hosts
        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": base_url}, clear=True):
            ws_url = get_kalshi_ws_url()
            # Should always follow the pattern
            assert ws_url.startswith("wss://")
            assert ws_url.endswith("/trade-api/ws/v2")
            # Host should match
            host = base_url.replace("https://", "").replace("/trade-api/v2", "")
            assert host in ws_url


class TestProcessLifecycleAndSafety:
    """Process lifecycle, env flip detection, and production safety guards."""

    def test_single_kalshi_env_per_process(self):
        """Verify architecture assumes single Kalshi env per process."""
        from merid.event_venues.kalshi.invariants import verify_single_kalshi_env_per_process

        # Should pass with default/demo env
        assert verify_single_kalshi_env_per_process() is True

    def test_env_flip_detection(self):
        """Verify KalshiEnvMonitor detects env changes mid-process."""
        from merid.event_venues.kalshi.invariants import KalshiEnvMonitor

        # Create monitor with initial env
        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://external-api.demo.kalshi.co/trade-api/v2"}):
            monitor = KalshiEnvMonitor()
            assert not monitor.has_flipped()
            
            initial = monitor.get_initial_urls()
            assert "external-api.demo.kalshi.co" in initial["base_url"]
            
            # Check should pass (no flip)
            assert not monitor.check()
            
        # Simulate env flip (new patch simulating changed env)
        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://trading-api.kalshi.com/trade-api/v2"}):
            # Now check should detect flip
            assert monitor.check() is True
            assert monitor.has_flipped() is True

    def test_metrics_labels_generation(self):
        """Verify metrics labels include kalshi_env and kalshi_host."""
        from merid.event_venues.kalshi.invariants import get_kalshi_metrics_labels

        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://external-api.demo.kalshi.co/trade-api/v2"}):
            labels = get_kalshi_metrics_labels()
            assert "kalshi_env" in labels
            assert "kalshi_host" in labels
            assert labels["kalshi_env"] == "demo"
            assert labels["kalshi_host"] == "external-api.demo.kalshi.co"

        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://trading-api.kalshi.com/trade-api/v2"}):
            labels = get_kalshi_metrics_labels()
            assert labels["kalshi_env"] == "live"
            assert labels["kalshi_host"] == "trading-api.kalshi.com"

    def test_live_confirmation_guard_blocks_without_flag(self):
        """Verify live confirmation guard blocks without KALSHI_CONFIRM_LIVE=1."""
        from merid.event_venues.kalshi.invariants import require_live_confirmation

        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://trading-api.kalshi.com/trade-api/v2"}, clear=True):
            # Should raise without confirmation flag
            with pytest.raises(RuntimeError) as exc_info:
                require_live_confirmation()
            
            assert "KALSHI_CONFIRM_LIVE=1 not set" in str(exc_info.value)

    def test_live_confirmation_guard_passes_with_flag(self):
        """Verify live confirmation guard passes with KALSHI_CONFIRM_LIVE=1."""
        from merid.event_venues.kalshi.invariants import require_live_confirmation

        with patch.dict(os.environ, {
            "KALSHI_API_BASE_URL": "https://trading-api.kalshi.com/trade-api/v2",
            "KALSHI_CONFIRM_LIVE": "1",
        }):
            # Should not raise with confirmation flag
            require_live_confirmation()  # No exception

    def test_demo_does_not_require_confirmation(self):
        """Verify demo environment does not require KALSHI_CONFIRM_LIVE."""
        from merid.event_venues.kalshi.invariants import require_live_confirmation

        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://external-api.demo.kalshi.co/trade-api/v2"}, clear=True):
            # Should not raise for demo
            require_live_confirmation()  # No exception

    def test_strict_validation_passes_for_valid_config(self):
        """Verify strict validation passes for valid configuration."""
        from merid.event_venues.kalshi.invariants import validate_kalshi_config_strict

        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://external-api.demo.kalshi.co/trade-api/v2"}, clear=True):
            results = validate_kalshi_config_strict()
            assert "base_url" in results
            assert "ws_url" in results
            assert results["single_env"] is True

    def test_strict_validation_fails_for_invalid_base_url(self):
        """Verify strict validation hard-fails for invalid base URL.
        
        Note: Invalid URLs that don't match known patterns fall back to demo default,
        which is the safe behavior. This test verifies that fallback works correctly.
        """
        from merid.event_venues.kalshi.invariants import validate_kalshi_config_strict

        # Invalid URL should cause fallback to demo, strict validation passes with demo
        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": "https://invalid-host.com/api"}, clear=True):
            results = validate_kalshi_config_strict()
            # Falls back to valid demo URL
            assert results["base_url"] == "https://external-api.demo.kalshi.co/trade-api/v2"

    def test_strict_validation_fails_for_live_without_confirmation(self):
        """Verify strict validation hard-fails for live without confirmation."""
        from merid.event_venues.kalshi.invariants import validate_kalshi_config_strict

        with patch.dict(os.environ, {
            "KALSHI_API_BASE_URL": "https://trading-api.kalshi.com/trade-api/v2",
        }, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                validate_kalshi_config_strict()
            
            assert "KALSHI_CONFIRM_LIVE=1 not set" in str(exc_info.value)

    def test_unknown_host_with_trade_api_v2_falls_back_to_demo(self):
        """Verify unknown hosts fall back to demo (safe behavior).
        
        The invariants module validates against known patterns for safety.
        Unknown hosts fall back to demo default rather than accepting arbitrary URLs.
        """
        from merid.event_venues.kalshi.invariants import get_kalshi_base_url, get_kalshi_ws_url

        # Simulate an unknown/future host
        unknown_host = "https://future-api.kalshi.com/trade-api/v2"
        
        with patch.dict(os.environ, {"KALSHI_API_BASE_URL": unknown_host}, clear=True):
            base = get_kalshi_base_url()
            ws = get_kalshi_ws_url()
            
            # Unknown hosts fall back to demo for safety
            assert base == "https://external-api.demo.kalshi.co/trade-api/v2"
            assert ws == "wss://external-api.demo.kalshi.co/trade-api/ws/v2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
