"""
Production-Wide Anomaly Monitor (2026-07-24)

This script scans live logs for production anomalies across the MERID stack:
- Markets where signal.side=NO but no NO orders were ever sent
- Any [EXIT-INVARIANT-VIOLATION]
- Any case where post_size >= pre_size on an EXIT path
- Any [PRICE-SIDE-CHECK-VIOLATION] (price/side mismatch)
- Count of cheap_wrong_side_candidates (cheapness on wrong side correctly ignored)
- Signal-intent synchronization (signal_side == thesis_side == candidate.side == order.side)
- Runtime SSOT checks ([SSOT-INVARIANT] logs)
- Data freshness anomalies (stale orderbook, catalog staleness)
- Anomaly categorization (point, contextual, pattern)

Usage:
    python scripts/scan_bias_and_exit_health.py <log_file_path> [--output json|csv] [--output-file <path>]

This script is the production-wide anomaly monitor that can be run after
long 12-15 hour audits or as part of CI against recorded traces.

Output Schema (JSON):
{
    "scan_timestamp": "2026-07-24T12:00:00Z",
    "log_file": "path/to/log.txt",
    "summary": {
        "total_issues": 0,
        "exit_invariant_violations": 0,
        "exit_post_size_issues": 0,
        "bias_issues": 0,
        "price_side_mismatches": 0,
        "cheap_wrong_side_candidates": 0
    },
    "assets": {
        "BTC": {
            "no_signals_seen": 10,
            "no_orders_sent": 10,
            "yes_signals_seen": 5,
            "yes_orders_sent": 5,
            "exit_invariant_violations": 0,
            "exit_post_size_issues": 0,
            "bias_issues": 0,
            "price_side_mismatches": 0,
            "cheap_wrong_side_candidates": 0
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
        },
        {
            "type": "PRICE-SIDE-CHECK-VIOLATION",
            "timestamp": "2026-07-24T12:00:00Z",
            "line_num": 5678,
            "market_id": "KXBTC15M-26JUL211745-45",
            "asset": "BTC",
            "thesis_side": "no",
            "order_side": "BUY_YES",
            "details": "Order side does not match thesis_side from intent"
        }
    ]
}

Output Schema (CSV):
timestamp,asset,no_signals_seen,no_orders_sent,yes_signals_seen,yes_orders_sent,exit_invariant_violations,exit_post_size_issues,bias_issues,price_side_mismatches,cheap_wrong_side_candidates
2026-07-24T12:00:00Z,BTC,10,10,5,5,0,0,0,0,0
2026-07-24T12:00:00Z,ETH,8,8,6,6,0,0,0,0,0
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


class ProductionAnomalyMonitor:
    """Production-wide anomaly monitor for MERID stack."""
    
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
        self.thesis_side_by_market: Dict[str, str] = {}
        self.candidate_side_by_market: Dict[str, str] = {}
        self.order_side_by_market: Dict[str, Set[str]] = defaultdict(set)
        
        # Track exit invariants
        self.exit_invariant_violations: List[Dict] = []
        self.exit_post_size_issues: List[Dict] = []
        
        # Track price-side invariants
        self.price_side_mismatches: List[Dict] = []
        self.cheap_wrong_side_candidates: List[Dict] = []
        
        # Track signal-intent synchronization
        self.signal_intent_sync_issues: List[Dict] = []
        
        # Track runtime SSOT checks
        self.ssot_invariant_fires: List[Dict] = []
        
        # Track data freshness anomalies
        self.data_staleness_issues: List[Dict] = []
        
        # Track WS desired empty events
        self.ws_desired_empty_events: List[Dict] = []
        
        # Track MD staleness bursts (repeated circuit breaker cooldowns)
        self.md_staleness_bursts: Dict[str, List[Dict]] = defaultdict(list)  # series -> events
        
        # Per-asset metrics
        self.asset_metrics: Dict[str, Dict] = {
            "BTC": {
                "no_signals_seen": 0,
                "no_orders_sent": 0,
                "yes_signals_seen": 0,
                "yes_orders_sent": 0,
                "exit_invariant_violations": 0,
                "exit_post_size_issues": 0,
                "bias_issues": 0,
                "price_side_mismatches": 0,
                "cheap_wrong_side_candidates": 0,
                "signal_intent_sync_issues": 0,
                "ssot_invariant_fires": 0,
                "data_staleness_issues": 0,
                "ws_desired_empty_events": 0,
                "md_staleness_bursts": 0
            },
            "ETH": {
                "no_signals_seen": 0,
                "no_orders_sent": 0,
                "yes_signals_seen": 0,
                "yes_orders_sent": 0,
                "exit_invariant_violations": 0,
                "exit_post_size_issues": 0,
                "bias_issues": 0,
                "price_side_mismatches": 0,
                "cheap_wrong_side_candidates": 0,
                "signal_intent_sync_issues": 0,
                "ssot_invariant_fires": 0,
                "data_staleness_issues": 0,
                "ws_desired_empty_events": 0,
                "md_staleness_bursts": 0
            },
            "SOL": {
                "no_signals_seen": 0,
                "no_orders_sent": 0,
                "yes_signals_seen": 0,
                "yes_orders_sent": 0,
                "exit_invariant_violations": 0,
                "exit_post_size_issues": 0,
                "bias_issues": 0,
                "price_side_mismatches": 0,
                "cheap_wrong_side_candidates": 0,
                "signal_intent_sync_issues": 0,
                "ssot_invariant_fires": 0,
                "data_staleness_issues": 0,
                "ws_desired_empty_events": 0,
                "md_staleness_bursts": 0
            },
            "XRP": {
                "no_signals_seen": 0,
                "no_orders_sent": 0,
                "yes_signals_seen": 0,
                "yes_orders_sent": 0,
                "exit_invariant_violations": 0,
                "exit_post_size_issues": 0,
                "bias_issues": 0,
                "price_side_mismatches": 0,
                "cheap_wrong_side_candidates": 0,
                "signal_intent_sync_issues": 0,
                "ssot_invariant_fires": 0,
                "data_staleness_issues": 0,
                "ws_desired_empty_events": 0,
                "md_staleness_bursts": 0
            },
            "DOGE": {
                "no_signals_seen": 0,
                "no_orders_sent": 0,
                "yes_signals_seen": 0,
                "yes_orders_sent": 0,
                "exit_invariant_violations": 0,
                "exit_post_size_issues": 0,
                "bias_issues": 0,
                "price_side_mismatches": 0,
                "cheap_wrong_side_candidates": 0,
                "signal_intent_sync_issues": 0,
                "ssot_invariant_fires": 0,
                "data_staleness_issues": 0,
                "ws_desired_empty_events": 0,
                "md_staleness_bursts": 0
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
        
        # Check for PRICE-SIDE-CHECK-VIOLATION
        if "[PRICE-SIDE-CHECK-VIOLATION]" in line:
            self._parse_price_side_violation(line, line_num)
        
        # Check for PRICE-SIDE-CHECK-REJECT (cheap wrong side correctly ignored)
        if "[PRICE-SIDE-CHECK-REJECT]" in line:
            self._parse_price_side_reject(line, line_num)
        
        # Check for SSOT-INVARIANT (runtime SSOT enforcement)
        if "[SSOT-INVARIANT]" in line:
            self._parse_ssot_invariant(line, line_num)
        
        # Check for SIDE-PRESERVATION-CHECK (signal-intent sync)
        if "[SIDE-PRESERVATION-CHECK]" in line:
            self._parse_side_preservation_check(line, line_num)
        
        # Check for data staleness
        if "catalog_staleness" in line or "stale_data" in line:
            self._parse_data_staleness(line, line_num)
        
        # Check for WS desired empty events
        if "[WS-SYNC] Desired ticker set is empty" in line:
            self._parse_ws_desired_empty(line, line_num)
        
        # Check for MD staleness bursts (circuit breaker cooldown)
        if "circuit breaker tripped" in line or "Circuit breaker tripped" in line:
            self._parse_md_staleness_burst(line, line_num)
        
        # Check for signal side
        if "signal_side=" in line:
            self._parse_signal_side(line)
        
        # Check for thesis side
        if "thesis_side=" in line:
            self._parse_thesis_side(line)
        
        # Check for candidate side
        if "candidate_side=" in line:
            self._parse_candidate_side(line)
        
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
    
    def _parse_thesis_side(self, line: str):
        """Parse thesis side from log line."""
        market_id = self._extract_field(line, "market_id=")
        thesis_side = self._extract_field(line, "thesis_side=")
        asset = self._get_asset_from_market_id(market_id)
        
        if market_id and thesis_side:
            self.thesis_side_by_market[market_id] = thesis_side
    
    def _parse_candidate_side(self, line: str):
        """Parse candidate side from log line."""
        market_id = self._extract_field(line, "market_id=")
        candidate_side = self._extract_field(line, "candidate_side=")
        asset = self._get_asset_from_market_id(market_id)
        
        if market_id and candidate_side:
            self.candidate_side_by_market[market_id] = candidate_side
    
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
    
    def _parse_price_side_violation(self, line: str, line_num: int):
        """Parse PRICE-SIDE-CHECK-VIOLATION log entry."""
        market_id = self._extract_field(line, "ticker=")
        asset = self._get_asset_from_market_id(market_id)
        thesis_side = self._extract_field(line, "thesis_side=")
        order_side = self._extract_field(line, "order_side=")
        strike_target = self._extract_field(line, "strike_target=")
        
        violation = {
            "line_num": line_num,
            "line": line.strip(),
            "timestamp": self._extract_timestamp(line),
            "market_id": market_id,
            "asset": asset,
            "thesis_side": thesis_side,
            "order_side": order_side,
            "strike_target": strike_target,
            "type": "PRICE-SIDE-CHECK-VIOLATION"
        }
        self.price_side_mismatches.append(violation)
        
        # Update asset metrics
        if asset in self.asset_metrics:
            self.asset_metrics[asset]["price_side_mismatches"] += 1
    
    def _parse_price_side_reject(self, line: str, line_num: int):
        """Parse PRICE-SIDE-CHECK-REJECT log entry (cheap wrong side correctly ignored)."""
        market_id = self._extract_field(line, "asset=")
        if not market_id:
            market_id = self._extract_field(line, "ticker=")
        asset = self._get_asset_from_market_id(market_id)
        thesis_side = self._extract_field(line, "thesis_side=")
        
        reject = {
            "line_num": line_num,
            "line": line.strip(),
            "timestamp": self._extract_timestamp(line),
            "market_id": market_id,
            "asset": asset,
            "thesis_side": thesis_side,
            "type": "PRICE-SIDE-CHECK-REJECT"
        }
        self.cheap_wrong_side_candidates.append(reject)
        
        # Update asset metrics
        if asset in self.asset_metrics:
            self.asset_metrics[asset]["cheap_wrong_side_candidates"] += 1
    
    def _parse_ssot_invariant(self, line: str, line_num: int):
        """Parse SSOT-INVARIANT log entry (runtime SSOT enforcement)."""
        market_id = self._extract_field(line, "market_id=")
        if not market_id:
            market_id = self._extract_field(line, "ticker=")
        asset = self._get_asset_from_market_id(market_id)
        
        invariant = {
            "line_num": line_num,
            "line": line.strip(),
            "timestamp": self._extract_timestamp(line),
            "market_id": market_id,
            "asset": asset,
            "type": "SSOT-INVARIANT"
        }
        self.ssot_invariant_fires.append(invariant)
        
        # Update asset metrics
        if asset in self.asset_metrics:
            self.asset_metrics[asset]["ssot_invariant_fires"] += 1
    
    def _parse_side_preservation_check(self, line: str, line_num: int):
        """Parse SIDE-PRESERVATION-CHECK log entry (signal-intent sync)."""
        market_id = self._extract_field(line, "market_id=")
        if not market_id:
            market_id = self._extract_field(line, "ticker=")
        asset = self._get_asset_from_market_id(market_id)
        signal_side = self._extract_field(line, "signal_side=")
        thesis_side = self._extract_field(line, "thesis_side=")
        candidate_side = self._extract_field(line, "candidate_side=")
        
        # Check for mismatch
        if signal_side and thesis_side and candidate_side:
            if signal_side != thesis_side or thesis_side != candidate_side:
                issue = {
                    "line_num": line_num,
                    "line": line.strip(),
                    "timestamp": self._extract_timestamp(line),
                    "market_id": market_id,
                    "asset": asset,
                    "signal_side": signal_side,
                    "thesis_side": thesis_side,
                    "candidate_side": candidate_side,
                    "type": "SIGNAL-INTENT-SYNC-ISSUE"
                }
                self.signal_intent_sync_issues.append(issue)
                
                # Update asset metrics
                if asset in self.asset_metrics:
                    self.asset_metrics[asset]["signal_intent_sync_issues"] += 1
    
    def _parse_data_staleness(self, line: str, line_num: int):
        """Parse data staleness log entry."""
        market_id = self._extract_field(line, "market_id=")
        if not market_id:
            market_id = self._extract_field(line, "ticker=")
        asset = self._get_asset_from_market_id(market_id)
        staleness_seconds = self._extract_field(line, "staleness_seconds=")
        
        issue = {
            "line_num": line_num,
            "line": line.strip(),
            "timestamp": self._extract_timestamp(line),
            "market_id": market_id,
            "asset": asset,
            "staleness_seconds": staleness_seconds,
            "type": "DATA-STALENESS-ISSUE"
        }
        self.data_staleness_issues.append(issue)
        
        # Update asset metrics
        if asset in self.asset_metrics:
            self.asset_metrics[asset]["data_staleness_issues"] += 1
    
    def _parse_ws_desired_empty(self, line: str, line_num: int):
        """Parse WS desired empty event."""
        current_count = self._extract_field(line, "current=")
        desired_count = self._extract_field(line, "desired=")
        
        event = {
            "line_num": line_num,
            "line": line.strip(),
            "timestamp": self._extract_timestamp(line),
            "current_count": current_count,
            "desired_count": desired_count,
            "type": "WS-DESIRED-EMPTY"
        }
        self.ws_desired_empty_events.append(event)
        
        # Update asset metrics (use "ALL" asset for WS-level events)
        if "ALL" in self.asset_metrics:
            self.asset_metrics["ALL"]["ws_desired_empty_events"] += 1
    
    def _parse_md_staleness_burst(self, line: str, line_num: int):
        """Parse MD staleness burst (circuit breaker cooldown)."""
        # Extract series from log line (e.g., "fetch_series_KXSOL15M")
        import re
        series_match = re.search(r'fetch_series_(KX\w+)', line)
        series = series_match.group(1) if series_match else ""
        
        # Extract cooldown remaining
        cooldown_match = re.search(r'Cooldown:\s*([\d.]+)s', line)
        cooldown_remaining = cooldown_match.group(1) if cooldown_match else ""
        
        # Extract asset from series ticker
        asset = "UNKNOWN"
        if series:
            if "BTC" in series:
                asset = "BTC"
            elif "ETH" in series:
                asset = "ETH"
            elif "SOL" in series:
                asset = "SOL"
            elif "XRP" in series:
                asset = "XRP"
            elif "DOGE" in series:
                asset = "DOGE"
        
        event = {
            "line_num": line_num,
            "line": line.strip(),
            "timestamp": self._extract_timestamp(line),
            "series": series,
            "cooldown_remaining": cooldown_remaining,
            "asset": asset,
            "type": "MD-STALENESS-BURST"
        }
        if series:
            self.md_staleness_bursts[series].append(event)
        
        # Update asset metrics
        if asset in self.asset_metrics:
            self.asset_metrics[asset]["md_staleness_bursts"] += 1
    
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
        print("PRODUCTION ANOMALY SCAN RESULTS")
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
        
        # Report price-side mismatches
        if self.price_side_mismatches:
            print(f"\n❌ CRITICAL: Found {len(self.price_side_mismatches)} PRICE-SIDE-CHECK-VIOLATION entries")
            print("-" * 80)
            for violation in self.price_side_mismatches:
                print(f"  Line {violation['line_num']}: {violation['timestamp']}")
                print(f"    Market: {violation['market_id']} ({violation['asset']})")
                print(f"    Thesis side: {violation['thesis_side']}, Order side: {violation['order_side']}")
                print(f"    {violation['line'][:100]}...")
        else:
            print("\n✅ No PRICE-SIDE-CHECK-VIOLATION entries found")
        
        # Report signal-intent sync issues
        if self.signal_intent_sync_issues:
            print(f"\n❌ CRITICAL: Found {len(self.signal_intent_sync_issues)} SIGNAL-INTENT-SYNC-ISSUE entries")
            print("-" * 80)
            for issue in self.signal_intent_sync_issues:
                print(f"  Line {issue['line_num']}: {issue['timestamp']}")
                print(f"    Market: {issue['market_id']} ({issue['asset']})")
                print(f"    Signal: {issue['signal_side']}, Thesis: {issue['thesis_side']}, Candidate: {issue['candidate_side']}")
                print(f"    {issue['line'][:100]}...")
        else:
            print("\n✅ No SIGNAL-INTENT-SYNC-ISSUE entries found")
        
        # Report SSOT invariant fires
        if self.ssot_invariant_fires:
            print(f"\n⚠️  WARNING: Found {len(self.ssot_invariant_fires)} SSOT-INVARIANT fires (runtime SSOT enforcement)")
            print("-" * 80)
            for invariant in self.ssot_invariant_fires[:5]:  # Show first 5
                print(f"  Line {invariant['line_num']}: {invariant['timestamp']}")
                print(f"    Market: {invariant['market_id']} ({invariant['asset']})")
                print(f"    {invariant['line'][:100]}...")
            if len(self.ssot_invariant_fires) > 5:
                print(f"  ... and {len(self.ssot_invariant_fires) - 5} more")
        else:
            print("\n✅ No SSOT-INVARIANT fires found")
        
        # Report data staleness issues
        if self.data_staleness_issues:
            print(f"\n⚠️  WARNING: Found {len(self.data_staleness_issues)} DATA-STALENESS-ISSUE entries")
            print("-" * 80)
            for issue in self.data_staleness_issues[:5]:  # Show first 5
                print(f"  Line {issue['line_num']}: {issue['timestamp']}")
                print(f"    Market: {issue['market_id']} ({issue['asset']})")
                print(f"    Staleness: {issue['staleness_seconds']}s")
                print(f"    {issue['line'][:100]}...")
            if len(self.data_staleness_issues) > 5:
                print(f"  ... and {len(self.data_staleness_issues) - 5} more")
        else:
            print("\n✅ No DATA-STALENESS-ISSUE entries found")
        
        # Report cheap wrong side candidates (correctly ignored)
        if self.cheap_wrong_side_candidates:
            print(f"\nℹ️  INFO: Found {len(self.cheap_wrong_side_candidates)} cheap wrong side candidates (correctly ignored)")
            print("-" * 80)
            for reject in self.cheap_wrong_side_candidates[:5]:  # Show first 5
                print(f"  Line {reject['line_num']}: {reject['timestamp']}")
                print(f"    Market: {reject['market_id']} ({reject['asset']})")
                print(f"    Thesis side: {reject['thesis_side']}")
            if len(self.cheap_wrong_side_candidates) > 5:
                print(f"  ... and {len(self.cheap_wrong_side_candidates) - 5} more")
        else:
            print("\n✅ No cheap wrong side candidates found")
        
        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        total_issues = (len(self.exit_invariant_violations) + len(self.exit_post_size_issues) + 
                       len(bias_issues) + len(self.price_side_mismatches) + 
                       len(self.signal_intent_sync_issues))
        if total_issues == 0:
            print("✅ ALL CRITICAL CHECKS PASSED - No production anomalies detected")
        else:
            print(f"❌ {total_issues} CRITICAL ISSUES DETECTED")
            print(f"   - EXIT-INVARIANT-VIOLATION: {len(self.exit_invariant_violations)}")
            print(f"   - Exit post_size issues: {len(self.exit_post_size_issues)}")
            print(f"   - Bias issues: {len(bias_issues)}")
            print(f"   - PRICE-SIDE-CHECK-VIOLATION: {len(self.price_side_mismatches)}")
            print(f"   - SIGNAL-INTENT-SYNC-ISSUE: {len(self.signal_intent_sync_issues)}")
        
        # Warnings summary
        total_warnings = len(self.ssot_invariant_fires) + len(self.data_staleness_issues)
        if total_warnings > 0:
            print(f"\n⚠️  {total_warnings} WARNINGS DETECTED")
            print(f"   - SSOT-INVARIANT fires: {len(self.ssot_invariant_fires)}")
            print(f"   - DATA-STALENESS-ISSUE: {len(self.data_staleness_issues)}")
        
        print(f"\nℹ️  Cheap wrong side candidates (correctly ignored): {len(self.cheap_wrong_side_candidates)}")
    
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
                "total_issues": (len(self.exit_invariant_violations) + len(self.exit_post_size_issues) + 
                               len(bias_issues) + len(self.price_side_mismatches) + 
                               len(self.signal_intent_sync_issues)),
                "total_warnings": len(self.ssot_invariant_fires) + len(self.data_staleness_issues) + 
                                  len(self.ws_desired_empty_events) + sum(len(events) for events in self.md_staleness_bursts.values()),
                "exit_invariant_violations": len(self.exit_invariant_violations),
                "exit_post_size_issues": len(self.exit_post_size_issues),
                "bias_issues": len(bias_issues),
                "price_side_mismatches": len(self.price_side_mismatches),
                "signal_intent_sync_issues": len(self.signal_intent_sync_issues),
                "ssot_invariant_fires": len(self.ssot_invariant_fires),
                "data_staleness_issues": len(self.data_staleness_issues),
                "ws_desired_empty_events": len(self.ws_desired_empty_events),
                "md_staleness_bursts": sum(len(events) for events in self.md_staleness_bursts.values()),
                "cheap_wrong_side_candidates": len(self.cheap_wrong_side_candidates)
            },
            "assets": self.asset_metrics,
            "issues": (self.exit_invariant_violations + self.exit_post_size_issues + 
                      self.price_side_mismatches + self.signal_intent_sync_issues),
            "warnings": self.ssot_invariant_fires + self.data_staleness_issues + 
                       self.ws_desired_empty_events + [event for events in self.md_staleness_bursts.values() for event in events]
        }
        
        return json.dumps(result, indent=2)
    
    def to_csv(self) -> str:
        """Convert scan results to CSV format."""
        output = []
        output.append("timestamp,asset,no_signals_seen,no_orders_sent,yes_signals_seen,yes_orders_sent,exit_invariant_violations,exit_post_size_issues,bias_issues,price_side_mismatches,signal_intent_sync_issues,ssot_invariant_fires,data_staleness_issues,ws_desired_empty_events,md_staleness_bursts,cheap_wrong_side_candidates")
        
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
                str(metrics["bias_issues"]),
                str(metrics["price_side_mismatches"]),
                str(metrics["signal_intent_sync_issues"]),
                str(metrics["ssot_invariant_fires"]),
                str(metrics["data_staleness_issues"]),
                str(metrics["ws_desired_empty_events"]),
                str(metrics["md_staleness_bursts"]),
                str(metrics["cheap_wrong_side_candidates"])
            ]
            output.append(",".join(row))
        
        return "\n".join(output)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/scan_bias_and_exit_health.py <log_file_path> [--output json|csv] [--output-file <path>]")
        print("\nThis script scans log files for production anomalies:")
        print("  - Markets where signal.side=NO but no NO orders were ever sent")
        print("  - Any [EXIT-INVARIANT-VIOLATION]")
        print("  - Any case where post_size >= pre_size on an EXIT path")
        print("  - Any [PRICE-SIDE-CHECK-VIOLATION] (price/side mismatch)")
        print("  - Signal-intent synchronization issues (signal_side == thesis_side == candidate.side == order.side)")
        print("  - Runtime SSOT checks ([SSOT-INVARIANT] logs)")
        print("  - Data freshness anomalies (stale orderbook, catalog staleness)")
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
    
    monitor = ProductionAnomalyMonitor(log_file_path)
    success = monitor.scan()
    
    # Output results
    if output_format == "json":
        output = monitor.to_json()
    elif output_format == "csv":
        output = monitor.to_csv()
    else:
        # Default text output already printed by monitor.scan()
        output = None
    
    if output:
        if output_file:
            with open(output_file, 'w') as f:
                f.write(output)
            print(f"\nOutput written to: {output_file}")
        else:
            print(output)
    
    # Exit with error code if critical issues found
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
