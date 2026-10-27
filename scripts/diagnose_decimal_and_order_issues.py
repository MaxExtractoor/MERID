#!/usr/bin/env python3
"""
Diagnostic script to expose decimal scaling and order execution reporting issues
across the entire 15M Kalshi crypto trading stack.

Issues to investigate:
1. SOL decimal scaling: Log shows 7807.0000 but SOL is actually $78.07
2. Order execution reporting: Logs show BUY_YES but actual execution may be different
3. Check decimal scaling across all assets (BTC, ETH, SOL, XRP, DOGE)
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Expected price ranges for validation
EXPECTED_PRICE_RANGES = {
    "BTC": (60000, 70000),  # ~$63K
    "ETH": (1500, 2000),    # ~$1.7K
    "SOL": (70, 90),        # ~$78
    "XRP": (1.0, 1.2),      # ~$1.09
    "DOGE": (0.07, 0.08),   # ~$0.073
}

def parse_fvg_update_log(log_path: Path) -> List[Dict]:
    """Parse FVG-UPDATE log lines to extract OHLC data."""
    fvg_logs = []
    pattern = r'\[FVG-UPDATE\] asset=(\w+) OHLC data updated in FVG forecaster: O=([\d.]+) H=([\d.]+) L=([\d.]+) C=([\d.]+)'
    
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            match = re.search(pattern, line)
            if match:
                asset, open_p, high, low, close = match.groups()
                fvg_logs.append({
                    'asset': asset,
                    'open': float(open_p),
                    'high': float(high),
                    'low': float(low),
                    'close': float(close),
                    'line': line.strip()
                })
    
    return fvg_logs

def parse_order_execution_logs(log_path: Path) -> List[Dict]:
    """Parse order execution logs to identify discrepancies."""
    order_logs = []
    patterns = [
        r'\[EXEC-PATH\] ENTRY intent_id=(\w+) ticker=(\w+) side=(\w+) count=(\d+)',
        r'\[15M-LOOP\] Order routed successfully: ticker=(\w+) side=(\w+) count=(\d+)',
        r'\[15M-LOOP\] ticker=(\w+) price_cents from candidate=(\d+)',
    ]
    
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            for pattern in patterns:
                match = re.search(pattern, line)
                if match:
                    order_logs.append({
                        'line': line.strip(),
                        'pattern': pattern,
                        'match': match.groups()
                    })
                    break
    
    return order_logs

def check_decimal_scaling(fvg_logs: List[Dict]) -> List[Dict]:
    """Check if OHLC values are within expected price ranges."""
    issues = []
    
    for log in fvg_logs:
        asset = log['asset']
        close = log['close']
        
        if asset in EXPECTED_PRICE_RANGES:
            min_price, max_price = EXPECTED_PRICE_RANGES[asset]
            
            # Check if close is within expected range
            if not (min_price <= close <= max_price):
                # Check if it's off by factor of 100 (decimal scaling issue)
                if min_price * 100 <= close <= max_price * 100:
                    issues.append({
                        'asset': asset,
                        'issue': 'DECIMAL_SCALING_100X',
                        'expected_range': (min_price, max_price),
                        'actual_value': close,
                        'scaled_value': close / 100,
                        'line': log['line']
                    })
                elif min_price / 100 <= close <= max_price / 100:
                    issues.append({
                        'asset': asset,
                        'issue': 'DECIMAL_SCALING_0.01X',
                        'expected_range': (min_price, max_price),
                        'actual_value': close,
                        'scaled_value': close * 100,
                        'line': log['line']
                    })
                else:
                    issues.append({
                        'asset': asset,
                        'issue': 'VALUE_OUT_OF_RANGE',
                        'expected_range': (min_price, max_price),
                        'actual_value': close,
                        'line': log['line']
                    })
    
    return issues

def analyze_order_execution(order_logs: List[Dict]) -> List[Dict]:
    """Analyze order execution logs for discrepancies."""
    issues = []
    
    # Group orders by ticker
    ticker_orders: Dict[str, List[Dict]] = {}
    for log in order_logs:
        ticker = log['match'][1] if len(log['match']) > 1 else 'UNKNOWN'
        if ticker not in ticker_orders:
            ticker_orders[ticker] = []
        ticker_orders[ticker].append(log)
    
    # Check for conflicting orders on same ticker
    for ticker, orders in ticker_orders.items():
        if len(orders) > 1:
            sides = [log['match'][2] if len(log['match']) > 2 else 'UNKNOWN' for log in orders]
            if len(set(sides)) > 1:
                issues.append({
                    'ticker': ticker,
                    'issue': 'CONFLICTING_SIDES',
                    'sides': sides,
                    'order_count': len(orders),
                    'lines': [log['line'] for log in orders]
                })
    
    return issues

def main():
    log_path = Path('logs/full.log')
    
    if not log_path.exists():
        print(f"ERROR: Log file not found: {log_path}")
        sys.exit(1)
    
    print("=" * 80)
    print("DIAGNOSTIC: Decimal Scaling and Order Execution Issues")
    print("=" * 80)
    print()
    
    # Parse FVG-UPDATE logs
    print("1. Parsing FVG-UPDATE logs...")
    fvg_logs = parse_fvg_update_log(log_path)
    print(f"   Found {len(fvg_logs)} FVG-UPDATE log entries")
    print()
    
    # Check decimal scaling
    print("2. Checking decimal scaling...")
    decimal_issues = check_decimal_scaling(fvg_logs)
    
    if decimal_issues:
        print(f"   FOUND {len(decimal_issues)} DECIMAL SCALING ISSUES:")
        print()
        for issue in decimal_issues:
            print(f"   Asset: {issue['asset']}")
            print(f"   Issue: {issue['issue']}")
            print(f"   Expected range: ${issue['expected_range'][0]:.2f} - ${issue['expected_range'][1]:.2f}")
            print(f"   Actual value: {issue['actual_value']}")
            if 'scaled_value' in issue:
                print(f"   Scaled value: {issue['scaled_value']}")
            print(f"   Log line: {issue['line'][:100]}...")
            print()
    else:
        print("   No decimal scaling issues found")
    print()
    
    # Parse order execution logs
    print("3. Parsing order execution logs...")
    order_logs = parse_order_execution_logs(log_path)
    print(f"   Found {len(order_logs)} order execution log entries")
    print()
    
    # Analyze order execution
    print("4. Analyzing order execution...")
    order_issues = analyze_order_execution(order_logs)
    
    if order_issues:
        print(f"   FOUND {len(order_issues)} ORDER EXECUTION ISSUES:")
        print()
        for issue in order_issues:
            print(f"   Ticker: {issue['ticker']}")
            print(f"   Issue: {issue['issue']}")
            print(f"   Sides: {issue['sides']}")
            print(f"   Order count: {issue['order_count']}")
            print(f"   Sample lines:")
            for line in issue['lines'][:3]:
                print(f"     {line[:120]}...")
            print()
    else:
        print("   No order execution issues found")
    print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Decimal scaling issues: {len(decimal_issues)}")
    print(f"Order execution issues: {len(order_issues)}")
    print()
    
    if decimal_issues or order_issues:
        print("CRITICAL ISSUES FOUND - INVESTIGATION REQUIRED")
        sys.exit(1)
    else:
        print("No critical issues found")
        sys.exit(0)

if __name__ == '__main__':
    main()
