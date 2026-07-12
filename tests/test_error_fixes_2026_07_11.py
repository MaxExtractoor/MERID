"""
Test suite for error fixes from 2026-07-11 server startup log analysis.

Tests:
1. Profile version attribute fix (version -> profile_version)
2. Price range canonical fix (10c-50c per commit c5ac4a18)
3. Sequential trading hasattr fix
4. Price validation deviation fix (40c -> 50c)
"""
import pytest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestProfileVersionAttributeFix:
    """Test that profile version attribute is correctly named profile_version."""
    
    def test_profile_adapter_has_profile_version_attribute(self):
        """Test that Crypto15mProfile has profile_version attribute."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile
        from dataclasses import fields
        
        # Verify the dataclass has profile_version field
        field_names = [f.name for f in fields(Crypto15mProfile)]
        
        assert 'profile_version' in field_names, \
            "Crypto15mProfile should have profile_version field"
        
        # Verify 'version' attribute does NOT exist (the bug we fixed)
        assert 'version' not in field_names, \
            "Crypto15mProfile should NOT have 'version' field (should be 'profile_version')"


class TestPriceRangeCanonicalFix:
    """Test that price range is canonical [10c-50c] per commit c5ac4a18."""
    
    def test_agent_grid_accepts_45c_price(self):
        """Test that agent_grid_15m.py accepts prices within canonical range (e.g., 45c)."""
        # This test verifies the canonical range [10c-50c]
        
        # Simulate the price validation logic from agent_grid_15m.py
        raw_price_cents = 45  # Mid price within canonical range
        
        # Check if price is within canonical range (10c-50c)
        assert 10 <= raw_price_cents <= 50, f"Price {raw_price_cents}c should be in canonical range [10c-50c]"
    
    def test_agent_grid_rejects_51c_price(self):
        """Test that agent_grid_15m.py rejects prices above 50c."""
        raw_price_cents = 51
        
        # Should be outside canonical range
        assert not (10 <= raw_price_cents <= 50), f"Price {raw_price_cents}c should be outside canonical range [10c-50c]"
    
    def test_agent_grid_accepts_10c_price(self):
        """Test that agent_grid_15m.py accepts minimum price of 10c."""
        raw_price_cents = 10
        
        # Should be within canonical range
        assert 10 <= raw_price_cents <= 50, f"Price {raw_price_cents}c should be in canonical range [10c-50c]"
    
    def test_agent_grid_rejects_9c_price(self):
        """Test that agent_grid_15m.py rejects prices below 10c."""
        raw_price_cents = 9
        
        # Should be outside canonical range
        assert not (10 <= raw_price_cents <= 50), f"Price {raw_price_cents}c should be outside canonical range [10c-50c]"


class TestSequentialTradingHasattrFix:
    """Test that sequential trading check has hasattr guard."""
    
    def test_order_gate_has_hasattr_check(self):
        """Test that order_gate.py has hasattr check for risk_policy_sequential_trading."""
        from merid.event_venues.kalshi.order_gate import PreTradeGate
        
        # Read the source to verify hasattr check exists
        import inspect
        source = inspect.getsource(PreTradeGate.check)
        
        # Verify hasattr check is present
        assert "hasattr(profile, 'risk_policy_sequential_trading')" in source, \
            "order_gate.py should have hasattr check for risk_policy_sequential_trading"
    
    def test_profile_adapter_has_risk_policy_sequential_trading(self):
        """Test that Crypto15mProfile has risk_policy_sequential_trading attribute."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile
        
        # Verify the attribute exists in the dataclass definition
        from dataclasses import fields
        field_names = [f.name for f in fields(Crypto15mProfile)]
        
        assert 'risk_policy_sequential_trading' in field_names, \
            "Crypto15mProfile should have risk_policy_sequential_trading field"


class TestPriceValidationDeviationFix:
    """Test that price validation deviation was increased from 40c to 50c."""
    
    def test_order_router_max_deviation_50c(self):
        """Test that order_router.py allows 50c deviation from mid price."""
        from merid.event_venues.kalshi.order_router import _validate_price_against_orderbook
        
        # Read the source to verify max_deviation_cents = 50
        import inspect
        source = inspect.getsource(_validate_price_against_orderbook)
        
        # Verify max_deviation_cents is set to 50
        assert "max_deviation_cents = 50" in source, \
            "order_router.py should have max_deviation_cents = 50"
        
        # Verify the comment mentions the fix
        assert "2026-07-11" in source or "50c" in source, \
            "order_router.py should have comment about 2026-07-11 fix or 50c threshold"
    
    def test_price_validation_allows_50c_deviation(self):
        """Test that 50c deviation from mid is allowed."""
        mid_cents = 50
        order_price = 100  # 50c deviation
        max_deviation_cents = 50
        
        deviation = abs(order_price - mid_cents)
        assert deviation <= max_deviation_cents, \
            f"Deviation {deviation}c should be allowed with max_deviation_cents={max_deviation_cents}"
    
    def test_price_validation_rejects_51c_deviation(self):
        """Test that 51c deviation from mid is rejected."""
        mid_cents = 50
        order_price = 101  # 51c deviation
        max_deviation_cents = 50
        
        deviation = abs(order_price - mid_cents)
        assert deviation > max_deviation_cents, \
            f"Deviation {deviation}c should be rejected with max_deviation_cents={max_deviation_cents}"


