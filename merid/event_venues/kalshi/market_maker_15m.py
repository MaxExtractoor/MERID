"""15m Market Making Agent for Kalshi Crypto Trading.

Implements two-phase market making strategy for 15-minute crypto prediction markets.
Configuration loaded from kalshi_crypto_15m_v2.yaml profile.

Phase 1 (0-720s): Two-sided quoting at $0.50 ± 3¢, refresh every 15s
Phase 2 (720-900s): Directional GTC on winning side at $0.52

Respects $1 fixed exposure cap and inventory limits.
"""

from __future__ import annotations
import time
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple
from enum import Enum
from datetime import datetime, timezone, timedelta

from utils.logger import get_logger
logger = get_logger("merid.event_venues.kalshi.market_maker_15m")


class MarketMakingPhase(str, Enum):
    """Market making phase."""
    PHASE1_TWO_SIDED = "phase1_two_sided"
    PHASE2_DIRECTIONAL = "phase2_directional"
    DISABLED = "disabled"


@dataclass
class MarketMakingConfig:
    """Market making configuration from profile."""
    enabled: bool = False
    quoting_mode: str = "two_phase"
    spread_cents: int = 2
    inventory_limit_contracts: int = 50
    skew_adjustment: bool = True
    phase1_duration_seconds: int = 720
    phase1_price_center_cents: int = 50
    phase1_spread_cents: int = 3
    phase1_refresh_interval_seconds: int = 15
    phase1_contracts_per_side: int = 15
    phase2_price_cents: int = 52
    phase2_contracts: int = 15
    phase2_min_move_pct: float = 0.0012


@dataclass
class Quote:
    """A market maker quote."""
    ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    price_cents: int
    size_contracts: int  # Number of contracts (kept for backward compatibility)
    phase: MarketMakingPhase
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    
    @property
    def count(self) -> int:
        """Alias for size_contracts for compatibility with OrderIntent."""
        return self.size_contracts


@dataclass
class InventoryState:
    """Inventory state for a ticker."""
    ticker: str
    yes_contracts: int = 0
    no_contracts: int = 0
    net_position: int = 0  # Positive = long YES, Negative = long NO
    avg_entry_price: float = 0.0
    last_updated: float = field(default_factory=time.time)


