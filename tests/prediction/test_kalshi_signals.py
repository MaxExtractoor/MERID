"""Tests for D1: signal dataclass enum coercion and factory functions."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from merid.signals.kalshi_signals import (
    MarketEdgeSignal, LiquiditySignal, VolumeAnomalySignal, KalshiRiskSignal,
    KalshiSignalType, LiquiditySeverity, RiskEventCategory,
    make_market_edge_signal, make_liquidity_signal,
    make_volume_anomaly_signal, make_kalshi_risk_signal,
)

def test_market_edge_signal_enum_coercion():
    s = MarketEdgeSignal(signal_type=KalshiSignalType.MARKET_EDGE, ticker="BTC")
    assert isinstance(s.signal_type, str)
    assert s.signal_type == "market_edge"

def test_liquidity_signal_enum_coercion():
    s = LiquiditySignal(severity=LiquiditySeverity.CRITICAL, ticker="BTC")
    assert isinstance(s.severity, str)
    assert s.severity == "critical"

def test_risk_signal_category_coercion():
    s = KalshiRiskSignal(category=RiskEventCategory.CIRCUIT_BREAKER)
    assert isinstance(s.category, str)
    assert s.category == "circuit_breaker"

def test_risk_signal_signal_type_coercion():
    s = KalshiRiskSignal(signal_type=KalshiSignalType.RISK_EVENT)
    assert isinstance(s.signal_type, str)

def test_factory_make_market_edge():
    s = make_market_edge_signal(ticker="ETH", confidence=0.7)
    assert s.ticker == "ETH"
    assert s.confidence == 0.7

def test_factory_make_risk_signal_with_enum():
    s = make_kalshi_risk_signal(category=RiskEventCategory.DRAWDOWN)
    assert s.category == "drawdown"

def test_fields_accessible():
    s = MarketEdgeSignal(ticker="SOL", edge_pct=3.5, confidence=0.6)
    assert s.edge_pct == 3.5
    assert s.ticker == "SOL"
