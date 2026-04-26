#!/usr/bin/env python3
"""Repair script for Kalshi fills ledger - backfills missing fills from DLQ and API.

This script is part of SCHEMA-FIX-001 remediation. It:
1. Checks DLQ for fills that failed due to schema errors
2. Resets the circuit breaker if needed
3. Replays eligible fills from DLQ
4. Optionally fetches missing fills from Kalshi REST API

Usage:
    python scripts/repair_kalshi_fills.py [--dry-run] [--from-date DATE]

Environment:
    MERID_KALSHI_API_KEY - API key for Kalshi (required for API backfill)
    MERID_KALSHI_API_SECRET - API secret for Kalshi (required for API backfill)
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.logger import get_logger

logger = get_logger(__name__)


async def get_dlq_status() -> Dict[str, Any]:
    """Get current DLQ status from fills ledger."""
    from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
    
    ledger = get_fills_ledger()
    return await ledger.get_dlq_status()


async def reset_circuit_and_replay() -> Dict[str, Any]:
    """Reset circuit breaker and replay DLQ fills."""
    from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
    
    ledger = get_fills_ledger()
    return await ledger.reset_circuit_breaker()


async def fetch_missing_fills_from_api(
    since: datetime,
    dry_run: bool = False
) -> List[Dict[str, Any]]:
    """Fetch fills from Kalshi REST API for backfill.
    
    Args:
        since: Fetch fills since this datetime
        dry_run: If True, don't actually fetch, just log what would be done
        
    Returns:
        List of fill dicts from API
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would fetch fills from API since {since.isoformat()}")
        return []
    
    try:
        from merid.event_venues.kalshi.client import get_kalshi_client
        
        client = get_kalshi_client()
        if not client:
            logger.error("Kalshi client not available")
            return []
        
        # Fetch fills from API
        logger.info(f"Fetching fills from Kalshi API since {since.isoformat()}")
        
        # Use the client's get_fills method if available
        if hasattr(client, 'get_fills'):
            fills = await client.get_fills(since=since)
            logger.info(f"Fetched {len(fills)} fills from API")
            return fills
        else:
            logger.warning("Kalshi client does not have get_fills method")
            return []
            
    except Exception as e:
        logger.error(f"Failed to fetch fills from API: {e}")
        return []


