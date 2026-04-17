"""Unified trading adapter interfaces for the MERID trading suite."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Sequence

import httpx

from utils.logger import get_logger
from trading.trade_mode import get_trade_mode, TradeMode

logger = get_logger("trading.adapters.base")


class TradeSide(str, Enum):
    """Supported trade directions."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Supported order types for adapters."""

    MARKET = "market"
    LIMIT = "limit"
    IOC = "ioc"
    FOK = "fok"


@dataclass(frozen=True)
class TradeRequest:
    """Normalized parameters passed to adapters."""

    venue: str
    symbol: str
    side: TradeSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    notional_usd: Optional[float] = None
    client_reference: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    live: bool = False


@dataclass(frozen=True)
class OrderResult:
    """Adapter execution response."""

    venue: str
    symbol: str
    side: TradeSide
    quantity: float
    executed_price: float
    status: str
    venue_order_id: Optional[str] = None
    transaction_hash: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BalanceSnapshot:
    """Adapter balance record."""

    asset: str
    total: float
    available: float
    usd_value: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PositionSnapshot:
    """Adapter position record."""

    symbol: str
    quantity: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VenueHealth:
    """Adapter health and availability status."""

    venue: str
    status: str
    last_updated: float
    latency_ms: Optional[float] = None
    last_error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class TradingVenueAdapter(Protocol):
    """Protocol implemented by all trading adapters."""

    venue: str
    supported_assets: Sequence[str]
    supports_trading: bool

    def get_health(self) -> VenueHealth:
        ...

    def get_balances(self) -> List[BalanceSnapshot]:
        ...

    def get_positions(self) -> List[PositionSnapshot]:
        ...

    def submit_order(self, request: TradeRequest) -> OrderResult:
        ...

    def cancel_order(self, venue_order_id: str) -> bool:
        ...


class TradingVenueAdapterBase(TradingVenueAdapter):
    """Reusable base adapter with HTTP plumbing + deterministic fallbacks."""

    venue: str = "venue"
    supported_assets: Sequence[str] = ()
    supports_trading: bool = False

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 10.0,
        use_mock: Optional[bool] = None,
    ) -> None:
        env_prefix = f"MERID_{self.venue.upper()}"
        self.api_key = api_key or os.getenv(f"{env_prefix}_API_KEY")
        self.api_secret = api_secret or os.getenv(f"{env_prefix}_API_SECRET")
        self.base_url = base_url or os.getenv(f"{env_prefix}_BASE_URL")
        self.use_mock = bool(use_mock) if use_mock is not None else not bool(self.api_key)
        self._client = httpx.Client(timeout=timeout) if not self.use_mock else None
        self._last_error: Optional[str] = None
        self._last_latency_ms: Optional[float] = None

    # ------------------------------------------------------------------ #
    # Public helpers
    # ------------------------------------------------------------------ #
    def get_health(self) -> VenueHealth:
        status = "offline" if self.use_mock else "online"
        if self._last_error:
            status = "degraded"
        return VenueHealth(
            venue=self.venue,
            status=status,
            last_updated=time.time(),
            latency_ms=self._last_latency_ms,
            last_error=self._last_error,
            metadata={"supports_trading": self.supports_trading},
        )

    def get_balances(self) -> List[BalanceSnapshot]:
        if self.use_mock:
            logger.debug("%s balances unavailable - mock mode", self.venue)
            return []
        return self._get_balances_live()

    def get_positions(self) -> List[PositionSnapshot]:
        if self.use_mock:
            logger.debug("%s positions unavailable - mock mode", self.venue)
            return []
        return self._get_positions_live()

    def submit_order(self, request: TradeRequest) -> OrderResult:
        # ---- Hard mode guard: canonical TradeMode check ----
        current_mode = get_trade_mode()
        if current_mode != TradeMode.LIVE:
            raise RuntimeError(
                f"{self.venue} live order blocked: global trade mode is "
                f"{current_mode.value!r}, not 'live'. "
                f"Use the paper engine for simulated fills."
            )
        if self.use_mock:
            raise RuntimeError(f"{self.venue} adapter in mock mode - trading disabled")
        if not self.supports_trading:
            raise RuntimeError(f"{self.venue} adapter is read-only")
        start = time.perf_counter()
        try:
            result = self._submit_order_live(request)
            self._record_latency(start)
            return result
        except Exception as exc:  # pragma: no cover - adapters override
            self._last_error = str(exc)
            logger.error("%s order failed: %s", self.venue, exc)
            raise

    def cancel_order(self, venue_order_id: str) -> bool:
        if self.use_mock:
            logger.debug("%s cancel skipped - mock mode", self.venue)
            return False
        start = time.perf_counter()
        try:
            result = self._cancel_order_live(venue_order_id)
            self._record_latency(start)
            return result
        except Exception as exc:  # pragma: no cover - adapters override
            self._last_error = str(exc)
            logger.error("%s cancel failed: %s", self.venue, exc)
            raise

    # ------------------------------------------------------------------ #
    # Hooks for subclasses
    # ------------------------------------------------------------------ #
    def _get_balances_live(self) -> List[BalanceSnapshot]:
        return []

    def _get_positions_live(self) -> List[PositionSnapshot]:
        return []

    def _submit_order_live(self, request: TradeRequest) -> OrderResult:
        raise NotImplementedError

    def _cancel_order_live(self, venue_order_id: str) -> bool:
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _record_latency(self, start: float) -> None:
        self._last_latency_ms = (time.perf_counter() - start) * 1000.0
        self._last_error = None


__all__ = [
    "TradeSide",
    "OrderType",
    "TradeRequest",
    "OrderResult",
    "BalanceSnapshot",
    "PositionSnapshot",
    "VenueHealth",
    "TradingVenueAdapter",
    "TradingVenueAdapterBase",
]
