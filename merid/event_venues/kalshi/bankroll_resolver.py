"""Bankroll Resolver — Resilient bankroll derivation with retry and fallback.

This module provides robust bankroll/equity derivation with exponential backoff
retry and unified fallback policies, eliminating the divergence between CT
(reject on None) and Grid (fall back to env) behaviors.

Usage::
    from merid.event_venues.kalshi.bankroll_resolver import (
        BankrollResolver,
        FallbackPolicy,
        BankrollResolution,
    )
    
    resolver = BankrollResolver()
    result = await resolver.derive_live_bankroll_with_retry()
    
    if result.source == "live_api":
        print(f"Live bankroll: ${result.equity_usd:.2f}")
    else:
        print(f"Fallback bankroll: ${result.equity_usd:.2f} (source: {result.source})")
"""

from __future__ import annotations

import os
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Callable
from enum import Enum
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.bankroll_resolver")


class FallbackPolicy(Enum):
    """Policy for handling bankroll derivation failure."""
    REJECT = "reject"           # Fail closed - raise exception
    USE_LAST_KNOWN = "last"     # Use cached value with staleness limit
    USE_MINIMUM = "minimum"     # Use minimum viable bankroll
    USE_ENV = "env"             # Fall back to MERID_INITIAL_CAPITAL


@dataclass
class BankrollCacheEntry:
    """Cached bankroll value with timestamp."""
    value: float
    timestamp: datetime
    
    @property
    def age_seconds(self) -> float:
        """Get age of cache entry in seconds."""
        return (datetime.now(timezone.utc) - self.timestamp).total_seconds()


@dataclass
class BankrollResolution:
    """Result of bankroll derivation attempt."""
    equity_usd: float
    """Resolved equity in USD."""
    
    source: str
    """Source of the value ("live_api", "cached", "env_fallback", "minimum")."""
    
    stale_seconds: Optional[float] = None
    """How stale the value is (if from cache)."""
    
    retries_attempted: int = 0
    """Number of retries attempted before resolution."""
    
    last_error: Optional[str] = None
    """Last error encountered (if any)."""


class BankrollDerivationError(Exception):
    """Raised when bankroll derivation fails and policy is REJECT."""
    pass


