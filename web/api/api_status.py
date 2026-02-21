"""API Status and Integration Dashboard."""

from __future__ import annotations

import os
from typing import Dict, List, Any
from fastapi import APIRouter
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["api-status"])


def check_api_status(key_name: str, required: bool = True) -> Dict[str, Any]:
    """Check if an API key is configured and return status."""
    key_value = os.getenv(key_name)
    is_configured = bool(key_value and key_value != "change_me" and key_value != "")
    
    return {
        "name": key_name,
        "configured": is_configured,
        "required": required,
        "status": "active" if is_configured else ("missing" if required else "optional"),
        "value_preview": key_value[:8] + "..." if key_value and len(key_value) > 8 else (key_value if key_value else None)
    }


@router.get("/api-status")
async def get_api_status() -> Dict[str, Any]:
    """Get comprehensive status of all API integrations."""
    
    # Market Data APIs
    market_data = [
        check_api_status("MESSARI_API_KEY"),
        check_api_status("ALPHA_VANTAGE_API_KEY"),
        check_api_status("POLYGON_API_KEY"),
        check_api_status("NEWS_API_KEY"),
        check_api_status("SERPER_API_KEY"),
        check_api_status("FRED_API_KEY"),
        check_api_status("FINNHUB_API_KEY"),
        check_api_status("THE_GRAPH_API_KEY"),
    ]
    
    # AI & ML APIs
    ai_apis = [
        check_api_status("HUGGINGFACE_API_KEY", required=False),
        check_api_status("CLAUDE_SONNET_4", required=False),
        check_api_status("DEEPSEEK_API_KEY", required=False),
        check_api_status("OLLAMA_API_KEY", required=False),
        check_api_status("OPENAI_API_KEY", required=False),
        check_api_status("OPEN_ROUTER_API_KEY", required=False),
    ]
    
    # Trading Exchanges
    trading_apis = [
        check_api_status("ALPACA_API_KEY"),
        check_api_status("ALPACA_API_SECRET"),
        check_api_status("BINANCE_API_KEY"),
        check_api_status("BINANCE_API_SECRET"),
        check_api_status("COINBASE_API_KEY"),
        check_api_status("COINBASE_API_SECRET"),
        check_api_status("KRAKEN_API_KEY"),
        check_api_status("KRAKE_PRIVATE_KEY"),
        check_api_status("OKX_API_KEY"),
        check_api_status("OKX_SECRET_KEY"),
        check_api_status("BYBIT_API_KEY", required=False),
        check_api_status("BYBIT_API_SECRET", required=False),
    ]
    
    # Prediction Markets
    prediction_markets = [
        check_api_status("KALSHI_API_KEY_ID"),
        check_api_status("POLYMARKET_API_KEY", required=False),
        check_api_status("POLYMARKET_API_SECRET", required=False),
    ]
    
    # Analytics & Intelligence
    analytics = [
        check_api_status("NANSEN_API_KEY", required=False),
        check_api_status("MERID_COINGLASS_API_KEY", required=False),
        check_api_status("MERID_ARKHAM_API_KEY", required=False),
        check_api_status("MERID_GLASSNODE_API_KEY", required=False),
        check_api_status("MERID_SANTIMENT_API_KEY", required=False),
    ]
    
    # Infrastructure
    infrastructure = [
        check_api_status("MONGODB_URI"),
        check_api_status("REDIS_URL"),
        check_api_status("RAILWAY_API_TOKEN", required=False),
        check_api_status("HELIUS_RPC_URL"),
    ]
    
    # Communications
    communications = [
        check_api_status("TELEGRAM_TOKEN"),
        check_api_status("TWILIO_SID", required=False),
        check_api_status("TWILIO_TOKEN", required=False),
        check_api_status("X_ACCESS_TOKEN", required=False),
        check_api_status("X_API_KEY", required=False),
    ]
    
    # IBKR
    ibkr = [
        check_api_status("IBKR_PAPER_TRADING_USERNAME"),
        check_api_status("IBKR_PAPER_TRADING_ACCOUNT_NUMBER"),
    ]
    
    # Calculate overall stats
    all_apis = market_data + ai_apis + trading_apis + prediction_markets + analytics + infrastructure + communications + ibkr
    total_apis = len(all_apis)
    configured_apis = len([api for api in all_apis if api["configured"]])
    required_apis = len([api for api in all_apis if api["required"]])
    required_configured = len([api for api in all_apis if api["required"] and api["configured"]])
    
    return {
        "summary": {
            "total_apis": total_apis,
            "configured_apis": configured_apis,
            "configuration_percentage": round((configured_apis / total_apis) * 100, 1) if total_apis > 0 else 0,
            "required_apis": required_apis,
            "required_configured": required_configured,
            "required_percentage": round((required_configured / required_apis) * 100, 1) if required_apis > 0 else 0,
            "overall_status": "healthy" if required_configured == required_apis else "incomplete"
        },
        "categories": {
            "market_data": {
                "name": "Market Data",
                "apis": market_data,
                "configured": len([api for api in market_data if api["configured"]]),
                "total": len(market_data)
            },
            "ai_ml": {
                "name": "AI & Machine Learning",
                "apis": ai_apis,
                "configured": len([api for api in ai_apis if api["configured"]]),
                "total": len(ai_apis)
            },
            "trading": {
                "name": "Trading Exchanges",
                "apis": trading_apis,
                "configured": len([api for api in trading_apis if api["configured"]]),
                "total": len(trading_apis)
            },
            "prediction_markets": {
                "name": "Prediction Markets",
                "apis": prediction_markets,
                "configured": len([api for api in prediction_markets if api["configured"]]),
                "total": len(prediction_markets)
            },
            "analytics": {
                "name": "Analytics & Intelligence",
                "apis": analytics,
                "configured": len([api for api in analytics if api["configured"]]),
                "total": len(analytics)
            },
            "infrastructure": {
                "name": "Infrastructure",
                "apis": infrastructure,
                "configured": len([api for api in infrastructure if api["configured"]]),
                "total": len(infrastructure)
            },
            "communications": {
                "name": "Communications",
                "apis": communications,
                "configured": len([api for api in communications if api["configured"]]),
                "total": len(communications)
            },
            "ibkr": {
                "name": "IBKR Paper Trading",
                "apis": ibkr,
                "configured": len([api for api in ibkr if api["configured"]]),
                "total": len(ibkr)
            }
        }
    }
