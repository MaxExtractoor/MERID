"""
Agent Migration Example — Before & After Using Crypto Surface

Shows how to refactor existing agents to use the unified crypto surface
instead of hardcoded market lists and implicit "near-spot" logic.
"""

# ═════════════════════════════════════════════════════════════════════════════
# BEFORE: Old-style agent (implicit config, scattered magic numbers)
# ═════════════════════════════════════════════════════════════════════════════

# OLD file: agents/btc_15m_mm_agent_old.py

"""
BEFORE: Agent with hardcoded configuration (DON'T USE THIS PATTERN)
Shows the problem this system solves.
"""


class OldBtc15mMMAgent:
    """
    OLD PATTERN: Implicit configuration scattered throughout agent code.
    
    Problems:
    - Magic number for "near spot": 2.0 (why? where?)
    - Hardcoded market list: ["KXBTC15M"] (correct?(
    - Spot fetched separately: no consistency check
    - Hard to audit: what's spot source?
    - Scaling: add SOL → need new agent class
    """
    
    # ❌ Magic numbers everywhere
    KALSHI_15M_MARKETS = ["KXBTC15M"]  # Which series is this? Is it current?
    KALSHI_1H_MARKETS = ["KXBTCH1"]
    NEAR_SPOT_BAND_PCT = 2.0  # Where does this come from?
    MAX_MARKETS = 10  # Why 10?
    
    def __init__(self, kalshi_api_client, binance_api_client):
        self.kalshi = kalshi_api_client
        self.binance = binance_api_client
    
    def tick(self):
        """Agent loop: fetch, filter, trade."""
        
        # ❌ Spot fetched independently (no guarantees it matches Kalshi)
        spot_price = self.binance.get_price("BTC")
        
        # ❌ Hardcoded Kalshi market list
        raw_markets = self.kalshi.get_markets(self.KALSHI_15M_MARKETS)
        
        # ❌ Implicit near-spot selection with magic number
        near_spot_markets = [
            m for m in raw_markets
            if abs(m.target_price - spot_price) / spot_price * 100.0 <= self.NEAR_SPOT_BAND_PCT
        ][:self.MAX_MARKETS]
        
        # Trade...
        for market in near_spot_markets:
            self.submit_order(market.market_id, ...)


# ═════════════════════════════════════════════════════════════════════════════
# AFTER: New-style agent (clean, unified, auditable)
# ═════════════════════════════════════════════════════════════════════════════

# NEW file: agents/btc_15m_mm_agent_new.py

import logging
from typing import Optional, List

from config.crypto_spot_kalshi_config import (
    CryptoSurfaceEntry,
    KalshiMarketView,
    select_markets_near_spot,
    log_markets_near_spot,
)

logger = logging.getLogger(__name__)


