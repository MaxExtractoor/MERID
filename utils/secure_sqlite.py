"""T-047: Secure SQLite connection factory.

Provides encrypted SQLite connections when sqlcipher is available,
falling back to standard sqlite3 with a warning.

Usage:
    from utils.secure_sqlite import get_secure_connection
    conn = get_secure_connection("data/mydb.sqlite")
"""

from __future__ import annotations

from utils.logger import get_logger
import os
import sqlite3
from typing import Optional

logger = get_logger(__name__)

_ENCRYPTION_KEY = os.environ.get("MERID_DB_ENCRYPTION_KEY", "")

# Try to import sqlcipher
_HAS_SQLCIPHER = False
try:
    from pysqlcipher3 import dbapi2 as sqlcipher  # type: ignore[import-untyped]
    _HAS_SQLCIPHER = True
except ImportError:
    sqlcipher = None


def get_secure_connection(
    db_path: str,
    encryption_key: Optional[str] = None,
) -> sqlite3.Connection:
    """Get a SQLite connection with encryption if available.

    Args:
        db_path: Path to the SQLite database file.
        encryption_key: Optional encryption key. Falls back to
            MERID_DB_ENCRYPTION_KEY env var.

    Returns:
        sqlite3.Connection (or sqlcipher Connection if available).
    """
    key = encryption_key or _ENCRYPTION_KEY

    if _HAS_SQLCIPHER and key:
        conn = sqlcipher.connect(db_path)
        conn.execute(f"PRAGMA key='{key}'")
        conn.execute("PRAGMA cipher_compatibility = 4")
        logger.debug("Opened encrypted SQLite: %s", db_path)
        return conn

    if key and not _HAS_SQLCIPHER:
        logger.warning(
            "MERID_DB_ENCRYPTION_KEY is set but pysqlcipher3 is not installed. "
            "Database '%s' is NOT encrypted. Install pysqlcipher3 for encryption.",
            db_path,
        )

    conn = sqlite3.connect(db_path)
    # Enable WAL mode for better concurrent read performance
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
