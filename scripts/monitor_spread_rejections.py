#!/usr/bin/env python3
"""
Spread Rejection Monitor
Monitors spread rejections in real-time to identify potential flaws in spread validation logic.
Tracks spread values, assets, timing, and market conditions to detect patterns that may indicate
legitimate trades being incorrectly rejected.
"""

import re
import json
import time
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from pathlib import Path
from typing import Dict, List, Tuple
import statistics

class SpreadRejectionMonitor:
    def __init__(self, log_file: str, duration_minutes: int = 30):
        self.log_file = Path(log_file)
        self.duration_minutes = duration_minutes
        self.start_time = datetime.now()
        self.end_time = self.start_time + timedelta(minutes=duration_minutes)
        
        # Tracking data structures
        self.rejections = []
        self.by_asset = defaultdict(list)
        self.by_ticker = defaultdict(list)
        self.spread_distribution = []
        self.depth_analysis = []
        self.time_analysis = []
        
        # Patterns to match
        self.spread_rejection_pattern = re.compile(
            r'\[MARKET-VALIDATION\] asset=(\S+) ticker=(\S+) spread exceeds coarse filter=(\d+)c \(spread=(\d+)c\)'
        )
        self.market_validation_pattern = re.compile(
            r'\[MARKET-VALIDATION\] asset=(\S+) ticker=(\S+) regime=(\S+) depth_yes=(\d+) depth_no=(\d+)'
        )
        self.cycle_complete_pattern = re.compile(
            r'\[CYCLE-COMPLETE\] tick=(\d+) candidates=(\d+)'
        )
        
    def parse_log_line(self, line: str) -> Dict:
        """Parse a log line and extract relevant information."""
        # Try to parse as JSON first (structured logs)
        try:
            log_entry = json.loads(line)
            if 'message' in log_entry:
                message = log_entry['message']
                timestamp = log_entry.get('ts', '')
                logger = log_entry.get('logger', '')
                
                # Check for spread rejection
                match = self.spread_rejection_pattern.search(message)
                if match:
                    return {
                        'type': 'spread_rejection',
                        'timestamp': timestamp,
                        'asset': match.group(1),
                        'ticker': match.group(2),
                        'threshold': int(match.group(3)),
                        'spread': int(match.group(4)),
                        'logger': logger
                    }
                
                # Check for market validation (depth info)
                match = self.market_validation_pattern.search(message)
                if match:
                    return {
                        'type': 'market_validation',
                        'timestamp': timestamp,
                        'asset': match.group(1),
                        'ticker': match.group(2),
                        'regime': match.group(3),
                        'depth_yes': int(match.group(4)),
                        'depth_no': int(match.group(5)),
                        'logger': logger
                    }
                
                # Check for cycle complete
                match = self.cycle_complete_pattern.search(message)
                if match:
                    return {
                        'type': 'cycle_complete',
                        'timestamp': timestamp,
                        'tick': int(match.group(1)),
                        'candidates': int(match.group(2)),
                        'logger': logger
                    }
        except (json.JSONDecodeError, ValueError):
            pass
        
        # Fallback to plain text parsing
        match = self.spread_rejection_pattern.search(line)
        if match:
            return {
                'type': 'spread_rejection',
                'timestamp': datetime.now().isoformat(),
                'asset': match.group(1),
                'ticker': match.group(2),
                'threshold': int(match.group(3)),
                'spread': int(match.group(4)),
                'logger': 'unknown'
            }
        
        return None
    
    def monitor(self):
        """Monitor the log file for spread rejections."""
        print(f"Starting spread rejection monitor for {self.duration_minutes} minutes")
        print(f"Log file: {self.log_file}")
        print(f"Start time: {self.start_time}")
        print(f"End time: {self.end_time}")
        print("-" * 80)
        
        # Track recent market validation data for context
        recent_market_data = {}
        
        while datetime.now() < self.end_time:
            try:
                # Read new lines from log file
                with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    # Seek to end if file exists, otherwise start from beginning
                    if self.log_file.stat().st_size > 0:
                        f.seek(0, 2)
                    
                    while datetime.now() < self.end_time:
                        line = f.readline()
                        if not line:
                            time.sleep(0.5)
                            continue
                        
                        parsed = self.parse_log_line(line)
                        if not parsed:
                            continue
                        
                        # Process different event types
                        if parsed['type'] == 'market_validation':
                            key = f"{parsed['asset']}_{parsed['ticker']}"
                            recent_market_data[key] = {
                                'regime': parsed['regime'],
                                'depth_yes': parsed['depth_yes'],
                                'depth_no': parsed['depth_no']
                            }
                        
                        elif parsed['type'] == 'spread_rejection':
                            # Get context from recent market data
                            key = f"{parsed['asset']}_{parsed['ticker']}"
                            market_context = recent_market_data.get(key, {})
                            
                            rejection = {
                                'timestamp': parsed['timestamp'],
                                'asset': parsed['asset'],
                                'ticker': parsed['ticker'],
                                'threshold': parsed['threshold'],
                                'spread': parsed['spread'],
                                'excess': parsed['spread'] - parsed['threshold'],
                                'regime': market_context.get('regime', 'unknown'),
                                'depth_yes': market_context.get('depth_yes', 0),
                                'depth_no': market_context.get('depth_no', 0)
                            }
                            
                            self.rejections.append(rejection)
                            self.by_asset[parsed['asset']].append(rejection)
                            self.by_ticker[parsed['ticker']].append(rejection)
                            self.spread_distribution.append(parsed['spread'])
                            self.depth_analysis.append(market_context)
                            self.time_analysis.append(parsed['timestamp'])
                            
                            # Print real-time alert
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] REJECTION: "
                                  f"{parsed['asset']} {parsed['ticker']} spread={parsed['spread']}c "
                                  f"(threshold={parsed['threshold']}c, excess={rejection['excess']}c) "
                                  f"depth_yes={market_context.get('depth_yes', 0)} "
                                  f"depth_no={market_context.get('depth_no', 0)}")
                        
                        elif parsed['type'] == 'cycle_complete':
                            if parsed['candidates'] > 0:
                                print(f"[{datetime.now().strftime('%H:%M:%S')}] CYCLE: "
                                      f"tick={parsed['tick']} candidates={parsed['candidates']} "
                                      f"*** TRADING ACTIVITY DETECTED ***")
            
            except FileNotFoundError:
                print(f"Log file not found: {self.log_file}. Waiting...")
                time.sleep(5)
            except Exception as e:
                print(f"Error reading log file: {e}")
                time.sleep(5)
    
    def analyze(self):
        """Analyze the collected rejection data for potential flaws."""
        print("\n" + "=" * 80)
        print("SPREAD REJECTION ANALYSIS")
        print("=" * 80)
        
        if not self.rejections:
            print("No spread rejections detected during monitoring period.")
            return
        
        # Overall statistics
        print(f"\nOVERALL STATISTICS:")
        print(f"Total rejections: {len(self.rejections)}")
        print(f"Monitoring duration: {self.duration_minutes} minutes")
        print(f"Rejections per minute: {len(self.rejections) / self.duration_minutes:.2f}")
        
        # Spread distribution
        print(f"\nSPREAD DISTRIBUTION:")
        if self.spread_distribution:
            print(f"Min spread: {min(self.spread_distribution)}c")
            print(f"Max spread: {max(self.spread_distribution)}c")
            print(f"Mean spread: {statistics.mean(self.spread_distribution):.1f}c")
            print(f"Median spread: {statistics.median(self.spread_distribution):.1f}c")
            print(f"Std dev: {statistics.stdev(self.spread_distribution) if len(self.spread_distribution) > 1 else 0:.1f}c")
        
        # Spread buckets
        print(f"\nSPREAD BUCKETS:")
        buckets = Counter()
        for spread in self.spread_distribution:
            if spread <= 25:
                buckets['20-25c'] += 1
            elif spread <= 30:
                buckets['26-30c'] += 1
            elif spread <= 40:
                buckets['31-40c'] += 1
            elif spread <= 50:
                buckets['41-50c'] += 1
            elif spread <= 60:
                buckets['51-60c'] += 1
            elif spread <= 70:
                buckets['61-70c'] += 1
            else:
                buckets['71c+'] += 1
        
        for bucket, count in sorted(buckets.items()):
            print(f"  {bucket}: {count} ({count/len(self.spread_distribution)*100:.1f}%)")
        
        # By asset
        print(f"\nREJECTIONS BY ASSET:")
        for asset, rejections in sorted(self.by_asset.items()):
            spreads = [r['spread'] for r in rejections]
            print(f"  {asset}: {len(rejections)} rejections "
                  f"(avg spread: {statistics.mean(spreads):.1f}c, "
                  f"min: {min(spreads)}c, max: {max(spreads)}c)")
        
        # Depth analysis
        print(f"\nDEPTH ANALYSIS:")
        yes_depths = [d.get('depth_yes', 0) for d in self.depth_analysis if d]
        no_depths = [d.get('depth_no', 0) for d in self.depth_analysis if d]
        
        if yes_depths:
            print(f"  YES depth - avg: {statistics.mean(yes_depths):.0f}, "
                  f"min: {min(yes_depths)}, max: {max(yes_depths)}")
        if no_depths:
            print(f"  NO depth - avg: {statistics.mean(no_depths):.0f}, "
                  f"min: {min(no_depths)}, max: {max(no_depths)}")
        
        # Regime analysis
        print(f"\nREGIME ANALYSIS:")
        regimes = Counter([r['regime'] for r in self.rejections])
        for regime, count in sorted(regimes.items()):
            print(f"  {regime}: {count} ({count/len(self.rejections)*100:.1f}%)")
        
        # Potential flaws detection
        print(f"\n" + "=" * 80)
        print("POTENTIAL FLAWS DETECTION")
        print("=" * 80)
        
        flaws = []
        
        # Check for spreads close to threshold
        near_threshold = [r for r in self.rejections if r['excess'] <= 5]
        if near_threshold:
            flaws.append(f"NEAR-THRESHOLD REJECTIONS: {len(near_threshold)} rejections "
                        f"within 5c of 20c threshold. These may be legitimate trades being rejected.")
            print(f"⚠️  {flaws[-1]}")
            for r in near_threshold[:5]:  # Show first 5 examples
                print(f"    - {r['asset']} {r['ticker']}: spread={r['spread']}c (excess={r['excess']}c)")
        
        # Check for high depth but rejected
        high_depth_rejections = [r for r in self.rejections 
                                if r['depth_yes'] > 1000 and r['depth_no'] > 1000]
        if high_depth_rejections:
            flaws.append(f"HIGH DEPTH REJECTIONS: {len(high_depth_rejections)} rejections "
                        f"with depth_yes > 1000 and depth_no > 1000. "
                        f"These may be liquid markets being incorrectly rejected.")
            print(f"⚠️  {flaws[-1]}")
            for r in high_depth_rejections[:5]:
                print(f"    - {r['asset']} {r['ticker']}: spread={r['spread']}c, "
                      f"depth_yes={r['depth_yes']}, depth_no={r['depth_no']}")
        
        # Check for one-sided regime
        one_sided = [r for r in self.rejections if r['regime'] in ['yes_only', 'no_only']]
        if one_sided:
            flaws.append(f"ONE-SIDED REGIME: {len(one_sided)} rejections in one-sided markets. "
                        f"This may be expected but worth monitoring.")
            print(f"⚠️  {flaws[-1]}")
        
        # Check for consistent rejection patterns
        asset_consistency = {}
        for asset, rejections in self.by_asset.items():
            spreads = [r['spread'] for r in rejections]
            if len(spreads) > 5:
                spread_range = max(spreads) - min(spreads)
                if spread_range < 10:  # Tight range
                    asset_consistency[asset] = {
                        'count': len(rejections),
                        'range': spread_range,
                        'avg': statistics.mean(spreads)
                    }
        
        if asset_consistency:
            flaws.append(f"CONSISTENT REJECTION PATTERNS: Some assets show tight spread ranges, "
                        f"possibly indicating systematic rejection of valid opportunities.")
            print(f"⚠️  {flaws[-1]}")
            for asset, stats in sorted(asset_consistency.items()):
                print(f"    - {asset}: {stats['count']} rejections, "
                      f"spread range {stats['range']}c (avg {stats['avg']:.1f}c)")
        
        if not flaws:
            print("✓ No obvious flaws detected. Rejections appear to be driven by genuine market conditions.")
        
        # Summary
        print(f"\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total rejections analyzed: {len(self.rejections)}")
        print(f"Potential flaws identified: {len(flaws)}")
        print(f"Recommendation: {'Further investigation needed' if flaws else 'Current logic appears sound'}")
        
        return {
            'total_rejections': len(self.rejections),
            'flaws': flaws,
            'spread_distribution': self.spread_distribution,
            'by_asset': dict(self.by_asset),
            'near_threshold_count': len(near_threshold) if near_threshold else 0,
            'high_depth_count': len(high_depth_rejections) if high_depth_rejections else 0
        }

def main():
    log_file = r"C:\Dev\MERID\logs\full.log"
    monitor = SpreadRejectionMonitor(log_file, duration_minutes=30)
    
    try:
        monitor.monitor()
    except KeyboardInterrupt:
        print("\nMonitoring interrupted by user.")
    
    results = monitor.analyze()
    
    # Save results to file
    output_file = r"C:\Dev\MERID\spread_rejection_analysis.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\nResults saved to: {output_file}")

if __name__ == "__main__":
    main()
