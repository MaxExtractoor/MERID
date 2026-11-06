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
    depend on an in-memory record.  The ``resubmit_count`` parameter is kept for
    API compatibility but is intentionally ignored: a timeout or lost ack is a
    retry of the same economic exit, not a new order.  Reusing the same
    client_order_id lets Kalshi's idempotency and the durable order-attempt
    store collapse the retry into the same exchange order.
    """
    if not entry_fill_id or not exit_reason:
        return f"exit_{uuid.uuid4().hex[:20]}"
    payload = (
        f"client_order_id:{entry_fill_id}:{str(exit_reason).lower()}".encode("utf-8")
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
    # Quote-feed provenance bound to the durable attempt record so an order can
    # be audited back to the feed that owned its entry quote.
    payload["quote_owner"] = getattr(intent, "quote_owner", None)
    payload["degraded_mode"] = bool(getattr(intent, "degraded_mode", False))
    payload["entry_or_exit"] = getattr(intent, "entry_or_exit", None)
    payload["reduce_only"] = getattr(intent, "reduce_only", None)
    # 2026-10-06: persist the requested order parameters readably.  The
    # fingerprint hashes them but is opaque; the attempt row must answer
    # "what was actually submitted" (e.g. 3-contract sizing vs 1-contract
    # fill) without replaying logs.
    try:
        _count_fp = getattr(intent, "count_fp", None)
        if _count_fp is None:
            _count_fp = Decimal(getattr(intent, "count", 0) or 0)
        else:
            _count_fp = Decimal(_count_fp)
    except Exception:
        _count_fp = Decimal("0")
    payload["order"] = {
        "ticker": str(getattr(intent, "ticker", "") or ""),
        "action": str(getattr(intent, "action", "") or "").lower(),
        "side": str(getattr(intent, "side", "") or "").lower(),
        "price_cents": int(getattr(intent, "price_cents", 0) or 0),
        "count_fp": f"{_count_fp:.6f}",
        "tif": _resolve_tif(intent),
        "decision_lane": getattr(intent, "decision_lane", None),
        "liquidity_role": getattr(intent, "liquidity_role", None),
    }
    # 2026-11-06 (payload schema v2): the attempt row previously preserved only
    # generic diagnostic economics (canonical gross edge / taker-basis net_ev),
    # which read as "EV gate ALLOWS net_ev<0" on bounded-lane admissions.  The
    # block below records the route-specific economics that actually authorized
    # the order, plus the authority that enforced them, so an audit never has
    # to reconstruct admitting EV from surrounding log lines.  All *_cents /
    # *_cents_per_contract fields are per-contract unless suffixed _order.
    # Missing inputs stay None — never backfilled to zero.
    payload["payload_schema_version"] = "2"
    try:
        _pi = getattr(intent, "probability_inputs", None) or {}
        _p_sel = _pi.get("p_selected")
        _px_c = getattr(intent, "price_cents", None)
        _lane = getattr(intent, "decision_lane", None)
        _bounded = bool(_lane) or bool(
            getattr(intent, "threshold_cell_id", None)
        ) or bool(getattr(intent, "provisional_cell_id", None))
        _role = getattr(intent, "liquidity_role", None)
        _post_only = getattr(intent, "post_only", None)
        _basis = (
            "bid" if (_role == "maker" or _post_only)
            else ("ask" if _role == "taker" else None)
        )
        try:
            from merid.event_venues.kalshi.order_router import (
                _execution_contract,
            )
            _contract = dict(_execution_contract(intent) or {})
        except Exception:
            _contract = {}
        try:
            from merid.prediction.current_build_provisional import (
                current_build_sha,
            )
            _bsha = getattr(intent, "build_sha", None) or current_build_sha()
        except Exception:
            _bsha = getattr(intent, "build_sha", None)
        _gross_c = (
            round(float(_p_sel) * 100.0 - float(_px_c), 4)
            if (_p_sel is not None and _px_c is not None)
            else None
        )
        payload["build_sha"] = _bsha
        payload["admitting_economics"] = {
            "units": "cents_per_contract",
            "admitting_authority": (
                "bounded_lane" if _bounded else "generic_gate"
            ),
            "admitting_lane": _lane,
            "admission_owner": getattr(intent, "admission_owner", None),
            "threshold_cell_id": getattr(intent, "threshold_cell_id", None),
            "provisional_cell_id": getattr(intent, "provisional_cell_id", None),
            "admitting_route": _contract.get("admission_lane") or _role,
            "resolved_execution_mode": _contract.get("resolved_execution_mode"),
            "price_basis": _basis,
            "liquidity_role": _role,
            "post_only": _post_only,
            "time_in_force": getattr(intent, "time_in_force", None),
            "selected_probability": _p_sel,
            "probability_model": _pi.get("model"),
            "p_yes_calibrated": _pi.get("p_yes_calibrated"),
            "p_no_calibrated": _pi.get("p_no_calibrated"),
            "entry_price_cents": _px_c,
            "gross_edge_cents_per_contract": _gross_c,
            "candidate_ev_net_cents_per_contract": getattr(
                intent, "ev_net_cents", None
            ),
            "entry_fee_cents_per_contract": getattr(intent, "fee_cents", None),
            "slippage_cents_per_contract": getattr(
                intent, "slippage_cents", None
            ),
            "all_in_cost_cents": getattr(intent, "all_in_cost_cents", None),
            "min_required_edge": getattr(intent, "min_required_edge", None),
            "economic_cap_cents": _contract.get("economic_cap"),
            "chase_cap_cents": _contract.get("chase_cap"),
            "time_to_expiry_seconds": getattr(
                intent, "time_to_expiry_seconds", None
            ),
            "quote_owner": getattr(intent, "quote_owner", None),
            "degraded_mode": bool(getattr(intent, "degraded_mode", False)),
            "policy_epoch": getattr(intent, "policy_epoch", None),
            "directional_regime": getattr(intent, "directional_regime", None),
            "snapshot_ts": getattr(intent, "snapshot_ts", None),
            "decision_id": getattr(intent, "decision_id", None),
            "exchange_index": getattr(intent, "exchange_index", None),
        }
        # Generic diagnostics carried on the intent (mid/canonical basis) —
        # explicitly marked non-authoritative whenever a bounded lane or cell
        # admitted the candidate under its own economics.
        payload["generic_economics"] = {
            "units": "diagnostic_mixed",
            "edge_net_of_fees_pct": getattr(intent, "edge_net_of_fees_pct", None),
            "estimated_fee_cents": getattr(intent, "estimated_fee_cents", None),
            "authoritative": not _bounded,
        }
        payload["generic_economics_authoritative"] = not _bounded
    except Exception:
        # Schema-v2 fields are observability-only; never fail identity
        # finalization over them.
        payload.setdefault("payload_schema_version", "2")
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
            # Reuse the durable attempt when the caller has explicitly supplied
            # the same client_order_id AND the intent matches the stored record.
            # The intent_id is the authoritative link for retries/reprices of the
            # same exit (it is derived from the parent fill and reason and is
            # stable across resubmits); the fingerprint may legitimately drift
            # when the exit guard reprices between attempts.  Mismatched intent_id
            # means the coid is being recycled for a different order, which is
            # disallowed.
            record_intent_id = record.intent_id
            caller_intent_id = getattr(intent, "intent_id", None)
            if record_intent_id and caller_intent_id and record_intent_id == caller_intent_id:
                if record.status in ("FILLED", "REJECTED", "CANCELED"):
                    # The stored attempt is terminal — its client_order_id is
                    # permanently consumed by the venue (a resubmit 409s with
                    # order_already_exists).  The same economic intent must
                    # mint a fresh idempotency key, never rebind the dead one.
                    logger.info(
                        "[ORDER-IDENTITY] Stored attempt for intent_id=%s is terminal "
                        "(status=%s); minting fresh client_order_id instead of "
                        "reusing %s",
                        caller_intent_id,
                        record.status,
                        existing_coid,
                    )
                    existing_coid = None
                else:
                    logger.info(
                        "[ORDER-IDENTITY] Reusing client_order_id=%s order_attempt_id=%s for same intent_id=%s",
                        existing_coid,
                        record.order_attempt_id,
                        caller_intent_id,
                    )
                    intent.order_attempt_id = record.order_attempt_id
                    return intent
            if (
                record.fingerprint == fingerprint
                and record.status not in ("FILLED", "REJECTED", "CANCELED")
            ):
                logger.info(
                    "[ORDER-IDENTITY] Recovering order_attempt_id=%s from legacy client_order_id=%s",
                    record.order_attempt_id,
                    existing_coid,
                )
                intent.order_attempt_id = record.order_attempt_id
                return intent
            # The coid already belongs to a different order (different intent_id
            # and different economic fingerprint), or its attempt is terminal
            # and the key is permanently consumed. Do not reuse it.
            logger.warning(
                "[ORDER-IDENTITY] coid=%s belongs to a different order; "
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
        # An acknowledged or possibly submitted order remains an owner until
        # authoritative reconciliation, regardless of its age.
        if pending.status in ("SUBMITTING", "SUBMISSION_UNKNOWN", "ACKNOWLEDGED"):
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
