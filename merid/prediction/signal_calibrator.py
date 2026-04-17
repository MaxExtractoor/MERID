"""H1: Signal Calibrator — Adaptive Per-Signal Brier Scoring

Tracks per-signal prediction accuracy; derives adaptive nudge multipliers
so better-calibrated signals get proportionally higher weight in _context_signal.

Usage
-----
  from merid.prediction.signal_calibrator import get_signal_calibrator

  cal = get_signal_calibrator()
  cal.record("polygon_regime", predicted_prob=0.72, outcome=1)
  weight = cal.weight("polygon_regime")  # 0.0–2.0 range

Brier score:  mean((predicted - actual)^2)  — lower is better.
  perfect predictor: 0.0
  random (always 0.5): 0.25
  worst case (always 1 when wrong): 1.0

Adaptive weight formula (per-signal):
  raw = max(0, 1 - brier / 0.25)   → 0..1
  With < MIN_OBS observations → neutral weight 1.0 (no bonus/penalty)
  All weights normalised so mean = 1.0 across all tracked signals.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from threading import RLock
from typing import Any, Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
MIN_OBS    = 10       # minimum observations before applying adaptive weight
WINDOW     = 200      # rolling window per signal
PERSIST_PATH = Path(os.getenv("MERID_SIGNAL_CALIBRATOR_PATH",
                               "data/signal_calibrator.json"))

SIGNAL_NAMES: List[str] = [
    "macro_vix", "macro_curve", "macro_cpi",
    "perp_funding", "perp_iv",
    "finnhub_release", "finnhub_sentiment",
    "polygon_regime", "polygon_pcr",
    "news_crypto", "news_macro",
    "trends_risk", "trends_crypto",
    "hurr_fl",
    "fg_contrarian",
    "messari_momentum",
    "av_gdp",
]


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class SignalStats:
    name: str
    observations: int = 0
    brier_sum: float = 0.0
    brier_sq_sum: float = 0.0   # for variance
    last_updated: float = field(default_factory=time.time)

    @property
    def brier_score(self) -> float:
        if self.observations == 0:
            return 0.25    # neutral
        return self.brier_sum / self.observations

    @property
    def brier_std(self) -> float:
        if self.observations < 2:
            return 0.0
        mean = self.brier_score
        var  = max(0, self.brier_sq_sum / self.observations - mean ** 2)
        return math.sqrt(var)

    @property
    def raw_weight(self) -> float:
        if self.observations < MIN_OBS:
            return 1.0    # neutral — not enough data
        return max(0.0, 1.0 - self.brier_score / 0.25)

    def record(self, predicted: float, outcome: float) -> None:
        err = (predicted - outcome) ** 2
        self.brier_sum += err
        self.brier_sq_sum += err ** 2
        self.observations += 1
        self.last_updated = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "observations": self.observations,
            "brier_score": round(self.brier_score, 4),
            "brier_std": round(self.brier_std, 4),
            "raw_weight": round(self.raw_weight, 4),
        }


# ── Calibrator ─────────────────────────────────────────────────────────────────

class SignalCalibrator:
    """Rolling Brier-score tracker with adaptive weight derivation."""

    def __init__(self) -> None:
        self._stats: Dict[str, SignalStats] = {
            name: SignalStats(name=name) for name in SIGNAL_NAMES
        }
        self._lock = RLock()
        self._load()

    # ── Public API ─────────────────────────────────────────────────────────────

    def record(self, signal: str, predicted_prob: float, outcome: float) -> None:
        """Record a single observation (predicted_prob in [0,1], outcome in {0,1})."""
        predicted_prob = max(0.0, min(1.0, float(predicted_prob)))
        outcome        = float(outcome)
        with self._lock:
            if signal not in self._stats:
                self._stats[signal] = SignalStats(name=signal)
            self._stats[signal].record(predicted_prob, outcome)
        logger.debug("calibrator: %s recorded pred=%.3f out=%.0f brier=%.4f",
                     signal, predicted_prob, outcome,
                     self._stats[signal].brier_score)

    def weight(self, signal: str) -> float:
        """
        Returns adaptive weight for a signal in ~[0, 2.0].
        If insufficient data → 1.0 (neutral). Well-calibrated → >1.0 (relative).
        """
        with self._lock:
            all_raw = [s.raw_weight for s in self._stats.values()]
            mean_raw = sum(all_raw) / max(1, len(all_raw))
            stat = self._stats.get(signal)
            if stat is None:
                return 1.0
            raw = stat.raw_weight
            return (raw / mean_raw) if mean_raw > 0 else 1.0

    def weights(self) -> Dict[str, float]:
        """Return normalised weights for all tracked signals."""
        with self._lock:
            all_raw = {n: s.raw_weight for n, s in self._stats.items()}
            mean_raw = sum(all_raw.values()) / max(1, len(all_raw))
            if mean_raw == 0:
                return {n: 1.0 for n in all_raw}
            return {n: r / mean_raw for n, r in all_raw.items()}

    def stats(self) -> Dict[str, Dict[str, Any]]:
        """Return all signal stats as dicts (for the API endpoint)."""
        with self._lock:
            w = self.weights()
            result = {}
            for name, stat in self._stats.items():
                d = stat.to_dict()
                d["adaptive_weight"] = round(w.get(name, 1.0), 4)
                result[name] = d
            return result

    def persist(self) -> None:
        """Save stats to disk for persistence across restarts."""
        try:
            PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {n: s.to_dict() for n, s in self._stats.items()}
            PERSIST_PATH.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.debug("calibrator: persist failed: %s", exc)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if not PERSIST_PATH.exists():
                return
            data = json.loads(PERSIST_PATH.read_text())
            for name, d in data.items():
                if name in self._stats:
                    obs     = int(d.get("observations", 0))
                    brier   = float(d.get("brier_score", 0.25))
                    self._stats[name].observations = obs
                    self._stats[name].brier_sum    = brier * obs
                logger.debug("calibrator: loaded %s obs=%d brier=%.4f",
                             name, self._stats[name].observations, brier)
        except Exception as exc:
            logger.debug("calibrator: load failed: %s", exc)


# ── Singleton ──────────────────────────────────────────────────────────────────

_calibrator: Optional[SignalCalibrator] = None
_cal_lock = RLock()


def get_signal_calibrator() -> SignalCalibrator:
    global _calibrator
    if _calibrator is None:
        with _cal_lock:
            if _calibrator is None:
                _calibrator = SignalCalibrator()
    return _calibrator
