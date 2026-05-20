"""TRADING_SCOPE - Production Scope Freeze for BTC/ETH/SOL/XRP/DOGE 15m

This is the single source of truth for what is ALLOWED in production trading.
Any market, asset, or timeframe outside this scope must be rejected with loud logging.

PRODUCTION SCOPE:
- Assets: BTC, ETH, SOL, XRP, DOGE only
- Timeframe: 15-minute markets only
- Venue: Kalshi only
- Series tickers: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M only

All trading paths must validate against this scope before order submission.
"""

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional, Set, Tuple
from utils.logger import get_logger

logger = get_logger("config.trading_scope")


class ScopeViolation(str, Enum):
    """Types of scope violations."""
    INVALID_ASSET = "INVALID_ASSET"
    INVALID_TIMEFRAME = "INVALID_TIMEFRAME"
    INVALID_SERIES_TICKER = "INVALID_SERIES_TICKER"
    INVALID_VENUE = "INVALID_VENUE"


@dataclass(frozen=True)
class TradingScope:
    """Production trading scope configuration."""
    
    # Allowed assets (uppercase)
    ALLOWED_ASSETS: FrozenSet[str] = frozenset({"BTC", "ETH", "SOL", "XRP", "DOGE"})
    
    # Allowed timeframe (only 15m for production)
    ALLOWED_TIMEFRAME: str = "15m"
    
    # Allowed venue (only Kalshi for production)
    ALLOWED_VENUE: str = "kalshi"
    
    # Allowed series tickers (5 assets × 15m only)
    ALLOWED_SERIES_TICKERS: FrozenSet[str] = frozenset({
        "KXBTC15M",
        "KXETH15M",
        "KXSOL15M",
        "KXXRP15M",
        "KXDOGE15M",
    })
    
    # Legacy timeframe aliases that map to 15m (for backward compatibility)
    TIMEFRAME_ALIASES: FrozenSet[str] = frozenset({"15m", "15M", "scalp", "SCALP"})
    
    def validate_asset(self, asset: str) -> Tuple[bool, Optional[str]]:
        """Validate asset is within scope.
        
        Returns:
            (is_valid, error_message) - error_message is None if valid
        """
        asset_upper = asset.upper().strip()
        if asset_upper not in self.ALLOWED_ASSETS:
            allowed_str = ", ".join(sorted(self.ALLOWED_ASSETS))
            error = f"[SCOPE_VIOLATION] Invalid asset '{asset}'. Allowed: {allowed_str}"
            logger.error(error)
            return False, error
        return True, None
    
    def validate_timeframe(self, timeframe: str) -> Tuple[bool, Optional[str]]:
        """Validate timeframe is within scope.
        
        Returns:
            (is_valid, error_message) - error_message is None if valid
        """
        # Check direct match or alias
        normalized = timeframe.strip()
        if normalized == self.ALLOWED_TIMEFRAME or normalized in self.TIMEFRAME_ALIASES:
            return True, None
        
        error = f"[SCOPE_VIOLATION] Invalid timeframe '{timeframe}'. Allowed: {self.ALLOWED_TIMEFRAME} (aliases: {', '.join(self.TIMEFRAME_ALIASES)})"
        logger.error(error)
        return False, error
    
    def validate_series_ticker(self, series_ticker: str) -> Tuple[bool, Optional[str]]:
        """Validate series ticker is within scope.

        Accepts either a pure series ticker (e.g., "KXBTC15M") or a full market ticker
        (e.g., "KXBTC15M-26MAY192245-45"). For full market tickers, validates that
        the series prefix is in the allowed list.

        Returns:
            (is_valid, error_message) - error_message is None if valid
        """
        ticker_upper = series_ticker.upper().strip()

        # Check if it's a full market ticker (contains hyphen) or pure series ticker
        if "-" in ticker_upper:
            # Extract the series prefix (everything before the first hyphen)
            series_prefix = ticker_upper.split("-")[0]
            if series_prefix not in self.ALLOWED_SERIES_TICKERS:
                allowed_str = ", ".join(sorted(self.ALLOWED_SERIES_TICKERS))
                error = f"[SCOPE_VIOLATION] Invalid series ticker '{series_ticker}'. Allowed: {allowed_str}"
                logger.error(error)
                return False, error
        else:
            # Pure series ticker - check exact match
            if ticker_upper not in self.ALLOWED_SERIES_TICKERS:
                allowed_str = ", ".join(sorted(self.ALLOWED_SERIES_TICKERS))
                error = f"[SCOPE_VIOLATION] Invalid series ticker '{series_ticker}'. Allowed: {allowed_str}"
                logger.error(error)
                return False, error
        return True, None
    
    def validate_market(self, asset: str, timeframe: str, series_ticker: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """Validate all market parameters are within scope.
        
        Returns:
            (is_valid, error_message) - error_message is None if valid
        """
        # Validate asset
        asset_valid, asset_error = self.validate_asset(asset)
        if not asset_valid:
            return False, asset_error
        
        # Validate timeframe
        tf_valid, tf_error = self.validate_timeframe(timeframe)
        if not tf_valid:
            return False, tf_error
        
        # Validate series ticker if provided
        if series_ticker:
            ticker_valid, ticker_error = self.validate_series_ticker(series_ticker)
            if not ticker_valid:
                return False, ticker_error
        
        # All validations passed
        logger.debug(f"[SCOPE_OK] Market validated: {asset}/{timeframe}/{series_ticker or 'N/A'}")
        return True, None
    
    def infer_asset_from_ticker(self, ticker: str) -> Optional[str]:
        """Infer asset from a market ticker if it matches allowed series prefix."""
        ticker_upper = ticker.upper().strip()
        for asset in self.ALLOWED_ASSETS:
            prefix = f"KX{asset}"
            if ticker_upper.startswith(prefix):
                return asset
        return None
    
    def is_15m_series_ticker(self, ticker: str) -> bool:
        """Check if ticker is a valid 15m series ticker.

        Accepts either a pure series ticker (e.g., "KXBTC15M") or a full market ticker
        (e.g., "KXBTC15M-26MAY192245-45"). For full market tickers, checks if the
        series prefix is in the allowed list.
        """
        ticker_upper = ticker.upper().strip()

        # Check if it's a full market ticker (contains hyphen) or pure series ticker
        if "-" in ticker_upper:
            # Extract the series prefix (everything before the first hyphen)
            series_prefix = ticker_upper.split("-")[0]
            return series_prefix in self.ALLOWED_SERIES_TICKERS
        else:
            # Pure series ticker - check exact match
            return ticker_upper in self.ALLOWED_SERIES_TICKERS
    
    def get_summary(self) -> dict:
        """Get summary of trading scope for logging."""
        return {
            "allowed_assets": sorted(self.ALLOWED_ASSETS),
            "allowed_timeframe": self.ALLOWED_TIMEFRAME,
            "allowed_venue": self.ALLOWED_VENUE,
            "allowed_series_tickers": sorted(self.ALLOWED_SERIES_TICKERS),
            "total_assets": len(self.ALLOWED_ASSETS),
            "total_series": len(self.ALLOWED_SERIES_TICKERS),
        }


# Global singleton instance
_TRADING_SCOPE: Optional[TradingScope] = None


def get_trading_scope() -> TradingScope:
    """Get the global trading scope singleton."""
    global _TRADING_SCOPE
    if _TRADING_SCOPE is None:
        _TRADING_SCOPE = TradingScope()
        logger.info("[SCOPE_INIT] Trading scope initialized", extra=_TRADING_SCOPE.get_summary())
    return _TRADING_SCOPE


# Convenience functions for common validations
def validate_asset_for_trading(asset: str) -> bool:
    """Validate asset is allowed for trading. Logs error if invalid."""
    scope = get_trading_scope()
    is_valid, _ = scope.validate_asset(asset)
    return is_valid


def validate_timeframe_for_trading(timeframe: str) -> bool:
    """Validate timeframe is allowed for trading. Logs error if invalid."""
    scope = get_trading_scope()
    is_valid, _ = scope.validate_timeframe(timeframe)
    return is_valid


def validate_series_ticker_for_trading(series_ticker: str) -> bool:
    """Validate series ticker is allowed for trading. Logs error if invalid."""
    scope = get_trading_scope()
    is_valid, _ = scope.validate_series_ticker(series_ticker)
    return is_valid


def validate_market_for_trading(asset: str, timeframe: str, series_ticker: Optional[str] = None) -> bool:
    """Validate all market parameters for trading. Logs error if invalid."""
    scope = get_trading_scope()
    is_valid, _ = scope.validate_market(asset, timeframe, series_ticker)
    return is_valid
