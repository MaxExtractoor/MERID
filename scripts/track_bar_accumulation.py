#!/usr/bin/env python3
"""
Track bar count and data accumulation for 15m Kalshi crypto trading system.

This script monitors the server logs for MOMENTUM-FVG-WARMUP messages and tracks:
- Bar count for each asset (BTC, ETH, SOL, XRP, DOGE)
- Data accumulation metrics
- Timestamps when bars increase
- Warmup status (warming up vs fully warmed)
- Time to reach 20-bar threshold

Usage:
    python scripts/track_bar_accumulation.py [--log-file PATH] [--follow]

Options:
    --log-file PATH    Path to the log file (default: auto-detect latest)
    --follow           Continuously monitor the log file (like tail -f)
"""

import re
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import time
import sys


class BarAccumulationTracker:
    """Track bar count and data accumulation for all assets."""
    
    def __init__(self):
        self.assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
        self.bar_history = defaultdict(list)  # asset -> list of (timestamp, bar_count)
        self.warmup_complete = defaultdict(bool)  # asset -> bool
        self.first_seen = defaultdict(lambda: None)  # asset -> first timestamp
        self.last_seen = defaultdict(lambda: None)  # asset -> last timestamp
        self.min_bars_required = 20
        
    def parse_log_line(self, line):
        """Parse a log line for MOMENTUM-FVG-WARMUP messages."""
        # Pattern: [MOMENTUM-FVG-WARMUP] asset=ASSET bars_available=N (requires 20) - warming up
        pattern = r'\[MOMENTUM-FVG-WARMUP\] asset=(\w+) bars_available=(\d+) \(requires (\d+)\)'
        match = re.search(pattern, line)
        
        if match:
            asset = match.group(1)
            bar_count = int(match.group(2))
            required = int(match.group(3))
            
            # Extract timestamp from log line
            timestamp_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'
            timestamp_match = re.search(timestamp_pattern, line)
            timestamp = timestamp_match.group(1) if timestamp_match else None
            
            return asset, bar_count, required, timestamp
        
        # Also check for INDICATOR-STACK messages (fully warmed)
        pattern2 = r'\[MOMENTUM-FVG-INDICATOR-STACK\] asset=(\w+) bars_available=(\d+)'
        match2 = re.search(pattern2, line)
        
        if match2:
            asset = match2.group(1)
            bar_count = int(match2.group(2))
            
            # Extract timestamp
            timestamp_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'
            timestamp_match = re.search(timestamp_pattern, line)
            timestamp = timestamp_match.group(1) if timestamp_match else None
            
            return asset, bar_count, self.min_bars_required, timestamp
        
        return None, None, None, None
    
    def update(self, asset, bar_count, required, timestamp):
        """Update tracking data for an asset."""
        if asset not in self.assets:
            return
        
        # Record first and last seen
        if self.first_seen[asset] is None:
            self.first_seen[asset] = timestamp
        self.last_seen[asset] = timestamp
        
        # Add to history if bar count changed
        if not self.bar_history[asset] or self.bar_history[asset][-1][1] != bar_count:
            self.bar_history[asset].append((timestamp, bar_count))
        
        # Check if warmup complete
        if bar_count >= required:
            self.warmup_complete[asset] = True
    
    def get_summary(self):
        """Get a summary of current state."""
        summary = []
        summary.append("=" * 80)
        summary.append("BAR ACCUMULATION TRACKING SUMMARY")
        summary.append("=" * 80)
        summary.append(f"Minimum bars required: {self.min_bars_required}")
        summary.append(f"Tracking assets: {', '.join(self.assets)}")
        summary.append("")
        
        for asset in self.assets:
            summary.append(f"\n{asset}:")
            summary.append(f"  First seen: {self.first_seen[asset]}")
            summary.append(f"  Last seen: {self.last_seen[asset]}")
            
            if self.bar_history[asset]:
                current_bars = self.bar_history[asset][-1][1]
                summary.append(f"  Current bars: {current_bars}")
                summary.append(f"  Warmup complete: {self.warmup_complete[asset]}")
                
                if current_bars < self.min_bars_required:
                    remaining = self.min_bars_required - current_bars
                    summary.append(f"  Bars needed: {remaining}")
                
                # Show history
                summary.append(f"  Bar history:")
                for ts, count in self.bar_history[asset]:
                    status = "✓" if count >= self.min_bars_required else "→"
                    summary.append(f"    {status} {ts}: {count} bars")
            else:
                summary.append(f"  No data yet")
        
        summary.append("")
        summary.append("=" * 80)
        
        # Overall status
        warmed_count = sum(1 for asset in self.assets if self.warmup_complete[asset])
        summary.append(f"Overall: {warmed_count}/{len(self.assets)} assets fully warmed")
        summary.append("=" * 80)
        
        return "\n".join(summary)
    
    def get_detailed_metrics(self):
        """Get detailed metrics for analysis."""
        metrics = {}
        
        for asset in self.assets:
            if self.bar_history[asset]:
                current_bars = self.bar_history[asset][-1][1]
                metrics[asset] = {
                    'current_bars': current_bars,
                    'warmup_complete': self.warmup_complete[asset],
                    'first_seen': self.first_seen[asset],
                    'last_seen': self.last_seen[asset],
                    'bar_history': self.bar_history[asset],
                    'bars_needed': max(0, self.min_bars_required - current_bars),
                    'progress_pct': min(100, (current_bars / self.min_bars_required) * 100)
                }
            else:
                metrics[asset] = {
                    'current_bars': 0,
                    'warmup_complete': False,
                    'first_seen': None,
                    'last_seen': None,
                    'bar_history': [],
                    'bars_needed': self.min_bars_required,
                    'progress_pct': 0
                }
        
        return metrics


