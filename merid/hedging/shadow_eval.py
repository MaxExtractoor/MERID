"""Counterfactual hedge evaluation — shadow lane (observe-only).

Answers "would the hedge the engine suppressed have worked?" without
submitting anything.  When ``entries_enabled`` is false the hedge engine
still computes its deterministic orders in ``shadow`` mode; this module
records each hypothetical order to ``logs/hedge_shadow.jsonl`` with the
executable book state, displayed depth, versioned Kalshi taker fee, and
data-quality flags needed for post-settlement grading.

Fill model is deliberately conservative:

- Entry price is the *executable ask* for the hedge side (YES ask, or NO
  ask / ``100 - yes_bid``), never the engine's mid/FVG estimate.
- ``fillable_contracts`` assumes only displayed top-of-book depth; a
  queue-position haircut is applied offline at grading time, not here.
- ``research_eligible`` requires a fresh initialized book, a real
  executable ask, and depth covering the full hypothetical count.  Touch
  without depth is recorded but never counted as a fill.

Write-only, exception-safe, never influences order routing, and cannot
self-promote: records are evidence for a future shared-accounting design,
not authorization.

Env:
    MERID_HEDGE_SHADOW_ENABLED   default "1" — set "0" to disable
    MERID_HEDGE_SHADOW_LOG       JSONL path (default logs/hedge_shadow.jsonl)
    MERID_HEDGE_SHADOW_MAX_BOOK_AGE_S  book freshness bound (default 5.0)
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.hedging.shadow_eval")

_DEFAULT_PATH = os.path.join("logs", "hedge_shadow.jsonl")
_lock = threading.Lock()

_ENABLED = os.environ.get(
    "MERID_HEDGE_SHADOW_ENABLED", "1"
).strip().lower() in ("1", "true", "yes", "on")

_MAX_BOOK_AGE_S = float(os.environ.get("MERID_HEDGE_SHADOW_MAX_BOOK_AGE_S", "5.0"))


def shadow_enabled() -> bool:
    return _ENABLED


def _f(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _book_for(ticker: Optional[str]) -> tuple[Optional[Any], Optional[str]]:
    """Return (KalshiMarketState, None) or (None, reason)."""
    if not ticker:
        return None, "no_target_ticker"
    try:
        from merid.event_venues.kalshi.market_state import (
            get_kalshi_market_state_store,
        )

        state = get_kalshi_market_state_store().get(ticker)
        if state is None:
            return None, "ticker_not_in_store"
        return state, None
    except Exception as exc:
        return None, f"store_error:{type(exc).__name__}"


def _executable_ask(state: Any, side: str) -> tuple[Optional[int], Optional[int], str]:
    """Return (ask_cents, side_depth_contracts, source) for the hedge side.

    Kalshi books are YES-denominated; the NO ask equals 100 - yes_bid when
    the dedicated NO-side fields are absent.  ``depth_10c_{side}`` is the
    within-10c depth on that side's book (contracts); it overstates touch
    depth, so grading applies its own haircut — we record the basis.
    """
    if side == "no":
        depth = _f(getattr(state, "depth_10c_no", None))
        no_ask = getattr(state, "best_no_ask_cents", None)
        if no_ask is not None:
            return int(no_ask), depth, "no_book"
        yes_bid = getattr(state, "best_bid_cents", None)
        if yes_bid is not None:
            return int(100 - int(yes_bid)), depth, "derived_no_ask"
        return None, depth, "missing"
    # yes
    depth = _f(getattr(state, "depth_10c_yes", None))
    yes_ask = getattr(state, "best_ask_cents", None)
    if yes_ask is not None:
        return int(yes_ask), depth, "yes_book"
    return None, depth, "missing"


def _taker_fee_cents(price_cents: float, contracts: float) -> Optional[float]:
    try:
        from merid.event_venues.kalshi.parabolic_fees import kalshi_fee_cents_exact

        return float(
            kalshi_fee_cents_exact(price_cents / 100.0, contracts, "taker")
        )
    except Exception:
        return None


def _record_for_order(
    order: Any,
    *,
    bankroll_cents: int,
    net_delta_cents: Optional[int],
    now: float,
) -> Dict[str, Any]:
    ticker = getattr(order, "target_ticker", None)
    side = str(getattr(order, "side", "") or "").lower()
    count = int(getattr(order, "count", 0) or 0)
    engine_px = _f(getattr(order, "price_cents", None))

    rec: Dict[str, Any] = {
        "type": "hedge_shadow",
        "schema_version": 1,
        "event_ts_utc": datetime.now(timezone.utc).isoformat(),
        "event_ts_epoch": now,
        "asset": getattr(order, "asset", None),
        "timeframe": getattr(order, "timeframe", None),
        "ticker": ticker,
        "side": side,
        "action": getattr(order, "action", None),
        "count_contracts": count,
        "engine_price_cents": engine_px,
        "hedge_reason": getattr(order, "hedge_reason", None),
        "paired_alpha_id": getattr(order, "paired_alpha_id", None),
        "cell_net_delta_cents": net_delta_cents,
        "bankroll_cents": bankroll_cents,
        # book / executable state
        "book_state": "missing",
        "book_age_s": None,
        "book_initialized": None,
        "seconds_to_expiry": None,
        "executable_ask_cents": None,
        "ask_source": None,
        "displayed_depth_cc": None,
        "fillable_contracts": 0,
        "fill_ratio": 0.0,
        # economics (conservative taker assumptions)
        "taker_fee_cents_total": None,
        "taker_fee_cents_per_contract": None,
        "all_in_entry_cents_per_contract": None,
        "cost_vs_engine_price_cents": None,
        # grading
        "research_eligible": False,
        "data_quality": [],
    }

    state, err = _book_for(ticker)
    if err is not None:
        rec["data_quality"].append(err)
        return rec

    rec["book_state"] = "present"
    rec["book_initialized"] = bool(getattr(state, "book_initialized", False))
    rec["seconds_to_expiry"] = _f(getattr(state, "seconds_to_expiry", None))

    wall_ts = _f(getattr(state, "last_book_update_wall_ts", None)) or _f(
        getattr(state, "last_book_update_ts", None)
    )
    if wall_ts is not None:
        rec["book_age_s"] = round(now - wall_ts, 3)

    ask, side_depth, src = _executable_ask(state, side)
    rec["executable_ask_cents"] = ask
    rec["ask_source"] = src
    rec["displayed_depth_cc"] = (
        round(side_depth * 100.0, 2) if side_depth is not None else None
    )

    if ask is None:
        rec["data_quality"].append("no_executable_ask")
        return rec

    if not rec["book_initialized"]:
        rec["data_quality"].append("book_not_initialized")
    if rec["book_age_s"] is None:
        rec["data_quality"].append("book_age_unknown")
    elif rec["book_age_s"] > _MAX_BOOK_AGE_S:
        rec["data_quality"].append("book_stale")

    # Conservative fill: side-specific within-10c depth only, no queue
    # model.  This overstates touch depth, so it is a ceiling — grading
    # applies latency/queue haircuts offline.
    if side_depth is not None and side_depth > 0:
        fillable_cc = min(count * 100.0, side_depth * 100.0)
        rec["fillable_contracts"] = round(fillable_cc / 100.0, 4)
        rec["fill_ratio"] = round(fillable_cc / (count * 100.0), 4) if count else 0.0
    else:
        rec["data_quality"].append("depth_unknown")

    fee_total = _taker_fee_cents(float(ask), float(count))
    rec["taker_fee_cents_total"] = fee_total
    if fee_total is not None and count > 0:
        rec["taker_fee_cents_per_contract"] = round(fee_total / count, 4)
        rec["all_in_entry_cents_per_contract"] = round(
            float(ask) + fee_total / count, 4
        )
        if engine_px:
            rec["cost_vs_engine_price_cents"] = round(
                float(ask) + fee_total / count - float(engine_px), 4
            )

    # Eligible only when the conservative model says the full size fills
    # on a fresh book at a real ask.
    rec["research_eligible"] = (
        ask is not None
        and rec["book_initialized"]
        and rec["book_age_s"] is not None
        and rec["book_age_s"] <= _MAX_BOOK_AGE_S
        and rec["fillable_contracts"] >= count
        and not any(q in ("no_executable_ask", "book_stale", "depth_unknown")
                    for q in rec["data_quality"])
    )
    return rec


def record_shadow_orders(
    orders: List[Any],
    *,
    exposure: Any = None,
    bankroll_cents: int = 0,
) -> int:
    """Append one JSONL record per hypothetical hedge order.

    Returns the number of records written.  Never raises.
    """
    if not _ENABLED or not orders:
        return 0
    try:
        now = time.time()
        # Best-effort per-cell net delta for grading context.
        deltas: Dict[tuple, Optional[int]] = {}
        if exposure is not None:
            try:
                for o in orders:
                    key = (getattr(o, "asset", None), getattr(o, "timeframe", None))
                    if key not in deltas:
                        try:
                            deltas[key] = int(exposure.net_delta_cents(*key))
                        except Exception:
                            deltas[key] = None
            except Exception:
                pass

        records = []
        for o in orders:
            key = (getattr(o, "asset", None), getattr(o, "timeframe", None))
            try:
                records.append(_record_for_order(
                    o,
                    bankroll_cents=int(bankroll_cents or 0),
                    net_delta_cents=deltas.get(key),
                    now=now,
                ))
            except Exception as exc:  # per-order isolation
                logger.debug("[hedge-shadow] record build failed: %s", exc)

        if not records:
            return 0
        path = os.environ.get("MERID_HEDGE_SHADOW_LOG", _DEFAULT_PATH)
        with _lock:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec, default=str) + "\n")
        eligible = sum(1 for r in records if r.get("research_eligible"))
        logger.info(
            "[hedge-shadow] recorded %d hypothetical hedge orders "
            "(%d research-eligible) — entries remain gated off",
            len(records), eligible,
        )
        return len(records)
    except Exception as exc:  # pragma: no cover - telemetry must never break trading
        logger.debug("[hedge-shadow] failed to write records: %s", exc)
        return 0
