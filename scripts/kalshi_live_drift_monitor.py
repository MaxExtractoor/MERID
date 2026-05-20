#!/usr/bin/env python3
"""
Kalshi Live Drift Monitoring Script

Periodically pulls live Kalshi positions and fills, runs a replay + reconciliation
in isolation, and alerts on unexpected discrepancies.

This is an early-warning system for Kalshi API or behavior changes that
fixtures don't yet capture.

Usage:
    python scripts/kalshi_live_drift_monitor.py --subaccount 0 --minutes 30
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# Add project root to path
sys.path.insert(0, "c:\\Dev\\MERID")

from merid.event_venues.kalshi.client import KalshiClient
from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
from merid.reconciliation.venue_reconciler import reconcile_venue
from merid.reconciliation.reconciliation_metrics import emit_recon_metrics
from utils.logger import get_logger

# Import alerting module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drift_alerting import DriftAlerter

logger = get_logger("kalshi_live_drift_monitor")


class DriftMonitorResult:
    """Result of a drift monitoring run."""

    def __init__(
        self,
        timestamp: datetime,
        status: str,
        discrepancy_count: int,
        worst_delta: float,
        asset_breakdown: Dict[str, int],
        details: Optional[Dict[str, Any]] = None,
    ):
        self.timestamp = timestamp
        self.status = status  # "OK" or "DRIFTING"
        self.discrepancy_count = discrepancy_count
        self.worst_delta = worst_delta
        self.asset_breakdown = asset_breakdown
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "discrepancy_count": self.discrepancy_count,
            "worst_delta": self.worst_delta,
            "asset_breakdown": self.asset_breakdown,
            "details": self.details,
        }


async def pull_live_positions(
    client: KalshiClient,
    subaccount: int = 0,
) -> Dict[str, Any]:
    """Pull current positions from Kalshi.

    Args:
        client: KalshiClient instance
        subaccount: Subaccount ID

    Returns:
        Dict with market_positions and event_positions
    """
    logger.info(f"Pulling live positions for subaccount {subaccount}")

    result = await client.get_positions_result(subaccount=subaccount)
    if not result.success:
        logger.error(f"Failed to pull positions: {result.error}")
        return {"market_positions": [], "event_positions": []}

    data = result.data
    logger.info(f"Retrieved {len(data.get('market_positions', []))} market positions")
    return data


async def pull_recent_fills(
    client: KalshiClient,
    minutes: int = 30,
    subaccount: int = 0,
) -> List[Dict[str, Any]]:
    """Pull recent fills from Kalshi.

    Args:
        client: KalshiClient instance
        minutes: Number of minutes to look back
        subaccount: Subaccount ID

    Returns:
        List of fill dicts
    """
    logger.info(f"Pulling fills from last {minutes} minutes for subaccount {subaccount}")

    # Calculate start time
    start_time = datetime.utcnow() - timedelta(minutes=minutes)

    result = await client.get_fills(
        limit=1000,  # Reasonable limit
        start_ts=int(start_time.timestamp()),
        subaccount=subaccount,
    )

    if not result.success:
        logger.error(f"Failed to pull fills: {result.error}")
        return []

    fills = result.data if isinstance(result.data, list) else []
    logger.info(f"Retrieved {len(fills)} fills")
    return fills


async def replay_fills_to_ledger(
    fills: List[Dict[str, Any]],
    ledger: KalshiFillsLedger,
) -> None:
    """Replay fills into an in-memory ledger.

    Args:
        fills: List of fill dicts from Kalshi
        ledger: KalshiFillsLedger instance
    """
    logger.info(f"Replaying {len(fills)} fills into ledger")

    # Ingest fills
    await ledger.ingest_http_fills(fills, agent_map={})

    # Compute net positions
    positions = ledger.compute_net_positions()
    logger.info(f"Computed positions: {positions}")


async def run_drift_monitor(
    subaccount: int = 0,
    minutes: int = 30,
    ledger_path: Optional[str] = None,
) -> DriftMonitorResult:
    """Run a single drift monitoring cycle.

    Args:
        subaccount: Subaccount ID to monitor
        minutes: Number of minutes to look back for fills
        ledger_path: Optional path for ledger DB (uses in-memory if None)

    Returns:
        DriftMonitorResult with status and details
    """
    start_time = datetime.utcnow()
    logger.info(f"Starting drift monitor cycle for subaccount {subaccount}")

    try:
        # Initialize client
        client = KalshiClient()
        logger.info("KalshiClient initialized")

        # Initialize ledger (in-memory for isolation)
        if ledger_path:
            ledger = KalshiFillsLedger(db_path=ledger_path)
        else:
            import tempfile
            import os
            tmp_dir = tempfile.mkdtemp()
            ledger_path = os.path.join(tmp_dir, "drift_monitor_ledger.db")
            ledger = KalshiFillsLedger(db_path=ledger_path)

        # Pull live data
        positions = await pull_live_positions(client, subaccount)
        fills = await pull_recent_fills(client, minutes, subaccount)

        # Replay fills
        await replay_fills_to_ledger(fills, ledger)

        # Compute internal positions
        internal_positions = ledger.compute_net_positions()

        # Run reconciliation
        discrepancies = reconcile_venue("kalshi")

        # Analyze results
        discrepancy_count = len(discrepancies)
        worst_delta = 0.0
        asset_breakdown = {}

        for d in discrepancies:
            if abs(d.delta_qty) > worst_delta:
                worst_delta = abs(d.delta_qty)

            # Extract asset from symbol
            symbol_parts = d.symbol.split("-")
            if symbol_parts:
                asset = symbol_parts[0].replace("KX", "")
                asset_breakdown[asset] = asset_breakdown.get(asset, 0) + 1

        # Determine status
        status = "OK"
        if discrepancy_count > 0:
            # Check if any critical discrepancies
            critical_count = sum(1 for d in discrepancies if d.severity == "critical")
            if critical_count > 0:
                status = "DRIFTING"

        duration_seconds = (datetime.utcnow() - start_time).total_seconds()

        # Emit metrics
        emit_recon_metrics(
            venue="kalshi",
            duration_seconds=duration_seconds,
            discrepancies=discrepancies,
        )

        result = DriftMonitorResult(
            timestamp=start_time,
            status=status,
            discrepancy_count=discrepancy_count,
            worst_delta=worst_delta,
            asset_breakdown=asset_breakdown,
            details={
                "duration_seconds": duration_seconds,
                "fills_count": len(fills),
                "positions_count": len(positions.get("market_positions", [])),
                "internal_positions": internal_positions,
            },
        )

        logger.info(
            f"Drift monitor complete: status={status}, "
            f"discrepancies={discrepancy_count}, "
            f"worst_delta={worst_delta}"
        )

        return result

    except Exception as e:
        logger.error(f"Drift monitor failed: {e}", exc_info=True)
        return DriftMonitorResult(
            timestamp=start_time,
            status="ERROR",
            discrepancy_count=-1,
            worst_delta=-1.0,
            asset_breakdown={},
            details={"error": str(e)},
        )


def main():
    """Main entry point for drift monitoring."""
    parser = argparse.ArgumentParser(
        description="Kalshi Live Drift Monitoring Script"
    )
    parser.add_argument(
        "--subaccount",
        type=int,
        default=0,
        help="Subaccount ID to monitor (default: 0)",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=30,
        help="Minutes to look back for fills (default: 30)",
    )
    parser.add_argument(
        "--ledger-path",
        type=str,
        default=None,
        help="Optional path for ledger DB (uses in-memory if not specified)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (default: False)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Interval between runs in seconds (default: 300)",
    )
    parser.add_argument(
        "--alert-threshold",
        type=int,
        default=3,
        help="Number of consecutive failures before alerting (default: 3)",
    )
    parser.add_argument(
        "--no-alerts",
        action="store_true",
        help="Disable alerts (default: False)",
    )

    args = parser.parse_args()

    # Initialize alerter if not disabled
    alerter = None
    if not args.no_alerts:
        alerter = DriftAlerter(consecutive_threshold=args.alert_threshold)
        logger.info(f"Alerting enabled (threshold: {args.alert_threshold} consecutive failures)")
    else:
        logger.info("Alerting disabled")

    async def run_cycle():
        result = await run_drift_monitor(
            subaccount=args.subaccount,
            minutes=args.minutes,
            ledger_path=args.ledger_path,
        )
        print(f"\n=== Drift Monitor Result ===")
        print(f"Timestamp: {result.timestamp}")
        print(f"Status: {result.status}")
        print(f"Discrepancies: {result.discrepancy_count}")
        print(f"Worst Delta: {result.worst_delta}")
        print(f"Asset Breakdown: {result.asset_breakdown}")
        print(f"Details: {result.details}")
        print("=" * 30)

        # Check if we should alert
        if alerter and alerter.should_alert(result.status):
            logger.warning(f"Alerting on status: {result.status}")
            asyncio.create_task(alerter.send_alert(
                status=result.status,
                discrepancy_count=result.discrepancy_count,
                worst_delta=result.worst_delta,
                asset_breakdown=result.asset_breakdown,
                details=result.details,
            ))

        return result

    if args.once:
        # Run once and exit
        result = asyncio.run(run_cycle())
        sys.exit(0 if result.status in ["OK", "DRIFTING"] else 1)
    else:
        # Run continuously
        logger.info(f"Starting continuous drift monitoring (interval: {args.interval}s)")
        while True:
            try:
                result = asyncio.run(run_cycle())

                # Log warning if drifting
                if result.status == "DRIFTING":
                    logger.warning(
                        f"DRIFT DETECTED: {result.discrepancy_count} discrepancies, "
                        f"worst delta: {result.worst_delta}"
                    )

            except Exception as e:
                logger.error(f"Drift monitor cycle failed: {e}", exc_info=True)

            # Wait for next cycle
            logger.info(f"Waiting {args.interval}s before next cycle...")
            asyncio.run(asyncio.sleep(args.interval))


if __name__ == "__main__":
    main()
