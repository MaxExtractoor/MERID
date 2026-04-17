"""
Enhanced Prediction Markets with Synthetic Data Generation

Creates realistic drift and arbitrage signals for testing and demonstration.
Generates synthetic price movements and cross-platform discrepancies.
"""

import asyncio
import threading
import time
import random
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import uuid
from collections import deque

from monitoring.real_prediction_markets import (
    RealPredictionMarketAggregator, 
    PredictionMarket, 
    OddsDriftSignal, 
    CrossPlatformArbitrage,
    PredictionPlatform,
    MarketCategory
)
from utils.logger import get_logger

logger = get_logger("monitoring.enhanced_prediction_markets")


@dataclass
class SyntheticMarketConfig:
    """Configuration for synthetic market generation."""
    
    # Drift generation
    drift_probability: float = 0.15  # 15% chance of drift per update
    drift_min_change: float = 0.02   # 2% minimum drift
    drift_max_change: float = 0.10   # 10% maximum drift
    
    # Arbitrage generation
    arbitrage_probability: float = 0.10  # 10% chance of arbitrage
    arbitrage_min_spread: float = 0.01     # 1% minimum spread
    arbitrage_max_spread: float = 0.05     # 5% maximum spread
    
    # Market categories to simulate
    active_categories: List[MarketCategory] = field(default_factory=lambda: [
        MarketCategory.CRYPTO,
        MarketCategory.POLITICS,
        MarketCategory.SPORTS,
        MarketCategory.ECONOMICS
    ])


class EnhancedPredictionMarketAggregator(RealPredictionMarketAggregator):
    """
    Enhanced aggregator with synthetic data generation for testing.
    
    Extends the real aggregator with:
    - Synthetic drift signal generation
    - Synthetic arbitrage opportunity generation
    - Realistic price movements
    - Cross-platform price discrepancies
    """
    
    def __init__(self, config: Optional[SyntheticMarketConfig] = None):
        super().__init__()
        self.config = config or SyntheticMarketConfig()
        
        # Synthetic data generation
        self._synthetic_markets: Dict[str, PredictionMarket] = {}
        self._price_generators: Dict[str, float] = {}  # Base prices for synthetic markets
        self._last_synthetic_update = 0.0
        
        # Initialize synthetic markets
        self._initialize_synthetic_markets()
        
        logger.info("EnhancedPredictionMarketAggregator initialized with synthetic data generation")
    
    def _initialize_synthetic_markets(self):
        """Initialize synthetic markets for testing - DISABLED for real data only."""
        logger.info("Synthetic markets disabled - using real data only")
        self._synthetic_markets = {}
        self._price_generators = {}
    
    async def _update_loop(self) -> None:
        """Enhanced update loop with synthetic data generation."""
        while self._running:
            try:
                # Fetch real markets
                await self._fetch_all_markets()
                
                # Update synthetic markets
                self._update_synthetic_markets()
                
                # Merge synthetic and real markets
                self._merge_markets()
                
                # Detect drift and arbitrage
                self._detect_odds_drift()
                self._find_arbitrage_opportunities()
                
                # Generate synthetic signals if none exist
                self._generate_synthetic_signals()
                
                await asyncio.sleep(15)  # Update every 15 seconds for faster testing
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Enhanced update loop error: {e}")
                await asyncio.sleep(5)
    
    def _update_synthetic_markets(self):
        """Update synthetic market prices - DISABLED for real data only."""
        # Disabled - no synthetic markets
        pass
    
    def _merge_markets(self):
        """Merge synthetic and real markets - REAL DATA ONLY."""
        # Use only real markets
        self._markets = dict(self._all_markets)
        
        logger.info(f"Merged {len(self._all_markets)} real markets")
    
    def _generate_synthetic_signals(self):
        """Generate synthetic drift and arbitrage signals - DISABLED for real data only."""
        # Disabled - no synthetic signals
        pass
    
    def _generate_synthetic_drift(self):
        """Generate synthetic drift signals."""
        # Select a random market
        markets = list(self._all_markets.values())
        if not markets:
            return
        
        market = random.choice(markets)
        
        # Generate realistic drift
        old_price = market.yes_price
        drift_pct = random.uniform(
            self.config.drift_min_change * 100,
            self.config.drift_max_change * 100
        )
        
        if random.random() < 0.5:
            drift_pct = -drift_pct  # Random direction
        
        new_price = old_price * (1 + drift_pct / 100)
        new_price = max(0.05, min(0.95, new_price))
        
        # Create drift signal
        signal = OddsDriftSignal(
            signal_id=f"synthetic_drift_{uuid.uuid4().hex[:8]}",
            market_id=market.market_id,
            platform=market.platform,
            question=market.question,
            old_probability=old_price,
            new_probability=new_price,
            drift_pct=drift_pct,
            drift_direction="up" if drift_pct > 0 else "down",
            time_window_seconds=1800,  # 30 minutes
            volume_in_window=market.volume_24h / 48,
        )
        
        self._drift_signals.append(signal)
        logger.info(f"Generated synthetic drift: {market.question[:50]}... {drift_pct:+.1f}%")
    
    def _generate_synthetic_arbitrage(self):
        """Generate synthetic arbitrage opportunities."""
        # Group markets by question (simplified)
        question_groups = {}
        
        for market in self._all_markets.values():
            # Group by first 50 characters of question (simplified matching)
            key = market.question[:50].lower()
            if key not in question_groups:
                question_groups[key] = []
            question_groups[key].append(market)
        
        # Find groups with multiple platforms
        for key, markets in question_groups.items():
            if len(markets) < 2:
                continue
            
            # Create synthetic arbitrage
            platform_a_markets = [m for m in markets if m.platform == PredictionPlatform.POLYMARKET]
            platform_b_markets = [m for m in markets if m.platform == PredictionPlatform.AUGUR]
            
            if platform_a_markets and platform_b_markets:
                market_a = platform_a_markets[0]
                market_b = platform_b_markets[0]
                
                # Generate spread
                spread = random.uniform(
                    self.config.arbitrage_min_spread,
                    self.config.arbitrage_max_spread
                )
                
                # Adjust prices to create spread
                price_a = market_a.yes_price
                price_b = price_a + spread
                
                if price_b > 0.95:
                    price_b = price_a - spread
                
                market_b.yes_price = price_b
                market_b.no_price = 1.0 - price_b
                
                # Create arbitrage opportunity
                arb = CrossPlatformArbitrage(
                    arb_id=f"synthetic_arb_{uuid.uuid4().hex[:8]}",
                    question=market_a.question,
                    category=market_a.category,
                    platform_a=market_a.platform,
                    platform_b=market_b.platform,
                    prob_a=price_a,
                    prob_b=price_b,
                    spread=abs(price_a - price_b),
                    spread_pct=abs(price_a - price_b) * 100,
                    potential_edge=abs(price_a - price_b) * 0.8,
                    liquidity_constraint=min(market_a.liquidity, market_b.liquidity),
                )
                
                self._arbitrage_opps.append(arb)
                logger.info(f"Generated synthetic arbitrage: {abs(price_a - price_b) * 100:.1f}% spread")


