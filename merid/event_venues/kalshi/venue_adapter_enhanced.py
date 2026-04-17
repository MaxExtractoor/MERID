"""Enhanced Kalshi Venue Adapter with resiliency primitives."""

from __future__ import annotations

import asyncio
import time
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.client_enhanced import EnhancedKalshiClient
from merid.event_venues.kalshi.venue_adapter import (
    KalshiVenueAdapter,
    get_kalshi_venue_adapter,
)
from merid.event_venues.base import VenueOrder, PlacedOrder, VenuePosition
from merid.paper_config import InstrumentConfig, DomainMode
from merid.resilience import CircuitBreaker, retry_async, get_circuit_breaker
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.venue_adapter_enhanced")


class VenueAdapterOperationResult:
    """Result of a venue adapter operation with success/error metadata."""

    def __init__(
        self,
        success: bool = True,
        data: Any = None,
        error: Optional[str] = None,
        latency_ms: float = 0.0,
    ) -> None:
        self.success = success
        self.data = data
        self.error = error
        self.latency_ms = latency_ms

    @classmethod
    def ok(cls, data: Any = None, latency_ms: float = 0.0) -> "VenueAdapterOperationResult":
        return cls(success=True, data=data, latency_ms=latency_ms)

    @classmethod
    def err(cls, error: str, latency_ms: float = 0.0) -> "VenueAdapterOperationResult":
        return cls(success=False, error=error, latency_ms=latency_ms)

    def __bool__(self) -> bool:
        return self.success


