#!/usr/bin/env python3
"""Test script to force Kalshi alerts in dev environment.

Usage:
    python test_kalshi_alerts.py --circuit-breaker
    python test_kalshi_alerts.py --latency
    python test_kalshi_alerts.py --all

This script forces alert conditions to verify Prometheus alerting pipeline:
1. Circuit Breaker OPEN alert - simulates API failures
2. High Latency alert - injects >500ms latency observations

Prerequisites:
- MERID backend running on localhost:8000
- Prometheus scraping /api/v1/kalshi/metrics
- AlertManager running with alert_rules.yml loaded
"""

import argparse
import asyncio
import sys
import time

# Add project root to path
sys.path.insert(0, 'c:/Dev/MERID')


def force_circuit_breaker_open():
    """Force circuit breaker to OPEN state by simulating failures."""
    print("🔴 Forcing Circuit Breaker OPEN...")
    
    from merid.circuit_breaker import get_circuit_breaker
    
    # Get or create a test circuit breaker
    cb = get_circuit_breaker("kalshi_api_test")
    
    # Force multiple failures to trip the breaker
    print(f"   Current state: {cb.state.value}")
    print("   Injecting 10 failures...")
    
    for i in range(10):
        cb._on_failure()
        print(f"   Failure {i+1}: count={cb._failure_count}, state={cb.state.value}")
        time.sleep(0.1)
    
    print(f"\n✅ Circuit Breaker is now: {cb.state.value}")
    print("   Alert 'Kalshi_Circuit_Breaker_Open' should fire within 30s")
    print("   Check Prometheus: http://localhost:9090/alerts")
    
    return cb


def force_high_latency():
    """Force high latency metrics to trigger p99 > 500ms alert."""
    print("🟠 Injecting high latency observations...")
    
    from monitoring.kalshi_metrics import get_kalshi_metrics_collector
    
    collector = get_kalshi_metrics_collector()
    
    # Inject multiple high latency observations (700-1000ms)
    print("   Recording 50 observations of 600-1000ms latency...")
    
    import random
    for i in range(50):
        latency_s = random.uniform(0.6, 1.0)  # 600-1000ms
        collector.api_latency.observe(latency_s, {"method": "GET", "endpoint": "/markets"})
        if (i + 1) % 10 == 0:
            print(f"   Recorded {i+1} observations...")
    
    # Record some critical latencies (>1s)
    print("   Recording 10 critical observations (>1s)...")
    for i in range(10):
        collector.api_latency.observe(1.5, {"method": "POST", "endpoint": "/orders"})
    
    print("\n✅ High latency metrics injected")
    print("   Alert 'Kalshi_API_High_Latency' should fire within 30s")
    print("   Check Prometheus: http://localhost:9090/alerts")


def check_metrics_endpoint():
    """Verify metrics endpoint returns valid Prometheus text."""
    print("🔍 Checking /api/v1/kalshi/metrics endpoint...")
    
    import requests
    
    try:
        response = requests.get("http://localhost:8000/api/v1/kalshi/metrics", timeout=5)
        response.raise_for_status()
        
        content_type = response.headers.get('content-type', '')
        print(f"   Status: {response.status_code}")
        print(f"   Content-Type: {content_type}")
        
        # Verify Prometheus format
        lines = response.text.strip().split('\n')
        print(f"   Lines: {len(lines)}")
        
        # Check for expected metrics
        metrics_found = []
        for line in lines:
            if line.startswith('kalshi_'):
                metric_name = line.split('{')[0].split(' ')[0]
                if metric_name not in metrics_found:
                    metrics_found.append(metric_name)
        
        print(f"   Kalshi metrics found: {len(metrics_found)}")
        for m in metrics_found[:5]:
            print(f"      - {m}")
        
        # Verify circuit breaker metric exists
        if any('circuit_breaker' in m for m in metrics_found):
            print("   ✅ Circuit breaker metrics present")
        
        # Verify latency histogram exists
        if any('latency' in m for m in metrics_found):
            print("   ✅ Latency metrics present")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print("   ❌ Connection failed - is MERID running on localhost:8000?")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def reset_circuit_breaker():
    """Reset circuit breaker to CLOSED state."""
    print("🔄 Resetting Circuit Breaker...")
    
    from merid.circuit_breaker import get_circuit_breaker
    
    cb = get_circuit_breaker("kalshi_api_test")
    cb.reset()
    
    print(f"   Circuit Breaker is now: {cb.state.value}")
    print("   Alert should resolve within 1-2 evaluation cycles")


def main():
    parser = argparse.ArgumentParser(
        description="Test Kalshi alerting in dev environment"
    )
    parser.add_argument(
        '--circuit-breaker', '-cb',
        action='store_true',
        help='Force circuit breaker OPEN alert'
    )
    parser.add_argument(
        '--latency', '-lat',
        action='store_true',
        help='Force high latency alert'
    )
    parser.add_argument(
        '--check', '-c',
        action='store_true',
        help='Check metrics endpoint only'
    )
    parser.add_argument(
        '--reset', '-r',
        action='store_true',
        help='Reset circuit breaker to CLOSED'
    )
    parser.add_argument(
        '--all', '-a',
        action='store_true',
        help='Run all tests (circuit breaker + latency)'
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🧪 Kalshi Alert Testing Tool")
    print("=" * 60)
    print()
    
    if not any([args.circuit_breaker, args.latency, args.check, args.reset, args.all]):
        parser.print_help()
        return
    
    # Check metrics endpoint first
    if args.check or args.all or args.circuit_breaker or args.latency:
        if not check_metrics_endpoint():
            print("\n❌ Cannot proceed - metrics endpoint not available")
            return
        print()
    
    # Run requested tests
    if args.circuit_breaker or args.all:
        force_circuit_breaker_open()
        print()
    
    if args.latency or args.all:
        force_high_latency()
        print()
    
    if args.reset:
        reset_circuit_breaker()
        print()
    
    print("=" * 60)
    print("📊 Next steps:")
    print("   1. Open Prometheus: http://localhost:9090/alerts")
    print("   2. Wait 30-60s for alert evaluation")
    print("   3. Verify alerts appear in 'Pending' then 'Firing'")
    print("   4. Check AlertManager: http://localhost:9093")
    print("=" * 60)


if __name__ == "__main__":
    main()
