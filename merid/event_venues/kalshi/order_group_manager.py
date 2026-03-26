"""Kalshi Order Group Manager - Full lifecycle management with WS tracking.

Combines REST operations with WebSocket real-time updates for complete
order group state management.
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.ws import KalshiWebSocket
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_group_manager")


@dataclass
class OrderGroupState:
    """Order group state from WebSocket or REST update.

    Tracks limit usage and group lifecycle status.
    """
    order_group_id: str
    status: str = "active"
    contracts_limit: int = 0
    matched_contracts: int = 0
    used_contracts: int = 0
    subaccount: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrderGroupState":
        """Create OrderGroupState from dict (WS or REST payload)."""
        return cls(
            order_group_id=data.get("order_group_id", ""),
            status=data.get("status", "active"),
            contracts_limit=data.get("contracts_limit", 0),
            matched_contracts=data.get("matched_contracts", 0),
            used_contracts=data.get("used_contracts", 0),
            subaccount=data.get("subaccount", 0),
        )

    def can_add_contracts(self, new_contracts: int) -> bool:
        """Check if adding contracts stays within limit.

        Args:
            new_contracts: Number of contracts to add

        Returns:
            True if within limit or no limit set
        """
        if not self.is_active():
            return False
        if self.contracts_limit <= 0:
            return True  # No limit set
        return (self.used_contracts + new_contracts) <= self.contracts_limit

    @property
    def utilization_pct(self) -> float:
        """Percentage of contracts used vs. limit."""
        if self.contracts_limit <= 0:
            return 0.0
        return round((self.used_contracts / self.contracts_limit) * 100, 2)

    def record_new_order(self, contracts: int) -> None:
        """Optimistically record a new order against the group."""
        self.used_contracts += contracts

    def record_fill(self, matched_contracts: int) -> None:
        """Record filled contracts and reduce outstanding usage."""
        self.matched_contracts += matched_contracts
        self.used_contracts = max(0, self.used_contracts - matched_contracts)

    @property
    def remaining_contracts(self) -> int:
        """Remaining contracts before hitting limit."""
        if self.contracts_limit <= 0:
            return sys.maxsize  # No limit set — return sentinel max int
        return max(0, self.contracts_limit - self.used_contracts)

    def is_active(self) -> bool:
        """Check if group is active (not triggered/canceled)."""
        return self.status not in ("triggered", "canceled", "completed")


class OrderGroupRiskManager:
    """Tracks order group limit usage and provides risk checks.

    Combines REST polling with WS updates for accurate usage tracking.
    """

    def __init__(self, client: KalshiVenueClient):
        self.client = client
        self.groups: Dict[str, OrderGroupState] = {}
        self._ws_callback: Optional[Callable[[OrderGroupState], None]] = None

    def refresh_all(self) -> Dict[str, OrderGroupState]:
        """Refresh all order groups from REST API.

        Returns:
            Dict mapping group_id -> OrderGroupState
        """
        async def _refresh() -> Dict[str, OrderGroupState]:
            result = await self.client.get_order_groups(limit=200)
            if not result.success:
                raise RuntimeError(f"Failed to fetch groups: {result.error}")

            groups = result.data or []
            self.groups.clear()
            for og in groups:
                og_id = og.get("order_group_id") or og.get("id")
                if og_id:
                    self.groups[og_id] = OrderGroupState.from_dict(og)
            return dict(self.groups)

        try:
            loop = asyncio.get_running_loop()
            return asyncio.run_coroutine_threadsafe(_refresh(), loop).result(timeout=30)
        except RuntimeError:
            return asyncio.run(_refresh())

    def get_group(self, og_id: str) -> Optional[OrderGroupState]:
        """Get order group state (from cache or fetch from API).

        Args:
            og_id: Group ID

        Returns:
            OrderGroupState or None if not found
        """
        if og_id in self.groups:
            return self.groups[og_id]

        # Fetch from API
        import asyncio

        async def _fetch():
            result = await self.client.get_order_group(og_id)
            if not result.success:
                return None
            og = result.data or {}
            state = OrderGroupState.from_dict(og)
            self.groups[og_id] = state
            return state

        try:
            loop = asyncio.get_running_loop()
            return asyncio.run_coroutine_threadsafe(_fetch(), loop).result(timeout=30)
        except RuntimeError:
            return asyncio.run(_fetch())

    def can_add_contracts(self, og_id: str, new_contracts: int) -> bool:
        """Check if we can add contracts to this group.

        Args:
            og_id: Group ID
            new_contracts: Number of contracts to add

        Returns:
            True if within limit
        """
        state = self.groups.get(og_id)
        if not state:
            # Unknown group - refresh
            state = self.get_group(og_id)
            if not state:
                return False
        return state.can_add_contracts(new_contracts)

    def record_new_order(self, og_id: str, contracts: int) -> None:
        """Record a new order locally (optimistic update).

        Args:
            og_id: Group ID
            contracts: Number of contracts in the order
        """
        state = self.groups.get(og_id)
        if state:
            state.record_new_order(contracts)

    def record_fill(self, og_id: str, matched_contracts: int) -> None:
        """Record a fill (updates matched contracts).

        Args:
            og_id: Group ID
            matched_contracts: Number of contracts filled
        """
        state = self.groups.get(og_id)
        if state:
            state.record_fill(matched_contracts)

    def apply_ws_update(self, msg: Dict[str, Any]) -> Optional[OrderGroupState]:
        """Apply WebSocket update to local state.

        Args:
            msg: WebSocket message dict

        Returns:
            Updated OrderGroupState or None
        """
        data = msg.get("data", msg)
        og_id = data.get("order_group_id") or data.get("group_id")
        if not og_id:
            return None

        # Update existing or create new
        if og_id in self.groups:
            state = self.groups[og_id]
            # Update fields from message
            if "status" in data:
                state.status = data["status"]
            if "contracts_limit" in data:
                state.contracts_limit = data["contracts_limit"]
            if "matched_contracts" in data:
                state.matched_contracts = data["matched_contracts"]
            if "used_contracts" in data:
                state.used_contracts = data["used_contracts"]
            if "subaccount" in data:
                state.subaccount = data["subaccount"]
        else:
            state = OrderGroupState.from_dict(data)
            self.groups[og_id] = state

        # Log triggered status
        if state.status == "triggered":
            logger.warning(f"Order group {og_id} triggered; usage exceeded limit.")

        # Call callback if set
        if self._ws_callback:
            try:
                self._ws_callback(state)
            except Exception as e:
                logger.error(f"Error in WS callback: {e}")

        return state

    def set_ws_callback(self, callback: Callable[[OrderGroupState], None]) -> None:
        """Set callback for WS updates.

        Args:
            callback: Function(state) called on each WS update
        """
        self._ws_callback = callback

    def get_usage_summary(self, og_id: str) -> Dict[str, Any]:
        """Get usage summary for a group.

        Args:
            og_id: Group ID

        Returns:
            Dict with limit, used, remaining, status
        """
        state = self.groups.get(og_id)
        if not state:
            return {
                "order_group_id": og_id,
                "status": "unknown",
                "contracts_limit": 0,
                "used_contracts": 0,
                "remaining": 0,
                "available": False,
            }

        return {
            "order_group_id": og_id,
            "status": state.status,
            "contracts_limit": state.contracts_limit,
            "used_contracts": state.used_contracts,
            "matched_contracts": state.matched_contracts,
            "remaining": state.remaining_contracts,
            "utilization_pct": state.utilization_pct,
            "available": state.is_active() and state.remaining_contracts > 0,
        }


class KalshiOrderGroupManager:
    """Manager for Kalshi order groups with REST + WS integration.

    Provides:
    - REST operations: create, update, trigger, reset, delete
    - WS tracking: real-time updates via order_group_updates channel
    - State management: local cache of group states
    - Auto-reconciliation: sync on trigger/delete events
    """

    def __init__(self, client: KalshiVenueClient, ws: Optional[KalshiWebSocket] = None):
        self.client = client
        self.ws = ws
        self.groups: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self._ws_task: Optional[asyncio.Task] = None
        self._watched_groups: Set[str] = set()
        self._on_triggered: Optional[Callable[[str, Dict[str, Any]], None]] = None

    # ═══════════════════════════════════════════════════════════════════════════
    # REST Operations
    # ═══════════════════════════════════════════════════════════════════════════

    async def create_group(
        self,
        name: str,
        max_cost_cents: int,
        subaccount: int = 0,
        contracts_limit: Optional[int] = None,
        contracts_limit_fp: Optional[str] = None,
    ) -> str:
        """Create a new order group.

        Args:
            name: Group name
            max_cost_cents: Maximum cost in cents
            subaccount: Subaccount number (default 0)
            contracts_limit: Contracts limit for rolling 15s window
            contracts_limit_fp: Contracts limit as string (e.g., "10.00")

        Returns:
            order_group_id
        """
        result = await self.client.create_order_group(name, max_cost_cents)
        if not result.success:
            raise RuntimeError(f"Failed to create order group: {result.error}")

        og_id = result.data
        self.groups[og_id]["id"] = og_id
        self.groups[og_id]["name"] = name
        self.groups[og_id]["max_cost"] = max_cost_cents

        # If we have contracts limit, update it
        if contracts_limit is not None or contracts_limit_fp is not None:
            await self.update_limit(og_id, contracts_limit, contracts_limit_fp)

        return og_id

    async def update_limit(
        self,
        order_group_id: str,
        contracts_limit: Optional[int] = None,
        contracts_limit_fp: Optional[str] = None,
    ) -> bool:
        """Update order group contracts limit.

        Args:
            order_group_id: Group ID to update
            contracts_limit: Contracts limit (int)
            contracts_limit_fp: Contracts limit as string

        Returns:
            True if successful
        """
        if contracts_limit is None and contracts_limit_fp is None:
            raise ValueError("Provide contracts_limit or contracts_limit_fp")

        result = await self.client.set_order_group_limit(
            group_id=order_group_id,
            contracts_limit=contracts_limit,
            contracts_limit_fp=contracts_limit_fp,
        )

        if not result.success:
            raise RuntimeError(f"Failed to update limit: {result.error}")

        # Update local cache
        if contracts_limit is not None:
            self.groups[order_group_id]["contracts_limit"] = contracts_limit
        if contracts_limit_fp is not None:
            self.groups[order_group_id]["contracts_limit_fp"] = contracts_limit_fp

        return True

    async def safe_update_limit(
        self,
        order_group_id: str,
        new_limit: int,
    ) -> bool:
        """Safely update limit with validation and clamping.

        Args:
            order_group_id: Group ID
            new_limit: Desired limit (will be clamped to [1, 1_000_000])

        Returns:
            True if successful
        """
        result = await self.client.safe_update_group_limit(order_group_id, new_limit)
        if not result.success:
            raise RuntimeError(f"Failed to update limit: {result.error}")

        self.groups[order_group_id]["contracts_limit"] = min(max(new_limit, 1), 1_000_000)
        return True

    async def reset(self, order_group_id: str) -> bool:
        """Reset order group matched contracts counter.

        Args:
            order_group_id: Group ID to reset

        Returns:
            True if successful
        """
        result = await self.client.reset_order_group_endpoint(order_group_id)
        if not result.success:
            raise RuntimeError(f"Failed to reset group: {result.error}")

        self.groups[order_group_id]["status"] = "active"
        return True

    async def trigger(self, order_group_id: str) -> bool:
        """Trigger order group (cancels all orders, blocks new ones).

        Args:
            order_group_id: Group ID to trigger

        Returns:
            True if successful
        """
        result = await self.client.trigger_order_group(order_group_id)
        if not result.success:
            raise RuntimeError(f"Failed to trigger group: {result.error}")

        self.groups[order_group_id]["status"] = "triggered"
        return True

    async def delete(self, order_group_id: str) -> bool:
        """Delete order group and cancel all its orders.

        Args:
            order_group_id: Group ID to delete

        Returns:
            True if deleted, False if not found
        """
        result = await self.client.delete_order_group(order_group_id)
        if not result.success:
            raise RuntimeError(f"Failed to delete group: {result.error}")

        deleted = result.data  # True if deleted, False if 404
        if deleted:
            self.groups.pop(order_group_id, None)
        return deleted

    async def refresh_all(self) -> Dict[str, Dict[str, Any]]:
        """Refresh all order groups from API.

        Returns:
            Dict mapping group_id -> group data
        """
        result = await self.client.get_order_groups(limit=200)
        if not result.success:
            raise RuntimeError(f"Failed to fetch groups: {result.error}")

        groups = result.data or []
        self.groups.clear()
        for og in groups:
            og_id = og.get("order_group_id") or og.get("id")
            if og_id:
                self.groups[og_id] = og

        return dict(self.groups)

    async def get_group(self, order_group_id: str) -> Optional[Dict[str, Any]]:
        """Get single order group details.

        Args:
            order_group_id: Group ID

        Returns:
            Group data or None if not found
        """
        # Check cache first
        if order_group_id in self.groups:
            return self.groups[order_group_id]

        # Fetch from API
        result = await self.client.get_order_group(order_group_id)
        if not result.success:
            return None

        data = result.data or {}
        self.groups[order_group_id].update(data)
        return data

    # ═══════════════════════════════════════════════════════════════════════════
    # WebSocket Tracking
    # ═══════════════════════════════════════════════════════════════════════════

    def set_on_triggered(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        """Set callback for when a group is triggered.

        Args:
            callback: Function(group_id, group_data) to call on trigger
        """
        self._on_triggered = callback

    def set_watched_groups(self, group_ids: List[str]) -> None:
        """Set which groups to watch for updates.

        Args:
            group_ids: List of group IDs to watch
        """
        self._watched_groups = set(group_ids)
        if self.ws:
            self.ws.set_watched_groups(group_ids)

    def is_group_watched(self, group_id: str) -> bool:
        """Check if a group is in the watched set.

        Args:
            group_id: Group ID

        Returns:
            True if watched (or no filter set)
        """
        if not self._watched_groups:
            return True
        return group_id in self._watched_groups

    async def start_ws(self) -> None:
        """Start WebSocket listener for order_group_updates."""
        if not self.ws:
            raise RuntimeError("WebSocket client not provided")

        await self.ws.subscribe_order_group_updates()
        self._ws_task = asyncio.create_task(self._ws_loop())
        logger.info("Started order group WebSocket tracking")

    async def stop_ws(self) -> None:
        """Stop WebSocket listener."""
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None
            logger.info("Stopped order group WebSocket tracking")

    async def _ws_loop(self) -> None:
        """WebSocket message loop."""
        if not self.ws:
            return

        # Use the WS client's listen method with our handler
        await self.ws.listen(self._handle_ws_message)

    async def _handle_ws_message(self, msg: Dict[str, Any]) -> None:
        """Handle WebSocket message.

        Args:
            msg: WebSocket message dict
        """
        channel = msg.get("channel") or msg.get("type")
        if channel != "order_group_updates":
            return

        data = msg.get("data", msg)
        og_id = data.get("order_group_id") or data.get("group_id")
        if not og_id:
            return

        # Check watched groups filter
        if not self.is_group_watched(og_id):
            return

        # Update local state
        self.groups[og_id].update(data)

        status = data.get("status")
        update_type = data.get("_update_type", "delta")

        logger.debug(f"Order group {og_id} update: status={status}, type={update_type}")

        # Handle triggered status
        if status == "triggered":
            logger.warning(f"Order group {og_id} triggered - orders auto-canceled")
            if self._on_triggered:
                try:
                    self._on_triggered(og_id, dict(self.groups[og_id]))
                except Exception as e:
                    logger.error(f"Error in on_triggered callback: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # Utility Methods
    # ═══════════════════════════════════════════════════════════════════════════

    def get_group_summary(self, order_group_id: str) -> Optional[Dict[str, Any]]:
        """Get summary of order group state.

        Args:
            order_group_id: Group ID

        Returns:
            Summary dict with key fields
        """
        data = self.groups.get(order_group_id)
        if not data:
            return None

        return {
            "order_group_id": order_group_id,
            "status": data.get("status"),
            "name": data.get("name"),
            "contracts_limit": data.get("contracts_limit"),
            "matched_contracts": data.get("matched_contracts"),
            "filled_cost": data.get("filled_cost"),
            "remaining_cost": data.get("remaining_cost"),
            "max_cost": data.get("max_cost"),
        }

    def get_all_groups(self) -> Dict[str, Dict[str, Any]]:
        """Get all cached order groups.

        Returns:
            Dict mapping group_id -> group data
        """
        return dict(self.groups)

    def is_group_active(self, order_group_id: str) -> bool:
        """Check if a group is active (not triggered/canceled).

        Args:
            order_group_id: Group ID

        Returns:
            True if group is active and can receive orders
        """
        data = self.groups.get(order_group_id, {})
        status = data.get("status", "active")
        return status not in ("triggered", "canceled", "completed")

    async def sync_on_trigger(self, order_group_id: str) -> Dict[str, Any]:
        """Sync portfolio state after group trigger.

        Fetches current orders and positions to ensure local state
        matches the exchange after auto-cancel.

        Args:
            order_group_id: Group ID that was triggered

        Returns:
            Dict with orders and positions
        """
        # Refresh the specific group
        await self.get_group(order_group_id)

        # Sync portfolio
        orders_result = await self.client.get_open_orders_result()
        positions_result = await self.client.get_positions_result()

        return {
            "group": self.groups.get(order_group_id, {}),
            "orders": orders_result.unwrap_or([]),
            "positions": positions_result.unwrap_or([]),
        }

    def update_from_ws(self, order_group_id: str, group_data: Dict[str, Any]) -> None:
        """Update order group cache from WebSocket real-time event.

        Args:
            order_group_id: Group ID
            group_data: Latest group data from WebSocket
        """
        if order_group_id in self.groups:
            # Update existing group with latest data
            self.groups[order_group_id].update(group_data)
        else:
            # Add new group from WS (shouldn't normally happen but handle it)
            self.groups[order_group_id] = OrderGroupState.from_dict(group_data)

        logger.debug(f"Order group {order_group_id} updated from WebSocket")


# Singleton accessor
_order_group_manager_instance: Optional[KalshiOrderGroupManager] = None


def get_order_group_manager() -> Optional[KalshiOrderGroupManager]:
    """Get the global order group manager singleton (if initialized)."""
    return _order_group_manager_instance


def set_order_group_manager(manager: KalshiOrderGroupManager) -> None:
    """Set the global order group manager singleton."""
    global _order_group_manager_instance
    _order_group_manager_instance = manager
