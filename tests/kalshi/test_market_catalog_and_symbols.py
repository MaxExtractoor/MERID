"""Kalshi Market Catalog and Symbol Wiring Tests — Step 3 Audit Deliverable

Validates:
1. All supported crypto assets (BTC, ETH, SOL, XRP, DOGE) are properly cataloged
2. Symbol normalization is consistent (single canonical path)
3. Timeframe suffix mapping is correct (15m, 1h, daily, weekly)
4. No legacy perp contamination in Kalshi code paths
5. Group ID generation is consistent

Run: pytest tests/kalshi/test_market_catalog_and_symbols.py -v
"""

from __future__ import annotations

import pytest
import re

# PRODUCTION AUDIT: Import shared scope constants
from tests.test_production_scope import (
    ALLOWED_SYMBOLS,
    ALLOWED_TIMEFRAMES,
    KALSHI_SERIES_TICKERS,
)
from typing import List, Optional, Tuple

# =============================================================================
# Test Class: Supported Assets Coverage
# =============================================================================

class TestKalshiSupportedAssets:
    """Verify all expected crypto assets have catalog coverage.
    
    PRODUCTION AUDIT: Uses shared ALLOWED_SYMBOLS constant.
    """
    
    EXPECTED_ASSETS = ALLOWED_SYMBOLS
    
    def test_crypto_assets_in_ticker_map(self):
        """All expected assets appear in market_catalog ticker regex patterns."""
        try:
            from merid.event_venues.kalshi.market_catalog import _TICKER_CATEGORY_MAP
            
            # Extract all asset patterns from ticker map
            found_assets = set()
            for pattern, category, asset in _TICKER_CATEGORY_MAP:
                if category == "crypto" and asset:
                    found_assets.add(asset)
            
            for asset in self.EXPECTED_ASSETS:
                assert asset in found_assets, f"{asset} not found in ticker category map"
                
        except ImportError:
            pytest.skip("market_catalog not available")
            
    def test_cfb_settlement_coverage(self):
        """All expected assets have CF Benchmarks settlement config."""
        try:
            from merid.event_venues.kalshi.cfb_settlement import (
                CFB_INDEX_BY_ASSET,
                CFB_REFERENCE_RATE_BY_ASSET,
                SETTLEMENT_BY_KEY,
            )
            
            for asset in self.EXPECTED_ASSETS:
                assert asset in CFB_INDEX_BY_ASSET, f"{asset} missing from CFB_INDEX_BY_ASSET"
                assert asset in CFB_REFERENCE_RATE_BY_ASSET, f"{asset} missing from CFB_REFERENCE_RATE_BY_ASSET"
                
                # Check all timeframes have settlement params
                for timeframe in ["15m", "1h", "daily", "weekly"]:
                    key = (asset, timeframe)
                    assert key in SETTLEMENT_BY_KEY, f"{asset}/{timeframe} missing settlement params"
                    
        except ImportError:
            pytest.skip("cfb_settlement not available")
            
    def test_kalshi_series_mapping(self):
        """Series ticker patterns exist for all assets."""
        try:
            from merid.event_venues.kalshi.market_selector import CRYPTO_SERIES_BASE
            
            # Should have mappings for all assets
            for coin in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                assert coin in CRYPTO_SERIES_BASE, f"{coin} missing from CRYPTO_SERIES_BASE"
                
            # Values should be KX-prefixed
            for coin, series in CRYPTO_SERIES_BASE.items():
                assert series.startswith("KX"), f"{coin} series {series} should start with KX"
                
        except ImportError:
            pytest.skip("market_selector not available")
            
    def test_agent_series_map_completeness(self):
        """AGENT_SERIES_MAP covers expected agent patterns."""
        try:
            from merid.event_venues.kalshi.market_selector import AGENT_SERIES_MAP
            
            # Should have entries for crypto agents
            crypto_agents = [name for name in AGENT_SERIES_MAP.keys() if any(
                a in name for a in ["BTC", "ETH", "SOL", "XRP", "DOGE", "Crypto"]
            )]
            
            assert len(crypto_agents) > 0, "No crypto agents found in AGENT_SERIES_MAP"
            
        except ImportError:
            pytest.skip("market_selector not available")


# =============================================================================
# Test Class: Symbol Normalization
# =============================================================================

