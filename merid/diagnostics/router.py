"""
Server-integrated singleton access harness.

This FastAPI router provides HTTP endpoints for running diagnostic functions
against the live server's singletons, ensuring we always introspect the
actual running instance rather than creating new ones.
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
from typing import Dict, Any
import json

# Import diagnostic functions
from merid.diagnostics.time_alignment import check_time_alignment_and_active_window
from merid.diagnostics.catalog_ws_md_consistency import check_catalog_ws_md_consistency
from merid.diagnostics.ws_raw_vs_parsed import check_ws_raw_vs_parsed
from merid.diagnostics.market_state_health_distribution import check_market_state_health_distribution
from merid.diagnostics.ticker_inference_vs_close_ts import check_ticker_inference_vs_close_ts
from merid.diagnostics.active_vs_truly_live import check_active_vs_truly_live
from merid.diagnostics.agent_grid_and_signals import check_agent_grid_and_signals
from merid.diagnostics.end_to_end_signal_path import check_end_to_end_signal_path

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("/")
async def list_diagnostics() -> Dict[str, Any]:
    """List all available diagnostic endpoints."""
    return {
        "available_diagnostics": [
            {
                "name": "time_alignment",
                "endpoint": "/diagnostics/time_alignment",
                "description": "Check time alignment and active window selection"
            },
            {
                "name": "catalog_ws_md_consistency",
                "endpoint": "/diagnostics/catalog_ws_md_consistency",
                "description": "Check catalog vs WS vs MD consistency"
            },
            {
                "name": "ws_raw_vs_parsed",
                "endpoint": "/diagnostics/ws_raw_vs_parsed",
                "description": "Check WebSocket raw traffic vs parsed MD"
            },
            {
                "name": "market_state_health",
                "endpoint": "/diagnostics/market_state_health",
                "description": "Check market state age distribution"
            },
            {
                "name": "ticker_inference",
                "endpoint": "/diagnostics/ticker_inference",
                "description": "Check ticker inference vs close_ts authority"
            },
            {
                "name": "active_vs_live",
                "endpoint": "/diagnostics/active_vs_live",
                "description": "Check active vs truly live markets"
            },
            {
                "name": "agent_grid",
                "endpoint": "/diagnostics/agent_grid",
                "description": "Check agent grid and signal path"
            },
            {
                "name": "end_to_end_signal_path",
                "endpoint": "/diagnostics/end_to_end_signal_path",
                "description": "Check end-to-end signal generation path"
            },
            {
                "name": "all",
                "endpoint": "/diagnostics/all",
                "description": "Run all diagnostics and return combined results"
            }
        ]
    }


@router.get("/time_alignment")
async def run_time_alignment() -> Dict[str, Any]:
    """Run time alignment and active window diagnostic."""
    try:
        result = await check_time_alignment_and_active_window()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog_ws_md_consistency")
async def run_catalog_ws_md_consistency() -> Dict[str, Any]:
    """Run catalog vs WS vs MD consistency diagnostic."""
    try:
        result = await check_catalog_ws_md_consistency()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ws_raw_vs_parsed")
async def run_ws_raw_vs_parsed() -> Dict[str, Any]:
    """Run WebSocket raw traffic vs parsed MD diagnostic."""
    try:
        result = await check_ws_raw_vs_parsed()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market_state_health")
async def run_market_state_health() -> Dict[str, Any]:
    """Run market state age distribution diagnostic."""
    try:
        result = await check_market_state_health_distribution()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ticker_inference")
async def run_ticker_inference() -> Dict[str, Any]:
    """Run ticker inference vs close_ts authority diagnostic."""
    try:
        result = await check_ticker_inference_vs_close_ts()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active_vs_live")
async def run_active_vs_live() -> Dict[str, Any]:
    """Run active vs truly live diagnostic."""
    try:
        result = await check_active_vs_truly_live()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agent_grid")
async def run_agent_grid() -> Dict[str, Any]:
    """Run agent grid and signal path diagnostic."""
    try:
        result = await check_agent_grid_and_signals()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/end_to_end_signal_path")
async def run_end_to_end_signal_path() -> Dict[str, Any]:
    """Run end-to-end signal path diagnostic."""
    try:
        result = await check_end_to_end_signal_path()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/all")
async def run_all_diagnostics() -> Dict[str, Any]:
    """
    Run all diagnostics and return combined results.
    
    This provides a comprehensive view of system health in a single call.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    results = {
        "timestamp": timestamp,
        "diagnostics": {},
        "summary": {
            "total_diagnostics": 8,
            "successful": 0,
            "failed": 0,
            "errors": []
        }
    }
    
    # Run each diagnostic
    diagnostics = [
        ("time_alignment", run_time_alignment),
        ("catalog_ws_md_consistency", run_catalog_ws_md_consistency),
        ("ws_raw_vs_parsed", run_ws_raw_vs_parsed),
        ("market_state_health", run_market_state_health),
        ("ticker_inference", run_ticker_inference),
        ("active_vs_live", run_active_vs_live),
        ("agent_grid", run_agent_grid),
        ("end_to_end_signal_path", run_end_to_end_signal_path)
    ]
    
    for name, diagnostic_func in diagnostics:
        try:
            result = await diagnostic_func()
            results["diagnostics"][name] = result
            results["summary"]["successful"] += 1
        except Exception as e:
            results["diagnostics"][name] = {"error": str(e)}
            results["summary"]["failed"] += 1
            results["summary"]["errors"].append(f"{name}: {str(e)}")
    
    return results
