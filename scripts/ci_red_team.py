#!/usr/bin/env python3
"""
MERID Red Team CI Script

Continuous invariant testing for the MERID UI spine.
This script runs random bursts of orders and verifies cross-view invariants.

Usage:
    python scripts/ci_red_team.py [--profile kalshi-only] [--duration 300]

Exit codes:
    0 - All invariants passed
    1 - Invariant violation detected
    2 - System not responsive
    3 - Configuration error
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ci_red_team")


@dataclass
class InvariantResult:
    """Result of a single invariant check."""
    name: str
    passed: bool
    details: Dict[str, Any]
    timestamp: str


class MERIDRedTeam:
    """Red team testing harness for MERID trading system."""
    
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        profile: str = "kalshi-only",
        assets: List[str] = None,
    ):
        self.base_url = base_url
        self.profile = profile
        self.assets = assets or ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        self.session: Optional[aiohttp.ClientSession] = None
        self.results: List[InvariantResult] = []
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def _get(self, endpoint: str) -> Tuple[int, Dict]:
        """GET request to API."""
        url = f"{self.base_url}{endpoint}"
        try:
            async with self.session.get(url) as resp:
                data = await resp.json() if resp.status == 200 else {}
                return resp.status, data
        except Exception as exc:
            logger.error(f"GET {endpoint} failed: {exc}")
            return 0, {"error": str(exc)}
    
    async def _post(self, endpoint: str, payload: Dict) -> Tuple[int, Dict]:
        """POST request to API."""
        url = f"{self.base_url}{endpoint}"
        try:
            async with self.session.post(url, json=payload) as resp:
                data = await resp.json() if resp.status in (200, 201) else {}
                return resp.status, data
        except Exception as exc:
            logger.error(f"POST {endpoint} failed: {exc}")
            return 0, {"error": str(exc)}
    
    # ═════════════════════════════════════════════════════════════════════════════
    # Invariant Tests
    # ═════════════════════════════════════════════════════════════════════════════
    
    async def invariant_positions_have_fills(self) -> InvariantResult:
        """
        Every non-synthetic position must have at least one backing fill.
        """
        status_code, positions_data = await self._get("/api/v1/kalshi/positions")
        if status_code != 200:
            return InvariantResult(
                name="positions_have_fills",
                passed=False,
                details={"error": f"Failed to fetch positions: {status_code}"},
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        
        status_code, fills_data = await self._get("/api/v1/kalshi/fills?since_hours=168")
        if status_code != 200:
            return InvariantResult(
                name="positions_have_fills",
                passed=False,
                details={"error": f"Failed to fetch fills: {status_code}"},
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        
        positions = positions_data.get("positions", [])
        fills = fills_data.get("fills", [])
        
        fills_by_ticker = {}
        for fill in fills:
            ticker = fill.get("ticker")
            if ticker:
                fills_by_ticker.setdefault(ticker, []).append(fill)
        
        violations = []
        for pos in positions:
            if pos.get("synthetic") or pos.get("manual_or_external"):
                continue
            
            ticker = pos.get("ticker")
            if not fills_by_ticker.get(ticker):
                violations.append({
                    "ticker": ticker,
                    "size": pos.get("size"),
                    "issue": "no_backing_fills",
                })
        
        return InvariantResult(
            name="positions_have_fills",
            passed=len(violations) == 0,
            details={
                "positions_checked": len(positions),
                "fills_checked": len(fills),
                "violations": violations,
            },
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    
    async def invariant_kill_switch_consistency(self) -> InvariantResult:
        """
        Kill switch state must be consistent across /risk and /operator endpoints.
        """
        status_code1, risk_data = await self._get("/api/v1/kalshi/risk")
        status_code2, operator_data = await self._get("/api/v1/operator/kill-switch-status")
        
        if status_code1 != 200 or status_code2 != 200:
            return InvariantResult(
                name="kill_switch_consistency",
                passed=False,
                details={
                    "error": "Failed to fetch kill switch status",
                    "risk_status": status_code1,
                    "operator_status": status_code2,
                },
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        
        risk_ks = risk_data.get("kill_switch_active", False)
        operator_ks = operator_data.get("kill_switch_active") or operator_data.get("active", False)
        
        consistent = risk_ks == operator_ks
        
        return InvariantResult(
            name="kill_switch_consistency",
            passed=consistent,
            details={
                "risk_kill_switch": risk_ks,
                "operator_kill_switch": operator_ks,
                "mismatch": not consistent,
            },
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    
    async def invariant_synthetic_gating(self) -> InvariantResult:
        """
        Synthetic data must never appear in default (ungated) responses.
        """
        status_code, orders_data = await self._get("/api/v1/kalshi/orders")
        if status_code != 200:
            return InvariantResult(
                name="synthetic_gating",
                passed=False,
                details={"error": f"Failed to fetch orders: {status_code}"},
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        
        status_code, positions_data = await self._get("/api/v1/kalshi/positions")
        if status_code != 200:
            return InvariantResult(
                name="synthetic_gating",
                passed=False,
                details={"error": f"Failed to fetch positions: {status_code}"},
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        
        orders = orders_data.get("orders", [])
        positions = positions_data.get("positions", [])
        
        synthetic_orders = [o for o in orders if o.get("synthetic")]
        synthetic_positions = [p for p in positions if p.get("synthetic")]
        
        violations = []
        if synthetic_orders:
            violations.append({
                "type": "synthetic_orders_in_default",
                "count": len(synthetic_orders),
                "examples": [o.get("order_id") for o in synthetic_orders[:3]],
            })
        if synthetic_positions:
            violations.append({
                "type": "synthetic_positions_in_default",
                "count": len(synthetic_positions),
                "examples": [p.get("ticker") for p in synthetic_positions[:3]],
            })
        
        return InvariantResult(
            name="synthetic_gating",
            passed=len(violations) == 0,
            details={
                "orders_checked": len(orders),
                "positions_checked": len(positions),
                "violations": violations,
            },
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    
    async def invariant_reconciliation_exposed(self) -> InvariantResult:
        """
        Reconciliation status must be exposed in /positions and /risk.
        """
        endpoints = [
            "/api/v1/kalshi/positions",
            "/api/v1/kalshi/risk",
        ]
        
        missing = []
        for endpoint in endpoints:
            status_code, data = await self._get(endpoint)
            if status_code == 200 and "reconciliation_status" not in data:
                missing.append(endpoint)
        
        return InvariantResult(
            name="reconciliation_exposed",
            passed=len(missing) == 0,
            details={"endpoints_missing_field": missing},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    
    async def invariant_lineage_complete(self) -> InvariantResult:
        """
        Sample real orders must have complete lineage (signal → agent → risk → router).
        """
        status_code, orders_data = await self._get("/api/v1/kalshi/orders")
        if status_code != 200:
            return InvariantResult(
                name="lineage_complete",
                passed=False,
                details={"error": f"Failed to fetch orders: {status_code}"},
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        
        orders = orders_data.get("orders", [])
        real_orders = [o for o in orders if not o.get("synthetic") and not o.get("manual_or_external")]
        
        if not real_orders:
            return InvariantResult(
                name="lineage_complete",
                passed=True,
                details={"note": "No real orders to check"},
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        
        # Sample up to 3 orders for lineage check
        sample = random.sample(real_orders, min(3, len(real_orders)))
        
        incomplete = []
        for order in sample:
            order_id = order.get("order_id")
            status_code, lineage = await self._get(f"/api/v1/kalshi/orders/{order_id}/lineage")
            
            if status_code != 200:
                incomplete.append({"order_id": order_id, "issue": "lineage_endpoint_failed"})
                continue
            
            if not lineage.get("chain_complete"):
                incomplete.append({
                    "order_id": order_id,
                    "issue": "incomplete_chain",
                    "chain_coverage": lineage.get("chain_coverage"),
                    "warnings": lineage.get("warnings", []),
                })
        
        return InvariantResult(
            name="lineage_complete",
            passed=len(incomplete) == 0,
            details={
                "orders_checked": len(sample),
                "incomplete_lineage": incomplete,
            },
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    
    async def invariant_pnl_divergence(self, threshold_usd: float = 5.0) -> InvariantResult:
        """
        PnL from fills ledger must match risk controller PnL within threshold.
        """
        status_code, recon_data = await self._get("/api/v1/kalshi/reconciliation/breaks")
        if status_code != 200:
            return InvariantResult(
                name="pnl_divergence",
                passed=False,
                details={"error": f"Failed to fetch reconciliation: {status_code}"},
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        
        pnl_divergence = recon_data.get("summary", {}).get("pnl_divergence", 0)
        
        return InvariantResult(
            name="pnl_divergence",
            passed=pnl_divergence <= threshold_usd,
            details={
                "pnl_divergence_usd": pnl_divergence,
                "threshold_usd": threshold_usd,
                "break_count": recon_data.get("break_count", 0),
            },
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    
    # ═════════════════════════════════════════════════════════════════════════════
    # Order Burst Generation
    # ═════════════════════════════════════════════════════════════════════════════
    
    async def burst_orders(self, count: int = 5) -> List[Dict]:
        """
        Generate a burst of random orders via canonical router.
        Returns list of order results.
        """
        results = []
        
        for i in range(count):
            asset = random.choice(self.assets)
            ticker = f"KX{asset}15M-25MAR26"  # Example ticker format
            
            payload = {
                "ticker": ticker,
                "side": random.choice(["yes", "no"]),
                "action": "buy",
                "price_cents": random.randint(45, 55),
                "count": 1,
                "mode": "paper",  # Always paper for CI testing
            }
            
            try:
                # Use the canary trade endpoint for safe testing
                status_code, result = await self._post(
                    "/api/v1/kalshi-grid/canary-trade",
                    payload
                )
                results.append({
                    "ticker": ticker,
                    "status_code": status_code,
                    "result": result,
                })
            except Exception as exc:
                results.append({
                    "ticker": ticker,
                    "error": str(exc),
                })
            
            # Small delay between orders
            await asyncio.sleep(0.5)
        
        return results
    
    # ═════════════════════════════════════════════════════════════════════════════
    # Main Test Loop
    # ═════════════════════════════════════════════════════════════════════════════
    
    async def run_all_invariants(self) -> List[InvariantResult]:
        """Run all invariant tests."""
        invariants = [
            self.invariant_positions_have_fills(),
            self.invariant_kill_switch_consistency(),
            self.invariant_synthetic_gating(),
            self.invariant_reconciliation_exposed(),
            self.invariant_lineage_complete(),
            self.invariant_pnl_divergence(),
        ]
        
        results = await asyncio.gather(*invariants, return_exceptions=True)
        
        # Handle exceptions
        processed = []
        for result in results:
            if isinstance(result, Exception):
                processed.append(InvariantResult(
                    name="unknown",
                    passed=False,
                    details={"exception": str(result)},
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))
            else:
                processed.append(result)
        
        return processed
    
    async def run_ci_loop(
        self,
        duration_sec: int = 300,
        burst_interval_sec: int = 60,
        invariant_interval_sec: int = 30,
    ) -> int:
        """
        Main CI loop: bursts + invariant checks.
        
        Returns exit code: 0 = success, 1 = invariant violation
        """
        logger.info(f"Starting CI Red Team loop (duration={duration_sec}s, profile={self.profile})")
        
        start_time = time.time()
        last_burst = 0
        last_invariant = 0
        all_passed = True
        
        while time.time() - start_time < duration_sec:
            current_time = time.time()
            
            # Run invariant checks
            if current_time - last_invariant >= invariant_interval_sec:
                logger.info("Running invariant checks...")
                results = await self.run_all_invariants()
                
                for result in results:
                    status = "✓ PASS" if result.passed else "✗ FAIL"
                    logger.info(f"  {status}: {result.name}")
                    if not result.passed:
                        all_passed = False
                        logger.error(f"    Details: {json.dumps(result.details, indent=2)}")
                
                last_invariant = current_time
            
            # Generate order burst
            if current_time - last_burst >= burst_interval_sec:
                logger.info("Generating order burst...")
                burst_results = await self.burst_orders(count=3)
                success_count = sum(1 for r in burst_results if r.get("status_code") == 200)
                logger.info(f"  Burst complete: {success_count}/{len(burst_results)} orders successful")
                last_burst = current_time
            
            # Small sleep to prevent tight loop
            await asyncio.sleep(1)
        
        # Final summary
        logger.info("=" * 60)
        if all_passed:
            logger.info("CI Red Team: ALL INVARIANTS PASSED ✓")
            return 0
        else:
            logger.error("CI Red Team: INVARIANT VIOLATIONS DETECTED ✗")
            return 1


def main():
    parser = argparse.ArgumentParser(description="MERID Red Team CI Script")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--profile", default="kalshi-only", help="Trading profile")
    parser.add_argument("--duration", type=int, default=300, help="Test duration in seconds")
    parser.add_argument("--burst-interval", type=int, default=60, help="Seconds between order bursts")
    parser.add_argument("--invariant-interval", type=int, default=30, help="Seconds between invariant checks")
    parser.add_argument("--assets", nargs="+", default=["BTC", "ETH", "SOL", "XRP", "DOGE"], help="Assets to test")
    
    args = parser.parse_args()
    
    async def run():
        async with MERIDRedTeam(
            base_url=args.base_url,
            profile=args.profile,
            assets=args.assets,
        ) as redteam:
            exit_code = await redteam.run_ci_loop(
                duration_sec=args.duration,
                burst_interval_sec=args.burst_interval,
                invariant_interval_sec=args.invariant_interval,
            )
            return exit_code
    
    try:
        exit_code = asyncio.run(run())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
    except Exception as exc:
        logger.error(f"Fatal error: {exc}")
        sys.exit(3)


if __name__ == "__main__":
    main()
