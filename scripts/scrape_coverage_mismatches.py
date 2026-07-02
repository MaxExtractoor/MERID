#!/usr/bin/env python3
"""
Coverage mismatch scraper - scans logs for E2E asset coverage issues.

Usage:
    python scripts/scrape_coverage_mismatches.py [--log-file=path/to/log] [--tail]

This script looks for patterns like:
- Spot fresh but no orderbook
- Orderbook fresh but stale spot
- Trading enabled while data is degraded, or vice versa
"""

import re
import sys
import argparse
import time
from pathlib import Path
from typing import Dict, List, Tuple, Any
from collections import defaultdict

# Patterns to look for
PATTERNS = {
    'spot_freshness': r'\[SPOT-HEALTH-FRESHNESS\] asset=(\w+) freshness_s=([\d.]+)',
    'orderbook_freshness': r'\[MD-FRESHNESS\] ticker=(\w+-\w+-\w+-\w+) staleness=([\d.]+)',
    'ws_subscription': r'\[E2E-COVERAGE-WS-STATE\] asset=(\w+) subscribed_markets=\[(.*?)\] size=(\d+)',
    'agent_enabled': r'\[AGENT-GRID-RESULTS\].*signals_generated=(\d+)',
    'degraded_action': r'\[SPOT-DEGRADED-ACTION\] suppressing (\w+) trading',
    'recovered_action': r'\[SPOT-RECOVERED-ACTION\] resuming (\w+) trading',
    'coverage_summary': r'\[E2E-ASSET-COVERAGE\] asset_coverage=(.+)',
    'md_freshness_alert': r'\[MD-FRESHNESS-ALERT\] ticker=(\w+-\w+-\w+-\w+) staleness=([\d.]+)'
}

