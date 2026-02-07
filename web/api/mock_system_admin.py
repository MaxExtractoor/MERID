"""
Mock API endpoints for system administration
"""

from fastapi import APIRouter
from typing import Dict, List, Any
import random
import time
import psutil
import os

router = APIRouter()

@router.get("/health")
async def get_system_health():
    """Get overall system health status"""
    # Get system metrics
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # Determine overall health
    status = "healthy"
    if cpu_percent > 80 or memory.percent > 85:
        status = "degraded"
    if cpu_percent > 95 or memory.percent > 95:
        status = "unhealthy"
    
    return {
        "status": status,
        "uptime": time.time() - psutil.boot_time(),
        "version": "2.0.0",
        "build": "dev",
        "cpu_percent": cpu_percent,
        "memory_percent": memory.percent,
        "disk_percent": disk.percent,
        "timestamp": time.time()
    }

@router.get("/subsystems")
async def get_subsystems():
    """Get status of all system subsystems"""
    subsystems = [
        {
            "id": "orchestrator",
            "name": "Core Orchestrator",
            "status": "healthy",
            "description": "Agent coordination and task distribution",
            "memory": random.randint(100, 500) * 1024 * 1024,
            "cpu": random.uniform(5, 25),
            "connections": random.randint(5, 15),
            "last_update": time.time() - random.randint(0, 60)
        },
        {
            "id": "prediction_aggregator",
            "name": "Prediction Market Aggregator",
            "status": random.choice(["healthy", "degraded"]),
            "description": "Polymarket and prediction market data aggregation",
            "memory": random.randint(200, 800) * 1024 * 1024,
            "cpu": random.uniform(10, 30),
            "connections": random.randint(10, 25),
            "last_update": time.time() - random.randint(0, 60)
        },
        {
            "id": "price_feed",
            "name": "Live Price Feed",
            "status": random.choice(["healthy", "degraded", "unhealthy"]),
            "description": "Real-time price data from multiple exchanges",
            "memory": random.randint(50, 300) * 1024 * 1024,
            "cpu": random.uniform(3, 15),
            "connections": random.randint(3, 8),
            "last_update": time.time() - random.randint(0, 60)
        },
        {
            "id": "news_agent",
            "name": "News Sentinel Agent",
            "status": "healthy",
            "description": "News monitoring and sentiment analysis",
            "memory": random.randint(100, 400) * 1024 * 1024,
            "cpu": random.uniform(5, 20),
            "connections": random.randint(2, 6),
            "last_update": time.time() - random.randint(0, 60)
        },
        {
            "id": "trading_engine",
            "name": "Trading Execution Engine",
            "status": random.choice(["healthy", "degraded"]),
            "description": "Order execution and position management",
            "memory": random.randint(150, 600) * 1024 * 1024,
            "cpu": random.uniform(8, 35),
            "connections": random.randint(5, 12),
            "last_update": time.time() - random.randint(0, 60)
        },
        {
            "id": "database",
            "name": "Database Layer",
            "status": random.choice(["healthy", "degraded"]),
            "description": "PostgreSQL database connection pool",
            "memory": random.randint(200, 1000) * 1024 * 1024,
            "cpu": random.uniform(5, 25),
            "connections": random.randint(10, 20),
            "last_update": time.time() - random.randint(0, 60)
        },
        {
            "id": "websocket_server",
            "name": "WebSocket Server",
            "status": "healthy",
            "description": "Real-time WebSocket connections",
            "memory": random.randint(50, 200) * 1024 * 1024,
            "cpu": random.uniform(2, 10),
            "connections": random.randint(1, 5),
            "last_update": time.time() - random.randint(0, 60)
        },
        {
            "id": "simulation_engine",
            "name": "Simulation Engine",
            "status": random.choice(["healthy", "degraded"]),
            "description": "Agent simulation and testing framework",
            "memory": random.randint(300, 800) * 1024 * 1024,
            "cpu": random.uniform(15, 40),
            "connections": random.randint(8, 16),
            "last_update": time.time() - random.randint(0, 60)
        }
    ]
    
    return {"subsystems": subsystems}

@router.get("/metrics")
async def get_system_metrics():
    """Get detailed system metrics"""
    # Get real system metrics
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # Network stats
    network = psutil.net_io_counters()
    
    # Process info
    processes = len(psutil.pids())
    
    return {
        "cpu": cpu_percent,
        "memory_used": memory.used,
        "memory_total": memory.total,
        "memory_percent": memory.percent,
        "disk_used": disk.used,
        "disk_total": disk.total,
        "disk_percent": disk.percent,
        "network_bytes_sent": network.bytes_sent,
        "network_bytes_recv": network.bytes_recv,
        "processes": processes,
        "websocket_clients": random.randint(5, 25),
        "queue_depth": random.randint(0, 50),
        "db_status": random.choice(["connected", "slow", "disconnected"]),
        "db_connections": random.randint(5, 15),
        "price_feed_status": random.choice(["active", "delayed", "offline"]),
        "price_feed_lag": random.randint(10, 500),
        "timestamp": time.time()
    }

@router.get("/events")
async def get_system_events(limit: int = 20):
    """Get recent system events"""
    events = []
    
    event_types = ["info", "warning", "error", "critical"]
    sources = ["orchestrator", "price_feed", "database", "websocket", "trading_engine", "news_agent"]
    
    messages = [
        "Component started successfully",
        "Component health check passed",
        "Component performance degraded",
        "Component error detected",
        "Component restarted",
        "Connection established",
        "Connection lost",
        "High memory usage detected",
        "High CPU usage detected",
        "Database query slow",
        "WebSocket client connected",
        "WebSocket client disconnected",
        "Task completed successfully",
        "Task failed with error",
        "System backup completed",
        "Configuration updated"
    ]
    
    for i in range(limit):
        events.append({
            "id": f"event_{i}",
            "level": random.choice(event_types),
            "source": random.choice(sources),
            "message": random.choice(messages),
            "timestamp": time.time() - random.randint(0, 3600)
        })
    
    # Sort by timestamp (newest first)
    events.sort(key=lambda x: x["timestamp"], reverse=True)
    
    return {"events": events}

@router.post("/subsystems/{subsystem_id}/restart")
async def restart_subsystem(subsystem_id: str):
    """Restart a specific subsystem"""
    # Mock restart
    return {
        "success": True,
        "subsystem_id": subsystem_id,
        "restarted_at": time.time(),
        "message": f"Subsystem {subsystem_id} restart initiated"
    }

@router.get("/subsystems/{subsystem_id}/logs")
async def get_subsystem_logs(subsystem_id: str, limit: int = 50):
    """Get logs for a specific subsystem"""
    logs = []
    
    log_levels = ["INFO", "WARNING", "ERROR", "DEBUG"]
    
    for i in range(limit):
        logs.append({
            "id": f"log_{subsystem_id}_{i}",
            "level": random.choice(log_levels),
            "message": f"Log entry {i} for {subsystem_id}",
            "timestamp": time.time() - random.randint(0, 3600),
            "source": subsystem_id
        })
    
    return {"logs": logs}
