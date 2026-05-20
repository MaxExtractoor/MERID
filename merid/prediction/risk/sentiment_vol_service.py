"""
SentimentVolService — Centralized Service for Fear/Greed, Volatility & Sizing

This is the SINGLE SOURCE OF TRUTH for all sentiment, volatility, and sizing
decisions in the MERID Kalshi stack.

Architecture:
- Raw data sources (CFGI API, Kalshi orderbook, internal models) feed into this service
- Service produces canonical SentimentScalar, VolatilityScalar objects
- Position sizing uses SizingMultiplier computed deterministically from canonical inputs
- All consumers import ONLY from this service, never re-implement calculations

Usage:
    from merid.prediction.risk.sentiment_vol_service import get_sentiment_vol_service
    
    service = get_sentiment_vol_service()
    
    # Get canonical sentiment for an asset
    sentiment, is_stale = service.get_sentiment("BTC")
    
    # Get canonical volatility
    vol = service.get_volatility("BTC")
    
    # Get sizing multiplier for a trade
    mult = service.get_sizing_multiplier("BTC", is_contrarian=False)
    
    # Apply to position size
    final_size = mult.apply_to_size(base_kelly_size)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List, Callable, Any, Tuple
from collections import deque

from utils.logger import get_logger

from merid.prediction.risk.sentiment_vol_types import (
    SentimentScalar,
    VolatilityScalar,
    SizingMultiplier,
    FearGreedRegime,
    VolatilityRegime,
    UncertaintyRegime,
    get_sentiment_vol_config,
    compute_sentiment_regime,
    compute_volatility_regime,
    compute_uncertainty_regime,
    compute_sizing_multiplier,
    create_sentiment_scalar,
    create_volatility_scalar,
)

logger = get_logger("merid.prediction.risk.sentiment_vol_service")


# ═══════════════════════════════════════════════════════════════════════════
# Volatility Calculation Utilities
# ═══════════════════════════════════════════════════════════════════════════

def calculate_realized_volatility(
    returns: List[float],
    annualization_factor: float = 725.0,  # sqrt(minutes_per_year) for 1m returns
) -> float:
    """
    Calculate annualized realized volatility from a series of returns.
    
    Args:
        returns: List of period returns (e.g., 1-minute returns as fractions)
        annualization_factor: Factor to annualize the volatility
    
    Returns:
        Annualized volatility as fraction (e.g., 0.50 = 50% vol)
    """
    if len(returns) < 2:
        return 0.0
    
    mean_r = sum(returns) / len(returns)
    var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    # Handle floating point precision: treat tiny variance as zero
    if var_r < 1e-12:
        return 0.0
    std_period = var_r ** 0.5
    
    return std_period * annualization_factor


def calculate_vol_of_vol(
    vol_series: List[float],
    window: int = 5,
) -> float:
    """
    Calculate volatility of volatility (uncertainty measure).
    
    Args:
        vol_series: Series of volatility readings
        window: Lookback window for calculation
    
    Returns:
        Uncertainty measure (0-1 scale, normalized)
    """
    if len(vol_series) < window:
        return 0.0
    
    recent = vol_series[-window:]
    mean_vol = sum(recent) / len(recent)
    if mean_vol <= 0:
        return 0.0
    
    var_vol = sum((v - mean_vol) ** 2 for v in recent) / len(recent)
    std_vol = var_vol ** 0.5 if var_vol > 0 else 0.0
    
    # Normalize: cv of volatility
    cv = std_vol / mean_vol
    # Scale to 0-1 (typical cv range 0-1, cap at 2.0)
    return min(1.0, cv / 2.0)


def calculate_atr_volatility_proxy(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> float:
    """
    Calculate ATR-based volatility proxy.
    
    For Kalshi where we may not have full OHLC, this uses available data
    to estimate a volatility measure that correlates with true volatility.
    
    Returns:
        ATR as percentage of price (annualized approximation)
    """
    if len(closes) < 2:
        return 0.0
    
    # Simple ATR using available data
    tr_values = []
    for i in range(1, len(closes)):
        if i < len(highs) and i < len(lows):
            # Full range available
            hl = abs(highs[i] - lows[i])
            hpc = abs(highs[i] - closes[i - 1])
            lpc = abs(lows[i] - closes[i - 1])
            tr = max(hl, hpc, lpc)
        else:
            # Only close-to-close available
            tr = abs(closes[i] - closes[i - 1])
        tr_values.append(tr)
    
    if not tr_values:
        return 0.0
    
    # Average over window
    window = min(period, len(tr_values))
    atr = sum(tr_values[-window:]) / window
    
    # Convert to percentage of price and annualize
    if closes and closes[-1] > 0:
        atr_pct = atr / closes[-1]
        # Rough annualization: multiply by sqrt(trading periods per year)
        # For hourly data: ~250 trading days * 24 hours = 6000, sqrt ~ 77
        # For daily: sqrt(250) ~ 16
        # This is an approximation; true annualization depends on timeframe
        annualized = atr_pct * 25.0  # Approximation for hourly-like data
        return annualized
    
    return 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Asset State Tracking
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class AssetState:
    """Internal state tracking for an asset's sentiment and volatility."""
    asset: str
    
    # Sentiment state
    current_sentiment: Optional[SentimentScalar] = None
    sentiment_history: deque = field(default_factory=lambda: deque(maxlen=100))
    
    # Volatility state
    current_volatility: Optional[VolatilityScalar] = None
    returns_history: deque = field(default_factory=lambda: deque(maxlen=120))  # ~2 hours of 1m
    vol_history: deque = field(default_factory=lambda: deque(maxlen=50))  # For vol-of-vol
    
    # Price history for vol calc
    price_history: deque = field(default_factory=lambda: deque(maxlen=120))
    
    # Last update tracking
    last_sentiment_update: Optional[datetime] = None
    last_vol_update: Optional[datetime] = None
    
    # Subscribers
    callbacks: List[Callable[[SentimentScalar, VolatilityScalar], None]] = field(default_factory=list)
    
    def is_stale(self, max_age_seconds: float = 300.0) -> Tuple[bool, str]:
        """Check if data is stale."""
        now = datetime.now(timezone.utc)
        
        if self.last_sentiment_update is None:
            return True, "no_sentiment_data"
        
        sent_age = (now - self.last_sentiment_update).total_seconds()
        if sent_age > max_age_seconds:
            return True, f"sentiment_stale({sent_age:.0f}s)"
        
        if self.last_vol_update is None:
            return True, "no_volatility_data"
        
        vol_age = (now - self.last_vol_update).total_seconds()
        if vol_age > max_age_seconds:
            return True, f"volatility_stale({vol_age:.0f}s)"
        
        return False, "fresh"


