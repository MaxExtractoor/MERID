#!/usr/bin/env python3
"""Promote 15m crypto agents to LIVE mode in deployment_state.json"""

import json
from pathlib import Path
from datetime import datetime, timezone

# Path to deployment state
DEPLOYMENT_STATE_PATH = Path(__file__).parent / "data" / "deployment_state.json"

# 15m crypto agent patterns to promote
AGENT_PATTERNS = [
    "kalshi-btc_15m_",
    "kalshi-eth_15m_",
    "kalshi-sol_15m_",
    "kalshi-xrp_15m_",
    "kalshi-doge_15m_",
]

def promote_15m_agents():
    """Promote all 15m crypto agents to LIVE mode"""
    # Read deployment state
    with open(DEPLOYMENT_STATE_PATH, 'r') as f:
        deployment_state = json.load(f)
    
    promoted_count = 0
    already_live_count = 0
    now = datetime.now(timezone.utc).isoformat()
    
    # Update each 15m agent
    for agent_name, agent_data in deployment_state.get("agents", {}).items():
        # Check if this is a 15m crypto agent
        is_15m_agent = any(agent_name.startswith(pattern) for pattern in AGENT_PATTERNS)
        
        if is_15m_agent:
            if agent_data.get("mode") == "LIVE":
                already_live_count += 1
                print(f"  [SKIP] {agent_name} already in LIVE mode")
            else:
                # Promote to LIVE
                agent_data["mode"] = "LIVE"
                agent_data["promoted_at"] = now
                promoted_count += 1
                print(f"  [PROMOTE] {agent_name}: {agent_data.get('mode')} -> LIVE")
    
    # Write back
    with open(DEPLOYMENT_STATE_PATH, 'w') as f:
        json.dump(deployment_state, f, indent=2)
    
    print(f"\nSummary:")
    print(f"  Promoted: {promoted_count} agents to LIVE mode")
    print(f"  Already LIVE: {already_live_count} agents")
    print(f"  Total agents: {len(deployment_state.get('agents', {}))}")

if __name__ == "__main__":
    print("Promoting 15m crypto agents to LIVE mode...")
    promote_15m_agents()
    print("\nDone!")
