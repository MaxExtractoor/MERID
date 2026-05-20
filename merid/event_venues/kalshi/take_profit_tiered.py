"""Tiered Take-Profit Extension — Explicit 40%/40%/20% Tier Tracking.

This module extends the existing TakeProfitManager with explicit tier-level
observability for the 40%/40%/20% ladder strategy. It maintains backward
compatibility with existing code while adding:

- Tier completion tracking (Tier 1, 2, 3)
- Per-tier realized PnL metrics
- Explicit tier state transitions
- Tier-aware logging and observability

The extension is designed as a mixin-style addition that can be applied to
existing TakeProfitManager instances without breaking existing functionality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.take_profit_tiered")


@dataclass
class TierCompletionRecord:
    """Record of a completed tier exit."""
    tier_number: int
    exit_price_cents: int
    contracts_exited: int
    realized_pnl_cents: float
    exit_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    r_multiple_captured: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            "tier": self.tier_number,
            "exit_price": self.exit_price_cents,
            "contracts": self.contracts_exited,
            "realized_pnl_cents": self.realized_pnl_cents,
            "r_multiple": self.r_multiple_captured,
            "timestamp": self.exit_timestamp,
        }


@dataclass
class TieredPositionState:
    """Extended position state with explicit tier tracking.
    
    This wraps the existing TakeProfitPositionState and adds tier-specific
    tracking for the 40%/40%/20% ladder strategy.
    """
    position_id: str
    ticker: str
    side: str
    entry_price_cents: int
    total_contracts: int
    
    # Tier tracking
    tier1_completed: bool = False
    tier2_completed: bool = False
    tier3_completed: bool = False
    
    # Contracts remaining after each tier
    contracts_after_tier1: int = 0
    contracts_after_tier2: int = 0
    
    # Per-tier results
    tier_completions: List[TierCompletionRecord] = field(default_factory=list)
    
    # Running totals
    total_realized_pnl_cents: float = 0.0
    
    def get_current_tier(self) -> int:
        """Determine which tier we are currently in."""
        if self.tier3_completed:
            return 4  # Fully closed
        if self.tier2_completed:
            return 3  # In tier 3 (final)
        if self.tier1_completed:
            return 2  # In tier 2
        return 1  # In tier 1 (initial)
    
    def get_remaining_for_tier(self, tier: int) -> int:
        """Get contracts remaining at start of given tier."""
        if tier == 1:
            return self.total_contracts
        if tier == 2:
            return self.contracts_after_tier1
        if tier == 3:
            return self.contracts_after_tier2
        return 0
    
    def record_tier_completion(
        self,
        tier: int,
        exit_price_cents: int,
        contracts_exited: int,
        fees_cents: float,
    ) -> TierCompletionRecord:
        """Record completion of a tier exit."""
        # Calculate PnL
        if self.side == "yes":
            gross_pnl = (exit_price_cents - self.entry_price_cents) * contracts_exited
        else:
            gross_pnl = (self.entry_price_cents - exit_price_cents) * contracts_exited
        
        net_pnl = gross_pnl - fees_cents
        
        # Calculate R-multiple
        r_cents = self.entry_price_cents if self.side == "yes" else (100 - self.entry_price_cents)
        if r_cents > 0:
            r_multiple = (exit_price_cents - self.entry_price_cents) / r_cents
            if self.side == "no":
                r_multiple = (self.entry_price_cents - exit_price_cents) / r_cents
        else:
            r_multiple = 0.0
        
        record = TierCompletionRecord(
            tier_number=tier,
            exit_price_cents=exit_price_cents,
            contracts_exited=contracts_exited,
            realized_pnl_cents=net_pnl,
            r_multiple_captured=r_multiple,
        )
        
        self.tier_completions.append(record)
        self.total_realized_pnl_cents += net_pnl
        
        # Update tier flags and remaining contracts
        if tier == 1:
            self.tier1_completed = True
            self.contracts_after_tier1 = self.total_contracts - contracts_exited
        elif tier == 2:
            self.tier2_completed = True
            self.contracts_after_tier2 = self.contracts_after_tier1 - contracts_exited
        elif tier == 3:
            self.tier3_completed = True
        
        return record
    
    def to_dict(self) -> dict:
        return {
            "position_id": self.position_id,
            "ticker": self.ticker,
            "side": self.side,
            "entry_price": self.entry_price_cents,
            "total_contracts": self.total_contracts,
            "current_tier": self.get_current_tier(),
            "tier_progress": {
                "tier1_complete": self.tier1_completed,
                "tier2_complete": self.tier2_completed,
                "tier3_complete": self.tier3_completed,
            },
            "contracts_remaining": {
                "after_tier1": self.contracts_after_tier1,
                "after_tier2": self.contracts_after_tier2,
            },
            "tier_completions": [t.to_dict() for t in self.tier_completions],
            "total_realized_pnl_cents": self.total_realized_pnl_cents,
        }


class TakeProfitManagerTieredExtension:
    """Extension mixin that adds explicit tier tracking to TakeProfitManager.
    
    Usage:
        >>> tp_mgr = TakeProfitManager(config=config)
        >>> tiered_ext = TakeProfitManagerTieredExtension(tp_mgr)
        >>> 
        >>> # In on_fill handler:
        >>> tier = tiered_ext.infer_tier_from_action(action)
        >>> tiered_ext.record_tier_completion(pos_id, tier, exit_price, contracts, fees)
    """
    
    def __init__(self, tp_manager: "TakeProfitManager") -> None:
        self._tp_mgr = tp_manager
        self._tiered_states: Dict[str, TieredPositionState] = {}
    
    def get_or_create_tiered_state(
        self,
        position_id: str,
        ticker: str,
        side: str,
        entry_price_cents: int,
        total_contracts: int,
    ) -> TieredPositionState:
        """Get or create tiered state for a position."""
        if position_id not in self._tiered_states:
            self._tiered_states[position_id] = TieredPositionState(
                position_id=position_id,
                ticker=ticker,
                side=side,
                entry_price_cents=entry_price_cents,
                total_contracts=total_contracts,
            )
        return self._tiered_states[position_id]
    
    def infer_tier_from_action(self, action: "TakeProfitAction", current_state: Optional[TieredPositionState] = None) -> int:
        """Infer which tier an action belongs to based on its characteristics.
        
        Uses heuristics:
        - If state shows tier1 not complete → Tier 1
        - If state shows tier1 complete but not tier2 → Tier 2
        - If state shows tier2 complete → Tier 3
        - If no state, uses action reason string heuristics
        """
        if current_state:
            return current_state.get_current_tier()
        
        # Fallback: parse from reason string
        reason_lower = action.reason.lower()
        if "hard" in reason_lower or "150%" in reason_lower or "tier 3" in reason_lower:
            return 3
        if "trailing" in reason_lower and "tier 2" in reason_lower:
            return 2
        if "primary" in reason_lower or "tier 1" in reason_lower:
            return 1
        
        # Default: assume tier 1 for partial, tier 3 for full close
        return 3 if action.action_type == "CLOSE_FULL" else 1
    
    def record_tier_completion(
        self,
        position_id: str,
        tier: int,
        exit_price_cents: int,
        contracts_exited: int,
        fees_cents: float,
    ) -> Optional[TieredPositionState]:
        """Record completion of a tier and return updated state."""
        tiered_state = self._tiered_states.get(position_id)
        if not tiered_state:
            logger.warning(
                "[TIERED-TP] %s: No tiered state found for tier %d completion",
                position_id, tier
            )
            return None
        
        record = tiered_state.record_tier_completion(
            tier=tier,
            exit_price_cents=exit_price_cents,
            contracts_exited=contracts_exited,
            fees_cents=fees_cents,
        )
        
        logger.info(
            "[TIERED-TP-COMPLETE] %s | tier=%d | qty=%d | price=%dc | pnl=%.1f¢ | r=%.2f",
            position_id,
            tier,
            contracts_exited,
            exit_price_cents,
            record.realized_pnl_cents,
            record.r_multiple_captured,
        )
        
        # Emit metric
        self._emit_tier_completion_metric(tiered_state.ticker, tier, record)
        
        return tiered_state
    
    def get_tiered_summary(self, position_id: str) -> Optional[dict]:
        """Get tiered summary for a specific position."""
        state = self._tiered_states.get(position_id)
        return state.to_dict() if state else None
    
    def get_all_summaries(self) -> Dict[str, dict]:
        """Get tiered summaries for all tracked positions."""
        return {pos_id: state.to_dict() for pos_id, state in self._tiered_states.items()}
    
    def cleanup_closed_position(self, position_id: str) -> Optional[dict]:
        """Clean up a closed position and return its final tiered summary."""
        state = self._tiered_states.pop(position_id, None)
        if state:
            logger.info(
                "[TIERED-TP-CLEANUP] %s | final_pnl=%.1f¢ | tiers_completed=%d",
                position_id,
                state.total_realized_pnl_cents,
                len(state.tier_completions)
            )
            return state.to_dict()
        return None
    
    def _emit_tier_completion_metric(
        self,
        ticker: str,
        tier: int,
        record: TierCompletionRecord,
    ) -> None:
        """Emit metric for tier completion."""
        try:
            from merid.metrics.cell_metrics import record_metric
            record_metric(
                name="tp_tier_complete",
                value=record.realized_pnl_cents,
                tags={
                    "ticker": ticker,
                    "tier": str(tier),
                    "r_multiple": f"{record.r_multiple_captured:.2f}",
                }
            )
        except Exception as e:
            logger.debug("[TIERED-TP] Failed to emit metric: %s", e)


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS for CT integration
# ═══════════════════════════════════════════════════════════════════════════

def calculate_tiered_exit_summary(
    entry_price_cents: int,
    exit_price_cents: int,
    side: str,
    total_contracts: int,
    tier: int,
    fees_cents: float,
) -> dict:
    """Calculate comprehensive exit summary for a tier completion.
    
    Returns dict with:
        - gross_pnl_cents
        - net_pnl_cents
        - r_multiple_captured
        - tier_percentage_of_total (what % of original position this was)
        - cumulative_pnl_after_this_tier
    """
    # Gross PnL
    if side == "yes":
        gross_pnl = (exit_price_cents - entry_price_cents) * total_contracts
    else:
        gross_pnl = (entry_price_cents - exit_price_cents) * total_contracts
    
    net_pnl = gross_pnl - fees_cents
    
    # R-multiple
    r_cents = entry_price_cents if side == "yes" else (100 - entry_price_cents)
    if r_cents > 0:
        price_delta = exit_price_cents - entry_price_cents
        if side == "no":
            price_delta = entry_price_cents - exit_price_cents
        r_multiple = price_delta / r_cents
    else:
        r_multiple = 0.0
    
    # Tier percentage
    tier_fractions = {1: 0.40, 2: 0.40, 3: 1.00}  # Tier 3 takes remainder
    tier_pct = tier_fractions.get(tier, 0.0) * 100
    
    return {
        "gross_pnl_cents": gross_pnl,
        "net_pnl_cents": net_pnl,
        "fees_cents": fees_cents,
        "r_multiple_captured": r_multiple,
        "tier_percentage": tier_pct,
        "tier_number": tier,
        "entry_price_cents": entry_price_cents,
        "exit_price_cents": exit_price_cents,
    }


def format_tp_lifecycle_log(
    position_id: str,
    ticker: str,
    side: str,
    entry_price: int,
    tier_records: List[TierCompletionRecord],
) -> str:
    """Format a complete position lifecycle for structured logging."""
    total_pnl = sum(r.realized_pnl_cents for r in tier_records)
    total_contracts = sum(r.contracts_exited for r in tier_records)
    
    lines = [
        f"[TP-LIFECYCLE] {position_id} {ticker} {side}",
        f"  Entry: {entry_price}c",
        f"  Total exited: {total_contracts} contracts",
        f"  Total realized PnL: {total_pnl:.1f}¢",
        "  Tier breakdown:",
    ]
    
    for record in tier_records:
        lines.append(
            f"    Tier {record.tier_number}: {record.contracts_exited}@" +
            f"{record.exit_price_cents}c PnL={record.realized_pnl_cents:.1f}¢ R={record.r_multiple_captured:.2f}"
        )
    
    return "\n".join(lines)
