"""late_window_trend_favorite research shadow lane (observe-only).

Audits the proposed lane contract inside the live decision path without
changing routing:

    lane:    late_window_trend_favorite
    window:  120s < seconds_to_expiry <= 150s  (activation at 150s,
             re-evaluated on every pass through the entry-eligible period;
             the >120s lower bound deliberately avoids mixing with the
             <=120s passive-path rules and final-minute settlement lane)
    price:   own-side ask strictly > 85c; research band 86-89c flagged
             separately from wider diagnostic bands
    side:    YES and NO evaluated independently, one record per side
    position: signed distance on the purchased side of the verified target
             (settlement reference - strike, sign-mapped per contract side)
    trend:   frozen non-shrinking spec — cushion now vs ~30s ago, flat
             band = +/-0.10 * sigma_remaining_price, crossings over 60s.
             Requires valid volatility: without sigma_rem the flat band is
             undefined and the stage is NOT_EVALUABLE, never "flat".
    basis:   taker economics (executable ask + exact parabolic taker fee
             + late-window reserves), matching late_taker_shadow reserves

Forecast provenance (probability_status):
    COMPUTED_VALID  — engine probability stages ran on complete inputs
                      (ref+strike+vol present AND stage markers present)
    FALLBACK_PRIOR  — probability exists but required inputs were missing;
                      the value may reflect defaults/priors rather than the
                      contemporaneous cushion
    INPUTS_MISSING  — no usable probability and/or inputs absent
    UNKNOWN         — probability exists but provenance markers absent

w7/w8 economics are PASS/FAIL only when the forecast is COMPUTED_VALID;
otherwise NOT_EVALUABLE.  A missing-input probability is never reported as
"the model rejects the ask."

Scoped-exemption semantics: the lane *evaluates and records* at TTE<=180s
where the ordinary engine floor would have rejected — the exemption is
shadow-only.  ``engine_would_reject_tte`` records the floor verdict so the
funnel separates "structurally unavailable" from "economically declined".
Nothing here can submit, replace, or cancel an order; the exemption cannot
affect other lanes because no routing state is touched.

Settlement semantics: ``ref_price`` is the settlement-quantized CF-RTI
value (``settlement_price()``); ``ref_tick`` is the instantaneous
Bachelier tick.  Kalshi's 15m crypto contract settles on the final-minute
average vs the target — the cushion fields are computed on the settlement
reference and the tick-based distance is retained as a diagnostic.  The
endpoint-normal ``q_phi_diagnostic`` is recomputed from THIS record's own
ref/strike/vol inputs — not from the stored model z-score — so the check
verifies inputs, not just internal consistency.

Distance history: per-(ticker, strike) ring buffer of (ts, ref_price).
Keyed by contract identity so a strike change or rollover cannot blend two
contracts' distances.

Writes one JSONL record per (eval, side) to ``logs/lwf_shadow.jsonl`` plus
a periodic ``lwf_shadow_meta`` heartbeat carrying unit-explicit counters
(hook_invocations / invocations_skipped_tte / side_evaluations /
records_written / side_evaluations_deduplicated / evaluation_errors /
write_errors) plus process_id and counters_reset_utc, so a zero-record
window can be reconciled against skips, dedup, and errors instead of being
silently attributed to inputs.  Missing inputs produce an INPUTS_MISSING
record, not an absent record.  Write-only, exception-safe, never
influences order routing.
"""
from __future__ import annotations

import json
import math
import os
import threading
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.lwf_shadow_lane")

_DEFAULT_PATH = os.path.join("logs", "lwf_shadow.jsonl")
_lock = threading.Lock()

_ENABLED = os.environ.get(
    "MERID_LWF_SHADOW_ENABLED", "1"
).strip().lower() in ("1", "true", "yes", "on")

