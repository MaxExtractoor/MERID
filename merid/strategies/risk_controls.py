"""
Risk Controls - Max Drawdown Stops and Risk Management

Impose per-asset and global max drawdown limits with automatic trading stops.
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

@dataclass
class RiskLimits:
    """Risk limit configuration."""
    per_asset_dd_limit: float = -0.10  # -10% per asset
    global_dd_limit: float = -0.20     # -20% global
    max_consecutive_losses: int = 5     # Stop after 5 consecutive losses
    max_daily_loss: float = -0.05       # -5% daily loss limit
    min_equity_usd: float = 80000.0    # Stop if equity drops below $80k
    enable_auto_stop: bool = True       # Enable automatic trading stops

@dataclass
class RiskState:
    """Current risk state tracking."""
    current_equity: float
    peak_equity: float
    current_drawdown: float
    per_asset_equity: Dict[str, float]
    per_asset_peak: Dict[str, float]
    per_asset_dd: Dict[str, float]
    consecutive_losses: int
    daily_pnl: float
    trading_enabled: bool
    last_stop_time: Optional[float]
    stop_reasons: List[str]

class RiskController:
    """Risk management controller with drawdown stops."""
    
    def __init__(self, initial_equity: float, assets: List[str], limits: Optional[RiskLimits] = None):
        """
        Initialize risk controller.
        
        Args:
            initial_equity: Starting equity in USD
            assets: List of asset names (e.g., ["BTC", "ETH"])
            limits: Risk limit configuration
        """
        self.initial_equity = initial_equity
        self.assets = assets
        self.limits = limits or RiskLimits()
        
        # Initialize state
        self.state = RiskState(
            current_equity=initial_equity,
            peak_equity=initial_equity,
            current_drawdown=0.0,
            per_asset_equity={asset: 0.0 for asset in assets},
            per_asset_peak={asset: 0.0 for asset in assets},
            per_asset_dd={asset: 0.0 for asset in assets},
            consecutive_losses=0,
            daily_pnl=0.0,
            trading_enabled=True,
            last_stop_time=None,
            stop_reasons=[]
        )
        
        # Daily reset tracking
        self.last_daily_reset = datetime.now(timezone.utc).date()
        
        logger.info(f"RiskController initialized: equity=${initial_equity:,.0f}, "
                   f"assets={assets}, limits={self.limits}")

    def update_equity(self, total_equity: float, per_asset_pnl: Dict[str, float]):
        """
        Update equity and check risk limits.
        
        Args:
            total_equity: Total portfolio equity
            per_asset_pnl: PnL per asset since last update
        """
        # Check daily reset
        current_date = datetime.now(timezone.utc).date()
        if current_date != self.last_daily_reset:
            self._reset_daily_stats()
        
        # Update state
        self.state.current_equity = total_equity
        
        # Update per-asset equity
        for asset in self.assets:
            self.state.per_asset_equity[asset] += per_asset_pnl.get(asset, 0.0)
            
            # Update per-asset peak
            if self.state.per_asset_equity[asset] > self.state.per_asset_peak[asset]:
                self.state.per_asset_peak[asset] = self.state.per_asset_equity[asset]
            
            # Calculate per-asset drawdown
            if self.state.per_asset_peak[asset] > 0:
                self.state.per_asset_dd[asset] = (
                    self.state.per_asset_equity[asset] - self.state.per_asset_peak[asset]
                ) / self.state.per_asset_peak[asset]
        
        # Update global peak and drawdown
        if total_equity > self.state.peak_equity:
            self.state.peak_equity = total_equity
        
        self.state.current_drawdown = (
            (total_equity - self.state.peak_equity) / self.state.peak_equity
            if self.state.peak_equity > 0 else 0.0
        )
        
        # Update daily PnL
        self.state.daily_pnl = total_equity - self.initial_equity
        
        # Check consecutive losses
        if total_equity < self.state.current_equity - per_asset_pnl.get('total', 0):
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        
        # Check risk limits
        self._check_risk_limits()

    def _reset_daily_stats(self):
        """Reset daily statistics."""
        self.state.daily_pnl = 0.0
        self.state.consecutive_losses = 0
        self.last_daily_reset = datetime.now(timezone.utc).date()
        logger.info("Daily risk statistics reset")

    def _check_risk_limits(self):
        """Check all risk limits and stop trading if needed."""
        stop_reasons = []
        
        # Check global drawdown limit
        if self.state.current_drawdown < self.limits.global_dd_limit:
            stop_reasons.append(f"Global drawdown: {self.state.current_drawdown:.2%}")
        
        # Check per-asset drawdown limits
        for asset in self.assets:
            if self.state.per_asset_dd[asset] < self.limits.per_asset_dd_limit:
                stop_reasons.append(f"{asset} drawdown: {self.state.per_asset_dd[asset]:.2%}")
        
        # Check consecutive losses
        if self.state.consecutive_losses >= self.limits.max_consecutive_losses:
            stop_reasons.append(f"Consecutive losses: {self.state.consecutive_losses}")
        
        # Check daily loss limit
        if self.state.daily_pnl < self.initial_equity * self.limits.max_daily_loss:
            stop_reasons.append(f"Daily loss: {self.state.daily_pnl/ self.initial_equity:.2%}")
        
        # Check minimum equity
        if self.state.current_equity < self.limits.min_equity_usd:
            stop_reasons.append(f"Minimum equity: ${self.state.current_equity:,.0f}")
        
        # Stop trading if any limits breached
        if stop_reasons and self.limits.enable_auto_stop:
            self._stop_trading(stop_reasons)

    def _stop_trading(self, reasons: List[str]):
        """Stop trading due to risk limit breach."""
        if not self.state.trading_enabled:
            return  # Already stopped
        
        self.state.trading_enabled = False
        self.state.last_stop_time = datetime.now(timezone.utc).timestamp()
        self.state.stop_reasons = reasons
        
        logger.warning(f"TRADING STOPPED - Risk limits breached: {', '.join(reasons)}")
        
        # Emit risk event
        from merid.kalshi.maker_bot_advanced import kalshi_event_bus, KalshiEvent
        import time
        
        kalshi_event_bus.publish(KalshiEvent(
            type="api_error",
            payload={
                "risk_stop": True,
                "reasons": reasons,
                "equity": self.state.current_equity,
                "drawdown": self.state.current_drawdown,
                "timestamp": time.time()
            },
            ts=time.time(),
            source="risk_controller"
        ))

    def enable_trading(self, reason: str = "Manual enable"):
        """Manually enable trading."""
        if not self.state.trading_enabled:
            self.state.trading_enabled = True
            self.state.stop_reasons = []
            logger.info(f"Trading enabled: {reason}")
            
            # Emit enable event
            from merid.kalshi.maker_bot_advanced import kalshi_event_bus, KalshiEvent
            import time
            
            kalshi_event_bus.publish(KalshiEvent(
                type="position_update",
                payload={
                    "risk_enable": True,
                    "reason": reason,
                    "equity": self.state.current_equity,
                    "timestamp": time.time()
                },
                ts=time.time(),
                source="risk_controller"
            ))

    def can_trade(self, asset: str) -> bool:
        """Check if trading is allowed for a specific asset."""
        if not self.state.trading_enabled:
            return False
        
        # Check per-asset drawdown
        if self.state.per_asset_dd.get(asset, 0) < self.limits.per_asset_dd_limit:
            return False
        
        return True

    def get_risk_status(self) -> Dict:
        """Get current risk status."""
        return {
            "trading_enabled": self.state.trading_enabled,
            "current_equity": self.state.current_equity,
            "peak_equity": self.state.peak_equity,
            "current_drawdown": self.state.current_drawdown,
            "daily_pnl": self.state.daily_pnl,
            "consecutive_losses": self.state.consecutive_losses,
            "per_asset": {
                asset: {
                    "equity": self.state.per_asset_equity[asset],
                    "peak": self.state.per_asset_peak[asset],
                    "drawdown": self.state.per_asset_dd[asset],
                    "can_trade": self.can_trade(asset)
                }
                for asset in self.assets
            },
            "limits": {
                "global_dd": self.limits.global_dd_limit,
                "per_asset_dd": self.limits.per_asset_dd_limit,
                "max_consecutive_losses": self.limits.max_consecutive_losses,
                "daily_loss": self.limits.max_daily_loss,
                "min_equity": self.limits.min_equity_usd
            },
            "stop_reasons": self.state.stop_reasons,
            "last_stop_time": self.state.last_stop_time
        }

    def apply_drawdown_stop_to_equity_curve(self, equity_curve: pd.Series, dd_limit: float) -> pd.Series:
        """
        Apply drawdown stop to historical equity curve.
        
        Args:
            equity_curve: Historical equity curve
            dd_limit: Maximum drawdown limit (negative)
            
        Returns:
            Truncated equity curve
        """
        if equity_curve.empty:
            return equity_curve
        
        peak = equity_curve.iloc[0]
        stopped_index = None
        
        for i, eq in enumerate(equity_curve):
            if eq > peak:
                peak = eq
            
            dd = (eq - peak) / peak if peak != 0 else 0
            
            if dd < dd_limit:
                stopped_index = i
                break
        
        if stopped_index is not None:
            logger.info(f"Drawdown stop applied at index {stopped_index}: {dd:.2%}")
            return equity_curve.iloc[:stopped_index + 1]
        
        return equity_curve

    def calculate_risk_metrics(self, equity_curve: pd.Series) -> Dict:
        """
        Calculate risk metrics from equity curve.
        
        Args:
            equity_curve: Historical equity curve
            
        Returns:
            Dictionary with risk metrics
        """
        if equity_curve.empty:
            return {}
        
        # Calculate returns
        returns = equity_curve.pct_change().dropna()
        
        # Basic metrics
        total_return = (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1 if equity_curve.iloc[0] != 0 else 0.0
        
        # Drawdown metrics
        running_max = equity_curve.cummax()
        drawdowns = equity_curve - running_max
        max_dd = drawdowns.min() / running_max.max() if running_max.max() != 0 else 0.0
        
        # Volatility metrics
        volatility = returns.std()
        downside_volatility = returns[returns < 0].std()
        
        # VaR (5%)
        var_5 = returns.quantile(0.05)
        
        # Calmar ratio (annualized return / max drawdown)
        calmar_ratio = (total_return / abs(max_dd)) if max_dd != 0 else 0
        
        return {
            "total_return": total_return,
            "max_drawdown": max_dd,
            "volatility": volatility,
            "downside_volatility": downside_volatility,
            "var_5": var_5,
            "calmar_ratio": calmar_ratio,
            "sharpe_ratio": returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        }

# Risk controller singleton
risk_controller = RiskController(
    initial_equity=100000.0,
    assets=["BTC", "ETH"],
    limits=RiskLimits(
        per_asset_dd_limit=-0.10,
        global_dd_limit=-0.20,
        max_consecutive_losses=5,
        max_daily_loss=-0.05,
        min_equity_usd=80000.0,
        enable_auto_stop=True
    )
)

# Example usage:
"""
# Update equity and check risk
risk_controller.update_equity(
    total_equity=95000.0,
    per_asset_pnl={"BTC": -2000.0, "ETH": 1000.0}
)

# Check if can trade
can_trade_btc = risk_controller.can_trade("BTC")
print(f"Can trade BTC: {can_trade_btc}")

# Get risk status
status = risk_controller.get_risk_status()
print(f"Risk status: {status}")

# Manually enable trading
risk_controller.enable_trading("Manual override")
"""