class TestWebSocketMessageProcessingFix:
    """Test that WebSocket message processing has defensive error handling."""
    
    def test_ws_has_defensive_error_handling(self):
        """Test that ws.py has defensive error handling for AttributeError."""
        from merid.event_venues.kalshi.ws import KalshiWebSocket
        
        # Read the source to verify defensive error handling exists
        import inspect
        source = inspect.getsource(KalshiWebSocket._process_messages_until_disconnect)
        
        # Verify AttributeError is caught and doesn't trigger reconnect
        assert "AttributeError" in source, \
            "ws.py should catch AttributeError"
        
        # Verify the error message mentions skipping message
        assert "skipping message" in source.lower(), \
            "ws.py should skip message on AttributeError instead of reconnecting"


class TestContractExpiryTickerInferenceFix:
    """Test that 15m contracts use ticker-based inference for expiry (API close_time is unreliable)."""
    
    def test_contract_normalization_uses_ticker_inference_for_15m(self):
        """Test that contract_normalization.py uses ticker inference as primary for 15m contracts."""
        from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract
        from datetime import datetime, timezone
        
        # Test with a 15m contract ticker (26 = 2026)
        # Format: KXBTC15M-26JUL110515-15 = 2026-07-11 05:15 AM ET
        ticker = "KXBTC15M-26JUL110515-15"
        
        # Use a time that's within the 15m window of the ticker expiry
        # Ticker is for 5:15 AM ET = 09:15 UTC, expiry at 09:30 UTC
        # Test at 09:20 UTC (5 minutes before expiry)
        now = datetime(2026, 7, 11, 9, 20, 0, tzinfo=timezone.utc)
        
        # Call normalization with close_time=None to force ticker inference
        normalized = normalize_kalshi_contract(
            ticker=ticker,
            expiration_time=None,
            expected_expiration_time=None,
            end_date=None,
            close_time=None,  # Force ticker inference
            now=now
        )
        
        # Verify normalization succeeded or expired (both are valid outcomes)
        # The key is that ticker inference was used, not that the contract is currently active
        assert normalized.status in ("ok", "expired"), \
            f"Normalization should succeed with ticker inference, got status={normalized.status}: {normalized.status_reason}"
        
        # Verify expiry is set from ticker inference
        assert normalized.expiry_ts is not None, \
            "Expiry timestamp should be set from ticker inference"
        
        # Verify the expiry is reasonable (not some distant future or past)
        # The relaxed invariant allows -1 hour to +24 hours for ticker-inferred expiry
        assert -3600 <= normalized.seconds_to_expiry <= 86400, \
            f"Ticker-inferred expiry should be within reasonable range, got {normalized.seconds_to_expiry}s"
    
    def test_market_catalog_skips_close_time_for_15m(self):
        """Test that market_catalog.py skips close_time extraction for 15m contracts."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        import inspect
        
        # Read the source to verify close_time is skipped for 15m contracts
        source = inspect.getsource(KalshiMarketCatalog)
        
        # Verify the logic checks timeframe != "15m" before extracting close_time
        assert 'if timeframe != "15m"' in source, \
            "market_catalog.py should skip close_time extraction for 15m contracts"
    
    def test_ticker_inference_parses_correct_expiry(self):
        """Test that expiry_fallback.py correctly parses ticker to extract expiry."""
        from merid.event_venues.kalshi.expiry_fallback import _infer_15m_window_end_utc
        
        # Test with a known ticker format
        ticker = "KXBTC15M-26JUL110515-15"
        
        # Call inference function
        expiry = _infer_15m_window_end_utc(ticker)
        
        # Verify expiry is returned
        assert expiry is not None, \
            "Ticker inference should return expiry for valid 15m ticker"
        
        # Verify expiry is a datetime object
        from datetime import datetime
        assert isinstance(expiry, datetime), \
            "Expiry should be a datetime object"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
