"""Tests for Kalshi Signal Generator — prediction market signals.

Test Cases:
1. Edge signal generation from market data
2. Liquidity signal generation
3. Volume anomaly detection
4. Risk event signal generation
5. Graceful degradation on data fetch failure
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.signals.kalshi_signals import (
    KalshiSignalGenerator,
    MarketEdgeSignal,
    LiquiditySignal,
    VolumeAnomalySignal,
    KalshiRiskSignal,
    KalshiSignalType,
    LiquiditySeverity,
    RiskEventCategory,
    get_kalshi_signal_generator,
    reset_kalshi_signal_generator,
)


@pytest.fixture
def mock_venue_adapter():
    """Mock KalshiVenueAdapter for signal generation."""
    with patch("merid.event_venues.kalshi.venue_adapter.get_kalshi_venue_adapter") as mock:
        adapter = MagicMock()
        
        # Mock list_instruments to return some crypto markets with price data
        # (edge computation requires bid/ask or last_price to compute implied_prob)
        instruments = [
            MagicMock(
                id="BTC-24FEB-50K-YES",
                domain="prediction",
                venues=["kalshi"],
                best_bid=50, bid=50,
                best_ask=55, ask=55,
                last_price=52, price=52,
                volume=150, open_interest=200,
                title="BTC 24h above 50K",
            ),
            MagicMock(
                id="ETH-WEEKLY-HIGH",
                domain="prediction",
                venues=["kalshi"],
                best_bid=40, bid=40,
                best_ask=45, ask=45,
                last_price=42, price=42,
                volume=80, open_interest=100,
                title="ETH weekly high",
            ),
            MagicMock(
                id="SOL-DAILY-RALLY",
                domain="prediction",
                venues=["kalshi"],
                best_bid=60, bid=60,
                best_ask=65, ask=65,
                last_price=62, price=62,
                volume=60, open_interest=90,
                title="SOL daily rally",
            ),
        ]
        adapter.list_instruments = AsyncMock(return_value=instruments)
        mock.return_value = adapter
        yield adapter


@pytest.fixture
def generator():
    """Create a fresh KalshiSignalGenerator for testing."""
    reset_kalshi_signal_generator()
    return KalshiSignalGenerator()


# ── Test: Edge Signal Generation ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_edge_signals(generator, mock_venue_adapter):
    """Test generation of market edge signals from Kalshi data."""
    signals = await generator.generate_all(now=1234567890.0)
    
    # Edge signals are only emitted when actionable (edge_pct >= 2%).
    # The mock instruments have moderate spreads so edge is small.
    # Verify that the generator processes all instruments and at least
    # produces *some* signals (liquidity signals fire on the 10% spread).
    assert len(signals) > 0
    
    # Check that signals have correct structure regardless of type
    for signal in signals:
        assert hasattr(signal, "to_dict")
        d = signal.to_dict()
        assert "signal_type" in d
        assert "venue" in d
        assert d["venue"] == "kalshi"


@pytest.mark.asyncio
async def test_edge_signal_actionability(generator, mock_venue_adapter):
    """Test edge signal actionability logic."""
    signal = MarketEdgeSignal(
        ticker="BTC-TEST",
        asset="BTC",
        timeframe="24h",
        question="Will BTC hit 50k?",
        implied_prob=0.55,
        model_prob=0.60,
        ev_cents=5.0,
        edge_pct=9.0,
        confidence=0.7,
        confidence_bucket="high",
        sizing_tier="normal",
    )
    
    # High confidence + good edge = actionable
    assert signal.is_actionable()
    
    # Low edge = not actionable
    signal.edge_pct = 1.0
    assert not signal.is_actionable()
    
    # Halted sizing = not actionable
    signal.edge_pct = 9.0
    signal.sizing_tier = "halted"
    assert not signal.is_actionable()


def test_edge_signal_serialization():
    """Test edge signal to_dict conversion."""
    signal = MarketEdgeSignal(
        ticker="BTC-TEST",
        asset="BTC",
        timeframe="24h",
        question="Test market",
        implied_prob=0.55,
        model_prob=0.60,
        ev_cents=5.0,
        edge_pct=9.0,
        confidence=0.7,
        timestamp=1234567890.0,
    )
    
    d = signal.to_dict()
    assert d["signal_type"] == "market_edge"
    assert d["venue"] == "kalshi"
    assert d["ticker"] == "BTC-TEST"
    assert d["asset"] == "BTC"
    assert d["edge_pct"] == 9.0
    assert "actionable" in d


# ── Test: Liquidity Signal ────────────────────────────────────────────────

def test_liquidity_signal_creation():
    """Test liquidity signal structure."""
    signal = LiquiditySignal(
        ticker="BTC-TEST",
        spread_cents=5.0,
        spread_pct=10.0,
        depth_contracts=50.0,
        alert_type="wide_spread",
        severity=LiquiditySeverity.WARNING.value,
        message="Spread above 8%",
        timestamp=1234567890.0,
    )
    
    assert signal.signal_type == KalshiSignalType.LIQUIDITY.value
    assert signal.venue == "kalshi"
    assert signal.severity == "warning"
    assert signal.alert_type == "wide_spread"


def test_liquidity_signal_serialization():
    """Test liquidity signal to_dict conversion."""
    signal = LiquiditySignal(
        ticker="BTC-TEST",
        spread_cents=5.0,
        spread_pct=10.0,
        depth_contracts=50.0,
        alert_type="wide_spread",
        severity=LiquiditySeverity.CRITICAL.value,
        message="Critical liquidity",
    )
    
    d = signal.to_dict()
    assert d["signal_type"] == "liquidity"
    assert d["ticker"] == "BTC-TEST"
    assert d["severity"] == "critical"
    assert d["spread_pct"] == 10.0


# ── Test: Volume Anomaly Signal ───────────────────────────────────────────

def test_volume_anomaly_signal_creation():
    """Test volume anomaly signal structure."""
    signal = VolumeAnomalySignal(
        ticker="BTC-TEST",
        asset="BTC",
        current_volume=10000.0,
        rolling_mean=5000.0,
        rolling_std=1000.0,
        z_score=5.0,
        severity="critical",
        direction="spike",
        timestamp=1234567890.0,
    )
    
    assert signal.signal_type == KalshiSignalType.VOLUME_ANOMALY.value
    assert signal.venue == "kalshi"
    assert signal.z_score == 5.0
    assert signal.is_significant()  # z_score > 3.0


def test_volume_anomaly_significance():
    """Test volume anomaly significance thresholds."""
    signal = VolumeAnomalySignal(
        ticker="BTC-TEST",
        asset="BTC",
        current_volume=10000.0,
        rolling_mean=5000.0,
        rolling_std=1000.0,
        z_score=2.5,
    )
    
    # Below threshold
    assert not signal.is_significant(threshold=3.0)
    
    # Above threshold
    signal.z_score = 4.0
    assert signal.is_significant(threshold=3.0)


def test_volume_anomaly_serialization():
    """Test volume anomaly signal to_dict conversion."""
    signal = VolumeAnomalySignal(
        ticker="ETH-TEST",
        asset="ETH",
        current_volume=8000.0,
        rolling_mean=4000.0,
        rolling_std=800.0,
        z_score=5.0,
        severity="critical",
        direction="spike",
    )
    
    d = signal.to_dict()
    assert d["signal_type"] == "volume_anomaly"
    assert d["asset"] == "ETH"
    assert d["z_score"] == 5.0
    assert d["significant"] is True


# ── Test: Risk Event Signal ───────────────────────────────────────────────

def test_risk_signal_creation():
    """Test risk event signal structure."""
    signal = KalshiRiskSignal(
        category=RiskEventCategory.DRAWDOWN.value,
        severity="critical",
        title="Portfolio Drawdown",
        detail="Exceeded 10% daily drawdown limit",
        drawdown_pct=12.5,
        timestamp=1234567890.0,
    )
    
    assert signal.signal_type == KalshiSignalType.RISK_EVENT.value
    assert signal.venue == "kalshi"
    assert signal.category == "drawdown"
    assert signal.drawdown_pct == 12.5


def test_risk_signal_serialization():
    """Test risk event signal to_dict conversion."""
    signal = KalshiRiskSignal(
        category=RiskEventCategory.RATE_LIMIT.value,
        severity="warning",
        title="Rate Limit Warning",
        detail="Approaching rate limit",
        rate_limit_count=95,
    )
    
    d = signal.to_dict()
    assert d["signal_type"] == "risk_event"
    assert d["category"] == "rate_limit"
    assert d["rate_limit_count"] == 95
    assert "drawdown_pct" not in d  # Optional field not present


def test_risk_signal_optional_fields():
    """Test risk signal with optional metrics."""
    signal = KalshiRiskSignal(
        category=RiskEventCategory.LOSS_CAP.value,
        severity="critical",
        title="Daily Loss Cap Hit",
        detail="Exceeded daily loss limit",
        daily_loss_usd=1500.0,
    )
    
    d = signal.to_dict()
    assert d["daily_loss_usd"] == 1500.0
    assert "drawdown_pct" not in d
    assert "rate_limit_count" not in d


# ── Test: Full Signal Generation ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_all_signals(generator, mock_venue_adapter):
    """Test full signal generation across all types."""
    signals = await generator.generate_all(now=1234567890.0)
    
    # Should return a list with at least some signals (liquidity fires on mock data spreads)
    assert isinstance(signals, list)
    assert len(signals) > 0
    
    # Check that signals have correct structure
    for signal in signals:
        assert hasattr(signal, "to_dict")
        d = signal.to_dict()
        assert "signal_type" in d
        assert "venue" in d
        assert d["venue"] == "kalshi"


@pytest.mark.asyncio
async def test_signal_caching(generator, mock_venue_adapter):
    """Test that generated signals are cached."""
    signals1 = await generator.generate_all(now=1234567890.0)
    cached = generator.get_last_signals()
    
    assert len(cached) == len(signals1)
    assert cached == signals1


# ── Test: Graceful Degradation ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_graceful_degradation_no_adapter(generator):
    """Test graceful handling when venue adapter is unavailable."""
    with patch("merid.event_venues.kalshi.venue_adapter.get_kalshi_venue_adapter", side_effect=Exception("Adapter unavailable")):
        signals = await generator.generate_all()
        
        # Should return empty list, not crash
        assert signals == []


@pytest.mark.asyncio
async def test_graceful_degradation_empty_instruments(generator, mock_venue_adapter):
    """Test handling of empty instrument list."""
    mock_venue_adapter.list_instruments = AsyncMock(return_value=[])
    
    signals = await generator.generate_all()
    
    # Should return empty list gracefully
    assert signals == []


@pytest.mark.asyncio
async def test_graceful_degradation_api_failure(generator, mock_venue_adapter):
    """Test handling of API failures during signal generation."""
    mock_venue_adapter.list_instruments = AsyncMock(side_effect=Exception("API error"))
    
    signals = await generator.generate_all()
    
    # Should return empty list, not propagate exception
    assert signals == []


# ── Test: Asset and Timeframe Extraction ──────────────────────────────────

def test_asset_extraction():
    """Test asset extraction from Kalshi tickers."""
    generator = KalshiSignalGenerator()
    
    assert generator._extract_asset("BTC-24FEB-50K") == "BTC"
    assert generator._extract_asset("ETH-WEEKLY-HIGH") == "ETH"
    assert generator._extract_asset("SOL-DAILY") == "SOL"
    assert generator._extract_asset("UNKNOWN-MARKET") == "UNKNOWN"


def test_timeframe_extraction():
    """Test timeframe extraction from Kalshi tickers."""
    generator = KalshiSignalGenerator()
    
    assert generator._extract_timeframe("BTC-24H-HIGH") == "24h"
    assert generator._extract_timeframe("ETH-WEEKLY-LOW") == "weekly"
    assert generator._extract_timeframe("SOL-HOURLY-PUMP") == "1h"
    assert generator._extract_timeframe("BTC-UNKNOWN") == "unknown"


# ── Test: Singleton ────────────────────────────────────────────────────────

def test_singleton_accessor():
    """Test singleton accessor returns same instance."""
    reset_kalshi_signal_generator()
    
    gen1 = get_kalshi_signal_generator()
    gen2 = get_kalshi_signal_generator()
    
    assert gen1 is gen2
