"""Kalshi Risk Policy - Explicit behavior for each bankroll state.

NO magic. NO "error -> 0". Just clear rules:
- FRESH: Normal risk caps
- STALE: Reduced caps or block new risk
- ERROR: Hard block with clear reason
- UNKNOWN: Hard block
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict, Any

from utils.logger import get_logger
from merid.event_venues.kalshi.types import BalanceState, InternalBankroll
# CRITICAL FIX: Make BankrollSummary import lazy to prevent import-time bankroll service initialization
# BankrollSummary import was triggering bankroll service initialization during import
def _get_BankrollSummary():
    """Lazy import wrapper for BankrollSummary to prevent import-time bankroll initialization."""
    from merid.event_venues.kalshi.bankroll_service_v2 import BankrollSummary
    return BankrollSummary

logger = get_logger("merid.event_venues.kalshi.risk_policy")


@dataclass(frozen=True)
class RiskAllowance:
    """Result of risk policy evaluation - what trading is allowed."""
    allow_new_positions: bool
    max_position_usd: Decimal  # Can be 0 if blocked
    allow_increases: bool      # Can we increase existing positions?
    risk_fraction_multiplier: Decimal  # Applied to base risk fraction
    
    # Messaging
    reason: str                  # Human-readable why
    log_level: str               # info | warning | error
    alert: bool                  # Should we alert ops?
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "allow_new_positions": self.allow_new_positions,
            "max_position_usd": str(self.max_position_usd),
            "allow_increases": self.allow_increases,
            "risk_fraction_multiplier": str(self.risk_fraction_multiplier),
            "reason": self.reason,
        }


class KalshiRiskPolicy:
    """Defines explicit risk behavior for each bankroll state.
    
    This is the ONLY place that decides what happens when bankroll
    is fresh, stale, error, or unknown. No scattered logic.
    """
    
    def __init__(
        self,
        fresh_risk_multiplier: Decimal = Decimal("1.0"),      # 100% of configured risk
        stale_risk_multiplier: Decimal = Decimal("0.5"),     # 50% when stale
        allow_trading_when_stale: bool = True,                # Or block entirely?
        block_on_error: bool = True,
        stale_warning_threshold: int = 3,                     # Warn after N stale periods
    ):
        self._fresh_mult = fresh_risk_multiplier
        self._stale_mult = stale_risk_multiplier
        self._allow_stale_trading = allow_trading_when_stale
        self._block_on_error = block_on_error
        self._stale_warning_threshold = stale_warning_threshold
        
        self._consecutive_stale_periods = 0
    
    def evaluate(self, summary) -> RiskAllowance:
        """Evaluate risk policy for current bankroll state.
        
        This is the SINGLE entry point for all risk decisions.
        NO other code should check bankroll state directly.
        """
        state = summary.state
        
        if state == BalanceState.FRESH:
            self._consecutive_stale_periods = 0
            equity = summary.equity_usd or Decimal("0")
            max_pos = equity * self._fresh_mult
            
            return RiskAllowance(
                allow_new_positions=True,
                max_position_usd=max_pos,
                allow_increases=True,
                risk_fraction_multiplier=self._fresh_mult,
                reason=f"Bankroll FRESH: equity=${equity:,.2f}, normal risk",
                log_level="info",
                alert=False,
            )
        
        elif state == BalanceState.STALE:
            self._consecutive_stale_periods += 1
            equity = summary.equity_usd
            
            if equity is None:
                # Stale but no equity known - this is effectively ERROR
                return RiskAllowance(
                    allow_new_positions=False,
                    max_position_usd=Decimal("0"),
                    allow_increases=False,
                    risk_fraction_multiplier=Decimal("0"),
                    reason="Bankroll STALE with no known equity - BLOCKING",
                    log_level="error",
                    alert=True,
                )
            
            if not self._allow_stale_trading:
                return RiskAllowance(
                    allow_new_positions=False,
                    max_position_usd=Decimal("0"),
                    allow_increases=False,
                    risk_fraction_multiplier=Decimal("0"),
                    reason="Bankroll STALE: trading disabled by policy",
                    log_level="warning",
                    alert=False,
                )
            
            # Stale but allowing degraded trading
            max_pos = equity * self._stale_mult
            alert = self._consecutive_stale_periods >= self._stale_warning_threshold
            
            return RiskAllowance(
                allow_new_positions=True,
                max_position_usd=max_pos,
                allow_increases=True,  # Allow increases but with reduced size
                risk_fraction_multiplier=self._stale_mult,
                reason=f"Bankroll STALE (periods={self._consecutive_stale_periods}): "
                       f"equity=${equity:,.2f}, reduced risk to {self._stale_mult*100:.0f}%",
                log_level="warning",
                alert=alert,
            )
        
        elif state == BalanceState.ERROR:
            self._consecutive_stale_periods += 1
            
            return RiskAllowance(
                allow_new_positions=False,
                max_position_usd=Decimal("0"),
                allow_increases=False,
                risk_fraction_multiplier=Decimal("0"),
                reason=f"Bankroll ERROR: {summary.last_error_reason or 'Unknown error'}",
                log_level="error",
                alert=True,
            )
        
        elif state == BalanceState.UNKNOWN:
            return RiskAllowance(
                allow_new_positions=False,
                max_position_usd=Decimal("0"),
                allow_increases=False,
                risk_fraction_multiplier=Decimal("0"),
                reason="Bankroll UNKNOWN: never successfully fetched",
                log_level="error",
                alert=True,
            )
        
        else:
            # Should never happen
            logger.error(f"[risk_policy] Unexpected state: {state}")
            return RiskAllowance(
                allow_new_positions=False,
                max_position_usd=Decimal("0"),
                allow_increases=False,
                risk_fraction_multiplier=Decimal("0"),
                reason=f"Unexpected bankroll state: {state} - BLOCKING",
                log_level="error",
                alert=True,
            )


# Default policy instance
DEFAULT_POLICY = KalshiRiskPolicy()


def get_default_policy() -> KalshiRiskPolicy:
    """Get the default risk policy."""
    return DEFAULT_POLICY


async def check_trade_allowed(
    summary,
    proposed_notional: Decimal,
    policy: Optional[KalshiRiskPolicy] = None,
) -> tuple[bool, str]:
    """Quick check if a trade is allowed.
    
    Returns (allowed, reason).
    """
    policy = policy or DEFAULT_POLICY
    allowance = policy.evaluate(summary)
    
    if not allowance.allow_new_positions:
        return False, allowance.reason
    
    if proposed_notional > allowance.max_position_usd:
        return False, (
            f"Proposed ${proposed_notional:,.2f} exceeds max "
            f"${allowance.max_position_usd:,.2f} ({allowance.reason})"
        )
    
    return True, allowance.reason
