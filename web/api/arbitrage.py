"""
Arbitrage API Endpoints.

Provides API access to arbitrage scanners, opportunities, and controls.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from arbitrage import (
    get_cross_cex_scanner,
    get_dex_cex_scanner,
    get_perp_spot_scanner,
    get_funding_rate_scanner,
    get_cost_model_engine,
    get_execution_gate,
    ScannerState,
    EXECUTION_ENABLED,
)
from schemas.arbitrage import ArbitrageOpportunity
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/arbitrage", tags=["arbitrage"])
logger = get_logger("web.api.arbitrage")

# Store recent opportunities for API access
_recent_opportunities: List[Dict[str, Any]] = []
_latest_scan_snapshot: Dict[str, Any] = {}
_max_opportunities: int = 100


def _success(payload: Dict[str, Any], data_mode: str = "live") -> Dict[str, Any]:
    data = dict(payload)
    data.setdefault("status", "success")
    data["data_mode"] = data_mode
    data["timestamp"] = time.time()
    return data


def _offline(reason: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = dict(extra) if extra else {}
    payload["error"] = reason
    return _success(payload, data_mode="offline")


def _opportunity_callback(opp: ArbitrageOpportunity) -> None:
    """Callback to store opportunities."""
    global _recent_opportunities, _latest_scan_snapshot
    _recent_opportunities.append(opp.to_dict())
    if len(_recent_opportunities) > _max_opportunities:
        _recent_opportunities = _recent_opportunities[-_max_opportunities:]
    scanner_id = opp.source_scanner or opp.arb_type.value.lower()
    bucket = _latest_scan_snapshot.setdefault(scanner_id, [])
    bucket.insert(0, opp.to_dict())
    del bucket[_max_opportunities:]


# Register callbacks on scanner creation
def _setup_callbacks():
    """Setup opportunity callbacks for all scanners."""
    try:
        get_cross_cex_scanner().add_callback(_opportunity_callback)
        get_dex_cex_scanner().add_callback(_opportunity_callback)
        get_perp_spot_scanner().add_callback(_opportunity_callback)
        get_funding_rate_scanner().add_callback(_opportunity_callback)
    except Exception as e:
        logger.warning(f"Could not setup callbacks: {e}")


class ScannerControlRequest(BaseModel):
    """Request to control a scanner."""
    scanner_id: str


class VenueControlRequest(BaseModel):
    """Request to control a venue."""
    venue: str


class SymbolControlRequest(BaseModel):
    """Request to control a symbol."""
    symbol: str


class KillSwitchRequest(BaseModel):
    """Request to activate kill switch."""
    reason: str


@router.get("/status")
async def get_arbitrage_status() -> Dict[str, Any]:
    """Get overall arbitrage engine status."""
    cross_cex = get_cross_cex_scanner()
    dex_cex = get_dex_cex_scanner()
    perp_spot = get_perp_spot_scanner()
    funding_rate = get_funding_rate_scanner()
    gate = get_execution_gate()
    
    return {
        "execution_enabled_global": EXECUTION_ENABLED,
        "execution_gate": gate.get_status(),
        "scanners": {
            "cross_cex": cross_cex.get_status(),
            "dex_cex": dex_cex.get_status(),
            "perp_spot": perp_spot.get_status(),
            "funding_rate": funding_rate.get_status(),
        },
        "recent_opportunities_count": len(_recent_opportunities),
    }


@router.get("/scanners")
async def get_scanners() -> Dict[str, Any]:
    """Get all scanner statuses."""
    return {
        "scanners": [
            get_cross_cex_scanner().get_status(),
            get_dex_cex_scanner().get_status(),
            get_perp_spot_scanner().get_status(),
            get_funding_rate_scanner().get_status(),
        ]
    }


@router.get("/scanners/{scanner_id}")
async def get_scanner(scanner_id: str) -> Dict[str, Any]:
    """Get specific scanner status."""
    scanners = {
        "cross_cex_scanner": get_cross_cex_scanner,
        "dex_cex_scanner": get_dex_cex_scanner,
        "perp_spot_scanner": get_perp_spot_scanner,
        "funding_rate_scanner": get_funding_rate_scanner,
    }
    
    if scanner_id not in scanners:
        raise HTTPException(status_code=404, detail=f"Scanner not found: {scanner_id}")
    
    return scanners[scanner_id]().get_status()


@router.post("/scanners/{scanner_id}/start")
async def start_scanner(scanner_id: str, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Start a scanner."""
    scanners = {
        "cross_cex_scanner": get_cross_cex_scanner,
        "dex_cex_scanner": get_dex_cex_scanner,
        "perp_spot_scanner": get_perp_spot_scanner,
        "funding_rate_scanner": get_funding_rate_scanner,
    }
    
    if scanner_id not in scanners:
        raise HTTPException(status_code=404, detail=f"Scanner not found: {scanner_id}")
    
    scanner = scanners[scanner_id]()
    
    if scanner.state == ScannerState.RUNNING:
        return {"status": "already_running", "scanner": scanner.get_status()}
    
    # Start in background
    background_tasks.add_task(scanner.start)
    
    return {"status": "starting", "scanner_id": scanner_id}


