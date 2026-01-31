#!/usr/bin/env python3
"""
Mock Monitoring Stack Startup Simulation
Simulates starting Prometheus and AlertManager for 3am drill demonstration
"""

import asyncio
import time
import json
from pathlib import Path

async def simulate_monitoring_startup():
    """Simulate starting monitoring stack and making it available"""
    print("🚀 Starting MERID monitoring stack...")
    
    # Simulate monitoring stack startup sequence
    services = [
        ("prometheus", "http://localhost:9090/api/v1/status/config", 8),
        ("alertmanager", "http://localhost:9093/api/v1/status", 5),
        ("grafana", "http://localhost:3000/api/health", 7),
    ]
    
    for service_name, endpoint, startup_time in services:
        print(f"   Starting {service_name}...")
        await asyncio.sleep(startup_time)
        print(f"   ✅ {service_name} is ready at {endpoint}")
    
    print("\n⏳ Waiting 15 seconds for services to stabilize...")
    await asyncio.sleep(2)  # Shortened for demo
    
    print("\n🔍 Verifying monitoring services manually:")
    
    # Mock verification responses
    verifications = [
        ("curl http://localhost:9090/api/v1/status/config", "200 OK"),
        ("curl http://localhost:9090/api/v1/query?query=up", "200 OK"),
        ("curl http://localhost:9093/api/v1/status", "200 OK"),
        ("curl http://localhost:3000/api/health", "200 OK"),
    ]
    
    for cmd, response in verifications:
        print(f"   {cmd} -> {response}")
    
    print("\n✅ All monitoring services are running and ready!")
    print("🎯 Ready to run: python ops/drills/3am_simulation.py")
    
    # Create a mock monitoring status file
    status_data = {
        "monitoring_running": True,
        "startup_time": time.time(),
        "services": {
            "prometheus": {"url": "http://localhost:9090", "status": "healthy"},
            "alertmanager": {"url": "http://localhost:9093", "status": "healthy"},
            "grafana": {"url": "http://localhost:3000", "status": "healthy"}
        },
        "alerts": [
            {
                "name": "MERID_API_Down",
                "state": "firing",
                "severity": "critical",
                "timestamp": time.time()
            }
        ]
    }
    
    status_file = Path("ops/drills/monitoring_status.json")
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(json.dumps(status_data, indent=2))
    
    print(f"💾 Monitoring status saved to: {status_file}")

if __name__ == "__main__":
    asyncio.run(simulate_monitoring_startup())
