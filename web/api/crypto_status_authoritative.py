"""
Authoritative Crypto Status API

State-driven crypto market status without speculation
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
import asyncio
import os
from datetime import datetime

router = APIRouter()

@router.get("/crypto/status")
async def get_crypto_market_status() -> Dict[str, Any]:
    """Get authoritative crypto market status based on actual API checks"""
    
    try:
        # Import here to avoid circular imports
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        
        # Get catalog and build summary
        catalog = get_market_catalog()
        summary = catalog.build_catalog_summary()
        
        # Test connectivity
        connectivity = await test_kalshi_connectivity()
        
        # Determine status based on actual state
        crypto_count = summary["counts"].get("crypto", 0)
        
        if connectivity["primary_endpoint"]["status"] == "error" and connectivity["fallback_endpoint"]["status"] == "error":
            status = "error"
            crypto_available = False
        elif crypto_count > 0:
            status = "ok"
            crypto_available = True
        else:
            status = "no_markets_visible"
            crypto_available = False
        
        return {
            "crypto_available": crypto_available,
            "status": status,
            "kalshi_environment": "demo" if os.getenv("KALSHI_USE_DEMO", "false").lower() == "true" else "production",
            "total_markets_seen": summary["total_markets"],
            "crypto_markets_seen": crypto_count,
            "last_checked_at": datetime.now().isoformat(),
            "connectivity": connectivity,
            "catalog_summary": summary,
            "crypto_examples": summary["examples"].get("crypto"),
            "next_steps": get_next_steps(status, crypto_count, connectivity)
        }
        
    except Exception as e:
        return {
            "crypto_available": False,
            "status": "error",
            "kalshi_environment": "demo" if os.getenv("KALSHI_USE_DEMO", "false").lower() == "true" else "production",
            "total_markets_seen": 0,
            "crypto_markets_seen": 0,
            "last_checked_at": datetime.now().isoformat(),
            "connectivity": {
                "primary_endpoint": {"url": "", "status": "error"},
                "fallback_endpoint": {"url": "", "status": "error"},
            },
            "error": str(e),
        }

@router.get("/crypto/markets")
async def get_crypto_markets() -> Dict[str, Any]:
    """Get available crypto markets"""
    
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        
        catalog = get_market_catalog()
        summary = catalog.build_catalog_summary()
        
        crypto_markets = []
        if summary["counts"].get("crypto", 0) > 0:
            all_markets = catalog.get_all_markets()
            crypto_markets = [
                {
                    "ticker": market.market_id,
                    "title": market.question or "",
                    "subtitle": getattr(market, 'subtitle', ''),
                    "active": market.market.active,
                    "category": market.category,
                    "asset": market.asset,
                    "expires_at": market.expires_at
                }
                for market in all_markets
                if catalog.classify_market_unified(market) == "crypto"
            ]
        
        return {
            "markets": crypto_markets,
            "count": len(crypto_markets),
            "status": "ok" if crypto_markets else "no_crypto_markets"
        }
        
    except Exception as e:
        return {
            "markets": [],
            "count": 0,
            "status": "error",
            "error": str(e),
        }

async def test_kalshi_connectivity() -> Dict[str, Any]:
    """Test Kalshi API connectivity"""
    import httpx
    
    results = {
        "primary_endpoint": {
            "url": "https://api.kalshi.co",
            "status": "unknown",
            "error_type": None,
            "error_message": None
        },
        "fallback_endpoint": {
            "url": "https://api.elections.kalshi.com", 
            "status": "unknown",
            "error_type": None,
            "error_message": None
        }
    }
    
    # Test primary endpoint
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get("https://api.kalshi.co/trade-api/v2/markets?limit=10")
            
            if response.status_code == 200:
                results["primary_endpoint"]["status"] = "ok"
            else:
                results["primary_endpoint"]["status"] = "http_error"
                results["primary_endpoint"]["error_type"] = f"http_{response.status_code}"
                results["primary_endpoint"]["error_message"] = response.text[:100]
                
    except httpx.ConnectError as e:
        results["primary_endpoint"]["status"] = "error"
        results["primary_endpoint"]["error_type"] = "connection_error"
        results["primary_endpoint"]["error_message"] = str(e)
    except Exception as e:
        results["primary_endpoint"]["status"] = "error"
        results["primary_endpoint"]["error_type"] = "unknown"
        results["primary_endpoint"]["error_message"] = str(e)
    
    # Test fallback endpoint
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get("https://api.elections.kalshi.com/trade-api/v2/markets?limit=10")
            
            if response.status_code == 200:
                results["fallback_endpoint"]["status"] = "ok"
            else:
                results["fallback_endpoint"]["status"] = "http_error"
                results["fallback_endpoint"]["error_type"] = f"http_{response.status_code}"
                results["fallback_endpoint"]["error_message"] = response.text[:100]
                
    except Exception as e:
        results["fallback_endpoint"]["status"] = "error"
        results["fallback_endpoint"]["error_type"] = type(e).__name__
        results["fallback_endpoint"]["error_message"] = str(e)
    
    return results

def get_next_steps(status: str, crypto_count: int, connectivity: Dict[str, Any]) -> list:
    """Get actionable next steps based on actual state"""
    steps = []
    
    if status == "error":
        if connectivity["primary_endpoint"]["error_type"] == "connection_error":
            steps.append("Check network connectivity to Kalshi API")
            steps.append("Verify DNS resolution for api.kalshi.co")
        else:
            steps.append("Check Kalshi API credentials")
    
    elif status == "no_markets_visible":
        steps.append("Verify account has crypto market access")
        steps.append("Check Kalshi account settings in web UI")
    
    elif status == "ok":
        steps.append("Crypto markets available - trading bot can run")
        steps.append("Monitor BTC market opportunities")
    
    return steps
