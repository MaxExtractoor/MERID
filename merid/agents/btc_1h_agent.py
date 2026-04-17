"""
BTC 1h Agent — KalshiGrid integration for regime-aware BTC hourly trading.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import uuid

from merid.agents.base import BaseKalshiAgent, AgentOpinion
from merid.kalshi.market_registry import KalshiMarketRegistry
from merid.kalshi.rti import CryptoRTIMonitor
from merid.portfolio.risk import PortfolioRiskAgent

from config.btc_1h_agent_spec import (
    Btc1hInputs,
    Btc1hParams,
    should_trade_btc_1h,
)


class Btc1hAgent(BaseKalshiAgent):
    """BTC 1h Kalshi agent mirroring BTC 15m structure with hourly horizons."""

    agent_id = "btc_1h_regime"
    product = "btc_1h"

    def __init__(
        self,
        market_registry: KalshiMarketRegistry | None = None,
        crypto_rti_monitor: CryptoRTIMonitor | None = None,
        portfolio_risk_agent: PortfolioRiskAgent | None = None,
        params: Btc1hParams | None = None,
    ) -> None:
        super().__init__(agent_id=self.agent_id)
        self.market_registry = market_registry
        self.crypto_rti_monitor = crypto_rti_monitor
        self.portfolio_risk_agent = portfolio_risk_agent
        self.params = params or Btc1hParams()

    async def configure_dependencies(self, container: Any) -> None:
        """DI hook used by KalshiGrid bootstrap."""
        if self.market_registry is None:
            self.market_registry = container.resolve(KalshiMarketRegistry)
        if self.crypto_rti_monitor is None:
            self.crypto_rti_monitor = container.resolve(CryptoRTIMonitor)
        if self.portfolio_risk_agent is None:
            self.portfolio_risk_agent = container.resolve(PortfolioRiskAgent)

    async def _build_inputs(self) -> Optional[Btc1hInputs]:
        assert self.market_registry is not None
        assert self.crypto_rti_monitor is not None
        assert self.portfolio_risk_agent is not None

        market = self.market_registry.get_active_btc_1h()
        if not market:
            self.logger.debug("BTC 1h: no active market, skipping.")
            return None

        rti = self.crypto_rti_monitor.get_current_metrics(symbol="BTC")
        if rti is None:
            self.logger.debug("BTC 1h: no RTI metrics, skipping.")
            return None

        # Assume CryptoRTIMonitor can provide 5m/60m vols; adapt names if needed.
        vol_metrics = self.crypto_rti_monitor.get_vol_metrics(symbol="BTC")
        if vol_metrics is None:
            self.logger.debug("BTC 1h: no vol metrics, skipping.")
            return None

        is_vol_elevated = self.portfolio_risk_agent.is_crypto_vol_elevated("BTC")
        exposure_pct = self.portfolio_risk_agent.get_exposure_pct(
            venue="kalshi",
            category="crypto",
            product=self.product,
        )

        return Btc1hInputs(
            rti_current=rti.rti_current,
            rti_5m_sma=getattr(rti, "rti_5m_sma", rti.rti_60s_sma),
            rti_60m_sma=getattr(rti, "rti_60m_sma", rti.rti_60s_sma),
            vol_5m_realized=getattr(vol_metrics, "vol_5m_realized", vol_metrics.vol_1m_realized),
            vol_60m_realized=getattr(vol_metrics, "vol_60m_realized", vol_metrics.vol_15m_realized),
            vol_baseline_median=vol_metrics.vol_baseline_median,
            seconds_to_expiry=market.seconds_to_expiry,
            best_bid=market.best_bid,
            best_ask=market.best_ask,
            is_crypto_vol_elevated=is_vol_elevated,
            current_exposure_pct=exposure_pct,
        )

    async def get_opinion(
        self,
        trace_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Optional[AgentOpinion]:
        """Main KalshiGrid hook to produce an opinion per cycle.

        Args:
            trace_id: Unique identifier for tracing this opinion through the swarm
            correlation_id: Business correlation ID linking to upstream decision
        """
        # Generate trace_id if not provided (swarm matrix tracking)
        _trace_id = trace_id or f"op-{uuid.uuid4().hex[:12]}"
        _corr_id = correlation_id or _trace_id

        inputs = await self._build_inputs()
        if inputs is None:
            self.logger.debug("trace_id=%s: no inputs, skipping opinion", _trace_id)
            return None

        signal = should_trade_btc_1h(inputs, self.params)
        if signal is None:
            self.logger.debug("trace_id=%s: no signal generated", _trace_id)
            return None

        size_pct = self.portfolio_risk_agent.get_kelly_size_pct(
            venue="kalshi",
            category="crypto",
            product=self.product,
            edge_estimate=signal.edge_estimate,
        )

        side = "buy_yes" if signal.direction == "up" else "buy_no"

        self.logger.info(
            "trace_id=%s corr_id=%s: opinion generated %s %s edge=%.3f",
            _trace_id, _corr_id, self.agent_id, side, signal.edge_estimate
        )

        return AgentOpinion.for_series(
            agent_id=self.agent_id,
            symbol="BTC",
            timeframe="1h",
            market_id=self.market_registry.get_active_btc_1h().ticker,
            side=side,
            confidence=signal.regime_confidence,
            edge_estimate=signal.edge_estimate,
            horizon="medium",
            trace_id=_trace_id,
            correlation_id=_corr_id,
            size_pct=size_pct,
            metadata={
                "product": self.product,
                "rti_current": inputs.rti_current,
                "rti_60m_sma": inputs.rti_60m_sma,
            },
        )


_btc_1h_agent: Optional[Btc1hAgent] = None


def get_btc_1h_agent() -> Btc1hAgent:
    """Get global BTC 1h agent instance."""
    global _btc_1h_agent
    if _btc_1h_agent is None:
        _btc_1h_agent = Btc1hAgent()
    return _btc_1h_agent
