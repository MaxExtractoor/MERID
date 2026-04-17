"""
Risk Agent for MERID - Core risk management and monitoring agent.

This agent provides comprehensive risk assessment, position monitoring,
and risk-based decision making for the MERID trading system.
"""

from __future__ import annotations

import asyncio
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger
from agents.base_agent import BaseAgent

logger = get_logger("agents.risk")

ROLE_PROMPT = """
You are MERID's institutional-grade risk manager.
- Monitor all trading positions for risk exposure
- Calculate VaR, drawdowns, and concentration risks
- Generate risk alerts and position sizing recommendations
- Ensure compliance with risk limits and regulatory requirements
- Provide risk-adjusted performance metrics
""".strip()


@dataclass
class RiskMetrics:
    """Risk assessment metrics for trading positions."""
    total_exposure: float = 0.0
    max_position_size: float = 0.0
    var_95: float = 0.0  # Value at Risk 95%
    var_99: float = 0.0  # Value at Risk 99%
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    leverage_ratio: float = 0.0
    risk_score: float = 0.0  # 0-100 risk score
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RiskAlert:
    """Risk alert with severity and action recommendations."""
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    message: str
    metric: str
    current_value: float
    threshold: float
    recommendation: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RiskAgent(BaseAgent):
    """
    Core risk management agent for MERID.
    
    Responsibilities:
    1. Monitor portfolio risk metrics
    2. Calculate real-time risk exposure
    3. Generate risk alerts and warnings
    4. Provide risk-based position sizing recommendations
    5. Track compliance with risk limits
    """
    
    def __init__(self, agent_id: str = "risk-agent-01", model_name: str = "gemma3:1b"):
        super().__init__(agent_id, model_name, ROLE_PROMPT, tool_budget=3)
        self.name = "risk-agent"
        self.enabled = True
        self._running = False
        self._lock = threading.Lock()
        
        # Risk thresholds
        self.max_total_exposure = 100000.0  # USD
        self.max_position_pct = 0.1  # 10% of portfolio per position
        self.max_leverage = 3.0
        self.var_threshold_95 = 0.05  # 5% daily VaR limit
        self.var_threshold_99 = 0.1   # 10% daily VaR limit
        self.max_drawdown_threshold = 0.15  # 15% max drawdown
        
        # Current state
        self._current_metrics = RiskMetrics()
        self._risk_alerts: List[RiskAlert] = []
        self._position_data: Dict[str, Dict] = {}
        self._last_update = 0.0
        
        # Background task
        self._monitor_task: Optional[asyncio.Task] = None
        
        logger.info("RiskAgent initialized")
    
    async def start(self) -> None:
        """Start the risk monitoring agent."""
        if self._running:
            logger.warning("RiskAgent already running")
            return
            
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("RiskAgent started")
    
    async def stop(self) -> None:
        """Stop the risk monitoring agent."""
        if not self._running:
            return
            
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("RiskAgent stopped")
    
    async def _monitor_loop(self) -> None:
        """Main risk monitoring loop."""
        while self._running:
            try:
                # Sync live positions from venues
                self.sync_positions_from_venues()
                
                await self._update_risk_metrics()
                await self._check_risk_limits()
                await asyncio.sleep(30)  # Update every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Risk monitoring error: {e}")
                await asyncio.sleep(5)
    
    async def _update_risk_metrics(self) -> None:
        """Update current risk metrics."""
        with self._lock:
            # Calculate total exposure
            total_exposure = sum(
                pos.get('value', 0) * pos.get('quantity', 0)
                for pos in self._position_data.values()
            )
            
            # Calculate position sizes
            position_values = [
                pos.get('value', 0) * pos.get('quantity', 0)
                for pos in self._position_data.values()
            ]
            max_position = max(position_values) if position_values else 0.0
            
            # Simple VaR calculation (placeholder - would use historical data in production)
            portfolio_value = total_exposure
            var_95 = portfolio_value * self.var_threshold_95
            var_99 = portfolio_value * self.var_threshold_99
            
            # Calculate risk score (0-100)
            risk_score = min(100.0, (
                (total_exposure / self.max_total_exposure) * 40 +
                (max_position / (portfolio_value * self.max_position_pct)) * 30 +
                (var_95 / (portfolio_value * self.var_threshold_95)) * 30
            )) if portfolio_value > 0 else 0.0
            
            self._current_metrics = RiskMetrics(
                total_exposure=total_exposure,
                max_position_size=max_position,
                var_95=var_95,
                var_99=var_99,
                risk_score=risk_score,
                timestamp=datetime.now(timezone.utc)
            )
            
            self._last_update = time.time()
    
    async def _check_risk_limits(self) -> None:
        """Check risk limits and generate alerts."""
        alerts = []
        
        # Check total exposure
        if self._current_metrics.total_exposure > self.max_total_exposure:
            alerts.append(RiskAlert(
                severity="CRITICAL",
                message=f"Total exposure exceeds limit: ${self._current_metrics.total_exposure:,.2f} > ${self.max_total_exposure:,.2f}",
                metric="total_exposure",
                current_value=self._current_metrics.total_exposure,
                threshold=self.max_total_exposure,
                recommendation="Reduce position sizes immediately"
            ))
        
        # Check position concentration
        portfolio_value = self._current_metrics.total_exposure
        if portfolio_value > 0:
            max_position_pct = self._current_metrics.max_position_size / portfolio_value
            if max_position_pct > self.max_position_pct:
                alerts.append(RiskAlert(
                    severity="HIGH",
                    message=f"Position concentration too high: {max_position_pct:.1%} > {self.max_position_pct:.1%}",
                    metric="position_concentration",
                    current_value=max_position_pct,
                    threshold=self.max_position_pct,
                    recommendation="Diversify positions across multiple assets"
                ))
        
        # Check VaR limits
        if portfolio_value > 0:
            var_95_pct = self._current_metrics.var_95 / portfolio_value
            if var_95_pct > self.var_threshold_95:
                alerts.append(RiskAlert(
                    severity="MEDIUM",
                    message=f"VaR 95% exceeds threshold: {var_95_pct:.1%} > {self.var_threshold_95:.1%}",
                    metric="var_95",
                    current_value=var_95_pct,
                    threshold=self.var_threshold_95,
                    recommendation="Consider reducing overall exposure"
                ))
        
        # Update alerts list
        with self._lock:
            self._risk_alerts.extend(alerts)
            # Keep only last 100 alerts
            self._risk_alerts = self._risk_alerts[-100:]
    
    def update_position(self, symbol: str, quantity: float, price: float, side: str) -> None:
        """Update position data for risk calculations."""
        with self._lock:
            self._position_data[symbol] = {
                'quantity': quantity,
                'price': price,
                'value': price,
                'side': side,
                'timestamp': datetime.now(timezone.utc)
            }
    
    def sync_positions_from_venues(self) -> None:
        """Sync live position data from all venue adapters.
        
        This method pulls current positions from Kalshi, crypto exchanges,
        and other venue adapters to ensure risk metrics reflect reality.
        """
        try:
            # Sync from Kalshi venue
            self._sync_kalshi_positions()
            
            # Sync from crypto venues
            self._sync_crypto_positions()
            
            # Sync from other venues as needed
            # self._sync_other_positions()
            
            logger.debug(f"Synced positions from venues: {len(self._position_data)} positions")
            
        except Exception as e:
            logger.error(f"Error syncing positions from venues: {e}")
    
    def _sync_kalshi_positions(self) -> None:
        """Sync positions from Kalshi venue adapter."""
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            from merid.venue_registry import get_venue_registry
            
            # Get Kalshi client and registry
            client = get_kalshi_client()
            registry = get_venue_registry()
            
            if not client or not registry:
                return
            
            # Get current positions from Kalshi
            try:
                # This would need to be implemented based on your Kalshi client API
                # For now, we'll use a placeholder approach
                kalshi_positions = self._get_kalshi_positions_placeholder(client)
                
                for position in kalshi_positions:
                    symbol = position.get('ticker', position.get('market_id'))
                    quantity = position.get('quantity', 0)
                    price = position.get('price', 0)
                    side = position.get('side', 'long')
                    
                    if symbol and quantity != 0:
                        self.update_position(symbol, quantity, price, side)
                        
            except Exception as e:
                logger.warning(f"Could not sync Kalshi positions: {e}")
                
        except ImportError:
            logger.debug("Kalshi client not available for position sync")
    
    def _sync_crypto_positions(self) -> None:
        """Sync positions from crypto venue adapters."""
        try:
            # This would sync from crypto exchanges
            # Implementation depends on your crypto venue adapters
            pass
        except Exception as e:
            logger.warning(f"Could not sync crypto positions: {e}")
    
    def _get_kalshi_positions_placeholder(self, client) -> List[Dict[str, Any]]:
        """Placeholder method to get Kalshi positions.
        
        This should be replaced with actual API calls to your Kalshi client
        to retrieve current positions, orders, and market data.
        """
        # TODO: Implement actual position fetching from Kalshi client
        # This might look like:
        # positions = await client.get_positions()
        # orders = await client.get_orders()
        # 
        # For now, return empty list
        return []
    
    def get_risk_metrics(self) -> RiskMetrics:
        """Get current risk metrics."""
        with self._lock:
            return self._current_metrics
    
    def get_risk_alerts(self, severity: Optional[str] = None, limit: int = 50) -> List[RiskAlert]:
        """Get recent risk alerts."""
        with self._lock:
            alerts = self._risk_alerts
            if severity:
                alerts = [a for a in alerts if a.severity == severity]
            return alerts[-limit:]
    
    def get_position_recommendation(self, symbol: str, proposed_size: float, price: float) -> Tuple[bool, str]:
        """Get risk-based recommendation for a proposed position."""
        with self._lock:
            portfolio_value = self._current_metrics.total_exposure
            proposed_value = proposed_size * price
            
            # Check if position would exceed limits
            if portfolio_value + proposed_value > self.max_total_exposure:
                return False, f"Would exceed total exposure limit of ${self.max_total_exposure:,.2f}"
            
            if portfolio_value > 0:
                position_pct = proposed_value / (portfolio_value + proposed_value)
                if position_pct > self.max_position_pct:
                    return False, f"Would exceed position concentration limit of {self.max_position_pct:.1%}"
            
            # Check risk score impact
            projected_risk_score = min(100.0, self._current_metrics.risk_score + (proposed_value / self.max_total_exposure) * 20)
            if projected_risk_score > 80:
                return False, f"Would push risk score too high: {projected_risk_score:.1f}/100"
            
            return True, "Position approved within risk limits"
    
    def is_healthy(self) -> bool:
        """Check if the risk agent is healthy."""
        return self._running and (time.time() - self._last_update) < 300  # Updated within 5 minutes


# Singleton instance
_risk_agent: Optional[RiskAgent] = None
_risk_lock = threading.Lock()


def get_risk_agent() -> RiskAgent:
    """Get the singleton RiskAgent instance."""
    global _risk_agent
    if _risk_agent is None:
        with _risk_lock:
            if _risk_agent is None:
                _risk_agent = RiskAgent()
    return _risk_agent
