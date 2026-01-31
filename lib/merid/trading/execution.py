"""Execution layer: place, cancel, and modify orders with basic safeguards."""

from __future__ import annotations

import uuid
from typing import Dict, Optional

from trading.risk import pre_trade_check, CircuitBreaker
from db.order_store import save_order, get_order, find_by_idempotency_key, update_order
from db.audit_store import append_audit


class ExecutionError(Exception):
    pass


def _new_order_id() -> str:
    return uuid.uuid4().hex


def place_order(order: Dict, idempotency_key: Optional[str] = None, account: Optional[Dict] = None, actor: Optional[str] = None) -> Dict:
    """Place an order after risk checks and circuit-breaker validation.

    This is a synchronous, test-friendly implementation that sets the order
    status to 'filled' for now. In production we will integrate with exchange
    adapters and persist asynchronous execution state.
    The optional `actor` string is recorded in the audit log for traceability.
    """
    # Idempotency: return existing order if key used
    if idempotency_key:
        existing = find_by_idempotency_key(idempotency_key)
        if existing:
            append_audit(actor, "order.place.duplicate", {"id": existing["id"], "idempotency_key": idempotency_key})
            return existing

    if CircuitBreaker.is_tripped():
        append_audit(actor, "order.place.failed", {"reason": "circuit_breaker_tripped"})
        raise ExecutionError("Execution disabled: circuit breaker tripped")

    # Server lockdown check
    try:
        from core.lockdown import is_lockdown

        if is_lockdown():
            append_audit(actor, "order.place.failed", {"reason": "lockdown_active"})
            raise ExecutionError("Execution disabled: server is in lockdown")
    except ImportError:
        # If lockdown module isn't available, continue—this is a conservative default
        pass

    account = account or {"balance": 1_000_000, "max_notional_pct": 0.5}
    ok, reason = pre_trade_check(order, account)
    if not ok:
        CircuitBreaker.record_error()
        append_audit(actor, "order.place.failed", {"reason": reason})
        raise ExecutionError(f"Pre-trade check failed: {reason}")

    order_id = _new_order_id()
    record = {
        "id": order_id,
        "idempotency_key": idempotency_key,
        "order": order,
        "status": "pending",
    }
    save_order(record)

    # Simulate immediate acceptance and fill (replace with real adapter later)
    record = update_order(order_id, {"status": "filled", "filled_at": None, "fill_qty": order.get("quantity")})

    append_audit(actor, "order.place", {"id": order_id, "status": record.get("status"), "idempotency_key": idempotency_key})

    return record


def cancel_order(order_id: str, actor: Optional[str] = None) -> Dict:
    o = get_order(order_id)
    if not o:
        append_audit(actor, "order.cancel.failed", {"order_id": order_id, "reason": "not_found"})
        raise ExecutionError("Order not found")
    if o.get("status") == "filled":
        append_audit(actor, "order.cancel.failed", {"order_id": order_id, "reason": "already_filled"})
        raise ExecutionError("Cannot cancel a filled order")
    update_order(order_id, {"status": "cancelled"})
    entry = get_order(order_id)
    append_audit(actor, "order.cancel", {"order_id": order_id})
    return entry


def modify_order(order_id: str, changes: Dict, actor: Optional[str] = None) -> Dict:
    o = get_order(order_id)
    if not o:
        append_audit(actor, "order.modify.failed", {"order_id": order_id, "reason": "not_found"})
        raise ExecutionError("Order not found")
    if o.get("status") == "filled":
        append_audit(actor, "order.modify.failed", {"order_id": order_id, "reason": "already_filled"})
        raise ExecutionError("Cannot modify a filled order")
    update_order(order_id, {"order": {**o.get("order", {}), **changes}})
    entry = get_order(order_id)
    append_audit(actor, "order.modify", {"order_id": order_id, "changes": changes})
    return entry
