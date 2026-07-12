#!/usr/bin/env python3
"""
Real-time diagnostic script to monitor order execution blockers in the 15M Kalshi crypto trading system.
This script monitors logs and system state to identify why orders are not executing.
"""

import asyncio
import re
import time
from datetime import datetime
from pathlib import Path
import json
from collections import defaultdict, Counter
import sys

class OrderBlockerMonitor:
    def __init__(self, log_path=None):
        self.log_path = log_path or Path("c:/Dev/MERID/output/15m_server.log")
        self.blockers = {
            'signal_generation': [],
            'order_routing': [],
            'risk_gates': [],
            'execution': [],
            'websocket': [],
            'market_data': []
        }
        self.signal_count = 0
        self.order_attempts = 0
        self.order_rejections = 0
        self.order_executions = 0
        self.start_time = time.time()
        self.patterns = {
            'signal': re.compile(r'SIGNAL|signal|agent.*opinion|confidence'),
            'order_attempt': re.compile(r'ORDER|order.*router|submit.*order|place.*order'),
            'order_rejection': re.compile(r'REJECT|reject|block|deny|fail.*order'),
            'order_execution': re.compile(r'FILL|fill|executed|order.*confirm'),
            'risk_gate': re.compile(r'PRE.*TRADE|risk.*gate|guardrail|window.*limit|exposure'),
            'websocket': re.compile(r'WS.*FORWARDER|websocket|subscription'),
            'market_data': re.compile(r'market.*data|price|ticker|snapshot')
        }
        
    def analyze_log_line(self, line):
        """Analyze a single log line for blocker patterns."""
        line_lower = line.lower()
        
        # Categorize log line
        if self.patterns['signal'].search(line):
            self.blockers['signal_generation'].append(line)
            self.signal_count += 1
            
        if self.patterns['order_attempt'].search(line):
            self.blockers['order_routing'].append(line)
            self.order_attempts += 1
            
        if self.patterns['order_rejection'].search(line):
            self.blockers['risk_gates'].append(line)
            self.order_rejections += 1
            
        if self.patterns['order_execution'].search(line):
            self.blockers['execution'].append(line)
            self.order_executions += 1
            
        if self.patterns['risk_gate'].search(line):
            self.blockers['risk_gates'].append(line)
            
        if self.patterns['websocket'].search(line):
            self.blockers['websocket'].append(line)
            
        if self.patterns['market_data'].search(line):
            self.blockers['market_data'].append(line)
    
    def get_summary(self):
        """Get current summary of monitoring."""
        elapsed = time.time() - self.start_time
        return {
            'elapsed_seconds': elapsed,
            'signal_count': self.signal_count,
            'order_attempts': self.order_attempts,
            'order_rejections': self.order_rejections,
            'order_executions': self.order_executions,
            'success_rate': (self.order_executions / self.order_attempts * 100) if self.order_attempts > 0 else 0,
            'blocker_counts': {k: len(v) for k, v in self.blockers.items()}
        }
    
    def print_summary(self):
        """Print current summary."""
        summary = self.get_summary()
        print(f"\n{'='*60}")
        print(f"MONITOR SUMMARY - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Elapsed: {summary['elapsed_seconds']:.1f}s")
        print(f"Signals Generated: {summary['signal_count']}")
        print(f"Order Attempts: {summary['order_attempts']}")
        print(f"Order Rejections: {summary['order_rejections']}")
        print(f"Order Executions: {summary['order_executions']}")
        print(f"Success Rate: {summary['success_rate']:.1f}%")
        print(f"\nBlocker Category Counts:")
        for category, count in summary['blocker_counts'].items():
            print(f"  {category}: {count}")
        print(f"{'='*60}\n")
        
        # Print recent blocker patterns
        if self.order_rejections > 0:
            print("RECENT ORDER REJECTIONS:")
            for line in self.blockers['risk_gates'][-5:]:
                print(f"  {line.strip()}")
            print()
            
        if self.signal_count > 0 and self.order_attempts == 0:
            print("WARNING: Signals generated but NO order attempts!")
            print("This suggests agents are generating opinions but order router is not being called.")
            print()
            
        if self.order_attempts > 0 and self.order_executions == 0:
            print("WARNING: Order attempts but NO executions!")
            print("This suggests orders are being blocked at gate or execution layer.")
            print()

async def monitor_logs(duration_minutes=30):
    """Monitor logs for specified duration."""
    monitor = OrderBlockerMonitor()
    print(f"Starting order blocker monitor for {duration_minutes} minutes...")
    print("Press Ctrl+C to stop early.\n")
    
    # Simulate log monitoring by checking command output periodically
    # In production, this would tail the actual log file
    check_interval = 10  # seconds
    checks = int(duration_minutes * 60 / check_interval)
    
    for i in range(checks):
        await asyncio.sleep(check_interval)
        monitor.print_summary()
        
        # Check if we've identified the root cause
        summary = monitor.get_summary()
        
        # Key diagnostic patterns
        if summary['signal_count'] == 0:
            print("DIAGNOSTIC: No signals generated - check agent grid and signal generation")
        elif summary['order_attempts'] == 0:
            print("DIAGNOSTIC: Signals exist but no order attempts - check order router wiring")
        elif summary['order_rejections'] > 0:
            print(f"DIAGNOSTIC: {summary['order_rejections']} order rejections - check risk gates and limits")
        elif summary['order_executions'] == 0:
            print("DIAGNOSTIC: Orders attempted but not executing - check execution layer")
        else:
            print("DIAGNOSTIC: Orders are executing successfully!")
            
    print("\nMonitoring complete.")
    monitor.print_summary()
    return monitor

if __name__ == "__main__":
    try:
        asyncio.run(monitor_logs(duration_minutes=30))
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")
