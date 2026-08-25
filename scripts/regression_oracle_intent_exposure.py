"""
Regression Oracle: Detect Intent→Exposure Violations in Historical Logs

This script analyzes historical trade logs to detect instances where the old
"sell Yes as entry" bug would have fired. It uses the new StrategyIntent
contract to validate that BULLISH_EVENT produces +Yes exposure and BEARISH_EVENT
produces +No exposure.

CRITICAL FIX (2026-07-19): This oracle prevents regression of side/price mapping bugs.

Usage:
    python scripts/regression_oracle_intent_exposure.py --log-file path/to/logfile.log
    python scripts/regression_oracle_intent_exposure.py --log-dir path/to/logs/

Output:
    - Violations flagged with ticker, intent, exposure, kalshi_side, action, price
    - Classification: true_bug, canonical_equivalent, closure_noise
    - Position state reconstruction for context
"""

import re
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from enum import Enum


class ViolationType(Enum):
    """Classification of intent/exposure violations."""
    TRUE_BUG = "true_bug"  # Entry opened opposite exposure from stated intent
    CANONICAL_EQUIVALENT = "canonical_equivalent"  # sell_yes/buy_no same exposure, used correctly
    CLOSURE_NOISE = "closure_noise"  # Valid exit, not an invalid entry
    NO_VIOLATION = "no_violation"  # Intent matches exposure correctly


class ExposureDelta(Enum):
    """Signed exposure delta for position tracking."""
    POSITIVE_YES = "+YES"  # buy_yes, sell_no
    POSITIVE_NO = "+NO"  # buy_no, sell_yes
    NEGATIVE_YES = "-YES"  # sell_yes (close YES), buy_no (close YES)
    NEGATIVE_NO = "-NO"  # sell_no (close NO), buy_yes (close NO)
    FLAT = "FLAT"  # No position change


@dataclass
class IntentExecRecord:
    """Parsed [INTENT-EXEC] log record."""
    timestamp: str
    ticker: str
    intent: str
    exposure: str
    kalshi_side: str
    action: str
    price_cents: int
    raw_line: str


@dataclass
class PositionState:
    """Track position state over time for a ticker."""
    ticker: str
    yes_contracts: int = 0
    no_contracts: int = 0
    history: List[IntentExecRecord] = field(default_factory=list)
    
    @property
    def is_flat(self) -> bool:
        return self.yes_contracts == 0 and self.no_contracts == 0
    
    @property
    def net_exposure(self) -> str:
        """Current net exposure: +YES, +NO, or FLAT."""
        if self.yes_contracts > 0 and self.no_contracts == 0:
            return "+YES"
        elif self.no_contracts > 0 and self.yes_contracts == 0:
            return "+NO"
        elif self.yes_contracts == 0 and self.no_contracts == 0:
            return "FLAT"
        else:
            # Mixed position (should not happen in binary options)
            return "MIXED"
    
    def apply_order(self, record: IntentExecRecord, count: int = 1) -> ExposureDelta:
        """Apply order to position state and return exposure delta."""
        kalshi_side = record.kalshi_side
        action = record.action
        
        # Calculate exposure delta
        if kalshi_side == "BUY_YES":
            self.yes_contracts += count
            delta = ExposureDelta.POSITIVE_YES
        elif kalshi_side == "SELL_YES":
            self.yes_contracts -= count
            delta = ExposureDelta.NEGATIVE_YES
        elif kalshi_side == "BUY_NO":
            self.no_contracts += count
            delta = ExposureDelta.POSITIVE_NO
        elif kalshi_side == "SELL_NO":
            self.no_contracts -= count
            delta = ExposureDelta.NEGATIVE_NO
        else:
            delta = ExposureDelta.FLAT
        
        # Clamp to zero (no short positions in binary options)
        self.yes_contracts = max(0, self.yes_contracts)
        self.no_contracts = max(0, self.no_contracts)
        
        self.history.append(record)
        return delta


