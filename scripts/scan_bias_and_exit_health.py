"""
Bias and Exit Health Log Scanner (2026-07-24)

This script scans live logs for bias and exit health issues:
- Markets where signal.side=NO but no NO orders were ever sent
- Any [EXIT-INVARIANT-VIOLATION]
- Any case where post_size >= pre_size on an EXIT path

Usage:
    python scripts/scan_bias_and_exit_health.py <log_file_path> [--output json|csv] [--output-file <path>]

This script becomes the "bias and exit health" check that can be run after
long 12-15 hour audits or as part of CI against recorded traces.

Output Schema (JSON):
{
    "scan_timestamp": "2026-07-24T12:00:00Z",
    "log_file": "path/to/log.txt",
    "summary": {
        "total_issues": 0,
        "exit_invariant_violations": 0,
        "exit_post_size_issues": 0,
        "bias_issues": 0
    },
    "assets": {
        "BTC": {
            "no_signals_seen": 10,
            "no_orders_sent": 10,
            "yes_signals_seen": 5,
            "yes_orders_sent": 5,
            "exit_invariant_violations": 0,
            "exit_post_size_issues": 0,
            "bias_issues": 0
        },
        "ETH": { ... },
        "SOL": { ... },
        "XRP": { ... },
        "DOGE": { ... }
    },
    "issues": [
        {
            "type": "EXIT-INVARIANT-VIOLATION",
            "timestamp": "2026-07-24T12:00:00Z",
            "line_num": 1234,
            "market_id": "KXBTC15M-26JUL211745-45",
            "position_id": "abc123",
            "details": "..."
        }
    ]
}

Output Schema (CSV):
timestamp,asset,no_signals_seen,no_orders_sent,yes_signals_seen,yes_orders_sent,exit_invariant_violations,exit_post_size_issues,bias_issues
2026-07-24T12:00:00Z,BTC,10,10,5,5,0,0,0
2026-07-24T12:00:00Z,ETH,8,8,6,6,0,0,0
...
"""

import re
import sys
import json
import csv
from pathlib import Path
from typing import List, Dict, Set, Tuple
from collections import defaultdict
from datetime import datetime


