#!/usr/bin/env python3
"""Create the 'merid' PostgreSQL role and database using the postgres superuser.

Usage:
    python scripts/setup_postgres_user.py
"""

import asyncio
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass


def _validate_identifier(name: str) -> bool:
    """Validate PostgreSQL identifier (role name, database name) to prevent SQL injection.
    
    Only allows alphanumeric characters, underscores, and hyphens.
    Must start with a letter or underscore.
    Maximum length is 63 characters (PostgreSQL limit).
    
    Args:
        name: The identifier to validate
        
    Returns:
        True if the identifier is safe to use in SQL queries
    """
    if not name:
        return False
    if len(name) > 63:
        return False
    # Must start with letter or underscore
    if not (name[0].isalpha() or name[0] == '_'):
        return False
    # Only allow alphanumeric, underscore, and hyphen
    for char in name:
        if not (char.isalnum() or char in ('_', '-')):
            return False
    return True


async def setup():
    import asyncpg

    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    merid_user = os.getenv("POSTGRES_USER", "merid")
    merid_password = os.getenv("POSTGRES_PASSWORD")
    merid_db = os.getenv("POSTGRES_DB", "merid")
    superuser_password = os.getenv("POSTGRES_SUPERUSER_PASSWORD", merid_password)

    if not merid_password:
        print("ERROR: POSTGRES_PASSWORD not set in .env")
        sys.exit(1)

    # SECURITY: Validate identifiers to prevent SQL injection
    if not _validate_identifier(merid_user):
        print(f"ERROR: Invalid POSTGRES_USER '{merid_user}': must be alphanumeric with underscores/hyphens")
        sys.exit(1)
    if not _validate_identifier(merid_db):
        print(f"ERROR: Invalid POSTGRES_DB '{merid_db}': must be alphanumeric with underscores/hyphens")
        sys.exit(1)

    conn = await asyncpg.connect(
        host=host, port=port, user="postgres",
        password=superuser_password, database="postgres",
    )
    try:
        role_exists = await conn.fetchval(
            "SELECT 1 FROM pg_roles WHERE rolname = $1", merid_user
        )
        if role_exists:
            # SECURITY FIX: Use parameterized query for password to prevent SQL injection
            # Use asyncpg.Identifier for role name to prevent SQL injection
            await conn.execute(
                "ALTER ROLE {} WITH LOGIN PASSWORD $1",
                asyncpg.Identifier(merid_user), merid_password
            )
            print(f"Role '{merid_user}' exists - password reset")
        else:
            # SECURITY FIX: Use parameterized query for password to prevent SQL injection
            # Use asyncpg.Identifier for role name to prevent SQL injection
            await conn.execute(
                "CREATE ROLE {} WITH LOGIN PASSWORD $1",
                asyncpg.Identifier(merid_user), merid_password
            )
            print(f"Role '{merid_user}' created")

        db_exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", merid_db
        )
        if db_exists:
            print(f"Database '{merid_db}' exists")
        else:
            # SECURITY FIX: Use asyncpg.Identifier for database and role names
            # to prevent SQL injection through proper identifier quoting
            await conn.execute(
                "CREATE DATABASE {} OWNER {}",
                asyncpg.Identifier(merid_db), asyncpg.Identifier(merid_user)
            )
            print(f"Database '{merid_db}' created")

        # SECURITY FIX: Use asyncpg.Identifier for database ownership
        await conn.execute(
            "ALTER DATABASE {} OWNER TO {}",
            asyncpg.Identifier(merid_db), asyncpg.Identifier(merid_user)
        )
        print(f"Database '{merid_db}' owned by '{merid_user}'")
    finally:
        await conn.close()

    # Verify merid user can connect
    test_conn = await asyncpg.connect(
        host=host, port=port, user=merid_user,
        password=merid_password, database=merid_db,
    )
    await test_conn.close()
    print(f"Verified: '{merid_user}' can connect to '{merid_db}'")


if __name__ == "__main__":
    asyncio.run(setup())