@router.post("/scanners/{scanner_id}/stop")
async def stop_scanner(scanner_id: str) -> Dict[str, Any]:
    """Stop a scanner."""
    scanners = {
        "cross_cex_scanner": get_cross_cex_scanner,
        "dex_cex_scanner": get_dex_cex_scanner,
        "perp_spot_scanner": get_perp_spot_scanner,
        "funding_rate_scanner": get_funding_rate_scanner,
    }
    
    if scanner_id not in scanners:
        raise HTTPException(status_code=404, detail=f"Scanner not found: {scanner_id}")
    
    scanner = scanners[scanner_id]()
    await scanner.stop()
    
    return {"status": "stopped", "scanner": scanner.get_status()}


@router.post("/scanners/{scanner_id}/pause")
async def pause_scanner(scanner_id: str) -> Dict[str, Any]:
    """Pause a scanner."""
    scanners = {
        "cross_cex_scanner": get_cross_cex_scanner,
        "dex_cex_scanner": get_dex_cex_scanner,
        "perp_spot_scanner": get_perp_spot_scanner,
        "funding_rate_scanner": get_funding_rate_scanner,
    }
    
    if scanner_id not in scanners:
        raise HTTPException(status_code=404, detail=f"Scanner not found: {scanner_id}")
    
    scanner = scanners[scanner_id]()
    scanner.pause()
    
    return {"status": "paused", "scanner": scanner.get_status()}


@router.post("/scanners/{scanner_id}/resume")
async def resume_scanner(scanner_id: str) -> Dict[str, Any]:
    """Resume a paused scanner."""
    scanners = {
        "cross_cex_scanner": get_cross_cex_scanner,
        "dex_cex_scanner": get_dex_cex_scanner,
        "perp_spot_scanner": get_perp_spot_scanner,
        "funding_rate_scanner": get_funding_rate_scanner,
    }
    
    if scanner_id not in scanners:
        raise HTTPException(status_code=404, detail=f"Scanner not found: {scanner_id}")
    
    scanner = scanners[scanner_id]()
    scanner.resume()
    
    return {"status": "resumed", "scanner": scanner.get_status()}


@router.get("/opportunities")
async def get_opportunities(
    limit: int = 50,
    arb_type: Optional[str] = None,
    min_profit: Optional[float] = None,
) -> Dict[str, Any]:
    """Get recent arbitrage opportunities."""
    opportunities = _recent_opportunities.copy()
    
    # Filter by type
    if arb_type:
        opportunities = [o for o in opportunities if o.get("arb_type") == arb_type]
    
    # Filter by min profit
    if min_profit is not None:
        opportunities = [o for o in opportunities if o.get("net_profit_usd", 0) >= min_profit]
    
    # Sort by profit descending
    opportunities.sort(key=lambda x: x.get("net_profit_usd", 0), reverse=True)
    
    return {
        "count": len(opportunities[:limit]),
        "total": len(_recent_opportunities),
        "opportunities": opportunities[:limit],
    }


