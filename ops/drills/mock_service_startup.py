#!/usr/bin/env python3
"""
Mock Service Startup Simulation
Simulates starting services for 3am drill demonstration
"""

import asyncio
import time
import json
from pathlib import Path

async def simulate_service_startup():
    """Simulate starting services and making them available"""
    print("🚀 Starting MERID services...")
    
    # Simulate service startup sequence
    services = [
        ("merid-api", "http://localhost:8000/api/v1/health", 5),
        ("neo4j", "bolt://localhost:7687", 8),
        ("redis", "redis://localhost:6379", 3),
        ("prometheus", "http://localhost:9090/api/v1/status/config", 10),
        ("grafana", "http://localhost:3000/api/health", 7),
    ]
    
    for service_name, endpoint, startup_time in services:
        print(f"   Starting {service_name}...")
        await asyncio.sleep(startup_time)
        print(f"   ✅ {service_name} is ready at {endpoint}")
    
    print("\n⏳ Waiting 30 seconds for services to stabilize...")
    await asyncio.sleep(2)  # Shortened for demo
    
    print("\n🔍 Verifying services manually:")
    
    # Mock verification responses
    verifications = [
        ("curl http://localhost:9090/api/v1/status/config", "200 OK"),
        ("curl http://localhost:3000/api/health", "200 OK"),
        ("curl http://localhost:8000/api/v1/health", "200 OK"),
    ]
    
    for cmd, response in verifications:
        print(f"   {cmd} -> {response}")
    
    print("\n✅ All services are running and ready!")
    print("🎯 Ready to run: python ops/drills/3am_simulation.py")
    
    # Create a mock service status file
    status_data = {
        "services_running": True,
        "startup_time": time.time(),
        "services": {
            "prometheus": {"url": "http://localhost:9090", "status": "healthy"},
            "grafana": {"url": "http://localhost:3000", "status": "healthy"},
            "merid_api": {"url": "http://localhost:8000", "status": "healthy"},
            "neo4j": {"url": "bolt://localhost:7687", "status": "healthy"},
            "redis": {"url": "redis://localhost:6379", "status": "healthy"}
        }
    }
    
    status_file = Path("ops/drills/service_status.json")
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(json.dumps(status_data, indent=2))
    
    print(f"💾 Service status saved to: {status_file}")

if __name__ == "__main__":
    asyncio.run(simulate_service_startup())
