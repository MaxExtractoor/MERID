"""Post-session analysis — slice session_log.jsonl by bracket and compute metrics.

Reads the JSONL session log and produces per-bracket statistics:
  - Event counts by category and severity
  - Gate state transitions (CLEAR → LIMITED → BLOCKED frequency)
  - Top block/limit reasons
  - Bracket duration and transition timestamps

Run:  py scripts/analyze_session.py [--session SESSION_ID] [--file PATH]
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_events(path: Path, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load events from JSONL, optionally filtering by session_id."""
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
                if session_id and evt.get("session_id") != session_id:
                    continue
                events.append(evt)
            except json.JSONDecodeError:
                continue
    events.sort(key=lambda e: e.get("timestamp", 0))
    return events


def assign_brackets(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Assign a bracket label to each event based on bracket transition events."""
    current_bracket = "pre-bracket"
    for evt in events:
        meta = evt.get("metadata", {})
        if meta.get("bracket"):
            current_bracket = meta["bracket"]
        evt["_bracket"] = current_bracket
    return events


def format_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


def analyze(events: List[Dict[str, Any]]) -> None:
    """Print per-bracket analysis."""
    if not events:
        print("No events found.")
        return

    events = assign_brackets(events)

    # Group by bracket
    brackets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for evt in events:
        brackets[evt["_bracket"]].append(evt)

    session_start = events[0].get("timestamp", 0)
    session_end = events[-1].get("timestamp", 0)
    session_id = events[0].get("session_id", "unknown")

    print("\n" + "=" * 70)
    print("  MERID SESSION ANALYSIS")
    print("=" * 70)
    print(f"  Session ID:    {session_id}")
    print(f"  Duration:      {format_duration(session_end - session_start)}")
    print(f"  Total events:  {len(events)}")
    print(f"  Brackets:      {len(brackets)}")
    print(f"  Time range:    {format_ts(session_start)} → {format_ts(session_end)}")
    print("=" * 70)

    for bracket_name, bracket_events in brackets.items():
        if bracket_name == "pre-bracket" and len(bracket_events) <= 1:
            continue

        b_start = bracket_events[0]["timestamp"]
        b_end = bracket_events[-1]["timestamp"]

        print(f"\n{'─' * 70}")
        print(f"  BRACKET: {bracket_name}")
        print(f"  Duration: {format_duration(b_end - b_start)}  |  Events: {len(bracket_events)}")
        print(f"  Time: {format_ts(b_start)} → {format_ts(b_end)}")
        print(f"{'─' * 70}")

        # Category breakdown
        cat_counts = Counter(e["category"] for e in bracket_events)
        print(f"\n  Events by category:")
        for cat, count in cat_counts.most_common():
            print(f"    {cat:20s}  {count}")

        # Severity breakdown
        sev_counts = Counter(e["severity"] for e in bracket_events)
        print(f"\n  Events by severity:")
        for sev in ["critical", "warning", "info"]:
            if sev in sev_counts:
                marker = "🔴" if sev == "critical" else "🟡" if sev == "warning" else "🟢"
                print(f"    {marker} {sev:12s}  {sev_counts[sev]}")

        # Gate transitions
        gate_events = [e for e in bracket_events if e["category"] == "gate"]
        if gate_events:
            blocked_count = sum(1 for e in gate_events if "BLOCKED" in e.get("title", ""))
            clear_count = sum(1 for e in gate_events if "CLEAR" in e.get("title", "") or "OPEN" in e.get("title", ""))
            print(f"\n  Gate transitions:")
            print(f"    BLOCKED events:  {blocked_count}")
            print(f"    CLEAR events:    {clear_count}")

            # Gate reasons from metadata
            all_reasons = []
            for e in gate_events:
                reasons = e.get("metadata", {}).get("reasons", [])
                all_reasons.extend(reasons)
            if all_reasons:
                reason_counts = Counter(all_reasons)
                print(f"    Top block reasons:")
                for reason, count in reason_counts.most_common(5):
                    print(f"      {reason:25s}  {count}x")

            # Gate state from metadata
            gate_states = [e.get("metadata", {}).get("gate_state") for e in gate_events if e.get("metadata", {}).get("gate_state")]
            if gate_states:
                state_counts = Counter(gate_states)
                print(f"    Gate states seen:")
                for state, count in state_counts.most_common():
                    marker = "🔴" if state == "blocked" else "🟡" if state == "limited" else "🟢"
                    print(f"      {marker} {state:12s}  {count}x")

        # Kill switch events
        ks_events = [e for e in bracket_events if e["category"] == "kill_switch"]
        if ks_events:
            triggered = sum(1 for e in ks_events if "TRIGGERED" in e.get("title", ""))
            reset = sum(1 for e in ks_events if "RESET" in e.get("title", ""))
            print(f"\n  Kill switch:")
            print(f"    Triggered: {triggered}  |  Reset: {reset}")

        # Feed events
        feed_events = [e for e in bracket_events if e["category"] == "feed"]
        if feed_events:
            print(f"\n  Feed events: {len(feed_events)}")

        # Reconciliation events
        recon_events = [e for e in bracket_events if e["category"] == "reconciliation"]
        if recon_events:
            print(f"\n  Reconciliation events: {len(recon_events)}")

        # Hints (unique)
        hints = set()
        for e in bracket_events:
            if e.get("hint"):
                hints.add(e["hint"])
        if hints:
            print(f"\n  Remediation hints seen:")
            for h in sorted(hints):
                print(f"    → {h}")

    # Summary table
    print(f"\n{'=' * 70}")
    print("  BRACKET SUMMARY")
    print(f"{'=' * 70}")
    print(f"  {'Bracket':<30s} {'Events':>7s} {'Critical':>9s} {'Warning':>8s} {'Gate':>6s} {'Duration':>10s}")
    print(f"  {'─' * 30} {'─' * 7} {'─' * 9} {'─' * 8} {'─' * 6} {'─' * 10}")

    for bracket_name, bracket_events in brackets.items():
        if bracket_name == "pre-bracket" and len(bracket_events) <= 1:
            continue
        sev = Counter(e["severity"] for e in bracket_events)
        gate_count = sum(1 for e in bracket_events if e["category"] == "gate")
        duration = bracket_events[-1]["timestamp"] - bracket_events[0]["timestamp"]
        print(f"  {bracket_name:<30s} {len(bracket_events):>7d} {sev.get('critical', 0):>9d} {sev.get('warning', 0):>8d} {gate_count:>6d} {format_duration(duration):>10s}")

    print(f"{'=' * 70}\n")


def main():
    parser = argparse.ArgumentParser(description="Analyze MERID session log by bracket")
    parser.add_argument("--file", "-f", default="data/session_log.jsonl", help="Path to session_log.jsonl")
    parser.add_argument("--session", "-s", default=None, help="Filter by session ID")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"Error: {path} not found. Run a session first.")
        sys.exit(1)

    events = load_events(path, session_id=args.session)
    analyze(events)


if __name__ == "__main__":
    main()
