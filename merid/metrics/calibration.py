"""Brier Score Calibration Store — Per-forecaster, per-bucket rolling calibration.

Tracks forecast accuracy using Brier scores so that consensus can weight
agents by calibration quality.  Persists to SQLite alongside other MERID data.

Brier score:  BS = (p_model - outcome)^2   where outcome in {0, 1}
Lower is better.  Perfect calibration = 0.0, coin-flip = 0.25.

Usage::

    store = get_calibration_store()
    store.record_forecast("edge_model_v1", "crypto", "KXBTC-26FEB-T95000",
                          p_model=0.62, timestamp=time.time())
    # ... later, when outcome is known ...
    store.resolve_outcome("KXBTC-26FEB-T95000", outcome=1)
    stats = store.get_brier("edge_model_v1", "crypto")
    weight = store.get_weight("edge_model_v1", "crypto")
"""

from __future__ import annotations

import threading
import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.metrics.calibration")

# Default DB path — anchored to project root so path is stable regardless of CWD
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "data", "calibration.db")

# EWMA decay factor for rolling Brier (0.95 = slow decay, recent matters more)
EWMA_ALPHA = 0.05

# Minimum *resolved* forecasts before a calibration weight is used.
# Set to 1 so the very first resolved outcome immediately moves the weight
# away from the coin-flip default — eliminating the multi-day cold-start
# window where all forecasters received equal weight regardless of skill.
MIN_FORECASTS_FOR_WEIGHT = 1

# Default weight for forecasters with zero resolved history (coin-flip prior).
DEFAULT_WEIGHT = 1.0

# Weight scaling: inverse Brier, clamped.  A perfect forecaster (BS=0) gets
# max weight; a coin-flip forecaster (BS=0.25) gets weight ~1.0.
WEIGHT_SCALE_FACTOR = 0.25  # normalizer: weight = WEIGHT_SCALE_FACTOR / max(brier, epsilon)
WEIGHT_EPSILON = 0.01       # floor to avoid division by zero
MAX_WEIGHT = 5.0
MIN_WEIGHT = 0.1


@dataclass
class BrierStats:
    """Aggregated Brier statistics for one (forecaster, bucket) pair."""
    forecaster_id: str
    bucket: str
    count: int = 0
    resolved_count: int = 0
    sum_brier: float = 0.0
    sum_brier_sq: float = 0.0
    ewma_brier: float = 0.25        # start at coin-flip
    last_updated: float = 0.0

    @property
    def mean_brier(self) -> float:
        if self.resolved_count == 0:
            return 0.25
        return self.sum_brier / self.resolved_count

    @property
    def std_brier(self) -> float:
        if self.resolved_count < 2:
            return 0.0
        # Sample variance: use (n-1) denominator via the Bessel-corrected identity
        # Var_sample = (sum_sq - n * mean^2) / (n - 1)
        n = self.resolved_count
        var = (self.sum_brier_sq - n * (self.mean_brier ** 2)) / (n - 1)
        return math.sqrt(max(0.0, var))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "forecaster_id": self.forecaster_id,
            "bucket": self.bucket,
            "count": self.count,
            "resolved_count": self.resolved_count,
            "mean_brier": round(self.mean_brier, 6),
            "ewma_brier": round(self.ewma_brier, 6),
            "std_brier": round(self.std_brier, 6),
            "last_updated": self.last_updated,
        }


@dataclass
class ForecastRecord:
    """A single forecast logged for later resolution."""
    forecaster_id: str
    bucket: str
    market_id: str
    p_model: float
    timestamp: float
    resolved: bool = False
    outcome: Optional[int] = None
    brier_score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "forecaster_id": self.forecaster_id,
            "bucket": self.bucket,
            "market_id": self.market_id,
            "p_model": round(self.p_model, 6),
            "timestamp": self.timestamp,
            "resolved": self.resolved,
            "outcome": self.outcome,
            "brier_score": round(self.brier_score, 6) if self.brier_score is not None else None,
        }


