"""
Minimal MERID Web Application - Kalshi Integration Test

Simple FastAPI app to test Kalshi endpoints without complex initialization.
"""

from fastapi import FastAPI
from contextlib import asynccontextmanager
import os
import sys

# Add path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger
from merid.event_venues.kalshi.venue_adapter import KalshiVenueAdapter
from merid.venue_registry import VenueRegistry

logger = get_logger("merid.web.minimal")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Minimal lifespan with just Kalshi venue"""
    logger.info("Starting minimal MERID with Kalshi venue")
    
    # Live-first configuration
    trading_mode = os.getenv("MERID_TRADING_MODE", "live").lower()
    use_demo = os.getenv("KALSHI_USE_DEMO", "false").lower() == "true"
    
    logger.info(f"Configuration:")
    logger.info(f"  Trading Mode: {trading_mode}")
    logger.info(f"  Demo Mode: {use_demo}")
    logger.info(f"  API Key ID: {'SET' if os.getenv('KALSHI_API_KEY_ID') else 'MISSING'}")
    
    # Initialize just the venue registry and Kalshi adapter
    venue_registry = VenueRegistry()
    venue_mode = "paper" if trading_mode == "paper" else "live"
    kalshi_venue = KalshiVenueAdapter(mode=venue_mode)
    venue_registry.register(kalshi_venue)
    
    # Store in app state
    app.state.venue_registry = venue_registry
    app.state.kalshi_venue = kalshi_venue
    
    logger.info("Minimal MERID startup complete")
    
    yield
    
    logger.info("Shutting down minimal MERID")

# Create FastAPI app
app = FastAPI(
    title="MERID (Minimal)",
    description="MERID trading system - Kalshi integration test",
    version="1.0.0",
    lifespan=lifespan,
)

# Health check
@app.get("/health")
async def health():
    return {"status": "ok", "service": "merid-minimal"}

# Kalshi endpoints
@app.get("/api/v1/kalshi/status")
async def kalshi_status():
    """Get Kalshi venue status"""
    try:
        venue = app.state.venue_registry.get_venue("kalshi")
        if not venue:
            return {"error": "Kalshi venue not found"}
        
        # For now, return basic status without async calls
        return {
            "venue_id": "kalshi",
            "status": "connected",
            "total_markets": 0,
            "crypto_markets": 0,
            "error_message": None,
        }
    except Exception as e:
        logger.error(f"Kalshi status endpoint error: {e}")
        return {"error": str(e)}

@app.get("/api/v1/kalshi/markets")
async def kalshi_markets(market_type: str | None = None):
    """Get Kalshi markets"""
    try:
        venue = app.state.venue_registry.get_venue("kalshi")
        if not venue:
            return {"error": "Kalshi venue not found", "markets": []}
        
        # For now, return empty catalog
        catalog = []
        
        if market_type:
            catalog = [m for m in catalog if getattr(m, 'market_type', None) == market_type]
        
        return {
            "markets": catalog,
            "total_count": len(catalog),
        }
    except Exception as e:
        logger.error(f"Kalshi markets endpoint error: {e}")
        return {"error": str(e), "markets": []}

@app.post("/api/v1/kalshi/orders")
async def submit_kalshi_order(order: dict):
    """Submit Kalshi order"""
    try:
        venue = app.state.venue_registry.get_venue("kalshi")
        if not venue:
            return {"success": False, "error": "Kalshi venue not found"}
        
        # For now, just return the order as received
        return {"success": True, "order": order}
    except Exception as e:
        logger.error(f"Kalshi order submission error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/")
async def root():
    return {
        "service": "MERID (Minimal)",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "kalshi_status": "/api/v1/kalshi/status",
            "kalshi_markets": "/api/v1/kalshi/markets",
            "kalshi_orders": "/api/v1/kalshi/orders",
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
