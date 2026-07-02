"""
Lane Registry - Manages crypto trading lanes for MERID.

Registers and provides access to Crypto15MLane instances for different
symbols (BTC, ETH, SOL, XRP) in both live and paper modes.

Usage:
    from merid.lanes.registry import build_crypto_lanes, get_lane_registry
    
    # Build all lanes
    registry = build_crypto_lanes(kalshi_client, price_feed, signal_bus, risk_bus, portfolio, lane_control)
    
    # Get specific lane
    btc_lane = registry.get_lane("BTC_15M")
    xrp_paper_lane = registry.get_lane("XRP_15M_PAPER")
"""

from __future__ import annotations

from typing import Dict, List, Optional
from merid.lanes.crypto15m_lane import Crypto15MLane, Crypto15MLaneConfig
from utils.logger import get_logger

logger = get_logger(__name__)


class LaneRegistry:
    """Registry for managing crypto trading lanes."""
    
    def __init__(self):
        self._lanes: Dict[str, Crypto15MLane] = {}
        self._configs: Dict[str, Crypto15MLaneConfig] = {}
    
    def register(self, lane_id: str, lane: Crypto15MLane, config: Crypto15MLaneConfig) -> None:
        """Register a lane with the registry."""
        self._lanes[lane_id] = lane
        self._configs[lane_id] = config
        logger.info("Registered lane: %s (paper=%s)", lane_id, config.paper)
    
    def get_lane(self, lane_id: str) -> Optional[Crypto15MLane]:
        """Get a lane by ID."""
        return self._lanes.get(lane_id)
    
    def get_config(self, lane_id: str) -> Optional[Crypto15MLaneConfig]:
        """Get a lane config by ID."""
        return self._configs.get(lane_id)
    
    def get_all_lanes(self) -> Dict[str, Crypto15MLane]:
        """Get all registered lanes."""
        return self._lanes.copy()
    
    def get_lanes_by_symbol(self, symbol: str) -> Dict[str, Crypto15MLane]:
        """Get all lanes for a specific symbol."""
        return {
            lane_id: lane for lane_id, lane in self._lanes.items()
            if lane.cfg.symbol == symbol
        }
    
    def get_paper_lanes(self) -> Dict[str, Crypto15MLane]:
        """Get all paper trading lanes."""
        return {
            lane_id: lane for lane_id, lane in self._lanes.items()
            if lane.cfg.paper
        }
    
    def get_live_lanes(self) -> Dict[str, Crypto15MLane]:
        """Get all live trading lanes."""
        return {
            lane_id: lane for lane_id, lane in self._lanes.items()
            if not lane.cfg.paper
        }
    
    def list_lane_ids(self) -> List[str]:
        """List all registered lane IDs."""
        return list(self._lanes.keys())
    
    def get_status_summary(self) -> Dict[str, any]:
        """Get status summary of all lanes."""
        summary = {
            "total_lanes": len(self._lanes),
            "live_lanes": len(self.get_live_lanes()),
            "paper_lanes": len(self.get_paper_lanes()),
            "running_lanes": len([l for l in self._lanes.values() if l.is_running]),
            "symbols": list(set(l.cfg.symbol for l in self._lanes.values())),
            "lanes": {}
        }
        
        for lane_id, lane in self._lanes.items():
            summary["lanes"][lane_id] = lane.get_status()
        
        return summary


# Global registry instance
_registry: Optional[LaneRegistry] = None


def get_lane_registry() -> LaneRegistry:
    """Get the global lane registry."""
    global _registry
    if _registry is None:
        _registry = LaneRegistry()
    return _registry