class RegressionOracle:
    """Detect intent→exposure violations in historical logs."""
    
    # Parse [INTENT-EXEC] log format
    INTENT_EXEC_PATTERN = re.compile(
        r'\[INTENT-EXEC\] ticker=(\S+) intent=(\S+) exposure=(\S+) kalshi_side=(\S+) action=(\S+) price=(\d+)c'
    )
    
    def __init__(self):
        self.records: List[IntentExecRecord] = []
        self.position_states: Dict[str, PositionState] = defaultdict(
            lambda: PositionState(ticker="")
        )
        self.violations: List[Dict] = []
    
    def parse_log_file(self, log_path: Path) -> None:
        """Parse log file and extract [INTENT-EXEC] records."""
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                match = self.INTENT_EXEC_PATTERN.search(line)
                if match:
                    record = IntentExecRecord(
                        timestamp=line[:23],  # Assume ISO timestamp prefix
                        ticker=match.group(1),
                        intent=match.group(2),
                        exposure=match.group(3),
                        kalshi_side=match.group(4),
                        action=match.group(5),
                        price_cents=int(match.group(6)),
                        raw_line=line.strip()
                    )
                    self.records.append(record)
                    # Initialize position state for this ticker
                    if record.ticker not in self.position_states:
                        self.position_states[record.ticker] = PositionState(ticker=record.ticker)
    
    def analyze(self) -> List[Dict]:
        """Analyze records and detect violations."""
        # Sort records by timestamp within each ticker
        ticker_records = defaultdict(list)
        for record in self.records:
            ticker_records[record.ticker].append(record)
        
        for ticker, records in ticker_records.items():
            # Sort by timestamp (assume ISO format sortable)
            records.sort(key=lambda r: r.timestamp)
            
            pos_state = self.position_states[ticker]
            
            for record in records:
                violation = self._validate_record(record, pos_state)
                if violation:
                    self.violations.append(violation)
                
                # Apply order to position state
                pos_state.apply_order(record)
        
        return self.violations
    
    def _validate_record(self, record: IntentExecRecord, pos_state: PositionState) -> Optional[Dict]:
        """Validate a single record against intent→exposure contract."""
        intent = record.intent.lower()
        exposure = record.exposure.lower()
        kalshi_side = record.kalshi_side.upper()
        action = record.action.lower()
        
        # Check intent→exposure invariant
        if intent == "bullish_event":
            expected_exposure = "+yes"
        elif intent == "bearish_event":
            expected_exposure = "+no"
        else:
            # Neutral/unknown intent - skip validation
            return None
        
        # Calculate actual net exposure from kalshi_side
        if kalshi_side in ("BUY_YES", "SELL_NO"):
            actual_exposure = "+yes"
        elif kalshi_side in ("BUY_NO", "SELL_YES"):
            actual_exposure = "+no"
        else:
            actual_exposure = "unknown"
        
        # Check for violation
        if actual_exposure != expected_exposure:
            # Determine violation type
            was_flat_before = pos_state.is_flat
            
            if was_flat_before:
                # Opening a position with wrong exposure = true bug
                violation_type = ViolationType.TRUE_BUG
            else:
                # Check if this is a closure
                if action == "sell":
                    # Sell orders are typically closures
                    violation_type = ViolationType.CLOSURE_NOISE
                else:
                    # Could be canonical equivalent (sell_yes/buy_no)
                    violation_type = ViolationType.CANONICAL_EQUIVALENT
            
            return {
                "violation_type": violation_type.value,
                "ticker": record.ticker,
                "timestamp": record.timestamp,
                "intent": record.intent,
                "expected_exposure": expected_exposure.upper(),
                "actual_exposure": actual_exposure.upper(),
                "kalshi_side": record.kalshi_side,
                "action": record.action,
                "price_cents": record.price_cents,
                "position_before": pos_state.net_exposure,
                "was_flat_before": was_flat_before,
                "raw_line": record.raw_line
            }
        
        return None
    
    def generate_report(self) -> str:
        """Generate human-readable report."""
        lines = []
        lines.append("=" * 80)
        lines.append("REGRESSION ORACLE: Intent→Exposure Violation Report")
        lines.append("=" * 80)
        lines.append(f"Total records analyzed: {len(self.records)}")
        lines.append(f"Total violations found: {len(self.violations)}")
        lines.append("")
        
        # Group violations by type
        by_type = defaultdict(list)
        for v in self.violations:
            by_type[v['violation_type']].append(v)
        
        for vtype in ViolationType:
            if vtype.value in by_type:
                count = len(by_type[vtype.value])
                lines.append(f"{vtype.value.upper()}: {count} violations")
        
        lines.append("")
        lines.append("-" * 80)
        lines.append("DETAILED VIOLATIONS")
        lines.append("-" * 80)
        
        for v in self.violations:
            lines.append(f"\n[{v['violation_type'].upper()}]")
            lines.append(f"  Ticker: {v['ticker']}")
            lines.append(f"  Timestamp: {v['timestamp']}")
            lines.append(f"  Intent: {v['intent']} (expected exposure: {v['expected_exposure']})")
            lines.append(f"  Actual exposure: {v['actual_exposure']}")
            lines.append(f"  Kalshi side: {v['kalshi_side']}")
            lines.append(f"  Action: {v['action']}")
            lines.append(f"  Price: {v['price_cents']}c")
            lines.append(f"  Position before: {v['position_before']}")
            lines.append(f"  Was flat before: {v['was_flat_before']}")
            lines.append(f"  Raw log: {v['raw_line']}")
        
        lines.append("")
        lines.append("=" * 80)
        
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Regression Oracle: Detect Intent→Exposure Violations"
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Path to a single log file to analyze"
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        help="Path to directory containing log files"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Path to output report file (default: stdout)"
    )
    
    args = parser.parse_args()
    
    oracle = RegressionOracle()
    
    if args.log_file:
        oracle.parse_log_file(args.log_file)
    elif args.log_dir:
        for log_path in args.log_dir.glob("*.log"):
            print(f"Parsing {log_path}...")
            oracle.parse_log_file(log_path)
    else:
        parser.error("Must specify --log-file or --log-dir")
    
    print(f"Analyzing {len(oracle.records)} records...")
    violations = oracle.analyze()
    
    report = oracle.generate_report()
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"Report written to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
