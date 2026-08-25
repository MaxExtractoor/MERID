"""
Direct reconciliation script that queries the existing kalshi_fills.db
and compares to Kalshi API data without using the ledger initialization.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set
from collections import defaultdict
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
from utils.logger import get_logger

logger = get_logger("direct_reconciliation")


class DirectReconciler:
    """Direct reconciler using existing database and API."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.client = None
        self.reconciliation_report = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "watermark_start": None,
            "watermark_end": None,
            "api_fills": [],
            "db_fills": [],
            "discrepancies": [],
            "summary": {}
        }

    async def initialize(self):
        """Initialize Kalshi client."""
        try:
            config = get_kalshi_config()
            self.client = KalshiVenueClient(config)
            logger.info("Reconciler initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize reconciler: {e}")
            raise

    def get_db_fills(self) -> List[Dict[str, Any]]:
        """Get all fills from the existing database."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT fill_id, order_id, client_order_id, market_ticker, side, action, count_fp, 
                       yes_price_dollars, no_price_dollars, fee_cost, created_time, raw_payload
                FROM kalshi_fills 
                ORDER BY created_time DESC
            """)
            
            rows = cursor.fetchall()
            fills = []
            for row in rows:
                fill_dict = {
                    "fill_id": row[0],
                    "order_id": row[1],
                    "client_order_id": row[2],
                    "market_ticker": row[3],
                    "side": row[4],
                    "action": row[5],
                    "count_fp": row[6],
                    "yes_price_dollars": row[7],
                    "no_price_dollars": row[8],
                    "fee_cost": row[9],
                    "created_time": row[10],
                    "raw_payload": row[11]
                }
                fills.append(fill_dict)
            
            conn.close()
            logger.info(f"Retrieved {len(fills)} fills from database")
            return fills
        except Exception as e:
            logger.error(f"Error retrieving fills from database: {e}")
            return []

    async def get_api_fills(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Fetch fills from Kalshi API."""
        try:
            since_ts = int(start_time.timestamp() * 1000) if start_time else None
            result = await self.client.get_fills(limit=limit, since_ts=since_ts)
            
            if result.success:
                fills = result.data or []
                logger.info(f"Fetched {len(fills)} fills from API")
                return fills
            else:
                logger.error(f"Failed to fetch API fills: {result.error}")
                return []
        except Exception as e:
            logger.error(f"Error fetching API fills: {e}")
            return []

    def calculate_signed_yes_delta(self, fill: Dict[str, Any]) -> int:
        """Calculate signed YES exposure delta."""
        count_str = fill.get("count_fp", "0")
        try:
            count = int(float(count_str)) if isinstance(count_str, str) else int(count_str)
        except (ValueError, TypeError):
            count = 0
            
        action = fill.get("action", "").lower()
        outcome_side = fill.get("outcome_side", "").lower()
        side = fill.get("side", "").lower()
        
        # Use outcome_side if available, otherwise fall back to side
        canonical_side = outcome_side if outcome_side else side
        
        if canonical_side == "yes":
            return +count if action == "buy" else -count
        else:  # side == "no"
            return -count if action == "buy" else +count

    def reconcile_fills(
        self,
        api_fills: List[Dict[str, Any]],
        db_fills: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Reconcile API fills against database fills."""
        discrepancies = []
        
        # Index by fill_id
        api_fills_by_id = {f.get("fill_id", ""): f for f in api_fills}
        db_fills_by_id = {f["fill_id"]: f for f in db_fills}
        
        api_fill_ids = set(api_fills_by_id.keys())
        db_fill_ids = set(db_fills_by_id.keys())
        
        # Check for fills in API but not in DB
        missing_in_db = api_fill_ids - db_fill_ids
        for fill_id in missing_in_db:
            api_fill = api_fills_by_id[fill_id]
            discrepancies.append({
                "type": "EXTERNAL_FILL_MISSING_INTERNAL",
                "fill_id": fill_id,
                "order_id": api_fill.get("order_id"),
                "ticker": api_fill.get("market_ticker"),
                "created_time": api_fill.get("created_time"),
                "count": api_fill.get("count_fp"),
                "action": api_fill.get("action"),
                "outcome_side": api_fill.get("outcome_side"),
                "book_side": api_fill.get("book_side"),
                "severity": "CRITICAL"
            })
        
        # Check for fills in DB but not in API
        missing_in_api = db_fill_ids - api_fill_ids
        for fill_id in missing_in_api:
            db_fill = db_fills_by_id[fill_id]
            discrepancies.append({
                "type": "INTERNAL_FILL_MISSING_EXTERNAL",
                "fill_id": fill_id,
                "order_id": db_fill["order_id"],
                "ticker": db_fill["market_ticker"],
                "created_time": db_fill["created_time"],
                "count": db_fill["count_fp"],
                "action": db_fill["action"],
                "side": db_fill["side"],
                "severity": "WARNING"
            })
        
        # Check for mismatches in common fills
        common_fill_ids = api_fill_ids & db_fill_ids
        for fill_id in common_fill_ids:
            api_fill = api_fills_by_id[fill_id]
            db_fill = db_fills_by_id[fill_id]
            
            # Check count mismatch
            if api_fill.get("count_fp") != db_fill["count_fp"]:
                discrepancies.append({
                    "type": "COUNT_MISMATCH",
                    "fill_id": fill_id,
                    "api_count": api_fill.get("count_fp"),
                    "db_count": db_fill["count_fp"],
                    "severity": "CRITICAL"
                })
            
            # Check direction field mismatch
            api_outcome_side = api_fill.get("outcome_side", "").lower()
            db_side = db_fill["side"].lower() if db_fill["side"] else ""
            if api_outcome_side and db_side and api_outcome_side != db_side:
                discrepancies.append({
                    "type": "DIRECTION_FIELD_MISMATCH",
                    "fill_id": fill_id,
                    "api_outcome_side": api_outcome_side,
                    "db_side": db_side,
                    "api_book_side": api_fill.get("book_side"),
                    "api_action": api_fill.get("action"),
                    "db_action": db_fill["action"],
                    "severity": "CRITICAL"
                })
            
            # Check action mismatch
            api_action = api_fill.get("action", "").lower()
            db_action = db_fill["action"].lower() if db_fill["action"] else ""
            if api_action and db_action and api_action != db_action:
                discrepancies.append({
                    "type": "ACTION_MISMATCH",
                    "fill_id": fill_id,
                    "api_action": api_action,
                    "db_action": db_action,
                    "severity": "CRITICAL"
                })
        
        return {
            "total_api_fills": len(api_fills),
            "total_db_fills": len(db_fills),
            "common_fills": len(common_fill_ids),
            "missing_in_db": len(missing_in_db),
            "missing_in_api": len(missing_in_api),
            "discrepancies": discrepancies
        }

    async def run_reconciliation(
        self,
        hours_back: int = 72,
        target_fill_id: Optional[str] = None,
        target_ticker: Optional[str] = None
    ) -> Dict[str, Any]:
        """Run full reconciliation."""
        logger.info(f"Starting reconciliation for {hours_back} hours back")
        
        # Set watermark
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours_back)
        self.reconciliation_report["watermark_start"] = start_time.isoformat()
        self.reconciliation_report["watermark_end"] = end_time.isoformat()
        
        # Get API fills
        api_fills = await self.get_api_fills(start_time=start_time, end_time=end_time)
        
        # Filter by target fill_id or ticker if specified
        if target_fill_id:
            api_fills = [f for f in api_fills if f.get("fill_id") == target_fill_id]
            logger.info(f"Filtered to target fill_id: {target_fill_id}")
        
        if target_ticker:
            api_fills = [f for f in api_fills if f.get("market_ticker") == target_ticker]
            logger.info(f"Filtered to target ticker: {target_ticker}")
        
        self.reconciliation_report["api_fills"] = api_fills
        
        # Get DB fills
        db_fills = self.get_db_fills()
        
        # Filter DB fills by time window
        db_fills_filtered = [
            f for f in db_fills
            if f.get("created_time") and start_time <= datetime.fromisoformat(f["created_time"]) <= end_time
        ]
        
        # Filter by target fill_id or ticker if specified
        if target_fill_id:
            db_fills_filtered = [f for f in db_fills_filtered if f["fill_id"] == target_fill_id]
        
        if target_ticker:
            db_fills_filtered = [f for f in db_fills_filtered if f["market_ticker"] == target_ticker]
        
        self.reconciliation_report["db_fills"] = db_fills_filtered
        
        # Reconcile fills
        fill_reconciliation = self.reconcile_fills(api_fills, db_fills_filtered)
        self.reconciliation_report["discrepancies"] = fill_reconciliation["discrepancies"]
        
        # Summary
        self.reconciliation_report["summary"] = {
            "critical_discrepancies": len([d for d in fill_reconciliation["discrepancies"] if d.get("severity") == "CRITICAL"]),
            "warning_discrepancies": len([d for d in fill_reconciliation["discrepancies"] if d.get("severity") == "WARNING"]),
            "api_fill_count": len(api_fills),
            "db_fill_count": len(db_fills_filtered),
            "reconciliation_status": "PASS" if fill_reconciliation["missing_in_db"] == 0 and fill_reconciliation["missing_in_api"] == 0 else "FAIL"
        }
        
        logger.info(f"Reconciliation complete: {self.reconciliation_report['summary']}")
        return self.reconciliation_report


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Direct Kalshi API reconciliation")
    parser.add_argument("--db-path", type=str, default="kalshi_fills.db", help="Path to kalshi_fills.db")
    parser.add_argument("--hours", type=int, default=72, help="Hours back to reconcile")
    parser.add_argument("--fill-id", type=str, help="Target specific fill_id")
    parser.add_argument("--ticker", type=str, help="Target specific ticker")
    parser.add_argument("--output", type=str, help="Output file for reconciliation report")
    
    args = parser.parse_args()
    
    reconciler = DirectReconciler(args.db_path)
    await reconciler.initialize()
    
    report = await reconciler.run_reconciliation(
        hours_back=args.hours,
        target_fill_id=args.fill_id,
        target_ticker=args.ticker
    )
    
    # Output report
    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f"Reconciliation report saved to {args.output}")
    else:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
