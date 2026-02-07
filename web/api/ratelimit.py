"""
Rate Limiting API Endpoints.

Provides API access to rate limiting configuration and status.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ratelimit import (
    get_rate_limiter,
    get_token_bucket_manager,
    get_throttle_manager,
)
from ratelimit.rate_limiter import LimitType, RateLimitConfig
from ratelimit.throttle import ThrottleLevel
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/ratelimit", tags=["ratelimit"])
logger = get_logger("web.api.ratelimit")


# ============================================
# REQUEST MODELS
# ============================================

class RateLimitRuleRequest(BaseModel):
    rule_id: str
    limit_type: str
    requests_per_second: float = 1.0
    requests_per_minute: float = 60.0
    burst_size: float = 10.0
    endpoints: List[str] = []
    methods: List[str] = []
    block_duration_seconds: float = 60.0


class BlockRequest(BaseModel):
    identifier: str
    duration_seconds: float = 3600.0


class ThrottleLevelRequest(BaseModel):
    level: str


# ============================================
# RATE LIMITER ENDPOINTS
# ============================================

@router.get("/status")
async def get_ratelimit_status() -> Dict[str, Any]:
    """Get rate limiter status."""
    return {
        "limiter": get_rate_limiter().get_stats(),
        "buckets": get_token_bucket_manager().get_stats(),
        "throttle": get_throttle_manager().get_stats(),
    }


@router.get("/rules")
async def get_rules() -> Dict[str, Any]:
    """Get all rate limit rules."""
    return get_rate_limiter().get_rules()


@router.post("/rules")
async def add_rule(request: RateLimitRuleRequest) -> Dict[str, Any]:
    """Add a rate limit rule."""
    try:
        limit_type = LimitType(request.limit_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid limit type: {request.limit_type}")
    
    config = RateLimitConfig(
        rule_id=request.rule_id,
        limit_type=limit_type,
        requests_per_second=request.requests_per_second,
        requests_per_minute=request.requests_per_minute,
        burst_size=request.burst_size,
        endpoints=request.endpoints,
        methods=request.methods,
        block_duration_seconds=request.block_duration_seconds,
    )
    
    get_rate_limiter().add_rule(config)
    return {"status": "added", "rule_id": request.rule_id}


@router.delete("/rules/{rule_id}")
async def remove_rule(rule_id: str) -> Dict[str, Any]:
    """Remove a rate limit rule."""
    success = get_rate_limiter().remove_rule(rule_id)
    if success:
        return {"status": "removed"}
    raise HTTPException(status_code=404, detail="Rule not found")


# ============================================
# BLOCK LIST ENDPOINTS
# ============================================

@router.get("/blocked")
async def get_blocked() -> Dict[str, Any]:
    """Get blocked identifiers."""
    blocked = get_rate_limiter().get_blocked_list()
    return {"count": len(blocked), "blocked": blocked}


@router.post("/block")
async def block_identifier(request: BlockRequest) -> Dict[str, Any]:
    """Block an identifier."""
    get_rate_limiter().block(request.identifier, request.duration_seconds)
    return {"status": "blocked", "identifier": request.identifier}


@router.post("/unblock/{identifier}")
async def unblock_identifier(identifier: str) -> Dict[str, Any]:
    """Unblock an identifier."""
    success = get_rate_limiter().unblock(identifier)
    if success:
        return {"status": "unblocked"}
    raise HTTPException(status_code=404, detail="Identifier not blocked")


# ============================================
# WHITELIST ENDPOINTS
# ============================================

@router.get("/whitelist")
async def get_whitelist() -> Dict[str, Any]:
    """Get whitelist."""
    whitelist = get_rate_limiter().get_whitelist()
    return {"count": len(whitelist), "whitelist": whitelist}


@router.post("/whitelist/{identifier}")
async def add_to_whitelist(identifier: str) -> Dict[str, Any]:
    """Add to whitelist."""
    get_rate_limiter().whitelist_add(identifier)
    return {"status": "added", "identifier": identifier}


@router.delete("/whitelist/{identifier}")
async def remove_from_whitelist(identifier: str) -> Dict[str, Any]:
    """Remove from whitelist."""
    success = get_rate_limiter().whitelist_remove(identifier)
    if success:
        return {"status": "removed"}
    raise HTTPException(status_code=404, detail="Identifier not in whitelist")


# ============================================
# BUCKET ENDPOINTS
# ============================================

@router.get("/buckets")
async def get_buckets() -> Dict[str, Any]:
    """Get all token buckets."""
    return get_token_bucket_manager().get_all_buckets()


@router.get("/buckets/{identifier}")
async def get_bucket(identifier: str) -> Dict[str, Any]:
    """Get a specific bucket."""
    info = get_token_bucket_manager().get_bucket_info(identifier)
    if info:
        return info
    raise HTTPException(status_code=404, detail="Bucket not found")


@router.post("/buckets/{identifier}/reset")
async def reset_bucket(identifier: str) -> Dict[str, Any]:
    """Reset a bucket."""
    success = get_token_bucket_manager().reset_bucket(identifier)
    if success:
        return {"status": "reset"}
    raise HTTPException(status_code=404, detail="Bucket not found")


# ============================================
# THROTTLE ENDPOINTS
# ============================================

@router.get("/throttle")
async def get_throttle_status() -> Dict[str, Any]:
    """Get throttle status."""
    return get_throttle_manager().get_stats()


@router.get("/throttle/state")
async def get_throttle_state() -> Dict[str, Any]:
    """Get current throttle state."""
    return get_throttle_manager().get_state()


@router.post("/throttle/manual")
async def set_manual_throttle(request: ThrottleLevelRequest) -> Dict[str, Any]:
    """Set manual throttle level."""
    try:
        level = ThrottleLevel[request.level.upper()]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Invalid throttle level: {request.level}")
    
    get_throttle_manager().set_manual_throttle(level)
    return {"status": "set", "level": level.name}


@router.delete("/throttle/manual")
async def clear_manual_throttle() -> Dict[str, Any]:
    """Clear manual throttle."""
    get_throttle_manager().clear_manual_throttle()
    return {"status": "cleared"}


@router.post("/throttle/endpoint/{endpoint}")
async def set_endpoint_throttle(endpoint: str, request: ThrottleLevelRequest) -> Dict[str, Any]:
    """Set throttle for a specific endpoint."""
    try:
        level = ThrottleLevel[request.level.upper()]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Invalid throttle level: {request.level}")
    
    get_throttle_manager().set_endpoint_throttle(endpoint, level)
    return {"status": "set", "endpoint": endpoint, "level": level.name}


@router.delete("/throttle/endpoint/{endpoint}")
async def clear_endpoint_throttle(endpoint: str) -> Dict[str, Any]:
    """Clear endpoint throttle."""
    success = get_throttle_manager().clear_endpoint_throttle(endpoint)
    if success:
        return {"status": "cleared"}
    raise HTTPException(status_code=404, detail="Endpoint throttle not found")


@router.get("/throttle/levels")
async def get_throttle_levels() -> Dict[str, Any]:
    """Get available throttle levels."""
    return {"levels": [l.name for l in ThrottleLevel]}
