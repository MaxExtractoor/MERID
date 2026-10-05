"""Canonical trade decision contract for 15-minute crypto binaries.

A TradeDecision is the single source of truth for whether an asset has a
tradable edge.  It is produced once per asset per cycle by the hybrid decision
engine and consumed by the candidate selector, risk manager, order router, and
monitor.  Price-only rules must never produce a candidate; they may only be
inputs to the decision engine.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Literal, NamedTuple, Optional, Tuple

from merid.risk.probability.tail_calibrator import load_tail_calibrator
from merid.prediction import evidence_policy
from merid.prediction import current_build_provisional as _cbp
from merid.prediction.threshold_cells import (
    THRESHOLD_CELLS,
    bump_cell_funnel,
    cell_admission,
    cell_region_registered,
    cell_fills_today,
    emit_cell_lifecycle,
    explain_cell_miss,
    get_cell_state,
    threshold_cell_admission_allowed,
    resolve_threshold_cell,
)
from merid.prediction.rejection_counterfactual import log_rejected_candidate
from merid.prediction import empirical_price_calibration as _epc
from merid.prediction.settlement_distribution import SettlementDistribution
from merid.data.ingress_replay import replay_time
from merid.audit.replay_state_diff import record_state_checksum
from utils.logger import get_logger

logger = get_logger("merid.prediction.trade_decision")


# Minimum posterior for a regime classification to be usable.
MIN_REGIME_POSTERIOR = Decimal(os.environ.get("MERID_MIN_REGIME_POSTERIOR", "0.5"))

# Absolute minimum model probability for a side to be considered.  The
# effective per-side floor is computed in _min_p_for_side and is
# price-aware: p_selected must exceed executable_entry_price + all-in cost
# reserve (entry_fee + exit_cost_reserve + model_risk_reserve).  This
# preserves positive-EV cost-basis trades on cheap contracts without the
# old unconditional 0.5 directional-confidence veto.
TRADE_DECISION_MIN_P_SELECTED = float(os.environ.get("MERID_TRADE_DECISION_MIN_P_SELECTED", "0.0"))

# Minimum net edge (as a fraction of notional) for a side to be selected.
# 2026-08-30: Lowered to 0.02 (2%) as the hard global floor.  The actual
# threshold used at decision time is computed by ``_compute_dynamic_min_required_edge``,
# which adds an asset-tier base, a price-convexity term (halved on >=50c held
# prices), and the FLB longshot premium below 50c.  The bid/ask spread is not
# added again here: the taker-ask entry price and the pi* cost stack already
# charge it once each.  The resolved live config may raise this floor further,
# but never below the hard 0.02 floor.
TRADE_DECISION_MIN_REQUIRED_EDGE = float(os.environ.get("MERID_TRADE_DECISION_MIN_REQUIRED_EDGE", "0.02"))

# 2026-10-02: Marginal-band threshold relief.  The settled-rejection
# counterfactual (541k rejected candidates, joined to outcomes) shows the
# 0-1c and 1-2c bands *below* the gate are net profitable (+3.76c and
# +2.96c per trade) — but only at held prices 50-89c; the <50c and >=90c
# cohorts rejected at the margin were correctly blocked.  The formula
# threshold in that band is therefore reduced by a bounded constant,
# floored at the global hard floor.  Approved threshold-cell and
# provisional-cell values are untouched (they replace the formula output).
# Override with MERID_EDGE_MID_BAND_RELIEF_CENTS; set 0 to disable.
MERID_EDGE_MID_BAND_RELIEF_CENTS = max(
    0.0, float(os.environ.get("MERID_EDGE_MID_BAND_RELIEF_CENTS", "1.5"))
)
MERID_EDGE_MID_BAND_LO_CENTS = float(
    os.environ.get("MERID_EDGE_MID_BAND_LO_CENTS", "50")
)
MERID_EDGE_MID_BAND_HI_CENTS = float(
    os.environ.get("MERID_EDGE_MID_BAND_HI_CENTS", "89")
)

# Hard entry-price floor for the held side.  Contracts with a held-side price
# below this (in cents) are rejected because the 7-day data showed 0/16 wins in
# the 0-19c tail.  Override with MERID_MIN_HELD_PRICE_CENTS to raise/lower.
# 2026-08-28: raised to 35c to match the cheap-tail filter.
# 2026-09-25: lowered to 25c on the settled rejection counterfactual (390k
# classified candidates): rejected 25-29c entries netted +18.5c/trade (47% win)
# and 30-34c +10.3c/trade (44% win) after fees, while 15-19c (-2.4c/trade) and
# 20-24c (-3.4c/trade) stayed net-negative.  25c is the empirical boundary.
# Trades below this floor are only allowed when the model probability is
# exceptionally high (see MERID_CHEAP_TAIL_P_EXCEPTION).
MERID_MIN_HELD_PRICE_CENTS = max(0.0, float(os.environ.get("MERID_MIN_HELD_PRICE_CENTS", "25")))

# Low-price policy is shadow-only by default. It records the proposed policy
# without changing live admission until replay and calibration evidence support
# a separately authorized canary.
MERID_ENTRY_POLICY_MODE = os.environ.get("MERID_ENTRY_POLICY_MODE", "shadow_compare").strip().lower()
MERID_SHADOW_MIN_HELD_PRICE_CENTS = float(
    os.environ.get("MERID_SHADOW_MIN_HELD_PRICE_CENTS", "10")
)
MERID_SHADOW_LOW_PRICE_MAX_CENTS = float(
    os.environ.get("MERID_SHADOW_LOW_PRICE_MAX_CENTS", "34")
)
MERID_SHADOW_MIN_NET_EDGE = float(
    os.environ.get("MERID_SHADOW_MIN_NET_EDGE", "0.08")
)
MERID_SHADOW_DEFAULT_MIN_NET_EDGE = float(
    os.environ.get("MERID_SHADOW_DEFAULT_MIN_NET_EDGE", "0.06")
)
MERID_SHADOW_UNCERTAINTY_MULTIPLIER = float(
    os.environ.get("MERID_SHADOW_UNCERTAINTY_MULTIPLIER", "2.0")
)
MERID_LOW_PRICE_CANARY_ASSETS = {
    value.strip().upper()
    for value in os.environ.get("MERID_LOW_PRICE_CANARY_ASSETS", "BTC,SOL").split(",")
    if value.strip()
}
MERID_LOW_PRICE_CANARY_SIDES = {
    value.strip().lower()
    for value in os.environ.get("MERID_LOW_PRICE_CANARY_SIDES", "no").split(",")
    if value.strip()
}

# Very high-confidence cheap-tail exception.  DISABLED by default (threshold 1.0)
# because 7-day data showed the cheap tail (0-19c held) has a near-zero realized
# win rate and the model is overconfident there.  The per-side isotonic
# recalibration must be proven out-of-sample before re-enabling any value < 1.0.
# 2026-09-10: Clamp to 1.0 because the separate cheap-tail canary lane is the
# only authorized path for 20-34c entries; the main lane must not be weakened.
MERID_CHEAP_TAIL_P_EXCEPTION = max(1.0, float(os.environ.get("MERID_CHEAP_TAIL_P_EXCEPTION", "1.0")))

# Tail calibration applies the isotonic correction from
# data/probability_tail_calibration.json (produced by scripts/calibrate_tail_probability.py).
# It caps model probability at historical actual_win_rate + buffer.
MERID_TAIL_CALIBRATION_ENABLED = os.environ.get("MERID_TAIL_CALIBRATION_ENABLED", "1").lower() in ("1", "true", "yes")
MERID_TAIL_CALIBRATION_BUFFER = float(os.environ.get("MERID_TAIL_CALIBRATION_BUFFER", "0.05"))
MERID_TAIL_CALIBRATION_PRICE_FLOOR = float(os.environ.get("MERID_TAIL_CALIBRATION_PRICE_FLOOR", "0.35"))
# 2026-08-30: When the NO tail curve is still the YES dual (not re-fit on
# real NO-held records), only apply the dual tail cap if the raw NO model
# probability is itself in the cheap-tail region.  Capping a moderate or
# high raw p_no down to 0.05 based on a derived dual is an over-correction
# that structurally suppresses the NO side.  This is a stop-gap until the
# real NO curve is fit.
MERID_TAIL_CALIBRATION_NO_DUAL_RAW_FLOOR = float(
    os.environ.get("MERID_TAIL_CALIBRATION_NO_DUAL_RAW_FLOOR", "0.20")
)
MERID_TAIL_CALIBRATION_NO_DUAL_TRANSITION = float(
    os.environ.get("MERID_TAIL_CALIBRATION_NO_DUAL_TRANSITION", "0.05")
)

# 2026-09-25: Full-range calibration cap.  The realized bucket join (324
# settled entries, 2026-08-25..2026-09-25) showed the model's unverified edge
# is the loss source at EVERY price, not just the cheap tail: NO 30-39c won
# 30.9% (-343c) and YES 50-59c won 42.9% (-253c).  The PAVA artifact covers
# 5-99c on both sides, so apply the observed win-rate cap at any held price,
# not only below the tail floor.  Disable with MERID_CALIBRATION_CAP_FULL_RANGE=0
# to revert to tail-only caps.
MERID_CALIBRATION_CAP_FULL_RANGE = os.environ.get(
    "MERID_CALIBRATION_CAP_FULL_RANGE", "1"
).strip().lower() in ("1", "true", "yes")

# 2026-09-25: Evidence floor.  A price cell is only tradeable when the
# historically observed win rate at that held-side price clears the entry
# cost by an explicit margin.  This is a static, model-independent
# eligibility check: the model's own probability still has to clear its own
# EV/min-edge gates, but no amount of model confidence can open a cell whose
# observed bucket rate does not cover price + fee + margin.
MERID_CALIBRATION_EVIDENCE_MARGIN = float(
    os.environ.get("MERID_CALIBRATION_EVIDENCE_MARGIN", "0.01")
)

# 2026-09-28: Live rolling entry-evidence gate.  The static calibration
# artifact above is only refit offline, so a regime break keeps passing the
# frozen evidence floor for days — BTC NO-side entries decayed 77% -> 45%
# win rate over 2026-09-26..28 (~300 settled entries) while the static floor
# kept admitting the same cells.  The decision audit ledger rebuilds
# data/live_entry_evidence.json on every settlement with trailing-window
# win rates per (asset, side) and per (asset, side, 10c price bucket).  A
# cell fails closed when its *recent* observed win rate no longer clears
# entry price + fee + margin, and an asset+side fails entirely when the
# cohort's trailing win rate no longer covers its mean entry price.
# Fail-open when the artifact is absent or a cohort has too few samples —
# the static floor still applies.  Disable with MERID_LIVE_EVIDENCE_GATE=0.
MERID_LIVE_EVIDENCE_GATE = os.environ.get(
    "MERID_LIVE_EVIDENCE_GATE", "1"
).strip().lower() in ("1", "true", "yes")
MERID_LIVE_EVIDENCE_MARGIN = float(
    os.environ.get("MERID_LIVE_EVIDENCE_MARGIN", "0.03")
)
MERID_LIVE_EVIDENCE_MIN_ASSET_SAMPLES = int(
    os.environ.get("MERID_LIVE_EVIDENCE_MIN_ASSET_SAMPLES", "30")
)
MERID_LIVE_EVIDENCE_MIN_CELL_SAMPLES = int(
    os.environ.get("MERID_LIVE_EVIDENCE_MIN_CELL_SAMPLES", "15")
)

# Fail-closed gate for externally supplied hybrid p_yes.  Bachelier-only is the
# live baseline; a hybrid probability is only accepted when this flag is
# explicitly enabled, and still subject to tail calibration / π* / floor gates.
MERID_TRADE_DECISION_ALLOW_HYBRID_P = os.environ.get("MERID_TRADE_DECISION_ALLOW_HYBRID_P", "").strip().lower() in ("1", "true", "yes")

# Per-bucket π* EV gate.  The minimum required p_selected for a positive
# risk-adjusted EV is (held_price + fee + risk_premium) / 100.  The risk
# premium is tiered by held price to reflect the observed tail overconfidence:
# cheap-tail contracts need a much larger safety margin than high-price ones.
MERID_PI_STAR_TIERED = os.environ.get("MERID_PI_STAR_TIERED", "1").lower() in ("1", "true", "yes")
MERID_PI_STAR_FLAT_PREMIUM_CENTS = int(os.environ.get("MERID_PI_STAR_FLAT_PREMIUM_CENTS", "0"))
MERID_PI_STAR_TIERS_CENTS = os.environ.get("MERID_PI_STAR_TIERS_CENTS", "0:40,20:25,40:10,60:0")

# 2026-09-23: Favorite-longshot-bias reserve.  Kalshi microstructure research
# (Burgi et al. 2025 / CEPR DP20631, 300k+ contracts) shows contracts priced
# below ~50c win less often than break-even while >50c contracts earn a small
# positive return.  The slope scales an additional required net edge that grows
# linearly as the held price falls below 0.50: slope * (0.5 - price).
MERID_FLB_LONGSHOT_SLOPE = float(os.environ.get("MERID_FLB_LONGSHOT_SLOPE", "0.15"))

# 2026-09-27: Market-lean fade gate.  Settled-fill cohort analysis
# (scripts/_fade_vs_aligned_analysis.py, 75 filled entries) showed entries
# that trade AGAINST a meaningful market lean are toxic for some assets and
# profitable for others:
#   BTC fades: n=14, 36% WR, -5.7c/trade   (blocked)
#   XRP fades: n=5,  40% WR, -13.8c/trade  (blocked)
#   DOGE fades:n=2,  0% WR,  -42c/trade    (blocked)
#   ETH fades: n=5,  100% WR, +45c/trade   (allowed)
#   SOL fades: n=5,  80% WR, +35.4c/trade  (allowed)
# The toxic anatomy is always the same: market leans +12..24c, the model's
# lean agrees in DIRECTION but is weaker in magnitude, so the relative-price
# EV diff selects the opposite side and we systematically sell into the
# prevailing move.  Fading leans below ~10c was net-positive (+19c/trade),
# so only meaningful leans are gated.
MERID_FADE_BLOCK_MIN_LEAN_CENTS = float(
    os.environ.get("MERID_FADE_BLOCK_MIN_LEAN_CENTS", "10.0")
)
MERID_FADE_ALLOWED_ASSETS = {
    s.strip().upper()
    for s in os.environ.get("MERID_FADE_ALLOWED_ASSETS", "ETH,SOL").split(",")
    if s.strip()
}

# 2026-09-29: Walk-forward asset x TTE canonical-probability calibration.
# scripts/build_walkforward_calibrator.py fits C_{asset,tte}(p_yes_raw) on
# first-observation-per-(market,tte_bucket) settled records and ships
# "identity" for any cell whose OOS Brier/log-loss does not improve, so
# loading the artifact is safe: unproven cells are literal no-ops.
# Applied once to the canonical (anchored) p_yes BEFORE the per-side
# evidence caps, preserving p_no = 1 - p_yes coherence while caps remain
# safety bounds.  Disable with MERID_WALKFWD_CAL_ENABLED=0.
MERID_WALKFWD_CAL_ENABLED = os.environ.get(
    "MERID_WALKFWD_CAL_ENABLED", "1"
).strip().lower() in ("1", "true", "yes")
_WALKFWD_CAL_DEFAULT_PATH = os.path.join(
    "data", "calibration", "walkforward_calibrator.json"
)
_WALKFWD_CAL_PATH = os.environ.get(
    "MERID_WALKFWD_CAL_PATH", _WALKFWD_CAL_DEFAULT_PATH
)
_walkfwd_cal_cache: Dict[str, Any] = {"mtime": None, "artifact": None}


def _walkforward_tte_bucket(seconds_to_expiry: float) -> str:
    if seconds_to_expiry > 600.0:
        return "early"
    if seconds_to_expiry >= 300.0:
        return "mid"
    return "late"


def _load_walkforward_calibrator() -> Optional[Dict[str, Any]]:
    """Load the walk-forward calibration artifact (mtime-cached).

    Hermetic-test guard (same convention as ``_load_live_evidence``): under
    pytest the machine-local default artifact is ignored so a live-rebuilt
    calibrator can never change unrelated test outcomes.  Tests opt in by
    setting ``MERID_WALKFWD_CAL_PATH`` or monkeypatching ``_WALKFWD_CAL_PATH``.
    """
    if not MERID_WALKFWD_CAL_ENABLED:
        return None
    if (
        _WALKFWD_CAL_PATH == _WALKFWD_CAL_DEFAULT_PATH
        and "MERID_WALKFWD_CAL_PATH" not in os.environ
        and (
            "PYTEST_CURRENT_TEST" in os.environ
            or os.environ.get("MERID_ENV", "").strip().lower() in ("test", "ci")
        )
    ):
        return None
    try:
        mtime = os.path.getmtime(_WALKFWD_CAL_PATH)
        if _walkfwd_cal_cache["artifact"] is not None and _walkfwd_cal_cache["mtime"] == mtime:
            return _walkfwd_cal_cache["artifact"]
        with open(_WALKFWD_CAL_PATH, "r", encoding="utf-8") as f:
            artifact = json.load(f)
        if artifact.get("version") != "walkforward_v1":
            return None
        _walkfwd_cal_cache["mtime"] = mtime
        _walkfwd_cal_cache["artifact"] = artifact
        return artifact
    except Exception:
        return None


def _walkforward_calibrate_p_yes(asset: str, seconds_to_expiry: float, p_yes: float) -> Optional[float]:
    """Map canonical p_yes through the fitted (asset, tte) corrector.

    Returns None when the artifact is missing/disabled or the cell is
    identity — the caller leaves p_yes unchanged.  Output is clamped to
    [0.01, 0.99]; the caller's [0.05, 0.95] venue clamp still applies.
    """
    artifact = _load_walkforward_calibrator()
    if artifact is None:
        return None
    cell = (artifact.get("cells") or {}).get(
        f"{str(asset).upper()}:{_walkforward_tte_bucket(float(seconds_to_expiry))}"
    )
    if not cell:
        return None
    method = cell.get("method")
    if method == "isotonic":
        xs, ys = cell.get("x") or [], cell.get("y") or []
        if len(xs) < 2 or len(xs) != len(ys):
            return None
        p = float(p_yes)
        if p <= xs[0]:
            out = ys[0]
        elif p >= xs[-1]:
            out = ys[-1]
        else:
            lo, hi = 0, len(xs) - 1
            while hi - lo > 1:
                mid_i = (lo + hi) // 2
                if xs[mid_i] <= p:
                    lo = mid_i
                else:
                    hi = mid_i
            x0, x1, y0, y1 = xs[lo], xs[hi], ys[lo], ys[hi]
            out = y0 + (y1 - y0) * (p - x0) / max(x1 - x0, 1e-12)
        return max(0.01, min(0.99, float(out)))
    if method in ("platt", "pooled_platt"):
        a, b = float(cell.get("a", 0.0)), float(cell.get("b", 1.0))
        x = max(1e-6, min(1.0 - 1e-6, float(p_yes)))
        z = a + b * math.log(x / (1.0 - x))
        return max(0.01, min(0.99, 1.0 / (1.0 + math.exp(-z))))
    return None

# 2026-09-23: Minimum time-to-expiry for new entries.  Late-window fills were
# empirically the most adversely selected (momentum dominates the last minutes
# of a 15m window and the market is most efficient there).  New entries must
# have at least this many seconds remaining; exits are unaffected.
MERID_ENTRY_MIN_SECONDS_TO_EXPIRY = float(
    os.environ.get("MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", "180")
)

# 2026-09-27: Operator kill switch — when the automatic exit policy is
# disabled, every entry necessarily holds to settlement.  Kalshi charges no
# fee on settlement, so charging an exit-cost reserve inside net_edge is a
# phantom cost that understates true hold-to-settlement EV.  The flag is
# module-level like the other env knobs; flag changes take effect on restart.
MERID_DISABLE_EXIT_POLICY = os.environ.get(
    "MERID_DISABLE_EXIT_POLICY", "0"
).strip().lower() in ("1", "true", "yes")

# 2026-10-05 (entry-throughput canary): policy-aware expected exit cost.
# The old reserve charged a full taker exit fee at 100% probability on every
# entry.  Under the current ``ev_gated`` discretionary mode only a fraction
# of positions ever submit an exit order — fills-ledger counts since the
# 2026-09-28 exit hardening show ~10% of entries, concentrated in
# hard_profit_lock on tail-priced positions — and settlement itself is
# fee-free on Kalshi.  The reserve is therefore ``p_trigger * taker_fee``
# rather than ``1.0 * taker_fee``:
#   * settlement lane / exits disabled          -> 0  ("hold_to_settlement")
#   * entries priced >= MERID_EXPECTED_EXIT_LOCK_PROXIMITY_CENTS can
#     plausibly print the MERID_HARD_PROFIT_LOCK_CENTS bid inside the window
#                                                -> MERID_EXPECTED_EXIT_PROB_TAIL
#   * every other entry                          -> MERID_EXPECTED_EXIT_PROB
# Exit orders are always IOC/taker when they fire, so the conditional cost
# stays the full taker fee; only the trigger probability is modeled.
# ``MERID_EXPECTED_EXIT_COST=0`` restores the legacy unconditional reserve.
MERID_EXPECTED_EXIT_COST = os.environ.get(
    "MERID_EXPECTED_EXIT_COST", "1"
).strip().lower() in ("1", "true", "yes")
MERID_EXPECTED_EXIT_PROB = float(
    os.environ.get("MERID_EXPECTED_EXIT_PROB", "0.10")
)
MERID_EXPECTED_EXIT_PROB_TAIL = float(
    os.environ.get("MERID_EXPECTED_EXIT_PROB_TAIL", "0.30")
)
MERID_EXPECTED_EXIT_LOCK_PROXIMITY_CENTS = float(
    os.environ.get("MERID_EXPECTED_EXIT_LOCK_PROXIMITY_CENTS", "60")
)

# 2026-10-05 (entry-throughput canary): counter-regime admission.  The
# categorical countertrend veto closed half the side-space whenever the
# tick-run regime was confirmed — including genuinely large, independently
# supported reversal edges.  In "penalty" mode the veto becomes an elevated
# absolute net-edge floor for the counter-regime side (default 8c — far
# above the ordinary dynamic bound) plus a degraded-quote ban; the deep-ITM
# exception inside ``regime_entry_block`` is unchanged, and ``veto``
# restores the categorical block.
MERID_COUNTER_REGIME_MODE = os.environ.get(
    "MERID_COUNTER_REGIME_MODE", "penalty"
).strip().lower()
MERID_COUNTER_REGIME_MIN_EDGE = float(
    os.environ.get("MERID_COUNTER_REGIME_MIN_EDGE_CENTS", "8.0")
) / 100.0

# 2026-10-05 (entry-throughput canary): evidence "transferrable" tier.  A
# sparse exact cell whose price-matched pooled level already cleared its
# posterior-LCB margin check is supported evidence, not blind exploration —
# it skips the escape vetoes (which were built for zero-evidence trials)
# but must clear an extra margin premium over its active edge bound.
MERID_EVIDENCE_TRANSFER_EXTRA_C = float(
    os.environ.get("MERID_EVIDENCE_TRANSFER_EXTRA_CENTS", "1.0")
)

# 2026-10-05 (entry-throughput canary): top-edge IOC canary lane.  When the
# full bound rejects the taker pass on edge alone, the side may still
# qualify at a reduced floor — but only on a pristine verified quote with
# adequate depth, fresh book state, and no WS/REST divergence, and only
# through the bounded ``canary_taker`` lane (1 contract, IOC, daily cap).
MERID_CANARY_LANE_ENABLED = os.environ.get(
    "MERID_CANARY_LANE_ENABLED", "1"
).strip().lower() in ("1", "true", "yes")
MERID_CANARY_MIN_EDGE = float(
    os.environ.get("MERID_CANARY_MIN_EDGE_CENTS", "1.5")
) / 100.0
MERID_CANARY_DAILY_MAX = int(
    os.environ.get("MERID_CANARY_DAILY_MAX", "8")
)

# 2026-09-23: Market-anchor shrinkage.  Kalshi short-dated crypto binaries are
# arbitraged tick-for-tick against spot and are essentially perfectly
# calibrated inside the last minutes (prediction-market-efficiency audits show
# every price band's implied probability inside the CI of realized frequency).
# The raw model probability is therefore shrunk toward the market-implied
# probability in logit space, with weight ramping from
# MERID_MARKET_ANCHOR_MIN_W at window open to MERID_MARKET_ANCHOR_MAX_W at
# expiry over MERID_MARKET_ANCHOR_WINDOW_S seconds.  A model that still shows
# edge after shrinkage has a defensible disagreement with the market; a model
# whose edge only exists pre-shrinkage does not.
MERID_MARKET_ANCHOR_MIN_W = float(os.environ.get("MERID_MARKET_ANCHOR_MIN_W", "0.25"))
MERID_MARKET_ANCHOR_MAX_W = float(os.environ.get("MERID_MARKET_ANCHOR_MAX_W", "0.85"))
MERID_MARKET_ANCHOR_WINDOW_S = float(os.environ.get("MERID_MARKET_ANCHOR_WINDOW_S", "900"))

# 2026-09-23: Settlement-convergence lane.  Kalshi crypto 15m binaries settle
# on the mean of 60 one-second CF RTI samples in the final minute.  Once most
# of those samples are banked the outcome is near-determined while the order
# book still quotes the terminal price as live — that divergence is the
# structural edge (research: TWAP-settled binaries keep pricing ~0.50 while
# ~45/60 samples are already realized).  When a settlement-aware distribution
# is supplied and its favored side clears MERID_SETTLEMENT_LANE_MIN_P, entries
# are allowed inside the min-TTE/final-minute cutoffs down to
# MERID_SETTLEMENT_LANE_MIN_TTE_S.  Requires a minimum count of banked samples
# so the confidence claim is grounded in realized settlement data.
MERID_SETTLEMENT_LANE_ENABLED = os.environ.get(
    "MERID_SETTLEMENT_LANE_ENABLED", ""
).strip().lower() in ("1", "true", "yes")
MERID_SETTLEMENT_LANE_MIN_P = float(os.environ.get("MERID_SETTLEMENT_LANE_MIN_P", "0.84"))
MERID_SETTLEMENT_LANE_MIN_OBSERVED = int(os.environ.get("MERID_SETTLEMENT_LANE_MIN_OBSERVED", "10"))
MERID_SETTLEMENT_LANE_MIN_TTE_S = float(os.environ.get("MERID_SETTLEMENT_LANE_MIN_TTE_S", "30"))
MERID_SETTLEMENT_LANE_MAX_PRICE_CENTS = float(os.environ.get("MERID_SETTLEMENT_LANE_MAX_PRICE_CENTS", "97"))

# In the settlement window the book prices the *terminal tick* while the
# settlement distribution prices the *banked average* — the model is strictly
# better informed there, so the market anchor is released in proportion to the
# share of settlement samples still unrealized (n_rem / 60).
MERID_SETTLEMENT_ANCHOR_RELEASE = os.environ.get(
    "MERID_SETTLEMENT_ANCHOR_RELEASE", "1"
).strip().lower() in ("1", "true", "yes")

# 2026-08-29: Executable-cost EV gate becomes the final entry authority.
# When enabled, the gate is evaluated after the existing edge/π* computation
# and can overrule a selected side if the net dollar EV or EV/tail-risk ratio
# does not clear the configured thresholds.  The old edge-%/p_selected gates
# remain visible in the decision as telemetry, but the EV gate is the sole
# authority for live entries.
MERID_EV_GATE_AUTHORITATIVE = os.environ.get("MERID_EV_GATE_AUTHORITATIVE", "1").lower() in ("1", "true", "yes")

# 2026-08-29: Order decision ledger collection.  When enabled, every trade
# decision is persisted before any order is submitted.
MERID_ORDER_DECISION_LEDGER_ENABLED = os.environ.get("MERID_ORDER_DECISION_LEDGER_ENABLED", "1").lower() in ("1", "true", "yes")

# 2026-08-30: Annualized-volatility sanity controls.  The Bachelier baseline is
# only defensible when sigma is in a TWAP-appropriate band for the asset.
# Values below the band produce overconfident p_yes (e.g. 0.95 for a 30-80c
# spot-strike move) and can create false edges.  Values above the band are
# economically implausible for 15m crypto.  Env vars override the band per asset
# or globally; MERID_ANNUALIZED_VOL_{ASSET} is still the primary requested value
# when set, but it is clamped to this band unless an explicit override is given.
# 2026-09-27: floors re-fit against 25,412 deduped settled decisions whose
# vol_source was 'realized_clamped' (scripts/_vol_floor_analysis.py).
# Brier-loss minimizers on that population were BTC 0.175, ETH 0.20,
# SOL 0.25, XRP 0.30, DOGE 0.30 — the old floors over-clamped every asset
# by 1.4-1.7x, pushing p toward 0.5 and shrinking model edge ~2x exactly
# when the tape is quiet (the moments the floor was most often binding).
# Counterfactual join at exact taker fees + production edge thresholds:
# entries unlocked by lower floors were net-positive at every grid level
# (peak +4.4c/trade at a 0.15 floor vs +5.2c/trade on 60% fewer trades at
# 0.30).  The calibration-evidence gate remains the empirical backstop for
# cells whose observed win rate never cleared cost; the vol floor only
# guards against genuinely pathological estimator readings.
_ANNUALIZED_VOL_BANDS = {
    "BTC": (0.18, 0.90),
    "ETH": (0.20, 1.00),
    "SOL": (0.25, 1.10),
    "XRP": (0.30, 1.10),
    "DOGE": (0.30, 1.20),
}
# Global min must sit below the lowest asset floor or it re-binds them
# (applied as max(asset_floor, GLOBAL_MIN)).
_ANNUALIZED_VOL_GLOBAL_MIN = float(os.environ.get("MERID_MIN_ANNUALIZED_VOL", "0.15"))
_ANNUALIZED_VOL_GLOBAL_MAX = float(os.environ.get("MERID_MAX_ANNUALIZED_VOL", "1.20"))

# Optional vol sources (off by default).  Realized vol is preferred when fresh;
# market-implied vol is a cross-check against the Kalshi price.  Both are sanity
# clamped before use.
MERID_USE_REALIZED_VOL = os.environ.get("MERID_USE_REALIZED_VOL", "1").strip().lower() in ("1", "true", "yes")
MERID_REALIZED_VOL_MAX_AGE_S = float(os.environ.get("MERID_REALIZED_VOL_MAX_AGE_S", "300"))
MERID_REALIZED_VOL_MIN_CONFIDENCE = float(os.environ.get("MERID_REALIZED_VOL_MIN_CONFIDENCE", "0.5"))
MERID_ANCHOR_VOL_TO_MARKET = os.environ.get("MERID_ANCHOR_VOL_TO_MARKET", "").strip().lower() in ("1", "true", "yes")

# 4c LCB(EV_net) canary threshold experiment.
MERID_CANARY_4C_LCB = os.environ.get("MERID_CANARY_4C_LCB", "").strip().lower() in ("1", "true", "yes")
MERID_CANARY_LCB_BASE_CENTS = float(os.environ.get("MERID_CANARY_LCB_BASE_CENTS", "4.0"))

# Cheap-tail canary lane: bounded exploration for 20-34c contracts.
# This is a separate lane from the core 35c+ policy; it does not lower global
# held-price or π* gates for the main lane.  It is intentionally narrow:
# one contract, YES-only by default, post-only/maker, strict EV and gap rules.
MERID_CHEAP_TAIL_CANARY_ENABLED = os.environ.get("MERID_CHEAP_TAIL_CANARY_ENABLED", "0").strip().lower() in ("1", "true", "yes")
MERID_CHEAP_TAIL_CANARY_MIN_PRICE_CENTS = int(os.environ.get("MERID_CHEAP_TAIL_CANARY_MIN_PRICE_CENTS", "20"))
MERID_CHEAP_TAIL_CANARY_MAX_PRICE_CENTS = int(os.environ.get("MERID_CHEAP_TAIL_CANARY_MAX_PRICE_CENTS", "34"))
MERID_CHEAP_TAIL_CANARY_ALLOWED_SIDES = [
    s.strip().lower()
    for s in os.environ.get("MERID_CHEAP_TAIL_CANARY_ALLOWED_SIDES", "yes").split(",")
    if s.strip()
]
MERID_CHEAP_TAIL_CANARY_ALLOWED_ASSETS = [
    s.strip().upper()
    for s in os.environ.get("MERID_CHEAP_TAIL_CANARY_ALLOWED_ASSETS", "ETH").split(",")
    if s.strip()
]
MERID_CHEAP_TAIL_CANARY_MIN_NET_EDGE_PCT = float(
    os.environ.get("MERID_CHEAP_TAIL_CANARY_MIN_NET_EDGE_PCT", "8.0")
)
MERID_CHEAP_TAIL_CANARY_MIN_PROB_GAP_PCT = float(
    os.environ.get("MERID_CHEAP_TAIL_CANARY_MIN_PROB_GAP_PCT", "9.0")
)
MERID_CHEAP_TAIL_CANARY_MIN_EV_TO_TAIL_RATIO = float(
    os.environ.get("MERID_CHEAP_TAIL_CANARY_MIN_EV_TO_TAIL_RATIO", "0.10")
)
MERID_CHEAP_TAIL_CANARY_MIN_TTE_S = float(
    os.environ.get("MERID_CHEAP_TAIL_CANARY_MIN_TTE_S", "120.0")
)
MERID_CHEAP_TAIL_CANARY_MAX_TTE_S = float(
    os.environ.get("MERID_CHEAP_TAIL_CANARY_MAX_TTE_S", "900.0")
)
MERID_CHEAP_TAIL_CANARY_MAX_DAILY = int(
    os.environ.get("MERID_CHEAP_TAIL_CANARY_MAX_DAILY", "3")
)
MERID_CHEAP_TAIL_CANARY_DAILY_FILE = os.environ.get(
    "MERID_CHEAP_TAIL_CANARY_DAILY_FILE",
    "data/cheap_tail_canary_daily.json",
)

# Bounded post-only lanes: every lane whose decision contract is one-contract
# post-only maker regardless of the primary lane's execution posture.  These
# lanes carry authoritative executable-price economics from this decision
# engine (executable ask, exact fees, depth, adverse-selection reserve), so
# downstream gates must not re-derive an approval verdict from orderbook
# midpoints or silently substitute a taker/IOC order style — they keep their
# own admission thresholds and fail closed instead.
BOUNDED_POST_ONLY_LANES = frozenset({
    "cheap_tail_canary",
    "evidence_cell_escape",
    "threshold_cell",
    "current_build_provisional",
    "trend_yes_hi",
    # 2026-10-02: queue-priced maker lane — admitted on bid-side economics
    # with an explicit adverse-selection reserve; stays 1-contract post-only.
    "maker_bid",
    # 2026-10-05 (Experiment A): empirical marginal-maker lane — bounded
    # δ-slack below the active maker bound, bid-priced, 1-contract post-only,
    # short resting life.  Cohort measured separately vs current policy.
    "empirical_marginal_maker",
    # 2026-10-05: top-edge IOC canary — taker route, so the bounded-lane
    # execution policy converts it to IOC at taker fee rather than resting
    # post-only.  1-contract, per-day submission cap.
    "canary_taker",
})

# Bounded live-entry domain + tail LCB admission gate (2026-10-01).
#
# The controlled dual-side rollout restricts *live* entries to the bounded
# domain (20-89c executable ask, 120-600s TTE).  The cbp/threshold cell grids
# bound their own admission, but the residual formula lane could still emit
# live orders outside the box — observed live: XRP NO@75 entered at TTE 823s
# and lost -75c on a toxic fill.  ``MERID_LIVE_ENTRY_MAX_TTE_S`` is the
# emit-side ceiling; decisions outside remain audited as no-trade so the band
# stays measurable.  The lower bound is untouched: per-band regime TTE floors
# and the settlement-convergence lane own it.
#
# The tail LCB gate addresses the second observed failure mode: entries at
# >=70c passed the point-EV bar while their lower confidence bound
# (net_edge - model_risk_reserve) sat below the required edge — the claimed
# edge did not survive the model's own uncertainty charge (BTC YES@77:
# lcb 1.68c < 2.5c required; XRP NO@75: lcb 1.11c < 2.85c — both lost).  In
# the 70-89c band one miss costs 70-89c against an 11-30c win, so admission
# there requires LCB >= the threshold the side was admitted on.
MERID_LIVE_ENTRY_MAX_TTE_S = float(
    os.environ.get("MERID_LIVE_ENTRY_MAX_TTE_S", "600")
)
MERID_TAIL_LCB_GATE_ENABLED = os.environ.get(
    "MERID_TAIL_LCB_GATE_ENABLED", "1"
).strip().lower() in ("1", "true", "yes")
MERID_TAIL_LCB_MIN_PRICE_CENTS = int(
    os.environ.get("MERID_TAIL_LCB_MIN_PRICE_CENTS", "70")
)

# 2026-10-04 (counterfactual audit): marginal-band edge rescue.  The settled
# counterfactual join over logs/rejected_candidates.jsonl shows candidates
# whose net edge fell <=1c short of the stacked dynamic threshold were
# net-profitable ONLY inside the 50-89c executable-price band
# (n=6,268, 76.8% counterfactual win rate, +3.75c/contract net of fees;
# <50c: +0.50c; 90c+: -3.76c — the >89c tail stays hard-gated).  The slack
# relaxes ONLY the edge-threshold leg of qualification: depth, tail-guard,
# evidence, regime, conviction, throttle, countertrend and bookflow vetoes
# are unchanged, and p_selected must still clear its cost-basis floor.
# Rescued decisions carry a per-side indicator so routing can prefer the
# ask-priced (taker) realization the counterfactual actually measured.
MERID_MARGINAL_BAND_ENABLED = os.environ.get(
    "MERID_MARGINAL_BAND_RESCUE_ENABLED", "1"
).strip().lower() in ("1", "true", "yes")
MERID_MARGINAL_BAND_SLACK = float(
    os.environ.get("MERID_MARGINAL_BAND_SLACK_CENTS", "1.0")
) / 100.0
MERID_MARGINAL_BAND_MIN_CENTS = int(
    os.environ.get("MERID_MARGINAL_BAND_MIN_CENTS", "50")
)
MERID_MARGINAL_BAND_MAX_CENTS = int(
    os.environ.get("MERID_MARGINAL_BAND_MAX_CENTS", "89")
)


def _marginal_band_slack(entry_price_cents: Optional[float]) -> float:
    """Edge-threshold slack (probability units) for the profitable near-miss
    band.  Zero outside [50, 89]c — the 90c+ tail cohort lost money even at
    86.8% counterfactual win rate (fee + asymmetric payout), and sub-50c
    near-misses are only +0.50c/trade — not worth the added flow."""
    if not MERID_MARGINAL_BAND_ENABLED or entry_price_cents is None:
        return 0.0
    try:
        p = float(entry_price_cents)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(p):
        return 0.0
    # Upper bound is exclusive-ish: executable_entry_price*100 is a float that
    # can carry epsilon above an integer-cent ask, so admit [MIN, MAX+1).
    if MERID_MARGINAL_BAND_MIN_CENTS <= p < MERID_MARGINAL_BAND_MAX_CENTS + 1.0:
        return MERID_MARGINAL_BAND_SLACK
    return 0.0


# 2026-10-05 (SOL post-mortem): evidence_escape admission narrowing.  The
# lane is a discretionary override over thin evidence — its fills include the
# knife-edge 206s-TTE SOL NO@52 loss where the book went one-sided and the
# position never saw a salvageable exit.  Escape admissions now carry their
# own vetoes on top of the escape budget:
#   * no BTC/SOL/DOGE admission in the 120-240s TTE window — the realized
#     toxic maker cohort (-461c over 31 fills, -15c/fill, 2026-10 audit);
#   * knife-edge buffer: inside the 40-60c price band the spot must sit at
#     least K * sigma*sqrt(TTE) from the strike, else the contract is a pure
#     gamma coin-flip the evidence lane has no basis to override;
#   * mid-band extra margin: 40-60c escape admissions require net EV >=
#     required_edge + MERID_ESCAPE_MID_EXTRA_CENTS;
#   * one-sided bookflow veto: opposing-side book pressure above the shared
#     imbalance block (applied on every route — resting OR crossing into a
#     one-sided book is the same pick-off signature);
#   * counter-move veto: the trailing 60s underlying return must not
#     contradict the selected side beyond MERID_ESCAPE_COUNTER_BPS.
# Every veto is env-gated and degrades open on missing inputs (the evidence
# gate itself remains the hard block).
MERID_ESCAPE_LATE_ASSETS = frozenset(
    a.strip().upper()
    for a in os.environ.get("MERID_ESCAPE_LATE_ASSETS", "BTC,SOL,DOGE").split(",")
    if a.strip()
)
MERID_ESCAPE_LATE_TTE_LO_S = float(
    os.environ.get("MERID_ESCAPE_LATE_TTE_LO_S", "120")
)
MERID_ESCAPE_LATE_TTE_HI_S = float(
    os.environ.get("MERID_ESCAPE_LATE_TTE_HI_S", "240")
)
MERID_ESCAPE_KNIFE_LO_C = float(os.environ.get("MERID_ESCAPE_KNIFE_LO_C", "40"))
MERID_ESCAPE_KNIFE_HI_C = float(os.environ.get("MERID_ESCAPE_KNIFE_HI_C", "60"))
MERID_ESCAPE_KNIFE_K = float(os.environ.get("MERID_ESCAPE_KNIFE_K", "0.5"))
MERID_ESCAPE_MID_EXTRA_C = float(
    os.environ.get("MERID_ESCAPE_MID_EXTRA_CENTS", "1.0")
)
MERID_ESCAPE_BOOKFLOW_VETO = os.environ.get(
    "MERID_ESCAPE_BOOKFLOW_VETO", "1"
).strip().lower() in ("1", "true", "yes")
MERID_ESCAPE_COUNTER_BPS = float(
    os.environ.get("MERID_ESCAPE_COUNTER_BPS", "10.0")
)


def _evidence_escape_veto_reason(
    *,
    asset: str,
    side: str,
    price_cents: float,
    net_ev_cents: float,
    required_edge_cents: float,
    seconds_to_expiry: Optional[float],
    spot_price: Optional[float],
    strike_price: Optional[float],
    annualized_vol: Optional[float],
    feature_snapshot: Any,
    dir_regime: Any,
) -> Optional[str]:
    """Additional vetoes for evidence_escape admissions (see block above).

    Returns a snake_case reason stem (``evidence_escape_<cause>``) or None
    when the escape admission is clean.  Fail-open on missing inputs — each
    check only fires on data it can actually evaluate.
    """
    tte = float(seconds_to_expiry or 0.0)
    # Late-window maker/taker cohort veto — the realized -15c/fill bucket.
    if (
        asset.upper() in MERID_ESCAPE_LATE_ASSETS
        and MERID_ESCAPE_LATE_TTE_LO_S <= tte <= MERID_ESCAPE_LATE_TTE_HI_S
    ):
        return "evidence_escape_late_window"
    _px = float(price_cents or 0.0)
    if MERID_ESCAPE_KNIFE_LO_C <= _px <= MERID_ESCAPE_KNIFE_HI_C:
        # Mid-band extra margin: knife-edge prices carry the most model risk.
        if net_ev_cents < required_edge_cents + MERID_ESCAPE_MID_EXTRA_C:
            return "evidence_escape_mid_band_margin"
        # Distance-to-strike buffer normalized by sigma*sqrt(TTE).
        try:
            if (
                spot_price is not None
                and strike_price is not None
                and spot_price > 0
                and strike_price > 0
                and annualized_vol is not None
                and float(annualized_vol) > 0
                and tte > 0
            ):
                move = abs(math.log(float(spot_price) / float(strike_price)))
                sigma_t = float(annualized_vol) * math.sqrt(tte / 31557600.0)
                if sigma_t > 0 and move < MERID_ESCAPE_KNIFE_K * sigma_t:
                    return "evidence_escape_knife_edge"
        except (TypeError, ValueError):
            pass
    # One-sided book pressure opposite the held side.
    if MERID_ESCAPE_BOOKFLOW_VETO:
        try:
            from merid.prediction import directional_regime as _dreg

            _bf = _dreg.bookflow_block_reason(feature_snapshot, asset, side)
        except Exception:
            _bf = None
        if _bf is not None:
            return "evidence_escape_bookflow"
    # Trailing-60s underlying move contradicts the held side.
    try:
        _r60 = None
        if dir_regime is not None:
            _r60 = (getattr(dir_regime, "asset_r60", None) or {}).get(
                str(asset).upper()
            )
        if _r60 is not None and math.isfinite(float(_r60)):
            tol = MERID_ESCAPE_COUNTER_BPS / 10000.0
            if side == "no" and float(_r60) > tol:
                return "evidence_escape_counter_move"
            if side == "yes" and float(_r60) < -tol:
                return "evidence_escape_counter_move"
    except (TypeError, ValueError):
        pass
    return None


# ── Experiment A: empirical_marginal_maker lane (2026-10-05) ───────────────
# The controlled minimum-opportunity experiment: a bounded δ-slack below the
# active maker requirement, evaluated at the BID (truly non-marketable),
# inside a declared admission domain (50-89c entry, 240-600s TTE).  The
# domain itself encodes the exclusions: TTE<240s keeps the lane out of the
# toxic 2-4min passive-maker bucket, and evidence-escape-owned sides are
# denied the slack per-side below.  Route "empirical_marginal_maker" only —
# never widened into the generic taker marginal band.
# δ in edge units (probability/dollars, same convention as
# MERID_MARGINAL_BAND_SLACK — 0.005 = 0.5¢ of edge).
EMM_SLACK = float(os.environ.get("MERID_EMM_SLACK", "0.005"))
EMM_PRICE_LO_CENTS = float(os.environ.get("MERID_EMM_PRICE_LO_CENTS", "50"))
EMM_PRICE_HI_CENTS = float(os.environ.get("MERID_EMM_PRICE_HI_CENTS", "90"))
EMM_TTE_LO_SECONDS = int(os.environ.get("MERID_EMM_TTE_LO_SECONDS", "240"))
EMM_TTE_HI_SECONDS = int(os.environ.get("MERID_EMM_TTE_HI_SECONDS", "600"))


def _marginal_maker_slack(
    entry_price_cents: float, seconds_to_expiry: Optional[float]
) -> float:
    """Bounded marginal-maker slack: δ inside the declared admission domain,
    zero outside — the near-miss cohort is measured, not widened."""
    if seconds_to_expiry is None:
        return 0.0
    if (
        EMM_PRICE_LO_CENTS <= entry_price_cents < EMM_PRICE_HI_CENTS
        and EMM_TTE_LO_SECONDS <= float(seconds_to_expiry) <= EMM_TTE_HI_SECONDS
    ):
        return EMM_SLACK
    return 0.0


# In-memory and persisted daily canary attempt accounting.
_cheap_tail_canary_daily_lock = threading.RLock()
_cheap_tail_canary_daily_state: Dict[str, Any] = {}


def _load_cheap_tail_canary_daily_state() -> Dict[str, Any]:
    """Load or initialize the persisted cheap-tail canary daily counter."""
    global _cheap_tail_canary_daily_state
    with _cheap_tail_canary_daily_lock:
        if _cheap_tail_canary_daily_state:
            return dict(_cheap_tail_canary_daily_state)
        try:
            path = Path(MERID_CHEAP_TAIL_CANARY_DAILY_FILE)
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = {}
        except Exception:
            data = {}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if "date" not in data or data.get("date") != today:
            data = {"date": today, "count": 0, "assets": {}}
        _cheap_tail_canary_daily_state = data
        return dict(data)


def _canary_daily_count(asset: Optional[str] = None) -> int:
    with _cheap_tail_canary_daily_lock:
        state = _load_cheap_tail_canary_daily_state()
        if asset:
            return int(state.get("assets", {}).get(asset, 0))
        return int(state.get("count", 0))


def _increment_canary_daily_count(asset: str) -> None:
    with _cheap_tail_canary_daily_lock:
        state = _load_cheap_tail_canary_daily_state()
        state["count"] = int(state.get("count", 0)) + 1
        assets = state.setdefault("assets", {})
        assets[asset] = int(assets.get(asset, 0)) + 1
        _cheap_tail_canary_daily_state = state
        try:
            Path(MERID_CHEAP_TAIL_CANARY_DAILY_FILE).parent.mkdir(parents=True, exist_ok=True)
            Path(MERID_CHEAP_TAIL_CANARY_DAILY_FILE).write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("[CHEAP-TAIL-CANARY] failed to persist daily count: %s", exc)


def _inverse_normal_cdf(p: float) -> float:
    """Return the inverse CDF of the standard normal distribution.

    Uses the standard-library ``statistics.NormalDist`` so no external
    dependencies are required.  Values are clamped to (epsilon, 1-epsilon) to
    avoid divergence at the tails.
    """
    p = max(1e-9, min(1.0 - 1e-9, p))
    return statistics.NormalDist().inv_cdf(p)


def _compute_bachelier_components(
    spot_price: float,
    strike_price: float,
    seconds_to_expiry: float,
    annualized_vol: float,
) -> Optional[Dict[str, float]]:
    """Return Bachelier z-score, log-moneyness, and raw p_yes.

    ``p_yes_raw`` is not clipped to the [0.05, 0.95] venue band so callers can
    see the model's unclipped opinion.
    """
    if not all(math.isfinite(x) for x in (spot_price, strike_price, seconds_to_expiry, annualized_vol)):
        return None
    if seconds_to_expiry <= 0 or strike_price <= 0 or annualized_vol <= 0:
        return None
    t_years = seconds_to_expiry / (365.0 * 24.0 * 60.0 * 60.0)
    log_moneyness = math.log(spot_price / strike_price) if strike_price > 0 else 0.0
    sigma = max(annualized_vol, 1e-6)
    # Black-model digital call: P(S_T > K) = N(d2) with
    # d2 = (ln(S/K) - sigma^2 T / 2) / (sigma * sqrt(T)).
    # The -sigma^2 T/2 Ito correction was previously omitted; at 15-minute
    # horizons it is small (~1e-5) but including it keeps the z-score
    # consistent with the standard risk-neutral digital used by the market.
    z = (log_moneyness - 0.5 * sigma * sigma * t_years) / (sigma * math.sqrt(t_years))
    p_yes_raw = max(0.0, min(1.0, 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))))
    return {
        "log_moneyness": log_moneyness,
        "z_score": z,
        "p_yes_raw": p_yes_raw,
        "t_years": t_years,
        "sigma": sigma,
    }


def _compute_market_implied_vol(
    spot_price: float,
    strike_price: float,
    seconds_to_expiry: float,
    market_prob: float,
) -> Optional[float]:
    """Back out annualized vol from the Kalshi market price via the Bachelier model.

    This is a diagnostic/anchor, not the primary p_yes.  Returns None when the
    market is at-the-money, the price is too close to 0/1, or spot and market
    disagree on direction, in which case the caller falls back to the configured
    default.
    """
    if not all(math.isfinite(x) for x in (spot_price, strike_price, seconds_to_expiry, market_prob)):
        return None
    if seconds_to_expiry <= 0 or strike_price <= 0:
        return None
    if market_prob <= 1e-4 or market_prob >= 1.0 - 1e-4:
        return None
    t_years = seconds_to_expiry / (365.0 * 24.0 * 60.0 * 60.0)
    if t_years <= 0:
        return None
    log_moneyness = math.log(spot_price / strike_price)
    if abs(log_moneyness) < 1e-9:
        return None
    z_target = _inverse_normal_cdf(market_prob)
    if z_target == 0.0:
        return None
    # Market price and spot must agree on direction.  If they disagree, the
    # quoted price is stale or the strike is stale; do not trust the implied vol.
    if log_moneyness * z_target <= 0:
        return None
    sigma = log_moneyness / (z_target * math.sqrt(t_years))
    if not math.isfinite(sigma) or sigma <= 0:
        return None
    return sigma


def _clamp_annualized_vol(asset: str, vol: float, source: str = "default") -> float:
    """Clamp annualized vol to the per-asset sanity band and log drift.

    A value outside the band is a config/input-drift red flag.  The band can be
    widened via ``MERID_MIN_ANNUALIZED_VOL`` / ``MERID_MAX_ANNUALIZED_VOL`` or
    per-asset env overrides.  Non-finite or non-positive values fallback to the
    band minimum.
    """
    asset = asset.upper() if asset else ""
    band = _ANNUALIZED_VOL_BANDS.get(asset, (_ANNUALIZED_VOL_GLOBAL_MIN, _ANNUALIZED_VOL_GLOBAL_MAX))
    env_min = os.environ.get(f"MERID_MIN_ANNUALIZED_VOL_{asset}")
    env_max = os.environ.get(f"MERID_MAX_ANNUALIZED_VOL_{asset}")
    if env_min is not None:
        try:
            band = (float(env_min), band[1])
        except ValueError:
            pass
    if env_max is not None:
        try:
            band = (band[0], float(env_max))
        except ValueError:
            pass
    mn, mx = band
    mn = max(mn, _ANNUALIZED_VOL_GLOBAL_MIN)
    mx = min(mx, _ANNUALIZED_VOL_GLOBAL_MAX)

    if not math.isfinite(vol) or vol <= 0:
        logger.warning(
            "[VOL-SANITY-CLAMP] asset=%s source=%s vol=%s is non-finite or non-positive; falling back to %.4f",
            asset, source, vol, mn,
        )
        return mn
    if vol < mn:
        logger.warning(
            "[VOL-SANITY-CLAMP] asset=%s source=%s vol=%.4f below band [%.4f, %.4f]; clamping to %.4f",
            asset, source, vol, mn, mx, mn,
        )
        return mn
    if vol > mx:
        logger.warning(
            "[VOL-SANITY-CLAMP] asset=%s source=%s vol=%.4f above band [%.4f, %.4f]; clamping to %.4f",
            asset, source, vol, mn, mx, mx,
        )
        return mx
    return vol


def _fetch_realized_vol(asset: str) -> Optional[float]:
    """Return the canonical realized vol if it is fresh and confident.

    Sources an EWMA realized-volatility estimate built from the live RTI/spot
    tick stream (see ``merid.prediction.realized_vol``).  Returns ``None`` when
    the estimator has insufficient samples or the last tick is stale — callers
    then fall back to the next vol source in ``_resolve_annualized_vol``.
    """
    if not MERID_USE_REALIZED_VOL:
        return None
    try:
        from merid.prediction.realized_vol import get_realized_vol_tracker

        estimate = get_realized_vol_tracker().annualized_vol(asset)
        if estimate is None:
            return None
        return float(estimate.value)
    except Exception as exc:
        logger.warning("[VOL-REALIZED] asset=%s failed to fetch realized vol: %s", asset, exc)
        return None


def _resolve_annualized_vol(
    asset: str,
    requested_vol: float,
    spot_price: Optional[float] = None,
    strike_price: Optional[float] = None,
    seconds_to_expiry: Optional[float] = None,
    market_prob: Optional[float] = None,
) -> Tuple[float, str, float, float, Optional[Dict[str, float]]]:
    """Resolve the final annualized vol for the Bachelier model.

    Priority:
      1. Explicit env override ``MERID_ANNUALIZED_VOL_{ASSET}`` (legacy).
      2. Realized vol from SentimentVolService (if ``MERID_USE_REALIZED_VOL=1`` and fresh).
      3. Market-implied vol backed out of the Kalshi price (if ``MERID_ANCHOR_VOL_TO_MARKET=1``).
      4. The caller-supplied ``requested_vol`` (usually the code default).

    The chosen value is sanity-clamped and returned along with the source, the
    band min/max, and the Bachelier components computed with the clamped vol.
    If spot/strike/TTE are not supplied, the Bachelier components are None.
    """
    asset = asset.upper() if asset else ""
    source = "requested"
    env_override = os.environ.get(f"MERID_ANNUALIZED_VOL_{asset}")
    if env_override is not None:
        try:
            requested_vol = float(env_override)
            source = "env_override"
        except ValueError:
            logger.warning("[VOL-RESOLVE] asset=%s invalid MERID_ANNUALIZED_VOL_%s=%s; ignoring", asset, asset, env_override)

    resolved_vol: Optional[float] = None
    tried: List[str] = []

    realized = _fetch_realized_vol(asset)
    if realized is not None:
        resolved_vol = realized
        source = "realized"
        tried.append("realized")

    if resolved_vol is None and MERID_ANCHOR_VOL_TO_MARKET:
        if market_prob is not None and spot_price is not None and strike_price is not None and seconds_to_expiry is not None:
            implied = _compute_market_implied_vol(spot_price, strike_price, seconds_to_expiry, market_prob)
            if implied is not None:
                resolved_vol = implied
                source = "market_implied"
            tried.append("market_implied")

    if resolved_vol is None:
        resolved_vol = requested_vol
        source = source if source != "requested" else "default"

    band = _ANNUALIZED_VOL_BANDS.get(asset, (_ANNUALIZED_VOL_GLOBAL_MIN, _ANNUALIZED_VOL_GLOBAL_MAX))
    env_min = os.environ.get(f"MERID_MIN_ANNUALIZED_VOL_{asset}")
    env_max = os.environ.get(f"MERID_MAX_ANNUALIZED_VOL_{asset}")
    if env_min is not None:
        try:
            band = (float(env_min), band[1])
        except ValueError:
            pass
    if env_max is not None:
        try:
            band = (band[0], float(env_max))
        except ValueError:
            pass
    mn, mx = band
    mn = max(mn, _ANNUALIZED_VOL_GLOBAL_MIN)
    mx = min(mx, _ANNUALIZED_VOL_GLOBAL_MAX)

    clamped = _clamp_annualized_vol(asset, resolved_vol, source)
    if clamped != resolved_vol:
        source = f"{source}_clamped"

    components: Optional[Dict[str, float]] = None
    if spot_price is not None and strike_price is not None and seconds_to_expiry is not None:
        components = _compute_bachelier_components(spot_price, strike_price, seconds_to_expiry, clamped)

    return clamped, source, mn, mx, components


def _get_resolved_live_config() -> Optional[Any]:
    """Return the resolved live config if available, otherwise None."""
    try:
        from merid.config.live_config import get_resolved_live_config

        resolved = get_resolved_live_config(allow_unresolved=True)
        if resolved.resolved:
            return resolved
    except Exception:
        pass
    return None


def _get_resolved_min_required_edge(default: float) -> float:
    """Use the resolved live config edge floor if it is stricter."""
    resolved = _get_resolved_live_config()
    if resolved is None:
        return default
    resolved_edge = float(resolved.min_required_edge)
    return max(default, resolved_edge)


class EdgeThresholdDecomposition(NamedTuple):
    """Component breakdown of the dynamic min-required-edge threshold.

    Every value is in probability points (0-1 scale); multiply by 100 for
    cents.  ``total`` is the clamped value actually compared against
    ``net_edge``.
    """
    total: float
    base_floor: float          # max(global floor, asset tier floor)
    global_floor: float        # floor_min_required_edge input
    asset_base: float          # asset liquidity tier floor
    convexity: float           # K * p*(1-p) adverse-selection term
    flb_premium: float         # favorite-longshot-bias premium (p < 0.35)
    clamped_floor: bool        # True if the 0.02 floor bound
    clamped_ceiling: bool      # True if the 0.15 ceiling bound
    band_relief: float = 0.0   # 50-89c marginal-band threshold relief (subtracted)
    cell_id: Optional[str] = None       # threshold-cell override id
    cell_min_ev_cents: Optional[float] = None  # cell threshold, cents
    cell_cap_exhausted: bool = False    # cell matched but daily lane cap hit
    formula_total: Optional[float] = None     # formula output before cell replace
    cell_block_reason: Optional[str] = None   # matched-but-suppressed reason
    provisional_cell_id: Optional[str] = None       # current-build provisional cell
    provisional_min_ev_cents: Optional[float] = None
    provisional_cap_exhausted: bool = False         # cell matched but lane cap/state blocked
    provisional_block_reason: Optional[str] = None


def _compute_dynamic_min_required_edge(
    asset: str,
    price_cents: int,
    side: Literal["yes", "no"],
    yes_bid_cents: float,
    yes_ask_cents: float,
    no_bid_cents: float,
    no_ask_cents: float,
    floor_min_required_edge: float,
    seconds_to_expiry: Optional[float] = None,
) -> float:
    """Compute a fee-aware, asset-tiered edge threshold (total only).

    Returns ``_decompose_dynamic_min_required_edge(...).total``; call sites
    that need the component breakdown use the decompose variant directly.
    """
    return _decompose_dynamic_min_required_edge(
        asset=asset,
        price_cents=price_cents,
        side=side,
        yes_bid_cents=yes_bid_cents,
        yes_ask_cents=yes_ask_cents,
        no_bid_cents=no_bid_cents,
        no_ask_cents=no_ask_cents,
        floor_min_required_edge=floor_min_required_edge,
        seconds_to_expiry=seconds_to_expiry,
    ).total


def _decompose_dynamic_min_required_edge(
    asset: str,
    price_cents: int,
    side: Literal["yes", "no"],
    yes_bid_cents: float,
    yes_ask_cents: float,
    no_bid_cents: float,
    no_ask_cents: float,
    floor_min_required_edge: float,
    seconds_to_expiry: Optional[float] = None,
) -> EdgeThresholdDecomposition:
    """Compute a fee-aware, asset-tiered edge threshold with decomposition.

    The threshold is applied to ``net_edge`` (after Kalshi fees, exit-cost
    reserve, and model-risk reserve).  It therefore represents the required
    *pure edge* profit floor, not the full cost stack.

    Components:
      - Asset-tier base floor (BTC most liquid, DOGE/XRP least).
      - Convex price-risk term: ``K * p * (1-p)`` peaks at 50c where taker
        fee and adverse-selection risk are largest and shrinks in the tails.
        Halved for held prices >=50c: the taker fee is already deducted inside
        net_edge and the counterfactual rejection join (390k settled
        candidates, 2026-09) showed the marginal 0-2c-below-gate band on
        favorites was net profitable (+9.7c/trade, 75% win rate) -- the full
        convexity term was over-rejecting favorites.
      - FLB longshot premium for held prices below 35c.

    The bid/ask spread is deliberately NOT added here: ``executable_entry_price``
    is the taker ask, so the full spread is already charged inside gross_edge,
    and the pi* cost stack charges ``spread_slippage_prob`` again.  Adding a
    third half-spread term was double-charging the same cost.

    The final value is clamped to the global floor and a 15% sanity ceiling.

    2026-09-27 threshold refit (scripts/_gate_cost_analysis.py): 20,744
    settled candidates the model scored net-positive but the edge gate
    rejected realized this at expiry, net of fees at the decision-time ask:

        <25c:  -0.41c   25-34c: -0.93c   (FLB premium remains justified)
        35-44c:+2.51c   45-49c: +7.00c   50-64c: +10.04c (all 5 assets
        +8.5c..+13.7c)  65-74c: +8.01c   75+c: +4.66c

    The old floors (BTC 3c / ETH,SOL 4c / XRP,DOGE 5c) + FLB premium from
    50c rejected ~700 model-liked candidates/day in the 35c+ band that
    realized +2.5c..+10c per trade.  Floors halved; FLB premium now starts
    below 35c where the realized data actually turns toxic.
    """
    asset_base = {
        "BTC": 0.015,
        "ETH": 0.02,
        "SOL": 0.02,
        "XRP": 0.025,
        "DOGE": 0.025,
    }.get(asset.upper(), 0.025)

    base = max(float(floor_min_required_edge), asset_base)

    # Price-adj convexity term.  At 50c, p*(1-p) = 0.25 -> 0.01 (1 point).
    # At 10c/90c, p*(1-p) = 0.09 -> 0.0036 (0.36 points).
    p = float(price_cents) / 100.0
    p = max(0.01, min(0.99, p))
    convexity_k = 0.04 if p < 0.5 else 0.02
    price_adj = convexity_k * p * (1.0 - p)

    # Favorite-longshot bias reserve.  Our own settled-candidate join
    # (2026-09-27, n=20,744 model-liked rejects) shows the realized turn only
    # below 35c: 25-34c nets -0.93c, sub-25c -0.41c, while 35-44c is +2.51c
    # and 45-49c +7.0c.  The premium therefore starts below 35c, not 50c
    # (Burgi-style sub-50c research holds for unconditional base rates, but
    # our model-conditioned 35-50c cells clear fees).
    flb_adj = MERID_FLB_LONGSHOT_SLOPE * max(0.0, 0.35 - p)

    # 2026-10-02: marginal-band relief — the settled counterfactual shows the
    # 0-2c-below-gate cohort is net profitable only at held prices 50-89c.
    # Subtracted before the clamp; the 0.02 hard floor still binds.
    band_relief = 0.0
    if (
        MERID_EDGE_MID_BAND_RELIEF_CENTS > 0.0
        and MERID_EDGE_MID_BAND_LO_CENTS <= float(price_cents) <= MERID_EDGE_MID_BAND_HI_CENTS
    ):
        band_relief = MERID_EDGE_MID_BAND_RELIEF_CENTS / 100.0

    dynamic = base + price_adj + flb_adj - band_relief
    total = max(0.02, min(dynamic, 0.15))

    # 2026-09-30: conditional threshold cells (merid.prediction.threshold_cells)
    # replace the formula output inside the empirically-qualified
    # asset x side x price x TTE regions from the settled counterfactual
    # frontier.  The cell value is the single source of truth there — the
    # 0.02 floor clamp intentionally does NOT apply (SOL-NO mid band is
    # qualified at 1.5c).  Formula components are still returned for audit.
    cell = resolve_threshold_cell(asset, side, price_cents, seconds_to_expiry)
    formula_total = total
    cell_cap_hit = False
    cell_block_reason: Optional[str] = None
    prov_cell = None
    prov_cap_hit = False
    prov_block_reason: Optional[str] = None
    if cell is not None:
        bump_cell_funnel("matched", cell.cell_id)
        _allowed, _block = cell_admission(cell.cell_id)
        if not _allowed:
            # Lane not admitting (suspended / caps / kill switch): fail closed
            # to the legacy formula and surface the suppression in telemetry.
            cell_cap_hit = True
            cell_block_reason = _block or "cell_admission_blocked"
            cell = None
    if cell is None and cell_block_reason is None and not cell_region_registered(
        asset, side, price_cents, seconds_to_expiry
    ):
        # Current-build dual-side provisional lane: owns only regions with no
        # configured registry cell.  A SUSPENDED, cap-blocked, or lane-disabled
        # registered cell keeps sole authority over its band — never re-opened
        # here.
        prov_cell = _cbp.resolve_provisional_cell(
            asset, side, price_cents, seconds_to_expiry
        )
        if prov_cell is not None:
            _cbp.bump_provisional_funnel("matched", prov_cell.cell_id)
            _p_ok, _p_block = _cbp.provisional_cell_admission(prov_cell.cell_id)
            if not _p_ok:
                prov_cap_hit = True
                prov_block_reason = _p_block or "provisional_admission_blocked"
                prov_cell = None
    if cell is not None:
        total = max(0.0, min(cell.min_net_ev_cents / 100.0, 0.15))
    elif prov_cell is not None:
        # Provisional cells may carry a negative min-EV (env-bounded by
        # MERID_PROVISIONAL_MIN_EV_FLOOR_C, default 0.0) — that admits
        # shallow-negative-EV candidates into the capped bootstrap lane so
        # its own fills can settle whether the cell is truly underpriced.
        _pc_min = _cbp.cell_min_ev_cents(prov_cell) / 100.0
        _pc_floor = _cbp.provisional_min_ev_floor_cents() / 100.0
        total = max(_pc_floor, min(_pc_min, 0.15))

    return EdgeThresholdDecomposition(
        total=total,
        base_floor=base,
        global_floor=float(floor_min_required_edge),
        asset_base=asset_base,
        convexity=price_adj,
        flb_premium=flb_adj,
        band_relief=band_relief,
        clamped_floor=(cell is None and total == 0.02 and dynamic < 0.02),
        clamped_ceiling=(cell is None and total == 0.15 and dynamic > 0.15),
        cell_id=cell.cell_id if cell is not None else None,
        cell_min_ev_cents=(
            float(cell.min_net_ev_cents) if cell is not None else None
        ),
        cell_cap_exhausted=cell_cap_hit,
        formula_total=formula_total,
        cell_block_reason=cell_block_reason,
        provisional_cell_id=(
            prov_cell.cell_id if prov_cell is not None else None
        ),
        provisional_min_ev_cents=(
            float(_cbp.cell_min_ev_cents(prov_cell))
            if prov_cell is not None else None
        ),
        provisional_cap_exhausted=prov_cap_hit,
        provisional_block_reason=prov_block_reason,
    )


def _get_resolved_min_p_selected(default: float) -> float:
    """Use the resolved live config p_selected floor if it is stricter."""
    resolved = _get_resolved_live_config()
    if resolved is None:
        return float(default)
    resolved_p = float(resolved.min_p_selected)
    return max(float(default), resolved_p)


def _probability_source_allowed(source: str) -> bool:
    """Fail-closed allowlist for probability sources admitted into the decision.

    When an immutable live config has been resolved, only sources in
    ``resolved.allowed_probability_sources`` may contribute to the live
    decision probability; the legacy module flag alone cannot admit a source.
    Before resolution (dev/test), the legacy ``MERID_TRADE_DECISION_ALLOW_HYBRID_P``
    flag is the fallback so existing non-prod behavior is preserved.
    """
    resolved = _get_resolved_live_config()
    if resolved is not None:
        allowed = getattr(resolved, "allowed_probability_sources", None)
        if not allowed:
            allowed = ("settlement_rti_bachelier_v2",)
        return source in allowed
    if source == "hybrid_bachelier_deltas":
        return bool(MERID_TRADE_DECISION_ALLOW_HYBRID_P)
    return True


def _min_p_for_side(breakdown: EdgeBreakdown, floor: float) -> float:
    """Return the side-aware minimum p_selected for a positive-EV trade.

    The model probability must exceed the all-in cost basis of the held
    side: executable entry price plus entry fee, expected exit cost, and
    model-risk reserve.  The absolute ``floor`` (from env / live config) is
    applied as an additional hard minimum.
    """
    cost_basis = (
        breakdown.executable_entry_price
        + breakdown.entry_fee
        + breakdown.exit_cost_reserve
        + breakdown.model_risk_reserve
    )
    return max(floor, cost_basis)


def _get_resolved_min_held_price_cents(default: float) -> float:
    """Use the resolved live config held-price floor if it is stricter."""
    resolved = _get_resolved_live_config()
    if resolved is None:
        return default
    resolved_floor = float(resolved.min_held_price_cents)
    return max(default, resolved_floor)


def _get_resolved_config_hash() -> Optional[str]:
    """Return the resolved live config hash if available."""
    resolved = _get_resolved_live_config()
    return resolved.config_hash if resolved is not None else None


def _get_resolved_max_contracts() -> int:
    """Return the resolved per-order contract cap, falling back to env/default.

    In 4c LCB canary mode the per-order cap is always one contract.  The canary
    is intentionally tiny and one contract is the minimum non-zero exposure.
    """
    if MERID_CANARY_4C_LCB:
        return 1
    resolved = _get_resolved_live_config()
    if resolved is not None and resolved.max_contracts_per_order is not None:
        return int(resolved.max_contracts_per_order)
    try:
        return int(os.environ.get("MERID_MAX_CONTRACTS_PER_ORDER", "2"))
    except Exception:
        return 2


def _canary_lcb_threshold_cents(
    asset: str,
    price_cents: int,
    vol_source: str,
    settlement_reference: str,
) -> float:
    """Return the required LCB(EV_net) threshold in cents for the 4c canary.

    The threshold is a function of asset liquidity, price bucket, volatility
    source, and settlement-reference quality.  It is *never* a single global 4c
    floor; the floor is 4c for the safest domain (BTC/ETH, 30-70c, validated
    vol, live RTI settlement reference) and higher everywhere else.
    """
    if vol_source in ("default", "requested", "fallback", "unknown"):
        return float("inf")
    if settlement_reference != "cfb_rti_live":
        return float("inf")
    if price_cents < 10 or price_cents > 75:
        return float("inf")

    threshold = MERID_CANARY_LCB_BASE_CENTS

    asset_premium = {
        "BTC": 0.0,
        "ETH": 0.0,
        "SOL": 1.0,
        "XRP": 1.0,
        "DOGE": 2.0,
    }.get(asset.upper(), 2.0)
    threshold += asset_premium

    if 10 <= price_cents <= 19 or 66 <= price_cents <= 75:
        threshold += 3.0
    elif 20 <= price_cents <= 29 or 56 <= price_cents <= 65:
        threshold += 1.0

    return threshold


def _threshold_json(threshold: float) -> Any:
    return threshold if math.isfinite(threshold) else "inf"


def apply_canary_lcb_gate(
    decision: TradeDecision,
    asset: str,
    annualized_vol_source: str,
    settlement_reference: str,
) -> TradeDecision:
    """Apply the 4c LCB(EV_net) canary threshold to a TradeDecision.

    This is a fail-closed overlay: if MERID_CANARY_4C_LCB is not set, the
    decision is returned unchanged.  When set, the selected side must clear the
    conditional LCB threshold; otherwise the decision is downgraded to a
    no-trade with a structured shadow-cohort record.  Sizing is capped at one
    contract for the canary.
    """
    if not MERID_CANARY_4C_LCB:
        return decision

    original_selected = decision.selected_outcome

    def _lcb_cents(side: str) -> float:
        net_edge = float(getattr(decision, f"{side}_net_edge", Decimal("0")))
        risk_reserve = float(getattr(decision, f"model_risk_reserve_{side}", Decimal("0")))
        return (net_edge - risk_reserve) * 100.0

    def _price_cents(side: str) -> int:
        entry = getattr(decision, f"{side}_entry_vwap", Decimal("0"))
        if entry is None:
            return -1
        return int(round(float(entry) * 100.0))

    yes_price = _price_cents("yes")
    no_price = _price_cents("no")
    yes_lcb = _lcb_cents("yes")
    no_lcb = _lcb_cents("no")

    yes_threshold = _canary_lcb_threshold_cents(asset, yes_price, annualized_vol_source, settlement_reference)
    no_threshold = _canary_lcb_threshold_cents(asset, no_price, annualized_vol_source, settlement_reference)

    yes_selected = (
        float(decision.yes_net_edge) > 0
        and yes_lcb >= yes_threshold - 1e-9
        and original_selected == "yes"
    )
    no_selected = (
        float(decision.no_net_edge) > 0
        and no_lcb >= no_threshold - 1e-9
        and original_selected == "no"
    )

    would_enter_at_canary = bool(yes_selected or no_selected)
    would_enter_at_prior = original_selected is not None

    shadow_cohort = {
        "canary_enabled": True,
        "canary_base_cents": MERID_CANARY_LCB_BASE_CENTS,
        "annualized_vol_source": annualized_vol_source,
        "settlement_reference": settlement_reference,
        "yes_price_cents": yes_price,
        "yes_lcb_cents": yes_lcb,
        "yes_threshold_cents": _threshold_json(yes_threshold),
        "yes_would_enter": yes_selected,
        "no_price_cents": no_price,
        "no_lcb_cents": no_lcb,
        "no_threshold_cents": _threshold_json(no_threshold),
        "no_would_enter": no_selected,
        "would_enter_at_canary": would_enter_at_canary,
        "would_enter_at_prior_threshold": would_enter_at_prior,
        "delta_reason": None,
    }

    new_indicators = dict(decision.indicators or {})
    new_indicators["shadow_cohort"] = shadow_cohort

    if would_enter_at_canary:
        size_cc = min(int(decision.approved_size_cc or 0), 100)
        return replace(
            decision,
            indicators=new_indicators,
            approved_size_cc=Decimal(str(size_cc)) if size_cc > 0 else Decimal("0"),
        )

    if would_enter_at_prior:
        shadow_cohort["delta_reason"] = "lcb_below_canary_threshold"
        new_indicators["shadow_cohort"] = shadow_cohort

    return replace(
        decision,
        selected_outcome=None,
        selected_action=None,
        selected_side_pre_edge=None,
        selected_outcome_price=None,
        gross_edge=None,
        net_edge=None,
        p_selected=None,
        p_opposite=None,
        approved_size_cc=Decimal("0"),
        no_trade_reason=shadow_cohort["delta_reason"] or decision.no_trade_reason or "lcb_canary_no_trade",
        indicators=new_indicators,
    )


def _downgrade_live_selection(
    decision: TradeDecision,
    reason: str,
    gate_record: Dict[str, Any],
) -> TradeDecision:
    """Downgrade a selected decision to no-trade under a bounded-domain gate.

    The selection fields are cleared exactly as the canary overlays do; the
    per-side breakdowns stay attached so audit rows keep the measured EV, and
    ``indicators["bounded_domain_gate"]`` records why the live emit was vetoed.
    """
    new_indicators = dict(decision.indicators or {})
    new_indicators["bounded_domain_gate"] = gate_record
    return replace(
        decision,
        selected_outcome=None,
        selected_action=None,
        selected_side_pre_edge=None,
        selected_outcome_price=None,
        p_selected=None,
        p_opposite=None,
        gross_edge=None,
        net_edge=None,
        edge_breakdown=None,
        approved_size_cc=Decimal("0"),
        no_trade_reason=reason,
        ev_gate_allowed=False,
        indicators=new_indicators,
    )


def _log_bounded_domain_reject(decision: TradeDecision, reason: str) -> None:
    """Emit a settlement-counterfactual record for a bounded-domain veto.

    These downgrades previously produced no counterfactual row, so the TTE
    ceiling and tail-LCB gate had zero outcome feedback.  All values are the
    pre-downgrade selection economics, exactly what would have traded.
    """
    try:
        sel = str(decision.selected_outcome or "").lower()
        breakdown = decision.edge_breakdown or (
            decision.yes_edge_breakdown
            if sel == "yes"
            else decision.no_edge_breakdown
        )
        _ind = decision.indicators or {}
        log_rejected_candidate(
            reason=reason,
            run_id=str(decision.run_id or ""),
            decision_id=str(decision.decision_id or ""),
            asset=str(decision.asset or ""),
            ticker=decision.ticker,
            side=sel or None,
            model_p_selected=(
                float(breakdown.p_selected) if breakdown is not None else None
            ),
            held_price_cents=(
                float(breakdown.executable_entry_price) * 100.0
                if breakdown is not None
                else None
            ),
            gross_edge=(
                float(breakdown.gross_edge) if breakdown is not None else None
            ),
            net_edge=(
                float(breakdown.net_edge) if breakdown is not None else None
            ),
            # Indicator is in cents; the record's edge_threshold is a
            # probability like net_edge (shortfall = (thr - net) * 100).
            edge_threshold=(
                float(_ind[f"{sel}_effective_required_edge_cents"]) / 100.0
                if _ind.get(f"{sel}_effective_required_edge_cents") is not None
                else None
            ),
            tte_seconds=(
                float(decision.seconds_to_expiry)
                if decision.seconds_to_expiry is not None
                else None
            ),
            fee_cents=(
                float(breakdown.entry_fee) * 100.0
                if breakdown is not None
                else None
            ),
            route=_ind.get("order_route") or "unknown",
            depth_for_quantity_cc=(
                float(getattr(decision, f"{sel}_depth_cc", 0) or 0) if sel else None
            ),
            risk_reserve_cents=(
                float(breakdown.model_risk_reserve) * 100.0
                if breakdown is not None
                else None
            ),
            exit_cost_reserve_cents=(
                float(breakdown.exit_cost_reserve) * 100.0
                if breakdown is not None
                else None
            ),
            adverse_selection_reserve_cents=(
                float(breakdown.adverse_selection_reserve) * 100.0
                if breakdown is not None
                else None
            ),
        )
    except Exception:
        pass


def apply_bounded_live_domain_gate(
    decision: TradeDecision,
    *,
    yes_threshold: Optional[EdgeThresholdDecomposition] = None,
    no_threshold: Optional[EdgeThresholdDecomposition] = None,
) -> TradeDecision:
    """Final bounded-domain admission gate for live selections.

    Runs after all selection overlays.  Two independent checks:

      1. TTE ceiling — selections past ``MERID_LIVE_ENTRY_MAX_TTE_S``
         (default 600s, the rollout's bounded live domain) are downgraded.
         The lower bound is intentionally left to the per-band regime TTE
         floors and the settlement-convergence lane.
      2. Tail LCB — at executable prices >= ``MERID_TAIL_LCB_MIN_PRICE_CENTS``
         (default 70c) the selected side's lower confidence bound
         (``net_edge - model_risk_reserve``) must clear the edge threshold it
         was admitted on.  Point-EV passes with sub-threshold LCB in the
         loss-asymmetric tail were the common signature of the 2026-09-30
         losing entries (BTC YES@77, XRP NO@75).

    Downgraded decisions carry a ``bounded_domain_gate`` indicator record;
    evaluated-and-passed tail selections are stamped too, so current-build
    evidence shows the gate ran.
    """
    if decision.selected_outcome is None:
        return decision

    sel = str(decision.selected_outcome)

    tte = float(decision.seconds_to_expiry) if decision.seconds_to_expiry is not None else None
    if tte is not None and tte > MERID_LIVE_ENTRY_MAX_TTE_S:
        record = {
            "gate": "tte_ceiling",
            "seconds_to_expiry": tte,
            "max_tte_s": MERID_LIVE_ENTRY_MAX_TTE_S,
            "would_enter_at_prior": True,
        }
        _reason = (
            f"bounded_domain_tte:{tte:.0f}s>{MERID_LIVE_ENTRY_MAX_TTE_S:.0f}s"
        )
        _log_bounded_domain_reject(decision, _reason)
        return _downgrade_live_selection(decision, _reason, record)

    breakdown = decision.edge_breakdown or (
        decision.yes_edge_breakdown if sel == "yes" else decision.no_edge_breakdown
    )
    if not MERID_TAIL_LCB_GATE_ENABLED or breakdown is None:
        return decision

    price_cents = int(round(float(breakdown.executable_entry_price) * 100.0))
    if price_cents < MERID_TAIL_LCB_MIN_PRICE_CENTS:
        return decision

    thr = yes_threshold if sel == "yes" else no_threshold
    required_cents = float(thr.total) * 100.0 if thr is not None else 0.0
    lcb_cents = (
        float(breakdown.net_edge) - float(breakdown.model_risk_reserve)
    ) * 100.0
    # 2026-10-04 (EPC): when a validated empirical cell supplied the
    # probability, the model-side risk reserve double-charges estimation
    # uncertainty the cell's walk-forward LCB already encodes.  The gate
    # then takes the better of the model LCB and the price-adjusted
    # empirical LCB (fee-net, half-sample-stable) — still bounded by the
    # required edge.
    _ind = decision.indicators or {}
    _epc_lcb_used = None
    if _ind.get(f"{sel}_epc_applied"):
        _epc_lcb = _ind.get(f"{sel}_epc_adj_lcb_cents")
        if _epc_lcb is not None and float(_epc_lcb) > lcb_cents:
            lcb_cents = float(_epc_lcb)
            _epc_lcb_used = float(_epc_lcb)
    record = {
        "gate": "tail_lcb",
        "price_cents": price_cents,
        "lcb_cents": round(lcb_cents, 3),
        "required_cents": round(required_cents, 3),
        "epc_lcb_cents": _epc_lcb_used,
        "epc_cell": _ind.get(f"{sel}_epc_cell"),
        "would_enter_at_prior": True,
    }
    if lcb_cents < required_cents - 1e-9:
        _reason = (
            f"tail_lcb_gate:lcb={lcb_cents:.2f}c"
            f"<required={required_cents:.2f}c@{price_cents}c"
        )
        _log_bounded_domain_reject(decision, _reason)
        return _downgrade_live_selection(decision, _reason, record)

    record["would_enter_at_prior"] = True
    record["passed"] = True
    new_indicators = dict(decision.indicators or {})
    new_indicators["bounded_domain_gate"] = record
    return replace(decision, indicators=new_indicators)


def _log_canary_rejected(
    decision: TradeDecision,
    canary_side: str,
    canary_breakdown: EdgeBreakdown,
    ev_result: Any,
    reason: str,
) -> TradeDecision:
    """Return the decision with a structured canary rejection record."""
    new_indicators = dict(decision.indicators or {})
    new_indicators["cheap_tail_canary"] = {
        "eligible_side": canary_side,
        "eligible_price_cents": int(round(float(canary_breakdown.executable_entry_price) * 100.0)),
        "gross_edge": round(float(canary_breakdown.gross_edge), 4),
        "net_edge": round(float(canary_breakdown.net_edge), 4),
        "ev_gate_allowed": False,
        "ev_gate_result": ev_result.to_dict() if hasattr(ev_result, "to_dict") else ev_result,
        "reason": reason,
    }
    return replace(decision, indicators=new_indicators)


def _downgrade_to_canary_no_trade(decision: TradeDecision, reason: str) -> TradeDecision:
    """Downgrade a selected core decision to no-trade because the canary lane rejected it."""
    new_indicators = dict(decision.indicators or {})
    new_indicators["cheap_tail_canary"] = {
        "eligible_side": decision.selected_outcome,
        "eligible_price_cents": (
            int(round(float(decision.edge_breakdown.executable_entry_price) * 100.0))
            if decision.edge_breakdown else None
        ),
        "gross_edge": (
            round(float(decision.edge_breakdown.gross_edge), 4)
            if decision.edge_breakdown else None
        ),
        "net_edge": (
            round(float(decision.edge_breakdown.net_edge), 4)
            if decision.edge_breakdown else None
        ),
        "ev_gate_allowed": False,
        "reason": reason,
    }
    return replace(
        decision,
        selected_outcome=None,
        selected_action=None,
        selected_outcome_price=None,
        p_selected=None,
        p_opposite=None,
        gross_edge=None,
        net_edge=None,
        edge_breakdown=None,
        approved_size_cc=Decimal("0"),
        no_trade_reason=f"cheap_tail_canary:{reason}",
        ev_gate_allowed=False,
        ev_gate_result=None,
        indicators=new_indicators,
    )


def _canary_breakdown_passes(breakdown: EdgeBreakdown, side: str) -> bool:
    """Check a single side's edge breakdown against canary thresholds."""
    if side not in MERID_CHEAP_TAIL_CANARY_ALLOWED_SIDES:
        return False
    price_cents = int(round(float(breakdown.executable_entry_price) * 100.0))
    if price_cents < MERID_CHEAP_TAIL_CANARY_MIN_PRICE_CENTS:
        return False
    if price_cents > MERID_CHEAP_TAIL_CANARY_MAX_PRICE_CENTS:
        return False
    gross_edge = float(breakdown.gross_edge)
    if gross_edge < (MERID_CHEAP_TAIL_CANARY_MIN_PROB_GAP_PCT / 100.0) - 1e-9:
        return False
    net_edge = float(breakdown.net_edge)
    if net_edge < (MERID_CHEAP_TAIL_CANARY_MIN_NET_EDGE_PCT / 100.0) - 1e-9:
        return False
    return True


def _apply_cheap_tail_canary_lane(
    decision: TradeDecision,
    quote_age_ms: Optional[int],
) -> TradeDecision:
    """Bounded cheap-tail canary overlay for 20-34c held-side contracts.

    This lane is separate from the core 35c+ policy.  It does not lower the
    global held-price floor or the π* premium.  It is the *only* authorized
    entry path for 20-34c held-side contracts.  If the core lane has selected
    a cheap-tail contract that fails the canary thresholds, this overlay
    downgrades it to no-trade.

    Defaults are fail-closed: disabled, YES-only, one contract, ETH-only,
    post-only/maker, strict net edge and probability-gap requirements.
    """
    from merid.risk.executable_cost_ev_gate import (
        evaluate_executable_cost_ev,
        EVInput,
    )
    if not MERID_CHEAP_TAIL_CANARY_ENABLED:
        return decision
    if decision.data_state != "healthy":
        return decision
    if decision.regime_label == "unknown" or float(decision.regime_probability) < float(MIN_REGIME_POSTERIOR):
        return decision
    if not decision.confidence_valid:
        return decision
    if decision.seconds_to_expiry is None:
        return decision
    tte = float(decision.seconds_to_expiry)
    if tte < MERID_CHEAP_TAIL_CANARY_MIN_TTE_S or tte > MERID_CHEAP_TAIL_CANARY_MAX_TTE_S:
        return decision
    if _canary_daily_count(decision.asset) >= MERID_CHEAP_TAIL_CANARY_MAX_DAILY:
        return decision

    # Asset scope guard: the canary is restricted to an explicit allow-list
    # (ETH-only by default) so the experiment is narrow and auditable.
    if decision.asset.upper() not in MERID_CHEAP_TAIL_CANARY_ALLOWED_ASSETS:
        logger.info(
            "[CHEAP-TAIL-CANARY] asset=%s not in allowed canary asset list %s",
            decision.asset, MERID_CHEAP_TAIL_CANARY_ALLOWED_ASSETS,
        )
        # If the core lane selected a non-allowed-asset cheap-tail contract,
        # downgrade it.  Non-cheap-tail core selections are untouched.
        if (
            decision.selected_outcome is not None
            and decision.edge_breakdown is not None
        ):
            price_cents = int(round(float(decision.edge_breakdown.executable_entry_price) * 100.0))
            if MERID_CHEAP_TAIL_CANARY_MIN_PRICE_CENTS <= price_cents <= MERID_CHEAP_TAIL_CANARY_MAX_PRICE_CENTS:
                return _downgrade_to_canary_no_trade(decision, "canary_asset_not_allowed")
        return decision

    # If the core lane has already selected a side, treat the canary as the
    # final authority for the 20-34c band.  A core selection in that band must
    # survive the canary thresholds; otherwise it is downgraded.
    if decision.selected_outcome is not None and decision.edge_breakdown is not None:
        price_cents = int(round(float(decision.edge_breakdown.executable_entry_price) * 100.0))
        if price_cents < MERID_CHEAP_TAIL_CANARY_MIN_PRICE_CENTS:
            return decision
        if price_cents > MERID_CHEAP_TAIL_CANARY_MAX_PRICE_CENTS:
            return decision
        if not _canary_breakdown_passes(decision.edge_breakdown, decision.selected_outcome):
            return _downgrade_to_canary_no_trade(decision, "canary_thresholds_not_met")
        # Core selected a canary-eligible side; keep the same side but force
        # one contract and canary labeling after EV-gate confirmation.
        canary_side = decision.selected_outcome
        canary_breakdown = decision.edge_breakdown
    else:
        # Core rejected; look for a canary-eligible side from the side
        # breakdowns.  We no longer require a tail-calibration artifact to be
        # present; the canary's stricter EV/gap gates and one-contract sizing
        # are the compensating controls when calibration is missing.
        canary_side = None
        canary_breakdown = None
        for side, breakdown in (
            ("yes", decision.yes_edge_breakdown),
            ("no", decision.no_edge_breakdown),
        ):
            if breakdown is None:
                continue
            if not _canary_breakdown_passes(breakdown, side):
                continue
            if canary_breakdown is None or float(breakdown.net_edge) > float(canary_breakdown.net_edge):
                canary_side = side
                canary_breakdown = breakdown

    if canary_side is None or canary_breakdown is None:
        return decision

    # Re-evaluate the executable-cost EV gate with canary-specific thresholds.
    entry_fee = Decimal(str(canary_breakdown.entry_fee))
    exit_cost = Decimal(str(canary_breakdown.exit_cost_reserve))
    uncertainty_reserve = Decimal(str(canary_breakdown.model_risk_reserve))
    adverse_selection_reserve = Decimal(str(decision.adverse_selection_reserve or "0"))

    ev_input = EVInput(
        p_model=Decimal(str(canary_breakdown.p_selected)),
        p_exec=Decimal(str(canary_breakdown.executable_entry_price)),
        qty_cc=100,
        entry_fee_per_contract=entry_fee,
        expected_exit_cost_per_contract=exit_cost,
        adverse_selection_reserve_per_contract=adverse_selection_reserve,
        uncertainty_reserve_per_contract=uncertainty_reserve,
        quote_age_ms=quote_age_ms,
        ticker=decision.ticker,
        decision_id=decision.decision_id,
        min_dollar_ev=Decimal(str(MERID_CHEAP_TAIL_CANARY_MIN_NET_EDGE_PCT / 100.0)),
        min_ev_to_tail_ratio=Decimal(str(MERID_CHEAP_TAIL_CANARY_MIN_EV_TO_TAIL_RATIO)),
    )
    ev_result = evaluate_executable_cost_ev(ev_input)
    if not ev_result.allowed:
        return _log_canary_rejected(decision, canary_side, canary_breakdown, ev_result, "canary_ev_gate_rejected")

    _increment_canary_daily_count(decision.asset)
    logger.info(
        "[CHEAP-TAIL-CANARY-SELECTED] asset=%s ticker=%s side=%s "
        "price_cents=%d p_selected=%.3f gross_edge=%.4f net_edge=%.4f "
        "decision_id=%s daily_count=%d",
        decision.asset,
        decision.ticker,
        canary_side,
        int(round(float(canary_breakdown.executable_entry_price) * 100.0)),
        canary_breakdown.p_selected,
        canary_breakdown.gross_edge,
        canary_breakdown.net_edge,
        decision.decision_id,
        _canary_daily_count(decision.asset),
    )

    new_indicators = dict(decision.indicators or {})
    new_indicators["decision_lane"] = "cheap_tail_canary"
    new_indicators["cheap_tail_canary"] = {
        "eligible_side": canary_side,
        "eligible_price_cents": int(round(float(canary_breakdown.executable_entry_price) * 100.0)),
        "gross_edge": round(float(canary_breakdown.gross_edge), 4),
        "net_edge": round(float(canary_breakdown.net_edge), 4),
        "min_net_edge_pct": MERID_CHEAP_TAIL_CANARY_MIN_NET_EDGE_PCT,
        "min_prob_gap_pct": MERID_CHEAP_TAIL_CANARY_MIN_PROB_GAP_PCT,
        "ev_gate_allowed": True,
        "ev_gate_result": ev_result.to_dict(),
    }

    return replace(
        decision,
        selected_outcome=canary_side,
        selected_action="buy",
        selected_outcome_price=Decimal(str(canary_breakdown.executable_entry_price)),
        p_selected=Decimal(str(canary_breakdown.p_selected)),
        p_opposite=Decimal(str(canary_breakdown.p_opposite)),
        gross_edge=Decimal(str(canary_breakdown.gross_edge)),
        net_edge=Decimal(str(canary_breakdown.net_edge)),
        edge_breakdown=canary_breakdown,
        approved_size_cc=Decimal("100"),
        no_trade_reason=None,
        ev_gate_allowed=True,
        ev_gate_result=ev_result.to_dict(),
        indicators=new_indicators,
    )


def _parse_pi_star_tiers() -> List[Tuple[int, int]]:
    tiers: List[Tuple[int, int]] = []
    for part in MERID_PI_STAR_TIERS_CENTS.split(","):
        if not part:
            continue
        price, premium = part.split(":")
        tiers.append((int(price), int(premium)))
    tiers.sort(key=lambda x: x[0])
    return tiers

def _pi_star_risk_premium(held_price_cents: int) -> int:
    if not MERID_PI_STAR_TIERED:
        return MERID_PI_STAR_FLAT_PREMIUM_CENTS
    tiers = _parse_pi_star_tiers()
    premium = 0
    for price_threshold, tier_premium in tiers:
        if held_price_cents >= price_threshold:
            premium = tier_premium
    return premium


def _dual_tail_shrinkage_weight(raw_probability: float) -> float:
    """Return a continuous provisional-NO calibration weight in [0, 1]."""
    width = max(1e-9, MERID_TAIL_CALIBRATION_NO_DUAL_TRANSITION)
    lower = MERID_TAIL_CALIBRATION_NO_DUAL_RAW_FLOOR - width
    upper = MERID_TAIL_CALIBRATION_NO_DUAL_RAW_FLOOR + width
    if raw_probability <= lower:
        return 1.0
    if raw_probability >= upper:
        return 0.0
    normalized = (upper - raw_probability) / (upper - lower)
    # Smoothstep avoids a slope discontinuity at either transition boundary.
    return normalized * normalized * (3.0 - 2.0 * normalized)

# Allowed data-state and regime-label values.
# `unknown` is a data-quality state; it must never be an economic regime.
ALLOWED_DATA_STATES = frozenset({"warming_up", "healthy", "stale", "degraded", "invalid"})
ALLOWED_REGIME_LABELS = frozenset({
    "unknown",
    "low_vol", "normal", "high_vol", "trend_up", "trend_down", "transition",
    "both_sides", "one_sided_yes", "one_sided_no", "no_liquidity",
})


@dataclass(frozen=True)
class EdgeBreakdown:
    """Explicit, side-aware EV decomposition for a single candidate side.

    Every field is in fractional units (0.0-1.0) so that:

        gross_edge = p_selected - executable_entry_price
        net_edge   = gross_edge - entry_fee - exit_cost_reserve
                     - model_risk_reserve - adverse_selection_reserve

    No hidden constants are permitted.  If a cost cannot be explained, the
    decision must be ``no_trade``.
    """
    p_yes: float
    p_no: float
    selected_side: Literal["yes", "no"]
    p_selected: float
    p_opposite: float
    executable_entry_price: float
    entry_fee: float
    exit_cost_reserve: float
    model_risk_reserve: float
    gross_edge: float
    net_edge: float
    adverse_selection_reserve: float = 0.0


@dataclass(frozen=True)
class EntryCostStack:
    """Single probability-space acceptance hurdle for one executable side."""

    executable_price_prob: float
    venue_fee_prob: float
    spread_slippage_prob: float
    model_uncertainty_prob: float
    required_net_edge_prob: float

    @property
    def pi_star(self) -> float:
        return (
            self.executable_price_prob
            + self.venue_fee_prob
            + self.spread_slippage_prob
            + self.model_uncertainty_prob
            + self.required_net_edge_prob
        )

    def net_edge_before_required(self, p_selected: float) -> float:
        return p_selected - (
            self.executable_price_prob
            + self.venue_fee_prob
            + self.spread_slippage_prob
            + self.model_uncertainty_prob
        )

    def net_edge_after_required(self, p_selected: float) -> float:
        return p_selected - self.pi_star


@dataclass(frozen=True)
class ConfidenceResult:
    """Confidence must carry provenance and a validity flag.

    A confidence value without an uncertainty engine is not a valid trading
    input.  Invalid confidence always blocks entry.  Component penalties are
    the additive uncertainty terms that produced ``value``.
    """
    value: Optional[float]
    valid: bool
    source: str
    reasons: List[str] = field(default_factory=list)
    data_penalty: float = 0.0
    book_penalty: float = 0.0
    model_penalty: float = 0.0
    regime_penalty: float = 0.0


@dataclass(frozen=True)
class TradeDecision:
    """Immutable per-asset trade decision produced by the hybrid engine.

    Required fields
    ---------------
    If any required field is missing, non-finite, or logically inconsistent,
    the decision is ``no_trade`` and downstream must not emit an order.
    """
    run_id: str
    decision_id: str
    ticker: str
    asset: str
    timestamp_utc: datetime

    # Probability (raw -> calibrated) with explicit side semantics
    p_yes_raw: Decimal
    p_yes_calibrated: Decimal
    p_yes_uncertainty: Decimal
    p_no_calibrated: Decimal
    p_selected: Optional[Decimal] = None
    p_opposite: Optional[Decimal] = None

    # Evidence
    indicators: Dict[str, Any] = field(default_factory=dict)
    regime: str = "unknown"
    data_quality: str = "unknown"
    data_state: str = "unknown"
    regime_label: str = "unknown"
    regime_probability: Decimal = Decimal("0")
    regime_warmup_samples: int = 0
    seconds_to_expiry: Decimal = Decimal("0")
    settlement_reference: str = "unknown"

    # Executable economics (depth-weighted)
    yes_entry_vwap: Decimal = Decimal("0")
    no_entry_vwap: Decimal = Decimal("0")
    yes_depth_cc: Decimal = Decimal("0")
    no_depth_cc: Decimal = Decimal("0")
    fee_yes: Decimal = Decimal("0")
    fee_no: Decimal = Decimal("0")
    expected_exit_cost_yes: Decimal = Decimal("0")
    expected_exit_cost_no: Decimal = Decimal("0")

    # Upstream signal / vote provenance
    yes_score: Optional[Decimal] = None
    no_score: Optional[Decimal] = None
    yes_vote_count: int = 0
    no_vote_count: int = 0
    selected_side_pre_edge: Optional[Literal["yes", "no"]] = None
    selection_reason: str = "unknown"

    # Per-side edge / cost / reserve decomposition
    gross_edge_yes: Optional[Decimal] = None
    gross_edge_no: Optional[Decimal] = None
    net_edge_yes: Decimal = Decimal("0")
    net_edge_no: Decimal = Decimal("0")
    yes_net_edge: Decimal = Decimal("0")
    no_net_edge: Decimal = Decimal("0")
    best_side: Optional[Literal["yes", "no"]] = None
    best_net_edge: Optional[Decimal] = None
    edge_threshold: Decimal = Decimal("0")
    entry_fee_yes: Decimal = Decimal("0")
    entry_fee_no: Decimal = Decimal("0")
    exit_cost_reserve_yes: Decimal = Decimal("0")
    exit_cost_reserve_no: Decimal = Decimal("0")
    model_risk_reserve_yes: Decimal = Decimal("0")
    model_risk_reserve_no: Decimal = Decimal("0")
    selected_outcome: Optional[Literal["yes", "no"]] = None
    selected_action: Optional[Literal["buy"]] = None
    selected_outcome_price: Optional[Decimal] = None
    gross_edge: Optional[Decimal] = None
    net_edge: Optional[Decimal] = None
    no_trade_reason: Optional[str] = None

    # Explicit edge and confidence provenance
    edge_breakdown: Optional[EdgeBreakdown] = None
    yes_edge_breakdown: Optional[EdgeBreakdown] = None
    no_edge_breakdown: Optional[EdgeBreakdown] = None
    confidence: Optional[Decimal] = None
    confidence_valid: bool = False
    confidence_source: str = "missing"
    confidence_reasons: List[str] = field(default_factory=list)
    confidence_data_penalty: Optional[Decimal] = None
    confidence_book_penalty: Optional[Decimal] = None
    confidence_model_penalty: Optional[Decimal] = None
    confidence_regime_penalty: Optional[Decimal] = None
    model_risk_reserve: Decimal = Decimal("0")
    min_required_edge: Decimal = Decimal("0")
    approved_size_cc: Decimal = Decimal("0")
    policy_version: str = "trade_decision_v2"

    # 2026-08-29: Executable-cost EV gate state.
    # The EV gate is the final entry authority; these fields carry its economics
    # and its allow/reject outcome for audit and ledger provenance.
    adverse_selection_reserve: Decimal = Decimal("0")
    uncertainty_reserve: Decimal = Decimal("0")
    ev_gate_allowed: bool = False
    ev_gate_result: Optional[Dict[str, Any]] = None

    # 2026-08-29: Hash of the resolved live config that authorized this decision.
    config_hash: Optional[str] = None
    build_sha: Optional[str] = None

    @property
    def side(self) -> Optional[Literal["yes", "no"]]:
        """Alias for the selected (consumed) side used by downstream paths."""
        return self.selected_outcome

    @property
    def evaluated_side(self) -> Optional[Literal["yes", "no"]]:
        """Alias for the dual-side evaluator's unconstrained best side."""
        return self.best_side

    def __post_init__(self) -> None:
        if not (Decimal("0") <= self.p_yes_raw <= Decimal("1")):
            raise ValueError(f"p_yes_raw out of [0,1]: {self.p_yes_raw}")
        if not (Decimal("0") <= self.p_yes_calibrated <= Decimal("1")):
            raise ValueError(f"p_yes_calibrated out of [0,1]: {self.p_yes_calibrated}")
        if not (Decimal("0") <= self.p_yes_uncertainty <= Decimal("1")):
            raise ValueError(f"p_yes_uncertainty out of [0,1]: {self.p_yes_uncertainty}")
        if not (Decimal("0") <= self.p_no_calibrated <= Decimal("1")):
            raise ValueError(f"p_no_calibrated out of [0,1]: {self.p_no_calibrated}")
        if self.selected_outcome is not None and self.selected_action is None:
            raise ValueError("selected_action required when selected_outcome is set")
        if self.selected_outcome is None and self.selected_action is not None:
            raise ValueError("selected_outcome required when selected_action is set")
        if self.selected_outcome is not None and self.no_trade_reason is not None:
            raise ValueError("no_trade_reason must be None when a side is selected")

        # Data-state and regime are data-quality gates; they cannot co-exist with a trade.
        if self.data_state not in ALLOWED_DATA_STATES:
            raise ValueError(f"data_state not in {ALLOWED_DATA_STATES}: {self.data_state}")
        if self.data_state != "healthy" and self.selected_outcome is not None:
            raise ValueError(f"data_state={self.data_state} cannot produce selected_outcome")
        if self.regime_label not in ALLOWED_REGIME_LABELS:
            raise ValueError(f"regime_label not in {ALLOWED_REGIME_LABELS}: {self.regime_label}")
        if self.regime_label == "unknown" and self.selected_outcome is not None:
            raise ValueError("regime_label=unknown cannot produce selected_outcome")

        # Score finiteness
        for score in (self.yes_score, self.no_score):
            if score is not None and not score.is_finite():
                raise ValueError(f"non-finite score: {score}")
        for edge in (self.yes_net_edge, self.no_net_edge, self.best_net_edge or Decimal("0"), self.net_edge or Decimal("0")):
            if edge is not None and not edge.is_finite():
                raise ValueError(f"non-finite edge: {edge}")


def _normal_cdf(x: float) -> float:
    """Standard normal CDF using erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _data_quality_to_data_state(data_quality: str) -> str:
    """Map legacy data_quality string to data_state."""
    dq = (data_quality or "unknown").strip().lower()
    if dq in ("good", "live", "healthy"):
        return "healthy"
    if dq in ("stale", "degraded"):
        return dq
    if dq == "bad":
        return "degraded"
    return "invalid"


def _regime_to_regime_label(regime: str) -> str:
    """Coerce a raw regime string to an allowed regime_label."""
    rl = (regime or "unknown").strip().lower()
    if rl in ALLOWED_REGIME_LABELS:
        return rl
    if rl == "insufficient_data":
        return "no_liquidity"
    if rl in ("calm", "elevated", "violent"):
        return rl  # volatility regime labels are intentionally allowed
    return "unknown"


def _resolve_data_state(
    *,
    data_state: Optional[str],
    data_quality: str,
) -> str:
    if data_state is not None:
        return data_state
    return _data_quality_to_data_state(data_quality)


def _resolve_regime_label(
    *,
    regime_label: Optional[str],
    regime: str,
) -> str:
    if regime_label is not None:
        return regime_label
    return _regime_to_regime_label(regime)


def _resolve_regime_probability(
    *,
    regime_probability: Optional[float],
    regime_label: str,
) -> Decimal:
    if regime_probability is not None:
        return Decimal(str(regime_probability))
    if regime_label == "unknown":
        return Decimal("0")
    return Decimal("1")


def compute_edge(
    p_yes: float,
    selected_side: Literal["yes", "no"],
    entry_price: float,
    entry_fee: float,
    exit_cost_reserve: float,
    model_risk_reserve: float,
    adverse_selection_reserve: float = 0.0,
) -> EdgeBreakdown:
    """Compute a fully explained net edge for one side.

    ``p_yes`` is the model probability of YES.  The selected side's probability
    is derived from it so that ``p_yes + p_no == 1`` is invariant.

    ``adverse_selection_reserve`` is an explicit haircut for resting (maker)
    fills: a queue-priced order executes preferentially when the market moves
    through its price, so the conditional fill is worth less than the quoted
    edge.  Zero by default — only the maker-bid lane carries it.
    """
    if not (0.0 <= p_yes <= 1.0):
        raise ValueError(f"p_yes must be in [0,1]: {p_yes}")
    if selected_side not in ("yes", "no"):
        raise ValueError(f"selected_side must be 'yes' or 'no': {selected_side}")
    if not (0.0 <= entry_price <= 1.0):
        raise ValueError(f"entry_price must be in [0,1]: {entry_price}")

    p_no = 1.0 - p_yes
    p_selected = p_yes if selected_side == "yes" else p_no
    p_opposite = p_no if selected_side == "yes" else p_yes
    gross_edge = p_selected - entry_price
    net_edge = (
        gross_edge
        - entry_fee
        - exit_cost_reserve
        - model_risk_reserve
        - adverse_selection_reserve
    )

    return EdgeBreakdown(
        p_yes=p_yes,
        p_no=p_no,
        selected_side=selected_side,
        p_selected=p_selected,
        p_opposite=p_opposite,
        executable_entry_price=entry_price,
        entry_fee=entry_fee,
        exit_cost_reserve=exit_cost_reserve,
        model_risk_reserve=model_risk_reserve,
        gross_edge=gross_edge,
        net_edge=net_edge,
        adverse_selection_reserve=adverse_selection_reserve,
    )


def entry_cost_stack_from_breakdown(
    breakdown: EdgeBreakdown,
    required_net_edge: float,
) -> EntryCostStack:
    """Translate an edge breakdown into the canonical probability hurdle."""
    return EntryCostStack(
        executable_price_prob=breakdown.executable_entry_price,
        venue_fee_prob=breakdown.entry_fee,
        spread_slippage_prob=breakdown.exit_cost_reserve,
        model_uncertainty_prob=breakdown.model_risk_reserve,
        required_net_edge_prob=required_net_edge,
    )


def _expected_exit_cost(
    entry_price_frac: float,
    fee_frac: float,
    settlement_lane: bool,
) -> Tuple[float, str, float]:
    """Policy-aware expected liquidation cost — see MERID_EXPECTED_EXIT_*.

    Returns ``(expected_cost, exit_policy_class, trigger_prob)`` in
    probability-fraction units.  ``hold_to_settlement`` (settlement lane or
    exits disabled) reserves nothing; ``legacy_full_taker_reserve`` is the
    pre-2026-10-05 unconditional fee; ``expected_ev_gated`` charges
    ``p_trigger * fee`` where p_trigger is higher for tail-priced entries
    that can realistically print the hard-profit-lock bid in-window.
    """
    if settlement_lane or MERID_DISABLE_EXIT_POLICY:
        return 0.0, "hold_to_settlement", 0.0
    if not MERID_EXPECTED_EXIT_COST:
        return float(fee_frac), "legacy_full_taker_reserve", 1.0
    tail = float(entry_price_frac) * 100.0 >= MERID_EXPECTED_EXIT_LOCK_PROXIMITY_CENTS
    p = MERID_EXPECTED_EXIT_PROB_TAIL if tail else MERID_EXPECTED_EXIT_PROB
    p = min(1.0, max(0.0, float(p)))
    return float(fee_frac) * p, "expected_ev_gated", p


def _compute_model_risk_reserve(
    model_uncertainty: float,
    data_quality: str,
    regime: str,
    seconds_to_expiry: float,
    settlement_lane: bool = False,
) -> float:
    """Observable uncertainty reserve used in the edge calculation."""
    reserve = max(0.0, min(1.0, model_uncertainty))
    if data_quality in ("stale", "bad", "unknown"):
        reserve = min(1.0, reserve + 0.15)
    # The flat +0.20 near-expiry bump prices the contract as if the terminal
    # tick settles it.  In the settlement-convergence lane the distribution's
    # own std already encodes the unrealized fraction, so the bump would
    # double-count the same uncertainty.
    if seconds_to_expiry < 60.0 and not settlement_lane:
        reserve = min(1.0, reserve + 0.20)
    if regime in ("unknown", "insufficient_data"):
        reserve = min(1.0, reserve + 0.05)
    return reserve


def _compute_confidence(
    data_quality: str,
    regime: str,
    settlement_reference: str,
    seconds_to_expiry: float,
    yes_bid_cents: float,
    yes_ask_cents: float,
    no_bid_cents: float,
    no_ask_cents: float,
    yes_depth_cc: float,
    no_depth_cc: float,
    model_uncertainty: float,
    *,
    rti_age_ms: Optional[int] = None,
    quote_age_ms: Optional[int] = None,
    rti_book_skew_ms: Optional[int] = None,
    book_sequence_confirmed: Optional[bool] = None,
    book_initialized: Optional[bool] = None,
    cfb_execution_eligible: Optional[bool] = None,
    rti_execution_max_age_ms: int = 2000,
    book_execution_max_age_ms: int = 1000,
    rti_book_skew_max_ms: int = 1500,
    settlement_lane: bool = False,
    entry_price_basis: str = "ask",
) -> ConfidenceResult:
    """Derive confidence from observable uncertainty sources.

    Confidence is not a magic number.  It is produced only when every trust
    input is present and within bounds.  Missing or degraded inputs produce
    ``valid=False`` and block entry.

    2026-10-02: ``entry_price_basis="bid"`` demotes the >5c-spread hard
    blocks to non-blocking.  A resting post-only order captures the spread
    instead of paying it; its fill-time pickoff cost is charged explicitly
    through the adverse-selection reserve in net edge and the EV gate.
    """
    reasons: List[str] = []

    if data_quality in ("stale", "bad", "unknown"):
        reasons.append(f"data_quality={data_quality}")
    if regime in ("unknown", "insufficient_data"):
        reasons.append(f"regime={regime}")
    if settlement_reference != "cfb_rti_live":
        reasons.append(f"settlement_reference={settlement_reference}")
    # ``near_expiry`` treats the contract as a terminal-tick bet; in the
    # settlement-convergence lane the probability claim comes from banked
    # settlement samples, so proximity to expiry is the feature, not a risk.
    if seconds_to_expiry < 60.0 and not settlement_lane:
        reasons.append("near_expiry")

    # 2026-09-08: P0 freshness/skew/sequence gates become confidence blockers.
    if cfb_execution_eligible is False:
        reasons.append("rti_not_execution_eligible")
    if rti_age_ms is not None and rti_age_ms > rti_execution_max_age_ms:
        reasons.append(f"rti_stale:{rti_age_ms}ms")
    if quote_age_ms is not None and quote_age_ms > book_execution_max_age_ms:
        reasons.append(f"orderbook_stale:{quote_age_ms}ms")
    if rti_age_ms is not None and quote_age_ms is not None:
        skew = abs(rti_age_ms - quote_age_ms)
        if skew > rti_book_skew_max_ms:
            reasons.append(f"rti_book_skew:{skew}ms")
    if book_initialized is False:
        reasons.append("orderbook_not_initialized")
    if book_sequence_confirmed is False:
        reasons.append("orderbook_sequence_gap")

    # Spread and depth checks: a wide spread or thin book reduces confidence.
    # Under the maker (bid) basis a wide own-side spread is the opportunity
    # being captured, not a cost — only a taker entry crosses it.
    yes_spread = yes_ask_cents - yes_bid_cents
    no_spread = no_ask_cents - no_bid_cents
    if entry_price_basis != "bid":
        if yes_bid_cents > 0 and yes_ask_cents > 0 and yes_spread > 5.0:
            reasons.append(f"yes_spread={yes_spread:.1f}c")
        if no_bid_cents > 0 and no_ask_cents > 0 and no_spread > 5.0:
            reasons.append(f"no_spread={no_spread:.1f}c")
    if yes_depth_cc < 100.0 and no_depth_cc < 100.0:
        reasons.append(
            f"no_executable_depth:yes={yes_depth_cc:.0f},no={no_depth_cc:.0f}"
        )

    if reasons:
        return ConfidenceResult(
            value=None,
            valid=False,
            source="uncertainty_engine",
            reasons=reasons,
        )

    yes_spread = max(0.0, yes_ask_cents - yes_bid_cents)
    no_spread = max(0.0, no_ask_cents - no_bid_cents)
    avg_spread = (yes_spread + no_spread) / 2.0
    spread_penalty = min(0.08, avg_spread / 50.0)

    min_depth = max(1.0, min(yes_depth_cc, no_depth_cc, 1.0))
    depth_penalty = max(0.0, 0.05 - (min_depth / 5000.0))

    time_penalty = 0.05 if (seconds_to_expiry < 120.0 and not settlement_lane) else 0.0

    # Decompose uncertainty into four explicit additive terms.
    # Data: data-quality + near-expiry time penalty.
    data_penalty = 0.0
    if data_quality in ("stale", "bad", "unknown"):
        data_penalty += 0.15
    if seconds_to_expiry < 60.0:
        data_penalty += 0.20
    data_penalty += time_penalty
    data_penalty = min(1.0, data_penalty)

    # Book: spread + depth.
    book_penalty = min(1.0, spread_penalty + depth_penalty)

    # Model: base model uncertainty.
    model_penalty = max(0.0, min(1.0, model_uncertainty))

    # Regime: unclassified or insufficient-data.
    regime_penalty = 0.05 if regime in ("unknown", "insufficient_data") else 0.0

    total_uncertainty = min(0.99, data_penalty + book_penalty + model_penalty + regime_penalty)
    value = max(0.0, min(1.0, 1.0 - total_uncertainty))
    return ConfidenceResult(
        value=value,
        valid=True,
        source="uncertainty_engine",
        data_penalty=data_penalty,
        book_penalty=book_penalty,
        model_penalty=model_penalty,
        regime_penalty=regime_penalty,
    )


# mtime-cached view of data/live_entry_evidence.json, rebuilt on each
# settlement by the decision audit ledger.  See MERID_LIVE_EVIDENCE_GATE.
_live_evidence_cache: Dict[str, Any] = {"mtime": None, "data": None}


def _load_live_evidence() -> Optional[Dict[str, Any]]:
    """Load the rolling entry-evidence artifact, re-reading only on mtime change.

    Hermetic-test guard: under pytest the machine-local default artifact is
    ignored so a stale local file can never change unrelated test outcomes;
    tests opt in by setting MERID_LIVE_EVIDENCE_PATH explicitly.
    """
    if "MERID_LIVE_EVIDENCE_PATH" not in os.environ and (
        "PYTEST_CURRENT_TEST" in os.environ
        or os.environ.get("MERID_ENV", "").strip().lower() in ("test", "ci")
    ):
        return None
    path = os.environ.get("MERID_LIVE_EVIDENCE_PATH", "data/live_entry_evidence.json")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if _live_evidence_cache["mtime"] == mtime and _live_evidence_cache["data"] is not None:
        return _live_evidence_cache["data"]
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return None
    _live_evidence_cache["mtime"] = mtime
    _live_evidence_cache["data"] = data
    return data


def _clear_live_evidence_cache() -> None:
    _live_evidence_cache["mtime"] = None
    _live_evidence_cache["data"] = None


def _wilson_lower_bound(wr: float, n: int, z: float) -> float:
    """One-sided Wilson score lower bound for a binomial proportion.

    A raw win rate ``k/n`` is a point estimate; on sparse cohorts it materially
    overstates confidence.  The Wilson LCB is the conservative statistic the
    evidence gate compares against the cost floor: a cohort is only trusted to
    cover its cost basis when the *lower* credible bound on its true win rate
    still clears it.
    """
    if n <= 0:
        return 0.0
    phat = max(0.0, min(1.0, wr))
    z2 = z * z
    denom = 1.0 + z2 / n
    center = phat + z2 / (2.0 * n)
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * n)) / n)
    return max(0.0, (center - margin) / denom)


MERID_LIVE_EVIDENCE_Z = float(
    os.environ.get("MERID_LIVE_EVIDENCE_Z", "1.645")  # one-sided ~95%
)


def _live_evidence_allows(
    evidence: Dict[str, Any],
    asset: str,
    side: str,
    entry_price_cents: int,
    fee_frac: float,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Return (allowed, detail).  Fails closed only on positive live evidence:

    - asset level: trailing settled WR for this asset+side no longer covers
      mean entry price + fee + margin (regime break across the whole cohort);
    - cell level: trailing WR in this 10c held-price bucket no longer covers
      entry price + fee + margin.

    The comparison uses the Wilson score lower bound of the win rate, not the
    point estimate, so a cohort must clear its cost floor *conservatively*.
    Missing/under-sampled cohorts defer to the caller (static floor still applies).
    """
    rec = ((evidence.get("assets") or {}).get(str(asset).upper()) or {}).get(side)
    if not isinstance(rec, dict):
        return True, None
    n = int(rec.get("n") or 0)
    if n >= MERID_LIVE_EVIDENCE_MIN_ASSET_SAMPLES:
        wr = float(rec.get("wr") or 0.0)
        wr_lcb = _wilson_lower_bound(wr, n, MERID_LIVE_EVIDENCE_Z)
        avg_entry_cents = float(rec.get("avg_entry_cents") or 0.0)
        floor = avg_entry_cents / 100.0 + fee_frac + MERID_LIVE_EVIDENCE_MARGIN
        if wr_lcb < floor:
            return False, {
                "level": "asset",
                "n": n,
                "wr": wr,
                "wr_lcb": wr_lcb,
                "avg_entry_cents": avg_entry_cents,
                "floor": floor,
            }
    bucket = str(min(int(entry_price_cents) // 10 * 10, 90))
    b = (rec.get("buckets") or {}).get(bucket)
    if isinstance(b, dict) and int(b.get("n") or 0) >= MERID_LIVE_EVIDENCE_MIN_CELL_SAMPLES:
        n_cell = int(b["n"])
        wr = float(b.get("wr") or 0.0)
        wr_lcb = _wilson_lower_bound(wr, n_cell, MERID_LIVE_EVIDENCE_Z)
        floor = entry_price_cents / 100.0 + fee_frac + MERID_LIVE_EVIDENCE_MARGIN
        if wr_lcb < floor:
            return False, {
                "level": "cell",
                "bucket": bucket,
                "n": n_cell,
                "wr": wr,
                "wr_lcb": wr_lcb,
                "floor": floor,
            }
    return True, None


def _provisional_evidence_probe(
    _d: Optional["EdgeThresholdDecomposition"],
    side: str,
    net_ev_cents: Optional[float],
    evidence_code: Optional[str],
    matching_hard_block: bool,
    indicators: Dict[str, Any],
) -> bool:
    """Demote a legacy evidence verdict to a live-monitoring label when the
    current-build provisional lane owns this region.

    A verdict produced by a *pre-change* build (any cell-aware code, the v1
    rolling win-rate block, or ``matching_hard_block``) is never by itself an
    execution veto for a current-build candidate inside the bounded
    provisional domain: it becomes ``legacy_risk_label`` + monitoring
    metadata, and the candidate proceeds when its current net EV clears the
    cell's provisional threshold and the lane has capacity.  Current-build
    operational hard blocks (stale book, negative EV, post-only construction,
    tail/timing) are enforced elsewhere and are untouched here.

    Returns True when the side's admission is rescued by this lane.
    """
    if _d is None or _d.provisional_cell_id is None:
        return False
    ok, _reason = _cbp.provisional_admission_allowed(
        cell_id=_d.provisional_cell_id,
        evidence_code=evidence_code,
        matching_hard_block=matching_hard_block,
        net_ev_cents=net_ev_cents,
        effective_required_edge_cents=_d.total * 100.0,
    )
    if not ok:
        return False
    _cbp.bump_provisional_funnel(
        "legacy_evidence_labelled", _d.provisional_cell_id
    )
    indicators[f"{side}_admission_owner"] = "current_build_provisional"
    indicators[f"{side}_admission_decision"] = "allowed"
    indicators[f"{side}_admission_reason"] = "cbp_legacy_evidence_labelled"
    indicators[f"{side}_legacy_risk_label"] = str(evidence_code or "legacy")
    indicators[f"{side}_legacy_risk_hard_block"] = bool(matching_hard_block)
    return True


def _select_best_side(
    yes_breakdown: EdgeBreakdown,
    no_breakdown: EdgeBreakdown,
    tie_epsilon: float = 1e-9,
) -> Tuple[Optional[Literal["yes", "no"]], float, str]:
    """Return (best_side, best_net_edge, selection_reason).

    Ties are explicit no-trade events to avoid hidden directional bias.
    """
    yes_edge = yes_breakdown.net_edge
    no_edge = no_breakdown.net_edge
    if abs(yes_edge - no_edge) <= tie_epsilon:
        return None, (yes_edge + no_edge) / 2.0, "directional_tie"
    if yes_edge > no_edge:
        return "yes", yes_edge, "best_executable_edge_yes"
    return "no", no_edge, "best_executable_edge_no"


def compute_trade_decision(
    *,
    run_id: str,
    decision_id: str,
    ticker: str,
    asset: str,
    spot_price: float,
    strike_price: float,
    seconds_to_expiry: float,
    yes_bid_cents: float,
    yes_ask_cents: float,
    no_bid_cents: float,
    no_ask_cents: float,
    yes_depth_cc: float = 0.0,
    no_depth_cc: float = 0.0,
    fee_per_contract_cents: float = 0.0,
    annualized_vol: float = 0.60,
    model_uncertainty: float = 0.05,
    data_quality: str = "unknown",
    data_state: Optional[str] = None,
    regime: str = "unknown",
    regime_label: Optional[str] = None,
    regime_probability: Optional[float] = None,
    regime_warmup_samples: int = 0,
    yes_score: Optional[float] = None,
    no_score: Optional[float] = None,
    p_yes_model: Optional[float] = None,
    p_no_model: Optional[float] = None,
    settlement_distribution: Optional[SettlementDistribution] = None,
    yes_vote_count: int = 0,
    no_vote_count: int = 0,
    selected_side_pre_edge: Optional[Literal["yes", "no"]] = None,
    selection_reason: str = "best_executable_edge",
    indicators: Optional[Dict[str, Any]] = None,
    min_required_edge: float = TRADE_DECISION_MIN_REQUIRED_EDGE,
    settlement_reference: str = "unknown",
    policy_version: str = "trade_decision_v2",
    quote_age_ms: Optional[int] = None,
    rti_age_ms: Optional[int] = None,
    rti_book_skew_ms: Optional[int] = None,
    book_sequence_confirmed: Optional[bool] = None,
    book_initialized: Optional[bool] = None,
    cfb_execution_eligible: Optional[bool] = None,
    build_sha: Optional[str] = None,
    directional_regime: Optional[Any] = None,
    feature_snapshot: Optional[Any] = None,
    entry_price_basis: str = "ask",
    adverse_selection_reserve: float = 0.0,
    route: str = "taker",
) -> TradeDecision:
    """Compute a calibrated, cost-aware trade decision for a 15m binary market.

    The default raw probability uses a log-moneyness Bachelier baseline.  When a
    ``settlement_distribution`` is supplied, it is treated as the authoritative
    distribution of the final 60-second CF RTI settlement average and is used
    directly for p_yes_raw.  Drift is shrunk to zero because 15-minute drift
    estimates are unreliable.

    A trade is emitted only when:
      1. The data_state is healthy.
      2. The regime_label is known and its posterior is high enough.
      3. The selected side's calibrated probability is > its all-in cost basis
         (entry price + fee + exit reserve + model-risk reserve).
      4. Its net edge exceeds ``min_required_edge``.
      5. Confidence is valid (produced by the uncertainty engine, not a default).
    """
    now = datetime.fromtimestamp(replay_time(), tz=timezone.utc)
    _data_state = _resolve_data_state(data_state=data_state, data_quality=data_quality)
    _regime_label = _resolve_regime_label(regime_label=regime_label, regime=regime)
    _regime_probability = _resolve_regime_probability(
        regime_probability=regime_probability, regime_label=_regime_label
    )

    # Layer-0: Resolve live config overrides.  When a resolved live config is
    # active, use its stricter safety floors for edge, p_selected, and the
    # held-side price floor.  Attach its hash to the decision for audit.
    _resolved = _get_resolved_live_config()
    _config_hash = _get_resolved_config_hash() if _resolved is not None else None
    _build_sha = getattr(_resolved, "build_sha", None) if _resolved is not None else None
    if _resolved is not None:
        min_required_edge = _get_resolved_min_required_edge(min_required_edge)
    min_p_selected = _get_resolved_min_p_selected(TRADE_DECISION_MIN_P_SELECTED)
    min_held_price_cents = _get_resolved_min_held_price_cents(MERID_MIN_HELD_PRICE_CENTS)

    # Initialize mutable indicators dict for provenance/telemetry.  Vol and
    # z-score are attached below after the quote and vol resolution.
    indicators = dict(indicators) if indicators else {}
    indicators.setdefault("annualized_vol_requested", float(annualized_vol))
    # Executable quotes are stamped up-front so every downstream no-trade
    # (including Layer-1/2 gates) carries the prices that were evaluated.
    # Under the bid basis the evaluated entry is the own-side bid.
    if entry_price_basis == "bid":
        _yes_entry_c = yes_bid_cents if yes_bid_cents > 0 else 100.0
        _no_entry_c = no_bid_cents if no_bid_cents > 0 else 100.0
    else:
        _yes_entry_c = yes_ask_cents if yes_ask_cents > 0 else (100.0 - no_bid_cents)
        _no_entry_c = no_ask_cents if no_ask_cents > 0 else (100.0 - yes_bid_cents)
    indicators.update({
        "yes_bid_cents": yes_bid_cents,
        "yes_ask_cents": yes_ask_cents,
        "no_bid_cents": no_bid_cents,
        "no_ask_cents": no_ask_cents,
        "yes_entry_price_cents": int(round(_yes_entry_c)),
        "no_entry_price_cents": int(round(_no_entry_c)),
    })

    def _no_trade(reason: str) -> TradeDecision:
        decision = TradeDecision(
            run_id=run_id,
            decision_id=decision_id,
            ticker=ticker,
            asset=asset,
            timestamp_utc=now,
            p_yes_raw=Decimal("0.5"),
            p_yes_calibrated=Decimal("0.5"),
            p_yes_uncertainty=Decimal("1.0"),
            p_no_calibrated=Decimal("0.5"),
            data_state=_data_state,
            regime_label=_regime_label,
            regime_probability=_regime_probability,
            regime_warmup_samples=regime_warmup_samples,
            data_quality=data_quality,
            regime=regime,
            no_trade_reason=reason,
            confidence_valid=False,
            confidence_source="pre_trade_gate",
            confidence_reasons=[reason],
            settlement_reference=settlement_reference,
            min_required_edge=Decimal(str(min_required_edge)),
            yes_score=Decimal(str(yes_score)) if yes_score is not None else None,
            no_score=Decimal(str(no_score)) if no_score is not None else None,
            yes_vote_count=yes_vote_count,
            no_vote_count=no_vote_count,
            selected_side_pre_edge=selected_side_pre_edge,
            selection_reason=selection_reason,
            policy_version=policy_version,
            config_hash=_config_hash,
            build_sha=_build_sha,
            indicators=dict(indicators),
        )
        record_state_checksum(decision_id, asdict(decision), kind="trade_decision")
        return decision

    # Layer-1: market / time gates.
    # Missing, non-finite, or non-positive TTE is a fail-closed no-trade for
    # new entries.  Exits are routed through the execution firewall which has
    # its own reduce-only fallback for stale snapshots.
    if seconds_to_expiry is None or not math.isfinite(seconds_to_expiry) or seconds_to_expiry <= 0:
        return _no_trade("expired_or_no_time")

    # 2026-09-23: settlement-convergence lane eligibility.  Inside the final
    # settlement minute, a settlement-aware distribution with enough banked
    # samples and a high-confidence side may bypass the generic TTE cutoffs:
    # the contract's outcome is largely realized arithmetic at that point, not
    # a live price guess.  The lane still fails closed when the distribution
    # is absent, has too few banked samples, is not clearly resolved, or the
    # remaining time is below the lane's own execution floor.
    settlement_lane = False
    if (
        MERID_SETTLEMENT_LANE_ENABLED
        and settlement_distribution is not None
        and float(seconds_to_expiry) >= MERID_SETTLEMENT_LANE_MIN_TTE_S
        and getattr(settlement_distribution, "phase", None) == "in_window"
        and int(getattr(settlement_distribution, "observed_count", 0) or 0) >= MERID_SETTLEMENT_LANE_MIN_OBSERVED
    ):
        _sd_p = getattr(settlement_distribution, "p_yes_raw", None)
        if _sd_p is not None and math.isfinite(_sd_p):
            _sd_p_side = max(float(_sd_p), 1.0 - float(_sd_p))
            if _sd_p_side >= MERID_SETTLEMENT_LANE_MIN_P:
                settlement_lane = True
                indicators["entry_lane"] = "settlement_convergence"
                indicators["settlement_lane_p_side"] = _sd_p_side
                indicators["settlement_lane_observed"] = int(settlement_distribution.observed_count)
                indicators["settlement_lane_filled"] = int(getattr(settlement_distribution, "filled_count", 0) or 0)

    # EXIT_ONLY window: no new entries inside the pre-close cutoff.
    # Exits (take-profit, stop, manual close) remain enabled.
    exit_only_cutoff = float(
        os.environ.get(
            "MERID_EXIT_ONLY_CUTOFF_S",
            os.environ.get("MERID_FINAL_MINUTE_CUTOFF_S", "30"),
        )
    )
    if seconds_to_expiry <= exit_only_cutoff and not settlement_lane:
        return _no_trade("final_minute_entry_disabled")

    # 2026-09-23: minimum time-to-expiry for new entries.  Post-restart audit
    # showed entries landing in the final 2-7 minutes were the most adversely
    # selected cohort (momentum dominates and the market is most efficient
    # there); MERID_ENTRY_MIN_SECONDS_TO_EXPIRY (default 180s) keeps entries
    # out of that tail.  Exits are unaffected.  The settlement-convergence
    # lane is exempt because its probability claim rests on banked settlement
    # samples rather than on a live-price forecast.
    if seconds_to_expiry <= MERID_ENTRY_MIN_SECONDS_TO_EXPIRY and not settlement_lane:
        return _no_trade("min_tte_entry_disabled")

    # Layer-2: data and regime gates.
    if _data_state != "healthy":
        return _no_trade("data_state_not_healthy")
    if _regime_label == "unknown":
        return _no_trade("regime_unclassified")
    if _regime_probability < MIN_REGIME_POSTERIOR:
        return _no_trade("regime_uncertain")

    # Layer-3: score finiteness assertions (fail-closed).
    if yes_score is not None and not math.isfinite(yes_score):
        return _no_trade("non_finite_yes_score")
    if no_score is not None and not math.isfinite(no_score):
        return _no_trade("non_finite_no_score")
    if p_yes_model is not None and not math.isfinite(p_yes_model):
        return _no_trade("non_finite_p_yes_model")
    if p_no_model is not None and not math.isfinite(p_no_model):
        return _no_trade("non_finite_p_no_model")

    # Kalshi duality: YES ask = 100 - NO bid; NO ask = 100 - YES bid.
    # Prefer the explicit ask if present; otherwise derive it.
    #
    # 2026-10-02: ``entry_price_basis="bid"`` evaluates queue-priced maker
    # economics — a resting post-only buy actually pays the own-side BID,
    # not the ask.  Pricing the maker pass at the ask systematically
    # understated resting-order edge by the full spread and left the maker
    # lane unable to admit anything the taker lane had not already cleared.
    # A side with no bid cannot host a resting order: charge it 100% entry
    # so it fails the edge gate naturally instead of being silently priced.
    if entry_price_basis == "bid":
        yes_entry = (yes_bid_cents / 100.0) if yes_bid_cents > 0 else 1.0
        no_entry = (no_bid_cents / 100.0) if no_bid_cents > 0 else 1.0
    else:
        yes_entry = yes_ask_cents / 100.0
        no_entry = no_ask_cents / 100.0
        if yes_ask_cents <= 0 and no_bid_cents > 0:
            yes_entry = (100.0 - no_bid_cents) / 100.0
        if no_ask_cents <= 0 and yes_bid_cents > 0:
            no_entry = (100.0 - yes_bid_cents) / 100.0
    indicators["entry_price_basis"] = entry_price_basis
    indicators["adverse_selection_reserve_cents"] = (
        float(adverse_selection_reserve) * 100.0
    )

    # Validate executable asks are inside [0,1]; a bad quote is a no-trade.
    if not (0.0 <= yes_entry <= 1.0 and 0.0 <= no_entry <= 1.0):
        return _no_trade("invalid_executable_asks")

    # 2026-08-30: resolve and sanity-clamp the Bachelier volatility.  The
    # mid-market price is used only as an optional implied-vol cross-check, never
    # as the p_yes estimate.  Resolved vol, source, band, and z-score are
    # recorded in indicators for telemetry and audit.
    yes_mid_cents = (
        (yes_bid_cents + yes_ask_cents) / 2.0
        if yes_bid_cents > 0 and yes_ask_cents > 0
        else (yes_ask_cents if yes_ask_cents > 0 else 100.0 - no_bid_cents)
    )
    yes_mid_cents = max(1.0, min(99.0, yes_mid_cents))
    market_prob = yes_mid_cents / 100.0

    resolved_vol, vol_source, band_min, band_max, components = _resolve_annualized_vol(
        asset=asset,
        requested_vol=float(annualized_vol),
        spot_price=float(spot_price),
        strike_price=float(strike_price),
        seconds_to_expiry=float(seconds_to_expiry),
        market_prob=market_prob,
    )
    if components is None:
        return _no_trade("bachelier_vol_resolution_failed")
    log_moneyness = components["log_moneyness"]
    z = components["z_score"]
    p_yes_raw = components["p_yes_raw"]
    indicators.update({
        "annualized_vol": resolved_vol,
        "annualized_vol_source": vol_source,
        "annualized_vol_band_min": band_min,
        "annualized_vol_band_max": band_max,
        "log_moneyness": log_moneyness,
        "z_score": z,
        "market_prob_for_implied_vol": market_prob,
        "bachelier_spot": float(spot_price),
        "strike": float(strike_price),
    })

    # If a settlement-aware distribution is supplied, use it as the canonical
    # distribution of the final 60-second settlement average.  This overrides
    # the legacy point-price Bachelier p_yes for probability but preserves the
    # same cost/edge/tail gates.
    if settlement_distribution is not None and math.isfinite(settlement_distribution.p_yes_raw):
        p_yes_raw = float(settlement_distribution.p_yes_raw)
        log_moneyness = (float(settlement_distribution.mean) - float(strike_price)) / max(abs(float(strike_price)), 1e-12)
        z = float(settlement_distribution.z_score)
        indicators.update({
            "settlement_forecast_mean": float(settlement_distribution.mean),
            "settlement_forecast_std": float(settlement_distribution.std),
            "settlement_observed_count": int(settlement_distribution.observed_count),
            "settlement_remaining_count": int(settlement_distribution.remaining_count),
            "settlement_phase": settlement_distribution.phase,
            "settlement_forecast_method": settlement_distribution.forecast_method,
            "settlement_model_version": settlement_distribution.model_version,
            "log_moneyness": log_moneyness,
            "z_score": z,
            "p_yes_raw": p_yes_raw,
        })

    # 2026-08-30: Per-side tail calibration.  The YES and NO held-side
    # probabilities are calibrated independently from their own tail curves,
    # then the opposite side is derived for logical consistency.  This fixes
    # the dual-inflation bug where capping cheap-YES p_yes forced p_no = 0.95,
    # fabricating large NO edges on expensive NO contracts.
    p_no_raw = 1.0 - p_yes_raw

    # 2026-08-28: accept externally supplied p_yes_model only when hybrid
    # probabilities are explicitly enabled.  Bachelier-only is the live default.
    # 2026-11: admission now consults the resolved probability-source allowlist —
    # MERID_TRADE_DECISION_ALLOW_HYBRID_P alone can no longer admit a source that
    # the resolved config has not granted (see live_config.py allowlist).
    p_yes_for_yes = float(p_yes_raw)
    p_no_for_no = float(p_no_raw)
    if _probability_source_allowed("hybrid_bachelier_deltas") and p_yes_model is not None and math.isfinite(p_yes_model):
        p_yes_for_yes = max(0.0, min(1.0, p_yes_model))
        p_no_for_no = 1.0 - p_yes_for_yes

    # 2026-09-23: Market-anchor shrinkage.  The Kalshi 15m book is arbitraged
    # against live spot and is near-perfectly calibrated at the horizons we
    # trade, so the market mid is the strongest available prior.  Shrink the
    # model probability toward the market-implied probability in logit space
    # with a weight that ramps from MERID_MARKET_ANCHOR_MIN_W (window open) to
    # MERID_MARKET_ANCHOR_MAX_W (expiry).  Only a two-sided book qualifies as
    # an anchor; without one the model keeps full authority.
    p_yes_pre_anchor = p_yes_for_yes
    market_anchor_weight = 0.0
    if yes_bid_cents > 0 and yes_ask_cents > yes_bid_cents:
        anchor_window = max(MERID_MARKET_ANCHOR_WINDOW_S, 1.0)
        frac_elapsed = max(0.0, min(1.0, 1.0 - float(seconds_to_expiry) / anchor_window))
        market_anchor_weight = MERID_MARKET_ANCHOR_MIN_W + (
            MERID_MARKET_ANCHOR_MAX_W - MERID_MARKET_ANCHOR_MIN_W
        ) * frac_elapsed
        market_anchor_weight = max(0.0, min(0.98, market_anchor_weight))
        # 2026-09-23: anchor release in the settlement window.  The book quotes
        # the terminal price while the settlement distribution prices the
        # banked 60-sample average — with k of 60 samples realized, the model
        # is strictly better informed, so the market's authority scales with
        # the unrealized fraction rather than the wall-clock ramp.
        if (
            MERID_SETTLEMENT_ANCHOR_RELEASE
            and settlement_distribution is not None
            and getattr(settlement_distribution, "phase", None) == "in_window"
        ):
            _n_rem = float(getattr(settlement_distribution, "remaining_count", 60) or 0)
            market_anchor_weight *= max(0.0, min(1.0, _n_rem / 60.0))
        if market_anchor_weight > 0.0:
            def _logit(x: float) -> float:
                x = max(1e-6, min(1.0 - 1e-6, x))
                return math.log(x / (1.0 - x))

            blended = (1.0 - market_anchor_weight) * _logit(p_yes_for_yes) + (
                market_anchor_weight * _logit(market_prob)
            )
            p_yes_for_yes = max(0.0, min(1.0, 1.0 / (1.0 + math.exp(-blended))))
            p_no_for_no = 1.0 - p_yes_for_yes
    indicators.update({
        "market_anchor_weight": market_anchor_weight,
        "market_anchor_prob": market_prob,
        "p_yes_pre_anchor": p_yes_pre_anchor,
        "p_yes_post_anchor": p_yes_for_yes,
    })

    # Walk-forward asset x TTE canonical calibration (2026-09-29).  One
    # correction on the anchored p_yes; the NO lane derives the complement so
    # YES and NO remain coherent.  Per-side evidence caps below still bind as
    # safety bounds on whichever lane is evaluated.
    _p_yes_wf = _walkforward_calibrate_p_yes(asset, seconds_to_expiry, p_yes_for_yes)
    if _p_yes_wf is not None:
        indicators["p_yes_pre_walkforward"] = p_yes_for_yes
        indicators["walkforward_cal_applied"] = True
        p_yes_for_yes = _p_yes_wf
        p_no_for_no = 1.0 - p_yes_for_yes
    else:
        indicators["walkforward_cal_applied"] = False

    # 2026-10-04: empirical price-calibration overlay (favorite-longshot).
    # The market anchor above assumes the book is calibrated; the settled
    # record says it is not in specific (side, price, TTE) cells.  In a
    # validated cell the shrunk empirical win rate replaces the side's
    # probability (live mode, upward only — the cells are validated as
    # under-priced).  The tail caps and deviation guard below still bind.
    _epc_mode = _epc.mode()
    indicators["epc_mode"] = _epc_mode
    if _epc_mode != "off":
        for _epc_side, _epc_entry in (("yes", yes_entry), ("no", no_entry)):
            _epc_est = _epc.lookup(_epc_side, float(_epc_entry) * 100.0, float(seconds_to_expiry))
            if _epc_est is None:
                continue
            _epc_cur = p_yes_for_yes if _epc_side == "yes" else p_no_for_no
            indicators[f"{_epc_side}_epc_cell"] = _epc_est.cell_id
            indicators[f"{_epc_side}_epc_p"] = _epc_est.p
            indicators[f"{_epc_side}_epc_p_model"] = _epc_cur
            indicators[f"{_epc_side}_epc_cell_n"] = _epc_est.n
            indicators[f"{_epc_side}_epc_cell_edge_lcb_c"] = _epc_est.edge_lcb_c
            # Price-adjusted empirical LCB: the cell's walk-forward-validated
            # lower-bound edge is measured at the cell's average fill price;
            # entering above that average reduces realized edge cent-for-cent.
            indicators[f"{_epc_side}_epc_adj_lcb_cents"] = (
                _epc_est.edge_lcb_c
                - (float(_epc_entry) * 100.0 - _epc_est.avg_price_c)
            )
            _epc_apply = _epc_mode == "live" and _epc_est.p > _epc_cur
            indicators[f"{_epc_side}_epc_applied"] = _epc_apply
            if _epc_apply:
                if _epc_side == "no":
                    p_no_for_no = _epc_est.p
                    p_yes_for_yes = min(p_yes_for_yes, 1.0 - _epc_est.p)
                else:
                    p_yes_for_yes = _epc_est.p
                    p_no_for_no = min(p_no_for_no, 1.0 - _epc_est.p)
            _epc.log_observation(
                ticker=ticker, asset=asset, side=_epc_side, mode=_epc_mode,
                held_price_cents=float(_epc_entry) * 100.0,
                seconds_to_expiry=float(seconds_to_expiry), est=_epc_est,
                p_model=float(_epc_cur), applied=_epc_apply,
                fee_cents=float(fee_per_contract_cents) if fee_per_contract_cents is not None else None,
            )

    # YES-held curve: calibrate p_yes when the artifact has support at the held
    # price.  2026-09-25: extended from tail-only (<35c) to the full fitted
    # range — the model may never claim more than observed_win_rate + buffer
    # at any price.
    p_yes_for_yes_pre_cap = p_yes_for_yes
    tail_cap_yes_reason = "none"
    tail_calibration_yes_configured = False
    tail_calibration_yes_applied = False
    tail_calibrator = None
    if MERID_TAIL_CALIBRATION_ENABLED:
        tail_calibrator = load_tail_calibrator()
        if tail_calibrator is not None and (
            MERID_CALIBRATION_CAP_FULL_RANGE
            or yes_entry < MERID_TAIL_CALIBRATION_PRICE_FLOOR
        ):
            tail_calibration_yes_configured = True
            tail_cap_yes_reason = "real_curve"
            p_yes_for_yes = tail_calibrator.cap_p_yes(p_yes_for_yes, yes_entry, asset=asset)
            if abs(p_yes_for_yes - p_yes_for_yes_pre_cap) > 1e-9:
                tail_calibration_yes_applied = True
    # Kalshi venue-invariant [0.05, 0.95] so the downstream order router does
    # not reject high-confidence signals as invalid_model_prob.
    p_yes_for_yes = max(0.05, min(0.95, p_yes_for_yes))
    p_no_for_yes = 1.0 - p_yes_for_yes

    # NO-held curve: calibrate p_no if NO is in the cheap tail.
    # The NO curve in the calibration file is currently a dual, so this is a
    # stop-gap until a real NO tail curve is refit from NO-held records.
    # 2026-08-30: To avoid over-correcting moderate NO beliefs, only apply the
    # dual NO cap when the raw NO model probability is itself in the cheap-tail
    # region (below MERID_TAIL_CALIBRATION_NO_DUAL_RAW_FLOOR).  A real NO curve
    # (no_curve_is_dual=False) is applied unconditionally in the cheap-price tail.
    p_no_for_no_pre_cap = p_no_for_no
    tail_cap_no_reason = "none"
    tail_calibration_no_configured = False
    tail_calibration_no_applied = False
    tail_calibration_no_weight = 0.0
    if MERID_TAIL_CALIBRATION_ENABLED:
        tail_calibrator = load_tail_calibrator()
        # 2026-09-25: the real NO curve (non-dual) applies at any held price;
        # a dual NO curve remains a tail-only stop-gap.
        _no_cap_in_scope = tail_calibrator is not None and (
            no_entry < MERID_TAIL_CALIBRATION_PRICE_FLOOR
            or (
                MERID_CALIBRATION_CAP_FULL_RANGE
                and not tail_calibrator.no_curve_is_dual
            )
        )
        if _no_cap_in_scope:
            tail_calibration_no_configured = True
            if tail_calibrator.no_curve_is_dual:
                tail_calibration_no_weight = _dual_tail_shrinkage_weight(p_no_for_no)
                calibrated_no = tail_calibrator.cap_p_no(p_no_for_no, no_entry, asset=asset)
                p_no_for_no = p_no_for_no + tail_calibration_no_weight * (
                    calibrated_no - p_no_for_no
                )
                tail_cap_no_reason = "dual_continuous_shrinkage"
                if abs(p_no_for_no - p_no_for_no_pre_cap) > 1e-9:
                    tail_calibration_no_applied = True
                logger.info(
                    "[TAIL-CALIBRATION-NO-DUAL] asset=%s ticker=%s no_entry=%.3f "
                    "raw_p_no=%.3f weight=%.4f calibrated_p_no=%.3f",
                    asset, ticker, no_entry, p_no_for_no_pre_cap,
                    tail_calibration_no_weight, p_no_for_no,
                )
            else:
                tail_cap_no_reason = "real_curve"
                p_no_for_no = tail_calibrator.cap_p_no(p_no_for_no, no_entry, asset=asset)
                if abs(p_no_for_no - p_no_for_no_pre_cap) > 1e-9:
                    tail_calibration_no_applied = True
    p_no_for_no = max(0.05, min(0.95, p_no_for_no))
    p_yes_for_no = 1.0 - p_no_for_no

    # Deviation guard: fail-closed on probability INFLATION only, outside the
    # cheap tail.  A large upward move from the raw model probability on a
    # non-tail held side is a calibration-inflation red flag (model-market
    # divergence the anchor must not silently override).  Downward moves are
    # data-driven (market anchor and the observed-rate cap, now applied at all
    # prices) and are legitimate.  In the tail the observed-rate cap already
    # bounds the final value, so large moves remain exempt as before.
    # The threshold is configurable; default 0.15.
    tail_calibration_deviation_guard = float(
        os.environ.get("MERID_TAIL_CALIBRATION_DEVIATION_GUARD", "0.15")
    )
    yes_deviation = abs(p_yes_for_yes - p_yes_raw)
    no_deviation = abs(p_no_for_no - p_no_raw)
    yes_in_tail = yes_entry < MERID_TAIL_CALIBRATION_PRICE_FLOOR
    no_in_tail = no_entry < MERID_TAIL_CALIBRATION_PRICE_FLOOR

    tail_guard_violation_yes = False
    tail_guard_violation_no = False
    if (
        yes_entry > 0
        and (p_yes_for_yes - p_yes_raw) > tail_calibration_deviation_guard
        and not yes_in_tail
    ):
        tail_guard_violation_yes = True
        logger.warning(
            "[TAIL-CALIBRATION-GUARD] asset=%s ticker=%s YES held_price=%.2f not in tail; "
            "p_yes inflated %.3f beyond guard %.3f (raw_p_yes=%.3f, final_p_yes=%.3f)",
            asset, ticker, yes_entry, p_yes_for_yes - p_yes_raw,
            tail_calibration_deviation_guard, p_yes_raw, p_yes_for_yes,
        )
    if (
        no_entry > 0
        and (p_no_for_no - p_no_raw) > tail_calibration_deviation_guard
        and not no_in_tail
    ):
        tail_guard_violation_no = True
        logger.warning(
            "[TAIL-CALIBRATION-GUARD] asset=%s ticker=%s NO held_price=%.2f not in tail; "
            "p_no inflated %.3f beyond guard %.3f (raw_p_no=%.3f, final_p_no=%.3f)",
            asset, ticker, no_entry, p_no_for_no - p_no_raw,
            tail_calibration_deviation_guard, p_no_raw, p_no_for_no,
        )

    indicators.update({
        "p_yes_raw": p_yes_raw,
        "p_no_raw": p_no_raw,
        "p_yes_for_yes": p_yes_for_yes,
        "p_no_for_yes": p_no_for_yes,
        "p_yes_for_no": p_yes_for_no,
        "p_no_for_no": p_no_for_no,
        "p_yes_for_yes_pre_cap": p_yes_for_yes_pre_cap,
        "p_no_for_no_pre_cap": p_no_for_no_pre_cap,
        "tail_cap_yes": tail_calibration_yes_applied,
        "tail_cap_no": tail_calibration_no_applied,
        "tail_cap_yes_reason": tail_cap_yes_reason,
        "tail_cap_no_reason": tail_cap_no_reason,
        "tail_calibration_yes_configured": tail_calibration_yes_configured,
        "tail_calibration_yes_applied": tail_calibration_yes_applied,
        "tail_calibration_no_configured": tail_calibration_no_configured,
        "tail_calibration_no_applied": tail_calibration_no_applied,
        "tail_calibration_yes_reason": tail_cap_yes_reason,
        "tail_calibration_no_reason": tail_cap_no_reason,
        "tail_deviation_yes": yes_deviation,
        "tail_deviation_no": no_deviation,
        "tail_deviation_guard": tail_calibration_deviation_guard,
        "tail_guard_violation_yes": tail_guard_violation_yes,
        "tail_guard_violation_no": tail_guard_violation_no,
        "tail_calibration_no_dual_raw_floor": MERID_TAIL_CALIBRATION_NO_DUAL_RAW_FLOOR,
        "tail_calibration_no_dual_transition": MERID_TAIL_CALIBRATION_NO_DUAL_TRANSITION,
        "tail_calibration_no_weight": tail_calibration_no_weight,
        "tail_calibration_provenance": (
            {
                "n_trades": int(getattr(tail_calibrator, "n_trades", 0)),
                "buffer": float(getattr(tail_calibrator, "buffer", 0.0)),
                "metadata": dict(getattr(tail_calibrator, "metadata", {}) or {}),
                "no_curve_is_dual": bool(getattr(tail_calibrator, "no_curve_is_dual", False)),
                "yes_bucket_count": len(getattr(tail_calibrator, "yes_held_prices", []) or []),
                "no_bucket_count": len(getattr(tail_calibrator, "no_held_prices", []) or []),
            }
            if tail_calibrator is not None
            else None
        ),
    })

    fee = fee_per_contract_cents / 100.0

    # 2026-09-25: Calibration evidence floor.  A held-side price cell is only
    # tradeable when the observed win rate at that price clears
    # price + entry_fee + margin.  This gate depends only on the artifact and
    # the executable quote — no model inputs — so cell eligibility is static
    # between refits.  A dual NO curve carries no independent evidence and
    # does not gate.
    yes_evidence_ok = True
    no_evidence_ok = True
    yes_evidence_reason: Optional[str] = None
    no_evidence_reason: Optional[str] = None
    if tail_calibrator is not None and MERID_CALIBRATION_CAP_FULL_RANGE:
        _ev_floor_yes = yes_entry + fee + MERID_CALIBRATION_EVIDENCE_MARGIN
        _ev_floor_no = no_entry + fee + MERID_CALIBRATION_EVIDENCE_MARGIN
        yes_evidence_ok = yes_entry <= 0 or (
            tail_calibrator.p_yes(yes_entry, asset=asset) >= _ev_floor_yes
        )
        no_evidence_ok = no_entry <= 0 or (
            tail_calibrator.no_curve_is_dual
            or tail_calibrator.p_no(no_entry, asset=asset) >= _ev_floor_no
        )
        indicators.update({
            "calibration_evidence_floor_yes": _ev_floor_yes,
            "calibration_evidence_floor_no": _ev_floor_no,
            "calibration_evidence_obs_yes": tail_calibrator.p_yes(yes_entry, asset=asset),
            "calibration_evidence_obs_no": tail_calibrator.p_no(no_entry, asset=asset),
            "calibration_evidence_scope": (
                "asset" if tail_calibrator.has_asset_curve(asset) else "pooled"
            ),
            "calibration_evidence_yes": yes_evidence_ok,
            "calibration_evidence_no": no_evidence_ok,
        })
        if not yes_evidence_ok:
            yes_evidence_reason = "calibration_evidence_yes"
        if not no_evidence_ok:
            no_evidence_reason = "calibration_evidence_no"

    # 2026-09-23: settlement-convergence entries hold to settlement — there is
    # no exit order and no exit fee inside the final minute, so the reserve is
    # zero rather than a phantom taker exit.  (Dataset: hold-to-settlement
    # beats any timed exit on this product; charging an exit that cannot
    # happen suppresses real edge.)
    # 2026-09-27: identical reasoning when the operator disabled the exit
    # policy outright — every entry holds to settlement, so no exit fee can
    # ever be incurred.  Charging it understates net edge by ~1.6c/contract.
    # 2026-10-05: the exit reserve is the *expected* liquidation cost under
    # the active exit policy, not a full taker fee charged at certainty.
    # Settlement-lane / exit-disabled entries still reserve zero; ev_gated
    # entries reserve p_trigger * fee (see MERID_EXPECTED_EXIT_* constants).
    expected_exit_cost_yes, _exit_class_yes, _exit_p_yes = _expected_exit_cost(
        yes_entry, fee, settlement_lane
    )
    expected_exit_cost_no, _exit_class_no, _exit_p_no = _expected_exit_cost(
        no_entry, fee, settlement_lane
    )
    indicators.update({
        "yes_exit_policy_class": _exit_class_yes,
        "no_exit_policy_class": _exit_class_no,
        "yes_exit_trigger_prob": _exit_p_yes,
        "no_exit_trigger_prob": _exit_p_no,
        "yes_exit_cost_method": (
            "p_trigger_x_taker_fee" if _exit_p_yes > 0.0 else "none"
        ),
        "no_exit_cost_method": (
            "p_trigger_x_taker_fee" if _exit_p_no > 0.0 else "none"
        ),
    })

    model_risk_reserve = _compute_model_risk_reserve(
        model_uncertainty, data_quality, regime, seconds_to_expiry,
        settlement_lane=settlement_lane,
    )

    yes_breakdown = compute_edge(
        p_yes=p_yes_for_yes,
        selected_side="yes",
        entry_price=yes_entry,
        entry_fee=fee,
        exit_cost_reserve=expected_exit_cost_yes,
        model_risk_reserve=model_risk_reserve,
        adverse_selection_reserve=adverse_selection_reserve,
    )
    no_breakdown = compute_edge(
        p_yes=p_yes_for_no,
        selected_side="no",
        entry_price=no_entry,
        entry_fee=fee,
        exit_cost_reserve=expected_exit_cost_no,
        adverse_selection_reserve=adverse_selection_reserve,
        model_risk_reserve=model_risk_reserve,
    )

    # 2026-08-30: Fee-aware, asset-tiered, spread-aware edge threshold.
    # The threshold is evaluated per side because each side has a different
    # price and spread.  ``min_required_edge`` remains the hard global floor.
    yes_price_cents = int(round(yes_entry * 100.0))
    no_price_cents = int(round(no_entry * 100.0))
    _yes_edge_thr = _decompose_dynamic_min_required_edge(
        asset=asset,
        price_cents=yes_price_cents,
        side="yes",
        yes_bid_cents=yes_bid_cents,
        yes_ask_cents=yes_ask_cents,
        no_bid_cents=no_bid_cents,
        no_ask_cents=no_ask_cents,
        floor_min_required_edge=min_required_edge,
        seconds_to_expiry=seconds_to_expiry,
    )
    _no_edge_thr = _decompose_dynamic_min_required_edge(
        asset=asset,
        price_cents=no_price_cents,
        side="no",
        yes_bid_cents=yes_bid_cents,
        yes_ask_cents=yes_ask_cents,
        no_bid_cents=no_bid_cents,
        no_ask_cents=no_ask_cents,
        floor_min_required_edge=min_required_edge,
        seconds_to_expiry=seconds_to_expiry,
    )
    yes_min_edge = _yes_edge_thr.total
    no_min_edge = _no_edge_thr.total
    indicators["yes_min_edge"] = yes_min_edge
    indicators["no_min_edge"] = no_min_edge
    # Threshold decomposition (probability points) — lets the audit answer
    # "what reserve blocked this candidate" rather than just the total.
    for _pfx, _d in (("yes", _yes_edge_thr), ("no", _no_edge_thr)):
        indicators[f"{_pfx}_thr_base_floor_cents"] = _d.base_floor * 100.0
        indicators[f"{_pfx}_thr_global_floor_cents"] = _d.global_floor * 100.0
        indicators[f"{_pfx}_thr_asset_base_cents"] = _d.asset_base * 100.0
        indicators[f"{_pfx}_thr_convexity_cents"] = _d.convexity * 100.0
        indicators[f"{_pfx}_thr_flb_premium_cents"] = _d.flb_premium * 100.0
        indicators[f"{_pfx}_thr_band_relief_cents"] = _d.band_relief * 100.0
        indicators[f"{_pfx}_thr_clamped_floor"] = _d.clamped_floor
        indicators[f"{_pfx}_thr_clamped_ceiling"] = _d.clamped_ceiling
        indicators[f"{_pfx}_thr_cell_id"] = _d.cell_id
        indicators[f"{_pfx}_thr_cell_min_ev_cents"] = _d.cell_min_ev_cents
        indicators[f"{_pfx}_thr_cell_cap_exhausted"] = _d.cell_cap_exhausted
        # Unambiguous threshold-source fields: the formula output, the cell's
        # value, the effective enforced value, and which one authorized.
        _formula_c = (
            _d.formula_total * 100.0 if _d.formula_total is not None
            else _d.total * 100.0
        )
        indicators[f"{_pfx}_formula_required_edge_cents"] = _formula_c
        indicators[f"{_pfx}_cell_required_edge_cents"] = _d.cell_min_ev_cents
        indicators[f"{_pfx}_provisional_required_edge_cents"] = (
            _d.provisional_min_ev_cents
        )
        indicators[f"{_pfx}_effective_required_edge_cents"] = _d.total * 100.0
        indicators[f"{_pfx}_threshold_source"] = (
            "threshold_cell" if _d.cell_id is not None
            else "current_build_provisional" if _d.provisional_cell_id is not None
            else "formula"
        )
        indicators[f"{_pfx}_thr_cell_block_reason"] = _d.cell_block_reason
        indicators[f"{_pfx}_thr_prov_cell_id"] = _d.provisional_cell_id
        indicators[f"{_pfx}_thr_prov_cap_exhausted"] = (
            _d.provisional_cap_exhausted
        )
        indicators[f"{_pfx}_thr_prov_block_reason"] = _d.provisional_block_reason
        # Boundary-miss attribution: when the (asset, side) pair has cells but
        # none matched, name the exact boundary that excluded this quote so a
        # near-miss never silently falls through to the generic formula.
        if _d.cell_id is None:
            _miss_px = yes_price_cents if _pfx == "yes" else no_price_cents
            _miss = explain_cell_miss(asset, _pfx, _miss_px, seconds_to_expiry)
            if _miss and _miss != "no_cells_for_asset_side":
                indicators[f"{_pfx}_thr_cell_miss_reason"] = _miss
            if _d.provisional_cell_id is None and not cell_region_registered(
                asset, _pfx, _miss_px, seconds_to_expiry
            ):
                _pmiss = _cbp.explain_provisional_miss(
                    asset, _pfx, _miss_px, seconds_to_expiry
                )
                if _pmiss and _pmiss != "provisional_lane_disabled":
                    indicators[f"{_pfx}_prov_cell_miss_reason"] = _pmiss
                    if _pmiss in (
                        "provisional_price_below_min",
                        "provisional_price_above_max",
                        "provisional_tte_below_min",
                        "provisional_tte_above_max",
                        "provisional_cell_gap",
                    ):
                        _cbp.bump_provisional_funnel("blocked_by_price_band")

    # 2026-09-28: Live rolling entry-evidence gate.  See MERID_LIVE_EVIDENCE_GATE
    # notes at module level — applies the evidence-floor semantics to the
    # trailing settled-outcome window the audit ledger rebuilds per settlement.
    # Fail-open on absent/under-sampled cohorts (static floor above still applies).
    # 2026-09-29: cell-aware policy (evidence_policy.py / artifact v2) replaces
    # the price-blind asset-side veto: hierarchical Beta-binomial posterior at
    # asset x side x price-bucket x TTE-bucket with partial pooling to the
    # nearest adequately-sampled ancestor, scored as an LCB net-EV check at the
    # candidate's own executable price.  Only a dense, matched, non-contradicted
    # toxic cell hard-blocks; sparse cells raise the required margin via an
    # uncertainty uplift and route through the bounded escape lane.
    if MERID_LIVE_EVIDENCE_GATE:
        _live_ev = _load_live_evidence()
        if _live_ev is not None:
            indicators["live_evidence_evaluated"] = True
            if evidence_policy.enabled() and isinstance(
                (_live_ev or {}).get("cells"), dict
            ) and (_live_ev or {}).get("cells"):
                indicators["evidence_policy_version"] = (
                    evidence_policy.EVIDENCE_POLICY_VERSION
                )
                for _side, _px, _ne_c in (
                    ("yes", yes_price_cents, float(yes_breakdown.net_edge) * 100.0),
                    ("no", no_price_cents, float(no_breakdown.net_edge) * 100.0),
                ):
                    _ed = evidence_policy.evaluate(
                        _live_ev,
                        asset,
                        _side,
                        _px,
                        seconds_to_expiry,
                        fee,
                        MERID_LIVE_EVIDENCE_MARGIN,
                        _ne_c,
                    )
                    indicators[f"evidence_{_side}"] = _ed.detail()
                    if _ed.escape_required:
                        indicators[f"evidence_escape_{_side}"] = True
                    if not _ed.allowed:
                        # 2026-09-30: bounded soft-evidence override for the
                        # threshold-cell lane.  A matched, historically
                        # qualified cell whose current net EV already clears
                        # its own effective threshold owns its admission —
                        # soft verdicts (SOFT_EVIDENCE_CODES, incl. the
                        # generic escape-lane budget) route through the cell
                        # lane's own caps/suspension instead of the shared
                        # escape budget.  Hard blocks, non-soft codes,
                        # low-EV candidates, and suspended/capped lanes keep
                        # their original rejection.
                        _d = _yes_edge_thr if _side == "yes" else _no_edge_thr
                        _ovr_ok, _ovr_reason = threshold_cell_admission_allowed(
                            cell_id=_d.cell_id,
                            evidence_code=_ed.code,
                            matching_hard_block=bool(_ed.matching_hard_block),
                            net_ev_cents=_ne_c,
                            effective_required_edge_cents=(
                                _d.total * 100.0 if _d.cell_id is not None else None
                            ),
                        )
                        # Current-build provisional lane: when no registered
                        # cell owns the region, a *legacy* verdict (including
                        # a legacy hard block) is a label, not a veto — the
                        # probe enforces current EV >= provisional threshold,
                        # lane state, and all cbp caps.
                        _ovr_via_cbp = False
                        if not _ovr_ok and _d.provisional_cell_id is not None:
                            _ovr_via_cbp = _provisional_evidence_probe(
                                _d,
                                _side,
                                _ne_c,
                                _ed.code,
                                bool(_ed.matching_hard_block),
                                indicators,
                            )
                        if _ovr_ok:
                            bump_cell_funnel("soft_evidence_override", _d.cell_id)
                            indicators[f"{_side}_admission_owner"] = "threshold_cell"
                            indicators[f"{_side}_admission_decision"] = "allowed"
                            indicators[f"{_side}_admission_reason"] = (
                                "qualified_cell_soft_evidence_override"
                            )
                            indicators[f"{_side}_evidence_override"] = (
                                "threshold_cell_soft_evidence_provisional"
                            )
                            indicators[f"{_side}_evidence_override_detail"] = (
                                _ed.detail()
                            )
                            try:
                                _cell = next(
                                    (c for c in THRESHOLD_CELLS
                                     if c.cell_id == _d.cell_id),
                                    None,
                                )
                                _decay = evidence_policy.decayed_evidence_report(
                                    _live_ev, asset, _side, _px,
                                    seconds_to_expiry,
                                )
                                emit_cell_lifecycle(
                                    "soft_evidence_override",
                                    event="threshold_cell_soft_evidence_override",
                                    threshold_cell_id=_d.cell_id,
                                    asset=asset,
                                    side=_side.upper(),
                                    lane_state_before=get_cell_state(_d.cell_id),
                                    evidence_code=_ed.code,
                                    matching_hard_block=bool(
                                        _ed.matching_hard_block
                                    ),
                                    historical_counterfactual_lcb10_cents=(
                                        _cell.historical_lcb10_cents
                                        if _cell else None
                                    ),
                                    live_fill_count_before=cell_fills_today(
                                        _d.cell_id
                                    ),
                                    cell_required_edge_cents=_d.total * 100.0,
                                    candidate_net_ev_cents=_ne_c,
                                    formula_required_edge_cents=(
                                        _d.formula_total * 100.0
                                        if _d.formula_total is not None
                                        else None
                                    ),
                                    override_reason=(
                                        "bounded_live_execution_validation"
                                    ),
                                    quantity=1,
                                    post_only=True,
                                    tte_seconds=seconds_to_expiry,
                                    price_cents=_px,
                                    decision_id=decision_id,
                                    admission_owner="threshold_cell",
                                    decayed_evidence=_decay,
                                    terminal_state="override_admitted",
                                )
                            except Exception:
                                pass
                        elif _ovr_via_cbp:
                            # Legacy evidence demoted to a monitoring label;
                            # the provisional lane admitted on current-build
                            # economics alone.  Lift the side's evidence flag —
                            # inside the provisional domain a legacy verdict
                            # (static calibration floor or cell-policy block)
                            # is a label, not a veto.
                            if _side == "yes":
                                yes_evidence_ok = True
                                yes_evidence_reason = None
                            else:
                                no_evidence_ok = True
                                no_evidence_reason = None
                            indicators[f"{_side}_evidence_override"] = (
                                "current_build_provisional_lane"
                            )
                            indicators[f"{_side}_legacy_risk_detail"] = (
                                _ed.detail()
                            )
                            try:
                                _pcell = _cbp.provisional_cell_for_id(
                                    _d.provisional_cell_id
                                )
                                _cbp.emit_provisional_lifecycle(
                                    "legacy_evidence_labelled",
                                    provisional_cell_id=_d.provisional_cell_id,
                                    asset=asset,
                                    side=_side.upper(),
                                    lane_state_before=_cbp.get_cell_state(
                                        _d.provisional_cell_id
                                    ),
                                    legacy_risk_label=_ed.code,
                                    matching_hard_block=bool(
                                        _ed.matching_hard_block
                                    ),
                                    provisional_required_ev_cents=(
                                        _d.total * 100.0
                                    ),
                                    candidate_net_ev_cents=_ne_c,
                                    formula_required_edge_cents=(
                                        _d.formula_total * 100.0
                                        if _d.formula_total is not None
                                        else None
                                    ),
                                    quantity=1,
                                    post_only=True,
                                    tte_seconds=seconds_to_expiry,
                                    price_cents=_px,
                                    price_bucket=(
                                        _cbp.price_band_label(_pcell)
                                        if _pcell else None
                                    ),
                                    tte_bucket=(
                                        _cbp.tte_band_label(_pcell)
                                        if _pcell else None
                                    ),
                                    decision_id=decision_id,
                                    admission_owner=(
                                        "current_build_provisional"
                                    ),
                                    build_sha=_cbp.current_build_sha(),
                                    model_version=(
                                        _cbp.current_model_version(indicators)
                                    ),
                                    calibration_version=(
                                        _cbp.current_calibration_version()
                                    ),
                                    evidence_generation=(
                                        (_live_ev or {}).get("generated_at")
                                    ),
                                    terminal_state="override_admitted",
                                )
                            except Exception:
                                pass
                        else:
                            # The cell matched but could not admit — name the
                            # owner and the true blocker for audit.
                            if _d.cell_id is not None:
                                indicators[f"{_side}_admission_owner"] = (
                                    "hard_block"
                                    if _ed.matching_hard_block
                                    or _ed.code == "MATCHING_TOXIC_CELL"
                                    else "threshold_cell"
                                )
                                indicators[f"{_side}_admission_decision"] = (
                                    "blocked"
                                )
                                indicators[f"{_side}_admission_reason"] = (
                                    _ovr_reason or _ed.code.lower()
                                )
                                indicators[
                                    f"{_side}_evidence_override_denied"
                                ] = _ovr_reason
                            elif _d.provisional_cell_id is not None:
                                _cbp.bump_provisional_funnel(
                                    "blocked_by_evidence", _d.provisional_cell_id
                                )
                                indicators[f"{_side}_admission_owner"] = (
                                    "current_build_provisional"
                                )
                                indicators[f"{_side}_admission_decision"] = (
                                    "blocked"
                                )
                                indicators[f"{_side}_admission_reason"] = (
                                    _d.provisional_block_reason or _ed.code.lower()
                                )
                                indicators[
                                    f"{_side}_evidence_override_denied"
                                ] = _d.provisional_block_reason or _ed.code
                            else:
                                indicators[f"{_side}_admission_owner"] = (
                                    "evidence_escape"
                                )
                                indicators[f"{_side}_admission_decision"] = (
                                    "blocked"
                                )
                                indicators[f"{_side}_admission_reason"] = (
                                    "generic_escape_budget_exhausted"
                                    if _ed.code in (
                                        "ESCAPE_CAP_EXHAUSTED",
                                        "CHALLENGE_CAP_EXHAUSTED",
                                    )
                                    else _ed.code.lower()
                                )
                            _reason_stem = {
                                "CELL_EVIDENCE_INSUFFICIENT": "evidence_cell_insufficient",
                                "SPARSE_MATCHED_INSUFFICIENT": "evidence_sparse_matched",
                                "MATCHING_TOXIC_CELL": "evidence_toxic_cell",
                                "EVIDENCE_EMPTY_INSUFFICIENT": "evidence_empty_insufficient",
                                "ESCAPE_CAP_EXHAUSTED": "evidence_escape_cap",
                                "ESCAPE_LANE_DISABLED": "evidence_escape_disabled",
                                "CHALLENGE_INSUFFICIENT": "evidence_challenge_insufficient",
                                "CHALLENGE_LANE_DISABLED": "evidence_escape_disabled",
                                "CHALLENGE_CAP_EXHAUSTED": "evidence_escape_cap",
                                "SOFT_PENALTY_INSUFFICIENT": "evidence_soft_penalty_insufficient",
                                "SOFT_PENALTY_LANE_DISABLED": "evidence_escape_disabled",
                            }.get(_ed.code, f"evidence_{_ed.code.lower()}")
                            if _side == "yes" and yes_evidence_ok:
                                yes_evidence_ok = False
                                yes_evidence_reason = f"{_reason_stem}_yes"
                                indicators[yes_evidence_reason] = _ed.detail()
                            elif _side == "no" and no_evidence_ok:
                                no_evidence_ok = False
                                no_evidence_reason = f"{_reason_stem}_no"
                                indicators[no_evidence_reason] = _ed.detail()
                    else:
                        # Evidence passed cleanly — name the owner so the
                        # admission lineage is explicit either way.
                        _d = _yes_edge_thr if _side == "yes" else _no_edge_thr
                        # 2026-10-05 (pooled-transfer tier): a sparse exact
                        # cell backed by an adequately-sampled price-matched
                        # pooled level (CELL_EVIDENCE_PASS on a scored level)
                        # is *transferrable* evidence, not blind exploration.
                        # It skips the escape vetoes — those were built for
                        # zero-evidence trials — but must clear an extra
                        # margin premium over the side's active edge bound.
                        _transfer = (
                            _ed.escape_required
                            and _ed.code == "CELL_EVIDENCE_PASS"
                            and _ed.evidence_level_used not in (None, "none")
                            and _ed.effective_independent_n
                            >= evidence_policy.min_cell_neff()
                        )
                        _escape_veto = None
                        if _transfer:
                            if (
                                float(_ne_c)
                                < float(_d.total) * 100.0
                                + MERID_EVIDENCE_TRANSFER_EXTRA_C
                            ):
                                _escape_veto = "evidence_transfer_margin"
                            else:
                                indicators[f"{_side}_evidence_mode"] = (
                                    "pooled_transfer"
                                )
                        elif _ed.escape_required:
                            _escape_veto = _evidence_escape_veto_reason(
                                asset=asset,
                                side=_side,
                                price_cents=float(_px),
                                net_ev_cents=float(_ne_c),
                                required_edge_cents=float(_d.total) * 100.0,
                                seconds_to_expiry=seconds_to_expiry,
                                spot_price=spot_price,
                                strike_price=strike_price,
                                annualized_vol=resolved_vol,
                                feature_snapshot=feature_snapshot,
                                dir_regime=directional_regime,
                            )
                        if _escape_veto is not None:
                            indicators[f"{_side}_admission_owner"] = (
                                "evidence_escape"
                            )
                            indicators[f"{_side}_admission_decision"] = (
                                "blocked"
                            )
                            indicators[f"{_side}_admission_reason"] = (
                                _escape_veto
                            )
                            if _side == "yes" and yes_evidence_ok:
                                yes_evidence_ok = False
                                yes_evidence_reason = f"{_escape_veto}_yes"
                                indicators[yes_evidence_reason] = _ed.detail()
                            elif _side == "no" and no_evidence_ok:
                                no_evidence_ok = False
                                no_evidence_reason = f"{_escape_veto}_no"
                                indicators[no_evidence_reason] = _ed.detail()
                        else:
                            indicators[f"{_side}_admission_owner"] = (
                                "threshold_cell" if _d.cell_id is not None
                                else "current_build_provisional"
                                if _d.provisional_cell_id is not None
                                else "evidence_pooled_transfer" if _transfer
                                else "evidence_escape" if _ed.escape_required
                                else "formula"
                            )
                            indicators[f"{_side}_admission_decision"] = "allowed"
                            indicators[f"{_side}_admission_reason"] = _ed.code.lower()
                        # 2026-10-02: inside the provisional domain the static
                        # calibration floor is a legacy verdict like the live
                        # gate — a clean live pass lifts it (caps/state were
                        # already verified when the cell id was assigned).
                        # An evidence_escape veto above is final — the lift
                        # must not re-admit a side the escape vetoes denied.
                        if _d.provisional_cell_id is not None and _escape_veto is None:
                            if _side == "yes" and not yes_evidence_ok:
                                yes_evidence_ok = True
                                yes_evidence_reason = None
                            elif _side == "no" and not no_evidence_ok:
                                no_evidence_ok = True
                                no_evidence_reason = None
            else:
                _yes_live_ok, _yes_live_det = _live_evidence_allows(
                    _live_ev, asset, "yes", yes_price_cents, fee
                )
                _no_live_ok, _no_live_det = _live_evidence_allows(
                    _live_ev, asset, "no", no_price_cents, fee
                )
                # The v1 rolling-win-rate block is itself pre-change legacy
                # evidence — inside the provisional domain it labels rather
                # than vetoes, subject to the same EV + lane-capacity checks.
                if not _yes_live_ok and yes_evidence_ok:
                    if _provisional_evidence_probe(
                        _yes_edge_thr, "yes",
                        float(yes_breakdown.net_edge) * 100.0,
                        "LEGACY_V1_BLOCK", False, indicators,
                    ):
                        indicators["legacy_risk_label_yes_v1"] = _yes_live_det
                    else:
                        yes_evidence_ok = False
                        yes_evidence_reason = f"live_evidence_{_yes_live_det['level']}_yes"
                        indicators[yes_evidence_reason] = _yes_live_det
                if not _no_live_ok and no_evidence_ok:
                    if _provisional_evidence_probe(
                        _no_edge_thr, "no",
                        float(no_breakdown.net_edge) * 100.0,
                        "LEGACY_V1_BLOCK", False, indicators,
                    ):
                        indicators["legacy_risk_label_no_v1"] = _no_live_det
                    else:
                        no_evidence_ok = False
                        no_evidence_reason = f"live_evidence_{_no_live_det['level']}_no"
                        indicators[no_evidence_reason] = _no_live_det

    # Funnel: a cell that matched (and survived lane admission) but loses its
    # side to an evidence hard block is a distinct cohort from unmatched
    # quotes — count it so blocked_by_evidence is measurable per cell.
    for _pfx, _d, _ev_ok in (
        ("yes", _yes_edge_thr, yes_evidence_ok),
        ("no", _no_edge_thr, no_evidence_ok),
    ):
        if _d.cell_id is not None and not _ev_ok:
            bump_cell_funnel("blocked_by_evidence", _d.cell_id)
        if _d.provisional_cell_id is not None and not _ev_ok:
            _cbp.bump_provisional_funnel(
                "blocked_by_evidence", _d.provisional_cell_id
            )

    best_side, best_net_edge, best_reason = _select_best_side(yes_breakdown, no_breakdown)
    # Best-side executable economics snapshot: the single line that separates
    # "no positive edge exists" from "edge exists but the reserve ate it".
    if best_side is not None:
        _best_min_edge = yes_min_edge if best_side == "yes" else no_min_edge
        _best_ev_c = float(best_net_edge) * 100.0
        _best_thr_c = float(_best_min_edge) * 100.0
        indicators["best_executable_side"] = best_side
        indicators["best_executable_ev_cents"] = _best_ev_c
        indicators["best_required_edge_cents"] = _best_thr_c
        indicators["edge_shortfall_cents"] = max(0.0, _best_thr_c - _best_ev_c)
    if selected_side_pre_edge is None and best_side is not None:
        selected_side_pre_edge = best_side
    if selection_reason == "best_executable_edge" and best_reason:
        selection_reason = best_reason

    # Confidence must be valid before any trade can be emitted.
    confidence_result = _compute_confidence(
        data_quality=data_quality,
        regime=regime,
        settlement_reference=settlement_reference,
        seconds_to_expiry=seconds_to_expiry,
        yes_bid_cents=yes_bid_cents,
        yes_ask_cents=yes_ask_cents,
        no_bid_cents=no_bid_cents,
        no_ask_cents=no_ask_cents,
        yes_depth_cc=yes_depth_cc,
        no_depth_cc=no_depth_cc,
        model_uncertainty=model_uncertainty,
        rti_age_ms=rti_age_ms,
        quote_age_ms=quote_age_ms,
        rti_book_skew_ms=rti_book_skew_ms,
        book_sequence_confirmed=book_sequence_confirmed,
        book_initialized=book_initialized,
        cfb_execution_eligible=cfb_execution_eligible,
        settlement_lane=settlement_lane,
        entry_price_basis=entry_price_basis,
    )

    # Selection: prefer the side with the higher *qualifying* net edge.
    # A side qualifies only when its model probability clears the side-aware
    # positive-EV floor (entry + all-in cost reserve) and its net edge clears
    # the threshold.  Ties are no-trade.
    selected_outcome: Optional[Literal["yes", "no"]] = None
    selected_action: Optional[Literal["buy"]] = None
    no_trade_reason: Optional[str] = None
    approved_size_cc = Decimal("0")
    edge_breakdown: Optional[EdgeBreakdown] = None
    p_selected: Optional[Decimal] = None
    p_opposite: Optional[Decimal] = None
    selected_outcome_price: Optional[Decimal] = None
    gross_edge: Optional[Decimal] = None
    net_edge: Optional[Decimal] = None

    yes_min_p = _min_p_for_side(yes_breakdown, min_p_selected)
    no_min_p = _min_p_for_side(no_breakdown, min_p_selected)

    # 2026-10-01 (post_drawdown epoch): directional-regime, conviction,
    # book-flow, countertrend cold-start and same-side throttle gates.
    # All five are evaluated unconditionally so every gate's verdict is
    # stamped on the decision even when economics own the terminal reason.
    from merid.prediction import directional_regime as _dr

    _dir_reg = directional_regime
    indicators["policy_epoch"] = _dr.POLICY_EPOCH
    if _dir_reg is not None:
        indicators["dir_regime"] = _dir_reg.label
        indicators["dir_regime_score"] = _dir_reg.score
        indicators["breadth60_pos"] = _dir_reg.breadth60_pos
        indicators["breadth60_total"] = _dir_reg.breadth60_total
        indicators["btc_r60"] = _dir_reg.btc_r60

    # CAUTION tier: a post-release same-side loss tightens the edge floor
    # rather than blocking the lane (graded state machine replaces the old
    # one-loss -> manual-review relock).  The margin is added to the side's
    # effective min edge so downstream threshold fields record what was
    # actually enforced.
    _yes_caution_c = _dr.side_caution_margin_cents("yes", now.timestamp())
    _no_caution_c = _dr.side_caution_margin_cents("no", now.timestamp())
    if _yes_caution_c > 0.0:
        yes_min_edge = float(yes_min_edge) + _yes_caution_c / 100.0
    if _no_caution_c > 0.0:
        no_min_edge = float(no_min_edge) + _no_caution_c / 100.0
    # Re-stamp: the indicator set earlier predates the CAUTION bump.
    indicators["yes_min_edge"] = yes_min_edge
    indicators["no_min_edge"] = no_min_edge
    indicators["yes_caution_ev_margin_cents"] = _yes_caution_c
    indicators["no_caution_ev_margin_cents"] = _no_caution_c
    indicators["yes_lane_state"] = _dr.side_lane_state("yes", now.timestamp(), asset=asset)
    indicators["no_lane_state"] = _dr.side_lane_state("no", now.timestamp(), asset=asset)

    # Trend-aligned high-price YES lane (91-94c): armed only via
    # MERID_TREND_YES_HI_ENABLED.  ``_yes_hi_price`` is flag-independent —
    # while the price sits in the lane window the *normal* qualify path is
    # disabled, so a >90c candidate can never ride ordinary gates through an
    # admission path that skipped the upstream band filter.
    _yes_hi_price = _dr.trend_yes_hi_band_match(yes_price_cents)
    _yes_trend_hi_block = _dr.trend_yes_hi_block(
        asset=asset,
        yes_price_cents=float(yes_price_cents) if yes_price_cents else None,
        p_yes_cal=float(yes_breakdown.p_selected),
        net_ev_cents=float(yes_breakdown.net_edge) * 100.0,
        tte_seconds=(
            float(seconds_to_expiry) if seconds_to_expiry is not None else None
        ),
        regime=_dir_reg,
        feature_snapshot=feature_snapshot,
    )
    _yes_trend_hi_qualifies = (
        _yes_hi_price
        and _dr.trend_yes_hi_enabled()
        and _yes_trend_hi_block is None
    )

    _yes_regime_block = _dr.regime_entry_block(_dir_reg, "yes", z)
    _no_regime_block = _dr.regime_entry_block(_dir_reg, "no", z)
    _yes_conv_block = _dr.conviction_block_reason(asset, float(yes_breakdown.p_selected))
    _no_conv_block = _dr.conviction_block_reason(asset, float(no_breakdown.p_selected))
    _yes_throttle_block = _dr.side_throttle_block("yes", now.timestamp(), asset=asset) or _dr.strip_concentration_block(
        "yes", float(yes_breakdown.net_edge) * 100.0, ts=now.timestamp()
    )
    _no_throttle_block = _dr.side_throttle_block("no", now.timestamp(), asset=asset) or _dr.strip_concentration_block(
        "no", float(no_breakdown.net_edge) * 100.0, ts=now.timestamp()
    )
    _yes_ct_lane_block = _dr.countertrend_lane_block(asset, "yes", _dir_reg)
    _no_ct_lane_block = _dr.countertrend_lane_block(asset, "no", _dir_reg)
    # 2026-10-04: the book-flow confirmation gate exists to protect RESTING
    # (passive) entries from being picked off into adverse flow — an IOC
    # taker pays the ask once and never rests in the book, so the veto does
    # not apply to taker evaluations.  Counterfactual evidence agrees:
    # bookflow_* vetoes blocked 134 winners vs 74 losers at imb>=0.20.
    _bookflow_applies = route != "taker"
    _yes_bookflow_block = (
        _dr.bookflow_block_reason(feature_snapshot, asset, "yes")
        if _bookflow_applies else None
    )
    _no_bookflow_block = (
        _dr.bookflow_block_reason(feature_snapshot, asset, "no")
        if _bookflow_applies else None
    )
    # 91-94c YES window: the lane's strict-gate failure (armed) or the
    # reserved-window price with the lane off both own the terminal reason.
    _yes_lane_terminal = (
        _yes_trend_hi_block
        or (
            "trend_yes_hi_disabled"
            if (_yes_hi_price and not _dr.trend_yes_hi_enabled())
            else None
        )
    )
    indicators.update({
        "yes_regime_block": _yes_regime_block,
        "no_regime_block": _no_regime_block,
        "yes_conviction_block": _yes_conv_block,
        "no_conviction_block": _no_conv_block,
        "yes_throttle_block": _yes_throttle_block,
        "no_throttle_block": _no_throttle_block,
        "yes_ct_lane_block": _yes_ct_lane_block,
        "no_ct_lane_block": _no_ct_lane_block,
        "yes_bookflow_block": _yes_bookflow_block,
        "no_bookflow_block": _no_bookflow_block,
        "yes_trend_hi_price": _yes_hi_price,
        "yes_trend_hi_block": _yes_trend_hi_block,
        "yes_trend_hi_qualifies": bool(_yes_trend_hi_qualifies),
    })

    # 2026-09-30: side-specific depth eligibility.  A side whose executable
    # book cannot absorb one contract is ineligible on its own; it must not
    # poison the opposite side via the (now both-empty-only) confidence floor.
    yes_depth_ok = yes_depth_cc >= 100.0
    no_depth_ok = no_depth_cc >= 100.0
    # Audit vector: stamp every primitive gate flag so the decision-audit
    # ledger can persist the complete gate evaluation (not just the first
    # live blocker).  Purely additive — no gate reads these keys.
    indicators.update({
        "yes_depth_ok": bool(yes_depth_ok),
        "no_depth_ok": bool(no_depth_ok),
        "yes_evidence_ok": bool(yes_evidence_ok),
        "no_evidence_ok": bool(no_evidence_ok),
        "yes_evidence_reason": locals().get("yes_evidence_reason"),
        "no_evidence_reason": locals().get("no_evidence_reason"),
        "tail_guard_violation_yes": bool(tail_guard_violation_yes),
        "tail_guard_violation_no": bool(tail_guard_violation_no),
        "yes_min_p_selected": float(yes_min_p),
        "no_min_p_selected": float(no_min_p),
    })
    # Two mutually exclusive YES qualification paths: the normal cell/formula
    # gates (inert while the ask sits in the 91-94c hi-price window) and the
    # armed trend-aligned hi-price lane (stricter: confirmed rally, breadth,
    # BTC/asset momentum, p>=0.94, net EV>=3c, TTE 120-300s, no recent adverse
    # m5 in the lane).  Integrity gates — depth, tail guard, evidence,
    # throttle, book-flow — wrap both paths.
    # 2026-10-04: a provisional cell with a NEGATIVE min-EV floor admits
    # shallow-negative-EV candidates as bounded evidence buys (env-bounded
    # by MERID_PROVISIONAL_MIN_EV_FLOOR_C / per-side overrides).  The
    # ``p_selected > cost_basis`` gate is the positive-EV requirement stated
    # a second time — applied unconditionally it makes every negative floor
    # unreachable by construction (~95 floor-clearing rescued candidates
    # vetoed in one run under no_positive_executable_edge).  Inside a
    # negative-floor provisional domain the cell floor is the sole economics
    # gate; depth/tail/evidence/throttle/bookflow/regime/conviction/
    # countertrend and the lane's own caps still apply unchanged.
    _yes_cbp_neg_floor = (
        _yes_edge_thr.provisional_cell_id is not None and yes_min_edge < 0.0
    )
    _no_cbp_neg_floor = (
        _no_edge_thr.provisional_cell_id is not None and no_min_edge < 0.0
    )
    indicators["yes_cbp_neg_floor_p_bypass"] = bool(_yes_cbp_neg_floor)
    indicators["no_cbp_neg_floor_p_bypass"] = bool(_no_cbp_neg_floor)

    # 2026-10-04 (EPC double-count fix): when a validated empirical cell
    # supplied the side's probability, the reserve-stacked net_edge still
    # carries the model's own FLB/uncertainty charges — uncertainty the
    # cell's walk-forward LCB already encodes.  The economics leg accepts
    # max(reserve-stacked edge, price-adjusted empirical LCB): the cell's
    # conservative bound may satisfy the threshold but never clears a bar
    # it doesn't reach.
    def _epc_eff_edge(side: str, bd: EdgeBreakdown) -> float:
        if not indicators.get(f"{side}_epc_applied"):
            return float(bd.net_edge)
        _lcb = indicators.get(f"{side}_epc_adj_lcb_cents")
        if _lcb is None:
            return float(bd.net_edge)
        return max(float(bd.net_edge), float(_lcb) / 100.0)

    _yes_eff_edge = _epc_eff_edge("yes", yes_breakdown)
    _no_eff_edge = _epc_eff_edge("no", no_breakdown)
    indicators["yes_epc_eff_edge_cents"] = _yes_eff_edge * 100.0
    indicators["no_epc_eff_edge_cents"] = _no_eff_edge * 100.0

    # 2026-10-05 (canary): the countertrend regime block is an elevated
    # floor, not a categorical veto, under MERID_COUNTER_REGIME_MODE=penalty.
    # A counter-regime side may qualify only when its effective net edge
    # clears the absolute floor AND the quote owner is not degraded; the
    # ordinary economics bound still applies on top.  Same-direction and
    # deep-ITM sides are unaffected (``regime_entry_block`` returns None).
    _cr_penalty = MERID_COUNTER_REGIME_MODE == "penalty"
    _yes_regime_ok = _yes_regime_block is None or (
        _cr_penalty
        and _yes_eff_edge >= MERID_COUNTER_REGIME_MIN_EDGE
        and not indicators.get("quote_degraded_mode")
    )
    _no_regime_ok = _no_regime_block is None or (
        _cr_penalty
        and _no_eff_edge >= MERID_COUNTER_REGIME_MIN_EDGE
        and not indicators.get("quote_degraded_mode")
    )
    indicators.update({
        "counter_regime_mode": MERID_COUNTER_REGIME_MODE,
        "counter_regime_min_edge_cents": MERID_COUNTER_REGIME_MIN_EDGE * 100.0,
        "yes_counter_regime_admitted": bool(
            _yes_regime_block is not None and _yes_regime_ok
        ),
        "no_counter_regime_admitted": bool(
            _no_regime_block is not None and _no_regime_ok
        ),
    })

    # 2026-10-04: marginal-band rescue slack.  Only positive thresholds in the
    # 50-89c executable band relax; bounded negative-floor lanes keep their own
    # edge bound, and >89c/<50c near-misses are counterfactually unprofitable.
    # Taker-route evaluations only: the counterfactual was measured on ask-price
    # fills; a resting-bid (maker) fill is a different, adverse-selected
    # distribution and must not inherit the slack.
    _mb_on_route = route == "taker"
    # Experiment A: the empirical_marginal_maker route gets its own bounded
    # slack — δ=0.5c, bid-priced (non-marketable) entry, inside the declared
    # 4-10min / 50-89c domain, and denied to evidence-escape-owned sides
    # (an escape override already consumed the side's evidence budget).
    _emm_on_route = route == "empirical_marginal_maker"
    _mb_yes_slack = (
        _marginal_band_slack(float(yes_breakdown.executable_entry_price) * 100.0)
        if (_mb_on_route and yes_min_edge > 0.0)
        else 0.0
    )
    _mb_no_slack = (
        _marginal_band_slack(float(no_breakdown.executable_entry_price) * 100.0)
        if (_mb_on_route and no_min_edge > 0.0)
        else 0.0
    )
    if _emm_on_route:
        if (
            yes_min_edge > 0.0
            and indicators.get("yes_admission_owner") != "evidence_escape"
        ):
            _mb_yes_slack = _marginal_maker_slack(
                float(yes_breakdown.executable_entry_price) * 100.0,
                seconds_to_expiry,
            )
        if (
            no_min_edge > 0.0
            and indicators.get("no_admission_owner") != "evidence_escape"
        ):
            _mb_no_slack = _marginal_maker_slack(
                float(no_breakdown.executable_entry_price) * 100.0,
                seconds_to_expiry,
            )
    _yes_edge_eff_bound = yes_min_edge - _mb_yes_slack
    _no_edge_eff_bound = no_min_edge - _mb_no_slack
    # A "rescued" side is one that would have failed without the slack —
    # stamped so routing can realize the ask-priced fill the counterfactual
    # measured, and so the rescue lane has its own outcome cohort.
    _yes_mb_rescued = (
        _mb_yes_slack > 0.0
        and _yes_eff_edge >= _yes_edge_eff_bound
        and _yes_eff_edge < yes_min_edge
    )
    _no_mb_rescued = (
        _mb_no_slack > 0.0
        and _no_eff_edge >= _no_edge_eff_bound
        and _no_eff_edge < no_min_edge
    )
    if _mb_yes_slack > 0.0 or _mb_no_slack > 0.0:
        indicators["marginal_band"] = {
            "enabled": True,
            "route": route,
            "slack_cents": (
                EMM_SLACK if _emm_on_route else MERID_MARGINAL_BAND_SLACK
            ) * 100.0,
            "yes_slack_cents": _mb_yes_slack * 100.0,
            "no_slack_cents": _mb_no_slack * 100.0,
            "yes_rescued": bool(_yes_mb_rescued),
            "no_rescued": bool(_no_mb_rescued),
        }
    # A rescued side's admission bound IS the slackened threshold — every
    # downstream re-gate (loop lane-EV floor, router stale-decision check)
    # must compare against it, not the un-slackened policy threshold.
    if _yes_mb_rescued:
        indicators["yes_effective_required_edge_cents"] = (
            _yes_edge_eff_bound * 100.0
        )
    if _no_mb_rescued:
        indicators["no_effective_required_edge_cents"] = (
            _no_edge_eff_bound * 100.0
        )

    # 2026-10-05 (post-audit): restamp the enforced edge-bound surface AFTER
    # every mutation is complete.  The decomposition stamps at ~3195 and the
    # best-side stamps at ~3590 predate the CAUTION-margin bump (3664) and the
    # marginal-band slack (3832) — observed live: effective_required_edge=2.0c
    # recorded while 4.0c was actually enforced, so rejects read as
    # "shortfall 0.0" against the true bound.  Fields below are the
    # post-mutation truth the gate applied:
    #   *_route_required_edge_cents   post-caution policy bound for this route
    #   *_effective_gate_edge_cents   the bound actually compared (post-slack)
    #   *_gate_ev_cents               the quantity compared (EPC-LCB adjusted)
    #   *_true_shortfall_cents        max(0, gate_bound - gate_ev)
    for _pfx, _bd, _bnd, _eff in (
        ("yes", yes_breakdown, _yes_edge_eff_bound, _yes_eff_edge),
        ("no", no_breakdown, _no_edge_eff_bound, _no_eff_edge),
    ):
        _min_e = yes_min_edge if _pfx == "yes" else no_min_edge
        _rescued = _yes_mb_rescued if _pfx == "yes" else _no_mb_rescued
        # effective_required_edge is the admission bound downstream re-gates
        # must keep comparing against: slackened iff this side was rescued,
        # else the full post-caution route bound.  The gate-comparison bound
        # (always slack-adjusted) is exposed separately as *_gate_edge.
        indicators[f"{_pfx}_effective_required_edge_cents"] = (
            _bnd if _rescued else _min_e
        ) * 100.0
        indicators[f"{_pfx}_route_required_edge_cents"] = _min_e * 100.0
        indicators[f"{_pfx}_effective_gate_edge_cents"] = _bnd * 100.0
        indicators[f"{_pfx}_gate_ev_cents"] = _eff * 100.0
        indicators[f"{_pfx}_true_shortfall_cents"] = max(
            0.0, (_bnd - _eff) * 100.0
        )
        indicators[f"{_pfx}_fee_reserve_cents"] = float(_bd.entry_fee) * 100.0
        indicators[f"{_pfx}_impact_reserve_cents"] = (
            float(_bd.exit_cost_reserve) * 100.0
        )
        indicators[f"{_pfx}_model_uncertainty_reserve_cents"] = (
            float(_bd.model_risk_reserve) * 100.0
        )
        indicators[f"{_pfx}_adverse_selection_reserve_cents"] = (
            float(_bd.adverse_selection_reserve) * 100.0
        )
    indicators["order_route"] = route
    indicators["entry_price_basis"] = entry_price_basis
    if best_side is not None:
        _gb = _yes_edge_eff_bound if best_side == "yes" else _no_edge_eff_bound
        _ge = _yes_eff_edge if best_side == "yes" else _no_eff_edge
        _gbd = yes_breakdown if best_side == "yes" else no_breakdown
        indicators["best_required_edge_cents"] = _gb * 100.0
        indicators["effective_gate_edge_cents"] = _gb * 100.0
        indicators["edge_shortfall_cents"] = max(0.0, (_gb - _ge) * 100.0)
        indicators["true_shortfall_to_active_requirement_cents"] = indicators[
            "edge_shortfall_cents"
        ]
        _sbid, _sask = (
            (yes_bid_cents, yes_ask_cents)
            if best_side == "yes"
            else (no_bid_cents, no_ask_cents)
        )
        indicators["selected_side_best_bid_cents"] = _sbid
        indicators["selected_side_best_ask_cents"] = _sask
        _entry_px_c = float(_gbd.executable_entry_price) * 100.0
        indicators["order_would_cross"] = bool(
            _sask is not None and _entry_px_c >= float(_sask)
        )
        # Which bound owned this side's requirement — deterministic reject
        # attribution (cell override > caution margin > floor clamp > formula)
        # so a threshold reject never needs reverse-engineering.
        _sel_d = _yes_edge_thr if best_side == "yes" else _no_edge_thr
        _min_e_sel = yes_min_edge if best_side == "yes" else no_min_edge
        _best_rescued = (
            _yes_mb_rescued if best_side == "yes" else _no_mb_rescued
        )
        if _best_rescued:
            _bsrc = (
                "empirical_marginal_maker" if _emm_on_route
                else "marginal_band_rescue"
            )
        elif _sel_d.cell_id is not None:
            _bsrc = "threshold_cell"
        elif _sel_d.provisional_cell_id is not None:
            _bsrc = "provisional_cell"
        elif _min_e_sel > float(_sel_d.total) + 1e-9:
            _bsrc = "caution_margin"
        elif _sel_d.clamped_floor:
            _bsrc = "base_floor"
        else:
            _bsrc = "dynamic_formula"
        indicators["edge_gate_bound_source"] = _bsrc
        if _ge < _gb:
            indicators["reject_reason_code"] = (
                "NO_EDGE_BASE_FLOOR"
                if _bsrc == "base_floor"
                else (
                    "NO_EDGE_CAUTION_MARGIN"
                    if _bsrc == "caution_margin"
                    else "NO_EDGE_DYNAMIC_THRESHOLD"
                )
            )

    yes_qualifies = (
        yes_depth_ok
        and not tail_guard_violation_yes
        and yes_evidence_ok
        and _yes_throttle_block is None
        and _yes_bookflow_block is None
        and (
            _yes_trend_hi_qualifies
            or (
                not _yes_hi_price
                and _yes_eff_edge >= _yes_edge_eff_bound
                and (
                    _yes_cbp_neg_floor
                    or yes_breakdown.p_selected > yes_min_p
                )
                and _yes_regime_ok
                and _yes_conv_block is None
                and _yes_ct_lane_block is None
            )
        )
    )
    no_qualifies = (
        no_depth_ok
        and _no_eff_edge >= _no_edge_eff_bound
        and (
            _no_cbp_neg_floor
            or no_breakdown.p_selected > no_min_p
        )
        and not tail_guard_violation_no
        and no_evidence_ok
        and _no_regime_ok
        and _no_conv_block is None
        and _no_throttle_block is None
        and _no_ct_lane_block is None
        and _no_bookflow_block is None
    )

    # Candidate-surface export: per-side executable economics and the first
    # failing condition per side, so a rejected evaluation is auditable from
    # telemetry alone (no side's state is lost when the other side wins or
    # when both fail).
    def _side_block_reason(
        side: str,
        bd: EdgeBreakdown,
        min_edge_s: float,
        min_p_s: float,
        evidence_ok_s: bool,
        tail_violation_s: bool,
        depth_ok_s: bool = True,
        regime_block_s: Optional[str] = None,
        conv_block_s: Optional[str] = None,
        throttle_block_s: Optional[str] = None,
        ct_lane_block_s: Optional[str] = None,
        bookflow_block_s: Optional[str] = None,
        hi_price_applies_s: bool = False,
        trend_hi_block_s: Optional[str] = None,
        eff_edge_s: Optional[float] = None,
    ) -> Optional[str]:
        _edge_s = float(eff_edge_s) if eff_edge_s is not None else float(bd.net_edge)
        if not depth_ok_s:
            return f"insufficient_depth_{side}"
        if tail_violation_s:
            return f"tail_guard_{side}"
        # 2026-09-30: economics first — a side that never had positive
        # executable EV is an EV rejection, not an evidence-policy block.
        # Evidence only owns the terminal code when the economics cleared.
        # 2026-10-04: a NEGATIVE min_edge means the side lives in a
        # bounded evidence-buying lane — non-positive EV is the domain,
        # not the failure.  The honest labels are edge_below_lane_floor
        # (missed the lane's own bound) and the structural gates; the
        # positive-EV / cost-basis labels only apply on >=0 floors.
        if min_edge_s >= 0.0 and _edge_s <= 0:
            return f"no_positive_executable_edge_{side}"
        if _edge_s < min_edge_s:
            return (
                f"edge_below_lane_floor_{side}"
                if min_edge_s < 0.0
                else f"edge_below_threshold_{side}"
            )
        if min_edge_s >= 0.0 and bd.p_selected <= min_p_s:
            return f"cost_basis_{side}"
        # 91-94c YES window: the lane owns the terminal reason — the strict
        # gate's specific failure when armed, or `trend_yes_hi_disabled` when
        # the price sits in the reserved window with the lane off.
        if hi_price_applies_s:
            if trend_hi_block_s:
                return trend_hi_block_s
            if not _dr.trend_yes_hi_enabled():
                return "trend_yes_hi_disabled"
        # 2026-10-01 (post_drawdown): structural safety gates own the
        # terminal code when the economics cleared — countertrend regime,
        # coin-flip conviction, side-streak suspension, cold-start
        # countertrend lane, and adverse book flow.
        if regime_block_s:
            return regime_block_s
        if conv_block_s:
            return f"{conv_block_s}_{side}"
        if throttle_block_s:
            return throttle_block_s
        if ct_lane_block_s:
            return ct_lane_block_s
        if bookflow_block_s:
            return bookflow_block_s
        if not evidence_ok_s:
            return (
                yes_evidence_reason if side == "yes" else no_evidence_reason
            ) or f"evidence_{side}"
        return None

    indicators.update({
        "yes_bid_cents": yes_bid_cents,
        "yes_ask_cents": yes_ask_cents,
        "no_bid_cents": no_bid_cents,
        "no_ask_cents": no_ask_cents,
        "yes_entry_price_cents": yes_price_cents,
        "no_entry_price_cents": no_price_cents,
        "yes_ev_net_cents": float(yes_breakdown.net_edge) * 100.0,
        "no_ev_net_cents": float(no_breakdown.net_edge) * 100.0,
        "yes_gross_edge_cents": float(yes_breakdown.gross_edge) * 100.0,
        "no_gross_edge_cents": float(no_breakdown.gross_edge) * 100.0,
        "yes_p_selected": float(yes_breakdown.p_selected),
        "no_p_selected": float(no_breakdown.p_selected),
        "yes_min_p_selected": float(yes_min_p),
        "no_min_p_selected": float(no_min_p),
        "yes_qualifies": bool(yes_qualifies),
        "no_qualifies": bool(no_qualifies),
        "yes_block": _side_block_reason(
            "yes", yes_breakdown, yes_min_edge, yes_min_p,
            yes_evidence_ok, tail_guard_violation_yes, yes_depth_ok,
            regime_block_s=_yes_regime_block if not _yes_regime_ok else None,
            conv_block_s=_yes_conv_block,
            throttle_block_s=_yes_throttle_block,
            ct_lane_block_s=_yes_ct_lane_block,
            bookflow_block_s=_yes_bookflow_block,
            hi_price_applies_s=_yes_hi_price,
            trend_hi_block_s=_yes_trend_hi_block,
            eff_edge_s=_yes_eff_edge,
        ),
        "no_block": _side_block_reason(
            "no", no_breakdown, no_min_edge, no_min_p,
            no_evidence_ok, tail_guard_violation_no, no_depth_ok,
            regime_block_s=_no_regime_block if not _no_regime_ok else None,
            conv_block_s=_no_conv_block,
            throttle_block_s=_no_throttle_block,
            ct_lane_block_s=_no_ct_lane_block,
            bookflow_block_s=_no_bookflow_block,
            eff_edge_s=_no_eff_edge,
        ),
    })

    # 2026-10-05 (top-edge IOC canary): a side that failed ONLY the edge
    # bound — every structural gate passed, the executable quote is the
    # WS-verified canonical book — may still be emitted at the reduced
    # canary floor.  Taker route only (IOC at the ask); the grid assigns
    # the bounded ``canary_taker`` lane and the daily submission cap.
    # ``net_edge > 0`` is preserved via the p_selected > cost-basis leg.
    _canary_side: Optional[str] = None
    _canary_edge = 0.0
    _canary_pristine = (
        MERID_CANARY_LANE_ENABLED
        and route == "taker"
        and indicators.get("quote_owner") == "WS_FRESH_VERIFIED"
        and not indicators.get("quote_degraded_mode")
    )
    # Only the best-side edge is canary-eligible — the lane exists for the
    # top-ranked candidate, and the dual-side assertion below requires
    # selected_outcome == best_side.
    if (
        _canary_pristine
        and not yes_qualifies
        and not no_qualifies
        and best_side is not None
    ):
        _cs = best_side
        _ce = _yes_eff_edge if _cs == "yes" else _no_eff_edge
        _cb = _yes_edge_eff_bound if _cs == "yes" else _no_edge_eff_bound
        if _cb >= 0.0 and MERID_CANARY_MIN_EDGE <= _ce < _cb:
            if _cs == "yes":
                _gates_ok = (
                    yes_depth_ok
                    and not tail_guard_violation_yes
                    and yes_evidence_ok
                    and _yes_regime_ok
                    and _yes_conv_block is None
                    and _yes_throttle_block is None
                    and _yes_ct_lane_block is None
                    and _yes_bookflow_block is None
                    and not _yes_hi_price
                    and (
                        _yes_cbp_neg_floor
                        or yes_breakdown.p_selected > yes_min_p
                    )
                )
            else:
                _gates_ok = (
                    no_depth_ok
                    and not tail_guard_violation_no
                    and no_evidence_ok
                    and _no_regime_ok
                    and _no_conv_block is None
                    and _no_throttle_block is None
                    and _no_ct_lane_block is None
                    and _no_bookflow_block is None
                    and (
                        _no_cbp_neg_floor
                        or no_breakdown.p_selected > no_min_p
                    )
                )
            if _gates_ok:
                _canary_side = _cs
                _canary_edge = _ce
        if _canary_side is not None:
            indicators["canary_taker"] = {
                "side": _canary_side,
                "gate_ev_cents": _canary_edge * 100.0,
                "full_bound_cents": (
                    _yes_edge_eff_bound if _canary_side == "yes"
                    else _no_edge_eff_bound
                ) * 100.0,
                "canary_floor_cents": MERID_CANARY_MIN_EDGE * 100.0,
                "quote_owner": indicators.get("quote_owner"),
            }

    if yes_qualifies and no_qualifies:
        # This should not happen because of duality, but handle explicitly.
        if yes_breakdown.net_edge >= no_breakdown.net_edge:
            selected_outcome = "yes"
            edge_breakdown = yes_breakdown
        else:
            selected_outcome = "no"
            edge_breakdown = no_breakdown
    elif yes_qualifies:
        selected_outcome = "yes"
        edge_breakdown = yes_breakdown
    elif no_qualifies:
        selected_outcome = "no"
        edge_breakdown = no_breakdown
    elif _canary_side is not None:
        selected_outcome = _canary_side
        edge_breakdown = (
            yes_breakdown if _canary_side == "yes" else no_breakdown
        )
        indicators["decision_lane"] = "canary_taker"
    else:
        # No side qualifies.  Determine the most informative rejection reason.
        if best_side is None:
            no_trade_reason = "directional_tie"
        else:
            best_threshold = yes_min_edge if best_side == "yes" else no_min_edge
            best_min_p = yes_min_p if best_side == "yes" else no_min_p
            best_evidence_ok = yes_evidence_ok if best_side == "yes" else no_evidence_ok
            # 2026-10-05: label with the same quantities the qualification gate
            # compared (EPC-adjusted edge vs post-slack bound).  The raw
            # reserve-stacked net edge mislabeled EPC-cleared sides (gate EV
            # +4.8c) as no_positive_executable_edge, hiding the real blocker.
            _best_gate_ev = _yes_eff_edge if best_side == "yes" else _no_eff_edge
            _best_gate_bound = (
                _yes_edge_eff_bound if best_side == "yes" else _no_edge_eff_bound
            )
            if _best_gate_ev <= 0 and best_threshold >= 0:
                # 2026-09-30: both legs uneconomic is an EV rejection, not an
                # evidence-policy veto.  Label it honestly so the funnel can
                # separate "no edge right now" from "historically censored".
                # 2026-10-04: a negative floor means the lane admits
                # non-positive EV — the EV-zero label would mask whichever
                # structural gate or lane floor actually vetoed.
                no_trade_reason = "no_positive_executable_edge"
            elif _best_gate_ev < _best_gate_bound:
                if best_threshold < 0:
                    no_trade_reason = f"{best_side}_edge_below_lane_floor"
                elif best_side == "yes":
                    no_trade_reason = "yes_edge_below_threshold"
                else:
                    no_trade_reason = "no_edge_below_threshold"
            elif not (yes_depth_ok if best_side == "yes" else no_depth_ok):
                # Edge and evidence cleared but the held side's book cannot
                # absorb a contract — label it a liquidity rejection.
                no_trade_reason = f"insufficient_depth_{best_side}"
            elif (
                best_threshold >= 0
                and (
                    yes_breakdown.p_selected if best_side == "yes" else no_breakdown.p_selected
                )
                <= best_min_p
            ):
                # p_selected does not clear the side-aware positive-EV floor
                # (entry + all-in cost reserve).  Checked before the
                # structural safety gates to match _side_block_reason's
                # ordering — a below-floor price is the deeper rejection.
                best_p = yes_breakdown.p_selected if best_side == "yes" else no_breakdown.p_selected
                no_trade_reason = f"cost_basis_override_{best_side}"
                indicators[f"cost_basis_override_{best_side}_p"] = best_p
                indicators[f"cost_basis_override_{best_side}_floor"] = best_min_p
            elif (
                # Under counter-regime *penalty* mode a cleared side is not a
                # regime rejection — report the effective block only.
                (_yes_regime_block if best_side == "yes" and not _yes_regime_ok
                 else _no_regime_block if best_side == "no" and not _no_regime_ok
                 else None)
                if best_side is not None else None
            ) or (
                _yes_conv_block if best_side == "yes" else _no_conv_block
            ) or (
                _yes_throttle_block if best_side == "yes" else _no_throttle_block
            ) or (
                _yes_ct_lane_block if best_side == "yes" else _no_ct_lane_block
            ) or (
                _yes_bookflow_block if best_side == "yes" else _no_bookflow_block
            ) or (
                best_side == "yes" and _yes_lane_terminal
            ):
                # 2026-10-01: edge cleared the floor but a structural safety
                # gate owns the rejection — report the gate, not evidence.
                _eff_regime_yes = _yes_regime_block if not _yes_regime_ok else None
                _eff_regime_no = _no_regime_block if not _no_regime_ok else None
                _gate_blocks = (
                    (
                        _eff_regime_yes,
                        _yes_conv_block,
                        _yes_throttle_block,
                        _yes_ct_lane_block,
                        _yes_bookflow_block,
                        _yes_lane_terminal,
                    )
                    if best_side == "yes"
                    else (
                        _eff_regime_no,
                        _no_conv_block,
                        _no_throttle_block,
                        _no_ct_lane_block,
                        _no_bookflow_block,
                        None,
                    )
                )
                _first_gate = next((b for b in _gate_blocks if b), None)
                no_trade_reason = (
                    f"{_first_gate}_{best_side}"
                    if _first_gate == "low_conviction"
                    else _first_gate
                )
            elif not best_evidence_ok:
                # The observed win-rate evidence at this held-side price does
                # not clear price + fee + margin: the cell is unprofitable for
                # our signal population regardless of what the model claims.
                # Prefer the specific reason (live-rolling vs static-artifact).
                no_trade_reason = (
                    yes_evidence_reason if best_side == "yes" else no_evidence_reason
                ) or f"calibration_evidence_{best_side}"
            else:
                # Edge cleared, depth is fine, p clears the cost floor, no
                # structural gate fired, evidence passed — yet the side did
                # not qualify.  Defensive catch-all; should be unreachable.
                no_trade_reason = "no_qualifying_side"

            # Counterfactual logging: record the rejected candidate so a
            # post-settlement join can classify saved/missed/flat per bucket.
            _rej_bd = yes_breakdown if best_side == "yes" else no_breakdown
            log_rejected_candidate(
                reason=no_trade_reason,
                run_id=run_id,
                decision_id=decision_id,
                asset=asset,
                ticker=ticker,
                side=best_side,
                model_p_selected=float(_rej_bd.p_selected),
                held_price_cents=float(_rej_bd.executable_entry_price) * 100.0,
                gross_edge=float(_rej_bd.gross_edge),
                net_edge=float(_rej_bd.net_edge),
                edge_threshold=float(best_threshold),
                min_p_selected=float(best_min_p),
                tte_seconds=float(seconds_to_expiry),
                spot_price=float(spot_price),
                strike_price=float(strike_price),
                fee_cents=float(fee) * 100.0,
                route=route,
                depth_for_quantity_cc=float(
                    yes_depth_cc if best_side == "yes" else no_depth_cc
                ),
                risk_reserve_cents=float(_rej_bd.model_risk_reserve) * 100.0,
                exit_cost_reserve_cents=float(_rej_bd.exit_cost_reserve) * 100.0,
                adverse_selection_reserve_cents=float(_rej_bd.adverse_selection_reserve) * 100.0,
            )

    # 2026-09-27: Market-lean fade gate.  Reject entries that trade AGAINST a
    # meaningful market lean on assets whose historical fade cohort is
    # toxic.  See the cohort table next to MERID_FADE_BLOCK_MIN_LEAN_CENTS.
    if selected_outcome is not None:
        _mkt_mid = (float(yes_bid_cents) + float(yes_ask_cents)) / 200.0
        _mkt_lean_c = (_mkt_mid - 0.5) * 100.0
        indicators["market_lean_cents"] = _mkt_lean_c
        _fade = (
            (selected_outcome == "yes" and _mkt_lean_c < -MERID_FADE_BLOCK_MIN_LEAN_CENTS)
            or (selected_outcome == "no" and _mkt_lean_c > MERID_FADE_BLOCK_MIN_LEAN_CENTS)
        )
        if _fade:
            indicators["fade_gate_evaluated"] = True
            if asset.upper() in MERID_FADE_ALLOWED_ASSETS:
                indicators["fade_gate_outcome"] = "allowed_by_cohort"
            else:
                logger.info(
                    "[TRADE-DECISION] asset=%s ticker=%s FADE GATE blocked %s entry: "
                    "market lean %.1fc opposes trade side (historical fade cohort toxic)",
                    asset, ticker, selected_outcome.upper(), _mkt_lean_c,
                )
                no_trade_reason = f"market_fade_blocked_{selected_outcome}"
                log_rejected_candidate(
                    reason=no_trade_reason,
                    run_id=run_id,
                    decision_id=decision_id,
                    asset=asset,
                    ticker=ticker,
                    side=selected_outcome,
                    model_p_selected=float(edge_breakdown.p_selected),
                    held_price_cents=float(edge_breakdown.executable_entry_price) * 100.0,
                    gross_edge=float(edge_breakdown.gross_edge),
                    net_edge=float(edge_breakdown.net_edge),
                    edge_threshold=float(yes_min_edge if selected_outcome == "yes" else no_min_edge),
                    min_p_selected=float(yes_min_p if selected_outcome == "yes" else no_min_p),
                    tte_seconds=float(seconds_to_expiry),
                    spot_price=float(spot_price),
                    strike_price=float(strike_price),
                    fee_cents=float(fee) * 100.0,
                    route=route,
                    depth_for_quantity_cc=float(
                        yes_depth_cc if selected_outcome == "yes" else no_depth_cc
                    ),
                    risk_reserve_cents=float(edge_breakdown.model_risk_reserve) * 100.0,
                    exit_cost_reserve_cents=float(edge_breakdown.exit_cost_reserve) * 100.0,
                    adverse_selection_reserve_cents=float(edge_breakdown.adverse_selection_reserve) * 100.0,
                )
                selected_outcome = None
                edge_breakdown = None

    if selected_outcome is not None:
        selected_action = "buy"
        # 2026-08-29: Use the resolved live-config per-order contract cap as the
        # default approved size.  In canary mode this is one contract (100 cc).
        _max_contracts = _get_resolved_max_contracts()
        approved_size_cc = Decimal(str(_max_contracts * 100))
        p_selected = Decimal(str(edge_breakdown.p_selected))
        p_opposite = Decimal(str(edge_breakdown.p_opposite))
        selected_outcome_price = Decimal(str(edge_breakdown.executable_entry_price))
        gross_edge = Decimal(str(edge_breakdown.gross_edge))
        net_edge = Decimal(str(edge_breakdown.net_edge))

        # The probability hurdle is an algebraic view of the same final
        # net-edge policy. It must not be a second independent veto.
        _required_edge = yes_min_edge if selected_outcome == "yes" else no_min_edge
        _entry_cost_stack = entry_cost_stack_from_breakdown(edge_breakdown, _required_edge)
        _pi_star = _entry_cost_stack.pi_star
        _net_edge_before_required = _entry_cost_stack.net_edge_before_required(
            edge_breakdown.p_selected
        )
        _net_edge_after_required = _entry_cost_stack.net_edge_after_required(
            edge_breakdown.p_selected
        )
        indicators.update({
            "pi_star": _pi_star,
            "net_edge_before_required": _net_edge_before_required,
            "net_edge_after_required": _net_edge_after_required,
            "pi_star_identity_difference": (
                _net_edge_after_required
                - (edge_breakdown.net_edge - _required_edge)
            ),
            "entry_cost_stack": {
                "executable_price_prob": _entry_cost_stack.executable_price_prob,
                "venue_fee_prob": _entry_cost_stack.venue_fee_prob,
                "spread_slippage_prob": _entry_cost_stack.spread_slippage_prob,
                "model_uncertainty_prob": _entry_cost_stack.model_uncertainty_prob,
                "required_net_edge_prob": _entry_cost_stack.required_net_edge_prob,
            },
        })
        logger.info(
            "[ENTRY-ECONOMICS] asset=%s ticker=%s side=%s best_ask_cents=%.4f "
            "model_prob=%0.4f pi_star=%0.4f net_edge_before_required=%0.4f "
            "net_edge_after_required=%0.4f identity_difference=%0.8f "
            "raw_economics=POSITIVE terminal_decision=PENDING",
            asset,
            ticker,
            selected_outcome.upper(),
            _entry_cost_stack.executable_price_prob * 100.0,
            edge_breakdown.p_selected,
            _pi_star,
            _net_edge_before_required,
            _net_edge_after_required,
            _net_edge_after_required - (edge_breakdown.net_edge - _required_edge),
        )

    if selected_outcome is not None:
        # 2026-08-28: Held-side entry price floor.  Cheap-tail contracts have a
        # near-zero realized win rate; we block entries below 35c unless the
        # model is extremely confident (p_selected >= MERID_CHEAP_TAIL_P_EXCEPTION).
        min_held_price_dollars = min_held_price_cents / 100.0
        held_price = float(selected_outcome_price)
        if (
            held_price < min_held_price_dollars
            and edge_breakdown.p_selected < MERID_CHEAP_TAIL_P_EXCEPTION - 1e-9
        ):
            _floor_p = edge_breakdown.p_selected
            _held_price_cents = round(held_price * 100.0, 6)
            _shadow_low_price = (
                MERID_SHADOW_MIN_HELD_PRICE_CENTS
                <= _held_price_cents
                <= MERID_SHADOW_LOW_PRICE_MAX_CENTS
            )
            _shadow_min_edge = (
                MERID_SHADOW_MIN_NET_EDGE
                if _shadow_low_price
                else MERID_SHADOW_DEFAULT_MIN_NET_EDGE
            )
            _shadow_uncertainty = (
                edge_breakdown.model_risk_reserve
                * MERID_SHADOW_UNCERTAINTY_MULTIPLIER
            )
            _shadow_required_edge = _shadow_min_edge + max(
                0.0,
                _shadow_uncertainty - edge_breakdown.model_risk_reserve,
            )
            _shadow_rules = [
                {
                    "rule": "shadow_min_entry_price",
                    "passed": _held_price_cents >= MERID_SHADOW_MIN_HELD_PRICE_CENTS,
                    "value": _held_price_cents,
                    "threshold": MERID_SHADOW_MIN_HELD_PRICE_CENTS,
                },
                {
                    "rule": "shadow_required_net_edge",
                    "passed": edge_breakdown.net_edge >= _shadow_required_edge,
                    "value": edge_breakdown.net_edge,
                    "threshold": _shadow_required_edge,
                },
            ]
            _shadow_passed = all(rule["passed"] for rule in _shadow_rules)
            indicators["shadow_policy"] = {
                "mode": MERID_ENTRY_POLICY_MODE,
                "decision": "ACCEPT" if _shadow_passed else "REJECT",
                "terminal_reason": None
                if _shadow_passed
                else next(
                    rule["rule"]
                    for rule in _shadow_rules
                    if not rule["passed"]
                ),
                "side": selected_outcome,
                "price_cents": _held_price_cents,
                "model_probability": _floor_p,
                "net_edge": edge_breakdown.net_edge,
                "uncertainty_reserve": _shadow_uncertainty,
                "required_net_edge": _shadow_required_edge,
                "rules": _shadow_rules,
            }
            indicators["terminal_decision"] = "REJECT"
            indicators["terminal_reason"] = (
                f"held_entry_price_below_floor:{held_price:.2f}<"
                f"{min_held_price_cents / 100.0:.2f}"
            )
            _canary_allowed = (
                MERID_ENTRY_POLICY_MODE == "canary"
                and asset.upper() in MERID_LOW_PRICE_CANARY_ASSETS
                and selected_outcome in MERID_LOW_PRICE_CANARY_SIDES
                and _shadow_low_price
                and _shadow_passed
            )
            if _canary_allowed:
                approved_size_cc = min(approved_size_cc, Decimal("100"))
                indicators["canary_policy"] = {
                    "version": "low_price_v1",
                    "decision": "ACCEPT",
                    "asset_allowlisted": True,
                    "side_allowlisted": True,
                    "max_contracts_per_order": 1,
                    "price_cents": _held_price_cents,
                }
                indicators["terminal_decision"] = "PENDING_DOWNSTREAM_GATES"
                indicators["terminal_reason"] = "low_price_canary_shadow_accept"
                logger.warning(
                    "[ENTRY-POLICY-CANARY] asset=%s ticker=%s side=%s price_cents=%.2f "
                    "contracts=1 decision=ACCEPT downstream_gates=pending",
                    asset,
                    ticker,
                    selected_outcome.upper(),
                    _held_price_cents,
                )
            else:
                log_rejected_candidate(
                    reason=f"held_entry_price_below_floor:{held_price:.2f}<{min_held_price_cents/100.0:.2f}|p={_floor_p:.3f}",
                    run_id=run_id,
                    decision_id=decision_id,
                    asset=asset,
                    ticker=ticker,
                    side=selected_outcome,
                    model_p_selected=float(_floor_p),
                    held_price_cents=held_price * 100.0,
                    gross_edge=float(edge_breakdown.gross_edge),
                    net_edge=float(edge_breakdown.net_edge),
                    edge_threshold=float(yes_min_edge if selected_outcome == "yes" else no_min_edge),
                    tte_seconds=float(seconds_to_expiry),
                    spot_price=float(spot_price),
                    strike_price=float(strike_price),
                    fee_cents=float(fee) * 100.0,
                    route=route,
                    depth_for_quantity_cc=float(
                        yes_depth_cc if selected_outcome == "yes" else no_depth_cc
                    ),
                    risk_reserve_cents=float(edge_breakdown.model_risk_reserve) * 100.0,
                    exit_cost_reserve_cents=float(edge_breakdown.exit_cost_reserve) * 100.0,
                    adverse_selection_reserve_cents=float(edge_breakdown.adverse_selection_reserve) * 100.0,
                )
                logger.info(
                    "[ENTRY-POLICY-SHADOW] asset=%s ticker=%s side=%s price_cents=%.2f "
                    "decision=%s terminal_reason=%s net_edge=%.4f required_net_edge=%.4f",
                    asset,
                    ticker,
                    selected_outcome.upper(),
                    _held_price_cents,
                    indicators["shadow_policy"]["decision"],
                    indicators["shadow_policy"]["terminal_reason"],
                    edge_breakdown.net_edge,
                    _shadow_required_edge,
                )
                selected_outcome = None
                selected_action = None
                approved_size_cc = Decimal("0")
                p_selected = None
                p_opposite = None
                selected_outcome_price = None
                gross_edge = None
                net_edge = None
                edge_breakdown = None
                no_trade_reason = (
                    f"held_entry_price_below_floor:{held_price:.2f}<"
                    f"{min_held_price_cents/100.0:.2f}|p={_floor_p:.3f}"
                )

    # Final confidence gate: even if a side qualifies, an invalid confidence
    # blocks the trade.  This is the hard no-trade rule for missing/fallback
    # confidence.
    if selected_outcome is not None and not confidence_result.valid:
        selected_outcome = None
        selected_action = None
        approved_size_cc = Decimal("0")
        p_selected = None
        p_opposite = None
        selected_outcome_price = None
        gross_edge = None
        net_edge = None
        edge_breakdown = None
        no_trade_reason = "invalid_confidence"

    # 2026-09-23: settlement-lane price cap.  Buying a near-certain outcome at
    # > MERID_SETTLEMENT_LANE_MAX_PRICE_CENTS leaves no room for the entry fee,
    # let alone edge — the fee curve collapses to zero only below ~97c.
    if (
        settlement_lane
        and selected_outcome is not None
        and selected_outcome_price is not None
        and float(selected_outcome_price) * 100.0 > MERID_SETTLEMENT_LANE_MAX_PRICE_CENTS
    ):
        selected_outcome = None
        selected_action = None
        approved_size_cc = Decimal("0")
        p_selected = None
        p_opposite = None
        selected_outcome_price = None
        gross_edge = None
        net_edge = None
        edge_breakdown = None
        no_trade_reason = "settlement_lane_price_cap"

    # 2026-08-29: Executable-cost EV gate.  This is the final entry authority.
    # It is evaluated with the executable price, not the midpoint, and it
    # enforces a minimum dollar EV and a minimum EV/tail-risk ratio.  When it
    # rejects, the selected side is cleared and ``no_trade_reason`` is set to
    # the gate's reason.  The old edge-% and π* outputs remain in the decision
    # record as telemetry.
    ev_gate_allowed = False
    ev_gate_result: Optional[Dict[str, Any]] = None
    # 2026-10-01: adverse-selection reserve is now measured, not hardcoded.
    # Post-only fills are picked off when the market moves through them —
    # the provisional lane's rolling 5s markouts are the realized cost for
    # this (asset, side, price, tte) bucket, floored so cold cells still
    # carry a prior.  Charged inside the authoritative EV gate; also stamped
    # on the decision so the audit side_ev rows record it.
    adverse_selection_reserve = Decimal("0")
    if (
        selected_outcome is not None
        and selected_outcome_price is not None
        and seconds_to_expiry is not None
    ):
        try:
            from merid.prediction import (
                current_build_provisional as _cbp_asr,
            )
            _asr_cents = _cbp_asr.adverse_selection_reserve_cents(
                asset,
                selected_outcome,
                float(selected_outcome_price) * 100.0,
                float(seconds_to_expiry),
                regime_label=getattr(directional_regime, "label", None),
            )
            adverse_selection_reserve = (
                Decimal(str(_asr_cents)) / Decimal("100")
            )
        except Exception:
            adverse_selection_reserve = Decimal("0")
    uncertainty_reserve = Decimal(str(model_risk_reserve))

    if selected_outcome is not None:
        from merid.risk.executable_cost_ev_gate import evaluate_executable_cost_ev, EVInput

        entry_fee = (
            Decimal(str(yes_breakdown.entry_fee))
            if selected_outcome == "yes"
            else Decimal(str(no_breakdown.entry_fee))
        )
        exit_cost = (
            Decimal(str(yes_breakdown.exit_cost_reserve))
            if selected_outcome == "yes"
            else Decimal(str(no_breakdown.exit_cost_reserve))
        )

        # Bounded-lane floors: provisional cells may carry a configured
        # negative EV floor (evidence-buying lanes).  The gate defaults to
        # min_dollar_ev=0.0, which would veto every candidate those lanes
        # exist to admit, so the selected side's floor is passed through
        # when it is negative.  Positive thresholds keep the gate's
        # canonical "> 0 net EV" sanity check — the qualification layer
        # already enforced the side's positive threshold.
        _side_min_edge = (
            yes_min_edge if selected_outcome == "yes" else no_min_edge
        )
        _ev_gate_min_dollar = (
            Decimal(str(_side_min_edge)) if float(_side_min_edge) < 0.0 else None
        )
        # A negative dollar floor makes the EV/tail ratio check vacuous —
        # the ratio is negative for every candidate the lane exists to
        # admit, and the dollar floor already bounds the spend.
        _ev_gate_min_ratio = (
            Decimal("-1") if _ev_gate_min_dollar is not None else None
        )
        ev_input = EVInput(
            p_model=p_selected,
            p_exec=selected_outcome_price,
            qty_cc=int(approved_size_cc),
            entry_fee_per_contract=entry_fee,
            expected_exit_cost_per_contract=exit_cost,
            adverse_selection_reserve_per_contract=adverse_selection_reserve,
            uncertainty_reserve_per_contract=uncertainty_reserve,
            quote_age_ms=quote_age_ms,
            ticker=ticker,
            decision_id=decision_id,
            min_dollar_ev=_ev_gate_min_dollar,
            min_ev_to_tail_ratio=_ev_gate_min_ratio,
        )
        ev_result = evaluate_executable_cost_ev(ev_input)
        ev_gate_allowed = ev_result.allowed
        ev_gate_result = ev_result.to_dict()

        if MERID_EV_GATE_AUTHORITATIVE and not ev_result.allowed:
            selected_outcome = None
            selected_action = None
            approved_size_cc = Decimal("0")
            p_selected = None
            p_opposite = None
            selected_outcome_price = None
            gross_edge = None
            net_edge = None
            edge_breakdown = None
            no_trade_reason = ev_result.reasons[0] if ev_result.reasons else "ev_gate_rejected"

    # CRITICAL FIX (2026-08-27): Fail fast on dual-side contradiction.
    # The consumed side must equal the dual-side evaluator's output whenever
    # both are non-None.  A mismatch means the candidate generator would use the
    # wrong side.
    if selected_outcome is not None and best_side is not None:
        assert selected_outcome == best_side, (
            f"DUAL-SIDE-CONTRADICTION: selected_outcome={selected_outcome} "
            f"best_side={best_side} decision_id={decision_id}"
        )

    # Use the selected side's dynamic threshold for telemetry; fall back to the
    # global floor when no side was selected.
    if selected_outcome == "yes" or (selected_outcome is None and best_side == "yes"):
        selected_threshold = yes_min_edge
    elif selected_outcome == "no" or (selected_outcome is None and best_side == "no"):
        selected_threshold = no_min_edge
    else:
        selected_threshold = min_required_edge

    # Calibrated p_yes/p_no are now side-specific.  Export the selected side's
    # probabilities; for no-trade telemetry use the best-side (most plausible)
    # pair so p_yes_calibrated reflects the tail cap on a cheap YES candidate.
    if selected_outcome == "yes" or best_side == "yes":
        p_yes_calibrated = p_yes_for_yes
        p_no_calibrated = p_no_for_yes
    elif selected_outcome == "no" or best_side == "no":
        p_yes_calibrated = p_yes_for_no
        p_no_calibrated = p_no_for_no
    else:
        p_yes_calibrated = max(0.05, min(0.95, float(p_yes_raw)))
        p_no_calibrated = 1.0 - p_yes_calibrated

    # Lane precedence (2026-09-30): a qualified threshold cell owns its
    # candidate end-to-end — the generic evidence escape lane (and its
    # shared daily budget) applies only to non-cell candidates.  A
    # cell-matched selection is stamped ``threshold_cell`` first; the escape
    # stamp is considered only when no cell matched the selected side.
    if selected_outcome is not None:
        # Trend-aligned hi-price YES lane owns its region (91-94c): measured
        # separately so it cannot contaminate ordinary YES cell evidence.
        if (
            selected_outcome == "yes"
            and _yes_trend_hi_qualifies
            and not indicators.get("decision_lane")
        ):
            indicators["decision_lane"] = "trend_yes_hi"
        _sel_thr = _yes_edge_thr if selected_outcome == "yes" else _no_edge_thr
        if _sel_thr.cell_id is not None and not indicators.get("decision_lane"):
            indicators["decision_lane"] = "threshold_cell"
            indicators["threshold_cell_id"] = _sel_thr.cell_id
            indicators["threshold_cell_min_ev_cents"] = _sel_thr.cell_min_ev_cents
        elif (
            _sel_thr.provisional_cell_id is not None
            and not indicators.get("decision_lane")
        ):
            # Current-build dual-side provisional lane: stamps only when it
            # actually admitted (caps/state checked during decomposition) —
            # an unregistered region with no provisional admission falls
            # through to the formula lane.
            indicators["decision_lane"] = "current_build_provisional"
            indicators["provisional_cell_id"] = _sel_thr.provisional_cell_id
            indicators["provisional_cell_min_ev_cents"] = (
                _sel_thr.provisional_min_ev_cents
            )

        # Generic evidence escape lane: a pass resting on sparse/pooled cell
        # evidence is admissible only as a bounded post-only canary entry —
        # and only for candidates owned by no cell lane.  A provisional
        # cell (or a cap-blocked one) owns its region's evidence treatment,
        # so the shared escape budget must not double-dip it.
        _sel_ev = indicators.get(f"evidence_{selected_outcome}") or {}
        if (
            isinstance(_sel_ev, dict)
            and _sel_ev.get("allowed")
            and _sel_ev.get("escape_required")
            and not indicators.get("decision_lane")
            and _sel_thr.provisional_cell_id is None
            and not _sel_thr.provisional_cap_exhausted
        ):
            indicators["decision_lane"] = "evidence_cell_escape"

        # 2026-10-02: a bid-priced (queue-maker) decision is its own lane —
        # it was admitted on resting economics the ask-priced passes never
        # evaluated, so it must carry the bounded post-only contract.  Cell
        # ids are kept as secondary indicators for research joins.  The
        # empirical_marginal_maker route gets its own lane id so its cohort
        # (bounded δ-slack admissions) stays separable from full-bound
        # maker_bid fills in the outcome joins.
        if entry_price_basis == "bid":
            indicators["decision_lane"] = (
                "empirical_marginal_maker"
                if route == "empirical_marginal_maker"
                else "maker_bid"
            )

        if _sel_thr.cell_id is not None:
            indicators["threshold_cell_id"] = _sel_thr.cell_id
            indicators["threshold_cell_min_ev_cents"] = _sel_thr.cell_min_ev_cents
        if _sel_thr.provisional_cell_id is not None:
            indicators["provisional_cell_id"] = _sel_thr.provisional_cell_id
            indicators["provisional_cell_min_ev_cents"] = (
                _sel_thr.provisional_min_ev_cents
            )
            _sel_pcell = _cbp.provisional_cell_for_id(
                _sel_thr.provisional_cell_id
            )
            if _sel_pcell is not None:
                indicators["provisional_price_bucket"] = _cbp.price_band_label(
                    _sel_pcell
                )
                indicators["provisional_tte_bucket"] = _cbp.tte_band_label(
                    _sel_pcell
                )

        # Top-level admission owner mirrors the selected side's per-side
        # fields (set in the evidence gate above) for audit readability.
        for _f in ("admission_owner", "admission_decision", "admission_reason"):
            _v = indicators.get(f"{selected_outcome}_{_f}")
            if _v is not None:
                indicators[_f] = _v

        # Marginal-band rescue: the selected side cleared the edge leg only
        # through the 50-89c near-miss slack.  Routing must realize the
        # ask-priced fill the counterfactual measured — a resting bid fill is
        # a different, adverse-selected distribution — so downstream prefers
        # taker/IOC for rescued candidates regardless of maker preference.
        if (selected_outcome == "yes" and _yes_mb_rescued) or (
            selected_outcome == "no" and _no_mb_rescued
        ):
            indicators["marginal_band_rescue"] = True
            if _emm_on_route:
                indicators["empirical_marginal_maker"] = True
            # The admission bound carried downstream (intent.min_required_edge
            # → router stale-decision revalidation; edge_threshold audit field)
            # is the slackened bound the side actually cleared — otherwise
            # every rescued intent dies at submit-time as "edge decayed".
            _sel_slack = (
                _mb_yes_slack if selected_outcome == "yes" else _mb_no_slack
            )
            selected_threshold = selected_threshold - _sel_slack
            indicators["marginal_band_admission_bound_cents"] = (
                float(selected_threshold) * 100.0
            )

    decision = TradeDecision(
        run_id=run_id,
        decision_id=decision_id,
        ticker=ticker,
        asset=asset,
        timestamp_utc=now,
        p_yes_raw=Decimal(str(p_yes_raw)),
        p_yes_calibrated=Decimal(str(p_yes_calibrated)),
        p_yes_uncertainty=Decimal(str(model_risk_reserve)),
        p_no_calibrated=Decimal(str(p_no_calibrated)),
        p_selected=p_selected,
        p_opposite=p_opposite,
        indicators=dict(indicators) if indicators else {},
        regime=regime,
        data_quality=data_quality,
        data_state=_data_state,
        regime_label=_regime_label,
        regime_probability=_regime_probability,
        regime_warmup_samples=regime_warmup_samples,
        seconds_to_expiry=Decimal(str(seconds_to_expiry)),
        settlement_reference=settlement_reference,
        yes_entry_vwap=Decimal(str(yes_entry)),
        no_entry_vwap=Decimal(str(no_entry)),
        yes_depth_cc=Decimal(str(yes_depth_cc)),
        no_depth_cc=Decimal(str(no_depth_cc)),
        fee_yes=Decimal(str(fee)),
        fee_no=Decimal(str(fee)),
        expected_exit_cost_yes=Decimal(str(expected_exit_cost_yes)),
        expected_exit_cost_no=Decimal(str(expected_exit_cost_no)),
        yes_score=Decimal(str(
            yes_score if yes_score is not None else p_yes_calibrated
        )),
        no_score=Decimal(str(
            no_score if no_score is not None else p_no_calibrated
        )),
        yes_vote_count=yes_vote_count,
        no_vote_count=no_vote_count,
        selected_side_pre_edge=selected_side_pre_edge,
        selection_reason=selection_reason,
        yes_net_edge=Decimal(str(yes_breakdown.net_edge)),
        no_net_edge=Decimal(str(no_breakdown.net_edge)),
        best_side=best_side,
        best_net_edge=Decimal(str(best_net_edge)) if best_net_edge is not None else None,
        edge_threshold=Decimal(str(selected_threshold)),
        gross_edge_yes=Decimal(str(yes_breakdown.gross_edge)),
        gross_edge_no=Decimal(str(no_breakdown.gross_edge)),
        net_edge_yes=Decimal(str(yes_breakdown.net_edge)),
        net_edge_no=Decimal(str(no_breakdown.net_edge)),
        entry_fee_yes=Decimal(str(yes_breakdown.entry_fee)),
        entry_fee_no=Decimal(str(no_breakdown.entry_fee)),
        exit_cost_reserve_yes=Decimal(str(yes_breakdown.exit_cost_reserve)),
        exit_cost_reserve_no=Decimal(str(no_breakdown.exit_cost_reserve)),
        model_risk_reserve_yes=Decimal(str(yes_breakdown.model_risk_reserve)),
        model_risk_reserve_no=Decimal(str(no_breakdown.model_risk_reserve)),
        selected_outcome=selected_outcome,
        selected_action=selected_action,
        selected_outcome_price=selected_outcome_price,
        gross_edge=gross_edge,
        net_edge=net_edge,
        no_trade_reason=no_trade_reason,
        edge_breakdown=edge_breakdown,
        yes_edge_breakdown=yes_breakdown,
        no_edge_breakdown=no_breakdown,
        confidence=Decimal(str(confidence_result.value)) if confidence_result.value is not None else None,
        confidence_valid=confidence_result.valid,
        confidence_source=confidence_result.source,
        confidence_reasons=confidence_result.reasons,
        confidence_data_penalty=Decimal(str(confidence_result.data_penalty)),
        confidence_book_penalty=Decimal(str(confidence_result.book_penalty)),
        confidence_model_penalty=Decimal(str(confidence_result.model_penalty)),
        confidence_regime_penalty=Decimal(str(confidence_result.regime_penalty)),
        model_risk_reserve=Decimal(str(model_risk_reserve)),
        min_required_edge=Decimal(str(selected_threshold)),
        approved_size_cc=approved_size_cc,
        policy_version=policy_version,
        adverse_selection_reserve=adverse_selection_reserve,
        uncertainty_reserve=uncertainty_reserve,
        ev_gate_allowed=ev_gate_allowed,
        ev_gate_result=ev_gate_result,
        config_hash=_config_hash,
        build_sha=_build_sha,
    )

    # 4c LCB(EV_net) canary overlay.  When enabled this is the final authority
    # for the canary cohort; it may downgrade a selected side to no-trade and
    # records the shadow-cohort comparison in decision indicators.
    if MERID_CANARY_4C_LCB:
        _vol_source_for_canary = indicators.get("annualized_vol_source", "unknown")
        decision = apply_canary_lcb_gate(
            decision,
            asset=asset,
            annualized_vol_source=_vol_source_for_canary,
            settlement_reference=settlement_reference,
        )

    # Cheap-tail canary overlay (20-34c).  This is the narrow, bounded lane
    # configured by MERID_CHEAP_TAIL_CANARY_* environment variables.  It runs
    # after the 4c LCB overlay and may select a side the core lane rejected.
    if MERID_CHEAP_TAIL_CANARY_ENABLED:
        decision = _apply_cheap_tail_canary_lane(decision, quote_age_ms=quote_age_ms)

    # Bounded live-entry domain: the rollout restricts live admission to
    # TTE <= MERID_LIVE_ENTRY_MAX_TTE_S and, in the >=70c tail, requires the
    # claimed edge to survive the model-risk reserve (LCB).  Selections
    # outside are downgraded to no-trade with a shadow record; measurement
    # and per-side audit rows continue unaffected.
    decision = apply_bounded_live_domain_gate(
        decision,
        yes_threshold=_yes_edge_thr,
        no_threshold=_no_edge_thr,
    )

    record_state_checksum(decision_id, asdict(decision), kind="trade_decision")

    # 2026-08-29: Write the decision-time ledger snapshot before any order is
    # submitted.  The ledger is append-only; subsequent fills/exit events are
    # recorded by the order lifecycle.
    if MERID_ORDER_DECISION_LEDGER_ENABLED:
        from merid.execution.order_decision_ledger import (
            build_order_decision_record_from_trade_decision,
            get_order_decision_ledger,
        )
        try:
            ledger = get_order_decision_ledger()
            record = build_order_decision_record_from_trade_decision(
                decision,
                ev_gate_result=ev_gate_result,
                build_sha=_build_sha,
            )
            ledger.start(record)
        except Exception as exc:
            logger.warning(
                "[TRADE-DECISION] failed to write decision ledger for %s: %s",
                decision_id,
                exc,
            )

    return decision