class BankrollResolver:
    """Resilient bankroll derivation with retry and fallback.
    
    This resolver implements exponential backoff retry for live API calls
    and provides configurable fallback policies for failure scenarios.
    """
    
    _instance: Optional[BankrollResolver] = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay_seconds: float = 1.0,
        fallback_policy: FallbackPolicy = FallbackPolicy.USE_LAST_KNOWN,
        max_staleness_seconds: float = 300.0,
        env_fallback_var: str = "MERID_INITIAL_CAPITAL",
        minimum_viable_bankroll: float = 100.0,
    ):
        if self._initialized:
            return
            
        self.max_retries = max_retries
        self.base_delay_seconds = base_delay_seconds
        self.fallback_policy = fallback_policy
        self.max_staleness_seconds = max_staleness_seconds
        self.env_fallback_var = env_fallback_var
        self.minimum_viable_bankroll = minimum_viable_bankroll
        
        # Cache for last known good value
        self._cache: Optional[BankrollCacheEntry] = None
        self._cache_lock = asyncio.Lock()
        
        # Metrics
        self._success_count = 0
        self._fallback_count = 0
        self._error_count = 0
        
        self._initialized = True
    
    async def derive_live_bankroll_with_retry(
        self,
        force_refresh: bool = False
    ) -> BankrollResolution:
        """Derive live bankroll with exponential backoff retry.
        
        Strategy:
        1. Try live API with exponential backoff (1s, 2s, 4s)
        2. If all retries fail, apply fallback policy
        3. Cache successful results for fallback use
        
        Args:
            force_refresh: Ignore cache and force new API call
            
        Returns:
            BankrollResolution with equity and metadata
            
        Raises:
            BankrollDerivationError: If all retries fail and policy is REJECT
        """
        # Check cache first (unless forced refresh)
        if not force_refresh:
            cached = await self._get_cached_value()
            if cached and cached.age_seconds < self.max_staleness_seconds:
                return BankrollResolution(
                    equity_usd=cached.value,
                    source="cached",
                    stale_seconds=cached.age_seconds,
                    retries_attempted=0
                )
        
        # Attempt live API with retry
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                result = await self._fetch_live_bankroll()
                
                if result is not None and result > 0:
                    # Success - cache and return
                    await self._cache_value(result)
                    self._success_count += 1
                    
                    return BankrollResolution(
                        equity_usd=result,
                        source="live_api",
                        retries_attempted=attempt
                    )
                    
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"Bankroll derivation attempt {attempt + 1}/{self.max_retries} failed: {e}"
                )
                
                if attempt < self.max_retries - 1:
                    # Exponential backoff
                    delay = self.base_delay_seconds * (2 ** attempt)
                    logger.info(f"Retrying in {delay}s...")
                    await asyncio.sleep(delay)
        
        # All retries exhausted
        self._error_count += 1
        logger.error(
            f"All {self.max_retries} bankroll derivation attempts failed. "
            f"Last error: {last_error}"
        )
        
        # Apply fallback policy
        return await self._apply_fallback_policy(last_error)
    
    async def _fetch_live_bankroll(self) -> Optional[float]:
        """Fetch live bankroll from BankrollServiceV2 (single source of truth).
        
        Returns:
            Equity in USD, or None if unavailable
        """
        from merid.event_venues.kalshi.bankroll_service_v2 import (
            get_bankroll_service,
            get_equity_for_risk_calc_sync,
        )
        
        try:
            service = await get_bankroll_service()
            equity = await service.get_equity_for_risk_calc()
            
            if equity is not None and equity > 0:
                logger.debug(f"Bankroll from v2 service: ${float(equity):.2f}")
                return float(equity)
            else:
                logger.warning("BankrollServiceV2 returned None or zero equity")
                return None
        except Exception as e:
            logger.warning(f"Failed to fetch bankroll from v2 service: {e}")
            return None
    
    async def _apply_fallback_policy(
        self,
        last_error: Optional[str]
    ) -> BankrollResolution:
        """Apply fallback policy when all retries fail.
        
        Args:
            last_error: Last error encountered
            
        Returns:
            BankrollResolution from fallback source
            
        Raises:
            BankrollDerivationError: If policy is REJECT
        """
        self._fallback_count += 1
        
        if self.fallback_policy == FallbackPolicy.REJECT:
            raise BankrollDerivationError(
                f"Failed to derive bankroll after {self.max_retries} attempts. "
                f"Last error: {last_error}"
            )
        
        elif self.fallback_policy == FallbackPolicy.USE_LAST_KNOWN:
            cached = await self._get_cached_value()
            
            if cached:
                logger.warning(
                    f"Using stale cached bankroll: ${cached.value:.2f} "
                    f"({cached.age_seconds:.0f}s old)"
                )
                return BankrollResolution(
                    equity_usd=cached.value,
                    source="cached",
                    stale_seconds=cached.age_seconds,
                    retries_attempted=self.max_retries,
                    last_error=last_error
                )
            
            # No cache available, fall through to next policy
            logger.warning("No cached bankroll available, falling back to env")
        
        elif self.fallback_policy == FallbackPolicy.USE_ENV:
            env_value = os.environ.get(self.env_fallback_var)
            
            if env_value:
                try:
                    equity = float(env_value)
                    logger.warning(f"Using env fallback bankroll: ${equity:.2f}")
                    return BankrollResolution(
                        equity_usd=equity,
                        source="env_fallback",
                        retries_attempted=self.max_retries,
                        last_error=last_error
                    )
                except ValueError:
                    logger.error(f"Invalid env value: {env_value}")
        
        # Final fallback: minimum viable
        logger.warning(
            f"Using minimum viable bankroll: ${self.minimum_viable_bankroll:.2f}"
        )
        return BankrollResolution(
            equity_usd=self.minimum_viable_bankroll,
            source="minimum",
            retries_attempted=self.max_retries,
            last_error=last_error
        )
    
    async def _cache_value(self, value: float) -> None:
        """Cache a successful bankroll value."""
        async with self._cache_lock:
            self._cache = BankrollCacheEntry(
                value=value,
                timestamp=datetime.now(timezone.utc)
            )
    
    async def _get_cached_value(self) -> Optional[BankrollCacheEntry]:
        """Get cached bankroll value."""
        async with self._cache_lock:
            return self._cache
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get resolver metrics."""
        return {
            "success_count": self._success_count,
            "fallback_count": self._fallback_count,
            "error_count": self._error_count,
            "success_rate": (
                self._success_count / max(1, self._success_count + self._fallback_count)
            ),
        }
    
    async def invalidate_cache(self) -> None:
        """Invalidate the cached value."""
        async with self._cache_lock:
            self._cache = None


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience function
# ═══════════════════════════════════════════════════════════════════════════════

async def get_live_bankroll(
    force_refresh: bool = False,
    max_retries: int = 3,
    fallback_policy: Optional[FallbackPolicy] = None
) -> float:
    """Get live bankroll with sensible defaults.
    
    This is a convenience function for simple use cases.
    For more control, use BankrollResolver directly.
    
    Args:
        force_refresh: Force new API call
        max_retries: Number of retry attempts
        fallback_policy: Override default fallback policy
        
    Returns:
        Equity in USD
        
    Raises:
        BankrollDerivationError: If derivation fails and policy is REJECT
    """
    resolver = BankrollResolver()
    
    if fallback_policy:
        resolver.fallback_policy = fallback_policy
    
    result = await resolver.derive_live_bankroll_with_retry(force_refresh)
    return result.equity_usd
