#!/usr/bin/env python3
"""
Blocker Audit Script — Analyzes blocked orders and flags non-canonical reasons.

This script scans log files or structured event data to:
1. Group blocked orders by block_reason and stage
2. Flag any blocks using non-canonical reasons
3. Flag blocks from unexpected code paths (legacy agents, old HTTP routes)
4. Generate a report with actionable findings

Usage:
    python scripts/blocker_audit.py --logs-path data/logs/ --days 7
    python scripts/blocker_audit.py --json > blocker_audit_report.json
    python scripts/blocker_audit.py --scan-codebase
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from merid.guards.block_reasons import (
        BlockReason,
        OrderStage,
        CANONICAL_BLOCK_REASONS,
        CANONICAL_STAGES,
        get_block_reason_category,
    )
    BLOCK_REASONS_AVAILABLE = True
except ImportError:
    print("ERROR: merid.guards.block_reasons module not available")
    print("Run from project root with: python scripts/blocker_audit.py")
    sys.exit(1)


class BlockerAuditResult:
    """Results of a blocker audit."""
    
    def __init__(self):
        self.total_blocks: int = 0
        self.canonical_blocks: int = 0
        self.non_canonical_blocks: int = 0
        self.unknown_stages: int = 0
        self.blocks_by_reason: Counter = Counter()
        self.blocks_by_stage: Counter = Counter()
        self.blocks_by_category: Counter = Counter()
        self.non_canonical_samples: List[Dict[str, Any]] = []
        self.unexpected_callers: Counter = Counter()
        self.time_range: Optional[tuple] = None
        self.findings: List[str] = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "summary": {
                "total_blocks": self.total_blocks,
                "canonical_blocks": self.canonical_blocks,
                "non_canonical_blocks": self.non_canonical_blocks,
                "unknown_stages": self.unknown_stages,
                "canonical_pct": (self.canonical_blocks / self.total_blocks * 100) if self.total_blocks > 0 else 0,
            },
            "blocks_by_reason": dict(self.blocks_by_reason.most_common(20)),
            "blocks_by_stage": dict(self.blocks_by_stage.most_common()),
            "blocks_by_category": dict(self.blocks_by_category.most_common()),
            "non_canonical_samples": self.non_canonical_samples[:20],  # Limit to 20 samples
            "unexpected_callers": dict(self.unexpected_callers.most_common(10)),
            "time_range": {
                "start": self.time_range[0].isoformat() if self.time_range else None,
                "end": self.time_range[1].isoformat() if self.time_range else None,
            } if self.time_range else None,
            "findings": self.findings,
        }


def parse_log_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a log line looking for ORDER_BLOCKED structured events.
    
    Expected format:
    {"order_id": "...", "stage": "...", "reason": "...", ...}
    """
    try:
        # Try to extract JSON from log line
        json_match = re.search(r'\{[^}]*"order_id"[^}]*\}', line)
        if not json_match:
            return None
        
        data = json.loads(json_match.group(0))
        
        # Validate required fields
        if "order_id" not in data or "stage" not in data or "reason" not in data:
            return None
        
        return data
    except (json.JSONDecodeError, Exception):
        return None


def scan_log_file(log_path: Path, days: int = 7) -> BlockerAuditResult:
    """Scan a log file for blocked order events."""
    result = BlockerAuditResult()
    
    if not log_path.exists():
        print(f"WARNING: Log file not found: {log_path}")
        return result
    
    # Calculate time threshold
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
    
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                block_event = parse_log_line(line)
                if not block_event:
                    continue
                
                # Check time filter
                event_time = datetime.fromtimestamp(block_event.get("timestamp", 0), tz=timezone.utc)
                if event_time < cutoff_time:
                    continue
                
                # Update time range
                if result.time_range is None:
                    result.time_range = (event_time, event_time)
                else:
                    result.time_range = (
                        min(result.time_range[0], event_time),
                        max(result.time_range[1], event_time)
                    )
                
                # Count blocks
                result.total_blocks += 1
                
                reason = block_event.get("reason", "")
                stage = block_event.get("stage", "")
                caller = block_event.get("caller_module", "")
                
                # Check if canonical
                if reason in CANONICAL_BLOCK_REASONS:
                    result.canonical_blocks += 1
                    result.blocks_by_reason[reason] += 1
                    
                    # Add category
                    try:
                        category = get_block_reason_category(BlockReason(reason))
                        result.blocks_by_category[category] += 1
                    except ValueError:
                        result.blocks_by_category["UNKNOWN"] += 1
                else:
                    result.non_canonical_blocks += 1
                    result.blocks_by_reason[reason] += 1
                    
                    # Track sample
                    if len(result.non_canonical_samples) < 50:
                        result.non_canonical_samples.append({
                            "order_id": block_event.get("order_id"),
                            "reason": reason,
                            "stage": stage,
                            "caller": caller,
                            "asset": block_event.get("asset", ""),
                            "timestamp": event_time.isoformat(),
                        })
                
                # Check stage
                if stage in CANONICAL_STAGES:
                    result.blocks_by_stage[stage] += 1
                else:
                    result.unknown_stages += 1
                    result.blocks_by_stage[stage] += 1
                
                # Track caller
                if caller:
                    result.unexpected_callers[caller] += 1
    
    except Exception as e:
        print(f"ERROR reading log file {log_path}: {e}")
    
    return result


