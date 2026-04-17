"""
Memecoin Sniping API Endpoints - Phase 20

Provides API access to memecoin detection and analysis.
ALERT-ONLY by default - execution requires consensus + manual approval.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from sniping import (
    get_memecoin_engine,
    TokenRisk,
)
from web.api.auth import get_current_session
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/sniping", tags=["sniping"], dependencies=[Depends(get_current_session)]  # ZT6-01
)
logger = get_logger("web.api.sniping")


class AnalyzeTokenRequest(BaseModel):
    token_address: str
    token_symbol: str
    chain: str
    liquidity_usd: float = 0.0
    buy_tax: float = 0.0
    sell_tax: float = 0.0
    deployer_address: Optional[str] = None
    holder_data: Optional[List[Dict[str, Any]]] = None
    lock_info: Optional[Dict[str, Any]] = None


class DetectLaunchRequest(BaseModel):
    token_address: str
    token_name: str
    token_symbol: str
    chain: str
    pair_address: Optional[str] = None
    initial_liquidity_usd: float = 0.0
    deployer_address: Optional[str] = None


class SetRuleRequest(BaseModel):
    rule_name: str
    value: Any
    enabled: bool = True


class EnableExecutionRequest(BaseModel):
    consensus_approval: str
    manual_approval: str


@router.get("/status")
async def get_status() -> Dict[str, Any]:
    """Get sniping engine status."""
    return get_memecoin_engine().get_status()


@router.get("/alerts")
async def get_alerts(
    risk_level: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Get snipe alerts."""
    engine = get_memecoin_engine()
    
    risk_filter = None
    if risk_level:
        try:
            risk_filter = TokenRisk(risk_level)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid risk level: {risk_level}")
    
    alerts = engine.get_alerts(risk_level=risk_filter, limit=limit)
    return {
        "count": len(alerts),
        "alerts": [a.to_dict() for a in alerts],
    }


@router.post("/analyze")
async def analyze_token(request: AnalyzeTokenRequest) -> Dict[str, Any]:
    """Analyze a token for sniping opportunity."""
    engine = get_memecoin_engine()
    
    risk_level, alert = engine.analyze_token(
        token_address=request.token_address,
        token_symbol=request.token_symbol,
        chain=request.chain,
        liquidity_usd=request.liquidity_usd,
        buy_tax=request.buy_tax,
        sell_tax=request.sell_tax,
        deployer_address=request.deployer_address,
        holder_data=request.holder_data,
        lock_info=request.lock_info,
    )
    
    return {
        "token_address": request.token_address,
        "risk_level": risk_level.value,
        "alert": alert.to_dict(),
    }


@router.post("/detect-launch")
async def detect_launch(request: DetectLaunchRequest) -> Dict[str, Any]:
    """Record a detected token launch."""
    engine = get_memecoin_engine()
    
    launch = engine.launch_detector.detect_launch(
        token_address=request.token_address,
        token_name=request.token_name,
        token_symbol=request.token_symbol,
        chain=request.chain,
        pair_address=request.pair_address,
        initial_liquidity_usd=request.initial_liquidity_usd,
        deployer_address=request.deployer_address,
    )
    
    return {"status": "detected", "launch": launch.to_dict()}


@router.get("/launches")
async def get_recent_launches(
    hours: float = 24.0,
    chain: Optional[str] = None,
) -> Dict[str, Any]:
    """Get recent token launches."""
    engine = get_memecoin_engine()
    launches = engine.launch_detector.get_recent_launches(hours=hours, chain=chain)
    return {
        "count": len(launches),
        "launches": [l.to_dict() for l in launches],
    }


@router.post("/honeypot/analyze")
async def analyze_honeypot(
    token_address: str,
    buy_tax_pct: float = 0.0,
    sell_tax_pct: float = 0.0,
    max_tx_pct: float = 100.0,
    max_wallet_pct: float = 100.0,
    has_blacklist: bool = False,
    has_proxy: bool = False,
    has_mint: bool = False,
    has_pause: bool = False,
    owner_can_change_tax: bool = False,
) -> Dict[str, Any]:
    """Analyze token for honeypot characteristics."""
    engine = get_memecoin_engine()
    
    analysis = engine.honeypot_detector.analyze(
        token_address=token_address,
        buy_tax_pct=buy_tax_pct,
        sell_tax_pct=sell_tax_pct,
        max_tx_pct=max_tx_pct,
        max_wallet_pct=max_wallet_pct,
        has_blacklist=has_blacklist,
        has_proxy=has_proxy,
        has_mint=has_mint,
        has_pause=has_pause,
        owner_can_change_tax=owner_can_change_tax,
    )
    
    return analysis.to_dict()


@router.get("/honeypot/{token_address}")
async def get_honeypot_analysis(token_address: str) -> Dict[str, Any]:
    """Get honeypot analysis for a token."""
    engine = get_memecoin_engine()
    analysis = engine.honeypot_detector.get_analysis(token_address)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis.to_dict()


@router.post("/mev-route")
async def get_mev_route(
    token_address: str,
    chain: str,
    size_usd: float,
    urgency: str = "normal",
) -> Dict[str, Any]:
    """Get MEV-aware routing recommendation."""
    engine = get_memecoin_engine()
    route = engine.mev_router.get_route(
        token_address=token_address,
        chain=chain,
        size_usd=size_usd,
        urgency=urgency,
    )
    return route.to_dict()


@router.get("/rules")
async def get_rejection_rules() -> Dict[str, Any]:
    """Get auto-rejection rules."""
    engine = get_memecoin_engine()
    return {"rules": engine.auto_reject.get_rules()}


@router.post("/rules")
async def set_rejection_rule(request: SetRuleRequest) -> Dict[str, Any]:
    """Set an auto-rejection rule."""
    engine = get_memecoin_engine()
    engine.auto_reject.set_rule(
        rule_name=request.rule_name,
        value=request.value,
        enabled=request.enabled,
    )
    return {"status": "updated", "rule": request.rule_name}


@router.post("/execution/enable")
async def enable_execution(request: EnableExecutionRequest) -> Dict[str, Any]:
    """
    Enable execution mode.
    
    REQUIRES BOTH CONSENSUS AND MANUAL APPROVAL.
    This is an extremely dangerous operation.
    """
    engine = get_memecoin_engine()
    success = engine.enable_execution(
        consensus_approval=request.consensus_approval,
        manual_approval=request.manual_approval,
    )
    if not success:
        raise HTTPException(status_code=403, detail="Both consensus and manual approval required")
    return {"status": "enabled", "warning": "EXECUTION MODE ACTIVE - HIGH RISK"}


@router.post("/execution/disable")
async def disable_execution() -> Dict[str, Any]:
    """Disable execution mode."""
    engine = get_memecoin_engine()
    engine.disable_execution()
    return {"status": "disabled", "mode": "ALERT_ONLY"}