class NewBtc15mMMAgent:
    """
    NEW PATTERN: Clean config + unified surface.
    
    Benefits:
    - All config in one place: CRYPTO_CONFIG + NEAR_SPOT_CONFIG
    - Explicit mapping: BTC → binance → KXBTC15M
    - Explicit bands: ("BTC", "15M") → ±2.0% (verified in config)
    - Easy to audit: just query surface
    - Easy to scale: add DOGE → update config, done
    """
    
    # ✅ No magic numbers here—all in unified config
    SYMBOL = "BTC"
    TIMEFRAME = "15M"
    
    def __init__(self, crypto_surface_service):
        """
        Args:
            crypto_surface_service: Reference to CryptoSurfaceService
                                  (which owns the loader + adapter)
        """
        self.crypto_surface = crypto_surface_service
        self.logger = logger.getChild(f"{self.SYMBOL}_{self.TIMEFRAME}_MM")
    
    async def on_surface_updated(self, surface) -> None:
        """
        Called by surface service when surface is updated.
        
        This is cleaner than polling—surface tells agent when to update.
        """
        self.logger.debug(f"Surface updated; recalculating {self.SYMBOL}-{self.TIMEFRAME}")
        await self.tick()
    
    async def tick(self) -> None:
        """
        Agent loop: query surface, select markets, trade.
        
        Everything is now declarative + auditable.
        """
        
        # ✅ Get entry from unified surface
        entry = self.crypto_surface.get_entry(self.SYMBOL, self.TIMEFRAME)
        if not entry:
            self.logger.warning(f"No entry for {self.SYMBOL}/{self.TIMEFRAME}")
            return
        
        # ✅ Select near-spot using unified selector
        # (band % automatically pulled from NEAR_SPOT_CONFIG)
        markets_near_spot = select_markets_near_spot(entry)
        
        if not markets_near_spot:
            self.logger.debug("No near-spot markets available")
            return
        
        # ✅ Log for audit trail (shows alignment)
        log_markets_near_spot(entry, markets_near_spot, selector="mm_active")
        
        # ✅ Generate orders (now with guaranteed spot/series alignment)
        orders = []
        for market in markets_near_spot[:5]:  # Limit to top 5
            order = self._generate_quote(entry, market)
            if order:
                orders.append(order)
        
        if orders:
            self.logger.info(f"Generated {len(orders)} orders")
            await self._submit_orders(orders)
    
    def _generate_quote(
        self, entry: CryptoSurfaceEntry, market: KalshiMarketView
    ) -> Optional[dict]:
        """
        Generate quote for this market.
        
        All context (spot price, market target, distance) is available.
        """
        
        # Calculate spread around market mid
        mid = market.mid_price()
        bid = max(0.01, mid - 0.02)
        ask = min(0.99, mid + 0.02)
        
        distance_pct = market.distance_to_spot(entry.spot_price)
        
        return {
            "market_id": market.market_id,
            "bid": bid,
            "ask": ask,
            "qty_bid": 10,
            "qty_ask": 10,
            # ✅ Include full context for debugging/auditing
            "context": {
                "spot_price": entry.spot_price,
                "spot_source": entry.spot_source,
                "target_price": market.target_price,
                "distance_pct": distance_pct,
                "series": entry.kalshi_series,
            },
        }
    
    async def _submit_orders(self, orders: List[dict]) -> None:
        """Submit orders to Kalshi (pseudo-code)."""
        for order in orders:
            self.logger.debug(
                f"Submitting: {order['market_id']} "
                f"bid={order['bid']:.3f} ask={order['ask']:.3f} "
                f"(spot={order['context']['spot_price']:.2f})"
            )
            # actual_order_id = await kalshi_api.submit_order(order)


# ═════════════════════════════════════════════════════════════════════════════
# COMPARISON TABLE
# ═════════════════════════════════════════════════════════════════════════════

"""
┌─────────────────────────┬──────────────────────┬─────────────────────────┐
│ Aspect                  │ OLD Pattern          │ NEW Pattern             │
├─────────────────────────┼──────────────────────┼─────────────────────────┤
│ Config Location         │ Scattered in agent   │ Unified in config file  │
│ Near-spot Band          │ Magic number (2.0)   │ Defined per combo       │
│ Spot Source             │ Implicit (binance?)  │ Explicit (binance)      │
│ Kalshi Series           │ Hardcoded list       │ From CRYPTO_CONFIG      │
│ Consistency Check       │ None                 │ Via log_markets_near... │
│ Spot/Series Alignment   │ Assumption           │ Guaranteed              │
│ Adding New Asset        │ New agent class      │ Update config file      │
│ Debugging               │ Hard (where's spot?) │ Easy (full context)     │
│ Auditing                │ Hard                 │ Logs show everything    │
│ Testing                 │ Needs mock client    │ Pure functions           │
│ Scaling                 │ Breaks at ~10 agents │ Unlimited              │
└─────────────────────────┴──────────────────────┴─────────────────────────┘
"""


# ═════════════════════════════════════════════════════════════════════════════
# INTEGRATION: Wiring Old Agent to New Surface (Compatibility Layer)
# ═════════════════════════════════════════════════════════════════════════════


