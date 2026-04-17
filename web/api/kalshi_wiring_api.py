"""
Kalshi Market Wiring API

REST API endpoints for market wiring management, monitoring, and control.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks

from merid.event_venues.kalshi.market_wiring.orchestrator import get_kalshi_wiring_orchestrator
from merid.event_venues.kalshi.market_wiring.models import RiskProfile
from merid.event_venues.kalshi.market_wiring.store import get_kalshi_market_store
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_wiring.api")

router = APIRouter(prefix="/api/v1/kalshi/wiring", tags=["kalshi_wiring"])


@router.get("/status")
async def get_wiring_status():
    """Get overall wiring system status"""
    try:
        orchestrator = await get_kalshi_wiring_orchestrator()
        status = orchestrator.get_wiring_status()
        return status
    except Exception as e:
        logger.error(f"Failed to get wiring status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def get_wiring_health():
    """Get health check of wiring components"""
    try:
        orchestrator = await get_kalshi_wiring_orchestrator()
        health = await orchestrator.health_check()
        return health
    except Exception as e:
        logger.error(f"Failed to get wiring health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/full")
async def trigger_full_sync(background_tasks: BackgroundTasks):
    """Trigger complete synchronization of universe and mappings"""
    try:
        orchestrator = await get_kalshi_wiring_orchestrator()
        
        # Run sync in background
        async def run_sync():
            result = await orchestrator.perform_full_sync()
            logger.info(f"Background sync completed: {result}")
        
        background_tasks.add_task(run_sync)
        
        return {"message": "Full sync triggered", "status": "running"}
    except Exception as e:
        logger.error(f"Failed to trigger full sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/markets")
async def get_markets(
    status: Optional[str] = Query(None, description="Filter by market status"),
    category: Optional[str] = Query(None, description="Filter by category"),
    risk_profile: Optional[str] = Query(None, description="Filter by risk profile"),
    enabled_only: bool = Query(False, description="Only return enabled markets"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of markets to return")
):
    """Get Kalshi markets with optional filtering"""
    try:
        store = get_kalshi_market_store()
        
        # Get markets based on filters
        if risk_profile:
            risk_enum = RiskProfile(risk_profile)
            markets = store.get_markets_by_risk_profile(risk_enum)
        elif category:
            markets = store.get_markets_by_category(category)
        elif status == "open":
            markets = store.get_open_markets()
        else:
            markets = store.get_open_markets()  # Default to open markets
        
        # Filter enabled if requested
        if enabled_only:
            enabled_mappings = store.get_enabled_mappings()
            enabled_tickers = {mapping.market_ticker for mapping in enabled_mappings}
            markets = [market for market in markets if market.market_ticker in enabled_tickers]
        
        # Apply limit
        markets = markets[:limit]
        
        return {
            "markets": [market.to_dict() for market in markets],
            "total_found": len(markets),
            "filters": {
                "status": status,
                "category": category,
                "risk_profile": risk_profile,
                "enabled_only": enabled_only,
                "limit": limit
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get markets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/markets/{market_ticker}")
async def get_market_detail(market_ticker: str):
    """Get detailed information for a specific market"""
    try:
        store = get_kalshi_market_store()
        
        # Get market and mapping
        market = store.get_market(market_ticker)
        mapping = store.get_mapping(market_ticker)
        
        if not market:
            raise HTTPException(status_code=404, detail=f"Market {market_ticker} not found")
        
        result = {
            "market": market.to_dict(),
            "mapping": mapping.to_dict() if mapping else None,
        }
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get market detail for {market_ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/markets/{market_ticker}/context")
async def get_market_context(market_ticker: str):
    """Get complete context configuration for a market"""
    try:
        orchestrator = await get_kalshi_wiring_orchestrator()
        context = orchestrator.get_market_context_config(market_ticker)
        
        if not context:
            raise HTTPException(status_code=404, detail=f"Context not available for {market_ticker}")
        
        return {
            "market_ticker": market_ticker,
            "market_mapping": context.market_mapping.to_dict(),
            "kalshi_market": context.kalshi_market.to_dict(),
            "context_availability": {
                "crypto_available": context.crypto_context_available,
                "sentiment_available": context.sentiment_context_available,
                "debate_available": context.debate_context_available,
                "crypto_fresh": context.crypto_fresh,
                "sentiment_fresh": context.sentiment_fresh,
                "debate_fresh": context.debate_fresh,
                "context_complete": context.context_complete,
                "safe_to_trade": context.safe_to_trade,
            },
            "effective_limits": {
                "max_notional_per_trade": context.effective_max_notional,
                "max_daily_notional": context.effective_daily_notional,
                "max_open_risk": context.effective_open_risk,
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get market context for {market_ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/markets/{market_ticker}/safety")
async def check_market_safety(
    market_ticker: str,
    proposed_notional: float = Query(0.0, description="Proposed notional for risk check")
):
    """Perform safety check for a market"""
    try:
        orchestrator = await get_kalshi_wiring_orchestrator()
        safety_result = orchestrator.check_market_safety(market_ticker, proposed_notional=proposed_notional)
        
        return {
            "market_ticker": market_ticker,
            "safe_to_trade": safety_result.safe_to_trade,
            "context_check": {
                "crypto_status": safety_result.context_check.crypto_status.value,
                "sentiment_status": safety_result.context_check.sentiment_status.value,
                "debate_status": safety_result.context_check.debate_status.value,
                "crypto_age_seconds": safety_result.context_check.crypto_age_seconds,
                "sentiment_age_seconds": safety_result.context_check.sentiment_age_seconds,
                "debate_age_seconds": safety_result.context_check.debate_age_seconds,
                "all_available": safety_result.context_check.all_available,
                "any_stale": safety_result.context_check.any_stale,
            },
            "risk_check": {
                "passes_risk_limits": safety_result.risk_check.passes_risk_limits,
                "current_exposure": safety_result.risk_check.current_exposure,
                "daily_pnl": safety_result.risk_check.daily_pnl,
                "max_notional_per_trade": safety_result.risk_check.max_notional_per_trade,
                "max_daily_notional": safety_result.risk_check.max_daily_notional,
                "max_open_risk": safety_result.risk_check.max_open_risk,
                "breaches": safety_result.risk_check.get_breach_reasons(),
            },
            "cqi_check": {
                "decision": safety_result.cqi_decision.value,
                "value": safety_result.cqi_value,
                "band": safety_result.cqi_band.value,
            },
            "block_reasons": safety_result.block_reasons,
            "effective_limits": {
                "max_notional": safety_result.effective_max_notional,
                "max_daily": safety_result.effective_daily_notional,
                "max_open_risk": safety_result.effective_open_risk,
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to check market safety for {market_ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mappings")
async def get_mappings(
    underlying_symbol: Optional[str] = Query(None, description="Filter by underlying symbol"),
    risk_profile: Optional[str] = Query(None, description="Filter by risk profile"),
    enabled_only: bool = Query(True, description="Only return enabled mappings"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of mappings to return")
):
    """Get market mappings with optional filtering"""
    try:
        store = get_kalshi_market_store()
        
        # Get mappings based on filters
        if underlying_symbol:
            mappings = store.get_mappings_by_underlying(underlying_symbol)
        elif risk_profile:
            risk_enum = RiskProfile(risk_profile)
            mappings = store.get_mappings_by_risk_profile(risk_enum)
        else:
            mappings = store.get_enabled_mappings() if enabled_only else []
        
        # Apply limit
        mappings = mappings[:limit]
        
        return {
            "mappings": [mapping.to_dict() for mapping in mappings],
            "total_found": len(mappings),
            "filters": {
                "underlying_symbol": underlying_symbol,
                "risk_profile": risk_profile,
                "enabled_only": enabled_only,
                "limit": limit
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get mappings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/coverage")
async def get_coverage_report():
    """Get latest coverage report"""
    try:
        orchestrator = await get_kalshi_wiring_orchestrator()
        coverage_checker = orchestrator.get_coverage_checker()
        
        if not coverage_checker:
            raise HTTPException(status_code=503, detail="Coverage checker not available")
        
        report = coverage_checker.get_latest_report()
        summary = coverage_checker.get_coverage_summary()
        
        if not report:
            return {
                "message": "No coverage report available",
                "summary": summary
            }
        
        return {
            "report": {
                "total_open_markets": report.total_open_markets,
                "mapped_markets": report.mapped_markets,
                "enabled_markets": report.enabled_markets,
                "unmapped_markets": report.unmapped_markets,
                "disabled_markets": report.disabled_markets,
                "coverage_percentage": report.coverage_percentage,
                "enablement_percentage": report.enablement_percentage,
                "unmapped_market_tickers": report.unmapped_market_tickers,
                "disabled_market_tickers": report.disabled_market_tickers,
                "coverage_by_risk_profile": report.coverage_by_risk_profile,
                "checked_at": report.checked_at,
            },
            "summary": summary
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get coverage report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/coverage/check")
async def trigger_coverage_check(background_tasks: BackgroundTasks):
    """Trigger coverage check"""
    try:
        orchestrator = await get_kalshi_wiring_orchestrator()
        coverage_checker = orchestrator.get_coverage_checker()
        
        if not coverage_checker:
            raise HTTPException(status_code=503, detail="Coverage checker not available")
        
        # Run coverage check in background
        async def run_coverage_check():
            result = await coverage_checker.check_coverage()
            logger.info(f"Background coverage check completed: {result}")
        
        background_tasks.add_task(run_coverage_check)
        
        return {"message": "Coverage check triggered", "status": "running"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger coverage check: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/symbols/{underlying_symbol}/markets")
async def get_markets_for_symbol(underlying_symbol: str):
    """Get all enabled markets for a given underlying symbol"""
    try:
        orchestrator = await get_kalshi_wiring_orchestrator()
        markets = orchestrator.get_enabled_markets_for_symbol(underlying_symbol)
        
        return {
            "underlying_symbol": underlying_symbol,
            "markets": [
                {
                    "market_ticker": config.market_mapping.market_ticker,
                    "merid_symbol": config.market_mapping.merid_symbol,
                    "risk_profile": config.market_mapping.risk_profile.value,
                    "safe_to_trade": config.safe_to_trade,
                    "effective_limits": {
                        "max_notional": config.effective_max_notional,
                        "max_daily": config.effective_daily_notional,
                        "max_open_risk": config.effective_open_risk,
                    }
                }
                for config in markets
            ],
            "total_found": len(markets)
        }
        
    except Exception as e:
        logger.error(f"Failed to get markets for {underlying_symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_wiring_statistics():
    """Get comprehensive wiring statistics"""
    try:
        orchestrator = await get_kalshi_wiring_orchestrator()
        store = get_kalshi_market_store()
        
        # Get basic counts
        total_markets = len(store.get_open_markets())
        enabled_mappings_list = store.get_enabled_mappings()
        enabled_mappings_count = len(enabled_mappings_list)
        
        # Get coverage report
        coverage_report = orchestrator.get_latest_coverage_report()
        
        # Symbol distribution
        symbol_counts = {}
        for mapping in enabled_mappings_list:
            symbol = mapping.underlying_symbol
            symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
        
        # Risk profile distribution
        risk_profile_counts = {}
        for risk_profile in ["crypto_linked", "macro_election", "equity_linked", "idiosyncratic"]:
            markets = store.get_markets_by_risk_profile(RiskProfile(risk_profile))
            risk_profile_counts[risk_profile] = len(markets)
        # Get sync timestamps
        sync_timestamps = store.get_sync_timestamps()
        
        return {
            "success": True,
            "data": {
                "overview": {
                    "total_open_markets": total_markets,
                    "enabled_mappings": enabled_mappings_count,
                    "coverage_percentage": (enabled_mappings_count / total_markets * 100) if total_markets > 0 else 0.0,
                    "enablement_percentage": (enabled_mappings_count / total_markets * 100) if total_markets > 0 else 0.0,
                },
                "risk_profile_distribution": risk_profile_counts,
                "underlying_symbol_distribution": symbol_counts,
                "sync_timestamps": sync_timestamps,
                "wiring_status": orchestrator.get_wiring_status(),
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get wiring statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
