"""Simple in-memory order store used for tests and early development."""

from __future__ import annotations

from typing import Dict, Optional
import time

_ORDERS: Dict[str, Dict] = {}
_IDEMPOTENCY_INDEX: Dict[str, str] = {}


def save_order(order: Dict) -> Dict:
    order_id = order.get("id")
    if not order_id:
        raise ValueError("order must have an 'id' field")
    order["created_at"] = time.time()
    _ORDERS[order_id] = order
    ik = order.get("idempotency_key")
    if ik:
        _IDEMPOTENCY_INDEX[ik] = order_id
    return order


def get_order(order_id: str) -> Optional[Dict]:
    return _ORDERS.get(order_id)


def find_by_idempotency_key(key: str) -> Optional[Dict]:
    oid = _IDEMPOTENCY_INDEX.get(key)
    if not oid:
        return None
    return get_order(oid)


def update_order(order_id: str, updates: Dict) -> Optional[Dict]:
    o = _ORDERS.get(order_id)
    if not o:
        return None
    o.update(updates)
    return o


def clear_store() -> None:
    _ORDERS.clear()
    _IDEMPOTENCY_INDEX.clear()


def count_open_orders() -> int:
    """Return the number of open (non-filled, non-cancelled) orders.

    This is a helper used by pre-trade checks to enforce max_open_orders.
    """
    return sum(1 for o in _ORDERS.values() if o.get("status") not in ("filled", "cancelled"))
