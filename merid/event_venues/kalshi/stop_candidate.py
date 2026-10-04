"""Stop-candidate event and gated submission for Kalshi 15-minute crypto markets.

This module replaces the legacy "strategy signal -> stop trigger -> direct
sell/buy submission" path with an audited `StopCandidate` event.  A stop
candidate is **not** an order; it is a durable, immutable record of the
predicate and market state at the moment a stop *would* have fired.  It may be
converted into a reduce-only IOC/FOK close order only after all execution
gate invariants pass.

Invariants:
- `reduce_only` is True.
- `time_in_force` is IOC or FOK.
- The order's signed YES delta exactly offsets the confirmed exchange position.
- Action/contract are derived from the *confirmed* exchange position sign.
- The order is outside the market close cutoff window.
- Book and position snapshots are fresh.
- Edge stops (when enabled) require the model fair value to have crossed the
  executable liquidation value by a fee/spread/hysteresis buffer on at least
  `MERID_STOP_EDGE_MIN_CONSECUTIVE` consecutive observations.

The stop-candidate path is disabled for automatic submission by default until
it passes replay tests.  Set `MERID_ENABLE_STOP_CANDIDATE_SUBMISSION=true` to
allow a validated candidate to call `route_order_async`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from utils.logger import get_logger
from merid.event_venues.kalshi.binary_price_space import (
    from_signed_yes_exposure,
    to_kalshi_side,
    yes_delta,
)

logger = get_logger("merid.event_venues.kalshi.stop_candidate")


# ── Environment-driven gates ──────────────────────────────────────────────────
def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").lower()
    return val in ("1", "true", "yes") if val else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# Default: stop candidates are logged but never submitted automatically.
ENABLE_STOP_CANDIDATE_SUBMISSION = _env_bool(
    "MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", False
)


def stop_submission_enabled() -> bool:
    """Return True when stop candidates may be converted into live orders.

    The resolved live config is the authority once it is available; until then
    the legacy ``MERID_ENABLE_STOP_CANDIDATE_SUBMISSION`` env var is used so
    existing replay and unit tests continue to work.  ``MERID_STOP_SUBMISSION_KILL=1``
    is an emergency kill switch that overrides both.
    """
    if _env_bool("MERID_STOP_SUBMISSION_KILL", False):
        return False

    try:
        from merid.config.live_config import get_resolved_live_config

        resolved = get_resolved_live_config(allow_unresolved=True)
        if resolved.resolved:
            return resolved.stop_candidate_submission_enabled
    except Exception:
        pass

    # Default to False (fail-closed) so monkeypatch.delenv() in tests and
    # missing env both disable automatic submission.
    return _env_bool(
        "MERID_ENABLE_STOP_CANDIDATE_SUBMISSION", False
    )


# Bounded liquidation policy: stop exits are submitted at
# ``best executable bid - STOP_MAX_SLIPPAGE_CENTS`` (floor 1c) so a stale
# trigger price cannot sweep a thin book to an unbounded low.
STOP_MAX_SLIPPAGE_CENTS = _env_int("MERID_STOP_MAX_SLIPPAGE_CENTS", 3)

# Trigger reasons that are explicit price/operational stops.  They do not
# require a model fair value or edge persistence to be submitted.
PRICE_STOP_TRIGGER_REASONS = frozenset({
    "POSITION_MONITOR_STOP",
    "STOP_LOSS",
    "HARD_STOP",
    "SOFT_STOP",
    "TRAILING_STOP",
    "EDGE_DECAY",
    "OPERATIONAL_RISK",
    "STALE_DATA",
    "POSITION_MISMATCH",
})

# Map a stop-candidate trigger reason to a canonical safety exit-reason so the
# order-router and execution-risk-firewall treat the close as a protective exit
# (parentage may be backfilled from cache, but safety classification lets it
# proceed even when the cache entry-fill linkage is temporarily unavailable).
_STOP_TRIGGER_TO_EXIT_REASON = {
    "HARD_STOP": "HARD_STOP",
    "SOFT_STOP": "SOFT_STOP",
    "TRAILING_STOP": "TRAILING_STOP",
    "POSITION_MONITOR_STOP": "STOP_LOSS",
    "STOP_LOSS": "STOP_LOSS",
    "OPERATIONAL_RISK": "RISK",
    "STALE_DATA": "STALE_DATA",
    "POSITION_MISMATCH": "RISK",
    "UNIFIED_POLICY_STOP": "STOP_LOSS",
    "EDGE_STOP": "STOP_LOSS",
    "EDGE_DECAY": "EDGE_DECAY",
}

# Cutoff and freshness constants (seconds / ms).
EXIT_CUTOFF_SECONDS = _env_int("MERID_EXIT_CUTOFF_SECONDS", 60)
MAX_EXIT_QUOTE_AGE_MS = _env_int("MERID_MAX_EXIT_QUOTE_AGE_MS", 10_000)
MAX_POSITION_AGE_MS = _env_int("MERID_MAX_POSITION_AGE_MS", 10_000)
MIN_HOLD_MS = _env_int("MERID_MIN_HOLD_MS", 2_000)

# Edge-stop persistence and buffers.
STOP_EDGE_MIN_CONSECUTIVE = _env_int("MERID_STOP_EDGE_MIN_CONSECUTIVE", 3)
STOP_EDGE_HYSTERESIS_CENTS = _env_int("MERID_STOP_EDGE_HYSTERESIS_CENTS", 1)
STOP_EDGE_TOTAL_EXIT_COST_CENTS = _env_int(
    "MERID_STOP_EDGE_TOTAL_EXIT_COST_CENTS", 2
)

# ── Degraded-exit reevaluation (2026-10-04) ──────────────────────────────────
# A rejected protective exit must not be the terminal state of a protective
# exit.  When the execution firewall refuses a stop IOC because the stated
# limit cannot fill at available depth (``limit_not_executable``), the
# position is still live binary tail risk.  The residual branch reevaluates
# hold-vs-exit against the *actual* depth-weighted VWAP and either submits
# one bounded degraded IOC or durably records an explicit hold-to-settlement
# decision.  Submission stays env-gated; the decision event is always
# recorded so observe-only mode still produces replayable telemetry.
STOP_DEGRADED_RESIDUAL_SLIP_CENTS = _env_int(
    "MERID_STOP_DEGRADED_RESIDUAL_SLIP_C", 2
)


def degraded_exit_enabled() -> bool:
    return _env_bool("MERID_STOP_DEGRADED_EXIT_ENABLED", False)


_NON_EXECUTABLE_VWAP_RE = re.compile(r"vwap=(\d+)")


def parse_non_executable_vwap_cents(reason: Any) -> Optional[int]:
    """Return the firewall's depth-weighted VWAP from a
    ``limit_not_executable`` rejection reason, else None."""
    r = str(reason or "").lower()
    if "limit_not_executable" not in r:
        return None
    m = _NON_EXECUTABLE_VWAP_RE.search(r)
    return int(m.group(1)) if m else None

# Settlement-aware phase constants (seconds).
SETTLEMENT_CLOSE_BUFFER_SECONDS = _env_int(
    "MERID_SETTLEMENT_CLOSE_BUFFER_SECONDS", 60
)
STOP_NO_NORMAL_STOP_BELOW_SECONDS = _env_int(
    "MERID_STOP_NO_NORMAL_STOP_BELOW_SECONDS", 90
)
STOP_STRONG_INVALIDATION_BELOW_SECONDS = _env_int(
    "MERID_STOP_STRONG_INVALIDATION_BELOW_SECONDS", 300
)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StopCandidate:
    """Immutable stop-candidate event.

    All size/position fields use signed-YES centi-contracts (positive = long
    YES, negative = long NO).  `held_contract` is derived from the sign.
    """

    market_ticker: str
    trigger_reason: str
    position_from_exchange_cc: int
    source_book_sequence: Optional[int] = None
    source_book_age_ms: Optional[int] = None
    fair_value_cents: Optional[int] = None
    executable_exit_cents: Optional[int] = None
    predicted_net_pnl_cents: Optional[int] = None
    total_exit_cost_cents: Optional[int] = None
    hysteresis_cents: Optional[int] = None
    consecutive_edge_below: int = 0
    quote_age_ms: Optional[int] = None
    position_snapshot_age_ms: Optional[int] = None
    seconds_to_expiry: Optional[float] = None
    candidate_id: str = field(default_factory=lambda: f"sc-{uuid.uuid4().hex[:12]}")
    created_at: float = field(default_factory=time.time)
    model_fair_value_cents: Optional[int] = None  # P(YES) from external/model, in cents
    entry_price_cents: Optional[int] = None
    held_contract: Optional[Literal["yes", "no"]] = None

    # Edge-decay telemetry (2026-08-25): record entry/current edge and the
    # derived hybrid stop level so the 7-day backtest can replay the decision.
    entry_edge_cents: Optional[int] = None
    current_edge_cents: Optional[int] = None
    edge_decay_exit_cents: Optional[int] = None
    stop_level_cents: Optional[int] = None

    def __post_init__(self) -> None:
        # Derive the held contract deterministically from the signed position.
        if self.held_contract is None and self.position_from_exchange_cc is not None:
            side, _ = from_signed_yes_exposure(self.position_from_exchange_cc)
            object.__setattr__(self, "held_contract", side)

    @property
    def held_contracts_cc(self) -> int:
        return abs(self.position_from_exchange_cc)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "candidate_id": self.candidate_id,
            "created_at": self.created_at,
            "market_ticker": self.market_ticker,
            "trigger_reason": self.trigger_reason,
            "position_from_exchange_cc": self.position_from_exchange_cc,
            "held_contract": self.held_contract,
            "source_book_sequence": self.source_book_sequence,
            "source_book_age_ms": self.source_book_age_ms,
            "fair_value_cents": self.fair_value_cents,
            "model_fair_value_cents": self.model_fair_value_cents,
            "executable_exit_cents": self.executable_exit_cents,
            "predicted_net_pnl_cents": self.predicted_net_pnl_cents,
            "total_exit_cost_cents": self.total_exit_cost_cents,
            "hysteresis_cents": self.hysteresis_cents,
            "consecutive_edge_below": self.consecutive_edge_below,
            "quote_age_ms": self.quote_age_ms,
            "position_snapshot_age_ms": self.position_snapshot_age_ms,
            "seconds_to_expiry": self.seconds_to_expiry,
            "entry_price_cents": self.entry_price_cents,
            "entry_edge_cents": self.entry_edge_cents,
            "current_edge_cents": self.current_edge_cents,
            "edge_decay_exit_cents": self.edge_decay_exit_cents,
            "stop_level_cents": self.stop_level_cents,
        }
        return d

    def to_log_line(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ── Ledger ────────────────────────────────────────────────────────────────────

@dataclass
class StopCandidateLedger:
    """In-memory ledger of stop candidates.  Not a durable store; logs persist."""

    _candidates: List[StopCandidate] = field(default_factory=list)
    _submissions: List[Dict[str, Any]] = field(default_factory=list)

    def record(self, candidate: StopCandidate) -> None:
        self._candidates.append(candidate)
        logger.warning(
            "[STOP-CANDIDATE] %s (submission gated by stop_submission_enabled())",
            candidate.to_log_line(),
        )
        try:
            self._persist(candidate)
        except Exception as exc:
            logger.debug("[STOP-CANDIDATE] failed to persist: %s", exc)

    def record_submission(
        self,
        candidate: StopCandidate,
        result: Any,
        *,
        submitted_price_cents: Optional[int] = None,
        reference_bid_cents: Optional[int] = None,
    ) -> None:
        fill_price_cents = None
        for attr in ("avg_fill_price_cents", "fill_price_cents", "price_cents"):
            val = getattr(result, attr, None)
            if val is not None:
                try:
                    fill_price_cents = int(val)
                    break
                except (TypeError, ValueError):
                    pass
        realized_slippage_cents = (
            reference_bid_cents - fill_price_cents
            if (reference_bid_cents is not None and fill_price_cents is not None)
            else None
        )
        record = {
            "candidate_id": candidate.candidate_id,
            "submitted_at": time.time(),
            "trigger_price_cents": candidate.executable_exit_cents,
            "reference_bid_cents": reference_bid_cents,
            "submitted_price_cents": submitted_price_cents,
            "fill_price_cents": fill_price_cents,
            "realized_slippage_cents": realized_slippage_cents,
            "result": _serialize_result(result),
        }
        self._submissions.append(record)
        logger.info(
            "[STOP-CANDIDATE-SUBMISSION] candidate=%s status=%s submitted=%sc fill=%sc slippage=%sc",
            candidate.candidate_id,
            getattr(result, "status", "unknown"),
            submitted_price_cents,
            fill_price_cents,
            realized_slippage_cents,
        )

    def record_residual_decision(
        self, candidate: StopCandidate, record: Dict[str, Any]
    ) -> None:
        """Persist a post-rejection residual-exposure decision.

        Every rejected protective exit ends in exactly one durable state:
        ``DEGRADED_EXIT_APPROVED`` (submitted / observe-only), or
        ``HOLD_TO_SETTLEMENT_APPROVED`` / ``RESIDUAL_RISK_BREACH``.  The
        record keeps the trigger, fair value, executable VWAP, both price
        bounds, and the submitted limit so stop-to-settlement counterfactuals
        can score the decision ex post.
        """
        entry = {
            "record_type": "residual_decision",
            "candidate_id": candidate.candidate_id,
            "recorded_at": time.time(),
            **record,
        }
        self._submissions.append(entry)
        log = logger.warning
        if record.get("decision") == "RESIDUAL_RISK_BREACH":
            log = logger.critical
        log(
            "[STOP-RESIDUAL-%s] candidate=%s ticker=%s trigger=%s "
            "fair=%sc vwap=%sc basis=%s",
            record.get("decision", "UNKNOWN"),
            candidate.candidate_id,
            candidate.market_ticker,
            candidate.trigger_reason,
            record.get("fair_value_cents"),
            record.get("degraded_vwap_cents"),
            record.get("basis"),
        )
        try:
            log_dir = Path(__file__).resolve().parents[3] / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "stop_candidates.jsonl"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as exc:
            logger.debug("[STOP-CANDIDATE] failed to persist residual decision: %s", exc)

    def recent(self, n: int = 100) -> List[StopCandidate]:
        return self._candidates[-n:]

    def _persist(self, candidate: StopCandidate) -> None:
        """Append to a dedicated stop-candidate log for replay analysis."""
        log_dir = Path(__file__).resolve().parents[3] / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "stop_candidates.jsonl"
        record = candidate.to_dict()
        record["_recorded_at"] = time.time()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")


_ledger = StopCandidateLedger()


def get_stop_candidate_ledger() -> StopCandidateLedger:
    return _ledger


def record_stop_candidate(candidate: StopCandidate) -> None:
    get_stop_candidate_ledger().record(candidate)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialize_result(result: Any) -> Dict[str, Any]:
    if result is None:
        return {}
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if hasattr(result, "__dict__"):
        return {k: v for k, v in result.__dict__.items() if not k.startswith("_")}
    return {"repr": repr(result)}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int_cents(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        if d != d.to_integral_value():
            return None
        return int(d)
    except Exception:
        return None


def _kalshi_taker_fee_cents(qty_cc: int, price_cents: int, fee_rate_bps: float = 10.0) -> int:
    """Estimate taker fee in cents.  Default 0.1% (10 bps) of notional.

    ``qty_cc`` is the canonical integer number of centi-contracts.
    """
    qty_cc = int(qty_cc)
    price_cents = int(price_cents)
    notional_cents = Decimal(qty_cc * price_cents) / Decimal(100)
    fee = notional_cents * Decimal(str(fee_rate_bps)) / Decimal(10_000)
    if fee > 0:
        return max(1, int(fee.to_integral_value(rounding=ROUND_HALF_UP)))
    return 0


# ── Edge stop evaluation ──────────────────────────────────────────────────────

def evaluate_edge_stop(
    fair_value_cents: Optional[int],
    executable_exit_cents: Optional[int],
    total_exit_cost_cents: Optional[int] = None,
    hysteresis_cents: Optional[int] = None,
) -> bool:
    """Return True when the model fair value no longer supports holding.

    For a long YES position:
        close_long_yes = fair_yes_cents + total_exit_cost + hysteresis <= best_yes_bid

    For a long NO position the caller must supply the executable NO bid in
    ``executable_exit_cents`` and the NO-side fair value in ``fair_value_cents``.
    """
    if fair_value_cents is None or executable_exit_cents is None:
        return False

    costs = total_exit_cost_cents if total_exit_cost_cents is not None else STOP_EDGE_TOTAL_EXIT_COST_CENTS
    hyst = hysteresis_cents if hysteresis_cents is not None else STOP_EDGE_HYSTERESIS_CENTS

    if not (1 <= executable_exit_cents <= 99):
        return False

    return fair_value_cents + costs + hyst <= executable_exit_cents


def settlement_phase_allows_stop(
    seconds_to_expiry: Optional[float],
    trigger_reason: str,
    consecutive_edge_below: int = 0,
) -> Tuple[bool, str]:
    """Return (allowed, reason) for a stop candidate based on time-to-expiry.

    Time remaining:
    - > 5 min: model/edge stop allowed, requiring persistence.
    - 1-5 min: require stronger invalidation (more consecutive observations).
    - < 60-90 sec: no automatic "normal" stop; only explicit model invalidation
      or operational-risk exit.
    - Within close window: block.
    """
    if seconds_to_expiry is None:
        return True, "no_expiry_info"

    if seconds_to_expiry <= SETTLEMENT_CLOSE_BUFFER_SECONDS:
        return False, f"settlement_close_window:seconds_to_expiry={seconds_to_expiry:.1f}"

    # Explicit price/operational stops do not need edge persistence; they are
    # an unconditional invalidation of the position outside the close window.
    if trigger_reason in PRICE_STOP_TRIGGER_REASONS:
        return True, f"price_stop_allowed:trigger={trigger_reason}"

    if seconds_to_expiry <= STOP_NO_NORMAL_STOP_BELOW_SECONDS:
        if trigger_reason in ("OPERATIONAL_RISK", "STALE_DATA", "POSITION_MISMATCH"):
            return True, f"operational_exit_allowed:seconds_to_expiry={seconds_to_expiry:.1f}"
        return False, f"no_normal_stop_near_expiry:seconds_to_expiry={seconds_to_expiry:.1f}"

    if seconds_to_expiry <= STOP_STRONG_INVALIDATION_BELOW_SECONDS:
        if consecutive_edge_below >= STOP_EDGE_MIN_CONSECUTIVE + 2:
            return True, f"strong_invalidations_sufficient:consecutive={consecutive_edge_below}"
        return False, (
            f"needs_stronger_invalidations_near_expiry:"
            f"consecutive={consecutive_edge_below}"
        )

    if consecutive_edge_below < STOP_EDGE_MIN_CONSECUTIVE:
        return False, f"insufficient_edge_persistence:consecutive={consecutive_edge_below}"

    return True, "model_edge_stop_allowed"


# ── Stop-order invariants ─────────────────────────────────────────────────────

class StopOrderInvariantError(ValueError):
    """A stop-generated order violated a non-negotiable execution invariant."""


def validate_stop_order_invariants(
    order: Any,
    exchange_position_cc: int,
    market_close_time: Optional[datetime] = None,
    quote_age_ms: Optional[int] = None,
    position_snapshot_age_ms: Optional[int] = None,
    now: Optional[datetime] = None,
    seconds_to_expiry: Optional[float] = None,
) -> None:
    """Hard-reject a stop-generated close order that violates invariants.

    ``order`` may be a `CanonicalOrderIntent` or any duck-typed object with the
    required attributes (`market_ticker`, `contract`, `action`, `qty_cc`,
    `reduce_only`, `time_in_force`, `expected_position_before`,
    `expected_position_after`).
    """
    if now is None:
        now = _now_utc()

    market_ticker = getattr(order, "market_ticker", "")

    if not getattr(order, "reduce_only", False):
        raise StopOrderInvariantError(
            f"stop_order_not_reduce_only:ticker={market_ticker}"
        )

    tif = (getattr(order, "time_in_force", "") or "").lower()
    if tif not in {"ioc", "fok", "immediate_or_cancel", "fill_or_kill"}:
        raise StopOrderInvariantError(
            f"stop_order_invalid_tif:ticker={market_ticker}:tif={tif}"
        )

    if exchange_position_cc == 0:
        raise StopOrderInvariantError(
            f"stop_order_flat_position:ticker={market_ticker}"
        )

    qty_cc = int(getattr(order, "qty_cc", 0) or 0)
    if qty_cc <= 0:
        raise StopOrderInvariantError(
            f"stop_order_non_positive_qty:ticker={market_ticker}:qty_cc={qty_cc}"
        )
    if qty_cc > abs(exchange_position_cc):
        raise StopOrderInvariantError(
            f"stop_order_over_close:ticker={market_ticker}:qty={qty_cc}:position={exchange_position_cc}"
        )

    expected_before = int(getattr(order, "expected_position_before", 0) or 0)
    if expected_before != exchange_position_cc:
        raise StopOrderInvariantError(
            f"stop_order_position_before_mismatch:ticker={market_ticker}:"
            f"expected={expected_before}:exchange={exchange_position_cc}"
        )

    expected_after = int(getattr(order, "expected_position_after", 0) or 0)
    if expected_after == 0:
        # Full close: the order must exactly offset the position.
        if qty_cc != abs(exchange_position_cc):
            raise StopOrderInvariantError(
                f"stop_order_partial_full_close:ticker={market_ticker}:qty={qty_cc}:position={exchange_position_cc}"
            )
    elif abs(expected_after) >= abs(exchange_position_cc):
        raise StopOrderInvariantError(
            f"stop_order_did_not_reduce:ticker={market_ticker}:after={expected_after}"
        )
    elif expected_after * exchange_position_cc < 0:
        raise StopOrderInvariantError(
            f"stop_order_flipped_position:ticker={market_ticker}:after={expected_after}"
        )

    # Contract / action must close the held side.  The canonical mapping is:
    #   long YES -> SELL_YES   (contract=yes, action=sell)
    #   long NO  -> SELL_NO    (contract=no,  action=sell)
    held_side, _ = from_signed_yes_exposure(exchange_position_cc)
    order_contract = (getattr(order, "contract", "") or "").lower()
    order_action = (getattr(order, "action", "") or "").lower()

    if order_action != "sell" or order_contract != held_side:
        raise StopOrderInvariantError(
            f"stop_order_wrong_side:ticker={market_ticker}:"
            f"contract={order_contract}:action={order_action}:held={held_side}"
        )

    # Market-close cutoff.
    cutoff_seconds = _env_int("MERID_EXIT_CUTOFF_SECONDS", 60)
    if market_close_time is not None:
        if market_close_time.tzinfo is None:
            market_close_time = market_close_time.replace(tzinfo=timezone.utc)
        if now >= market_close_time - timedelta(seconds=cutoff_seconds):
            raise StopOrderInvariantError(
                f"stop_order_inside_close_cutoff:ticker={market_ticker}:"
                f"time_to_close={(market_close_time - now).total_seconds():.1f}s"
            )
    elif seconds_to_expiry is not None and seconds_to_expiry <= cutoff_seconds:
        raise StopOrderInvariantError(
            f"stop_order_inside_close_cutoff:ticker={market_ticker}:seconds_to_expiry={seconds_to_expiry:.1f}s"
        )

    # Freshness guards.
    if quote_age_ms is not None and quote_age_ms > MAX_EXIT_QUOTE_AGE_MS:
        raise StopOrderInvariantError(
            f"stop_order_stale_quote:ticker={market_ticker}:age_ms={quote_age_ms}"
        )
    if position_snapshot_age_ms is not None and position_snapshot_age_ms > MAX_POSITION_AGE_MS:
        raise StopOrderInvariantError(
            f"stop_order_stale_position_snapshot:ticker={market_ticker}:age_ms={position_snapshot_age_ms}"
        )


def _get_market_state(ticker: str) -> Tuple[Optional[Any], Optional[Any]]:
    """Return (kalshi_state, unified_state) for ``ticker`` if available."""
    try:
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        store = get_kalshi_market_state_store()
        kalshi = store.get(ticker)
        unified = store.get_unified(ticker) if hasattr(store, "get_unified") else None
        return kalshi, unified
    except Exception as exc:
        logger.debug("[STOP-CANDIDATE] market state lookup failed for %s: %s", ticker, exc)
        return None, None


def _get_executable_exit_cents(
    state: Any, held_contract: Literal["yes", "no"]
) -> Optional[int]:
    """Return the best bid for the held contract from market state.

    Divergence-aware: when the WS top-of-book is internally locked
    (bid >= ask) and a fresh REST quote diverges materially, the WS bid is a
    phantom — an exit limit priced off it can never fill (the order asks for
    bids that no longer exist).  A locked top that disagrees with a
    just-fetched REST book is a split-tape artifact, so the fresh REST side
    becomes the executable reference for the held contract's bid.
    """
    if state is None:
        return None

    book = getattr(state, "book", None)

    bid: Optional[int] = None
    if held_contract == "yes":
        # Prefer KalshiMarketState.best_bid_cents (YES bid) or OrderbookSnapshot.
        bid = getattr(state, "best_bid_cents", None)
        if bid is not None:
            bid = _safe_int_cents(bid)
        elif book is not None:
            if hasattr(book, "best_yes_bid"):
                bid = _safe_int_cents(getattr(book, "best_yes_bid"))
            elif getattr(book, "yes_bids", None):
                bid = _safe_int_cents(book.yes_bids[0].price_cents)
    else:
        # Prefer explicit NO bid; otherwise derive from opposing YES ask.
        no_bid = getattr(state, "no_bid_cents", None)
        if no_bid is not None:
            bid = _safe_int_cents(no_bid)
        elif book is not None:
            if getattr(book, "no_bids", None):
                bid = _safe_int_cents(book.no_bids[0].price_cents)
            elif hasattr(book, "best_no_bid"):
                bid = _safe_int_cents(getattr(book, "best_no_bid"))
        if bid is None:
            yes_ask = getattr(state, "best_ask_cents", None) or (
                getattr(book, "best_yes_ask", None)
                if book
                else None
            )
            if yes_ask is not None:
                bid = _safe_int_cents(100 - int(yes_ask))

    corrected = _locked_ws_divergent_rest_bid(state, held_contract)
    if corrected is not None and bid is not None and corrected != bid:
        logger.warning(
            "[EXIT-QUOTE-DIVERGENT] held=%s ws_bid=%sc rest_bid=%sc — "
            "locked WS top diverges from fresh REST; pricing exit off REST",
            held_contract, bid, corrected,
        )
        return corrected
    if corrected is not None and bid is None:
        return corrected
    return bid


def _locked_ws_divergent_rest_bid(
    state: Any, held_contract: Literal["yes", "no"]
) -> Optional[int]:
    """Return the fresh REST-derived bid for the held contract when the WS
    top-of-book is locked AND diverges from a fresh REST quote beyond
    ``MERID_EXIT_QUOTE_DIVERGENCE_CENTS`` (default 3c); else ``None``.

    A locked WS top (bid >= ask) that disagrees with a just-fetched REST book
    means the local ladder lost a repricing burst — the same corruption class
    the entry router treats as a split-tape artifact.  For exits the failure
    is asymmetric: pricing a reduce-only sell off a phantom bid produces an
    IOC that asks for prices no longer on the exchange and can never fill.
    """
    try:
        ws_bid = getattr(state, "last_ws_bid_cents", None)
        ws_ask = getattr(state, "last_ws_ask_cents", None)
        if ws_bid is None or ws_ask is None or int(ws_bid) < int(ws_ask):
            return None  # unlocked or absent WS top — not the locked-book case

        rest_bid = getattr(state, "last_rest_bid_cents", None)
        rest_ask = getattr(state, "last_rest_ask_cents", None)
        rest_ts = float(getattr(state, "last_rest_quote_update_ts", 0.0) or 0.0)
        max_rest_age_s = float(os.environ.get("MERID_EXIT_QUOTE_REST_MAX_AGE_S", "5.0"))
        if (
            rest_bid is None
            or rest_ask is None
            or rest_ts <= 0
            or (time.monotonic() - rest_ts) > max_rest_age_s
        ):
            return None

        ws_held_bid = int(ws_bid) if held_contract == "yes" else 100 - int(ws_ask)
        rest_held_bid = int(rest_bid) if held_contract == "yes" else 100 - int(rest_ask)
        div_cap = int(os.environ.get("MERID_EXIT_QUOTE_DIVERGENCE_CENTS", "3"))
        if abs(ws_held_bid - rest_held_bid) <= div_cap:
            return None
        return rest_held_bid
    except Exception:
        return None


def _model_fair_value_max_age_s() -> float:
    try:
        return max(1.0, float(os.environ.get("MERID_MODEL_FAIR_VALUE_MAX_AGE_MS", "120000")) / 1000.0)
    except Exception:
        return 120.0


def _get_fair_value_cents(state: Any, held_contract: Literal["yes", "no"]) -> Optional[int]:
    """Return model fair value in the held contract's price space."""
    # The active model's P(YES), published by the agent decision path, is the
    # most faithful fair value — it is the same probability entries use.  A
    # stale model value is worse than none: a market whose model stopped
    # updating must not borrow a frozen probability for a live EV decision.
    unified = state
    if hasattr(unified, "model_fair_prob") and unified.model_fair_prob is not None:
        try:
            prob_ts = float(getattr(unified, "model_fair_prob_ts", 0.0) or 0.0)
            age_s = time.time() - prob_ts if prob_ts > 0 else float("inf")
            if age_s <= _model_fair_value_max_age_s():
                yes_fair = int(round(float(unified.model_fair_prob) * 100))
                if 1 <= yes_fair <= 99:
                    if held_contract == "yes":
                        return yes_fair
                    return 100 - yes_fair
        except Exception:
            pass

    # Unified market state carries external_fair_value as P(YES).
    if hasattr(unified, "external_fair_value") and unified.external_fair_value is not None:
        try:
            yes_fair = int(round(float(unified.external_fair_value) * 100))
            if not 1 <= yes_fair <= 99:
                return None
            if held_contract == "yes":
                return yes_fair
            return 100 - yes_fair
        except Exception:
            pass

    # Fall back to implied probability.
    if hasattr(unified, "implied_prob") and unified.implied_prob is not None:
        try:
            yes_fair = int(round(float(unified.implied_prob) * 100))
            if not 1 <= yes_fair <= 99:
                return None
            if held_contract == "yes":
                return yes_fair
            return 100 - yes_fair
        except Exception:
            pass

    return None


