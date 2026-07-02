"""
WebSocket raw traffic vs parsed Market Data probe.

This diagnostic confirms whether Kalshi is actually sending MD for these channels
and whether the parser is discarding it.

NOTE: This requires integration with the WebSocket service to track message counts.
This module provides the structure and tracking logic that should be integrated
into the WS client.
"""

import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Any
from threading import Lock


class WSTrafficTracker:
    """
    Tracks WebSocket message traffic and parse results.
    
    This should be integrated into the WebSocket client to count:
    - Total messages received
    - Messages per market ID
    - Parse successes/failures
    """
    
    def __init__(self):
        self._lock = Lock()
        self._total_messages = 0
        self._messages_per_market = defaultdict(int)
        self._parse_successes = defaultdict(int)
        self._parse_failures = defaultdict(int)
        self._parse_failure_reasons = defaultdict(int)
        self._start_time = time.time()
    
    def record_message(self, market_id: str):
        """Record a raw message received for a market."""
        with self._lock:
            self._total_messages += 1
            self._messages_per_market[market_id] += 1
    
    def record_parse_success(self, market_id: str):
        """Record a successful parse for a market."""
        with self._lock:
            self._parse_successes[market_id] += 1
    
    def record_parse_failure(self, market_id: str, reason: str = "unknown"):
        """Record a parse failure for a market."""
        with self._lock:
            self._parse_failures[market_id] += 1
            self._parse_failure_reasons[reason] += 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Get traffic summary statistics."""
        with self._lock:
            elapsed = time.time() - self._start_time
            msgs_per_minute = (self._total_messages / elapsed * 60) if elapsed > 0 else 0
            
            return {
                "total_messages": self._total_messages,
                "elapsed_seconds": elapsed,
                "messages_per_minute": msgs_per_minute,
                "messages_per_market": dict(self._messages_per_market),
                "parse_successes": dict(self._parse_successes),
                "parse_failures": dict(self._parse_failures),
                "parse_failure_reasons": dict(self._parse_failure_reasons),
                "top_failure_reasons": sorted(
                    self._parse_failure_reasons.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:5]
            }


# Global tracker instance (should be initialized in WS client)
_ws_tracker = None


def get_ws_tracker() -> WSTrafficTracker:
    """Get the global WS traffic tracker."""
    global _ws_tracker
    if _ws_tracker is None:
        _ws_tracker = WSTrafficTracker()
    return _ws_tracker


async def check_ws_raw_vs_parsed() -> Dict[str, Any]:
    """
    Check WebSocket raw traffic vs parsed MD.
    
    Returns:
        Dict with diagnostic results including:
        - Total messages received
        - Messages per market ID
        - Parse successes/failures
        - Top failure reasons
        - Per-ticker message counts and book update ages
    """
    tracker = get_ws_tracker()
    summary = tracker.get_summary()
    
    # Get market state store to check book update ages
    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
    state_store = get_kalshi_market_state_store()
    all_md_states = state_store.get_all()
    
    # Add per-ticker book update ages
    ticker_details = {}
    for ticker, state in all_md_states.items():
        last_update = None
        if hasattr(state, 'last_book_update_ts') and state.last_book_update_ts:
            last_update = state.last_book_update_ts
        elif hasattr(state, 'last_update_ts') and state.last_update_ts:
            last_update = state.last_update_ts
        
        md_age = None
        if last_update:
            # last_update_ts uses time.monotonic(), so calculate age as time.monotonic() - last_update
            md_age = time.monotonic() - last_update
        
        ticker_details[ticker] = {
            "messages_received": summary["messages_per_market"].get(ticker, 0),
            "parse_successes": summary["parse_successes"].get(ticker, 0),
            "parse_failures": summary["parse_failures"].get(ticker, 0),
            "book_last_update_age_seconds": md_age
        }
    
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ws_raw_summary": {
            "total_msgs": summary["total_messages"],
            "msgs_per_minute": summary["messages_per_minute"],
            "parse_success": sum(summary["parse_successes"].values()),
            "parse_fail": sum(summary["parse_failures"].values()),
            "top_fail_reasons": summary["top_failure_reasons"]
        },
        "per_ticker_details": ticker_details,
        "diagnosis": _diagnose_ws_issues(summary, ticker_details)
    }
    
    return result


def _diagnose_ws_issues(summary: Dict, ticker_details: Dict) -> List[str]:
    """Diagnose potential WS issues based on traffic data."""
    issues = []
    
    # Check if receiving any messages
    if summary["total_messages"] == 0:
        issues.append("CRITICAL: No WebSocket messages received at all")
        return issues
    
    # Check parse success rate
    total_parse = sum(summary["parse_successes"].values()) + sum(summary["parse_failures"].values())
    if total_parse > 0:
        success_rate = sum(summary["parse_successes"].values()) / total_parse
        if success_rate < 0.5:
            issues.append(f"WARNING: Low parse success rate: {success_rate:.1%}")
    
    # Check per-ticker message distribution
    for ticker, details in ticker_details.items():
        if details["messages_received"] == 0:
            issues.append(f"WARNING: No messages received for {ticker}")
        elif details["parse_successes"] == 0 and details["parse_failures"] > 0:
            issues.append(f"ERROR: All messages failed to parse for {ticker}")
        elif details["book_last_update_age_seconds"] and details["book_last_update_age_seconds"] > 60:
            issues.append(f"WARNING: Stale book for {ticker}: {details['book_last_update_age_seconds']:.1f}s old")
    
    return issues


if __name__ == "__main__":
    # Run standalone for testing (will show empty data if not integrated)
    import json
    result = asyncio.run(check_ws_raw_vs_parsed())
    print(json.dumps(result, indent=2))
