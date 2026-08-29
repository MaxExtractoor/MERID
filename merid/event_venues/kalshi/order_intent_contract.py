"""Canonical order-intent contract and validation for Kalshi execution.

This module defines the single, immutable order-intent object that every
proposed trade must pass through before it is submitted to the exchange.  It
collapses the four raw Kalshi order forms (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
into signed-YES centi-contracts and enforces the containment invariants from
AGENTS.md:

- One open inventory unit per ticker/market.
- No position flips in a single action.
- A sell action may never produce a negative YES position unless
  ``allow_short=True``.
- Exits must be validated against a fresh exchange position snapshot.
- Predicted PnL must not exceed the configured adverse-PnL budget.

Usage::

    from merid.event_venues.kalshi.order_intent_contract import (
        CanonicalOrderIntent,
        normalize_order,
        validate_canonical_intent,
    )

    canonical = normalize_order(intent, exchange_position_cc=100)
    validate_canonical_intent(canonical, exchange_position_cc=100)
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import threading
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from merid.event_venues.kalshi.binary_price_space import (
    canonical_outcome_side,
    normalize_rest_position,
    parse_kalshi_side,
    to_kalshi_side,
    to_signed_yes_exposure,
    yes_delta,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_intent_contract")


# Source markers that unambiguously identify a close order.
EXIT_SOURCE_MARKERS: set[str] = {
    "take_profit",
    "stop_loss",
    "micro_scalp",
    "exit",
    "close",
    "ratchet",
    "trim",
    "scale_out",
    "hedge",
    "hedge_engine",
    "offset_hedging",
    "position_monitor_exit",
    "resting_bracket",
    "bracket",
}


class OrderIntentValidationError(ValueError):
    """An order intent violates a non-negotiable execution invariant."""


# ── Protective-exit gate and per-ticker entry idempotency (2026-08-16) ───────
#
# Entries may not open while protective (stop-loss) exits cannot be
# submitted.  This is a fail-closed kill switch: stop submission defaults to
# off, so entries default to blocked until
# ``MERID_ENABLE_STOP_CANDIDATE_SUBMISSION=true`` is set after replay tests
# pass.  ``MERID_ALLOW_UNPROTECTED_ENTRIES=1`` is an explicit ops override.


def protective_exits_enabled() -> bool:
    """True when stop-loss candidates can actually be submitted as orders."""
    try:
        from merid.event_venues.kalshi.stop_candidate import stop_submission_enabled

        return bool(stop_submission_enabled())
    except Exception:
        return False


def _unprotected_entries_allowed() -> bool:
    return os.getenv("MERID_ALLOW_UNPROTECTED_ENTRIES", "").lower() in ("1", "true", "yes")


def _entry_dedup_enabled() -> bool:
    return os.getenv("MERID_ENTRY_IDEMPOTENCY_ENABLED", "1").lower() in ("1", "true", "yes")


def _entry_dedup_ttl_seconds() -> int:
    """Window TTL for accepted/submitted entry records."""
    try:
        return int(os.getenv("MERID_ENTRY_IDEMPOTENCY_TTL_SECONDS", "900"))
    except (TypeError, ValueError):
        return 900


def _pre_submit_stale_ttl_seconds() -> float:
    """TTL after which a pre-submit (no order_id, no execution) record is stale.

    This bounds the time a rejected-but-not-cleaned entry intent can block a
    retry.  Once ``mark_entry_idempotency_submitted`` has been called the
    record switches to the longer window TTL above.
    """
    try:
        return float(os.getenv("MERID_ENTRY_PRE_SUBMIT_TTL_SECONDS", "10.0"))
    except (TypeError, ValueError):
        return 10.0


# (market_ticker, contract) -> record of the most recent accepted entry.
# The ticker encodes the 15-minute window/expiry, so the key is per
# ticker/side/window as required.
_accepted_entry_intents: dict[tuple[str, str], dict[str, Any]] = {}
_entry_idempotency_lock = threading.RLock()


def clear_entry_idempotency_registry() -> None:
    """Reset the accepted-entry registry (tests and process restart only)."""
    _accepted_entry_intents.clear()


def ticker_has_stale_pending_entry_intent(ticker: str, max_age_s: float = 60.0) -> bool:
    """Return True if any contract for ``ticker`` has a stale PENDING record."""
    now = time.time()
    with _entry_idempotency_lock:
        for (market_ticker, _contract), rec in _accepted_entry_intents.items():
            if market_ticker != ticker:
                continue
            if _is_pre_submit_record(rec) and now - rec["ts"] > max_age_s:
                return True
            if rec.get("status") == "rejected" and now - rec["ts"] > max_age_s:
                return True
    return False


def _new_entry_record(i: CanonicalOrderIntent, now: float) -> dict[str, Any]:
    return {
        "ts": now,
        "submitted_ts": None,
        "intent_id": i.intent_id,
        "client_order_id": i.client_order_id,
        "limit_cents": i.limit_cents,
        "submitted": False,
        "order_id": None,
        "has_execution": False,
        "status": "pending",
    }


def _is_pre_submit_record(rec: dict[str, Any]) -> bool:
    return bool(
        not rec["submitted"]
        and not rec.get("order_id")
        and not rec["has_execution"]
        and rec.get("status") in (None, "pending")
    )


def _lookup_gate_record(client_order_id: str | None) -> Any | None:
    """Best-effort local gate lookup used to reconcile a canonical record."""
    if not client_order_id:
        return None
    try:
        from merid.event_venues.kalshi.order_gate import get_pre_trade_gate

        gate = get_pre_trade_gate()
        if gate is None or gate.store is None:
            return None
        return gate.store.lookup(client_order_id)
    except Exception as exc:
        logger.debug(
            "[ENTRY-IDEMPOTENCY-GATE-LOOKUP] failed for %s: %s", client_order_id, exc
        )
        return None


def _prune_stale_entry_records(now: float) -> None:
    """Evict stale records: terminal pre-submit, rejected, or window-aged."""
    ttl = _entry_dedup_ttl_seconds()
    pre_ttl = _pre_submit_stale_ttl_seconds()
    keys_to_remove = []
    for key, rec in _accepted_entry_intents.items():
        age = now - rec["ts"]
        if _is_pre_submit_record(rec) and age >= pre_ttl:
            # Pre-submit record that never became a real order.
            gate_rec = _lookup_gate_record(rec.get("client_order_id"))
            if gate_rec is None or gate_rec.status.value in ("rejected", "canceled", "expired"):
                keys_to_remove.append(key)
            elif gate_rec.status.value == "pending" and now - gate_rec.created_at >= pre_ttl:
                # Gate PENDING record is also stale; it should have been submitted.
                keys_to_remove.append(key)
            # For submitted/live/partial/filled/submission_unknown we keep.
        elif rec.get("status") == "rejected" and age >= pre_ttl or age >= ttl:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        removed = _accepted_entry_intents.pop(key, None)
        if removed is not None:
            logger.info(
                "[ENTRY-IDEMPOTENCY-PRUNE] ticker=%s contract=%s intent=%s "
                "status=%s age=%.1fs",
                key[0], key[1], removed.get("intent_id"), removed.get("status"), now - removed["ts"],
            )


def _enforce_entry_idempotency(i: CanonicalOrderIntent) -> None:
    """Reject a second entry for the same (ticker, side, window).

    A resubmission of the *same* order (same ``client_order_id``) qualifies
    as a deliberate cancel/replace and is allowed.  A pre-submit record that
    never reached the exchange is evicted after ``_pre_submit_stale_ttl_seconds``
    and replaced by the new intent, so a rejected intent cannot block retries
    indefinitely.  Submitted/filled records remain active for the window TTL.
    """
    if not _entry_dedup_enabled():
        return
    now = time.time()
    key = (i.market_ticker, i.contract)

    with _entry_idempotency_lock:
        _prune_stale_entry_records(now)
        rec = _accepted_entry_intents.get(key)
        if rec is not None:
            # Same client_order_id => deliberate resubmission / cancel-replace.
            if i.client_order_id and i.client_order_id == rec.get("client_order_id"):
                rec["ts"] = now
                rec["limit_cents"] = i.limit_cents
                rec["intent_id"] = i.intent_id
                logger.info(
                    "[ENTRY-IDEMPOTENCY-RESUBMIT] ticker=%s contract=%s intent=%s "
                    "client_order_id=%s status=%s",
                    i.market_ticker, i.contract, i.intent_id, i.client_order_id, rec.get("status"),
                )
                return

            # If the existing record is pre-submit and stale, reconcile with the
            # local idempotent order store and replace it if it is terminal or
            # absent from the exchange/gate.
            if _is_pre_submit_record(rec):
                age = now - rec["ts"]
                pre_ttl = _pre_submit_stale_ttl_seconds()
                if age >= pre_ttl:
                    gate_rec = _lookup_gate_record(rec.get("client_order_id"))
                    replace = False
                    if gate_rec is None or gate_rec.status.value in ("rejected", "canceled", "expired") or gate_rec.status.value == "pending" and now - gate_rec.created_at >= pre_ttl:
                        replace = True
                    if replace:
                        logger.warning(
                            "[ENTRY-IDEMPOTENCY-STALE-REPLACE] ticker=%s contract=%s "
                            "stale_intent=%s age=%.1fs new_intent=%s gate_status=%s",
                            i.market_ticker, i.contract, rec.get("intent_id"), age,
                            i.intent_id, gate_rec.status.value if gate_rec else None,
                        )
                        _accepted_entry_intents[key] = _new_entry_record(i, now)
                        return

            # Active record - block.
            age = now - rec["ts"]
            logger.warning(
                "[ENTRY-IDEMPOTENCY-REJECT] ticker=%s contract=%s original_intent=%s "
                "original_client_order_id=%s prior_limit=%sc current_limit=%sc age=%.1fs "
                "submitted=%s order_id=%s has_execution=%s status=%s reason=duplicate_entry",
                i.market_ticker, i.contract, rec.get("intent_id"),
                rec.get("client_order_id"), rec.get("limit_cents"), i.limit_cents, age,
                rec.get("submitted"), rec.get("order_id"), rec.get("has_execution"),
                rec.get("status"),
            )
            raise OrderIntentValidationError(
                f"duplicate_entry:ticker={i.market_ticker}:side={i.contract}:"
                f"original_intent={rec.get('intent_id')}"
            )

        _accepted_entry_intents[key] = _new_entry_record(i, now)
        logger.info(
            "[ENTRY-IDEMPOTENCY-RECORDED] ticker=%s contract=%s intent=%s "
            "client_order_id=%s limit=%sc status=pending",
            i.market_ticker, i.contract, i.intent_id, i.client_order_id, i.limit_cents,
        )


def mark_entry_idempotency_reconciliation_required(
    market_ticker: str,
    contract: str,
    client_order_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Promote a canonical entry record to reconciliation-required.

    Use this when a submission was attempted but the outcome is ambiguous
    (timeout after write, duplicate response without confirmatory lookup).
    The record stays active until exchange reconciliation resolves it or the
    window TTL expires.
    """
    key = (market_ticker, contract)
    with _entry_idempotency_lock:
        rec = _accepted_entry_intents.get(key)
        if rec is None:
            return
        if client_order_id and client_order_id != rec.get("client_order_id"):
            if rec.get("client_order_id") is not None:
                return
            rec["client_order_id"] = client_order_id
        rec["status"] = "reconciliation_required"
        rec["submitted_ts"] = time.time()
        logger.info(
            "[ENTRY-IDEMPOTENCY-RECONCILIATION-REQUIRED] ticker=%s contract=%s intent=%s "
            "client_order_id=%s reason=%s",
            market_ticker, contract, rec.get("intent_id"), rec.get("client_order_id"), reason,
        )