class CoverageScraper:
    def __init__(self, log_file: str = None):
        self.log_file = Path(log_file) if log_file else None
        self.assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        self.asset_state = defaultdict(dict)
        self.issues = []
        
    def parse_line(self, line: str) -> Dict[str, Any]:
        """Parse a single log line for coverage information."""
        result = {'timestamp': None, 'asset': None, 'type': None, 'data': {}}
        
        # Extract timestamp (assuming format: [2026-06-03 20:24:17.106936+00:00])
        timestamp_match = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[^\]]*)\]', line)
        if timestamp_match:
            result['timestamp'] = timestamp_match.group(1)
        
        # Check each pattern
        for pattern_name, pattern in PATTERNS.items():
            match = re.search(pattern, line)
            if match:
                result['type'] = pattern_name
                
                if pattern_name == 'spot_freshness':
                    result['asset'] = match.group(1)
                    result['data'] = {'freshness_s': float(match.group(2))}
                    
                elif pattern_name == 'orderbook_freshness':
                    ticker = match.group(1)
                    # Extract asset from ticker (e.g., KXBTC15M-26JUN031630-30 -> BTC)
                    asset = next((a for a in self.assets if a in ticker.upper()), None)
                    if asset:
                        result['asset'] = asset
                        result['data'] = {'staleness_s': float(match.group(2))}
                        
                elif pattern_name == 'ws_subscription':
                    result['asset'] = match.group(1)
                    result['data'] = {
                        'subscribed_markets': match.group(2).split(', ') if match.group(2) else [],
                        'count': int(match.group(3))
                    }
                    
                elif pattern_name == 'agent_enabled':
                    # This is a global signal count, not asset-specific
                    result['data'] = {'signals_generated': int(match.group(1))}
                    
                elif pattern_name == 'degraded_action':
                    result['asset'] = match.group(1)
                    result['data'] = {'action': 'degraded'}
                    
                elif pattern_name == 'recovered_action':
                    result['asset'] = match.group(1)
                    result['data'] = {'action': 'recovered'}
                    
                elif pattern_name == 'coverage_summary':
                    # Parse the JSON-like coverage summary
                    try:
                        # Extract the JSON part
                        json_match = re.search(r'asset_coverage=(\{.+\})', line)
                        if json_match:
                            import json
                            coverage_data = json.loads(json_match.group(1))
                            result['data'] = coverage_data
                    except:
                        pass
                
                elif pattern_name == 'md_freshness_alert':
                    ticker = match.group(1)
                    asset = next((a for a in self.assets if a in ticker.upper()), None)
                    if asset:
                        result['asset'] = asset
                        result['data'] = {'staleness_s': float(match.group(2)), 'alert': True}
                
                break
        
        return result
    
    def update_asset_state(self, parsed: Dict[str, Any]):
        """Update asset state based on parsed log entry."""
        if not parsed['asset'] or not parsed['type']:
            return
        
        asset = parsed['asset']
        data_type = parsed['type']
        data = parsed['data']
        
        if data_type == 'spot_freshness':
            self.asset_state[asset]['spot_freshness_s'] = data['freshness_s']
            self.asset_state[asset]['spot_timestamp'] = parsed['timestamp']
            
        elif data_type == 'orderbook_freshness':
            self.asset_state[asset]['orderbook_freshness_s'] = data['staleness_s']
            self.asset_state[asset]['orderbook_timestamp'] = parsed['timestamp']
            
        elif data_type == 'ws_subscription':
            self.asset_state[asset]['ws_subscribed'] = data['count'] > 0
            self.asset_state[asset]['ws_markets'] = data['subscribed_markets']
            
        elif data_type == 'degraded_action':
            self.asset_state[asset]['degraded'] = True
            self.asset_state[asset]['degraded_timestamp'] = parsed['timestamp']
            
        elif data_type == 'recovered_action':
            self.asset_state[asset]['degraded'] = False
            self.asset_state[asset]['recovered_timestamp'] = parsed['timestamp']
            
        elif data_type == 'coverage_summary':
            # Update comprehensive coverage data
            for asset_name, coverage in data.items():
                if asset_name in self.assets:
                    self.asset_state[asset_name].update(coverage)
    
    def detect_mismatches(self) -> List[Dict[str, Any]]:
        """Detect coverage mismatches based on current asset state."""
        mismatches = []
        
        for asset in self.assets:
            state = self.asset_state.get(asset, {})
            
            # Check for spot fresh but no orderbook
            spot_fresh = state.get('spot_freshness_s', float('inf')) < 20.0
            orderbook_fresh = state.get('orderbook_freshness_s', float('inf')) < 30.0
            
            if spot_fresh and not orderbook_fresh:
                mismatches.append({
                    'asset': asset,
                    'type': 'spot_fresh_no_orderbook',
                    'message': f"{asset}: Spot fresh ({state.get('spot_freshness_s', 'N/A')}s) but orderbook stale ({state.get('orderbook_freshness_s', 'N/A')}s)",
                    'severity': 'medium'
                })
            
            # Check for orderbook fresh but stale spot
            if orderbook_fresh and not spot_fresh:
                mismatches.append({
                    'asset': asset,
                    'type': 'orderbook_fresh_stale_spot',
                    'message': f"{asset}: Orderbook fresh ({state.get('orderbook_freshness_s', 'N/A')}s) but spot stale ({state.get('spot_freshness_s', 'N/A')}s)",
                    'severity': 'high'
                })
            
            # Check for trading enabled while data degraded
            agent_enabled = state.get('agent_enabled', False)
            data_degraded = state.get('degraded', False) or not spot_fresh or not orderbook_fresh
            
            if agent_enabled and data_degraded:
                mismatches.append({
                    'asset': asset,
                    'type': 'trading_enabled_degraded_data',
                    'message': f"{asset}: Agent enabled but data degraded (spot_fresh={spot_fresh}, orderbook_fresh={orderbook_fresh}, degraded={data_degraded})",
                    'severity': 'high'
                })
            
            # Check for trading disabled while data healthy
            if not agent_enabled and not data_degraded and spot_fresh and orderbook_fresh:
                mismatches.append({
                    'asset': asset,
                    'type': 'trading_disabled_healthy_data',
                    'message': f"{asset}: Agent disabled but data healthy (spot_fresh={spot_fresh}, orderbook_fresh={orderbook_fresh})",
                    'severity': 'medium'
                })
            
            # Check for no WS subscription despite healthy data
            ws_subscribed = state.get('ws_subscribed', False)
            if spot_fresh and orderbook_fresh and not ws_subscribed:
                mismatches.append({
                    'asset': asset,
                    'type': 'healthy_data_no_ws',
                    'message': f"{asset}: Data healthy but no WS subscription",
                    'severity': 'high'
                })
        
        return mismatches
    
    def parse_file(self, file_path: Path) -> int:
        """Parse a log file and update state."""
        lines_processed = 0
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    parsed = self.parse_line(line.strip())
                    self.update_asset_state(parsed)
                    lines_processed += 1
        except FileNotFoundError:
            print(f"ERROR: Log file not found: {file_path}", file=sys.stderr)
            return 0
        except Exception as e:
            print(f"ERROR: Failed to parse log file: {e}", file=sys.stderr)
            return 0
        
        return lines_processed
    
    def tail_file(self, file_path: Path, follow: bool = True):
        """Tail a log file for real-time monitoring."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # Go to end of file
                f.seek(0, 2)
                
                while follow:
                    line = f.readline()
                    if line:
                        parsed = self.parse_line(line.strip())
                        self.update_asset_state(parsed)
                        
                        # Check for new mismatches
                        new_mismatches = self.detect_mismatches()
                        for mismatch in new_mismatches:
                            if mismatch not in self.issues:
                                self.issues.append(mismatch)
                                severity_emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}
                                emoji = severity_emoji.get(mismatch['severity'], '⚪')
                                print(f"{emoji} {mismatch['message']}")
                    else:
                        time.sleep(0.1)
                        
        except KeyboardInterrupt:
            print("\nStopping log monitoring...")
        except Exception as e:
            print(f"ERROR: Failed to tail log file: {e}", file=sys.stderr)
    
    def print_summary(self):
        """Print a summary of current state and detected issues."""
        print("\n📊 Asset Coverage Summary:")
        print("-" * 60)
        
        for asset in self.assets:
            state = self.asset_state.get(asset, {})
            
            spot_freshness = state.get('spot_freshness_s', None)
            orderbook_freshness = state.get('orderbook_freshness_s', None)
            ws_subscribed = state.get('ws_subscribed', False)
            agent_enabled = state.get('agent_enabled', False)
            degraded = state.get('degraded', False)
            
            status_emoji = "✅" if not degraded and spot_freshness and spot_freshness < 20 and orderbook_freshness and orderbook_freshness < 30 else "❌"
            
            print(f"{status_emoji} {asset}:")
            print(f"   Spot freshness: {spot_freshness:.1f}s" if spot_freshness else "   Spot freshness: N/A")
            print(f"   Orderbook freshness: {orderbook_freshness:.1f}s" if orderbook_freshness else "   Orderbook freshness: N/A")
            print(f"   WS subscribed: {'Yes' if ws_subscribed else 'No'}")
            print(f"   Agent enabled: {'Yes' if agent_enabled else 'No'}")
            print(f"   Degraded: {'Yes' if degraded else 'No'}")
            print()
        
        # Print current mismatches
        current_mismatches = self.detect_mismatches()
        if current_mismatches:
            print("🚨 Current Mismatches:")
            print("-" * 60)
            for mismatch in current_mismatches:
                severity_emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}
                emoji = severity_emoji.get(mismatch['severity'], '⚪')
                print(f"{emoji} {mismatch['message']}")
        else:
            print("✅ No coverage mismatches detected")

def main():
    parser = argparse.ArgumentParser(description='Scrape coverage mismatches from logs')
    parser.add_argument('--log-file', '-f', help='Log file to parse')
    parser.add_argument('--tail', '-t', action='store_true', help='Tail log file for real-time monitoring')
    parser.add_argument('--summary', '-s', action='store_true', help='Print summary and exit')
    args = parser.parse_args()
    
    scraper = CoverageScraper(args.log_file)
    
    if args.log_file:
        log_path = Path(args.log_file)
        if not log_path.exists():
            print(f"ERROR: Log file not found: {log_path}", file=sys.stderr)
            return 1
        
        if args.tail:
            print(f"🔍 Tailing log file: {log_path}")
            print("Press Ctrl+C to stop...")
            scraper.tail_file(log_path)
        else:
            lines_processed = scraper.parse_file(log_path)
            print(f"📄 Processed {lines_processed} lines from {log_path}")
            scraper.print_summary()
    
    elif args.summary:
        # Try to find recent log files
        log_files = list(Path('.').glob('*.log')) + list(Path('.').glob('*.txt'))
        recent_logs = sorted(log_files, key=lambda p: p.stat().st_mtime, reverse=True)[:3]
        
        if recent_logs:
            print(f"📄 Parsing recent logs: {[f.name for f in recent_logs]}")
            for log_file in recent_logs:
                scraper.parse_file(log_file)
            scraper.print_summary()
        else:
            print("No log files found in current directory")
            return 1
    
    else:
        print("Usage: python scripts/scrape_coverage_mismatches.py --log-file=path/to/log [--tail] [--summary]")
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