@router.get("/opportunities/{opportunity_id}")
async def get_opportunity(opportunity_id: str) -> Dict[str, Any]:
    """Get specific opportunity details."""
    for opp in _recent_opportunities:
        if opp.get("opportunity_id") == opportunity_id:
            return opp
    
    raise HTTPException(status_code=404, detail=f"Opportunity not found: {opportunity_id}")


@router.get("/gate")
async def get_execution_gate_status() -> Dict[str, Any]:
    """Get execution gate status."""
    return get_execution_gate().get_status()


@router.post("/gate/enable")
async def enable_execution() -> Dict[str, Any]:
    """
    Enable arbitrage execution.
    
    WARNING: This enables real trading. Use with extreme caution.
    """
    gate = get_execution_gate()
    gate.enable_execution()
    logger.warning("Arbitrage execution ENABLED via API")
    return {"status": "enabled", "gate": gate.get_status()}


@router.post("/gate/disable")
async def disable_execution() -> Dict[str, Any]:
    """Disable arbitrage execution."""
    gate = get_execution_gate()
    gate.disable_execution()
    logger.info("Arbitrage execution disabled via API")
    return {"status": "disabled", "gate": gate.get_status()}


@router.post("/gate/kill-switch/activate")
async def activate_kill_switch(request: KillSwitchRequest) -> Dict[str, Any]:
    """Activate the kill switch."""
    gate = get_execution_gate()
    gate.activate_kill_switch(request.reason)
    return {"status": "kill_switch_activated", "reason": request.reason}


@router.post("/gate/kill-switch/deactivate")
async def deactivate_kill_switch() -> Dict[str, Any]:
    """Deactivate the kill switch."""
    gate = get_execution_gate()
    gate.deactivate_kill_switch()
    return {"status": "kill_switch_deactivated"}


@router.post("/gate/venue/disable")
async def disable_venue(request: VenueControlRequest) -> Dict[str, Any]:
    """Disable a venue."""
    gate = get_execution_gate()
    gate.disable_venue(request.venue)
    return {"status": "venue_disabled", "venue": request.venue}


@router.post("/gate/venue/enable")
async def enable_venue(request: VenueControlRequest) -> Dict[str, Any]:
    """Enable a venue."""
    gate = get_execution_gate()
    gate.enable_venue(request.venue)
    return {"status": "venue_enabled", "venue": request.venue}


@router.post("/gate/symbol/disable")
async def disable_symbol(request: SymbolControlRequest) -> Dict[str, Any]:
    """Disable a symbol."""
    gate = get_execution_gate()
    gate.disable_symbol(request.symbol)
    return {"status": "symbol_disabled", "symbol": request.symbol}


@router.post("/gate/symbol/enable")
async def enable_symbol(request: SymbolControlRequest) -> Dict[str, Any]:
    """Enable a symbol."""
    gate = get_execution_gate()
    gate.enable_symbol(request.symbol)
    return {"status": "symbol_enabled", "symbol": request.symbol}


@router.get("/cost-model")
async def get_cost_model_status() -> Dict[str, Any]:
    """Get cost model status."""
    return get_cost_model_engine().get_status()


