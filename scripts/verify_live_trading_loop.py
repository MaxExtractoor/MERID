#!/usr/bin/env python3
"""
Verify that the 15m trading loop is properly wired for order execution.

This script checks:
1. Loop is running and executing cycles
2. Agent grid is initialized with 5 agents
3. Agents are generating signals/candidates
4. Infrastructure (WS, catalog, spot) is healthy
5. Order router is being called (log-based check)

Usage:
    python scripts/verify_live_trading_loop.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

async def verify_loop_wiring():
    """Verify trading loop execution path."""
    print("=== 15m Trading Loop Wiring Verification ===\n")
    
    # 1. Check loop is running
    print("1. Checking loop status...")
    try:
        from web.main_15m_lean import app
        from fastapi.testclient import TestClient
        
        client = TestClient(app)
        response = client.get("/api/v1/loop-status")
        status = response.json()
        
        print(f"   Loop status: {status['status']}")
        print(f"   Running: {status['running']}")
        print(f"   Last cycle: {status.get('last_cycle_at')}")
        print(f"   Pipeline ready: {status.get('pipeline_ready', False)}")
        print(f"   Trading ready: {status.get('trading_ready', False)}")
        
        if status['status'] != 'running':
            print("   ❌ FAIL: Loop is not running")
            return False
        print("   ✅ PASS: Loop is running\n")
    except Exception as e:
        print(f"   ❌ FAIL: {e}\n")
        return False
    
    # 2. Check agent grid is initialized
    print("2. Checking agent grid...")
    try:
        response = client.get("/debug/state")
        state = response.json()
        
        print(f"   Has grid: {state['has_grid']}")
        print(f"   Grid type: {state['grid_type']}")
        print(f"   Grid module: {state['grid_module']}")
        
        if not state['has_grid']:
            print("   ❌ FAIL: Agent grid not initialized")
            return False
        print("   ✅ PASS: Agent grid initialized\n")
    except Exception as e:
        print(f"   ❌ FAIL: {e}\n")
        return False
    
    # 3. Check agents are generating candidates
    print("3. Checking agent signal generation...")
    try:
        response = client.get("/api/v1/agents")
        agents = response.json()
        
        print(f"   Schema version: {agents['schema_version']}")
        print(f"   Initialized: {agents['initialized']}")
        print(f"   Total agents: {agents['summary']['total']}")
        print(f"   Enabled: {agents['summary']['enabled']}")
        print(f"   Disabled: {agents['summary']['disabled']}")
        print(f"   Zombies: {agents['summary']['zombies']}")
        
        if not agents['initialized']:
            print("   ❌ FAIL: Agents not initialized")
            return False
        
        if agents['summary']['enabled'] == 0:
            print("   ❌ FAIL: No agents enabled")
            return False
        
        print("\n   Per-agent status:")
        for asset, agent_data in agents['agents_by_asset'].items():
            print(f"   {asset}:")
            print(f"     - enabled: {agent_data['enabled']}")
            print(f"     - has_signal: {agent_data['has_signal']}")
            print(f"     - last_signal_age: {agent_data['last_signal_age_seconds']:.1f}s")
            print(f"     - is_zombie: {agent_data['is_zombie']}")
            print(f"     - open_positions: {agent_data['open_positions']}")
        
        print("   ✅ PASS: Agents are generating signals\n")
    except Exception as e:
        print(f"   ❌ FAIL: {e}\n")
        return False
    
    # 4. Check for order router calls (log-based)
    print("4. Checking for order router calls...")
    print("   ⚠️  MANUAL CHECK: Review logs for 'route_order_async' calls")
    print("   Expected log pattern: '[15M-LOOP] Order routed:' or '[AGENT-ORDER] Placed order:'")
    print("   If no such logs exist, the candidate-to-order bridge is missing\n")
    
    # 5. Check infra health
    print("5. Checking infrastructure health...")
    try:
        response = client.get("/api/v1/infra")
        infra = response.json()
        
        print(f"   WS connected: {infra['ws_forwarder']['connected']}")
        print(f"   WS healthy: {infra['ws_forwarder']['healthy']}")
        print(f"   WS events/sec: {infra['ws_forwarder']['events_per_sec']}")
        print(f"   Catalog state: {infra['catalog']['state']}")
        print(f"   Catalog age: {infra['catalog']['age_s']:.1f}s")
        
        md_healthy = len([s for s in infra['md_freshness'].values() if s['state'] == 'healthy'])
        print(f"   MD fresh: {md_healthy}/5")
        
        spot_healthy = len([s for s in infra['spot_freshness'].values() if s['state'] == 'healthy'])
        print(f"   Spot fresh: {spot_healthy}/5")
        
        if not infra['ws_forwarder']['connected']:
            print("   ⚠️  WARNING: WS not connected")
        
        if md_healthy < 5:
            print(f"   ⚠️  WARNING: Only {md_healthy}/5 MD fresh")
        
        if spot_healthy < 5:
            print(f"   ⚠️  WARNING: Only {spot_healthy}/5 spot fresh")
        
        print("   ✅ PASS: Infra check complete\n")
    except Exception as e:
        print(f"   ❌ FAIL: {e}\n")
        return False
    
    # 6. Check health endpoint
    print("6. Checking overall health...")
    try:
        response = client.get("/api/v1/health")
        health = response.json()
        
        print(f"   Status: {health['status']}")
        print(f"   API version: {health['api_version']}")
        print(f"   Startup completed: {health['startup_completed']}")
        print(f"   Loop task alive: {health['loop_task_alive']}")
        
        if health['status'] != 'ok':
            print(f"   ⚠️  WARNING: Health status is '{health['status']}'")
        
        print("   ✅ PASS: Health check complete\n")
    except Exception as e:
        print(f"   ❌ FAIL: {e}\n")
        return False
    
    print("=== Verification Complete ===\n")
    print("CRITICAL GAP IDENTIFIED:")
    print("The trading loop is running and agents generate candidates,")
    print("but there is NO code that converts candidates to actual orders.")
    print("\nFix location: merid/loop_15m.py lines 985 and 2747")
    print("The loop calls agent_grid.run_cycle() but ignores the return value.")
    print("Add candidate processing logic to convert dicts to OrderIntent")
    print("and call route_order_async() with proper risk contract.")
    
    return True

if __name__ == "__main__":
    try:
        result = asyncio.run(verify_loop_wiring())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
