"""§4 Arb/Dislocation engine — cross-venue opportunity detection with TTL.

Scans for:
  - Crypto: CEX vs CEX vs DEX/AMM price differences
  - Prediction: Kalshi vs sportsbooks vs spot/macro
  - Sports: book vs book vs prediction market

Each DislocationSignal carries a TTL and min_edge so plans auto-invalidate
when the opportunity decays.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from merid.signals.decay import (
    DecayEnvelope,
    SignalDomain,
    decay_weight_at,
    get_decay_config,
)

from utils.logger import get_logger

logger = get_logger("merid.signals.arbitrage")


# ── Enums ─────────────────────────────────────────────────────────────

class DislocationDomain(str, Enum):
    CRYPTO_CEX = "crypto_cex"
    CRYPTO_DEX = "crypto_dex"
    PREDICTION = "prediction"
    SPORTS = "sports"
    CROSS_DOMAIN = "cross_domain"


class DislocationStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CAPTURED = "captured"
    INVALIDATED = "invalidated"


class ArbType(str, Enum):
    PURE_ARB = "pure_arb"          # near risk-free
    STAT_ARB = "stat_arb"          # statistical edge
    DISLOCATION = "dislocation"    # directional mispricing


# ── VenuePrice — normalized price from any venue ──────────────────────

@dataclass
class VenuePrice:
    """A price/probability observation from a single venue."""
    venue: str = ""
    symbol: str = ""
    bid: float = 0.0
    ask: float = 0.0
    mid: float = 0.0
    timestamp: float = field(default_factory=time.time)
    liquidity_usd: float = 0.0
    fees_bps: float = 0.0
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def spread_bps(self) -> float:
        if self.mid == 0:
            return 0.0
        return (self.ask - self.bid) / self.mid * 10000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "spread_bps": round(self.spread_bps, 1),
            "timestamp": self.timestamp,
            "liquidity_usd": self.liquidity_usd,
            "fees_bps": self.fees_bps,
        }


# ── DislocationSignal — detected mispricing ───────────────────────────

@dataclass
class DislocationSignal:
    """A detected cross-venue mispricing or arbitrage opportunity."""
    signal_id: str = field(default_factory=lambda: f"dis-{uuid.uuid4().hex[:8]}")
    domain: str = DislocationDomain.CRYPTO_CEX.value
    arb_type: str = ArbType.DISLOCATION.value
    symbol: str = ""
    venues: List[VenuePrice] = field(default_factory=list)

    # Edge metrics
    gross_edge_bps: float = 0.0       # raw price difference in bps
    net_edge_bps: float = 0.0         # after fees, spread, slippage estimate
    edge_usd: float = 0.0             # estimated profit in USD for reference size
    reference_size_usd: float = 1000.0

    # Costs
    total_fees_bps: float = 0.0
    spread_cost_bps: float = 0.0
    slippage_est_bps: float = 0.0
    mev_risk_bps: float = 0.0

    # Timing
    detected_at: float = field(default_factory=time.time)
    ttl_seconds: float = 120.0        # opportunity typically collapses in 2 min
    min_edge_bps: float = 10.0        # don't act below this
    status: str = DislocationStatus.ACTIVE.value

    # Decay
    decay_weight: float = 1.0

    def is_expired(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        return (now - self.detected_at) > self.ttl_seconds

    def is_actionable(self, now: Optional[float] = None) -> bool:
        if self.is_expired(now):
            return False
        if self.status != DislocationStatus.ACTIVE.value:
            return False
        return self.net_edge_bps >= self.min_edge_bps

    def current_decay(self, now: Optional[float] = None) -> float:
        return decay_weight_at(self.detected_at, SignalDomain.ARB.value, now)

    def to_dict(self) -> Dict[str, Any]:
        now = time.time()
        return {
            "signal_id": self.signal_id,
            "domain": self.domain,
            "arb_type": self.arb_type,
            "symbol": self.symbol,
            "venues": [v.to_dict() for v in self.venues],
            "gross_edge_bps": round(self.gross_edge_bps, 1),
            "net_edge_bps": round(self.net_edge_bps, 1),
            "edge_usd": round(self.edge_usd, 2),
            "total_fees_bps": round(self.total_fees_bps, 1),
            "ttl_seconds": self.ttl_seconds,
            "age_seconds": round(now - self.detected_at, 1),
            "is_actionable": self.is_actionable(now),
            "decay_weight": round(self.current_decay(now), 4),
            "status": self.status,
        }


# ── ArbPlan / DislocationPlan ─────────────────────────────────────────

@dataclass
class ArbLeg:
    """One leg of an arb/dislocation trade."""
    venue: str = ""
    symbol: str = ""
    side: str = "buy"           # buy or sell
    size_usd: float = 0.0
    limit_price: float = 0.0
    max_slippage_bps: float = 50.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue, "symbol": self.symbol, "side": self.side,
            "size_usd": self.size_usd, "limit_price": self.limit_price,
            "max_slippage_bps": self.max_slippage_bps,
        }


@dataclass
class ArbPlan:
    """A multi-leg arb/dislocation trade plan with TTL and auto-invalidation."""
    plan_id: str = field(default_factory=lambda: f"arb-{uuid.uuid4().hex[:8]}")
    signal_id: str = ""               # the DislocationSignal that triggered this
    domain: str = DislocationDomain.CRYPTO_CEX.value
    arb_type: str = ArbType.DISLOCATION.value
    symbol: str = ""

    legs: List[ArbLeg] = field(default_factory=list)
    total_size_usd: float = 0.0
    expected_edge_bps: float = 0.0
    expected_profit_usd: float = 0.0

    # TTL / validity
    created_at: float = field(default_factory=time.time)
    ttl_seconds: float = 120.0
    min_required_edge_bps: float = 10.0
    status: str = "proposed"          # proposed, approved, executing, filled, expired, cancelled

    def is_valid(self, current_edge_bps: float = 0.0, now: Optional[float] = None) -> bool:
        """Check if plan is still valid (within TTL and edge threshold)."""
        now = now or time.time()
        if (now - self.created_at) > self.ttl_seconds:
            return False
        if self.status not in ("proposed", "approved"):
            return False
        if current_edge_bps < self.min_required_edge_bps:
            return False
        return True

    def expire(self):
        self.status = "expired"

    def to_dict(self) -> Dict[str, Any]:
        now = time.time()
        return {
            "plan_id": self.plan_id,
            "signal_id": self.signal_id,
            "domain": self.domain,
            "arb_type": self.arb_type,
            "symbol": self.symbol,
            "legs": [l.to_dict() for l in self.legs],
            "total_size_usd": self.total_size_usd,
            "expected_edge_bps": round(self.expected_edge_bps, 1),
            "expected_profit_usd": round(self.expected_profit_usd, 2),
            "ttl_seconds": self.ttl_seconds,
            "age_seconds": round(now - self.created_at, 1),
            "is_valid": self.is_valid(self.expected_edge_bps, now),
            "status": self.status,
        }


# ── DislocationScanner — the engine ──────────────────────────────────

class DislocationScanner:
    """Scans for cross-venue arbitrage and pricing dislocations.

    Continuously ingests VenuePrices, detects opportunities, and
    generates DislocationSignals with TTLs.
    """

    def __init__(
        self,
        min_gross_edge_bps: float = 20.0,
        default_ttl: float = 120.0,
    ):
        self.min_gross_edge_bps = min_gross_edge_bps
        self.default_ttl = default_ttl
        self._prices: Dict[str, Dict[str, VenuePrice]] = {}  # symbol → {venue → VenuePrice}
        self._signals: List[DislocationSignal] = []
        self._plans: List[ArbPlan] = []

    def ingest_price(self, price: VenuePrice):
        """Ingest a venue price observation."""
        self._prices.setdefault(price.symbol, {})[price.venue] = price

    def ingest_batch(self, prices: List[VenuePrice]):
        for p in prices:
            self.ingest_price(p)

    def scan(self, now: Optional[float] = None) -> List[DislocationSignal]:
        """Scan all symbols for cross-venue dislocations."""
        now = now or time.time()
        new_signals = []

        for symbol, venues in self._prices.items():
            if len(venues) < 2:
                continue
            venue_list = list(venues.values())
            # Find all pairwise dislocations
            for i in range(len(venue_list)):
                for j in range(i + 1, len(venue_list)):
                    signal = self._check_pair(venue_list[i], venue_list[j], now)
                    if signal:
                        new_signals.append(signal)
                        self._signals.append(signal)

        # Expire old signals
        self._expire_signals(now)
        return new_signals

    def _check_pair(self, a: VenuePrice, b: VenuePrice, now: float) -> Optional[DislocationSignal]:
        """Check two venue prices for a dislocation opportunity."""
        if a.mid == 0 or b.mid == 0:
            return None

        # Check staleness
        max_age = 300  # 5 min max for price to be valid
        if now - a.timestamp > max_age or now - b.timestamp > max_age:
            return None

        # Determine which side to buy and sell
        if a.ask < b.bid:
            buy_venue, sell_venue = a, b
            gross_edge = (b.bid - a.ask) / a.ask * 10000  # in bps
        elif b.ask < a.bid:
            buy_venue, sell_venue = b, a
            gross_edge = (a.bid - b.ask) / b.ask * 10000
        else:
            # No pure arb, check dislocation
            diff_bps = abs(a.mid - b.mid) / min(a.mid, b.mid) * 10000
            if diff_bps < self.min_gross_edge_bps:
                return None
            # Build dislocation signal
            buy_venue = a if a.mid < b.mid else b
            sell_venue = b if a.mid < b.mid else a
            gross_edge = diff_bps
            arb_type = ArbType.DISLOCATION.value
            # Fall through to build signal
            total_fees = buy_venue.fees_bps + sell_venue.fees_bps
            spread_cost = buy_venue.spread_bps / 2 + sell_venue.spread_bps / 2
            net_edge = gross_edge - total_fees - spread_cost
            ref_size = min(buy_venue.liquidity_usd, sell_venue.liquidity_usd, 10000)
            edge_usd = ref_size * net_edge / 10000

            return DislocationSignal(
                domain=self._infer_domain(buy_venue.symbol),
                arb_type=arb_type,
                symbol=buy_venue.symbol,
                venues=[buy_venue, sell_venue],
                gross_edge_bps=gross_edge,
                net_edge_bps=net_edge,
                edge_usd=edge_usd,
                reference_size_usd=ref_size,
                total_fees_bps=total_fees,
                spread_cost_bps=spread_cost,
                detected_at=now,
                ttl_seconds=self.default_ttl,
            )

        # Pure arb path
        if gross_edge < self.min_gross_edge_bps:
            return None

        total_fees = buy_venue.fees_bps + sell_venue.fees_bps
        spread_cost = buy_venue.spread_bps / 2 + sell_venue.spread_bps / 2
        net_edge = gross_edge - total_fees - spread_cost
        ref_size = min(buy_venue.liquidity_usd, sell_venue.liquidity_usd, 10000)
        edge_usd = ref_size * net_edge / 10000

        return DislocationSignal(
            domain=self._infer_domain(buy_venue.symbol),
            arb_type=ArbType.PURE_ARB.value,
            symbol=buy_venue.symbol,
            venues=[buy_venue, sell_venue],
            gross_edge_bps=gross_edge,
            net_edge_bps=net_edge,
            edge_usd=edge_usd,
            reference_size_usd=ref_size,
            total_fees_bps=total_fees,
            spread_cost_bps=spread_cost,
            detected_at=now,
            ttl_seconds=self.default_ttl,
        )

    def _infer_domain(self, symbol: str) -> str:
        s = symbol.upper()
        crypto = {"BTC", "ETH", "SOL", "AVAX", "LINK", "DOGE", "ADA", "DOT", "MATIC"}
        if any(c in s for c in crypto):
            return DislocationDomain.CRYPTO_CEX.value
        if "KALSHI" in s or "POLYMARKET" in s:
            return DislocationDomain.PREDICTION.value
        return DislocationDomain.CROSS_DOMAIN.value

    _MAX_SIGNALS = 500
    _MAX_PLANS = 200

    def _expire_signals(self, now: float):
        for sig in self._signals:
            if sig.status == DislocationStatus.ACTIVE.value and sig.is_expired(now):
                sig.status = DislocationStatus.EXPIRED.value
        # Prune: drop expired signals older than 10 min to bound list size
        cutoff = now - 600
        self._signals = [
            s for s in self._signals
            if s.status == DislocationStatus.ACTIVE.value or s.detected_at > cutoff
        ][-self._MAX_SIGNALS:]
        self._plans = [
            p for p in self._plans
            if p.status in ("proposed", "approved") or (now - p.created_at) < 600
        ][-self._MAX_PLANS:]

    def build_arb_plan(self, signal: DislocationSignal, size_usd: float = 1000.0) -> Optional[ArbPlan]:
        """Build an ArbPlan from a DislocationSignal."""
        if not signal.is_actionable():
            return None
        if len(signal.venues) < 2:
            return None

        buy_v = signal.venues[0]
        sell_v = signal.venues[1]

        legs = [
            ArbLeg(
                venue=buy_v.venue, symbol=buy_v.symbol, side="buy",
                size_usd=size_usd, limit_price=buy_v.ask,
                max_slippage_bps=50.0,
            ),
            ArbLeg(
                venue=sell_v.venue, symbol=sell_v.symbol, side="sell",
                size_usd=size_usd, limit_price=sell_v.bid,
                max_slippage_bps=50.0,
            ),
        ]

        plan = ArbPlan(
            signal_id=signal.signal_id,
            domain=signal.domain,
            arb_type=signal.arb_type,
            symbol=signal.symbol,
            legs=legs,
            total_size_usd=size_usd,
            expected_edge_bps=signal.net_edge_bps,
            expected_profit_usd=size_usd * signal.net_edge_bps / 10000,
            ttl_seconds=signal.ttl_seconds,
            min_required_edge_bps=signal.min_edge_bps,
        )
        self._plans.append(plan)
        return plan

    def get_active_signals(self, now: Optional[float] = None) -> List[DislocationSignal]:
        now = now or time.time()
        return [s for s in self._signals if s.is_actionable(now)]

    def get_all_signals(self, limit: int = 100) -> List[DislocationSignal]:
        return self._signals[-limit:]

    def get_plans(self, status: Optional[str] = None, limit: int = 50) -> List[ArbPlan]:
        plans = self._plans
        if status:
            plans = [p for p in plans if p.status == status]
        return plans[-limit:]

    def validate_plans(self, now: Optional[float] = None):
        """Expire plans whose TTL has passed or edge has decayed."""
        now = now or time.time()
        for plan in self._plans:
            if plan.status in ("proposed", "approved"):
                if not plan.is_valid(plan.expected_edge_bps, now):
                    plan.expire()

    def get_metrics(self) -> Dict[str, Any]:
        now = time.time()
        active = [s for s in self._signals if s.is_actionable(now)]
        expired = [s for s in self._signals if s.status == DislocationStatus.EXPIRED.value]
        return {
            "total_signals": len(self._signals),
            "active_signals": len(active),
            "expired_signals": len(expired),
            "total_plans": len(self._plans),
            "active_plans": sum(1 for p in self._plans if p.status in ("proposed", "approved")),
            "symbols_tracked": len(self._prices),
            "venues_per_symbol": {
                sym: len(venues) for sym, venues in self._prices.items()
            },
        }

    def synthetic_scan(self, now: Optional[float] = None) -> List[DislocationSignal]:
        """Generate synthetic dislocation signals for development."""
        import random
        now = now or time.time()
        rng = random.Random(int(now / 60))

        symbols = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        venues_map = {
            "BTC": [("binance", 43250), ("coinbase", 43280), ("kraken", 43260)],
            "ETH": [("binance", 2650), ("coinbase", 2655), ("uniswap", 2645)],
            "SOL": [("binance", 105.5), ("coinbase", 105.8), ("jupiter", 105.3)],
            "XRP": [("binance", 0.62), ("coinbase", 0.621), ("kraken", 0.619)],
            "DOGE": [("binance", 0.105), ("coinbase", 0.1055), ("kraken", 0.1048)],
        }

        signals = []
        for sym in symbols:
            venues = venues_map.get(sym, [])
            for venue, base in venues:
                spread_pct = rng.uniform(0.01, 0.1)
                mid = base * (1 + rng.uniform(-0.005, 0.005))
                self.ingest_price(VenuePrice(
                    venue=venue, symbol=sym,
                    bid=mid * (1 - spread_pct / 200),
                    ask=mid * (1 + spread_pct / 200),
                    mid=mid,
                    timestamp=now - rng.uniform(0, 30),
                    liquidity_usd=rng.uniform(50000, 500000),
                    fees_bps=rng.uniform(5, 30),
                ))

        signals = self.scan(now)
        return signals


# ── Singleton ─────────────────────────────────────────────────────────

_scanner: Optional[DislocationScanner] = None
_scanner_lock = threading.Lock()


def get_dislocation_scanner() -> DislocationScanner:
    global _scanner
    if _scanner is None:
        with _scanner_lock:
            if _scanner is None:
                _scanner = DislocationScanner()
    return _scanner
