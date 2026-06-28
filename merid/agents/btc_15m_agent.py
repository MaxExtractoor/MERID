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
from merid.agents.base import BaseKalshiAgent, AgentOpinion
from merid.agents.loop_tracing import trace_agent_step
from merid.kalshi.market_registry import KalshiMarketRegistry
from merid.portfolio.risk import PortfolioRiskAgent
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


class Btc15mAgent(BaseKalshiAgent):
    """BTC 15m Kalshi trading agent implementing KalshiGrid interface.
    
    DEPRECATED: This agent is NOT used in production 15m crypto trading.
    Production uses LeanAgent15m from merid/prediction/agent_grid_15m.py.
    This agent is kept for backward compatibility and testing only.
    """

    agent_id = "btc_15m_regime"
    product = "btc_15m"

    def __init__(
        self,
        market_registry: KalshiMarketRegistry | None = None,
        crypto_rti_monitor: CryptoRTIMonitor | None = None,
        portfolio_risk_agent: PortfolioRiskAgent | None = None,
        params: Any = None,
    ) -> None:
        super().__init__(agent_id=self.agent_id)
        self.market_registry = market_registry
        self.crypto_rti_monitor = crypto_rti_monitor
        self.portfolio_risk_agent = portfolio_risk_agent
        
        # Initialize spec-based components for backward compatibility
        from config.kalshi_btc_15m_agent_spec import BTC_15M_AGENT_SPEC
        self.spec = BTC_15M_AGENT_SPEC
        self.state = Btc15mAgentState(agent_id=self.spec.agent_id)
        self.signal_generator = Btc15mSignalGenerator(self.spec)
        self.risk_rules = Btc15mRiskRules(self.spec)
        
        # DEPRECATED: Legacy agent - not used in production 15m stack
        # Production uses LeanAgent15m from merid/prediction/agent_grid_15m.py
        # Risk limit logging removed to avoid deprecated config import

    async def configure_dependencies(self, container: Any) -> None:
        """DI hook used by KalshiGrid bootstrap."""
        if self.market_registry is None:
            self.market_registry = container.resolve(KalshiMarketRegistry)
        if self.crypto_rti_monitor is None:
            self.crypto_rti_monitor = container.resolve(CryptoRTIMonitor)
        if self.portfolio_risk_agent is None:
            self.portfolio_risk_agent = container.resolve(PortfolioRiskAgent)

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

    @trace_agent_step()
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
        assert self.market_registry is not None
        assert self.crypto_rti_monitor is not None
        assert self.portfolio_risk_agent is not None

        market = self.market_registry.get_active_btc_15m()
        if not market or not market.ticker:
            self.logger.debug("BTC 15m: no active market, skipping.")
            return None

        rti = self.crypto_rti_monitor.get_rti_metrics(asset="BTC")
        if rti is None:
            self.logger.debug("BTC 15m: no RTI metrics, skipping.")
            return None

        # Risk state
        current_position_size = self.portfolio_risk_agent.get_exposure_pct(
            venue="kalshi",
            category="crypto",
            product="btc_15m",
        )
        crypto_vol_alert_active = self.portfolio_risk_agent.is_crypto_vol_elevated("BTC")

        # Market data
        market_id = market.ticker
        strike_price = market.strike
        time_to_expiry = market.seconds_to_expiry
        orderbook_bid = market.best_bid
        orderbook_ask = market.best_ask

        # Regime signal - not available in lean 15m mode, use None
        btc_15m_regime_signal = None

        # PROFILE-GUARD: Skip SignalFusion microstructure signals for kalshi_crypto_15m_v2 (experimental, not needed for lean 15m)
        import os as _os
        _profile = _os.getenv("MERID_PROFILE", "full").lower().strip()
        _is_15m_crypto = _profile == "kalshi_crypto_15m_v2"
        
        # LEAN 15m KALSHI STACK (2026-05-13): SignalFusion microstructure signals disabled for 15m
        orderflow_bias = 0.0
        onchain_velocity = 0.0

        return Btc15mInputs(
            rti_current=rti.get("rti_current", 0.0),
            rti_60s_sma=rti.get("rti_60s_sma", 0.0),
            vol_1m_realized=rti.get("rti_60s_vol", 0.0),
            vol_5m_realized=rti.get("rti_60s_vol", 0.0),
            vol_15m_realized=rti.get("rti_60s_vol", 0.0),
            vol_baseline_median=0.0,
            market_id=market_id,
            strike_price=strike_price,
            time_to_expiry=time_to_expiry,
            orderbook_bid=orderbook_bid,
            orderbook_ask=orderbook_ask,
            btc_15m_regime_signal=btc_15m_regime_signal,
            crypto_vol_alert_active=crypto_vol_alert_active,
            current_position_size=current_position_size,
            daily_pnl=self.state.daily_pnl,
            orderflow_bias=orderflow_bias,
            onchain_velocity=onchain_velocity,
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
