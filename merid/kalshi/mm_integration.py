"""Market Maker Integration Agent

Phase 6 of MERID single-signal hierarchy:
Integrates passive maker strategies with the unified signal stack.

Provides:
- Maker order sizing based on unified regime state
- Inventory skew adjustment based on signal direction
- Quote refresh logic aligned with signal confidence
- Risk bounds for maker exposures

Architecture:
- Thread-safe singleton
- Hooks into existing maker_bot_advanced.py infrastructure
- Respects unified regime classifier state
- Q-inline policy compatible (preparation for Phase 7)
"""

from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Tuple
from enum import Enum
from collections import deque

from merid.signals.unified_regime_classifier import (
    get_unified_regime_classifier,
    UnifiedRegimeState,
    ExecutionRegime,
)
from merid.kalshi.macro_overlay import get_kalshi_macro_overlay
from utils.logger import get_logger

logger = get_logger("merid.kalshi.mm_integration")


class MakerSide(str, Enum):
    """Maker order side."""
    BID = "bid"
    ASK = "ask"


@dataclass
class MakerQuote:
    """A market maker quote with signal-adjusted parameters."""
    ticker: str
    side: MakerSide
    price_cents: int
    size: int
    
    # Signal-derived adjustments
    confidence_adjusted: bool = False
    regime_skew_applied: bool = False
    inventory_offset: int = 0  # Contracts to offset inventory
    
    # Timing
    created_ts: float = field(default_factory=time.time)
    expires_ts: float = 0.0  # Quote validity
    
    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_ts if self.expires_ts > 0 else False


@dataclass
class MakerInventory:
    """Current maker inventory state for a ticker."""
    ticker: str
    net_position: int = 0  # Positive = long, negative = short
    avg_entry_price: float = 0.0
    
    # Unhedged exposure in cents
    gross_exposure: int = 0
    
    # PnL tracking
    realized_pnl_cents: int = 0
    unrealized_pnl_cents: int = 0
    
    # Quote history
    quotes_filled: int = 0
    quotes_cancelled: int = 0


@dataclass
class MakerStrategyConfig:
    """Configuration for maker strategy on a specific ticker."""
    ticker: str
    
    # Base sizing
    base_contracts_per_side: int = 10
    max_inventory_contracts: int = 50
    
    # Spread settings
    base_spread_cents: int = 2
    min_spread_cents: int = 1
    max_spread_cents: int = 10
    
    # Signal integration
    enable_signal_skew: bool = True
    enable_regime_adjustment: bool = True
    
    # Quote lifetime
    quote_ttl_seconds: float = 30.0
    refresh_threshold_seconds: float = 15.0


