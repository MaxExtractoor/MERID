#!/usr/bin/env python3
"""
Check agent grid status from the running server.
This script checks if all crypto agents are active and functioning.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.prediction.agent_grid_15m import get_agent_grid
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS


def check_agent_grid_status():
    """Check agent grid status from running server."""
    print("="*80)
    print("AGENT GRID STATUS CHECK")
    print("="*80)
    print(f"Timestamp: {datetime.now(timezone.utc)}")
    print()
    
    # Get agent grid (singleton from running server)
    try:
        agent_grid = get_agent_grid()
        print("✅ Agent grid singleton available")
    except Exception as e:
        print(f"❌ Agent grid not available: {e}")
        return {"status": "NO_GRID", "error": str(e)}
    
    # Check each asset's agent
    results = {}
    for asset in ACTIVE_CRYPTO_ASSETS:
        agent_name = f"{asset.upper()}_15M"
        
        try:
            # Try to get the agent from the grid
            agent = agent_grid.get_agent(agent_name)
            if agent:
                # Check agent status
                is_active = hasattr(agent, '_is_active') and agent._is_active
                has_config = hasattr(agent, 'config') and agent.config is not None
                
                results[asset] = {
                    "status": "ACTIVE" if is_active else "INACTIVE",
                    "agent_name": agent_name,
                    "is_active": is_active,
                    "has_config": has_config
                }
                
                if is_active:
                    print(f"{asset}: ✅ Agent active ({agent_name})")
                else:
                    print(f"{asset}: ⚠️ Agent inactive ({agent_name})")
            else:
                results[asset] = {"status": "NO_AGENT", "agent_name": agent_name}
                print(f"{asset}: ❌ Agent not found ({agent_name})")
        except Exception as e:
            results[asset] = {"status": "ERROR", "agent_name": agent_name, "error": str(e)}
            print(f"{asset}: ❌ Error: {e}")
    
    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    active = sum(1 for r in results.values() if r["status"] == "ACTIVE")
    inactive = sum(1 for r in results.values() if r["status"] == "INACTIVE")
    no_agent = sum(1 for r in results.values() if r["status"] == "NO_AGENT")
    error = sum(1 for r in results.values() if r["status"] == "ERROR")
    
    print(f"Active agents: {active}/5")
    print(f"Inactive agents: {inactive}/5")
    print(f"No agent found: {no_agent}/5")
    print(f"Error: {error}/5")
    
    return results


if __name__ == "__main__":
    check_agent_grid_status()