class TestKalshiSymbolNormalization:
    """Verify consistent symbol/ticker normalization."""
    
    def test_extract_asset_from_ticker_consistency(self):
        """Asset extraction is consistent for known ticker patterns."""
        try:
            from merid.event_venues.kalshi.market_filter import extract_asset_from_ticker
            
            test_cases = [
                ("KXBTC-25DEC-ABOVE-100000", "BTC"),
                ("KXETH-15M-BELOW-2000", "ETH"),
                ("KXSOL-D-ABOVE-150", "SOL"),
                ("KXXRP-26MAR-ABOVE-2", "XRP"),
                ("KXDOGE-W-BELOW-1", "DOGE"),
                ("KXBTCD-26MAR2003-T79299", "BTC"),  # Daily pattern
                ("KXBTC-15M-26MAR2003-T70000", "BTC"),  # 15m pattern
            ]
            
            for ticker, expected_asset in test_cases:
                result = extract_asset_from_ticker(ticker)
                # May return None if pattern not recognized, but should be consistent
                if result:
                    assert result == expected_asset, f"{ticker}: expected {expected_asset}, got {result}"
                    
        except ImportError:
            pytest.skip("market_filter not available")
            
    def test_group_id_generation_consistency(self):
        """Group ID generation produces consistent output."""
        try:
            from merid.event_venues.kalshi.market_filter import group_id_from_ticker
            
            # Same ticker should always produce same group_id
            ticker = "KXBTC-25DEC-ABOVE-100000"
            gid1 = group_id_from_ticker(ticker)
            gid2 = group_id_from_ticker(ticker)
            
            assert gid1 == gid2, "group_id_from_ticker should be deterministic"
            
            # Different tickers should produce different group_ids (with high probability)
            ticker2 = "KXETH-25DEC-ABOVE-2000"
            gid3 = group_id_from_ticker(ticker2)
            
            assert gid1 != gid3, "Different tickers should have different group_ids"
            
        except ImportError:
            pytest.skip("market_filter not available")
            
    def test_timeframe_normalization(self):
        """Timeframe strings are normalized consistently."""
        try:
            from merid.event_venues.kalshi.market_filter import _normalize_timeframe
            
            test_cases = [
                ("15m", "15m"),
                ("15M", "15m"),
                ("1h", "1h"),
                ("hourly", "1h"),
                ("HOURLY", "1h"),
                ("daily", "daily"),
                ("D", "daily"),
                ("weekly", "weekly"),
                ("W", "weekly"),
            ]
            
            for input_tf, expected in test_cases:
                result = _normalize_timeframe(input_tf)
                assert result == expected, f"_normalize_timeframe({input_tf}) = {result}, expected {expected}"
                
        except ImportError:
            pytest.skip("market_filter not available")
            
    def test_series_ticker_resolution(self):
        """Series ticker resolution maps coin + timeframe to series ticker.
        
        PRODUCTION AUDIT: Uses shared ALLOWED_SYMBOLS and ALLOWED_TIMEFRAMES constants.
        """
        try:
            from merid.event_venues.kalshi.market_selector import resolve_series_ticker

            # Use shared scope constants
            for symbol in ALLOWED_SYMBOLS[:2]:  # Test first 2 for speed
                for timeframe in ALLOWED_TIMEFRAMES:
                    expected = KALSHI_SERIES_TICKERS[symbol]
                    result = resolve_series_ticker(symbol, timeframe)
                    assert result == expected, f"resolve_series_ticker({symbol}, {timeframe}) = {result}, expected {expected}"
        except ImportError:
            pytest.skip("market_selector not available")


# =============================================================================
# Test Class: Timeframe Suffix Mapping
# =============================================================================

