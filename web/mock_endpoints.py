from fastapi import APIRouter
from fastapi.responses import JSONResponse

# Create routers for mock endpoints
predictions_router = APIRouter()
intelligence_router = APIRouter()

@predictions_router.get("/markets")
async def predictions_markets(request, limit: int = 30):
    """
    Prediction markets endpoint - returns mock data for testing.
    This endpoint is called by the Predictions section loader.
    """
    import time
    start_time = time.time()
    
    # Log the request
    print(f"[API] predictions_markets called: limit={limit}")
    
    # Mock data for testing
    mock_data = {
        "markets": [
            {
                "question": "BTC will reach $100k by end of Q1 2024",
                "category": "crypto",
                "yes_price": 0.65,
                "no_price": 0.35,
                "volume_24h": 15000000,
                "liquidity": 5000000,
                "expires": "2024-03-31T23:59:59Z"
            },
            {
                "question": "ETH will outperform BTC in next 30 days",
                "category": "crypto", 
                "yes_price": 0.45,
                "no_price": 0.55,
                "volume_24h": 8000000,
                "liquidity": 3000000,
                "expires": "2024-02-23T23:59:59Z"
            },
            {
                "question": "Federal Reserve will cut rates in March 2024",
                "category": "macro",
                "yes_price": 0.72,
                "no_price": 0.28,
                "volume_24h": 25000000,
                "liquidity": 8000000,
                "expires": "2024-03-31T23:59:59Z"
            }
        ],
        "total_markets": 3,
        "updated_at": time.time()
    }
    
    processing_time = (time.time() - start_time) * 1000
    print(f"[API] predictions_markets completed: {processing_time:.2f}ms")
    
    return JSONResponse(
        content=mock_data,
        headers={"X-Processing-Time": f"{processing_time:.2f}ms"}
    )

@predictions_router.get("/drift")
async def predictions_drift(request):
    """
    Prediction drift endpoint - returns mock data for testing.
    This endpoint is called by the Predictions section loader.
    """
    import time
    start_time = time.time()
    
    print(f"[API] predictions_drift called")
    
    mock_data = {
        "signals": [
            {
                "question": "BTC price prediction drift analysis",
                "drift_pct": 2.5,
                "confidence": 0.78,
                "timestamp": time.time() - 3600
            },
            {
                "question": "ETH vs BTC performance drift",
                "drift_pct": -1.2,
                "confidence": 0.65,
                "timestamp": time.time() - 7200
            },
            {
                "question": "Fed rate cut probability drift",
                "drift_pct": 3.8,
                "confidence": 0.82,
                "timestamp": time.time() - 1800
            }
        ],
        "updated_at": time.time()
    }
    
    processing_time = (time.time() - start_time) * 1000
    print(f"[API] predictions_drift completed: {processing_time:.2f}ms")
    
    return JSONResponse(
        content=mock_data,
        headers={"X-Processing-Time": f"{processing_time:.2f}ms"}
    )

@predictions_router.get("/arbitrage")
async def predictions_arbitrage(request):
    """
    Prediction arbitrage endpoint - returns mock data for testing.
    This endpoint is called by the Predictions section loader.
    """
    import time
    start_time = time.time()
    
    print(f"[API] predictions_arbitrage called")
    
    mock_data = {
        "opportunities": [
            {
                "question": "BTC price prediction arbitrage opportunity",
                "platform_a": "Polymarket",
                "platform_b": "Augur",
                "spread_pct": 1.5,
                "potential_profit": 15000,
                "confidence": 0.71
            },
            {
                "question": "ETH market cross-platform arbitrage",
                "platform_a": "PredictIt",
                "platform_b": "Foretell",
                "spread_pct": 0.8,
                "potential_profit": 8000,
                "confidence": 0.64
            },
            {
                "question": "Rate prediction arbitrage opportunity",
                "platform_a": "Kalshi",
                "platform_b": "PredictIt",
                "spread_pct": 2.1,
                "potential_profit": 21000,
                "confidence": 0.76
            }
        ],
        "total_opportunities": 3,
        "updated_at": time.time()
    }
    
    processing_time = (time.time() - start_time) * 1000
    print(f"[API] predictions_arbitrage completed: {processing_time:.2f}ms")
    
    return JSONResponse(
        content=mock_data,
        headers={"X-Processing-Time": f"{processing_time:.2f}ms"}
    )

@intelligence_router.get("/news")
async def intelligence_news(request, limit: int = 15):
    """
    Intelligence news endpoint - returns mock data for testing.
    This endpoint is called by the Intelligence section loader.
    """
    import time
    start_time = time.time()
    
    print(f"[API] intelligence_news called: limit={limit}")
    
    mock_data = {
        "news": [
            {
                "source": "CoinTelegraph",
                "title": "Bitcoin Reaches New Heights as Institutional Adoption Accelerates",
                "description": "Major financial institutions continue to allocate significant portions of their portfolios to Bitcoin, driving prices to unprecedented levels. Market analysts predict continued growth through Q1 2024.",
                "url": "https://cointelegraph.com/news/bitcoin-institutional-adoption",
                "published_at": time.time() - 3600,
                "sentiment": {
                    "label": "positive",
                    "score": 0.8,
                    "confidence": 0.85
                },
                "topics": ["bitcoin", "institutional", "adoption"]
            },
            {
                "source": "Decrypt",
                "title": "Ethereum Network Upgrades Show Promise for Scalability Solutions",
                "description": "Recent network improvements demonstrate significant progress in addressing Ethereum's long-standing scalability challenges. Developers report increased throughput and reduced gas fees.",
                "url": "https://decrypt.co/ethereum-scalability-upgrades",
                "published_at": time.time() - 7200,
                "sentiment": {
                    "label": "positive", 
                    "score": 0.6,
                    "confidence": 0.78
                },
                "topics": ["ethereum", "scaling", "upgrades"]
            },
            {
                "source": "TheBlock",
                "title": "Regulatory Concerns Mount Over DeFi Protocol Vulnerabilities",
                "description": "Security researchers identify critical vulnerabilities in several major DeFi protocols, prompting increased regulatory scrutiny. Industry leaders call for enhanced security standards.",
                "url": "https://theblockcrypto.com/defi-vulnerabilities",
                "published_at": time.time() - 1800,
                "sentiment": {
                    "label": "negative",
                    "score": -0.7,
                    "confidence": 0.82
                },
                "topics": ["defi", "security", "regulation"]
            }
        ],
        "total_news": 3,
        "sources": ["CoinTelegraph", "Decrypt", "TheBlock"],
        "updated_at": time.time()
    }
    
    processing_time = (time.time() - start_time) * 1000
    print(f"[API] intelligence_news completed: {processing_time:.2f}ms")
    
    return JSONResponse(
        content=mock_data,
        headers={"X-Processing-Time": f"{processing_time:.2f}ms"}
    )
