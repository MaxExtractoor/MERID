"""Cheap-NO research shadow lane (read-only instrumentation).

Scores every evaluation where the executable NO ask sits inside the
research price band, writing one JSONL record per evaluation to
``logs/cheap_no_research.jsonl`` for post-settlement grading.

Purpose: the settled-candidate counterfactual (decision_audit
side_ev/outcomes join, ~200 unique markets per asset) shows the pooled
cheap-NO edge is a composition artifact.  Conditioned on executable ask,
first-observation-per-market, the only positive cells are mid-window
(300-600s to close):

    asset   mid-window net/ct (maker econ)   all-TTE net/ct
    DOGE    +12.25c                           +3.02c
    ETH     +13.28c                           +0.94c
    SOL      +6.12c                           +0.72c
    XRP     +10.07c                           -1.22c
    BTC      -3.27c                           -5.08c   (toxic in all bands)

Late-window (<300s) is toxic nearly everywhere (SOL -21.6c, n=10; DOGE
-2.0c; XRP -1.6c).  Early-window (>600s) is negative for BTC/ETH/XRP.

This module therefore records every in-band evaluation with a
``research_eligible`` flag conditioned on the surviving cohort
(non-BTC assets, mid-window TTE) plus explicit ``exclusions`` so the
grading join can validate or kill the lane out-of-sample.  It is
write-only, exception-safe, and never influences order routing.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.cheap_no_research")

_DEFAULT_PATH = os.path.join("logs", "cheap_no_research.jsonl")
_lock = threading.Lock()

_ENABLED = os.environ.get("MERID_CHEAP_NO_RESEARCH_ENABLED", "1").strip().lower() in (
    "1", "true", "yes",
)

# Executable NO-ask research band (cents).
BAND_LO_CENTS = float(os.environ.get("MERID_CHEAP_NO_BAND_LO_CENTS", "10"))
BAND_HI_CENTS = float(os.environ.get("MERID_CHEAP_NO_BAND_HI_CENTS", "24"))

# Conditioned cohort from the settled-market executable-price audit
# (first-obs-per-market, real asks, mid-window net/contract):
#   ETH +6.5c (n=86), DOGE +7.5c (n=91), XRP +5.8c (n=79), SOL +4.0c (n=95)
#   BTC -2.9c (n=99) — toxic in every TTE band, excluded.
# Per the deployment plan, ETH-mid is the primary candidate cohort;
# DOGE/SOL/XRP-mid are quarantined research cohorts (fresh fade-toxicity
# and late-window calibration concerns).  Late-window is excluded for all
# assets pending larger samples (SOL late n=17, DOGE late n=23).
ELIGIBLE_ASSETS = frozenset(
    a.strip().upper()
    for a in os.environ.get(
        "MERID_CHEAP_NO_RESEARCH_ASSETS", "ETH,SOL,DOGE,XRP"
    ).split(",")
    if a.strip()
)
PRIMARY_ASSETS = frozenset(
    a.strip().upper()
    for a in os.environ.get("MERID_CHEAP_NO_PRIMARY_ASSETS", "ETH").split(",")
    if a.strip()
)

# Mid-window TTE band where the conditioned cohort is positive.
TTE_MIN_S = float(os.environ.get("MERID_CHEAP_NO_TTE_MIN_S", "300"))
TTE_MAX_S = float(os.environ.get("MERID_CHEAP_NO_TTE_MAX_S", "600"))

# Minimum displayed own-side depth for a 1-contract research fill (cc).
MIN_DEPTH_CC = float(os.environ.get("MERID_CHEAP_NO_MIN_DEPTH_CC", "100"))

# Freshness SLOs mirroring the execution gates: the shadow record is only
# meaningful if the quote and reference were contemporaneous.
MAX_QUOTE_AGE_MS = float(os.environ.get("MERID_CHEAP_NO_MAX_QUOTE_AGE_MS", "1000"))
MAX_RTI_AGE_MS = float(os.environ.get("MERID_CHEAP_NO_MAX_RTI_AGE_MS", "2000"))


def _tte_bucket(tte_seconds: Optional[float]) -> str:
    if tte_seconds is None:
        return "unknown"
    if tte_seconds > TTE_MAX_S:
        return "early"
    if tte_seconds >= TTE_MIN_S:
        return "mid"
    return "late"


def evaluate_eligibility(
    *,
    asset: str,
    no_ask_cents: float,
    no_depth_cc: float,
    tte_seconds: Optional[float],
    quote_age_ms: Optional[float],
    rti_age_ms: Optional[float],
    net_edge_maker: Optional[float],
) -> Dict[str, Any]:
    """Return the conditioned research-lane verdict for one observation.

    ``eligible`` means the observation sits inside the cohort that was
    positive on settled executable-price counterfactuals AND carries a
    positive maker-economics net edge.  ``exclusions`` lists every failed
    condition so the grader can re-slice without re-emitting records.
    """
    exclusions: List[str] = []
    if str(asset).upper() not in ELIGIBLE_ASSETS:
        exclusions.append("asset_toxic_cohort")
    if not (BAND_LO_CENTS <= float(no_ask_cents) <= BAND_HI_CENTS):
        exclusions.append("price_outside_band")
    bucket = _tte_bucket(tte_seconds)
    if bucket != "mid":
        exclusions.append(f"tte_{bucket}")
    if float(no_depth_cc or 0.0) < MIN_DEPTH_CC:
        exclusions.append("insufficient_depth")
    if quote_age_ms is not None and float(quote_age_ms) > MAX_QUOTE_AGE_MS:
        exclusions.append("quote_stale")
    if rti_age_ms is not None and float(rti_age_ms) > MAX_RTI_AGE_MS:
        exclusions.append("rti_stale")
    if net_edge_maker is None or float(net_edge_maker) <= 0.0:
        exclusions.append("nonpositive_maker_edge")
    eligible = not exclusions
    if not eligible:
        tier = "excluded"
    elif str(asset).upper() in PRIMARY_ASSETS:
        tier = "primary_candidate"
    else:
        tier = "quarantined_research"
    return {
        "eligible": eligible,
        "tier": tier,
        "exclusions": exclusions,
        "tte_bucket": bucket,
    }


def log_cheap_no_research(
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
    no_depth_cc: float,
    # model / economics
    p_no_calibrated: Optional[float],
    p_no_raw: Optional[float],
    net_edge_taker: Optional[float],
    net_edge_maker: Optional[float],
    edge_threshold: Optional[float],
    fee_cents_maker: Optional[float],
    fee_cents_taker: Optional[float],
    # provenance / freshness
    tte_seconds: Optional[float],
    z_score: Optional[float] = None,
    log_moneyness: Optional[float] = None,
    annualized_vol: Optional[float] = None,
    vol_source: Optional[str] = None,
    quote_age_ms: Optional[float] = None,
    rti_age_ms: Optional[float] = None,
    rti_book_skew_ms: Optional[float] = None,
    regime: Optional[str] = None,
    market_lean_cents: Optional[float] = None,
    liquidity_role_eval: Optional[str] = None,
    decision_reason: Optional[str] = None,
    was_selected: bool = False,
) -> None:
    """Append one research-shadow record when the NO ask is in band.

    Records are emitted for *every* in-band evaluation — selected or
    rejected — so the grading join measures the lane, not just its
    rejects.  Never raises.
    """
    if not _ENABLED:
        return
    try:
        if not (BAND_LO_CENTS <= float(no_ask_cents) <= BAND_HI_CENTS):
            return
        verdict = evaluate_eligibility(
            asset=asset,
            no_ask_cents=no_ask_cents,
            no_depth_cc=no_depth_cc,
            tte_seconds=tte_seconds,
            quote_age_ms=quote_age_ms,
            rti_age_ms=rti_age_ms,
            net_edge_maker=net_edge_maker,
        )
        record = {
            "type": "cheap_no_research",
            "schema_version": 1,
            "event_ts_utc": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "decision_id": decision_id,
            "asset": asset,
            "ticker": ticker,
            "side": "no",
            # executable microstructure snapshot
            "yes_bid_cents": float(yes_bid_cents),
            "yes_ask_cents": float(yes_ask_cents),
            "no_bid_cents": float(no_bid_cents),
            "no_ask_cents": float(no_ask_cents),
            "no_spread_cents": float(no_ask_cents) - float(no_bid_cents),
            "yes_spread_cents": float(yes_ask_cents) - float(yes_bid_cents),
            "no_depth_cc": float(no_depth_cc),
            "market_lean_cents": market_lean_cents,
            # model + economics
            "p_no_calibrated": p_no_calibrated,
            "p_no_raw": p_no_raw,
            "net_edge_taker": net_edge_taker,
            "net_edge_maker": net_edge_maker,
            "edge_threshold": edge_threshold,
            "fee_cents_maker": fee_cents_maker,
            "fee_cents_taker": fee_cents_taker,
            "liquidity_role_eval": liquidity_role_eval,
            # provenance
            "tte_seconds": tte_seconds,
            "tte_bucket": verdict["tte_bucket"],
            "z_score": z_score,
            "log_moneyness": log_moneyness,
            "annualized_vol": annualized_vol,
            "vol_source": vol_source,
            "quote_age_ms": quote_age_ms,
            "rti_age_ms": rti_age_ms,
            "rti_book_skew_ms": rti_book_skew_ms,
            "regime": regime,
            "decision_reason": decision_reason,
            "was_selected": bool(was_selected),
            # conditioned verdict
            "research_eligible": verdict["eligible"],
            "research_tier": verdict["tier"],
            "research_exclusions": verdict["exclusions"],
        }
        path = os.environ.get("MERID_CHEAP_NO_RESEARCH_LOG", _DEFAULT_PATH)
        line = json.dumps(record, default=str)
        with _lock:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:  # pragma: no cover - telemetry must never break trading
        logger.debug("[CHEAP-NO-RESEARCH] failed to write record: %s", e)
