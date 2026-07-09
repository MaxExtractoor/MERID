#!/usr/bin/env python3
"""
Diagnostic script to analyze recent trade execution and verify correctness.
Focuses on the last 2 executed trades to ensure proper exit/entry behavior.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

def parse_trade_logs(log_path: Path) -> List[Dict]:
    """Parse recent trade execution logs."""
    trade_logs = []
    
    # Patterns for trade execution
    patterns = [
        r'\[EXEC-PATH\] ENTRY intent_id=(\w+) ticker=(\w+) side=(\w+) count=(\d+)',
        r'\[15M-LOOP\] Order routed successfully: ticker=(\w+) side=(\w+) count=(\d+)',
        r'\[15M-LOOP\] ticker=(\w+) price_cents from candidate=(\d+)',
        r'\[EXIT-ORDER\] ticker=(\w+) side=(\w+) action=(\w+)',
        r'\[15M-LOOP\] Order rejected - not updating position tracking: ticker=(\w+) reason=(.+)',
    ]
    
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            for pattern in patterns:
                match = re.search(pattern, line)
                if match:
                    trade_logs.append({
                        'line': line.strip(),
                        'pattern': pattern,
                        'match': match.groups(),
                        'timestamp': extract_timestamp(line)
                    })
                    break
    
    return trade_logs

def extract_timestamp(line: str) -> Optional[datetime]:
    """Extract timestamp from log line."""
    # Format: 2026-07-09 15:10:55
    match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return None
    return None

def analyze_trade_sequence(trade_logs: List[Dict]) -> List[Dict]:
    """Analyze trade sequence for correctness."""
    issues = []
    
    # Group by ticker
    ticker_trades: Dict[str, List[Dict]] = {}
    for log in trade_logs:
        ticker = log['match'][1] if len(log['match']) > 1 else 'UNKNOWN'
        if ticker not in ticker_trades:
            ticker_trades[ticker] = []
        ticker_trades[ticker].append(log)
    
    # Analyze each ticker's trade sequence
    for ticker, trades in ticker_trades.items():
        if len(trades) < 2:
            continue
        
        # Sort by timestamp
        trades.sort(key=lambda x: x['timestamp'] or datetime.min)
        
        # Get last 2 trades
        recent_trades = trades[-2:]
        
        # Extract sides and actions
        sides = []
        for trade in recent_trades:
            if 'EXEC-PATH' in trade['line']:
                sides.append(('ENTRY', trade['match'][2], trade['match'][3]))  # (type, side, count)
            elif 'Order routed successfully' in trade['line']:
                sides.append(('ROUTED', trade['match'][2], trade['match'][3]))
            elif 'EXIT-ORDER' in trade['line']:
                sides.append(('EXIT', trade['match'][1], trade['match'][2]))
            elif 'Order rejected' in trade['line']:
                sides.append(('REJECTED', trade['match'][1], trade['match'][2]))
        
        # Check for exit followed by entry (normal exit behavior)
        if len(sides) >= 2:
            first_trade = sides[0]
            second_trade = sides[1]
            
            # Check if first was SELL (exit) and second was BUY (entry)
            if first_trade[0] == 'EXIT' and 'SELL' in first_trade[1]:
                if second_trade[0] == 'ENTRY' and 'BUY' in second_trade[1]:
                    # Normal exit followed by entry
                    pass
                else:
                    issues.append({
                        'ticker': ticker,
                        'issue': 'EXIT_NOT_FOLLOWED_BY_ENTRY',
                        'trades': sides,
                        'lines': [t['line'] for t in recent_trades]
                    })
            elif first_trade[0] == 'EXIT' and 'SELL' in first_trade[1]:
                # Exit without follow-up entry (position closed)
                pass
            elif first_trade[0] == 'REJECTED':
                # Rejected order - check if it was duplicate
                if 'duplicate' in first_trade[2].lower():
                    # Normal duplicate rejection
                    pass
                else:
                    issues.append({
                        'ticker': ticker,
                        'issue': 'UNEXPECTED_REJECTION',
                        'trades': sides,
                        'lines': [t['line'] for t in recent_trades]
                    })
    
    return issues

def check_price_consistency(trade_logs: List[Dict]) -> List[Dict]:
    """Check price consistency across trades."""
    issues = []
    
    # Extract price information
    price_logs = []
    for log in trade_logs:
        if 'price_cents' in log['line']:
            match = re.search(r'price_cents=(\d+)', log['line'])
            if match:
                price_logs.append({
                    'line': log['line'],
                    'price_cents': int(match.group(1)),
                    'timestamp': log['timestamp']
                })
    
    # Check for price anomalies
    if len(price_logs) >= 2:
        price_logs.sort(key=lambda x: x['timestamp'] or datetime.min)
        recent_prices = price_logs[-2:]
        
        # Check if prices are reasonable (10-50c range)
        for price_log in recent_prices:
            price = price_log['price_cents']
            if price < 10 or price > 50:
                issues.append({
                    'issue': 'PRICE_OUT_OF_RANGE',
                    'price_cents': price,
                    'expected_range': '10-50c',
                    'line': price_log['line']
                })
    
    return issues

def main():
    log_path = Path('logs/full.log')
    
    if not log_path.exists():
        print(f"ERROR: Log file not found: {log_path}")
        sys.exit(1)
    
    print("=" * 80)
    print("DIAGNOSTIC: Recent Trade Execution Analysis")
    print("=" * 80)
    print()
    
    # Parse trade logs
    print("1. Parsing trade execution logs...")
    trade_logs = parse_trade_logs(log_path)
    print(f"   Found {len(trade_logs)} trade-related log entries")
    print()
    
    # Analyze trade sequence
    print("2. Analyzing trade sequence...")
    sequence_issues = analyze_trade_sequence(trade_logs)
    
    if sequence_issues:
        print(f"   FOUND {len(sequence_issues)} TRADE SEQUENCE ISSUES:")
        print()
        for issue in sequence_issues:
            print(f"   Ticker: {issue['ticker']}")
            print(f"   Issue: {issue['issue']}")
            print(f"   Trades: {issue['trades']}")
            print(f"   Sample lines:")
            for line in issue['lines'][:3]:
                print(f"     {line[:120]}...")
            print()
    else:
        print("   No trade sequence issues found")
    print()
    
    # Check price consistency
    print("3. Checking price consistency...")
    price_issues = check_price_consistency(trade_logs)
    
    if price_issues:
        print(f"   FOUND {len(price_issues)} PRICE CONSISTENCY ISSUES:")
        print()
        for issue in price_issues:
            print(f"   Issue: {issue['issue']}")
            print(f"   Price: {issue['price_cents']}c")
            print(f"   Expected: {issue['expected_range']}")
            print(f"   Line: {issue['line'][:120]}...")
            print()
    else:
        print("   No price consistency issues found")
    print()
    
    # Display last 2 trades
    print("4. Last 2 trade executions:")
    print()
    if trade_logs:
        # Sort by timestamp and get last 2
        trade_logs.sort(key=lambda x: x['timestamp'] or datetime.min)
        recent_trades = trade_logs[-2:]
        
        for i, trade in enumerate(recent_trades, 1):
            print(f"   Trade {i}:")
            print(f"   {trade['line'][:150]}...")
            print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Trade sequence issues: {len(sequence_issues)}")
    print(f"Price consistency issues: {len(price_issues)}")
    print()
    
    if sequence_issues or price_issues:
        print("ISSUES FOUND - INVESTIGATION REQUIRED")
        sys.exit(1)
    else:
        print("No issues found - trade execution appears correct")
        sys.exit(0)

if __name__ == '__main__':
    main()
