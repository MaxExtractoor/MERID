#!/usr/bin/env python3
"""
Check if agents have enough historical data for signal generation.
This script monitors the warmup period and identifies when agents can start generating signals.
"""

import asyncio
import re
from datetime import datetime
from pathlib import Path

class SignalWarmupMonitor:
    def __init__(self):
        self.agent_status = {
            'BTC_15M': {'data_points': 0, 'signals': 0, 'warmup_complete': False},
            'ETH_15M': {'data_points': 0, 'signals': 0, 'warmup_complete': False},
            'SOL_15M': {'data_points': 0, 'signals': 0, 'warmup_complete': False},
            'XRP_15M': {'data_points': 0, 'signals': 0, 'warmup_complete': False},
            'DOGE_15M': {'data_points': 0, 'signals': 0, 'warmup_complete': False},
        }
        self.required_data_points = 35  # MACD requirement
        self.patterns = {
            'data_points': re.compile(r'insufficient price history.*(\d+)\s*<\s*(\d+)'),
            'no_signal': re.compile(r'NO-SIGNAL.*asset=(\w+)'),
            'signal_generated': re.compile(r'SIGNAL|candidate|opinion'),
            'fvg_update': re.compile(r'FVG-UPDATE.*asset=(\w+)'),
        }
        
    def parse_log_line(self, line):
        """Parse a log line for warmup status."""
        # Check for insufficient data warning
        data_match = self.patterns['data_points'].search(line)
        if data_match:
            current_points = int(data_match.group(1))
            required_points = int(data_match.group(2))
            # Extract asset from line
            for asset in self.agent_status.keys():
                if asset.split('_')[0] in line:
                    self.agent_status[asset]['data_points'] = current_points
                    self.agent_status[asset]['warmup_complete'] = current_points >= required_points
                    break
                    
        # Check for no-signal messages
        no_signal_match = self.patterns['no_signal'].search(line)
        if no_signal_match:
            asset = no_signal_match.group(1)
            asset_key = f"{asset}_15M"
            if asset_key in self.agent_status:
                self.agent_status[asset_key]['signals'] += 1
                
        # Check for FVG updates (indicates data is flowing)
        fvg_match = self.patterns['fvg_update'].search(line)
        if fvg_match:
            asset = fvg_match.group(1)
            asset_key = f"{asset}_15M"
            if asset_key in self.agent_status:
                # Increment data points when FVG updates
                self.agent_status[asset_key]['data_points'] += 1
                
    def get_status(self):
        """Get current warmup status."""
        complete_count = sum(1 for s in self.agent_status.values() if s['warmup_complete'])
        total_agents = len(self.agent_status)
        return {
            'agents_ready': complete_count,
            'total_agents': total_agents,
            'ready_percentage': (complete_count / total_agents * 100) if total_agents > 0 else 0,
            'agent_details': self.agent_status
        }
        
    def print_status(self):
        """Print current warmup status."""
        status = self.get_status()
        print(f"\n{'='*60}")
        print(f"SIGNAL WARMUP STATUS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Agents Ready: {status['agents_ready']}/{status['total_agents']} ({status['ready_percentage']:.1f}%)")
        print(f"Required Data Points: {self.required_data_points}")
        print(f"\nAgent Details:")
        for asset, info in status['agent_details'].items():
            status_str = "READY" if info['warmup_complete'] else "WARMING"
            print(f"  {asset}: {info['data_points']}/{self.required_data_points} points [{status_str}] (no-signal count: {info['signals']})")
        print(f"{'='*60}\n")
        
        if status['ready_percentage'] == 100:
            print("ALL AGENTS READY - Signal generation should begin")
        elif status['ready_percentage'] > 0:
            print(f"PARTIAL WARMUP - {status['agents_ready']} agents ready, {status['total_agents'] - status['agents_ready']} still warming")
        else:
            print("NO AGENTS READY - Still in warmup phase")

def main():
    """Monitor warmup status."""
    monitor = SignalWarmupMonitor()
    print("Monitoring agent warmup status...")
    print("Agents need 35 data points for MACD calculations before generating signals.")
    print()
    
    # In production, this would tail the log file
    # For now, print instructions for manual monitoring
    monitor.print_status()
    print("\nTo monitor in real-time, watch for these log patterns:")
    print("  - 'insufficient price history' - indicates warmup in progress")
    print("  - 'FVG-UPDATE' - indicates data points being accumulated")
    print("  - 'NO-SIGNAL' - indicates agent ran but found no trading opportunity")
    print("  - 'SIGNAL' or 'candidate' - indicates signal generation started")
    print()
    print("Expected warmup time: ~35-40 minutes of 1-minute data collection")

if __name__ == "__main__":
    main()
