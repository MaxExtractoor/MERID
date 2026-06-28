"""
Crypto Market Status API

Provides information about crypto market access and availability
"""

from fastapi import APIRouter
from typing import Dict, Any
import os

router = APIRouter()

@router.get("/crypto/status")
async def get_crypto_market_status() -> Dict[str, Any]:
    """Get crypto market access status"""
    
    # Check if we have crypto market access
    has_crypto_access = False  # Would be determined from actual API access
    
    return {
        "crypto_available": has_crypto_access,
        "market_types": {
            "available": ["sports", "economics", "weather", "politics"],
            "coming_soon": ["crypto"] if not has_crypto_access else [],
            "message": "Crypto markets require special API access" if not has_crypto_access else "Crypto markets available"
        },
        "account_info": {
            "api_key_id": os.getenv("KALSHI_API_KEY_ID", "")[:8] + "..." if os.getenv("KALSHI_API_KEY_ID") else None,
            "environment": "demo" if os.getenv("KALSHI_USE_DEMO", "false").lower() == "true" else "production"  # TODO: migrate to kalshi_config.get_kalshi_env()
        },
        "next_steps": [
            "Contact Kalshi support for crypto market access",
            "Check account permissions",
            "Upgrade to crypto-enabled account"
        ] if not has_crypto_access else []
    }

@router.get("/crypto/markets")
async def get_crypto_markets() -> Dict[str, Any]:
    """Get available crypto markets"""
    
    # This would return actual crypto markets when available
    return {
        "markets": [],
        "message": "Crypto markets not currently accessible",
        "suggestion": "Contact Kalshi support for crypto market access"
    }
