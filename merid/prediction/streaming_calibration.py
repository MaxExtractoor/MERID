"""Streaming self-correcting calibration overlay (2026-10-15, FIX 14).

The refit tail-calibration artifact (``data/probability_tail_calibration.json``)
is the read path's static bound, but it is only as fresh as the last manual
refit.  This module maintains a *live* calibration state that every settlement
update nudges: an EMA-bucket calibrator keyed on the canonical evidence cell
dimensions (asset x side x price-bucket x TTE-bucket), fed by fills AND by
rejected candidates joined to their settlement outcomes (the same merged
cohort the evidence refresh builds — a vetoed candidate's outcome is equally
valid calibration evidence).

Semantics: each settled observation contributes ``(calibrated_p, won)`` to its
cell.  The cell's streaming bound is the decayed empirical win rate shrunk
toward the cell's own claimed mean (Beta-style posterior with strength
``MERID_STREAM_CAL_PRIOR_K``) plus a small honesty buffer, then
PAV-isotonized across the price axis within each (asset, side, tte) slice so
the implied cap curve cannot claim a cheaper contract is *more* likely to
win than a pricier one.

The read path applies the bound as ``min(p_after_artifact_cap, bound)`` — it
can only tighten a claim toward measured reality, never inflate one, so it
stays clear of the calibration-deviation guard's inflation semantics and the
settlement lane's own probability ceiling.

Update idempotency: the refresh re-scans a rolling window, so a settled_at
watermark bounds what has been applied; rows at-or-below it are skipped.
Rows are deduped to the newest eval per (ticker, side) before applying, so a
market evaluated 200x contributes one observation per settlement.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from merid.prediction import evidence_policy as _ep

logger = logging.getLogger(__name__)

_STATE_PATH_DEFAULT = "data/streaming_calibration.json"
_CACHE_TTL_S = 60.0

_cache: Dict[str, Any] = {"ts": 0.0, "state": None, "mtime": None}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, default)))
    except Exception:
        return default


def enabled() -> bool:
    return os.environ.get("MERID_STREAM_CAL_ENABLED", "1").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _state_path() -> str:
    return os.environ.get("MERID_STREAM_CAL_PATH", _STATE_PATH_DEFAULT)


def _halflife_days() -> float:
    return max(0.25, _env_float("MERID_STREAM_CAL_HALFLIFE_DAYS", 10.0))


def _prior_k() -> float:
    return max(0.0, _env_float("MERID_STREAM_CAL_PRIOR_K", 20.0))


def _min_neff() -> float:
    return max(1.0, _env_float("MERID_STREAM_CAL_MIN_NEFF", 8.0))


def _buffer() -> float:
    return max(0.0, _env_float("MERID_STREAM_CAL_BUFFER", 0.05))


def _cusum_slack() -> float:
    """Per-observation allowance k: residuals inside +/-k are sampling noise."""
    return max(0.0, _env_float("MERID_DRIFT_CUSUM_SLACK", 0.05))


def _cusum_threshold() -> float:
    """Cumulative drift that trips the alarm (in units of prob x obs)."""
    return max(0.01, _env_float("MERID_DRIFT_CUSUM_H", 0.5))


_PRICE_BUCKET_ORDER = ("01-09", "10-24", "25-49", "50-74", "75-89", "90-100")


def _empty_state() -> Dict[str, Any]:
    return {"version": 1, "watermark": 0.0, "cells": {}}


def load_state(force: bool = False) -> Dict[str, Any]:
    """TTL-cached read of the persistent streaming state."""
    # Test-context isolation: unless the test pinned an explicit state path,
    # never let the live file leak into a unit test's decisions.
    if _test_default_path():
        return _empty_state()
    now = time.time()
    if not force and _cache["state"] is not None and (
        now - float(_cache["ts"]) < _CACHE_TTL_S
    ):
        return _cache["state"]
    path = _state_path()
    try:
        mtime = os.path.getmtime(path)
        if (
            _cache["state"] is not None
            and _cache["mtime"] is not None
            and mtime <= float(_cache["mtime"])
        ):
            _cache["ts"] = now
            return _cache["state"]
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        if not isinstance(state, dict) or "cells" not in state:
            state = _empty_state()
    except Exception:
        state = _empty_state()
        mtime = None
    _cache["state"] = state
    _cache["ts"] = now
    _cache["mtime"] = mtime
    return state


def _test_default_path() -> bool:
    """True under pytest when no explicit state path was configured."""
    return bool(
        os.environ.get("PYTEST_CURRENT_TEST")
        and not os.environ.get("MERID_STREAM_CAL_PATH")
    )


def _save_state(state: Dict[str, Any]) -> None:
    if _test_default_path():
        return
    path = _state_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
        _cache["state"] = state
        _cache["ts"] = time.time()
        try:
            _cache["mtime"] = os.path.getmtime(path)
        except Exception:
            _cache["mtime"] = None
    except Exception as e:
        logger.warning("[STREAM-CAL] state write failed: %s", e)


def reset_cache() -> None:
    _cache["ts"] = 0.0
    _cache["state"] = None
    _cache["mtime"] = None


def update_from_rows(rows: List[Dict[str, Any]], now: Optional[float] = None) -> int:
    """Fold a settled evidence cohort into the streaming state.

    ``rows`` are the refresh's merged fill+veto dict rows carrying
    ``asset``, ``side``, ``entry_cents``, ``seconds_to_close``,
    ``calibrated_probability``, ``settled_yes``, ``settled_at``,
    ``decision_ts`` and ``mkey``.  Returns the number of *applied*
    observations (deduped, watermark-filtered).
    """
    if not enabled() or not rows:
        return 0
    now_ts = float(now if now is not None else time.time())
    state = load_state(force=True)
    cells = state.setdefault("cells", {})
    watermark = float(state.get("watermark") or 0.0)

    # Dedup to the newest eval per market-side; a market's outcome is one
    # observation regardless of how many times it was evaluated.
    latest: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        p = r.get("calibrated_probability")
        sat = r.get("settled_at")
        if p is None or sat is None:
            continue
        try:
            p = float(p)
            sat = float(sat)
        except Exception:
            continue
        if not (0.0 <= p <= 1.0) or sat <= watermark:
            continue
        entry = r.get("entry_cents")
        if entry is None or not (0 < float(entry) <= 100):
            continue
        # Dedup on (ticker, side) regardless of row-src mkey shape — the
        # fill query keys on ticker while the veto query keys on
        # ticker|side; a fill + veto pair for one market-side is still a
        # single observation of that side's calibrated claim.
        mk = f"{r.get('ticker')}|{r.get('side')}"
        prev = latest.get(mk)
        if prev is None or float(r.get("decision_ts") or 0.0) >= float(
            prev.get("decision_ts") or 0.0
        ):
            latest[mk] = r
    if not latest:
        return 0

    hl = _halflife_days()
    applied = 0
    new_watermark = watermark
    for r in latest.values():
        try:
            sat = float(r["settled_at"])
            p = float(r["calibrated_probability"])
            y = 1.0 if (
                (str(r["side"]).lower() == "yes") == bool(r["settled_yes"])
            ) else 0.0
            key = _ep.cell_key(
                str(r.get("asset") or "").upper() or "UNKNOWN",
                str(r["side"]).lower(),
                float(r["entry_cents"]),
                r.get("seconds_to_close"),
            )
        except Exception:
            continue
        cell = cells.setdefault(key, {"wy": 0.0, "wp": 0.0, "n": 0.0, "ts": sat})
        # Decay the accumulated sums to this observation's settlement time.
        age_days = max(0.0, (sat - float(cell.get("ts") or sat)) / 86400.0)
        decay = 0.5 ** (age_days / hl)
        cell["wy"] = float(cell.get("wy") or 0.0) * decay + y
        cell["wp"] = float(cell.get("wp") or 0.0) * decay + p
        cell["n"] = float(cell.get("n") or 0.0) * decay + 1.0
        cell["ts"] = sat
        # 2026-10-15 (FIX 15): per-cell CUSUM on the signed residual
        # (claim - outcome).  cusum_hi accumulates overconfidence drift
        # (model claims more than reality delivers — the losing-entry
        # direction); cusum_lo accumulates underconfidence (suppressed
        # opportunity — audit signal only, the tighten-only bound cannot
        # relax upward).  Slack k ignores sampling noise inside +/-k.
        resid = p - y
        slack = _cusum_slack()
        cell["cusum_hi"] = max(
            0.0, float(cell.get("cusum_hi") or 0.0) * decay + resid - slack
        )
        cell["cusum_lo"] = max(
            0.0, float(cell.get("cusum_lo") or 0.0) * decay - resid - slack
        )
        new_watermark = max(new_watermark, sat)
        applied += 1

    if applied:
        state["watermark"] = new_watermark
        # Prune fully-decayed cells so the map stays bounded.
        prune_before = now_ts - 10.0 * hl * 86400.0
        cells = {
            k: v for k, v in cells.items()
            if float(v.get("ts") or 0.0) >= prune_before
        }
        state["cells"] = cells
        _save_state(state)
        logger.info(
            "[STREAM-CAL] applied %d settled observations (watermark=%.0f, cells=%d)",
            applied, new_watermark, len(cells),
        )
    return applied


def _decayed_cells(state: Dict[str, Any], now_ts: float) -> Dict[str, Dict[str, float]]:
    """Effective (decayed-to-now) win sums/claim sums/counts per cell."""
    hl = _halflife_days()
    out: Dict[str, Dict[str, float]] = {}
    for key, cell in (state.get("cells") or {}).items():
        ts = float(cell.get("ts") or 0.0)
        age_days = max(0.0, (now_ts - ts) / 86400.0)
        decay = 0.5 ** (age_days / hl)
        n = float(cell.get("n") or 0.0) * decay
        if n <= 0.0:
            continue
        out[key] = {
            "wy": float(cell.get("wy") or 0.0) * decay,
            "wp": float(cell.get("wp") or 0.0) * decay,
            "n": n,
            "cusum_hi": float(cell.get("cusum_hi") or 0.0) * decay,
            "cusum_lo": float(cell.get("cusum_lo") or 0.0) * decay,
        }
    return out


def _pav(xs: List[float], ws: List[float]) -> List[float]:
    """Pool-adjacent-violators isotonic regression (non-decreasing).

    Returns a per-position list: pooled blocks expand back onto every
    member so the result always aligns with the input positions.
    """
    # Each block: [mean, total_weight, member_count].
    blocks: List[List[float]] = [[x, w, 1] for x, w in zip(xs, ws)]
    out: List[float] = []
    i = 0
    n = len(blocks)
    while i < n - 1:
        if blocks[i][0] > blocks[i + 1][0] + 1e-12:
            w = blocks[i][1] + blocks[i + 1][1]
            c = blocks[i][2] + blocks[i + 1][2]
            blocks[i] = [
                (blocks[i][0] * blocks[i][1]
                 + blocks[i + 1][0] * blocks[i + 1][1]) / w,
                w,
                c,
            ]
            del blocks[i + 1]
            n -= 1
            i = max(0, i - 1)
        else:
            i += 1
    for mean, _w, c in blocks:
        out.extend([mean] * int(c))
    return out


def streaming_bound(
    asset: str,
    side: str,
    price_cents: float,
    tte_seconds: Optional[float],
    now: Optional[float] = None,
) -> Optional[float]:
    """Measured upper bound (probability fraction) for this candidate's cell.

    ``None`` when the cohort is unmeasured (callers pass through unchanged);
    otherwise ``min(p, bound)`` is the honest correction.  The bound is the
    decayed empirical win rate shrunk toward the cell's own claimed mean,
    plus ``MERID_STREAM_CAL_BUFFER``, PAV-isotonized over the price axis
    within the (asset, side, tte) slice.
    """
    detail = streaming_bound_detail(asset, side, price_cents, tte_seconds, now)
    return (detail or {}).get("bound")


def streaming_bound_detail(
    asset: str,
    side: str,
    price_cents: float,
    tte_seconds: Optional[float],
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """``streaming_bound`` plus the bound's provenance.

    ``source`` is ``"exact"`` when the bound came from the candidate's own
    (asset, side, price, tte) slice — the path where a CUSUM-alarmed exact
    cell already contributes its shrunk mean *without* the honesty buffer
    and drags the isotonic curve down, so the alarm's correction is fully
    priced into ``p``.  ``"pooled"`` marks every fallback path (TTE-pooled
    aggregates carry no ``cusum_hi`` and the slice-mean fallback only
    dilutes the alarmed cell across the slice) — the bound is alarm-blind
    there, so an ``over`` drift alarm still warrants its own charge.
    ``source=None`` means no measured cohort applied.
    """
    empty: Dict[str, Any] = {"bound": None, "source": None}
    if not enabled():
        return empty
    state = load_state()
    cells = (state or {}).get("cells")
    if not cells:
        return empty
    now_ts = float(now if now is not None else time.time())
    eff = _decayed_cells(state, now_ts)
    a = str(asset).upper()
    s = str(side).lower()
    tb = _ep.tte_bucket(tte_seconds)
    pb = _ep.price_bucket(price_cents)

    K = _prior_k()
    min_n = _min_neff()

    # Slice = (asset, side, tte) over the canonical price ordering; the bound
    # must be non-decreasing in the held price (a 70c claim cannot be less
    # likely than the 30c claim on the same contract side).
    order = [b for b in _PRICE_BUCKET_ORDER]
    slice_cells: Dict[str, Dict[str, float]] = {}
    for b in order:
        key = f"{a}|{s}|{b}|{tb}"
        c = eff.get(key)
        if c is not None:
            slice_cells[b] = c

    # Exact-slice too thin?  Pool across TTE within the same price bucket so
    # the candidate still sees the asset's measured curve.
    slice_is_pooled = False
    if not slice_cells or (
        slice_cells.get(pb) is None or slice_cells[pb]["n"] < min_n
    ):
        pooled: Dict[str, Dict[str, float]] = {}
        for key, c in eff.items():
            ka, ks, kb, _kt = key.split("|", 3)
            if ka != a or ks != s:
                continue
            rec = pooled.setdefault(kb, {"wy": 0.0, "wp": 0.0, "n": 0.0})
            rec["wy"] += c["wy"]
            rec["wp"] += c["wp"]
            rec["n"] += c["n"]
        if not pooled:
            return empty
        slice_cells = pooled
        slice_is_pooled = True

    xs: List[float] = []
    ws: List[float] = []
    present: List[str] = []
    buf = _buffer()
    h = _cusum_threshold()
    for b in order:
        c = slice_cells.get(b)
        if c is None or c["n"] <= 0.0:
            continue
        # Posterior mean shrunk toward the cell's own claimed mean.
        claimed = c["wp"] / c["n"] if c["n"] else 0.5
        m = (c["wy"] + K * claimed) / (c["n"] + K)
        # FIX 15: a CUSUM-alarmed cell contributes its shrunk mean WITHOUT
        # the honesty buffer, then the whole slice is isotonized — the alarm
        # tightens inside the monotone cap curve rather than puncturing it.
        alarmed = float(c.get("cusum_hi") or 0.0) >= h
        xs.append(m + (0.0 if alarmed else buf))
        ws.append(c["n"] + K)
        present.append(b)
    if not present:
        return empty
    iso = _pav(xs, ws)
    bound_map = dict(zip(present, iso))

    exact = slice_cells.get(pb)
    if exact is not None and exact["n"] >= min_n and pb in bound_map:
        bound = bound_map[pb]
        source = "pooled" if slice_is_pooled else "exact"
    else:
        # Sparse exact bucket: fall back to the pooled asset-level mean so a
        # thin cell still inherits the measured direction.
        tot_wy = sum(c["wy"] for c in slice_cells.values())
        tot_wp = sum(c["wp"] for c in slice_cells.values())
        tot_n = sum(c["n"] for c in slice_cells.values())
        if tot_n <= 0.0:
            return empty
        claimed = tot_wp / tot_n
        alarmed = float(exact.get("cusum_hi") or 0.0) >= h if exact else False
        bound = (tot_wy + K * claimed) / (tot_n + K) + (0.0 if alarmed else buf)
        source = "pooled"
    return {"bound": max(0.01, min(0.99, bound)), "source": source}


def drift_alarm(
    asset: str,
    side: str,
    price_cents: float,
    tte_seconds: Optional[float],
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """CUSUM drift-alarm state for this candidate's cell (or None).

    ``direction="over"`` means the model's claims ran systematically above
    outcomes (the losing-entry drift); ``"under"`` is the suppressed-
    opportunity direction kept for audit.  Callers charge an extra risk
    reserve while ``over`` alarms are active.
    """
    if not enabled():
        return None
    state = load_state()
    if not state or not state.get("cells"):
        return None
    now_ts = float(now if now is not None else time.time())
    eff = _decayed_cells(state, now_ts)
    key = _ep.cell_key(
        str(asset).upper(), str(side).lower(), price_cents, tte_seconds
    )
    c = eff.get(key)
    if c is None:
        return None
    h = _cusum_threshold()
    hi = float(c.get("cusum_hi") or 0.0)
    lo = float(c.get("cusum_lo") or 0.0)
    if hi >= h:
        return {"direction": "over", "cusum": round(hi, 4), "cell": key}
    if lo >= h:
        return {"direction": "under", "cusum": round(lo, 4), "cell": key}
    return None


def corrected_probability(
    asset: str,
    side: str,
    price_cents: float,
    tte_seconds: Optional[float],
    p: float,
    now: Optional[float] = None,
) -> float:
    """Apply the streaming bound: tighten-only (``min``) so the overlay can
    never inflate a claim the artifact already allowed."""
    b = streaming_bound(asset, side, price_cents, tte_seconds, now=now)
    if b is None:
        return p
    return min(float(p), b)
