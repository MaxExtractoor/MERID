"""C7: Implied vs Realized Probability Tracker

Records model-implied probability at signal time vs the binary outcome on
resolution, then aggregates accuracy metrics per market family (event series).

Usage:
    tracker = get_prob_accuracy_tracker()
    tracker.record_prediction("KXBTC-24DEC31-B90000", model_prob=0.63, market_family="KXBTC")
    # ... on resolution:
    tracker.record_outcome("KXBTC-24DEC31-B90000", resolved_yes=True)
    report = tracker.family_report()
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_DB_PATH = Path("data/prob_accuracy.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prob_predictions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL,
    family      TEXT NOT NULL,
    model_prob  REAL NOT NULL,
    recorded_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS prob_outcomes (
    ticker       TEXT PRIMARY KEY,
    family       TEXT NOT NULL,
    resolved_yes INTEGER NOT NULL,
    resolved_at  REAL NOT NULL
);
"""


@dataclass
class FamilyAccuracy:
    family: str
    n_resolved: int
    mean_abs_error: float
    mean_brier: float
    bias: float
    well_calibrated: bool


class ProbAccuracyTracker:
    """Records implied model probabilities and actual binary outcomes.

    Thread-safe.  Uses SQLite for persistence across restarts.
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path
        self._lock = Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        import time as _time
        print(f"[IO-DEBUG] prob_accuracy_tracker: Connecting to SQLite DB at {_time.time()}")
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        print(f"[IO-DEBUG] prob_accuracy_tracker: Connected to SQLite DB at {_time.time()}")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.executescript(_SCHEMA)

    # ── Recording ─────────────────────────────────────────────────────────

    def record_prediction(
        self,
        ticker: str,
        model_prob: float,
        market_family: Optional[str] = None,
    ) -> None:
        """Record a model-implied probability at signal time.

        ``market_family`` defaults to the first segment of *ticker* (e.g. ``KXBTC``).
        """
        family = market_family or (ticker.split("-")[0] if "-" in ticker else ticker)
        now = time.time()
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    "INSERT INTO prob_predictions (ticker, family, model_prob, recorded_at) VALUES (?,?,?,?)",
                    (ticker, family, float(model_prob), now),
                )
        except Exception as exc:
            logger.warning("prob_accuracy: record_prediction failed for %s: %s", ticker, exc)

    def record_outcome(
        self,
        ticker: str,
        resolved_yes: bool,
        market_family: Optional[str] = None,
    ) -> None:
        """Record the binary resolution of a market."""
        family = market_family or (ticker.split("-")[0] if "-" in ticker else ticker)
        now = time.time()
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    """INSERT INTO prob_outcomes (ticker, family, resolved_yes, resolved_at)
                       VALUES (?,?,?,?)
                       ON CONFLICT(ticker) DO UPDATE
                       SET resolved_yes=excluded.resolved_yes, resolved_at=excluded.resolved_at""",
                    (ticker, family, int(resolved_yes), now),
                )
        except Exception as exc:
            logger.warning("prob_accuracy: record_outcome failed for %s: %s", ticker, exc)

    # ── Analytics ─────────────────────────────────────────────────────────

    def family_report(self) -> List[FamilyAccuracy]:
        """Return calibration accuracy per market family for all resolved markets."""
        try:
            with self._lock, self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT p.family,
                           AVG(p.model_prob)                         AS avg_pred,
                           AVG(o.resolved_yes)                       AS avg_outcome,
                           AVG(ABS(p.model_prob - o.resolved_yes))   AS mae,
                           AVG((p.model_prob - o.resolved_yes) * (p.model_prob - o.resolved_yes)) AS brier,
                           AVG(p.model_prob - o.resolved_yes)        AS bias,
                           COUNT(*)                                   AS n
                    FROM prob_predictions p
                    INNER JOIN prob_outcomes o ON p.ticker = o.ticker
                    GROUP BY p.family
                    """
                ).fetchall()
        except Exception as exc:
            logger.warning("prob_accuracy: family_report failed: %s", exc)
            return []

        result: List[FamilyAccuracy] = []
        for row in rows:
            result.append(
                FamilyAccuracy(
                    family=row["family"],
                    n_resolved=row["n"],
                    mean_abs_error=round(row["mae"], 4),
                    mean_brier=round(row["brier"], 4),
                    bias=round(row["bias"], 4),
                    well_calibrated=row["mae"] < 0.10,
                )
            )
        return sorted(result, key=lambda r: r.family)

    def ticker_detail(self, ticker: str) -> Dict[str, Any]:
        """Return all recorded predictions and the outcome (if any) for a ticker."""
        with self._lock, self._conn() as conn:
            preds = conn.execute(
                "SELECT model_prob, recorded_at FROM prob_predictions WHERE ticker=? ORDER BY recorded_at",
                (ticker,),
            ).fetchall()
            outcome_row = conn.execute(
                "SELECT resolved_yes, resolved_at FROM prob_outcomes WHERE ticker=?",
                (ticker,),
            ).fetchone()
        return {
            "ticker": ticker,
            "predictions": [{"prob": r["model_prob"], "at": r["recorded_at"]} for r in preds],
            "outcome": {"resolved_yes": bool(outcome_row["resolved_yes"]), "at": outcome_row["resolved_at"]}
            if outcome_row else None,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the full report for API consumption."""
        return {
            "families": [
                {
                    "family": f.family,
                    "n_resolved": f.n_resolved,
                    "mean_abs_error": f.mean_abs_error,
                    "mean_brier": f.mean_brier,
                    "bias": f.bias,
                    "well_calibrated": f.well_calibrated,
                }
                for f in self.family_report()
            ]
        }


# ── Singleton ──────────────────────────────────────────────────────────────

_tracker: Optional[ProbAccuracyTracker] = None
_tracker_lock = Lock()


def get_prob_accuracy_tracker() -> ProbAccuracyTracker:
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = ProbAccuracyTracker()
    return _tracker
