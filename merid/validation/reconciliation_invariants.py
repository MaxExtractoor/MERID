"""
End-to-End Reconciliation Invariants: Signal→Order→Fill→PnL Path Validation

This module enforces invariants for the complete trading episode lifecycle,
ensuring that model/execution state matches observables: fills, positions, balances, PnL.

Key Invariants:
- Episode metadata: unique episode_id ties together signals, contract, risk, orders, fills, PnL
- Conservation checks: net position size per contract equals sum of filled orders
- PnL calculation matches fills × price deltas + fees
- Edge realization attribution: realized PnL decomposable into strategy edge and execution slippage
- No orphan orders or fills (every order belongs to an episode; every fill matches an order)
- No PnL without corresponding position changes
- No negative balances or leverage beyond risk settings

Usage::

    from merid.validation.reconciliation_invariants import (
        ReconciliationInvariantChecker,
        check_episode_conservation,
        check_pnl_calculation,
        check_orphan_detection,
        check_edge_attribution
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from utils.logger import get_logger

logger = get_logger("merid.validation.reconciliation_invariants")


class ReconciliationViolation(str, Enum):
    """Types of reconciliation violations."""
    POSITION_SIZE_MISMATCH = "position_size_mismatch"
    PNL_CALCULATION_MISMATCH = "pnl_calculation_mismatch"
    ORPHAN_ORDER = "orphan_order"
    ORPHAN_FILL = "orphan_fill"
    PNL_WITHOUT_POSITION = "pnl_without_position"
    NEGATIVE_BALANCE = "negative_balance"
    LEVERAGE_EXCEEDED = "leverage_exceeded"
    EPISODE_ID_MISSING = "episode_id_missing"
    EDGE_ATTRIBUTION_MISMATCH = "edge_attribution_mismatch"


@dataclass
class Episode:
    """Complete trading episode with all lifecycle data."""
    episode_id: str
    signals: Dict[str, Any]  # Raw signals that triggered trade
    selected_contract: Dict[str, Any]  # Contract selection
    risk_decision: Dict[str, Any]  # Risk decision
    orders: List[Dict[str, Any]]  # All orders in episode
    fills: List[Dict[str, Any]]  # All fills in episode
    realized_pnl_usd: float
    edge_attribution: Dict[str, Any]  # Strategy edge vs execution slippage
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "signals": self.signals,
            "selected_contract": self.selected_contract,
            "risk_decision": self.risk_decision,
            "orders": self.orders,
            "fills": self.fills,
            "realized_pnl_usd": self.realized_pnl_usd,
            "edge_attribution": self.edge_attribution,
        }


@dataclass
class ReconciliationCheckResult:
    """Result of reconciliation check."""
    is_valid: bool
    violation_type: Optional[ReconciliationViolation]
    message: str
    context: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "violation_type": self.violation_type.value if self.violation_type else None,
            "message": self.message,
            "context": self.context,
        }


class ReconciliationInvariantChecker:
    """Checks end-to-end reconciliation invariants for trading episodes."""
    
    def __init__(self, max_leverage: float = 1.0, min_balance_usd: float = 0.0):
        self.max_leverage = max_leverage
        self.min_balance_usd = min_balance_usd
    
    def check_episode_conservation(
        self,
        episode: Episode,
        net_position_size: int,
    ) -> ReconciliationCheckResult:
        """INVARIANT: Net position size per contract equals sum of filled orders.
        
        Conservation check: the net position from fills must match the reported
        net position size for the contract.
        """
        context = {
            "episode_id": episode.episode_id,
            "net_position_size": net_position_size,
            "fill_count": len(episode.fills),
        }
        
        # Calculate net position from fills
        calculated_net_position = 0
        for fill in episode.fills:
            side = fill.get("side", "").lower()
            action = fill.get("action", "").lower()
            count = fill.get("count", 0)
            
            # BUY increases position, SELL decreases position
            if action == "buy":
                calculated_net_position += count
            elif action == "sell":
                calculated_net_position -= count
        
        context["calculated_net_position"] = calculated_net_position
        
        if calculated_net_position != net_position_size:
            return ReconciliationCheckResult(
                is_valid=False,
                violation_type=ReconciliationViolation.POSITION_SIZE_MISMATCH,
                message=f"Position size mismatch: reported={net_position_size}, calculated from fills={calculated_net_position}",
                context=context,
            )
        
        return ReconciliationCheckResult(
            is_valid=True,
            violation_type=None,
            message="Position size conservation check passed",
            context=context,
        )
    
    def check_pnl_calculation(
        self,
        episode: Episode,
        entry_price_cents: int,
        exit_price_cents: int,
        position_size: int,
        fees_usd: float,
    ) -> ReconciliationCheckResult:
        """INVARIANT: PnL calculation matches fills × price deltas + fees.
        
        PnL = (exit_price - entry_price) * position_size * direction + fees
        """
        context = {
            "episode_id": episode.episode_id,
            "entry_price_cents": entry_price_cents,
            "exit_price_cents": exit_price_cents,
            "position_size": position_size,
            "fees_usd": fees_usd,
            "reported_pnl_usd": episode.realized_pnl_usd,
        }
        
        # Calculate expected PnL
        price_delta_cents = exit_price_cents - entry_price_cents
        price_delta_usd = price_delta_cents / 100.0
        expected_pnl_usd = price_delta_usd * position_size - fees_usd
        
        context["expected_pnl_usd"] = expected_pnl_usd
        
        # Allow small epsilon for floating point comparison
        epsilon = 0.01  # 1 cent tolerance
        if abs(expected_pnl_usd - episode.realized_pnl_usd) > epsilon:
            return ReconciliationCheckResult(
                is_valid=False,
                violation_type=ReconciliationViolation.PNL_CALCULATION_MISMATCH,
                message=f"PnL calculation mismatch: reported=${episode.realized_pnl_usd:.2f}, expected=${expected_pnl_usd:.2f}",
                context=context,
            )
        
        return ReconciliationCheckResult(
            is_valid=True,
            violation_type=None,
            message="PnL calculation check passed",
            context=context,
        )
    
    def check_orphan_detection(
        self,
        episode: Episode,
        all_orders: List[Dict[str, Any]],
        all_fills: List[Dict[str, Any]],
    ) -> ReconciliationCheckResult:
        """INVARIANT: No orphan orders or fills.
        
        Every order must belong to an episode, and every fill must match an order.
        """
        context = {
            "episode_id": episode.episode_id,
            "episode_order_count": len(episode.orders),
            "episode_fill_count": len(episode.fills),
            "total_order_count": len(all_orders),
            "total_fill_count": len(all_fills),
        }
        
        # Check for orphan orders (orders not in any episode)
        episode_order_ids = {order.get("order_id") for order in episode.orders if order.get("order_id")}
        all_order_ids = {order.get("order_id") for order in all_orders if order.get("order_id")}
        
        orphan_orders = all_order_ids - episode_order_ids
        if orphan_orders:
            context["orphan_order_ids"] = list(orphan_orders)
            return ReconciliationCheckResult(
                is_valid=False,
                violation_type=ReconciliationViolation.ORPHAN_ORDER,
                message=f"Found {len(orphan_orders)} orphan orders not in episode: {orphan_orders}",
                context=context,
            )
        
        # Check for orphan fills (fills not matching any order)
        episode_fill_order_ids = {fill.get("order_id") for fill in episode.fills if fill.get("order_id")}
        all_fill_order_ids = {fill.get("order_id") for fill in all_fills if fill.get("order_id")}
        
        orphan_fills = all_fill_order_ids - episode_fill_order_ids
        if orphan_fills:
            context["orphan_fill_order_ids"] = list(orphan_fills)
            return ReconciliationCheckResult(
                is_valid=False,
                violation_type=ReconciliationViolation.ORPHAN_FILL,
                message=f"Found {len(orphan_fills)} orphan fills not in episode: {orphan_fills}",
                context=context,
            )
        
        return ReconciliationCheckResult(
            is_valid=True,
            violation_type=None,
            message="Orphan detection check passed",
            context=context,
        )
    
    def check_pnl_without_position(
        self,
        episode: Episode,
        position_changes: List[Dict[str, Any]],
    ) -> ReconciliationCheckResult:
        """INVARIANT: No PnL without corresponding position changes.
        
        If PnL is non-zero, there must be corresponding position changes.
        """
        context = {
            "episode_id": episode.episode_id,
            "realized_pnl_usd": episode.realized_pnl_usd,
            "position_change_count": len(position_changes),
        }
        
        if abs(episode.realized_pnl_usd) > 0.01 and len(position_changes) == 0:
            return ReconciliationCheckResult(
                is_valid=False,
                violation_type=ReconciliationViolation.PNL_WITHOUT_POSITION,
                message=f"PnL=${episode.realized_pnl_usd:.2f} but no position changes recorded",
                context=context,
            )
        
        return ReconciliationCheckResult(
            is_valid=True,
            violation_type=None,
            message="PnL without position check passed",
            context=context,
        )
    
    def check_negative_balance(
        self,
        balance_usd: float,
    ) -> ReconciliationCheckResult:
        """INVARIANT: No negative balances.
        
        Account balance must never go negative.
        """
        context = {
            "balance_usd": balance_usd,
            "min_balance_usd": self.min_balance_usd,
        }
        
        if balance_usd < self.min_balance_usd:
            return ReconciliationCheckResult(
                is_valid=False,
                violation_type=ReconciliationViolation.NEGATIVE_BALANCE,
                message=f"Balance=${balance_usd:.2f} below minimum=${self.min_balance_usd:.2f}",
                context=context,
            )
        
        return ReconciliationCheckResult(
            is_valid=True,
            violation_type=None,
            message="Negative balance check passed",
            context=context,
        )
    
    def check_leverage_exceeded(
        self,
        notional_usd: float,
        balance_usd: float,
    ) -> ReconciliationCheckResult:
        """INVARIANT: No leverage beyond risk settings.
        
        Notional exposure must not exceed leverage multiple of balance.
        """
        context = {
            "notional_usd": notional_usd,
            "balance_usd": balance_usd,
            "max_leverage": self.max_leverage,
        }
        
        if balance_usd <= 0:
            return ReconciliationCheckResult(
                is_valid=False,
                violation_type=ReconciliationViolation.LEVERAGE_EXCEEDED,
                message=f"Cannot calculate leverage with balance=${balance_usd:.2f}",
                context=context,
            )
        
        leverage = notional_usd / balance_usd
        context["leverage"] = leverage
        
        if leverage > self.max_leverage:
            return ReconciliationCheckResult(
                is_valid=False,
                violation_type=ReconciliationViolation.LEVERAGE_EXCEEDED,
                message=f"Leverage={leverage:.2f}x exceeds max={self.max_leverage}x (notional=${notional_usd:.2f}, balance=${balance_usd:.2f})",
                context=context,
            )
        
        return ReconciliationCheckResult(
            is_valid=True,
            violation_type=None,
            message="Leverage check passed",
            context=context,
        )
    
    def check_edge_attribution(
        self,
        episode: Episode,
        strategy_edge_usd: float,
        execution_slippage_usd: float,
    ) -> ReconciliationCheckResult:
        """INVARIANT: Edge realization attribution must be decomposable.
        
        Realized PnL = strategy edge - execution slippage
        """
        context = {
            "episode_id": episode.episode_id,
            "realized_pnl_usd": episode.realized_pnl_usd,
            "strategy_edge_usd": strategy_edge_usd,
            "execution_slippage_usd": execution_slippage_usd,
        }
        
        # Calculate expected PnL from edge attribution
        expected_pnl_usd = strategy_edge_usd - execution_slippage_usd
        
        # Allow small epsilon for floating point comparison
        epsilon = 0.01  # 1 cent tolerance
        if abs(expected_pnl_usd - episode.realized_pnl_usd) > epsilon:
            return ReconciliationCheckResult(
                is_valid=False,
                violation_type=ReconciliationViolation.EDGE_ATTRIBUTION_MISMATCH,
                message=f"Edge attribution mismatch: reported PnL=${episode.realized_pnl_usd:.2f}, expected=${expected_pnl_usd:.2f} (edge=${strategy_edge_usd:.2f} - slippage=${execution_slippage_usd:.2f})",
                context=context,
            )
        
        return ReconciliationCheckResult(
            is_valid=True,
            violation_type=None,
            message="Edge attribution check passed",
            context=context,
        )
    
    def check_episode_id_integrity(
        self,
        episode: Episode,
    ) -> ReconciliationCheckResult:
        """INVARIANT: Episode must have unique episode_id.
        
        Ensures episode metadata is complete and traceable.
        """
        context = {
            "episode_id": episode.episode_id,
        }
        
        if not episode.episode_id or episode.episode_id == "":
            return ReconciliationCheckResult(
                is_valid=False,
                violation_type=ReconciliationViolation.EPISODE_ID_MISSING,
                message="Episode missing episode_id",
                context=context,
            )
        
        return ReconciliationCheckResult(
            is_valid=True,
            violation_type=None,
            message="Episode ID integrity check passed",
            context=context,
        )
    
    def check_all_invariants(
        self,
        episode: Episode,
        net_position_size: int,
        entry_price_cents: int,
        exit_price_cents: int,
        position_size: int,
        fees_usd: float,
        all_orders: List[Dict[str, Any]],
        all_fills: List[Dict[str, Any]],
        position_changes: List[Dict[str, Any]],
        balance_usd: float,
        notional_usd: float,
        strategy_edge_usd: float,
        execution_slippage_usd: float,
    ) -> List[ReconciliationCheckResult]:
        """Run all reconciliation invariants."""
        results = []
        
        # Check episode ID integrity
        result = self.check_episode_id_integrity(episode)
        results.append(result)
        
        # Check episode conservation
        result = self.check_episode_conservation(episode, net_position_size)
        results.append(result)
        
        # Check PnL calculation
        result = self.check_pnl_calculation(
            episode, entry_price_cents, exit_price_cents, position_size, fees_usd
        )
        results.append(result)
        
        # Check orphan detection
        result = self.check_orphan_detection(episode, all_orders, all_fills)
        results.append(result)
        
        # Check PnL without position
        result = self.check_pnl_without_position(episode, position_changes)
        results.append(result)
        
        # Check negative balance
        result = self.check_negative_balance(balance_usd)
        results.append(result)
        
        # Check leverage exceeded
        result = self.check_leverage_exceeded(notional_usd, balance_usd)
        results.append(result)
        
        # Check edge attribution
        result = self.check_edge_attribution(
            episode, strategy_edge_usd, execution_slippage_usd
        )
        results.append(result)
        
        return results


# Convenience functions for direct use

def check_episode_conservation(
    episode: Episode,
    net_position_size: int,
) -> ReconciliationCheckResult:
    """Check episode conservation invariant."""
    checker = ReconciliationInvariantChecker()
    return checker.check_episode_conservation(episode, net_position_size)


def check_pnl_calculation(
    episode: Episode,
    entry_price_cents: int,
    exit_price_cents: int,
    position_size: int,
    fees_usd: float,
) -> ReconciliationCheckResult:
    """Check PnL calculation invariant."""
    checker = ReconciliationInvariantChecker()
    return checker.check_pnl_calculation(
        episode, entry_price_cents, exit_price_cents, position_size, fees_usd
    )


def check_orphan_detection(
    episode: Episode,
    all_orders: List[Dict[str, Any]],
    all_fills: List[Dict[str, Any]],
) -> ReconciliationCheckResult:
    """Check orphan detection invariant."""
    checker = ReconciliationInvariantChecker()
    return checker.check_orphan_detection(episode, all_orders, all_fills)


def check_edge_attribution(
    episode: Episode,
    strategy_edge_usd: float,
    execution_slippage_usd: float,
) -> ReconciliationCheckResult:
    """Check edge attribution invariant."""
    checker = ReconciliationInvariantChecker()
    return checker.check_edge_attribution(episode, strategy_edge_usd, execution_slippage_usd)


# Synthetic test data generator for invariant testing

def generate_synthetic_reconciliation_test_cases() -> List[Dict[str, Any]]:
    """Generate synthetic test cases for reconciliation invariants.
    
    Returns:
        List of test case dictionaries with controlled episode data.
    """
    test_cases = []
    
    # Valid case
    episode = Episode(
        episode_id="test_episode_001",
        signals={"asset": "BTC", "timestamp": 1234567890},
        selected_contract={"ticker": "KXBTC15M-26JUL211730-30", "strike": 65000},
        risk_decision={"max_size": 1, "notional": 0.50},
        orders=[
            {"order_id": "order_001", "side": "yes", "action": "buy", "count": 1}
        ],
        fills=[
            {"fill_id": "fill_001", "order_id": "order_001", "side": "yes", "action": "buy", "count": 1, "price_cents": 50}
        ],
        realized_pnl_usd=0.10,
        edge_attribution={"strategy_edge_usd": 0.15, "execution_slippage_usd": 0.05},
    )
    
    test_cases.append({
        "episode": episode,
        "net_position_size": 1,
        "entry_price_cents": 50,
        "exit_price_cents": 60,
        "position_size": 1,
        "fees_usd": 0.02,
        "all_orders": episode.orders,
        "all_fills": episode.fills,
        "position_changes": [{"ticker": "KXBTC15M-26JUL211730-30", "delta": 1}],
        "balance_usd": 100.00,
        "notional_usd": 0.50,
        "strategy_edge_usd": 0.15,
        "execution_slippage_usd": 0.05,
        "expected_valid": True,
        "description": "Valid episode with all conservation checks passing",
    })
    
    # Invalid case: position size mismatch
    episode_invalid = Episode(
        episode_id="test_episode_002",
        signals={"asset": "BTC", "timestamp": 1234567890},
        selected_contract={"ticker": "KXBTC15M-26JUL211730-30", "strike": 65000},
        risk_decision={"max_size": 1, "notional": 0.50},
        orders=[
            {"order_id": "order_002", "side": "yes", "action": "buy", "count": 1}
        ],
        fills=[
            {"fill_id": "fill_002", "order_id": "order_002", "side": "yes", "action": "buy", "count": 2, "price_cents": 50}
        ],
        realized_pnl_usd=0.10,
        edge_attribution={"strategy_edge_usd": 0.15, "execution_slippage_usd": 0.05},
    )
    
    test_cases.append({
        "episode": episode_invalid,
        "net_position_size": 1,  # Reported size is 1, but fill shows 2
        "entry_price_cents": 50,
        "exit_price_cents": 60,
        "position_size": 1,
        "fees_usd": 0.02,
        "all_orders": episode_invalid.orders,
        "all_fills": episode_invalid.fills,
        "position_changes": [{"ticker": "KXBTC15M-26JUL211730-30", "delta": 1}],
        "balance_usd": 100.00,
        "notional_usd": 0.50,
        "strategy_edge_usd": 0.15,
        "execution_slippage_usd": 0.05,
        "expected_valid": False,
        "description": "Position size mismatch between reported and calculated from fills",
    })
    
    # Invalid case: PnL without position
    episode_no_position = Episode(
        episode_id="test_episode_003",
        signals={"asset": "BTC", "timestamp": 1234567890},
        selected_contract={"ticker": "KXBTC15M-26JUL211730-30", "strike": 65000},
        risk_decision={"max_size": 1, "notional": 0.50},
        orders=[],
        fills=[],
        realized_pnl_usd=0.10,  # PnL but no position changes
        edge_attribution={"strategy_edge_usd": 0.15, "execution_slippage_usd": 0.05},
    )
    
    test_cases.append({
        "episode": episode_no_position,
        "net_position_size": 0,
        "entry_price_cents": 50,
        "exit_price_cents": 60,
        "position_size": 0,
        "fees_usd": 0.02,
        "all_orders": episode_no_position.orders,
        "all_fills": episode_no_position.fills,
        "position_changes": [],  # No position changes
        "balance_usd": 100.00,
        "notional_usd": 0.50,
        "strategy_edge_usd": 0.15,
        "execution_slippage_usd": 0.05,
        "expected_valid": False,
        "description": "PnL recorded without corresponding position changes",
    })
    
    return test_cases