class BiasAndExitHealthScanner:
    """Scanner for bias and exit health issues in log files."""
    
    # Asset mapping from market_id prefix to asset name
    ASSET_MAPPING = {
        "KXBTC": "BTC",
        "KXETH": "ETH",
        "KXSOL": "SOL",
        "KXXRP": "XRP",
        "KXDOGE": "DOGE"
    }
    
    def __init__(self, log_file_path: str):
        self.log_file_path = Path(log_file_path)
        self.issues: List[Dict] = []
        
        # Track signal → order mapping
        self.signal_side_by_market: Dict[str, str] = {}
        self.order_side_by_market: Dict[str, Set[str]] = defaultdict(set)
        
        # Track exit invariants
        self.exit_invariant_violations: List[Dict] = []
        self.exit_post_size_issues: List[Dict] = []
        
        # Per-asset metrics
        self.asset_metrics: Dict[str, Dict] = {
            "BTC": {
                "no_signals_seen": 0,
                "no_orders_sent": 0,
                "yes_signals_seen": 0,
                "yes_orders_sent": 0,
                "exit_invariant_violations": 0,
                "exit_post_size_issues": 0,
                "bias_issues": 0
            },
            "ETH": {
                "no_signals_seen": 0,
                "no_orders_sent": 0,
                "yes_signals_seen": 0,
                "yes_orders_sent": 0,
                "exit_invariant_violations": 0,
                "exit_post_size_issues": 0,
                "bias_issues": 0
            },
            "SOL": {
                "no_signals_seen": 0,
                "no_orders_sent": 0,
                "yes_signals_seen": 0,
                "yes_orders_sent": 0,
                "exit_invariant_violations": 0,
                "exit_post_size_issues": 0,
                "bias_issues": 0
            },
            "XRP": {
                "no_signals_seen": 0,
                "no_orders_sent": 0,
                "yes_signals_seen": 0,
                "yes_orders_sent": 0,
                "exit_invariant_violations": 0,
                "exit_post_size_issues": 0,
                "bias_issues": 0
            },
            "DOGE": {
                "no_signals_seen": 0,
                "no_orders_sent": 0,
                "yes_signals_seen": 0,
                "yes_orders_sent": 0,
                "exit_invariant_violations": 0,
                "exit_post_size_issues": 0,
                "bias_issues": 0
            }
        }
        
    def _get_asset_from_market_id(self, market_id: str) -> str:
        """Extract asset name from market_id."""
        for prefix, asset in self.ASSET_MAPPING.items():
            if market_id.startswith(prefix):
                return asset
        return "UNKNOWN"
        
    def scan(self) -> bool:
        """Scan the log file for bias and exit health issues.
        
        Returns:
            True if no critical issues found, False otherwise
        """
        if not self.log_file_path.exists():
            print(f"ERROR: Log file not found: {self.log_file_path}")
            return False
        
        print(f"Scanning log file: {self.log_file_path}")
        print("=" * 80)
        
        with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                self._scan_line(line, line_num)
        
        self._populate_asset_metrics()
        self._analyze_results()
        return len(self.exit_invariant_violations) == 0
    
    def _scan_line(self, line: str, line_num: int):
        """Scan a single log line for issues."""
        # Check for EXIT-INVARIANT-VIOLATION
        if "[EXIT-INVARIANT-VIOLATION]" in line:
            self._parse_exit_invariant_violation(line, line_num)
        
        # Check for exit post_size >= pre_size
        if "entry_or_exit=exit" in line and "pre_position_size" in line and "expected_post_position_size" in line:
            self._parse_exit_post_size(line, line_num)
        
        # Check for signal side
        if "signal_side=" in line:
            self._parse_signal_side(line)
        
        # Check for order side
        if "kalshi_side=" in line and "kalshi_action=buy" in line:
            self._parse_order_side(line)
    
    def _parse_exit_invariant_violation(self, line: str, line_num: int):
        """Parse EXIT-INVARIANT-VIOLATION log entry."""
        market_id = self._extract_field(line, "ticker=")
        asset = self._get_asset_from_market_id(market_id)
        
        violation = {
            "line_num": line_num,
            "line": line.strip(),
            "timestamp": self._extract_timestamp(line),
            "market_id": market_id,
            "asset": asset,
            "position_id": self._extract_field(line, "position_id="),
            "type": "EXIT-INVARIANT-VIOLATION"
        }
        self.exit_invariant_violations.append(violation)
        
        # Update asset metrics
        if asset in self.asset_metrics:
            self.asset_metrics[asset]["exit_invariant_violations"] += 1
    
    def _parse_exit_post_size(self, line: str, line_num: int):
        """Parse exit order and check for post_size >= pre_size."""
        pre_size = self._extract_field(line, "pre_position_size=")
        post_size = self._extract_field(line, "expected_post_position_size=")
        market_id = self._extract_field(line, "ticker=")
        asset = self._get_asset_from_market_id(market_id)
        
        if pre_size and post_size:
            try:
                pre = int(pre_size)
                post = int(post_size)
                
                if post >= pre:
                    issue = {
                        "line_num": line_num,
                        "line": line.strip(),
                        "timestamp": self._extract_timestamp(line),
                        "market_id": market_id,
                        "asset": asset,
                        "pre_size": pre,
                        "post_size": post,
                        "type": "EXIT-POST-SIZE-ISSUE"
                    }
                    self.exit_post_size_issues.append(issue)
                    
                    # Update asset metrics
                    if asset in self.asset_metrics:
                        self.asset_metrics[asset]["exit_post_size_issues"] += 1
            except (ValueError, TypeError):
                pass
    
    def _parse_signal_side(self, line: str):
        """Parse signal side from log line."""
        market_id = self._extract_field(line, "market_id=")
        signal_side = self._extract_field(line, "signal_side=")
        asset = self._get_asset_from_market_id(market_id)
        
        if market_id and signal_side:
            self.signal_side_by_market[market_id] = signal_side
            
            # Update asset metrics
            if asset in self.asset_metrics:
                if signal_side == "no":
                    self.asset_metrics[asset]["no_signals_seen"] += 1
                elif signal_side == "yes":
                    self.asset_metrics[asset]["yes_signals_seen"] += 1
    
    def _parse_order_side(self, line: str):
        """Parse order side from log line."""
        market_id = self._extract_field(line, "market_id=")
        kalshi_side = self._extract_field(line, "kalshi_side=")
        asset = self._get_asset_from_market_id(market_id)
        
        if market_id and kalshi_side:
            # Extract outcome side from kalshi_side (BUY_YES -> yes, BUY_NO -> no)
            if kalshi_side == "BUY_YES":
                outcome_side = "yes"
            elif kalshi_side == "BUY_NO":
                outcome_side = "no"
            else:
                outcome_side = kalshi_side
            
            self.order_side_by_market[market_id].add(outcome_side)
            
            # Update asset metrics
            if asset in self.asset_metrics:
                if outcome_side == "no":
                    self.asset_metrics[asset]["no_orders_sent"] += 1
                elif outcome_side == "yes":
                    self.asset_metrics[asset]["yes_orders_sent"] += 1
    
    def _extract_field(self, line: str, field: str) -> str:
        """Extract a field value from a log line."""
        pattern = rf"{field}(\S+)"
        match = re.search(pattern, line)
        if match:
            return match.group(1)
        return ""
    
    def _extract_timestamp(self, line: str) -> str:
        """Extract timestamp from log line."""
        # Assume timestamp is at the start of the line
        # Format: 2026-07-24 12:00:00
        match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
        if match:
            return match.group(1)
        return ""
    
    def _populate_asset_metrics(self):
        """Populate asset metrics from collected data."""
        # Check for bias issues per asset
        for market_id, signal_side in self.signal_side_by_market.items():
            asset = self._get_asset_from_market_id(market_id)
            if signal_side == "no":
                order_sides = self.order_side_by_market.get(market_id, set())
                if "no" not in order_sides and asset in self.asset_metrics:
                    self.asset_metrics[asset]["bias_issues"] += 1
    
    def _analyze_results(self):
        """Analyze scan results and report issues."""
        print("\n" + "=" * 80)
        print("SCAN RESULTS")
        print("=" * 80)
        
        # Report EXIT-INVARIANT-VIOLATION
        if self.exit_invariant_violations:
            print(f"\n❌ CRITICAL: Found {len(self.exit_invariant_violations)} EXIT-INVARIANT-VIOLATION entries")
            print("-" * 80)
            for violation in self.exit_invariant_violations:
                print(f"  Line {violation['line_num']}: {violation['timestamp']}")
                print(f"    Market: {violation['market_id']} ({violation['asset']})")
                print(f"    Position: {violation['position_id']}")
                print(f"    {violation['line'][:100]}...")
        else:
            print("\n✅ No EXIT-INVARIANT-VIOLATION entries found")
        
        # Report exit post_size issues
        if self.exit_post_size_issues:
            print(f"\n❌ CRITICAL: Found {len(self.exit_post_size_issues)} exit post_size >= pre_size issues")
            print("-" * 80)
            for issue in self.exit_post_size_issues:
                print(f"  Line {issue['line_num']}: {issue['timestamp']}")
                print(f"    Market: {issue['market_id']} ({issue['asset']})")
                print(f"    Pre-size: {issue['pre_size']}, Post-size: {issue['post_size']}")
                print(f"    {issue['line'][:100]}...")
        else:
            print("\n✅ No exit post_size >= pre_size issues found")
        
        # Report bias issues (signal=NO but no NO orders)
        bias_issues = self._check_bias_issues()
        if bias_issues:
            print(f"\n❌ CRITICAL: Found {len(bias_issues)} bias issues (signal=NO but no NO orders)")
            print("-" * 80)
            for market_id in bias_issues:
                signal_side = self.signal_side_by_market.get(market_id, "unknown")
                order_sides = self.order_side_by_market.get(market_id, set())
                asset = self._get_asset_from_market_id(market_id)
                print(f"  Market: {market_id} ({asset})")
                print(f"    Signal side: {signal_side}")
                print(f"    Order sides: {order_sides}")
                print(f"    Expected NO orders but found: {order_sides}")
        else:
            print("\n✅ No bias issues found (signal=NO markets have NO orders)")
        
        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        total_issues = len(self.exit_invariant_violations) + len(self.exit_post_size_issues) + len(bias_issues)
        if total_issues == 0:
            print("✅ ALL CHECKS PASSED - No bias or exit health issues detected")
        else:
            print(f"❌ {total_issues} ISSUES DETECTED")
            print(f"   - EXIT-INVARIANT-VIOLATION: {len(self.exit_invariant_violations)}")
            print(f"   - Exit post_size issues: {len(self.exit_post_size_issues)}")
            print(f"   - Bias issues: {len(bias_issues)}")
    
    def _check_bias_issues(self) -> List[str]:
        """Check for markets where signal=NO but no NO orders were sent."""
        bias_issues = []
        
        for market_id, signal_side in self.signal_side_by_market.items():
            if signal_side == "no":
                order_sides = self.order_side_by_market.get(market_id, set())
                if "no" not in order_sides:
                    bias_issues.append(market_id)
        
        return bias_issues
    
    def to_json(self) -> str:
        """Convert scan results to JSON format."""
        bias_issues = self._check_bias_issues()
        
        result = {
            "scan_timestamp": datetime.utcnow().isoformat() + "Z",
            "log_file": str(self.log_file_path),
            "summary": {
                "total_issues": len(self.exit_invariant_violations) + len(self.exit_post_size_issues) + len(bias_issues),
                "exit_invariant_violations": len(self.exit_invariant_violations),
                "exit_post_size_issues": len(self.exit_post_size_issues),
                "bias_issues": len(bias_issues)
            },
            "assets": self.asset_metrics,
            "issues": self.exit_invariant_violations + self.exit_post_size_issues
        }
        
        return json.dumps(result, indent=2)
    
    def to_csv(self) -> str:
        """Convert scan results to CSV format."""
        output = []
        output.append("timestamp,asset,no_signals_seen,no_orders_sent,yes_signals_seen,yes_orders_sent,exit_invariant_violations,exit_post_size_issues,bias_issues")
        
        scan_timestamp = datetime.utcnow().isoformat() + "Z"
        
        for asset, metrics in self.asset_metrics.items():
            row = [
                scan_timestamp,
                asset,
                str(metrics["no_signals_seen"]),
                str(metrics["no_orders_sent"]),
                str(metrics["yes_signals_seen"]),
                str(metrics["yes_orders_sent"]),
                str(metrics["exit_invariant_violations"]),
                str(metrics["exit_post_size_issues"]),
                str(metrics["bias_issues"])
            ]
            output.append(",".join(row))
        
        return "\n".join(output)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/scan_bias_and_exit_health.py <log_file_path> [--output json|csv] [--output-file <path>]")
        print("\nThis script scans log files for:")
        print("  - Markets where signal.side=NO but no NO orders were ever sent")
        print("  - Any [EXIT-INVARIANT-VIOLATION]")
        print("  - Any case where post_size >= pre_size on an EXIT path")
        print("\nOptions:")
        print("  --output json|csv  Output format (default: text)")
        print("  --output-file <path>  Write output to file (default: stdout)")
        sys.exit(1)
    
    log_file_path = sys.argv[1]
    output_format = "text"
    output_file = None
    
    # Parse optional arguments
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--output":
            if i + 1 < len(sys.argv):
                output_format = sys.argv[i + 1].lower()
                i += 2
            else:
                print("ERROR: --output requires a format (json or csv)")
                sys.exit(1)
        elif sys.argv[i] == "--output-file":
            if i + 1 < len(sys.argv):
                output_file = sys.argv[i + 1]
                i += 2
            else:
                print("ERROR: --output-file requires a path")
                sys.exit(1)
        else:
            i += 1
    
    scanner = BiasAndExitHealthScanner(log_file_path)
    success = scanner.scan()
    
    # Output results
    if output_format == "json":
        output = scanner.to_json()
    elif output_format == "csv":
        output = scanner.to_csv()
    else:
        # Default text output already printed by scanner.scan()
        output = None
    
    if output:
        if output_file:
            with open(output_file, 'w') as f:
                f.write(output)
            print(f"\nOutput written to: {output_file}")
        else:
            print(output)
    
    # Exit with error code if issues found
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
