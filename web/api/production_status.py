"""
Production Status API - Comprehensive system status for production dashboard.

Shows real-time status of all API integrations, services, and data feeds.
No mock data - only real API status and metrics.
"""

import os
import asyncio
from typing import Dict, List, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/production", tags=["production"])

class ServiceStatus(BaseModel):
    name: str
    status: str  # "online", "offline", "degraded"
    last_check: datetime
    response_time_ms: float
    error_message: str = ""
    metrics: Dict[str, Any] = {}

class CategoryStatus(BaseModel):
    category: str
    services: List[ServiceStatus]
    overall_status: str

class ProductionStatus(BaseModel):
    timestamp: datetime
    system_health: str
    categories: Dict[str, CategoryStatus]
    summary: Dict[str, Any]

@router.get("/status", response_model=ProductionStatus)
async def get_production_status():
    """Get comprehensive production status of all services."""
    
    categories = {}
    summary = {
        "total_services": 0,
        "online_services": 0,
        "offline_services": 0,
        "degraded_services": 0
    }
    
    # Check Market Data APIs
    market_data_status = await check_market_data_apis()
    categories["market_data"] = market_data_status
    update_summary(market_data_status.services, summary)
    
    # Check Prediction Markets
    prediction_status = await check_prediction_markets()
    categories["prediction_markets"] = prediction_status
    update_summary(prediction_status.services, summary)
    
    # Check Blockchain APIs
    blockchain_status = await check_blockchain_apis()
    categories["blockchain"] = blockchain_status
    update_summary(blockchain_status.services, summary)
    
    # Check AI/ML APIs
    ai_status = await check_ai_apis()
    categories["ai_ml"] = ai_status
    update_summary(ai_status.services, summary)
    
    # Check Database Connections
    database_status = await check_database_connections()
    categories["databases"] = database_status
    update_summary(database_status.services, summary)
    
    # Determine overall system health
    if summary["offline_services"] == 0:
        system_health = "healthy"
    elif summary["offline_services"] < summary["total_services"] * 0.3:
        system_health = "degraded"
    else:
        system_health = "unhealthy"
    
    return ProductionStatus(
        timestamp=datetime.now(),
        system_health=system_health,
        categories=categories,
        summary=summary
    )

async def check_market_data_apis() -> CategoryStatus:
    """Check status of all market data APIs."""
    services = []
    
    # Check Kraken
    kraken_status = await check_exchange_api("kraken", "Kraken", {
        "api_key": os.getenv("KRAKEN_API_KEY"),
        "private_key": os.getenv("KRAKE_PRIVATE_KEY")
    })
    services.append(kraken_status)
    
    # Check Coinbase
    coinbase_status = await check_exchange_api("coinbase", "Coinbase", {
        "api_key": os.getenv("COINBASE_API_KEY"),
        "secret": os.getenv("COINBASE_API_SECRET")
    })
    services.append(coinbase_status)
    
    # Check Gemini
    gemini_status = await check_exchange_api("gemini", "Gemini", {})
    services.append(gemini_status)
    
    # Check Binance
    binance_status = await check_exchange_api("binance", "Binance", {
        "api_key": os.getenv("BINANCE_API_KEY"),
        "secret": os.getenv("BINANCE_API_SECRET")
    })
    services.append(binance_status)
    
    # Check Polygon.io
    polygon_status = await check_polygon_api()
    services.append(polygon_status)
    
    # Check Alpha Vantage
    alpha_status = await check_alpha_vantage_api()
    services.append(alpha_status)
    
    return CategoryStatus(
        category="Market Data",
        services=services,
        overall_status=determine_category_status(services)
    )

async def check_prediction_markets() -> CategoryStatus:
    """Check status of prediction market APIs."""
    services = []
    
    # Check Kalshi
    kalshi_status = await check_kalshi_api()
    services.append(kalshi_status)
    
    return CategoryStatus(
        category="Prediction Markets",
        services=services,
        overall_status=determine_category_status(services)
    )

async def check_blockchain_apis() -> CategoryStatus:
    """Check status of blockchain APIs."""
    services = []
    
    # Check Helius (Solana)
    helius_status = await check_helius_api()
    services.append(helius_status)
    
    return CategoryStatus(
        category="Blockchain",
        services=services,
        overall_status=determine_category_status(services)
    )

async def check_ai_apis() -> CategoryStatus:
    """Check status of AI/ML APIs."""
    services = []
    
    # Check OpenAI
    openai_status = await check_openai_api()
    services.append(openai_status)
    
    # Check HuggingFace
    hf_status = await check_huggingface_api()
    services.append(hf_status)
    
    return CategoryStatus(
        category="AI/ML",
        services=services,
        overall_status=determine_category_status(services)
    )

async def check_database_connections() -> CategoryStatus:
    """Check status of database connections."""
    services = []
    
    # Check MongoDB
    mongodb_status = await check_mongodb_connection()
    services.append(mongodb_status)
    
    # Check Redis
    redis_status = await check_redis_connection()
    services.append(redis_status)
    
    # Check Neo4j
    neo4j_status = await check_neo4j_connection()
    services.append(neo4j_status)
    
    return CategoryStatus(
        category="Databases",
        services=services,
        overall_status=determine_category_status(services)
    )