def build_crypto_lanes(
    kalshi_client,
    price_feed,
    risk_bus,
    portfolio,
    lane_control,
) -> LaneRegistry:
    """
    Build and register crypto lanes for all symbols and modes.
    
    Args:
        kalshi_client: Kalshi venue client
        price_feed: Price feed service
        risk_bus: Risk management bus
        portfolio: Portfolio manager
        lane_control: Lane control service
        
    Returns:
        LaneRegistry with all lanes registered
    """
    registry = get_lane_registry()
    
    # Configuration for all symbols and modes
    configs = [
        # LIVE ladders
        Crypto15MLaneConfig(
            symbol="BTC",
            max_positions=1,
            max_markets_live=1,
            base_kelly_fraction=0.25,
            min_edge_bps=50,
            fear_greed_weight=0.5,
            risk_stream_topic="risk.crypto.btc15m",
            paper=False,
        ),
        Crypto15MLaneConfig(
            symbol="ETH",
            max_positions=1,
            max_markets_live=1,
            base_kelly_fraction=0.2,
            min_edge_bps=60,
            fear_greed_weight=0.4,
            risk_stream_topic="risk.crypto.eth15m",
            paper=False,
        ),
        Crypto15MLaneConfig(
            symbol="SOL",
            max_positions=1,
            max_markets_live=1,
            base_kelly_fraction=0.15,
            min_edge_bps=70,
            fear_greed_weight=0.3,
            risk_stream_topic="risk.crypto.sol15m",
            paper=False,
        ),
        Crypto15MLaneConfig(
            symbol="XRP",
            max_positions=1,
            max_markets_live=1,
            base_kelly_fraction=0.15,
            min_edge_bps=70,
            fear_greed_weight=0.3,
            risk_stream_topic="risk.crypto.xrp15m",
            paper=False,
        ),

        # PAPER ladders (shadow trading)
        Crypto15MLaneConfig(
            symbol="BTC",
            max_positions=1,
            max_markets_live=1,
            base_kelly_fraction=0.25,
            min_edge_bps=50,
            fear_greed_weight=0.5,
            risk_stream_topic="risk.crypto.btc15m.paper",
            paper=True,
        ),
        Crypto15MLaneConfig(
            symbol="ETH",
            max_positions=1,
            max_markets_live=1,
            base_kelly_fraction=0.2,
            min_edge_bps=60,
            fear_greed_weight=0.4,
            risk_stream_topic="risk.crypto.eth15m.paper",
            paper=True,
        ),
        Crypto15MLaneConfig(
            symbol="SOL",
            max_positions=1,
            max_markets_live=1,
            base_kelly_fraction=0.15,
            min_edge_bps=70,
            fear_greed_weight=0.3,
            risk_stream_topic="risk.crypto.sol15m.paper",
            paper=True,
        ),
        Crypto15MLaneConfig(
            symbol="XRP",
            max_positions=1,
            max_markets_live=1,
            base_kelly_fraction=0.15,
            min_edge_bps=70,
            fear_greed_weight=0.3,
            risk_stream_topic="risk.crypto.xrp15m.paper",
            paper=True,
        ),

        # DOGE lanes - meme volatility with social-sentiment weighting
        Crypto15MLaneConfig(
            symbol="DOGE",
            max_positions=1,
            max_markets_live=1,
            base_kelly_fraction=0.10,  # Lower base due to meme volatility
            min_edge_bps=100,  # Higher edge requirement for DOGE
            fear_greed_weight=0.6,  # Heavy social sentiment weighting
            risk_stream_topic="risk.crypto.doge15m",
            paper=False,
        ),
        Crypto15MLaneConfig(
            symbol="DOGE",
            max_positions=1,
            max_markets_live=1,
            base_kelly_fraction=0.10,
            min_edge_bps=100,
            fear_greed_weight=0.6,
            risk_stream_topic="risk.crypto.doge15m.paper",
            paper=True,
        ),
    ]

    # Create and register lanes
    for cfg in configs:
        lane = Crypto15MLane(cfg, kalshi_client, price_feed, risk_bus, portfolio)
        lane_id = f"{lane.lane_id}{'_PAPER' if cfg.paper else ''}"
        registry.register(lane_id=lane_id, lane=lane, config=cfg)
        
        # Register with lane control if provided
        if lane_control:
            lane_control.register(lane_id=lane_id, lane=lane)

    logger.info(
        "Built %d crypto lanes: %d live, %d paper",
        len(configs),
        len([c for c in configs if not c.paper]),
        len([c for c in configs if c.paper])
    )
    
    return registry


def reset_lane_registry() -> None:
    """Reset the global lane registry (for testing)."""
    global _registry
    _registry = None
