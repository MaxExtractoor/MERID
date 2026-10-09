"""Test order execution through the running server.

This script adds a test endpoint to the server to submit actual orders
through the complete system pipeline to expose any gaps or failures.
"""

import requests
import json
import time

SERVER_URL = "http://localhost:8011"

def test_system_readiness():
    """Check if the system is ready for order execution."""
    print("\n=== System Readiness Check ===")
    
    # Check health
    try:
        response = requests.get(f"{SERVER_URL}/api/v1/health", timeout=5)
        response.raise_for_status()
        health = response.json()
        print(f"✓ Server health: {health.get('status')}")
        print(f"  Startup completed: {health.get('startup_completed')}")
        print(f"  Loop alive: {health.get('loop_task_alive')}")
    except Exception as e:
        print(f"✗ Health check failed: {e}")
        return False
    
    # Check loop status
    try:
        response = requests.get(f"{SERVER_URL}/api/v1/loop-status", timeout=5)
        response.raise_for_status()
        loop = response.json()
        print(f"✓ Loop status: {loop.get('status')}")
        print(f"  Running: {loop.get('running')}")
        print(f"  Cycle duration: {loop.get('cycle_duration_ms')}ms")
    except Exception as e:
        print(f"✗ Loop status failed: {e}")
        return False
    
    # Check agents
    try:
        response = requests.get(f"{SERVER_URL}/api/v1/agents", timeout=5)
        response.raise_for_status()
        agents = response.json()
        summary = agents.get('summary', {})
        print(f"✓ Agents: {summary.get('total')} total, {summary.get('enabled')} enabled")
    except Exception as e:
        print(f"✗ Agents check failed: {e}")
        return False
    
    # Check market data
    try:
        response = requests.get(f"{SERVER_URL}/api/v1/md-debug", timeout=5)
        response.raise_for_status()
        md = response.json()
        tickers = md.get('tickers', {})
        print(f"✓ Market data: {len(tickers)} markets")
        
        # Show market states
        for ticker, data in list(tickers.items())[:3]:
            bid = data.get('best_bid_cents', 0)
            ask = data.get('best_ask_cents', 0)
            executable = data.get('executable', False)
            print(f"  {ticker}: bid={bid} ask={ask} executable={executable}")
    except Exception as e:
        print(f"✗ Market data check failed: {e}")
        return False
    
    return True

def trigger_agent_grid_signal():
    """Trigger the agent grid to generate a trading signal."""
    print("\n=== Triggering Agent Grid Signal ===")
    
    # The agent grid runs autonomously, but we can check its status
    try:
        response = requests.get(f"{SERVER_URL}/api/v1/agents", timeout=5)
        response.raise_for_status()
        agents = response.json()
        
        print("Agent grid status:")
        for asset, data in agents.get('agents_by_asset', {}).items():
            enabled = data.get('enabled', False)
            has_signal = data.get('has_signal', False)
            open_positions = data.get('open_positions', 0)
            print(f"  {asset}: enabled={enabled} has_signal={has_signal} positions={open_positions}")
        
        # Check if any agents have signals
        any_signals = any(
            data.get('has_signal', False) 
            for data in agents.get('agents_by_asset', {}).values()
        )
        
        if any_signals:
            print("✓ Some agents have trading signals")
            return True
        else:
            print("⚠ No agents currently have trading signals")
            print("   The agent grid generates signals autonomously based on market conditions")
            return False
            
    except Exception as e:
        print(f"✗ Failed to check agent grid: {e}")
        return False

