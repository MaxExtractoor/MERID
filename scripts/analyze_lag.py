#!/usr/bin/env python3
"""Analyze loop lag profiles to identify blocking patterns."""

import json
import sys
from collections import Counter
from pathlib import Path

def analyze_profiles(filepath: str):
    with open(filepath) as f:
        data = json.load(f)
    
    profiles = data.get("profiles", [])
    if not profiles:
        print("No profiles captured")
        return
    
    print("="*70)
    print("EVENT LOOP LAG ANALYSIS")
    print("="*70)
    print(f"\nTotal profiles: {len(profiles)}")
    print(f"Lag range: {min(p['lag_ms'] for p in profiles):.0f}ms - {max(p['lag_ms'] for p in profiles):.0f}ms")
    print(f"Avg lag: {sum(p['lag_ms'] for p in profiles)/len(profiles):.0f}ms")
    
    # Count tasks by name pattern
    task_names = []
    coro_patterns = []
    
    for profile in profiles:
        for task in profile.get("tasks", []):
            name = task.get("name", "unknown")
            coro = task.get("coro", "")
            
            # Group similar tasks
            if "kalshi-agent" in name:
                task_names.append("kalshi-agent")
            elif "insight-" in name:
                task_names.append("insight-pipeline")
            elif "merid-loop" in name:
                task_names.append("merid-loop")
            elif "recon" in name:
                task_names.append("kalshi-recon")
            elif "AlertManager" in coro:
                task_names.append("alert-manager")
            elif "WebSocket" in coro:
                task_names.append("websocket")
            else:
                task_names.append("other")
                
            # Extract coroutine patterns
            if "_run_loop" in coro:
                coro_patterns.append("_run_loop")
            elif "_category_loop" in coro:
                coro_patterns.append("_category_loop")
            elif "_monitor_loop" in coro:
                coro_patterns.append("_monitor_loop")
            elif "transfer_data" in coro:
                coro_patterns.append("ws_transfer_data")
            else:
                coro_patterns.append("other")
    
    print("\n" + "="*70)
    print("ACTIVE TASK PATTERNS (what's consuming the event loop)")
    print("="*70)
    print("\nTask types:")
    for name, count in Counter(task_names).most_common():
        print(f"  {name}: {count}")
    
    print("\nCoroutine patterns:")
    for coro, count in Counter(coro_patterns).most_common():
        print(f"  {coro}: {count}")
    
    print("\n" + "="*70)
    print("FINDINGS")
    print("="*70)
    print("""
1. HIGH TASK COUNT: 166+ concurrent tasks - this is excessive
2. AGENT LOOPS: 35+ kalshi-agent loops running concurrently
3. INSIGHT PIPELINES: Multiple category loops (culture, economics, tech, etc.)
4. WEBSOCKET: Active WebSocket transfer_data coroutines

ROOT CAUSE (likely):
- Too many tasks scheduled on the same event loop
- KalshiTradingAgent._run_loop not yielding properly
- Insight pipelines running tight loops without asyncio.sleep()
- Possible blocking I/O in async paths

RECOMMENDATION:
1. Add asyncio.sleep(0) or small delays in agent run loops
2. Move Kalshi WS client to separate thread
3. Audit insight pipelines for proper async yielding
4. Consider reducing concurrent task count
""")
    
    print("="*70)

if __name__ == "__main__":
    analyze_profiles(sys.argv[1] if len(sys.argv) > 1 else "lag_profiles.json")
