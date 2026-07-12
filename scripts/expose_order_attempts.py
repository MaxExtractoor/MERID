#!/usr/bin/env python3
"""
Script to expose all order attempts with detailed metrics.

This script monitors the 15m Kalshi crypto trading system logs and extracts
all order attempts with their key metrics including:
- Ticker and asset
- Side (yes/no) and action (buy/sell)
- Price (cents)
- Edge percentage
- Aggressiveness (0.0=resting, 0.5-1.0=marketable)
- Spread information
- Confidence and model probability
- Order status and fill information
- Rejection reasons (if any)

Usage:
    python scripts/expose_order_attempts.py
"""

import re
import time
import json
import sys
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional


class OrderAttemptMonitor:
    """Monitor and extract order attempt details from logs."""
    
    def __init__(self):
        self.order_attempts: List[Dict] = []
        self.current_market_state: Dict[str, Dict] = {}
        self.current_edge_data: Dict[str, Dict] = {}
        
        # Regex patterns for log parsing
        self.patterns = {
            # Aggressiveness computation (from loop_15m.py fix)
            'aggressiveness': re.compile(
                r'\[15M-LOOP\] Computed aggressiveness: ticker=(\S+) asset=(\S+) edge_pct=([\d.]+)% aggressiveness=([\d.]+) tte=(\d+)s'
            ),
            # Agent grid candidate generation
            'candidate': re.compile(
                r'\[CANDIDATE\] asset=(\S+) ticker=(\S+) side=(\w+) action=(\w+) edge_pct=([\d.]+) confidence=([\d.]+) model_prob=([\d.]+)'
            ),
            # Market state
            'market_state': re.compile(
                r'\[MARKET-STATE\] ticker=(\S+) bid=(\d+) ask=(\d+) mid=([\d.]+) spread=([\d.]+) depth_yes=(\d+) depth_no=(\d+)'
            ),
            # Order routing
            'route_order': re.compile(
                r'\[ROUTE-ORDER\] ticker=(\S+) side=(\w+) action=(\w+) price_cents=(\d+) count=(\d+) status=(\w+) reason=(\S+)'
            ),
            # Order result
            'order_result': re.compile(
                r'\[ORDER-RESULT\] ticker=(\S+) order_id=(\S+) status=(\w+) filled_count=(\d+) requested_count=(\d+)'
            ),
            # Edge calculation
            'edge_calc': re.compile(
                r'\[EDGE-CALC\] asset=(\S+) ticker=(\S+) edge_pct=([\d.]+) velocity=([\d.]+)'
            ),
            # Position limit
            'position_limit': re.compile(
                r'\[POSITION-LIMIT\] agent=(\S+) total_positions=(\d+) open_positions=(\d+)'
            ),
            # Trading window
            'trading_window': re.compile(
                r'\[TRADING-WINDOW\] asset=(\S+) time_to_expiry=([\d.]+)s within trading window.*?-> (\w+)'
            ),
            # Market validation
            'market_validation': re.compile(
                r'\[MARKET-VALIDATION\] asset=(\S+) ticker=(\S+) regime=(\w+) depth_yes=(\d+) depth_no=(\d+)'
            ),
            # Price filter reject
            'price_filter': re.compile(
                r'\[PRICE-FILTER-REJECT\] asset=(\S+) both sides outside.*?yes=(\d+)c, no=(\d+)c.*?-> SKIP'
            ),
        }
    
    def parse_log_line(self, line: str) -> Optional[Dict]:
        """Parse a single log line and extract order attempt data."""
        timestamp = datetime.now().isoformat()
        
        # Try aggressiveness pattern (from our fix)
        match = self.patterns['aggressiveness'].search(line)
        if match:
            return {
                'type': 'aggressiveness',
                'timestamp': timestamp,
                'ticker': match.group(1),
                'asset': match.group(2),
                'edge_pct': float(match.group(3)),
                'aggressiveness': float(match.group(4)),
                'time_to_expiry': int(match.group(5)),
            }
        
        # Try candidate pattern
        match = self.patterns['candidate'].search(line)
        if match:
            return {
                'type': 'candidate',
                'timestamp': timestamp,
                'asset': match.group(1),
                'ticker': match.group(2),
                'side': match.group(3),
                'action': match.group(4),
                'edge_pct': float(match.group(5)),
                'confidence': float(match.group(6)),
                'model_prob': float(match.group(7)),
            }
        
        # Try market_state pattern
        match = self.patterns['market_state'].search(line)
        if match:
            state = {
                'type': 'market_state',
                'timestamp': timestamp,
                'ticker': match.group(1),
                'bid': int(match.group(2)),
                'ask': int(match.group(3)),
                'mid': float(match.group(4)),
                'spread': float(match.group(5)),
                'depth_yes': int(match.group(6)),
                'depth_no': int(match.group(7)),
            }
            self.current_market_state[match.group(1)] = state
            return state
        
        # Try route_order pattern
        match = self.patterns['route_order'].search(line)
        if match:
            return {
                'type': 'route_order',
                'timestamp': timestamp,
                'ticker': match.group(1),
                'side': match.group(2),
                'action': match.group(3),
                'price_cents': int(match.group(4)),
                'count': int(match.group(5)),
                'status': match.group(6),
                'reason': match.group(7),
            }
        
        # Try order_result pattern
        match = self.patterns['order_result'].search(line)
        if match:
            return {
                'type': 'order_result',
                'timestamp': timestamp,
                'ticker': match.group(1),
                'order_id': match.group(2),
                'status': match.group(3),
                'filled_count': int(match.group(4)),
                'requested_count': int(match.group(5)),
            }
        
        # Try edge_calc pattern
        match = self.patterns['edge_calc'].search(line)
        if match:
            edge_data = {
                'type': 'edge_calc',
                'timestamp': timestamp,
                'asset': match.group(1),
                'ticker': match.group(2),
                'edge_pct': float(match.group(3)),
                'velocity': float(match.group(4)),
            }
            self.current_edge_data[match.group(2)] = edge_data
            return edge_data
        
        # Try position_limit pattern
        match = self.patterns['position_limit'].search(line)
        if match:
            return {
                'type': 'position_limit',
                'timestamp': timestamp,
                'agent': match.group(1),
                'total_positions': int(match.group(2)),
                'open_positions': int(match.group(3)),
            }
        
        # Try trading_window pattern
        match = self.patterns['trading_window'].search(line)
        if match:
            return {
                'type': 'trading_window',
                'timestamp': timestamp,
                'asset': match.group(1),
                'time_to_expiry': float(match.group(2)),
                'decision': match.group(3),
            }
        
        # Try market_validation pattern
        match = self.patterns['market_validation'].search(line)
        if match:
            return {
                'type': 'market_validation',
                'timestamp': timestamp,
                'asset': match.group(1),
                'ticker': match.group(2),
                'regime': match.group(3),
                'depth_yes': int(match.group(4)),
                'depth_no': int(match.group(5)),
            }
        
        # Try price_filter pattern
        match = self.patterns['price_filter'].search(line)
        if match:
            return {
                'type': 'price_filter_reject',
                'timestamp': timestamp,
                'asset': match.group(1),
                'yes_price': int(match.group(2)),
                'no_price': int(match.group(3)),
            }
        
        return None
    
    def display_order_attempt(self, attempt: Dict):
        """Display order attempt details in a readable format."""
        print("\n" + "=" * 100)
        print(f"ORDER ATTEMPT - {attempt.get('timestamp', 'N/A')}")
        print("=" * 100)
        
        if attempt['type'] == 'aggressiveness':
            print(f"Type: Aggressiveness Computation (NEW FIX)")
            print(f"Ticker: {attempt['ticker']}")
            print(f"Asset: {attempt['asset']}")
            print(f"Edge: {attempt['edge_pct']:.2f}%")
            print(f"Aggressiveness: {attempt['aggressiveness']:.2f} ({'MARKETABLE' if attempt['aggressiveness'] > 0 else 'RESTING'})")
            print(f"Time to Expiry: {attempt['time_to_expiry']}s")
            
            # Add market state if available
            if attempt['ticker'] in self.current_market_state:
                ms = self.current_market_state[attempt['ticker']]
                print(f"\nMarket State:")
                print(f"  Bid: {ms['bid']}c | Ask: {ms['ask']}c | Mid: {ms['mid']:.1f}c")
                print(f"  Spread: {ms['spread']:.1f}c")
                print(f"  Depth YES: {ms['depth_yes']} | Depth NO: {ms['depth_no']}")
        
        elif attempt['type'] == 'candidate':
            print(f"Type: Candidate Generation")
            print(f"Asset: {attempt['asset']}")
            print(f"Ticker: {attempt['ticker']}")
            print(f"Side: {attempt['side']}")
            print(f"Action: {attempt['action']}")
            print(f"Edge: {attempt['edge_pct']:.2f}%")
            print(f"Confidence: {attempt['confidence']:.2f}")
            print(f"Model Prob: {attempt['model_prob']:.2f}")
        
        elif attempt['type'] == 'route_order':
            print(f"Type: Order Routing")
            print(f"Ticker: {attempt['ticker']}")
            print(f"Side: {attempt['side']}")
            print(f"Action: {attempt['action']}")
            print(f"Price: {attempt['price_cents']} cents")
            print(f"Count: {attempt['count']}")
            print(f"Status: {attempt['status']}")
            print(f"Reason: {attempt['reason']}")
        
        elif attempt['type'] == 'order_result':
            print(f"Type: Order Result")
            print(f"Ticker: {attempt['ticker']}")
            print(f"Order ID: {attempt['order_id']}")
            print(f"Status: {attempt['status']}")
            print(f"Filled: {attempt['filled_count']}/{attempt['requested_count']}")
            if attempt['requested_count'] > 0:
                print(f"Fill Rate: {attempt['filled_count']/attempt['requested_count']*100:.1f}%")
        
        elif attempt['type'] == 'market_state':
            print(f"Type: Market State Update")
            print(f"Ticker: {attempt['ticker']}")
            print(f"Bid: {attempt['bid']} cents")
            print(f"Ask: {attempt['ask']} cents")
            print(f"Mid: {attempt['mid']:.1f} cents")
            print(f"Spread: {attempt['spread']:.1f} cents")
            print(f"Depth YES: {attempt['depth_yes']}")
            print(f"Depth NO: {attempt['depth_no']}")
        
        elif attempt['type'] == 'edge_calc':
            print(f"Type: Edge Calculation")
            print(f"Asset: {attempt['asset']}")
            print(f"Ticker: {attempt['ticker']}")
            print(f"Edge: {attempt['edge_pct']:.2f}%")
            print(f"Velocity: {attempt['velocity']:.6f}")
        
        elif attempt['type'] == 'position_limit':
            print(f"Type: Position Limit Check")
            print(f"Agent: {attempt['agent']}")
            print(f"Total Positions: {attempt['total_positions']}")
            print(f"Open Positions: {attempt['open_positions']}")
        
        elif attempt['type'] == 'trading_window':
            print(f"Type: Trading Window Check")
            print(f"Asset: {attempt['asset']}")
            print(f"Time to Expiry: {attempt['time_to_expiry']:.1f}s")
            print(f"Decision: {attempt['decision']}")
        
        elif attempt['type'] == 'market_validation':
            print(f"Type: Market Validation")
            print(f"Asset: {attempt['asset']}")
            print(f"Ticker: {attempt['ticker']}")
            print(f"Regime: {attempt['regime']}")
            print(f"Depth YES: {attempt['depth_yes']}")
            print(f"Depth NO: {attempt['depth_no']}")
        
        elif attempt['type'] == 'price_filter_reject':
            print(f"Type: Price Filter Reject")
            print(f"Asset: {attempt['asset']}")
            print(f"YES Price: {attempt['yes_price']}c")
            print(f"NO Price: {attempt['no_price']}c")
            print(f"Reason: Both sides outside 5c-95c range")
        
        print("=" * 100)
    
    def monitor_log_file(self, log_file: str):
        """Monitor log file for order attempts."""
        print(f"Monitoring log file: {log_file}")
        print("Press Ctrl+C to stop monitoring...")
        print("=" * 100)
        
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                # Move to end of file
                f.seek(0, 2)
                
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    
                    attempt = self.parse_log_line(line)
                    if attempt:
                        self.order_attempts.append(attempt)
                        self.display_order_attempt(attempt)
        
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped.")
            self.print_summary()
    
    def monitor_stdin(self):
        """Monitor stdin for log lines (for piping)."""
        print("Monitoring stdin for log lines...")
        print("Press Ctrl+C to stop monitoring...")
        print("=" * 100)
        
        try:
            for line in sys.stdin:
                attempt = self.parse_log_line(line)
                if attempt:
                    self.order_attempts.append(attempt)
                    self.display_order_attempt(attempt)
        
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped.")
            self.print_summary()
    
    def print_summary(self):
        """Print summary of all order attempts."""
        print("\n" + "=" * 100)
        print("ORDER ATTEMPT SUMMARY")
        print("=" * 100)
        
        # Group by type
        by_type = defaultdict(list)
        for attempt in self.order_attempts:
            by_type[attempt['type']].append(attempt)
        
        print(f"\nTotal Events: {len(self.order_attempts)}")
        for type_name, attempts in sorted(by_type.items()):
            print(f"  {type_name.upper()}: {len(attempts)}")
        
        # Calculate fill rate
        order_results = [a for a in self.order_attempts if a['type'] == 'order_result']
        if order_results:
            total_requested = sum(a['requested_count'] for a in order_results)
            total_filled = sum(a['filled_count'] for a in order_results)
            fill_rate = (total_filled / total_requested * 100) if total_requested > 0 else 0
            print(f"\nOverall Fill Rate: {fill_rate:.1f}% ({total_filled}/{total_requested})")
        
        # Calculate aggressiveness distribution
        aggressiveness_events = [a for a in self.order_attempts if a['type'] == 'aggressiveness']
        if aggressiveness_events:
            marketable = sum(1 for a in aggressiveness_events if a['aggressiveness'] > 0)
            resting = sum(1 for a in aggressiveness_events if a['aggressiveness'] == 0)
            print(f"\nAggressiveness Distribution:")
            print(f"  Marketable (>0): {marketable} ({marketable/len(aggressiveness_events)*100:.1f}%)")
            print(f"  Resting (0): {resting} ({resting/len(aggressiveness_events)*100:.1f}%)")
        
        # Calculate routing status
        route_orders = [a for a in self.order_attempts if a['type'] == 'route_order']
        if route_orders:
            by_status = defaultdict(int)
            for ro in route_orders:
                by_status[ro['status']] += 1
            print(f"\nOrder Routing Status:")
            for status, count in sorted(by_status.items()):
                print(f"  {status}: {count}")
        
        # Calculate price filter rejects
        price_rejects = [a for a in self.order_attempts if a['type'] == 'price_filter_reject']
        if price_rejects:
            print(f"\nPrice Filter Rejects: {len(price_rejects)}")
        
        print("=" * 100)


def main():
    """Main entry point."""
    monitor = OrderAttemptMonitor()
    
    if len(sys.argv) > 1:
        # Monitor specified log file
        log_file = sys.argv[1]
        monitor.monitor_log_file(log_file)
    else:
        # Monitor stdin (for piping)
        monitor.monitor_stdin()
    
    # Export to JSON
    export_file = 'order_attempts_export.json'
    with open(export_file, 'w') as f:
        json.dump({
            'order_attempts': monitor.order_attempts,
            'market_states': monitor.current_market_state,
            'edge_data': monitor.current_edge_data,
        }, f, indent=2)
    print(f"\nExported {len(monitor.order_attempts)} events to {export_file}")


if __name__ == '__main__':
    main()
