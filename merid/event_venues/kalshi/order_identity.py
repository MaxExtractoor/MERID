"""Canonical order identity finalization.

Allocates and persists durable, immutable ``(order_attempt_id, client_order_id)``
pairs before any network call. Enforces the invariant that a single
``client_order_id`` corresponds to a single ``order_attempt_id`` and a single
request fingerprint.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from merid.event_venues.kalshi.order_router import OrderIntent

from utils.logger import get_logger

from merid.event_venues.kalshi.order_attempt_store import (
    OrderAttemptRecord,
    OrderAttemptStore,
)

logger = get_logger("merid.event_venues.kalshi.order_identity")


class OrderIdentityError(Exception):
    """Raised when the order-identity contract is violated."""


_ORDER_STATUS = "PERSISTED"


def resolve_exit_parent_id(position: Any) -> str:
    """Return the most authoritative durable parent id for an exit.

    The canonical parent is the entry fill id.  For pre-Fix-3 positions or
    REST-synced fills that lack a fill id, fall back through the entry order
    id, the entry client order id, and finally the local position id.  Using
    the same resolver everywhere makes exit client order ids deterministic and
    backward-compatible with positions created before ``entry_fill_id`` was
    promoted to canonical.
    """
    parent = (
        getattr(position, "entry_fill_id", None)
        or getattr(position, "entry_order_id", None)
        or getattr(position, "client_order_id", None)
        or getattr(position, "entry_intent_id", None)
        or getattr(position, "position_id", None)
    )
    return str(parent or "unknown")


def _resolve_tif(intent: "OrderIntent") -> str:
    """Return canonical lowercase TIF without mutating intent."""
    return (getattr(intent, "time_in_force", None) or "gtc").lower()


def derive_exit_client_order_id(
    entry_fill_id: str, exit_reason: str, resubmit_count: int = 0
) -> str:
    """Return a stable, deterministic client order id for an exit.

    The id is derived from the authoritative parent ``entry_fill_id`` and
    ``exit_reason`` so it is stable across retries and restarts and does not
    depend on an in-memory record.  The resubmit count is included in the
    derivation so each resubmit attempts a distinct client order id when the
    exchange requires a fresh idempotency key (the unresolved-in-flight path
    takes precedence, so this only applies to explicit new attempts).
    """
    if not entry_fill_id or not exit_reason:
        return f"exit_{uuid.uuid4().hex[:20]}"
    payload = (
        f"client_order_id:{entry_fill_id}:{str(exit_reason).lower()}:{resubmit_count}".encode("utf-8")
    )
    digest = hashlib.sha256(payload).hexdigest()[:20]
    return f"exit_{digest}"


def derive_exit_intent_id(entry_fill_id: str, exit_reason: str) -> str:
    """Return a stable, deterministic intent id for an exit decision.

    This is the public counterpart to the auto-generated UUID on ``OrderIntent``;
    it lets the exit-decision audit record, the ``OrderIntent``, and downstream
    ``fills_ledger`` resolve to the same durable identity.
    """
    if not entry_fill_id or not exit_reason:
        return f"intent_exit_{uuid.uuid4().hex[:20]}"
    payload = f"intent_id:{entry_fill_id}:{str(exit_reason).lower()}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:20]
    return f"intent_exit_{digest}"


def _compute_fingerprint(intent: "OrderIntent") -> str:
    """Compute a canonical, side-effect-free fingerprint of the order request.

    The fingerprint captures the immutable economics and provenance of an
    order attempt. Any material change to these fields requires a new attempt.
    """
    count_fp = getattr(intent, "count_fp", None)
    if count_fp is None:
        try:
            count_fp = Decimal(getattr(intent, "count", 0))
        except Exception:
            count_fp = Decimal("0")
    else:
        count_fp = Decimal(count_fp)

    payload = {
        "ticker": str(getattr(intent, "ticker", "")),
        "action": str(getattr(intent, "action", "")).lower(),
        "side": str(getattr(intent, "side", "")).lower(),
        "price_cents": int(getattr(intent, "price_cents", 0)),
        "count_fp": f"{count_fp:.6f}",
        "tif": _resolve_tif(intent),
        "reduce_only": bool(getattr(intent, "reduce_only", False)),
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _new_ids() -> tuple[str, str]:
    order_attempt_id = f"oa_{uuid.uuid4().hex}"
    client_order_id = f"merid_{uuid.uuid4().hex[:20]}"
    return order_attempt_id, client_order_id


def _build_record(
    order_attempt_id: str,
    client_order_id: str,
    intent: "OrderIntent",
    fingerprint: str,
    *,
    replaces_order_attempt_id: Optional[str] = None,
    extra_payload: Optional[Dict[str, Any]] = None,
) -> OrderAttemptRecord:
    decision_id = (
        getattr(intent, "decision_id", None)
        or getattr(intent, "client_tag", None)
        or getattr(intent, "intent_id", None)
    )
    client_tag = getattr(intent, "client_tag", None) or getattr(
        intent, "intent_id", None
    )
    run_id = getattr(intent, "run_id", None)
    process_id = getattr(intent, "process_id", None)
    intent_id = getattr(intent, "intent_id", None) or client_order_id
    now = time.time()
    payload = extra_payload or {}
    payload["fingerprint_source"] = "finalize_order_identity"
    return OrderAttemptRecord(
        order_attempt_id=order_attempt_id,
        client_order_id=client_order_id,
        decision_id=decision_id,
        replaces_order_attempt_id=replaces_order_attempt_id,
        intent_id=intent_id,
        client_tag=client_tag,
        run_id=run_id,
        process_id=process_id,
        fingerprint=fingerprint,
        status=_ORDER_STATUS,
        created_at=now,
        updated_at=now,
        payload_json=json.dumps(payload, default=str, sort_keys=True),
    )


def finalize_order_identity(
    intent: "OrderIntent",
    store: Optional[OrderAttemptStore] = None,
) -> "OrderIntent":
    """Allocate or recover the canonical ``(order_attempt_id, client_order_id)`` pair.

    This must be called exactly once before any network request and only before
    the first request. Retries must reuse the same ``OrderIntent`` (or an object
    carrying the same ``order_attempt_id`` / ``client_order_id``) without
    changing the economic fingerprint.

    Raises ``OrderIdentityError`` if the identity is inconsistent or if a
    ``client_order_id`` already belongs to a different attempt.
    """
    if store is None:
        store = OrderAttemptStore()

    existing_attempt_id = getattr(intent, "order_attempt_id", None)
    existing_coid = getattr(intent, "client_order_id", None)
    fingerprint = _compute_fingerprint(intent)

    if existing_coid and existing_attempt_id:
        # Re-entrant path. The stored record must match exactly.
        record = store.get_by_client_order_id(existing_coid)
        if record is None:
            # CRITICAL FIX (2026-08-24): Trusted callers such as the position-monitor
            # exit path may pre-allocate a deterministic client_order_id and a fresh
            # attempt id before the store has seen them.  Adopt the pre-supplied pair
            # rather than rejecting, so every outbound order carries a persisted
            # identity record from the same code path.
            logger.warning(
                "[ORDER-IDENTITY] Adopting pre-supplied client_order_id=%s order_attempt_id=%s without an existing store record",
                existing_coid,
                existing_attempt_id,
            )
            record = _build_record(existing_attempt_id, existing_coid, intent, fingerprint)
            store.persist_attempt(record)
            return intent
        if record.order_attempt_id != existing_attempt_id:
            logger.critical(
                "[ORDER-IDENTITY] coid/attempt mismatch: coid=%s store_attempt=%s intent_attempt=%s",
                existing_coid,
                record.order_attempt_id,
                existing_attempt_id,
            )
            raise OrderIdentityError("client_order_id / order_attempt_id mismatch")
        # NOTE: We intentionally do NOT re-verify the fingerprint on re-entry.
        # The router may reprice an order within the same attempt; that does not
        # create a new coid. A true replacement must call create_replacement_attempt.
        return intent

    if existing_coid and not existing_attempt_id:
        # Legacy / externally-supplied coid with no attempt record. This is an
        # identity violation unless the store already knows it. If the store
        # already knows it, recover the attempt. If not, reject rather than
        # silently minting a new idempotency key for the same coid.
        record = store.get_by_client_order_id(existing_coid)
        if record is not None:
            if record.fingerprint == fingerprint:
                logger.info(
                    "[ORDER-IDENTITY] Recovering order_attempt_id=%s from legacy client_order_id=%s",
                    record.order_attempt_id,
                    existing_coid,
                )
                intent.order_attempt_id = record.order_attempt_id
                return intent
            # The coid already exists with a different fingerprint (e.g., the
            # guard repriced the order or the decision tag changed). Do not reuse
            # it for a materially different order; fall through and mint a fresh
            # coid so the durable identity stays accurate.
            logger.warning(
                "[ORDER-IDENTITY] coid=%s exists with a different fingerprint; "
                "minting a new idempotency key instead of reusing a mismatched attempt",
                existing_coid,
            )
            existing_coid = None

        # Trusted callers (pre-trade gate, position-monitor exits) may have
        # reserved a deterministic client_order_id before reaching the router.
        # If the coid is still set (no existing store record, no mismatch), adopt
        # it by minting a matching order_attempt_id and persisting a PERSISTED
        # record so the durable identity layer stays authoritative.
        if existing_coid:
            logger.warning(
                "[ORDER-IDENTITY] Adopting pre-supplied client_order_id=%s without an attempt record",
                existing_coid,
            )
            order_attempt_id = f"oa_{uuid.uuid4().hex}"
            record = _build_record(order_attempt_id, existing_coid, intent, fingerprint)
            store.persist_attempt(record)
            intent.client_order_id = existing_coid
            intent.order_attempt_id = order_attempt_id
            intent.client_tag = existing_coid
            return intent

    # Normal path: fresh intent with no coid. Look for an unresolved in-flight
    # attempt with the same fingerprint (durable dedup) before minting a new one.
    now = time.time()
    for pending in store.get_by_fingerprint(fingerprint):
        age_s = now - pending.created_at
        # Only treat actively in-flight or very recently allocated (but not yet
        # submitted) records as duplicate. Acknowledged/filled/rejected orders
        # are terminal and need a fresh attempt. Stale (>60s) SUBMITTING records
        # are presumed dead and are not reused.
        if pending.status in ("SUBMITTING", "SUBMISSION_UNKNOWN") and age_s < 60.0:
            pass
        elif pending.status == "PERSISTED" and age_s < 30.0:
            pass
        else:
            continue

        logger.info(
            "[ORDER-IDENTITY] Reusing unresolved order_attempt_id=%s client_order_id=%s for matching fingerprint",
            pending.order_attempt_id,
            pending.client_order_id,
        )
        intent.client_order_id = pending.client_order_id
        intent.order_attempt_id = pending.order_attempt_id
        intent.client_tag = pending.client_order_id
        return intent

    order_attempt_id, client_order_id = _new_ids()
    record = _build_record(order_attempt_id, client_order_id, intent, fingerprint)
    store.persist_attempt(record)

    intent.client_order_id = client_order_id
    intent.order_attempt_id = order_attempt_id
    # During the transition, client_tag is kept in lock-step with the canonical
    # client_order_id so downstream code that predates order_attempt_id still uses
    # the durable idempotency key. It remains mutable metadata and may be
    # reconciled to decision_id once all consumers are migrated.
    intent.client_tag = client_order_id

    logger.info(
        "[ORDER-IDENTITY] Finalized order_attempt_id=%s client_order_id=%s intent_id=%s fingerprint=%s",
        order_attempt_id,
        client_order_id,
        getattr(intent, "intent_id", None),
        fingerprint,
    )
    return intent


def create_replacement_attempt(
    intent: "OrderIntent",
    replaced_order_attempt_id: str,
    store: Optional[OrderAttemptStore] = None,
) -> "OrderIntent":
    """Create a new attempt linked to a previous one (cancel-requote chains)."""
    if store is None:
        store = OrderAttemptStore()

    original = store.get_by_order_attempt_id(replaced_order_attempt_id)
    if original is None:
        raise OrderIdentityError(
            f"cannot replace unknown attempt {replaced_order_attempt_id}"
        )

    order_attempt_id, client_order_id = _new_ids()
    fingerprint = _compute_fingerprint(intent)
    record = _build_record(
        order_attempt_id,
        client_order_id,
        intent,
        fingerprint,
        replaces_order_attempt_id=original.order_attempt_id,
    )
    store.persist_attempt(record)

    intent.client_order_id = client_order_id
    intent.order_attempt_id = order_attempt_id
    return intent
