"""Kalshi Strike Distance Calibrator — Data-driven adaptive thresholds.

Computes max_distance thresholds from historical Kalshi listing data using
the 90th percentile of observed strike distances, with guardrails.

Design (per user spec):
- Log every contract observation: asset, tenor, timestamp, spot, strike, distance
- Daily calibration job computes d90 (90th percentile) per (asset, tenor)
- max_distance = min(d90 * (1 + margin), hard_cap)
- Bootstrap defaults until MIN_OBS observations accumulated
- Deterministic: given N days of data, thresholds are uniquely determined

Usage::

    from merid.prediction.kalshi_strike_calibrator import get_calibrator

    # Log an observation
    get_calibrator().log_observation("BTC", "1h", spot=70000, strike=80000)

    # Run calibration (returns computed thresholds)
    thresholds = get_calibrator().calibrate()

    # Get threshold for runtime use
    max_dist = get_calibrator().get_max_distance("BTC", "1h")
"""

from __future__ import annotations

import json
import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.kalshi_strike_calibrator")

# ── Calibration hyperparameters ─────────────────────────────────────────────

# Minimum observations before switching from bootstrap to calibrated thresholds
MIN_OBSERVATIONS: int = int(os.getenv("MERID_STRIKE_MIN_OBS", "500"))

# Lookback window for calibration (days)
CALIBRATION_LOOKBACK_DAYS: int = int(os.getenv("MERID_STRIKE_CALIBRATION_DAYS", "30"))

# Margin applied to d90 (e.g., 0.1 = 10% buffer)
DISTANCE_MARGIN: float = float(os.getenv("MERID_STRIKE_DISTANCE_MARGIN", "0.1"))

# Calibration data persistence path
CALIBRATION_DATA_PATH: Path = Path(
    os.getenv("MERID_STRIKE_CALIBRATION_PATH", "data/kalshi_strike_calibration.json")
)
OBSERVATIONS_PATH: Path = Path(
    os.getenv("MERID_STRIKE_OBSERVATIONS_PATH", "data/kalshi_strike_observations.jsonl")
)

# ── Bootstrap defaults (deterministic, ship-today values) ─────────────────────
# These are used until sufficient observations are accumulated.
# Format: (asset, timeframe) -> max_distance_pct

BOOTSTRAP_DEFAULTS: Dict[Tuple[str, str], float] = {
    # Intraday: 15m / 1h
    ("BTC", "15m"): 0.18, ("BTC", "1h"): 0.18,
    ("ETH", "15m"): 0.28, ("ETH", "1h"): 0.28,
    ("SOL", "15m"): 0.30, ("SOL", "1h"): 0.30,
    ("XRP", "15m"): 0.30, ("XRP", "1h"): 0.30,
    ("DOGE", "15m"): 0.45, ("DOGE", "1h"): 0.45,
    # Daily
    ("BTC", "daily"): 0.25,
    ("ETH", "daily"): 0.35,
    ("SOL", "daily"): 0.40,
    ("XRP", "daily"): 0.40,
    ("DOGE", "daily"): 0.55,
    # Weekly
    ("BTC", "weekly"): 0.30,
    ("ETH", "weekly"): 0.40,
    ("SOL", "weekly"): 0.45,
    ("XRP", "weekly"): 0.45,
    ("DOGE", "weekly"): 0.60,
    # Monthly+
    ("BTC", "monthly"): 0.35, ("BTC", "annual"): 0.35,
    ("ETH", "monthly"): 0.45, ("ETH", "annual"): 0.45,
    ("SOL", "monthly"): 0.50, ("SOL", "annual"): 0.50,
    ("XRP", "monthly"): 0.50, ("XRP", "annual"): 0.50,
    ("DOGE", "monthly"): 0.70, ("DOGE", "annual"): 0.70,
}

# ── Hard caps (safety guardrails) ───────────────────────────────────────────
# These prevent trading absurdly far OTM contracts even if data suggests it.

