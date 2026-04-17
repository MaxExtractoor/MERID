"""
Agent Integration Examples — Using Crypto Surface for Market Selection

Shows how trading agents (MM, scalpers, makers) integrate with the unified
crypto surface to consistently reference "near spot" markets and spot prices.

Patterns demonstrated:
1. Querying a single asset/timeframe from the surface
2. Selecting near-spot markets for that combo
3. Logging trade decisions with surface context
4. Testing MM agent against mock surface
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from config.crypto_spot_kalshi_config import (
    CRYPTO_CONFIG,
    NEAR_SPOT_CONFIG,
    CryptoSurfaceEntry,
    KalshiMarketView,
    select_markets_near_spot,
    log_markets_near_spot,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. MM AGENT PATTERN
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class BtcMakerAgentContext:
    """
    RuntimeContext for BTC 15m MM agent.
    
    Holds references to surface loader + agent logic.
    Agents should obtain surface via loader.get_entry() each tick.
    """
    symbol: str = "BTC"
    timeframe: str = "15M"
    surface_loader: Optional[Any] = None  # CryptoSurfaceLoader instance


class Btc15mMakerAgent:
    """
    Example BTC 15m market maker agent using crypto surface.
    
    On each tick:
    1. Get current surface entry (symbol/timeframe)
    2. Apply near-spot selector to filter markets
    3. Iterate through near-spot markets for quoting
    4. Log all decisions with surface context
    """
    
    def __init__(self, context: BtcMakerAgentContext):
        self.context = context
        self.logger = logger.getChild(f"{context.symbol}_{context.timeframe}_MM")
    
    async def tick(self, depth_snapshot: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Main agent loop tick.
        
        Args:
            depth_snapshot: Optional orderbook depth data (for realistic MM logic)
        
        Returns:
            List of order decisions: [{"action": "quote", "market_id": ..., ...}, ...]
        """
        
        # 1. Get current surface entry
        if not self.context.surface_loader:
            self.logger.warning("No surface loader configured; skipping tick")
            return []
        
        surface_entry = self.context.surface_loader.get_entry(
            self.context.symbol, self.context.timeframe
        )
        if not surface_entry:
            self.logger.warning(
                f"No surface entry for {self.context.symbol}/{self.context.timeframe}"
            )
            return []
        
        # 2. Select near-spot markets
        markets_near_spot = select_markets_near_spot(surface_entry)
        if not markets_near_spot:
            self.logger.warning(f"No near-spot markets found for {surface_entry}")
            return []
        
        # 3. Log selection for audit
        log_markets_near_spot(
            surface_entry, markets_near_spot, selector="mm_active_selection"
        )
        
        # 4. Generate quotes for each near-spot market
        orders = []
        for market in markets_near_spot[:5]:  # Limit to top 5
            order = self._generate_quote(surface_entry, market)
            if order:
                orders.append(order)
        
        self.logger.info(
            f"MM tick: {len(orders)} orders for {len(markets_near_spot)} near-spot markets"
        )
        return orders
    
    def _generate_quote(
        self, surface_entry: CryptoSurfaceEntry, market: KalshiMarketView
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a quote order for this market.
        
        In production would compute bid/ask from model + orderbook.
        """
        
        # Example: quote ±2¢ around current price
        bid_price = max(0.01, market.mid_price() - 0.02)
        ask_price = min(0.99, market.mid_price() + 0.02)
        
        # Skip if spread is too wide or market is too far from spot
        distance_pct = market.distance_to_spot(surface_entry.spot_price)
        if distance_pct > NEAR_SPOT_CONFIG[(surface_entry.symbol, surface_entry.timeframe)]["pct_band"]:
            # This shouldn't happen if selector worked correctly
            self.logger.warning(f"Market {market.market_id} outside band! distance={distance_pct:.2f}%")
            return None
        
        return {
            "action": "quote",
            "market_id": market.market_id,
            "bid": bid_price,
            "ask": ask_price,
            "bid_qty": 10,
            "ask_qty": 10,
            "ref_spot_price": surface_entry.spot_price,
            "ref_spot_ts": surface_entry.spot_ts.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# 2. SCALPER AGENT PATTERN
# ─────────────────────────────────────────────────────────────────────────────


class ScalperAgent:
    """
    Example scalper that trades tight 15m markets against spot.
    
    Scalpers care most about:
    - Spot price recency (CFB RTI Settlement index)
    - Very tight distance from current spot
    - Fast expiry (only trade last N minutes of contract)
    """
    
    def __init__(self, symbol: str, ccy_pair: str = "15M"):
        self.symbol = symbol
        self.timeframe = ccy_pair
        self.logger = logger.getChild(f"{symbol}_{ccy_pair}_Scalper")
    
    async def find_scalp_opportunities(
        self, surface_entry: CryptoSurfaceEntry
    ) -> List[Dict[str, Any]]:
        """
        Scan for scalping opportunities in near-spot markets.
        
        Scalper filters:
        - Market expires in next 5 minutes (time decay edge)
        - Target price within ±1% of spot
        - Bankroll efficient position size
        """
        if surface_entry.symbol != self.symbol or surface_entry.timeframe != self.timeframe:
            self.logger.warning(
                f"Surface entry mismatch: asked for {self.symbol}/{self.timeframe}, "
                f"got {surface_entry.symbol}/{surface_entry.timeframe}"
            )
            return []
        
        # Select near-spot markets
        markets_near_spot = select_markets_near_spot(surface_entry)
        
        # Filter for scalping (time decay + tight distance)
        time_now = datetime.now()
        scalp_markets = []
        
        for market in markets_near_spot:
            # Must expire soon
            time_to_expiry = (market.expires_at - time_now).total_seconds()
            if time_to_expiry > 300:  # Only last 5 minutes
                continue
            if time_to_expiry < 30:   # But not TOO close (execution risk)
                continue
            
            # Must be very close to spot
            distance = market.distance_to_spot(surface_entry.spot_price)
            if distance > 1.0:  # More than 1% from spot
                continue
            
            scalp_markets.append(market)
        
        log_markets_near_spot(
            surface_entry, scalp_markets, selector="scalper_tight_band"
        )
        
        # Generate scalp orders
        orders = []
        for market in scalp_markets:
            order = self._generate_scalp_order(surface_entry, market)
            if order:
                orders.append(order)
        
        self.logger.info(
            f"Scalp opportunities: {len(orders)} orders from {len(scalp_markets)} tight markets"
        )
        return orders
    
    def _generate_scalp_order(
        self, surface_entry: CryptoSurfaceEntry, market: KalshiMarketView
    ) -> Optional[Dict]:
        """Generate scalp order: aggressive entry at current mid."""
        
        # Scalper: trade at market (aggressive)
        mid = market.mid_price()
        
        # Aggressive entry: buy YES if spot > target, NO if spot < target
        if surface_entry.spot_price > market.target_price:
            side = "YES"
            price = market.yes_price  # Pay the ask
        else:
            side = "NO"
            price = market.no_price
        
        return {
            "action": "market_order",
            "market_id": market.market_id,
            "side": side,
            "qty": 5,
            "price": price,
            "scalp_edge_expected": 0.02,  # ~2¢ edge from time decay
            "ref_spot_price": surface_entry.spot_price,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 3. POSITION TRACKER / RISK MONITOR
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PositionRecord:
    """Single position record with surface reference."""
    market_id: str
    symbol: str
    timeframe: str
    side: str  # "YES" or "NO"
    qty: int
    entry_price: float
    entry_ts: datetime
    ref_spot_price: float  # Spot at time of entry
    kalshi_series: str     # From surface


class RiskMonitor:
    """
    Tracks positions + monitor correlation to real spot.
    
    Uses surface to:
    - Map position series back to symbol/timeframe
    - Verify "near spot" assumption still holds
    - Flag positions that drift from surface
    """
    
    def __init__(self):
        self.positions: Dict[str, PositionRecord] = {}
        self.logger = logger.getChild("RiskMonitor")
    
    def add_position(self, pos: PositionRecord) -> None:
        self.positions[pos.market_id] = pos
        self.logger.info(
            f"Added position {pos.symbol}-{pos.timeframe}: {pos.side} x{pos.qty} "
            f"@ {pos.entry_price:.2f}, spot was {pos.ref_spot_price:.2f}"
        )
    
    def verify_positions_near_spot(self, surface: Any) -> List[Dict[str, Any]]:
        """
        For each position, check if it's still "near spot" per current surface.
        
        Returns list of warnings/issues found.
        """
        issues = []
        
        for market_id, pos in self.positions.items():
            # Find current surface for this position's asset/timeframe
            entry = surface.get_entry(pos.symbol, pos.timeframe) if hasattr(surface, "get_entry") else None
            if not entry:
                issues.append(f"Position {market_id}: no surface entry for {pos.symbol}/{pos.timeframe}")
                continue
            
            # Check if market is still near spot
            distance = abs(entry.spot_price - pos.ref_spot_price) / pos.ref_spot_price * 100.0
            max_band = NEAR_SPOT_CONFIG.get((pos.symbol, pos.timeframe), {}).get("pct_band", 5.0)
            
            if distance > max_band:
                issues.append(
                    f"Position {market_id}: spot drifted {distance:.2f}% "
                    f"(was {pos.ref_spot_price:.2f}, now {entry.spot_price:.2f}); "
                    f"exceeds band {max_band}%"
                )
                self.logger.warning(issues[-1])
        
        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 4. MOCK TESTS
# ─────────────────────────────────────────────────────────────────────────────


def test_mm_agent():
    """Test MM agent pattern with mock surface."""
    
    logger.info("=== MM Agent Pattern Test ===")
    
    # Create mock surface entry
    entry = CryptoSurfaceEntry(
        symbol="BTC",
        timeframe="15M",
        spot_price=70743.69,
        spot_source="binance",
        spot_ts=datetime.now(),
        kalshi_series="KXBTC15M",
        kalshi_markets=[
            KalshiMarketView(
                market_id=f"KXBTC15M-{i}",
                title="BTC Up or Down - 15m",
                yes_price=0.48 + i*0.01,
                no_price=0.52 - i*0.01,
                target_price=70500.0 + i*500,
                status="open",
                expires_at=datetime.now() + timedelta(minutes=5),
            )
            for i in range(5)
        ],
    )
    
    # Mock surface loader
    class MockSurfaceLoader:
        def get_entry(self, symbol, timeframe):
            if symbol == "BTC" and timeframe == "15M":
                return entry
            return None
    
    # Create agent
    context = BtcMakerAgentContext(surface_loader=MockSurfaceLoader())
    agent = Btc15mMakerAgent(context)
    
    # Simulate tick
    import asyncio
    orders = asyncio.run(agent.tick())
    
    logger.info(f"Generated {len(orders)} orders")
    for order in orders[:2]:
        logger.info(f"  Order: {order['market_id']} bid={order['bid']:.3f} ask={order['ask']:.3f}")


def test_scalper_agent():
    """Test scalper agent pattern."""
    
    logger.info("\n=== Scalper Agent Pattern Test ===")
    
    # Create mock surface with markets at different distances
    entry = CryptoSurfaceEntry(
        symbol="BTC",
        timeframe="15M",
        spot_price=70743.69,
        spot_source="binance",
        spot_ts=datetime.now(),
        kalshi_series="KXBTC15M",
        kalshi_markets=[
            # Scalp-eligible markets (close to spot, expiring soon)
            KalshiMarketView(
                market_id=f"KXBTC15M-scalp-{i}",
                title="BTC Up or Down - 15m",
                yes_price=0.49,
                no_price=0.51,
                target_price=70700.0 + i*50,  # ±50 from spot
                status="open",
                expires_at=datetime.now() + timedelta(seconds=120 + i*10),
            )
            for i in range(3)
        ],
    )
    
    agent = ScalperAgent("BTC", "15M")
    import asyncio
    orders = asyncio.run(agent.find_scalp_opportunities(entry))
    
    logger.info(f"Found {len(orders)} scalp opportunities")
    for order in orders[:2]:
        logger.info(f"  Order: {order['market_id']} {order['side']} x{order['qty']}")


def test_risk_monitor():
    """Test position tracking with surface verification."""
    
    logger.info("\n=== Risk Monitor Test ===")
    
    monitor = RiskMonitor()
    
    # Add some positions
    pos1 = PositionRecord(
        market_id="KXBTC15M-A",
        symbol="BTC",
        timeframe="15M",
        side="YES",
        qty=10,
        entry_price=0.48,
        entry_ts=datetime.now(),
        ref_spot_price=70743.69,
        kalshi_series="KXBTC15M",
    )
    monitor.add_position(pos1)
    
    # Create mock surface with entry that has drifted
    entry = CryptoSurfaceEntry(
        symbol="BTC",
        timeframe="15M",
        spot_price=71500.0,  # Drifted ~1.05%
        spot_source="binance",
        spot_ts=datetime.now(),
        kalshi_series="KXBTC15M",
        kalshi_markets=[],
    )
    
    class MockSurface:
        def get_entry(self, symbol, timeframe):
            if symbol == "BTC" and timeframe == "15M":
                return entry
            return None
    
    issues = monitor.verify_positions_near_spot(MockSurface())
    
    if issues:
        logger.info(f"Risk issues found: {len(issues)}")
        for issue in issues:
            logger.info(f"  ⚠ {issue}")
    else:
        logger.info("✓ All positions within near-spot band")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    test_mm_agent()
    test_scalper_agent()
    test_risk_monitor()
    
    logger.info("\n✓ All integration tests complete")
