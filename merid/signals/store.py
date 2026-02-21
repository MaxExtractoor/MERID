"""§5 SignalStore — SQLite persistence for signals, features, arbs, drift metrics.

Tables:
  signal_features    — cached feature snapshots per symbol/domain
  signal_snapshots   — frozen driver snapshots attached to opinions/plans
  arb_signals        — detected dislocations
  arb_plans          — multi-leg arb/dislocation plans
  drift_metrics      — per-domain drift/quality metrics over time
  cqi_history        — Consensus Quality Index snapshots
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.signals.store")


class SignalStore:
    """SQLite persistence for the signal layer."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or os.environ.get("MERID_SIGNAL_DB", "data/signals.db")
        self._mem_conn: Optional[sqlite3.Connection] = None
        if self._db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
        else:
            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if self._mem_conn:
            return self._mem_conn
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signal_features (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                domain TEXT NOT NULL,
                features_json TEXT NOT NULL,
                source TEXT DEFAULT 'synthetic',
                avg_freshness REAL DEFAULT 1.0,
                timestamp REAL NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sf_symbol ON signal_features(symbol);
            CREATE INDEX IF NOT EXISTS idx_sf_domain ON signal_features(domain);

            CREATE TABLE IF NOT EXISTS signal_snapshots (
                id TEXT PRIMARY KEY,
                opinion_or_plan_id TEXT,
                symbol TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                avg_freshness REAL DEFAULT 1.0,
                stale_count INTEGER DEFAULT 0,
                signal_count INTEGER DEFAULT 0,
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ss_symbol ON signal_snapshots(symbol);

            CREATE TABLE IF NOT EXISTS arb_signals (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                arb_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                venues_json TEXT NOT NULL,
                gross_edge_bps REAL DEFAULT 0,
                net_edge_bps REAL DEFAULT 0,
                edge_usd REAL DEFAULT 0,
                ttl_seconds REAL DEFAULT 120,
                status TEXT DEFAULT 'active',
                detected_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_arb_symbol ON arb_signals(symbol);
            CREATE INDEX IF NOT EXISTS idx_arb_status ON arb_signals(status);

            CREATE TABLE IF NOT EXISTS arb_plans (
                id TEXT PRIMARY KEY,
                signal_id TEXT,
                domain TEXT NOT NULL,
                arb_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                legs_json TEXT NOT NULL,
                total_size_usd REAL DEFAULT 0,
                expected_edge_bps REAL DEFAULT 0,
                expected_profit_usd REAL DEFAULT 0,
                ttl_seconds REAL DEFAULT 120,
                status TEXT DEFAULT 'proposed',
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS drift_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                window TEXT NOT NULL,
                brier_score REAL DEFAULT 0,
                log_loss REAL DEFAULT 0,
                pnl_per_risk REAL DEFAULT 0,
                feature_psi REAL DEFAULT 0,
                decay_discipline REAL DEFAULT 0,
                stale_trade_pct REAL DEFAULT 0,
                fresh_trade_pct REAL DEFAULT 0,
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_dm_domain ON drift_metrics(domain);

            CREATE TABLE IF NOT EXISTS cqi_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                quality_index REAL DEFAULT 0.5,
                band TEXT DEFAULT 'neutral',
                brier_component REAL DEFAULT 0,
                pnl_component REAL DEFAULT 0,
                drift_component REAL DEFAULT 0,
                decay_component REAL DEFAULT 0,
                window TEXT DEFAULT '24h',
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cqi_domain ON cqi_history(domain);
        """)
        if not self._mem_conn:
            conn.close()

    # ── Feature snapshots ─────────────────────────────────────────────

    def store_feature_snapshot(self, feature_set_dict: Dict[str, Any]):
        conn = self._conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO signal_features
                   (id, symbol, domain, features_json, source, avg_freshness, timestamp, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"sf-{feature_set_dict.get('symbol','')}-{feature_set_dict.get('domain','')}",
                    feature_set_dict.get("symbol", ""),
                    feature_set_dict.get("domain", ""),
                    json.dumps(feature_set_dict.get("features", {})),
                    feature_set_dict.get("source", "synthetic"),
                    feature_set_dict.get("avg_freshness", 1.0),
                    time.time(),
                    time.time(),
                ),
            )
            conn.commit()
        finally:
            if not self._mem_conn:
                conn.close()

    def get_latest_features(self, symbol: str, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            if domain:
                rows = conn.execute(
                    "SELECT * FROM signal_features WHERE symbol=? AND domain=? ORDER BY timestamp DESC LIMIT 1",
                    (symbol, domain),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM signal_features WHERE symbol=? ORDER BY timestamp DESC LIMIT 10",
                    (symbol,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._mem_conn:
                conn.close()

    # ── Signal snapshots ──────────────────────────────────────────────

    def store_snapshot(self, snapshot_dict: Dict[str, Any], opinion_or_plan_id: str = ""):
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO signal_snapshots
                   (id, opinion_or_plan_id, symbol, snapshot_json, avg_freshness, stale_count, signal_count, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_dict.get("snapshot_id", f"snap-{time.time()}"),
                    opinion_or_plan_id,
                    snapshot_dict.get("symbol", ""),
                    json.dumps(snapshot_dict),
                    snapshot_dict.get("avg_freshness", 1.0),
                    snapshot_dict.get("stale_count", 0),
                    snapshot_dict.get("signal_count", 0),
                    snapshot_dict.get("timestamp", time.time()),
                ),
            )
            conn.commit()
        finally:
            if not self._mem_conn:
                conn.close()

    def get_snapshots(self, opinion_or_plan_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            if opinion_or_plan_id:
                rows = conn.execute(
                    "SELECT * FROM signal_snapshots WHERE opinion_or_plan_id=? ORDER BY timestamp DESC LIMIT ?",
                    (opinion_or_plan_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM signal_snapshots ORDER BY timestamp DESC LIMIT ?", (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._mem_conn:
                conn.close()

    # ── Arb signals ───────────────────────────────────────────────────

    def store_arb_signal(self, signal_dict: Dict[str, Any]):
        conn = self._conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO arb_signals
                   (id, domain, arb_type, symbol, venues_json, gross_edge_bps, net_edge_bps,
                    edge_usd, ttl_seconds, status, detected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    signal_dict.get("signal_id", ""),
                    signal_dict.get("domain", ""),
                    signal_dict.get("arb_type", ""),
                    signal_dict.get("symbol", ""),
                    json.dumps(signal_dict.get("venues", [])),
                    signal_dict.get("gross_edge_bps", 0),
                    signal_dict.get("net_edge_bps", 0),
                    signal_dict.get("edge_usd", 0),
                    signal_dict.get("ttl_seconds", 120),
                    signal_dict.get("status", "active"),
                    signal_dict.get("detected_at", time.time()),
                ),
            )
            conn.commit()
        finally:
            if not self._mem_conn:
                conn.close()

    def list_arb_signals(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM arb_signals WHERE status=? ORDER BY detected_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM arb_signals ORDER BY detected_at DESC LIMIT ?", (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._mem_conn:
                conn.close()

    # ── Arb plans ─────────────────────────────────────────────────────

    def store_arb_plan(self, plan_dict: Dict[str, Any]):
        conn = self._conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO arb_plans
                   (id, signal_id, domain, arb_type, symbol, legs_json, total_size_usd,
                    expected_edge_bps, expected_profit_usd, ttl_seconds, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan_dict.get("plan_id", ""),
                    plan_dict.get("signal_id", ""),
                    plan_dict.get("domain", ""),
                    plan_dict.get("arb_type", ""),
                    plan_dict.get("symbol", ""),
                    json.dumps(plan_dict.get("legs", [])),
                    plan_dict.get("total_size_usd", 0),
                    plan_dict.get("expected_edge_bps", 0),
                    plan_dict.get("expected_profit_usd", 0),
                    plan_dict.get("ttl_seconds", 120),
                    plan_dict.get("status", "proposed"),
                    plan_dict.get("created_at", time.time()),
                ),
            )
            conn.commit()
        finally:
            if not self._mem_conn:
                conn.close()

    def list_arb_plans(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM arb_plans WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM arb_plans ORDER BY created_at DESC LIMIT ?", (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._mem_conn:
                conn.close()

    # ── Drift metrics ─────────────────────────────────────────────────

    def store_drift_metric(self, metric: Dict[str, Any]):
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO drift_metrics
                   (domain, window, brier_score, log_loss, pnl_per_risk, feature_psi,
                    decay_discipline, stale_trade_pct, fresh_trade_pct, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    metric.get("domain", ""),
                    metric.get("window", "24h"),
                    metric.get("brier_score", 0),
                    metric.get("log_loss", 0),
                    metric.get("pnl_per_risk", 0),
                    metric.get("feature_psi", 0),
                    metric.get("decay_discipline", 0),
                    metric.get("stale_trade_pct", 0),
                    metric.get("fresh_trade_pct", 0),
                    metric.get("timestamp", time.time()),
                ),
            )
            conn.commit()
        finally:
            if not self._mem_conn:
                conn.close()

    def get_drift_metrics(self, domain: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            if domain:
                rows = conn.execute(
                    "SELECT * FROM drift_metrics WHERE domain=? ORDER BY timestamp DESC LIMIT ?",
                    (domain, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM drift_metrics ORDER BY timestamp DESC LIMIT ?", (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._mem_conn:
                conn.close()

    # ── CQI history ───────────────────────────────────────────────────

    def store_cqi(self, cqi: Dict[str, Any]):
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO cqi_history
                   (domain, quality_index, band, brier_component, pnl_component,
                    drift_component, decay_component, window, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cqi.get("domain", ""),
                    cqi.get("quality_index", 0.5),
                    cqi.get("band", "neutral"),
                    cqi.get("brier_component", 0),
                    cqi.get("pnl_component", 0),
                    cqi.get("drift_component", 0),
                    cqi.get("decay_component", 0),
                    cqi.get("window", "24h"),
                    cqi.get("timestamp", time.time()),
                ),
            )
            conn.commit()
        finally:
            if not self._mem_conn:
                conn.close()

    def get_latest_cqi(self, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            if domain:
                rows = conn.execute(
                    "SELECT * FROM cqi_history WHERE domain=? ORDER BY timestamp DESC LIMIT 1",
                    (domain,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM cqi_history WHERE id IN
                       (SELECT MAX(id) FROM cqi_history GROUP BY domain)
                       ORDER BY domain""",
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._mem_conn:
                conn.close()

    def get_cqi_history(self, domain: str, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM cqi_history WHERE domain=? ORDER BY timestamp DESC LIMIT ?",
                (domain, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._mem_conn:
                conn.close()

    # ── Reset ─────────────────────────────────────────────────────────

    def reset_all(self) -> None:
        """Truncate all signal tables.  Used by fresh-start mode."""
        conn = self._conn()
        try:
            conn.executescript("""
                DELETE FROM signal_features;
                DELETE FROM arb_signals;
                DELETE FROM arb_plans;
                DELETE FROM drift_metrics;
                DELETE FROM cqi_history;
            """)
            if not self._mem_conn:
                conn.commit()
            logger.warning("SignalStore reset: all tables truncated")
        finally:
            if not self._mem_conn:
                conn.close()

    # ── Aggregate metrics ─────────────────────────────────────────────

    def get_signal_metrics(self) -> Dict[str, Any]:
        conn = self._conn()
        try:
            feature_count = conn.execute("SELECT COUNT(*) FROM signal_features").fetchone()[0]
            snapshot_count = conn.execute("SELECT COUNT(*) FROM signal_snapshots").fetchone()[0]
            arb_count = conn.execute("SELECT COUNT(*) FROM arb_signals").fetchone()[0]
            active_arbs = conn.execute("SELECT COUNT(*) FROM arb_signals WHERE status='active'").fetchone()[0]
            plan_count = conn.execute("SELECT COUNT(*) FROM arb_plans").fetchone()[0]
            drift_count = conn.execute("SELECT COUNT(*) FROM drift_metrics").fetchone()[0]
            cqi_count = conn.execute("SELECT COUNT(*) FROM cqi_history").fetchone()[0]

            return {
                "feature_snapshots": feature_count,
                "signal_snapshots": snapshot_count,
                "arb_signals_total": arb_count,
                "arb_signals_active": active_arbs,
                "arb_plans": plan_count,
                "drift_metrics": drift_count,
                "cqi_entries": cqi_count,
            }
        finally:
            if not self._mem_conn:
                conn.close()


# ── Singleton ─────────────────────────────────────────────────────────

_store: Optional[SignalStore] = None


def get_signal_store() -> SignalStore:
    global _store
    if _store is None:
        _store = SignalStore()
    return _store
