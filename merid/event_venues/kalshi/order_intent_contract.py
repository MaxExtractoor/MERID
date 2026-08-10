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
import os
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Optional, Set, Tuple

from utils.logger import get_logger
from merid.event_venues.kalshi.binary_price_space import (
    parse_kalshi_side,
    to_kalshi_side,
    to_signed_yes_exposure,
    yes_delta,
)

logger = get_logger("merid.event_venues.kalshi.order_intent_contract")


# Source markers that unambiguously identify a close order.
EXIT_SOURCE_MARKERS: Set[str] = {
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
    expected_realized_pnl_cents: Optional[int]
    reason: str
    allow_short: bool = False
    intent_id: Optional[str] = None
    client_order_id: Optional[str] = None
    kalshi_side: Optional[str] = None
    fee_cents: int = 0
    reduce_only: bool = False
    time_in_force: str = "gtc"

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
            "client_order_id": self.client_order_id,
            "kalshi_side": self.kalshi_side,
            "fee_cents": self.fee_cents,
        }


def _resolve_contract_action(intent: Any) -> Tuple[str, str]:
    """Resolve canonical ``(contract, action)`` from the raw intent.

    Accepts bare ``side``/``action`` fields, Kalshi-formatted ``kalshi_side``,
    or Kalshi-formatted ``side`` (``BUY_YES`` / ``SELL_NO`` etc.).
    """
    kalshi_side: Optional[str] = getattr(intent, "kalshi_side", None)
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
        contract = side_lower or "yes"  # placeholder; will be validated later

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
    exchange_position_cc: Optional[int],
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
        raise OrderIntentValidationError(f"invalid_price:price_not_integer")
    try:
        # Reject floats that are not integral (the existing tests expect this).
        if isinstance(value, float) and not value.is_integer():
            raise OrderIntentValidationError(f"invalid_price:price_not_integer")
        as_decimal = Decimal(str(value))
        if as_decimal != as_decimal.to_integral_value():
            raise OrderIntentValidationError(f"invalid_price:price_not_integer")
        return int(as_decimal)
    except (InvalidOperation, ValueError, TypeError):
        raise OrderIntentValidationError(f"invalid_price:price_not_integer")


def _safe_count(value: Any) -> int:
    """Coerce a contract count to a positive integer."""
    try:
        count = int(value) if value is not None else 0
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        raise OrderIntentValidationError("non_positive_size")
    return count


def compute_expected_realized_pnl_cents(
    purpose: Literal["open", "close"],
    qty_cc: int,
    limit_cents: int,
    contract: Literal["yes", "no"],
    position_before: int,
    position_avg_price_cents: Optional[int],
    position_side: Optional[str],
    fee_cents: int,
) -> Optional[int]:
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
    exchange_position_cc: Optional[int] = None,
    position_avg_price_cents: Optional[int] = None,
    position_side: Optional[str] = None,
    fee_cents: Optional[int] = None,
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
    if not (1 <= price_cents <= 99):
        raise OrderIntentValidationError(f"invalid_price:price_cents={price_cents}")

    count = _safe_count(getattr(intent, "count", None))
    qty_cc = count * 100

    delta_cc = yes_delta(action, contract, qty_cc)
    purpose = _resolve_purpose(intent, delta_cc, exchange_position_cc)

    # Determine expected position before.
    pre_position_size = getattr(intent, "pre_position_size", None)
    if exchange_position_cc is not None:
        expected_position_before = int(exchange_position_cc)
    elif pre_position_size is not None:
        # ``pre_position_size`` is normally an unsigned contract count.
        # We can only sign it if we know the position side.
        if position_side:
            expected_position_before = to_signed_yes_exposure(position_side, int(pre_position_size) * 100)
        else:
            expected_position_before = int(pre_position_size) * 100
    else:
        expected_position_before = 0

    # Determine expected position after.
    expected_post_position_size = getattr(intent, "expected_post_position_size", None)
    if expected_post_position_size is not None:
        # If the caller has already computed this, sign it using the current side.
        if position_side:
            expected_position_after = to_signed_yes_exposure(position_side, int(expected_post_position_size) * 100)
        else:
            expected_position_after = expected_position_before + delta_cc
            # If the computed sign is opposite, the caller-supplied post-size may be
            # on the wrong side; prefer the computed value.
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
        client_order_id=getattr(intent, "client_order_id", None) or getattr(intent, "client_tag", None),
        kalshi_side=kalshi_side,
        fee_cents=fee,
        reduce_only=bool(getattr(intent, "reduce_only", False)),
        time_in_force=str(getattr(intent, "time_in_force", "gtc") or "gtc").lower(),
    )


def validate_canonical_intent(
    i: CanonicalOrderIntent,
    *,
    exchange_position_cc: Optional[int] = None,
    position_avg_price_cents: Optional[int] = None,
    max_adverse_pnl_cents: Optional[int] = None,
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
    if not isinstance(i.limit_cents, int) or not (1 <= i.limit_cents <= 99):
        raise OrderIntentValidationError(f"invalid_price:price_cents={i.limit_cents}")
    if i.qty_cc <= 0:
        raise OrderIntentValidationError("non_positive_size")

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


async def fetch_fresh_signed_yes_exposure(
    ticker: str,
    timeout: float = 1.0,
    fallback_to_cache: bool = True,
) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """Return ``(signed_yes_cc, avg_price_cents, side)`` from the exchange or cache.

    First tries a live Kalshi REST position snapshot, then falls back to the
    in-memory position cache.  Returns ``(None, None, None)`` when both fail.
    """
    try:
        from merid.event_venues.kalshi.client import get_kalshi_client

        client = get_kalshi_client()
        if client is not None:
            positions = await asyncio.wait_for(client.get_positions(), timeout=timeout)
            for pos in positions:
                if pos.market_id == ticker:
                    size = pos.size or Decimal("0")
                    qty_cc = int(Decimal(size) * Decimal("100"))
                    side = (pos.outcome_id or "yes").lower()
                    signed = to_signed_yes_exposure(side, qty_cc)
                    avg = int(pos.average_entry_price) if pos.average_entry_price is not None else None
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


def persist_order_decision(record: dict) -> None:
    """Append a structured order decision record to ``logs/order_decisions.jsonl``.

    Failures are logged but never raise, so the trading path is not blocked by
    a logging problem.
    """
    try:
        # Project root is four parents up from this file.
        log_dir = Path(__file__).resolve().parents[3] / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "order_decisions.jsonl"
        record.setdefault("ts", time.time())
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:
        logger.debug("[ORDER-DECISION-LOG] failed to persist: %s", exc)


def max_adverse_pnl_cents() -> Optional[int]:
    """Return the configured adverse-PnL budget in cents, or ``None`` to disable."""
    raw = os.getenv("MERID_MAX_ADVERSE_PNL_CENTS", "")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
