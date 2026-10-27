"""Observe-only counterfactual for a pinned-fav maker band below MAKER_LO.

2026-10-27: the live maker floor is 90c (``MERID_PINNED_FAV_MAKER_LO``),
raised 76->90 on 2026-10-24 falsifying evidence (the 76-89c YES cohort
settled ~50% vs the ~80-89% breakeven; published Kalshi crypto calibration
shows 70-89c bands overpriced -22..-32pt).  The open operator question is
whether the floor should extend back down toward 85c — and whether the
90-91c pocket the floor still admits is earning its keep.

This tracker re-measures that pocket WITHOUT risking fills: on every
market eval where an own-side bid sits inside the shadow window (default
85-91c, deliberately overlapping the live 90-91c edge as a control) it
evaluates the lane's own admission gates read-only — TTE window, min-p
pin, min-EV floor, per-asset moneyness cap, daily cap — and appends one
JSONL record to ``logs/pinned_fav_maker_shadow.jsonl``.
``scripts/pinned_fav_maker_shadow_report.py`` joins the records to
``logs/settlement_outcomes.jsonl`` so the floor decision is made on fresh
measured data.

Write-only and exception-safe by construction: nothing here can submit,
replace, or cancel an order, consume the daily cap, demote evidence
cells, or reserve exposure.  ``pinned_fav_cap_remaining`` is a read-only
counter inspection — consumption only happens on real submissions via
``record_pinned_fav_submission``.
"""
from __future__ import annotations

import json
import math
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.pinned_fav_maker_shadow")

_DEFAULT_PATH = os.path.join("logs", "pinned_fav_maker_shadow.jsonl")
_lock = threading.Lock()

# Dedup: at most one record per (ticker, side, bid-cent, tte-minute).  A
# market that parks at 88c for three minutes yields ~3 records, not one
# per cycle — the settlement join only needs the trajectory.
_emitted: Dict[tuple, None] = {}
_EMIT_CAP = 50000


def _enabled() -> bool:
    return os.environ.get(
        "MERID_PINNED_FAV_MAKER_SHADOW_ENABLED", "1"
    ).strip().lower() in ("1", "true", "yes", "on")


def _shadow_lo() -> float:
    return float(os.environ.get("MERID_PINNED_FAV_MAKER_SHADOW_LO", "85"))


def _shadow_hi() -> float:
    return float(os.environ.get("MERID_PINNED_FAV_MAKER_SHADOW_HI", "91"))


def _maker_fee_est_cents(price_cents: float) -> Optional[float]:
    """Exact per-contract maker fee at the hypothetical resting price."""
    try:
        from merid.event_venues.kalshi.parabolic_fees import (
            kalshi_fee_cents_exact,
        )

        return float(
            kalshi_fee_cents_exact(
                float(price_cents) / 100.0, 1, role="maker"
            )
        )
    except Exception:
        return None


def _eval_side_gates(
    *,
    side: str,
    bid_price_cents: float,
    tte_seconds: Optional[float],
    p_selected: Optional[float],
    maker_ev_cents: Optional[float],
    asset: Optional[str],
) -> Dict[str, Any]:
    """Re-apply the lane's admission gates read-only at a shadow price.

    Mirrors ``directional_regime.pinned_fav_block`` minus the band check
    (emission already implies the shadow band) and minus any state
    mutation: the daily cap is inspected, never consumed.
    """
    from merid.prediction import directional_regime as _dr

    out: Dict[str, Any] = {
        "tte_required_lo_s": _dr._pinned_fav_min_tte(),
        "tte_required_hi_s": _dr._pinned_fav_max_tte(),
        "min_p_required": _dr._pinned_fav_maker_min_p(),
        "min_ev_floor_cents": _dr._pinned_fav_min_ev_cents(),
    }

    try:
        tte_ok = tte_seconds is not None and (
            out["tte_required_lo_s"] <= float(tte_seconds) <= out["tte_required_hi_s"]
        )
    except (TypeError, ValueError):
        tte_ok = False
    out["gate_tte_pass"] = bool(tte_ok)

    if p_selected is None or not math.isfinite(float(p_selected)):
        out["gate_min_p_pass"] = False
        out["min_p_block"] = "no_p"
    else:
        out["gate_min_p_pass"] = float(p_selected) >= out["min_p_required"]

    out["gate_min_ev_pass"] = (
        maker_ev_cents is not None
        and float(maker_ev_cents) >= out["min_ev_floor_cents"]
    )

    mon_cap = None
    mon_pass = True
    if _dr.pinned_fav_honor_moneyness_caps() and asset:
        mon_cap = _dr._moneyness_max_entry_price_cents(side, asset)
        if mon_cap is not None and float(bid_price_cents) > float(mon_cap):
            mon_pass = bool(
                _dr._moneyness_cap_exception(
                    side, asset, float(bid_price_cents), maker_ev_cents
                )
            )
    out["moneyness_cap_cents"] = mon_cap
    out["gate_moneyness_pass"] = bool(mon_pass)

    try:
        cap_remaining = _dr.pinned_fav_cap_remaining()
    except Exception:
        cap_remaining = None
    out["daily_cap_remaining"] = cap_remaining
    out["gate_daily_cap_pass"] = cap_remaining is None or cap_remaining > 0

    out["would_qualify"] = all(
        out[k] for k in (
            "gate_tte_pass",
            "gate_min_p_pass",
            "gate_min_ev_pass",
            "gate_moneyness_pass",
            "gate_daily_cap_pass",
        )
    )
    return out