def _seconds_to_expiry(state: Any) -> Optional[float]:
    return getattr(state, "seconds_to_expiry", None)


def _book_age_ms(state: Any) -> Optional[int]:
    updated = getattr(state, "book_updated_ts", None) or getattr(state, "last_book_update_ts", None)
    if not isinstance(updated, (int, float)) or updated <= 0:
        return None
    age_s = time.monotonic() - updated
    return max(0, int(age_s * 1000))


def _book_sequence(state: Any) -> Optional[int]:
    return getattr(state, "book_sequence", None)


# ── Building a stop candidate from position / market state ────────────────────

def build_stop_candidate(
    market_ticker: str,
    exchange_position_cc: int,
    trigger_reason: str,
    *,
    entry_price_cents: Optional[int] = None,
    fair_value_cents: Optional[int] = None,
    executable_exit_cents: Optional[int] = None,
    kalshi_state: Optional[Any] = None,
    unified_state: Optional[Any] = None,
    quote_age_ms: Optional[int] = None,
    position_snapshot_age_ms: Optional[int] = None,
    consecutive_edge_below: int = 0,
    total_exit_cost_cents: Optional[int] = None,
    hysteresis_cents: Optional[int] = None,
    seconds_to_expiry: Optional[float] = None,
    source_book_sequence: Optional[int] = None,
    hard_stop_cents: Optional[int] = None,
) -> StopCandidate:
    """Build a `StopCandidate` from live market and position state."""
    # Canonical exposure is always an integer number of centi-contracts.
    exchange_position_cc = int(exchange_position_cc)
    side, qty = from_signed_yes_exposure(exchange_position_cc)
    qty = int(qty)

    # Fair value comes from the unified/model state if available; executable
    # exit comes from the venue order book (kalshi_state) if available.
    fair = fair_value_cents if fair_value_cents is not None else (
        _get_fair_value_cents(unified_state, side) if unified_state
        else (_get_fair_value_cents(kalshi_state, side) if kalshi_state else None)
    )
    executable = executable_exit_cents if executable_exit_cents is not None else (
        _get_executable_exit_cents(kalshi_state, side) if kalshi_state
        else (_get_executable_exit_cents(unified_state, side) if unified_state else None)
    )
    state = unified_state or kalshi_state
    seconds = seconds_to_expiry if seconds_to_expiry is not None else (_seconds_to_expiry(state) if state else None)
    book_age = quote_age_ms if quote_age_ms is not None else (_book_age_ms(state) if state else None)
    book_seq = source_book_sequence if source_book_sequence is not None else (_book_sequence(state) if state else None)

    predicted_pnl = None
    if entry_price_cents is not None and executable is not None and qty > 0:
        # PnL in the held contract's price space, in cents.
        pnl_per = executable - entry_price_cents
        gross_cents = Decimal(qty) * Decimal(pnl_per) / Decimal(100)
        fee_cents = _kalshi_taker_fee_cents(qty, executable)
        predicted_pnl = int(
            (gross_cents - Decimal(fee_cents)).to_integral_value(rounding=ROUND_HALF_UP)
        )

    if total_exit_cost_cents is None:
        total_exit_cost_cents = STOP_EDGE_TOTAL_EXIT_COST_CENTS
    if hysteresis_cents is None:
        hysteresis_cents = STOP_EDGE_HYSTERESIS_CENTS

    # Edge-decay telemetry.  Entry/current edge are in the held contract's price
    # space: positive means the model thought the position had an edge, negative
    # means the model has flipped against the position.  edge_decay_exit is the
    # price at which current edge would be zero (model fair = market price).
    entry_edge = None
    current_edge = None
    edge_decay_exit = None
    stop_level = None
    if fair is not None and entry_price_cents is not None:
        entry_edge = fair - entry_price_cents
    if fair is not None and executable is not None:
        current_edge = fair - executable
        edge_decay_exit = fair
    if hard_stop_cents is not None and edge_decay_exit is not None:
        stop_level = max(hard_stop_cents, edge_decay_exit)
    elif hard_stop_cents is not None:
        stop_level = hard_stop_cents
    elif edge_decay_exit is not None:
        stop_level = edge_decay_exit

    return StopCandidate(
        market_ticker=market_ticker,
        trigger_reason=trigger_reason,
        position_from_exchange_cc=exchange_position_cc,
        held_contract=side,
        source_book_sequence=book_seq,
        source_book_age_ms=book_age,
        fair_value_cents=fair,
        model_fair_value_cents=fair,
        executable_exit_cents=executable,
        predicted_net_pnl_cents=predicted_pnl,
        total_exit_cost_cents=total_exit_cost_cents,
        hysteresis_cents=hysteresis_cents,
        consecutive_edge_below=consecutive_edge_below,
        quote_age_ms=book_age,
        position_snapshot_age_ms=position_snapshot_age_ms,
        seconds_to_expiry=seconds,
        entry_price_cents=entry_price_cents,
        entry_edge_cents=entry_edge,
        current_edge_cents=current_edge,
        edge_decay_exit_cents=edge_decay_exit,
        stop_level_cents=stop_level,
    )


