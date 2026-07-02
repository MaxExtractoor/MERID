"""
Pre-Trade Risk Checker

Validates trade decisions against risk limits before execution.
Can veto or clip size without changing agent logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
from datetime import datetime

from merid.pipelines.feature_bundle import TradeDecision
from utils.logger import get_logger

logger = get_logger("merid.pipelines.pre_trade_risk")


@dataclass
class RiskCheckResult:
    """Result of a pre-trade risk check."""
    passed: bool
    adjusted_size_pct: Optional[float] = None  # If clipped
    reason: str = ""
    check_name: str = ""


class PreTradeRiskChecker:
    """
    Pre-trade risk validation layer.
    
    Runs before Kalshi executor to validate decisions against risk limits.
    Can veto trades or clip position size based on:
    - Max position size
    - Asset exposure limits
    - Order frequency limits
    - Daily loss caps
    """
    
    def __init__(
        self,
        max_size_pct: float = 0.02,  # 2% of bankroll max per trade
        max_asset_exposure_pct: float = 0.10,  # 10% of bankroll per asset
        max_daily_trades: int = 20,
        max_daily_loss_pct: float = 0.05,  # 5% daily loss cap
    ):
        self.max_size_pct = max_size_pct
        self.max_asset_exposure_pct = max_asset_exposure_pct
        self.max_daily_trades = max_daily_trades
        self.max_daily_loss_pct = max_daily_loss_pct
        
        # Runtime state
        self.daily_trade_count: Dict[str, int] = {}
        self.daily_pnl: Dict[str, float] = {}
        self.current_exposure: Dict[str, float] = {}
    
    def check_decision(
        self,
        decision: TradeDecision,
        account_state: Dict[str, Any],
    ) -> RiskCheckResult:
        """
        Run all risk checks on a trade decision.
        
        Args:
            decision: Trade decision to validate
            account_state: Current account state (exposure, daily PnL, etc.)
            
        Returns:
            RiskCheckResult with pass/fail and any adjustments
        """
        checks = [
            self._check_max_size,
            self._check_asset_exposure,
            self._check_frequency_limit,
            self._check_daily_loss_cap,
        ]
        
        for check in checks:
            result = check(decision, account_state)
            if not result.passed:
                logger.warning(
                    f"Pre-trade risk check failed: {result.check_name} - {result.reason}"
                )
                return result
        
        logger.info(f"Pre-trade risk checks passed for {decision.asset} {decision.side}")
        # Return the last check's name when all pass
        last_check_name = checks[-1](decision, account_state).check_name
        return RiskCheckResult(passed=True, adjusted_size_pct=decision.size_pct, check_name=last_check_name)
    
    def _check_max_size(
        self,
        decision: TradeDecision,
        account_state: Dict[str, Any],
    ) -> RiskCheckResult:
        """Check if position size exceeds maximum."""
        if decision.size_pct > self.max_size_pct:
            # Clip to max
            adjusted = min(decision.size_pct, self.max_size_pct)
            return RiskCheckResult(
                passed=False,
                adjusted_size_pct=adjusted,
                reason=f"Size {decision.size_pct:.3f} exceeds max {self.max_size_pct:.3f}, clipped to {adjusted:.3f}",
                check_name="max_size",
            )
        return RiskCheckResult(passed=True, check_name="max_size")
    
    def _check_asset_exposure(
        self,
        decision: TradeDecision,
        account_state: Dict[str, Any],
    ) -> RiskCheckResult:
        """Check if asset exposure would exceed limit."""
        current_exposure = account_state.get("asset_exposure", {}).get(decision.asset, 0.0)
        new_exposure = current_exposure + decision.size_pct
        
        if new_exposure > self.max_asset_exposure_pct:
            # Clip to remaining capacity
            remaining = max(0, self.max_asset_exposure_pct - current_exposure)
            return RiskCheckResult(
                passed=False,
                adjusted_size_pct=remaining,
                reason=f"Asset exposure {new_exposure:.3f} exceeds max {self.max_asset_exposure_pct:.3f}, clipped to {remaining:.3f}",
                check_name="asset_exposure",
            )
        return RiskCheckResult(passed=True, check_name="asset_exposure")
    
    def _check_frequency_limit(
        self,
        decision: TradeDecision,
        account_state: Dict[str, Any],
    ) -> RiskCheckResult:
        """Check if daily trade limit exceeded."""
        asset = decision.asset
        daily_count = account_state.get("daily_trade_count", {}).get(asset, 0)
        
        if daily_count >= self.max_daily_trades:
            return RiskCheckResult(
                passed=False,
                reason=f"Daily trade limit reached: {daily_count}/{self.max_daily_trades}",
                check_name="frequency_limit",
            )
        return RiskCheckResult(passed=True, check_name="frequency_limit")
    
    def _check_daily_loss_cap(
        self,
        decision: TradeDecision,
        account_state: Dict[str, Any],
    ) -> RiskCheckResult:
        """Check if daily loss would exceed cap."""
        daily_pnl = account_state.get("daily_pnl", 0.0)
        
        # If already at loss cap, veto all trades
        if daily_pnl <= -self.max_daily_loss_pct:
            return RiskCheckResult(
                passed=False,
                reason=f"Daily loss cap reached: {daily_pnl:.3f} <= -{self.max_daily_loss_pct:.3f}",
                check_name="daily_loss_cap",
            )
        
        return RiskCheckResult(passed=True, check_name="daily_loss_cap")
    
    def update_account_state(self, account_state: Dict[str, Any]) -> None:
        """Update internal state from account state."""
        self.current_exposure = account_state.get("asset_exposure", {})
        self.daily_trade_count = account_state.get("daily_trade_count", {})
        self.daily_pnl = account_state.get("daily_pnl", 0.0)
