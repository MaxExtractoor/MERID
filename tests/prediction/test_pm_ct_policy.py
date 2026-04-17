"""AgentGrid PM vs KalshiContinuousTrader policy."""

from __future__ import annotations

from unittest import mock

import pytest


def test_agentgrid_pm_live_primary_requires_both_env_vars(monkeypatch):
    from merid.prediction.pm_ct_policy import agentgrid_pm_live_primary

    monkeypatch.delenv("MERID_PM_TRADING_MODE", raising=False)
    monkeypatch.delenv("MERID_PM_LIVE_ENABLED", raising=False)
    assert agentgrid_pm_live_primary() is False

    monkeypatch.setenv("MERID_PM_TRADING_MODE", "live")
    monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "false")
    assert agentgrid_pm_live_primary() is False

    monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "true")
    assert agentgrid_pm_live_primary() is True


def test_ct_live_api_orders_blocked_when_pm_live_without_research(monkeypatch):
    from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

    trader = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
    trader._guardian = None
    trader.config = mock.MagicMock(dry_run=False)

    monkeypatch.setenv("MERID_ALLOW_LIVE_TRADES", "true")
    monkeypatch.setenv("KALSHI_ENV", "live")
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "live")
    monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "true")
    monkeypatch.delenv("MERID_CT_RESEARCH_ALLOW_LOOP", raising=False)

    ok, msg = trader._live_api_orders_allowed()
    assert ok is False
    assert "CT-LEGACY" in msg


def test_ct_loop_suppressed_when_trade_mode_live_without_research(monkeypatch):
    from merid.prediction import pm_ct_policy

    monkeypatch.delenv("MERID_CT_RESEARCH_ALLOW_LOOP", raising=False)
    monkeypatch.setenv("MERID_TRADE_MODE", "live")
    monkeypatch.setenv("MERID_ALLOW_LIVE_TRADES", "true")
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "paper")
    monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "false")
    assert pm_ct_policy.ct_loop_suppressed() is True
    blocked, msg = pm_ct_policy.ct_legacy_must_not_trade()
    assert blocked is True
    assert "MERID_TRADE_MODE=live" in msg


def test_ct_loop_not_suppressed_when_research_flag(monkeypatch):
    from merid.prediction import pm_ct_policy

    monkeypatch.setenv("MERID_TRADE_MODE", "live")
    monkeypatch.setenv("MERID_ALLOW_LIVE_TRADES", "true")
    monkeypatch.setenv("MERID_CT_RESEARCH_ALLOW_LOOP", "true")
    assert pm_ct_policy.ct_loop_suppressed() is False


def test_ct_live_api_orders_blocked_trade_mode_live_without_research(monkeypatch):
    from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

    trader = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
    trader._guardian = None
    trader.config = mock.MagicMock(dry_run=False)

    monkeypatch.setenv("MERID_ALLOW_LIVE_TRADES", "true")
    monkeypatch.setenv("KALSHI_ENV", "live")
    monkeypatch.setenv("MERID_TRADE_MODE", "live")
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "paper")
    monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "false")
    monkeypatch.delenv("MERID_CT_RESEARCH_ALLOW_LOOP", raising=False)

    ok, msg = trader._live_api_orders_allowed()
    assert ok is False
    assert "CT-LEGACY" in msg


def test_ct_live_api_orders_allowed_when_research_flag(monkeypatch):
    from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

    trader = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
    trader._guardian = None
    trader.config = mock.MagicMock(dry_run=False)

    monkeypatch.setenv("MERID_ALLOW_LIVE_TRADES", "true")
    monkeypatch.setenv("KALSHI_ENV", "live")
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "live")
    monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "true")
    monkeypatch.setenv("MERID_CT_RESEARCH_ALLOW_LOOP", "true")

    ok, msg = trader._live_api_orders_allowed()
    assert ok is True
    assert msg == ""


def test_strategy_size_cap_full_when_ct_not_running():
    from merid.prediction.strategy import KalshiStrategy, StrategyConfig

    strat = KalshiStrategy(StrategyConfig(), agent_name="unit")
    with mock.patch("merid.trading.kalshi_continuous_trader.get_continuous_trader", return_value=None):
        assert strat._get_size_cap_for_asset("BTC") == 1.0


def test_agent_yaml_strategy_overrides_roundtrip():
    from merid.prediction.agent_grid_config import load_agent_grid_config

    cfg = load_agent_grid_config()
    btc = cfg.get_agent("BTC_15M")
    assert btc is not None
    assert btc.strategy_overrides.get("min_edge_early") is not None
    from decimal import Decimal

    assert btc.strategy_overrides["min_edge_early"] == Decimal("0.08")


def test_build_strategy_config_applies_overrides():
    from merid.prediction.agent_grid_config import AgentConfig, AgentRiskLimits, MarketFilterConfig
    from merid.prediction.trading_agent import KalshiTradingAgent
    from decimal import Decimal

    raw = AgentConfig(
        name="T",
        market_filter=MarketFilterConfig(),
        risk_limits=AgentRiskLimits(),
        strategy_overrides={"min_edge_early": Decimal("0.03")},
    )
    sc = KalshiTradingAgent._build_strategy_config(raw)
    assert sc.min_edge_early == Decimal("0.03")
