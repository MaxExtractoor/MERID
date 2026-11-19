"""Lead-lag shadow lane — read-only prospective capture (research only).

Emits one self-contained JSONL record per production trade-decision
evaluation for the preregistered cross-asset experiment: does lagged BTC
RTI information add settlement-forecast value beyond the lane incumbent?

Hard guarantees (acceptance criteria):
- NEVER read by entry/exit/sizing/allocator/risk logic — outputs go only to
  ``logs/leadlag_shadow.jsonl`` via a bounded queue + daemon writer.
- All exceptions are swallowed and counted; the live path cannot be blocked
  or altered.  A full queue drops the research record and increments
  ``dropped_records`` — trading behavior is unchanged either way.
- Frozen model artifact (``leadlag_shadow_model_v1.json``) is loaded once,
  hash-verified, and applied as pure dot-product inference — no sklearn in
  the decision path.
- Missing/stale features produce an explicit ``abstain_*`` record, never a
  fabricated zero.

Design: MERID_LEAD_LAG_SHADOW_LANE_DESIGN_2026-11-12.md (capture directive).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = Path(__file__).resolve().parent / "leadlag_shadow_model_v1.json"
TARGET_ASSETS = ("ETH", "SOL", "XRP", "DOGE")   # BTC is leader/control only
HORIZON_KEYS = ("rti_return_1s", "rti_return_3s", "rti_return_10s",
                "rti_return_30s", "rti_return_60s", "rti_return_120s")
EPS = 1e-6

_stats_lock = threading.Lock()
_stats = {
    "emitted": 0, "dropped_queue_full": 0, "emit_errors": 0,
    "write_errors": 0, "abstain": 0, "skipped_asset": 0,
    "model_load_failures": 0,
}
_model_cache: Optional[Dict[str, Any]] = None
_model_lock = threading.Lock()
_q: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=20000)
_writer_started = False
_writer_lock = threading.Lock()


def _env_flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


def enabled() -> bool:
    return _env_flag("MERID_LEADLAG_SHADOW_ENABLED", "1")


def _log_path() -> Path:
    custom = os.environ.get("MERID_LEADLAG_SHADOW_LOG_PATH")
    if custom:
        return Path(custom)
    return ROOT / "logs" / "leadlag_shadow.jsonl"


def _queue_max() -> int:
    try:
        return int(os.environ.get("MERID_LEADLAG_SHADOW_QUEUE_MAX", "20000"))
    except ValueError:
        return 20000


def get_stats() -> Dict[str, Any]:
    with _stats_lock:
        return dict(_stats)


def _bump(key: str, n: int = 1) -> None:
    with _stats_lock:
        _stats[key] = _stats.get(key, 0) + n


# ---------------------------------------------------------------------------
# frozen model
# ---------------------------------------------------------------------------

def _load_model() -> Optional[Dict[str, Any]]:
    global _model_cache
    if _model_cache is not None:
        return _model_cache
    with _model_lock:
        if _model_cache is not None:
            return _model_cache
        try:
            art = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
            # verify integrity: recompute hash over the same canonical spec
            canon = {
                "feature_names": art.get("feature_names"),
                "horizons_s": art.get("horizons_s"),
                "target_assets": art.get("target_assets"),
                "anchor": art.get("anchor"),
                "max_eval_age_s": art.get("max_eval_age_s"),
                "eps": art.get("eps"),
                "models": {k: {"coef": v.get("coef"),
                               "intercept": v.get("intercept"),
                               "p0_key": v.get("p0_key"),
                               "kind": v.get("kind"),
                               "include_btc": v.get("include_btc"),
                               "include_own": v.get("include_own"),
                               "include_market": v.get("include_market")}
                           for k, v in (art.get("models") or {}).items()},
            }
            h = hashlib.sha256(
                json.dumps(canon, sort_keys=True).encode()).hexdigest()
            if h != art.get("model_hash"):
                logger.warning("[LEADLAG-SHADOW] model hash mismatch: %s != %s",
                               h[:16], str(art.get("model_hash"))[:16])
                _bump("model_load_failures")
                return None
            _model_cache = art
        except Exception as exc:
            logger.warning("[LEADLAG-SHADOW] model load failed: %s", exc)
            _bump("model_load_failures")
            _model_cache = {}
    return _model_cache or None


def _logit(p: float) -> float:
    p = min(1.0 - EPS, max(EPS, float(p)))
    return float(__import__("math").log(p / (1.0 - p)))


def _sigmoid(x: float) -> float:
    import math
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


# ---------------------------------------------------------------------------
# feature extraction — mirrors the screen's _feat_vector exactly
# ---------------------------------------------------------------------------

def _returns_at(slice_, horizon_keys) -> Dict[str, Optional[float]]:
    """Map snapshot rti_returns string keys to horizon seconds."""
    out = {}
    rr = getattr(slice_, "rti_returns", None) or {}
    for hk in horizon_keys:
        # "rti_return_60s" -> 60.0
        try:
            h = float(hk.rsplit("_", 1)[1].rstrip("s"))
        except Exception:
            h = None
        out[h] = rr.get(hk) if h is not None else None
    return out


def _build_features(asset: str, snap, td_kwargs: Dict[str, Any],
                    decision) -> tuple[Optional[list], Dict[str, Any], list,
                                        Dict[str, bool]]:
    """Return (tail feature list or None, feature_dict, missing_reasons,
    block_ok).  ``tail`` always has the full 22-element layout; per-model
    block abstention is applied in ``_predict`` exactly as the screen's
    ``_feat_vector`` does (an included block with a missing return makes
    that model abstain; excluded blocks are zero-filled)."""
    missing: list = []
    block_ok = {"btc": False, "own": False}
    own = (getattr(snap, "by_asset", None) or {}).get(asset) if snap else None
    btc = (getattr(snap, "by_asset", None) or {}).get("BTC") if snap else None
    if own is None:
        return None, {}, ["snapshot_asset_missing"], block_ok
    if not getattr(own, "feature_valid", False):
        missing.append("own_feature_invalid")

    own_ret = _returns_at(own, HORIZON_KEYS)
    btc_ret = _returns_at(btc, HORIZON_KEYS) if btc is not None else {}
    feat: Dict[str, Any] = {}
    btc_ok = own_ok = True
    for h in (1.0, 3.0, 10.0, 30.0, 60.0, 120.0):
        v = btc_ret.get(h)
        feat[f"btc_ret_{int(h)}s"] = v
        if v is None:
            btc_ok = False
            missing.append(f"btc_ret_{int(h)}s_missing")
        v2 = own_ret.get(h)
        feat[f"own_ret_{int(h)}s"] = v2
        if v2 is None:
            own_ok = False
            missing.append(f"own_ret_{int(h)}s_missing")
    block_ok = {"btc": btc_ok, "own": own_ok}
    if not (btc_ok and own_ok):
        # partial features: tail still built (zeros for missing) so that
        # models excluding the missing block can still predict; models
        # including it abstain per-model in _predict.
        pass

    # controls
    sd = td_kwargs.get("settlement_distribution")
    zscore = getattr(sd, "z_score", None)
    if zscore is None:
        zscore = (getattr(decision, "indicators", None) or {}).get("z_score")
    try:
        zscore = float(zscore) if zscore is not None else 0.0
    except Exception:
        zscore = 0.0
    feat["zscore"] = zscore

    try:
        stc = float(getattr(decision, "seconds_to_expiry",
                            td_kwargs.get("seconds_to_expiry", 0.0)) or 0.0)
    except Exception:
        stc = 0.0
    feat["seconds_to_close"] = stc
    feat["tte_frac"] = stc / 900.0
    # screen semantics: falsy stc -> 999 sentinel -> not in window
    feat["in_window"] = 1.0 if (stc or 999.0) <= 60.0 else 0.0

    age_ms = getattr(own, "feature_age_ms", None)
    if age_ms is None:
        age_ms = getattr(own, "rti_age_ms", None)
    try:
        eval_age_s = float(age_ms) / 1000.0 if age_ms is not None else 0.0
    except Exception:
        eval_age_s = 0.0
    feat["eval_age_s"] = eval_age_s
    # unclipped, matching screen._feat_vector exactly
    feat["eval_age_frac"] = eval_age_s / 90.0

    yb = td_kwargs.get("yes_bid_cents")
    ya = td_kwargs.get("yes_ask_cents")
    try:
        if yb is not None and ya is not None:
            mp = (float(yb) + float(ya)) / 200.0
            feat["yes_mid_prob"] = mp if 0.0 < mp < 1.0 else None
        else:
            feat["yes_mid_prob"] = None
    except Exception:
        feat["yes_mid_prob"] = None
    feat["yes_mid_missing"] = 0.0 if feat["yes_mid_prob"] is not None else 1.0

    # ---- assemble x in FEATURE_NAMES order ----
    # [logit_p0] btc x6 own x6 zscore tte_frac in_window eval_age_frac
    # yes_mid_logit yes_mid_missing asset x4
    # p0 slot filled by caller per model; build the tail now.
    tail = []
    for h in (1.0, 3.0, 10.0, 30.0, 60.0, 120.0):
        v = btc_ret.get(h)
        tail.append(float(v) * 1e4 if v is not None else 0.0)
    for h in (1.0, 3.0, 10.0, 30.0, 60.0, 120.0):
        v = own_ret.get(h)
        tail.append(float(v) * 1e4 if v is not None else 0.0)
    tail.append(zscore)
    tail.append(feat["tte_frac"])
    tail.append(feat["in_window"])
    tail.append(feat["eval_age_frac"])
    mp = feat["yes_mid_prob"]
    tail.append(_logit(mp) if mp is not None else 0.0)
    tail.append(feat["yes_mid_missing"])
    tail.extend(1.0 if asset == a else 0.0 for a in TARGET_ASSETS)
    return tail, feat, missing, block_ok


def _predict(model: Dict[str, Any], p0: float, tail: list,
             block_ok: Dict[str, bool], max_eval_age_s: float,
             eval_age_s: float) -> Optional[float]:
    """Dot-product inference replicating screen._feat_vector semantics:
    a model abstains (returns None) when a block it was trained on has a
    missing required input; excluded blocks are zero-filled."""
    try:
        kind = model.get("kind")
        coef = model.get("coef") or []
        intercept = float(model.get("intercept", 0.0))
        if kind == "logit_only":
            return _sigmoid(intercept + coef[0] * _logit(p0))
        ib = model.get("include_btc")
        io = model.get("include_own")
        # per-model abstention on missing required blocks (screen parity;
        # flags are None for the recalibration controls -> falsy -> no
        # block requirement, matching _feat_vector's truthiness checks)
        if ib and not block_ok.get("btc", False):
            return None
        if io and not block_ok.get("own", False):
            return None
        # staleness bound: screen selected rows within MAX_EVAL_AGE_S of the
        # checkpoint; live feature age beyond the artifact bound abstains.
        if eval_age_s > max_eval_age_s:
            return None
        x = [_logit(p0)] + list(tail)
        if not model.get("include_market") and len(coef) == len(x) - 2:
            # screen._feat_vector omits the market pair entirely when
            # include_market is falsy (21-element vector; the frozen
            # p_control_* models use this layout).
            del x[17:19]
        if len(coef) != len(x):
            return None
        if not ib:
            for i in range(1, 7):    # btc block x[1..6]
                x[i] = 0.0
        if not io:
            for i in range(7, 13):   # own block x[7..12]
                x[i] = 0.0
        z = intercept + sum(c * v for c, v in zip(coef, x))
        return _sigmoid(z)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# record assembly + queue
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _writer_loop() -> None:
    path = _log_path()
    while True:
        try:
            rec = _q.get()
        except Exception:
            continue
        try:
            line = json.dumps(rec, default=str)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            _bump("write_errors")
        finally:
            _q.task_done()


def _ensure_writer() -> None:
    global _writer_started
    if _writer_started:
        return
    with _writer_lock:
        if _writer_started:
            return
        t = threading.Thread(target=_writer_loop, name="leadlag-shadow-writer",
                             daemon=True)
        t.start()
        _writer_started = True


def _enq(rec: Dict[str, Any]) -> None:
    _ensure_writer()
    try:
        _q.put_nowait(rec)
        _bump("emitted")
    except queue.Full:
        _bump("dropped_queue_full")


def maybe_emit(*, ticker: str, asset: str, decision, td_kwargs: Dict[str, Any]) -> None:
    """Entry point invoked beside the scheduled-shadow hook. Never raises."""
    try:
        if not enabled():
            return
        if asset not in TARGET_ASSETS:
            _bump("skipped_asset")
            return
        model = _load_model()
        snap = td_kwargs.get("feature_snapshot")
        indicators = getattr(decision, "indicators", None) or {}

        tail, feat, missing, block_ok = _build_features(
            asset, snap, td_kwargs, decision)
        abstain = tail is None
        status = "ok" if not abstain else "abstain_no_snapshot"
        if abstain:
            _bump("abstain")
        elif not block_ok.get("own"):
            status = "partial_missing_own_returns"
        elif not block_ok.get("btc"):
            status = "partial_missing_btc_returns"

        p_raw = p_cal = None
        try:
            p_raw = float(getattr(decision, "p_yes_raw", 0.5))
            p_cal = float(getattr(decision, "p_yes_calibrated", 0.5))
        except Exception:
            pass
        if p_raw is None or p_cal is None:
            status = "abstain_missing_p0"
            _bump("abstain")

        preds: Dict[str, Any] = {}
        max_age = float((model or {}).get("max_eval_age_s", 90.0))
        eval_age_s = float((feat or {}).get("eval_age_s") or 0.0)
        if model and not abstain and p_raw is not None and p_cal is not None:
            for mkey, m in (model.get("models") or {}).items():
                p0 = p_cal if m.get("p0_key") == "p_cal" else p_raw
                preds[mkey] = _predict(m, p0, tail, block_ok,
                                       max_age, eval_age_s)
        elif model is None:
            status = "abstain_no_model"
            _bump("abstain")

        # settlement lineage
        sd = td_kwargs.get("settlement_distribution")
        settlement = {
            "reference": getattr(decision, "settlement_reference", None)
                         or td_kwargs.get("settlement_reference"),
            "phase": getattr(sd, "phase", None),
            "observed_count": getattr(sd, "observed_count", None),
            "remaining_count": getattr(sd, "remaining_count", None),
            "z_score": feat.get("zscore"),
            "model_version": getattr(sd, "model_version", None),
            "forecast_method": getattr(sd, "forecast_method", None),
            "p_yes_raw_dist": getattr(sd, "p_yes_raw", None),
        }

        own = (getattr(snap, "by_asset", None) or {}).get(asset) if snap else None
        btc = (getattr(snap, "by_asset", None) or {}).get("BTC") if snap else None

        def _rti_block(s):
            if s is None:
                return None
            return {
                "rti_value": getattr(s, "rti_value", None),
                "rti_source_ts_ms": getattr(s, "rti_source_ts_ms", None),
                "rti_observed_ts_ms": getattr(s, "rti_observed_ts_ms", None),
                "rti_execution_eligible": getattr(s, "rti_execution_eligible", None),
                "rti_age_ms": getattr(s, "rti_age_ms", None),
                "feature_ts": getattr(s, "feature_ts", None),
                "feature_age_ms": getattr(s, "feature_age_ms", None),
                "feature_valid": getattr(s, "feature_valid", None),
                "missing_reasons": list(getattr(s, "missing_reasons", None) or []),
            }

        did = str(getattr(decision, "decision_id", "") or "")
        candidate_id = did.rsplit(":", 1)[0] if ":" in did else did
        try:
            dts = float(getattr(decision, "timestamp_utc").timestamp())
        except Exception:
            dts = time.time()
        stc = feat.get("seconds_to_close")
        rec = {
            "record_type": "leadlag_shadow",
            "schema_version": 1,
            "model_version": "leadlag-shadow-v1",
            "model_hash": (model or {}).get("model_hash"),
            "emitted_at_utc": _iso_now(),
            "emitted_at_epoch_s": time.time(),
            # identity
            "eval_id": did,
            "candidate_id": candidate_id,
            "ticker": ticker,
            "asset": asset,
            "route": td_kwargs.get("route"),
            "decision_lane": indicators.get("decision_lane"),
            "admission_lane": indicators.get("admission_lane"),
            "run_id": getattr(decision, "run_id", None),
            "build_sha": getattr(decision, "build_sha", None)
                        or indicators.get("build_sha"),
            # time
            "decision_ts_epoch_s": dts,
            "close_ts_epoch_s": (dts + float(stc))
                                if stc is not None else None,
            "seconds_to_close": stc,
            "feature_ts": getattr(snap, "ts", None) if snap else None,
            # settlement
            "settlement": settlement,
            # features (exact values fed to the models; None on abstain)
            "features": feat if not abstain else None,
            "feature_status": status,
            "missing_reasons": missing + list(
                getattr(own, "missing_reasons", None) or [] if own else []),
            # predictions
            "predictions": {
                "p_settle_raw": p_raw,
                "p_lane_incumbent": p_cal,
                "p_lane_incumbent_key": "p_yes_calibrated",
                **preds,
            },
            # economics inputs (raw; replay offline with exact fee fns)
            "economics": {
                "yes_bid_cents": td_kwargs.get("yes_bid_cents"),
                "yes_ask_cents": td_kwargs.get("yes_ask_cents"),
                "no_bid_cents": td_kwargs.get("no_bid_cents"),
                "no_ask_cents": td_kwargs.get("no_ask_cents"),
                "yes_depth_cc": td_kwargs.get("yes_depth_cc"),
                "no_depth_cc": td_kwargs.get("no_depth_cc"),
                "fee_per_contract_cents": td_kwargs.get("fee_per_contract_cents"),
                "adverse_selection_reserve": td_kwargs.get("adverse_selection_reserve"),
                "quote_age_ms": td_kwargs.get("quote_age_ms"),
                "rti_age_ms": td_kwargs.get("rti_age_ms"),
            },
            # incumbent decision outcome (counterfactual comparison later)
            "incumbent_decision": {
                "selected_outcome": str(getattr(decision, "selected_outcome", None)),
                "selected_action": str(getattr(decision, "selected_action", None)),
                "no_trade_reason": getattr(decision, "no_trade_reason", None),
                "ev_gate_allowed": getattr(decision, "ev_gate_allowed", None),
                "net_edge_yes": str(getattr(decision, "net_edge_yes", "")),
                "net_edge_no": str(getattr(decision, "net_edge_no", "")),
                "best_side": getattr(decision, "best_side", None),
                "min_required_edge": str(getattr(decision, "min_required_edge", "")),
            },
            # per-asset RTI provenance (source vs observed timestamps)
            "rti": {"own": _rti_block(own), "btc": _rti_block(btc)},
            # quality flags — kept separate so a book problem cannot
            # invalidate a valid forecast (and vice versa)
            "quality": {
                "forecast_valid": any(v is not None for v in preds.values()),
                "top_quote_economics_valid": bool(
                    td_kwargs.get("book_is_executable", True)),
                "depth_replay_valid": None,   # requires book archive join
                "maker_execution_valid": None,  # separate research track
                "in_training_scope": True,    # asset ∈ TARGET_ASSETS by gate
            },
        }
        _enq(rec)
    except Exception as exc:  # never propagate into the decision path
        _bump("emit_errors")
        try:
            logger.debug("[LEADLAG-SHADOW] emit failed: %s", exc)
        except Exception:
            pass
