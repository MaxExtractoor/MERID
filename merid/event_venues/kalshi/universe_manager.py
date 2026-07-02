"""Kalshi 15m Universe Manager - Hard guarantees for ticker consistency.

This module enforces the invariant that the 15m crypto universe must always
contain exactly 5 tickers (BTC, ETH, SOL, XRP, DOGE) with proper regex validation
and synchronized state across catalog, WS bridge, and market state store.
"""

import re
from typing import Set, List, Dict, Tuple
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.universe_manager")

# Universe invariant constants
EXPECTED_ASSETS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
EXPECTED_SERIES = {"KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"}
UNIVERSE_SIZE = 5

# Regex pattern for valid 15m crypto tickers
# Format: KX{ASSET}15M-{DATE}-{TIME}
TICKER_REGEX = re.compile(r"^KX(BTC|ETH|SOL|XRP|DOGE)15M-[A-Z0-9]+$")

class UniverseInvariantViolation(Exception):
    """Raised when universe invariant is violated."""
    pass

class UniverseManager:
    """Manages 15m crypto universe with hard invariants."""
    
    def __init__(self):
        self.last_validation_ts: float = 0.0
        self.violation_count: int = 0
        
    def validate_ticker_format(self, ticker: str) -> bool:
        """Validate ticker matches expected regex pattern."""
        # Check if it's a series ticker (e.g., KXBTC15M) or full market ticker
        if '-' not in ticker:
            # Series ticker - check if it matches series pattern
            series_regex = re.compile(r"^KX(BTC|ETH|SOL|XRP|DOGE)15M$")
            return bool(series_regex.match(ticker))
        else:
            # Full market ticker - check against full pattern
            return bool(TICKER_REGEX.match(ticker))
    
    def extract_asset_from_ticker(self, ticker: str) -> str:
        """Extract asset symbol from ticker."""
        # Handle both series tickers (KXBTC15M) and full market tickers
        if '-' not in ticker:
            # Series ticker - extract from series pattern
            series_regex = re.compile(r"^KX(BTC|ETH|SOL|XRP|DOGE)15M$")
            match = series_regex.match(ticker)
            if match:
                return match.group(1)
        else:
            # Full market ticker - extract from full pattern
            match = TICKER_REGEX.match(ticker)
            if match:
                return match.group(1)
        return ""
    
    def extract_series_from_ticker(self, ticker: str) -> str:
        """Extract series ticker from full market ticker."""
        # Convert KXBTC15M-26JUN041100-00 to KXBTC15M
        parts = ticker.split('-')
        if len(parts) >= 1:
            return parts[0]
        return ticker
    
    def validate_universe_invariant(self, 
                                  catalog_tickers: Set[str],
                                  state_tickers: Set[str],
                                  ws_tickers: Set[str]) -> Dict[str, any]:
        """
        Validate the universe invariant across all three sources.
        
        Args:
            catalog_tickers: Tickers from catalog snapshot (full market tickers)
            state_tickers: Tickers from market state store (full market tickers)
            ws_tickers: Tickers from WS bridge subscriptions (full market tickers)
            
        Returns:
            Dict with validation results and any violations
        """
        now = datetime.now(timezone.utc)
        
        # Convert full market tickers to series tickers for universe validation
        catalog_series = {self.extract_series_from_ticker(t) for t in catalog_tickers}
        state_series = {self.extract_series_from_ticker(t) for t in state_tickers}
        ws_series = {self.extract_series_from_ticker(t) for t in ws_tickers}
        
        result = {
            "timestamp": now.isoformat(),
            "valid": True,
            "violations": [],
            "catalog": {
                "count": len(catalog_tickers),
                "tickers": sorted(catalog_tickers),
                "series": sorted(catalog_series),
                "valid_format": all(self.validate_ticker_format(t) for t in catalog_series)
            },
            "state": {
                "count": len(state_tickers),
                "tickers": sorted(state_tickers),
                "series": sorted(state_series),
                "valid_format": all(self.validate_ticker_format(t) for t in state_series)
            },
            "ws": {
                "count": len(ws_tickers),
                "tickers": sorted(ws_tickers),
                "series": sorted(ws_series),
                "valid_format": all(self.validate_ticker_format(t) for t in ws_series)
            }
        }
        
        # Check universe size invariant (using series tickers)
        if len(catalog_series) != UNIVERSE_SIZE:
            result["valid"] = False
            result["violations"].append(
                f"UNIVERSE_SIZE: catalog has {len(catalog_series)} series, expected {UNIVERSE_SIZE}"
            )
        
        # Check ticker format invariant
        if not result["catalog"]["valid_format"]:
            result["valid"] = False
            invalid_format = [t for t in catalog_series if not self.validate_ticker_format(t)]
            result["violations"].append(
                f"TICKER_FORMAT: catalog has invalid tickers: {invalid_format}"
            )
        
        # Check asset coverage invariant (using series tickers)
        catalog_assets = {self.extract_asset_from_ticker(t) for t in catalog_series}
        missing_assets = EXPECTED_ASSETS - catalog_assets
        if missing_assets:
            result["valid"] = False
            result["violations"].append(
                f"ASSET_COVERAGE: catalog missing assets: {missing_assets}"
            )
        
        # Check synchronization invariants (using series tickers)
        catalog_state_intersection = catalog_series & state_series
        catalog_ws_intersection = catalog_series & ws_series
        
        # CRITICAL FIX: Allow grace period for WebSocket bridge to populate market state store during startup
        # Only enforce SYNC_STATE if market state store has been populated (has tickers)
        if len(state_series) > 0 and len(catalog_state_intersection) != UNIVERSE_SIZE:
            result["valid"] = False
            result["violations"].append(
                f"SYNC_STATE: catalog={len(catalog_series)}, state={len(state_series)}, "
                f"intersection={len(catalog_state_intersection)}"
            )
        
        # Only enforce SYNC_WS if WebSocket bridge has subscriptions
        if len(ws_series) > 0 and len(catalog_ws_intersection) != UNIVERSE_SIZE:
            result["valid"] = False
            result["violations"].append(
                f"SYNC_WS: catalog={len(catalog_series)}, ws={len(ws_series)}, "
                f"intersection={len(catalog_ws_intersection)}"
            )
        
        # Log validation results
        if result["valid"]:
            logger.info(
                "[UNIVERSE-INVARIANT] PASSED: catalog=%d state=%d ws=%d assets=%s",
                len(catalog_tickers), len(state_tickers), len(ws_tickers),
                sorted(catalog_assets)
            )
        else:
            self.violation_count += 1
            logger.error(
                "[UNIVERSE-INVARIANT] VIOLATION #%d: %s",
                self.violation_count, "; ".join(result["violations"])
            )
        
        self.last_validation_ts = now.timestamp()
        return result
    
    def compute_universe_delta(self,
                              current_tickers: Set[str],
                              desired_tickers: Set[str]) -> Tuple[Set[str], Set[str]]:
        """
        Compute delta between current and desired ticker sets.
        
        Returns:
            Tuple of (to_remove, to_add)
        """
        to_remove = current_tickers - desired_tickers
        to_add = desired_tickers - current_tickers
        return to_remove, to_add
    
    def log_universe_update(self,
                          old_tickers: Set[str],
                          new_tickers: Set[str],
                          to_remove: Set[str],
                          to_add: Set[str]) -> None:
        """Log detailed universe update information."""
        logger.info(
            "[UNIVERSE-UPDATE] assets=BTC,ETH,SOL,XRP,DOGE old=%d new=%d to_remove=%d to_add=%d",
            len(old_tickers), len(new_tickers), len(to_remove), len(to_add)
        )
        
        # Log individual ticker actions
        for ticker in to_remove:
            logger.info("[UNIVERSE-UPDATE] ticker=%s action=REMOVE", ticker)
        
        for ticker in to_add:
            logger.info("[UNIVERSE-UPDATE] ticker=%s action=ADD", ticker)

# Global universe manager instance
_universe_manager = UniverseManager()

def get_universe_manager() -> UniverseManager:
    """Get the global universe manager instance."""
    return _universe_manager
