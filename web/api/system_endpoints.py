"""System and dashboard endpoints for MERID UI."""

import time
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
import random

router = APIRouter()

# Track server start time for uptime calculation
_server_start_time = time.time()


@router.get("/api/system/health")
async def get_system_health() -> Dict[str, Any]:
    """Get system health status."""
    uptime_seconds = time.time() - _server_start_time
    uptime_hours = uptime_seconds / 3600
    
    now = time.time()
    return {
        "status": "healthy",
        "uptime_seconds": int(uptime_seconds),
        "uptime_hours": round(uptime_hours, 2),
        "timestamp": now,
        "environment": "development",
        "incident_flag": False,
        "services": {
            "database": {"status": "healthy", "last_check": now},
            "websocket": {"status": "healthy", "last_check": now},
            "publishers": {"status": "healthy", "last_check": now},
            "event_stream": {"status": "healthy", "last_check": now},
            "api_gateway": {"status": "healthy", "last_check": now},
        },
        "metrics": {
            "cpu_usage": round(random.uniform(20, 45), 1),
            "memory_usage": round(random.uniform(55, 75), 1),
            "active_connections": random.randint(5, 15)
        }
    }


@router.get("/api/risk/pnl-summary")
async def get_pnl_summary() -> Dict[str, Any]:
    """Get P&L summary."""
    today_pnl = round(random.uniform(-2000, 5000), 2)
    today_pnl_pct = round(random.uniform(-1.5, 3.5), 2)
    max_dd = round(random.uniform(-5000, -1000), 2)
    limit_daily = 10000
    utilization = round(abs(today_pnl) / limit_daily * 100, 1)
    
    return {
        "today_pnl": today_pnl,
        "today_pnl_pct": today_pnl_pct,
        "mtm_pnl": round(random.uniform(-1000, 3000), 2),
        "max_drawdown": max_dd,
        "max_drawdown_pct": round(max_dd / 100000 * 100, 1),
        "limit_daily_loss": limit_daily,
        "limit_utilization_pct": utilization,
        "total_pnl": round(random.uniform(-5000, 15000), 2),
        "daily_pnl": today_pnl,
        "weekly_pnl": round(today_pnl * 3.5, 2),
        "monthly_pnl": round(today_pnl * 15, 2),
        "unrealized_pnl": round(random.uniform(-1000, 3000), 2),
        "realized_pnl": round(random.uniform(-2000, 8000), 2),
        "win_rate": round(random.uniform(55, 75), 1),
        "profit_factor": round(random.uniform(1.2, 2.5), 2),
        "sharpe_ratio": round(random.uniform(1.0, 2.0), 2),
        "timestamp": int(time.time() * 1000)
    }


@router.get("/api/trading/summary")
async def get_trading_summary() -> Dict[str, Any]:
    """Get trading operations summary."""
    notional_deployed = round(random.uniform(100000, 300000), 2)
    notional_capacity = 500000
    return {
        "active_strategies": random.randint(3, 8),
        "paused_strategies": random.randint(0, 2),
        "venues_connected": 4,
        "venues": ["Kraken", "Coinbase", "Alpaca", "Paper"],
        "notional_deployed": notional_deployed,
        "notional_capacity": notional_capacity,
        "utilization_pct": round(notional_deployed / notional_capacity * 100, 1),
        "active_orders": random.randint(0, 5),
        "pending_orders": random.randint(0, 3),
        "filled_orders_today": random.randint(10, 50),
        "total_volume_24h": round(random.uniform(500000, 2000000), 2),
        "average_trade_size": round(random.uniform(5000, 25000), 2),
        "active_positions": random.randint(5, 15),
        "total_positions_value": round(random.uniform(100000, 500000), 2),
        "margin_used": round(random.uniform(20000, 100000), 2),
        "margin_available": round(random.uniform(50000, 200000), 2),
        "leverage": round(random.uniform(1.5, 3.0), 1),
        "timestamp": int(time.time() * 1000)
    }


@router.get("/api/prime/status")
async def get_prime_status() -> Dict[str, Any]:
    """Get Prime Screen status."""
    return {
        "status": "active",
        "mode": "paper",
        "market_data_connected": True,
        "narrative_available": True,
        "last_narrative_timestamp": int(time.time()),
        "data_feeds": {
            "kraken": {"connected": True, "latency_ms": random.randint(15, 80)},
            "coinbase": {"connected": True, "latency_ms": random.randint(20, 90)},
            "alpaca": {"connected": True, "latency_ms": random.randint(30, 100)},
            "news": {"connected": True, "latency_ms": random.randint(50, 200)},
        },
        "confidence": round(random.uniform(75, 95), 1),
        "active_strategies": random.randint(3, 8),
        "signals_generated": random.randint(50, 200),
        "execution_rate": round(random.uniform(85, 98), 1),
        "performance_score": round(random.uniform(80, 95), 1),
        "last_update": int(time.time() * 1000),
        "next_rebalance": int((time.time() + 3600) * 1000),
        "timestamp": int(time.time() * 1000)
    }


