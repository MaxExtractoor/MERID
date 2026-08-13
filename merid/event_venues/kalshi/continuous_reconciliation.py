"""Continuous Position Reconciliation Service

CRITICAL FIX (2026-07-17): Implements continuous position reconciliation with 60s background checks.
This ensures position drift is detected and corrected in real-time, not just on reconnect.

Architecture:
- ContinuousReconciler: Background service that runs periodic reconciliation
- PositionMismatch: Represents a discrepancy between sources
- ReconciliationAction: Actions to take on mismatch (ACCEPT_EXCHANGE, ACCEPT_LOCAL, FLAG_ONLY)

Reconciliation Sources:
1. Kalshi REST API (source of truth)
2. Internal fills ledger
3. PositionMonitor state

Frequency: Every 60 seconds
"""

from __future__ import annotations

import asyncio
import threading
import time as _time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from utils.logger import get_logger

logger = get_logger(__name__)


class ReconciliationAction(Enum):
    """Actions to take on position mismatch."""
    ACCEPT_EXCHANGE = "accept_exchange"  # Trust exchange, update local
    ACCEPT_LOCAL = "accept_local"  # Trust local, ignore exchange
    FLAG_ONLY = "flag_only"  # Log mismatch, do not adjust


@dataclass
class PositionMismatch:
    """Represents a discrepancy between position sources."""
    market_id: str
    local_contracts: int
    exchange_contracts: int
    local_side: str
    exchange_side: str
    local_avg_price_cents: int
    exchange_avg_price_cents: int
    detected_at: datetime
    action: ReconciliationAction = ReconciliationAction.FLAG_ONLY
    # CRITICAL 2026-08-13: Canonical centi-contract quantities for unit-safe
    # comparison and sync_from_rest.
    local_quantity_cc: int = 0
    exchange_quantity_cc: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/API."""
        return {
            "market_id": self.market_id,
            "local_contracts": self.local_contracts,
            "exchange_contracts": self.exchange_contracts,
            "local_side": self.local_side,
            "exchange_side": self.exchange_side,
            "local_avg_price_cents": self.local_avg_price_cents,
            "exchange_avg_price_cents": self.exchange_avg_price_cents,
            "local_quantity_cc": self.local_quantity_cc,
            "exchange_quantity_cc": self.exchange_quantity_cc,
            "detected_at": self.detected_at.isoformat(),
            "action": self.action.value,
        }


class ContinuousReconciler:
    """Background service for continuous position reconciliation.

    Runs every 60 seconds to:
    1. Fetch positions from Kalshi REST API
    2. Compare with internal fills ledger
    3. Compare with PositionMonitor state
    4. Detect and log mismatches
    5. Optionally auto-correct based on action policy

    Thread-safe: Uses lock for state mutations.
    """

    _instance: Optional[ContinuousReconciler] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> ContinuousReconciler:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._interval_seconds = 60  # Reconciliation interval
        self._tolerance_contracts = 1  # Tolerance for mismatch detection

        # Mismatch tracking
        self._mismatches: List[PositionMismatch] = []
        self._mismatch_callbacks: List[Callable[[PositionMismatch], None]] = []

        # Metrics
        self._reconciliation_count = 0
        self._last_reconciliation_time: Optional[float] = None
        self._mismatch_count = 0

        self._initialized = True
        logger.info("[CONTINUOUS-RECONCILER] Initialized")

    async def start(self) -> None:
        """Start the continuous reconciliation background task."""
        if self._running:
            logger.warning("[CONTINUOUS-RECONCILER] Already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._reconciliation_loop())
        logger.info("[CONTINUOUS-RECONCILER] Started background task")

    async def stop(self) -> None:
        """Stop the continuous reconciliation background task."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[CONTINUOUS-RECONCILER] Stopped background task")

    async def _reconciliation_loop(self) -> None:
        """Main reconciliation loop."""
        while self._running:
            try:
                await self._reconcile()
                await asyncio.sleep(self._interval_seconds)
            except asyncio.CancelledError:
                logger.info("[CONTINUOUS-RECONCILER] Reconciliation loop cancelled")
                break
            except Exception as e:
                logger.error(f"[CONTINUOUS-RECONCILER] Reconciliation error: {e}", exc_info=True)
                await asyncio.sleep(self._interval_seconds)

    async def _reconcile(self) -> None:
        """Perform a single reconciliation cycle."""
        self._reconciliation_count += 1
        self._last_reconciliation_time = _time.time()

        logger.info(
            f"[CONTINUOUS-RECONCILER] Starting reconciliation cycle #{self._reconciliation_count}"
        )

        try:
            # Fetch positions from Kalshi REST API
            exchange_positions = await self._fetch_exchange_positions()

            # Fetch positions from fills ledger
            ledger_positions = await self._fetch_ledger_positions()

            # Fetch positions from PositionMonitor
            monitor_positions = await self._fetch_monitor_positions()

            # Compare and detect mismatches
            mismatches = self._detect_mismatches(
                exchange_positions, ledger_positions, monitor_positions
            )

            # Process mismatches
            for mismatch in mismatches:
                self._mismatch_count += 1
                self._mismatches.append(mismatch)

                # Log mismatch
                logger.warning(
                    f"[CONTINUOUS-RECONCILER] Position mismatch detected: {mismatch.to_dict()}"
                )

                # Notify callbacks
                for callback in self._mismatch_callbacks:
                    try:
                        callback(mismatch)
                    except Exception as e:
                        logger.error(f"[CONTINUOUS-RECONCILER] Callback error: {e}", exc_info=True)

                # Apply action if not FLAG_ONLY
                if mismatch.action != ReconciliationAction.FLAG_ONLY:
                    await self._apply_action(mismatch)

            # Keep only recent mismatches (last 100)
            if len(self._mismatches) > 100:
                self._mismatches = self._mismatches[-100:]

            # Reconcile live UnifiedRiskManager exposure with the venue so
            # buy/sell fill tracking drift cannot accumulate into a phantom
            # CATEGORY_CAP / TOTAL_EXPOSURE block.  Use a long max_order_age
            # (1 hour) so GTC stop/bracket orders are not cancelled too early.
            try:
                from merid.event_venues.kalshi.kalshi_risk import reconcile_unified_risk_with_venue
                recon_result = await reconcile_unified_risk_with_venue(
                    max_order_age_seconds=3600.0,
                    category="crypto",
                )
                logger.info(
                    "[CONTINUOUS-RECONCILER] Unified risk reconcile: "
                    "confirmed_open_notional=$%.2f canceled=%d quarantined=%d",
                    recon_result.get("confirmed_open_notional_usd", 0.0),
                    len(recon_result.get("canceled_order_ids", [])),
                    len(recon_result.get("quarantined_order_ids", [])),
                )
            except Exception as e:
                logger.warning("[CONTINUOUS-RECONCILER] Unified risk reconcile failed: %s", e)

            logger.info(
                f"[CONTINUOUS-RECONCILER] Reconciliation cycle #{self._reconciliation_count} complete: "
                f"exchange_positions={len(exchange_positions)} "
                f"ledger_positions={len(ledger_positions)} "
                f"monitor_positions={len(monitor_positions)} "
                f"mismatches={len(mismatches)}"
            )

        except Exception as e:
            logger.error(f"[CONTINUOUS-RECONCILER] Reconciliation failed: {e}", exc_info=True)

    async def _fetch_exchange_positions(self) -> Dict[str, Dict[str, Any]]:
        """Fetch positions from Kalshi REST API."""
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            cache = get_position_cache()

            # Trigger a REST sync
            from merid.event_venues.kalshi.client import get_kalshi_client
            client = get_kalshi_client()
            positions = await client.get_positions()

            # Convert to dict by market_id (VenuePosition is a dataclass, not a dict).
            # CRITICAL 2026-08-13: `pos.size` is whole contracts; the canonical unit
            # for reconciliation and sync_from_rest is centi-contracts.
            return {pos.market_id: {
                "contracts": int(pos.size),
                "quantity_cc": int(Decimal(str(pos.size)) * Decimal("100")),
                "side": pos.outcome_id,
                "avg_price_cents": int(pos.average_entry_price * 100),  # Convert dollars to cents
            } for pos in positions}

        except Exception as e:
            logger.error(f"[CONTINUOUS-RECONCILER] Failed to fetch exchange positions: {e}")
            return {}

    async def _fetch_ledger_positions(self) -> Dict[str, Dict[str, Any]]:
        """Fetch positions from fills ledger."""
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            ledger = get_fills_ledger()

            # Compute net positions from ledger
            # compute_net_positions already returns {market_ticker: position_dict}
            net_positions = ledger.compute_net_positions(since_hours=24)

            # Re-key and validate by market_ticker so downstream reconciliation
            # never confuses the ticker key with the position record fields.
            return {
                pos["market_ticker"]: pos
                for pos in net_positions.values()
            }

        except Exception as e:
            logger.error(f"[CONTINUOUS-RECONCILER] Failed to fetch ledger positions: {e}")
            return {}

    async def _fetch_monitor_positions(self) -> Dict[str, Dict[str, Any]]:
        """Fetch positions from PositionMonitor."""
        try:
            from merid.position_management.position_monitor import get_position_monitor
            monitor = get_position_monitor()

            # Get all tracked positions
            positions = monitor.get_open_positions()

            # Convert to dict by market_id.
            # CRITICAL 2026-08-13: PositionMonitor uses whole contracts for display;
            # sync_from_rest needs centi-contracts.
            return {pos.market_id: {
                "contracts": pos.size,
                "quantity_cc": int(Decimal(str(pos.size)) * Decimal("100")),
                "side": pos.side.value,
                "avg_price_cents": pos.avg_entry_price_cents,
            } for pos in positions.values()}

        except Exception as e:
            logger.error(f"[CONTINUOUS-RECONCILER] Failed to fetch monitor positions: {e}")
            return {}

    def _detect_mismatches(
        self,
        exchange_positions: Dict[str, Dict[str, Any]],
        ledger_positions: Dict[str, Dict[str, Any]],
        monitor_positions: Dict[str, Dict[str, Any]],
    ) -> List[PositionMismatch]:
        """Detect position mismatches between sources."""
        mismatches: List[PositionMismatch] = []

        # Get all unique market IDs
        all_market_ids = set(exchange_positions.keys()) | set(ledger_positions.keys()) | set(monitor_positions.keys())

        for market_id in all_market_ids:
            exchange_pos = exchange_positions.get(market_id, {})
            ledger_pos = ledger_positions.get(market_id, {})
            monitor_pos = monitor_positions.get(market_id, {})

            # Extract contract counts for display and canonical centi-contracts for comparison.
            exchange_contracts = int(exchange_pos.get("contracts", 0))
            exchange_quantity_cc = int(exchange_pos.get("quantity_cc", exchange_contracts * 100))
            ledger_contracts = int(ledger_pos.get("contracts", 0))
            ledger_quantity_cc = int(ledger_pos.get("quantity_cc", ledger_contracts * 100))
            monitor_contracts = int(monitor_pos.get("contracts", 0))
            monitor_quantity_cc = int(monitor_pos.get("quantity_cc", monitor_contracts * 100))

            # Check for mismatches in canonical centi-contract units.
            tolerance_cc = self._tolerance_contracts * 100
            if abs(exchange_quantity_cc - ledger_quantity_cc) > tolerance_cc:
                mismatches.append(PositionMismatch(
                    market_id=market_id,
                    local_contracts=ledger_contracts,
                    exchange_contracts=exchange_contracts,
                    local_side=ledger_pos.get("side", "unknown"),
                    exchange_side=exchange_pos.get("side", "unknown"),
                    local_avg_price_cents=int(ledger_pos.get("avg_price_cents", 0)),
                    exchange_avg_price_cents=int(exchange_pos.get("avg_price_cents", 0)),
                    detected_at=datetime.now(timezone.utc),
                    action=ReconciliationAction.ACCEPT_EXCHANGE,  # Trust exchange
                    local_quantity_cc=ledger_quantity_cc,
                    exchange_quantity_cc=exchange_quantity_cc,
                ))

            if abs(exchange_quantity_cc - monitor_quantity_cc) > tolerance_cc:
                mismatches.append(PositionMismatch(
                    market_id=market_id,
                    local_contracts=monitor_contracts,
                    exchange_contracts=exchange_contracts,
                    local_side=monitor_pos.get("side", "unknown"),
                    exchange_side=exchange_pos.get("side", "unknown"),
                    local_avg_price_cents=int(monitor_pos.get("avg_price_cents", 0)),
                    exchange_avg_price_cents=int(exchange_pos.get("avg_price_cents", 0)),
                    detected_at=datetime.now(timezone.utc),
                    action=ReconciliationAction.ACCEPT_EXCHANGE,  # Trust exchange
                    local_quantity_cc=monitor_quantity_cc,
                    exchange_quantity_cc=exchange_quantity_cc,
                ))

        return mismatches

    async def _apply_action(self, mismatch: PositionMismatch) -> None:
        """Apply reconciliation action."""
        if mismatch.action == ReconciliationAction.ACCEPT_EXCHANGE:
            # Update local state to match exchange
            try:
                from merid.event_venues.kalshi.position_cache import get_position_cache
                cache = get_position_cache()

                # Force sync from REST to update local state.
                # CRITICAL 2026-08-13: Pass the canonical centi-contract quantity so
                # position_cache does not re-interpret display contracts as centi.
                await cache.sync_from_rest(
                    positions=[{
                        "market_id": mismatch.market_id,
                        "contracts": mismatch.exchange_contracts,
                        "quantity_cc": mismatch.exchange_quantity_cc,
                        "side": mismatch.exchange_side,
                        "avg_price_cents": mismatch.exchange_avg_price_cents,
                    }],
                    force=True,
                )

                logger.info(
                    f"[CONTINUOUS-RECONCILER] Applied ACCEPT_EXCHANGE action for {mismatch.market_id}"
                )

            except Exception as e:
                logger.error(f"[CONTINUOUS-RECONCILER] Failed to apply ACCEPT_EXCHANGE: {e}")

        elif mismatch.action == ReconciliationAction.ACCEPT_LOCAL:
            # Keep local state, log only
            logger.info(
                f"[CONTINUOUS-RECONCILER] Applied ACCEPT_LOCAL action for {mismatch.market_id}"
            )

        # FLAG_ONLY does nothing

    def register_mismatch_callback(self, callback: Callable[[PositionMismatch], None]) -> None:
        """Register a callback to be notified of mismatches."""
        self._mismatch_callbacks.append(callback)
        logger.info(f"[CONTINUOUS-RECONCILER] Registered mismatch callback: {callback.__name__}")

    def get_status(self) -> Dict[str, Any]:
        """Get reconciliation status."""
        return {
            "running": self._running,
            "reconciliation_count": self._reconciliation_count,
            "last_reconciliation_time": self._last_reconciliation_time,
            "mismatch_count": self._mismatch_count,
            "recent_mismatches": [m.to_dict() for m in self._mismatches[-10:]],
            "interval_seconds": self._interval_seconds,
        }


# Singleton accessor
def get_continuous_reconciler() -> ContinuousReconciler:
    """Get the continuous reconciler singleton."""
    return ContinuousReconciler()
