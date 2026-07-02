"""Kalshi Universe Invariants - Hard Consistency Enforcement.

This module enforces strict invariants for the Kalshi 15m crypto universe:
- Exactly 5 assets (BTC/ETH/SOL/XRP/DOGE) with 15m timeframe
- Catalog, state store, and WS subscriptions must be consistent
- Any violation blocks trading for affected assets
"""

import logging
from typing import Set, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Expected universe for 15m crypto trading
EXPECTED_UNIVERSE = {
    "KXBTC15M",  # Bitcoin 15-minute
    "KXETH15M",  # Ethereum 15-minute  
    "KXSOL15M",  # Solana 15-minute
    "KXXRP15M",  # Ripple 15-minute
    "KXDOGE15M"  # Dogecoin 15-minute
}

@dataclass
class UniverseState:
    """Current state of the universe across all components."""
    catalog_tickers: Set[str]
    state_store_tickers: Set[str]
    ws_subscribed_tickers: Set[str]
    catalog_open_markets: Set[str]
    state_store_active_markets: Set[str]
    timestamp: datetime
    
    @property
    def is_consistent(self) -> bool:
        """Check if all three sets are equal."""
        return (
            self.catalog_tickers == self.state_store_tickers == self.ws_subscribed_tickers
            and len(self.catalog_tickers) == len(EXPECTED_UNIVERSE)
        )
    
    @property
    def missing_assets(self) -> Dict[str, List[str]]:
        """Identify which components are missing which assets."""
        missing = {}
        
        catalog_missing = EXPECTED_UNIVERSE - self.catalog_tickers
        if catalog_missing:
            missing['catalog'] = list(catalog_missing)
        
        state_missing = EXPECTED_UNIVERSE - self.state_store_tickers
        if state_missing:
            missing['state_store'] = list(state_missing)
        
        ws_missing = EXPECTED_UNIVERSE - self.ws_subscribed_tickers
        if ws_missing:
            missing['ws_subscriptions'] = list(ws_missing)
        
        return missing

