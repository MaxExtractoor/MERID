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

    conn = await asyncpg.connect(
        host=host, port=port, user="postgres",
        password=superuser_password, database="postgres",
    )
    try:
        role_exists = await conn.fetchval(
            "SELECT 1 FROM pg_roles WHERE rolname = $1", merid_user
        )
        if role_exists:
            await conn.execute(
                f"ALTER ROLE {merid_user} WITH LOGIN PASSWORD '{merid_password}'"
            )
            print(f"Role '{merid_user}' exists - password reset")
        else:
            await conn.execute(
                f"CREATE ROLE {merid_user} WITH LOGIN PASSWORD '{merid_password}'"
            )
            print(f"Role '{merid_user}' created")

        db_exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", merid_db
        )
        if db_exists:
            print(f"Database '{merid_db}' exists")
        else:
            await conn.execute(f"CREATE DATABASE {merid_db} OWNER {merid_user}")
            print(f"Database '{merid_db}' created")

        await conn.execute(f"ALTER DATABASE {merid_db} OWNER TO {merid_user}")
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
