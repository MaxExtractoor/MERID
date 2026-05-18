"""§4 Arb/Dislocation engine — cross-venue opportunity detection with TTL.

Scans for:
  - Crypto: CEX vs CEX vs DEX/AMM price differences
  - Prediction: Kalshi vs sportsbooks vs spot/macro
  - Sports: book vs book vs prediction market

Each DislocationSignal carries a TTL and min_edge so plans auto-invalidate
when the opportunity decays.
"""

from __future__ import annotations

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

    def _expire_signals(self, now: float):
        for sig in self._signals:
            if sig.status == DislocationStatus.ACTIVE.value and sig.is_expired(now):
                sig.status = DislocationStatus.EXPIRED.value

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

        symbols = ["BTC", "ETH", "SOL"]
        venues_map = {
            "BTC": [("binance", 43250), ("coinbase", 43280), ("kraken", 43260)],
            "ETH": [("binance", 2650), ("coinbase", 2655), ("uniswap", 2645)],
            "SOL": [("binance", 105.5), ("coinbase", 105.8), ("jupiter", 105.3)],
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


def get_dislocation_scanner() -> DislocationScanner:
    global _scanner
    if _scanner is None:
        _scanner = DislocationScanner()
    return _scanner


# ── Pyth-Kalshi Arbitrage Scanner ────────────────────────────────────

class PythKalshiArbScanner:
    """
    Cross-venue arbitrage scanner for Kalshi prediction markets vs Pyth onchain feeds.

    Detects probability discrepancies between:
    - Kalshi binary markets (implied probability from orderbook mid)
    - Pyth Network onchain prediction feeds (probability distributions)

    Use case: Energy markets (ERCOT zero-carbon share), crypto price predictions.
    High-value opportunities when Kalshi and onchain markets disagree.
    """

    # Mapping: Kalshi event ticker patterns → Pyth feed categories
    KALSHI_TO_PYTH_MAPPING = {
        r"KXBTC.*": "BTC/USD",
        r"KXETH.*": "ETH/USD",
        r"KXSOL.*": "SOL/USD",
        r"KXXRP.*": "XRP/USD",
        # Energy markets - placeholder for future Pyth energy feeds
        r"KXERCOT.*": "ERCOT/CARBON",  # When Pyth adds energy feeds
        r"KXOIL.*": "OIL/WTI",
        r"KXGAS.*": "GAS/NATGAS",
    }

    def __init__(
        self,
        min_edge_threshold: float = 0.05,  # 5% probability difference
        net_edge_threshold: float = 0.02,  # 2% after costs
    ):
        self.min_edge_threshold = min_edge_threshold
        self.net_edge_threshold = net_edge_threshold
        self._pyth_oracle = None
        self._kalshi_client = None
        self._signals: List[DislocationSignal] = []

    async def initialize(self):
        """Initialize Pyth oracle and Kalshi client."""
        try:
            from oracles.pyth import get_pyth_oracle
            self._pyth_oracle = get_pyth_oracle()
            await self._pyth_oracle.connect()
            logger.info("Pyth oracle connected for arbitrage scanning")
        except Exception as exc:
            logger.warning(f"Failed to connect Pyth oracle: {exc}")

        try:
            from merid.event_venues.kalshi.client import KalshiVenueClient
            from merid.event_venues.kalshi.models import KalshiConfig
            self._kalshi_client = KalshiVenueClient(KalshiConfig())
            logger.info("Kalshi client initialized for arbitrage scanning")
        except Exception as exc:
            logger.warning(f"Failed to initialize Kalshi client: {exc}")

    def _map_ticker_to_pyth_feed(self, kalshi_ticker: str) -> Optional[str]:
        """
        Map Kalshi ticker to Pyth feed symbol.

        Args:
            kalshi_ticker: Kalshi market ticker (e.g., KXBTC-26MAR25-T95000)

        Returns:
            Pyth feed symbol (e.g., "BTC/USD") or None if no mapping
        """
        import re

        for pattern, pyth_symbol in self.KALSHI_TO_PYTH_MAPPING.items():
            if re.match(pattern, kalshi_ticker):
                return pyth_symbol

        return None

    async def _get_kalshi_probability(self, ticker: str) -> Optional[float]:
        """
        Get implied probability from Kalshi market orderbook.

        Args:
            ticker: Kalshi market ticker

        Returns:
            Implied probability (0.0 to 1.0) or None
        """
        if not self._kalshi_client:
            return None

        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            market = catalog.get_market(ticker)

            if not market:
                logger.debug(f"Market {ticker} not found in catalog")
                return None

            # Get orderbook mid from market data
            # Kalshi prices in cents, convert to probability
            if hasattr(market.market, 'last_price') and market.market.last_price:
                prob = float(market.market.last_price) / 100.0
                return prob

            # Fallback: use yes_bid/yes_ask if available
            raw = market.market.raw_data or {}
            yes_bid = raw.get("yes_bid")
            yes_ask = raw.get("yes_ask")

            if yes_bid is not None and yes_ask is not None:
                mid = (float(yes_bid) + float(yes_ask)) / 2.0
                prob = mid / 100.0
                return prob

            logger.debug(f"No price data for {ticker}")
            return None

        except Exception as exc:
            logger.warning(f"Failed to get Kalshi probability for {ticker}: {exc}")
            return None

    async def _get_pyth_probability(self, feed_symbol: str) -> Optional[float]:
        """
        Get probability from Pyth feed.

        For crypto price predictions, converts price levels to probabilities.
        For energy/prediction feeds (future), fetches probability directly.

        Args:
            feed_symbol: Pyth feed symbol (e.g., "BTC/USD")

        Returns:
            Probability or None
        """
        if not self._pyth_oracle:
            return None

        try:
            price_data = await self._pyth_oracle.fetch_price(feed_symbol)

            if not price_data:
                logger.debug(f"No Pyth price for {feed_symbol}")
                return None

            # For now, Pyth provides prices not probabilities
            # In future, Pyth will provide prediction market probability feeds
            # This is a placeholder for when Pyth adds prediction market data feeds
            logger.debug(
                f"Pyth price for {feed_symbol}: ${price_data.price:.2f} "
                "(probability feeds not yet available)"
            )
            return None

        except Exception as exc:
            logger.warning(f"Failed to fetch Pyth feed for {feed_symbol}: {exc}")
            return None

    async def detect_energy_arb(self, kalshi_ticker: str) -> Optional[DislocationSignal]:
        """
        Detect arbitrage between Kalshi energy market and Pyth onchain feed.

        Args:
            kalshi_ticker: Kalshi market ticker (e.g., KXERCOT-26MAR25)

        Returns:
            DislocationSignal if opportunity detected, None otherwise
        """
        # 1. Map to Pyth feed
        pyth_feed = self._map_ticker_to_pyth_feed(kalshi_ticker)
        if not pyth_feed:
            logger.debug(f"No Pyth mapping for {kalshi_ticker}")
            return None

        # 2. Get Kalshi probability
        kalshi_prob = await self._get_kalshi_probability(kalshi_ticker)
        if kalshi_prob is None:
            return None

        # 3. Get Pyth probability
        pyth_prob = await self._get_pyth_probability(pyth_feed)
        if pyth_prob is None:
            # Pyth prediction feeds not yet available
            return None

        # 4. Compute edge
        gross_edge = abs(kalshi_prob - pyth_prob)

        if gross_edge < self.min_edge_threshold:
            return None

        # 5. Account for costs
        # Kalshi fees: parabolic fee schedule
        kalshi_fees_bps = self._compute_kalshi_fees(kalshi_prob, size_usd=1000)

        # Onchain gas costs (estimated)
        gas_cost_bps = 50  # ~$5 gas on $1000 = 50 bps

        net_edge = gross_edge - (kalshi_fees_bps / 10000) - (gas_cost_bps / 10000)

        # Convert to bps
        gross_edge_bps = gross_edge * 10000
        net_edge_bps = net_edge * 10000

        if net_edge_bps < self.net_edge_threshold * 10000:
            return None

        # 6. Build signal
        now = time.time()

        # Determine trade direction
        if kalshi_prob > pyth_prob:
            # Kalshi overpriced: sell Kalshi, buy Pyth
            buy_venue_name = "pyth"
            sell_venue_name = "kalshi"
        else:
            # Kalshi underpriced: buy Kalshi, sell Pyth
            buy_venue_name = "kalshi"
            sell_venue_name = "pyth"

        signal = DislocationSignal(
            domain=DislocationDomain.PREDICTION.value,
            arb_type=ArbType.PURE_ARB.value,
            symbol=kalshi_ticker,
            venues=[
                VenuePrice(
                    venue="kalshi",
                    symbol=kalshi_ticker,
                    bid=kalshi_prob * 100,  # Convert to cents
                    ask=kalshi_prob * 100,
                    mid=kalshi_prob * 100,
                    timestamp=now,
                    liquidity_usd=1000,  # Placeholder
                    fees_bps=kalshi_fees_bps,
                ),
                VenuePrice(
                    venue="pyth",
                    symbol=pyth_feed,
                    bid=pyth_prob * 100,
                    ask=pyth_prob * 100,
                    mid=pyth_prob * 100,
                    timestamp=now,
                    liquidity_usd=10000,  # Onchain typically more liquid
                    fees_bps=gas_cost_bps,
                ),
            ],
            gross_edge_bps=gross_edge_bps,
            net_edge_bps=net_edge_bps,
            edge_usd=net_edge * 1000,  # On $1000 reference size
            reference_size_usd=1000,
            total_fees_bps=kalshi_fees_bps + gas_cost_bps,
            spread_cost_bps=0,  # Assume mid prices
            detected_at=now,
            ttl_seconds=120,  # 2 minute TTL
        )

        self._signals.append(signal)
        logger.info(
            f"Pyth-Kalshi arb detected: {kalshi_ticker} | "
            f"Kalshi={kalshi_prob:.3f} Pyth={pyth_prob:.3f} | "
            f"gross_edge={gross_edge_bps:.1f}bps net_edge={net_edge_bps:.1f}bps"
        )

        return signal

    def _compute_kalshi_fees(self, probability: float, size_usd: float = 1000) -> float:
        """
        Compute Kalshi taker fees using parabolic schedule.

        Taker fee: ceil(0.07 × C × P × (1-P)) dollars
        where C = contract count, P = probability

        Args:
            probability: Market probability (0-1)
            size_usd: Position size in USD

        Returns:
            Fee in basis points
        """
        import math

        # Convert size to contract count (each contract pays $1)
        contracts = size_usd

        # Parabolic taker fee
        fee_dollars = math.ceil(0.07 * contracts * probability * (1 - probability))

        # Convert to bps
        fee_bps = (fee_dollars / size_usd) * 10000

        return fee_bps

    async def scan_all_markets(self) -> List[DislocationSignal]:
        """
        Scan all Kalshi energy markets for Pyth arbitrage opportunities.

        Returns:
            List of detected arbitrage signals
        """
        if not self._kalshi_client or not self._pyth_oracle:
            logger.warning("Pyth-Kalshi scanner not initialized, call initialize() first")
            return []

        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()

            # Get energy markets (or all markets that map to Pyth feeds)
            energy_markets = catalog.get_markets_by_category("energy")
            crypto_markets = catalog.get_markets_by_category("crypto")

            all_markets = energy_markets + crypto_markets

            signals = []
            for market in all_markets[:50]:  # Limit to first 50 to avoid rate limits
                signal = await self.detect_energy_arb(market.market.market_id)
                if signal:
                    signals.append(signal)

            logger.info(f"Pyth-Kalshi scan complete: {len(signals)} opportunities found")
            return signals

        except Exception as exc:
            logger.error(f"Pyth-Kalshi scan failed: {exc}")
            return []

    def get_active_signals(self, now: Optional[float] = None) -> List[DislocationSignal]:
        """Get active Pyth-Kalshi arbitrage signals."""
        now = now or time.time()
        return [s for s in self._signals if s.is_actionable(now)]

    def get_metrics(self) -> Dict[str, Any]:
        """Get scanner metrics."""
        now = time.time()
        active = self.get_active_signals(now)
        expired = [s for s in self._signals if s.status == DislocationStatus.EXPIRED.value]

        return {
            "scanner_type": "pyth_kalshi",
            "total_signals": len(self._signals),
            "active_signals": len(active),
            "expired_signals": len(expired),
            "avg_edge_bps": sum(s.net_edge_bps for s in active) / len(active) if active else 0,
            "max_edge_bps": max((s.net_edge_bps for s in active), default=0),
        }


# Singleton
_pyth_kalshi_scanner: Optional[PythKalshiArbScanner] = None


def get_pyth_kalshi_scanner() -> PythKalshiArbScanner:
    """Get or create Pyth-Kalshi arbitrage scanner singleton."""
    global _pyth_kalshi_scanner
    if _pyth_kalshi_scanner is None:
        _pyth_kalshi_scanner = PythKalshiArbScanner()
    return _pyth_kalshi_scanner