class UniverseInvariantChecker:
    """Enforces universe consistency invariants."""
    
    def __init__(self):
        self._violation_count = 0
        self._last_violation_time: Optional[datetime] = None
        self._blocked_assets: Set[str] = set()
        
    def check_universe_consistency(self, 
                                  catalog_tickers: Set[str],
                                  state_store_tickers: Set[str], 
                                  ws_subscribed_tickers: Set[str],
                                  catalog_open_markets: Set[str] = None,
                                  state_store_active_markets: Set[str] = None) -> UniverseState:
        """
        Check universe consistency and enforce invariants.
        
        Args:
            catalog_tickers: Tickers available in catalog
            state_store_tickers: Tickers with market state
            ws_subscribed_tickers: Tickers subscribed to WebSocket
            catalog_open_markets: Subset of catalog that's open for trading
            state_store_active_markets: Subset of state store that's active
            
        Returns:
            UniverseState with current status
            
        Raises:
            ValueError: If critical violations detected
        """
        now = datetime.now(timezone.utc)
        
        # Default to full sets if subsets not provided
        catalog_open_markets = catalog_open_markets or catalog_tickers
        state_store_active_markets = state_store_active_markets or state_store_tickers
        
        state = UniverseState(
            catalog_tickers=catalog_tickers,
            state_store_tickers=state_store_tickers,
            ws_subscribed_tickers=ws_subscribed_tickers,
            catalog_open_markets=catalog_open_markets,
            state_store_active_markets=state_store_active_markets,
            timestamp=now
        )
        
        # Log detailed universe state
        logger.info(
            "[UNIVERSE-CHECK] catalog=%d state=%d ws=%d open=%d active=%d | "
            "catalog_set=%s state_set=%s ws_set=%s",
            len(catalog_tickers), len(state_store_tickers), len(ws_subscribed_tickers),
            len(catalog_open_markets), len(state_store_active_markets),
            sorted(catalog_tickers), sorted(state_store_tickers), sorted(ws_subscribed_tickers)
        )
        
        # Check for missing expected assets
        missing_assets = state.missing_assets
        if missing_assets:
            logger.warning(
                "[UNIVERSE-MISSING] Missing expected assets: %s",
                {component: sorted(tickers) for component, tickers in missing_assets.items()}
            )
        
        # Check for unexpected assets
        catalog_extra = catalog_tickers - EXPECTED_UNIVERSE
        if catalog_extra:
            logger.warning(
                "[UNIVERSE-EXTRA] Catalog has unexpected tickers: %s",
                sorted(catalog_extra)
            )
        
        # Check consistency violations
        if not state.is_consistent:
            self._violation_count += 1
            self._last_violation_time = now
            
            # Identify specific violations
            violations = []
            
            if catalog_tickers != state_store_tickers:
                catalog_only = catalog_tickers - state_store_tickers
                state_only = state_store_tickers - catalog_tickers
                if catalog_only:
                    violations.append(f"catalog missing from state: {sorted(catalog_only)}")
                if state_only:
                    violations.append(f"state missing from catalog: {sorted(state_only)}")
            
            if catalog_tickers != ws_subscribed_tickers:
                catalog_only = catalog_tickers - ws_subscribed_tickers
                ws_only = ws_subscribed_tickers - catalog_tickers
                if catalog_only:
                    violations.append(f"catalog not subscribed: {sorted(catalog_only)}")
                if ws_only:
                    violations.append(f"ws extra subscriptions: {sorted(ws_only)}")
            
            if state_store_tickers != ws_subscribed_tickers:
                state_only = state_store_tickers - ws_subscribed_tickers
                ws_only = ws_subscribed_tickers - state_store_tickers
                if state_only:
                    violations.append(f"state not subscribed: {sorted(state_only)}")
                if ws_only:
                    violations.append(f"ws extra subscriptions: {sorted(ws_only)}")
            
            logger.error(
                "[UNIVERSE-VIOLATION] #%d Inconsistency detected: %s | "
                "Expected: %s | Catalog: %s | State: %s | WS: %s",
                self._violation_count, " | ".join(violations),
                sorted(EXPECTED_UNIVERSE), sorted(catalog_tickers),
                sorted(state_store_tickers), sorted(ws_subscribed_tickers)
            )
            
            # Block trading for inconsistent assets
            inconsistent_assets = (
                (catalog_tickers ^ state_store_tickers) |
                (catalog_tickers ^ ws_subscribed_tickers) |
                (state_store_tickers ^ ws_subscribed_tickers)
            )
            self._blocked_assets.update(inconsistent_assets)
            
            logger.error(
                "[UNIVERSE-BLOCK] Trading blocked for inconsistent assets: %s",
                sorted(self._blocked_assets)
            )
            
            # Critical violation if universe size is wrong
            if len(catalog_tickers) != len(EXPECTED_UNIVERSE):
                raise ValueError(
                    f"CRITICAL UNIVERSE VIOLATION: Expected {len(EXPECTED_UNIVERSE)} "
                    f"assets, got {len(catalog_tickers)} in catalog"
                )
        else:
            # Universe is consistent - clear any previous blocks for these assets
            consistent_assets = catalog_tickers & state_store_tickers & ws_subscribed_tickers
            newly_unblocked = self._blocked_assets & consistent_assets
            if newly_unblocked:
                logger.info(
                    "[UNIVERSE-UNBLOCK] Trading unblocked for consistent assets: %s",
                    sorted(newly_unblocked)
                )
                self._blocked_assets -= newly_unblocked
        
        return state
    
    def is_asset_tradable(self, ticker: str) -> bool:
        """Check if an asset is allowed to trade based on universe consistency."""
        return ticker not in self._blocked_assets
    
    def get_tradable_assets(self) -> Set[str]:
        """Get the set of assets that are currently allowed to trade."""
        return EXPECTED_UNIVERSE - self._blocked_assets
    
    def get_violation_stats(self) -> Dict[str, any]:
        """Get statistics about universe violations."""
        return {
            'total_violations': self._violation_count,
            'last_violation_time': self._last_violation_time.isoformat() if self._last_violation_time else None,
            'blocked_assets': sorted(self._blocked_assets),
            'tradable_assets': sorted(self.get_tradable_assets()),
            'expected_universe_size': len(EXPECTED_UNIVERSE),
            'current_universe_size': len(EXPECTED_UNIVERSE - self._blocked_assets)
        }
    
    def reset_violations(self) -> None:
        """Reset violation counters (useful after fixes)."""
        self._violation_count = 0
        self._last_violation_time = None
        self._blocked_assets.clear()
        logger.info("[UNIVERSE-RESET] All violation counters and blocks cleared")

# Global checker instance
_universe_checker = UniverseInvariantChecker()

def get_universe_checker() -> UniverseInvariantChecker:
    """Get the global universe invariant checker."""
    return _universe_checker

def check_universe_consistency(catalog_tickers: Set[str],
                              state_store_tickers: Set[str],
                              ws_subscribed_tickers: Set[str],
                              catalog_open_markets: Set[str] = None,
                              state_store_active_markets: Set[str] = None) -> UniverseState:
    """Convenience function for universe checking."""
    return _universe_checker.check_universe_consistency(
        catalog_tickers, state_store_tickers, ws_subscribed_tickers,
        catalog_open_markets, state_store_active_markets
    )
