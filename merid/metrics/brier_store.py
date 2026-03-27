"""Brier score persistence with SQLite WAL mode and SHADOW/LIVE gating.

Provides:
- ``BrierStore``: SQLite-backed store for Brier scores.
  * WAL mode enabled for better concurrent read performance.
  * Scores are stored per agent and per market.
- ``BrierGate``: SHADOW→LIVE promotion gate based on Brier thresholds.
  * An agent in SHADOW mode is promoted to LIVE only when its rolling
    Brier score is below the configured threshold (lower = better).
  * If the Brier score rises above the demotion threshold the agent is
    moved back to SHADOW.

Thresholds (defaults, can be overridden):
  - ``shadow_to_live``: 0.20  — must achieve Brier ≤ 0.20 to promote.
  - ``live_to_shadow``:  0.25  — demoted back to SHADOW if score > 0.25.
  - ``min_samples``:      30   — minimum predictions before gate applies.

Typical usage::

    store = BrierStore()          # opens / creates DB
    store.record(agent_id="a1", market_id="BTC-Q1", forecast=0.7, outcome=1)
    …
    gate = BrierGate(store)
    gate.evaluate("a1")           # returns "live" or "shadow"
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.metrics.brier_store")

# ── Defaults ─────────────────────────────────────────────────────────────

DEFAULT_DB_PATH = "data/brier_scores.db"
SHADOW_TO_LIVE_THRESHOLD = 0.20
LIVE_TO_SHADOW_THRESHOLD = 0.25
MIN_SAMPLES_FOR_GATE = 30


# ── BrierStore ───────────────────────────────────────────────────────────

class BrierStore:
    """SQLite-backed Brier score persistence with WAL mode.

    Thread-safe: uses a per-instance lock around all writes.
    WAL mode is set once on connection open, making concurrent reads fast.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    # ── Internals ────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        """Open a connection with WAL mode and foreign keys."""
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        """Create tables if they do not already exist."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = self._connect()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS brier_scores (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id    TEXT    NOT NULL,
                    market_id   TEXT    NOT NULL,
                    forecast    REAL    NOT NULL,
                    outcome     INTEGER NOT NULL,
                    score       REAL    NOT NULL,
                    recorded_at REAL    NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_brier_agent ON brier_scores(agent_id)"
            )
            conn.commit()
            conn.close()

    # ── Public API ───────────────────────────────────────────────────────

    def record(
        self,
        agent_id: str,
        market_id: str,
        forecast: float,
        outcome: int,
        recorded_at: Optional[float] = None,
    ) -> float:
        """Record one prediction and return its Brier score contribution.

        Args:
            agent_id:    Identifier of the predicting agent.
            market_id:   Market / question identifier.
            forecast:    Predicted probability in [0, 1].
            outcome:     Realised outcome (0 or 1).
            recorded_at: Unix timestamp (defaults to now).

        Returns:
            The Brier contribution: ``(forecast - outcome) ** 2``.
        """
        score = (forecast - outcome) ** 2
        ts = recorded_at or time.time()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO brier_scores "
                "(agent_id, market_id, forecast, outcome, score, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (agent_id, market_id, forecast, outcome, score, ts),
            )
            conn.commit()
            conn.close()
        return score

    def rolling_brier(self, agent_id: str, last_n: int = 100) -> Optional[float]:
        """Return mean Brier score for the most recent *last_n* predictions.

        Returns ``None`` when fewer than one prediction exists.
        """
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                """
                SELECT AVG(score), COUNT(*)
                FROM (
                    SELECT score FROM brier_scores
                    WHERE agent_id = ?
                    ORDER BY recorded_at DESC
                    LIMIT ?
                )
                """,
                (agent_id, last_n),
            ).fetchone()
            conn.close()

        if row is None or row[1] == 0:
            return None
        return row[0]

    def sample_count(self, agent_id: str) -> int:
        """Return total number of recorded predictions for an agent."""
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT COUNT(*) FROM brier_scores WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            conn.close()
        return row[0] if row else 0

    def close(self) -> None:
        """No persistent connection to close; method provided for symmetry."""


# ── BrierGate ────────────────────────────────────────────────────────────

class BrierGate:
    """SHADOW/LIVE promotion gate based on Brier score thresholds.

    Agents start in ``"shadow"`` mode and are promoted to ``"live"`` once
    their rolling Brier score drops below *shadow_to_live_threshold* with
    at least *min_samples* predictions recorded.

    If a live agent's score rises above *live_to_shadow_threshold* it is
    automatically demoted back to ``"shadow"``.
    """

    def __init__(
        self,
        store: BrierStore,
        shadow_to_live_threshold: float = SHADOW_TO_LIVE_THRESHOLD,
        live_to_shadow_threshold: float = LIVE_TO_SHADOW_THRESHOLD,
        min_samples: int = MIN_SAMPLES_FOR_GATE,
    ):
        self._store = store
        self._promote_threshold = shadow_to_live_threshold
        self._demote_threshold = live_to_shadow_threshold
        self._min_samples = min_samples
        # In-memory mode cache: agent_id → "shadow" | "live"
        self._modes: dict[str, str] = {}
        self._lock = threading.Lock()

    def evaluate(self, agent_id: str) -> str:
        """Evaluate and return the current mode for *agent_id*.

        Reads the latest Brier score from the store, applies promotion /
        demotion logic, updates the in-memory cache, and returns the mode.

        Returns:
            ``"live"`` or ``"shadow"``.
        """
        n = self._store.sample_count(agent_id)
        if n < self._min_samples:
            return self._set_mode(agent_id, "shadow")

        score = self._store.rolling_brier(agent_id)
        if score is None:
            return self._set_mode(agent_id, "shadow")

        with self._lock:
            current = self._modes.get(agent_id, "shadow")

        if current == "shadow" and score <= self._promote_threshold:
            logger.info(
                "BrierGate: promoting %s to LIVE (brier=%.4f ≤ threshold=%.4f, n=%d)",
                agent_id, score, self._promote_threshold, n,
            )
            return self._set_mode(agent_id, "live")

        if current == "live" and score > self._demote_threshold:
            logger.warning(
                "BrierGate: demoting %s to SHADOW (brier=%.4f > threshold=%.4f)",
                agent_id, score, self._demote_threshold,
            )
            return self._set_mode(agent_id, "shadow")

        with self._lock:
            return self._modes.get(agent_id, "shadow")

    def get_mode(self, agent_id: str) -> str:
        """Return the last-evaluated mode without re-evaluating."""
        with self._lock:
            return self._modes.get(agent_id, "shadow")

    def _set_mode(self, agent_id: str, mode: str) -> str:
        with self._lock:
            self._modes[agent_id] = mode
        return mode
