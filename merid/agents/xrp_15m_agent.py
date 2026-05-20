"""
XRP 15m Agent — KalshiGrid integration for regime-aware XRP 15m trading.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import uuid

from merid.agents.base import BaseKalshiAgent, AgentOpinion
from merid.agents.loop_tracing import trace_agent_step
from merid.kalshi.market_registry import KalshiMarketRegistry
from merid.kalshi.rti import CryptoRTIMonitor
from merid.portfolio.risk import PortfolioRiskAgent

from config.xrp_15m_agent_spec import (
    Xrp15mInputs,
    Xrp15mParams,
    should_trade_xrp_15m,
)


class Xrp15mAgent(BaseKalshiAgent):
    """XRP 15m Kalshi agent mirroring BTC 15m structure."""

    agent_id = "xrp_15m_regime"
    product = "xrp_15m"

    def __init__(
        self,
        market_registry: KalshiMarketRegistry | None = None,
        crypto_rti_monitor: CryptoRTIMonitor | None = None,
        portfolio_risk_agent: PortfolioRiskAgent | None = None,
        params: Xrp15mParams | None = None,
    ) -> None:
        super().__init__(agent_id=self.agent_id)
        self.market_registry = market_registry
        self.crypto_rti_monitor = crypto_rti_monitor
        self.portfolio_risk_agent = portfolio_risk_agent
        self.params = params or Xrp15mParams()
        
        # Log risk limits at startup for audit trail
        from config.kalshi_15m_crypto_config import log_risk_limits_for_agent
        from merid.prediction.venue_gate import get_venue_gate
        mode = get_venue_gate().mode.value.upper()
        log_risk_limits_for_agent("XRP", mode)

    async def configure_dependencies(self, container: Any) -> None:
        """DI hook used by KalshiGrid bootstrap."""
        if self.market_registry is None:
            self.market_registry = container.resolve(KalshiMarketRegistry)
        if self.crypto_rti_monitor is None:
            self.crypto_rti_monitor = container.resolve(CryptoRTIMonitor)
        if self.portfolio_risk_agent is None:
            self.portfolio_risk_agent = container.resolve(PortfolioRiskAgent)

    async def _build_inputs(self) -> Optional[Xrp15mInputs]:
        assert self.market_registry is not None
        assert self.crypto_rti_monitor is not None
        assert self.portfolio_risk_agent is not None

        market = self.market_registry.get_active_xrp_15m()
        if not market:
            self.logger.debug("XRP 15m: no active market, skipping.")
            return None

        rti = self.crypto_rti_monitor.get_current_metrics(symbol="XRP")
        if rti is None:
            self.logger.debug("XRP 15m: no RTI metrics, skipping.")
            return None

        vol_metrics = self.crypto_rti_monitor.get_vol_metrics(symbol="XRP")
        if vol_metrics is None:
            self.logger.debug("XRP 15m: no vol metrics, skipping.")
            return None

        is_vol_elevated = self.portfolio_risk_agent.is_crypto_vol_elevated("XRP")
        exposure_pct = self.portfolio_risk_agent.get_exposure_pct(
            venue="kalshi",
            category="crypto",
            product=self.product,
        )

        return Xrp15mInputs(
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

    @trace_agent_step()
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

        # WINNER ALIGNMENT FIX (2026-05-10): Check if XRP is an arbiter winner before generating opinion
        # This ensures 15m agents only trade when their asset is in the winner set
        try:
            from merid.prediction.grid_context import get_grid_context
            grid_ctx = get_grid_context()
            
            # Get the current market ticker
            market = self.market_registry.get_active_xrp_15m()
            if market:
                is_winner = grid_ctx.is_winner(market.ticker)
                
                if not is_winner:
                    self.logger.info(
                        "[ARBITERBLOCKED] XRP15M %s not in arbiter winners - skipping opinion generation",
                        market.ticker
                    )
                    return None
                
                self.logger.debug(
                    "[ARBITEROK] XRP15M %s is in arbiter winners - proceeding with opinion generation",
                    market.ticker
                )
        except Exception as e:
            self.logger.warning("[ARBITER] Winner check failed for XRP15M: %s - fail-open allowing", e)
            # Fail-open: if check fails, allow opinion generation to avoid blocking valid signals

        signal = should_trade_xrp_15m(inputs, self.params)
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
            symbol="XRP",
            timeframe="15m",
            market_id=self.market_registry.get_active_xrp_15m().ticker,
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


_xrp_15m_agent: Optional[Xrp15mAgent] = None


def get_xrp_15m_agent() -> Xrp15mAgent:
    """Get global XRP 15m agent instance."""
    global _xrp_15m_agent
    if _xrp_15m_agent is None:
        _xrp_15m_agent = Xrp15mAgent()
    return _xrp_15m_agent