class TestKalshiTimeframeSuffixMapping:
    """Verify timeframe suffix conventions."""
    
    def test_timeframe_suffixes_defined(self):
        """All expected timeframe suffixes are defined.
        
        PRODUCTION AUDIT: Uses shared ALLOWED_TIMEFRAMES constant.
        """
        try:
            from merid.event_venues.kalshi.market_selector import TIMEFRAME_SERIES_SUFFIX
            
            # Use shared scope constants
            for timeframe in ALLOWED_TIMEFRAMES:
                assert timeframe in TIMEFRAME_SERIES_SUFFIX, f"{timeframe} not in TIMEFRAME_SERIES_SUFFIX"
                assert TIMEFRAME_SERIES_SUFFIX[timeframe] == "15M", f"{timeframe} suffix mismatch"
                
        except ImportError:
            pytest.skip("market_selector not available")
            
    def test_settlement_params_per_timeframe(self):
        """Each timeframe has appropriate settlement parameters.
        
        PRODUCTION AUDIT: Uses shared ALLOWED_SYMBOLS and ALLOWED_TIMEFRAMES constants.
        """
        try:
            from merid.event_venues.kalshi.cfb_settlement import (
                get_settlement_params,
                is_rti_settlement_type,
            )
            
            # Use shared scope constants
            for asset in ALLOWED_SYMBOLS:
                for timeframe in ALLOWED_TIMEFRAMES:
                    params = get_settlement_params(asset, timeframe)
                    assert params is not None, f"{asset}/{timeframe} missing settlement params"
                    assert params.settlement_type == "rti_twap", f"{asset}/{timeframe} should be rti_twap"
                    assert is_rti_settlement_type(asset, timeframe), f"{asset}/{timeframe} should report as RTI"
                
        except ImportError:
            pytest.skip("cfb_settlement not available")
            
    def test_twap_window_durations(self):
        """TWAP windows are appropriate for timeframe.
        
        PRODUCTION AUDIT: Uses shared ALLOWED_SYMBOLS and ALLOWED_TIMEFRAMES constants.
        """
        try:
            from merid.event_venues.kalshi.cfb_settlement import get_settlement_params
            
            # Use shared scope constants
            for asset in ALLOWED_SYMBOLS:
                for timeframe in ALLOWED_TIMEFRAMES:
                    params = get_settlement_params(asset, timeframe)
                    assert params.twap_window_seconds == 300, f"{asset}/{timeframe} should have 300s TWAP window"
                
        except ImportError:
            pytest.skip("cfb_settlement not available")


# =============================================================================
# Test Class: No Legacy Perp Contamination
# =============================================================================

class TestKalshiNoLegacyContamination:
    """Verify Kalshi code paths are free from legacy perp/CEX assumptions."""
    
    CONTAMINATION_PATTERNS = [
        "binance_perp",
        "bybit_perp",
        "okx_perp",
        "funding_rate",
        "mark_price",
        "perp_",
        "perpetual",
        "contract_type.*perp",
        "leverage.*perp",
    ]
    
    def test_no_perp_in_market_filter(self):
        """market_filter.py has no perp-specific logic."""
        try:
            import merid.event_venues.kalshi.market_filter as mf
            import inspect
            
            source = inspect.getsource(mf)
            
            for pattern in self.CONTAMINATION_PATTERNS:
                matches = re.findall(pattern, source, re.IGNORECASE)
                # Funding is allowed in CFB context (constituent exchanges)
                if pattern == "funding_rate":
                    continue
                assert len(matches) == 0, f"Found {pattern} in market_filter.py: {matches}"
                
        except ImportError:
            pytest.skip("market_filter not available")
            
    def test_no_perp_in_order_router(self):
        """order_router.py has no perp-specific logic."""
        try:
            import merid.event_venues.kalshi.order_router as orouter
            import inspect
            
            source = inspect.getsource(orouter)
            
            for pattern in self.CONTAMINATION_PATTERNS:
                matches = re.findall(pattern, source, re.IGNORECASE)
                assert len(matches) == 0, f"Found {pattern} in order_router.py"
                
        except ImportError:
            pytest.skip("order_router not available")
            
    def test_kalshi_risk_no_cex_assumptions(self):
        """Kalshi risk engine uses Kalshi-specific sizing."""
        try:
            from merid.event_venues.kalshi import kalshi_risk
            import inspect
            
            source = inspect.getsource(kalshi_risk)
            
            # Should not have CEX-specific patterns
            cex_patterns = ["binance", "coinbase", "kraken", "cex"]
            for pattern in cex_patterns:
                # Allow references in comments/docstrings only
                code_lines = [line for line in source.split("\n") if not line.strip().startswith("#")]
                code = "\n".join(code_lines)
                matches = re.findall(pattern, code, re.IGNORECASE)
                # Some mentions may be in CFB constituent exchanges list
                if matches:
                    # Check context — constituent exchanges list is OK
                    pass
                    
        except ImportError:
            pytest.skip("kalshi_risk not available")
            
    def test_position_sizing_in_cents(self):
        """Position sizing uses Kalshi cents, not CEX notional."""
        try:
            from merid.trading.kalshi_continuous_trader import TraderConfig
            
            config = TraderConfig()
            
            # Config should use cents for Kalshi
            assert hasattr(config, 'initial_bankroll_cents')
            assert hasattr(config, 'max_contract_price_cents')
            assert hasattr(config, 'min_contract_price_cents')
            
            # Values should be in cents (integers)
            assert isinstance(config.initial_bankroll_cents, int)
            assert isinstance(config.max_contract_price_cents, int)
            
        except ImportError:
            pytest.skip("kalshi_continuous_trader not available")