def find_latest_log_file():
    """Find the latest log file in the output directory."""
    output_dir = Path("c:/Dev/MERID/output")
    
    if not output_dir.exists():
        return None
    
    # Look for log files
    log_files = list(output_dir.glob("*.log"))
    
    if not log_files:
        return None
    
    # Sort by modification time
    log_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    return log_files[0]


def parse_log_file(log_file_path, tracker):
    """Parse a log file and update the tracker."""
    with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            asset, bar_count, required, timestamp = tracker.parse_log_line(line)
            if asset:
                tracker.update(asset, bar_count, required, timestamp)


def follow_log_file(log_file_path, tracker):
    """Follow a log file like tail -f."""
    with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
        # Move to end of file
        f.seek(0, 2)
        
        print(f"Following log file: {log_file_path}")
        print("Press Ctrl+C to stop...\n")
        
        try:
            while True:
                line = f.readline()
                if line:
                    asset, bar_count, required, timestamp = tracker.parse_log_line(line)
                    if asset:
                        tracker.update(asset, bar_count, required, timestamp)
                        print(f"[{timestamp}] {asset}: {bar_count} bars (required: {required})")
                else:
                    time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n\nStopped following log file.")


def main():
    parser = argparse.ArgumentParser(description='Track bar count and data accumulation')
    parser.add_argument('--log-file', help='Path to log file (default: auto-detect latest)')
    parser.add_argument('--follow', action='store_true', help='Continuously monitor log file')
    parser.add_argument('--output', help='Output file for detailed metrics (JSON)')
    
    args = parser.parse_args()
    
    # Determine log file
    if args.log_file:
        log_file = Path(args.log_file)
    else:
        log_file = find_latest_log_file()
        if not log_file:
            print("Error: No log file found in output directory")
            sys.exit(1)
    
    print(f"Using log file: {log_file}")
    
    # Create tracker
    tracker = BarAccumulationTracker()
    
    # Parse log file
    parse_log_file(log_file, tracker)
    
    # Show summary
    print(tracker.get_summary())
    
    # Save detailed metrics if requested
    if args.output:
        import json
        metrics = tracker.get_detailed_metrics()
        with open(args.output, 'w') as f:
            json.dump(metrics, f, indent=2)
        print(f"\nDetailed metrics saved to: {args.output}")
    
    # Follow mode
    if args.follow:
        follow_log_file(log_file, tracker)
        print("\n" + tracker.get_summary())


if __name__ == '__main__':
    main()