async def check_exchange_api(exchange_name: str, display_name: str, config: Dict[str, str]) -> ServiceStatus:
    """Check status of a specific exchange API."""
    start_time = datetime.now()
    
    try:
        import ccxt
        
        # Filter out None values
        filtered_config = {k: v for k, v in config.items() if v is not None and v != 'change_me'}
        
        if filtered_config:
            # Test with API keys
            exchange = getattr(ccxt, exchange_name)(filtered_config)
            await asyncio.to_thread(exchange.fetch_ticker, 'BTC/USDT')
            status = "online"
            error_message = ""
        else:
            # Test public endpoint
            exchange = getattr(ccxt, exchange_name)()
            await asyncio.to_thread(exchange.fetch_ticker, 'BTC/USDT')
            status = "degraded"  # Public access only
            error_message = "Public access only - no API keys configured"
        
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return ServiceStatus(
            name=display_name,
            status=status,
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=error_message,
            metrics={
                "configured": bool(filtered_config),
                "public_access": True
            }
        )
        
    except Exception as e:
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        return ServiceStatus(
            name=display_name,
            status="offline",
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=str(e),
            metrics={
                "configured": bool(config.get('api_key')),
                "public_access": False
            }
        )

async def check_polygon_api() -> ServiceStatus:
    """Check Polygon.io API status."""
    start_time = datetime.now()
    
    try:
        import httpx
        
        api_key = os.getenv("POLYGON_API_KEY")
        if not api_key or api_key == 'change_me':
            raise ValueError("No API key configured")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2023-01-01/2023-01-02?apiKey={api_key}",
                timeout=10.0
            )
            
            if response.status_code == 200:
                status = "online"
                error_message = ""
            else:
                status = "offline"
                error_message = f"HTTP {response.status_code}"
        
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return ServiceStatus(
            name="Polygon.io",
            status=status,
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=error_message,
            metrics={
                "configured": True,
                "api_calls_today": "N/A"
            }
        )
        
    except Exception as e:
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        return ServiceStatus(
            name="Polygon.io",
            status="offline",
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=str(e),
            metrics={
                "configured": bool(os.getenv("POLYGON_API_KEY") and os.getenv("POLYGON_API_KEY") != 'change_me')
            }
        )

async def check_alpha_vantage_api() -> ServiceStatus:
    """Check Alpha Vantage API status."""
    start_time = datetime.now()
    
    try:
        import httpx
        
        api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        if not api_key or api_key == 'change_me':
            raise ValueError("No API key configured")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=IBM&apikey={api_key}",
                timeout=10.0
            )
            
            if response.status_code == 200:
                status = "online"
                error_message = ""
            else:
                status = "offline"
                error_message = f"HTTP {response.status_code}"
        
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return ServiceStatus(
            name="Alpha Vantage",
            status=status,
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=error_message,
            metrics={
                "configured": True
            }
        )
        
    except Exception as e:
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        return ServiceStatus(
            name="Alpha Vantage",
            status="offline",
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=str(e),
            metrics={
                "configured": bool(os.getenv("ALPHA_VANTAGE_API_KEY") and os.getenv("ALPHA_VANTAGE_API_KEY") != 'change_me')
            }
        )

async def check_kalshi_api() -> ServiceStatus:
    """Check Kalshi API status."""
    start_time = datetime.now()
    
    try:
        from trading.integrations.kalshi_client import get_kalshi_client
        
        client = get_kalshi_client()
        balance = await asyncio.to_thread(client.get_balance)
        
        status = "online"
        error_message = ""
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return ServiceStatus(
            name="Kalshi",
            status=status,
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=error_message,
            metrics={
                "configured": True,
                "account_balance": balance.get('total', 0) if balance else 0
            }
        )
        
    except Exception as e:
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        return ServiceStatus(
            name="Kalshi",
            status="offline",
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=str(e),
            metrics={
                "configured": bool(os.getenv("KALSHI_API_KEY_ID"))
            }
        )

async def check_helius_api() -> ServiceStatus:
    """Check Helius (Solana) API status."""
    start_time = datetime.now()
    
    try:
        import httpx
        
        rpc_url = os.getenv("HELIUS_RPC_URL")
        if not rpc_url:
            raise ValueError("No RPC URL configured")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSlot"
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                status = "online"
                error_message = ""
            else:
                status = "offline"
                error_message = f"HTTP {response.status_code}"
        
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return ServiceStatus(
            name="Helius (Solana)",
            status=status,
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=error_message,
            metrics={
                "configured": True
            }
        )
        
    except Exception as e:
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        return ServiceStatus(
            name="Helius (Solana)",
            status="offline",
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=str(e),
            metrics={
                "configured": bool(os.getenv("HELIUS_RPC_URL"))
            }
        )