# ---- frozen lane spec -------------------------------------------------------
TTE_HI_S = float(os.environ.get("MERID_LWF_TTE_HI_S", "150"))
TTE_LO_S = float(os.environ.get("MERID_LWF_TTE_LO_S", "120"))  # strictly greater
ASK_MIN_CENTS = float(os.environ.get("MERID_LWF_ASK_MIN_C", "86"))   # "above 85c"
ASK_MAX_CENTS = float(os.environ.get("MERID_LWF_ASK_MAX_C", "99"))
RESEARCH_BAND = (
    float(os.environ.get("MERID_LWF_RESEARCH_LO_C", "86")),
    float(os.environ.get("MERID_LWF_RESEARCH_HI_C", "89")),
)
TREND_LOOKBACK_S = 30.0
TREND_LOOKBACK_TOL_S = 15.0
TREND_FLAT_FRAC = 0.10
CROSS_LOOKBACK_S = 60.0
SECS_PER_YEAR = 365.0 * 86400.0
ADVERSE_SEL_RESERVE = float(os.environ.get("MERID_LWF_ADV_SEL", "0.02"))
MODEL_UNCERTAINTY_RESERVE = float(
    os.environ.get("MERID_LWF_UNC_RESERVE", "0.02")
)
MAX_QUOTE_AGE_MS = float(os.environ.get("MERID_LWF_MAX_QUOTE_AGE_MS", "1000"))
MAX_RTI_AGE_MS = float(os.environ.get("MERID_LWF_MAX_RTI_AGE_MS", "2000"))

# (ticker, strike) -> deque[(ts, ref_price)].  In-process; keyed by contract
# identity so rollover or a strike re-resolution cannot mix two contracts.
_hist: Dict[Tuple[str, float], Deque[Tuple[float, float]]] = {}
_HIST_MAX_S = 900.0
_HIST_MAX_KEYS = 1024

# Invocation accounting with explicit counting units — hook-level counters are
# per log_lwf_shadow() call; side-level counters are per emitted side record.
# Never summed across units.  Invariants:
#   hook_invocations = in_window_invocations + invocations_skipped_tte
#   records_written  = side_evaluations - side_evaluations_deduplicated
#     (when write_errors == 0)
# process_id + counters_reset_utc delimit the accounting period so restarts
# cannot mix windows.
SCHEMA_VERSION = 3
LANE_REVISION = "lwf_shadow_v3_provenance_counters"
_PROCESS_ID = f"pid{os.getpid()}-{int(datetime.now(timezone.utc).timestamp())}"
_COUNTERS_RESET_UTC = datetime.now(timezone.utc).isoformat()
_stats = {
    "hook_invocations": 0,            # calls into log_lwf_shadow (both hooks)
    "invocations_skipped_tte": 0,     # calls out-of-window (early return)
    "side_evaluations": 0,            # per-side records built in-window
    "records_written": 0,             # JSONL lines actually written
    "side_evaluations_deduplicated": 0,  # suppressed duplicate writes
    "evaluation_errors": 0,           # exceptions while building records
    "write_errors": 0,                # exceptions during file write
}
_META_EVERY = 64
# per-asset hook coverage (bounded: 5 assets)
_stats_asset: Dict[str, Dict[str, Any]] = {}
# bounded dedup keys: (decision_id or ticker:path:sec, side)
_seen: "OrderedDict[Tuple[str, str], bool]" = OrderedDict()
_SEEN_MAX = 2048

# decision_reason values that prove the engine completed its probability
# stages (rejected on economics AFTER forecasting).
_PREMODEL_REASONS = frozenset({
    "min_tte_entry_disabled", "confidence_valid", "yes_regime", "no_regime",
    "market_time", "tte_entry_cutoff", "price_band_both_sides_disabled",
    "position_limit",  # held-position early return: engine never ran
})


def _live_rti(asset: str) -> Optional[Any]:
    """Read-only settlement reference fetch for pre-engine eval paths.

    Returns the observation object or None; never fabricates a fallback.
    """
    try:
        from merid.data.cf_rti_adapter import get_live_rti
        return get_live_rti(asset)
    except Exception:
        return None


