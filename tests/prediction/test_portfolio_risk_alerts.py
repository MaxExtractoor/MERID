from __future__ import annotations

from decimal import Decimal

from merid.prediction.agent_grid_config import PortfolioRiskConfig
from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent, PortfolioSnapshot


def _agent() -> PortfolioRiskAgent:
    return PortfolioRiskAgent(PortfolioRiskConfig(max_notional_per_asset_usd=Decimal("100")))


def _snapshot() -> PortfolioSnapshot:
    snap = PortfolioSnapshot(
        timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        total_notional_usd=Decimal("0"),
        open_market_count=0,
    )
    for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        snap.notional_per_asset[asset] = Decimal("0")
    return snap


def test_zero_positions_no_risk_limit_alert(monkeypatch):
    agent = _agent()
    fired = []

    class _Mgr:
        def fire_risk_breach(self, **kwargs):
            fired.append(kwargs)

    agent._alert_manager = _Mgr()
    snap = _snapshot()
    snap.notional_per_asset["BTC"] = Decimal("500")
    snap.total_notional_usd = Decimal("500")
    snap.open_market_count = 0

    agent._emit_exposure_risk_alerts(snap, ["BTC notional over cap"])
    assert fired == []


def test_under_cap_no_alert(monkeypatch):
    agent = _agent()
    fired = []

    class _Mgr:
        def fire_risk_breach(self, **kwargs):
            fired.append(kwargs)

    agent._alert_manager = _Mgr()
    snap = _snapshot()
    snap.notional_per_asset["BTC"] = Decimal("99")
    snap.total_notional_usd = Decimal("99")
    snap.open_market_count = 1

    agent._emit_exposure_risk_alerts(snap, ["BTC notional under cap"])
    assert fired == []


def test_over_cap_alert_deduped_with_cooldown(monkeypatch):
    agent = _agent()
    agent._risk_alert_cooldown_seconds = 3600
    agent._min_alert_exposure_usd = Decimal("1")
    fired = []

    class _Mgr:
        def fire_risk_breach(self, **kwargs):
            fired.append(kwargs)

    agent._alert_manager = _Mgr()
    snap = _snapshot()
    snap.notional_per_asset["BTC"] = Decimal("250")
    snap.total_notional_usd = Decimal("250")
    snap.open_market_count = 2

    breach = ["BTC notional 250 > limit 100"]
    agent._emit_exposure_risk_alerts(snap, breach)
    agent._emit_exposure_risk_alerts(snap, breach)

    assert len(fired) == 1
    assert fired[0]["market_id"] == "BTC:portfolio"
    assert "positions_count=2" in fired[0]["message"]
