"""
MERID Brier Metrics Database Schema and Integration

Production database schema for storing forecasts, calibration parameters,
and Brier metrics with online updates and versioning.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import sqlite3
import json
import numpy as np
from contextlib import contextmanager

from core.merid_metrics import (
    MERIDMetrics, CalibrationMethod, CalibrationArchetype,
    CalibrationResult, OnlineWeightedBrier
)
from utils.logger import get_logger

logger = get_logger("merid_metrics_db")

# Database schema for Brier metrics
BRIER_SCHEMA = """
-- Models table
CREATE TABLE IF NOT EXISTS models (
    model_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,  -- 'agent', 'strategy', 'ensemble', etc.
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Model features table
CREATE TABLE IF NOT EXISTS model_features (
    model_id TEXT NOT NULL,
    feature_name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (model_id, feature_name),
    FOREIGN KEY (model_id) REFERENCES models(model_id)
);

-- Forecasts table (core data)
CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id TEXT NOT NULL,
    user_id TEXT,
    market_id TEXT NOT NULL,
    ts_forecast TIMESTAMP NOT NULL,
    prob DOUBLE PRECISION NOT NULL,
    outcome SMALLINT,  -- 0/1 when resolved, NULL until then
    ts_resolved TIMESTAMP,
    weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    brier_event DOUBLE PRECISION,  -- (prob - outcome)^2, computed on resolution
    calibration_version INT DEFAULT 0,  -- Which calibration version was applied
    FOREIGN KEY (model_id) REFERENCES models(model_id)
);

-- Calibration runs table (versioned history)
CREATE TABLE IF NOT EXISTS calibration_runs (
    calib_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id TEXT NOT NULL,
    feature_name TEXT,  -- NULL = model-level calibration
    market_group TEXT,  -- Optional ('crypto', 'sports', etc.)
    archetype TEXT NOT NULL,  -- 'PIT', 'TTC', 'BASE'
    method TEXT NOT NULL,  -- 'platt', 'isotonic', 'temperature', 'baseline'
    params JSONB NOT NULL,  -- Fitted parameters
    data_start TIMESTAMP NOT NULL,
    data_end TIMESTAMP NOT NULL,
    brier_raw DOUBLE PRECISION,
    brier_cal DOUBLE PRECISION,
    bss_vs_raw DOUBLE PRECISION,
    n_events INT NOT NULL,
    version INT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    FOREIGN KEY (model_id) REFERENCES models(model_id)
);

-- Current calibration pointer table
CREATE TABLE IF NOT EXISTS calibration_current (
    model_id TEXT NOT NULL,
    feature_name TEXT,  -- NULL = model-level
    market_group TEXT,
    calib_run_id BIGINT NOT NULL,
    deployed_at TIMESTAMP NOT NULL,
    deployed_by TEXT,
    PRIMARY KEY (model_id, feature_name, market_group),
    FOREIGN KEY (calib_run_id) REFERENCES calibration_runs(calib_run_id)
);

-- Streaming calibration metrics table
CREATE TABLE IF NOT EXISTS calibration_metrics_streaming (
    metrics_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id TEXT NOT NULL,
    market_group TEXT,
    window_start TIMESTAMP NOT NULL,
    window_end TIMESTAMP NOT NULL,
    n_events BIGINT NOT NULL DEFAULT 0,
    
    -- Raw probabilities metrics
    sum_brier_raw DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    weight_sum_raw DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    
    -- Calibrated probabilities metrics
    sum_brier_cal DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    weight_sum_cal DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    
    -- Materialized scores
    brier_raw DOUBLE PRECISION,
    brier_cal DOUBLE PRECISION,
    bss_cal_vs_raw DOUBLE PRECISION,
    
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    
    FOREIGN KEY (model_id) REFERENCES models(model_id)
);

-- Aggregated forecast metrics table (for dashboards)
CREATE TABLE IF NOT EXISTS forecast_metrics (
    metrics_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id TEXT NOT NULL,
    strategy_id TEXT,
    market_id TEXT,  -- NULL for cross-market aggregates
    window_start TIMESTAMP NOT NULL,
    window_end TIMESTAMP NOT NULL,
    n_events BIGINT NOT NULL,
    brier_score DOUBLE PRECISION NOT NULL,
    brier_skill_score DOUBLE PRECISION,
    reliability DOUBLE PRECISION,
    resolution DOUBLE PRECISION,
    uncertainty DOUBLE PRECISION,
    log_loss DOUBLE PRECISION,
    quality_category TEXT,
    baseline_id TEXT,  -- Which baseline used for BSS
    created_at TIMESTAMP NOT NULL,
    
    FOREIGN KEY (model_id) REFERENCES models(model_id)
);

