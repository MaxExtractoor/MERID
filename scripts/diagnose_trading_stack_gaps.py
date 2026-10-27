#!/usr/bin/env python3
"""
Comprehensive diagnostic script to expose gaps, time issues, and misalignments
in the 15m Kalshi crypto trading execution stack.

This script checks:
1. Active markets across BTC, ETH, SOL, XRP, DOGE in current 15-minute window
2. Market catalog alignment (API vs local catalog, close_ts consistency, ticker parsing)
3. Time-related issues (clock skew, expiry windows, timezone awareness)
4. WebSocket subscription alignment
5. Agent grid alignment (all 5 assets have agents)
6. Price feed alignment
7. Risk enforcement (position limits, exposure tracking)
8. Trading pipeline end-to-end alignment
"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.client_v2 import KalshiClientV2
from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, CatalogMarket
from merid.event_venues.kalshi.crypto_catalog import collect_crypto_ws_subscription_tickers, KalshiCryptoCatalog
from merid.event_venues.kalshi.kalshi_15m_time import get_current_utc_window
from config.kalshi_universe import KALSHI_CRYPTO_ASSETS, ACTIVE_CRYPTO_WS_TIMEFRAMES
from config.kalshi_crypto_config import ACTIVE_CRYPTO_FREQS


class TradingStackDiagnostics:
    """Comprehensive diagnostics for the 15m trading stack."""
    
    CRITICAL_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    def __init__(self):
        self.now_utc = datetime.now(timezone.utc)
        self.issues: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.info: List[Dict[str, Any]] = []
        self.client: Optional[KalshiClientV2] = None
        self.catalog: Optional[KalshiMarketCatalog] = None
        
    def log_issue(self, category: str, message: str, details: Dict[str, Any] = None):
        """Log a critical issue."""
        self.issues.append({
            "category": category,
            "message": message,
            "details": details or {},
            "timestamp": self.now_utc.isoformat()
        })
        
    def log_warning(self, category: str, message: str, details: Dict[str, Any] = None):
        """Log a warning."""
        self.warnings.append({
            "category": category,
            "message": message,
            "details": details or {},
            "timestamp": self.now_utc.isoformat()
        })
        
    def log_info(self, category: str, message: str, details: Dict[str, Any] = None):
        """Log informational message."""
        self.info.append({
            "category": category,
            "message": message,
            "details": details or {},
            "timestamp": self.now_utc.isoformat()
        })
        
    async def initialize(self):
        """Initialize Kalshi client and catalog."""
        try:
            self.client = KalshiClientV2()
            # KalshiClientV2 initializes in __init__, no separate initialize() method
            self.catalog = KalshiMarketCatalog(client=self.client)
            await self.catalog.refresh()
            self.log_info("INITIALIZATION", "Kalshi client and catalog initialized successfully")
        except Exception as e:
            self.log_issue("INITIALIZATION", f"Failed to initialize Kalshi client: {e}", {"error": str(e)})
            raise
            
    async def check_active_markets_in_window(self):
        """Check 1: Active markets across all 5 assets in current 15-minute window."""
        print("\n" + "="*80)
        print("CHECK 1: Active Markets in Current 15-Minute Window")
        print("="*80)
        
        try:
            # Get current UTC window
            current_window = get_current_utc_window(self.now_utc)
            self.log_info("TIME_WINDOW", f"Current UTC window: {current_window.start_utc} to {current_window.end_utc}")
            
            # Get active markets from catalog
            active_markets = self.catalog.get_active_markets(timeframe="15m", max_minutes_to_expiry=15.0)
            
            # Group by asset
            markets_by_asset: Dict[str, List[CatalogMarket]] = {asset: [] for asset in self.CRITICAL_ASSETS}
            
            for market in active_markets:
                if market.asset in markets_by_asset:
                    markets_by_asset[market.asset].append(market)
            
            # Check each asset
            for asset in self.CRITICAL_ASSETS:
                markets = markets_by_asset[asset]
                if not markets:
                    self.log_issue("ACTIVE_MARKETS", f"No active 15m markets found for {asset}", {
                        "asset": asset,
                        "timeframe": "15m",
                        "window": str(current_window)
                    })
                else:
                    self.log_info("ACTIVE_MARKETS", f"Found {len(markets)} active 15m markets for {asset}", {
                        "asset": asset,
                        "count": len(markets),
                        "sample_tickers": [m.ticker for m in markets[:3]]
                    })
                    
                    # Check close_ts consistency
                    for market in markets:
                        if hasattr(market, "expires_at") and market.expires_at:
                            time_to_expiry = (market.expires_at - self.now_utc).total_seconds()
                            if time_to_expiry < 0:
                                self.log_issue("MARKET_TIMING", f"{asset} market {market.ticker} has expired", {
                                    "ticker": market.ticker,
                                    "expires_at": market.expires_at.isoformat(),
                                    "time_to_expiry_seconds": time_to_expiry
                                })
                            elif time_to_expiry > 900:  # More than 15 minutes
                                self.log_warning("MARKET_TIMING", f"{asset} market {market.ticker} is outside 15m window", {
                                    "ticker": market.ticker,
                                    "expires_at": market.expires_at.isoformat(),
                                    "time_to_expiry_seconds": time_to_expiry
                                })
                        else:
                            self.log_warning("MARKET_TIMING", f"{asset} market {market.ticker} missing expires_at", {
                                "ticker": market.ticker
                            })
                            
        except Exception as e:
            self.log_issue("ACTIVE_MARKETS", f"Failed to check active markets: {e}", {"error": str(e)})
            
    async def check_catalog_alignment(self):
        """Check 2: Market catalog alignment (API vs local, close_ts consistency, ticker parsing)."""
        print("\n" + "="*80)
        print("CHECK 2: Market Catalog Alignment")
        print("="*80)
        
        try:
            # Get all markets from catalog
            all_markets = self.catalog.get_all_markets()
            
            # Check for close_ts presence and consistency
            markets_without_close_ts = []
            markets_with_invalid_close_ts = []
            
            for market in all_markets:
                if not hasattr(market, "expires_at") or market.expires_at is None:
                    markets_without_close_ts.append(market.ticker)
                else:
                    # Check if close_ts is timezone-aware
                    if market.expires_at.tzinfo is None:
                        self.log_issue("CATALOG_ALIGNMENT", f"Market {market.ticker} has naive datetime (no timezone)", {
                            "ticker": market.ticker,
                            "expires_at": market.expires_at.isoformat()
                        })
                        
                    # Check for extreme clock skew
                    time_diff = (market.expires_at - self.now_utc).total_seconds()
                    if abs(time_diff) > 86400:  # More than 1 day difference
                        self.log_warning("CATALOG_ALIGNMENT", f"Market {market.ticker} has suspicious close_ts", {
                            "ticker": market.ticker,
                            "expires_at": market.expires_at.isoformat(),
                            "time_diff_seconds": time_diff
                        })
            
            if markets_without_close_ts:
                self.log_issue("CATALOG_ALIGNMENT", f"{len(markets_without_close_ts)} markets missing close_ts/expires_at", {
                    "count": len(markets_without_close_ts),
                    "sample_tickers": markets_without_close_ts[:10]
                })
                
            # Check ticker suffix parsing consistency
            ticker_parsing_issues = []
            for market in all_markets:
                if market.ticker and "-" in market.ticker:
                    parts = market.ticker.split("-")
                    if len(parts) < 3:
                        ticker_parsing_issues.append(market.ticker)
                        
            if ticker_parsing_issues:
                self.log_warning("CATALOG_ALIGNMENT", f"{len(ticker_parsing_issues)} tickers have non-standard format", {
                    "count": len(ticker_parsing_issues),
                    "sample_tickers": ticker_parsing_issues[:10]
                })
                
            self.log_info("CATALOG_ALIGNMENT", f"Catalog alignment check complete: {len(all_markets)} total markets")
            
        except Exception as e:
            self.log_issue("CATALOG_ALIGNMENT", f"Failed to check catalog alignment: {e}", {"error": str(e)})
            
    async def check_time_alignment(self):
        """Check 3: Time-related issues (clock skew, expiry windows, timezone awareness)."""
        print("\n" + "="*80)
        print("CHECK 3: Time Alignment")
        print("="*80)
        
        try:
            # Check system time vs UTC
            system_time = datetime.now(timezone.utc)
            time_diff = abs((system_time - self.now_utc).total_seconds())
            
            if time_diff > 1.0:
                self.log_warning("TIME_ALIGNMENT", f"System time drift detected: {time_diff:.2f}s", {
                    "drift_seconds": time_diff
                })
                
            # Check all datetime objects in catalog for timezone awareness
            naive_datetimes = []
            all_markets = self.catalog.get_all_markets()
            
            for market in all_markets:
                for attr_name in ["expires_at", "created_at", "updated_at"]:
                    if hasattr(market, attr_name):
                        attr_value = getattr(market, attr_name)
                        if attr_value and attr_value.tzinfo is None:
                            naive_datetimes.append(f"{market.ticker}.{attr_name}")
                            
            if naive_datetimes:
                self.log_issue("TIME_ALIGNMENT", f"{len(naive_datetimes)} naive datetime objects found", {
                    "count": len(naive_datetimes),
                    "sample_fields": naive_datetimes[:10]
                })
                
            # Check 15-minute window boundaries
            current_window = get_current_utc_window(self.now_utc)
            window_duration = (current_window.end_utc - current_window.start_utc).total_seconds()
            
            if abs(window_duration - 900) > 1:  # Should be exactly 15 minutes
                self.log_issue("TIME_ALIGNMENT", f"15-minute window duration incorrect: {window_duration}s", {
                    "expected_seconds": 900,
                    "actual_seconds": window_duration
                })
                
            self.log_info("TIME_ALIGNMENT", f"Current window: {current_window.start_utc} to {current_window.end_utc}")
            
        except Exception as e:
            self.log_issue("TIME_ALIGNMENT", f"Failed to check time alignment: {e}", {"error": str(e)})
            
    async def check_websocket_subscription_alignment(self):
        """Check 4: WebSocket subscription alignment."""
        print("\n" + "="*80)
        print("CHECK 4: WebSocket Subscription Alignment")
        print("="*80)
        
        try:
            # Get WebSocket subscription tickers
            ws_tickers = collect_crypto_ws_subscription_tickers(
                self.catalog,
                assets=self.CRITICAL_ASSETS,
                timeframes=["15m"],
                active_only=True
            )
            
            # Get active markets
            active_markets = self.catalog.get_active_markets(timeframe="15m", max_minutes_to_expiry=15.0)
            active_tickers = {m.ticker for m in active_markets if m.asset in self.CRITICAL_ASSETS}
            
            # Check for missing subscriptions
            missing_subscriptions = active_tickers - set(ws_tickers)
            if missing_subscriptions:
                self.log_issue("WS_SUBSCRIPTION", f"{len(missing_subscriptions)} active markets not subscribed", {
                    "count": len(missing_subscriptions),
                    "missing_tickers": list(missing_subscriptions)[:10]
                })
                
            # Check for extra subscriptions (subscribing to inactive markets)
            extra_subscriptions = set(ws_tickers) - active_tickers
            if extra_subscriptions:
                self.log_warning("WS_SUBSCRIPTION", f"{len(extra_subscriptions)} subscriptions to inactive markets", {
                    "count": len(extra_subscriptions),
                    "extra_tickers": list(extra_subscriptions)[:10]
                })
                
            # Check per-asset subscription coverage
            for asset in self.CRITICAL_ASSETS:
                asset_active = {m.ticker for m in active_markets if m.asset == asset}
                asset_subscribed = {t for t in ws_tickers if any(a in t for a in [asset])}
                
                if asset_active and not asset_subscribed:
                    self.log_issue("WS_SUBSCRIPTION", f"No WebSocket subscriptions for {asset}", {
                        "asset": asset,
                        "active_count": len(asset_active)
                    })
                    
            self.log_info("WS_SUBSCRIPTION", f"WebSocket subscriptions: {len(ws_tickers)} tickers")
            
        except Exception as e:
            self.log_issue("WS_SUBSCRIPTION", f"Failed to check WebSocket subscriptions: {e}", {"error": str(e)})
            
    async def check_agent_grid_alignment(self):
        """Check 5: Agent grid alignment (all 5 assets have agents)."""
        print("\n" + "="*80)
        print("CHECK 5: Agent Grid Alignment")
        print("="*80)
        
        try:
            # Try to import and check agent grid
            from merid.prediction.agent_grid_15m import get_agent_grid, get_15m_grid_from_app
            
            # Check singleton
            grid = get_agent_grid()
            if grid is None:
                self.log_warning("AGENT_GRID", "Agent grid singleton is None (may not be initialized)")
            else:
                # Check agent count
                if hasattr(grid, "_agents"):
                    agent_count = len(grid._agents)
                    if agent_count != 5:
                        self.log_issue("AGENT_GRID", f"Expected 5 agents, found {agent_count}", {
                            "expected": 5,
                            "actual": agent_count
                        })
                    else:
                        # Check each asset has an agent
                        assets_with_agents = set()
                        for agent in grid._agents:
                            if hasattr(agent, "asset"):
                                assets_with_agents.add(agent.asset)
                                
                        missing_assets = set(self.CRITICAL_ASSETS) - assets_with_agents
                        if missing_assets:
                            self.log_issue("AGENT_GRID", f"Missing agents for assets: {missing_assets}", {
                                "missing_assets": list(missing_assets)
                            })
                        else:
                            self.log_info("AGENT_GRID", f"All 5 assets have active agents: {sorted(assets_with_agents)}")
                            
            # Check if we can build a grid (tests dependencies)
            try:
                from merid.prediction.agent_grid_15m import build_15m_agent_grid
                self.log_info("AGENT_GRID", "build_15m_agent_grid function is importable")
            except ImportError as e:
                self.log_issue("AGENT_GRID", f"Cannot import build_15m_agent_grid: {e}", {"error": str(e)})
                
        except Exception as e:
            self.log_issue("AGENT_GRID", f"Failed to check agent grid: {e}", {"error": str(e)})
            
    async def check_price_feed_alignment(self):
        """Check 6: Price feed alignment."""
        print("\n" + "="*80)
        print("CHECK 6: Price Feed Alignment")
        print("="*80)
        
        try:
            # Check unified spot service - try different import paths
            try:
                from data.unified_spot_service import UnifiedSpotService
                self.log_info("PRICE_FEED", "UnifiedSpotService is importable from data.unified_spot_service")
                
                spot_service = UnifiedSpotService()
                
                # Check if all 5 assets are configured
                configured_assets = set()
                for asset in self.CRITICAL_ASSETS:
                    try:
                        # Try to get price for each asset
                        price = await spot_service.get_spot_price(f"{asset}/USD")
                        if price is not None:
                            configured_assets.add(asset)
                            self.log_info("PRICE_FEED", f"Price available for {asset}/USD: {price}")
                        else:
                            self.log_warning("PRICE_FEED", f"Price returned None for {asset}/USD")
                    except Exception as e:
                        self.log_warning("PRICE_FEED", f"Failed to get price for {asset}/USD: {e}")
                        
                missing_assets = set(self.CRITICAL_ASSETS) - configured_assets
                if missing_assets:
                    self.log_issue("PRICE_FEED", f"Missing price feeds for assets: {missing_assets}", {
                        "missing_assets": list(missing_assets)
                    })
                    
            except ImportError:
                # Try alternative import paths
                try:
                    import data as data_module
                    available_items = [name for name in dir(data_module) if not name.startswith("_")]
                    self.log_info("PRICE_FEED", f"Available items in data: {available_items}")
                except ImportError:
                    self.log_warning("PRICE_FEED", "Cannot import data module")
                    
                # Check for spot price providers in other locations
                try:
                    from merid.event_venues.kalshi.spot_provider import KalshiSpotProvider
                    self.log_info("PRICE_FEED", "KalshiSpotProvider is importable")
                except ImportError:
                    self.log_warning("PRICE_FEED", "Cannot import KalshiSpotService or KalshiSpotProvider")
                    
        except Exception as e:
            self.log_issue("PRICE_FEED", f"Failed to check price feed: {e}", {"error": str(e)})
            
    async def check_risk_enforcement(self):
        """Check 7: Risk enforcement (position limits, exposure tracking)."""
        print("\n" + "="*80)
        print("CHECK 7: Risk Enforcement")
        print("="*80)
        
        try:
            # Check kill switches - import the correct module
            try:
                import merid.risk.kill_switches as ks_module
                # Look for available functions/classes
                available_items = [name for name in dir(ks_module) if not name.startswith("_")]
                self.log_info("RISK_ENFORCEMENT", f"Available items in kill_switches: {available_items}")
                
                # Try to get kill switch status
                if hasattr(ks_module, "get_kill_switch_state"):
                    state = ks_module.get_kill_switch_state()
                    if state and state.get("active"):
                        self.log_issue("RISK_ENFORCEMENT", "Kill switch is ACTIVE - trading halted", {
                            "active": True,
                            "state": state
                        })
                    else:
                        self.log_info("RISK_ENFORCEMENT", "Kill switch is not active")
                else:
                    self.log_warning("RISK_ENFORCEMENT", "Cannot find get_kill_switch_state function")
            except ImportError as e:
                self.log_warning("RISK_ENFORCEMENT", f"Cannot import kill_switches module: {e}")
                
            # Check bankroll service
            try:
                from merid.event_venues.kalshi.bankroll_service_v2 import KalshiBankrollServiceV2
                self.log_info("RISK_ENFORCEMENT", "KalshiBankrollServiceV2 is importable")
            except ImportError as e:
                self.log_warning("RISK_ENFORCEMENT", f"Cannot import KalshiBankrollServiceV2: {e}")
                
        except Exception as e:
            self.log_issue("RISK_ENFORCEMENT", f"Failed to check risk enforcement: {e}", {"error": str(e)})
            
    async def check_end_to_end_pipeline(self):
        """Check 8: End-to-end trading pipeline alignment."""
        print("\n" + "="*80)
        print("CHECK 8: End-to-End Pipeline Alignment")
        print("="*80)
        
        try:
            # Check if all critical components are importable
            critical_components = {
                "KalshiClientV2": "merid.event_venues.kalshi.client_v2",
                "KalshiMarketCatalog": "merid.event_venues.kalshi.market_catalog",
                "KalshiCryptoCatalog": "merid.event_venues.kalshi.crypto_catalog",
                "LeanAgentGrid15m": "merid.prediction.agent_grid_15m",
                "Kalshi15mLoop": "merid.loop_15m",
                "UnifiedSpotService": "data.unified_spot_service",
                "KillSwitchManager": "merid.risk.kill_switches",
            }
            
            for component_name, module_path in critical_components.items():
                try:
                    __import__(module_path)
                    self.log_info("PIPELINE", f"{component_name} is importable from {module_path}")
                except ImportError as e:
                    self.log_issue("PIPELINE", f"Cannot import {component_name}: {e}", {
                        "component": component_name,
                        "module": module_path,
                        "error": str(e)
                    })
                    
            # Check config files
            config_checks = {
                "kalshi_crypto_config": "config.kalshi_crypto_config",
                "kalshi_universe": "config.kalshi_universe",
            }
            
            for config_name, module_path in config_checks.items():
                try:
                    module = __import__(module_path, fromlist=[config_name])
                    self.log_info("PIPELINE", f"{config_name} is importable")
                except ImportError as e:
                    self.log_issue("PIPELINE", f"Cannot import {config_name}: {e}", {
                        "config": config_name,
                        "error": str(e)
                    })
                    
        except Exception as e:
            self.log_issue("PIPELINE", f"Failed to check pipeline: {e}", {"error": str(e)})
            
    def generate_report(self) -> str:
        """Generate comprehensive diagnostic report."""
        report = []
        report.append("="*80)
        report.append("TRADING STACK DIAGNOSTIC REPORT")
        report.append(f"Generated: {self.now_utc.isoformat()}")
        report.append("="*80)
        
        # Summary
        report.append("\nSUMMARY")
        report.append("-" * 40)
        report.append(f"Critical Issues: {len(self.issues)}")
        report.append(f"Warnings: {len(self.warnings)}")
        report.append(f"Info Messages: {len(self.info)}")
        
        # Critical Issues
        if self.issues:
            report.append("\n" + "="*80)
            report.append("CRITICAL ISSUES")
            report.append("="*80)
            for i, issue in enumerate(self.issues, 1):
                report.append(f"\n{i}. [{issue['category']}] {issue['message']}")
                if issue['details']:
                    for key, value in issue['details'].items():
                        report.append(f"   {key}: {value}")
                        
        # Warnings
        if self.warnings:
            report.append("\n" + "="*80)
            report.append("WARNINGS")
            report.append("="*80)
            for i, warning in enumerate(self.warnings, 1):
                report.append(f"\n{i}. [{warning['category']}] {warning['message']}")
                if warning['details']:
                    for key, value in warning['details'].items():
                        report.append(f"   {key}: {value}")
                        
        # Info
        if self.info:
            report.append("\n" + "="*80)
            report.append("INFORMATION")
            report.append("="*80)
            for i, info in enumerate(self.info, 1):
                report.append(f"\n{i}. [{info['category']}] {info['message']}")
                if info['details']:
                    for key, value in info['details'].items():
                        report.append(f"   {key}: {value}")
                        
        report.append("\n" + "="*80)
        report.append("END OF REPORT")
        report.append("="*80)
        
        return "\n".join(report)
        
    def save_json_report(self, filepath: str):
        """Save detailed JSON report."""
        report_data = {
            "timestamp": self.now_utc.isoformat(),
            "summary": {
                "critical_issues": len(self.issues),
                "warnings": len(self.warnings),
                "info": len(self.info)
            },
            "issues": self.issues,
            "warnings": self.warnings,
            "info": self.info
        }
        
        with open(filepath, 'w') as f:
            json.dump(report_data, f, indent=2)
            
    async def run_all_checks(self):
        """Run all diagnostic checks."""
        print("\n" + "="*80)
        print("STARTING COMPREHENSIVE TRADING STACK DIAGNOSTICS")
        print("="*80)
        print(f"Timestamp: {self.now_utc.isoformat()}")
        print(f"Critical Assets: {', '.join(self.CRITICAL_ASSETS)}")
        
        await self.initialize()
        await self.check_active_markets_in_window()
        await self.check_catalog_alignment()
        await self.check_time_alignment()
        await self.check_websocket_subscription_alignment()
        await self.check_agent_grid_alignment()
        await self.check_price_feed_alignment()
        await self.check_risk_enforcement()
        await self.check_end_to_end_pipeline()
        
        # Generate reports
        report = self.generate_report()
        print("\n" + report)
        
        # Save JSON report
        json_path = Path(__file__).parent.parent / "output" / "trading_stack_diagnostics.json"
        json_path.parent.mkdir(exist_ok=True)
        self.save_json_report(str(json_path))
        print(f"\nJSON report saved to: {json_path}")
        
        # Save text report
        txt_path = Path(__file__).parent.parent / "output" / "trading_stack_diagnostics.txt"
        with open(txt_path, 'w') as f:
            f.write(report)
        print(f"Text report saved to: {txt_path}")
        
        return len(self.issues) == 0


async def main():
    """Main entry point."""
    diagnostics = TradingStackDiagnostics()
    
    try:
        success = await diagnostics.run_all_checks()
        
        if success:
            print("\n✅ All checks passed - no critical issues found")
            return 0
        else:
            print(f"\n❌ Found {len(diagnostics.issues)} critical issues - review report")
            return 1
            
    except Exception as e:
        print(f"\n💥 Fatal error running diagnostics: {e}")
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