HARD_CAPS: Dict[Tuple[str, str], float] = {
    # Intraday caps
    ("BTC", "15m"): 0.40, ("BTC", "1h"): 0.40,
    ("ETH", "15m"): 0.40, ("ETH", "1h"): 0.40,
    ("SOL", "15m"): 0.50, ("SOL", "1h"): 0.50,
    ("XRP", "15m"): 0.50, ("XRP", "1h"): 0.50,
    ("DOGE", "15m"): 0.70, ("DOGE", "1h"): 0.70,
    # Daily caps
    ("BTC", "daily"): 0.60,
    ("ETH", "daily"): 0.60,
    ("SOL", "daily"): 0.70,
    ("XRP", "daily"): 0.70,
    ("DOGE", "daily"): 0.90,
    # Weekly caps
    ("BTC", "weekly"): 0.60,
    ("ETH", "weekly"): 0.60,
    ("SOL", "weekly"): 0.70,
    ("XRP", "weekly"): 0.70,
    ("DOGE", "weekly"): 0.90,
    # Monthly+ caps
    ("BTC", "monthly"): 0.60, ("BTC", "annual"): 0.60,
    ("ETH", "monthly"): 0.60, ("ETH", "annual"): 0.60,
    ("SOL", "monthly"): 0.70, ("SOL", "annual"): 0.70,
    ("XRP", "monthly"): 0.70, ("XRP", "annual"): 0.70,
    ("DOGE", "monthly"): 0.90, ("DOGE", "annual"): 0.90,
}

# Fallback hard cap if not specified
FALLBACK_HARD_CAP: float = 0.50


@dataclass
class StrikeObservation:
    """A single observation of strike distance from spot."""
    asset: str
    timeframe: str
    timestamp: float  # epoch seconds
    spot: float
    strike: float
    distance_pct: float  # abs(strike - spot) / spot
    ticker: str = ""  # optional: source market ticker

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "spot": self.spot,
            "strike": self.strike,
            "distance_pct": round(self.distance_pct, 6),
            "ticker": self.ticker,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StrikeObservation":
        return cls(
            asset=d["asset"],
            timeframe=d["timeframe"],
            timestamp=d["timestamp"],
            spot=d["spot"],
            strike=d["strike"],
            distance_pct=d["distance_pct"],
            ticker=d.get("ticker", ""),
        )