async def backfill_fills_to_ledger(
    fills: List[Dict[str, Any]],
    dry_run: bool = False
) -> Dict[str, int]:
    """Backfill fills to the ledger.
    
    Args:
        fills: List of fill dicts to backfill
        dry_run: If True, don't actually insert, just log
        
    Returns:
        Stats dict with counts
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would backfill {len(fills)} fills to ledger")
        return {"processed": 0, "inserted": 0, "duplicates": 0, "errors": 0}
    
    from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
    
    ledger = get_fills_ledger()
    stats = {"processed": 0, "inserted": 0, "duplicates": 0, "errors": 0}
    
    for fill_data in fills:
        stats["processed"] += 1
        try:
            # Check if fill already exists
            fill_id = fill_data.get("fill_id") or fill_data.get("trade_id") or fill_data.get("id")
            if fill_id and fill_id in ledger._fills:
                stats["duplicates"] += 1
                continue
            
            # Parse and insert fill
            fill = ledger._parse_fill(fill_data, "api_backfill")
            if fill and fill.fill_id:
                async with ledger._mutex:
                    ledger._fills[fill.fill_id] = fill
                    ledger._index_fill(fill)
                stats["inserted"] += 1
            else:
                stats["errors"] += 1
                
        except Exception as e:
            logger.warning(f"Failed to backfill fill: {e}")
            stats["errors"] += 1
    
    # Trigger persistence
    if stats["inserted"] > 0:
        await ledger._persist()
        logger.info(f"Triggered persistence for {stats['inserted']} backfilled fills")
    
    return stats


async def run_repair(
    dry_run: bool = False,
    from_date: Optional[datetime] = None,
    skip_api_fetch: bool = False,
) -> Dict[str, Any]:
    """Run the full repair process.
    
    Args:
        dry_run: If True, don't make any changes
        from_date: Fetch fills from API since this date (default: 7 days ago)
        skip_api_fetch: If True, don't fetch from API, only repair from DLQ
        
    Returns:
        Repair result dict
    """
    result = {
        "dry_run": dry_run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps": [],
    }
    
    # Step 1: Check DLQ status
    logger.info("=" * 60)
    logger.info("Step 1: Checking DLQ status")
    logger.info("=" * 60)
    
    dlq_status = await get_dlq_status()
    result["dlq_before"] = dlq_status
    
    pending_total = dlq_status.get("pending_total", 0)
    by_category = dlq_status.get("by_category", {})
    
    logger.info(f"DLQ status: {pending_total} pending fills")
    for category, count in by_category.items():
        logger.info(f"  - {category}: {count}")
    
    circuit_open = dlq_status.get("circuit_open", False)
    if circuit_open:
        logger.warning(f"Circuit breaker is OPEN: {dlq_status.get('circuit_reason')}")
    else:
        logger.info("Circuit breaker is closed")
    
    # Step 2: Reset circuit breaker and replay DLQ
    logger.info("")
    logger.info("=" * 60)
    logger.info("Step 2: Resetting circuit breaker and replaying DLQ")
    logger.info("=" * 60)
    
    if dry_run:
        logger.info("[DRY RUN] Would reset circuit breaker and replay DLQ fills")
        result["circuit_reset"] = {"dry_run": True}
    else:
        reset_result = await reset_circuit_and_replay()
        result["circuit_reset"] = reset_result
        logger.info(f"Circuit reset result: {json.dumps(reset_result, indent=2, default=str)}")
    
    # Step 3: Check DLQ status after replay
    logger.info("")
    logger.info("=" * 60)
    logger.info("Step 3: Checking DLQ status after replay")
    logger.info("=" * 60)
    
    dlq_status_after = await get_dlq_status()
    result["dlq_after"] = dlq_status_after
    
    pending_after = dlq_status_after.get("pending_total", 0)
    logger.info(f"DLQ status after replay: {pending_after} pending fills")
    
    replayed = dlq_status.get("replayed_count", 0)
    if replayed > 0:
        logger.info(f"Total replayed fills (lifetime): {replayed}")
    
    # Step 4: Fetch missing fills from API (if needed and not skipped)
    if not skip_api_fetch:
        logger.info("")
        logger.info("=" * 60)
        logger.info("Step 4: Fetching missing fills from Kalshi API")
        logger.info("=" * 60)
        
        if from_date is None:
            from_date = datetime.now(timezone.utc) - timedelta(days=7)
        
        api_fills = await fetch_missing_fills_from_api(from_date, dry_run=dry_run)
        result["api_fills_fetched"] = len(api_fills)
        
        if api_fills:
            backfill_stats = await backfill_fills_to_ledger(api_fills, dry_run=dry_run)
            result["backfill_stats"] = backfill_stats
            logger.info(f"Backfill stats: {json.dumps(backfill_stats, indent=2)}")
        else:
            logger.info("No fills fetched from API")
    else:
        logger.info("Skipping API fetch as requested")
        result["api_fetch_skipped"] = True
    
    # Final summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Repair Summary")
    logger.info("=" * 60)
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info(f"DLQ pending before: {pending_total}")
    logger.info(f"DLQ pending after: {pending_after}")
    logger.info(f"Circuit was open: {circuit_open}")
    if "circuit_reset" in result and not dry_run:
        logger.info(f"DLQ replayed: {result['circuit_reset'].get('dlq_replayed_count', 0)}")
    if "backfill_stats" in result:
        stats = result["backfill_stats"]
        logger.info(f"API fills processed: {stats.get('processed', 0)}")
        logger.info(f"API fills inserted: {stats.get('inserted', 0)}")
        logger.info(f"API fill duplicates: {stats.get('duplicates', 0)}")
        logger.info(f"API fill errors: {stats.get('errors', 0)}")
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Repair Kalshi fills ledger - backfill missing fills"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--from-date",
        type=str,
        help="Fetch fills from API since this date (ISO format, e.g., 2024-01-01T00:00:00Z)"
    )
    parser.add_argument(
        "--skip-api-fetch",
        action="store_true",
        help="Skip fetching from API, only repair from DLQ"
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=7,
        help="Fetch fills from last N days (default: 7)"
    )
    
    args = parser.parse_args()
    
    # Parse from_date if provided
    from_date = None
    if args.from_date:
        try:
            from_date = datetime.fromisoformat(args.from_date.replace("Z", "+00:00"))
        except ValueError:
            logger.error(f"Invalid from-date format: {args.from_date}")
            sys.exit(1)
    else:
        from_date = datetime.now(timezone.utc) - timedelta(days=args.since_days)
    
    # Run repair
    result = asyncio.run(run_repair(
        dry_run=args.dry_run,
        from_date=from_date,
        skip_api_fetch=args.skip_api_fetch,
    ))
    
    # Output result as JSON for programmatic use
    print("\n" + "=" * 60)
    print("Final Result (JSON):")
    print("=" * 60)
    print(json.dumps(result, indent=2, default=str))
    
    # Exit with appropriate code
    dlq_after = result.get("dlq_after", {}).get("pending_total", 0)
    if dlq_after > 0 and not args.dry_run:
        logger.warning(f"Exiting with warning: {dlq_after} fills still in DLQ")
        sys.exit(2)  # Warning exit code
    
    sys.exit(0)


if __name__ == "__main__":
    main()
