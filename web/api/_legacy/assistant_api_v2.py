"""Operator Assistant API V2 — Hardened with Rate Limiting and Structured Errors

Major improvements over V1:
1. Strict read-only enforcement (no state mutations)
2. Rate limiting with sliding window per client
3. Request timeouts (prevents hanging queries)
4. Structured error responses (no swallowed exceptions)
5. Per-asset/timeframe health aggregation

Usage:
    POST /api/v1/assistant/query
    {
        "query": "What is BTC 15m health?",
        "context": "operator",
        "include_system_snapshot": true
    }

Response:
    {
        "trace_id": "ast-abc123",
        "answer": "BTC 15m: 3 agents healthy, 1 paused...",
        "context_domain": "operator",
        "sources": ["portfolio", "risk"],
        "system_snapshot": {...},
        "latency_ms": 45.2,
        "rate_limit": {"remaining": 29, "reset_at": 1234567890}
    }
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, validator

from merid.llm.governance import LLMRole, LLMTrace, get_llm_governance_store
from utils.logger import get_logger

logger = get_logger("web.api.assistant_v2")

# Security: HTTP Bearer token for API auth (placeholder for ZT6-01)
security = HTTPBearer(auto_error=False)

# ── Rate Limiting Configuration ─────────────────────────────────────────

RATE_LIMIT_REQUESTS = 30  # requests per window
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_TIMEOUT_SECONDS = 10  # max query processing time


@dataclass
class RateLimitState:
    """Rate limit state for a client."""
    requests: List[float]  # timestamps of requests
    
    def is_allowed(self, now: float) -> tuple[bool, int, float]:
        """
        Check if request is allowed.
        
        Returns:
            (allowed, remaining_requests, reset_timestamp)
        """
        # Remove old requests outside window
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        self.requests = [t for t in self.requests if t > cutoff]
        
        if len(self.requests) >= RATE_LIMIT_REQUESTS:
            reset_at = self.requests[0] + RATE_LIMIT_WINDOW_SECONDS
            return False, 0, reset_at
        
        self.requests.append(now)
        remaining = RATE_LIMIT_REQUESTS - len(self.requests)
        reset_at = now + RATE_LIMIT_WINDOW_SECONDS
        return True, remaining, reset_at


# In-memory rate limit store (replace with Redis in production)
_rate_limit_store: Dict[str, RateLimitState] = defaultdict(lambda: RateLimitState([]))


def get_client_id(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = None
) -> str:
    """Extract client identifier for rate limiting."""
    # Prefer authenticated user ID
    if credentials and credentials.credentials:
        return f"user:{credentials.credentials[:16]}"
    
    # Fall back to IP + User-Agent hash
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    return f"ip:{client_ip}:{hash(user_agent) % 10000}"


def check_rate_limit(client_id: str) -> tuple[bool, int, float]:
    """Check rate limit for client."""
    state = _rate_limit_store[client_id]
    return state.is_allowed(time.time())


# ── Request / Response Models ───────────────────────────────────────────

class AssistantQueryV2(BaseModel):
    """Query request with validation."""
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language question"
    )
    context: str = Field(
        "operator",
        description="Context domain: operator | dev | cognitive | sports"
    )
    include_system_snapshot: bool = Field(
        True,
        description="Attach live system snapshot"
    )
    asset_filter: Optional[List[str]] = Field(
        None,
        description="Filter to specific assets (BTC, ETH, SOL, XRP, DOGE)"
    )
    timeframe_filter: Optional[List[str]] = Field(
        None,
        description="Filter to specific timeframes (15m, 1h, daily, weekly)"
    )
    
    @validator('context')
    def validate_context(cls, v):
        allowed = {'operator', 'dev', 'cognitive', 'sports', 'risk'}
        if v not in allowed:
            raise ValueError(f"context must be one of {allowed}")
        return v
    
    @validator('asset_filter')
    def validate_assets(cls, v):
        if v is None:
            return v
        allowed = {'BTC', 'ETH', 'SOL', 'XRP', 'DOGE'}
        invalid = set(v) - allowed
        if invalid:
            raise ValueError(f"Invalid assets: {invalid}. Allowed: {allowed}")
        return v
    
    @validator('timeframe_filter')
    def validate_timeframes(cls, v):
        if v is None:
            return v
        allowed = {'15m', '1h', 'hourly', 'daily', 'weekly', 'monthly'}
        invalid = set(v) - allowed
        if invalid:
            raise ValueError(f"Invalid timeframes: {invalid}. Allowed: {allowed}")
        return v


class StructuredError(BaseModel):
    """Structured error response (no swallowed exceptions)."""
    error_type: str
    message: str
    details: Optional[Dict[str, Any]] = None
    recovery_hint: Optional[str] = None
    trace_id: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)


class AssistantMessageV2(BaseModel):
    """Message in conversation."""
    role: str
    content: str
    timestamp: float = 0.0
    metadata: Dict[str, Any] = {}


class RateLimitInfo(BaseModel):
    """Rate limit status in response."""
    remaining: int
    reset_at: float
    limit: int = RATE_LIMIT_REQUESTS


class AssistantResponseV2(BaseModel):
    """Response with rate limiting info."""
    trace_id: str
    answer: str
    context_domain: str
    sources: List[str] = []
    system_snapshot: Optional[Dict[str, Any]] = None
    messages: List[AssistantMessageV2] = []
    latency_ms: float = 0.0
    rate_limit: Optional[RateLimitInfo] = None
    # Asset/timeframe specific breakdown
    asset_health: Optional[Dict[str, Any]] = None
    timeframe_health: Optional[Dict[str, Any]] = None


# ── Router ────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


# ── Context Gatherers with Structured Error Handling ───────────────────

class GathererError(Exception):
    """Error from context gatherer with structured info."""
    def __init__(self, source: str, error: str, recovery_hint: str):
        self.source = source
        self.error = error
        self.recovery_hint = recovery_hint
        super().__init__(f"{source}: {error}")


def _gather_portfolio() -> Dict[str, Any]:
    """Gather portfolio with structured error."""
    try:
        from trading.paper_portfolio import get_paper_portfolio
        pf = get_paper_portfolio()
        return {
            "total_equity": pf.total_equity,
            "cash": pf.cash,
            "positions_count": len(pf.positions),
            "domains": list({p.domain for p in pf.positions.values()} if hasattr(pf, "positions") else []),
            "status": "available"
        }
    except ImportError as exc:
        raise GathererError("portfolio", f"Module not found: {exc}", "Check trading module installation")
    except Exception as exc:
        raise GathererError("portfolio", str(exc), "Check portfolio service health")


def _gather_risk() -> Dict[str, Any]:
    """Gather risk metrics with structured error."""
    try:
        from merid.pipeline.risk_manager import get_global_risk_manager
        rm = get_global_risk_manager()
        return {**rm.summary(), "status": "available"}
    except ImportError as exc:
        raise GathererError("risk", f"Module not found: {exc}", "Check risk module installation")
    except Exception as exc:
        raise GathererError("risk", str(exc), "Check risk manager initialization")


def _gather_pipeline_modes() -> Dict[str, Any]:
    """Gather pipeline modes with structured error."""
    try:
        from merid.pipeline.mode_manager import get_mode_manager
        mm = get_mode_manager()
        return {
            "venues": {v: cfg.mode.value for v, cfg in mm._venues.items()},
            "status": "available"
        }
    except ImportError as exc:
        raise GathererError("pipeline", f"Module not found: {exc}", "Check pipeline module installation")
    except Exception as exc:
        raise GathererError("pipeline", str(exc), "Check mode manager initialization")


def _gather_llm_governance() -> Dict[str, Any]:
    """Gather LLM governance with structured error."""
    try:
        store = get_llm_governance_store()
        return {
            **store.get_traces_summary(window_s=3600),
            "status": "available"
        }
    except ImportError as exc:
        raise GathererError("llm_governance", f"Module not found: {exc}", "Check governance module installation")
    except Exception as exc:
        raise GathererError("llm_governance", str(exc), "Check governance store initialization")


def _gather_agent_health(
    asset_filter: Optional[List[str]] = None,
    timeframe_filter: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Gather agent health with asset/timeframe filtering."""
    try:
        from agents.agent_framework import get_agent_registry
        from agents.governor_agent_v2 import get_hardened_governor_agent
        
        registry = get_agent_registry()
        governor = get_hardened_governor_agent()
        
        # Get all agents
        all_agents = registry.get_all_agents()
        
        # Build per-asset/timeframe health
        asset_health = {asset: {"total": 0, "healthy": 0, "paused": 0} for asset in (asset_filter or ["BTC", "ETH", "SOL", "XRP", "DOGE"])}
        timeframe_health = {tf: {"total": 0, "healthy": 0} for tf in (timeframe_filter or ["15m", "1h", "daily", "weekly", "monthly"])}
        
        for agent in all_agents:
            # Parse agent coverage
            agent_id_upper = agent.agent_id.upper()
            
            for asset in asset_health:
                if asset in agent_id_upper:
                    asset_health[asset]["total"] += 1
                    # Check if agent is healthy (running and not paused)
                    is_healthy = hasattr(agent, '_running') and getattr(agent, '_running', False)
                    if is_healthy:
                        asset_health[asset]["healthy"] += 1
                    else:
                        asset_health[asset]["paused"] += 1
            
            for tf in timeframe_health:
                tf_pattern = tf.upper().replace("H", "H")
                if tf_pattern in agent_id_upper or (tf == "1h" and "HOURLY" in agent_id_upper):
                    timeframe_health[tf]["total"] += 1
                    is_healthy = hasattr(agent, '_running') and getattr(agent, '_running', False)
                    if is_healthy:
                        timeframe_health[tf]["healthy"] += 1
        
        return {
            "agent_count": len(all_agents),
            "asset_health": asset_health,
            "timeframe_health": timeframe_health,
            "pending_governance_actions": len(governor._governance_engine.get_pending_actions()),
            "status": "available"
        }
    except ImportError as exc:
        raise GathererError("agent_health", f"Module not found: {exc}", "Check agent module installation")
    except Exception as exc:
        raise GathererError("agent_health", str(exc), "Check agent registry initialization")