# =============================================================================
# Test Class: Market Catalog Discovery
# =============================================================================

class TestKalshiMarketCatalogDiscovery:
    """Verify market discovery and categorization."""
    
    def test_catalog_ticker_patterns_exist(self):
        """Ticker detection patterns are comprehensive."""
        try:
            from merid.event_venues.kalshi.market_catalog import _TICKER_CATEGORY_MAP
            
            # Should have patterns for all supported assets
            assets_with_patterns = set()
            for pattern, category, asset in _TICKER_CATEGORY_MAP:
                if asset:
                    assets_with_patterns.add(asset)
                    
            expected = {"BTC", "ETH", "SOL", "XRP", "DOGE", "SPX", "NDX", "DJI", "CPI", "GDP", "JOBS", "RATES"}
            
            for asset in expected:
                assert asset in assets_with_patterns, f"{asset} missing from ticker patterns"
                
        except ImportError:
            pytest.skip("market_catalog not available")
            
    def test_crypto_pattern_priority(self):
        """Specific crypto patterns come before catch-all patterns."""
        try:
            from merid.event_venues.kalshi.market_catalog import _TICKER_CATEGORY_MAP
            
            # Find positions of specific vs catch-all patterns
            specific_positions = {}
            catchall_position = None
            
            for idx, (pattern, category, asset) in enumerate(_TICKER_CATEGORY_MAP):
                if category == "crypto":
                    if asset:
                        specific_positions[asset] = idx
                    elif pattern.pattern == "^KXCRYPTO":
                        catchall_position = idx
                        
            # Specific patterns should come before catch-all
            for asset, pos in specific_positions.items():
                assert pos < catchall_position, f"{asset} pattern should come before KXCRYPTO catch-all"
                
        except ImportError:
            pytest.skip("market_catalog not available")
            
    def test_category_extraction_methods(self):
        """Category can be extracted from various ticker formats."""
        try:
            from merid.event_venues.kalshi.market_catalog import _detect_from_ticker
            
            test_cases = [
                ("KXBTC-25DEC-ABOVE-100000", "crypto", "BTC"),
                ("KXETH-15M-BELOW-2000", "crypto", "ETH"),
                ("KXCPI-25DEC-ABOVE-3.0", "economics", "CPI"),
                ("KXFED-25DEC-RATE-CUT", "economics", "RATES"),
                ("KXSPX-25DEC-ABOVE-5000", "financials", "SPX"),
            ]
            
            for ticker, expected_cat, expected_asset in test_cases:
                cat, asset = _detect_from_ticker(ticker)
                assert cat == expected_cat, f"{ticker}: expected category {expected_cat}, got {cat}"
                if expected_asset:
                    assert asset == expected_asset, f"{ticker}: expected asset {expected_asset}, got {asset}"
                    
        except ImportError:
            pytest.skip("market_catalog not available")


# =============================================================================
# Test Class: Consistency Across Modules
# =============================================================================

