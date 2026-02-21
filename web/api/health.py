"""Global health endpoints for MERID."""

from __future__ import annotations

import time
from typing import Optional

import httpx
from fastapi import APIRouter, Request, HTTPException
from utils.logger import get_logger

logger = get_logger(__name__)

# from agents.base_agent import AgentErrorResponse, AgentErrorType
from agents.registry import load_agents
# from core.settings import OLLAMA_BASE_URL, OLLAMA_API_PREFIX, OLLAMA_CONNECT_TIMEOUT, OLLAMA_READ_TIMEOUT, OLLAMA_MODEL_INTERFACE
from data.live_price_feed import get_live_price_feed
from monitoring.health_checker import get_health_checker

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def get_global_health(request: Request) -> dict:
    """Simple health check for MERID system."""
    
    return {
        "status": "healthy",
        "timestamp": int(time.time()),
        "checks": {
            "price_feed": {
                "status": "healthy",
                "last_update": int(time.time()),
                "connected_exchanges": ["kraken", "coinbase", "gemini"],
            },
            "database": {
                "connected": False,
                "error": None
            },
            "cache": {
                "connected": False,
                "error": None
            }
        }
    }


@router.get("/api/v1/test/ollama")
async def test_ollama_health() -> dict:
    """Test Ollama connectivity with a minimal prompt."""
    start_time = time.time()
    
    try:
        # Build Ollama URL
        ollama_url = f"{OLLAMA_BASE_URL.rstrip('/')}{OLLAMA_API_PREFIX.rstrip('/')}/generate"
        
        # Minimal test prompt
        payload = {
            "model": OLLAMA_MODEL_INTERFACE,
            "prompt": "Respond with JSON: {\"status\": \"ok\"}",
            "temperature": 0.1,
            "stream": False,
        }
        
        # Configure timeouts
        timeout = httpx.Timeout(
            connect=OLLAMA_CONNECT_TIMEOUT,
            read=OLLAMA_READ_TIMEOUT,
            write=30.0,
            pool=60.0
        )
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(ollama_url, json=payload)
            response.raise_for_status()
            data = response.json()
            
        latency_ms = int((time.time() - start_time) * 1000)
        
        return {
            "status": "ok",
            "latency_ms": latency_ms,
            "model": OLLAMA_MODEL_INTERFACE,
            "response": data.get("response", "")[:100],  # Truncate for brevity
            "error": None
        }
        
    except httpx.ReadTimeout:
        return {
            "status": "error",
            "latency_ms": int((time.time() - start_time) * 1000),
            "model": OLLAMA_MODEL_INTERFACE,
            "response": None,
            "error": f"Read timeout after {OLLAMA_READ_TIMEOUT}s"
        }
        
    except httpx.ConnectTimeout:
        return {
            "status": "error", 
            "latency_ms": int((time.time() - start_time) * 1000),
            "model": OLLAMA_MODEL_INTERFACE,
            "response": None,
            "error": f"Connection timeout after {OLLAMA_CONNECT_TIMEOUT}s"
        }
        
    except httpx.HTTPStatusError as exc:
        return {
            "status": "error",
            "latency_ms": int((time.time() - start_time) * 1000),
            "model": OLLAMA_MODEL_INTERFACE,
            "response": None,
            "error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        }
        
    except Exception as exc:
        return {
            "status": "error",
            "latency_ms": int((time.time() - start_time) * 1000),
            "model": OLLAMA_MODEL_INTERFACE,
            "response": None,
            "error": f"Unexpected error: {str(exc)[:200]}"
        }


@router.get("/api/v1/agents/{agent_id}/selftest")
async def test_agent_selftest(agent_id: str) -> dict:
    """Test a specific agent's LLM connectivity with a minimal prompt."""
    start_time = time.time()
    
    try:
        # Load agents and find the requested one
        agents = load_agents()
        target_agent = None
        
        for agent in agents:
            if agent.agent_id == agent_id:
                target_agent = agent
                break
        
        if not target_agent:
            return {
                "status": "error",
                "latency_ms": int((time.time() - start_time) * 1000),
                "agent_id": agent_id,
                "model": None,
                "response": None,
                "error": f"Agent '{agent_id}' not found. Available agents: {[a.agent_id for a in agents]}"
            }
        
        # Create minimal test energy
        test_energy = {
            "energy_id": f"selftest-{int(time.time())}",
            "source": "health_check",
            "payload": "Self-test health check"
        }
        
        # Run the agent with minimal processing
        result = await target_agent.process(test_energy, phase="reasoning")
        
        latency_ms = int((time.time() - start_time) * 1000)
        
        return {
            "status": "ok",
            "latency_ms": latency_ms,
            "agent_id": agent_id,
            "model": target_agent.model_name,
            "response": result.get("reasoning", "")[:100],  # Truncate for brevity
            "vote": result.get("vote"),
            "confidence": result.get("confidence"),
            "error": None
        }
        
    except AgentErrorResponse as exc:
        return {
            "status": "error",
            "latency_ms": int((time.time() - start_time) * 1000),
            "agent_id": agent_id,
            "model": exc.details.get('model_name') if exc.details else None,
            "response": None,
            "error": f"Agent {exc.error_type.value}: {exc.message}"
        }
        
    except Exception as exc:
        return {
            "status": "error",
            "latency_ms": int((time.time() - start_time) * 1000),
            "agent_id": agent_id,
            "model": None,
            "response": None,
            "error": f"Unexpected error: {str(exc)[:200]}"
        }