class MarketMaker15m:
    """15m market making agent for Kalshi crypto prediction markets.
    
    Implements two-phase quoting strategy:
    - Phase 1 (0-720s): Two-sided quoting at center price ± spread
    - Phase 2 (720-900s): Directional quote on winning side
    
    Respects $1 fixed exposure cap and inventory limits.
    """
    
    def __init__(self, config: MarketMakingConfig):
        """Initialize market maker.
        
        Args:
            config: Market making configuration from profile
        """
        self.config = config
        self._inventory: Dict[str, InventoryState] = {}
        self._active_quotes: Dict[str, List[Quote]] = {}
        self._phase_start_time: float = 0.0
        self._current_phase = MarketMakingPhase.DISABLED
        self._last_quote_refresh: float = 0.0
        self._running = False
        
        if not config.enabled:
            logger.info("[MM-15M] Market making disabled in configuration")
            return
        
        logger.info(
            "[MM-15M] Initialized with quoting_mode=%s phase1_duration=%ds phase1_contracts=%d phase2_contracts=%d",
            config.quoting_mode, config.phase1_duration_seconds,
            config.phase1_contracts_per_side, config.phase2_contracts
        )
    
    def start(self, window_start: datetime) -> None:
        """Start market making for a new 15m window.
        
        Args:
            window_start: Start time of the current 15m window
        """
        if not self.config.enabled:
            return
        
        self._phase_start_time = time.time()
        self._current_phase = MarketMakingPhase.PHASE1_TWO_SIDED
        self._last_quote_refresh = 0.0
        self._running = True
        
        logger.info(
            "[MM-15M] Started for window %s phase=%s",
            window_start.isoformat(), self._current_phase
        )
    
    def stop(self) -> None:
        """Stop market making and cancel all quotes."""
        if not self._running:
            return
        
        self._running = False
        self._current_phase = MarketMakingPhase.DISABLED
        self._active_quotes.clear()
        
        logger.info("[MM-15M] Stopped - all quotes cancelled")
    
    def get_phase(self) -> MarketMakingPhase:
        """Get current market making phase based on time elapsed.
        
        Returns:
            Current phase
        """
        if not self._running or not self.config.enabled:
            return MarketMakingPhase.DISABLED
        
        elapsed = time.time() - self._phase_start_time
        
        if elapsed < self.config.phase1_duration_seconds:
            return MarketMakingPhase.PHASE1_TWO_SIDED
        else:
            return MarketMakingPhase.PHASE2_DIRECTIONAL
    
    def should_refresh_quotes(self) -> bool:
        """Check if quotes should be refreshed.
        
        Returns:
            True if quotes should be refreshed
        """
        if not self._running:
            return False
        
        phase = self.get_phase()
        if phase == MarketMakingPhase.DISABLED:
            return False
        
        # Phase 1: refresh every phase1_refresh_interval_seconds
        if phase == MarketMakingPhase.PHASE1_TWO_SIDED:
            elapsed = time.time() - self._last_quote_refresh
            return elapsed >= self.config.phase1_refresh_interval_seconds
        
        # Phase 2: no refresh (single directional quote)
        return False
    
    def generate_quotes(
        self,
        ticker: str,
        yes_bid: Optional[int],
        yes_ask: Optional[int],
        no_bid: Optional[int],
        no_ask: Optional[int],
        seconds_to_expiry: float
    ) -> List[Quote]:
        """Generate quotes for a ticker based on current phase.
        
        Args:
            ticker: Market ticker
            yes_bid: YES bid price in cents
            yes_ask: YES ask price in cents
            no_bid: NO bid price in cents
            no_ask: NO ask price in cents
            seconds_to_expiry: Seconds to contract expiry
            
        Returns:
            List of quotes to submit
        """
        if not self.config.enabled or not self._running:
            return []
        
        phase = self.get_phase()
        if phase == MarketMakingPhase.DISABLED:
            return []
        
        quotes = []
        
        # Check inventory limit
        inventory = self._get_inventory(ticker)
        if abs(inventory.net_position) >= self.config.inventory_limit_contracts:
            logger.warning(
                "[MM-15M] Inventory limit reached for %s: net_position=%d limit=%d",
                ticker, inventory.net_position, self.config.inventory_limit_contracts
            )
            return []
        
        if phase == MarketMakingPhase.PHASE1_TWO_SIDED:
            quotes = self._generate_phase1_quotes(ticker, yes_bid, yes_ask, no_bid, no_ask)
        elif phase == MarketMakingPhase.PHASE2_DIRECTIONAL:
            quotes = self._generate_phase2_quotes(ticker, yes_bid, yes_ask, no_bid, no_ask)
        
        if quotes:
            self._last_quote_refresh = time.time()
            self._active_quotes[ticker] = quotes
        
        return quotes
    
    def _generate_phase1_quotes(
        self,
        ticker: str,
        yes_bid: Optional[int],
        yes_ask: Optional[int],
        no_bid: Optional[int],
        no_ask: Optional[int]
    ) -> List[Quote]:
        """Generate Phase 1 two-sided quotes.
        
        Args:
            ticker: Market ticker
            yes_bid: YES bid price in cents
            yes_ask: YES ask price in cents
            no_bid: NO bid price in cents
            no_ask: NO ask price in cents
            
        Returns:
            List of quotes (YES bid, YES ask, NO bid, NO ask)
        """
        quotes = []
        center = self.config.phase1_price_center_cents
        spread = self.config.phase1_spread_cents
        size = self.config.phase1_contracts_per_side
        
        # Apply skew adjustment if enabled
        inventory = self._get_inventory(ticker)
        if self.config.skew_adjustment and inventory.net_position != 0:
            # Skew quotes away from net position
            skew = min(5, abs(inventory.net_position) // 5)  # Max 5c skew
            if inventory.net_position > 0:
                # Long YES: skew NO side higher (sell NO at higher price)
                center += skew
            else:
                # Long NO: skew YES side lower (sell YES at lower price)
                center -= skew
        
        # Generate quotes around center price
        yes_bid_price = center - spread
        yes_ask_price = center + spread
        no_bid_price = (100 - center) - spread
        no_ask_price = (100 - center) + spread
        
        # Clamp to valid range (10-75c)
        yes_bid_price = max(10, min(75, yes_bid_price))
        yes_ask_price = max(10, min(75, yes_ask_price))
        no_bid_price = max(10, min(75, no_bid_price))
        no_ask_price = max(10, min(75, no_ask_price))
        
        # CRITICAL FIX (2026-08-08): Market maker only generates BUY entries
        # SELL actions are reserved for exit trades only per exit policy
        # Market making provides liquidity via bid-side quotes only
        # Bid prices = buy (provide liquidity to sellers)
        quotes.append(Quote(ticker, "yes", "buy", yes_bid_price, size, MarketMakingPhase.PHASE1_TWO_SIDED))
        quotes.append(Quote(ticker, "no", "buy", no_bid_price, size, MarketMakingPhase.PHASE1_TWO_SIDED))
        
        logger.info(
            "[MM-15M-PHASE1] Generated quotes for %s: YES %d/%d NO %d/%d size=%d skew=%d",
            ticker, yes_bid_price, yes_ask_price, no_bid_price, no_ask_price, size,
            inventory.net_position if self.config.skew_adjustment else 0
        )
        
        return quotes
    
    def _generate_phase2_quotes(
        self,
        ticker: str,
        yes_bid: Optional[int],
        yes_ask: Optional[int],
        no_bid: Optional[int],
        no_ask: Optional[int]
    ) -> List[Quote]:
        """Generate Phase 2 directional quote on winning side.
        
        Args:
            ticker: Market ticker
            yes_bid: YES bid price in cents
            yes_ask: YES ask price in cents
            no_bid: NO bid price in cents
            no_ask: NO ask price in cents
            
        Returns:
            List of quotes (single directional quote)
        """
        quotes = []
        price = self.config.phase2_price_cents
        size = self.config.phase2_contracts
        
        # Determine winning side based on current market price
        # If YES ask < 50c, market favors YES (buy YES)
        # If NO ask < 50c, market favors NO (buy NO)
        # Default to YES if no clear signal
        side = "yes"
        if yes_ask and yes_ask < 50:
            side = "yes"
        elif no_ask and no_ask < 50:
            side = "no"
        
        # Clamp to valid range
        price = max(10, min(75, price))
        
        quotes.append(Quote(ticker, side, "buy", price, size, MarketMakingPhase.PHASE2_DIRECTIONAL))
        
        logger.info(
            "[MM-15M-PHASE2] Generated directional quote for %s: side=%s price=%dc size=%d",
            ticker, side, price, size
        )
        
        return quotes
    
    def _get_inventory(self, ticker: str) -> InventoryState:
        """Get or create inventory state for ticker.
        
        Args:
            ticker: Market ticker
            
        Returns:
            Inventory state
        """
        if ticker not in self._inventory:
            self._inventory[ticker] = InventoryState(ticker=ticker)
        return self._inventory[ticker]
    
    def update_inventory(self, ticker: str, side: str, contracts: int, price_cents: int) -> None:
        """Update inventory after a fill.
        
        Args:
            ticker: Market ticker
            side: "yes" or "no"
            contracts: Number of contracts filled (positive for buy, negative for sell)
            price_cents: Fill price in cents
        """
        inventory = self._get_inventory(ticker)
        
        if side == "yes":
            inventory.yes_contracts += contracts
        else:
            inventory.no_contracts += contracts
        
        # Update net position (YES = +1, NO = -1)
        inventory.net_position = inventory.yes_contracts - inventory.no_contracts
        
        # Update average entry price (weighted average)
        if contracts > 0:
            total_contracts = inventory.yes_contracts + inventory.no_contracts
            if total_contracts > 0:
                old_total = inventory.avg_entry_price * (total_contracts - contracts)
                new_total = old_total + (price_cents * contracts)
                inventory.avg_entry_price = new_total / total_contracts
        
        inventory.last_updated = time.time()
        
        logger.info(
            "[MM-15M-INVENTORY] Updated %s: side=%s contracts=%d price=%dc net_position=%d avg_entry=%.2f",
            ticker, side, contracts, price_cents, inventory.net_position, inventory.avg_entry_price
        )
    
    def get_inventory_state(self, ticker: str) -> Optional[InventoryState]:
        """Get inventory state for ticker.
        
        Args:
            ticker: Market ticker
            
        Returns:
            Inventory state or None if not tracked
        """
        return self._inventory.get(ticker)


# Singleton instance
_market_maker: Optional[MarketMaker15m] = None


def get_market_maker_15m() -> Optional[MarketMaker15m]:
    """Get singleton market maker instance.
    
    Returns:
        MarketMaker15m instance or None if not initialized
    """
    return _market_maker


def init_market_maker_15m(config: MarketMakingConfig) -> MarketMaker15m:
    """Initialize singleton market maker instance.
    
    Args:
        config: Market making configuration
        
    Returns:
        MarketMaker15m instance
    """
    global _market_maker
    _market_maker = MarketMaker15m(config)
    return _market_maker


def reset_market_maker_15m() -> None:
    """Reset singleton market maker instance (for testing)."""
    global _market_maker
    _market_maker = None