def _append(record: Dict[str, Any]) -> None:
    try:
        line = json.dumps(record, default=str)
    except Exception:
        return
    try:
        with _lock:
            with open(_DEFAULT_PATH, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:
        logger.debug("[PINNED-FAV-SHADOW] write failed (non-critical): %s", exc)


def evaluate(
    *,
    run_id: str,
    decision_id: str,
    asset: str,
    ticker: Optional[str],
    yes_bid_cents: Optional[float],
    yes_ask_cents: Optional[float],
    no_bid_cents: Optional[float],
    no_ask_cents: Optional[float],
    tte_seconds: Optional[float],
    p_yes: Optional[float],
    spot_price: Optional[float],
    strike_price: Optional[float],
    depth_at_own_bid_yes_cc: Optional[float] = None,
    depth_at_own_bid_no_cc: Optional[float] = None,
    quote_state: Optional[str] = None,
    quote_age_ms: Optional[float] = None,
    book_source_degraded: Optional[bool] = None,
) -> None:
    """Evaluate both own-side bids against the shadow maker band and log.

    ``yes_bid_cents`` / ``no_bid_cents`` are the prices a post-only order
    would join on each side.  A bid inside the shadow window means a
    resting favorite entry is hypothetically available; the record keeps
    the lane's per-gate verdicts so the report can separate "band too
    tight" from "moneyness/EV/pin would block it anyway".
    """
    try:
        if not _enabled() or not ticker:
            return
        lo, hi = _shadow_lo(), _shadow_hi()

        from merid.prediction import directional_regime as _dr

        live_lo, live_hi = float(_dr._pinned_fav_lo()), float(_dr._pinned_fav_hi())
        lane_armed = _dr.pinned_fav_enabled()
        maker_mode = _dr.pinned_fav_maker_mode()

        for side, bid, ask, dep in (
            ("yes", yes_bid_cents, yes_ask_cents, depth_at_own_bid_yes_cc),
            ("no", no_bid_cents, no_ask_cents, depth_at_own_bid_no_cc),
        ):
            try:
                if bid is None:
                    continue
                bid_f = float(bid)
                if not (lo <= bid_f <= hi):
                    continue
                tte_min = int(float(tte_seconds) // 60) if tte_seconds else None
                key = (ticker, side, int(round(bid_f)), tte_min)
                if key in _emitted:
                    continue
                if len(_emitted) >= _EMIT_CAP:
                    _emitted.clear()
                _emitted[key] = None

                p_sel = (
                    float(p_yes) if side == "yes"
                    else (1.0 - float(p_yes))
                ) if p_yes is not None else None

                fee_est = _maker_fee_est_cents(bid_f)
                maker_ev = (
                    (float(p_sel) * 100.0 - bid_f - float(fee_est))
                    if (p_sel is not None and fee_est is not None)
                    else None
                )

                gates = _eval_side_gates(
                    side=side,
                    bid_price_cents=bid_f,
                    tte_seconds=tte_seconds,
                    p_selected=p_sel,
                    maker_ev_cents=maker_ev,
                    asset=asset,
                )

                in_live_band = live_lo <= bid_f <= live_hi
                record = {
                    "type": "pinned_fav_maker_shadow",
                    "schema_version": 1,
                    "event_ts_utc": datetime.now(timezone.utc).isoformat(),
                    "run_id": run_id,
                    "decision_id": f"{decision_id}:pfshadow:{side}",
                    "process_id": str(os.getpid()),
                    "asset": asset,
                    "ticker": ticker,
                    "side": side,
                    "entry_price_cents": bid_f,
                    "entry_basis": "own_side_bid_post_only",
                    "fill_assumption": "filled_at_bid",
                    "locked_book": bool(
                        ask is not None and float(ask) <= bid_f
                    ),
                    "spread_cents": (
                        round(float(ask) - bid_f, 2) if ask is not None else None
                    ),
                    "in_live_band": in_live_band,
                    "shadow_band_lo": lo,
                    "shadow_band_hi": hi,
                    "live_maker_lo": live_lo,
                    "live_maker_hi": live_hi,
                    "lane_armed": lane_armed,
                    "maker_mode": maker_mode,
                    "tte_seconds": tte_seconds,
                    "p_selected": p_sel,
                    "p_source": (
                        "market_state.model_fair_prob" if p_sel is not None else None
                    ),
                    "maker_fee_est_cents": fee_est,
                    "maker_ev_est_cents": (
                        round(maker_ev, 3) if maker_ev is not None else None
                    ),
                    "yes_bid_cents": yes_bid_cents,
                    "yes_ask_cents": yes_ask_cents,
                    "no_bid_cents": no_bid_cents,
                    "no_ask_cents": no_ask_cents,
                    "depth_at_own_bid_cc": dep,
                    "quote_state": quote_state,
                    "quote_age_ms": quote_age_ms,
                    "book_source_degraded": book_source_degraded,
                    "spot_price": spot_price,
                    "strike_price": strike_price,
                    **gates,
                }
                _append(record)
            except Exception:
                continue
    except Exception:
        # Shadow instrumentation must never raise into the decision path.
        pass
