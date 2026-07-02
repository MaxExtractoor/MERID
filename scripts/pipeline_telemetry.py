#!/usr/bin/env python3
"""
Pipeline Telemetry Script for Kalshi 15m Crypto Trading

Tracks per-window statistics across the candidate → trade → execution pipeline:
- candidates_generated
- candidates_rejected (with reasons)
- orders_attempted
- orders_accepted (with reasons)

Usage:
    python scripts/pipeline_telemetry.py --log-file logs/kalshi_15m_lean.log --window-minutes 15
"""

import re
import argparse
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class WindowStats:
    """Statistics for a single 15-minute trading window."""
    window_start: datetime
    window_end: datetime
    
    # Per-asset stats
    candidates_generated: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    candidates_rejected: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    orders_attempted: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    orders_accepted: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    orders_rejected: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    
    # Aggregate stats
    total_candidates: int = 0
    total_orders: int = 0
    
    def add_candidate(self, asset: str, rejected: bool = False, reason: str = ""):
        """Record a candidate generation event."""
        self.candidates_generated[asset] += 1
        self.total_candidates += 1
        if rejected and reason:
            self.candidates_rejected[asset][reason] += 1
    
    def add_order(self, asset: str, accepted: bool = False, reason: str = ""):
        """Record an order attempt."""
        self.orders_attempted[asset] += 1
        self.total_orders += 1
        if accepted:
            self.orders_accepted[asset] += 1
        elif reason:
            self.orders_rejected[asset][reason] += 1
    
    def summary(self) -> str:
        """Generate a summary string for this window."""
        lines = [
            f"Window: {self.window_start.strftime('%H:%M')} - {self.window_end.strftime('%H:%M')}",
            f"Total Candidates: {self.total_candidates}",
            f"Total Orders: {self.total_orders}",
            "",
            "Per-Asset Candidates:",
        ]
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            gen = self.candidates_generated.get(asset, 0)
            lines.append(f"  {asset}: {gen} generated")
            if self.candidates_rejected[asset]:
                lines.append(f"    Rejections:")
                for reason, count in sorted(self.candidates_rejected[asset].items(), key=lambda x: -x[1]):
                    lines.append(f"      {reason}: {count}")
        
        lines.append("")
        lines.append("Per-Asset Orders:")
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            attempted = self.orders_attempted.get(asset, 0)
            accepted = self.orders_accepted.get(asset, 0)
            lines.append(f"  {asset}: {attempted} attempted, {accepted} accepted")
            if self.orders_rejected[asset]:
                lines.append(f"    Rejections:")
                for reason, count in sorted(self.orders_rejected[asset].items(), key=lambda x: -x[1]):
                    lines.append(f"      {reason}: {count}")
        
        return "\n".join(lines)


