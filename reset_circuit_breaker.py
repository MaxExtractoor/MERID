#!/usr/bin/env python3
"""
Reset Kalshi circuit breaker to restore API connectivity.
Run this when 'Circuit kalshi_live is OPEN' errors appear.
"""

import sys
sys.path.insert(0, r'c:\Dev\MERID')

from hardening.circuit_breaker import get_circuit_registry, get_circuit

def reset_kalshi_circuit():
    """Reset the kalshi_live circuit breaker."""
    registry = get_circuit_registry()
    
    # Reset all circuits
    registry.reset_all()
    
    # Also specifically reset kalshi_live if it exists
    kalshi_circuit = registry.get("kalshi_live")
    if kalshi_circuit:
        kalshi_circuit.reset()
        print(f"✅ Circuit 'kalshi_live' manually reset to CLOSED")
    else:
        print(f"ℹ️ Circuit 'kalshi_live' not found in registry (will be created fresh on next API call)")
    
    # Show current circuit states
    stats = registry.get_all_stats()
    if stats:
        print("\n📊 Current Circuit States:")
        for name, circuit_stats in stats.items():
            print(f"  - {name}: state={circuit_stats['state']}, failures={circuit_stats['failure_count']}")
    else:
        print("\n📊 No circuits registered yet")
    
    print("\n✅ Circuit breaker reset complete. Kalshi API calls should now work.")
    print("   Restart the backend or wait for the circuit to cool down naturally.")

if __name__ == "__main__":
    reset_kalshi_circuit()
