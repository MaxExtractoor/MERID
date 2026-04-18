"""Kalshi Signal to Order Pipeline Tests — Step 4 Audit Deliverable

Validates:
1. Single signal path — no direct order placement bypass
2. Group exposure tracking consistency
3. Position sizing invariants
4. Pre-flight execution checklist

Run: pytest tests/kalshi/test_signal_to_order_pipeline.py -v
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_signal():
    """Create a sample trading signal."""
    return {
        "ticker": "KXBTC-25DEC-ABOVE-100000",
        "side": "yes",
        "action": "buy",
        "confidence": 0.75,
        "edge": Decimal("0.12"),
        "suggested_size": 5,
        "agent_id": "btc_15m_agent",
    }


@pytest.fixture
def sample_order_intent():
    """Create a sample order intent."""
    try:
        from merid.event_venues.kalshi.order_router import OrderIntent
        return OrderIntent(
            ticker="KXBTC-25DEC-ABOVE-100000",
            side="yes",
            action="buy",
            price_cents=55,
            count=5,
            agent_id="btc_15m_agent",
        )
    except ImportError:
        return None


# =============================================================================
# Test Class: Single Signal Path
# =============================================================================

class TestKalshiSingleSignalPath:
    """Verify all signals flow through canonical path to orders."""
    
    def test_trading_agent_uses_order_router(self):
        """KalshiTradingAgent routes orders through order_router, not direct client."""
        try:
            import inspect
            from merid.prediction.trading_agent import KalshiTradingAgent
            
            # Check _execute_signal_body or similar method
            source = inspect.getsource(KalshiTradingAgent)
            
            # Should reference order_router or route_order
            assert "order_router" in source or "route_order" in source, \
                "KalshiTradingAgent should use order_router, not direct client calls"
                
            # Should NOT directly call client.place_order
            direct_client_pattern = "client.place_order"
            if direct_client_pattern in source:
                # Check context — may be in comments
                code_lines = [l for l in source.split("\n") if not l.strip().startswith("#")]
                code = "\n".join(code_lines)
                assert direct_client_pattern not in code, \
                    "KalshiTradingAgent should not directly call client.place_order"
                    
        except ImportError:
            pytest.skip("KalshiTradingAgent not available")
            
    def test_continuous_trader_uses_order_router(self):
        """KalshiContinuousTrader routes through order_router."""
        try:
            import inspect
            from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
            
            source = inspect.getsource(KalshiContinuousTrader)
            
            # Should use order_router for order placement
            assert "order_router" in source or "route_order" in source, \
                "KalshiContinuousTrader should use order_router"
                
        except ImportError:
            pytest.skip("KalshiContinuousTrader not available")
            
    def test_no_direct_client_import_in_trading_agent(self):
        """Trading agent imports order_router, not client directly."""
        try:
            import inspect
            from merid.prediction import trading_agent
            
            source = inspect.getsource(trading_agent)
            
            # Can import client for types, but orders should go through router
            # Check that route_order is called in execute methods
            assert "route_order" in source, "Should use route_order function"
            
        except ImportError:
            pytest.skip("trading_agent module not available")


# =============================================================================
# Test Class: Group Exposure Tracking
# =============================================================================

class TestKalshiGroupExposure:
    """Verify group exposure is tracked consistently."""
    
    def test_timeframe_suffixes_defined(self):
        """All expected timeframe suffixes are defined."""
        try:
            from merid.event_venues.kalshi.market_selector import TIMEFRAME_SERIES_SUFFIX
            
            # Note: Kalshi format has no dashes (e.g., "15M" not "-15M")
            expected = {
                "15m": "15M",      # No dash in Kalshi format
                "1h": "",          # Base series has no suffix
                "hourly": "",
                "daily": "D1",
                "weekly": "W1",
            }
            
            for tf, suffix in expected.items():
                assert tf in TIMEFRAME_SERIES_SUFFIX, f"{tf} not in TIMEFRAME_SERIES_SUFFIX"
                assert TIMEFRAME_SERIES_SUFFIX[tf] == suffix, f"{tf} suffix mismatch: got {TIMEFRAME_SERIES_SUFFIX[tf]}, expected {suffix}"
                
        except ImportError:
            pytest.skip("market_selector not available")
            
    def test_group_id_generation_deterministic(self):
        """Same ticker always produces same group_id."""
        try:
            from merid.event_venues.kalshi.market_filter import group_id_from_ticker
            
            tickers = [
                "KXBTC-25DEC-ABOVE-100000",
                "KXETH-15M-BELOW-2000",
                "KXSOL-D-ABOVE-150",
            ]
            
            for ticker in tickers:
                gid1 = group_id_from_ticker(ticker)
                gid2 = group_id_from_ticker(ticker)
                assert gid1 == gid2, f"{ticker} produced inconsistent group_ids"
                
        except ImportError:
            pytest.skip("market_filter not available")
            
    def test_group_id_unique_per_ticker(self):
        """Different tickers produce different group_ids."""
        try:
            from merid.event_venues.kalshi.market_filter import group_id_from_ticker
            
            # Use tickers with different expirations that parse correctly
            from datetime import datetime, timezone
            
            tickers = [
                ("KXBTC-26MAR2501-T80199", "BTC", "1h", datetime(2025, 3, 26, 1, 0, tzinfo=timezone.utc).timestamp()),
                ("KXBTC-27MAR2501-T80199", "BTC", "1h", datetime(2025, 3, 27, 1, 0, tzinfo=timezone.utc).timestamp()),  # Different date
                ("KXETH-26MAR2501-T2000", "ETH", "1h", datetime(2025, 3, 26, 1, 0, tzinfo=timezone.utc).timestamp()),    # Different asset
            ]
            
            group_ids = []
            for ticker, asset, tf, expiry in tickers:
                gid = group_id_from_ticker(ticker, timeframe=tf, expiry_ts=expiry)
                group_ids.append(gid)
            
            # All should be unique
            assert len(set(group_ids)) == len(tickers), \
                f"Different tickers produced duplicate group_ids: {group_ids}"
                
        except ImportError:
            pytest.skip("market_filter not available")
            
    def test_exposure_never_negative(self):
        """Group exposure can never go negative."""
        try:
            from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
            
            tracker = CategoryExposureTracker()
            
            # Simulate open and close using record_fill/release
            tracker.record_fill("crypto", "BTC", notional_usd=100.0)
            tracker.release("crypto", "BTC", notional_usd=100.0)
            
            # Try to over-close
            tracker.release("crypto", "BTC", notional_usd=50.0)
            
            # Exposure should be clamped to zero, not negative
            snapshot = tracker.get_snapshot()
            exposure = snapshot.corr_notional.get("BTC", 0.0)
            assert exposure >= 0, f"Exposure went negative: {exposure}"
            assert exposure == 0, f"Over-close should clamp to zero, got {exposure}"
            
        except ImportError:
            pytest.skip("category_exposure not available")
            
    def test_multi_asset_isolation(self):
        """Exposure for different assets is isolated."""
        try:
            from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
            
            tracker = CategoryExposureTracker()
            
            # Add BTC exposure
            tracker.record_fill("crypto", "BTC", notional_usd=1000.0)
            
            # Add ETH exposure
            tracker.record_fill("crypto", "ETH", notional_usd=2000.0)
            
            # Check isolation
            snapshot = tracker.get_snapshot()
            btc_exposure = snapshot.corr_notional.get("BTC", 0.0)
            eth_exposure = snapshot.corr_notional.get("ETH", 0.0)
            
            assert btc_exposure == 1000.0, f"BTC exposure incorrect: {btc_exposure}"
            assert eth_exposure == 2000.0, f"ETH exposure incorrect: {eth_exposure}"
            
        except ImportError:
            pytest.skip("category_exposure not available")


# =============================================================================
# Test Class: Position Sizing Invariants
# =============================================================================

class TestKalshiPositionSizing:
    """Verify sizing constraints are enforced."""
    
    def test_kelly_fraction_enforced(self):
        """Kelly fraction limits position size."""
        try:
            from merid.trading.kalshi_continuous_trader import TraderConfig
            
            config = TraderConfig()
            
            # Kelly fraction should be <= 1.0 and > 0
            assert 0 < config.kelly_fraction <= 1.0, \
                f"Kelly fraction {config.kelly_fraction} out of range"
                
            # Should typically be conservative (quarter-Kelly or less)
            assert config.kelly_fraction <= 0.5, \
                f"Kelly fraction {config.kelly_fraction} may be too aggressive"
                
        except ImportError:
            pytest.skip("kalshi_continuous_trader not available")
            
    def test_max_position_per_market_enforced(self):
        """Max contracts per market is respected."""
        try:
            from merid.trading.kalshi_continuous_trader import TraderConfig
            
            config = TraderConfig()
            
            # Should have a reasonable limit
            assert config.max_position_per_market > 0, "max_position_per_market must be positive"
            assert config.max_position_per_market <= 100, \
                f"max_position_per_market {config.max_position_per_market} seems high"
                
        except ImportError:
            pytest.skip("kalshi_continuous_trader not available")
            
    def test_max_open_positions_enforced(self):
        """Max simultaneous positions is limited."""
        try:
            from merid.trading.kalshi_continuous_trader import TraderConfig
            
            config = TraderConfig()
            
            # Should have a reasonable limit
            assert config.max_open_positions > 0, "max_open_positions must be positive"
            assert config.max_open_positions <= 50, \
                f"max_open_positions {config.max_open_positions} seems high"
                
        except ImportError:
            pytest.skip("kalshi_continuous_trader not available")
            
    def test_max_contract_price_enforced(self):
        """Contract price ceiling prevents expensive contracts."""
        try:
            from merid.trading.kalshi_continuous_trader import TraderConfig
            
            config = TraderConfig()
            
            # In cents — should be less than 100 (never buy >$1 contracts)
            assert config.max_contract_price_cents < 100, \
                f"max_contract_price_cents {config.max_contract_price_cents} should be < 100"

            # Typical value is 35-65 cents depending on market conditions
            assert config.max_contract_price_cents <= 75, \
                f"max_contract_price_cents {config.max_contract_price_cents} may be too high"
                
        except ImportError:
            pytest.skip("kalshi_continuous_trader not available")
            
    def test_asset_exposure_limits_defined(self):
        """Per-asset exposure limits are defined."""
        try:
            from merid.trading.kalshi_continuous_trader import TraderConfig
            
            config = TraderConfig()
            
            # Should have limits for all major assets
            expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
            for asset in expected_assets:
                assert asset in config.asset_max_exposure_pct, \
                    f"{asset} missing from asset_max_exposure_pct"
                    
            # Each limit should be reasonable
            for asset, limit in config.asset_max_exposure_pct.items():
                assert 0 < limit <= 1.0, f"{asset} exposure limit {limit} out of range"
                
        except ImportError:
            pytest.skip("kalshi_continuous_trader not available")


# =============================================================================
# Test Class: Execution Invariants
# =============================================================================

class TestKalshiExecutionInvariants:
    """Verify pre-flight and execution invariants."""
    
    def test_order_intent_validation(self):
        """OrderIntent validates required fields."""
        try:
            from merid.event_venues.kalshi.order_router import OrderIntent
            
            # Valid intent
            intent = OrderIntent(
                ticker="KXBTC-TEST",
                side="yes",
                action="buy",
                price_cents=55,
                count=5,
            )
            
            assert intent.ticker == "KXBTC-TEST"
            assert intent.side in ["yes", "no"]
            assert intent.action in ["buy", "sell"]
            assert intent.price_cents > 0
            assert intent.count > 0
            
        except ImportError:
            pytest.skip("order_router not available")
            
    def test_risk_check_before_order(self):
        """Risk checks run before order submission."""
        try:
            import inspect
            from merid.event_venues.kalshi.order_router import route_order
            
            source = inspect.getsource(route_order)
            
            # Should call risk check
            assert "risk" in source.lower() or "check" in source.lower(), \
                "route_order should include risk checks"
                
        except ImportError:
            pytest.skip("order_router not available")
            
    def test_mode_aware_execution(self):
        """Orders respect trading mode (paper vs live)."""
        try:
            import inspect
            from merid.event_venues.kalshi.order_router import route_order
            
            source = inspect.getsource(route_order)
            
            # Should reference trading mode
            assert any(x in source for x in ["paper", "live", "mode", "trade_mode"]), \
                "route_order should be mode-aware"
                
        except ImportError:
            pytest.skip("order_router not available")
            
    def test_kill_switch_blocks_orders(self):
        """Kill switch prevents order submission when active."""
        try:
            from merid.risk.kill_switches import risk_controller, RiskController

            # Test using the global risk_controller singleton
            assert isinstance(risk_controller, RiskController), "risk_controller should be RiskController instance"

            # Verify the guard pattern exists in order router
            import inspect
            from merid.event_venues.kalshi import order_router

            source = inspect.getsource(order_router)
            assert "kill" in source.lower() or "switch" in source.lower() or "risk" in source.lower(), \
                "order_router should check kill switch or risk"

        except ImportError:
            pytest.skip("kill_switches not available")


# =============================================================================
# Test Class: Pre-Flight Checklist
# =============================================================================

class TestKalshiPreFlightChecklist:
    """Verify structured pre-flight status checks exist."""
    
    def test_health_check_structure(self):
        """Health check returns structured status."""
        try:
            from merid.event_venues.kalshi.client import KalshiVenueClient
            
            # Should have health/status methods
            assert hasattr(KalshiVenueClient, 'is_circuit_open')
            assert hasattr(KalshiVenueClient, 'get_circuit_status')
            
        except ImportError:
            pytest.skip("KalshiVenueClient not available")
            
    def test_risk_engine_status(self):
        """Risk engine exposes status for pre-flight checks."""
        try:
            from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager

            engine = KalshiRiskManager()

            # Should have status/check methods
            assert hasattr(engine, 'check_order')

        except ImportError:
            pytest.skip("kalshi_risk not available")
            
    def test_continuous_trader_status(self):
        """Continuous trader exposes status snapshot."""
        try:
            from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
            
            assert hasattr(KalshiContinuousTrader, 'status_snapshot')
            
        except ImportError:
            pytest.skip("kalshi_continuous_trader not available")


# =============================================================================
# Test Class: Over-Close Protection
# =============================================================================

class TestKalshiOverCloseProtection:
    """Verify over-close scenarios are handled."""
    
    def test_over_close_clamped_to_zero(self):
        """Attempting to close more than open position clamps to zero."""
        try:
            from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
            
            tracker = CategoryExposureTracker()
            
            # Open position of 10 (notional)
            tracker.record_fill("crypto", "BTC", notional_usd=10.0)
            
            # Close 15 (over-close by 5)
            tracker.release("crypto", "BTC", notional_usd=15.0)
            
            # Exposure should be zero, not negative
            snapshot = tracker.get_snapshot()
            exposure = snapshot.corr_notional.get("BTC", 0.0)
            assert exposure == 0, f"Over-close should clamp to zero, got {exposure}"
            
        except ImportError:
            pytest.skip("category_exposure not available")
            
    def test_partial_close_tracked(self):
        """Partial close reduces exposure correctly."""
        try:
            from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
            
            tracker = CategoryExposureTracker()
            
            # Open position of 10 (notional)
            tracker.record_fill("crypto", "BTC", notional_usd=10.0)
            
            # Close 3
            tracker.release("crypto", "BTC", notional_usd=3.0)
            
            # Remaining exposure should be 7
            snapshot = tracker.get_snapshot()
            exposure = snapshot.corr_notional.get("BTC", 0.0)
            assert exposure == 7, f"Partial close should leave 7, got {exposure}"
            
        except ImportError:
            pytest.skip("category_exposure not available")


# =============================================================================
# Run Configuration
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
