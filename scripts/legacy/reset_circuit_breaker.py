#!/usr/bin/env python3
"""
Reset Kalshi circuit breaker to restore API connectivity.
Run this when 'Circuit kalshi_live is OPEN' errors appear.
"""

import sys
sys.path.insert(0, r'c:\Dev\MERID')

from merid.circuit_breaker import list_circuit_breakers, reset_circuit_breaker

def reset_kalshi_circuit():
    """Reset the kalshi_live circuit breaker."""
    # Reset kalshi_live specifically
    success = reset_circuit_breaker("kalshi_live")
    if success:
        print(f"✅ Circuit 'kalshi_live' manually reset to CLOSED")
    else:
        print(f"ℹ️ Circuit 'kalshi_live' not found in registry (will be created fresh on next API call)")
    
    # Show current circuit states
    stats = list_circuit_breakers()
    if stats:
        print("\n📊 Current Circuit States:")
        for circuit_stats in stats:
            print(f"  - {circuit_stats.name}: state={circuit_stats.state.value}, failures={circuit_stats.failure_count}")
    else:
        print("\n📊 No circuits registered yet")
    
    print("\n✅ Circuit breaker reset complete. Kalshi API calls should now work.")
    print("   Restart the backend or wait for the circuit to cool down naturally.")

if __name__ == "__main__":
    reset_kalshi_circuit()