def release_entry_idempotency(
    market_ticker: str,
    contract: str,
    client_order_id: str | None = None,
) -> None:
    """Remove a canonical entry record for a rejected/pre-submit intent.

    Safe to call from any rejection path.  Once a record has progressed to
    submitted/executed (has_execution=True) it is left intact so real fills
    continue to protect the window.  A record that was only submitted but
    never executed is removed so an exchange rejection/cancel does not block
    a retry.
    """
    key = (market_ticker, contract)
    with _entry_idempotency_lock:
        rec = _accepted_entry_intents.get(key)
        if rec is None:
            return
        if client_order_id and client_order_id != rec.get("client_order_id"):
            # If the record still has no client_order_id, bind this call to it.
            if rec.get("client_order_id") is not None:
                return
            rec["client_order_id"] = client_order_id
        if rec.get("has_execution"):
            # Real fill; do not remove the record.
            return
        # Remove the record: this was a rejected/canceled or pre-submit
        # terminal intent and must not block a retry.
        _accepted_entry_intents.pop(key, None)
        logger.info(
            "[ENTRY-IDEMPOTENCY-RELEASED] ticker=%s contract=%s intent=%s "
            "client_order_id=%s",
            market_ticker, contract, rec.get("intent_id"), rec.get("client_order_id"),
        )