class CalibrationStore:
    """SQLite-backed Brier score tracking per forecaster per bucket.

    Thread-safe via SQLite's built-in locking.  Supports :memory: for tests.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or os.getenv("MERID_CALIBRATION_DB", _DEFAULT_DB_PATH)
        in_memory = self._db_path == ":memory:"
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=True if in_memory else False,
            timeout=10,  # Connection timeout
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")  # Wait up to 5s if DB is locked
        self._conn.execute("PRAGMA journal_mode=WAL")  # Enable WAL for better concurrency
        self._init_tables()

    def _init_tables(self) -> None:
        with self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS forecasts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    forecaster_id TEXT NOT NULL,
                    bucket      TEXT NOT NULL,
                    market_id   TEXT NOT NULL,
                    p_model     REAL NOT NULL,
                    timestamp   REAL NOT NULL,
                    resolved    INTEGER DEFAULT 0,
                    outcome     INTEGER,
                    brier_score REAL,
                    mode        TEXT NOT NULL DEFAULT 'live'
                );

                -- Add mode column to existing DBs that pre-date this migration
                -- (no-op if the column already exists; SQLite ignores ALTER TABLE
                -- errors inside executescript so we handle it via a separate exec)
                

                CREATE INDEX IF NOT EXISTS idx_forecasts_market
                    ON forecasts(market_id);
                CREATE INDEX IF NOT EXISTS idx_forecasts_forecaster_bucket
                    ON forecasts(forecaster_id, bucket);
                CREATE INDEX IF NOT EXISTS idx_forecasts_unresolved
                    ON forecasts(resolved) WHERE resolved = 0;
                CREATE INDEX IF NOT EXISTS idx_forecasts_mode
                    ON forecasts(mode);

                CREATE TABLE IF NOT EXISTS brier_stats (
                    forecaster_id TEXT NOT NULL,
                    bucket        TEXT NOT NULL,
                    count         INTEGER DEFAULT 0,
                    resolved_count INTEGER DEFAULT 0,
                    sum_brier     REAL DEFAULT 0.0,
                    sum_brier_sq  REAL DEFAULT 0.0,
                    ewma_brier    REAL DEFAULT 0.25,
                    last_updated  REAL DEFAULT 0.0,
                    PRIMARY KEY (forecaster_id, bucket)
                );
            """)
            # Migration: add mode column to DBs created before this column existed.
            # SQLite does not support IF NOT EXISTS on ALTER TABLE, so we catch
            # the OperationalError that fires when the column already exists.
            try:
                self._conn.execute("ALTER TABLE forecasts ADD COLUMN mode TEXT NOT NULL DEFAULT 'live'")
            except Exception:
                pass  # column already present

    # ── Record forecasts ─────────────────────────────────────────────────

    def record_forecast(
        self,
        forecaster_id: str,
        bucket: str,
        market_id: str,
        p_model: float,
        timestamp: Optional[float] = None,
        mode: str = "live",
    ) -> None:
        """Log a forecast for later resolution.

        Args:
            forecaster_id: Name of the forecasting model/agent.
            bucket: Category bucket (crypto, macro, politics, etc.).
            market_id: Kalshi market ticker.
            p_model: Predicted YES probability (0.0-1.0).
            timestamp: Unix timestamp (defaults to now).
            mode: Trading mode that produced this forecast (``'live'``,
                ``'paper'``, or ``'mock'``).  Paper/mock forecasts are stored
                separately and excluded from live consensus weight computation.
        """
        ts = timestamp or time.time()
        p_model = max(0.0, min(1.0, p_model))
        mode = mode.lower() if mode else "live"

        with self._conn:
            self._conn.execute(
                """INSERT INTO forecasts
                   (forecaster_id, bucket, market_id, p_model, timestamp, mode)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (forecaster_id, bucket, market_id, p_model, ts, mode),
            )
            # Upsert the count in brier_stats (mode-segregated: live counts
            # only, so paper sessions don't inflate live forecast counts).
            if mode == "live":
                self._conn.execute(
                    """INSERT INTO brier_stats (forecaster_id, bucket, count, last_updated)
                       VALUES (?, ?, 1, ?)
                       ON CONFLICT(forecaster_id, bucket)
                       DO UPDATE SET count = count + 1, last_updated = ?""",
                    (forecaster_id, bucket, ts, ts),
                )

    # ── Resolve outcomes ─────────────────────────────────────────────────

    def resolve_outcome(self, market_id: str, outcome: int) -> int:
        """Resolve all unresolved forecasts for a market and update Brier stats.

        Args:
            market_id: Kalshi market ticker.
            outcome: 1 if YES won, 0 if NO won.

        Returns:
            Number of forecasts resolved.
        """
        if outcome not in (0, 1):
            raise ValueError(f"outcome must be 0 or 1, got {outcome}")

        # Find all unresolved forecasts for this market
        rows = self._conn.execute(
            """SELECT id, forecaster_id, bucket, p_model, mode
               FROM forecasts
               WHERE market_id = ? AND resolved = 0""",
            (market_id,),
        ).fetchall()

        if not rows:
            return 0

        now = time.time()
        resolved = 0

        with self._conn:
            for row in rows:
                brier = (row["p_model"] - outcome) ** 2

                # Update the forecast record
                self._conn.execute(
                    """UPDATE forecasts
                       SET resolved = 1, outcome = ?, brier_score = ?
                       WHERE id = ?""",
                    (outcome, brier, row["id"]),
                )

                # Only update live Brier stats — paper/mock forecasts must not
                # contaminate the consensus weight used in live trading (H03 fix).
                if (row["mode"] if "mode" in row.keys() else "live") == "live":
                    self._update_brier_stats(
                        row["forecaster_id"], row["bucket"], brier, now
                    )
                resolved += 1

        logger.info(
            f"Resolved {resolved} forecasts for market {market_id} "
            f"(outcome={'YES' if outcome else 'NO'})"
        )
        return resolved

    def _update_brier_stats(
        self,
        forecaster_id: str,
        bucket: str,
        brier: float,
        ts: float,
    ) -> None:
        """Update the rolling Brier statistics for a (forecaster, bucket) pair."""
        row = self._conn.execute(
            """SELECT ewma_brier, sum_brier, sum_brier_sq, resolved_count
               FROM brier_stats
               WHERE forecaster_id = ? AND bucket = ?""",
            (forecaster_id, bucket),
        ).fetchone()

        if row is None:
            # Shouldn't happen if record_forecast was called first, but handle it
            ewma = brier
            sum_b = brier
            sum_bsq = brier ** 2
            resolved = 1
        else:
            ewma = (1 - EWMA_ALPHA) * row["ewma_brier"] + EWMA_ALPHA * brier
            sum_b = row["sum_brier"] + brier
            sum_bsq = row["sum_brier_sq"] + brier ** 2
            resolved = row["resolved_count"] + 1

        self._conn.execute(
            """INSERT INTO brier_stats
               (forecaster_id, bucket, resolved_count, sum_brier, sum_brier_sq,
                ewma_brier, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(forecaster_id, bucket)
               DO UPDATE SET
                 resolved_count = ?,
                 sum_brier = ?,
                 sum_brier_sq = ?,
                 ewma_brier = ?,
                 last_updated = ?""",
            (forecaster_id, bucket, resolved, sum_b, sum_bsq, ewma, ts,
             resolved, sum_b, sum_bsq, ewma, ts),
        )

    # ── Query methods ────────────────────────────────────────────────────

    def get_brier(self, forecaster_id: str, bucket: str) -> float:
        """Get the EWMA Brier score for a forecaster in a bucket.

        Returns 0.25 (coin-flip) if no resolved forecasts exist.
        """
        row = self._conn.execute(
            """SELECT ewma_brier FROM brier_stats
               WHERE forecaster_id = ? AND bucket = ?""",
            (forecaster_id, bucket),
        ).fetchone()
        if row is None:
            return 0.25
        return row["ewma_brier"]

    def get_stats(self, forecaster_id: str, bucket: str) -> BrierStats:
        """Get full Brier statistics for a (forecaster, bucket) pair."""
        row = self._conn.execute(
            """SELECT * FROM brier_stats
               WHERE forecaster_id = ? AND bucket = ?""",
            (forecaster_id, bucket),
        ).fetchone()
        if row is None:
            return BrierStats(forecaster_id=forecaster_id, bucket=bucket)
        return BrierStats(
            forecaster_id=row["forecaster_id"],
            bucket=row["bucket"],
            count=row["count"],
            resolved_count=row["resolved_count"],
            sum_brier=row["sum_brier"],
            sum_brier_sq=row["sum_brier_sq"],
            ewma_brier=row["ewma_brier"],
            last_updated=row["last_updated"],
        )

    def get_weight(self, forecaster_id: str, bucket: str) -> float:
        """Compute consensus weight from calibration quality.

        Weight is inversely proportional to Brier score:
        - Perfect (BS=0): MAX_WEIGHT
        - Coin-flip (BS=0.25): ~1.0
        - Bad (BS>0.25): < 1.0

        Returns DEFAULT_WEIGHT if insufficient history.
        """
        stats = self.get_stats(forecaster_id, bucket)
        if stats.resolved_count < MIN_FORECASTS_FOR_WEIGHT:
            return DEFAULT_WEIGHT
        brier = stats.ewma_brier
        raw = WEIGHT_SCALE_FACTOR / max(brier, WEIGHT_EPSILON)
        return max(MIN_WEIGHT, min(raw, MAX_WEIGHT))

    def get_all_forecaster_stats(self) -> List[BrierStats]:
        """Get stats for all (forecaster, bucket) pairs."""
        rows = self._conn.execute("SELECT * FROM brier_stats").fetchall()
        return [
            BrierStats(
                forecaster_id=r["forecaster_id"],
                bucket=r["bucket"],
                count=r["count"],
                resolved_count=r["resolved_count"],
                sum_brier=r["sum_brier"],
                sum_brier_sq=r["sum_brier_sq"],
                ewma_brier=r["ewma_brier"],
                last_updated=r["last_updated"],
            )
            for r in rows
        ]

    def get_forecaster_summary(self, forecaster_id: str) -> Dict[str, Any]:
        """Get a summary across all buckets for one forecaster."""
        rows = self._conn.execute(
            "SELECT * FROM brier_stats WHERE forecaster_id = ?",
            (forecaster_id,),
        ).fetchall()

        buckets = {}
        total_resolved = 0
        weighted_brier = 0.0

        for r in rows:
            bs = BrierStats(
                forecaster_id=r["forecaster_id"],
                bucket=r["bucket"],
                count=r["count"],
                resolved_count=r["resolved_count"],
                sum_brier=r["sum_brier"],
                sum_brier_sq=r["sum_brier_sq"],
                ewma_brier=r["ewma_brier"],
                last_updated=r["last_updated"],
            )
            buckets[bs.bucket] = bs.to_dict()
            total_resolved += bs.resolved_count
            weighted_brier += bs.ewma_brier * bs.resolved_count

        avg_brier = weighted_brier / total_resolved if total_resolved > 0 else 0.25

        return {
            "forecaster_id": forecaster_id,
            "total_forecasts": sum(r["count"] for r in rows),
            "total_resolved": total_resolved,
            "avg_ewma_brier": round(avg_brier, 6),
            "buckets": buckets,
        }

    def get_unresolved_markets(self) -> List[str]:
        """Get list of market IDs with unresolved forecasts."""
        rows = self._conn.execute(
            "SELECT DISTINCT market_id FROM forecasts WHERE resolved = 0"
        ).fetchall()
        return [r["market_id"] for r in rows]

    def get_forecasts_for_market(self, market_id: str) -> List[ForecastRecord]:
        """Get all forecasts for a specific market."""
        rows = self._conn.execute(
            "SELECT * FROM forecasts WHERE market_id = ? ORDER BY timestamp",
            (market_id,),
        ).fetchall()
        return [
            ForecastRecord(
                forecaster_id=r["forecaster_id"],
                bucket=r["bucket"],
                market_id=r["market_id"],
                p_model=r["p_model"],
                timestamp=r["timestamp"],
                resolved=bool(r["resolved"]),
                outcome=r["outcome"],
                brier_score=r["brier_score"],
            )
            for r in rows
        ]

    def list_forecasters(self) -> List[str]:
        """Get distinct forecaster IDs."""
        rows = self._conn.execute(
            "SELECT DISTINCT forecaster_id FROM brier_stats"
        ).fetchall()
        return [r["forecaster_id"] for r in rows]

    def get_avg_forecast_confidence(self, forecaster_id: str) -> float:
        """Average decisiveness of this forecaster's predictions.

        Computed as the mean of |p_model - 0.5| × 2 across all logged forecasts.
        This gives 0.0 for a pure coin-flip forecaster and approaches 1.0
        for a forecaster that consistently predicts near 0 or 1.
        """
        row = self._conn.execute(
            "SELECT AVG(ABS(p_model - 0.5) * 2) AS avg_conf "
            "FROM forecasts WHERE forecaster_id = ?",
            (forecaster_id,),
        ).fetchone()
        if row and row["avg_conf"] is not None:
            return float(row["avg_conf"])
        return 0.0

    def reset(self) -> None:
        """Clear all calibration data. Use for fresh start."""
        with self._conn:
            self._conn.execute("DELETE FROM forecasts")
            self._conn.execute("DELETE FROM brier_stats")
        logger.info("Calibration store reset")


# ── Singleton ────────────────────────────────────────────────────────────

_store: Optional[CalibrationStore] = None
_store_lock = threading.Lock()


def get_calibration_store(db_path: Optional[str] = None) -> CalibrationStore:
    """Get or create the singleton CalibrationStore."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = CalibrationStore(db_path=db_path)
    return _store