# ── Submission ────────────────────────────────────────────────────────────────

async def _maybe_degraded_stop_exit(
    candidate: StopCandidate,
    primary_result: Any,
    *,
    held_side: str,
    held_contracts: int,
) -> None:
    """Residual-exposure branch for a non-executable protective exit.

    Runs after the primary stop IOC is rejected with ``limit_not_executable``.
    Compares depth-weighted liquidation proceeds (firewall VWAP, net of exit
    costs) against holding to settlement at the model's fair value:

        exit approved  <=>  fair + exit_costs + hysteresis <= degraded_vwap
                           <=>  V_exit > V_hold - C_carry

    When approved, one bounded degraded IOC is submitted at
    ``min(vwap, fresh_bid) - residual_slip`` under a fresh ``dg1`` client
    order id (the original coid was consumed by the venue).  When not
    approved, or when the fair-value basis is missing, an explicit
    HOLD_TO_SETTLEMENT / RESIDUAL_RISK_BREACH decision is persisted so the
    residual position is never silently carried to expiry.  Automatic
    submission remains env-gated; observe-only mode still records the
    decision it would have taken.
    """
    vwap_cents = parse_non_executable_vwap_cents(
        getattr(primary_result, "reason", None)
    )
    if vwap_cents is None or held_contracts <= 0:
        return

    fair = candidate.fair_value_cents
    record: Dict[str, Any] = {
        "ticker": candidate.market_ticker,
        "trigger_reason": candidate.trigger_reason,
        "held_contracts": held_contracts,
        "fair_value_cents": fair,
        "degraded_vwap_cents": vwap_cents,
        "primary_reject_reason": str(getattr(primary_result, "reason", "") or ""),
        "submitted_limit_cents": getattr(primary_result, "price_cents", None),
        "degraded_exit_enabled": degraded_exit_enabled(),
        "seconds_to_expiry": candidate.seconds_to_expiry,
    }

    if fair is None:
        # Price-triggered stops carry no model basis; without fair value the
        # hold-vs-exit comparison is impossible — surface the residual risk
        # instead of silently holding to settlement.
        record["decision"] = "RESIDUAL_RISK_BREACH"
        record["basis"] = "no_fair_value"
        get_stop_candidate_ledger().record_residual_decision(candidate, record)
        return

    exit_ok = evaluate_edge_stop(
        fair,
        vwap_cents,
        candidate.total_exit_cost_cents,
        candidate.hysteresis_cents,
    )
    if not exit_ok:
        record["decision"] = "HOLD_TO_SETTLEMENT_APPROVED"
        record["basis"] = "fair_above_degraded_exit_value"
        get_stop_candidate_ledger().record_residual_decision(candidate, record)
        return

    # Degraded exit is economically justified.  Re-fetch the executable bid so
    # the submitted limit prices off the freshest book, not the stale trigger.
    kalshi2, unified2 = _get_market_state(candidate.market_ticker)
    fresh_bid = _get_executable_exit_cents(unified2 or kalshi2, held_side)
    record["fresh_bid_cents"] = fresh_bid
    if fresh_bid is None or not (1 <= fresh_bid <= 99):
        record["decision"] = "RESIDUAL_RISK_BREACH"
        record["basis"] = "no_executable_depth"
        get_stop_candidate_ledger().record_residual_decision(candidate, record)
        return

    degraded_limit = max(
        1, min(vwap_cents, fresh_bid) - STOP_DEGRADED_RESIDUAL_SLIP_CENTS
    )
    record["degraded_limit_cents"] = degraded_limit

    if not degraded_exit_enabled():
        record["decision"] = "DEGRADED_EXIT_APPROVED"
        record["basis"] = "observe_only_submission_disabled"
        get_stop_candidate_ledger().record_residual_decision(candidate, record)
        return

    from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

    kalshi_side = to_kalshi_side(held_side, "sell")
    intent = OrderIntent(
        ticker=candidate.market_ticker,
        side=held_side,
        action="sell",
        price_cents=degraded_limit,
        count=held_contracts,
        order_type="limit",
        time_in_force="ioc",
        source="stop_candidate_degraded",
        agent_id="stop_candidate",
        # Distinct identity per candidate so venue dedup cannot conflate the
        # degraded retry with the consumed primary coid.
        intent_id=f"stop_candidate:{candidate.candidate_id}:dg1",
        client_order_id=f"stopcand_{candidate.candidate_id}dg1"[:64],
        kalshi_side=kalshi_side,
        reduce_only=True,
        entry_or_exit="exit",
        exit_reason=_STOP_TRIGGER_TO_EXIT_REASON.get(
            candidate.trigger_reason, "STOP_LOSS"
        ),
        exit_policy_id=f"stop_candidate:{candidate.candidate_id}:degraded",
        reason=(
            f"degraded_stop_exit:{candidate.trigger_reason}:{candidate.candidate_id}"
        ),
        rationale=(
            f"degraded_exit:vwap={vwap_cents}:fair={fair}:{candidate.candidate_id}"
        ),
        snapshot_age_ms=float(candidate.quote_age_ms or 0),
    )
    result = await route_order_async(intent)
    record["decision"] = "DEGRADED_EXIT_APPROVED"
    record["basis"] = "degraded_ioc_submitted"
    record["result"] = _serialize_result(result)
    get_stop_candidate_ledger().record_residual_decision(candidate, record)