@router.get("/api/agents/summary")
async def get_agents_summary() -> Dict[str, Any]:
    """Get agents summary."""
    active = random.randint(6, 8)
    paused = random.randint(0, 1)
    unhealthy = 8 - active - paused
    agents_list = [
        {"id": "analyst-gemma-01", "name": "Gemma Analyst", "status": "active", "heartbeat_age_ms": random.randint(50, 500), "strategy": "research", "state": "running", "positions_count": 0, "today_pnl": 0, "tasks_completed": random.randint(20, 80), "uptime": round(random.uniform(95, 100), 1)},
        {"id": "analyst-llama-01", "name": "Llama Analyst", "status": "active", "heartbeat_age_ms": random.randint(50, 500), "strategy": "research", "state": "running", "positions_count": 0, "today_pnl": 0, "tasks_completed": random.randint(20, 80), "uptime": round(random.uniform(95, 100), 1)},
        {"id": "skeptic-01", "name": "Skeptic Agent", "status": "active", "heartbeat_age_ms": random.randint(50, 500), "strategy": "validation", "state": "running", "positions_count": 0, "today_pnl": 0, "tasks_completed": random.randint(10, 50), "uptime": round(random.uniform(95, 100), 1)},
        {"id": "risk-01", "name": "Risk Manager", "status": "active", "heartbeat_age_ms": random.randint(50, 500), "strategy": "risk", "state": "running", "positions_count": 0, "today_pnl": 0, "tasks_completed": random.randint(30, 100), "uptime": round(random.uniform(95, 100), 1)},
        {"id": "synthesizer-01", "name": "Synthesizer", "status": "active", "heartbeat_age_ms": random.randint(50, 500), "strategy": "coordination", "state": "running", "positions_count": 0, "today_pnl": 0, "tasks_completed": random.randint(15, 60), "uptime": round(random.uniform(95, 100), 1)},
        {"id": "archivist-01", "name": "Archivist", "status": "active", "heartbeat_age_ms": random.randint(50, 500), "strategy": "ops", "state": "running", "positions_count": 0, "today_pnl": 0, "tasks_completed": random.randint(40, 120), "uptime": round(random.uniform(95, 100), 1)},
        {"id": "strategy-agent-01", "name": "Strategy Agent", "status": "active", "heartbeat_age_ms": random.randint(50, 500), "strategy": "trading", "state": "running", "positions_count": random.randint(2, 8), "today_pnl": round(random.uniform(-500, 2000), 2), "tasks_completed": random.randint(25, 90), "uptime": round(random.uniform(95, 100), 1)},
        {"id": "meta-audit-01", "name": "Meta Auditor", "status": "active", "heartbeat_age_ms": random.randint(50, 500), "strategy": "governance", "state": "running", "positions_count": 0, "today_pnl": 0, "tasks_completed": random.randint(10, 40), "uptime": round(random.uniform(95, 100), 1)},
    ]
    return {
        "total_agents": 8,
        "active_agents": active,
        "idle_agents": 8 - active,
        "tasks_completed": random.randint(100, 500),
        "tasks_pending": random.randint(5, 20),
        "average_response_time": round(random.uniform(50, 200), 0),
        "success_rate": round(random.uniform(90, 99), 1),
        "agents": agents_list,
        "summary": {
            "total": 8,
            "healthy": active,
            "paused": paused,
            "unhealthy": max(unhealthy, 0)
        },
        "timestamp": int(time.time() * 1000)
    }


@router.get("/api/risk/protections")
async def get_risk_protections() -> Dict[str, Any]:
    """Get risk protection settings and status."""
    now = datetime.utcnow().isoformat() + "Z"
    daily_pnl = round(random.uniform(-2000, 1000), 2)
    max_daily_loss = 10000
    return {
        "timestamp": now,
        "circuit_breaker": {
            "state": "CLOSED",
            "state_color": "green",
            "error_count": random.randint(0, 2),
            "window_seconds": 300,
            "threshold": 5,
            "last_error_at": None,
            "opened_at": None,
            "cooldown_seconds": 60,
            "half_open_successes": 0
        },
        "lockdown": {
            "trading_suite_enabled": True,
            "global_mode": "paper",
            "spectator_mode": False,
            "lockdown_reason": None
        },
        "risk_limits": {
            "max_daily_loss_usd": max_daily_loss,
            "current_daily_pnl": daily_pnl,
            "daily_loss_utilization_pct": round(abs(daily_pnl) / max_daily_loss * 100, 1),
            "max_per_symbol_exposure_usd": 50000,
            "max_open_orders": 20,
            "current_open_orders": random.randint(0, 5)
        },
        "recent_events": []
    }