def scan_codebase_for_blocks(root_path: Path = Path(__file__).parent.parent) -> Dict[str, Any]:
    """Scan codebase for blocking patterns that don't use canonical reasons.
    
    Looks for:
    - return statements with rejection reasons not using log_block_event
    - early returns without logging
    - legacy blocking patterns
    """
    findings = {
        "files_scanned": 0,
        "legacy_return_patterns": [],
        "silent_blocks": [],
        "direct_venue_calls": [],
    }
    
    # Patterns to search for
    legacy_return_pattern = re.compile(r'return.*"(reject|block|denied|halt)"', re.IGNORECASE)
    silent_return_pattern = re.compile(r'if.*:\s*return\s*None\s*$', re.MULTILINE)
    direct_venue_pattern = re.compile(r'(get_kalshi_client|KalshiVenueClient)\.(place_order|submit_order)')
    
    # Files to scan
    target_dirs = [
        root_path / "merid" / "event_venues" / "kalshi",
        root_path / "merid" / "prediction",
        root_path / "merid" / "trading",
    ]
    
    for target_dir in target_dirs:
        if not target_dir.exists():
            continue
        
        for py_file in target_dir.rglob("*.py"):
            # Skip test files
            if "test" in py_file.name or py_file.parent.name == "__tests__":
                continue
            
            findings["files_scanned"] += 1
            
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                    # Check for legacy return patterns
                    for match in legacy_return_pattern.finditer(content):
                        line_num = content[:match.start()].count('\n') + 1
                        findings["legacy_return_patterns"].append({
                            "file": str(py_file.relative_to(root_path)),
                            "line": line_num,
                            "match": match.group(0),
                        })
                    
                    # Check for silent blocks (return None without logging)
                    # This is a simple heuristic - may have false positives
                    for match in silent_return_pattern.finditer(content):
                        # Get context to check if there's logging nearby
                        context_start = max(0, match.start() - 200)
                        context = content[context_start:match.end()]
                        if "log" not in context.lower():
                            line_num = content[:match.start()].count('\n') + 1
                            findings["silent_blocks"].append({
                                "file": str(py_file.relative_to(root_path)),
                                "line": line_num,
                                "context": match.group(0),
                            })
                    
                    # Check for direct venue calls outside router
                    if "order_router" not in str(py_file):
                        for match in direct_venue_pattern.finditer(content):
                            line_num = content[:match.start()].count('\n') + 1
                            findings["direct_venue_calls"].append({
                                "file": str(py_file.relative_to(root_path)),
                                "line": line_num,
                                "match": match.group(0),
                            })
            
            except Exception as e:
                print(f"ERROR scanning {py_file}: {e}")
    
    return findings


def generate_findings(result: BlockerAuditResult, codebase_scan: Dict[str, Any]) -> List[str]:
    """Generate actionable findings from audit results."""
    findings = []
    
    # Check for non-canonical blocks
    if result.non_canonical_blocks > 0:
        pct = result.non_canonical_blocks / result.total_blocks * 100 if result.total_blocks > 0 else 0
        findings.append(
            f"CRITICAL: {result.non_canonical_blocks} blocks ({pct:.1f}%) use non-canonical reasons. "
            f"These should be migrated to BlockReason enum."
        )
    
    # Check for unknown stages
    if result.unknown_stages > 0:
        findings.append(
            f"WARNING: {result.unknown_stages} blocks use unknown stages. "
            f"Update OrderStage enum if these are legitimate."
        )
    
    # Check for legacy return patterns
    legacy_count = len(codebase_scan["legacy_return_patterns"])
    if legacy_count > 0:
        findings.append(
            f"WARNING: Found {legacy_count} legacy return patterns in codebase. "
            f"These should use log_block_event for structured logging."
        )
    
    # Check for silent blocks
    silent_count = len(codebase_scan["silent_blocks"])
    if silent_count > 0:
        findings.append(
            f"WARNING: Found {silent_count} potential silent blocks (return without logging). "
            f"These should log block reasons."
        )
    
    # Check for direct venue calls
    direct_count = len(codebase_scan["direct_venue_calls"])
    if direct_count > 0:
        findings.append(
            f"CRITICAL: Found {direct_count} direct venue calls outside order_router. "
            f"All orders must route through canonical order_router for safety."
        )
    
    # Check for unexpected callers
    unexpected_callers = [
        caller for caller, count in result.unexpected_callers.most_common()
        if not any(prefix in caller for prefix in ["merid.prediction.trading_agent", "tests.", "test_"])
    ]
    if unexpected_callers:
        findings.append(
            f"WARNING: Orders blocked from unexpected callers: {', '.join(unexpected_callers[:5])}. "
            f"Verify these are authorized execution paths."
        )
    
    if not findings:
        findings.append("SUCCESS: No critical issues found. All blocks use canonical reasons.")
    
    return findings


