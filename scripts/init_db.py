"""
MERID Database Initialization Script
Creates all necessary tables and initial data for production deployment.
"""

import os
import sqlite3
from pathlib import Path

# Ensure data directory exists
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "merid.db"

# SQL to create all tables
CREATE_TABLES_SQL = """
-- Users and authentication
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE,
    wallet_address TEXT UNIQUE,
    twitter_handle TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_verified BOOLEAN DEFAULT FALSE,
    total_referrals INTEGER DEFAULT 0,
    referred_by TEXT,
    FOREIGN KEY (referred_by) REFERENCES users(user_id)
);

-- Sessions
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address TEXT,
    user_agent TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Trading positions
CREATE TABLE IF NOT EXISTS positions (
    position_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT CHECK(side IN ('yes', 'no', 'long', 'short')),
    size REAL NOT NULL,
    entry_price REAL NOT NULL,
    current_price REAL,
    unrealized_pnl REAL DEFAULT 0,
    realized_pnl REAL DEFAULT 0,
    venue TEXT DEFAULT 'kalshi',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'open' CHECK(status IN ('open', 'closed', 'liquidated')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Orders
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    position_id TEXT,
    ticker TEXT NOT NULL,
    side TEXT CHECK(side IN ('yes', 'no', 'buy', 'sell')),
    order_type TEXT CHECK(order_type IN ('market', 'limit', 'stop')),
    size REAL NOT NULL,
    price REAL,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'filled', 'partial', 'cancelled', 'rejected')),
    filled_size REAL DEFAULT 0,
    avg_fill_price REAL,
    venue TEXT DEFAULT 'kalshi',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (position_id) REFERENCES positions(position_id) ON DELETE SET NULL
);

-- Trades/Fills
CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    size REAL NOT NULL,
    price REAL NOT NULL,
    fees REAL DEFAULT 0,
    venue TEXT DEFAULT 'kalshi',
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Risk events
CREATE TABLE IF NOT EXISTS risk_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    severity TEXT CHECK(severity IN ('info', 'warning', 'critical')),
    description TEXT,
    ticker TEXT,
    value REAL,
    threshold REAL,
    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    auto_resolved BOOLEAN DEFAULT FALSE
);

-- Notifications
CREATE TABLE IF NOT EXISTS notifications (
    notification_id TEXT PRIMARY KEY,
    user_id TEXT,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    severity TEXT CHECK(severity IN ('info', 'warning', 'error', 'success')),
    read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Agent activity
CREATE TABLE IF NOT EXISTS agent_activity (
    activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    agent_name TEXT,
    action TEXT NOT NULL,
    ticker TEXT,
    details TEXT,
    success BOOLEAN,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Market data cache
CREATE TABLE IF NOT EXISTS market_data_cache (
    ticker TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

-- System settings
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    action TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    details TEXT,
    ip_address TEXT,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
);
"""

# Default system settings
DEFAULT_SETTINGS = [
    ("trading_mode", "paper"),
    ("kalshi_only", "true"),
    ("max_order_size_usd", "100"),
    ("max_daily_loss_usd", "500"),
    ("max_position_size_usd", "1000"),
    ("kill_switch_active", "false"),
    ("last_kill_switch_reason", ""),
    ("circuit_breaker_enabled", "true"),
    ("circuit_breaker_threshold", "0.1"),
    ("daily_pnl", "0"),
    ("session_start_pnl", "0"),
]


def init_database():
    """Initialize the database with all tables and default data."""
    print(f"Initializing database at: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create tables
    print("Creating tables...")
    cursor.executescript(CREATE_TABLES_SQL)
    
    # Insert default settings
    print("Inserting default settings...")
    cursor.executemany(
        "INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)",
        DEFAULT_SETTINGS
    )
    
    conn.commit()
    conn.close()
    
    print("OK: Database initialized successfully")
    print(f"OK: Database location: {DB_PATH.absolute()}")
    return True


def verify_database():
    """Verify database was created correctly."""
    if not DB_PATH.exists():
        print("FAIL: Database file not found")
        return False
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    
    expected_tables = [
        'users', 'sessions', 'positions', 'orders', 'trades',
        'risk_events', 'notifications', 'agent_activity',
        'market_data_cache', 'system_settings', 'audit_log'
    ]
    
    missing = set(expected_tables) - set(tables)
    if missing:
        print(f"FAIL: Missing tables: {missing}")
        return False
    
    # Check settings
    cursor.execute("SELECT COUNT(*) FROM system_settings")
    settings_count = cursor.fetchone()[0]
    
    conn.close()
    
    print(f"OK: All {len(expected_tables)} tables present")
    print(f"OK: {settings_count} default settings loaded")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("MERID Database Initialization")
    print("=" * 60)
    
    if init_database():
        print()
        if verify_database():
            print()
            print("=" * 60)
            print("OK: Database ready for production")
            print("=" * 60)
        else:
            print("FAIL: Database verification failed")
            exit(1)
    else:
        print("FAIL: Database initialization failed")
        exit(1)
