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

        # Idempotency: a fill is applied once by immutable fill_id, and an
        # event once by immutable event_id (duplicate WS/REST ingest must not
        # double-count exposure or cash).
        self._applied_fill_ids: set = set()
        self._applied_event_ids: set = set()

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
        
        if not all([fill_id, ticker, quantity, price_cents]):
            logger.warning("Fill event missing required fields: %s", data)
            return

        # fill_id is the global immutable dedup key (AGENTS.md).  A second
        # event carrying an already-applied fill_id is a duplicate — drop it.
        # Quarantined (undetermined-direction) fills are NOT marked applied so
        # a later corrected event can still take effect.
        if fill_id in self._applied_fill_ids:
            logger.warning(
                "[PORTFOLIO-ENGINE-DUP-FILL] fill_id=%s ticker=%s - duplicate "
                "fill event dropped (already applied)", fill_id, ticker,
            )
            return

        # CRITICAL FIX (2026-09-21): Canonical signed-YES accounting.
        # The previous model keyed positions by traded leg ({ticker}_{side}) with
        # is_long=(action=="buy"), so a SELL YES while long NO created a phantom
        # "short YES" leg instead of netting against NO exposure, and settlement
        # inverted PnL for negative-quantity records.  On Kalshi a fill is a
        # buy/sell of a yes/no leg; the canonical exposure is signed YES:
        #   buy yes / sell no  -> +qty   (long YES)
        #   sell yes / buy no  -> -qty   (long NO)
        # Prefer the ledger's precomputed canonical signed-YES delta — it was
        # derived from canonical outcome fields and survives counterparty-form
        # exchange reporting.  Fall back to deriving from (action, side) only
        # when both are explicit and valid; never fabricate a direction.
        canonical_delta = data.get("canonical_yes_delta_cc")
        side_l = (side or "").lower()
        action_l = (action or "").lower()
        qty_contracts = Decimal(str(quantity))
        if canonical_delta is not None:
            # canonical_yes_delta_cc is in centi-contracts; this ledger's
            # quantity unit is contracts.  Divide exactly — ``// 100`` floors
            # negative deltas away from zero (e.g. -550cc -> -6 instead of
            # -5.5), overstating short exposure and corrupting basis.
            qty_change = Decimal(str(int(canonical_delta))) / Decimal(100)
        else:
            if side_l not in ("yes", "no") or action_l not in ("buy", "sell"):
                logger.critical(
                    "[PORTFOLIO-ENGINE-QUARANTINE] fill_id=%s ticker=%s action=%r side=%r - "
                    "undetermined direction; refusing to fabricate exposure",
                    fill_id, ticker, action, side,
                )
                return

            if (action_l, side_l) in (("buy", "yes"), ("sell", "no")):
                qty_change = qty_contracts  # signed YES delta > 0
            else:
                qty_change = -qty_contracts  # (sell,yes) or (buy,no) -> signed YES delta < 0

        # Canonical YES-space price: prefer the stored YES leg price; otherwise
        # complement the NO-leg price.  Never mix spaces.
        leg_price_cents = Decimal(str(price_cents))
        _leg_px = data.get("no_price_cents") if side_l == "no" else data.get("yes_price_cents")
        if _leg_px:
            leg_price_cents = Decimal(str(_leg_px))
        stored_yes = data.get("yes_price_cents")
        if stored_yes:
            yes_price_cents = Decimal(str(stored_yes))
        elif side_l == "no":
            yes_price_cents = Decimal(100) - leg_price_cents
        else:
            yes_price_cents = leg_price_cents

        # Position key is the market only: signed-YES inventory cannot be both
        # long YES and long NO on the same ticker.
        position_key = ticker

        # Get or create position
        if position_key not in self._positions:
            # New position
            position = Position(
                position_id=position_key,
                account_id=event.account_id,
                ticker=ticker,
                side="yes" if qty_change >= 0 else "no",
                quantity=Decimal(0),
                avg_entry_price_cents=yes_price_cents,
                cost_basis_cents=Decimal(0),
                realized_pnl_cents=Decimal(0),
            )
            self._positions[position_key] = position
            self._positions_by_ticker[ticker] = position
        else:
            position = self._positions[position_key]

        is_long = (action_l == "buy")

        old_quantity = position.quantity
        old_avg_price = position.avg_entry_price_cents  # YES-space cents
        old_cost_basis = position.cost_basis_cents

        # Calculate new position state (signed YES quantity, YES-space basis).
        new_quantity = old_quantity + qty_change
        realized_pnl = position.realized_pnl_cents

        if old_quantity == 0 or (old_quantity > 0) == (qty_change > 0):
            # Open or add: delta shares the existing exposure sign.
            if old_quantity == 0:
                new_avg_price = yes_price_cents
            else:
                total_contracts = abs(old_quantity) + abs(qty_change)
                total_cost = old_cost_basis + (abs(qty_change) * yes_price_cents)
                # Exact Decimal division: floor-div here silently truncates
                # basis (e.g. (5*60 + 5*55)/10 = 57.5 -> 57), skewing PnL.
                new_avg_price = (
                    total_cost / total_contracts if total_contracts > 0 else old_avg_price
                )
            new_cost_basis = abs(new_quantity) * new_avg_price
        else:
            # Reduce, close, or flip: delta opposes existing exposure.
            closed_qty = min(abs(old_quantity), abs(qty_change))
            realized_pnl += closed_qty * (yes_price_cents - old_avg_price) * (1 if old_quantity > 0 else -1)

            if abs(qty_change) > abs(old_quantity):
                # Flipped through zero - residual opens at the fill price
                new_avg_price = yes_price_cents
            else:
                # Partial or full close - residual keeps prior basis
                new_avg_price = old_avg_price
            new_cost_basis = abs(new_quantity) * new_avg_price

        # Update position
        new_position = replace(
            position,
            side="yes" if new_quantity > 0 else ("no" if new_quantity < 0 else position.side),
            quantity=new_quantity,
            avg_entry_price_cents=new_avg_price,
            cost_basis_cents=new_cost_basis,
            realized_pnl_cents=realized_pnl,
            last_updated=event.timestamp,
        )
        self._positions[position_key] = new_position
        self._positions_by_ticker[ticker] = new_position

        # Update cash ledger.
        # Prefer authoritative signed cash proceeds when the event carries them
        # (cross-leg / counterparty-form fills); otherwise derive cash in the
        # traded leg's price space.  When only the canonical delta is known
        # (side/action absent), approximate in YES space and flag it.
        fee = Decimal(str(fee_cents or 0))
        authoritative_proceeds = data.get("proceeds_cents")
        if authoritative_proceeds is not None:
            cash_impact = Decimal(str(authoritative_proceeds)) - fee
        elif side_l in ("yes", "no") and action_l in ("buy", "sell"):
            cash_impact = (-qty_contracts * leg_price_cents if is_long
                           else qty_contracts * leg_price_cents) - fee
        else:
            cash_impact = -qty_change * yes_price_cents - fee
            logger.warning(
                "[PORTFOLIO-ENGINE-CASH-ESTIMATE] fill_id=%s ticker=%s - "
                "no leg side/action or authoritative proceeds; cash impact "
                "estimated in YES space",
                fill_id, ticker,
            )
        
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
        self._applied_fill_ids.add(fill_id)

        logger.debug(
            "Applied fill: %s %s %s @ %sc (old_qty=%s new_qty=%s) cash_impact=%sc realized_pnl=%sc",
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
        reserved_cash = Decimal(str(quantity)) * Decimal(str(price_cents))
        
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
        
        logger.debug(f"Cancelled order: {order_id} released {order.reserved_cash_cents}c")
    
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

        # Calculate final PnL under canonical signed-YES accounting.
        # quantity is signed YES exposure (positive=long YES, negative=long NO)
        # and avg_entry_price_cents is in YES space, so the settlement value is
        # simply the YES payout: 100 when result=YES else 0.
        #   long YES 5 @ 60c, result YES -> +5*(100-60) = +200c
        #   long NO  5 @ 40c NO (=60c YES-space), result NO -> -5*(0-60) = +300c
        result_l = (result or "").lower()
        if result_l not in ("yes", "no"):
            logger.warning("Settlement event with unknown result=%r for %s", result, ticker)
            return
        settle_yes_cents = Decimal(100) if result_l == "yes" else Decimal(0)

        final_pnl_cents = position.quantity * (settle_yes_cents - position.avg_entry_price_cents)
        
        # Update position with realized PnL and zero quantity
        new_position = replace(
            position,
            quantity=Decimal(0),
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
            "Settlement: %s result=%s yes_settle=%dc final_pnl=%dc",
            ticker, result, settle_yes_cents, final_pnl_cents
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
            # Immutable event_id dedup: the append-only log may deliver the
            # same event twice (WS + REST double ingest, reconnect replay).
            if event.event_id in self._applied_event_ids:
                logger.warning(
                    "[PORTFOLIO-ENGINE-DUP-EVENT] event_id=%s type=%s - "
                    "duplicate event dropped", event.event_id, event.event_type,
                )
                return

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

            self._applied_event_ids.add(event.event_id)

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
            realized_pnl = sum(
                (pos.realized_pnl_cents for pos in account_positions.values()),
                Decimal(0),
            )

            # Calculate unrealized PnL from positions + current marks
            unrealized_pnl = Decimal(0)
            if current_marks:
                for pos in account_positions.values():
                    if pos.is_open and pos.ticker in current_marks:
                        current_mark = Decimal(str(current_marks[pos.ticker]))
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
        
        # Invariant 5: Position quantities must be exact (int/Decimal, never float)
        for pos_id, pos in self._positions.items():
            if pos.account_id == account_id:
                if isinstance(pos.quantity, float) or not isinstance(pos.quantity, (int, Decimal)):
                    violations.append(
                        f"Position {pos_id} has inexact quantity type: {type(pos.quantity).__name__}={pos.quantity}"
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
