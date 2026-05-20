"""Pydantic models for multi-exchange spot price subsystem.

Provides structured models for:
- ExchangeTick: Normalized tick from a single exchange
- CompositeSpot: Aggregated spot price across exchanges (VWAP/median)
- CfbRtiObservation: CF Benchmarks Real-Time Index observation
- SpotAlignment: Alignment snapshot between MERID_SPOT and CF Benchmarks RTI
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ExchangeName(str, Enum):
    """CF Benchmarks Constituent Exchanges and Fallback Sources."""
    COINBASE = "coinbase"
    KRAKEN = "kraken"
    BITSTAMP = "bitstamp"
    ITBIT = "itbit"
    GEMINI = "gemini"
    BULLISH = "bullish"
    BINANCE = "binance"
    BYBIT = "bybit"
    OKX = "okx"
    BINANCEUS = "binanceus"  # BinanceUS public API (fallback spot source)


class Asset(str, Enum):
    """Crypto assets traded on Kalshi 15m markets."""
    BTC = "BTC"
    ETH = "ETH"
    SOL = "SOL"
    XRP = "XRP"
    DOGE = "DOGE"


class CompositeHealth(str, Enum):
    """Health status of composite spot price."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    INSUFFICIENT_DATA = "insufficient_data"


class AlignmentHealth(str, Enum):
    """Health status of spot vs RTI alignment."""
    ALIGNED = "aligned"
    MILD_DRIFT = "mild_drift"
    SEVERE_DRIFT = "severe_drift"
    NO_RTI = "no_rti"
    NO_SPOT = "no_spot"


class ExchangeTick(BaseModel):
    """Normalized tick data from a single exchange.
    
    All prices in USD, timestamps in UTC.
    """
    exchange: ExchangeName
    asset: Asset
    base: str = Field(default="USD", description="Quote currency (always USD for MERID)")
    bid: Optional[float] = Field(default=None, description="Best bid price")
    ask: Optional[float] = Field(default=None, description="Best ask price")
    last: Optional[float] = Field(default=None, description="Last trade price")
    volume_24h: Optional[float] = Field(default=None, description="24h trading volume in USD")
    ts_exchange: datetime = Field(description="Timestamp from exchange")
    ts_received: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp when MERID received the tick")
    
    @property
    def mid(self) -> Optional[float]:
        """Mid price = (bid + ask) / 2 if both available."""
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2.0
        return self.last
    
    def is_fresh(self, max_age_seconds: float = 10.0) -> bool:
        """Check if tick is fresh (age < max_age_seconds)."""
        age = (datetime.now(timezone.utc) - self.ts_received).total_seconds()
        return age < max_age_seconds


class CompositeSpot(BaseModel):
    """Canonical MERID spot price aggregated from multiple exchanges.
    
    Uses either volume-weighted average (VWAP) or median mid price across
    healthy exchanges with fresh data.
    """
    asset: Asset
    price: Optional[float] = Field(default=None, description="Canonical MERID spot mid price")
    method: str = Field(description="Method used: 'vwap' or 'median'")
    contributing_exchanges: List[str] = Field(default_factory=list, description="List of exchanges that contributed")
    per_exchange_mids: Dict[str, float] = Field(default_factory=dict, description="Mid price per exchange")
    per_exchange_weights: Dict[str, float] = Field(default_factory=dict, description="Weight per exchange (for VWAP)")
    health: CompositeHealth = Field(default=CompositeHealth.INSUFFICIENT_DATA, description="Health status")
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp of composite calculation")
    
    @property
    def is_healthy(self) -> bool:
        """Check if composite is healthy (can be used for trading)."""
        return self.health == CompositeHealth.HEALTHY and self.price is not None


class CfbRtiObservation(BaseModel):
    """CF Benchmarks Real-Time Index observation.
    
    CF Benchmarks provides reference indices used by Kalshi for settlement.
    RTI publishes per-second for major crypto assets.
    """
    asset: Asset
    price: float = Field(description="CFB RTI price in USD")
    ts: datetime = Field(description="Timestamp from CF Benchmarks")
    ts_received: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp when MERID received the RTI")
    def is_fresh(self, max_age_seconds: float = 5.0) -> bool:
        """Check if RTI is fresh (age < max_age_seconds)."""
        age = (datetime.now(timezone.utc) - self.ts_received).total_seconds()
        return age < max_age_seconds


class SpotAlignment(BaseModel):
    """Alignment snapshot between MERID_SPOT and CF Benchmarks RTI.
    
    Computes basis (MERID_SPOT - CFB_RTI) and classifies alignment health.
    Used for monitoring and risk gating.
    """
    asset: Asset
    merid_spot: Optional[float] = Field(default=None, description="MERID composite spot price")
    cfb_rti: Optional[float] = Field(default=None, description="CF Benchmarks RTI price")
    basis_abs: Optional[float] = Field(default=None, description="Absolute basis: merid_spot - cfb_rti (USD)")
    basis_bps: Optional[float] = Field(default=None, description="Basis in basis points: (basis_abs / cfb_rti) * 10000")
    health: AlignmentHealth = Field(default=AlignmentHealth.NO_SPOT, description="Alignment health status")
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp of alignment calculation")
    
    @classmethod
    def from_composite_and_rti(
        cls,
        asset: Asset,
        composite: CompositeSpot,
        rti: Optional[CfbRtiObservation],
        threshold1_bps: float = 5.0,
        threshold2_bps: float = 20.0,
    ) -> "SpotAlignment":
        """Create SpotAlignment from CompositeSpot and CfbRtiObservation.
        
        Args:
            asset: Crypto asset
            composite: MERID composite spot
            rti: CF Benchmarks RTI observation (optional)
            threshold1_bps: Basis threshold for ALIGNED -> MILD_DRIFT (default 5 bps = 0.05%)
            threshold2_bps: Basis threshold for MILD_DRIFT -> SEVERE_DRIFT (default 20 bps = 0.2%)
        
        Returns:
            SpotAlignment instance
        """
        if composite.price is None:
            return cls(asset=asset, health=AlignmentHealth.NO_SPOT)
        
        if rti is None or rti.price is None:
            return cls(asset=asset, merid_spot=composite.price, health=AlignmentHealth.NO_RTI)
        
        basis_abs = composite.price - rti.price
        basis_bps = (basis_abs / rti.price) * 10000.0 if rti.price > 0 else None
        
        # Classify health based on basis magnitude
        if basis_bps is None:
            health = AlignmentHealth.NO_RTI
        elif abs(basis_bps) <= threshold1_bps:
            health = AlignmentHealth.ALIGNED
        elif abs(basis_bps) <= threshold2_bps:
            health = AlignmentHealth.MILD_DRIFT
        else:
            health = AlignmentHealth.SEVERE_DRIFT
        
        return cls(
            asset=asset,
            merid_spot=composite.price,
            cfb_rti=rti.price,
            basis_abs=basis_abs,
            basis_bps=basis_bps,
            health=health,
        )