def _gather_system_snapshot(
    asset_filter: Optional[List[str]] = None,
    timeframe_filter: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Collect live system metrics with structured error handling."""
    snapshot: Dict[str, Any] = {
        "gathered_at": time.time(),
        "errors": []
    }
    
    gatherers = [
        ("portfolio", _gather_portfolio),
        ("risk", _gather_risk),
        ("pipeline_modes", _gather_pipeline_modes),
        ("llm_governance", _gather_llm_governance),
    ]
    
    for name, gatherer in gatherers:
        try:
            snapshot[name] = gatherer()
        except GathererError as exc:
            snapshot[name] = {
                "status": "error",
                "error_type": "GathererError",
                "error_message": exc.error,
                "recovery_hint": exc.recovery_hint
            }
            snapshot["errors"].append({
                "source": name,
                "error": exc.error,
                "hint": exc.recovery_hint
            })
    
    # Agent health with filtering
    try:
        snapshot["agent_health"] = _gather_agent_health(asset_filter, timeframe_filter)
    except GathererError as exc:
        snapshot["agent_health"] = {
            "status": "error",
            "error_type": "GathererError",
            "error_message": exc.error,
            "recovery_hint": exc.recovery_hint
        }
        snapshot["errors"].append({
            "source": "agent_health",
            "error": exc.error,
            "hint": exc.recovery_hint
        })
    
    return snapshot


# ── Answer Builder ─────────────────────────────────────────────────────

def _build_answer(
    query: str,
    context: str,
    snapshot: Dict[str, Any]
) -> tuple[str, List[str]]:
    """Build answer from query and snapshot."""
    q_lower = query.lower()
    parts: List[str] = []
    sources: List[str] = []
    
    # Portfolio questions
    if any(kw in q_lower for kw in ("portfolio", "equity", "balance", "cash", "position")):
        pf = snapshot.get("portfolio", {})
        if pf.get("status") == "available":
            parts.append(
                f"Portfolio: ${pf.get('total_equity', 0):,.0f} total equity, "
                f"${pf.get('cash', 0):,.0f} cash, "
                f"{pf.get('positions_count', 0)} positions across "
                f"{', '.join(pf.get('domains', [])) or 'no'} domains."
            )
            sources.append("portfolio")
        elif pf.get("status") == "error":
            parts.append(f"Portfolio data unavailable: {pf.get('recovery_hint', 'unknown error')}")
    
    # Risk questions
    if any(kw in q_lower for kw in ("risk", "halt", "circuit", "kill", "drawdown", "loss")):
        risk = snapshot.get("risk", {})
        if risk.get("status") == "available":
            parts.append(f"Risk: {_summarize_dict(risk, exclude_keys=['status'])}")
            sources.append("risk")
        elif risk.get("status") == "error":
            parts.append(f"Risk data unavailable: {risk.get('recovery_hint', 'unknown error')}")
    
    # Pipeline / mode questions
    if any(kw in q_lower for kw in ("pipeline", "mode", "venue", "sim", "paper", "live")):
        modes = snapshot.get("pipeline_modes", {})
        if modes.get("status") == "available":
            venue_modes = modes.get("venues", {})
            mode_str = ", ".join(f"{v}: {m}" for v, m in venue_modes.items())
            parts.append(f"Pipeline modes: {mode_str}")
            sources.append("pipeline_modes")
        elif modes.get("status") == "error":
            parts.append(f"Pipeline data unavailable: {modes.get('recovery_hint', 'unknown error')}")
    
    # Agent health questions
    if any(kw in q_lower for kw in ("agent", "health", "running", "paused", "governor")):
        health = snapshot.get("agent_health", {})
        if health.get("status") == "available":
            parts.append(f"Agents: {health.get('agent_count', 0)} total, {health.get('pending_governance_actions', 0)} pending governance actions")
            
            # Per-asset breakdown if queried
            asset_health = health.get("asset_health", {})
            if asset_health and any(asset.lower() in q_lower for asset in asset_health.keys()):
                for asset, data in asset_health.items():
                    if asset.lower() in q_lower:
                        parts.append(f"{asset}: {data['healthy']}/{data['total']} healthy, {data.get('paused', 0)} paused")
            
            sources.append("agent_health")
    
    # LLM / governance questions
    if any(kw in q_lower for kw in ("llm", "trace", "governance", "guardrail", "token")):
        llm = snapshot.get("llm_governance", {})
        if llm.get("status") == "available":
            parts.append(
                f"LLM governance (1h): {llm.get('traces_window', 0)} traces, "
                f"{llm.get('tokens_window', 0)} tokens, "
                f"{llm.get('error_rate', 0):.1%} error rate"
            )
            sources.append("llm_governance")
    
    # Status / health catch-all
    if any(kw in q_lower for kw in ("status", "health", "overview", "summary")):
        available = [k for k, v in snapshot.items() if isinstance(v, dict) and v.get("status") == "available"]
        errors = snapshot.get("errors", [])
        
        parts.append(f"System modules reporting: {', '.join(available) or 'none'}")
        if errors:
            parts.append(f"Errors in: {', '.join(e['source'] for e in errors)}")
    
    if not parts:
        parts.append(
            f"I can help with portfolio, risk, pipeline, agent health, and LLM governance questions. "
            f"Available data sources: {', '.join(k for k, v in snapshot.items() if isinstance(v, dict) and v.get('status') == 'available') or 'none'}"
        )
    
    return " ".join(parts), sources


def _summarize_dict(d: Dict[str, Any], max_keys: int = 8, exclude_keys: Optional[Set[str]] = None) -> str:
    """Summarize dictionary for display."""
    exclude_keys = exclude_keys or set()
    items = []
    
    for k, v in list(d.items())[:max_keys]:
        if k in exclude_keys:
            continue
        if isinstance(v, float):
            items.append(f"{k}={v:.2f}")
        elif isinstance(v, dict):
            items.append(f"{k}={{...}}")
        elif isinstance(v, (list, tuple)):
            items.append(f"{k}=[{len(v)} items]")
        else:
            items.append(f"{k}={v}")
    
    return ", ".join(items)


# ── Endpoints ───────────────────────────────────────────────────────────

@router.post("/query", response_model=AssistantResponseV2)
async def assistant_query_v2(
    request: Request,
    req: AssistantQueryV2,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> AssistantResponseV2:
    """
    Process an operator assistant query with rate limiting and structured errors.
    
    This endpoint is strictly read-only - no state mutations are performed.
    """
    start = time.time()
    trace_id = f"ast-{time.time():.6f}"
    
    # Rate limiting
    client_id = get_client_id(request, credentials)
    allowed, remaining, reset_at = check_rate_limit(client_id)
    
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=StructuredError(
                error_type="RateLimitExceeded",
                message=f"Rate limit exceeded: {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW_SECONDS}s",
                recovery_hint=f"Wait until {time.strftime('%H:%M:%S', time.localtime(reset_at))}",
                trace_id=trace_id
            ).dict()
        )
    
    try:
        # Gather snapshot with timeout
        snapshot = await asyncio.wait_for(
            asyncio.to_thread(
                _gather_system_snapshot,
                req.asset_filter,
                req.timeframe_filter
            ),
            timeout=RATE_LIMIT_TIMEOUT_SECONDS
        )
        
        # Build answer
        answer, sources = _build_answer(req.query, req.context, snapshot)
        
        latency_ms = (time.time() - start) * 1000
        
        # Record trace for governance (async, don't block response)
        asyncio.create_task(_record_trace(trace_id, req, answer, latency_ms))
        
        # Extract asset/timeframe health for response
        agent_health = snapshot.get("agent_health", {})
        
        return AssistantResponseV2(
            trace_id=trace_id,
            answer=answer,
            context_domain=req.context,
            sources=sources,
            system_snapshot=snapshot if req.include_system_snapshot else None,
            messages=[
                AssistantMessageV2(role="user", content=req.query, timestamp=start),
                AssistantMessageV2(role="assistant", content=answer, timestamp=time.time()),
            ],
            latency_ms=round(latency_ms, 2),
            rate_limit=RateLimitInfo(
                remaining=remaining,
                reset_at=reset_at,
                limit=RATE_LIMIT_REQUESTS
            ),
            asset_health=agent_health.get("asset_health") if agent_health.get("status") == "available" else None,
            timeframe_health=agent_health.get("timeframe_health") if agent_health.get("status") == "available" else None,
        )
    
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=StructuredError(
                error_type="QueryTimeout",
                message=f"Query processing exceeded {RATE_LIMIT_TIMEOUT_SECONDS}s timeout",
                recovery_hint="Retry with simpler query or check system load",
                trace_id=trace_id
            ).dict()
        )
    
    except Exception as exc:
        logger.error(f"Assistant query failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=StructuredError(
                error_type="InternalError",
                message=str(exc),
                recovery_hint="Check system logs or contact operator",
                trace_id=trace_id
            ).dict()
        )


async def _record_trace(
    trace_id: str,
    req: AssistantQueryV2,
    answer: str,
    latency_ms: float
) -> None:
    """Record trace for governance audit (fire-and-forget is OK here)."""
    try:
        store = get_llm_governance_store()
        store.record_trace(LLMTrace(
            id=trace_id,
            role=LLMRole.OPS if req.context == "operator" else LLMRole(req.context) if req.context in [r.value for r in LLMRole] else LLMRole.RESEARCH,
            prompt_version="assistant-v2",
            model_name="context-engine",
            tokens_prompt=len(req.query.split()),
            tokens_completion=len(answer.split()),
            tools_used=["system_snapshot"] if req.include_system_snapshot else [],
            latency_ms=latency_ms,
            status="completed",
        ))
    except Exception as exc:
        logger.warning("Failed to record assistant trace: %s", exc)


@router.get("/contexts")
async def list_contexts_v2() -> Dict[str, Any]:
    """List available assistant context domains."""
    return {
        "contexts": [
            {"id": "operator", "description": "Portfolio, risk, pipeline, and system health"},
            {"id": "dev", "description": "Dev swarm, proposals, code quality"},
            {"id": "cognitive", "description": "Regime detection, hypothesis testing"},
            {"id": "sports", "description": "Live odds, consensus summaries"},
            {"id": "risk", "description": "Kill switches, exposure, drawdown"},
        ],
        "rate_limit": {
            "requests_per_minute": RATE_LIMIT_REQUESTS,
            "timeout_seconds": RATE_LIMIT_TIMEOUT_SECONDS
        }
    }


@router.get("/health")
async def assistant_health_check() -> Dict[str, Any]:
    """Health check endpoint for the assistant API."""
    return {
        "status": "healthy",
        "version": "v2",
        "read_only": True,
        "rate_limit_config": {
            "requests_per_minute": RATE_LIMIT_REQUESTS,
            "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
            "timeout_seconds": RATE_LIMIT_TIMEOUT_SECONDS
        }
    }


# Backward compatibility: mount v2 routes at same path as v1
# V1 is deprecated but kept for transition period