class EnhancedKalshiVenueAdapter:
    """Drop-in wrapper around KalshiVenueAdapter with retries and circuit breakers."""

    def __init__(
        self,
        mode: str = "paper",
        client: Optional[KalshiVenueClient] = None,
        cache_ttl: float = 300.0,
        base_adapter: Optional[KalshiVenueAdapter] = None,
    ):
        self._client: Optional[EnhancedKalshiClient] = None
        if client is not None:
            if isinstance(client, EnhancedKalshiClient):
                self._client = client
            else:
                self._client = EnhancedKalshiClient(client)
        elif base_adapter is not None:
            base_client = getattr(base_adapter, "_client", None)
            if isinstance(base_client, EnhancedKalshiClient):
                self._client = base_client
            elif base_client is not None:
                self._client = EnhancedKalshiClient(base_client)

        self.base_adapter = base_adapter or KalshiVenueAdapter(mode=mode, client=client)

        self._circuit_breakers: Dict[str, CircuitBreaker] = {
            "list_instruments": get_circuit_breaker(
                "venue_adapter_list", failure_threshold=8, recovery_timeout=30.0
            ),
            "get_positions": get_circuit_breaker(
                "venue_adapter_positions", failure_threshold=6, recovery_timeout=30.0
            ),
            "submit_order": get_circuit_breaker(
                "venue_adapter_submit", failure_threshold=8, recovery_timeout=30.0
            ),
            "get_orders": get_circuit_breaker(
                "venue_adapter_orders", failure_threshold=6, recovery_timeout=30.0
            ),
            "get_fills": get_circuit_breaker(
                "venue_adapter_fills", failure_threshold=6, recovery_timeout=30.0
            ),
            "risk_snapshot": get_circuit_breaker(
                "venue_adapter_risk", failure_threshold=5, recovery_timeout=60.0
            ),
        }

        # Instruments cache & stats
        self._instruments_cache: Dict[Tuple[str, bool], Dict[str, Any]] = {}
        self._cache_ts: float = 0.0
        self._cache_ttl: float = cache_ttl
        self._cache_hits = 0
        self._cache_misses = 0

        self._health_stats: Dict[str, int] = {
            "total_operations": 0,
            "successful_operations": 0,
            "failed_operations": 0,
            "timeout_operations": 0,
            "circuit_opens": 0,
        }
        self._last_health_check: float = time.time()

        logger.info(
            "EnhancedKalshiVenueAdapter initialized: mode=%s, cache_ttl=%.1fs",
            self.base_adapter.mode.value,
            self._cache_ttl,
        )

    # ------------------------------------------------------------------ #
    # Properties / client handling
    # ------------------------------------------------------------------ #
    @property
    def venue_name(self) -> str:
        return self.base_adapter.venue_name

    @property
    def mode(self) -> DomainMode:
        return self.base_adapter.mode

    @property
    def client(self) -> EnhancedKalshiClient:
        if self._client is None:
            from merid.event_venues.kalshi.models import KalshiConfig

            config = KalshiConfig()
            base_client = KalshiVenueClient(config)
            self._client = EnhancedKalshiClient(base_client)
        return self._client

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _retry_wrapper(max_retries: int = 3):
        def decorator(func: Callable):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                wrapped = retry_async(
                    func,
                    max_retries=max_retries,
                    backoff_base=2.0,
                    retryable_exceptions=(
                        asyncio.TimeoutError,
                        ConnectionError,
                    ),
                )
                return await wrapped(*args, **kwargs)

            return wrapper

        return decorator

    async def _execute_with_circuit_breaker(
        self,
        operation_type: str,
        coro: Callable[..., Any],
        *args,
        **kwargs,
    ) -> Any:
        self._health_stats["total_operations"] += 1
        circuit_breaker = self._circuit_breakers.get(operation_type)
        if circuit_breaker is None:
            return await coro(*args, **kwargs)

        start = time.perf_counter()
        try:
            async with circuit_breaker:
                result = await coro(*args, **kwargs)
            self._health_stats["successful_operations"] += 1
            return result
        except asyncio.TimeoutError:
            self._health_stats["timeout_operations"] += 1
            elapsed = time.perf_counter() - start
            logger.error(
                "EnhancedKalshiVenueAdapter %s timed out after %.2fs",
                operation_type,
                elapsed,
            )
            raise
        except Exception as exc:
            self._health_stats["failed_operations"] += 1
            logger.exception(
                "EnhancedKalshiVenueAdapter %s failed: %s", operation_type, exc
            )
            raise

    def _cache_key(self, category: Optional[str], active_only: bool) -> Tuple[str, bool]:
        return (category or "*", bool(active_only))

    def _is_cache_valid(self, cache_key: Tuple[str, bool]) -> bool:
        entry = self._instruments_cache.get(cache_key)
        if not entry:
            return False
        return (time.time() - entry["ts"]) < self._cache_ttl

    def _update_cache(self, cache_key: Tuple[str, bool], instruments: List[InstrumentConfig]) -> None:
        self._instruments_cache[cache_key] = {"data": instruments, "ts": time.time()}
        self._cache_ts = time.time()
        logger.debug(
            "Updated instruments cache for key %s with %d items",
            cache_key,
            len(instruments),
        )

    # ------------------------------------------------------------------ #
    # Public API mirroring KalshiVenueAdapter
    # ------------------------------------------------------------------ #
    @_retry_wrapper(max_retries=2)
    async def list_instruments(
        self,
        category: Optional[str] = None,
        active_only: bool = True,
        force_refresh: bool = False,
    ) -> List[InstrumentConfig]:
        cache_key = self._cache_key(category, active_only)
        if (not force_refresh) and self._is_cache_valid(cache_key):
            self._cache_hits += 1
            return self._instruments_cache[cache_key]["data"]

        self._cache_misses += 1

        async def _op():
            instruments = await self.base_adapter.list_instruments(
                category=category,
                active_only=active_only,
                force_refresh=force_refresh,
            )
            self._update_cache(cache_key, instruments)
            return instruments

        return await self._execute_with_circuit_breaker("list_instruments", _op)

    @_retry_wrapper(max_retries=2)
    async def get_positions(self) -> List[VenuePosition]:
        async def _op():
            return await self.base_adapter.get_positions()

        return await self._execute_with_circuit_breaker("get_positions", _op)

    @_retry_wrapper(max_retries=2)
    async def get_orders(self, status: Optional[str] = None) -> List[PlacedOrder]:
        async def _op():
            return await self.base_adapter.get_orders(status=status)

        return await self._execute_with_circuit_breaker("get_orders", _op)

    @_retry_wrapper(max_retries=3)
    async def submit_order(self, order: VenueOrder) -> PlacedOrder:
        async def _op():
            return await self.base_adapter.submit_order(order)

        return await self._execute_with_circuit_breaker("submit_order", _op)

    @_retry_wrapper(max_retries=2)
    async def get_fills(self, limit: int = 100):
        async def _op():
            return await self.base_adapter.get_fills(limit)  # type: ignore[attr-defined]

        return await self._execute_with_circuit_breaker("get_fills", _op)

    @_retry_wrapper(max_retries=2)
    async def get_risk_snapshot(self) -> Dict[str, Any]:
        async def _op():
            return await self.base_adapter.get_risk_snapshot()

        return await self._execute_with_circuit_breaker("risk_snapshot", _op)

    # ------------------------------------------------------------------ #
    # Convenience helpers (new API)
    # ------------------------------------------------------------------ #
    async def get_market_by_id(self, instrument_id: str) -> Optional[InstrumentConfig]:
        now = time.time()
        for key, entry in list(self._instruments_cache.items()):
            if (now - entry["ts"]) > self._cache_ttl:
                continue
            for inst in entry["data"]:
                if inst.id == instrument_id:
                    return inst

        instruments = await self.list_instruments(force_refresh=False)
        for inst in instruments:
            if inst.id == instrument_id:
                return inst
        return None

    def get_cache_stats(self) -> Dict[str, Any]:
        total = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total * 100.0) if total > 0 else 0.0
        cache_size = sum(len(entry["data"]) for entry in self._instruments_cache.values())
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "hit_rate": round(hit_rate, 2),
            "cache_size": cache_size,
            "cache_entries": len(self._instruments_cache),
            "cache_age": time.time() - self._cache_ts if self._cache_ts else 0.0,
            "cache_ttl": self._cache_ttl,
        }

    def get_health_stats(self) -> Dict[str, Any]:
        total_ops = self._health_stats["total_operations"]
        success_rate = (
            self._health_stats["successful_operations"] / total_ops * 100.0
            if total_ops > 0
            else 0.0
        )
        circuit_status: Dict[str, Any] = {}
        for op, cb in self._circuit_breakers.items():
            circuit_status[op] = {
                "state": cb.state.value,
                "failure_count": cb.failure_count,
                "last_failure_time": cb.last_failure_time,
            }
        return {
            "stats": dict(self._health_stats),
            "success_rate": round(success_rate, 2),
            "circuit_breakers": circuit_status,
            "cache_stats": self.get_cache_stats(),
            "last_health_check": self._last_health_check,
        }

    async def health_check(self) -> Dict[str, Any]:
        self._last_health_check = time.time()

        connectivity_ok = False
        try:
            balance_result = await self.client.get_balance_result()
            connectivity_ok = bool(getattr(balance_result, "success", True))
        except Exception:
            connectivity_ok = False

        operations_ok = False
        try:
            await self.list_instruments(force_refresh=False)
            operations_ok = True
        except Exception:
            operations_ok = False

        open_circuits = [
            op for op, cb in self._circuit_breakers.items() if cb.state.value == "open"
        ]

        return {
            "healthy": connectivity_ok and operations_ok and not open_circuits,
            "connectivity": connectivity_ok,
            "operations": operations_ok,
            "open_circuits": open_circuits,
            "stats": self.get_health_stats(),
        }

    def reset_circuit_breaker(self, operation_type: str) -> bool:
        cb = self._circuit_breakers.get(operation_type)
        if cb:
            cb.reset()
            logger.info("Reset circuit breaker for %s", operation_type)
            return True
        return False

    def reset_all_circuit_breakers(self) -> None:
        for op, cb in self._circuit_breakers.items():
            cb.reset()
        logger.info("Reset all venue adapter circuit breakers")

    def clear_cache(self) -> None:
        self._instruments_cache.clear()
        self._cache_ts = 0.0
        logger.info("Cleared instrument cache")

    def set_cache_ttl(self, ttl: float) -> None:
        self._cache_ttl = ttl
        logger.info("Set instruments cache TTL to %.2fs", ttl)

    # ------------------------------------------------------------------ #
    # Factory helpers
    # ------------------------------------------------------------------ #


