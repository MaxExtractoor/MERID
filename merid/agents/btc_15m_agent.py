"""
BTC 15m Agent — KalshiGrid integration for regime-aware BTC 15m trading.

Implements KalshiGrid agent interface for BTC 15m up/down contracts.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from config.kalshi_btc_15m_agent_spec import (
    Btc15mAgentSpec,
    Btc15mSignalGenerator,
    Btc15mRiskRules,
    Btc15mInputs,
)
from merid.data.rti_stream import RTIStream
from merid.risk.crypto_rti_monitor import CryptoRTIMonitor
from merid.agents.base import AgentOpinion
from utils.logger import get_logger

logger = get_logger("merid.agents.btc_15m")


@dataclass
class Btc15mAgentState:
    """Runtime state for BTC 15m agent."""
    agent_id: str
    enabled: bool = True
    active_positions: List[Dict[str, Any]] = None
    daily_trade_count: int = 0
    daily_pnl: float = 0.0

    def __post_init__(self):
        if self.active_positions is None:
            self.active_positions = []


class Btc15mAgent:
    """BTC 15m Kalshi trading agent implementing KalshiGrid interface."""

    def __init__(self, spec: Btc15mAgentSpec = BTC_15M_AGENT_SPEC):
        self.spec = spec
        self.state = Btc15mAgentState(agent_id=spec.agent_id)
        self.signal_generator = Btc15mSignalGenerator(spec)
        self.risk_rules = Btc15mRiskRules(spec)

        # Dependencies (injected by grid)
        self.rti_stream: Optional[RTIStream] = None
        self.crypto_rti_monitor: Optional[CryptoRTIMonitor] = None
        self.portfolio_risk_agent = None  # For exposure/PnL queries
        self.kalshi_market_registry = None  # For current market data
        self.btc_lane = None  # For regime signals

    def configure_dependencies(
        self,
        rti_stream: RTIStream,
        crypto_rti_monitor: CryptoRTIMonitor,
        portfolio_risk_agent,
        kalshi_market_registry,
        btc_lane
    ):
        """Inject dependencies from KalshiGrid."""
        self.rti_stream = rti_stream
        self.crypto_rti_monitor = crypto_rti_monitor
        self.portfolio_risk_agent = portfolio_risk_agent
        self.kalshi_market_registry = kalshi_market_registry
        self.btc_lane = btc_lane

    def get_status(self) -> Dict[str, Any]:
        """Get agent status for grid summary."""
        return {
            "agent_id": self.spec.agent_id,
            "enabled": self.state.enabled,
            "active_positions": len(self.state.active_positions),
            "daily_trades": self.state.daily_trade_count,
            "daily_pnl": round(self.state.daily_pnl, 4),
            "spec": {
                "max_daily_trades": self.spec.max_daily_trades,
                "max_position_size_pct": self.spec.max_position_size_pct,
                "max_crypto_exposure_pct": self.spec.max_crypto_exposure_pct,
            }
        }

    async def run_cycle(self) -> Optional[AgentOpinion]:
        """Run one agent cycle and return opinion if signal generated.

        This implements the KalshiGrid agent interface.
        """
        if not self.state.enabled:
            return None

        # Build inputs
        inputs = await self._build_inputs()
        if not inputs:
            return None

        # Generate signal
        signal = self.signal_generator.generate_signal(inputs)
        if not signal:
            return None

        # Risk check
        risk_check = self.risk_rules.pre_trade_check(signal, inputs)
        if not risk_check["allowed"]:
            logger.debug(f"BTC 15m signal blocked: {risk_check['reason']}")
            return None

        # Update state
        self.state.daily_trade_count += 1

        # Create opinion for consensus
        opinion = self._create_opinion(signal, risk_check)

        return opinion

    async def _build_inputs(self) -> Optional[Btc15mInputs]:
        """Build Btc15mInputs from current state."""
        if not all([self.rti_stream, self.crypto_rti_monitor, self.portfolio_risk_agent,
                    self.kalshi_market_registry, self.btc_lane]):
            logger.warning("BTC 15m agent missing dependencies")
            return None

        # RTI metrics
        rti_metrics = self.rti_stream.get_current_metrics("BTC")

        # Risk state
        current_position_size = self.portfolio_risk_agent.get_exposure_pct(
            venue="kalshi",
            category="crypto",
            product="btc_15m",
        )
        crypto_vol_alert_active = self.portfolio_risk_agent.is_crypto_vol_elevated("BTC")

        # Market data
        market = self.kalshi_market_registry.get_active_btc_15m()
        market_id = market.ticker
        strike_price = market.strike  # or settlement reference
        time_to_expiry = market.seconds_to_expiry
        orderbook_bid = market.best_bid
        orderbook_ask = market.best_ask

        # Regime signal
        btc_15m_regime_signal = self.btc_lane.get_regime_signal("BTC_15M_KALSHI")

        return Btc15mInputs(
            rti_current=rti_metrics["rti_current"],
            rti_60s_sma=rti_metrics["rti_60s_sma"],
            vol_1m_realized=rti_metrics["rti_60s_vol"],   # temporary approximation
            vol_5m_realized=rti_metrics["rti_60s_vol"],   # same
            vol_15m_realized=rti_metrics["rti_sma_trend"],
            vol_baseline_median=self.crypto_rti_monitor.get_vol_baseline("BTC"),
            market_id=market_id,
            strike_price=strike_price,
            time_to_expiry=time_to_expiry,
            orderbook_bid=orderbook_bid,
            orderbook_ask=orderbook_ask,
            btc_15m_regime_signal=btc_15m_regime_signal,
            crypto_vol_alert_active=crypto_vol_alert_active,
            current_position_size=current_position_size,
            daily_pnl=self.state.daily_pnl,
        )

    def _create_opinion(self, signal: Dict[str, Any], risk_check: Dict[str, Any]) -> AgentOpinion:
        """Create AgentOpinion from signal and risk check using canonical for_series()."""
        import uuid

        _trace_id = str(uuid.uuid4())
        _corr_id = str(uuid.uuid4())
        side = "buy_yes" if signal["action"] == "buy" else "buy_no"
        market_id = signal.get("market_id", "KXBTC15M")

        return AgentOpinion.for_series(
            agent_id=self.spec.agent_id,
            symbol="BTC",
            timeframe="15m",
            market_id=market_id,
            side=side,
            confidence=signal.get("regime_confidence", 0.8),
            edge_estimate=signal["edge_estimate"],
            horizon="short",
            trace_id=_trace_id,
            correlation_id=_corr_id,
            size_pct=risk_check.get("adjusted_size_pct"),
            metadata={
                "stop_loss_pct": signal.get("stop_loss_pct"),
                "take_profit_pct": signal.get("take_profit_pct"),
                "reason": signal.get("reason"),
            },
        )

    def enable(self):
        """Enable the agent."""
        self.state.enabled = True
        logger.info(f"BTC 15m agent {self.spec.agent_id} enabled")

    def disable(self):
        """Disable the agent."""
        self.state.enabled = False
        logger.info(f"BTC 15m agent {self.spec.agent_id} disabled")

    def reset_daily_state(self):
        """Reset daily counters (called at market open or daily reset)."""
        self.state.daily_trade_count = 0
        self.state.daily_pnl = 0.0
        logger.debug(f"BTC 15m agent {self.spec.agent_id} daily state reset")


# Global instance
_btc_15m_agent: Optional[Btc15mAgent] = None


def get_btc_15m_agent() -> Btc15mAgent:
    """Get global BTC 15m agent instance."""
    global _btc_15m_agent
    if _btc_15m_agent is None:
        _btc_15m_agent = Btc15mAgent()
    return _btc_15m_agent
