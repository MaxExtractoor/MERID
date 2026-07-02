#!/usr/bin/env python3
"""
Comprehensive E2E Trading Pipeline Reconciliation Script

This script traces through the entire trading execution pipeline to expose
all flaws, gaps, and missing data in the end-to-end plumbing.

Pipeline Stages:
1. Market Discovery (Catalog)
2. Candidate Generation (Optimizer)
3. Signal Generation (TA/Models)
4. Edge Calculation
5. Order Intent Creation
6. Order Placement
7. Fill Execution
8. Execution Reconciliation
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.market_catalog import get_market_catalog
from merid.event_venues.kalshi.kalshi_15m_time import get_kalshi_15m_window
from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
from data.unified_spot_service import get_unified_spot_service
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, ACTIVE_CRYPTO_FREQS


class PipelineReconciliation:
    """Comprehensive E2E pipeline reconciliation."""
    
    def __init__(self):
        self.catalog = None
        self.market_state_store = None
        self.spot_service = None
        self.results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stages": {},
            "gaps": [],
            "issues": [],
            "summary": {}
        }
    
    async def initialize(self):
        """Initialize all required services."""
        print("="*80)
        print("INITIALIZING SERVICES")
        print("="*80)
        
        # Initialize catalog
        try:
            self.catalog = get_market_catalog()
            await self.catalog.refresh()
            print("✅ Catalog initialized and refreshed")
        except Exception as e:
            print(f"❌ Catalog initialization failed: {e}")
            self.results["issues"].append(f"Catalog initialization: {e}")
        
        # Initialize market state store
        try:
            self.market_state_store = KalshiMarketStateStore()
            print("✅ Market state store initialized")
        except Exception as e:
            print(f"❌ Market state store initialization failed: {e}")
            self.results["issues"].append(f"Market state store initialization: {e}")
        
        # Initialize spot service
        try:
            self.spot_service = get_unified_spot_service()
            print("✅ Spot service initialized")
        except Exception as e:
            print(f"❌ Spot service initialization failed: {e}")
            self.results["issues"].append(f"Spot service initialization: {e}")
        
        print()
    
    async def check_market_discovery(self) -> Dict[str, Any]:
        """Stage 1: Market Discovery (Catalog)"""
        print("="*80)
        print("STAGE 1: MARKET DISCOVERY (CATALOG)")
        print("="*80)
        
        stage_result = {
            "stage": "market_discovery",
            "status": "unknown",
            "details": {},
            "gaps": []
        }
        
        try:
            # Get current 15m window
            window = get_kalshi_15m_window(datetime.now(timezone.utc))
            print(f"Current 15m window: {window.start_utc} to {window.end_utc}")
            print(f"Window suffix: {window.suffix}")
            stage_result["details"]["window"] = {
                "start_utc": window.start_utc.isoformat(),
                "end_utc": window.end_utc.isoformat(),
                "suffix": window.suffix
            }
            
            # Get all markets
            all_markets = self.catalog.get_all_markets()
            print(f"Total markets in catalog: {len(all_markets)}")
            stage_result["details"]["total_markets"] = len(all_markets)
            
            # Get 15m crypto markets
            crypto_15m_markets = self.catalog.get_markets_by_timeframe("15m")
            print(f"15m crypto markets: {len(crypto_15m_markets)}")
            stage_result["details"]["crypto_15m_markets"] = len(crypto_15m_markets)
            
            # Check each asset
            asset_coverage = {}
            for asset in ACTIVE_CRYPTO_ASSETS:
                asset_markets = self.catalog.get_markets_by_asset(asset, timeframe="15m")
                asset_coverage[asset] = len(asset_markets)
                print(f"  {asset}: {len(asset_markets)} markets")
                
                if len(asset_markets) == 0:
                    stage_result["gaps"].append(f"No 15m markets found for {asset}")
                    self.results["gaps"].append(f"Market discovery: No 15m markets for {asset}")
            
            stage_result["details"]["asset_coverage"] = asset_coverage
            
            # Check for active markets
            active_markets = self.catalog.get_active_markets(timeframe="15m", max_minutes_to_expiry=15.0)
            print(f"Active 15m markets (0-15 min to expiry): {len(active_markets)}")
            stage_result["details"]["active_markets"] = len(active_markets)
            
            if len(active_markets) == 0:
                stage_result["gaps"].append("No active 15m markets found")
                self.results["gaps"].append("Market discovery: No active 15m markets")
            
            # Check market data completeness
            for market in active_markets[:5]:  # Sample first 5
                market_id = getattr(market, 'market_id', None) or (getattr(market, 'market', None) and getattr(market.market, 'market_id', None))
                print(f"\n  Market: {market_id}")
                
                # Check required fields (CatalogMarket wraps EventMarket)
                required_fields = ['market', 'expires_at', 'asset', 'timeframe']
                missing_fields = []
                for field in required_fields:
                    if not hasattr(market, field):
                        missing_fields.append(field)
                        stage_result["gaps"].append(f"Market {market_id} missing field: {field}")
                
                # Check nested market object has market_id
                if hasattr(market, 'market') and hasattr(market.market, 'market_id'):
                    print(f"    ✅ All required fields present")
                else:
                    missing_fields.append('market.market_id')
                    stage_result["gaps"].append(f"Market {market_id} missing nested market.market_id")
                    print(f"    ❌ Missing fields: {missing_fields}")
            
            stage_result["status"] = "pass" if len(stage_result["gaps"]) == 0 else "partial"
            
        except Exception as e:
            print(f"❌ Market discovery check failed: {e}")
            stage_result["status"] = "fail"
            stage_result["error"] = str(e)
            self.results["issues"].append(f"Market discovery: {e}")
        
        self.results["stages"]["market_discovery"] = stage_result
        print()
        return stage_result
    
    async def check_market_data_availability(self) -> Dict[str, Any]:
        """Stage 1.5: Market Data Availability (Orderbook, Spot)"""
        print("="*80)
        print("STAGE 1.5: MARKET DATA AVAILABILITY")
        print("="*80)
        
        stage_result = {
            "stage": "market_data_availability",
            "status": "unknown",
            "details": {},
            "gaps": []
        }
        
        try:
            # Get active markets
            active_markets = self.catalog.get_active_markets(timeframe="15m", max_minutes_to_expiry=15.0)
            
            # Check market state for each
            md_status = {}
            for market in active_markets:
                market_id = getattr(market, 'market_id', None) or (getattr(market, 'market', None) and getattr(market.market, 'market_id', None))
                asset = getattr(market, 'asset', 'unknown')
                
                # Check market state (KalshiMarketStateStore uses get_all() to access states)
                all_states = self.market_state_store.get_all()
                state = all_states.get(market_id)
                if state is None:
                    md_status[market_id] = "NO_STATE"
                    stage_result["gaps"].append(f"No market state for {market_id}")
                    print(f"  {asset} ({market_id}): ❌ No market state")
                    continue
                
                # Check orderbook
                has_bid = state.best_bid > 0
                has_ask = state.best_ask > 0
                book_initialized = state.book_initialized
                
                status = "OK" if (has_bid and has_ask and book_initialized) else "INCOMPLETE"
                md_status[market_id] = status
                
                print(f"  {asset} ({market_id}): {status}")
                print(f"    Bid: {state.best_bid}, Ask: {state.best_ask}, Initialized: {book_initialized}")
                
                if not has_bid:
                    stage_result["gaps"].append(f"No bid for {market_id}")
                if not has_ask:
                    stage_result["gaps"].append(f"No ask for {market_id}")
                if not book_initialized:
                    stage_result["gaps"].append(f"Book not initialized for {market_id}")
            
            stage_result["details"]["market_state_status"] = md_status
            
            # Check spot prices (async call)
            spot_status = {}
            for asset in ACTIVE_CRYPTO_ASSETS:
                try:
                    spot_data = await self.spot_service.get_spot_price(asset)
                    if spot_data:
                        spot_status[asset] = "OK"
                        print(f"  {asset} spot: ✅ {spot_data.get('price', 'N/A')}")
                    else:
                        spot_status[asset] = "NO_DATA"
                        stage_result["gaps"].append(f"No spot data for {asset}")
                        print(f"  {asset} spot: ❌ No data")
                except Exception as e:
                    spot_status[asset] = f"ERROR: {e}"
                    stage_result["gaps"].append(f"Spot data error for {asset}: {e}")
                    print(f"  {asset} spot: ❌ {e}")
            
            stage_result["details"]["spot_status"] = spot_status
            
            stage_result["status"] = "pass" if len(stage_result["gaps"]) == 0 else "partial"
            
        except Exception as e:
            print(f"❌ Market data availability check failed: {e}")
            stage_result["status"] = "fail"
            stage_result["error"] = str(e)
            self.results["issues"].append(f"Market data availability: {e}")
        
        self.results["stages"]["market_data_availability"] = stage_result
        print()
        return stage_result
    
    async def check_candidate_generation(self) -> Dict[str, Any]:
        """Stage 2: Candidate Generation (Optimizer)"""
        print("="*80)
        print("STAGE 2: CANDIDATE GENERATION (OPTIMIZER)")
        print("="*80)
        
        stage_result = {
            "stage": "candidate_generation",
            "status": "unknown",
            "details": {},
            "gaps": []
        }
        
        try:
            # Check if optimizer is available
            try:
                from merid.prediction.candidate_optimizer import get_candidate_optimizer
                optimizer = get_candidate_optimizer()
                print("✅ Candidate optimizer available")
                stage_result["details"]["optimizer_available"] = True
            except Exception as e:
                print(f"❌ Candidate optimizer not available: {e}")
                stage_result["details"]["optimizer_available"] = False
                stage_result["gaps"].append(f"Candidate optimizer unavailable: {e}")
                self.results["gaps"].append("Candidate generation: Optimizer unavailable")
            
            # Check candidate generation for each asset
            candidate_status = {}
            for asset in ACTIVE_CRYPTO_ASSETS:
                markets = self.catalog.get_markets_by_asset(asset, timeframe="15m")
                if not markets:
                    candidate_status[asset] = "NO_MARKETS"
                    stage_result["gaps"].append(f"No markets to generate candidates for {asset}")
                    print(f"  {asset}: ❌ No markets")
                    continue
                
                # Try to generate candidates
                try:
                    # This would normally call the optimizer
                    # For now, just check if we have the required data
                    market = markets[0]
                    market_id = getattr(market, 'market_id', None) or (getattr(market, 'market', None) and getattr(market.market, 'market_id', None))
                    
                    # Check if we have market state (KalshiMarketStateStore uses get_all() to access states)
                    all_states = self.market_state_store.get_all()
                    state = all_states.get(market_id)
                    if state is None:
                        candidate_status[asset] = "NO_MD"
                        stage_result["gaps"].append(f"No market state for candidate generation: {asset}")
                        print(f"  {asset}: ❌ No market state")
                        continue
                    
                    # Check if we have spot data (async call)
                    spot_data = await self.spot_service.get_spot_price(asset)
                    if not spot_data:
                        candidate_status[asset] = "NO_SPOT"
                        stage_result["gaps"].append(f"No spot data for candidate generation: {asset}")
                        print(f"  {asset}: ❌ No spot data")
                        continue
                    
                    candidate_status[asset] = "READY"
                    print(f"  {asset}: ✅ Ready for candidate generation")
                    
                except Exception as e:
                    candidate_status[asset] = f"ERROR: {e}"
                    stage_result["gaps"].append(f"Candidate generation error for {asset}: {e}")
                    print(f"  {asset}: ❌ {e}")
            
            stage_result["details"]["candidate_status"] = candidate_status
            
            stage_result["status"] = "pass" if len(stage_result["gaps"]) == 0 else "partial"
            
        except Exception as e:
            print(f"❌ Candidate generation check failed: {e}")
            stage_result["status"] = "fail"
            stage_result["error"] = str(e)
            self.results["issues"].append(f"Candidate generation: {e}")
        
        self.results["stages"]["candidate_generation"] = stage_result
        print()
        return stage_result
    
    async def check_signal_generation(self) -> Dict[str, Any]:
        """Stage 3: Signal Generation (TA/Models)"""
        print("="*80)
        print("STAGE 3: SIGNAL GENERATION (TA/MODELS)")
        print("="*80)
        
        stage_result = {
            "stage": "signal_generation",
            "status": "unknown",
            "details": {},
            "gaps": []
        }
        
        try:
            # Check if signal generators are available
            signal_status = {}
            for asset in ACTIVE_CRYPTO_ASSETS:
                try:
                    # Check if agent exists
                    agent_module = f"merid.agents.{asset.lower()}_15m_agent"
                    __import__(agent_module)
                    signal_status[asset] = "AGENT_AVAILABLE"
                    print(f"  {asset}: ✅ Agent available")
                except ImportError:
                    signal_status[asset] = "NO_AGENT"
                    stage_result["gaps"].append(f"No agent for {asset}")
                    print(f"  {asset}: ❌ No agent")
                except Exception as e:
                    signal_status[asset] = f"ERROR: {e}"
                    stage_result["gaps"].append(f"Agent error for {asset}: {e}")
                    print(f"  {asset}: ❌ {e}")
            
            stage_result["details"]["signal_status"] = signal_status
            
            # Check TA indicators (correct module path)
            try:
                from merid.signals.crypto_15m_indicators import Crypto15mIndicatorStack
                print("✅ TA indicators available (Crypto15mIndicatorStack)")
                stage_result["details"]["ta_available"] = True
            except Exception as e:
                print(f"❌ TA indicators not available: {e}")
                stage_result["details"]["ta_available"] = False
                stage_result["gaps"].append(f"TA indicators unavailable: {e}")
            
            stage_result["status"] = "pass" if len(stage_result["gaps"]) == 0 else "partial"
            
        except Exception as e:
            print(f"❌ Signal generation check failed: {e}")
            stage_result["status"] = "fail"
            stage_result["error"] = str(e)
            self.results["issues"].append(f"Signal generation: {e}")
        
        self.results["stages"]["signal_generation"] = stage_result
        print()
        return stage_result
    
    async def check_edge_calculation(self) -> Dict[str, Any]:
        """Stage 4: Edge Calculation"""
        print("="*80)
        print("STAGE 4: EDGE CALCULATION")
        print("="*80)
        
        stage_result = {
            "stage": "edge_calculation",
            "status": "unknown",
            "details": {},
            "gaps": []
        }
        
        try:
            # Check if edge calculator is available (unified_edge module)
            try:
                from merid.prediction.unified_edge import UnifiedEdgeComputer
                print("✅ Edge calculator available (UnifiedEdgeComputer)")
                stage_result["details"]["edge_calculator_available"] = True
            except Exception as e:
                print(f"❌ Edge calculator not available: {e}")
                stage_result["details"]["edge_calculator_available"] = False
                stage_result["gaps"].append(f"Edge calculator unavailable: {e}")
            
            # Check edge requirements
            edge_status = {}
            for asset in ACTIVE_CRYPTO_ASSETS:
                markets = self.catalog.get_markets_by_asset(asset, timeframe="15m")
                if not markets:
                    edge_status[asset] = "NO_MARKETS"
                    continue
                
                market = markets[0]
                market_id = getattr(market, 'market_id', None) or (getattr(market, 'market', None) and getattr(market.market, 'market_id', None))
                
                # Check if we have orderbook for edge calculation (KalshiMarketStateStore uses get_all() to access states)
                all_states = self.market_state_store.get_all()
                state = all_states.get(market_id)
                if state and state.best_bid > 0 and state.best_ask > 0:
                    edge_status[asset] = "READY"
                    print(f"  {asset}: ✅ Ready for edge calculation")
                else:
                    edge_status[asset] = "NO_ORDERBOOK"
                    stage_result["gaps"].append(f"No orderbook for edge calculation: {asset}")
                    print(f"  {asset}: ❌ No orderbook")
            
            stage_result["details"]["edge_status"] = edge_status
            
            stage_result["status"] = "pass" if len(stage_result["gaps"]) == 0 else "partial"
            
        except Exception as e:
            print(f"❌ Edge calculation check failed: {e}")
            stage_result["status"] = "fail"
            stage_result["error"] = str(e)
            self.results["issues"].append(f"Edge calculation: {e}")
        
        self.results["stages"]["edge_calculation"] = stage_result
        print()
        return stage_result
    
    async def check_order_intent_creation(self) -> Dict[str, Any]:
        """Stage 5: Order Intent Creation"""
        print("="*80)
        print("STAGE 5: ORDER INTENT CREATION")
        print("="*80)
        
        stage_result = {
            "stage": "order_intent_creation",
            "status": "unknown",
            "details": {},
            "gaps": []
        }
        
        try:
            # Check if OrderIntent is available
            try:
                from merid.event_venues.kalshi.order_router import OrderIntent
                print("✅ OrderIntent available")
                stage_result["details"]["order_intent_available"] = True
            except Exception as e:
                print(f"❌ OrderIntent not available: {e}")
                stage_result["details"]["order_intent_available"] = False
                stage_result["gaps"].append(f"OrderIntent unavailable: {e}")
            
            # Check required order intent fields
            required_fields = [
                'action', 'count', 'price_cents', 'market_id', 
                'agent_id', 'source', 'group_id', 'edge_pct'
            ]
            stage_result["details"]["required_fields"] = required_fields
            print(f"  Required fields: {required_fields}")
            
            stage_result["status"] = "pass" if len(stage_result["gaps"]) == 0 else "partial"
            
        except Exception as e:
            print(f"❌ Order intent creation check failed: {e}")
            stage_result["status"] = "fail"
            stage_result["error"] = str(e)
            self.results["issues"].append(f"Order intent creation: {e}")
        
        self.results["stages"]["order_intent_creation"] = stage_result
        print()
        return stage_result
    
    async def check_order_placement(self) -> Dict[str, Any]:
        """Stage 6: Order Placement"""
        print("="*80)
        print("STAGE 6: ORDER PLACEMENT")
        print("="*80)
        
        stage_result = {
            "stage": "order_placement",
            "status": "unknown",
            "details": {},
            "gaps": []
        }
        
        try:
            # Check if order router is available
            try:
                from merid.event_venues.kalshi import order_router
                print("✅ Order router module available")
                stage_result["details"]["order_router_available"] = True
            except Exception as e:
                print(f"❌ Order router not available: {e}")
                stage_result["details"]["order_router_available"] = False
                stage_result["gaps"].append(f"Order router unavailable: {e}")
            
            # Check if venue client is available
            try:
                from merid.event_venues.kalshi.client import get_kalshi_client
                client = get_kalshi_client()
                print("✅ Kalshi client available")
                stage_result["details"]["kalshi_client_available"] = True
            except Exception as e:
                print(f"❌ Kalshi client not available: {e}")
                stage_result["details"]["kalshi_client_available"] = False
                stage_result["gaps"].append(f"Kalshi client unavailable: {e}")
            
            stage_result["status"] = "pass" if len(stage_result["gaps"]) == 0 else "partial"
            
        except Exception as e:
            print(f"❌ Order placement check failed: {e}")
            stage_result["status"] = "fail"
            stage_result["error"] = str(e)
            self.results["issues"].append(f"Order placement: {e}")
        
        self.results["stages"]["order_placement"] = stage_result
        print()
        return stage_result
    
    async def check_fill_execution(self) -> Dict[str, Any]:
        """Stage 7: Fill Execution"""
        print("="*80)
        print("STAGE 7: FILL EXECUTION")
        print("="*80)
        
        stage_result = {
            "stage": "fill_execution",
            "status": "unknown",
            "details": {},
            "gaps": []
        }
        
        try:
            # Check if fill tracking is available
            try:
                from merid.event_venues.kalshi.fills_ledger import KalshiFill
                print("✅ KalshiFill available")
                stage_result["details"]["venue_fill_available"] = True
            except Exception as e:
                print(f"❌ KalshiFill not available: {e}")
                stage_result["details"]["venue_fill_available"] = False
                stage_result["gaps"].append(f"KalshiFill unavailable: {e}")
            
            # Check if position tracking is available (uses fills_ledger)
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                ledger = get_fills_ledger()
                print("✅ Fills ledger available (position tracking)")
                stage_result["details"]["position_tracker_available"] = True
            except Exception as e:
                print(f"❌ Fills ledger not available: {e}")
                stage_result["details"]["position_tracker_available"] = False
                stage_result["gaps"].append(f"Fills ledger unavailable: {e}")
            
            stage_result["status"] = "pass" if len(stage_result["gaps"]) == 0 else "partial"
            
        except Exception as e:
            print(f"❌ Fill execution check failed: {e}")
            stage_result["status"] = "fail"
            stage_result["error"] = str(e)
            self.results["issues"].append(f"Fill execution: {e}")
        
        self.results["stages"]["fill_execution"] = stage_result
        print()
        return stage_result
    
    async def check_execution_reconciliation(self) -> Dict[str, Any]:
        """Stage 8: Execution Reconciliation"""
        print("="*80)
        print("STAGE 8: EXECUTION RECONCILIATION")
        print("="*80)
        
        stage_result = {
            "stage": "execution_reconciliation",
            "status": "unknown",
            "details": {},
            "gaps": []
        }
        
        try:
            # Check if reconciliation is available (PortfolioReconciler, not PortfolioReconciliation)
            try:
                from merid.event_venues.kalshi.portfolio_reconciliation import PortfolioReconciler
                print("✅ Portfolio reconciliation available (PortfolioReconciler)")
                stage_result["details"]["reconciliation_available"] = True
            except Exception as e:
                print(f"❌ Portfolio reconciliation not available: {e}")
                stage_result["details"]["reconciliation_available"] = False
                stage_result["gaps"].append(f"Portfolio reconciliation unavailable: {e}")
            
            # Check if trade logging is available (fills_ledger)
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                ledger = get_fills_ledger()
                print("✅ Fills ledger available (trade logging)")
                stage_result["details"]["trade_logger_available"] = True
            except Exception as e:
                print(f"❌ Fills ledger not available: {e}")
                stage_result["details"]["trade_logger_available"] = False
                stage_result["gaps"].append(f"Fills ledger unavailable: {e}")
            
            stage_result["status"] = "pass" if len(stage_result["gaps"]) == 0 else "partial"
            
        except Exception as e:
            print(f"❌ Execution reconciliation check failed: {e}")
            stage_result["status"] = "fail"
            stage_result["error"] = str(e)
            self.results["issues"].append(f"Execution reconciliation: {e}")
        
        self.results["stages"]["execution_reconciliation"] = stage_result
        print()
        return stage_result
    
    def print_summary(self):
        """Print comprehensive summary."""
        print("="*80)
        print("RECONCILIATION SUMMARY")
        print("="*80)
        
        total_stages = len(self.results["stages"])
        passed_stages = sum(1 for s in self.results["stages"].values() if s["status"] == "pass")
        partial_stages = sum(1 for s in self.results["stages"].values() if s["status"] == "partial")
        failed_stages = sum(1 for s in self.results["stages"].values() if s["status"] == "fail")
        
        print(f"Total stages: {total_stages}")
        print(f"Passed: {passed_stages}")
        print(f"Partial: {partial_stages}")
        print(f"Failed: {failed_stages}")
        print()
        
        print(f"Total gaps found: {len(self.results['gaps'])}")
        print(f"Total issues found: {len(self.results['issues'])}")
        print()
        
        if self.results["gaps"]:
            print("GAPS:")
            for gap in self.results["gaps"]:
                print(f"  - {gap}")
            print()
        
        if self.results["issues"]:
            print("ISSUES:")
            for issue in self.results["issues"]:
                print(f"  - {issue}")
            print()
        
        # Save results to file
        output_file = Path(__file__).parent.parent / "web" / "pipeline_reconciliation.json"
        with open(output_file, "w") as f:
            json.dump(self.results, f, indent=2, default=str)
        print(f"Results saved to: {output_file}")


async def main():
    """Run comprehensive E2E pipeline reconciliation."""
    recon = PipelineReconciliation()
    
    # Initialize services
    await recon.initialize()
    
    # Run all stage checks
    await recon.check_market_discovery()
    await recon.check_market_data_availability()
    await recon.check_candidate_generation()
    await recon.check_signal_generation()
    await recon.check_edge_calculation()
    await recon.check_order_intent_creation()
    await recon.check_order_placement()
    await recon.check_fill_execution()
    await recon.check_execution_reconciliation()
    
    # Print summary
    recon.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