# Enhanced global instance
_enhanced_aggregator = None
_enhanced_aggregator_lock = threading.Lock()

async def get_enhanced_prediction_aggregator() -> EnhancedPredictionMarketAggregator:
    """Get the enhanced prediction aggregator instance."""
    global _enhanced_aggregator
    
    if _enhanced_aggregator is None:
        with _enhanced_aggregator_lock:
            if _enhanced_aggregator is None:
                _enhanced_aggregator = EnhancedPredictionMarketAggregator()
    if not getattr(_enhanced_aggregator, '_started', False):
        await _enhanced_aggregator.start()
    
    return _enhanced_aggregator


# Testing
async def test_enhanced_prediction_markets():
    """Test the enhanced prediction markets aggregator."""
    aggregator = EnhancedPredictionMarketAggregator()
    
    try:
        await aggregator.start()
        
        # Wait for initial data
        await asyncio.sleep(5)
        
        # Test markets
        markets = aggregator.get_all_markets()
        print(f"Fetched {len(markets)} markets (synthetic + real)")
        
        # Test drift signals
        drift_signals = aggregator.get_drift_signals()
        print(f"Found {len(drift_signals)} drift signals")
        
        # Test arbitrage opportunities
        arbitrage_opps = aggregator.get_arbitrage_opportunities()
        print(f"Found {len(arbitrage_opps)} arbitrage opportunities")
        
        # Wait for synthetic signals
        await asyncio.sleep(20)
        
        # Check for new signals
        new_drift_signals = aggregator.get_drift_signals()
        new_arbitrage_opps = aggregator.get_arbitrage_opportunities()
        
        print(f"Total drift signals: {len(new_drift_signals)}")
        print(f"Total arbitrage opportunities: {len(new_arbitrage_opps)}")
        
    finally:
        await aggregator.stop()


if __name__ == "__main__":
    asyncio.run(test_enhanced_prediction_markets())
