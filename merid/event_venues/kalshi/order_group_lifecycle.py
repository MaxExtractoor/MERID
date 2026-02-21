"""Order Group Lifecycle Manager — Integration hooks for main trading loop.

Provides lifecycle management for order groups including:
- Pre-trade validation hooks
- Post-trade reconciliation
- Triggered group handling
- Periodic sync with REST API
- Health monitoring
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.order_group_manager import (
    KalshiOrderGroupManager,
    OrderGroupRiskManager,
    OrderGroupState,
)
from merid.event_venues.kalshi.order_router import handle_order_group_triggered
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_group_lifecycle")


@dataclass
class LifecycleConfig:
    """Configuration for order group lifecycle management."""
    sync_interval_seconds: float = 60.0  # REST sync interval
    health_check_interval_seconds: float = 30.0
    auto_cancel_on_trigger: bool = True
    block_new_orders_on_triggered: bool = True
    max_sync_retries: int = 3


@dataclass
class LifecycleState:
    """Current lifecycle state for monitoring."""
    last_sync_ts: Optional[str] = None
    last_health_check_ts: Optional[str] = None
    total_groups_tracked: int = 0
    active_groups: int = 0
    triggered_groups: Set[str] = field(default_factory=set)
    errors: List[Dict[str, Any]] = field(default_factory=list)


class OrderGroupLifecycleManager:
    """Manages order group lifecycle hooks for main trading loop.

    Integrates with the trading loop to provide:
    - Pre-flight order validation against group limits
    - Real-time WS monitoring and auto-cancel
    - Periodic REST sync for consistency
    - Health checks and alerting
    """

    def __init__(
        self,
        client: KalshiVenueClient,
        config: Optional[LifecycleConfig] = None,
    ):
        self.client = client
        self.config = config or LifecycleConfig()
        self.state = LifecycleState()
        self._manager: Optional[KalshiOrderGroupManager] = None
        self._risk_manager: Optional[OrderGroupRiskManager] = None
        self._sync_task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None
        self._running = False
        self._on_triggered_callbacks: List[Callable[[str, Dict], None]] = []

    # ═══════════════════════════════════════════════════════════════════════
    # Lifecycle Control
    # ═══════════════════════════════════════════════════════════════════════

    async def start(self) -> None:
        """Start lifecycle management tasks."""
        if self._running:
            return

        self._running = True

        # Initialize managers
        self._manager = KalshiOrderGroupManager(self.client)
        self._risk_manager = OrderGroupRiskManager(self.client)

        # Set up triggered callback
        self._manager.set_on_triggered(self._on_group_triggered)

        # Start WebSocket listener
        await self._manager.start_ws()

        # Start background tasks
        self._sync_task = asyncio.create_task(self._sync_loop())
        self._health_task = asyncio.create_task(self._health_loop())

        logger.info("OrderGroupLifecycleManager started")

    async def stop(self) -> None:
        """Stop lifecycle management tasks."""
        self._running = False

        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            self._sync_task = None

        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None

        if self._manager:
            await self._manager.stop_ws()

        logger.info("OrderGroupLifecycleManager stopped")

    # ═══════════════════════════════════════════════════════════════════════
    # Trading Loop Hooks
    # ═══════════════════════════════════════════════════════════════════════

    def can_place_order(
        self,
        order_group_id: Optional[str],
        contracts: int,
    ) -> tuple[bool, Optional[str]]:
        """Pre-flight check: Can this order be placed?

        Args:
            order_group_id: Target order group (if any)
            contracts: Number of contracts to add

        Returns:
            (allowed, reason) tuple
        """
        if not order_group_id:
            return True, None

        if not self._risk_manager:
            return True, None  # No risk manager = pass through

        # Check if group is active
        group = self._risk_manager.groups.get(order_group_id)
        if not group:
            return False, f"order_group_not_found:{order_group_id}"

        if not group.is_active():
            return False, f"order_group_not_active:{order_group_id}:status={group.status}"

        if not group.can_add_contracts(contracts):
            return (
                False,
                f"order_group_limit_exceeded:{order_group_id}:"
                f"used={group.used_contracts}:limit={group.contracts_limit}"
            )

        return True, None

    def record_order_placed(
        self,
        order_group_id: Optional[str],
        contracts: int,
    ) -> None:
        """Record order placement for tracking.

        Args:
            order_group_id: Order group ID (if any)
            contracts: Number of contracts
        """
        if not order_group_id or not self._risk_manager:
            return

        self._risk_manager.record_new_order(order_group_id, contracts)
        logger.debug(f"Recorded {contracts} contracts to group {order_group_id}")

    def record_fill(
        self,
        order_group_id: Optional[str],
        matched_contracts: int,
    ) -> None:
        """Record a fill for usage tracking.

        Args:
            order_group_id: Order group ID (if any)
            matched_contracts: Number of contracts filled
        """
        if not order_group_id or not self._risk_manager:
            return

        self._risk_manager.record_fill(order_group_id, matched_contracts)

    # ═══════════════════════════════════════════════════════════════════════
    # Callbacks & Events
    # ═══════════════════════════════════════════════════════════════════════

    def _on_group_triggered(self, group_id: str, group_data: Dict[str, Any]) -> None:
        """Internal handler for triggered groups."""
        logger.warning(f"LifecycleManager: Group {group_id} triggered")

        self.state.triggered_groups.add(group_id)

        # Auto-cancel if enabled
        if self.config.auto_cancel_on_trigger:
            _task = asyncio.create_task(
                handle_order_group_triggered(group_id, group_data),
                name=f"og-triggered-{group_id}",
            )
            _task.add_done_callback(
                lambda t: logger.error(
                    "handle_order_group_triggered failed for %s: %s", group_id, t.exception()
                ) if not t.cancelled() and t.exception() else None
            )

        # Call registered callbacks
        for callback in self._on_triggered_callbacks:
            try:
                callback(group_id, group_data)
            except Exception as e:
                logger.error(f"Error in triggered callback: {e}")

    def on_triggered(
        self,
        callback: Callable[[str, Dict[str, Any]], None],
    ) -> None:
        """Register callback for triggered groups.

        Args:
            callback: Function(group_id, group_data) to call
        """
        self._on_triggered_callbacks.append(callback)

    # ═══════════════════════════════════════════════════════════════════════
    # Background Tasks
    # ═══════════════════════════════════════════════════════════════════════

    async def _sync_loop(self) -> None:
        """Periodic REST sync for consistency."""
        while self._running:
            try:
                await self._sync_with_rest()
                self.state.last_sync_ts = datetime.now(timezone.utc).isoformat()
            except Exception as e:
                logger.error(f"Sync loop error: {e}")
                self.state.errors.append({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "type": "sync_error",
                    "error": str(e),
                })

            await asyncio.sleep(self.config.sync_interval_seconds)

    async def _sync_with_rest(self) -> None:
        """Sync state with REST API."""
        if not self._risk_manager:
            return

        # Refresh all groups from REST
        self._risk_manager.refresh_all()

        # Update state counts
        self.state.total_groups_tracked = len(self._risk_manager.groups)
        self.state.active_groups = sum(
            1 for g in self._risk_manager.groups.values() if g.is_active()
        )

        logger.debug(
            f"Synced {self.state.total_groups_tracked} groups, "
            f"{self.state.active_groups} active"
        )

    async def _health_loop(self) -> None:
        """Periodic health checks."""
        while self._running:
            try:
                await self._check_health()
                self.state.last_health_check_ts = datetime.now(timezone.utc).isoformat()
            except Exception as e:
                logger.error(f"Health check error: {e}")

            await asyncio.sleep(self.config.health_check_interval_interval_seconds)

    async def _check_health(self) -> None:
        """Check order group health."""
        if not self._manager:
            return

        # Check for stale data
        all_groups = self._manager.get_all_groups()

        for group_id, group in all_groups.items():
            status = group.get("status", "unknown")

            # Alert on long-triggered groups that haven't been reset
            if status == "triggered" and group_id not in self.state.triggered_groups:
                logger.warning(f"New triggered group detected: {group_id}")
                self.state.triggered_groups.add(group_id)

    # ═══════════════════════════════════════════════════════════════════════
    # Query Methods
    # ═══════════════════════════════════════════════════════════════════════

    def get_group_summary(self, group_id: str) -> Optional[Dict[str, Any]]:
        """Get summary of an order group."""
        if not self._manager:
            return None
        return self._manager.get_group_summary(group_id)

    def get_all_groups(self) -> Dict[str, Dict[str, Any]]:
        """Get all tracked order groups."""
        if not self._manager:
            return {}
        return self._manager.get_all_groups()

    def get_usage_summary(self, group_id: str) -> Dict[str, Any]:
        """Get usage summary for a group."""
        if not self._risk_manager:
            return {"error": "Risk manager not initialized"}
        return self._risk_manager.get_usage_summary(group_id)

    def get_lifecycle_state(self) -> Dict[str, Any]:
        """Get current lifecycle state for monitoring."""
        return {
            "running": self._running,
            "last_sync": self.state.last_sync_ts,
            "last_health_check": self.state.last_health_check_ts,
            "total_groups": self.state.total_groups_tracked,
            "active_groups": self.state.active_groups,
            "triggered_groups": list(self.state.triggered_groups),
            "recent_errors": self.state.errors[-10:],  # Last 10 errors
        }

    async def refresh_group(self, group_id: str) -> Optional[OrderGroupState]:
        """Force refresh a specific group from REST API."""
        if not self._risk_manager:
            return None
        return self._risk_manager.get_group(group_id)