class AgentCompatibilityAdapter:
    """
    If you have many old-style agents, use this adapter to make them work
    with the new surface without rewriting each agent.
    
    This is a temporary bridge; migrate to NewBtc15mMMAgent eventually.
    """
    
    def __init__(self, old_agent, crypto_surface_service):
        """
        Args:
            old_agent: Instance of OldBtc15mMMAgent (or similar)
            crypto_surface_service: New CryptoSurfaceService
        """
        self.old_agent = old_agent
        self.crypto_surface = crypto_surface_service
        self.logger = logger.getChild("CompatibilityAdapter")
    
    async def on_surface_updated(self, surface) -> None:
        """
        Adapt new surface to old agent's interface.
        
        Call old agent's tick(), but intercept market fetches to use surface.
        """
        
        # Monkey-patch: intercept old agent market fetches
        original_get_markets = self.old_agent.kalshi.get_markets
        
        def get_markets_from_surface(market_list):
            """Override: use surface instead of API."""
            self.logger.debug(f"Intercepting market fetch for {market_list}")
            # Map old market list format to surface queries
            # This is hacky but allows gradualswitching
            # e.g., ["KXBTC15M"] → query surface for BTC 15M markets
            return self._lookup_markets_in_surface(market_list)
        
        try:
            # Replace temporarily
            self.old_agent.kalshi.get_markets = get_markets_from_surface
            
            # Run old agent's tick (now using surface)
            self.old_agent.tick()
        
        finally:
            # Restore
            self.old_agent.kalshi.get_markets = original_get_markets
    
    def _lookup_markets_in_surface(self, market_list: list) -> list:
        """
        Map old market list (e.g., ["KXBTC15M"]) to surface entry.
        """
        # Pseudo-implementation; adapt to your format
        result = []
        
        # Try to figure out which symbol/timeframe this is
        # (hacky but necessary for compat)
        for ticker in market_list:
            for symbol, cfg in self._reverse_config.items():
                for tf, series in cfg["series"].items():
                    if series == ticker:
                        # Found it!
                        entry = self.crypto_surface.get_entry(symbol, tf)
                        if entry:
                            result.extend(entry.kalshi_markets)
        
        return result
    
    @property
    def _reverse_config(self):
        """Build reverse mapping: series → (symbol, timeframe)."""
        from config.crypto_spot_kalshi_config import CRYPTO_CONFIG
        
        reverse = {}
        for symbol, cfg in CRYPTO_CONFIG.items():
            reverse[symbol] = cfg
        return reverse


# ═════════════════════════════════════════════════════════════════════════════
# MIGRATION ROADMAP
# ═════════════════════════════════════════════════════════════════════════════

"""
STEP 1: Immediate (Day 1)
  □ Deploy CryptoSurfaceService to production
  □ Use AgentCompatibilityAdapter to wrap existing agents
  □ Agents continue working; now they use unified surface
  □ No code changes needed to existing agents

STEP 2: Short-term (Week 1)
  □ Migrate highest-value agents to NewBtc15mMMAgent pattern
  □ Start: agents that run frequently or have most impact
  □ Benefits accumulate: cleaner code, better logging
  □ Others continue using compat adapter

STEP 3: Medium-term (Week 2-3)
  □ Migrate all remaining agents
  □ Remove compat adapter
  □ Now all agents use unified surface
  □ Config becomes single source of truth

STEP 4: Optimization (Week 4+)
  □ Analyze logs to tune NEAR_SPOT_CONFIG bands
  □ Collect metrics on surface update latency
  □ Add monitoring/alerting on surface health
  □ Document final configuration for team
"""


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLE: Using New Agent
# ═════════════════════════════════════════════════════════════════════════════


async def example_usage():
    """Import and use the new agent."""
    
    # Assume you have crypto_surface_service created elsewhere
    from BACKEND_INTEGRATION_TEMPLATE import CryptoSurfaceService
    
    # Note: In real code, use actual API clients; here using None for demo
    crypto_surface = CryptoSurfaceService(
        binance_client=None,  # TODO: your actual client
        kalshi_client=None,   # TODO: your actual client
    )
    
    # Create new agent
    agent = NewBtc15mMMAgent(crypto_surface)
    
    # Subscribe to surface updates
    crypto_surface.subscribe("btc_15m_mm", agent.on_surface_updated)
    
    # Start service
    await crypto_surface.start()
    
    # Agent will receive on_surface_updated() calls automatically
    # (approximately every 10 seconds, per SurfaceLoaderConfig.update_interval_s)


if __name__ == "__main__":
    print("This file demonstrates agent migration patterns.")
    print("See BEFORE and AFTER sections for comparison.")
    print("Import into your backend to use NewBtc15mMMAgent pattern.")