async def check_openai_api() -> ServiceStatus:
    """Check OpenAI API status."""
    start_time = datetime.now()
    
    try:
        import httpx
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or api_key == 'change_me':
            raise ValueError("No API key configured")
        
        # Check if it's a project key (starts with sk-proj-) which doesn't work with chat completions
        if api_key.startswith('sk-proj-'):
            raise ValueError("Project key detected - need regular API key for chat completions")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 10
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                status = "online"
                error_message = ""
            else:
                status = "offline"
                error_message = f"HTTP {response.status_code}"
        
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return ServiceStatus(
            name="OpenAI",
            status=status,
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=error_message,
            metrics={
                "configured": True
            }
        )
        
    except Exception as e:
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        return ServiceStatus(
            name="OpenAI",
            status="offline",
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=str(e),
            metrics={
                "configured": bool(os.getenv("OPENAI_API_KEY"))
            }
        )

async def check_huggingface_api() -> ServiceStatus:
    """Check HuggingFace API status."""
    start_time = datetime.now()
    
    try:
        import httpx
        
        api_key = os.getenv("HUGGINGFACE_API_KEY")
        if not api_key or api_key == 'change_me':
            raise ValueError("No API key configured")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api-inference.huggingface.co/models/distilbert-base-uncased",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0
            )
            
            if response.status_code == 200:
                status = "online"
                error_message = ""
            else:
                status = "offline"
                error_message = f"HTTP {response.status_code}"
        
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return ServiceStatus(
            name="HuggingFace",
            status=status,
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=error_message,
            metrics={
                "configured": True
            }
        )
        
    except Exception as e:
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        return ServiceStatus(
            name="HuggingFace",
            status="offline",
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=str(e),
            metrics={
                "configured": bool(os.getenv("HUGGINGFACE_API_KEY") and os.getenv("HUGGINGFACE_API_KEY") != 'change_me')
            }
        )

async def check_mongodb_connection() -> ServiceStatus:
    """Check MongoDB connection status."""
    start_time = datetime.now()
    
    try:
        from pymongo import MongoClient
        
        uri = os.getenv("MONGODB_URI")
        if not uri:
            raise ValueError("No MongoDB URI configured")
        
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        await asyncio.to_thread(client.admin.command('ping'))
        
        status = "online"
        error_message = ""
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return ServiceStatus(
            name="MongoDB",
            status=status,
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=error_message,
            metrics={
                "configured": True
            }
        )
        
    except Exception as e:
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        return ServiceStatus(
            name="MongoDB",
            status="offline",
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=str(e),
            metrics={
                "configured": bool(os.getenv("MONGODB_URI"))
            }
        )

async def check_redis_connection() -> ServiceStatus:
    """Check Redis connection status."""
    start_time = datetime.now()
    
    try:
        import redis
        
        url = os.getenv("REDIS_URL")
        if not url:
            raise ValueError("No Redis URL configured")
        
        client = redis.from_url(url)
        await asyncio.to_thread(client.ping)
        
        status = "online"
        error_message = ""
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return ServiceStatus(
            name="Redis",
            status=status,
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=error_message,
            metrics={
                "configured": True
            }
        )
        
    except Exception as e:
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        return ServiceStatus(
            name="Redis",
            status="offline",
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=str(e),
            metrics={
                "configured": bool(os.getenv("REDIS_URL"))
            }
        )

async def check_neo4j_connection() -> ServiceStatus:
    """Check Neo4j connection status."""
    start_time = datetime.now()
    
    try:
        from neo4j import GraphDatabase
        
        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USER")
        password = os.getenv("NEO4J_PASSWORD")
        
        if not all([uri, user, password]):
            raise ValueError("Neo4j credentials not fully configured")
        
        driver = GraphDatabase.driver(uri, auth=(user, password))
        await asyncio.to_thread(driver.verify_connectivity)
        
        status = "online"
        error_message = ""
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return ServiceStatus(
            name="Neo4j",
            status=status,
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=error_message,
            metrics={
                "configured": True
            }
        )
        
    except Exception as e:
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        return ServiceStatus(
            name="Neo4j",
            status="offline",
            last_check=datetime.now(),
            response_time_ms=response_time,
            error_message=str(e),
            metrics={
                "configured": all([
                    os.getenv("NEO4J_URI"),
                    os.getenv("NEO4J_USER"),
                    os.getenv("NEO4J_PASSWORD")
                ])
            }
        )

def determine_category_status(services: List[ServiceStatus]) -> str:
    """Determine overall category status based on services."""
    if all(service.status == "online" for service in services):
        return "healthy"
    elif any(service.status == "online" for service in services):
        return "degraded"
    else:
        return "unhealthy"

def update_summary(services: List[ServiceStatus], summary: Dict[str, Any]):
    """Update summary statistics."""
    summary["total_services"] += len(services)
    summary["online_services"] += sum(1 for s in services if s.status == "online")
    summary["offline_services"] += sum(1 for s in services if s.status == "offline")
    summary["degraded_services"] += sum(1 for s in services if s.status == "degraded")
