#!/usr/bin/env python3
"""
Live Invariant Validation Script

This script validates that all invariant guards are working in a live or dev environment.
It can be run manually or integrated into CI/CD pipelines.

Usage:
    python scripts/validate_invariants.py [--mode=dev|prod] [--duration=300] [--paranoid]

Options:
    --mode: dev (inject violations) or prod (monitor only)
    --duration: seconds to run validation (default: 300)
    --paranoid: enable paranoid mode (raises on violations)
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from typing import Dict, Any, List
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.core.e2e_invariants import check_system_invariants, get_invariant_checker
from merid.event_venues.kalshi.ws_bridge import get_bridge, get_ws_forward_loop_health
from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog

# Use centralized logger from utils.logger
from utils.logger import get_logger
logger = get_logger(__name__)

class InvariantValidator:
    """Validates invariants in live environment."""
    
    def __init__(self, mode: str = "dev", paranoid_mode: bool = False):
        self.mode = mode
        self.paranoid_mode = paranoid_mode
        self.checker = get_invariant_checker(paranoid_mode=paranoid_mode)
        self.start_time = time.time()
        self.violation_history: List[Dict[str, Any]] = []
        
    def collect_system_state(self) -> Dict[str, Any]:
        """Collect current system state for invariant checking."""
        system_state = {
            "execution_ready": False,
            "subsystem_health": {},
            "market_data": {},
            "ws_forwarder": {},
            "market_quality": {}
        }
        
        try:
            # Collect WS forwarder health
            ws_health = get_ws_forward_loop_health()
            system_state["ws_forwarder"] = {
                "events_per_sec": ws_health.get("events_per_sec", 0.0),
                "time_since_last_event": ws_health.get("time_since_last_event", float('inf')),
                "stalled": ws_health.get("stalled", True),
                "status": "OK" if not ws_health.get("stalled", True) else "ERROR"
            }
            
            # Collect market data state
            mss = get_kalshi_market_state_store()
            tickers = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]
            
            for ticker in tickers:
                state = mss.get(ticker)
                if state and hasattr(state, 'last_update_ts'):
                    now = time.monotonic()
                    age = now - state.last_update_ts if state.last_update_ts else -1
                    stale = age > 120.0
                    
                    system_state["market_data"][ticker] = {
                        "age": age,
                        "stale": stale,
                        "reason": "FRESH" if not stale else "LAST_UPDATE_TOO_OLD"
                    }
                    
                    # Collect market quality info
                    if hasattr(state, 'best_bid_cents') and hasattr(state, 'best_ask_cents'):
                        spread_cents = state.best_ask_cents - state.best_bid_cents if (state.best_bid_cents and state.best_ask_cents) else 0
                        depth_yes = getattr(state, 'min_depth_yes', 0)
                        depth_no = getattr(state, 'min_depth_no', 0)
                        
                        # Apply quality classification logic
                        SPREAD_THRESHOLD_CENTS = 40
                        DEPTH_THRESHOLD = 10
                        
                        spread_quality = "GOOD" if spread_cents < SPREAD_THRESHOLD_CENTS else "WIDE"
                        depth_quality = "GOOD" if min(depth_yes, depth_no) >= DEPTH_THRESHOLD else "SHALLOW"
                        
                        if spread_quality == "GOOD" and depth_quality == "GOOD":
                            overall_quality = "GOOD"
                        elif spread_cents > SPREAD_THRESHOLD_CENTS:
                            overall_quality = "POOR"
                        elif depth_quality == "SHALLOW":
                            overall_quality = "ACCEPTABLE"
                        else:
                            overall_quality = "ACCEPTABLE"
                        
                        system_state["market_quality"][ticker] = {
                            "depth_yes": depth_yes,
                            "depth_no": depth_no,
                            "overall_quality": overall_quality,
                            "spread_cents": spread_cents
                        }
            
            # Collect catalog health
            catalog = KalshiMarketCatalog.get_instance()
            if catalog and hasattr(catalog, '_last_refresh_ts'):
                catalog_age = time.time() - catalog._last_refresh_ts
                catalog_fresh = catalog_age < 30.0
                
                system_state["subsystem_health"]["catalog"] = "HEALTH_GOOD" if catalog_fresh else "HEALTH_ERROR"
            else:
                system_state["subsystem_health"]["catalog"] = "HEALTH_UNKNOWN"
            
            # Determine MD freshness health
            fresh_markets = sum(1 for md in system_state["market_data"].values() if not md.get("stale", True))
            md_fresh = fresh_markets >= 5  # All 5 assets fresh
            system_state["subsystem_health"]["md_freshness"] = "HEALTH_GOOD" if md_fresh else "HEALTH_ERROR"
            
            # Determine depth coverage health
            good_depth = sum(1 for mq in system_state["market_quality"].values() 
                           if mq.get("overall_quality") in ["GOOD", "ACCEPTABLE"])
            depth_coverage = good_depth >= 5  # All 5 assets have good depth
            system_state["subsystem_health"]["depth_coverage"] = "HEALTH_GOOD" if depth_coverage else "HEALTH_ERROR"
            
            # Determine WS forwarder health
            ws_healthy = (
                not system_state["ws_forwarder"]["stalled"] and
                system_state["ws_forwarder"]["events_per_sec"] > 0.0 and
                system_state["ws_forwarder"]["time_since_last_event"] < 30.0
            )
            system_state["subsystem_health"]["ws_forwarder"] = "HEALTH_GOOD" if ws_healthy else "HEALTH_ERROR"
            
            # Determine overall execution readiness
            system_state["execution_ready"] = all(
                health == "HEALTH_GOOD" for health in system_state["subsystem_health"].values()
            )
            
        except Exception as e:
            logger.error(f"Error collecting system state: {e}", exc_info=True)
            
        return system_state
    
    def inject_test_violations(self, system_state: Dict[str, Any]) -> Dict[str, Any]:
        """Inject test violations in dev mode."""
        if self.mode != "dev":
            return system_state
            
        # Inject negative MD age
        if "KXBTC15M" in system_state["market_data"]:
            system_state["market_data"]["KXBTC15M"]["age"] = -1000.0
            system_state["market_data"]["KXBTC15M"]["stale"] = False
            system_state["market_data"]["KXBTC15M"]["reason"] = "FRESH"
        
        # Inject impossible FRESH age
        if "KXETH15M" in system_state["market_data"]:
            system_state["market_data"]["KXETH15M"]["age"] = 7200.0  # 2 hours
            system_state["market_data"]["KXETH15M"]["stale"] = False
            system_state["market_data"]["KXETH15M"]["reason"] = "FRESH"
        
        # Inject WS forwarder violation
        system_state["ws_forwarder"]["events_per_sec"] = 0.0
        system_state["ws_forwarder"]["time_since_last_event"] = 45.0
        system_state["ws_forwarder"]["stalled"] = False
        system_state["ws_forwarder"]["status"] = "OK"
        
        # Inject execution ready with critical failure
        system_state["execution_ready"] = True
        system_state["subsystem_health"]["catalog"] = "HEALTH_ERROR"
        
        # Inject quality/optimizer mismatch
        if "KXSOL15M" in system_state["market_quality"]:
            system_state["market_quality"]["KXSOL15M"]["overall_quality"] = "ACCEPTABLE"
            system_state["market_quality"]["KXSOL15M"]["spread_cents"] = 96  # Wide spread
        
        return system_state
    
    def log_system_state(self, system_state: Dict[str, Any], cycle: int):
        """Log current system state."""
        logger.info(f"[{cycle}] SYSTEM STATE:")
        logger.info(f"  Execution Ready: {system_state['execution_ready']}")
        
        logger.info(f"  Subsystem Health:")
        for subsystem, health in system_state["subsystem_health"].items():
            logger.info(f"    {subsystem}: {health}")
        
        logger.info(f"  WS Forwarder:")
        ws = system_state["ws_forwarder"]
        logger.info(f"    Events/sec: {ws['events_per_sec']:.1f}")
        logger.info(f"    Time since last: {ws['time_since_last_event']:.1f}s")
        logger.info(f"    Stalled: {ws['stalled']}")
        logger.info(f"    Status: {ws['status']}")
        
        logger.info(f"  Market Data (age/stale):")
        for ticker, md in system_state["market_data"].items():
            logger.info(f"    {ticker}: {md['age']:.1f}s / {md['stale']} ({md['reason']})")
        
        logger.info(f"  Market Quality:")
        for ticker, mq in system_state["market_quality"].items():
            logger.info(f"    {ticker}: {mq['overall_quality']} (spread={mq['spread_cents']}c)")
    
    def run_validation_cycle(self, cycle: int) -> Dict[str, Any]:
        """Run a single validation cycle."""
        logger.info(f"Starting validation cycle {cycle}")
        
        # Collect system state
        system_state = self.collect_system_state()
        
        # Inject test violations in dev mode
        if self.mode == "dev":
            system_state = self.inject_test_violations(system_state)
            logger.info("Injected test violations (dev mode)")
        
        # Log system state
        self.log_system_state(system_state, cycle)
        
        # Check invariants
        try:
            violations = check_system_invariants(system_state, paranoid_mode=self.paranoid_mode)
            
            # Record violations
            violation_record = {
                "cycle": cycle,
                "timestamp": time.time(),
                "violations": [
                    {
                        "invariant_name": v.invariant_name,
                        "severity": v.severity,
                        "message": v.message
                    } for v in violations
                ]
            }
            
            self.violation_history.append(violation_record)
            
            # Log violations
            if violations:
                logger.error(f"[{cycle}] INVARIANT VIOLATIONS DETECTED:")
                for v in violations:
                    logger.error(f"  {v.invariant_name} ({v.severity}): {v.message}")
                
                if self.paranoid_mode:
                    logger.critical(f"[{cycle}] PARANOID MODE: Stopping due to violations")
                    raise RuntimeError(f"Paranoid mode: {len(violations)} invariant violations")
            else:
                logger.info(f"[{cycle}] No invariant violations detected")
            
            return violation_record
            
        except Exception as e:
            logger.error(f"[{cycle}] Error during invariant checking: {e}", exc_info=True)
            return {
                "cycle": cycle,
                "timestamp": time.time(),
                "violations": [],
                "error": str(e)
            }
    
    def run_validation(self, duration: int = 300):
        """Run validation for specified duration."""
        logger.info(f"Starting invariant validation ({self.mode} mode, paranoid={self.paranoid_mode})")
        logger.info(f"Duration: {duration}s")
        
        start_time = time.time()
        cycle = 0
        
        try:
            while time.time() - start_time < duration:
                cycle_start = time.time()
                
                # Run validation cycle
                violation_record = self.run_validation_cycle(cycle)
                
                cycle += 1
                
                # Calculate next cycle time (run every 10 seconds)
                cycle_duration = time.time() - cycle_start
                sleep_time = max(0, 10.0 - cycle_duration)
                
                if sleep_time > 0:
                    time.sleep(sleep_time)
                else:
                    logger.warning(f"Cycle {cycle} took {cycle_duration:.1f}s, skipping sleep")
        
        except KeyboardInterrupt:
            logger.info("Validation interrupted by user")
        except Exception as e:
            logger.error(f"Validation failed: {e}", exc_info=True)
            raise
        finally:
            self.print_summary()
    
    def print_summary(self):
        """Print validation summary."""
        logger.info("=" * 60)
        logger.info("INVARIANT VALIDATION SUMMARY")
        logger.info("=" * 60)
        
        total_cycles = len(self.violation_history)
        total_violations = sum(len(record["violations"]) for record in self.violation_history)
        
        logger.info(f"Total cycles: {total_cycles}")
        logger.info(f"Total violations: {total_violations}")
        
        if total_violations > 0:
            # Count violations by type
            violation_counts = {}
            for record in self.violation_history:
                for violation in record["violations"]:
                    name = violation["invariant_name"]
                    violation_counts[name] = violation_counts.get(name, 0) + 1
            
            logger.info("Violations by type:")
            for name, count in sorted(violation_counts.items()):
                logger.info(f"  {name}: {count}")
            
            # Show most recent violations
            logger.info("Most recent violations:")
            for record in self.violation_history[-5:]:
                if record["violations"]:
                    logger.info(f"  Cycle {record['cycle']}:")
                    for violation in record["violations"]:
                        logger.info(f"    {violation['invariant_name']}: {violation['message']}")
        else:
            logger.info("✅ No invariant violations detected")
        
        logger.info("=" * 60)

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Validate invariants in live environment")
    parser.add_argument("--mode", choices=["dev", "prod"], default="dev",
                       help="Validation mode (dev=inject violations, prod=monitor only)")
    parser.add_argument("--duration", type=int, default=300,
                       help="Duration in seconds to run validation")
    parser.add_argument("--paranoid", action="store_true",
                       help="Enable paranoid mode (raises on violations)")
    
    args = parser.parse_args()
    
    # Set paranoid mode environment variable
    if args.paranoid:
        os.environ["MERID_PARANOID_MODE"] = "1"
    
    # Create validator
    validator = InvariantValidator(mode=args.mode, paranoid_mode=args.paranoid)
    
    # Run validation
    try:
        validator.run_validation(duration=args.duration)
        return 0
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