-- Forecast bins table (for decomposition details)
CREATE TABLE IF NOT EXISTS forecast_bins (
    bin_id INTEGER PRIMARY KEY AUTOINCREMENT,
    metrics_id BIGINT NOT NULL,
    bin_index INT NOT NULL,
    p_mean DOUBLE PRECISION NOT NULL,  -- Mean predicted probability in bin
    o_mean DOUBLE PRECISION NOT NULL,  -- Observed frequency in bin
    count INT NOT NULL,
    bin_start DOUBLE PRECISION NOT NULL,
    bin_end DOUBLE PRECISION NOT NULL,
    
    FOREIGN KEY (metrics_id) REFERENCES forecast_metrics(metrics_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_forecasts_model_time ON forecasts (model_id, ts_resolved) WHERE outcome IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_forecasts_market_time ON forecasts (market_id, ts_resolved) WHERE outcome IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_forecasts_model_market_time ON forecasts (model_id, market_id, ts_resolved);
CREATE INDEX IF NOT EXISTS idx_calibration_runs_model_time ON calibration_runs (model_id, feature_name, market_group, data_end DESC);
CREATE INDEX IF NOT EXISTS idx_calibration_metrics_model_window ON calibration_metrics_streaming (model_id, market_group, window_start);
CREATE INDEX IF NOT EXISTS idx_forecast_metrics_model_window ON forecast_metrics (model_id, window_start);
"""

@contextmanager
def get_brier_db_connection():
    """Context manager for Brier metrics database connection."""
    conn = sqlite3.connect("brier_metrics.db")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

class BrierMetricsDB:
    """Database interface for Brier metrics system."""
    
    def __init__(self, db_path: str = "brier_metrics.db"):
        self.db_path = db_path
        self._init_database()
    
    def get_brier_db_connection(self):
        """Create a sqlite connection bound to this database instance."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
def _init_database(self) -> None:
        """Initialize database with schema."""
        with self.get_brier_db_connection() as conn:
            conn.executescript(BRIER_SCHEMA)
            conn.commit()
            logger.info("Brier metrics database initialized")
    
    def register_model(self, model_id: str, name: str, kind: str) -> None:
        """Register a new model."""
        with self.get_brier_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO models (model_id, name, kind, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (model_id, name, kind, datetime.now(), datetime.now()))
            conn.commit()
            logger.info(f"Registered model: {model_id}")
    
    def record_forecast(self, model_id: str, market_id: str, prob: float,
                       user_id: Optional[str] = None, weight: float = 1.0) -> int:
        """
        Record a new forecast.
        
        Returns:
            forecast_id
        """
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
        with get_brier_db_connection() as conn:
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO forecasts (model_id, user_id, market_id, ts_forecast, prob, weight)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (model_id, user_id, market_id, datetime.now(), prob, weight))
            
            forecast_id = cursor.lastrowid
            conn.commit()
            
            logger.debug(f"Recorded forecast {forecast_id} for model {model_id}")
            return forecast_id
    
    def resolve_forecast(self, forecast_id: int, outcome: int) -> None:
        """Resolve a forecast with its outcome."""
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
        with get_brier_db_connection() as conn:
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
            cursor = conn.cursor()
            
            # Get forecast details
            cursor.execute("""
                SELECT prob, weight FROM forecasts WHERE forecast_id = ?
            """, (forecast_id,))
            row = cursor.fetchone()
            
            if not row:
                raise ValueError(f"Forecast {forecast_id} not found")
            
            prob = row["prob"]
            weight = row["weight"]
            
            # Compute Brier event
            brier_event = (prob - outcome) ** 2
            
            # Update forecast
            cursor.execute("""
                UPDATE forecasts 
                SET outcome = ?, ts_resolved = ?, brier_event = ?
                WHERE forecast_id = ?
            """, (outcome, datetime.now(), brier_event, forecast_id))
            
            conn.commit()
            
            # Update streaming metrics
            self._update_streaming_metrics(cursor, forecast_id, prob, outcome, weight)
            
            logger.debug(f"Resolved forecast {forecast_id} with outcome {outcome}")
    
    def _update_streaming_metrics(self, cursor: sqlite3.Cursor, forecast_id: int,
                                 prob: float, outcome: int, weight: float) -> None:
        """Update streaming calibration metrics."""
        # Get model info
        cursor.execute("""
            SELECT model_id, market_id FROM forecasts WHERE forecast_id = ?
        """, (forecast_id,))
        row = cursor.fetchone()
        
        if not row:
            return
        
        model_id = row["model_id"]
        market_id = row["market_id"]
        market_group = self._get_market_group(market_id)
        
        # Define window (current day)
        now = datetime.now()
        window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        window_end = window_start + timedelta(days=1)
        
        # Get or create streaming metrics row
        cursor.execute("""
            SELECT metrics_id, n_events, sum_brier_raw, weight_sum_raw
            FROM calibration_metrics_streaming
            WHERE model_id = ? AND market_group = ? AND window_start = ? AND window_end = ?
        """, (model_id, market_group, window_start, window_end))
        
        metrics_row = cursor.fetchone()
        
        if metrics_row:
            # Update existing row
            new_n_events = metrics_row["n_events"] + 1
            new_sum_brier_raw = metrics_row["sum_brier_raw"] + (weight * (prob - outcome) ** 2)
            new_weight_sum_raw = metrics_row["weight_sum_raw"] + weight
            new_brier_raw = new_sum_brier_raw / new_weight_sum_raw
            
            cursor.execute("""
                UPDATE calibration_metrics_streaming
                SET n_events = ?, sum_brier_raw = ?, weight_sum_raw = ?, 
                    brier_raw = ?, updated_at = ?
                WHERE metrics_id = ?
            """, (new_n_events, new_sum_brier_raw, new_weight_sum_raw, 
                  new_brier_raw, datetime.now(), metrics_row["metrics_id"]))
        else:
            # Create new row
            new_brier_raw = (prob - outcome) ** 2
            cursor.execute("""
                INSERT INTO calibration_metrics_streaming
                (model_id, market_group, window_start, window_end, n_events, 
                 sum_brier_raw, weight_sum_raw, brier_raw, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (model_id, market_group, window_start, window_end, 1,
                  weight * new_brier_raw, weight, new_brier_raw, 
                  datetime.now(), datetime.now()))
    
    def _get_market_group(self, market_id: str) -> str:
        """Extract market group from market ID."""
        # Simple heuristic - can be made more sophisticated
        if "crypto" in market_id.lower() or "btc" in market_id.lower() or "eth" in market_id.lower():
            return "crypto"
        elif "sports" in market_id.lower() or "game" in market_id.lower():
            return "sports"
        elif "politics" in market_id.lower() or "election" in market_id.lower():
            return "politics"
        else:
            return "other"
    
    def save_calibration(self, model_id: str, cal_result: CalibrationResult,
                        feature_name: Optional[str] = None, market_group: Optional[str] = None) -> int:
        """
        Save calibration result.
        
        Returns:
            calib_run_id
        """
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
        with get_brier_db_connection() as conn:
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
            cursor = conn.cursor()
            
            # Get next version
            cursor.execute("""
                SELECT COALESCE(MAX(version), 0) + 1 as next_version
                FROM calibration_runs
                WHERE model_id = ? AND feature_name = ? AND market_group = ?
            """, (model_id, feature_name, market_group))
            
            next_version = cursor.fetchone()["next_version"]
            
            # Insert calibration run
            cursor.execute("""
                INSERT INTO calibration_runs
                (model_id, feature_name, market_group, archetype, method, params,
                 data_start, data_end, brier_raw, brier_cal, bss_vs_raw, n_events,
                 version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (model_id, feature_name, market_group, cal_result.archetype.value,
                  cal_result.method.value, json.dumps(cal_result.params),
                  cal_result.trained_on_start, cal_result.trained_on_end,
                  cal_result.brier_raw, cal_result.brier_cal, cal_result.bss_vs_raw,
                  cal_result.n_events, next_version, datetime.now()))
            
            calib_run_id = cursor.lastrowid
            
            # Update current pointer
            cursor.execute("""
                INSERT OR REPLACE INTO calibration_current
                (model_id, feature_name, market_group, calib_run_id, deployed_at, deployed_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (model_id, feature_name, market_group, calib_run_id, datetime.now(), "system"))
            
            conn.commit()
            logger.info(f"Saved calibration {calib_run_id} for model {model_id}")
            
            return calib_run_id
    
    def get_current_calibration(self, model_id: str, feature_name: Optional[str] = None,
                              market_group: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get current calibration parameters for a model."""
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
        with get_brier_db_connection() as conn:
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
            cursor = conn.cursor()
            cursor.execute("""
                SELECT cr.* FROM calibration_runs cr
                JOIN calibration_current cc ON cr.calib_run_id = cc.calib_run_id
                WHERE cc.model_id = ? AND cc.feature_name IS ? AND cc.market_group IS ?
            """, (model_id, feature_name, market_group))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            return {
                "calib_run_id": row["calib_run_id"],
                "method": row["method"],
                "archetype": row["archetype"],
                "params": json.loads(row["params"]),
                "brier_raw": row["brier_raw"],
                "brier_cal": row["brier_cal"],
                "bss_vs_raw": row["bss_vs_raw"],
                "version": row["version"],
                "deployed_at": row["created_at"]
            }
    
    def compute_window_metrics(self, model_id: str, window_start: datetime, window_end: datetime,
                             market_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Compute aggregated metrics for a time window.
        
        Returns:
            Dictionary with Brier decomposition and metrics
        """
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
        with get_brier_db_connection() as conn:
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
            cursor = conn.cursor()
            
            # Get forecasts in window
            query = """
                SELECT prob, outcome, weight
                FROM forecasts
                WHERE model_id = ? AND ts_resolved >= ? AND ts_resolved < ?
                AND outcome IS NOT NULL
            """
            params = [model_id, window_start, window_end]
            
            if market_id:
                query += " AND market_id = ?"
                params.append(market_id)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            if not rows:
                return None
            
            # Extract data
            probs = np.array([row["prob"] for row in rows])
            outcomes = np.array([row["outcome"] for row in rows])
            weights = np.array([row["weight"] for row in rows])
            
            # Compute metrics
            metrics = get_merid_metrics()
            result = metrics.brier_decomposition(outcomes, probs)
            
            # Store in database
            self._store_aggregated_metrics(cursor, model_id, market_id, window_start, window_end,
                                         result, len(rows))
            
            return result.to_dict()
    
    def _store_aggregated_metrics(self, cursor: sqlite3.Cursor, model_id: str,
                                market_id: Optional[str], window_start: datetime,
                                window_end: datetime, result, n_events: int) -> None:
        """Store aggregated metrics in database."""
        # Insert main metrics
        cursor.execute("""
            INSERT INTO forecast_metrics
            (model_id, market_id, window_start, window_end, n_events,
             brier_score, brier_skill_score, reliability, resolution, uncertainty,
             quality_category, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (model_id, market_id, window_start, window_end, n_events,
              result.brier_score, result.brier_skill_score, result.reliability,
              result.resolution, result.uncertainty, result.quality_category,
              datetime.now()))
        
        metrics_id = cursor.lastrowid
        
        # Store bin details (would need to recompute for detailed bins)
        # This is a simplified version - full implementation would store bin stats
    
    def get_streaming_metrics(self, model_id: str, market_group: Optional[str] = None,
                            days: int = 7) -> List[Dict[str, Any]]:
        """Get streaming metrics for recent days."""
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
        with get_brier_db_connection() as conn:
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
            cursor = conn.cursor()
            
            cutoff_date = datetime.now() - timedelta(days=days)
            
            query = """
                SELECT window_start, window_end, n_events, brier_raw, brier_cal, bss_cal_vs_raw
                FROM calibration_metrics_streaming
                WHERE model_id = ? AND window_start >= ?
            """
            params = [model_id, cutoff_date]
            
            if market_group:
                query += " AND market_group = ?"
                params.append(market_group)
            
            query += " ORDER BY window_start DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [dict(row) for row in rows]
    
    def get_model_performance_summary(self, model_id: str, days: int = 30) -> Dict[str, Any]:
        """Get comprehensive performance summary for a model."""
<<<<<<< C:\Dev\MERID\core\brier_metrics_db.py
        with get_brier_db_connection() as conn:
=======
        with self.get_brier_db_connection() as conn:
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\core\brier_metrics_db.py
            cursor = conn.cursor()
            
            cutoff_date = datetime.now() - timedelta(days=days)
            
            # Recent aggregated metrics
            cursor.execute("""
                SELECT window_start, window_end, n_events, brier_score, brier_skill_score,
                       reliability, resolution, uncertainty, quality_category
                FROM forecast_metrics
                WHERE model_id = ? AND window_start >= ?
                ORDER BY window_start DESC
                LIMIT 10
            """, (model_id, cutoff_date))
            
            recent_metrics = [dict(row) for row in cursor.fetchall()]
            
            # Current calibration
            current_cal = self.get_current_calibration(model_id)
            
            # Streaming metrics
            streaming = self.get_streaming_metrics(model_id, days=7)
            
            # Total forecast count
            cursor.execute("""
                SELECT COUNT(*) as total_forecasts,
                       SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) as resolved_forecasts
                FROM forecasts
                WHERE model_id = ? AND ts_forecast >= ?
            """, (model_id, cutoff_date))
            
            counts = cursor.fetchone()
            
            return {
                "model_id": model_id,
                "period_days": days,
                "total_forecasts": counts["total_forecasts"],
                "resolved_forecasts": counts["resolved_forecasts"],
                "current_calibration": current_cal,
                "recent_aggregated_metrics": recent_metrics,
                "streaming_metrics": streaming,
                "summary_generated_at": datetime.now().isoformat()
            }

# Global database instance
_brier_db = BrierMetricsDB()

def get_brier_db() -> BrierMetricsDB:
    """Get the global Brier metrics database instance."""
    return _brier_db
