"""
PnL Attribution Database Schema and Persistence
Durable storage for trade records, attribution data, and configuration history.
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
import asyncio
import json
import sqlite3
from contextlib import contextmanager

from core.slo_monitor import SLOMonitor

logger = logging.getLogger("merid.prediction.pnl_attribution_db")


class ConfigVersionStatus(Enum):
    """Status of configuration versions."""
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"


@dataclass
class ConfigVersion:
    """Versioned configuration record."""
    version: str
    config_type: str  # "risk_limits", "agent_tiers", "exit_policy", "deployment"
    config_data: Dict[str, Any]
    status: ConfigVersionStatus
    created_by: str
    created_at: datetime
    reason: Optional[str] = None
    activated_at: Optional[datetime] = None
    superseded_at: Optional[datetime] = None


@dataclass
class PersistentTradeRecord:
    """Persistent trade record for database storage."""
    id: Optional[int] = None  # Primary key
    symbol: str = ""
    trade_type: str = ""  # "entry", "exit", "trim"
    timestamp: float = 0.0
    price: float = 0.0
    quantity: int = 0
    trade_id: str = ""
    agent_id: Optional[str] = None
    base_kelly_fraction: float = 0.0
    debate_multiplier: float = 1.0
    final_kelly_fraction: float = 0.0
    debate_recommendation: Optional[str] = None
    exit_reason: Optional[str] = None
    base_position_size: float = 0.0
    debate_position_size: float = 0.0
    debate_risk_amount: float = 0.0
    realized_pnl: Optional[float] = None
    base_pnl: Optional[float] = None
    debate_pnl_impact: Optional[float] = None
    exit_pnl_impact: Optional[float] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AttributionRecord:
    """Attribution analysis record."""
    id: Optional[int] = None  # Primary key
    symbol: str = ""
    entry_trade_id: str = ""
    exit_trade_id: Optional[str] = None
    entry_timestamp: float = 0.0
    exit_timestamp: Optional[float] = None
    holding_period_hours: float = 0.0
    realized_pnl: float = 0.0
    base_pnl: float = 0.0
    debate_sizing_impact: float = 0.0
    debate_exit_impact: float = 0.0
    total_debate_contribution: float = 0.0
    debate_contribution_pct: float = 0.0
    agent_id: Optional[str] = None
    entry_debate_multiplier: float = 1.0
    exit_debate_driven: bool = False
    config_version: Optional[str] = None  # Which config version was active
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DailySummary:
    """Daily summary record."""
    date: datetime
    total_trades: int = 0
    total_realized_pnl: float = 0.0
    total_base_pnl: float = 0.0
    total_debate_contribution: float = 0.0
    debate_sizing_win_rate: float = 0.0
    debate_exit_win_rate: float = 0.0
    debate_contribution_pct: float = 0.0
    top_agents: List[Dict[str, Any]] = field(default_factory=list)
    top_symbols: List[Dict[str, Any]] = field(default_factory=list)
    active_config_versions: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PnLAttributionDB:
    """Database manager for PnL attribution data."""
    
    def __init__(self, db_path: str = "merid_pnl_attribution.db"):
        self.db_path = db_path
        self.slo_monitor = SLOMonitor()
        self._init_database()
    
    def _init_database(self):
        """Initialize database tables."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Trade records table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trade_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        trade_type TEXT NOT NULL,
                        timestamp REAL NOT NULL,
                        price REAL NOT NULL,
                        quantity INTEGER NOT NULL,
                        trade_id TEXT NOT NULL UNIQUE,
                        agent_id TEXT,
                        base_kelly_fraction REAL DEFAULT 0.0,
                        debate_multiplier REAL DEFAULT 1.0,
                        final_kelly_fraction REAL DEFAULT 0.0,
                        debate_recommendation TEXT,
                        exit_reason TEXT,
                        base_position_size REAL DEFAULT 0.0,
                        debate_position_size REAL DEFAULT 0.0,
                        debate_risk_amount REAL DEFAULT 0.0,
                        realized_pnl REAL,
                        base_pnl REAL,
                        debate_pnl_impact REAL,
                        exit_pnl_impact REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Attribution records table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS attribution_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        entry_trade_id TEXT NOT NULL,
                        exit_trade_id TEXT,
                        entry_timestamp REAL NOT NULL,
                        exit_timestamp REAL,
                        holding_period_hours REAL DEFAULT 0.0,
                        realized_pnl REAL NOT NULL,
                        base_pnl REAL NOT NULL,
                        debate_sizing_impact REAL DEFAULT 0.0,
                        debate_exit_impact REAL DEFAULT 0.0,
                        total_debate_contribution REAL DEFAULT 0.0,
                        debate_contribution_pct REAL DEFAULT 0.0,
                        agent_id TEXT,
                        entry_debate_multiplier REAL DEFAULT 1.0,
                        exit_debate_driven BOOLEAN DEFAULT FALSE,
                        config_version TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Configuration versions table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS config_versions (
                        version TEXT PRIMARY KEY,
                        config_type TEXT NOT NULL,
                        config_data TEXT NOT NULL,  -- JSON
                        status TEXT NOT NULL,
                        created_by TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        reason TEXT,
                        activated_at TIMESTAMP,
                        superseded_at TIMESTAMP
                    )
                """)
                
                # Daily summaries table for quick analytics
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS daily_summaries (
                        date DATE PRIMARY KEY,
                        total_trades INTEGER DEFAULT 0,
                        total_realized_pnl REAL DEFAULT 0.0,
                        total_base_pnl REAL DEFAULT 0.0,
                        total_debate_contribution REAL DEFAULT 0.0,
                        debate_sizing_win_rate REAL DEFAULT 0.0,
                        debate_exit_win_rate REAL DEFAULT 0.0,
                        debate_contribution_pct REAL DEFAULT 0.0,
                        top_agents TEXT,  -- JSON
                        top_symbols TEXT,  -- JSON
                        active_config_versions TEXT,  -- JSON array of active config versions
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes for performance
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_records_symbol ON trade_records(symbol)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_records_timestamp ON trade_records(timestamp)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_records_agent ON trade_records(agent_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_attribution_records_symbol ON attribution_records(symbol)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_attribution_records_date ON attribution_records(created_at)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_config_versions_type ON config_versions(config_type)")
                
                conn.commit()
                logger.info("Database initialized successfully")
                
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """Get database connection with proper cleanup."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        try:
            yield conn
        finally:
            conn.close()
    
    async def store_trade_record(self, trade_record: PersistentTradeRecord) -> int:
        """Store a trade record in the database."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO trade_records (
                        symbol, trade_type, timestamp, price, quantity, trade_id,
                        agent_id, base_kelly_fraction, debate_multiplier, final_kelly_fraction,
                        debate_recommendation, exit_reason, base_position_size,
                        debate_position_size, debate_risk_amount, realized_pnl,
                        base_pnl, debate_pnl_impact, exit_pnl_impact, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade_record.symbol, 
                    trade_record.trade_type.value if hasattr(trade_record.trade_type, 'value') else trade_record.trade_type,
                    trade_record.timestamp,
                    trade_record.price, trade_record.quantity, trade_record.trade_id,
                    trade_record.agent_id, trade_record.base_kelly_fraction,
                    trade_record.debate_multiplier, trade_record.final_kelly_fraction,
                    trade_record.debate_recommendation, trade_record.exit_reason,
                    trade_record.base_position_size, trade_record.debate_position_size,
                    trade_record.debate_risk_amount, trade_record.realized_pnl,
                    trade_record.base_pnl, trade_record.debate_pnl_impact,
                    trade_record.exit_pnl_impact, datetime.now(timezone.utc).isoformat()
                ))
                
                trade_id = cursor.lastrowid
                conn.commit()
                
                # Track SLO
                self.slo_monitor.track_slo(
                    metric_name="debate.pnl_attribution.trade_stored",
                    success=True,
                    total=1,
                    metadata={
                        "symbol": trade_record.symbol,
                        "trade_type": trade_record.trade_type.value if hasattr(trade_record.trade_type, 'value') else trade_record.trade_type,
                        "agent_id": trade_record.agent_id
                    }
                )
                
                logger.debug(f"Stored trade record: {trade_record.trade_id}")
                return trade_id
                
        except Exception as e:
            logger.error(f"Error storing trade record: {e}")
            raise
    
    async def store_attribution_record(self, attribution: AttributionRecord) -> int:
        """Store an attribution record in the database."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO attribution_records (
                        symbol, entry_trade_id, exit_trade_id, entry_timestamp,
                        exit_timestamp, holding_period_hours, realized_pnl, base_pnl,
                        debate_sizing_impact, debate_exit_impact, total_debate_contribution,
                        debate_contribution_pct, agent_id, entry_debate_multiplier,
                        exit_debate_driven, config_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    attribution.symbol, attribution.entry_trade_id, attribution.exit_trade_id,
                    attribution.entry_timestamp, attribution.exit_timestamp,
                    attribution.holding_period_hours, attribution.realized_pnl,
                    attribution.base_pnl, attribution.debate_sizing_impact,
                    attribution.debate_exit_impact, attribution.total_debate_contribution,
                    attribution.debate_contribution_pct, attribution.agent_id,
                    attribution.entry_debate_multiplier, attribution.exit_debate_driven,
                    attribution.config_version
                ))
                
                attribution_id = cursor.lastrowid
                conn.commit()
                
                # Track SLO
                self.slo_monitor.track_slo(
                    metric_name="debate.pnl_attribution.attribution_stored",
                    success=True,
                    total=1,
                    metadata={
                        "symbol": attribution.symbol,
                        "debate_contribution": attribution.total_debate_contribution,
                        "debate_contribution_pct": attribution.debate_contribution_pct
                    }
                )
                
                logger.debug(f"Stored attribution record: {attribution.entry_trade_id}")
                return attribution_id
                
        except Exception as e:
            logger.error(f"Error storing attribution record: {e}")
            raise
    
    async def store_config_version(self, config: ConfigVersion) -> None:
        """Store a configuration version in the database."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO config_versions (
                        version, config_type, config_data, status, created_by,
                        created_at, reason, activated_at, superseded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    config.version, config.config_type, json.dumps(config.config_data),
                    config.status.value, config.created_by,
                    config.created_at.isoformat(),
                    config.reason,
                    config.activated_at.isoformat() if config.activated_at else None,
                    config.superseded_at.isoformat() if config.superseded_at else None
                ))
                
                conn.commit()
                
                # Track SLO
                self.slo_monitor.track_slo(
                    metric_name="debate.pnl_attribution.config_stored",
                    success=True,
                    total=1,
                    metadata={
                        "config_type": config.config_type,
                        "version": config.version,
                        "status": config.status.value
                    }
                )
                
                logger.info(f"Stored config version: {config.version} ({config.config_type})")
                
        except Exception as e:
            logger.error(f"Error storing config version: {e}")
            raise
    
    async def get_trade_records(
        self,
        symbol: Optional[str] = None,
        agent_id: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: Optional[int] = None
    ) -> List[PersistentTradeRecord]:
        """Retrieve trade records with optional filtering."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                query = "SELECT * FROM trade_records WHERE 1=1"
                params = []
                
                if symbol:
                    query += " AND symbol = ?"
                    params.append(symbol)
                
                if agent_id:
                    query += " AND agent_id = ?"
                    params.append(agent_id)
                
                if start_time:
                    query += " AND timestamp >= ?"
                    params.append(start_time)
                
                if end_time:
                    query += " AND timestamp <= ?"
                    params.append(end_time)
                
                query += " ORDER BY timestamp DESC"
                
                if limit:
                    query += " LIMIT ?"
                    params.append(limit)
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                trades = []
                for row in rows:
                    trade = PersistentTradeRecord(
                        id=row["id"],
                        symbol=row["symbol"],
                        trade_type=row["trade_type"],
                        timestamp=row["timestamp"],
                        price=row["price"],
                        quantity=row["quantity"],
                        trade_id=row["trade_id"],
                        agent_id=row["agent_id"],
                        base_kelly_fraction=row["base_kelly_fraction"],
                        debate_multiplier=row["debate_multiplier"],
                        final_kelly_fraction=row["final_kelly_fraction"],
                        debate_recommendation=row["debate_recommendation"],
                        exit_reason=row["exit_reason"],
                        base_position_size=row["base_position_size"],
                        debate_position_size=row["debate_position_size"],
                        debate_risk_amount=row["debate_risk_amount"],
                        realized_pnl=row["realized_pnl"],
                        base_pnl=row["base_pnl"],
                        debate_pnl_impact=row["debate_pnl_impact"],
                        exit_pnl_impact=row["exit_pnl_impact"],
                        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(timezone.utc),
                        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.now(timezone.utc)
                    )
                    trades.append(trade)
                
                return trades
                
        except Exception as e:
            logger.error(f"Error retrieving trade records: {e}")
            raise
    
    async def get_attribution_records(
        self,
        symbol: Optional[str] = None,
        agent_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        config_version: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[AttributionRecord]:
        """Retrieve attribution records with optional filtering."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                query = "SELECT * FROM attribution_records WHERE 1=1"
                params = []
                
                if symbol:
                    query += " AND symbol = ?"
                    params.append(symbol)
                
                if agent_id:
                    query += " AND agent_id = ?"
                    params.append(agent_id)
                
                if start_date:
                    query += " AND created_at >= ?"
                    params.append(start_date)
                
                if end_date:
                    query += " AND created_at <= ?"
                    params.append(end_date)
                
                if config_version:
                    query += " AND config_version = ?"
                    params.append(config_version)
                
                query += " ORDER BY created_at DESC"
                
                if limit:
                    query += " LIMIT ?"
                    params.append(limit)
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                attributions = []
                for row in rows:
                    attribution = AttributionRecord(
                        id=row["id"],
                        symbol=row["symbol"],
                        entry_trade_id=row["entry_trade_id"],
                        exit_trade_id=row["exit_trade_id"],
                        entry_timestamp=row["entry_timestamp"],
                        exit_timestamp=row["exit_timestamp"],
                        holding_period_hours=row["holding_period_hours"],
                        realized_pnl=row["realized_pnl"],
                        base_pnl=row["base_pnl"],
                        debate_sizing_impact=row["debate_sizing_impact"],
                        debate_exit_impact=row["debate_exit_impact"],
                        total_debate_contribution=row["total_debate_contribution"],
                        debate_contribution_pct=row["debate_contribution_pct"],
                        agent_id=row["agent_id"],
                        entry_debate_multiplier=row["entry_debate_multiplier"],
                        exit_debate_driven=bool(row["exit_debate_driven"]),
                        config_version=row["config_version"],
                        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(timezone.utc)
                    )
                    attributions.append(attribution)
                
                return attributions
                
        except Exception as e:
            logger.error(f"Error retrieving attribution records: {e}")
            raise
    
    async def get_config_versions(
        self,
        config_type: Optional[str] = None,
        status: Optional[ConfigVersionStatus] = None,
        limit: Optional[int] = None
    ) -> List[ConfigVersion]:
        """Retrieve configuration versions."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                query = "SELECT * FROM config_versions WHERE 1=1"
                params = []
                
                if config_type:
                    query += " AND config_type = ?"
                    params.append(config_type)
                
                if status:
                    query += " AND status = ?"
                    params.append(status.value)
                
                query += " ORDER BY created_at DESC"
                
                if limit:
                    query += " LIMIT ?"
                    params.append(limit)
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                configs = []
                for row in rows:
                    config = ConfigVersion(
                        version=row["version"],
                        config_type=row["config_type"],
                        config_data=json.loads(row["config_data"]),
                        status=ConfigVersionStatus(row["status"]),
                        created_by=row["created_by"],
                        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(timezone.utc),
                        reason=row["reason"],
                        activated_at=datetime.fromisoformat(row["activated_at"]) if row["activated_at"] else None,
                        superseded_at=datetime.fromisoformat(row["superseded_at"]) if row["superseded_at"] else None
                    )
                    configs.append(config)
                
                return configs
                
        except Exception as e:
            logger.error(f"Error retrieving config versions: {e}")
            raise
    
    async def get_daily_summary(self, date: datetime) -> Optional[Dict[str, Any]]:
        """Get daily summary for a specific date."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM daily_summaries WHERE date = ?
                """, (date.date(),))
                
                row = cursor.fetchone()
                if row:
                    return {
                        "date": row["date"],
                        "total_trades": row["total_trades"],
                        "total_realized_pnl": row["total_realized_pnl"],
                        "total_base_pnl": row["total_base_pnl"],
                        "total_debate_contribution": row["total_debate_contribution"],
                        "debate_sizing_win_rate": row["debate_sizing_win_rate"],
                        "debate_exit_win_rate": row["debate_exit_win_rate"],
                        "debate_contribution_pct": row["debate_contribution_pct"],
                        "top_agents": json.loads(row["top_agents"]) if row["top_agents"] else [],
                        "top_symbols": json.loads(row["top_symbols"]) if row["top_symbols"] else [],
                        "active_config_versions": json.loads(row["active_config_versions"]) if row["active_config_versions"] else []
                    }
                else:
                    return None
                    
        except Exception as e:
            logger.error(f"Error retrieving daily summary: {e}")
            raise
    
    async def update_daily_summary(self, date: datetime, summary_data: Dict[str, Any]):
        """Update or insert daily summary."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO daily_summaries (
                        date, total_trades, total_realized_pnl, total_base_pnl,
                        total_debate_contribution, debate_sizing_win_rate,
                        debate_exit_win_rate, debate_contribution_pct,
                        top_agents, top_symbols, active_config_versions, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    date.date(),
                    summary_data["total_trades"],
                    summary_data["total_realized_pnl"],
                    summary_data["total_base_pnl"],
                    summary_data["total_debate_contribution"],
                    summary_data["debate_sizing_win_rate"],
                    summary_data["debate_exit_win_rate"],
                    summary_data["debate_contribution_pct"],
                    json.dumps(summary_data["top_agents"]),
                    json.dumps(summary_data["top_symbols"]),
                    json.dumps(summary_data.get("active_config_versions", [])),
                    datetime.now(timezone.utc).isoformat()
                ))
                
                conn.commit()
                logger.debug(f"Updated daily summary for {date.date()}")
                
        except Exception as e:
            logger.error(f"Error updating daily summary: {e}")
            raise
    
    async def cleanup_old_records(self, days_to_keep: int = 365):
        """Clean up old records to manage database size."""
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Delete old trade records
                cursor.execute("""
                    DELETE FROM trade_records WHERE created_at < ?
                """, (cutoff_date,))
                
                trades_deleted = cursor.rowcount
                
                # Delete old attribution records
                cursor.execute("""
                    DELETE FROM attribution_records WHERE created_at < ?
                """, (cutoff_date,))
                
                attributions_deleted = cursor.rowcount
                
                # Delete old daily summaries
                cursor.execute("""
                    DELETE FROM daily_summaries WHERE date < ?
                """, (cutoff_date.date(),))
                
                summaries_deleted = cursor.rowcount
                
                conn.commit()
                
                logger.info(
                    f"Cleaned up old records: {trades_deleted} trades, "
                    f"{attributions_deleted} attributions, {summaries_deleted} summaries"
                )
                
        except Exception as e:
            logger.error(f"Error cleaning up old records: {e}")
            raise
    
    async def get_active_config_versions(self, timestamp: float) -> List[str]:
        """Get active configuration versions for a given timestamp."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Convert timestamp to datetime for comparison
                dt = datetime.fromtimestamp(timestamp, timezone.utc)
                
                cursor.execute("""
                    SELECT version FROM config_versions 
                    WHERE status = 'active' 
                    AND created_at <= ? 
                    AND (superseded_at IS NULL OR superseded_at > ?)
                    ORDER BY created_at DESC
                """, (dt.isoformat(), dt.isoformat()))
                
                rows = cursor.fetchall()
                return [row["version"] for row in rows]
                
        except Exception as e:
            logger.error(f"Error getting active config versions: {e}")
            return []
    
    async def update_daily_summary_with_configs(self, date: datetime, summary_data: Dict[str, Any]):
        """Update daily summary including active config versions."""
        try:
            # Get active config versions for the day
            start_timestamp = date.timestamp()
            end_timestamp = (date + timedelta(days=1)).timestamp()
            
            # Get active configs during this period
            active_configs = await self.get_active_config_versions(start_timestamp)
            
            # Add to summary data
            summary_data["active_config_versions"] = active_configs
            
            # Update the summary
            await self.update_daily_summary(date, summary_data)
            
        except Exception as e:
            logger.error(f"Error updating daily summary with configs: {e}")
            raise
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Count records in each table
                cursor.execute("SELECT COUNT(*) FROM trade_records")
                trade_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM attribution_records")
                attribution_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM config_versions")
                config_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM daily_summaries")
                summary_count = cursor.fetchone()[0]
                
                # Get database size
                cursor.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
                result = cursor.fetchone()
                db_size = result[0] if result else 0
                
                return {
                    "trade_records": trade_count,
                    "attribution_records": attribution_count,
                    "config_versions": config_count,
                    "daily_summaries": summary_count,
                    "database_size_bytes": db_size,
                    "database_size_mb": db_size / (1024 * 1024)
                }
                
        except Exception as e:
            logger.error(f"Error getting database stats: {e}")
            return {"error": str(e)}


# Global instance
_db_instance: Optional[PnLAttributionDB] = None


def get_pnl_attribution_db() -> PnLAttributionDB:
    """Get the global PnL attribution database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = PnLAttributionDB()
    return _db_instance
