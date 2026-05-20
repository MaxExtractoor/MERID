"""Kalshi API Event Sources for Portfolio Event Log.

This module provides adapters that wire up Kalshi APIs as event sources:
- FillsEventSource: Ingests fills from fills_ledger
- OrdersEventSource: Ingests orders from order system
- SettlementsEventSource: Ingests settlements from settlement_poller
- BankrollEventSource: Ingests cash events from bankroll_service

Design principles:
- Kalshi is the ONLY source of truth for events
- Events are converted to PortfolioEvents and appended to event log
- Idempotent: Duplicate events are rejected by event log
- Real-time: Subscribe to WebSocket events when available
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from uuid import uuid4

from utils.logger import get_logger
from merid.event_venues.kalshi.portfolio_models import (
    PortfolioEvent,
    EventType,
)
from merid.event_venues.kalshi.portfolio_event_log import get_portfolio_event_log
from merid.event_venues.kalshi.portfolio_engine import get_portfolio_engine

logger = get_logger("merid.event_venues.kalshi.portfolio_event_sources")


# ═══════════════════════════════════════════════════════════════════════════
# Event Source Adapters
# ═══════════════════════════════════════════════════════════════════════════

class KalshiEventSourceAdapter:
    """Base adapter for Kalshi event sources."""
    
    def __init__(self, account_id: str = "default"):
        self.account_id = account_id
        self._event_log = get_portfolio_event_log()
        self._engine = get_portfolio_engine()
        self._lock = threading.Lock()
        self._enabled = True
    
    def _create_event_id(self, prefix: str, source_id: str) -> str:
        """Create a unique event ID."""
        return f"{prefix}_{source_id}"
    
    def _append_event(self, event: PortfolioEvent) -> bool:
        """Append event to log and replay in engine."""
        if not self._enabled:
            return False
        
        with self._lock:
            # Append to event log
            appended = self._event_log.append_event(event)
            
            if appended:
                # Replay in engine
                self._engine.replay_event(event)
                logger.debug(
                    "EventSource: appended and replayed event_id=%s type=%s",
                    event.event_id,
                    event.event_type.value
                )
            else:
                logger.debug(
                    "EventSource: duplicate event_id=%s skipped",
                    event.event_id
                )
            
            return appended
    
    def enable(self) -> None:
        """Enable event ingestion."""
        with self._lock:
            self._enabled = True
            logger.info("EventSource enabled for account=%s", self.account_id)
    
    def disable(self) -> None:
        """Disable event ingestion."""
        with self._lock:
            self._enabled = False
            logger.info("EventSource disabled for account=%s", self.account_id)


class FillsEventSource(KalshiEventSourceAdapter):
    """Ingests fills from fills_ledger as FILL events."""
    
    def ingest_fill(self, fill_data: Dict[str, Any]) -> bool:
        """Ingest a fill from fills_ledger.
        
        Args:
            fill_data: Dictionary with fill fields from KalshiFill
            
        Returns:
            True if event was appended, False if duplicate
        """
        fill_id = fill_data.get("fill_id") or fill_data.get("venue_fill_id")
        if not fill_id:
            logger.warning("FillsEventSource: fill missing fill_id")
            return False
        
        event_id = self._create_event_id("fill", fill_id)
        
        event = PortfolioEvent(
            event_id=event_id,
            sequence_id=0,  # Assigned by event log
            event_type=EventType.FILL,
            account_id=self.account_id,
            timestamp=datetime.fromisoformat(fill_data.get("timestamp", datetime.now(timezone.utc).isoformat())),
            data={
                "fill_id": fill_id,
                "order_id": fill_data.get("order_id"),
                "ticker": fill_data.get("market_ticker") or fill_data.get("ticker"),
                "side": fill_data.get("side"),
                "action": fill_data.get("action", "buy"),
                "contracts": int(fill_data.get("count_fp", fill_data.get("size", 0))),
                "price_cents": int(fill_data.get("price_cents", 0)),
                "fee_cents": int(float(fill_data.get("fee_cost", fill_data.get("fee", 0))) * 100),
                "agent_id": fill_data.get("agent_id"),
                "ingestion_source": fill_data.get("ingestion_source", "unknown"),
            },
        )
        
        return self._append_event(event)


class OrdersEventSource(KalshiEventSourceAdapter):
    """Ingests order lifecycle events."""
    
    def ingest_order_created(self, order_data: Dict[str, Any]) -> bool:
        """Ingest an order created event.
        
        Args:
            order_data: Dictionary with order fields
            
        Returns:
            True if event was appended, False if duplicate
        """
        order_id = order_data.get("order_id")
        if not order_id:
            logger.warning("OrdersEventSource: order missing order_id")
            return False
        
        event_id = self._create_event_id("order_created", order_id)
        
        event = PortfolioEvent(
            event_id=event_id,
            sequence_id=0,
            event_type=EventType.ORDER_CREATED,
            account_id=self.account_id,
            timestamp=datetime.fromisoformat(order_data.get("created_at", datetime.now(timezone.utc).isoformat())),
            data={
                "order_id": order_id,
                "ticker": order_data.get("ticker"),
                "side": order_data.get("side"),
                "action": order_data.get("action", "buy"),
                "quantity": order_data.get("size", order_data.get("quantity", 0)),
                "price_cents": int(order_data.get("price", 0) * 100) if order_data.get("price") else 0,
                "client_order_id": order_data.get("client_order_id"),
                "agent_id": order_data.get("agent_id"),
            },
        )
        
        return self._append_event(event)
    
    def ingest_order_cancelled(self, order_data: Dict[str, Any]) -> bool:
        """Ingest an order cancelled event.
        
        Args:
            order_data: Dictionary with order fields
            
        Returns:
            True if event was appended, False if duplicate
        """
        order_id = order_data.get("order_id")
        if not order_id:
            logger.warning("OrdersEventSource: order missing order_id")
            return False
        
        event_id = self._create_event_id("order_cancelled", order_id)
        
        event = PortfolioEvent(
            event_id=event_id,
            sequence_id=0,
            event_type=EventType.ORDER_CANCELLED,
            account_id=self.account_id,
            timestamp=datetime.fromisoformat(order_data.get("updated_at", datetime.now(timezone.utc).isoformat())),
            data={
                "order_id": order_id,
            },
        )
        
        return self._append_event(event)
    
    def ingest_order_filled(self, order_data: Dict[str, Any]) -> bool:
        """Ingest an order filled event (for tracking order lifecycle).
        
        Note: Actual fills are ingested via FillsEventSource.
        This event is for order state tracking only.
        
        Args:
            order_data: Dictionary with order fields
            
        Returns:
            True if event was appended, False if duplicate
        """
        order_id = order_data.get("order_id")
        if not order_id:
            logger.warning("OrdersEventSource: order missing order_id")
            return False
        
        event_id = self._create_event_id("order_filled", order_id)
        
        event = PortfolioEvent(
            event_id=event_id,
            sequence_id=0,
            event_type=EventType.ORDER_FILLED,
            account_id=self.account_id,
            timestamp=datetime.fromisoformat(order_data.get("updated_at", datetime.now(timezone.utc).isoformat())),
            data={
                "order_id": order_id,
                "filled_quantity": order_data.get("filled", 0),
                "remaining_quantity": order_data.get("remaining", 0),
            },
        )
        
        return self._append_event(event)


class SettlementsEventSource(KalshiEventSourceAdapter):
    """Ingests settlement events from settlement_poller."""
    
    def ingest_settlement(self, settlement_data: Dict[str, Any]) -> bool:
        """Ingest a settlement event.
        
        Args:
            settlement_data: Dictionary with settlement fields
            
        Returns:
            True if event was appended, False if duplicate
        """
        ticker = settlement_data.get("ticker")
        if not ticker:
            logger.warning("SettlementsEventSource: settlement missing ticker")
            return False
        
        # Create unique event ID from ticker + timestamp
        timestamp = settlement_data.get("timestamp", datetime.now(timezone.utc).isoformat())
        event_id = self._create_event_id("settlement", f"{ticker}_{timestamp}")
        
        event = PortfolioEvent(
            event_id=event_id,
            sequence_id=0,
            event_type=EventType.SETTLEMENT,
            account_id=self.account_id,
            timestamp=datetime.fromisoformat(timestamp),
            data={
                "ticker": ticker,
                "result": settlement_data.get("result"),
                "market_id": settlement_data.get("market_id"),
                "asset": settlement_data.get("asset"),
                "timeframe": settlement_data.get("timeframe"),
            },
        )
        
        return self._append_event(event)


class BankrollEventSource(KalshiEventSourceAdapter):
    """Ingests cash events from bankroll_service."""
    
    def ingest_deposit(self, amount_cents: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Ingest a deposit event.
        
        Args:
            amount_cents: Deposit amount in cents
            metadata: Optional metadata
            
        Returns:
            True if event was appended, False if duplicate
        """
        event_id = self._create_event_id("deposit", uuid4().hex)
        
        event = PortfolioEvent(
            event_id=event_id,
            sequence_id=0,
            event_type=EventType.CASH_DEPOSIT,
            account_id=self.account_id,
            timestamp=datetime.now(timezone.utc),
            data={
                "amount_cents": amount_cents,
                **(metadata or {}),
            },
        )
        
        return self._append_event(event)
    
    def ingest_withdrawal(self, amount_cents: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Ingest a withdrawal event.
        
        Args:
            amount_cents: Withdrawal amount in cents
            metadata: Optional metadata
            
        Returns:
            True if event was appended, False if duplicate
        """
        event_id = self._create_event_id("withdrawal", uuid4().hex)
        
        event = PortfolioEvent(
            event_id=event_id,
            sequence_id=0,
            event_type=EventType.CASH_WITHDRAWAL,
            account_id=self.account_id,
            timestamp=datetime.now(timezone.utc),
            data={
                "amount_cents": amount_cents,
                **(metadata or {}),
            },
        )
        
        return self._append_event(event)
    
    def ingest_fee(self, amount_cents: int, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Ingest a fee event.
        
        Args:
            amount_cents: Fee amount in cents
            metadata: Optional metadata
            
        Returns:
            True if event was appended, False if duplicate
        """
        event_id = self._create_event_id("fee", uuid4().hex)
        
        event = PortfolioEvent(
            event_id=event_id,
            sequence_id=0,
            event_type=EventType.FEE,
            account_id=self.account_id,
            timestamp=datetime.now(timezone.utc),
            data={
                "amount_cents": amount_cents,
                **(metadata or {}),
            },
        )
        
        return self._append_event(event)


# ═══════════════════════════════════════════════════════════════════════════
# Event Source Manager
# ═══════════════════════════════════════════════════════════════════════════

class KalshiEventSourceManager:
    """Manages all Kalshi event sources and coordinates ingestion."""
    
    _instance: Optional["KalshiEventSourceManager"] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls, account_id: str = "default") -> "KalshiEventSourceManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, account_id: str = "default"):
        if self._initialized:
            return
        
        self.account_id = account_id
        self._fills_source = FillsEventSource(account_id)
        self._orders_source = OrdersEventSource(account_id)
        self._settlements_source = SettlementsEventSource(account_id)
        self._bankroll_source = BankrollEventSource(account_id)
        
        self._initialized = True
        logger.info("KalshiEventSourceManager initialized for account=%s", account_id)
    
    def get_fills_source(self) -> FillsEventSource:
        return self._fills_source
    
    def get_orders_source(self) -> OrdersEventSource:
        return self._orders_source
    
    def get_settlements_source(self) -> SettlementsEventSource:
        return self._settlements_source
    
    def get_bankroll_source(self) -> BankrollEventSource:
        return self._bankroll_source
    
    def enable_all(self) -> None:
        """Enable all event sources."""
        self._fills_source.enable()
        self._orders_source.enable()
        self._settlements_source.enable()
        self._bankroll_source.enable()
        logger.info("All Kalshi event sources enabled")
    
    def disable_all(self) -> None:
        """Disable all event sources."""
        self._fills_source.disable()
        self._orders_source.disable()
        self._settlements_source.disable()
        self._bankroll_source.disable()
        logger.info("All Kalshi event sources disabled")


def get_kalshi_event_source_manager(account_id: str = "default") -> KalshiEventSourceManager:
    """Get the singleton KalshiEventSourceManager instance."""
    return KalshiEventSourceManager(account_id)