def mark_entry_idempotency_submitted(
    market_ticker: str,
    contract: str,
    client_order_id: str | None = None,
    order_id: str | None = None,
) -> None:
    """Promote a canonical entry record to submitted (confirmed in flight)."""
    key = (market_ticker, contract)
    with _entry_idempotency_lock:
        rec = _accepted_entry_intents.get(key)
        if rec is None:
            return
        if client_order_id and client_order_id != rec.get("client_order_id"):
            if rec.get("client_order_id") is not None:
                return
            rec["client_order_id"] = client_order_id
        rec["submitted"] = True
        rec["submitted_ts"] = time.time()
        if order_id:
            rec["order_id"] = order_id
        rec["status"] = "submitted"
        logger.info(
            "[ENTRY-IDEMPOTENCY-SUBMITTED] ticker=%s contract=%s intent=%s "
            "client_order_id=%s order_id=%s",
            market_ticker, contract, rec.get("intent_id"), rec.get("client_order_id"), order_id,
        )


def assert_no_stale_pending_entry_record(
    market_ticker: str,
    contract: str,
    client_order_id: str | None = None,
) -> None:
    """Enforce the lifecycle invariant: no PENDING/no-order_id/no-execution record.

    Raises ``AssertionError`` if a stale canonical entry record remains in the
    pre-submit state.  Callers can use this as a post-condition after terminalizing
    a rejected intent.
    """
    key = (market_ticker, contract)
    with _entry_idempotency_lock:
        rec = _accepted_entry_intents.get(key)
        if rec is None:
            return
        if client_order_id and rec.get("client_order_id") is not None and rec["client_order_id"] != client_order_id:
            return
        stale = (
            rec.get("status") == "pending"
            and rec.get("submitted") is False
            and rec.get("order_id") is None
            and rec.get("has_execution") is False
        )
        if stale:
            raise AssertionError(
                f"stale_pending_entry_record: key={key} client_order_id={client_order_id} rec={rec}"
            )


def release_entry_idempotency_by_key(
    market_ticker: str,
    contract: str,
) -> None:
    """Force-remove an entry idempotency record by key, ignoring client_order_id.

    This is a last-resort cleanup for invariant violations.  It must only be
    called after a normal ``release_entry_idempotency`` has failed to remove a
    stale record.
    """
    key = (market_ticker, contract)
    with _entry_idempotency_lock:
        removed = _accepted_entry_intents.pop(key, None)
        if removed is not None:
            logger.warning(
                "[ENTRY-IDEMPOTENCY-FORCE-RELEASE] ticker=%s contract=%s intent=%s",
                market_ticker, contract, removed.get("intent_id"),
            )


def mark_entry_idempotency_executed(
    market_ticker: str,
    contract: str,
    client_order_id: str | None = None,
    fill_id: str | None = None,
) -> None:
    """Mark a canonical entry record as executed (at least one fill)."""
    key = (market_ticker, contract)
    with _entry_idempotency_lock:
        rec = _accepted_entry_intents.get(key)
        if rec is None:
            return
        if client_order_id and client_order_id != rec.get("client_order_id"):
            if rec.get("client_order_id") is not None:
                return
            rec["client_order_id"] = client_order_id
        rec["submitted"] = True
        rec["has_execution"] = True
        rec["status"] = "filled"
        logger.info(
            "[ENTRY-IDEMPOTENCY-EXECUTED] ticker=%s contract=%s intent=%s "
            "client_order_id=%s fill_id=%s",
            market_ticker, contract, rec.get("intent_id"), rec.get("client_order_id"), fill_id,
        )