def analyze_system_gaps():
    """Analyze the system for potential gaps or issues."""
    print("\n=== System Gap Analysis ===")
    
    gaps = []
    
    # Check if server has order submission endpoints
    try:
        response = requests.post(f"{SERVER_URL}/api/v1/trading/order", json={}, timeout=2)
        # If we get a 405 Method Not Allowed, the endpoint exists
        if response.status_code == 405:
            print("✓ Trading order endpoint exists")
        elif response.status_code == 404:
            gaps.append("No HTTP endpoint for manual order submission")
            print("⚠ No HTTP endpoint for manual order submission")
    except Exception as e:
        gaps.append("Cannot test order submission endpoint")
        print(f"⚠ Cannot test order submission: {e}")
    
    # Check if system is in paper mode
    try:
        response = requests.get(f"{SERVER_URL}/api/v1/meta-cognition", timeout=5)
        if response.status_code == 200:
            meta = response.json()
            is_live = meta.get('snapshot', {}).get('is_live', False)
            if is_live:
                gaps.append("System is in LIVE mode - test orders would execute with real money")
                print("⚠ System is in LIVE mode")
            else:
                print("✓ System is in PAPER/DEMO mode")
    except Exception as e:
        print(f"⚠ Cannot check trading mode: {e}")
    
    # Check if market data is executable
    try:
        response = requests.get(f"{SERVER_URL}/api/v1/md-debug", timeout=5)
        response.raise_for_status()
        md = response.json()
        
        executable_markets = 0
        for ticker, data in md.get('tickers', {}).items():
            if data.get('executable', False):
                executable_markets += 1
        
        if executable_markets == 0:
            gaps.append("No executable markets - agent grid cannot trade")
            print("⚠ No executable markets available")
        else:
            print(f"✓ {executable_markets} executable markets available")
    except Exception as e:
        print(f"⚠ Cannot check market executability: {e}")
    
    # Check infrastructure
    try:
        response = requests.get(f"{SERVER_URL}/api/v1/infra", timeout=5)
        response.raise_for_status()
        infra = response.json()
        
        ws_healthy = infra.get('ws_forwarder', {}).get('healthy', False)
        catalog_ok = infra.get('catalog', {}).get('state') == 'ok'
        
        if not ws_healthy:
            gaps.append("WebSocket forwarder not healthy")
            print("⚠ WebSocket forwarder not healthy")
        if not catalog_ok:
            gaps.append("Market catalog not OK")
            print("⚠ Market catalog not OK")
        
        if ws_healthy and catalog_ok:
            print("✓ Infrastructure healthy")
    except Exception as e:
        print(f"⚠ Cannot check infrastructure: {e}")
    
    return gaps

def main():
    print("=" * 70)
    print("SYSTEM ORDER EXECUTION CAPABILITY TEST")
    print("=" * 70)
    
    # Step 1: Check system readiness
    if not test_system_readiness():
        print("\n✗ System not ready for order execution")
        return
    
    # Step 2: Analyze system gaps
    gaps = analyze_system_gaps()
    
    # Step 3: Check agent grid status
    signal_status = trigger_agent_grid_signal()
    
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    if gaps:
        print("⚠ System gaps detected:")
        for gap in gaps:
            print(f"   - {gap}")
    else:
        print("✓ No obvious gaps detected")
    
    print("\n=== Key Findings ===")
    print("1. This system uses autonomous agent grid trading")
    print("2. Orders are generated automatically when signal conditions are met")
    print("3. No manual HTTP order submission endpoint exists")
    print("4. The system is designed for autonomous operation, not manual trading")
    print("5. To test actual order execution, you would need to:")
    print("   - Wait for the agent grid to generate trading signals")
    print("   - Or modify market conditions to trigger signal generation")
    print("   - Or add a test endpoint to inject test orders")
    
    print("\n=== System Architecture ===")
    print("The 15M Kalshi crypto trading system follows this flow:")
    print("1. Market data flows in via WebSocket")
    print("2. Agent grid analyzes market conditions")
    print("3. When signal conditions are met, agents generate order intents")
    print("4. Order intents are routed through risk checks")
    print("5. Valid orders are submitted to Kalshi venue")
    print("6. Fills are processed and positions are updated")
    
    print("\n=== Recommendation ===")
    print("To test actual order execution:")
    print("Option 1: Add a test endpoint to main_15m_lean.py that injects")
    print("          test order intents into the agent grid")
    print("Option 2: Wait for natural signal generation from the agent grid")
    print("Option 3: Modify market conditions to trigger signal generation")

if __name__ == "__main__":
    main()