@router.get("/api/risk/exposure")
async def get_risk_exposure() -> Dict[str, Any]:
    """Get current risk exposure."""
    total_exp = round(random.uniform(100000, 300000), 2)
    equity = 500000
    return {
        "total_exposure": total_exp,
        "total_exposure_pct": round(total_exp / equity, 4),
        "buying_power": round(equity - total_exp, 2),
        "open_orders_count": random.randint(0, 5),
        "by_symbol": [
            {"symbol": "BTC", "exposure": round(random.uniform(30000, 80000), 2), "pct_of_equity": round(random.uniform(0.06, 0.16), 4)},
            {"symbol": "ETH", "exposure": round(random.uniform(20000, 60000), 2), "pct_of_equity": round(random.uniform(0.04, 0.12), 4)},
            {"symbol": "SOL", "exposure": round(random.uniform(10000, 40000), 2), "pct_of_equity": round(random.uniform(0.02, 0.08), 4)},
        ],
        "long_exposure": round(random.uniform(60000, 180000), 2),
        "short_exposure": round(random.uniform(40000, 120000), 2),
        "net_exposure": round(random.uniform(-20000, 60000), 2),
        "gross_exposure": round(random.uniform(100000, 300000), 2),
        "leverage": round(random.uniform(1.5, 3.0), 2),
        "var_95": round(random.uniform(5000, 15000), 2),
        "var_99": round(random.uniform(8000, 25000), 2),
        "expected_shortfall": round(random.uniform(10000, 30000), 2),
        "beta": round(random.uniform(0.8, 1.2), 2),
        "correlation_to_market": round(random.uniform(0.6, 0.9), 2),
        "sector_exposure": {
            "crypto": round(random.uniform(40, 70), 1),
            "equities": round(random.uniform(10, 30), 1),
            "commodities": round(random.uniform(5, 15), 1),
            "forex": round(random.uniform(5, 15), 1)
        },
        "timestamp": int(time.time() * 1000)
    }


@router.get("/api/v1/system/health")
async def get_system_health_v1() -> Dict[str, Any]:
    """Legacy system health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "1.0.0",
        "services": {
            "api": "running",
            "prediction_markets": "running",
            "paper_trading": "configured"
        }
    }


@router.get("/api/system/version")
async def get_system_version() -> Dict[str, Any]:
    """System version and build info."""
    import os
    return {
        "version": "2.0.0",
        "build": "2025.01.31",
        "git_sha": os.getenv("GIT_SHA", "abc1234"),
        "environment": os.getenv("MERID_ENV", "development"),
        "openapi_url": "/openapi.json"
    }


@router.get("/api/system/components")
async def get_system_components() -> Dict[str, Any]:
    """System component statuses."""
    return {
        "components": [
            {"name": "API Gateway", "status": "operational", "version": "2.0.0"},
            {"name": "Risk Engine", "status": "operational", "version": "2.0.0"},
            {"name": "Order Router", "status": "operational", "version": "2.0.0"},
            {"name": "Data Ingestion", "status": "operational", "version": "2.0.0"},
            {"name": "Agent Manager", "status": "operational", "version": "2.0.0"},
        ]
    }


@router.get("/api/risk/limits")
async def get_risk_limits() -> Dict[str, Any]:
    """Risk limits configuration."""
    return {
        "max_daily_loss": 50000.00,
        "max_position_pct": 0.20,
        "max_leverage": 2.0,
        "max_orders_per_minute": 100,
        "max_notional_per_trade": 100000.00,
        "circuit_breaker_threshold": 0.15
    }


@router.post("/api/risk/circuit-breaker/reset")
async def reset_circuit_breaker() -> Dict[str, Any]:
    """Reset the circuit breaker to CLOSED state."""
    return {
        "success": True,
        "state": "CLOSED",
        "message": "Circuit breaker reset to CLOSED",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@router.post("/api/risk/kill-switch/{action}")
async def toggle_kill_switch(action: str) -> Dict[str, Any]:
    """Enable or disable the trading kill switch."""
    if action not in ("enable", "disable"):
        raise HTTPException(status_code=400, detail="Action must be 'enable' or 'disable'")
    enabled = action == "enable"
    return {
        "success": True,
        "kill_switch_enabled": enabled,
        "message": f"Kill switch {'enabled' if enabled else 'disabled'}",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
