"""
Production Trading Scope Constants for Tests

This module centralizes the production audit invariants for trading scope:
- Allowed assets: BTC, ETH, SOL, XRP, DOGE
- Allowed timeframe: 15m only

These constants are used across test suites to ensure tests enforce the
production scope and detect regressions if someone re-introduces
non-compliant assets or timeframes.

Reference: PRODUCTION_AUDIT_SUMMARY_2026-04-15.md
"""

# Production trading scope
ALLOWED_SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
ALLOWED_TIMEFRAMES = ["15m"]

# Series ticker format for 15m timeframe
SERIES_TICKER_FORMAT = "{asset}15M"  # e.g., "KXBTC15M"
FULL_TICKER_FORMAT = "KX{asset}15M-{series}"  # e.g., "KXBTC15M-T"

# Kalshi series tickers for allowed assets
KALSHI_SERIES_TICKERS = {
    "BTC": "KXBTC15M",
    "ETH": "KXETH15M",
    "SOL": "KXSOL15M",
    "XRP": "KXXRP15M",
    "DOGE": "KXDOGE15M",
}


def is_symbol_allowed(symbol: str) -> bool:
    """Check if a symbol is in the production trading scope."""
    return symbol.upper() in ALLOWED_SYMBOLS


def is_timeframe_allowed(timeframe: str) -> bool:
    """Check if a timeframe is in the production trading scope."""
    return timeframe.lower() == "15m"


def validate_scope(symbol: str, timeframe: str) -> tuple[bool, str]:
    """
    Validate that a symbol/timeframe pair is within production scope.
    
    Returns:
        (is_valid, error_message) tuple
    """
    if not is_symbol_allowed(symbol):
        return False, f"Symbol '{symbol}' not in production scope: {ALLOWED_SYMBOLS}"
    
    if not is_timeframe_allowed(timeframe):
        return False, f"Timeframe '{timeframe}' not in production scope: {ALLOWED_TIMEFRAMES}"
    
    return True, ""


# =============================================================================
# Scope Regression Tests
# =============================================================================

import pytest


class TestProductionScopeRegression:
    """Regression tests to ensure production scope invariants are maintained.
    
    PRODUCTION AUDIT: These tests enforce the BTC/ETH/SOL/XRP/DOGE 15m only
    trading scope. Run with: pytest -m production_audit
    """
    
    @pytest.mark.production_audit
    def test_allowed_symbols_constant_is_complete(self):
        """ALLOWED_SYMBOLS should contain exactly the 5 crypto assets."""
        assert len(ALLOWED_SYMBOLS) == 5
        assert set(ALLOWED_SYMBOLS) == {"BTC", "ETH", "SOL", "XRP", "DOGE"}
    
    @pytest.mark.production_audit
    def test_allowed_timeframes_constant_is_15m_only(self):
        """ALLOWED_TIMEFRAMES should contain only '15m'."""
        assert len(ALLOWED_TIMEFRAMES) == 1
        assert ALLOWED_TIMEFRAMES[0] == "15m"
    
    @pytest.mark.production_audit
    def test_validate_scope_rejects_invalid_symbol(self):
        """validate_scope should reject symbols outside production scope."""
        is_valid, error = validate_scope("ADA", "15m")
        assert not is_valid
        assert "ADA" in error
    
    @pytest.mark.production_audit
    def test_validate_scope_rejects_invalid_timeframe(self):
        """validate_scope should reject timeframes outside production scope."""
        is_valid, error = validate_scope("BTC", "1h")
        assert not is_valid
        assert "1h" in error
    
    @pytest.mark.production_audit
    def test_validate_scope_accepts_valid_pair(self):
        """validate_scope should accept valid symbol/timeframe pairs."""
        for symbol in ALLOWED_SYMBOLS:
            for timeframe in ALLOWED_TIMEFRAMES:
                is_valid, error = validate_scope(symbol, timeframe)
                assert is_valid, f"{symbol}/{timeframe} should be valid: {error}"
                assert error == ""
    
    @pytest.mark.production_audit
    def test_kalshi_series_tickers_are_complete(self):
        """KALSHI_SERIES_TICKERS should cover all allowed symbols."""
        assert set(KALSHI_SERIES_TICKERS.keys()) == set(ALLOWED_SYMBOLS)
    
    @pytest.mark.production_audit
    def test_kalshi_series_tickers_follow_format(self):
        """KALSHI_SERIES_TICKERS should follow the KX{ASSET}15M format."""
        for symbol, ticker in KALSHI_SERIES_TICKERS.items():
            assert ticker.startswith("KX")
            assert ticker.endswith("15M")
            assert symbol in ticker


class TestBankrollFailClosedBehavior:
    """Regression tests to ensure fail-closed bankroll behavior is maintained.
    
    PRODUCTION AUDIT: Bankroll service must fail-closed - no fallback to
    synthetic or default equity values. When bankroll is unknown or errors,
    the system must block trading and return 0 equity.
    
    Run with: pytest -m production_audit
    """
    
    @pytest.mark.production_audit
    def test_default_equity_cents_returns_zero_without_provider(self):
        """When no equity provider is set, should return 0 (fail-closed)."""
        try:
            from merid.guards.global_risk_guard import default_equity_cents, set_equity_provider
            
            # Ensure no provider is set
            set_equity_provider(None)
            
            # Should return 0 (fail-closed) instead of falling back to default
            equity = default_equity_cents()
            assert equity == 0, f"Expected 0 (fail-closed), got {equity}"
        except ImportError:
            pytest.skip("global_risk_guard not available")
    
    @pytest.mark.production_audit
    def test_resolve_equity_cents_returns_zero_on_provider_exception(self):
        """When equity provider raises exception, should return 0 (fail-closed)."""
        try:
            from merid.guards.global_risk_guard import resolve_equity_cents, set_equity_provider
            
            def failing_provider():
                raise RuntimeError("Bankroll service unavailable")
            
            set_equity_provider(failing_provider)
            
            # Should return 0 (fail-closed) instead of falling back
            equity = resolve_equity_cents()
            assert equity == 0, f"Expected 0 (fail-closed), got {equity}"
            
            # Clean up
            set_equity_provider(None)
        except ImportError:
            pytest.skip("global_risk_guard not available")
    
    @pytest.mark.production_audit
    def test_check_intent_rejects_orders_with_zero_equity(self):
        """When equity is 0 (fail-closed), check_intent should reject orders."""
        try:
            from merid.guards.global_risk_guard import check_intent, set_equity_provider
            
            # Set equity to 0 (fail-closed state)
            set_equity_provider(lambda: 0)
            
            ok, reason = check_intent(
                ticker="KXBTC15M-T",
                asset="BTC",
                side="yes",
                action="buy",
                price_cents=60,
                count=100,
            )
            
            # Should reject due to fail-closed bankroll
            assert not ok, "Order should be rejected when equity is 0 (fail-closed)"
            assert "fail-closed" in reason.lower() or "equity" in reason.lower(), \
                f"Error message should mention fail-closed or equity, got: {reason}"
            
            # Clean up
            set_equity_provider(None)
        except ImportError:
            pytest.skip("global_risk_guard not available")