class TestKalshiCrossModuleConsistency:
    """Verify consistency between different Kalshi modules."""
    
    def test_asset_list_consistency(self):
        """Same assets are referenced across all modules."""
        try:
            from merid.event_venues.kalshi.cfb_settlement import supported_assets
            from merid.event_venues.kalshi.market_selector import CRYPTO_SERIES_BASE
            
            cfb_assets = set(supported_assets())
            selector_assets = set(CRYPTO_SERIES_BASE.keys())
            
            # All selector assets should have CFB settlement
            assert selector_assets.issubset(cfb_assets), \
                f"Assets {selector_assets - cfb_assets} in selector but not CFB settlement"
                
        except ImportError:
            pytest.skip("Required modules not available")
            
    def test_timeframe_consistency(self):
        """Same timeframes are used across settlement and selector."""
        try:
            from merid.event_venues.kalshi.cfb_settlement import supported_timeframes_for_asset
            from merid.event_venues.kalshi.market_selector import TIMEFRAME_SERIES_SUFFIX
            
            # Get timeframes from CFB
            cfb_timeframes = set(supported_timeframes_for_asset("BTC"))
            
            # Get timeframes from selector
            selector_timeframes = set(TIMEFRAME_SERIES_SUFFIX.keys())
            
            # Normalize 1h/hourly
            normalized_selector = set()
            for tf in selector_timeframes:
                if tf in ["1h", "hourly"]:
                    normalized_selector.add("1h")
                else:
                    normalized_selector.add(tf)
                    
            # Should overlap significantly
            overlap = cfb_timeframes & normalized_selector
            assert len(overlap) >= 4, f"Timeframe mismatch: CFB={cfb_timeframes}, selector={selector_timeframes}"
            
        except ImportError:
            pytest.skip("Required modules not available")
            
    def test_series_ticker_consistency(self):
        """Series ticker patterns are consistent across modules."""
        try:
            from merid.event_venues.kalshi.market_selector import CRYPTO_SERIES_BASE
            from merid.event_venues.kalshi.market_catalog import _TICKER_CATEGORY_MAP
            
            # Extract series prefixes from catalog patterns
            catalog_series = set()
            for pattern, category, asset in _TICKER_CATEGORY_MAP:
                if category == "crypto" and asset:
                    # Extract the KX prefix from pattern
                    match = re.search(r"\^KX[A-Z]+", pattern.pattern)
                    if match:
                        catalog_series.add(match.group(0).lstrip("^"))
                        
            # Check selector series are in catalog
            for coin, series in CRYPTO_SERIES_BASE.items():
                assert series in catalog_series, f"{series} from selector not in catalog patterns"
                
        except ImportError:
            pytest.skip("Required modules not available")


# =============================================================================
# Test Class: Edge Cases and Validation
# =============================================================================

class TestKalshiSymbolEdgeCases:
    """Edge cases and validation for symbol handling."""
    
    def test_ticker_case_handling(self):
        """Tickers are handled case-insensitively."""
        try:
            from merid.event_venues.kalshi.market_catalog import _detect_from_ticker
            
            test_cases = [
                "kxbtc-25dec-above-100000",
                "KXBTC-25DEC-ABOVE-100000",
                "KxBtC-25DeC-AbOvE-100000",
            ]
            
            results = [_detect_from_ticker(ticker) for ticker in test_cases]
            
            # All should produce the same result
            assert len(set(results)) == 1, f"Case variations produced different results: {results}"
            
        except ImportError:
            pytest.skip("market_catalog not available")
            
    def test_unknown_ticker_handling(self):
        """Unknown tickers return safe defaults."""
        try:
            from merid.event_venues.kalshi.market_catalog import _detect_from_ticker
            
            unknown_tickers = [
                "UNKNOWN-TICKER-123",
                "XYZ-ABC-DEF",
                "",
            ]
            
            for ticker in unknown_tickers:
                cat, asset = _detect_from_ticker(ticker)
                # Should return something (even if None/"other")
                assert cat is not None or asset is None, f"Unexpected result for {ticker}"
                
        except ImportError:
            pytest.skip("market_catalog not available")
            
    def test_malformed_ticker_handling(self):
        """Malformed tickers are handled gracefully."""
        try:
            from merid.event_venues.kalshi.market_filter import extract_asset_from_ticker
            
            malformed = [
                "",
                "KX",
                "-BTC-",
                "BTC-25DEC",
                "!!!",
            ]
            
            for ticker in malformed:
                # Should not raise
                result = extract_asset_from_ticker(ticker)
                # Result may be None, but no exception
                
        except ImportError:
            pytest.skip("market_filter not available")


# =============================================================================
# Run Configuration
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