def _obs_price(obs: Any) -> Tuple[Optional[float], Optional[str], Optional[int]]:
    """(price, source, age_ms) from a CfbRtiObservation, or Nones."""
    if obs is None:
        return None, None, None
    try:
        raw = obs.settlement_price()
        px = float(raw) if raw is not None else None
        src = "cfb_rti_live" if getattr(obs, "execution_eligible", False) else \
            f"cf_rti_not_eligible:{getattr(obs, 'timestamp_quality', None)}"
        age = None
        s_ts, o_ts = getattr(obs, "source_ts_ms", None), getattr(obs, "observed_ts_ms", None)
        if s_ts is not None and o_ts is not None:
            age = max(0, int(o_ts - s_ts))
        return px, src, age
    except Exception:
        return None, None, None


def _feed_history(key: Tuple[str, float], ts: float, ref_price: Optional[float]) -> None:
    if ref_price is None or not math.isfinite(ref_price):
        return
    dq = _hist.get(key)
    if dq is None:
        if len(_hist) >= _HIST_MAX_KEYS:
            for k in list(_hist)[: len(_hist) - _HIST_MAX_KEYS + 1]:
                _hist.pop(k, None)
        dq = _hist[key] = deque(maxlen=2048)
    if dq and ts < dq[-1][0] - 0.25:
        dq.clear()  # clock jump; don't poison trend on out-of-order data
    dq.append((ts, ref_price))
    while dq and ts - dq[0][0] > _HIST_MAX_S:
        dq.popleft()


def _distance_at(dq: Deque[Tuple[float, float]], ts: float, target_age: float,
                 tol: float, strike: float) -> Optional[float]:
    """Signed ref-strike distance nearest to (ts - target_age) within +/-tol."""
    best = None
    best_err = tol
    for t, px in dq:
        err = abs(ts - t - target_age)
        if err <= best_err:
            best_err = err
            best = px - strike
    return best


def _crossings(dq: Deque[Tuple[float, float]], ts: float, lookback: float,
               strike: float) -> int:
    n = 0
    last = 0
    for t, px in dq:
        if t >= ts or ts - t > lookback:
            continue
        d = px - strike
        sg = 1 if d > 0 else (-1 if d < 0 else 0)
        if last and sg and sg != last:
            n += 1
        if sg:
            last = sg
    return n


def _taker_fee_cents(price_frac: float) -> float:
    """Exact Kalshi parabolic taker fee, cents, 1 contract (ceil $0.0001)."""
    p = min(0.99, max(0.01, float(price_frac)))
    return max(0.0, math.ceil(0.07 * p * (1 - p) * 1e4) * 100.0 / 1e4)


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _probability_status(
    *,
    p_cal: Optional[float],
    ref: Optional[float],
    K: Optional[float],
    vol: Optional[float],
    vol_source: Optional[str],
    ind: Dict[str, Any],
    decision_reason: Optional[str],
    decision_lane: Optional[str],
    settlement_state: Dict[str, Any],
) -> Tuple[str, str, List[str], bool]:
    """(status, source, missing_inputs, model_evaluation_completed)."""
    missing = []
    if ref is None:
        missing.append("settlement_reference")
    if K is None:
        missing.append("strike")
    if vol is None:
        missing.append("annualized_vol")
    if vol is not None and vol_source in (None, "", "unknown"):
        missing.append("vol_source")

    side_markers = (
        ind.get("fe_final_p_yes") is not None
        or ind.get("fe_final_p_no_for_no") is not None
        or ind.get("z_score") is not None
        or ind.get("p_yes_raw") is not None
        or ind.get("p_no_raw") is not None
    )
    settle_p = any(
        str(k).startswith("settlement") and isinstance(v, (int, float))
        for k, v in settlement_state.items()
    ) or decision_lane == "settlement_convergence"
    completed = bool(
        side_markers or settle_p
        or (decision_reason and decision_reason not in _PREMODEL_REASONS)
    )

    if p_cal is None:
        status = "INPUTS_MISSING"
    elif missing and not side_markers:
        status = "INPUTS_MISSING"
    elif missing:
        status = "FALLBACK_PRIOR"      # ran, but on incomplete/default inputs
    elif side_markers or settle_p:
        status = "COMPUTED_VALID"
    else:
        status = "UNKNOWN"

    if settle_p:
        source = "settlement_distribution"
    elif side_markers:
        source = "bachelier_pipeline"
    elif p_cal is not None:
        source = "unknown"
    else:
        source = "none"
    return status, source, missing, completed


