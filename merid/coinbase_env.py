"""Resolve Coinbase Advanced Trade credentials from settings or environment.

Coinbase credentials for 15m Kalshi crypto stack:
- API key: CB-ACCESS-KEY
- API secret: signing key

Priority order:
1. merid.settings (Pydantic, single source of truth)
2. MERID_COINBASE_* env vars
3. COINBASE_CLIENT_* env vars
4. COINBASE_* env vars

Note: No passphrase is used for our endpoints - only key + secret.
"""

from __future__ import annotations

import os
from typing import Optional


def coinbase_api_key() -> Optional[str]:
    """Get Coinbase API key from settings or environment (with fallbacks)."""
    # Try settings first (single source of truth)
    try:
        from merid.settings import settings
        if settings.COINBASE_API_KEY:
            return settings.COINBASE_API_KEY
    except Exception:
        pass
    
    # Fallback to environment variables
    v = (
        os.getenv("MERID_COINBASE_API_KEY")
        or os.getenv("COINBASE_CLIENT_API_KEY")
        or os.getenv("COINBASE_API_KEY")
    )
    return v if v else None


def coinbase_api_secret() -> Optional[str]:
    """Get Coinbase API secret from settings or environment (with fallbacks)."""
    # Try settings first (single source of truth)
    try:
        from merid.settings import settings
        if settings.COINBASE_API_SECRET:
            return settings.COINBASE_API_SECRET
    except Exception:
        pass
    
    # Fallback to environment variables
    v = (
        os.getenv("MERID_COINBASE_API_SECRET")
        or os.getenv("COINBASE_CLIENT_API_SECRET")
        or os.getenv("COINBASE_API_SECRET")
    )
    return v if v else None
