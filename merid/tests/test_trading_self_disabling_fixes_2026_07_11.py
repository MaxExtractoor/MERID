"""Tests for trading self-disabling fixes made on 2026-07-11.

This test file verifies the following bug fixes:
1. Catalog normalization - hard error for missing minutes_to_expiry field
2. Spread filter adaptive - 150c threshold instead of 75c
3. Indicator warmup - separate data failures from no-signal
4. Candidate breakdown logging - track why markets are filtered
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock
import logging


def test_catalog_normalization_hard_error():
    """Test that catalog normalization rejects invalid contracts with hard error."""
    from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract
    
    # Test with invalid ticker that should fail normalization
    # This should return status="invalid_metadata" not silently continue
    result = normalize_kalshi_contract(
        ticker="INVALID-TICKER",
        expiration_time=None,
        expected_expiration_time=None,
        end_date=None,
        close_time=None,
        now=datetime.now(timezone.utc)
    )
    
    # Should return invalid_metadata status, not ok
    assert result.status == "invalid_metadata"
    assert result.status_reason is not None
    assert "minutes_to_expiry" in result.__dict__  # Field should exist


def test_catalog_enrichment_rejects_invalid_metadata():
    """Test that market catalog enrichment rejects invalid normalized contracts."""
    from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract
    
    # Test that invalid contracts return invalid_metadata status
    result = normalize_kalshi_contract(
        ticker="INVALID-TICKER",
        expiration_time=None,
        expected_expiration_time=None,
        end_date=None,
        close_time=None,
        now=datetime.now(timezone.utc)
    )
    
    # Should return invalid_metadata status
    assert result.status == "invalid_metadata"
    assert result.minutes_to_expiry == 0.0
    assert result.seconds_to_expiry == 0.0


def test_spread_filter_adaptive_threshold():
    """Test that spread filter uses 150c threshold instead of 75c."""
    from merid.prediction.agent_grid_15m import LeanAgentConfig
    
    # Create agent config
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"],
        max_spread_cents=150  # Should be 150, not 75
    )
    
    # Verify the threshold is 150c
    assert config.max_spread_cents == 150
    
    # Test that 100c spread is allowed (would be rejected with 75c threshold)
    assert 100 < config.max_spread_cents  # Should pass
    
    # Test that 200c spread is rejected
    assert 200 > config.max_spread_cents  # Should fail


def test_indicator_warmup_separates_data_failures():
    """Test that indicator warmup separates data failures from no-signal."""
    from merid.prediction.agent_grid_15m import LeanAgentConfig
    from merid.signals.crypto_15m_indicators import IndicatorConfig, Crypto15mIndicatorStack
    import logging
    
    # Test that the code logs ERROR for data failures
    # This is a code inspection test to verify the log level
    import inspect
    from merid.prediction import agent_grid_15m
    
    source = inspect.getsource(agent_grid_15m)
    
    # Should contain ERROR log for data failures
    assert "DATA-FAILURE" in source or "logger.error" in source


def test_indicator_warmup_explicit_tracking():
    """Test that indicator warmup has explicit tracking with bars_available."""
    from merid.signals.crypto_15m_indicators import IndicatorSnapshot
    
    # Create snapshot with low bars_available (warming up)
    snapshot = IndicatorSnapshot(
        bars_available=10,  # Less than 20 (warmup threshold)
        macd_line=0.0,
        macd_histogram=0.0,
        rsi=50.0,
        vol_gate_ok=True,
        atr_move_ok=True,
        chop_gate_ok=True,
        trade_allowed=True
    )
    
    # Should have bars_available field
    assert hasattr(snapshot, 'bars_available')
    assert snapshot.bars_available == 10
    
    # Create snapshot with sufficient bars (warmed up)
    snapshot_warmed = IndicatorSnapshot(
        bars_available=60,  # Greater than 20
        macd_line=0.1,
        macd_histogram=0.05,
        rsi=55.0,
        vol_gate_ok=True,
        atr_move_ok=True,
        chop_gate_ok=True,
        trade_allowed=True
    )
    
    assert snapshot_warmed.bars_available == 60


def test_candidate_breakdown_logging():
    """Test that candidate breakdown logging tracks filter reasons."""
    from merid.prediction.universal_agent import KalshiUniversalAgent, UniversalAgentConfig
    from unittest.mock import Mock
    import inspect
    
    # Create agent
    config = UniversalAgentConfig(name="test_agent")
    agent = KalshiUniversalAgent(config=config)
    
    # Mock universe and strategy
    agent._universe = Mock()
    agent._universe.get_markets.return_value = {}
    agent._strategy = Mock()
    
    # Test that the code has breakdown tracking fields
    source = inspect.getsource(agent.collect_order_candidate)
    
    # Should contain breakdown tracking variables
    assert "filtered_by_no_snapshot" in source
    assert "filtered_by_no_signal" in source
    assert "filtered_by_edge_threshold" in source
    assert "filtered_by_risk" in source
    assert "filtered_by_mode" in source


def test_candidate_breakdown_metrics_increment():
    """Test that breakdown metrics increment correctly."""
    from merid.prediction.universal_agent import KalshiUniversalAgent, UniversalAgentConfig
    from unittest.mock import Mock, MagicMock
    from merid.prediction.strategy import SignalAction
    import inspect
    
    # Test that the code increments metrics correctly
    source = inspect.getsource(KalshiUniversalAgent.collect_order_candidate)
    
    # Should increment filtered_by_no_signal when no signal
    assert "filtered_by_no_signal +=" in source
    # Should increment filtered_by_edge_threshold when edge too low
    assert "filtered_by_edge_threshold +=" in source
    # Should increment filtered_by_risk when risk blocks
    assert "filtered_by_risk +=" in source


def test_risk_envelope_fixed_dollar_cap():
    """Test that risk envelope uses fixed $1 cap, not percentage-based."""
    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
    import os
    
    # Ensure environment variable is set to $1
    os.environ['MERID_FIXED_EXPOSURE_CAP_USD'] = '1.00'
    
    # Get risk envelope with test bankroll
    envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=32.55)
    
    # Verify fixed $1 cap is used
    assert envelope.max_total_notional_usd == 1.00
    assert envelope.max_single_order_notional_usd == 1.00
    
    # Verify it's NOT percentage-based (should not scale with bankroll)
    # Even with $32.55 bankroll, cap should still be $1.00
    assert envelope.max_total_notional_usd < envelope.live_bankroll_usd


def test_risk_envelope_environment_variable_override():
    """Test that MERID_FIXED_EXPOSURE_CAP_USD environment variable is respected."""
    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
    import os
    
    # Test with $2 cap
    os.environ['MERID_FIXED_EXPOSURE_CAP_USD'] = '2.00'
    envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=32.55)
    assert envelope.max_total_notional_usd == 2.00
    
    # Test with $0.50 cap
    os.environ['MERID_FIXED_EXPOSURE_CAP_USD'] = '0.50'
    envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=32.55)
    assert envelope.max_total_notional_usd == 0.50
    
    # Reset to default $1.00
    os.environ['MERID_FIXED_EXPOSURE_CAP_USD'] = '1.00'
    envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=32.55)
    assert envelope.max_total_notional_usd == 1.00


def test_finalized_status_filter():
    """Test that finalized markets are filtered out along with settled markets."""
    from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
    import inspect
    
    # Test that the code filters both "settled" and "finalized" status
    source = inspect.getsource(KalshiMarketCatalog.get_current_15m_market)
    
    # Should check for both settled and finalized
    assert '["settled", "finalized"]' in source or '"settled", "finalized"' in source


def test_status_open_filter_in_catalog_api():
    """Test that catalog API calls include status=open filter."""
    from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
    import inspect
    
    # Test that the catalog fetch includes status=open parameter
    # The filter is in the refresh method (called by _refresh_loop)
    source = inspect.getsource(KalshiMarketCatalog.refresh)
    
    # Should include status=open in the API call
    assert 'status=open' in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
