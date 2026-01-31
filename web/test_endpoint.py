@router_v1.get("/test/simple")
async def test_simple():
    """Simple test endpoint that returns static data."""
    return {
        "status": "working",
        "message": "Simple test endpoint is working",
        "data": {
            "prices": {"BTC/USDT": {"price": 95000, "change_24h": 2.5}},
            "news": [{"title": "Test news", "source": "Test"}],
            "reality": {"mode": "operational", "valid_assertions_pct": 1.0}
        }
    }