def create_enhanced_adapter(
    mode: str = "paper",
    client: Optional[KalshiVenueClient] = None,
    cache_ttl: float = 300.0,
) -> EnhancedKalshiVenueAdapter:
    return EnhancedKalshiVenueAdapter(mode=mode, client=client, cache_ttl=cache_ttl)


def wrap_adapter(adapter: KalshiVenueAdapter) -> EnhancedKalshiVenueAdapter:
    return EnhancedKalshiVenueAdapter(
        mode=adapter.mode.value,
        client=None,
        cache_ttl=getattr(adapter, "_cache_ttl", 300.0),
        base_adapter=adapter,
    )


_ENHANCED_ADAPTER: Optional[EnhancedKalshiVenueAdapter] = None


def get_enhanced_kalshi_adapter(
    mode: Optional[str] = None,
    cache_ttl: float = 300.0,
) -> EnhancedKalshiVenueAdapter:
    """Get a singleton enhanced adapter wrapping the base adapter."""

    global _ENHANCED_ADAPTER
    if _ENHANCED_ADAPTER is None:
        base = get_kalshi_venue_adapter(mode=mode)
        _ENHANCED_ADAPTER = wrap_adapter(base)
        if cache_ttl != getattr(base, "_cache_ttl", cache_ttl):
            _ENHANCED_ADAPTER.set_cache_ttl(cache_ttl)
    return _ENHANCED_ADAPTER


def reset_enhanced_kalshi_adapter() -> None:
    """Reset singleton for testing."""
    global _ENHANCED_ADAPTER
    _ENHANCED_ADAPTER = None
