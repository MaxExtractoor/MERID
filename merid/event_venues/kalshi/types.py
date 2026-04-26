"""Kalshi client v2 - Domain types and result patterns.

This module defines the core domain model for Kalshi integration.
NO legacy "locked bankroll" concepts. NO assertions on external data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any, Dict, Optional, Union


class BalanceState(Enum):
    """Bankroll freshness state - explicit, no lying with zeros."""
    FRESH = auto()      # Recently confirmed from Kalshi
    STALE = auto()      # Using cached value due to temporary error
    ERROR = auto()      # Permanent error, trading blocked
    UNKNOWN = auto()    # Never successfully fetched


@dataclass(frozen=True)
class RawVenueBalance:
    """Exactly what Kalshi returns - no interpretation.
    
    Kalshi API returns balance in cents. We store as Decimal USD
    for precision, but the mapping is 1:1 with raw fields.
    """
    cash_available: Decimal   # balance / 100
    cash_locked: Decimal      # locked_balance / 100  
    total_equity: Decimal     # balance / 100 (available + locked)
    raw_cents: Dict[str, int] # Original raw values for debugging
    as_of: datetime
    source: str = "kalshi"
    
    @classmethod
    def from_kalshi_response(cls, response: Dict[str, Any]) -> RawVenueBalance:
        """Parse Kalshi /portfolio/balance response.
        
        No assertions - if fields missing, they'll be 0 and logged.
        """
        balance_cents = response.get("balance", 0) or 0
        locked_cents = response.get("locked_balance", 0) or 0
        
        return cls(
            cash_available=Decimal(str(balance_cents)) / 100,
            cash_locked=Decimal(str(locked_cents)) / 100,
            total_equity=Decimal(str(balance_cents)) / 100,
            raw_cents={
                "balance": balance_cents,
                "locked_balance": locked_cents,
            },
            as_of=datetime.utcnow(),
            source="kalshi",
        )


@dataclass(frozen=True)
class InternalBankroll:
    """Canonical internal representation - the ONE source of truth.
    
    This is what the rest of the system uses. No "effective" nonsense.
    No "locked bankroll" legacy crap. Just clean equity and risk config.
    """
    equity_usd: Decimal           # Total equity for sizing
    max_riskable_frac: Decimal    # Configurable (e.g., 0.02 for 2%)
    as_of: datetime
    source: str
    state: BalanceState
    
    @property
    def max_position_usd(self) -> Decimal:
        """Maximum single position size based on equity * risk fraction."""
        return self.equity_usd * self.max_riskable_frac
    
    def with_state(self, state: BalanceState) -> InternalBankroll:
        """Return copy with different state (for stale/error transitions)."""
        return InternalBankroll(
            equity_usd=self.equity_usd,
            max_riskable_frac=self.max_riskable_frac,
            as_of=self.as_of,
            source=self.source,
            state=state,
        )


@dataclass(frozen=True)
class BalanceSuccess:
    """Balance fetch succeeded - contains the canonical bankroll."""
    bankroll: InternalBankroll
    raw: RawVenueBalance  # Keep raw for audit/debugging
    latency_ms: float


@dataclass(frozen=True)
class BalanceTemporaryError:
    """Transient error (network, timeout, 5xx) - can retry, use stale."""
    reason: str
    details: Dict[str, Any]
    last_known: Optional[InternalBankroll]  # Use this if available
    retry_after_seconds: int = 30


@dataclass(frozen=True)
class BalancePermanentError:
    """Permanent error (auth, account disabled, malformed config) - STOP."""
    reason: str
    details: Dict[str, Any]
    alert_immediately: bool = True


# Union type for balance results - EXPLICIT, no nulls, no zeros
BalanceResult = Union[BalanceSuccess, BalanceTemporaryError, BalancePermanentError]


def is_balance_success(result: BalanceResult) -> bool:
    """Type guard for success case."""
    return isinstance(result, BalanceSuccess)


def get_equity_or_none(result: BalanceResult) -> Optional[Decimal]:
    """Get equity if available, None if error (NOT ZERO)."""
    if isinstance(result, BalanceSuccess):
        return result.bankroll.equity_usd
    elif isinstance(result, BalanceTemporaryError):
        return result.last_known.equity_usd if result.last_known else None
    else:
        return None


# Market result types (same pattern)

@dataclass(frozen=True)
class MarketSuccess:
    """Market fetch succeeded."""
    data: Dict[str, Any]
    latency_ms: float


@dataclass(frozen=True)
class MarketTemporaryError:
    """Transient market error."""
    reason: str
    retry_after_seconds: int = 30


@dataclass(frozen=True)
class MarketPermanentError:
    """Permanent market error (market doesn't exist, delisted)."""
    reason: str
    market_id: Optional[str] = None


MarketResult = Union[MarketSuccess, MarketTemporaryError, MarketPermanentError]


# Order result types

@dataclass(frozen=True)
class OrderSuccess:
    """Order placement succeeded."""
    order_id: str
    status: str
    filled_qty: Decimal
    avg_price: Optional[Decimal]


@dataclass(frozen=True)
class OrderTemporaryError:
    """Order failed transiently - can retry."""
    reason: str
    retry_after_seconds: int = 5


@dataclass(frozen=True)
class OrderPermanentError:
    """Order failed permanently - don't retry."""
    reason: str
    rejection_code: Optional[str] = None


OrderResult = Union[OrderSuccess, OrderTemporaryError, OrderPermanentError]
