#!/usr/bin/env python3
"""
Regression Oracle for Execution Count Fix (2026-07-19)

This script analyzes logs to verify that the execution count fix is working correctly.
It checks for:
1. Proper rejection logging (GLOBAL-ALLOCATOR Order rejected by venue)
2. Accurate execution counts (executed=N/M where N <= M)
3. No instances of the old bug (executed=3/3 when only 1 actually executed)

Usage:
    python scripts/regression_oracle.py <log_file> [--since TIMESTAMP]
"""

import re
import sys
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Tuple, Optional


class RegressionOracle:
    """Analyzes logs for execution count regression"""
    
    def __init__(self, log_file: str, since_timestamp: Optional[str] = None):
        self.log_file = Path(log_file)
        self.since_timestamp = since_timestamp
        self.rejections = []
        self.execution_stats = []
        self.errors = []
        self.since_dt = None
        
        if since_timestamp:
            try:
                self.since_dt = datetime.fromisoformat(since_timestamp)
            except ValueError:
                print(f"Warning: Invalid timestamp format: {since_timestamp}")
        
    def analyze(self) -> Dict:
        """Analyze the log file for execution count issues"""
        if not self.log_file.exists():
            return {"error": f"Log file not found: {self.log_file}"}
        
        with open(self.log_file, 'r', encoding='utf-8') as f:
            for line in f:
                self._parse_line(line)
        
        return self._generate_report()
    
    def _parse_line(self, line: str):
        """Parse a single log line"""
        # Try to parse as JSON first
        try:
            log_entry = json.loads(line)
            timestamp_str = log_entry.get("ts", "")
            message = log_entry.get("message", "")
            level = log_entry.get("level", "")
            
            # Filter by timestamp if specified
            if self.since_dt:
                try:
                    log_dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    # Make both offset-aware or both offset-naive for comparison
                    if log_dt.tzinfo is None:
                        log_dt = log_dt.replace(tzinfo=self.since_dt.tzinfo)
                    elif self.since_dt.tzinfo is None:
                        self.since_dt = self.since_dt.replace(tzinfo=log_dt.tzinfo)
                    if log_dt < self.since_dt:
                        return
                except ValueError:
                    pass
            
            # Check for rejection logging
            if "GLOBAL-ALLOCATOR" in message and "Order rejected by venue" in message:
                self.rejections.append(message)
            
            # Check for execution complete logs
            match = re.search(r'Execution complete: executed=(\d+)/(\d+)', message)
            if match:
                executed = int(match.group(1))
                total = int(match.group(2))
                self.execution_stats.append((executed, total, timestamp_str, message))
            
            # Check for errors
            if level in ["ERROR", "CRITICAL"]:
                self.errors.append(message)
                
        except json.JSONDecodeError:
            # Fallback to plain text parsing
            # Check for rejection logging
            if "GLOBAL-ALLOCATOR" in line and "Order rejected by venue" in line:
                self.rejections.append(line.strip())
            
            # Check for execution complete logs
            match = re.search(r'Execution complete: executed=(\d+)/(\d+)', line)
            if match:
                executed = int(match.group(1))
                total = int(match.group(2))
                self.execution_stats.append((executed, total, "", line.strip()))
            
            # Check for errors
            if "ERROR" in line or "CRITICAL" in line:
                self.errors.append(line.strip())
    
    def _generate_report(self) -> Dict:
        """Generate analysis report"""
        report = {
            "log_file": str(self.log_file),
            "since_timestamp": self.since_timestamp,
            "rejections_found": len(self.rejections),
            "execution_stats_count": len(self.execution_stats),
            "errors_found": len(self.errors),
            "issues": [],
            "warnings": [],
            "passed": True
        }
        
        # Check execution statistics for accuracy
        for executed, total, timestamp, message in self.execution_stats:
            if executed > total:
                report["issues"].append(
                    f"INVALID: executed={executed}/{total} (executed > total) - {timestamp} - {message}"
                )
                report["passed"] = False
            elif executed == total and total > 1:
                # This could be legitimate (all orders succeeded) or the old bug
                # Only warn if there are NO rejections in the log (suspicious pattern)
                if len(self.rejections) == 0:
                    report["warnings"].append(
                        f"POTENTIAL BUG: executed={executed}/{total} (all succeeded, no rejections found) - {timestamp}"
                    )
        
        # Check for proper rejection logging
        if len(self.rejections) > 0:
            report["rejection_samples"] = self.rejections[:5]  # First 5 rejections
        
        # Check for the specific old bug pattern
        for executed, total, timestamp, message in self.execution_stats:
            if executed == 3 and total == 3:
                # This was the reported bug pattern
                if "BTC yes 53c" in message or "executed=3/3" in message:
                    report["issues"].append(
                        f"OLD BUG DETECTED: executed=3/3 pattern found - {timestamp} - {message}"
                    )
                    report["passed"] = False
        
        return report


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python regression_oracle.py <log_file> [--since TIMESTAMP]")
        print("Example: python regression_oracle.py logs/full.log --since 2026-07-19T20:40:00")
        sys.exit(1)
    
    log_file = sys.argv[1]
    since_timestamp = None
    
    if len(sys.argv) >= 4 and sys.argv[2] == "--since":
        since_timestamp = sys.argv[3]
    
    oracle = RegressionOracle(log_file, since_timestamp)
    report = oracle.analyze()
    
    print("\n" + "="*80)
    print("REGRESSION ORACLE REPORT")
    print("="*80)
    print(f"Log File: {report.get('log_file', 'N/A')}")
    if report.get('since_timestamp'):
        print(f"Since Timestamp: {report.get('since_timestamp')}")
    print(f"Rejections Found: {report.get('rejections_found', 0)}")
    print(f"Execution Stats: {report.get('execution_stats_count', 0)}")
    print(f"Errors Found: {report.get('errors_found', 0)}")
    print("\n" + "-"*80)
    
    if report.get("issues"):
        print("ISSUES FOUND:")
        for issue in report["issues"]:
            print(f"  ❌ {issue}")
    else:
        print("No issues found")
    
    if report.get("warnings"):
        print("\nWARNINGS:")
        for warning in report["warnings"]:
            print(f"  ⚠️  {warning}")
    
    if report.get("rejection_samples"):
        print("\nREJECTION LOG SAMPLES:")
        for sample in report["rejection_samples"]:
            print(f"  {sample}")
    
    print("\n" + "="*80)
    if report.get("passed"):
        print("✅ REGRESSION CHECK PASSED")
        print("="*80)
        sys.exit(0)
    else:
        print("❌ REGRESSION CHECK FAILED")
        print("="*80)
        sys.exit(1)


if __name__ == "__main__":
    main()
