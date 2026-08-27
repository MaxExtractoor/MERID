"""
Kalshi Market Wiring Database Schema

Persistent storage for Kalshi markets, mappings, and coverage tracking.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import os
import time
from typing import Dict, List, Optional, Any

from merid.signals.store import get_signal_store
from merid.event_venues.kalshi.market_wiring.models import (
    KalshiMarketRecord,
    MarketMapping,
    RiskProfile,
    MarketStatus,
    CoverageReport,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_wiring.store")


class KalshiMarketStore:
    """Persistent storage for Kalshi market wiring data"""
    
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or os.path.join(
            os.path.dirname(get_signal_store()._db_path),
            "kalshi_market_wiring.db"
        )
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._initialized = False
    
    def _conn(self) -> sqlite3.Connection:
        """Get thread-local database connection"""
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            if not self._initialized:
                with self._init_lock:
                    if not self._initialized:
                        self._init_db()
                        self._initialized = True
        return self._local.conn
    
    def _init_db(self):
        """Initialize database schema"""
        conn = self._conn()
        conn.executescript("""
            -- Kalshi markets table
            CREATE TABLE IF NOT EXISTS kalshi_markets (
                market_ticker TEXT PRIMARY KEY,
                event_ticker TEXT NOT NULL,
                series_ticker TEXT NOT NULL,
                category TEXT NOT NULL,
                tags TEXT,  -- JSON array
                title TEXT NOT NULL,
                subtitle TEXT DEFAULT '',
                close_ts REAL NOT NULL,
                status TEXT NOT NULL,
                enabled_for_merid BOOLEAN DEFAULT FALSE,
                risk_profile TEXT NOT NULL,
                max_notional_per_trade REAL DEFAULT 100.0,
                max_daily_notional REAL DEFAULT 1000.0,
                max_open_risk REAL DEFAULT 500.0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            
            -- Market mapping table
            CREATE TABLE IF NOT EXISTS market_mappings (
                market_ticker TEXT PRIMARY KEY,
                event_ticker TEXT NOT NULL,
                series_ticker TEXT NOT NULL,
                category TEXT NOT NULL,
                risk_profile TEXT NOT NULL,
                underlying_symbol TEXT NOT NULL,
                merid_symbol TEXT NOT NULL,
                sentiment_symbols TEXT,  -- JSON array
                debate_symbol TEXT,
                enabled BOOLEAN DEFAULT FALSE,
                requires_crypto_context BOOLEAN DEFAULT FALSE,
                requires_debate_context BOOLEAN DEFAULT FALSE,
                requires_sentiment_context BOOLEAN DEFAULT FALSE,
                max_crypto_staleness REAL DEFAULT 300.0,
                max_sentiment_staleness REAL DEFAULT 600.0,
                max_debate_staleness REAL DEFAULT 900.0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (market_ticker) REFERENCES kalshi_markets(market_ticker)
            );
            
            -- Coverage reports table
            CREATE TABLE IF NOT EXISTS coverage_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_open_markets INTEGER NOT NULL,
                mapped_markets INTEGER NOT NULL,
                enabled_markets INTEGER NOT NULL,
                unmapped_markets INTEGER NOT NULL,
                disabled_markets INTEGER NOT NULL,
                unmapped_market_tickers TEXT,  -- JSON array
                disabled_market_tickers TEXT,  -- JSON array
                coverage_by_risk_profile TEXT,  -- JSON object
                checked_at REAL NOT NULL
            );
            
            -- Sync status table
            CREATE TABLE IF NOT EXISTS sync_status (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_kalshi_sync REAL DEFAULT 0.0,
                last_mapping_sync REAL DEFAULT 0.0,
                last_coverage_check REAL DEFAULT 0.0,
                sync_errors TEXT  -- JSON array
            );
            
            -- Indexes for performance
            CREATE INDEX IF NOT EXISTS idx_km_status ON kalshi_markets(status);
            CREATE INDEX IF NOT EXISTS idx_km_category ON kalshi_markets(category);
            CREATE INDEX IF NOT EXISTS idx_km_enabled ON kalshi_markets(enabled_for_merid);
            CREATE INDEX IF NOT EXISTS idx_mm_underlying ON market_mappings(underlying_symbol);
            CREATE INDEX IF NOT EXISTS idx_mm_enabled ON market_mappings(enabled);
            CREATE INDEX IF NOT EXISTS idx_mm_risk_profile ON market_mappings(risk_profile);
            CREATE INDEX IF NOT EXISTS idx_cr_checked_at ON coverage_reports(checked_at);
            
            -- Ensure sync status table has exactly one row
            INSERT OR IGNORE INTO sync_status (id) VALUES (1);
        """)
        conn.commit()
        logger.info(f"Kalshi market wiring database initialized: {self._db_path}")
    
    # Kalshi Markets Operations
    def get_series(self, series_ticker: str) -> Optional[Dict[str, Any]]:
        """Get series metadata by ticker"""
        try:
            cursor = self._conn().cursor()
            cursor.execute("""
                SELECT ticker, title, category, tags, description, created_at, updated_at
                FROM kalshi_series
                WHERE ticker = ?
            """, (series_ticker,))
            
            row = cursor.fetchone()
            if row:
                return {
                    "ticker": row[0],
                    "title": row[1],
                    "category": row[2],
                    "tags": json.loads(row[3]) if row[3] else [],
                    "description": row[4],
                    "created_at": row[5],
                    "updated_at": row[6],
                }
            return None
            
        except Exception as e:
            logger.error(f"Error getting series {series_ticker}: {e}")
            return None
    
    def upsert_series(self, series_data: Dict[str, Any]) -> bool:
        """Insert or update a series"""
        try:
            conn = self._conn()
            conn.execute("""
                INSERT OR REPLACE INTO kalshi_series (
                    ticker, title, category, tags, description, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                series_data["ticker"], series_data["title"], series_data["category"],
                json.dumps(series_data["tags"]), series_data["description"],
                series_data["created_at"], series_data["updated_at"]
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error upserting series {series_data['ticker']}: {e}")
            return False
    
    def upsert_market(self, market: KalshiMarketRecord) -> bool:
        """Insert or update a Kalshi market record"""
        try:
            conn = self._conn()
            conn.execute("""
                INSERT OR REPLACE INTO kalshi_markets (
                    market_ticker, event_ticker, series_ticker, category, tags,
                    title, subtitle, close_ts, status, enabled_for_merid,
                    risk_profile, max_notional_per_trade, max_daily_notional,
                    max_open_risk, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                market.market_ticker, market.event_ticker, market.series_ticker,
                market.category, json.dumps(market.tags), market.title,
                market.subtitle, market.close_ts, market.status.value,
                market.enabled_for_merid, market.risk_profile.value,
                market.max_notional_per_trade, market.max_daily_notional,
                market.max_open_risk, market.created_at, market.updated_at
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to upsert market {market.market_ticker}: {e}")
            return False
    
    def get_market(self, market_ticker: str) -> Optional[KalshiMarketRecord]:
        """Get a single market by ticker"""
        try:
            conn = self._conn()
            cursor = conn.execute(
                "SELECT * FROM kalshi_markets WHERE market_ticker = ?",
                (market_ticker,)
            )
            row = cursor.fetchone()
            if row:
                return KalshiMarketRecord.from_dict(dict(row))
            return None
        except Exception as e:
            logger.error(f"Failed to get market {market_ticker}: {e}")
            return None
    
    def get_open_markets(self) -> List[KalshiMarketRecord]:
        """Get all open markets"""
        try:
            conn = self._conn()
            cursor = conn.execute(
                "SELECT * FROM kalshi_markets WHERE status = ? ORDER BY close_ts",
                (MarketStatus.OPEN.value,)
            )
            return [KalshiMarketRecord.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get open markets: {e}")
            return []
    
    def get_markets_by_category(self, category: str) -> List[KalshiMarketRecord]:
        """Get markets by category"""
        try:
            conn = self._conn()
            cursor = conn.execute(
                "SELECT * FROM kalshi_markets WHERE category = ? ORDER BY close_ts",
                (category,)
            )
            return [KalshiMarketRecord.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get markets by category {category}: {e}")
            return []
    
    def get_markets_by_risk_profile(self, risk_profile: RiskProfile) -> List[KalshiMarketRecord]:
        """Get markets by risk profile"""
        try:
            conn = self._conn()
            cursor = conn.execute(
                "SELECT * FROM kalshi_markets WHERE risk_profile = ? ORDER BY close_ts",
                (risk_profile.value,)
            )
            return [KalshiMarketRecord.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get markets by risk profile {risk_profile}: {e}")
            return []
    
    def update_market_status(self, market_ticker: str, status: MarketStatus) -> bool:
        """Update market status"""
        try:
            conn = self._conn()
            conn.execute(
                "UPDATE kalshi_markets SET status = ?, updated_at = ? WHERE market_ticker = ?",
                (status.value, time.time(), market_ticker)
            )
            conn.commit()
            return conn.total_changes > 0
        except Exception as e:
            logger.error(f"Failed to update market status {market_ticker}: {e}")
            return False
    
    # Market Mapping Operations
    def upsert_mapping(self, mapping: MarketMapping) -> bool:
        """Insert or update a market mapping"""
        try:
            conn = self._conn()
            conn.execute("""
                INSERT OR REPLACE INTO market_mappings (
                    market_ticker, event_ticker, series_ticker, category,
                    risk_profile, underlying_symbol, merid_symbol,
                    sentiment_symbols, debate_symbol, enabled,
                    requires_crypto_context, requires_debate_context,
                    requires_sentiment_context, max_crypto_staleness,
                    max_sentiment_staleness, max_debate_staleness,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                mapping.market_ticker, mapping.event_ticker, mapping.series_ticker,
                mapping.category, mapping.risk_profile.value, mapping.underlying_symbol,
                mapping.merid_symbol, json.dumps(mapping.sentiment_symbols),
                mapping.debate_symbol, mapping.enabled, mapping.requires_crypto_context,
                mapping.requires_debate_context, mapping.requires_sentiment_context,
                mapping.max_crypto_staleness, mapping.max_sentiment_staleness,
                mapping.max_debate_staleness, mapping.created_at, mapping.updated_at
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to upsert mapping {mapping.market_ticker}: {e}")
            return False
    
    def get_mapping(self, market_ticker: str) -> Optional[MarketMapping]:
        """Get a single market mapping by ticker"""
        try:
            conn = self._conn()
            cursor = conn.execute(
                "SELECT * FROM market_mappings WHERE market_ticker = ?",
                (market_ticker,)
            )
            row = cursor.fetchone()
            if row:
                return MarketMapping.from_dict(dict(row))
            return None
        except Exception as e:
            logger.error(f"Failed to get mapping {market_ticker}: {e}")
            return None
    
    def get_enabled_mappings(self) -> List[MarketMapping]:
        """Get all enabled mappings"""
        try:
            conn = self._conn()
            cursor = conn.execute(
                "SELECT * FROM market_mappings WHERE enabled = ? ORDER BY underlying_symbol",
                (True,)
            )
            return [MarketMapping.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get enabled mappings: {e}")
            return []
    
    def get_mappings_by_underlying(self, underlying_symbol: str) -> List[MarketMapping]:
        """Get mappings by underlying symbol"""
        try:
            conn = self._conn()
            cursor = conn.execute(
                "SELECT * FROM market_mappings WHERE underlying_symbol = ? AND enabled = ?",
                (underlying_symbol, True)
            )
            return [MarketMapping.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get mappings for {underlying_symbol}: {e}")
            return []
    
    def get_mappings_by_risk_profile(self, risk_profile: RiskProfile) -> List[MarketMapping]:
        """Get mappings by risk profile"""
        try:
            conn = self._conn()
            cursor = conn.execute(
                "SELECT * FROM market_mappings WHERE risk_profile = ? AND enabled = ?",
                (risk_profile.value, True)
            )
            return [MarketMapping.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get mappings by risk profile {risk_profile}: {e}")
            return []
    
    # Coverage and Sync Operations
    def save_coverage_report(self, report: CoverageReport) -> bool:
        """Save a coverage report"""
        try:
            conn = self._conn()
            conn.execute("""
                INSERT INTO coverage_reports (
                    total_open_markets, mapped_markets, enabled_markets,
                    unmapped_markets, disabled_markets, unmapped_market_tickers,
                    disabled_market_tickers, coverage_by_risk_profile, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                report.total_open_markets, report.mapped_markets, report.enabled_markets,
                report.unmapped_markets, report.disabled_markets,
                json.dumps(report.unmapped_market_tickers),
                json.dumps(report.disabled_market_tickers),
                json.dumps(report.coverage_by_risk_profile),
                report.checked_at
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save coverage report: {e}")
            return False
    
    def get_latest_coverage_report(self) -> Optional[CoverageReport]:
        """Get the latest coverage report"""
        try:
            conn = self._conn()
            cursor = conn.execute(
                "SELECT * FROM coverage_reports ORDER BY checked_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                return CoverageReport(
                    total_open_markets=row["total_open_markets"],
                    mapped_markets=row["mapped_markets"],
                    enabled_markets=row["enabled_markets"],
                    unmapped_markets=row["unmapped_markets"],
                    disabled_markets=row["disabled_markets"],
                    unmapped_market_tickers=json.loads(row["unmapped_market_tickers"]),
                    disabled_market_tickers=json.loads(row["disabled_market_tickers"]),
                    coverage_by_risk_profile=json.loads(row["coverage_by_risk_profile"]),
                    checked_at=row["checked_at"]
                )
            return None
        except Exception as e:
            logger.error(f"Failed to get latest coverage report: {e}")
            return None
    
    def update_sync_timestamp(self, sync_type: str, timestamp: Optional[float] = None) -> bool:
        """Update sync timestamp"""
        try:
            conn = self._conn()
            timestamp = timestamp or time.time()
            column_map = {
                "kalshi": "last_kalshi_sync",
                "mapping": "last_mapping_sync", 
                "coverage": "last_coverage_check"
            }
            if sync_type not in column_map:
                logger.error(f"Invalid sync type: {sync_type}")
                return False
            
            column = column_map[sync_type]
            conn.execute(
                f"UPDATE sync_status SET {column} = ? WHERE id = 1",
                (timestamp,)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to update sync timestamp for {sync_type}: {e}")
            return False
    
    def get_sync_timestamps(self) -> Dict[str, float]:
        """Get all sync timestamps"""
        try:
            conn = self._conn()
            cursor = conn.execute("SELECT * FROM sync_status WHERE id = 1")
            row = cursor.fetchone()
            if row:
                return {
                    "kalshi": row["last_kalshi_sync"],
                    "mapping": row["last_mapping_sync"],
                    "coverage": row["last_coverage_check"]
                }
            return {"kalshi": 0.0, "mapping": 0.0, "coverage": 0.0}
        except Exception as e:
            logger.error(f"Failed to get sync timestamps: {e}")
            return {"kalshi": 0.0, "mapping": 0.0, "coverage": 0.0}


# Singleton instance
_kalshi_market_store: Optional[KalshiMarketStore] = None
_kalshi_market_store_lock = threading.Lock()


def get_kalshi_market_store() -> KalshiMarketStore:
    """Get singleton Kalshi market store instance"""
    global _kalshi_market_store
    if _kalshi_market_store is None:
        with _kalshi_market_store_lock:
            if _kalshi_market_store is None:
                _kalshi_market_store = KalshiMarketStore()
    return _kalshi_market_store
