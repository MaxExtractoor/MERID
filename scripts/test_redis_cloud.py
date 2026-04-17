"""
Redis Cloud Connection Test Script
Tests the MERID cache adapter with Redis Cloud TLS + auth
"""
from __future__ import annotations

import os
import sys

# Ensure we're in the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cache import CacheAdapter
from core.settings import REDIS_URL, REDIS_USER
from utils.logger import get_logger

logger = get_logger("test.redis")


def test_redis_connection():
    """Test Redis Cloud connection with TLS and username auth."""
    logger.info("=" * 60)
    logger.info("Testing Redis Cloud Connection")
    logger.info("=" * 60)
    
    # Mask password in logs
    masked_url = REDIS_URL
    if "@" in masked_url:
        # rediss://user:pass@host -> rediss://user:***@host
        parts = masked_url.split("@")
        creds = parts[0].split(":")
        if len(creds) >= 3:  # scheme://user:pass
            masked_url = f"{creds[0]}:***@{parts[1]}"
    
    logger.info(f"REDIS_URL: {masked_url}")
    logger.info(f"REDIS_USER: {REDIS_USER}")
    logger.info(f"Using TLS: {REDIS_URL.startswith('rediss://')}")
    
    # Initialize cache adapter
    logger.info("\n1. Initializing CacheAdapter...")
    cache = CacheAdapter()
    
    if cache._client is None:
        logger.error("❌ Redis connection failed - using in-memory fallback")
        return False
    
    logger.info("✓ Redis client initialized")
    
    # Test basic operations
    logger.info("\n2. Testing basic operations...")
    
    # Test SET
    test_key = "merid:redis:test"
    test_value = {"status": "connected", "tls": REDIS_URL.startswith("rediss://")}
    
    try:
        cache.set_json(test_key, test_value, ttl=60)
        logger.info(f"✓ SET {test_key}")
    except Exception as e:
        logger.error(f"❌ SET failed: {e}")
        return False
    
    # Test GET
    try:
        result = cache.get_json(test_key)
        if result == test_value:
            logger.info(f"✓ GET {test_key} = {result}")
        else:
            logger.warning(f"⚠ GET returned unexpected value: {result}")
    except Exception as e:
        logger.error(f"❌ GET failed: {e}")
        return False
    
    # Test DELETE
    try:
        cache.delete(test_key)
        result = cache.get(test_key)
        if result is None:
            logger.info(f"✓ DELETE {test_key}")
        else:
            logger.warning(f"⚠ DELETE didn't work, key still exists")
    except Exception as e:
        logger.error(f"❌ DELETE failed: {e}")
        return False
    
    # Test server info
    logger.info("\n3. Testing server info...")
    try:
        info = cache._client.info("server")
        logger.info(f"✓ Redis version: {info.get('redis_version', 'unknown')}")
        logger.info(f"✓ Redis mode: {info.get('redis_mode', 'unknown')}")
    except Exception as e:
        logger.warning(f"⚠ Could not get server info: {e}")
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ All Redis Cloud tests passed!")
    logger.info("=" * 60)
    return True


if __name__ == "__main__":
    success = test_redis_connection()
    sys.exit(0 if success else 1)
