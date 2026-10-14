"""Artifact-independent model-calibration telemetry.

2026-10-14 audit: the only record of the model probability next to the
executable price was ``logs/empirical_cal_observations.jsonl``, which is
written solely inside a matched EPC cell and stops entirely once the EPC
artifact goes stale.  Scoring it against settlements showed the model has
real signal (residual slope 1.34, t=4.7) while the EPC overlay did not, so
the model probability must stay measurable regardless of overlay state.

One record per (ticker, side, TTE minute) with the model probability (after
market anchor + walk-forward calibration, before any EPC substitution or
tail caps), the executable entry price and TTE.  Joined to
``logs/settlement_outcomes.jsonl`` by ``scripts/model_calibration_report.py``.

``MERID_MODEL_CAL_LOG_ENABLED=0`` disables; ``MERID_MODEL_CAL_LOG_PATH``
overrides the destination.  Never raises.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.model_calibration_log")

_ROOT = Path(__file__).resolve().parents[2]
_lock = threading.Lock()
_seen: Dict[Tuple[str, str, int], float] = {}


def enabled() -> bool:
    return os.environ.get("MERID_MODEL_CAL_LOG_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")


def log_path() -> Path:
    p = os.environ.get("MERID_MODEL_CAL_LOG_PATH")
    return Path(p) if p else _ROOT / "logs" / "model_calibration_observations.jsonl"


def log_model_observation(
    *,
    ticker: Optional[str],
    asset: str,
    side: str,
    p_model: float,
    entry_price_cents: float,
    seconds_to_expiry: float,
    fee_cents: Optional[float],
) -> None:
    if not enabled() or not ticker or side not in ("yes", "no"):
        return
    try:
        px = float(entry_price_cents)
        tte = float(seconds_to_expiry)
        p = float(p_model)
        if not (0.0 < px < 100.0) or tte <= 0.0 or not (0.0 <= p <= 1.0):
            return
        key = (str(ticker), side, int(tte // 60))
        now = time.time()
        with _lock:
            if key in _seen:
                return
            _seen[key] = now
            if len(_seen) > 20000:
                cutoff = now - 3600
                for k in [k for k, t in _seen.items() if t < cutoff]:
                    del _seen[k]
        fee = float(fee_cents) if fee_cents is not None else None
        rec = {
            "ts": now,
            "ticker": ticker,
            "asset": asset,
            "side": side,
            "p_model": round(p, 5),
            "entry_price_cents": round(px, 2),
            "seconds_to_expiry": round(tte, 1),
            "fee_cents": None if fee is None else round(fee, 3),
            "gross_edge_c": round(100.0 * p - px, 3),
        }
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as exc:  # telemetry must never break trading
        logger.debug("[MODEL-CAL] observation log failed: %s", exc)


def reset_for_tests() -> None:
    with _lock:
        _seen.clear()
