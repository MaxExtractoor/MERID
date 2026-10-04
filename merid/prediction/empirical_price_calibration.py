"""Empirical price-calibration overlay (favorite-longshot correction).

Signal-quality audit 2026-10-04: the 15m Kalshi price is systematically
mis-calibrated.  NO-side favorites (held 50-89c) with 3-7 minutes to expiry
settle in-the-money more often than their price implies.  Walk-forward over
four train/test splits (Sep 2026) realized +6.8c to +9.4c per trade net of
fee out of sample, every split with a positive 95% lower bound.  The
Bachelier model cannot see this: it is shrunk toward the market mid
(MERID_MARKET_ANCHOR_*) on the premise that the book is calibrated.

This module serves a frozen, fitted artifact
(``data/empirical_price_calibration.json``, produced by
``scripts/fit_empirical_price_calibration.py``).  For a side whose held
price and TTE fall in a VALIDATED cell, it returns the beta-shrunk empirical
win rate.  The decision layer then substitutes that probability for the
side; every downstream gate (threshold, depth, conviction, regime,
book-flow, evidence caps, EV gate, router firewall) still applies.

Modes (``MERID_EMPIRICAL_CAL_MODE``):
    off     - no lookup
    shadow  - lookup + telemetry only; probabilities unchanged (default)
    live    - matched side's probability replaced by the cell estimate

The artifact is reloaded when its mtime changes, so a refit takes effect
without a restart.  A missing/invalid/stale artifact fails closed (no match).
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.empirical_price_calibration")

_ROOT = Path(__file__).resolve().parents[2]
_lock = threading.Lock()
_cache: Dict[str, Any] = {"path": None, "mtime": None, "cells": {}, "meta": {}}


def mode() -> str:
    m = os.environ.get("MERID_EMPIRICAL_CAL_MODE", "shadow").strip().lower()
    return m if m in ("off", "shadow", "live") else "off"


def artifact_path() -> Path:
    p = os.environ.get("MERID_EMPIRICAL_CAL_PATH")
    return Path(p) if p else _ROOT / "data" / "empirical_price_calibration.json"


def max_artifact_age_days() -> float:
    try:
        return float(os.environ.get("MERID_EMPIRICAL_CAL_MAX_AGE_DAYS", "14"))
    except ValueError:
        return 14.0


@dataclass(frozen=True)
class CellEstimate:
    cell_id: str
    side: str
    p: float
    n: int
    edge_c: float
    edge_lcb_c: float
    avg_price_c: float


def _load() -> Tuple[Dict[Tuple[str, int, int], Dict[str, Any]], Dict[str, Any]]:
    path = artifact_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}, {}
    with _lock:
        if _cache["path"] == str(path) and _cache["mtime"] == mtime:
            return _cache["cells"], _cache["meta"]
        cells: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
        meta: Dict[str, Any] = {}
        try:
            art = json.loads(path.read_text(encoding="utf-8"))
            if art.get("schema") != "empirical_price_calibration/v1":
                raise ValueError(f"unexpected schema {art.get('schema')!r}")
            for c in art.get("cells") or []:
                if not c.get("validated"):
                    continue
                key = (str(c["side"]), int(c["price_lo_c"]), int(c["tte_min_s"]) // 60)
                cells[key] = c
            meta = {k: art.get(k) for k in ("fitted_at_utc", "sample_start", "sample_end", "n_observations", "params")}
            meta["mtime"] = mtime
        except Exception as exc:
            logger.warning("[EMPIRICAL-CAL] failed to load %s: %s", path, exc)
            cells, meta = {}, {}
        _cache.update(path=str(path), mtime=mtime, cells=cells, meta=meta)
        if cells:
            logger.info(
                "[EMPIRICAL-CAL] loaded %d validated cells from %s (fitted %s)",
                len(cells), path, meta.get("fitted_at_utc"),
            )
        return cells, meta


def _stale(meta: Dict[str, Any]) -> bool:
    mt = meta.get("mtime")
    if mt is None:
        return True
    return (time.time() - float(mt)) > max_artifact_age_days() * 86400.0


def lookup(side: str, held_price_cents: float, seconds_to_expiry: float) -> Optional[CellEstimate]:
    """Return the validated cell estimate for a held side, or None."""
    if mode() == "off":
        return None
    if side not in ("yes", "no") or held_price_cents is None or seconds_to_expiry is None:
        return None
    try:
        px = float(held_price_cents)
        tte = float(seconds_to_expiry)
    except (TypeError, ValueError):
        return None
    if not (1.0 <= px <= 99.0) or tte <= 0:
        return None
    cells, meta = _load()
    if not cells or _stale(meta):
        return None
    c = cells.get((side, int(px // 10) * 10, int(tte // 60)))
    if c is None:
        return None
    # The mispricing is an additive uplift over price (win_rate - price is
    # ~flat inside a 10c bucket), so the cell's shrunk uplift is applied to
    # the actual held price rather than publishing the bucket-average p.
    uplift = float(c["p_shrunk"]) - float(c["avg_price_c"]) / 100.0
    p = max(0.01, min(0.99, px / 100.0 + uplift))
    return CellEstimate(
        cell_id=str(c["cell_id"]),
        side=side,
        p=p,
        n=int(c["n"]),
        edge_c=float(c["edge_c"]),
        edge_lcb_c=float(c["edge_lcb_c"]),
        avg_price_c=float(c["avg_price_c"]),
    )


_obs_lock = threading.Lock()
_obs_seen: Dict[Tuple[str, str, int], float] = {}


def _obs_path() -> Path:
    p = os.environ.get("MERID_EMPIRICAL_CAL_LOG_PATH")
    return Path(p) if p else _ROOT / "logs" / "empirical_cal_observations.jsonl"


def log_observation(
    *,
    ticker: Optional[str],
    asset: str,
    side: str,
    mode: str,
    held_price_cents: float,
    seconds_to_expiry: float,
    est: CellEstimate,
    p_model: float,
    applied: bool,
    fee_cents: Optional[float],
) -> None:
    """One record per (ticker, side, TTE minute): what the overlay saw and
    whether it acted.  Joined to settlement offline to score shadow/live.
    Never raises."""
    try:
        key = (str(ticker), side, int(seconds_to_expiry // 60))
        now = time.time()
        with _obs_lock:
            if key in _obs_seen:
                return
            _obs_seen[key] = now
            if len(_obs_seen) > 20000:
                cutoff = now - 3600
                for k in [k for k, t in _obs_seen.items() if t < cutoff]:
                    del _obs_seen[k]
        fee = float(fee_cents) if fee_cents is not None else 1.5
        rec = {
            "ts": now,
            "ticker": ticker,
            "asset": asset,
            "side": side,
            "mode": mode,
            "cell_id": est.cell_id,
            "held_price_cents": round(held_price_cents, 2),
            "seconds_to_expiry": round(seconds_to_expiry, 1),
            "p_model": round(p_model, 5),
            "p_empirical": round(est.p, 5),
            "ev_model_c": round(100.0 * p_model - held_price_cents - fee, 3),
            "ev_empirical_c": round(100.0 * est.p - held_price_cents - fee, 3),
            "cell_edge_lcb_c": round(est.edge_lcb_c, 3),
            "cell_avg_price_c": round(est.avg_price_c, 3),
            "adj_lcb_c": round(
                est.edge_lcb_c - (held_price_cents - est.avg_price_c), 3
            ),
            "applied": applied,
        }
        path = _obs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _obs_lock, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as exc:  # telemetry must never break trading
        logger.debug("[EMPIRICAL-CAL] observation log failed: %s", exc)


def artifact_meta() -> Dict[str, Any]:
    _, meta = _load()
    return dict(meta)


def reset_cache_for_tests() -> None:
    with _lock:
        _cache.update(path=None, mtime=None, cells={}, meta={})