async def maybe_submit_stop_candidate(
    candidate: StopCandidate,
    *,
    force: bool = False,
) -> Optional[Any]:
    """Convert a validated `StopCandidate` to a reduce-only IOC close order.

    By default this only logs the candidate.  Automatic submission is gated by
    ``MERID_ENABLE_STOP_CANDIDATE_SUBMISSION=true`` or ``force=True``.

    Returns the `OrderResult` if submitted, otherwise an ``OrderResult`` with
    status ``rejected`` and a diagnostic reason.
    """
    if not (stop_submission_enabled() or force) or _env_bool("MERID_STOP_SUBMISSION_KILL", False):
        kill = _env_bool("MERID_STOP_SUBMISSION_KILL", False)
        reason = (
            "stop_candidate_submission_kill_switch" if kill
            else "stop_candidate_submission_disabled_until_replay_tests"
        )
        # High-severity alert: a stop fired but no protective exit was sent.
        logger.critical(
            "[ALERT][STOP-CANDIDATE-NOT-SUBMITTED] candidate=%s ticker=%s "
            "trigger=%s position_cc=%d executable_exit_cents=%s reason=%s",
            candidate.candidate_id,
            candidate.market_ticker,
            candidate.trigger_reason,
            candidate.position_from_exchange_cc,
            candidate.executable_exit_cents,
            reason,
        )
        record_stop_candidate(candidate)
        # Return a synthetic rejected result so callers do not misinterpret.
        try:
            from merid.event_venues.kalshi.order_router import OrderResult, TradingMode
            return OrderResult(
                status="rejected",
                mode=TradingMode.PAPER,
                reason=reason,
            )
        except Exception:
            return None

    from merid.event_venues.kalshi.order_intent_contract import (
        OrderIntentValidationError,
        fetch_fresh_signed_yes_exposure,
        normalize_order,
        validate_canonical_intent,
    )
    from merid.event_venues.kalshi.order_router import OrderIntent, OrderResult, TradingMode

    # ── Discretionary trigger classification (2026-09) ───────────────────────
    # A candidate that passes the submission flag is still not authorized to
    # trade live when its trigger is discretionary: all discretionary exits
    # are observe-only until the settlement-aligned EV gate is enabled and
    # validated.  Operational/emergency triggers (reconciliation, expiry
    # liquidation, manual, hard risk) keep their mechanical path.  Unknown
    # triggers fail closed.
    from merid.event_venues.kalshi.settlement_aligned_exit import (
        ExitClass,
        classify_trigger_reason,
        ev_exit_gate_enabled,
    )

    trigger_class = classify_trigger_reason(candidate.trigger_reason)
    if trigger_class == ExitClass.UNKNOWN or (
        trigger_class == ExitClass.DISCRETIONARY and not ev_exit_gate_enabled()
    ):
        reason = (
            "trigger_reason_unclassified"
            if trigger_class == ExitClass.UNKNOWN
            else "discretionary_trigger_observe_only"
        )
        logger.critical(
            "[ALERT][STOP-CANDIDATE-OBSERVE-ONLY] candidate=%s ticker=%s "
            "trigger=%s class=%s - candidate not submitted (reason=%s)",
            candidate.candidate_id,
            candidate.market_ticker,
            candidate.trigger_reason,
            trigger_class.value,
            reason,
        )
        record_stop_candidate(candidate)
        return OrderResult(
            status="rejected",
            mode=TradingMode.PAPER,
            reason=reason,
        )

    # 1. Fresh exchange position snapshot.
    t0 = time.monotonic()
    exchange_position_cc, position_avg_price_cents, position_side = (
        await fetch_fresh_signed_yes_exposure(
            candidate.market_ticker, timeout=1.0, fallback_to_cache=True
        )
    )

    if exchange_position_cc is None:
        exchange_position_cc = 0

    position_snapshot_age_ms = int((time.monotonic() - t0) * 1000)

    # 2. Reconcile against the candidate.
    if exchange_position_cc == 0:
        record_stop_candidate(candidate)
        return OrderResult(
            status="rejected",
            mode=TradingMode.PAPER,
            reason="stop_candidate_exchange_position_flat",
        )

    if exchange_position_cc != candidate.position_from_exchange_cc:
        logger.critical(
            "[STOP-CANDIDATE-RECONCILIATION] ticker=%s system_position=%d exchange_position=%d - "
            "CRITICAL mismatch, blocking stop submission",
            candidate.market_ticker,
            candidate.position_from_exchange_cc,
            exchange_position_cc,
        )
        record_stop_candidate(candidate)
        return OrderResult(
            status="rejected",
            mode=TradingMode.PAPER,
            reason="stop_candidate_position_reconciliation_mismatch",
        )

    # 3. Settlement / edge gating.
    allowed, gate_reason = settlement_phase_allows_stop(
        candidate.seconds_to_expiry,
        candidate.trigger_reason,
        candidate.consecutive_edge_below,
    )
    if not allowed:
        record_stop_candidate(candidate)
        return OrderResult(
            status="rejected",
            mode=TradingMode.PAPER,
            reason=f"stop_candidate_settlement_gate:{gate_reason}",
        )

    # Edge stops require a model fair value that has crossed the executable
    # liquidation value.  Explicit price/operational stops (e.g.
    # POSITION_MONITOR_STOP) are their own invalidation and skip this gate.
    is_price_stop = candidate.trigger_reason in PRICE_STOP_TRIGGER_REASONS
    if not is_price_stop:
        if candidate.fair_value_cents is None:
            record_stop_candidate(candidate)
            return OrderResult(
                status="rejected",
                mode=TradingMode.PAPER,
                reason="stop_candidate_no_fair_value",
            )

        edge_fired = evaluate_edge_stop(
            candidate.fair_value_cents,
            candidate.executable_exit_cents,
            candidate.total_exit_cost_cents,
            candidate.hysteresis_cents,
        )
        if not edge_fired:
            record_stop_candidate(candidate)
            return OrderResult(
                status="rejected",
                mode=TradingMode.PAPER,
                reason="stop_candidate_edge_not_breached",
            )

    # 4. Build the canonical close order.
    held_side, held_qty_cc = from_signed_yes_exposure(exchange_position_cc)
    if held_qty_cc <= 0:
        record_stop_candidate(candidate)
        return OrderResult(
            status="rejected",
            mode=TradingMode.PAPER,
            reason="stop_candidate_no_held_position",
        )

    # current OrderIntent.count is whole contracts, so fractional cc positions
    # cannot be precisely closed through this path.
    qty_cc = min(candidate.held_contracts_cc, held_qty_cc)
    if qty_cc <= 0 or qty_cc % 100 != 0:
        record_stop_candidate(candidate)
        return OrderResult(
            status="rejected",
            mode=TradingMode.PAPER,
            reason="stop_candidate_fractional_qty",
        )

    exit_bid = candidate.executable_exit_cents
    if exit_bid is None or not (1 <= exit_bid <= 99):
        # Fall back to best bid on the held side.
        kalshi, unified = _get_market_state(candidate.market_ticker)
        exit_bid = _get_executable_exit_cents(unified or kalshi, held_side)
        if exit_bid is None or not (1 <= exit_bid <= 99):
            record_stop_candidate(candidate)
            return OrderResult(
                status="rejected",
                mode=TradingMode.PAPER,
                reason="stop_candidate_no_executable_price",
            )

    # Bounded liquidation: cross at most STOP_MAX_SLIPPAGE_CENTS through the
    # observed best bid so a stale trigger cannot sweep the book to the floor.
    exit_price = max(1, exit_bid - STOP_MAX_SLIPPAGE_CENTS)
    logger.info(
        "[STOP-CANDIDATE-PRICING] candidate=%s ticker=%s trigger=%s "
        "entry=%dc bid=%dc fair=%dc entry_edge=%dc current_edge=%dc "
        "stop_level=%dc submitted_limit=%dc slippage_cap=%dc tte=%.1fs",
        candidate.candidate_id,
        candidate.market_ticker,
        candidate.trigger_reason,
        candidate.entry_price_cents or -1,
        exit_bid,
        candidate.fair_value_cents or -1,
        candidate.entry_edge_cents or -99,
        candidate.current_edge_cents or -99,
        candidate.stop_level_cents or -1,
        exit_price,
        STOP_MAX_SLIPPAGE_CENTS,
        candidate.seconds_to_expiry or -1.0,
    )

    kalshi_side = to_kalshi_side(held_side, "sell")

    pre_contracts = held_qty_cc // 100
    held_contracts = qty_cc // 100

    # Resolve durable parentage from the local cache so the exit is linked to
    # its entry fill/order.  If the cache is unavailable, the safety exit-reason
    # below still lets the protective close proceed.
    parentage_status = "UNKNOWN"
    parent_entry_fill_id: Optional[str] = None
    parent_entry_order_id: Optional[str] = None
    parent_entry_signal_id: Optional[str] = None
    exit_policy_id = f"stop_candidate:{candidate.candidate_id}"
    cached_position = None
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache

        cache = get_position_cache()
        if cache is not None:
            cached_position = cache.get_position(candidate.market_ticker)
    except Exception as cache_exc:
        logger.debug("[STOP-CANDIDATE] could not fetch local position for parentage: %s", cache_exc)

    if cached_position is not None:
        if getattr(cached_position, "exit_policy_id", None):
            exit_policy_id = cached_position.exit_policy_id
        if getattr(cached_position, "entry_fill_id", None):
            parent_entry_fill_id = cached_position.entry_fill_id
            parentage_status = "CANONICAL_FILL"
        if getattr(cached_position, "entry_order_id", None):
            parent_entry_order_id = cached_position.entry_order_id
            if parentage_status == "UNKNOWN":
                parentage_status = "ORDER_LINKED"
                parent_entry_fill_id = parent_entry_fill_id or cached_position.entry_order_id
        elif getattr(cached_position, "client_order_id", None):
            parent_entry_order_id = cached_position.client_order_id
            if parentage_status == "UNKNOWN":
                parentage_status = "ORDER_LINKED"
                parent_entry_fill_id = parent_entry_fill_id or cached_position.client_order_id
        if getattr(cached_position, "entry_signal_id", None):
            parent_entry_signal_id = cached_position.entry_signal_id

    exit_reason = _STOP_TRIGGER_TO_EXIT_REASON.get(
        candidate.trigger_reason, "STOP_LOSS"
    )

    intent = OrderIntent(
        ticker=candidate.market_ticker,
        side=held_side,
        action="sell",
        price_cents=exit_price,
        count=held_contracts,
        order_type="limit",
        time_in_force="ioc",
        source="stop_candidate",
        agent_id="stop_candidate",
        # Stable identity per candidate: retries of the same stop candidate reuse
        # the same intent/client_order_id so router + venue dedup prevents a
        # second live order after an ambiguous submission outcome.
        intent_id=f"stop_candidate:{candidate.candidate_id}",
        client_order_id=f"stopcand_{candidate.candidate_id}"[:64],
        kalshi_side=kalshi_side,
        reduce_only=True,
        entry_or_exit="exit",
        exit_reason=exit_reason,
        exit_policy_id=exit_policy_id,
        pre_position_size=pre_contracts,
        expected_post_position_size=max(0, pre_contracts - held_contracts),
        reason=f"stop_loss:{candidate.trigger_reason}:{candidate.candidate_id}",
        rationale=f"stop_candidate:{candidate.trigger_reason}:{candidate.candidate_id}",
        parentage_status=parentage_status,
        parent_entry_fill_id=parent_entry_fill_id,
        parent_entry_order_id=parent_entry_order_id,
        parent_entry_signal_id=parent_entry_signal_id,
        snapshot_age_ms=float(candidate.quote_age_ms or 0),
    )

    # 5. Canonical contract validation (fetches fresh position again, but the
    #    above snapshot is already fresh so this is effectively idempotent).
    try:
        canonical = normalize_order(
            intent,
            exchange_position_cc=exchange_position_cc,
            position_avg_price_cents=position_avg_price_cents,
            position_side=position_side,
        )
        validate_canonical_intent(
            canonical,
            exchange_position_cc=exchange_position_cc,
            position_avg_price_cents=position_avg_price_cents,
        )
    except OrderIntentValidationError as exc:
        record_stop_candidate(candidate)
        return OrderResult(
            status="rejected",
            mode=TradingMode.PAPER,
            reason=f"stop_candidate_canonical_validation_failed:{exc}",
        )

    # 6. Stop-specific invariants.
    try:
        kalshi, unified = _get_market_state(candidate.market_ticker)
        market_close_time = None
        if kalshi and getattr(kalshi, "expected_expiration_time", None):
            try:
                market_close_time = datetime.fromisoformat(
                    str(kalshi.expected_expiration_time)
                )
                if market_close_time.tzinfo is None:
                    market_close_time = market_close_time.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        validate_stop_order_invariants(
            canonical,
            exchange_position_cc=exchange_position_cc,
            market_close_time=market_close_time,
            quote_age_ms=candidate.quote_age_ms,
            position_snapshot_age_ms=position_snapshot_age_ms,
            seconds_to_expiry=candidate.seconds_to_expiry,
        )
    except StopOrderInvariantError as exc:
        record_stop_candidate(candidate)
        return OrderResult(
            status="rejected",
            mode=TradingMode.PAPER,
            reason=f"stop_candidate_invariant_violation:{exc}",
        )

    # 7. Route the reduce-only IOC close.
    from merid.event_venues.kalshi.order_router import route_order_async
    result = await route_order_async(intent)
    get_stop_candidate_ledger().record_submission(
        candidate,
        result,
        submitted_price_cents=exit_price,
        reference_bid_cents=exit_bid,
    )
    # 8. Residual-exposure branch: a non-executable protective exit is not a
    #    terminal state — reevaluate hold-vs-exit at the firewall's actual
    #    depth VWAP and record an explicit downstream decision.
    try:
        await _maybe_degraded_stop_exit(
            candidate,
            result,
            held_side=held_side,
            held_contracts=held_contracts,
        )
    except Exception as exc:
        logger.critical(
            "[STOP-DEGRADED-ERROR] candidate=%s ticker=%s error=%s",
            candidate.candidate_id,
            candidate.market_ticker,
            exc,
            exc_info=True,
        )
    return result


def maybe_submit_stop_candidate_sync(
    candidate: StopCandidate,
    *,
    force: bool = False,
) -> Optional[Any]:
    """Synchronous wrapper that schedules ``maybe_submit_stop_candidate``.

    Use this from synchronous exit evaluators (e.g. `KalshiStrategy.evaluate_exits`)
    when an event loop is available.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.create_task(maybe_submit_stop_candidate(candidate, force=force))
    except Exception:
        pass
    logger.critical(
        "[ALERT][STOP-CANDIDATE-NOT-SUBMITTED] candidate=%s ticker=%s "
        "trigger=%s reason=no_running_event_loop",
        candidate.candidate_id, candidate.market_ticker, candidate.trigger_reason,
    )
    record_stop_candidate(candidate)
    return None
