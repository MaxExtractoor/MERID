"""CRYPTO_15M_MM PM spot hard gate — QUOTE without spot → NO_ACTION."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from merid.prediction.strategy import ExpiryPhase, SignalAction, StrategySignal


@pytest.fixture
def mm_agent():
    from merid.prediction.agent_grid_config import (
        AgentConfig,
        AgentRiskLimits,
        EntryWindowConfig,
        MarketFilterConfig,
    )
    from merid.prediction.trading_agent import KalshiTradingAgent

    cfg = AgentConfig(
        name="CRYPTO_15M_MM",
        category="crypto",
        assets=[],
        timeframes=["15m"],
        archetype="market_maker",
        pm_spot_hard_gate=True,
        market_filter=MarketFilterConfig(category="crypto", frequency="fifteen_min"),
        risk_limits=AgentRiskLimits(),
        entry_window=EntryWindowConfig(),
        enabled=True,
    )
    with patch("merid.prediction.trading_agent.get_prediction_risk"), patch(
        "merid.prediction.trading_agent.get_session_guard"
    ), patch("merid.prediction.trading_agent.get_venue_gate"):
        return KalshiTradingAgent(cfg)


def _quote_signal() -> StrategySignal:
    edge = MagicMock()
    edge.net_edge = Decimal("0.05")
    return StrategySignal(
        market_id="KXBTC15M-TEST",
        action=SignalAction.QUOTE,
        side="yes",
        contracts=5,
        bid_price_cents=48,
        ask_price_cents=52,
        edge=edge,
        phase=ExpiryPhase.MID,
        reason="mm",
        timestamp=datetime.now(timezone.utc),
    )


def test_pm_spot_gate_blocks_quote_when_spot_missing(mm_agent, monkeypatch):
    monkeypatch.setenv("MERID_CRYPTO_MM_PM_SPOT_HARD_GATE", "1")
    market = MagicMock()
    market.market_id = "KXBTC15M-TEST"
    snap = MagicMock()
    snap.spot_price_usd = None
    snap.resolved_asset = "BTC"
    sig_in = _quote_signal()
    out = mm_agent._apply_pm_spot_hard_gate(market, sig_in, snap)
    assert out.action == SignalAction.NO_ACTION
    assert out.contracts == 0
    assert "pm_spot_gate" in (out.reason or "")
    assert out.bid_price_cents is None and out.ask_price_cents is None


def test_pm_spot_gate_allows_quote_when_spot_present(mm_agent, monkeypatch):
    monkeypatch.setenv("MERID_CRYPTO_MM_PM_SPOT_HARD_GATE", "1")
    market = MagicMock()
    market.market_id = "KXBTC15M-TEST"
    snap = MagicMock()
    snap.spot_price_usd = Decimal("95000")
    snap.resolved_asset = "BTC"
    sig_in = _quote_signal()
    out = mm_agent._apply_pm_spot_hard_gate(market, sig_in, snap)
    assert out is sig_in


def test_pm_spot_gate_disabled_by_env(mm_agent, monkeypatch):
    monkeypatch.setenv("MERID_CRYPTO_MM_PM_SPOT_HARD_GATE", "0")
    market = MagicMock()
    market.market_id = "KXBTC15M-TEST"
    snap = MagicMock()
    snap.spot_price_usd = None
    snap.resolved_asset = "BTC"
    sig_in = _quote_signal()
    out = mm_agent._apply_pm_spot_hard_gate(market, sig_in, snap)
    assert out is sig_in


def test_pm_spot_gate_skipped_when_config_flag_off(monkeypatch):
    """``pm_spot_hard_gate: false`` on a market_maker does not block (opt-in safety)."""
    from merid.prediction.agent_grid_config import (
        AgentConfig,
        AgentRiskLimits,
        EntryWindowConfig,
        MarketFilterConfig,
    )
    from merid.prediction.trading_agent import KalshiTradingAgent

    monkeypatch.setenv("MERID_CRYPTO_MM_PM_SPOT_HARD_GATE", "1")
    cfg = AgentConfig(
        name="TEST_MM",
        category="crypto",
        assets=["BTC"],
        timeframes=["15m"],
        archetype="market_maker",
        pm_spot_hard_gate=False,
        market_filter=MarketFilterConfig(category="crypto", frequency="fifteen_min"),
        risk_limits=AgentRiskLimits(),
        entry_window=EntryWindowConfig(),
        enabled=True,
    )
    with patch("merid.prediction.trading_agent.get_prediction_risk"), patch(
        "merid.prediction.trading_agent.get_session_guard"
    ), patch("merid.prediction.trading_agent.get_venue_gate"):
        agent = KalshiTradingAgent(cfg)
    assert agent._pm_spot_hard_gate_enabled_for_agent() is False
    market = MagicMock()
    market.market_id = "KXBTC15M-TEST"
    snap = MagicMock()
    snap.spot_price_usd = None
    snap.resolved_asset = "BTC"
    sig_in = _quote_signal()
    out = agent._apply_pm_spot_hard_gate(market, sig_in, snap)
    assert out is sig_in