class MarketMakerIntegration:
    """Integrates market making with unified signal stack.
    
    Coordinates maker quoting with:
    - Unified regime state (Phase 5) for sizing
    - Macro overlay (Phase 3) for directional skew
    - Momentum ranker (Phase 4) for quote refresh urgency
    
    Thread-safe singleton that hooks into existing maker infrastructure.
    """
    
    # Regime-based sizing multipliers (applied to base_contracts_per_side)
    REGIME_SIZE_MULTIPLIERS = {
        ExecutionRegime.AGGRESSIVE: 1.5,
        ExecutionRegime.NORMAL: 1.0,
        ExecutionRegime.DEFENSIVE: 0.5,
        ExecutionRegime.HALT: 0.0,
    }
    
    # Signal-based spread adjustments
    # 2026-07-11: Updated from 3c to 5c to align with dynamic threshold system canonical default
    MAX_SPREAD_WIDENING = 5  # Cents to add in defensive/crisis
    
    # BUG-FIX: Made configurable constants for skew calculations (were hardcoded)
    MACRO_SKEW_MULTIPLIER = 5  # Contracts multiplier for macro conviction
    INVENTORY_SKEW_DIVISOR = 5  # Divisor for inventory-based position reduction
    MAX_INVENTORY_SKEW_RATIO = 0.5  # Max skew as ratio of base contracts (was // 2)
    
    def __init__(
        self,
        tracked_tickers: Optional[List[str]] = None,
    ):
        self.tracked_tickers = tracked_tickers or [
            "KXBTC-15M-UP", "KXBTC-15M-DOWN",
            "KXETH-15M-UP", "KXETH-15M-DOWN",
            "KXSOL-15M-UP", "KXSOL-15M-DOWN",
        ]
        
        self._regime_classifier = get_unified_regime_classifier()
        self._macro_overlay = get_kalshi_macro_overlay()
        
        # Per-ticker configurations
        self._configs: Dict[str, MakerStrategyConfig] = {}
        
        # Inventory tracking
        self._inventory: Dict[str, MakerInventory] = {}
        
        # Active quotes
        self._active_quotes: Dict[str, MakerQuote] = {}
        
        # History for audit
        self._quote_history: deque = deque(maxlen=1000)
        self._fill_history: deque = deque(maxlen=500)
        
        # Callbacks for quote updates
        self._quote_callbacks: List[Callable[[List[MakerQuote]], None]] = []
        
        self._lock = threading.Lock()
        self._running = False
        
        logger.info(
            "MarketMakerIntegration initialized for %d tickers",
            len(self.tracked_tickers)
        )
    
    def register_ticker(self, ticker: str, config: Optional[MakerStrategyConfig] = None) -> None:
        """Register a ticker for maker integration."""
        with self._lock:
            self._configs[ticker] = config or MakerStrategyConfig(ticker=ticker)
            self._inventory[ticker] = MakerInventory(ticker=ticker)
            logger.debug("Registered maker ticker: %s", ticker)
    
    def register_quote_callback(self, callback: Callable[[List[MakerQuote]], None]) -> None:
        """Register callback for quote updates."""
        with self._lock:
            self._quote_callbacks.append(callback)
            logger.debug("Quote callback registered")
    
    def compute_quotes(self, ticker: str, mid_price_cents: int) -> List[MakerQuote]:
        """Compute signal-integrated quotes for a ticker.
        
        Args:
            ticker: Market ticker
            mid_price_cents: Current mid price in cents
            
        Returns:
            List of bid and ask quotes with signal adjustments
        """
        with self._lock:
            if ticker not in self._configs:
                return []
            
            config = self._configs[ticker]
            inventory = self._inventory.get(ticker, MakerInventory(ticker=ticker))
            
            # Get unified regime state
            regime_state = self._regime_classifier.get_current_state()
            if regime_state is None:
                regime_state = UnifiedRegimeState(timestamp=time.time())
            
            # Check halt
            if regime_state.is_halted:
                logger.warning("MM halted for %s due to regime", ticker)
                return []
            
            # Compute base sizing with regime adjustment
            base_size = config.base_contracts_per_side
            size_mult = self.REGIME_SIZE_MULTIPLIERS.get(
                regime_state.execution_regime, 1.0
            )
            adjusted_size = max(1, int(base_size * size_mult))
            
            # Compute spread with regime adjustment
            base_spread = config.base_spread_cents
            if regime_state.is_defensive:
                # BUG-FIX: Made configurable instead of hardcoded +1 cent
                defensive_widening = int(os.getenv("MERID_MM_DEFENSIVE_SPREAD_WIDENING", "1"))
                base_spread += defensive_widening
            spread = max(config.min_spread_cents, min(config.max_spread_cents, base_spread))
            
            # Get macro conviction for directional skew
            macro_skew = self._compute_macro_skew(ticker)
            
            # Apply inventory-based offset
            inventory_skew = self._compute_inventory_skew(inventory, config)
            
            # Build quotes
            quotes = []
            now = time.time()
            
            # Bid quote
            bid_price = mid_price_cents - spread // 2
            bid_size = max(1, adjusted_size + macro_skew + inventory_skew)
            
            quotes.append(MakerQuote(
                ticker=ticker,
                side=MakerSide.BID,
                price_cents=bid_price,
                size=bid_size,
                confidence_adjusted=regime_state.confidence < 1.0,
                regime_skew_applied=macro_skew != 0,
                inventory_offset=inventory_skew,
                expires_ts=now + config.quote_ttl_seconds,
            ))
            
            # Ask quote
            ask_price = mid_price_cents + spread // 2
            ask_size = max(1, adjusted_size - macro_skew - inventory_skew)
            
            quotes.append(MakerQuote(
                ticker=ticker,
                side=MakerSide.ASK,
                price_cents=ask_price,
                size=ask_size,
                confidence_adjusted=regime_state.confidence < 1.0,
                regime_skew_applied=macro_skew != 0,
                inventory_offset=-inventory_skew,
                expires_ts=now + config.quote_ttl_seconds,
            ))
            
            # Store active quotes
            for q in quotes:
                self._active_quotes[f"{ticker}:{q.side.value}"] = q
            
            self._quote_history.append((now, quotes))
            
            # Notify callbacks
            for callback in self._quote_callbacks:
                try:
                    callback(quotes)
                except Exception as e:
                    logger.error("Quote callback failed: %s", e)
            
            return quotes
    
    def _compute_macro_skew(self, ticker: str) -> int:
        """Compute directional skew based on macro conviction.
        
        Returns:
            Signed contract offset (positive = favor longs/bids)
        """
        # Extract asset from ticker
        asset = self._extract_asset(ticker)
        if not asset:
            return 0
        
        convictions = self._macro_overlay.get_conviction_scores()
        if asset not in convictions:
            return 0
        
        conviction = convictions[asset]
        
        # Strong bullish = skew toward bids (more aggressive on bid)
        # Strong bearish = skew toward asks
        if conviction.is_bullish:
            # BUG-FIX: Use configurable constant instead of hardcoded 5
            return int(self.MACRO_SKEW_MULTIPLIER * conviction.confidence)
        elif conviction.is_bearish:
            return -int(self.MACRO_SKEW_MULTIPLIER * conviction.confidence)
        
        return 0
    
    def _compute_inventory_skew(self, inventory: MakerInventory, config: MakerStrategyConfig) -> int:
        """Compute inventory-based offset to reduce net exposure.
        
        Returns:
            Signed contract offset to apply
        """
        if not inventory.net_position:
            return 0
        
        # If long, reduce bid size / increase ask size
        # If short, increase bid size / reduce ask size
        
        # BUG-FIX: Use configurable ratio instead of hardcoded // 2
        max_skew = int(config.base_contracts_per_side * self.MAX_INVENTORY_SKEW_RATIO)
        
        if inventory.net_position > 0:
            # We're long, skew toward selling (negative offset for bid)
            # BUG-FIX: Use configurable divisor instead of hardcoded 5
            return -min(max_skew, inventory.net_position // self.INVENTORY_SKEW_DIVISOR)
        else:
            # We're short, skew toward buying (positive offset for bid)
            return min(max_skew, abs(inventory.net_position) // self.INVENTORY_SKEW_DIVISOR)
    
    def _extract_asset(self, ticker: str) -> Optional[str]:
        """Extract asset symbol from Kalshi ticker."""
        # Map KXBTC-... -> BTC
        if ticker.startswith("KXBTC"):
            return "BTC"
        elif ticker.startswith("KXETH"):
            return "ETH"
        elif ticker.startswith("KXSOL"):
            return "SOL"
        elif ticker.startswith("KXXRP"):
            return "XRP"
        elif ticker.startswith("KXDOGE"):
            return "DOGE"
        return None
    
    def on_fill(self, ticker: str, side: str, contracts: int, price_cents: int) -> None:
        """Handle a maker fill to update inventory."""
        with self._lock:
            if ticker not in self._inventory:
                self._inventory[ticker] = MakerInventory(ticker=ticker)
            
            inv = self._inventory[ticker]
            
            # Update net position
            if side == "bid":  # We sold (our bid was hit)
                inv.net_position += contracts
            else:  # We bought (our ask was lifted)
                inv.net_position -= contracts
            
            inv.quotes_filled += 1
            inv.gross_exposure += contracts * price_cents
            
            self._fill_history.append({
                "timestamp": time.time(),
                "ticker": ticker,
                "side": side,
                "contracts": contracts,
                "price_cents": price_cents,
            })
            
            logger.info(
                "Maker fill: %s %s %d @ %dc (net: %d)",
                ticker, side, contracts, price_cents, inv.net_position
            )
    
    def get_inventory(self, ticker: str) -> Optional[MakerInventory]:
        """Get current inventory for a ticker."""
        with self._lock:
            return self._inventory.get(ticker)
    
    def get_all_inventory(self) -> Dict[str, MakerInventory]:
        """Get all inventory states."""
        with self._lock:
            return dict(self._inventory)
    
    def should_refresh_quotes(self, ticker: str) -> bool:
        """Check if quotes should be refreshed based on signal changes."""
        with self._lock:
            config = self._configs.get(ticker)
            if not config:
                return False
            
            # Check if existing quotes are stale
            for key, quote in self._active_quotes.items():
                if quote.ticker == ticker:
                    age = time.time() - quote.created_ts
                    if age > config.refresh_threshold_seconds:
                        return True
                    if quote.is_expired:
                        return True
            
            return False
    
    def get_risk_summary(self) -> Dict:
        """Get summary of maker risk exposure."""
        with self._lock:
            total_gross = sum(inv.gross_exposure for inv in self._inventory.values())
            total_net = sum(abs(inv.net_position) for inv in self._inventory.values())
            
            regime_state = self._regime_classifier.get_current_state()
            
            return {
                "timestamp": time.time(),
                "total_gross_exposure_cents": total_gross,
                "total_net_contracts": total_net,
                "active_tickers": len(self._active_quotes) // 2,  # Bid+ask per ticker
                "total_fills": len(self._fill_history),
                "current_regime": regime_state.execution_regime.value if regime_state else "unknown",
                "by_ticker": {
                    ticker: {
                        "net": inv.net_position,
                        "gross": inv.gross_exposure,
                    }
                    for ticker, inv in self._inventory.items()
                },
            }
    
    def reset(self) -> None:
        """Reset all maker state."""
        with self._lock:
            self._inventory.clear()
            self._active_quotes.clear()
            self._quote_history.clear()
            self._fill_history.clear()
            self._configs.clear()
            logger.info("MarketMakerIntegration reset")


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════

_mm_integration_instance: Optional[MarketMakerIntegration] = None
_mm_integration_lock = threading.Lock()


def get_market_maker_integration(
    tracked_tickers: Optional[List[str]] = None,
) -> MarketMakerIntegration:
    """Get or create the singleton MarketMakerIntegration."""
    global _mm_integration_instance
    if _mm_integration_instance is None:
        with _mm_integration_lock:
            if _mm_integration_instance is None:
                _mm_integration_instance = MarketMakerIntegration(
                    tracked_tickers=tracked_tickers,
                )
                logger.info("MarketMakerIntegration singleton initialized")
    return _mm_integration_instance


def reset_market_maker_integration() -> None:
    """Reset the singleton (for testing)."""
    global _mm_integration_instance
    with _mm_integration_lock:
        _mm_integration_instance = None
        logger.info("MarketMakerIntegration singleton reset")