def _collect_scanner_data() -> List[Dict[str, Any]]:
    scanners = [
        get_cross_cex_scanner(),
        get_dex_cex_scanner(),
        get_perp_spot_scanner(),
        get_funding_rate_scanner(),
    ]
    payload: List[Dict[str, Any]] = []
    for scanner in scanners:
        try:
            status = scanner.get_status()
            metrics = status.get("metrics", {})
            last_scan_ts = metrics.get("last_scan_time")
            payload.append({
                "scanner_id": status.get("scanner_id"),
                "arb_type": status.get("scanner_type"),
                "enabled": status.get("state") in {ScannerState.RUNNING.value, ScannerState.PAUSED.value},
                "state": status.get("state"),
                "last_scan_ts": last_scan_ts,
                "opportunities_detected_24h": metrics.get("opportunities_found", 0),
                "opportunities_executed_24h": metrics.get("opportunities_executed", 0),
                "win_rate_24h": metrics.get("win_rate", 0.0),
                "gross_profit_usd_24h": metrics.get("total_potential_profit_usd", 0.0),
                "net_profit_usd_24h": metrics.get("total_realized_profit_usd", 0.0),
                "open_opportunities": len(_latest_scan_snapshot.get(status.get("scanner_id"), [])),
            })
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Scanner data collection failed: {exc}")
    return payload


@router.get("/stats")
async def get_arbitrage_stats() -> Dict[str, Any]:
    """Return aggregate stats for each arbitrage scanner."""
    try:
        scanners = _collect_scanner_data()
        totals = {
            "opportunities_detected_24h": sum(s["opportunities_detected_24h"] for s in scanners),
            "opportunities_executed_24h": sum(s["opportunities_executed_24h"] for s in scanners),
            "win_rate_24h": 0.0,
            "gross_profit_usd_24h": sum(s["gross_profit_usd_24h"] for s in scanners),
            "net_profit_usd_24h": sum(s["net_profit_usd_24h"] for s in scanners),
            "open_opportunities": sum(s["open_opportunities"] for s in scanners),
        }
        if totals["opportunities_detected_24h"]:
            totals["win_rate_24h"] = (
                totals["opportunities_executed_24h"] / totals["opportunities_detected_24h"]
            )

        return _success({
            "scanners": scanners,
            "totals": totals,
        }, data_mode="live" if scanners else "offline")
    except Exception as exc:
        logger.exception("Arbitrage stats failed: %s", exc)
        return _offline(f"arbitrage_stats_error: {exc}", {"scanners": [], "totals": {}})


@router.get("/scan")
async def get_latest_scan() -> Dict[str, Any]:
    """Return most recent opportunities grouped by scanner."""
    try:
        scanners_payload: List[Dict[str, Any]] = []
        for scanner in _collect_scanner_data():
            opportunities = _latest_scan_snapshot.get(scanner["scanner_id"], [])
            scanners_payload.append({
                "scanner_id": scanner["scanner_id"],
                "arb_type": scanner["arb_type"],
                "state": scanner["state"],
                "enabled": scanner["enabled"],
                "last_scan_ts": scanner["last_scan_ts"],
                "opportunities": opportunities,
            })

        return _success({
            "scanners": scanners_payload,
        }, data_mode="live" if scanners_payload else "offline")
    except Exception as exc:
        logger.exception("Arbitrage scan snapshot failed: %s", exc)
        return _offline(f"arbitrage_scan_error: {exc}", {"scanners": []})


@router.post("/start-all")
async def start_all_scanners(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Start all scanners."""
    _setup_callbacks()
    
    scanners = [
        get_cross_cex_scanner(),
        get_dex_cex_scanner(),
        get_perp_spot_scanner(),
        get_funding_rate_scanner(),
    ]
    
    for scanner in scanners:
        if scanner.state != ScannerState.RUNNING:
            background_tasks.add_task(scanner.start)
    
    return {
        "status": "starting_all",
        "scanners": [s.config.scanner_id for s in scanners],
    }


@router.post("/stop-all")
async def stop_all_scanners() -> Dict[str, Any]:
    """Stop all scanners."""
    scanners = [
        get_cross_cex_scanner(),
        get_dex_cex_scanner(),
        get_perp_spot_scanner(),
        get_funding_rate_scanner(),
    ]
    
    for scanner in scanners:
        await scanner.stop()
    
    return {
        "status": "stopped_all",
        "scanners": [s.config.scanner_id for s in scanners],
    }