@dataclass(frozen=True)
class CanonicalOrderIntent:
    """Immutable, canonical order intent.

    All size/position fields use integer centi-contracts and signed-YES
    exposure (positive = long YES, negative = long NO / short YES).
    """

    market_ticker: str
    contract: Literal["yes", "no"]
    action: Literal["buy", "sell"]
    purpose: Literal["open", "close"]
    qty_cc: int
    limit_cents: int
    strategy_signal: Literal["up", "down"]
    expected_position_before: int
    expected_position_after: int
    expected_realized_pnl_cents: int | None
    reason: str
    allow_short: bool = False
    intent_id: str | None = None
    order_attempt_id: str | None = None
    decision_id: str | None = None
    client_order_id: str | None = None
    kalshi_side: str | None = None
    fee_cents: int = 0
    reduce_only: bool = False
    time_in_force: str = "gtc"
    # 2026-08-11: Signal economics and settlement telemetry.
    all_in_cost_cents: float | None = None
    ev_net_cents: float | None = None
    slippage_cents: int | None = None
    time_to_expiry_seconds: float | None = None
    settlement_input_price: float | None = None
    cf_rti_basis: float | None = None
    is_counter_trend: bool = False
    thesis_side: str | None = None
    parent_entry_fill_id: str | None = None
    parent_entry_order_id: str | None = None
    parent_entry_signal_id: str | None = None
    parentage_status: str = "UNKNOWN"  # CANONICAL_FILL | ORDER_LINKED | SIGNAL_ONLY | UNKNOWN
    # 2026-08-19: Decision/economic provenance required for audit and fill-adjusted edge.
    run_id: str | None = None
    p_yes: float | None = None
    p_no: float | None = None
    p_selected: float | None = None
    confidence: float | None = None
    confidence_valid: bool = False
    confidence_source: str = "unknown"
    settlement_reference: str | None = None
    data_state: str | None = None
    regime_label: str | None = None
    regime_probability: float | None = None
    gross_edge: float | None = None
    net_edge_pretrade: float | None = None
    selected_outcome_price_cents: int | None = None
    # 2026-08-26: Immutable intent/position-effect/economic-side provenance for
    # clean entry/exit audit and model-sign attribution.
    intent: Literal["OPEN", "CLOSE", "REDUCE", "CANCEL_REPLACE"] | None = None
    position_effect: Literal["OPEN", "CLOSE"] | None = None
    economic_side: Literal["YES", "NO"] | None = None

    # 2026-08-29: Configuration hash of the resolved live config that authorized
    # this order.  Provides cryptographic audit linkage from every intent back
    # to the active safety policy.
    config_hash: str | None = None

    def yes_delta(self) -> int:
        """Signed-YES centi-contract delta for this order."""
        return yes_delta(self.action, self.contract, self.qty_cc)

    def kalshi_side_str(self) -> str:
        """Kalshi wire format, e.g. ``BUY_YES`` or ``SELL_NO``."""
        return to_kalshi_side(self.contract, self.action)

    def to_dict(self) -> dict:
        """Serialize for logging / persistence."""
        return {
            "market_ticker": self.market_ticker,
            "contract": self.contract,
            "action": self.action,
            "purpose": self.purpose,
            "qty_cc": self.qty_cc,
            "limit_cents": self.limit_cents,
            "strategy_signal": self.strategy_signal,
            "expected_position_before": self.expected_position_before,
            "expected_position_after": self.expected_position_after,
            "expected_realized_pnl_cents": self.expected_realized_pnl_cents,
            "reason": self.reason,
            "allow_short": self.allow_short,
            "intent_id": self.intent_id,
            "order_attempt_id": self.order_attempt_id,
            "decision_id": self.decision_id,
            "client_order_id": self.client_order_id,
            "kalshi_side": self.kalshi_side,
            "fee_cents": self.fee_cents,
            "all_in_cost_cents": self.all_in_cost_cents,
            "ev_net_cents": self.ev_net_cents,
            "slippage_cents": self.slippage_cents,
            "time_to_expiry_seconds": self.time_to_expiry_seconds,
            "settlement_input_price": self.settlement_input_price,
            "cf_rti_basis": self.cf_rti_basis,
            "is_counter_trend": self.is_counter_trend,
            "thesis_side": self.thesis_side,
            "parent_entry_fill_id": self.parent_entry_fill_id,
            "parent_entry_order_id": self.parent_entry_order_id,
            "parent_entry_signal_id": self.parent_entry_signal_id,
            "parentage_status": self.parentage_status,
            "run_id": self.run_id,
            "p_yes": self.p_yes,
            "p_no": self.p_no,
            "p_selected": self.p_selected,
            "confidence": self.confidence,
            "confidence_valid": self.confidence_valid,
            "confidence_source": self.confidence_source,
            "settlement_reference": self.settlement_reference,
            "data_state": self.data_state,
            "regime_label": self.regime_label,
            "regime_probability": self.regime_probability,
            "gross_edge": self.gross_edge,
            "net_edge_pretrade": self.net_edge_pretrade,
            "selected_outcome_price_cents": self.selected_outcome_price_cents,
            "intent": self.intent,
            "position_effect": self.position_effect,
            "economic_side": self.economic_side,
            "config_hash": self.config_hash,
        }


def _resolve_contract_action(intent: Any) -> tuple[str, str]:
    """Resolve canonical ``(contract, action)`` from the raw intent.

    Accepts bare ``side``/``action`` fields, Kalshi-formatted ``kalshi_side``,
    or Kalshi-formatted ``side`` (``BUY_YES`` / ``SELL_NO`` etc.).
    """
    kalshi_side: str | None = getattr(intent, "kalshi_side", None)
    side: str = (getattr(intent, "side", None) or "").strip()
    action: str = (getattr(intent, "action", None) or "").strip()

    # Prefer an explicit Kalshi-formatted side string.
    side_upper = side.upper()
    if kalshi_side:
        try:
            contract, action = parse_kalshi_side(str(kalshi_side).upper())
            return contract, action
        except ValueError:
            pass

    if side_upper in ("BUY_YES", "SELL_YES", "BUY_NO", "SELL_NO"):
        try:
            contract, action = parse_kalshi_side(side_upper)
            return contract, action
        except ValueError:
            pass

    # Fall back to bare side/action.
    side_lower = side.lower()
    if "no" in side_lower:
        contract = "no"
    elif "yes" in side_lower:
        contract = "yes"
    else:
        # Fail-closed: do not default to "yes".  Empty/unknown side is a
        # structural invariant violation that must not produce a BUY_YES order.
        raise OrderIntentValidationError(
            f"unresolvable_contract_side: side={side!r} action={action!r}"
        )

    action_lower = action.lower()
    if action_lower in ("buy", "sell"):
        action = action_lower
    elif "buy" in side_lower:
        action = "buy"
    elif "sell" in side_lower:
        action = "sell"

    return contract, action


def _resolve_purpose(
    intent: Any,
    delta_cc: int,
    exchange_position_cc: int | None,
) -> Literal["open", "close"]:
    """Derive ``purpose`` from explicit metadata or the signed position delta."""
    entry_or_exit = getattr(intent, "entry_or_exit", None)
    if entry_or_exit in ("exit", "close"):
        return "close"
    if entry_or_exit in ("entry", "open"):
        return "open"
    if getattr(intent, "reduce_only", False) or getattr(intent, "is_exit_order", False):
        return "close"

    source = (getattr(intent, "source", None) or "").lower()
    rationale = (getattr(intent, "rationale", None) or "").lower()
    exit_reason = (getattr(intent, "exit_reason", None) or "").lower()
    for text in (source, rationale, exit_reason):
        if any(marker in text for marker in EXIT_SOURCE_MARKERS):
            return "close"

    if exchange_position_cc is not None:
        pre = int(exchange_position_cc or 0)
        if pre == 0:
            return "open"
        if pre * delta_cc > 0:
            # Same sign -> increasing the existing position.
            return "open"
        if pre * delta_cc < 0:
            # Opposite sign.  If it does not overshoot, it is a close;
            # if it overshoots, ``validate_canonical_intent`` will reject.
            return "close"

    # No position context and no explicit direction -> conservatively treat as open.
    return "open"


