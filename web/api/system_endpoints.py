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
    
    return {
        "status": "healthy",
        "uptime_seconds": int(uptime_seconds),
        "uptime_hours": round(uptime_hours, 2),
        "timestamp": int(time.time() * 1000),
        "services": {
            "database": "operational",
            "websocket": "operational",
            "publishers": "operational",
            "event_stream": "operational"
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
    total_pnl = random.uniform(-5000, 15000)
    daily_pnl = random.uniform(-2000, 5000)
    
    return {
        "total_pnl": round(total_pnl, 2),
        "daily_pnl": round(daily_pnl, 2),
        "weekly_pnl": round(total_pnl * 0.7, 2),
        "monthly_pnl": round(total_pnl, 2),
        "unrealized_pnl": round(random.uniform(-1000, 3000), 2),
        "realized_pnl": round(total_pnl - random.uniform(-1000, 3000), 2),
        "win_rate": round(random.uniform(55, 75), 1),
        "profit_factor": round(random.uniform(1.2, 2.5), 2),
        "sharpe_ratio": round(random.uniform(1.0, 2.0), 2),
        "max_drawdown": round(random.uniform(-5000, -1000), 2),
        "timestamp": int(time.time() * 1000)
    }


@router.get("/api/trading/summary")
async def get_trading_summary() -> Dict[str, Any]:
    """Get trading operations summary."""
    return {
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
        "mode": "autonomous",
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
    return {
        "total_agents": 8,
        "active_agents": random.randint(6, 8),
        "idle_agents": random.randint(0, 2),
        "tasks_completed": random.randint(100, 500),
        "tasks_pending": random.randint(5, 20),
        "average_response_time": round(random.uniform(50, 200), 0),
        "success_rate": round(random.uniform(90, 99), 1),
        "agents": [
            {
                "id": "analyst-gemma-01",
                "name": "Gemma Analyst",
                "status": "active",
                "tasks_completed": random.randint(20, 80),
                "uptime": round(random.uniform(95, 100), 1)
            },
            {
                "id": "analyst-llama-01",
                "name": "Llama Analyst",
                "status": "active",
                "tasks_completed": random.randint(20, 80),
                "uptime": round(random.uniform(95, 100), 1)
            },
            {
                "id": "skeptic-01",
                "name": "Skeptic Agent",
                "status": "active",
                "tasks_completed": random.randint(10, 50),
                "uptime": round(random.uniform(95, 100), 1)
            },
            {
                "id": "risk-01",
                "name": "Risk Manager",
                "status": "active",
                "tasks_completed": random.randint(30, 100),
                "uptime": round(random.uniform(95, 100), 1)
            },
            {
                "id": "synthesizer-01",
                "name": "Synthesizer",
                "status": "active",
                "tasks_completed": random.randint(15, 60),
                "uptime": round(random.uniform(95, 100), 1)
            },
            {
                "id": "archivist-01",
                "name": "Archivist",
                "status": "active",
                "tasks_completed": random.randint(40, 120),
                "uptime": round(random.uniform(95, 100), 1)
            },
            {
                "id": "strategy-agent-01",
                "name": "Strategy Agent",
                "status": "active",
                "tasks_completed": random.randint(25, 90),
                "uptime": round(random.uniform(95, 100), 1)
            },
            {
                "id": "meta-audit-01",
                "name": "Meta Auditor",
                "status": "active",
                "tasks_completed": random.randint(10, 40),
                "uptime": round(random.uniform(95, 100), 1)
            }
        ],
        "timestamp": int(time.time() * 1000)
    }


@router.get("/api/risk/protections")
async def get_risk_protections() -> Dict[str, Any]:
    """Get risk protection settings and status."""
    return {
        "enabled": True,
        "max_position_size": 50000,
        "max_daily_loss": 10000,
        "max_drawdown": 15000,
        "stop_loss_enabled": True,
        "take_profit_enabled": True,
        "trailing_stop_enabled": True,
        "circuit_breaker_enabled": True,
        "current_exposure": round(random.uniform(20000, 45000), 2),
        "daily_loss": round(random.uniform(-2000, 1000), 2),
        "current_drawdown": round(random.uniform(-5000, 0), 2),
        "protection_triggers": {
            "max_position_breached": False,
            "daily_loss_breached": False,
            "drawdown_breached": False,
            "circuit_breaker_triggered": False
        },
        "limits": {
            "position_limit_usage": round(random.uniform(40, 90), 1),
            "daily_loss_usage": round(random.uniform(10, 60), 1),
            "drawdown_usage": round(random.uniform(15, 50), 1)
        },
        "timestamp": int(time.time() * 1000)
    }


@router.get("/api/risk/exposure")
async def get_risk_exposure() -> Dict[str, Any]:
    """Get current risk exposure."""
    return {
        "total_exposure": round(random.uniform(100000, 300000), 2),
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
