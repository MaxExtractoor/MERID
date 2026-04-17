"""
DOGE 15m Agent — KalshiGrid integration for regime-aware DOGE 15m trading.
"""
from __future__ import annotations

import uuid

from typing import Any, Optional

from merid.agents.base import BaseKalshiAgent, AgentOpinion
from merid.kalshi.market_registry import KalshiMarketRegistry
from merid.kalshi.rti import CryptoRTIMonitor
from merid.portfolio.risk import PortfolioRiskAgent

from config.doge_15m_agent_spec import (
    Doge15mInputs,
    Doge15mParams,
    should_trade_doge_15m,
)


class Doge15mAgent(BaseKalshiAgent):
    """DOGE 15m Kalshi agent mirroring XRP/BTC 15m structure."""

    agent_id = "doge_15m_regime"
    product = "doge_15m"

    def __init__(
        self,
        market_registry: KalshiMarketRegistry | None = None,
        crypto_rti_monitor: CryptoRTIMonitor | None = None,
        portfolio_risk_agent: PortfolioRiskAgent | None = None,
        params: Doge15mParams | None = None,
    ) -> None:
        super().__init__(agent_id=self.agent_id)
        self.market_registry = market_registry
        self.crypto_rti_monitor = crypto_rti_monitor
        self.portfolio_risk_agent = portfolio_risk_agent
        self.params = params or Doge15mParams()

    async def configure_dependencies(self, container: Any) -> None:
        """DI hook used by KalshiGrid bootstrap."""
        if self.market_registry is None:
            self.market_registry = container.resolve(KalshiMarketRegistry)
        if self.crypto_rti_monitor is None:
            self.crypto_rti_monitor = container.resolve(CryptoRTIMonitor)
        if self.portfolio_risk_agent is None:
            self.portfolio_risk_agent = container.resolve(PortfolioRiskAgent)

    async def _build_inputs(self) -> Optional[Doge15mInputs]:
        if self.market_registry is None or self.crypto_rti_monitor is None or self.portfolio_risk_agent is None:
            return None

        market = self.market_registry.get_active_doge_15m()
        if not market:
            self.logger.debug("DOGE 15m: no active market, skipping.")
            return None

        rti = self.crypto_rti_monitor.get_current_metrics(symbol="DOGE")
        if rti is None:
            self.logger.debug("DOGE 15m: no RTI metrics, skipping.")
            return None

        vol_metrics = self.crypto_rti_monitor.get_vol_metrics(symbol="DOGE")
        if vol_metrics is None:
            self.logger.debug("DOGE 15m: no vol metrics, skipping.")
            return None

        is_vol_elevated = self.portfolio_risk_agent.is_crypto_vol_elevated("DOGE")
        exposure_pct = self.portfolio_risk_agent.get_exposure_pct(
            venue="kalshi",
            category="crypto",
            product=self.product,
        )

        return Doge15mInputs(
            rti_current=rti.rti_current,
            rti_60s_sma=rti.rti_60s_sma,
            vol_1m_realized=vol_metrics.vol_1m_realized,
            vol_5m_realized=vol_metrics.vol_5m_realized,
            vol_15m_realized=vol_metrics.vol_15m_realized,
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
        _trace_id = trace_id or f"op-{uuid.uuid4().hex[:12]}"
        _corr_id = correlation_id or _trace_id

        inputs = await self._build_inputs()
        if inputs is None:
            self.logger.debug("trace_id=%s: no inputs, skipping opinion", _trace_id)
            return None

        signal = should_trade_doge_15m(inputs, self.params)
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
            symbol="DOGE",
            timeframe="15m",
            market_id=self.market_registry.get_active_doge_15m().ticker,
            side=side,
            confidence=signal.regime_confidence,
            edge_estimate=signal.edge_estimate,
            horizon="short",
            trace_id=_trace_id,
            correlation_id=_corr_id,
            size_pct=size_pct,
            metadata={
                "product": self.product,
                "rti_current": inputs.rti_current,
                "rti_60s_sma": inputs.rti_60s_sma,
            },
        )


_doge_15m_agent: Optional[Doge15mAgent] = None


def get_doge_15m_agent() -> Doge15mAgent:
    """Get global DOGE 15m agent instance."""
    global _doge_15m_agent
    if _doge_15m_agent is None:
        _doge_15m_agent = Doge15mAgent()
    return _doge_15m_agent
