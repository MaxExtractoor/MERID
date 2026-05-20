"""Portfolio Engine - Event Replay and State Reconstruction.

This module provides:
- PortfolioEngine: Replays events to build in-memory portfolio state
- Deterministic state transitions for each event type
- Real-time PnL computation from positions + market marks
- Snapshot generation for API consumption

Design principles:
- All state derived from event replay (deterministic)
- Unrealized PnL computed from positions + current marks (not stored)
- Cash ledger tracks all cash movements
- Positions track quantity, avg entry, cost basis, realized PnL
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

from utils.logger import get_logger
from merid.event_venues.kalshi.portfolio_models import (
    PortfolioEvent,
    EventType,
    CashEventType,
    Position,
    Order,
    Fill,
    CashLedgerEntry,
    PortfolioSnapshot,
    Account,
)

logger = get_logger("merid.event_venues.kalshi.portfolio_engine")


# ═══════════════════════════════════════════════════════════════════════════
# Portfolio Engine
# ═══════════════════════════════════════════════════════════════════════════

class PortfolioEngine:
    """Replays events to build in-memory portfolio state.
    
    Thread-safe singleton that maintains:
    - Cash ledger (all cash movements)
    - Positions (per-market quantity, entry price, cost basis, realized PnL)
    - Orders (working orders with reserved cash)
    - Last processed sequence ID for incremental updates
    """
    
    _instance: Optional["PortfolioEngine"] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> "PortfolioEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._local_lock = threading.Lock()
        
        # In-memory state
        self._accounts: Dict[str, Account] = {}
        self._cash_ledger: List[CashLedgerEntry] = []
        self._positions: Dict[str, Position] = {}  # position_id -> Position
        self._positions_by_ticker: Dict[str, Position] = {}  # ticker -> Position
        self._orders: Dict[str, Order] = {}  # order_id -> Order
        self._open_orders: Dict[str, Order] = {}  # order_id -> Order (only open)
        
        # Processing state
        self._last_sequence_id: int = 0
        self._last_updated: datetime = datetime.now(timezone.utc)
        
        self._initialized = True
        logger.info("PortfolioEngine initialized")
    
    def _ensure_account(self, account_id: str) -> Account:
        """Ensure account exists in state."""
        if account_id not in self._accounts:
            self._accounts[account_id] = Account(account_id=account_id)
        return self._accounts[account_id]
    
    def _apply_fill_event(self, event: PortfolioEvent) -> None:
        """Apply a fill event to update positions and cash."""
        data = event.data
        
        # Extract fill data
        fill_id = data.get("fill_id")
        order_id = data.get("order_id")
        ticker = data.get("ticker")
        side = data.get("side")  # "yes" or "no"
        action = data.get("action")  # "buy" or "sell"
        quantity = data.get("contracts", 0)
        price_cents = data.get("price_cents", 0)
        fee_cents = data.get("fee_cents", 0)
        
        if not all([fill_id, ticker, side, action, quantity, price_cents]):
            logger.warning("Fill event missing required fields: %s", data)
            return
        
        # Position key (ticker + side for now, could be more granular)
        position_key = f"{ticker}_{side}"
        
        # Get or create position
        if position_key not in self._positions:
            # New position
            position = Position(
                position_id=position_key,
                account_id=event.account_id,
                ticker=ticker,
                side=side,
                quantity=0,
                avg_entry_price_cents=price_cents,
                cost_basis_cents=0,
                realized_pnl_cents=0,
            )
            self._positions[position_key] = position
            self._positions_by_ticker[ticker] = position
        else:
            position = self._positions[position_key]
        
        # Determine direction of fill
        # buy yes = long yes, sell yes = short yes
        # buy no = long no, sell no = short no
        is_long = (action == "buy")
        qty_change = quantity if is_long else -quantity
        
        old_quantity = position.quantity
        old_avg_price = position.avg_entry_price_cents
        old_cost_basis = position.cost_basis_cents
        
        # Calculate new position state
        new_quantity = old_quantity + qty_change
        
        if (old_quantity >= 0 and new_quantity >= 0) or (old_quantity <= 0 and new_quantity <= 0):
            # Same direction - update average entry price
            if old_quantity == 0:
                new_avg_price = price_cents
                new_cost_basis = abs(new_quantity) * price_cents
            else:
                # Weighted average
                total_contracts = abs(old_quantity) + quantity
                total_cost = old_cost_basis + (quantity * price_cents)
                new_avg_price = total_cost // total_contracts if total_contracts > 0 else old_avg_price
                new_cost_basis = abs(new_quantity) * new_avg_price
            realized_pnl = position.realized_pnl_cents
        else:
            # Direction change - realize PnL on closed portion
            closed_qty = min(abs(old_quantity), abs(new_quantity))
            if old_quantity > 0:
                # Closing long
                realized_pnl = closed_qty * (price_cents - old_avg_price)
            else:
                # Closing short
                realized_pnl = closed_qty * (old_avg_price - price_cents)
            
            realized_pnl += position.realized_pnl_cents
            
            if abs(new_quantity) > abs(old_quantity):
                # Flipped direction - new entry price
                new_avg_price = price_cents
                new_cost_basis = abs(new_quantity) * price_cents
            else:
                # Fully closed or reduced
                new_avg_price = old_avg_price
                new_cost_basis = abs(new_quantity) * new_avg_price
        
        # Update position
        new_position = replace(
            position,
            quantity=new_quantity,
            avg_entry_price_cents=new_avg_price,
            cost_basis_cents=new_cost_basis,
            realized_pnl_cents=realized_pnl,
            last_updated=event.timestamp,
        )
        self._positions[position_key] = new_position
        self._positions_by_ticker[ticker] = new_position
        
        # Update cash ledger
        # buy = cash out, sell = cash in
        cash_impact = -quantity * price_cents if is_long else quantity * price_cents
        cash_impact -= fee_cents  # Fees reduce cash
        
        cash_entry = CashLedgerEntry(
            entry_id=f"cash_{fill_id}",
            account_id=event.account_id,
            event_type=CashEventType.TRADE,
            amount_cents=cash_impact,
            related_fill_id=fill_id,
            related_order_id=order_id,
            related_ticker=ticker,
            timestamp=event.timestamp,
        )
        self._cash_ledger.append(cash_entry)
        
        logger.debug(
            "Applied fill: %s %s %d @ %dc (old_qty=%d new_qty=%d) cash_impact=%dc realized_pnl=%dc",
            action, side, quantity, price_cents, old_quantity, new_quantity, cash_impact, realized_pnl
        )
    
    def _apply_order_created_event(self, event: PortfolioEvent) -> None:
        """Apply an order created event."""
        data = event.data
        
        order_id = data.get("order_id")
        ticker = data.get("ticker")
        side = data.get("side")
        action = data.get("action")
        quantity = data.get("quantity", 0)
        price_cents = data.get("price_cents", 0)
        
        if not all([order_id, ticker, side, action, quantity, price_cents]):
            logger.warning("Order created event missing required fields: %s", data)
            return
        
        # Calculate reserved cash
        reserved_cash = quantity * price_cents
        
        order = Order(
            order_id=order_id,
            account_id=event.account_id,
            ticker=ticker,
            side=side,
            action=action,
            quantity=quantity,
            price_cents=price_cents,
            status="resting",
            filled_quantity=0,
            remaining_quantity=quantity,
            reserved_cash_cents=reserved_cash,
            created_at=event.timestamp,
            updated_at=event.timestamp,
            client_order_id=data.get("client_order_id"),
            agent_id=data.get("agent_id"),
        )
        
        self._orders[order_id] = order
        self._open_orders[order_id] = order
        
        # Reserve cash
        cash_entry = CashLedgerEntry(
            entry_id=f"reserve_{order_id}",
            account_id=event.account_id,
            event_type=CashEventType.TRADE,  # Using TRADE for reservation
            amount_cents=-reserved_cash,  # Reserve reduces available cash
            related_order_id=order_id,
            related_ticker=ticker,
            timestamp=event.timestamp,
            metadata={"type": "reservation"},
        )
        self._cash_ledger.append(cash_entry)
        
        logger.debug(
            "Created order: %s %s %d @ %dc reserved=%dc",
            action, side, quantity, price_cents, reserved_cash
        )
    
    def _apply_order_cancelled_event(self, event: PortfolioEvent) -> None:
        """Apply an order cancelled event."""
        data = event.data
        order_id = data.get("order_id")
        
        if not order_id:
            logger.warning("Order cancelled event missing order_id: %s", data)
            return
        
        if order_id not in self._orders:
            logger.warning("Order cancelled for unknown order_id: %s", order_id)
            return
        
        order = self._orders[order_id]
        
        # Release reserved cash
        if order.reserved_cash_cents > 0:
            cash_entry = CashLedgerEntry(
                entry_id=f"release_{order_id}",
                account_id=event.account_id,
                event_type=CashEventType.TRADE,
                amount_cents=order.reserved_cash_cents,  # Release adds back cash
                related_order_id=order_id,
                related_ticker=order.ticker,
                timestamp=event.timestamp,
                metadata={"type": "release"},
            )
            self._cash_ledger.append(cash_entry)
        
        # Update order status
        updated_order = replace(
            order,
            status="cancelled",
            updated_at=event.timestamp,
        )
        self._orders[order_id] = updated_order
        
        # Remove from open orders
        if order_id in self._open_orders:
            del self._open_orders[order_id]
        
        logger.debug("Cancelled order: %s released %dc", order_id, order.reserved_cash_cents)
    
    def _apply_settlement_event(self, event: PortfolioEvent) -> None:
        """Apply a settlement event to realize PnL."""
        data = event.data
        
        ticker = data.get("ticker")
        result = data.get("result")  # "YES" or "NO"
        
        if not all([ticker, result]):
            logger.warning("Settlement event missing required fields: %s", data)
            return
        
        # Find position for this ticker
        position = self._positions_by_ticker.get(ticker)
        if not position or not position.is_open:
            logger.debug("No open position for settlement: %s", ticker)
            return
        
        # Calculate final PnL
        # If result matches side, position wins (100 cents per contract)
        # If result doesn't match, position loses (0 cents per contract)
        if position.side.lower() == result.lower():
            payout_cents = 100
        else:
            payout_cents = 0
        
        final_pnl_cents = (payout_cents - position.avg_entry_price_cents) * abs(position.quantity)
        
        # Update position with realized PnL and zero quantity
        new_position = replace(
            position,
            quantity=0,
            realized_pnl_cents=position.realized_pnl_cents + final_pnl_cents,
            last_updated=event.timestamp,
        )
        self._positions[position.position_id] = new_position
        self._positions_by_ticker[ticker] = new_position
        
        # Add cash for realized PnL
        cash_entry = CashLedgerEntry(
            entry_id=f"settlement_{ticker}_{event.timestamp.isoformat()}",
            account_id=event.account_id,
            event_type=CashEventType.SETTLEMENT,
            amount_cents=final_pnl_cents,
            related_ticker=ticker,
            timestamp=event.timestamp,
        )
        self._cash_ledger.append(cash_entry)
        
        logger.debug(
            "Settlement: %s result=%s payout=%dc final_pnl=%dc",
            ticker, result, payout_cents, final_pnl_cents
        )
    
    def _apply_cash_event(self, event: PortfolioEvent, cash_event_type: CashEventType) -> None:
        """Apply a cash event (deposit, withdrawal, fee, refund, adjustment)."""
        data = event.data
        amount_cents = data.get("amount_cents", 0)
        
        cash_entry = CashLedgerEntry(
            entry_id=f"{cash_event_type.value}_{event.event_id}",
            account_id=event.account_id,
            event_type=cash_event_type,
            amount_cents=amount_cents,
            timestamp=event.timestamp,
            metadata=data,
        )
        self._cash_ledger.append(cash_entry)
        
        logger.debug(
            "Cash event: %s amount=%dc",
            cash_event_type.value, amount_cents
        )
    
    def replay_event(self, event: PortfolioEvent) -> None:
        """Replay a single event to update state."""
        with self._local_lock:
            # Ensure account exists
            self._ensure_account(event.account_id)
            
            # Apply event based on type
            if event.event_type == EventType.FILL:
                self._apply_fill_event(event)
            elif event.event_type == EventType.ORDER_CREATED:
                self._apply_order_created_event(event)
            elif event.event_type == EventType.ORDER_CANCELLED:
                self._apply_order_cancelled_event(event)
            elif event.event_type == EventType.SETTLEMENT:
                self._apply_settlement_event(event)
            elif event.event_type == EventType.CASH_DEPOSIT:
                self._apply_cash_event(event, CashEventType.DEPOSIT)
            elif event.event_type == EventType.CASH_WITHDRAWAL:
                self._apply_cash_event(event, CashEventType.WITHDRAWAL)
            elif event.event_type == EventType.FEE:
                self._apply_cash_event(event, CashEventType.FEE)
            elif event.event_type == EventType.REFUND:
                self._apply_cash_event(event, CashEventType.REFUND)
            elif event.event_type == EventType.ADJUSTMENT:
                self._apply_cash_event(event, CashEventType.ADJUSTMENT)
            else:
                logger.warning("Unknown event type: %s", event.event_type)
            
            # Update processing state
            self._last_sequence_id = event.sequence_id
            self._last_updated = event.timestamp
            
            # Validate invariants after event application
            self._validate_invariants(event.account_id)
    
    def replay_events(self, events: List[PortfolioEvent]) -> None:
        """Replay multiple events in sequence order."""
        # Sort by sequence ID to ensure correct order
        events_sorted = sorted(events, key=lambda e: e.sequence_id)
        
        for event in events_sorted:
            self.replay_event(event)
        
        logger.info(
            "Replayed %d events, last sequence_id=%d",
            len(events),
            self._last_sequence_id
        )
    
    def get_snapshot(self, account_id: str, current_marks: Optional[Dict[str, int]] = None) -> PortfolioSnapshot:
        """Generate a portfolio snapshot.
        
        Args:
            account_id: Account to snapshot
            current_marks: Optional dict of ticker -> current price in cents
                           Used to compute unrealized PnL
            
        Returns:
            PortfolioSnapshot with current state
        """
        with self._local_lock:
            # Calculate cash state
            cash_available = sum(entry.amount_cents for entry in self._cash_ledger if entry.account_id == account_id)
            cash_reserved = sum(order.reserved_cash_cents for order in self._open_orders.values() if order.account_id == account_id)
            cash_total = cash_available + cash_reserved
            
            # Filter positions by account
            account_positions = {
                pos_id: pos
                for pos_id, pos in self._positions.items()
                if pos.account_id == account_id
            }
            
            # Filter orders by account
            account_orders = {
                order_id: order
                for order_id, order in self._orders.items()
                if order.account_id == account_id
            }
            
            # Calculate realized PnL
            realized_pnl = sum(pos.realized_pnl_cents for pos in account_positions.values())
            
            # Calculate unrealized PnL from positions + current marks
            unrealized_pnl = 0
            if current_marks:
                for pos in account_positions.values():
                    if pos.is_open and pos.ticker in current_marks:
                        current_mark = current_marks[pos.ticker]
                        if pos.quantity > 0:
                            # Long position
                            unrealized_pnl += (current_mark - pos.avg_entry_price_cents) * pos.quantity
                        else:
                            # Short position
                            unrealized_pnl += (pos.avg_entry_price_cents - current_mark) * abs(pos.quantity)
            
            return PortfolioSnapshot(
                account_id=account_id,
                sequence_id=self._last_sequence_id,
                timestamp=self._last_updated,
                cash_available_cents=cash_available,
                cash_reserved_cents=cash_reserved,
                cash_total_cents=cash_total,
                positions=account_positions,
                open_orders={oid: o for oid, o in account_orders.items() if o.status == "resting"},
                realized_pnl_cents=realized_pnl,
                unrealized_pnl_cents=unrealized_pnl,
            )
    
    def get_last_sequence_id(self) -> int:
        """Get the last processed sequence ID."""
        with self._local_lock:
            return self._last_sequence_id

    def _validate_invariants(self, account_id: str) -> None:
        """Validate portfolio state invariants.
        
        These checks ensure the portfolio state is consistent after event replay.
        Violations are logged but don't throw exceptions (to avoid breaking replay).
        
        Args:
            account_id: Account to validate
        """
        violations = []
        
        # Invariant 1: Cash ledger sum should equal available + reserved cash
        cash_ledger_sum = sum(
            entry.amount_cents 
            for entry in self._cash_ledger 
            if entry.account_id == account_id
        )
        cash_reserved = sum(
            order.reserved_cash_cents 
            for order in self._open_orders.values() 
            if order.account_id == account_id
        )
        cash_available = cash_ledger_sum + cash_reserved
        
        if cash_available < 0:
            violations.append(
                f"Negative cash available: {cash_available} cents (ledger_sum={cash_ledger_sum}, reserved={cash_reserved})"
            )
        
        # Invariant 2: Position quantity should match cost basis / avg entry price
        for pos_id, pos in self._positions.items():
            if pos.account_id == account_id and pos.is_open:
                expected_cost = abs(pos.quantity) * pos.avg_entry_price_cents
                if abs(pos.cost_basis_cents - expected_cost) > 1:  # Allow 1 cent rounding error
                    violations.append(
                        f"Position {pos_id} cost basis mismatch: "
                        f"expected={expected_cost}, actual={pos.cost_basis_cents}"
                    )
        
        # Invariant 3: Open orders should have reserved cash > 0
        for order_id, order in self._open_orders.items():
            if order.account_id == account_id:
                if order.reserved_cash_cents <= 0:
                    violations.append(
                        f"Open order {order_id} has non-positive reserved cash: {order.reserved_cash_cents}"
                    )
                if order.remaining_quantity <= 0:
                    violations.append(
                        f"Open order {order_id} has non-positive remaining quantity: {order.remaining_quantity}"
                    )
        
        # Invariant 4: Total reserved cash should not exceed available cash
        if cash_reserved > cash_available:
            violations.append(
                f"Reserved cash exceeds available: reserved={cash_reserved}, available={cash_available}"
            )
        
        # Invariant 5: Position quantities should be integers
        for pos_id, pos in self._positions.items():
            if pos.account_id == account_id:
                if not isinstance(pos.quantity, int):
                    violations.append(
                        f"Position {pos_id} has non-integer quantity: {pos.quantity}"
                    )
        
        # Invariant 6: All monetary values should be non-negative where expected
        for pos_id, pos in self._positions.items():
            if pos.account_id == account_id:
                if pos.avg_entry_price_cents < 0:
                    violations.append(
                        f"Position {pos_id} has negative avg entry price: {pos.avg_entry_price_cents}"
                    )
                if pos.cost_basis_cents < 0:
                    violations.append(
                        f"Position {pos_id} has negative cost basis: {pos.cost_basis_cents}"
                    )
        
        # Log violations if any
        if violations:
            logger.warning(
                "Portfolio invariant violations detected (account=%s):\n%s",
                account_id,
                "\n".join(f"  - {v}" for v in violations)
            )
        else:
            logger.debug("Portfolio invariants validated successfully (account=%s)", account_id)

    def check_invariants(self, account_id: str) -> Dict[str, any]:
        """Check portfolio invariants and return detailed results.
        
        Args:
            account_id: Account to validate
            
        Returns:
            Dictionary with validation results
        """
        with self._local_lock:
            results = {
                "account_id": account_id,
                "passed": True,
                "violations": [],
                "cash_state": {},
                "position_count": 0,
                "open_order_count": 0,
            }
            
            # Cash state
            cash_ledger_sum = sum(
                entry.amount_cents 
                for entry in self._cash_ledger 
                if entry.account_id == account_id
            )
            cash_reserved = sum(
                order.reserved_cash_cents 
                for order in self._open_orders.values() 
                if order.account_id == account_id
            )
            cash_available = cash_ledger_sum + cash_reserved
            
            results["cash_state"] = {
                "ledger_sum_cents": cash_ledger_sum,
                "reserved_cents": cash_reserved,
                "available_cents": cash_available,
            }
            
            if cash_available < 0:
                results["violations"].append(
                    f"Negative cash available: {cash_available} cents"
                )
                results["passed"] = False
            
            # Position checks
            account_positions = [
                pos for pos in self._positions.values() 
                if pos.account_id == account_id
            ]
            results["position_count"] = len(account_positions)
            
            for pos in account_positions:
                if pos.is_open:
                    expected_cost = abs(pos.quantity) * pos.avg_entry_price_cents
                    if abs(pos.cost_basis_cents - expected_cost) > 1:
                        results["violations"].append(
                            f"Position {pos.position_id} cost basis mismatch"
                        )
                        results["passed"] = False
                    
                    if pos.avg_entry_price_cents < 0:
                        results["violations"].append(
                            f"Position {pos.position_id} negative avg entry price"
                        )
                        results["passed"] = False
            
            # Order checks
            account_orders = [
                order for order in self._open_orders.values() 
                if order.account_id == account_id
            ]
            results["open_order_count"] = len(account_orders)
            
            for order in account_orders:
                if order.reserved_cash_cents <= 0:
                    results["violations"].append(
                        f"Order {order.order_id} non-positive reserved cash"
                    )
                    results["passed"] = False
                if order.remaining_quantity <= 0:
                    results["violations"].append(
                        f"Order {order.order_id} non-positive remaining quantity"
                    )
                    results["passed"] = False
            
            if cash_reserved > cash_available:
                results["violations"].append(
                    "Reserved cash exceeds available"
                )
                results["passed"] = False
            
            return results


# ═══════════════════════════════════════════════════════════════════════════
# Singleton Accessor
# ═══════════════════════════════════════════════════════════════════════════

def get_portfolio_engine() -> PortfolioEngine:
    """Get the singleton PortfolioEngine instance."""
    return PortfolioEngine()