def _resolve_strategy_signal(intent: Any, delta_cc: int) -> Literal["up", "down"]:
    """Resolve the strategy signal."""
    sig = getattr(intent, "strategy_signal", None)
    if sig in ("up", "down"):
        return sig  # type: ignore[return-value]

    # Derive from the order's signed-YES delta.
    if delta_cc > 0:
        return "up"
    if delta_cc < 0:
        return "down"
    return "up"


def _resolve_reason(intent: Any) -> str:
    """Human/machine-readable reason string."""
    for attr in ("rationale", "exit_reason", "source"):
        val = getattr(intent, attr, None)
        if val:
            return str(val)
    return "canonical_order_intent"


def _resolve_allow_short(intent: Any) -> bool:
    """Return the effective ``allow_short`` flag."""
    allow = getattr(intent, "allow_short", None)
    if allow is not None:
        return bool(allow)
    return os.getenv("MERID_ALLOW_SHORT_YES", "false").lower() in ("1", "true", "yes")


def _safe_int_cents(value: Any, field: str) -> int:
    """Coerce a value to integer cents, raising a clear validation error."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise OrderIntentValidationError("invalid_price:price_not_integer")
    try:
        # Reject floats that are not integral (the existing tests expect this).
        if isinstance(value, float) and not value.is_integer():
            raise OrderIntentValidationError("invalid_price:price_not_integer")
        as_decimal = Decimal(str(value))
        if as_decimal != as_decimal.to_integral_value():
            raise OrderIntentValidationError("invalid_price:price_not_integer")
        return int(as_decimal)
    except (InvalidOperation, ValueError, TypeError):
        raise OrderIntentValidationError("invalid_price:price_not_integer")


def _safe_count(value: Any) -> int:
    """Coerce a contract count to a positive integer."""
    try:
        count = int(value) if value is not None else 0
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        raise OrderIntentValidationError("non_positive_size")
    return count


def _resolve_count_fp(value: Any) -> Decimal:
    """Parse and validate a fixed-point contract count.

    ``count_fp`` must be a positive, finite Decimal aligned to the 0.01-contract
    (centi-contract) grid.  All other values are hard-rejected before they can
    reach the execution surface.
    """
    if value is None:
        raise OrderIntentValidationError("missing_size")

    try:
        if isinstance(value, Decimal):
            d = value
        elif isinstance(value, float):
            # Use str() to avoid binary-float Decimal artefacts.
            d = Decimal(str(value))
        else:
            d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise OrderIntentValidationError(f"invalid_count_fp:{value}")

    if d.is_nan() or d.is_infinite():
        raise OrderIntentValidationError(f"invalid_count_fp_nan_or_infinite:{d}")

    if d <= 0:
        raise OrderIntentValidationError("non_positive_size")

    # Centi-contract alignment check: d * 100 must be an exact integer.
    scaled = d * Decimal("100")
    if scaled != scaled.to_integral_value():
        raise OrderIntentValidationError(f"invalid_count_fp_not_aligned_to_0.01:{d}")

    return d


def compute_expected_realized_pnl_cents(
    purpose: Literal["open", "close"],
    qty_cc: int,
    limit_cents: int,
    contract: Literal["yes", "no"],
    position_before: int,
    position_avg_price_cents: int | None,
    position_side: str | None,
    fee_cents: int,
) -> int | None:
    """Predict realized PnL in cents for a close order.

    - ``position_before`` and the returned value use signed-YES centi-contracts.
    - ``position_avg_price_cents`` is in the *position side* space (YES or NO).
    - The fill ``limit_cents`` is converted to the position side when needed.
    """
    if purpose != "close":
        return None
    if position_avg_price_cents is None or position_side is None:
        return None
    if position_before == 0:
        return None

    closed_qty_cc = min(qty_cc, abs(position_before))
    if closed_qty_cc <= 0:
        return None

    pos_side = position_side.lower()
    if contract == pos_side:
        adjusted_price_cents = limit_cents
    else:
        adjusted_price_cents = 100 - limit_cents

    pnl_per = adjusted_price_cents - position_avg_price_cents
    pnl_cents = (closed_qty_cc * pnl_per) // 100
    return pnl_cents - fee_cents


def normalize_order(
    intent: Any,
    *,
    exchange_position_cc: int | None = None,
    position_avg_price_cents: int | None = None,
    position_side: str | None = None,
    fee_cents: int | None = None,
) -> CanonicalOrderIntent:
    """Normalize any order intent object into the immutable canonical contract.

    Args:
        intent: An ``OrderIntent``-like object (duck-typed).
        exchange_position_cc: Fresh signed-YES position before the order.
        position_avg_price_cents: Avg entry price in the position's side space.
        position_side: ``"yes"`` or ``"no"`` for the current position.
        fee_cents: Estimated fee for this fill in cents.

    Raises:
        OrderIntentValidationError: If the intent cannot be normalized.
    """
    market_ticker = str(getattr(intent, "ticker", "") or "").strip()
    if not market_ticker:
        raise OrderIntentValidationError("missing_ticker")

    contract, action = _resolve_contract_action(intent)
    if contract not in ("yes", "no"):
        raise OrderIntentValidationError(f"invalid_contract:{contract}")
    if action not in ("buy", "sell"):
        raise OrderIntentValidationError(f"invalid_action:{action}")

    price_cents = _safe_int_cents(getattr(intent, "price_cents", None), "price_cents")
    from merid.event_venues.kalshi.binary_price_space import (
        CANONICAL_MAX_CENTS,
        CANONICAL_MIN_CENTS,
    )
    is_exit = (
        getattr(intent, "reduce_only", False)
        or getattr(intent, "entry_or_exit", "") in ("exit", "close")
        or getattr(intent, "is_exit_order", False)
    )
    # Entries are constrained to the canonical 10c-75c range; exits can cross
    # the book at any valid 1c-99c price to close a position.
    if is_exit:
        if not (1 <= price_cents <= 99):
            raise OrderIntentValidationError(f"invalid_price:price_cents={price_cents}")
    else:
        if not (CANONICAL_MIN_CENTS <= price_cents <= CANONICAL_MAX_CENTS):
            raise OrderIntentValidationError(f"invalid_price:price_cents={price_cents}")

    # Canonical quantity resolution.  ``count_fp`` (Decimal contracts) is the
    # fixed-point authority; ``qty_cc`` is the integer centi-contract form.  If
    # ``count_fp`` is not supplied we fall back to the legacy integer ``count``
    # field and convert it exactly.
    count_fp = getattr(intent, "count_fp", None)
    if count_fp is not None:
        count_fp = _resolve_count_fp(count_fp)
    else:
        count = _safe_count(getattr(intent, "count", None))
        count_fp = Decimal(count)
    qty_cc = int(count_fp * Decimal("100"))

    delta_cc = yes_delta(action, contract, qty_cc)
    purpose = _resolve_purpose(intent, delta_cc, exchange_position_cc)

    # Determine expected position before (centi-contracts exact).
    pre_position_fp = getattr(intent, "pre_position_fp", None)
    pre_position_size = getattr(intent, "pre_position_size", None)
    if exchange_position_cc is not None:
        expected_position_before = int(exchange_position_cc)
    elif pre_position_fp is not None:
        if position_side:
            expected_position_before = to_signed_yes_exposure(position_side, int(pre_position_fp))
        else:
            expected_position_before = int(pre_position_fp)
    elif pre_position_size is not None:
        # Legacy whole-contract fallback; loses fractional precision.
        if position_side:
            expected_position_before = to_signed_yes_exposure(position_side, int(pre_position_size) * 100)
        else:
            expected_position_before = int(pre_position_size) * 100
    else:
        expected_position_before = 0

    # Determine expected position after (centi-contracts exact).
    expected_post_position_fp = getattr(intent, "expected_post_position_fp", None)
    expected_post_position_size = getattr(intent, "expected_post_position_size", None)
    if expected_post_position_fp is not None:
        if position_side:
            expected_position_after = to_signed_yes_exposure(position_side, int(expected_post_position_fp))
        else:
            expected_position_after = expected_position_before + delta_cc
            if expected_position_after != 0 and (expected_position_after > 0) != (int(expected_post_position_fp) >= 0):
                expected_position_after = expected_position_before + delta_cc
    elif expected_post_position_size is not None:
        # Legacy whole-contract fallback; loses fractional precision.
        if position_side:
            expected_position_after = to_signed_yes_exposure(position_side, int(expected_post_position_size) * 100)
        else:
            expected_position_after = expected_position_before + delta_cc
            if expected_position_after != 0 and (expected_position_after > 0) != (int(expected_post_position_size) >= 0):
                expected_position_after = expected_position_before + delta_cc
    else:
        expected_position_after = expected_position_before + delta_cc

    allow_short = _resolve_allow_short(intent)
    strategy_signal = _resolve_strategy_signal(intent, delta_cc)
    reason = _resolve_reason(intent)

    fee = fee_cents if fee_cents is not None else getattr(intent, "estimated_fee_cents", 0) or 0

    expected_pnl = compute_expected_realized_pnl_cents(
        purpose=purpose,
        qty_cc=qty_cc,
        limit_cents=price_cents,
        contract=contract,  # type: ignore[arg-type]
        position_before=expected_position_before,
        position_avg_price_cents=position_avg_price_cents,
        position_side=position_side,
        fee_cents=fee,
    )
    # If the intent already carried an expected PnL, trust it.
    if getattr(intent, "expected_realized_pnl_cents", None) is not None:
        try:
            expected_pnl = int(intent.expected_realized_pnl_cents)
        except (TypeError, ValueError):
            expected_pnl = None

    kalshi_side = getattr(intent, "kalshi_side", None)

    # Authoritative intent/position-effect/economic-side provenance.  These are
    # derived from the canonical contract/action and the absolute position change,
    # not from the caller's optional metadata, so downstream audit joins can trust
    # them as the source of truth for entry vs. exit classification.
    economic_side_val: Literal["YES", "NO"] = (
        "YES"
        if (contract == "yes" and action == "buy") or (contract == "no" and action == "sell")
        else "NO"
    )
    if abs(expected_position_after) > abs(expected_position_before):
        position_effect_val: Literal["OPEN", "CLOSE"] = "OPEN"
    elif abs(expected_position_after) < abs(expected_position_before) or (
        expected_position_before != 0 and expected_position_after == 0
    ):
        position_effect_val = "CLOSE"
    else:
        position_effect_val = (
            "OPEN" if expected_position_before == 0 and expected_position_after != 0 else "CLOSE"
        )
    if position_effect_val == "OPEN":
        intent_val: Literal["OPEN", "CLOSE", "REDUCE", "CANCEL_REPLACE"] = "OPEN"
    else:
        intent_val = "CLOSE" if expected_position_after == 0 else "REDUCE"
    if getattr(intent, "intent", None) in ("OPEN", "CLOSE", "REDUCE", "CANCEL_REPLACE"):
        intent_val = intent.intent

    # Resolve time-in-force from the canonical live config when no explicit
    # TIF is supplied on the intent.  Exits are allowed to rest; entries are
    # immediate (ioc/fok) to avoid stale capital.
    explicit_tif = getattr(intent, "time_in_force", None)
    if explicit_tif:
        time_in_force = str(explicit_tif).lower()
    else:
        try:
            from merid.config.live_config import get_resolved_live_config

            resolved = get_resolved_live_config(allow_unresolved=True)
            if resolved.resolved:
                time_in_force = (
                    resolved.exit_tif_default
                    if purpose == "close"
                    else resolved.entry_tif_default
                )
            else:
                time_in_force = "gtc"
        except Exception:
            time_in_force = "gtc"

    # Attach the configuration hash that authorized this order.
    config_hash = getattr(intent, "config_hash", None)
    if not config_hash:
        try:
            from merid.config.live_config import get_resolved_live_config

            resolved = get_resolved_live_config(allow_unresolved=True)
            if resolved.resolved:
                config_hash = resolved.config_hash
        except Exception:
            config_hash = None

    return CanonicalOrderIntent(
        market_ticker=market_ticker,
        contract=contract,  # type: ignore[arg-type]
        action=action,  # type: ignore[arg-type]
        purpose=purpose,  # type: ignore[arg-type]
        qty_cc=qty_cc,
        limit_cents=price_cents,
        strategy_signal=strategy_signal,  # type: ignore[arg-type]
        expected_position_before=expected_position_before,
        expected_position_after=expected_position_after,
        expected_realized_pnl_cents=expected_pnl,
        reason=reason,
        allow_short=allow_short,
        intent_id=getattr(intent, "intent_id", None),
        order_attempt_id=getattr(intent, "order_attempt_id", None),
        decision_id=getattr(intent, "decision_id", None),
        client_order_id=getattr(intent, "client_order_id", None) or getattr(intent, "client_tag", None),
        kalshi_side=kalshi_side,
        fee_cents=fee,
        reduce_only=bool(getattr(intent, "reduce_only", False)),
        time_in_force=time_in_force,
        all_in_cost_cents=getattr(intent, "all_in_cost_cents", None),
        ev_net_cents=getattr(intent, "ev_net_cents", None),
        slippage_cents=getattr(intent, "slippage_cents", None),
        time_to_expiry_seconds=getattr(intent, "time_to_expiry_seconds", None),
        settlement_input_price=getattr(intent, "settlement_input_price", None),
        cf_rti_basis=getattr(intent, "cf_rti_basis", None),
        is_counter_trend=bool(getattr(intent, "is_counter_trend", False)),
        thesis_side=getattr(intent, "thesis_side", None),
        parent_entry_fill_id=getattr(intent, "parent_entry_fill_id", None),
        parent_entry_order_id=getattr(intent, "parent_entry_order_id", None),
        parent_entry_signal_id=getattr(intent, "parent_entry_signal_id", None),
        parentage_status=getattr(intent, "parentage_status", "UNKNOWN"),
        run_id=getattr(intent, "run_id", None),
        p_yes=getattr(intent, "p_yes", None),
        p_no=getattr(intent, "p_no", None),
        p_selected=getattr(intent, "p_selected", None),
        confidence=getattr(intent, "confidence", None),
        confidence_valid=bool(getattr(intent, "confidence_valid", False)),
        confidence_source=str(getattr(intent, "confidence_source", "unknown") or "unknown"),
        settlement_reference=getattr(intent, "settlement_reference", None),
        data_state=getattr(intent, "data_state", None),
        regime_label=getattr(intent, "regime_label", None),
        regime_probability=getattr(intent, "regime_probability", None),
        gross_edge=getattr(intent, "gross_edge", None),
        net_edge_pretrade=getattr(intent, "net_edge_pretrade", None),
        selected_outcome_price_cents=getattr(intent, "selected_outcome_price_cents", None),
        intent=intent_val,
        position_effect=position_effect_val,
        economic_side=economic_side_val,
        config_hash=config_hash,
    )


def validate_canonical_intent(
    i: CanonicalOrderIntent,
    *,
    exchange_position_cc: int | None = None,
    position_avg_price_cents: int | None = None,
    max_adverse_pnl_cents: int | None = None,
) -> None:
    """Hard-reject an order intent that violates execution invariants.

    Args:
        i: Canonical order intent to validate.
        exchange_position_cc: Optional fresh signed-YES position to compare.
        position_avg_price_cents: Optional position avg price for PnL guard.
        max_adverse_pnl_cents: Optional PnL budget.  If set, predicted realized
            PnL must not be worse than ``-max_adverse_pnl_cents``.

    Raises:
        OrderIntentValidationError: With a machine-readable reason.
    """
    from merid.event_venues.kalshi.binary_price_space import (
        CANONICAL_MAX_CENTS,
        CANONICAL_MIN_CENTS,
    )
    if not isinstance(i.limit_cents, int):
        raise OrderIntentValidationError(f"invalid_price:price_cents={i.limit_cents}")
    # Entries are constrained to the canonical 10c-75c range; exits can cross
    # the book at any valid 1c-99c price to close a position.
    if i.purpose == "open" and not (CANONICAL_MIN_CENTS <= i.limit_cents <= CANONICAL_MAX_CENTS):
        raise OrderIntentValidationError(f"invalid_price:price_cents={i.limit_cents}")
    if i.purpose == "close" and not (1 <= i.limit_cents <= 99):
        raise OrderIntentValidationError(f"invalid_price:price_cents={i.limit_cents}")
    if i.qty_cc <= 0:
        raise OrderIntentValidationError("non_positive_size")

    # New-entry invariants: hard TTE cutoff, positive EV, and extreme-price margin.
    if i.purpose == "open":
        # Fail-closed kill switch: entries are prohibited while protective
        # (stop-loss) exits cannot be submitted.  Exits are unaffected.
        if not _unprotected_entries_allowed() and not protective_exits_enabled():
            raise OrderIntentValidationError("PROTECTIVE_EXIT_DISABLED")
        # One open inventory unit per ticker: never open into a live position.
        if exchange_position_cc is not None and exchange_position_cc != 0:
            raise OrderIntentValidationError(
                f"entry_with_open_position:ticker={i.market_ticker}:"
                f"exchange_position_cc={exchange_position_cc}"
            )
        # Missing or non-finite temporal data is a fail-closed rejection for new
        # entries.  Exits use a separate reduce-only fallback that can tolerate
        # missing TTE when close_time / market status are known.
        if i.time_to_expiry_seconds is None or not math.isfinite(i.time_to_expiry_seconds):
            raise OrderIntentValidationError("missing_time_to_expiry")

        exit_only_cutoff = float(
            os.environ.get(
                "MERID_EXIT_ONLY_CUTOFF_S",
                os.environ.get("MERID_FINAL_MINUTE_CUTOFF_S", "30"),
            )
        )
        if i.time_to_expiry_seconds <= exit_only_cutoff:
            raise OrderIntentValidationError(
                f"hard_tte_cutoff:tte={i.time_to_expiry_seconds:.1f}s<={exit_only_cutoff:.0f}s"
            )
        if i.ev_net_cents is not None and i.ev_net_cents <= 0:
            raise OrderIntentValidationError(
                f"negative_ev:ev_net_cents={i.ev_net_cents:.4f}"
            )
        if i.limit_cents <= 5 or i.limit_cents >= 95:
            _fee = i.fee_cents or 2
            _min_ev_extreme = 2.5 * _fee
            if i.ev_net_cents is not None and i.ev_net_cents < _min_ev_extreme:
                raise OrderIntentValidationError(
                    f"insufficient_ev_extreme:ev={i.ev_net_cents:.4f}<min={_min_ev_extreme:.4f}"
                )

    # Position-before must match the exchange/cache if a snapshot was provided.
    if exchange_position_cc is not None and i.expected_position_before != exchange_position_cc:
        raise OrderIntentValidationError(
            f"position_before_mismatch:expected={i.expected_position_before}:exchange={exchange_position_cc}"
        )

    # Expected after must be arithmetically consistent.
    computed_after = i.expected_position_before + i.yes_delta()
    if computed_after != i.expected_position_after:
        raise OrderIntentValidationError(
            f"position_after_mismatch:expected={i.expected_position_after}:computed={computed_after}"
        )

    # Close-specific invariants (checked before open/short guards).
    if i.purpose == "close":
        if exchange_position_cc is None or exchange_position_cc == 0:
            raise OrderIntentValidationError("close_with_zero_position")

        if i.qty_cc > abs(exchange_position_cc):
            raise OrderIntentValidationError(
                f"over_close:qty={i.qty_cc}:position={abs(exchange_position_cc)}"
            )

        # A close must reduce or flatten absolute exposure and must not flip.
        if i.expected_position_after != 0:
            if abs(i.expected_position_after) >= abs(exchange_position_cc):
                raise OrderIntentValidationError("close_did_not_reduce_exposure")
            if i.expected_position_after * exchange_position_cc < 0:
                raise OrderIntentValidationError("close_flipped_position")

    # No position flips in one action.
    if i.expected_position_before != 0 and i.expected_position_after != 0:
        if (i.expected_position_before > 0 and i.expected_position_after < 0) or (
            i.expected_position_before < 0 and i.expected_position_after > 0
        ):
            raise OrderIntentValidationError("position_flip_prohibited")

    # A sell may not open a short YES position (from flat or long YES) unless shorting is allowed.
    if not i.allow_short and i.action == "sell" and i.expected_position_after < 0 and i.expected_position_before >= 0:
        raise OrderIntentValidationError("sell_to_short_prohibited")

    # PnL guard: reject exits that would lose more than the configured budget.
    if max_adverse_pnl_cents is not None and i.expected_realized_pnl_cents is not None:
        if i.expected_realized_pnl_cents < -max_adverse_pnl_cents:
            raise OrderIntentValidationError(
                f"adverse_pnl:predicted={i.expected_realized_pnl_cents}:budget={max_adverse_pnl_cents}"
            )

    # Sanity: the internal position delta must match the exchange delta.
    if exchange_position_cc is not None:
        expected_exchange_after = exchange_position_cc + i.yes_delta()
        if expected_exchange_after != i.expected_position_after:
            raise OrderIntentValidationError(
                f"exchange_position_after_mismatch:expected={i.expected_position_after}:exchange={expected_exchange_after}"
            )

    # Per-(ticker, side, window) entry idempotency.  Recorded only after all
    # other invariants pass, so a canonical-rejected intent never blocks a
    # retry.  Router rejections are healed by an explicit release call and by
    # the bounded pre-submit TTL in _enforce_entry_idempotency.
    if i.purpose == "open":
        _enforce_entry_idempotency(i)


async def fetch_fresh_signed_yes_exposure(
    ticker: str,
    timeout: float = 1.0,
    fallback_to_cache: bool = True,
) -> tuple[int | None, int | None, str | None]:
    """Return ``(signed_yes_cc, avg_price_cents, side)`` from the exchange or cache.

    First tries a live Kalshi REST position snapshot, then falls back to the
    in-memory position cache.  Returns ``(None, None, None)`` when both fail.

    The canonical rule is:
        - a long YES position has positive signed-YES exposure
        - a long NO position has negative signed-YES exposure
    Missing or unrecognised ``outcome_id`` values no longer silently default to
    YES; they are rejected and the function falls back to the cache.
    """
    try:
        from merid.event_venues.kalshi.client import get_kalshi_client

        client = get_kalshi_client()
        if client is not None:
            positions = await asyncio.wait_for(client.get_positions(), timeout=timeout)
            for pos in positions:
                if pos.market_id == ticker:
                    if pos.outcome_id is None:
                        raise ValueError(f"ticker={ticker}: missing outcome_id on exchange position")
                    side = canonical_outcome_side(pos.outcome_id).value
                    size = pos.size or Decimal("0")
                    qty_cc = int(Decimal(size) * Decimal("100"))
                    signed = normalize_rest_position(qty_cc, side, ticker)
                    avg = int(pos.average_entry_price * Decimal("100")) if pos.average_entry_price is not None else None
                    return signed, avg, side
    except Exception as exc:
        logger.debug("[FRESH-POSITION] exchange fetch failed for %s: %s", ticker, exc)

    if fallback_to_cache:
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache

            cache = get_position_cache()
            pos = cache.get_position(ticker)
            if pos is not None:
                return pos._yes_exposure(), pos.avg_price_cents, pos.side
        except Exception as exc:
            logger.debug("[FRESH-POSITION] cache fallback failed for %s: %s", ticker, exc)

    return None, None, None


_order_decision_lock: threading.Lock = threading.Lock()


def persist_order_decision(record: dict) -> None:
    """Append a structured order decision record to ``logs/order_decisions.jsonl``.

    Writes are fsync'd before returning so the record survives an OS crash or
    power failure.  Failures are logged but never raise, so the trading path is
    not blocked by a logging problem.
    """
    try:
        # Project root is four parents up from this file.
        log_dir = Path(__file__).resolve().parents[3] / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "order_decisions.jsonl"
        record.setdefault("ts", time.time())
        line = json.dumps(record, default=str, separators=(",", ":")) + "\n"
        with _order_decision_lock:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
    except Exception as exc:
        logger.debug("[ORDER-DECISION-LOG] failed to persist: %s", exc)


def max_adverse_pnl_cents() -> int | None:
    """Return the configured adverse-PnL budget in cents, or ``None`` to disable."""
    raw = os.getenv("MERID_MAX_ADVERSE_PNL_CENTS", "")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