def log_lwf_shadow(
    *,
    run_id: str,
    decision_id: str,
    asset: str,
    ticker: Optional[str],
    eval_path: str = "post_engine",
    # executable book state at decision time
    yes_bid_cents: float,
    yes_ask_cents: float,
    no_bid_cents: float,
    no_ask_cents: float,
    yes_depth_cc: float,
    no_depth_cc: float,
    # contract + settlement reference
    strike: Optional[float],
    strike_source: Optional[str],
    ref_price: Optional[float],
    ref_source: Optional[str],
    ref_tick: Optional[float],
    rti_age_ms: Optional[float],
    # model / economics (per side, production pipeline output; None when the
    # engine never ran — the record must not invent one)
    p_yes_calibrated: Optional[float],
    p_no_calibrated: Optional[float],
    p_yes_raw: Optional[float],
    p_no_raw: Optional[float],
    net_edge_taker_yes: Optional[float],
    net_edge_taker_no: Optional[float],
    # provenance
    tte_seconds: Optional[float],
    quote_age_ms: Optional[float] = None,
    book_is_executable: Optional[bool] = None,
    annualized_vol: Optional[float] = None,
    vol_source: Optional[str] = None,
    admission_owner_yes: Optional[str] = None,
    admission_owner_no: Optional[str] = None,
    bookflow_block_yes: Optional[str] = None,
    bookflow_block_no: Optional[str] = None,
    regime: Optional[str] = None,
    dir_regime: Optional[str] = None,
    decision_lane: Optional[str] = None,
    decision_reason: Optional[str] = None,
    was_selected: bool = False,
    stage_indicators: Optional[Dict[str, Any]] = None,
    spot_price: Optional[float] = None,
) -> None:
    """Append one shadow record per side for each in-window evaluation.

    Records the full waterfall with three-state stages; never raises,
    never influences routing.
    """
    if not _ENABLED:
        return
    _stats["hook_invocations"] += 1
    try:
        tte = float(tte_seconds or 0.0)
        now = datetime.now(timezone.utc)
        ts_now = now.timestamp()
        a_stat = _stats_asset.setdefault(
            asset or "?",
            {"hook_invocations": 0, "invocations_skipped_tte": 0,
             "last_tte_seconds": None},
        )
        a_stat["hook_invocations"] += 1
        a_stat["last_tte_seconds"] = tte

        # Resolve settlement reference: prefer the caller's value; fall back
        # to the live RTI read path so pre-engine evals still measure the
        # cushion.  ``ref_source`` records provenance, never a fabrication.
        ref = float(ref_price) if ref_price is not None else (
            float(ref_tick) if ref_tick is not None else None
        )
        r_src = ref_source
        r_age = rti_age_ms
        if ref is None:
            _px, _src, _age = _obs_price(_live_rti(asset))
            if _px is not None:
                ref, r_src = _px, _src
                if r_age is None:
                    r_age = _age
        K = float(strike) if strike is not None else None

        # Feed distance history (any TTE) keyed by contract identity; then
        # gate the write to the window.
        if ticker and K is not None:
            _feed_history((ticker, K), ts_now, ref)

        # classify this call BEFORE the heartbeat so each meta snapshot is
        # self-consistent (the in-flight invocation is already counted).
        if not (TTE_LO_S < tte <= TTE_HI_S):
            _stats["invocations_skipped_tte"] += 1
            a_stat["invocations_skipped_tte"] += 1
        if _stats["hook_invocations"] % _META_EVERY == 0:
            _write_meta(now, ts_now, asset, ticker, tte)
        if not (TTE_LO_S < tte <= TTE_HI_S):
            return

        # ``_hist.get`` returns None when this contract has no fed sample yet
        # (e.g. ref missing so _feed_history never created the deque) — iterate
        # an empty deque instead of crashing and losing the INPUTS_MISSING
        # record the lane contract requires.
        dq = _hist.get((ticker, K)) or deque()
        sig_frac = None
        sig_price = None
        if annualized_vol:
            sig_frac = float(annualized_vol) * math.sqrt(tte / SECS_PER_YEAR)
            if ref is not None:
                sig_price = ref * sig_frac

        d_prev = (
            _distance_at(dq, ts_now, TREND_LOOKBACK_S, TREND_LOOKBACK_TOL_S, K)
            if K is not None else None
        )
        n_cross = (
            _crossings(dq, ts_now, CROSS_LOOKBACK_S, K)
            if K is not None else 0
        )

        ind = stage_indicators or {}
        settlement_state = {
            k: v for k, v in ind.items()
            if str(k).startswith("settlement") and isinstance(v, (int, float, str, bool))
        }
        ind_get = lambda *names: next(
            (ind[n] for n in names if ind.get(n) is not None), None
        )

        records: List[Dict[str, Any]] = []
        for side, ask, bid, depth, p_cal, p_raw, net_edge, owner, bf in (
            ("yes", yes_ask_cents, yes_bid_cents, yes_depth_cc,
             p_yes_calibrated, p_yes_raw, net_edge_taker_yes,
             admission_owner_yes, bookflow_block_yes),
            ("no", no_ask_cents, no_bid_cents, no_depth_cc,
             p_no_calibrated, p_no_raw, net_edge_taker_no,
             admission_owner_no, bookflow_block_no),
        ):
            s_dir = 1.0 if side == "yes" else -1.0
            d_side = (s_dir * (ref - K)) if (ref is not None and K is not None) else None
            d_bps = (1e4 * d_side / K) if (d_side is not None and K) else None
            z_cush = (d_side / sig_price) if (
                d_side is not None and sig_price and sig_price > 0
            ) else None
            # endpoint-normal diagnostic recomputed from this record's own
            # inputs (lognormal form used by the production engine); NOT a
            # settlement-average model.
            q_phi = None
            if ref is not None and K is not None and K > 0 and sig_frac and sig_frac > 0:
                lm = math.log(ref / K)
                q_phi = _phi(s_dir * (lm / sig_frac))

            # frozen trend — requires sigma_rem for the flat band AND a prior
            if annualized_vol is None:
                trend = "no_vol"
            elif d_side is None:
                trend = "no_inputs"
            elif d_prev is None:
                trend = "no_prior"
            else:
                tol = TREND_FLAT_FRAC * (sig_price or 0.0)
                chg = d_side - s_dir * d_prev
                trend = ("expanding" if chg > tol
                         else "shrinking" if chg < -tol else "flat")

            fee = _taker_fee_cents(float(ask) / 100.0)
            margin_fee = (
                float(p_cal) * 100.0 - float(ask) - fee
                if p_cal is not None else None
            )
            margin_lane = (
                margin_fee - (ADVERSE_SEL_RESERVE + MODEL_UNCERTAINTY_RESERVE) * 100.0
                if margin_fee is not None else None
            )

            p_status, p_source, missing_inputs, model_completed = (
                _probability_status(
                    p_cal=p_cal, ref=ref, K=K, vol=annualized_vol,
                    vol_source=vol_source, ind=ind,
                    decision_reason=decision_reason,
                    decision_lane=decision_lane,
                    settlement_state=settlement_state,
                )
            )

            # ---- three-state waterfall ----
            inputs_ok = (
                ref is not None and K is not None and annualized_vol is not None
                and (quote_age_ms is None or float(quote_age_ms) <= MAX_QUOTE_AGE_MS)
                and (r_age is None or float(r_age) <= MAX_RTI_AGE_MS)
            )
            price_ok = ASK_MIN_CENTS <= float(ask) <= ASK_MAX_CENTS
            research_band = RESEARCH_BAND[0] <= float(ask) <= RESEARCH_BAND[1]
            position_ok = d_side is not None and d_side > 0
            trend_evaluable = trend in ("expanding", "flat", "shrinking")
            trend_ok = trend in ("expanding", "flat")
            depth_ok = float(depth or 0.0) >= 100.0
            bf_ok = bf is None
            model_ok = (
                p_status == "COMPUTED_VALID" and margin_fee is not None
                and margin_fee > 0.0
            )
            econ_ok = (
                p_status == "COMPUTED_VALID" and margin_lane is not None
                and margin_lane > 0.0
            )

            def st(ok: bool, evaluable: bool = True) -> str:
                if not evaluable:
                    return "not_evaluable"
                return "pass" if ok else "fail"

            stages = {
                "w0_in_window": "pass",
                "w1_inputs_trusted": st(inputs_ok),
                "w2_price_above_85": st(price_ok),
                "w2b_research_band_86_89": st(research_band),
                "w3_correct_side": st(position_ok, d_side is not None),
                "w4_trend_non_shrinking": st(trend_ok, trend_evaluable),
                "w5_depth_ok": st(depth_ok),
                "w6_bookflow_clear": st(bf_ok),
                "w7_model_margin_positive": st(
                    model_ok, p_status == "COMPUTED_VALID"
                ),
                "w8_econ_admission_lane": st(
                    econ_ok, p_status == "COMPUTED_VALID"
                ),
            }
            lane_pass = all(v == "pass" for v in stages.values())
            first_fail = next((k for k, v in stages.items() if v != "pass"), None)
            # invariant: not_evaluable anywhere => indeterminate, never a
            # lane admission and never reported as an economic rejection.
            lane_verdict = (
                "indeterminate"
                if any(v == "not_evaluable" for v in stages.values())
                else ("admit" if lane_pass else "reject")
            )
            ref_ts = (
                (now - timedelta(milliseconds=float(r_age))).isoformat()
                if r_age is not None else None
            )

            records.append({
                "type": "lwf_shadow",
                "schema_version": SCHEMA_VERSION,
                "lane_revision": LANE_REVISION,
                "process_id": _PROCESS_ID,
                "lane": "late_window_trend_favorite",
                "eval_path": eval_path,
                "event_ts_utc": now.isoformat(),
                "run_id": run_id,
                "decision_id": decision_id,
                "asset": asset,
                "ticker": ticker,
                "side": side,
                # market state
                "ask_cents": float(ask),
                "bid_cents": float(bid),
                "spread_cents": float(ask) - float(bid),
                "depth_cc": float(depth),
                "yes_bid_cents": float(yes_bid_cents),
                "yes_ask_cents": float(yes_ask_cents),
                "no_bid_cents": float(no_bid_cents),
                "no_ask_cents": float(no_ask_cents),
                # contract / settlement reference
                "strike": K,
                "strike_source": strike_source,
                "ref_price": ref,
                "ref_source": r_src,
                "ref_tick": ref_tick,
                "ref_price_ts_utc": ref_ts,
                "spot_price": spot_price,
                "rti_age_ms": r_age,
                # cushion section
                "signed_distance_price": d_side,
                "signed_distance_bps": d_bps,
                "distance_30s_ago_yes_axis": d_prev,
                "sigma_rem_price": sig_price,
                "sigma_rem_frac": sig_frac,
                "z_cushion": z_cush,
                "trend": trend,
                "trend_lookback_s": TREND_LOOKBACK_S,
                "trend_flat_frac": TREND_FLAT_FRAC,
                "crossings_60s": n_cross,
                "annualized_vol": annualized_vol,
                "vol_source": vol_source,
                # probability provenance
                "probability_status": p_status,
                "probability_source": p_source,
                "missing_input_fields": missing_inputs,
                "model_evaluation_completed": model_completed,
                "model_input_snapshot_id": decision_id,
                "p_calibrated_side": p_cal,
                "p_raw_side": p_raw,
                "q_phi_diagnostic": q_phi,
                "z_score_model": ind_get("z_score"),
                "log_moneyness": ind_get("log_moneyness"),
                "fe_final_p_yes": ind_get("fe_final_p_yes"),
                "fe_final_p_no": ind_get("fe_final_p_no_for_no"),
                "stream_bound_yes": ind_get("streaming_cal_bound_yes"),
                "stream_bound_no": ind_get("streaming_cal_bound_no"),
                "settlement_state": settlement_state or None,
                # economics
                "taker_fee_cents": fee,
                "margin_fee_only_cents": margin_fee,
                "margin_lane_cents": margin_lane,
                "adverse_sel_reserve": ADVERSE_SEL_RESERVE,
                "model_uncertainty_reserve": MODEL_UNCERTAINTY_RESERVE,
                "engine_net_edge_taker": net_edge,
                # waterfall
                "stages": stages,
                "first_failed_stage": first_fail,
                "lane_would_admit": lane_pass,
                "lane_verdict": lane_verdict,
                # engine outcome (reference only — not the lane's verdict)
                "engine_would_reject_tte": tte <= 180.0,
                "engine_decision_reason": decision_reason,
                "engine_was_selected": was_selected,
                "engine_decision_lane": decision_lane,
                "admission_owner": owner,
                "bookflow_block": bf,
                "regime": regime,
                "dir_regime": dir_regime,
                # hypothetical execution assumption (taker basis)
                "exec_role": "taker_ioc",
                "exec_limit_cents": float(ask),
                "exec_assumption": "fill_at_ask_depth>=100cc",
                # provenance
                "tte_seconds": tte,
                "quote_age_ms": quote_age_ms,
                "book_is_executable": book_is_executable,
            })

    except Exception as e:  # pragma: no cover - telemetry must never break trading
        _stats["evaluation_errors"] += 1
        logger.debug("[LWF-SHADOW] evaluation failed: %s", e)
        return

    # ---- dedup + write (separate error domain from evaluation) ----
    kept = []
    for record in records:
        _stats["side_evaluations"] += 1
        dkey = (
            record.get("decision_id")
            or f"{record.get('ticker')}:{record.get('eval_path')}:"
               f"{str(record.get('event_ts_utc'))[:19]}",
            record.get("side"),
        )
        if dkey in _seen:
            _stats["side_evaluations_deduplicated"] += 1
            continue
        _seen[dkey] = True
        if len(_seen) > _SEEN_MAX:
            _seen.popitem(last=False)
        kept.append(record)
    if not kept:
        return
    try:
        path = os.environ.get("MERID_LWF_SHADOW_LOG", _DEFAULT_PATH)
        with _lock:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                for record in kept:
                    f.write(json.dumps(record, default=str) + "\n")
        _stats["records_written"] += len(kept)
    except Exception as e:
        _stats["write_errors"] += 1
        logger.debug("[LWF-SHADOW] write failed: %s", e)


def _write_meta(now: datetime, ts_now: float, asset: str,
                ticker: Optional[str], tte: float) -> None:
    """Periodic heartbeat with per-unit counters + process identity."""
    try:
        path = os.environ.get("MERID_LWF_SHADOW_LOG", _DEFAULT_PATH)
        rec = {
            "type": "lwf_shadow_meta",
            "schema_version": SCHEMA_VERSION,
            "lane_revision": LANE_REVISION,
            "process_id": _PROCESS_ID,
            "counters_reset_utc": _COUNTERS_RESET_UTC,
            "event_ts_utc": now.isoformat(),
            **_stats,
            "by_asset": dict(_stats_asset),
            "last_asset": asset,
            "last_ticker": ticker,
            "last_tte_seconds": tte,
        }
        with _lock:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass
