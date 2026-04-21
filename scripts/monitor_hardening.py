#!/usr/bin/env python3
"""
Quick validation script for event-loop hardening changes.
Run this against live logs to verify Phase 2-3 behavior.

Usage:
    tail -f /var/log/merid/server.log | python scripts/monitor_hardening.py
    # or
    python scripts/monitor_hardening.py < /var/log/merid/server.log.2026-04-18
"""

import sys
import re
from collections import defaultdict
from datetime import datetime

# Patterns to track
PATTERNS = {
    'profiling': re.compile(r'\[PROF\]\s+(\w+)\s+action=(\w+)\s+duration_ms=([\d.]+)'),
    'circuit_breaker': re.compile(r'\[CIRCUIT-BREAKER\]\s+(TRIPPED|Resetting|Approaching threshold)'),
    'budget_exceeded': re.compile(r'\[BUDGET\]\s+(\w+)_budget_exceeded'),
    'budget_scope': re.compile(r'\[BUDGET\]\s+(\w+):\s+reduced scope'),
    'lag_skip': re.compile(r'\[LAG-SKIP\]\s+action=(\w+)'),
    'og_timeout': re.compile(r'order_groups:start_timeout'),
    'event_loop_lag': re.compile(r'Event-loop lag:\s+([\d.]+)ms'),
    'ws_connect': re.compile(r'KalshiWebSocketBridge started|WS bridge connect attempt'),
    'slow_action': re.compile(r'Slow action\s+(\w+)\s+.*duration=([\d.]+)ms'),
}

class HardeningMonitor:
    def __init__(self):
        self.durations = defaultdict(list)  # action -> [durations]
        self.lag_readings = []
        self.circuit_events = []
        self.budget_exceeded = defaultdict(int)
        self.budget_scope_reductions = defaultdict(int)
        self.lag_skips = defaultdict(int)
        self.og_timeouts = 0
        self.ws_connects = 0
        self.slow_actions = defaultdict(list)
        self.start_time = datetime.now()
        
    def process_line(self, line: str):
        # Profiling events
        if match := PATTERNS['profiling'].search(line):
            action, _, duration = match.groups()
            self.durations[action].append(float(duration))
            
        # Circuit breaker
        if match := PATTERNS['circuit_breaker'].search(line):
            event = match.group(1)
            self.circuit_events.append((datetime.now(), event))
            
        # Budget exceeded
        if match := PATTERNS['budget_exceeded'].search(line):
            action = match.group(1)
            self.budget_exceeded[action] += 1
            
        # Scope reductions
        if match := PATTERNS['budget_scope'].search(line):
            action = match.group(1)
            self.budget_scope_reductions[action] += 1
            
        # Lag skips
        if match := PATTERNS['lag_skip'].search(line):
            action = match.group(1)
            self.lag_skips[action] += 1
            
        # Order groups timeout
        if PATTERNS['og_timeout'].search(line):
            self.og_timeouts += 1
            
        # Event loop lag
        if match := PATTERNS['event_loop_lag'].search(line):
            lag = float(match.group(1))
            self.lag_readings.append(lag)
            
        # WS connects
        if PATTERNS['ws_connect'].search(line):
            self.ws_connects += 1
            
        # Slow actions
        if match := PATTERNS['slow_action'].search(line):
            action, duration = match.groups()
            self.slow_actions[action].append(float(duration))
    
    def _percentile(self, values: list, p: float) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = int(len(sorted_vals) * p / 100)
        return sorted_vals[idx]
    
    def report(self):
        elapsed = (datetime.now() - self.start_time).total_seconds()
        
        print(f"\n{'='*60}")
        print(f"HARDENING VALIDATION REPORT — {elapsed:.0f}s window")
        print(f"{'='*60}\n")
        
        # Event loop lag
        if self.lag_readings:
            print("EVENT LOOP LAG:")
            print(f"  Readings: {len(self.lag_readings)}")
            print(f"  p50: {self._percentile(self.lag_readings, 50):.1f}ms")
            print(f"  p95: {self._percentile(self.lag_readings, 95):.1f}ms")
            print(f"  p99: {self._percentile(self.lag_readings, 99):.1f}ms")
            print(f"  max: {max(self.lag_readings):.1f}ms")
            status = "✅ PASS" if self._percentile(self.lag_readings, 95) < 100 else "⚠️  WARN" if self._percentile(self.lag_readings, 95) < 250 else "❌ FAIL"
            print(f"  Status: {status} (target p95 < 100ms)")
        
        # Action durations
        print("\nPIPELINE ACTION DURATIONS:")
        for action in ['liquidity', 'arb_scan', 'order_groups']:
            if action in self.durations:
                times = self.durations[action]
                p95 = self._percentile(times, 95)
                budget = 1000 if action != 'arb_scan' else 2000
                status = "✅" if p95 < budget else "⚠️ " if p95 < budget * 1.5 else "❌"
                print(f"  {action}: n={len(times)}, p95={p95:.1f}ms {status}")
        
        # Budget enforcement
        print("\nBUDGET ENFORCEMENT:")
        if self.budget_exceeded:
            for action, count in self.budget_exceeded.items():
                status = "⚠️ " if count < 5 else "❌ CRITICAL"
                print(f"  {action}_budget_exceeded: {count} {status}")
        else:
            print("  No budget exceeded events ✅")
            
        if self.budget_scope_reductions:
            print(f"\n  Scope reductions (lag-based):")
            for action, count in self.budget_scope_reductions.items():
                print(f"    {action}: {count}")
        
        if self.og_timeouts:
            print(f"\n  order_groups:start_timeout: {self.og_timeouts} ❌")
        else:
            print(f"\n  order_groups:start_timeout: 0 ✅")
        
        # Circuit breaker
        print("\nCIRCUIT BREAKER:")
        if self.circuit_events:
            trips = sum(1 for _, e in self.circuit_events if e == 'TRIPPED')
            resets = sum(1 for _, e in self.circuit_events if e == 'Resetting')
            approaching = sum(1 for _, e in self.circuit_events if 'Approaching' in e)
            print(f"  TRIPPED: {trips}, Resetting: {resets}, Approaching: {approaching}")
            status = "✅" if trips == 0 else "⚠️ " if trips < 3 else "❌"
            print(f"  Status: {status}")
        else:
            print("  No circuit breaker events ✅")
        
        # Lag-based skips
        if self.lag_skips:
            print("\nLAG-BASED SKIPS:")
            for action, count in self.lag_skips.items():
                print(f"  {action}: {count}")
        
        # WebSocket activity
        print(f"\nWEBSOCKET:")
        print(f"  Connect attempts: {self.ws_connects}")
        
        print(f"\n{'='*60}\n")


def main():
    monitor = HardeningMonitor()
    
    try:
        for line in sys.stdin:
            monitor.process_line(line)
            
        # Final report
        monitor.report()
        
    except KeyboardInterrupt:
        monitor.report()


if __name__ == '__main__':
    main()
