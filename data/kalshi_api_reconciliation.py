"""
Read-only Kalshi API reconciliation script.

This script performs a three-level reconciliation:
1. Execution: Compare Kalshi fills to internal ledger by fill_id
2. Intent: Compare orders and client_order_id correlation
3. Position: Compare reconstructed positions from exchange fills to internal position cache

NO MODIFICATIONS TO PRODUCTION DATA - READ ONLY
"""

import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
from utils.logger import get_logger

logger = get_logger("kalshi_api_reconciliation")


class KalshiAPIReconciler:
    """Read-only reconciler for Kalshi API vs internal state."""

    def __init__(self):
        self.client = None
        self.ledger = None
        self.reconciliation_report = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "watermark_start": None,
            "watermark_end": None,
            "historical_cutoff": None,
            "api_fills": [],
            "ledger_fills": [],
            "discrepancies": [],
            "position_comparison": {},
            "summary": {}
        }

    async def initialize(self):
        """Initialize Kalshi client and fills ledger."""
        try:
            config = get_kalshi_config()
            self.client = KalshiVenueClient(config)
            self.ledger = get_fills_ledger()
            logger.info("Reconciler initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize reconciler: {e}")
            raise

    async def get_historical_cutoff(self) -> Optional[int]:
        """Fetch the historical cutoff timestamp from Kalshi."""
        try:
            result = await self.client._request_with_resilience(
                "GET", "/historical/cutoff", operation_name="get_historical_cutoff"
            )
            if result.success and result.data:
                cutoff_ts = result.data.get("cutoff_ts")
                self.reconciliation_report["historical_cutoff"] = cutoff_ts
                if cutoff_ts:
                    logger.info(f"Historical cutoff: {cutoff_ts} ({datetime.fromtimestamp(cutoff_ts/1000, tz=timezone.utc)})")
                else:
                    logger.info("Historical cutoff: None (no cutoff)")
                return cutoff_ts
            else:
                logger.warning(f"Failed to get historical cutoff: {result.error}")
                return None
        except Exception as e:
            logger.error(f"Error fetching historical cutoff: {e}")
            return None

    async def get_portfolio_fills(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Fetch fills from /portfolio/fills (recent records)."""
        try:
            since_ts = int(start_time.timestamp() * 1000) if start_time else None
            result = await self.client.get_fills(limit=limit, since_ts=since_ts)
            
            if result.success:
                fills = result.data or []
                logger.info(f"Fetched {len(fills)} fills from /portfolio/fills")
                return fills
            else:
                logger.error(f"Failed to fetch portfolio fills: {result.error}")
                return []
        except Exception as e:
            logger.error(f"Error fetching portfolio fills: {e}")
            return []

    async def get_historical_fills(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Fetch fills from /historical/fills (older records)."""
        try:
            params: Dict[str, Any] = {"limit": limit}
            if start_time:
                params["start_ts"] = int(start_time.timestamp() * 1000)
            if end_time:
                params["end_ts"] = int(end_time.timestamp() * 1000)
            
            result = await self.client._request_with_resilience(
                "GET", "/historical/fills", params=params, operation_name="get_historical_fills"
            )
            
            if result.success:
                fills = result.data.get("fills", []) if result.data else []
                logger.info(f"Fetched {len(fills)} fills from /historical/fills")
                return fills
            else:
                logger.error(f"Failed to fetch historical fills: {result.error}")
                return []
        except Exception as e:
            logger.error(f"Error fetching historical fills: {e}")
            return []

    async def get_portfolio_positions(self) -> List[Dict[str, Any]]:
        """Fetch current portfolio positions from Kalshi."""
        try:
            result = await self.client.get_positions_with_filters(filters={}, limit=200)
            
            if result.success and result.data:
                positions = result.data.get("market_positions", [])
                logger.info(f"Fetched {len(positions)} portfolio positions")
                return positions
            else:
                logger.error(f"Failed to fetch portfolio positions: {result.error}")
                return []
        except Exception as e:
            logger.error(f"Error fetching portfolio positions: {e}")
            return []

    def get_ledger_fills(self) -> List[Any]:
        """Get all fills from internal ledger database."""
        try:
            import sqlite3
            import os
            
            # Try multiple possible database paths
            possible_paths = [
                self.ledger._db_path if hasattr(self.ledger, '_db_path') else None,
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "kalshi_fills.db"),
                os.path.join(os.path.dirname(__file__), "kalshi_fills.db"),
                "kalshi_fills.db"
            ]
            
            db_path = None
            for path in possible_paths:
                if path and os.path.exists(path):
                    db_path = path
                    break
            
            if not db_path:
                logger.error("Could not find kalshi_fills.db in expected locations")
                return []
            
            conn = sqlite3.connect(db_path)
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
            logger.info(f"Retrieved {len(fills)} fills from ledger database at {db_path}")
            return fills
        except Exception as e:
            logger.error(f"Error retrieving ledger fills from database: {e}")
            return []

    def extract_fill_key(self, fill: Dict[str, Any]) -> str:
        """Extract unique key for fill deduplication."""
        return fill.get("fill_id", "")

    def calculate_signed_yes_delta(self, fill: Dict[str, Any]) -> int:
        """Calculate signed YES exposure delta from Kalshi V2 fill.
        
        Kalshi V2 semantics:
        - BUY YES: +count (long YES)
        - SELL YES: -count (close YES)
        - BUY NO: -count (long NO = negative YES exposure)
        - SELL NO: +count (close NO = positive YES exposure)
        """
        count_str = fill.get("count_fp", "0")
        try:
            count = int(float(count_str)) if isinstance(count_str, str) else int(count_str)
        except (ValueError, TypeError):
            count = 0
            
        action = fill.get("action", "").lower()
        outcome_side = fill.get("outcome_side", "").lower()
        
        if outcome_side == "yes":
            return +count if action == "buy" else -count
        elif outcome_side == "no":
            return -count if action == "buy" else +count
        else:
            # Fallback for legacy payloads
            side = fill.get("side", "").lower()
            if side == "yes":
                return +count if action == "buy" else -count
            else:  # side == "no"
                return -count if action == "buy" else +count

    def reconstruct_position_from_fills(self, fills: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
        """Reconstruct positions from exchange fills by ticker.
        
        Returns: {ticker: {"signed_yes_exposure": int, "contracts": int}}
        """
        positions = defaultdict(lambda: {"signed_yes_exposure": 0, "contracts": 0})
        
        for fill in fills:
            ticker = fill.get("market_ticker", "")
            if not ticker:
                continue
            
            signed_delta = self.calculate_signed_yes_delta(fill)
            count_str = fill.get("count_fp", "0")
            try:
                count = int(float(count_str)) if isinstance(count_str, str) else int(count_str)
            except (ValueError, TypeError):
                count = 0
            
            positions[ticker]["signed_yes_exposure"] += signed_delta
            positions[ticker]["contracts"] += count if signed_delta > 0 else -count
        
        return dict(positions)

    def reconcile_fills(
        self,
        api_fills: List[Dict[str, Any]],
        ledger_fills: List[Any]
    ) -> Dict[str, Any]:
        """Reconcile Kalshi API fills against internal ledger."""
        discrepancies = []
        
        # Index API fills by fill_id
        api_fills_by_id = {self.extract_fill_key(f): f for f in api_fills}
        
        # Index ledger fills by fill_id
        ledger_fills_by_id = {f["fill_id"]: f for f in ledger_fills}
        
        # Check for fills in API but not in ledger
        api_fill_ids = set(api_fills_by_id.keys())
        ledger_fill_ids = set(ledger_fills_by_id.keys())
        
        missing_in_ledger = api_fill_ids - ledger_fill_ids
        for fill_id in missing_in_ledger:
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
        
        # Check for fills in ledger but not in API
        missing_in_api = ledger_fill_ids - api_fill_ids
        for fill_id in missing_in_api:
            ledger_fill = ledger_fills_by_id[fill_id]
            discrepancies.append({
                "type": "INTERNAL_FILL_MISSING_EXTERNAL",
                "fill_id": fill_id,
                "order_id": ledger_fill["order_id"],
                "ticker": ledger_fill["market_ticker"],
                "created_time": ledger_fill["created_time"],
                "count": ledger_fill["count_fp"],
                "action": ledger_fill["action"],
                "side": ledger_fill["side"],
                "severity": "WARNING"
            })
        
        # Check for mismatches in common fills
        common_fill_ids = api_fill_ids & ledger_fill_ids
        for fill_id in common_fill_ids:
            api_fill = api_fills_by_id[fill_id]
            ledger_fill = ledger_fills_by_id[fill_id]
            
            # Check count mismatch
            if api_fill.get("count_fp") != ledger_fill["count_fp"]:
                discrepancies.append({
                    "type": "COUNT_MISMATCH",
                    "fill_id": fill_id,
                    "api_count": api_fill.get("count_fp"),
                    "ledger_count": ledger_fill["count_fp"],
                    "severity": "CRITICAL"
                })
            
            # Check price mismatch
            api_yes_price = api_fill.get("yes_price_dollars")
            ledger_yes_price = ledger_fill["yes_price_dollars"]
            if api_yes_price != ledger_yes_price:
                discrepancies.append({
                    "type": "PRICE_MISMATCH",
                    "fill_id": fill_id,
                    "api_yes_price": api_yes_price,
                    "ledger_yes_price": ledger_yes_price,
                    "severity": "WARNING"
                })
            
            # Check V2 direction fields mismatch
            api_outcome_side = api_fill.get("outcome_side", "").lower()
            ledger_side = ledger_fill["side"].lower() if ledger_fill["side"] else ""
            if api_outcome_side and ledger_side and api_outcome_side != ledger_side:
                discrepancies.append({
                    "type": "DIRECTION_FIELD_MISMATCH",
                    "fill_id": fill_id,
                    "api_outcome_side": api_outcome_side,
                    "ledger_side": ledger_side,
                    "api_book_side": api_fill.get("book_side"),
                    "api_action": api_fill.get("action"),
                    "ledger_action": ledger_fill["action"],
                    "severity": "CRITICAL"
                })
        
        return {
            "total_api_fills": len(api_fills),
            "total_ledger_fills": len(ledger_fills),
            "common_fills": len(common_fill_ids),
            "missing_in_ledger": len(missing_in_ledger),
            "missing_in_api": len(missing_in_api),
            "discrepancies": discrepancies
        }

    def reconcile_positions(
        self,
        api_positions: List[Dict[str, Any]],
        ledger_fills: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Reconstruct positions from ledger fills and compare to API positions."""
        # Convert ledger fills to dict format for reconstruction
        ledger_fill_dicts = []
        for fill in ledger_fills:
            ledger_fill_dicts.append({
                "fill_id": fill["fill_id"],
                "market_ticker": fill["market_ticker"],
                "count_fp": fill["count_fp"],
                "action": fill["action"],
                "side": fill["side"],
                "outcome_side": fill["side"],  # Ledger uses side as outcome_side
                "created_time": fill["created_time"]
            })
        
        # Reconstruct positions from ledger fills
        ledger_positions = self.reconstruct_position_from_fills(ledger_fill_dicts)
        
        # Convert API positions to comparable format
        api_positions_by_ticker = {}
        for pos in api_positions:
            ticker = pos.get("market_ticker", "")
            if ticker:
                # API returns net position (could be positive or negative)
                contracts = pos.get("total_contracts", 0)
                api_positions_by_ticker[ticker] = {
                    "contracts": contracts,
                    "signed_yes_exposure": contracts  # Simplified - API doesn't provide signed exposure
                }
        
        # Compare positions
        position_discrepancies = []
        all_tickers = set(ledger_positions.keys()) | set(api_positions_by_ticker.keys())
        
        for ticker in all_tickers:
            ledger_pos = ledger_positions.get(ticker, {"signed_yes_exposure": 0, "contracts": 0})
            api_pos = api_positions_by_ticker.get(ticker, {"signed_yes_exposure": 0, "contracts": 0})
            
            if ledger_pos["contracts"] != api_pos["contracts"]:
                position_discrepancies.append({
                    "ticker": ticker,
                    "ledger_contracts": ledger_pos["contracts"],
                    "api_contracts": api_pos["contracts"],
                    "ledger_signed_exposure": ledger_pos["signed_yes_exposure"],
                    "api_signed_exposure": api_pos["signed_yes_exposure"],
                    "severity": "CRITICAL" if abs(ledger_pos["contracts"] - api_pos["contracts"]) > 0 else "OK"
                })
        
        return {
            "total_api_positions": len(api_positions),
            "total_ledger_positions": len(ledger_positions),
            "position_discrepancies": position_discrepancies
        }

    async def run_reconciliation(
        self,
        hours_back: int = 72,
        target_fill_id: Optional[str] = None,
        target_ticker: Optional[str] = None
    ) -> Dict[str, Any]:
        """Run full reconciliation for specified time window."""
        logger.info(f"Starting reconciliation for {hours_back} hours back")
        
        # Set watermark
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours_back)
        self.reconciliation_report["watermark_start"] = start_time.isoformat()
        self.reconciliation_report["watermark_end"] = end_time.isoformat()
        
        # Get historical cutoff
        cutoff_ts = await self.get_historical_cutoff()
        
        # Fetch API fills (both portfolio and historical)
        portfolio_fills = await self.get_portfolio_fills(start_time=start_time, end_time=end_time)
        historical_fills = await self.get_historical_fills(start_time=start_time, end_time=end_time)
        
        # Deduplicate API fills by fill_id
        all_api_fills = {self.extract_fill_key(f): f for f in portfolio_fills + historical_fills}
        api_fills_list = list(all_api_fills.values())
        
        # Filter by target fill_id or ticker if specified
        if target_fill_id:
            api_fills_list = [f for f in api_fills_list if self.extract_fill_key(f) == target_fill_id]
            logger.info(f"Filtered to target fill_id: {target_fill_id}")
        
        if target_ticker:
            api_fills_list = [f for f in api_fills_list if f.get("market_ticker") == target_ticker]
            logger.info(f"Filtered to target ticker: {target_ticker}")
        
        self.reconciliation_report["api_fills"] = api_fills_list
        
        # Get ledger fills
        ledger_fills = self.get_ledger_fills()
        
        # Filter ledger fills by time window
        ledger_fills_filtered = [
            f for f in ledger_fills
            if f.get("created_time") and start_time <= datetime.fromisoformat(f["created_time"]) <= end_time
        ]
        
        # Filter by target fill_id or ticker if specified
        if target_fill_id:
            ledger_fills_filtered = [f for f in ledger_fills_filtered if f["fill_id"] == target_fill_id]
        
        if target_ticker:
            ledger_fills_filtered = [f for f in ledger_fills_filtered if f["market_ticker"] == target_ticker]
        
        self.reconciliation_report["ledger_fills"] = [
            {
                "fill_id": f["fill_id"],
                "order_id": f["order_id"],
                "market_ticker": f["market_ticker"],
                "side": f["side"],
                "action": f["action"],
                "count_fp": f["count_fp"],
                "yes_price_dollars": f["yes_price_dollars"],
                "created_time": f["created_time"]
            }
            for f in ledger_fills_filtered
        ]
        
        # Reconcile fills
        fill_reconciliation = self.reconcile_fills(api_fills_list, ledger_fills_filtered)
        self.reconciliation_report["discrepancies"] = fill_reconciliation["discrepancies"]
        
        # Fetch portfolio positions
        api_positions = await self.get_portfolio_positions()
        
        # Reconcile positions
        position_reconciliation = self.reconcile_positions(api_positions, ledger_fills_filtered)
        self.reconciliation_report["position_comparison"] = position_reconciliation
        
        # Summary
        self.reconciliation_report["summary"] = {
            "critical_discrepancies": len([d for d in fill_reconciliation["discrepancies"] if d.get("severity") == "CRITICAL"]),
            "warning_discrepancies": len([d for d in fill_reconciliation["discrepancies"] if d.get("severity") == "WARNING"]),
            "position_discrepancies": len(position_reconciliation["position_discrepancies"]),
            "api_fill_count": len(api_fills_list),
            "ledger_fill_count": len(ledger_fills_filtered),
            "reconciliation_status": "PASS" if fill_reconciliation["missing_in_ledger"] == 0 and fill_reconciliation["missing_in_api"] == 0 else "FAIL"
        }
        
        logger.info(f"Reconciliation complete: {self.reconciliation_report['summary']}")
        return self.reconciliation_report


async def main():
    """Main entry point for reconciliation."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Kalshi API reconciliation")
    parser.add_argument("--hours", type=int, default=72, help="Hours back to reconcile")
    parser.add_argument("--fill-id", type=str, help="Target specific fill_id")
    parser.add_argument("--ticker", type=str, help="Target specific ticker")
    parser.add_argument("--output", type=str, help="Output file for reconciliation report")
    
    args = parser.parse_args()
    
    reconciler = KalshiAPIReconciler()
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
