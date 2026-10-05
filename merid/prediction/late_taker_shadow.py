"""Late-taker IOC research shadow lane (Experiment B, observe-only).

Records every evaluation inside the late-window regime (2-4 min to
expiry — the bucket where passive maker fills measured -15c/fill but
taker-equivalent counterfactuals were positive), writing one JSONL
record per evaluation to ``logs/late_taker_shadow.jsonl`` for
post-settlement grading.

Per the deployment plan the lane is calibrated separately from passive
maker results: every record carries the executable ask, the all-in
taker fee, the fee-inclusive executable edge, and the regime-specific
reserves a live IOC route would pay.  ``research_eligible`` marks the
observation inside the declared cohort — positive fee-inclusive edge
at the real ask, TTE 120-240s, outside the 40-60c knife-edge band, no
evidence_escape ownership, no opposing one-sided-book signal.  Grading
joins compute 1s/5s/15s post-fill-equivalent markouts and terminal P&L
against settlement; a sharply negative markout halts the lane before
it ever goes live.

Write-only, exception-safe, never influences order routing.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.late_taker_shadow")

_DEFAULT_PATH = os.path.join("logs", "late_taker_shadow.jsonl")
_lock = threading.Lock()

_ENABLED = os.environ.get(
    "MERID_LATE_TAKER_SHADOW_ENABLED", "1"
).strip().lower() in ("1", "true", "yes")

# Late-window regime under test (the 2-4min passive-toxic bucket).
TTE_LO_S = float(os.environ.get("MERID_LATE_TAKER_TTE_LO_S", "120"))
TTE_HI_S = float(os.environ.get("MERID_LATE_TAKER_TTE_HI_S", "240"))

# Knife-edge exclusion band (cents) — 40-60c prices carry maximal model
# risk at high gamma; excluded until stratified evidence supports them.
KNIFE_LO_CENTS = float(os.environ.get("MERID_LATE_TAKER_KNIFE_LO_C", "40"))
KNIFE_HI_CENTS = float(os.environ.get("MERID_LATE_TAKER_KNIFE_HI_C", "60"))

# Minimum displayed own-side depth for a 1-contract fill (cc).
MIN_DEPTH_CC = float(os.environ.get("MERID_LATE_TAKER_MIN_DEPTH_CC", "100"))

# Freshness SLOs mirroring execution gates.
MAX_QUOTE_AGE_MS = float(os.environ.get("MERID_LATE_TAKER_MAX_QUOTE_AGE_MS", "1000"))
MAX_RTI_AGE_MS = float(os.environ.get("MERID_LATE_TAKER_MAX_RTI_AGE_MS", "2000"))

# Regime-specific reserves charged on top of the executable ask + fee
# (probability units): expected short-horizon adverse selection plus a
# model-uncertainty reserve for late-window calibration error.
ADVERSE_SEL_RESERVE = float(
    os.environ.get("MERID_LATE_TAKER_ADV_SEL", "0.02")
)
MODEL_UNCERTAINTY_RESERVE = float(
    os.environ.get("MERID_LATE_TAKER_UNC_RESERVE", "0.02")
)


def evaluate_eligibility(
    *,
    asset: str,
    side: str,
    ask_cents: float,
    depth_cc: float,
    tte_seconds: Optional[float],
    quote_age_ms: Optional[float],
    rti_age_ms: Optional[float],
    fee_inclusive_edge: Optional[float],
    admission_owner: Optional[str],
    bookflow_block: Optional[str],
) -> Dict[str, Any]:
    """Return the late-taker shadow verdict for one evaluation.

    ``eligible`` means the observation sits inside the cohort the live
    IOC lane would be permitted on: positive fee-inclusive executable
    edge after late-window reserves, 2-4min TTE, outside the knife-edge
    band, non-escape admission, no opposing one-sided-book signal, fresh
    quote and reference.  ``exclusions`` lists every failed condition.
    """
    exclusions: List[str] = []
    tte = float(tte_seconds or 0.0)
    if not (TTE_LO_S <= tte <= TTE_HI_S):
        exclusions.append("tte_outside_late_window")
    if KNIFE_LO_CENTS <= float(ask_cents) <= KNIFE_HI_CENTS:
        exclusions.append("knife_edge_band")
    if float(depth_cc or 0.0) < MIN_DEPTH_CC:
        exclusions.append("insufficient_depth")
    if quote_age_ms is not None and float(quote_age_ms) > MAX_QUOTE_AGE_MS:
        exclusions.append("quote_stale")
    if rti_age_ms is not None and float(rti_age_ms) > MAX_RTI_AGE_MS:
        exclusions.append("rti_stale")
    if fee_inclusive_edge is None or float(fee_inclusive_edge) <= 0.0:
        exclusions.append("nonpositive_fee_inclusive_edge")
    if str(admission_owner or "") == "evidence_escape":
        exclusions.append("evidence_escape_owned")
    if bookflow_block is not None:
        exclusions.append(f"opposing_bookflow:{bookflow_block}")
    return {"eligible": not exclusions, "exclusions": exclusions}


def log_late_taker_shadow(
    *,
    run_id: str,
    decision_id: str,
    asset: str,
    ticker: Optional[str],
    # executable book state at decision time
    yes_bid_cents: float,
    yes_ask_cents: float,
    no_bid_cents: float,
    no_ask_cents: float,
    yes_depth_cc: float,
    no_depth_cc: float,
    # model / economics (per side)
    p_yes_calibrated: Optional[float],
    p_no_calibrated: Optional[float],
    net_edge_taker_yes: Optional[float],
    net_edge_taker_no: Optional[float],
    taker_fee_cents: Optional[float],
    # provenance
    tte_seconds: Optional[float],
    quote_age_ms: Optional[float] = None,
    rti_age_ms: Optional[float] = None,
    yes_admission_owner: Optional[str] = None,
    no_admission_owner: Optional[str] = None,
    yes_bookflow_block: Optional[str] = None,
    no_bookflow_block: Optional[str] = None,
    regime: Optional[str] = None,
    decision_reason: Optional[str] = None,
    was_selected: bool = False,
) -> None:
    """Append one shadow record when the evaluation sits in the late
    window.  Both sides are scored; each record carries everything the
    grader needs for 1s/5s/15s markouts and settlement P&L.  Never
    raises, never influences routing."""
    if not _ENABLED:
        return
    try:
        tte = float(tte_seconds or 0.0)
        if not (TTE_LO_S <= tte <= TTE_HI_S):
            return
        records: List[Dict[str, Any]] = []
        for side, ask, bid, depth, p_sel, net_edge_taker, owner, bf in (
            (
                "yes", yes_ask_cents, yes_bid_cents, yes_depth_cc,
                p_yes_calibrated, net_edge_taker_yes,
                yes_admission_owner, yes_bookflow_block,
            ),
            (
                "no", no_ask_cents, no_bid_cents, no_depth_cc,
                p_no_calibrated, net_edge_taker_no,
                no_admission_owner, no_bookflow_block,
            ),
        ):
            # Late-taker executable edge: p_model − ask − taker fee −
            # short-horizon adverse-selection reserve − model-uncertainty
            # reserve.  net_edge_taker already includes fee+exit-cost; the
            # shadow charges the additional regime reserves explicitly.
            fee_edge = None
            if net_edge_taker is not None:
                fee_edge = (
                    float(net_edge_taker)
                    - ADVERSE_SEL_RESERVE
                    - MODEL_UNCERTAINTY_RESERVE
                )
            verdict = evaluate_eligibility(
                asset=asset,
                side=side,
                ask_cents=float(ask),
                depth_cc=float(depth),
                tte_seconds=tte,
                quote_age_ms=quote_age_ms,
                rti_age_ms=rti_age_ms,
                fee_inclusive_edge=fee_edge,
                admission_owner=owner,
                bookflow_block=bf,
            )
            records.append(
                {
                    "type": "late_taker_shadow",
                    "schema_version": 1,
                    "event_ts_utc": datetime.now(timezone.utc).isoformat(),
                    "run_id": run_id,
                    "decision_id": decision_id,
                    "asset": asset,
                    "ticker": ticker,
                    "side": side,
                    # executable microstructure snapshot
                    "ask_cents": float(ask),
                    "bid_cents": float(bid),
                    "spread_cents": float(ask) - float(bid),
                    "depth_cc": float(depth),
                    "yes_bid_cents": float(yes_bid_cents),
                    "yes_ask_cents": float(yes_ask_cents),
                    "no_bid_cents": float(no_bid_cents),
                    "no_ask_cents": float(no_ask_cents),
                    # model + economics
                    "p_calibrated": p_sel,
                    "net_edge_taker": net_edge_taker,
                    "taker_fee_cents": taker_fee_cents,
                    "adverse_sel_reserve": ADVERSE_SEL_RESERVE,
                    "model_uncertainty_reserve": MODEL_UNCERTAINTY_RESERVE,
                    "fee_inclusive_edge": fee_edge,
                    # provenance
                    "tte_seconds": tte,
                    "quote_age_ms": quote_age_ms,
                    "rti_age_ms": rti_age_ms,
                    "admission_owner": owner,
                    "bookflow_block": bf,
                    "regime": regime,
                    "decision_reason": decision_reason,
                    "was_selected": bool(was_selected),
                    # conditioned verdict
                    "research_eligible": verdict["eligible"],
                    "research_exclusions": verdict["exclusions"],
                }
            )
        path = os.environ.get("MERID_LATE_TAKER_SHADOW_LOG", _DEFAULT_PATH)
        with _lock:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                for record in records:
                    f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:  # pragma: no cover - telemetry must never break trading
        logger.debug("[LATE-TAKER-SHADOW] failed to write record: %s", e)