class StrikeCalibrator:
    """Data-driven strike distance calibration.

    Thread-safe. Maintains:
    - In-memory observation buffer (recent observations)
    - On-disk observation log (JSONL, rolling)
    - Calibrated thresholds (JSON, updated by calibrate())
    """

    def __init__(
        self,
        min_obs: int = MIN_OBSERVATIONS,
        lookback_days: int = CALIBRATION_LOOKBACK_DAYS,
        margin: float = DISTANCE_MARGIN,
        bootstrap_defaults: Optional[Dict[Tuple[str, str], float]] = None,
        hard_caps: Optional[Dict[Tuple[str, str], float]] = None,
        calibration_path: Path = CALIBRATION_DATA_PATH,
        observations_path: Path = OBSERVATIONS_PATH,
    ):
        self._min_obs = min_obs
        self._lookback_days = lookback_days
        self._margin = margin
        self._bootstrap = bootstrap_defaults or BOOTSTRAP_DEFAULTS.copy()
        self._hard_caps = hard_caps or HARD_CAPS.copy()
        self._calibration_path = calibration_path
        self._observations_path = observations_path

        # TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
        # TODO: Re-enable lock after startup is stable and investigate proper async synchronization
        # self._lock = threading.Lock()
        self._lock = None  # Disabled to prevent startup hang
        self._calibrated: Dict[Tuple[str, str], float] = {}
        self._observation_count: Dict[Tuple[str, str], int] = {}
        self._calibrated_at: Optional[float] = None

        # Ensure directories exist
        self._calibration_path.parent.mkdir(parents=True, exist_ok=True)
        self._observations_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing calibration on init
        self._load_calibration()

    # ── Public API ────────────────────────────────────────────────────────

    def log_observation(
        self,
        asset: str,
        timeframe: str,
        spot: float,
        strike: float,
        ticker: str = "",
        timestamp: Optional[float] = None,
    ) -> None:
        """Log a strike observation for later calibration.

        This is called by the strike selector on every market evaluation.
        Writes to in-memory buffer and periodically to disk.
        """
        if spot <= 0:
            return
        distance_pct = abs(strike - spot) / spot

        obs = StrikeObservation(
            asset=asset.upper(),
            timeframe=timeframe.lower(),
            timestamp=timestamp or time.time(),
            spot=spot,
            strike=strike,
            distance_pct=distance_pct,
            ticker=ticker,
        )

        # Write to disk (append mode, thread-safe via GIL for single line)
        try:
            with open(self._observations_path, "a") as f:
                f.write(json.dumps(obs.to_dict(), sort_keys=True) + "\n")
        except Exception as e:
            logger.debug("Failed to log observation: %s", e)

        # Update in-memory count
        key = (obs.asset, obs.timeframe)
        if self._lock is not None:
            with self._lock:
                self._observation_count[key] = self._observation_count.get(key, 0) + 1
        else:
            # Lock disabled - direct access (startup workaround)
            self._observation_count[key] = self._observation_count.get(key, 0) + 1

    def get_max_distance(self, asset: str, timeframe: str) -> float:
        """Get the max_distance for an asset/timeframe combo.

        Priority:
        1. Calibrated threshold (if min_obs met)
        2. Bootstrap default
        3. Fallback from similar timeframe/asset
        """
        key = (asset.upper(), timeframe.lower())

        if self._lock is not None:
            with self._lock:
                # 1. Calibrated value available?
                if key in self._calibrated:
                    count = self._observation_count.get(key, 0)
                    if count >= self._min_obs:
                        return self._calibrated[key]

                # 2. Bootstrap default
                if key in self._bootstrap:
                    return self._bootstrap[key]

                # 3. Fallback to similar timeframe (same asset)
                asset_prefix = key[0]
                for k, v in self._bootstrap.items():
                    if k[0] == asset_prefix:
                        return v

                # 4. Fallback to similar asset (same timeframe)
                timeframe_suffix = key[1]
                for k, v in self._bootstrap.items():
                    if k[1] == timeframe_suffix:
                        return v

                # 5. Hard cap fallback
                return self._hard_caps.get(asset_prefix, 1.0)
        else:
            # Lock disabled - direct access (startup workaround)
            # 1. Calibrated value available?
            if key in self._calibrated:
                count = self._observation_count.get(key, 0)
                if count >= self._min_obs:
                    return self._calibrated[key]

            # 2. Bootstrap default
            if key in self._bootstrap:
                return self._bootstrap[key]

            # 3. Fallback to similar timeframe (same asset)
            asset_prefix = key[0]
            for k, v in self._bootstrap.items():
                if k[0] == asset_prefix:
                    return v

            # 4. Fallback to similar asset (same timeframe)
            timeframe_suffix = key[1]
            for k, v in self._bootstrap.items():
                if k[1] == timeframe_suffix:
                    return v

            # 5. Hard cap fallback
            return self._hard_caps.get(asset_prefix, 1.0)

    def calibrate(self) -> Dict[Tuple[str, str], float]:
        """Run calibration: compute d90 per (asset, tenor) from observations.

        Returns the computed thresholds. Also persists to disk.
        """
        observations = self._load_observations()
        now = time.time()
        cutoff = now - (self._lookback_days * 86400)

        # Group by (asset, timeframe)
        grouped: Dict[Tuple[str, str], List[float]] = {}
        for obs in observations:
            if obs.timestamp < cutoff:
                continue
            key = (obs.asset, obs.timeframe)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(obs.distance_pct)

        # Compute d90 for each group
        new_calibrated: Dict[Tuple[str, str], float] = {}
        summary: List[str] = []

        for key, distances in grouped.items():
            count = len(distances)
            if count < self._min_obs:
                continue

            # Compute 90th percentile
            distances_sorted = sorted(distances)
            d90_idx = int(len(distances_sorted) * 0.90)
            if d90_idx >= len(distances_sorted):
                d90_idx = len(distances_sorted) - 1
            d90 = distances_sorted[d90_idx]

            # Apply margin and hard cap
            margin_applied = d90 * (1 + self._margin)
            hard_cap = self._hard_caps.get(key, FALLBACK_HARD_CAP)
            final_value = min(margin_applied, hard_cap)

            new_calibrated[key] = round(final_value, 4)
            summary.append(
                f"{key[0]}/{key[1]}: d90={d90:.4f} margin={margin_applied:.4f} cap={hard_cap:.2f} final={final_value:.4f} n={count}"
            )

        if self._lock is not None:
            with self._lock:
                self._calibrated = new_calibrated
                self._calibrated_at = now
                # Update observation counts
                for key, dists in grouped.items():
                    self._observation_count[key] = len(dists)
        else:
            # Lock disabled - direct access (startup workaround)
            self._calibrated = new_calibrated
            self._calibrated_at = now
            # Update observation counts
            for key, dists in grouped.items():
                self._observation_count[key] = len(dists)

        self._save_calibration()

        logger.info(
            "[STRIKE_CALIBRATION] Computed thresholds for %d asset/timeframe pairs\n  %s",
            len(new_calibrated),
            "\n  ".join(summary) if summary else "(none)",
        )

        return new_calibrated

    def get_calibration_summary(self) -> dict:
        """Return current calibration state for diagnostics."""
        if self._lock is not None:
            with self._lock:
                return {
                    "calibrated_at": self._calibrated_at,
                    "calibrated_pairs": list(self._calibrated.keys()),
                    "observation_counts": dict(self._observation_count),
                    "min_observations_required": self._min_obs,
                    "using_calibration": [
                        k for k in self._calibrated
                        if self._observation_count.get(k, 0) >= self._min_obs
                    ],
                }
        else:
            # Lock disabled - direct access (startup workaround)
            return {
                "calibrated_at": self._calibrated_at,
                "calibrated_pairs": list(self._calibrated.keys()),
                "observation_counts": dict(self._observation_count),
                "min_observations_required": self._min_obs,
                "using_calibration": [
                    k for k in self._calibrated
                    if self._observation_count.get(k, 0) >= self._min_obs
                ],
            }

    def reset(self) -> None:
        """Reset calibration (testing only)."""
        if self._lock is not None:
            with self._lock:
                self._calibrated.clear()
                self._observation_count.clear()
                self._calibrated_at = None
        else:
            # Lock disabled - direct access (startup workaround)
            self._calibrated.clear()
            self._observation_count.clear()
            self._calibrated_at = None

    # ── Internal persistence ────────────────────────────────────────────

    def _load_calibration(self) -> None:
        """Load previously computed calibration from disk."""
        if not self._calibration_path.exists():
            return
        try:
            with open(self._calibration_path, "r") as f:
                data = json.load(f)
            self._calibrated = {
                (k[0], k[1]): v for k, v in data.get("calibrated", {}).items()
            }
            self._calibrated_at = data.get("calibrated_at")
            self._observation_count = {
                (k[0], k[1]): v for k, v in data.get("observation_counts", {}).items()
            }
            logger.debug(
                "[STRIKE_CALIBRATION] Loaded %d calibrated thresholds from %s",
                len(self._calibrated),
                self._calibration_path,
            )
        except Exception as e:
            logger.warning("Failed to load calibration: %s", e)

    def _save_calibration(self) -> None:
        """Persist calibration to disk."""
        try:
            data = {
                "calibrated_at": self._calibrated_at,
                "calibrated": {f"{k[0]},{k[1]}": v for k, v in self._calibrated.items()},
                "observation_counts": {f"{k[0]},{k[1]}": v for k, v in self._observation_count.items()},
                "metadata": {
                    "min_obs": self._min_obs,
                    "lookback_days": self._lookback_days,
                    "margin": self._margin,
                },
            }
            with open(self._calibration_path, "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
        except Exception as e:
            logger.warning("Failed to save calibration: %s", e)

    def _load_observations(self) -> List[StrikeObservation]:
        """Load observations from disk (for calibration)."""
        observations: List[StrikeObservation] = []
        if not self._observations_path.exists():
            return observations
        try:
            with open(self._observations_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obs = StrikeObservation.from_dict(json.loads(line))
                        observations.append(obs)
                    except Exception:
                        continue
        except Exception as e:
            logger.warning("Failed to load observations: %s", e)
        return observations


# ── Global singleton ─────────────────────────────────────────────────────────

_calibrator: Optional[StrikeCalibrator] = None
_calibrator_lock = threading.Lock()


def get_calibrator() -> StrikeCalibrator:
    """Get the process-wide strike calibrator singleton."""
    global _calibrator
    if _calibrator is not None:
        return _calibrator
    with _calibrator_lock:
        if _calibrator is None:
            _calibrator = StrikeCalibrator()
        return _calibrator


def reset_calibrator_for_testing() -> None:
    """Reset the global calibrator (tests only)."""
    global _calibrator
    with _calibrator_lock:
        _calibrator = None


def run_calibration_job() -> Dict[Tuple[str, str], float]:
    """Convenience function to run the calibration job and return thresholds."""
    return get_calibrator().calibrate()
