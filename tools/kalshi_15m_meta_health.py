#!/usr/bin/env python3
"""
Kalshi 15m Meta Health Script - Pre-flight diagnostic for kalshi_crypto_15m_v2 profile.

This script performs a comprehensive health check of the Kalshi 15m trading stack
without placing any orders. It validates:
- WebSocket connectivity and subscription status
- Market state freshness and lock contention
- Bankroll service and event loop health
- Agent grid initialization and evaluation loop

Usage:
    python -m tools.kalshi_15m_meta_health --profile=kalshi_crypto_15m_v2

Output format:
    Concise block per layer with PASS/FAIL status and key metrics.
"""

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class HealthCheckResult:
    """Result of a health check."""
    def __init__(self, component: str, status: str, metrics: Dict[str, Any], message: str = ""):
        self.component = component
        self.status = status  # PASS, FAIL, WARN
        self.metrics = metrics
        self.message = message
    
    def __str__(self) -> str:
        status_symbol = "✓" if self.status == "PASS" else ("⚠" if self.status == "WARN" else "✗")
        metrics_str = ", ".join(f"{k}={v}" for k, v in self.metrics.items())
        return f"{status_symbol} {self.component}: {self.status} | {metrics_str} | {self.message}"


class KalshiMetaHealthChecker:
    """Meta health checker for Kalshi 15m stack."""
    
    def __init__(self, profile: str, diagnostic_mode: bool = True):
        self.profile = profile
        self.diagnostic_mode = diagnostic_mode
        self.results: list[HealthCheckResult] = []
        self.start_time = time.monotonic()
        
        # Set diagnostic mode env var
        if diagnostic_mode:
            os.environ["MERID_VALIDATION_MODE"] = "1"
    
    async def run_checks(self, duration_seconds: int = 120) -> list[HealthCheckResult]:
        """Run all health checks."""
        print(f"\n{'='*70}")
        print(f"KALSHI 15m META HEALTH CHECK")
        print(f"Profile: {self.profile}")
        print(f"Duration: {duration_seconds}s")
        print(f"Diagnostic Mode: {self.diagnostic_mode}")
        print(f"Started: {datetime.now(timezone.utc).isoformat()}")
        print(f"{'='*70}\n")
        
        # Import modules
        try:
            from merid.event_venues.kalshi.ws_bridge import get_bridge
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
            from merid.prediction.agent_grid_15m import get_agent_grid
        except ImportError as e:
            self.results.append(HealthCheckResult(
                "IMPORT",
                "FAIL",
                {},
                f"Failed to import modules: {e}"
            ))
            return self.results
        
        # Initialize components
        try:
            ws_bridge = get_bridge()
            market_state_store = get_kalshi_market_state_store()
            bankroll_service = await get_bankroll_service()
            agent_grid = get_agent_grid()
        except Exception as e:
            self.results.append(HealthCheckResult(
                "INIT",
                "FAIL",
                {},
                f"Failed to initialize components: {e}"
            ))
            return self.results
        
        # Run checks
        await self._check_ws_health(ws_bridge)
        await self._check_market_state_health(market_state_store)
        await self._check_bankroll_health(bankroll_service)
        await self._check_agent_grid_health(agent_grid)
        
        # Wait for specified duration to observe steady-state behavior
        print(f"\nObserving steady-state behavior for {duration_seconds}s...")
        await asyncio.sleep(duration_seconds)
        
        # Final checks
        await self._check_final_state(ws_bridge, market_state_store, bankroll_service, agent_grid)
        
        # Print summary
        self._print_summary()
        
        return self.results
    
    async def _check_ws_health(self, ws_bridge) -> None:
        """Check WebSocket health."""
        print("Checking WebSocket health...")
        
        metrics = {
            "connected": getattr(ws_bridge, '_running', False),
            "subscribed_tickers": len(getattr(ws_bridge, '_subscribed_tickers', set())),
            "recv_errors": getattr(ws_bridge, '_recv_error_count', 0),
            "concurrency_errors": getattr(ws_bridge, '_concurrency_error_count', 0),
        }
        
        status = "PASS"
        message = ""
        
        if not metrics["connected"]:
            status = "FAIL"
            message = "WS not connected"
        elif metrics["subscribed_tickers"] < 5:
            status = "WARN"
            message = f"Expected 5 tickers, got {metrics['subscribed_tickers']}"
        elif metrics["concurrency_errors"] > 0:
            status = "FAIL"
            message = f"Concurrency errors detected: {metrics['concurrency_errors']}"
        
        self.results.append(HealthCheckResult("WS", status, metrics, message))
    
    async def _check_market_state_health(self, market_state_store) -> None:
        """Check market state health."""
        print("Checking market state health...")
        
        # Get all tickers
        tickers = market_state_store.get_all_tickers() if hasattr(market_state_store, 'get_all_tickers') else []
        
        # Check freshness and lock contention
        healthy_count = 0
        stale_count = 0
        total_states = 0
        
        for ticker in tickers[:5]:  # Check first 5 tickers
            state = market_state_store._states.get(ticker)
            if state:
                total_states += 1
                age = time.time() - (state.last_book_update_ts if hasattr(state, 'last_book_update_ts') else 0)
                if age < 15:  # 15s staleness threshold
                    healthy_count += 1
                else:
                    stale_count += 1
        
        metrics = {
            "total_states": total_states,
            "healthy": healthy_count,
            "stale": stale_count,
            "lock_contention": getattr(market_state_store, '_lock_contention_count', 0),
        }
        
        status = "PASS"
        message = ""
        
        if total_states == 0:
            status = "FAIL"
            message = "No market states loaded"
        elif healthy_count < total_states * 0.8:  # Require 80% healthy
            status = "WARN"
            message = f"Only {healthy_count}/{total_states} states healthy"
        elif metrics["lock_contention"] > 10:
            status = "WARN"
            message = f"High lock contention: {metrics['lock_contention']}"
        
        self.results.append(HealthCheckResult("MARKET_STATE", status, metrics, message))
    
    async def _check_bankroll_health(self, bankroll_service) -> None:
        """Check bankroll service health."""
        print("Checking bankroll service health...")
        
        try:
            summary = await bankroll_service.get_summary(caller_module="meta_health")
            
            metrics = {
                "equity_cents": getattr(summary, 'equity_cents', 0),
                "state": str(getattr(summary, 'state', 'UNKNOWN')),
                "fresh": getattr(summary, 'state', None) != "STALE",
            }
            
            status = "PASS"
            message = ""
            
            if not metrics["fresh"]:
                status = "WARN"
                message = "Bankroll state is STALE"
            elif metrics["equity_cents"] == 0:
                status = "WARN"
                message = "Equity is zero"
            
            self.results.append(HealthCheckResult("BANKROLL", status, metrics, message))
        except Exception as e:
            self.results.append(HealthCheckResult(
                "BANKROLL",
                "FAIL",
                {},
                f"Bankroll check failed: {e}"
            ))
    
    async def _check_agent_grid_health(self, agent_grid) -> None:
        """Check agent grid health."""
        print("Checking agent grid health...")
        
        metrics = {
            "running": getattr(agent_grid, '_running', False),
            "agents_count": len(getattr(agent_grid, '_agents', [])),
            "tick": getattr(agent_grid, '_tick', 0),
        }
        
        status = "PASS"
        message = ""
        
        if not metrics["running"]:
            status = "WARN"
            message = "Agent grid not running"
        elif metrics["agents_count"] != 5:
            status = "WARN"
            message = f"Expected 5 agents, got {metrics['agents_count']}"
        
        self.results.append(HealthCheckResult("AGENT_GRID", status, metrics, message))
    
    async def _check_final_state(self, ws_bridge, market_state_store, bankroll_service, agent_grid) -> None:
        """Check final state after observation period."""
        print("Checking final state...")
        
        # Check for any errors during observation
        ws_errors = getattr(ws_bridge, '_recv_error_count', 0)
        lock_contention = getattr(market_state_store, '_lock_contention_count', 0)
        
        metrics = {
            "ws_errors": ws_errors,
            "lock_contention": lock_contention,
            "observation_duration_s": time.monotonic() - self.start_time,
        }
        
        status = "PASS"
        message = ""
        
        if ws_errors > 5:
            status = "WARN"
            message = f"High WS error count: {ws_errors}"
        elif lock_contention > 20:
            status = "WARN"
            message = f"High lock contention: {lock_contention}"
        
        self.results.append(HealthCheckResult("FINAL_STATE", status, metrics, message))
    
    def _print_summary(self) -> None:
        """Print summary of all checks."""
        print(f"\n{'='*70}")
        print("HEALTH CHECK SUMMARY")
        print(f"{'='*70}\n")
        
        for result in self.results:
            print(result)
        
        # Overall status
        pass_count = sum(1 for r in self.results if r.status == "PASS")
        fail_count = sum(1 for r in self.results if r.status == "FAIL")
        warn_count = sum(1 for r in self.results if r.status == "WARN")
        
        print(f"\n{'='*70}")
        print(f"TOTAL: {len(self.results)} checks")
        print(f"PASS: {pass_count}")
        print(f"WARN: {warn_count}")
        print(f"FAIL: {fail_count}")
        print(f"{'='*70}\n")
        
        if fail_count > 0:
            print("❌ HEALTH CHECK FAILED - Do not enable live trading")
            sys.exit(1)
        elif warn_count > 0:
            print("⚠️  HEALTH CHECK PASSED WITH WARNINGS - Review before enabling live trading")
            sys.exit(2)
        else:
            print("✅ HEALTH CHECK PASSED - Safe to enable live trading")
            sys.exit(0)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Kalshi 15m Meta Health Check")
    parser.add_argument("--profile", default="kalshi_crypto_15m_v2", help="Profile to check")
    parser.add_argument("--duration", type=int, default=120, help="Observation duration in seconds")
    parser.add_argument("--no-diagnostic", action="store_true", help="Disable diagnostic mode")
    
    args = parser.parse_args()
    
    checker = KalshiMetaHealthChecker(
        profile=args.profile,
        diagnostic_mode=not args.no_diagnostic
    )
    
    await checker.run_checks(duration_seconds=args.duration)


if __name__ == "__main__":
    asyncio.run(main())