def main():
    parser = argparse.ArgumentParser(description="Audit blocked orders and blocker patterns")
    parser.add_argument("--logs-path", type=str, default="data/logs/",
                        help="Path to log directory (default: data/logs/)")
    parser.add_argument("--days", type=int, default=7,
                        help="Number of days to scan (default: 7)")
    parser.add_argument("--scan-codebase", action="store_true",
                        help="Scan codebase for blocking patterns")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON instead of human-readable report")
    
    args = parser.parse_args()
    
    # Scan logs
    logs_dir = Path(args.logs_path)
    if not logs_dir.exists():
        print(f"WARNING: Logs directory not found: {logs_dir}")
        result = BlockerAuditResult()
    else:
        # Find most recent log file
        log_files = list(logs_dir.glob("*.log")) + list(logs_dir.glob("*.json"))
        if log_files:
            # Sort by modification time, get most recent
            latest_log = max(log_files, key=lambda p: p.stat().st_mtime)
            print(f"Scanning log file: {latest_log}")
            result = scan_log_file(latest_log, days=args.days)
        else:
            print(f"WARNING: No log files found in {logs_dir}")
            result = BlockerAuditResult()
    
    # Scan codebase if requested
    codebase_scan = {}
    if args.scan_codebase:
        print("Scanning codebase for blocking patterns...")
        codebase_scan = scan_codebase_for_blocks()
    
    # Generate findings
    result.findings = generate_findings(result, codebase_scan)
    
    # Output
    if args.json:
        output = {
            "audit_result": result.to_dict(),
            "codebase_scan": codebase_scan,
        }
        print(json.dumps(output, indent=2))
    else:
        print("\n" + "="*70)
        print("BLOCKER AUDIT REPORT")
        print("="*70)
        
        print(f"\nSummary:")
        print(f"  Total blocks (last {args.days} days): {result.total_blocks}")
        print(f"  Canonical blocks: {result.canonical_blocks} ({result.canonical_blocks/result.total_blocks*100:.1f}%)" if result.total_blocks > 0 else "  Canonical blocks: 0")
        print(f"  Non-canonical blocks: {result.non_canonical_blocks} ({result.non_canonical_blocks/result.total_blocks*100:.1f}%)" if result.total_blocks > 0 else "  Non-canonical blocks: 0")
        print(f"  Unknown stages: {result.unknown_stages}")
        
        if result.blocks_by_reason:
            print(f"\nTop block reasons:")
            for reason, count in result.blocks_by_reason.most_common(10):
                print(f"  {reason}: {count}")
        
        if result.blocks_by_stage:
            print(f"\nBlocks by stage:")
            for stage, count in result.blocks_by_stage.most_common():
                print(f"  {stage}: {count}")
        
        if result.blocks_by_category:
            print(f"\nBlocks by category:")
            for category, count in result.blocks_by_category.most_common():
                print(f"  {category}: {count}")
        
        if codebase_scan:
            print(f"\nCodebase scan:")
            print(f"  Files scanned: {codebase_scan['files_scanned']}")
            print(f"  Legacy return patterns: {len(codebase_scan['legacy_return_patterns'])}")
            print(f"  Silent blocks: {len(codebase_scan['silent_blocks'])}")
            print(f"  Direct venue calls: {len(codebase_scan['direct_venue_calls'])}")
        
        print(f"\nFindings:")
        for finding in result.findings:
            print(f"  • {finding}")
        
        if result.non_canonical_samples:
            print(f"\nNon-canonical block samples (first 5):")
            for sample in result.non_canonical_samples[:5]:
                print(f"  - {sample['reason']} at {sample['stage']} from {sample['caller']}")
        
        print("\n" + "="*70)
    
    # Exit with error code if critical issues found
    critical_keywords = ["CRITICAL", "non-canonical", "direct venue"]
    has_critical = any(keyword in " ".join(result.findings).lower() for keyword in critical_keywords)
    sys.exit(1 if has_critical else 0)


if __name__ == "__main__":
    main()