# ═══════════════════════════════════════════════════════════════════════════
# Main Service
# ═══════════════════════════════════════════════════════════════════════════

class SentimentVolService:
    """
    Centralized service for sentiment, volatility, and sizing decisions.
    
    This is the single integration point for:
    - CFGI/external fear-greed indices
    - Kalshi orderbook-derived sentiment
    - Realized volatility from price feeds
    - ATR-based volatility proxies
    
    All consumers should use this service; no direct access to raw sources.
    """
    
    _instance: Optional[SentimentVolService] = None
    # TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
    # TODO: Re-enable lock after startup is stable and investigate proper async synchronization
    # _lock = threading.Lock()
    _lock = None  # Disabled to prevent startup hang
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            if cls._lock is not None:
                with cls._lock:
                    if cls._instance is None:
                        cls._instance = super().__new__(cls)
                        cls._instance._initialized = False
            else:
                # Lock disabled - direct initialization (startup workaround)
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        update_interval_seconds: float = 60.0,
        stale_threshold_seconds: float = 300.0,
    ):
        if self._initialized:
            return
        
        self.config = get_sentiment_vol_config()
        self._update_interval = update_interval_seconds
        self._stale_threshold = stale_threshold_seconds
        
        # Asset state tracking
        self._assets: Dict[str, AssetState] = {}
        # TEMPORARILY DISABLED: threading.RLock causing deadlock during startup
        # TODO: Re-enable lock after startup is stable and investigate proper async synchronization
        # self._asset_lock = threading.RLock()
        self._asset_lock = None  # Disabled to prevent startup hang
        
        # Background update control
        self._running = False
        self._update_thread: Optional[threading.Thread] = None
        
        # Metrics tracking
        self._update_count = 0
        self._error_count = 0
        
        self._initialized = True
        logger.info("SentimentVolService initialized")
    
    # ── Metrics integration (optional) ────────────────────────────────────
        try:
            from merid.prediction.risk.sentiment_vol_metrics import get_metrics_recorder
            self._metrics = get_metrics_recorder()
            self._metrics.initialize_config(self.config)
        except Exception:
            self._metrics = None
    
    # ── Asset Management ───────────────────────────────────────────────────
    
    def register_asset(self, asset: str) -> None:
        """Register an asset for tracking."""
        if self._asset_lock is not None:
            with self._asset_lock:
                if asset.upper() not in self._assets:
                    self._assets[asset.upper()] = AssetState(asset=asset.upper())
                    logger.debug(f"Registered asset: {asset}")
        else:
            # Lock disabled - direct access (startup workaround)
            if asset.upper() not in self._assets:
                self._assets[asset.upper()] = AssetState(asset=asset.upper())
                logger.debug(f"Registered asset: {asset}")
    
    def unregister_asset(self, asset: str) -> None:
        """Unregister an asset."""
        if self._asset_lock is not None:
            with self._asset_lock:
                self._assets.pop(asset.upper(), None)
        else:
            # Lock disabled - direct access (startup workaround)
            self._assets.pop(asset.upper(), None)
    
    def get_tracked_assets(self) -> List[str]:
        """Get list of tracked assets."""
        if self._asset_lock is not None:
            with self._asset_lock:
                return list(self._assets.keys())
        else:
            # Lock disabled - direct access (startup workaround)
            return list(self._assets.keys())
    
    # ── Sentiment Updates ─────────────────────────────────────────────────
    
    def update_sentiment(
        self,
        asset: str,
        value: float,
        confidence: float = 1.0,
        source: str = "manual",
        is_synthetic: bool = False,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> SentimentScalar:
        """
        Update sentiment for an asset from a raw source.
        
        This is the canonical entry point for all sentiment data ingestion.
        Raw sources (CFGI, orderbook, etc.) should call this method.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            value: 0-100 fear/greed index
            confidence: 0-1 confidence in reading
            source: Identifier of data source
            is_synthetic: True if data is estimated/fallback
            raw_data: Optional source-specific data
        
        Returns:
            Canonical SentimentScalar
        """
        asset = asset.upper()
        self.register_asset(asset)
        
        # Create canonical sentiment
        sentiment = create_sentiment_scalar(
            value=value,
            confidence=confidence,
            source=source,
            is_synthetic=is_synthetic,
            raw_data=raw_data,
        )
        
        if self._asset_lock is not None:
            with self._asset_lock:
                state = self._assets[asset]
                state.current_sentiment = sentiment
                state.sentiment_history.append(sentiment)
        else:
            # Lock disabled - direct access (startup workaround)
            state = self._assets[asset]
            state.current_sentiment = sentiment
            state.sentiment_history.append(sentiment)
            state.last_sentiment_update = datetime.now(timezone.utc)
        
        # Notify subscribers
        self._notify_subscribers(asset)
        
        # Record metrics
        if self._metrics:
            self._metrics.record_sentiment(asset, sentiment)
        
        return sentiment
    
    def update_sentiment_from_cfgi(self, asset: str) -> Optional[SentimentScalar]:
        """Update sentiment from CFGI API."""
        try:
            from merid.sentiment.cfgi_client import quick_fg, is_crypto_asset
            
            if not is_crypto_asset(asset):
                return None
            
            fgi = quick_fg(asset)
            # quick_fg returns 50 for synthetic/unavailable, detect this
            is_synthetic = (fgi == 50)

            return self.update_sentiment(
                asset=asset,
                value=float(fgi),
                confidence=0.8 if not is_synthetic else 0.5,
                source="cfgi",
                is_synthetic=is_synthetic,
            )
        except Exception as exc:
            logger.warning(f"Failed to update CFGI sentiment for {asset}: {exc}")
            self._error_count += 1
            return None
    
    # ── Volatility Updates ────────────────────────────────────────────────
    
    def update_price(self, asset: str, price: float) -> Optional[VolatilityScalar]:
        """
        Feed a price update for volatility calculation.
        
        Call this with each new price tick (e.g., 1-minute close).
        Service will automatically calculate realized volatility.
        
        Args:
            asset: Asset symbol
            price: Current price
        
        Returns:
            Updated VolatilityScalar or None if insufficient data
        """
        asset = asset.upper()
        self.register_asset(asset)
        
        if self._asset_lock is not None:
            with self._asset_lock:
                state = self._assets[asset]
                
                # Calculate return if we have previous price
                if state.price_history:
                    prev_price = state.price_history[-1]
                    if prev_price > 0:
                        ret = (price - prev_price) / prev_price
                        state.returns_history.append(ret)
                
                state.price_history.append(price)
                
                # Need minimum data for vol calc
                if len(state.returns_history) < 5:
                    return None
                
                # Calculate realized vol
                vol = calculate_realized_volatility(list(state.returns_history))
                
                # Create canonical volatility
                volatility = create_volatility_scalar(
                    value=vol,
                    confidence=0.8,
                    source="realized",
                )
                
                state.current_volatility = volatility
                state.last_vol_update = datetime.now(timezone.utc)
        else:
            # Lock disabled - direct access (startup workaround)
            state = self._assets[asset]
            
            # Calculate return if we have previous price
            if state.price_history:
                prev_price = state.price_history[-1]
                if prev_price > 0:
                    ret = (price - prev_price) / prev_price
                    state.returns_history.append(ret)
            
            state.price_history.append(price)
            
            # Need minimum data for vol calc
            if len(state.returns_history) < 5:
                return None
            
            # Calculate realized vol
            vol = calculate_realized_volatility(list(state.returns_history))
            
            # Create canonical volatility
            volatility = create_volatility_scalar(
                value=vol,
                confidence=0.8,
                source="realized",
            )
            
            state.current_volatility = volatility
            state.last_vol_update = datetime.now(timezone.utc)
        
        # Notify subscribers
        self._notify_subscribers(asset)
        
        return volatility
    
    def update_volatility_direct(
        self,
        asset: str,
        annualized_vol: float,
        uncertainty: float = 0.0,
        source: str = "direct",
        confidence: float = 1.0,
    ) -> VolatilityScalar:
        """
        Update volatility directly from an external calculation.
        
        Use this when you have volatility from another source (e.g., VIX,
        implied vol from options, ATR-based calculation).
        
        Args:
            asset: Asset symbol
            annualized_vol: Annualized volatility as fraction
            uncertainty: Vol-of-vol proxy (0-1)
            source: Source identifier
            confidence: Confidence in reading
        
        Returns:
            Canonical VolatilityScalar
        """
        asset = asset.upper()
        self.register_asset(asset)
        
        volatility = create_volatility_scalar(
            value=annualized_vol,
            uncertainty=uncertainty,
            source=source,
            confidence=confidence,
        )
        
        if self._asset_lock is not None:
            with self._asset_lock:
                state = self._assets[asset]
                state.current_volatility = volatility
                state.last_vol_update = datetime.now(timezone.utc)
                state.vol_history.append(annualized_vol)
        else:
            # Lock disabled - direct access (startup workaround)
            state = self._assets[asset]
            state.current_volatility = volatility
            state.last_vol_update = datetime.now(timezone.utc)
            state.vol_history.append(annualized_vol)
        
        self._notify_subscribers(asset)
        
        return volatility
    
    # ── Retrieval Methods ─────────────────────────────────────────────────
    
    def get_sentiment(self, asset: str) -> Tuple[Optional[SentimentScalar], bool]:
        """
        Get canonical sentiment for an asset.

        This is the PRIMARY API for sentiment consumption.
        All sizing, risk, and UI code should call this method.

        Args:
            asset: Asset symbol

        Returns:
            (SentimentScalar or None, is_stale) — is_stale=True when data is
            older than stale_threshold or no data is available at all.
        """
        asset = asset.upper()

        if self._asset_lock is not None:
            with self._asset_lock:
                state = self._assets.get(asset)
                if state is None:
                    return None, True

                # Check staleness
                is_stale, reason = state.is_stale(self._stale_threshold)
                if is_stale:
                    logger.debug(f"Stale sentiment for {asset}: {reason}")

                return state.current_sentiment, is_stale
        else:
            # Lock disabled - direct access (startup workaround)
            state = self._assets.get(asset)
            if state is None:
                return None, True

            # Check staleness
            is_stale, reason = state.is_stale(self._stale_threshold)
            if is_stale:
                logger.debug(f"Stale sentiment for {asset}: {reason}")

            return state.current_sentiment, is_stale
    
    def get_volatility(self, asset: str) -> Optional[VolatilityScalar]:
        """
        Get canonical volatility for an asset.
        
        This is the PRIMARY API for volatility consumption.
        
        Args:
            asset: Asset symbol
        
        Returns:
            VolatilityScalar or None if unavailable
        """
        asset = asset.upper()
        
        if self._asset_lock is not None:
            with self._asset_lock:
                state = self._assets.get(asset)
                if state is None:
                    return None
                
                is_stale, reason = state.is_stale(self._stale_threshold)
                if is_stale:
                    logger.debug(f"Stale volatility for {asset}: {reason}")
                
                return state.current_volatility
        else:
            # Lock disabled - direct access (startup workaround)
            state = self._assets.get(asset)
            if state is None:
                return None
            
            is_stale, reason = state.is_stale(self._stale_threshold)
            if is_stale:
                logger.debug(f"Stale volatility for {asset}: {reason}")
            
            return state.current_volatility
    
    def get_sizing_multiplier(
        self,
        asset: str,
        is_contrarian: bool = False,
    ) -> SizingMultiplier:
        """
        Get canonical sizing multiplier for an asset.
        
        This is the PRIMARY API for position sizing decisions.
        Combines sentiment, volatility, and news health into a single deterministic multiplier.
        
        Args:
            asset: Asset symbol
            is_contrarian: True if position is against crowd sentiment
        
        Returns:
            SizingMultiplier (never None - returns neutral if data unavailable)
        """
        asset = asset.upper()

        sentiment, _sent_stale = self.get_sentiment(asset)
        volatility = self.get_volatility(asset)
        
        # Fetch news health status for conviction plumbing
        news_health_status = self._get_news_health_status()

        # Fallback to neutral if data unavailable or stale
        if sentiment is None:
            sentiment = create_sentiment_scalar(
                value=50.0,
                confidence=0.5,
                source="fallback_neutral",
                is_synthetic=True,
            )
        
        if volatility is None:
            volatility = create_volatility_scalar(
                value=0.50,
                uncertainty=0.5,
                source="fallback_target",
                confidence=0.5,
            )
        
        return compute_sizing_multiplier(sentiment, volatility, is_contrarian, news_health_status)
    
    def _get_news_health_status(self) -> str:
        """Fetch news feed health status from LiveFeedManager.
        
        Returns:
            News health status string (healthy, stale, zero_data, no_matches, error, not_configured, unknown)
        """
        try:
            from merid.signals.live_feeds import get_live_feed_manager
            mgr = get_live_feed_manager()
            feed_health = mgr.get_feed_health()
            news = feed_health.get("news", {})
            return news.get("status", "unknown")
        except Exception:
            return "unknown"
    
    def get_composite_state(self, asset: str) -> Dict[str, Any]:
        """
        Get full composite state for an asset (for UI/API).
        
        Returns dict with sentiment, volatility, sizing multiplier,
        and metadata in a single call.
        """
        asset = asset.upper()

        sentiment, _sent_stale = self.get_sentiment(asset)
        volatility = self.get_volatility(asset)
        multiplier = self.get_sizing_multiplier(asset)

        is_stale = False
        stale_reason = ""
        if self._asset_lock is not None:
            with self._asset_lock:
                state = self._assets.get(asset)
                if state:
                    is_stale, stale_reason = state.is_stale(self._stale_threshold)
        else:
            # Lock disabled - direct access (startup workaround)
            state = self._assets.get(asset)
            if state:
                is_stale, stale_reason = state.is_stale(self._stale_threshold)
        
        return {
            "asset": asset,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sentiment": sentiment.to_dict() if sentiment else None,
            "volatility": volatility.to_dict() if volatility else None,
            "sizing_multiplier": multiplier.to_dict(),
            "is_stale": is_stale,
            "stale_reason": stale_reason,
            "effective_size_factor": multiplier.value,
            "regime_label": multiplier.get_regime_label(),
        }
    
    # ── Subscription ─────────────────────────────────────────────────────
    
    def subscribe(
        self,
        asset: str,
        callback: Callable[[SentimentScalar, VolatilityScalar], None],
    ) -> None:
        """Subscribe to updates for an asset."""
        asset = asset.upper()
        self.register_asset(asset)
        
        if self._asset_lock is not None:
            with self._asset_lock:
                self._assets[asset].callbacks.append(callback)
        else:
            # Lock disabled - direct access (startup workaround)
            self._assets[asset].callbacks.append(callback)
    
    def unsubscribe(
        self,
        asset: str,
        callback: Callable[[SentimentScalar, VolatilityScalar], None],
    ) -> None:
        """Unsubscribe from updates."""
        asset = asset.upper()
        
        if self._asset_lock is not None:
            with self._asset_lock:
                state = self._assets.get(asset)
                if state and callback in state.callbacks:
                    state.callbacks.remove(callback)
        else:
            # Lock disabled - direct access (startup workaround)
            state = self._assets.get(asset)
            if state and callback in state.callbacks:
                state.callbacks.remove(callback)
    
    def _notify_subscribers(self, asset: str) -> None:
        """Notify subscribers of an update."""
        if self._asset_lock is not None:
            with self._asset_lock:
                state = self._assets.get(asset)
                if not state:
                    return
                
                sentiment = state.current_sentiment
                volatility = state.current_volatility
        else:
            # Lock disabled - direct access (startup workaround)
            state = self._assets.get(asset)
            if not state:
                return
            
            sentiment = state.current_sentiment
            volatility = state.current_volatility
        
        for callback in state.callbacks:
            try:
                callback(sentiment, volatility)
            except Exception:
                pass
    
# ... (rest of the code remains the same)
    # ── Background Updates ───────────────────────────────────────────────
    
    def start(self) -> None:
        """Start background update thread."""
        if self._running:
            return
        
        self._running = True
        self._update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self._update_thread.start()
        logger.info("SentimentVolService background updates started")
    
    def stop(self) -> None:
        """Stop background updates."""
        self._running = False
        if self._update_thread:
            self._update_thread.join(timeout=5.0)
        logger.info("SentimentVolService stopped")
    
    def _update_loop(self) -> None:
        """Background loop for periodic sentiment updates."""
        # Offset start to avoid thundering herd
        time.sleep(10)
        
        while self._running:
            try:
                self._run_update_cycle()
                self._update_count += 1
            except Exception as exc:
                logger.warning(f"Update cycle error: {exc}")
                self._error_count += 1
            
            # Sleep with early wake on stop
            for _ in range(int(self._update_interval)):
                if not self._running:
                    break
                time.sleep(1)
    
    def _run_update_cycle(self) -> None:
        """Run one update cycle - refresh sentiment from sources."""
        if self._asset_lock is not None:
            with self._asset_lock:
                assets = list(self._assets.keys())
        else:
            # Lock disabled - direct access (startup workaround)
            assets = list(self._assets.keys())
        
        for asset in assets:
            try:
                # Update from CFGI (primary source)
                self.update_sentiment_from_cfgi(asset)
            except Exception as exc:
                logger.debug(f"CFGI update failed for {asset}: {exc}")
            
            # Small delay between assets
            time.sleep(0.1)
    
    # ── Health & Metrics ─────────────────────────────────────────────────
    
    def get_health(self) -> Dict[str, Any]:
        """Get service health status."""
        if self._asset_lock is not None:
            with self._asset_lock:
                assets = list(self._assets.keys())
                stale_count = 0
                fresh_count = 0
                
                for asset in assets:
                    state = self._assets[asset]
                    is_stale, _ = state.is_stale(self._stale_threshold)
                    if is_stale:
                        stale_count += 1
                    else:
                        fresh_count += 1
        else:
            # Lock disabled - direct access (startup workaround)
            assets = list(self._assets.keys())
            stale_count = 0
            fresh_count = 0
            
            for asset in assets:
                state = self._assets[asset]
                is_stale, _ = state.is_stale(self._stale_threshold)
                if is_stale:
                    stale_count += 1
                else:
                    fresh_count += 1
        
        return {
            "service": "SentimentVolService",
            "running": self._running,
            "tracked_assets": len(assets),
            "fresh_assets": fresh_count,
            "stale_assets": stale_count,
            "update_count": self._update_count,
            "error_count": self._error_count,
            "error_rate": self._error_count / max(1, self._update_count),
            "config": {
                "update_interval": self._update_interval,
                "stale_threshold": self._stale_threshold,
            },
        }
    
    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """Get composite state for all tracked assets."""
        if self._asset_lock is not None:
            with self._asset_lock:
                assets = list(self._assets.keys())
        else:
            # Lock disabled - direct access (startup workaround)
            assets = list(self._assets.keys())
        
        return {asset: self.get_composite_state(asset) for asset in assets}


# ═══════════════════════════════════════════════════════════════════════════
# Singleton Accessor
# ═══════════════════════════════════════════════════════════════════════════

_service_instance: Optional[SentimentVolService] = None
# TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
# TODO: Re-enable lock after startup is stable and investigate proper async synchronization
# _service_lock = threading.Lock()
_service_lock = None  # Disabled to prevent startup hang


def get_sentiment_vol_service(
    update_interval_seconds: float = 60.0,
) -> SentimentVolService:
    """Get the singleton SentimentVolService instance."""
    global _service_instance
    if _service_instance is None:
        if _service_lock is not None:
            with _service_lock:
                if _service_instance is None:
                    _service_instance = SentimentVolService(
                        update_interval_seconds=update_interval_seconds,
                    )
        else:
            # Lock disabled - direct initialization (startup workaround)
            _service_instance = SentimentVolService(
                update_interval_seconds=update_interval_seconds,
            )
    return _service_instance


# ═══════════════════════════════════════════════════════════════════════════
# Convenience Functions (One-liners for consumers)
# ═══════════════════════════════════════════════════════════════════════════

def get_current_sentiment(asset: str) -> Optional[SentimentScalar]:
    """Quick one-liner to get sentiment (returns value only; ignores staleness)."""
    value, _stale = get_sentiment_vol_service().get_sentiment(asset)
    return value


def get_current_volatility(asset: str) -> Optional[VolatilityScalar]:
    """Quick one-liner to get volatility."""
    return get_sentiment_vol_service().get_volatility(asset)


def get_current_sizing_multiplier(asset: str, is_contrarian: bool = False) -> SizingMultiplier:
    """Quick one-liner to get sizing multiplier."""
    return get_sentiment_vol_service().get_sizing_multiplier(asset, is_contrarian)


def feed_price_update(asset: str, price: float) -> None:
    """Quick one-liner to feed a price update."""
    get_sentiment_vol_service().update_price(asset, price)


def feed_sentiment_update(
    asset: str,
    value: float,
    confidence: float = 1.0,
    source: str = "manual",
) -> None:
    """Quick one-liner to feed a sentiment update."""
    get_sentiment_vol_service().update_sentiment(asset, value, confidence, source)


def should_reduce_position_size(asset: str) -> Tuple[bool, float, str]:
    """
    Check if position size should be reduced for an asset.
    
    Returns:
        (should_reduce, multiplier, reason)
    """
    mult = get_current_sizing_multiplier(asset)
    
    should_reduce = mult.value < 0.9
    reason = mult.reasoning
    
    return should_reduce, mult.value, reason


def explain_sizing_for_position(
    asset: str,
    base_size: float,
    is_contrarian: bool = False,
) -> Dict[str, Any]:
    """
    Get full explanation of sizing calculation for a position.
    
    Useful for UI display and trade logging.
    """
    service = get_sentiment_vol_service()

    sentiment, _sent_stale = service.get_sentiment(asset)
    if _sent_stale and sentiment is not None:
        logger.warning("[sizing] Using stale sentiment data for %s", asset)
    volatility = service.get_volatility(asset)
    multiplier = service.get_sizing_multiplier(asset, is_contrarian)
    
    final_size = multiplier.apply_to_size(base_size)
    
    return {
        "asset": asset,
        "base_size": base_size,
        "final_size": final_size,
        "sizing_multiplier": multiplier.value,
        "regime_label": multiplier.get_regime_label(),
        "sentiment": sentiment.to_dict() if sentiment else None,
        "volatility": volatility.to_dict() if volatility else None,
        "reasoning": multiplier.reasoning,
        "is_contrarian": is_contrarian,
    }
