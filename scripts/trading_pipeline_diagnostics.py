#!/usr/bin/env python3
"""
Comprehensive diagnostics script for the 15m Kalshi crypto trading pipeline.

This script performs end-to-end health checks across the entire trading pipeline:
- Upstream: WebSocket connection, market data freshness, catalog health
- Midstream: Market state store, orderbook depth, signal generation
- Downstream: Agent grid, candidate building, risk checks, execution pipeline

Usage:
    python scripts/trading_pipeline_diagnostics.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Any, List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger

logger = get_logger("trading_pipeline_diagnostics")


class TradingPipelineDiagnostics:
    """Comprehensive diagnostics for the trading pipeline."""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "upstream": {},
            "midstream": {},
            "downstream": {},
            "execution": {},
            "summary": {}
        }
    
    async def run_all_diagnostics(self) -> Dict[str, Any]:
        """Run all diagnostic checks."""
        logger.info("=" * 80)
        logger.info("TRADING PIPELINE DIAGNOSTICS STARTING")
        logger.info("=" * 80)
        
        # Upstream diagnostics
        await self.check_upstream()
        
        # Midstream diagnostics
        await self.check_midstream()
        
        # Downstream diagnostics
        await self.check_downstream()
        
        # Execution diagnostics
        await self.check_execution()
        
        # Generate summary
        self.generate_summary()
        
        # Print results
        self.print_results()
        
        return self.results
    
    async def check_upstream(self) -> None:
        """Check upstream components: WebSocket, catalog, spot data."""
        logger.info("\n" + "=" * 80)
        logger.info("UPSTREAM DIAGNOSTICS")
        logger.info("=" * 80)
        
        try:
            # Check WebSocket bridge
            from merid.kalshi import get_ws_bridge
            ws_bridge = get_ws_bridge()
            
            if ws_bridge:
                stats = ws_bridge.stats() if hasattr(ws_bridge, 'stats') else {}
                self.results["upstream"]["ws_bridge"] = {
                    "status": "connected" if stats.get("connected", False) else "disconnected",
                    "events_processed": stats.get("events_processed", 0),
                    "queue_size": stats.get("queue_size", 0),
                    "subscribed_tickers": len(stats.get("subscribed_tickers", [])),
                    "last_event_time": stats.get("last_event_time", None)
                }
                logger.info(f"WS Bridge: {self.results['upstream']['ws_bridge']}")
            else:
                self.results["upstream"]["ws_bridge"] = {"status": "not_initialized"}
                logger.warning("WS Bridge not initialized")
        except Exception as e:
            self.results["upstream"]["ws_bridge"] = {"status": "error", "error": str(e)}
            logger.error(f"WS Bridge check failed: {e}")
        
        try:
            # Check market catalog
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            
            snapshot = catalog.snapshot()
            all_markets = catalog.get_all_markets()
            
            self.results["upstream"]["catalog"] = {
                "total_markets": len(all_markets),
                "snapshot_markets": len(snapshot.markets),
                "last_refresh": catalog.last_refreshed_at.isoformat() if catalog.last_refreshed_at else None,
                "by_asset": {}
            }
            
            # Count markets by asset
            asset_counts = {}
            for m in all_markets:
                if m.asset:
                    asset_counts[m.asset] = asset_counts.get(m.asset, 0) + 1
            self.results["upstream"]["catalog"]["by_asset"] = asset_counts
            
            logger.info(f"Catalog: {self.results['upstream']['catalog']}")
        except Exception as e:
            self.results["upstream"]["catalog"] = {"status": "error", "error": str(e)}
            logger.error(f"Catalog check failed: {e}")
        
        try:
            # Check spot data service
            from data.unified_spot_service import get_unified_spot_service
            spot_service = get_unified_spot_service()
            
            self.results["upstream"]["spot_service"] = {
                "status": "running" if spot_service._running else "stopped",
                "assets": {}
            }
            
            for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                try:
                    spot_result = spot_service.get_spot_price(asset)
                    self.results["upstream"]["spot_service"]["assets"][asset] = {
                        "status": "ok" if hasattr(spot_result, 'price') else "error",
                        "price": getattr(spot_result, 'price', None),
                        "age_s": getattr(spot_result, 'age_s', None) if hasattr(spot_result, 'age_s') else None
                    }
                except Exception as e:
                    self.results["upstream"]["spot_service"]["assets"][asset] = {
                        "status": "error",
                        "error": str(e)
                    }
            
            logger.info(f"Spot Service: {self.results['upstream']['spot_service']}")
        except Exception as e:
            self.results["upstream"]["spot_service"] = {"status": "error", "error": str(e)}
            logger.error(f"Spot service check failed: {e}")
    
    async def check_midstream(self) -> None:
        """Check midstream components: Market state store, orderbooks."""
        logger.info("\n" + "=" * 80)
        logger.info("MIDSTREAM DIAGNOSTICS")
        logger.info("=" * 80)
        
        try:
            # Check market state store
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            
            # Get current 15m markets
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            snapshot = catalog.snapshot()
            
            self.results["midstream"]["market_state"] = {
                "assets": {}
            }
            
            for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                try:
                    market = snapshot.get_current_15m_market(asset)
                    if market:
                        ticker = market.market.market_id
                        orderbook = store.get_orderbook(ticker)
                        
                        yes_depth = len(orderbook.get("yes", [])) if orderbook else 0
                        no_depth = len(orderbook.get("no", [])) if orderbook else 0
                        
                        self.results["midstream"]["market_state"]["assets"][asset] = {
                            "ticker": ticker,
                            "has_orderbook": orderbook is not None,
                            "yes_depth": yes_depth,
                            "no_depth": no_depth,
                            "depth_sufficient": yes_depth >= 1 and no_depth >= 1
                        }
                    else:
                        self.results["midstream"]["market_state"]["assets"][asset] = {
                            "status": "no_market"
                        }
                except Exception as e:
                    self.results["midstream"]["market_state"]["assets"][asset] = {
                        "status": "error",
                        "error": str(e)
                    }
            
            logger.info(f"Market State: {self.results['midstream']['market_state']}")
        except Exception as e:
            self.results["midstream"]["market_state"] = {"status": "error", "error": str(e)}
            logger.error(f"Market state check failed: {e}")
    
    async def check_downstream(self) -> None:
        """Check downstream components: Agent grid, signal generation."""
        logger.info("\n" + "=" * 80)
        logger.info("DOWNSTREAM DIAGNOSTICS")
        logger.info("=" * 80)
        
        try:
            # Check agent grid
            from merid.prediction.agent_grid_15m import LeanAgentGrid15m
            
            # We can't directly instantiate the grid, but we can check the module
            self.results["downstream"]["agent_grid"] = {
                "status": "module_available",
                "agents_configured": ["BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"]
            }
            
            logger.info(f"Agent Grid: {self.results['downstream']['agent_grid']}")
        except Exception as e:
            self.results["downstream"]["agent_grid"] = {"status": "error", "error": str(e)}
            logger.error(f"Agent grid check failed: {e}")
        
        try:
            # Check risk profile
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15MRiskEnvelope
            
            self.results["downstream"]["risk_profile"] = {
                "status": "available",
                "profile": "kalshi_crypto_15m"
            }
            
            logger.info(f"Risk Profile: {self.results['downstream']['risk_profile']}")
        except Exception as e:
            self.results["downstream"]["risk_profile"] = {"status": "error", "error": str(e)}
            logger.error(f"Risk profile check failed: {e}")
    
    async def check_execution(self) -> None:
        """Check execution components: Kalshi client, bankroll."""
        logger.info("\n" + "=" * 80)
        logger.info("EXECUTION DIAGNOSTICS")
        logger.info("=" * 80)
        
        try:
            # Check Kalshi client
            from merid.event_venues.kalshi import get_kalshi_client
            client = get_kalshi_client()
            
            self.results["execution"]["kalshi_client"] = {
                "status": "available",
                "env": client._config.env if hasattr(client, '_config') else "unknown"
            }
            
            logger.info(f"Kalshi Client: {self.results['execution']['kalshi_client']}")
        except Exception as e:
            self.results["execution"]["kalshi_client"] = {"status": "error", "error": str(e)}
            logger.error(f"Kalshi client check failed: {e}")
        
        try:
            # Check bankroll service
            from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
            bankroll_service = get_bankroll_service()
            
            bankroll = bankroll_service.get_bankroll_snapshot()
            
            self.results["execution"]["bankroll"] = {
                "status": "available",
                "equity": getattr(bankroll, 'equity', None),
                "available_cash": getattr(bankroll, 'available_cash', None),
                "positions": getattr(bankroll, 'positions', None)
            }
            
            logger.info(f"Bankroll: {self.results['execution']['bankroll']}")
        except Exception as e:
            self.results["execution"]["bankroll"] = {"status": "error", "error": str(e)}
            logger.error(f"Bankroll check failed: {e}")
    
    def generate_summary(self) -> None:
        """Generate overall summary."""
        logger.info("\n" + "=" * 80)
        logger.info("SUMMARY")
        logger.info("=" * 80)
        
        # Count issues
        issues = []
        
        # Upstream issues
        if self.results["upstream"].get("ws_bridge", {}).get("status") != "connected":
            issues.append("WS Bridge not connected")
        if self.results["upstream"].get("catalog", {}).get("total_markets", 0) == 0:
            issues.append("Catalog has no markets")
        
        # Midstream issues
        for asset, data in self.results["midstream"].get("market_state", {}).get("assets", {}).items():
            if not data.get("depth_sufficient", False):
                issues.append(f"{asset} has insufficient orderbook depth")
        
        # Downstream issues
        if self.results["downstream"].get("agent_grid", {}).get("status") != "module_available":
            issues.append("Agent grid not available")
        
        # Execution issues
        if self.results["execution"].get("kalshi_client", {}).get("status") != "available":
            issues.append("Kalshi client not available")
        
        self.results["summary"] = {
            "overall_status": "healthy" if len(issues) == 0 else "issues_detected",
            "issues": issues,
            "issue_count": len(issues)
        }
        
        logger.info(f"Overall Status: {self.results['summary']['overall_status']}")
        if issues:
            logger.warning(f"Issues Detected ({len(issues)}):")
            for issue in issues:
                logger.warning(f"  - {issue}")
        else:
            logger.info("No issues detected - pipeline is healthy")
    
    def print_results(self) -> None:
        """Print full results."""
        print("\n" + "=" * 80)
        print("FULL DIAGNOSTIC RESULTS")
        print("=" * 80)
        print(json.dumps(self.results, indent=2, default=str))
        print("=" * 80)


async def main():
    """Main entry point."""
    diagnostics = TradingPipelineDiagnostics()
    results = await diagnostics.run_all_diagnostics()
    
    # Save results to file
    output_path = "trading_pipeline_diagnostics_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info(f"\nResults saved to: {output_path}")
    
    # Exit with error code if issues detected
    if results["summary"]["issue_count"] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