class PipelineTelemetry:
    """Parse logs and extract pipeline telemetry."""
    
    # Regex patterns for log parsing
    PATTERNS = {
        'candidate_generated': re.compile(r'\[CANDIDATE-GENERATED\] asset=(\w+)_15M side=(\w+)'),
        'candidate_rejected': re.compile(r'\[([A-Z-]+)\] asset=(\w+)_15M.*'),
        'order_attempted': re.compile(r'\[15M-LOOP\] Order routed successfully: ticker=(\w+).*'),
        'order_rejected': re.compile(r'\[ORDER-ROUTER\] .* ticker=(\w+).*'),
        'velocity_signal': re.compile(r'\[VELOCITY-SIGNAL\] asset=(\w+) velocity=.*-> (BUY YES|BUY NO|NO TRADE)'),
        'market_validation': re.compile(r'\[MARKET-VALIDATION\] asset=(\w+)_15M ticker=.* regime=(\w+)'),
        'time_expiry_validation': re.compile(r'\[TIME-EXPIRY-VALIDATION\] asset=(\w+)_15M.*'),
        'cooldown_check': re.compile(r'\[COOLDOWN-CHECK\] asset=(\w+) in cooldown'),
        'strip_limit_check': re.compile(r'\[STRIP-LIMIT-CHECK\] strip=.*'),
    }
    
    def __init__(self, log_file: str, window_minutes: int = 15):
        self.log_file = log_file
        self.window_minutes = window_minutes
        self.windows: List[WindowStats] = []
        self.current_window: Optional[WindowStats] = None
        
    def parse_log(self):
        """Parse the log file and extract telemetry."""
        with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                self._process_line(line)
    
    def _process_line(self, line: str):
        """Process a single log line."""
        # Extract timestamp
        timestamp_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
        if not timestamp_match:
            return
        
        timestamp = datetime.strptime(timestamp_match.group(1), '%Y-%m-%d %H:%M:%S')
        
        # Determine window
        window_start = timestamp.replace(
            minute=(timestamp.minute // self.window_minutes) * self.window_minutes,
            second=0,
            microsecond=0
        )
        window_end = window_start + timedelta(minutes=self.window_minutes)
        
        # Check if we need to start a new window
        if self.current_window is None or window_start > self.current_window.window_end:
            if self.current_window:
                self.windows.append(self.current_window)
            self.current_window = WindowStats(window_start=window_start, window_end=window_end)
        
        # Parse candidate generation
        match = self.PATTERNS['candidate_generated'].search(line)
        if match:
            asset = match.group(1)
            self.current_window.add_candidate(asset, rejected=False)
            return
        
        # Parse candidate rejections
        match = self.PATTERNS['candidate_rejected'].search(line)
        if match:
            tag = match.group(1)
            asset = match.group(2)
            
            # Determine rejection reason based on tag
            if tag == 'MARKET-VALIDATION-FAILED':
                reason = 'market_validation'
            elif tag == 'TIME-EXPIRY-VALIDATION':
                reason = 'expired'
            elif tag == 'COOLDOWN-CHECK':
                reason = 'cooldown'
            elif tag == 'STRIP-LIMIT-CHECK':
                reason = 'strip_limit'
            elif tag == 'NO-SIGNAL':
                reason = 'no_signal'
            elif tag == 'SPOT-ERROR':
                reason = 'no_spot_price'
            elif tag == 'MARKET-ERROR':
                reason = 'no_market'
            else:
                reason = tag.lower()
            
            self.current_window.add_candidate(asset, rejected=True, reason=reason)
            return
        
        # Parse velocity signal (NO TRADE is a rejection)
        match = self.PATTERNS['velocity_signal'].search(line)
        if match:
            asset = match.group(1)
            decision = match.group(2)
            if decision == 'NO TRADE':
                self.current_window.add_candidate(asset, rejected=True, reason='insufficient_velocity')
            return
        
        # Parse order attempts
        match = self.PATTERNS['order_attempted'].search(line)
        if match:
            ticker = match.group(1)
            asset = self._extract_asset_from_ticker(ticker)
            if asset:
                self.current_window.add_order(asset, accepted=True)
            return
        
        # Parse order rejections
        match = self.PATTERNS['order_rejected'].search(line)
        if match:
            ticker = match.group(1)
            asset = self._extract_asset_from_ticker(ticker)
            if asset:
                # Extract rejection reason from line
                if 'MIN_EDGE_THRESHOLD' in line:
                    reason = 'min_edge_threshold'
                elif 'MODEL_PROB_DISTANCE' in line:
                    reason = 'model_prob_distance'
                elif 'BANKROLL_CAP' in line:
                    reason = 'bankroll_cap'
                elif 'TRADING_MODE_GATE' in line:
                    reason = 'trading_mode_gate'
                else:
                    reason = 'router_rejection'
                self.current_window.add_order(asset, accepted=False, reason=reason)
            return
    
    def _extract_asset_from_ticker(self, ticker: str) -> Optional[str]:
        """Extract asset from ticker (e.g., KXBTC15M-... -> BTC)."""
        if ticker.startswith('KXBTC'):
            return 'BTC'
        elif ticker.startswith('KXETH'):
            return 'ETH'
        elif ticker.startswith('KXSOL'):
            return 'SOL'
        elif ticker.startswith('KXXRP'):
            return 'XRP'
        elif ticker.startswith('KXDOGE'):
            return 'DOGE'
        return None
    
    def report(self, last_n_windows: int = 10) -> str:
        """Generate a telemetry report."""
        if not self.windows and self.current_window:
            self.windows.append(self.current_window)
        
        windows_to_show = self.windows[-last_n_windows:]
        
        lines = [
            "=" * 80,
            "PIPELINE TELEMETRY REPORT",
            f"Log File: {self.log_file}",
            f"Window Size: {self.window_minutes} minutes",
            f"Total Windows: {len(self.windows)}",
            "=" * 80,
            "",
        ]
        
        for window in windows_to_show:
            lines.append(window.summary())
            lines.append("")
        
        # Aggregate summary
        lines.append("=" * 80)
        lines.append("AGGREGATE SUMMARY (All Windows)")
        lines.append("=" * 80)
        
        total_candidates = sum(w.total_candidates for w in self.windows)
        total_orders = sum(w.total_orders for w in self.windows)
        
        lines.append(f"Total Candidates: {total_candidates}")
        lines.append(f"Total Orders: {total_orders}")
        lines.append(f"Conversion Rate: {total_orders / total_candidates * 100 if total_candidates > 0 else 0:.1f}%")
        lines.append("")
        
        # Per-asset aggregate
        lines.append("Per-Asset Aggregate:")
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            total_gen = sum(w.candidates_generated.get(asset, 0) for w in self.windows)
            total_acc = sum(w.orders_accepted.get(asset, 0) for w in self.windows)
            lines.append(f"  {asset}: {total_gen} candidates, {total_acc} orders ({total_acc / total_gen * 100 if total_gen > 0 else 0:.1f}% conversion)")
        
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Extract pipeline telemetry from logs')
    parser.add_argument('--log-file', required=True, help='Path to log file')
    parser.add_argument('--window-minutes', type=int, default=15, help='Window size in minutes')
    parser.add_argument('--last-n-windows', type=int, default=10, help='Number of recent windows to show')
    
    args = parser.parse_args()
    
    telemetry = PipelineTelemetry(args.log_file, args.window_minutes)
    telemetry.parse_log()
    
    print(telemetry.report(args.last_n_windows))


if __name__ == '__main__':
    main()
