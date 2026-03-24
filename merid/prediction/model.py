"""§2 Prediction Market Model — Implied probabilities, edge, and lifecycle.

Converts Kalshi prices to implied odds, tracks contract lifecycle,
and computes expected edge after fees and slippage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional

import math

from utils.logger import get_logger

logger = get_logger("merid.prediction.model")

# Kalshi fee schedule (per contract, in cents)
KALSHI_FEE_PER_CONTRACT_CENTS = Decimal("2")  # $0.02 per contract
KALSHI_TICK_SIZE_CENTS = Decimal("1")          # 1 cent tick


class ContractState(str, Enum):
    """Lifecycle states for a prediction market contract."""
    LISTED = "listed"          # Market created, not yet trading
    TRADING = "trading"        # Active trading
    CLOSING = "closing"        # Near expiry, reduced liquidity expected
    CLOSED = "closed"          # Trading halted, awaiting resolution
    SETTLED_YES = "settled_yes"
    SETTLED_NO = "settled_no"
    CANCELLED = "cancelled"


@dataclass
class ImpliedProbability:
    """Implied probability derived from market prices."""
    yes_prob: Decimal          # 0.00 – 1.00
    no_prob: Decimal           # 0.00 – 1.00
    yes_bid: Optional[Decimal] = None
    yes_ask: Optional[Decimal] = None
    no_bid: Optional[Decimal] = None
    no_ask: Optional[Decimal] = None
    spread_cents: Optional[Decimal] = None  # yes_ask - yes_bid
    overround: Optional[Decimal] = None     # yes_prob + no_prob - 1
    timestamp: Optional[datetime] = None

    @property
    def is_efficient(self) -> bool:
        """True if yes + no probabilities sum to ~1 (within 3 cents)."""
        if self.overround is None:
            return True
        return abs(self.overround) <= Decimal("0.03")


@dataclass
class EdgeEstimate:
    """Expected edge for a trade after fees and slippage."""
    market_id: str
    side: str                  # "yes" or "no"
    action: str                # "buy" or "sell"
    market_prob: Decimal       # Market-implied probability
    model_prob: Decimal        # MERID's estimated probability
    raw_edge: Decimal          # model_prob - market_prob (for buy)
    fee_drag: Decimal          # Fee cost as fraction of contract
    slippage_est: Decimal      # Estimated slippage
    net_edge: Decimal          # raw_edge - fee_drag - slippage_est
    edge_type: str             # "arb" or "speculative"
    confidence: Decimal        # 0-1, how confident the model is
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_actionable(self) -> bool:
        """True if net edge is positive."""
        return self.net_edge > Decimal("0")


@dataclass
class MarketSnapshot:
    """Complete snapshot of a Kalshi market for strategy consumption."""
    market_id: str
    event_id: str
    title: str
    state: ContractState
    implied: ImpliedProbability
    volume: Decimal
    open_interest: Decimal
    market_shape: Optional[Any] = None  # Normalized shape (direction, strike, expiry)
    spot_price: Optional[float] = None
    time_to_expiry_hours: Optional[Decimal] = None
    close_time: Optional[datetime] = None
    category: Optional[str] = None
    edges: List[EdgeEstimate] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Fear/greed sentiment (injected by trading_agent._build_snapshot)
    sentiment_local: Optional[float] = None    # 0–100, this market
    sentiment_category: Optional[float] = None # 0–100, category average
    sentiment_global: Optional[float] = None   # 0–100, all Kalshi markets
    sentiment_regime: Optional[str] = None     # extreme_fear|fear|greed|extreme_greed


_active_snapshots: List[MarketSnapshot] = []


def record_snapshot(snapshot: MarketSnapshot) -> None:
    """Record a market snapshot for critic evaluation."""
    global _active_snapshots
    # Keep latest per market_id, cap at 200
    _active_snapshots = [s for s in _active_snapshots if s.market_id != snapshot.market_id]
    _active_snapshots.append(snapshot)
    if len(_active_snapshots) > 200:
        _active_snapshots = _active_snapshots[-200:]


def get_active_snapshots() -> List[MarketSnapshot]:
    """Return current active market snapshots for critic checks."""
    return list(_active_snapshots)


class PredictionMarketModel:
    """Core prediction market model for Kalshi.

    Responsibilities:
    - Convert Kalshi cent prices to implied probabilities.
    - Determine contract lifecycle state.
    - Compute expected edge after fees and slippage.
    - Detect pure arb (yes+no mispricing) vs speculative edge.
    """

    def __init__(
        self,
        fee_per_contract: Decimal = KALSHI_FEE_PER_CONTRACT_CENTS,
        default_slippage_cents: Decimal = Decimal("1"),
    ):
        self._fee = fee_per_contract
        self._default_slippage = default_slippage_cents
        self._model_probs: Dict[str, Decimal] = {}
        
        # Integration with external price feeds
        try:
            from data.live_price_feed import get_live_price_feed
            self._price_feed = get_live_price_feed()
        except ImportError:
            self._price_feed = None

    # ------------------------------------------------------------------
    # Implied probabilities
    # ------------------------------------------------------------------

    def implied_probabilities(
        self,
        yes_bid: Optional[Decimal],
        yes_ask: Optional[Decimal],
        no_bid: Optional[Decimal] = None,
        no_ask: Optional[Decimal] = None,
    ) -> ImpliedProbability:
        """Derive implied probabilities from Kalshi cent prices.

        Kalshi prices are in cents (0-100).  A yes price of 55 means
        the market implies a 55 % probability of the event occurring.

        Args:
            yes_bid: Best bid for YES in cents.
            yes_ask: Best ask for YES in cents.
            no_bid:  Best bid for NO in cents (optional, derived if absent).
            no_ask:  Best ask for NO in cents (optional, derived if absent).

        Returns:
            ImpliedProbability with mid-point probabilities.
        """
        # Mid-point for YES
        if yes_bid is not None and yes_ask is not None:
            yes_mid = (yes_bid + yes_ask) / 2
        elif yes_bid is not None:
            yes_mid = yes_bid
        elif yes_ask is not None:
            yes_mid = yes_ask
        else:
            yes_mid = Decimal("50")

        # Derive NO from YES if not provided (Kalshi: yes + no = 100)
        if no_bid is None and yes_ask is not None:
            no_bid = Decimal("100") - yes_ask
        if no_ask is None and yes_bid is not None:
            no_ask = Decimal("100") - yes_bid

        if no_bid is not None and no_ask is not None:
            no_mid = (no_bid + no_ask) / 2
        else:
            no_mid = Decimal("100") - yes_mid

        yes_prob = (yes_mid / Decimal("100")).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        no_prob = (no_mid / Decimal("100")).quantize(Decimal("0.0001"), ROUND_HALF_UP)

        spread = None
        if yes_bid is not None and yes_ask is not None:
            spread = yes_ask - yes_bid

        overround = yes_prob + no_prob - Decimal("1")

        return ImpliedProbability(
            yes_prob=yes_prob,
            no_prob=no_prob,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            spread_cents=spread,
            overround=overround,
            timestamp=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Lifecycle state
    # ------------------------------------------------------------------

    def determine_state(
        self,
        status: str,
        close_time: Optional[datetime] = None,
        settlement_time: Optional[datetime] = None,
        resolution: Optional[str] = None,
    ) -> ContractState:
        """Map Kalshi status strings + times to ContractState.

        Args:
            status: Kalshi status string (active, closed, settled, etc.)
            close_time: When trading closes.
            settlement_time: When the market settles.
            resolution: Resolution outcome if settled.
        """
        status_lower = status.lower()

        if status_lower in ("settled", "finalized"):
            if resolution and "yes" in resolution.lower():
                return ContractState.SETTLED_YES
            if resolution and "no" in resolution.lower():
                return ContractState.SETTLED_NO
            return ContractState.SETTLED_YES  # default if ambiguous

        if status_lower in ("cancelled", "voided"):
            return ContractState.CANCELLED

        if status_lower in ("closed", "halted"):
            return ContractState.CLOSED

        # Active — check if near expiry
        if close_time:
            now = datetime.now(timezone.utc)
            hours_left = (close_time - now).total_seconds() / 3600
            if hours_left <= 0:
                return ContractState.CLOSED
            if hours_left <= 2:
                return ContractState.CLOSING

        if status_lower in ("active", "open", "trading"):
            return ContractState.TRADING

        return ContractState.LISTED

    # ------------------------------------------------------------------
    # Edge computation
    # ------------------------------------------------------------------

    def set_model_probability(self, market_id: str, prob: Decimal) -> None:
        """Set MERID's internal probability estimate for a market."""
        self._model_probs[market_id] = prob

    def compute_edge(
        self,
        market_id: str,
        implied: ImpliedProbability,
        model_prob: Optional[Decimal] = None,
        side: str = "yes",
        action: str = "buy",
        order_size_contracts: int = 1,
        asset: Optional[str] = None,
        strike_price: Optional[float] = None,
        market_shape: Optional[Any] = None,
    ) -> EdgeEstimate:
        """Compute expected edge for a potential trade.

        Edge types:
        - **arb**: yes_ask + no_ask < 100 (guaranteed profit).
        - **speculative**: MERID's model probability differs from market.

        Args:
            market_id: Kalshi market ticker.
            implied: Current implied probabilities.
            model_prob: MERID's probability estimate (overrides stored).
            side: "yes" or "no".
            action: "buy" or "sell".
            order_size_contracts: Number of contracts for fee calc.
            asset: Underlying asset (e.g. BTC) for external feed integration.
            strike_price: The strike price of the contract for spot-relative model.
            market_shape: Normalized market description (threshold vs up/down).
        """
        mp = model_prob or self._model_probs.get(market_id)
        
        # If no explicit model prob, try to derive from external spot price feed for crypto
        if mp is None and self._price_feed and asset and strike_price:
            price_data = self._price_feed.get_current_price(f"{asset}/USDT")
            if price_data:
                spot = Decimal(str(price_data.price))
                strike = Decimal(str(strike_price))

                # Use market_shape when available to align direction semantics.
                mtype = getattr(market_shape, "market_type", None) if market_shape else None
                # Positive distance implies spot > strike
                dist_pct = (spot - strike) / strike
                if mtype == "THRESHOLD_LEQ":
                    # For "≤ K" markets, positive distance should decrease YES prob
                    dist_pct = -dist_pct
                # Logistic mapping keeps probabilities bounded and smooth
                prob_float = 1.0 / (1.0 + math.exp(float(-dist_pct * Decimal("12"))))
                derived_prob = Decimal(str(round(prob_float, 4)))
                derived_prob = min(max(derived_prob, Decimal("0.02")), Decimal("0.98"))

                if side == "no":
                    derived_prob = Decimal("1.0") - derived_prob

                mp = derived_prob
                logger.debug(
                    f"[model] Derived {side} prob {mp:.2f} for {market_id} "
                    f"(type={mtype}) from spot {spot:.2f} vs strike {strike:.2f}"
                )

        if mp is None:
            mp = implied.yes_prob if side == "yes" else implied.no_prob

        market_prob = implied.yes_prob if side == "yes" else implied.no_prob

        # Raw edge: for a buy, edge = model_prob - market_prob
        # For a sell, edge = market_prob - model_prob
        if action == "buy":
            raw_edge = mp - market_prob
        else:
            raw_edge = market_prob - mp

        # Fee drag: fee per contract / 100 (convert cents to dollars)
        total_fee = self._fee * order_size_contracts
        fee_drag = (total_fee / (Decimal("100") * order_size_contracts)).quantize(
            Decimal("0.0001"), ROUND_HALF_UP
        )

        # Slippage estimate
        slippage = (self._default_slippage / Decimal("100")).quantize(
            Decimal("0.0001"), ROUND_HALF_UP
        )

        net_edge = raw_edge - fee_drag - slippage

        # Detect arb: if yes_ask + no_ask < 100 cents
        edge_type = "speculative"
        if implied.yes_ask is not None and implied.no_ask is not None:
            if implied.yes_ask + implied.no_ask < Decimal("100"):
                edge_type = "arb"

        # Confidence: higher when spread is tight and volume is present
        confidence = Decimal("0.5")
        if implied.spread_cents is not None:
            if implied.spread_cents <= Decimal("2"):
                confidence = Decimal("0.8")
            elif implied.spread_cents <= Decimal("5"):
                confidence = Decimal("0.6")

        return EdgeEstimate(
            market_id=market_id,
            side=side,
            action=action,
            market_prob=market_prob,
            model_prob=mp,
            raw_edge=raw_edge.quantize(Decimal("0.0001"), ROUND_HALF_UP),
            fee_drag=fee_drag,
            slippage_est=slippage,
            net_edge=net_edge.quantize(Decimal("0.0001"), ROUND_HALF_UP),
            edge_type=edge_type,
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Arb detection
    # ------------------------------------------------------------------

    def detect_arb(self, implied: ImpliedProbability) -> Optional[EdgeEstimate]:
        """Check if yes+no prices create a risk-free arb opportunity.

        On Kalshi, if yes_ask + no_ask < 100, buying both sides locks
        in a guaranteed profit of (100 - yes_ask - no_ask) cents minus fees.
        """
        if implied.yes_ask is None or implied.no_ask is None:
            return None

        total = implied.yes_ask + implied.no_ask
        if total >= Decimal("100"):
            return None

        gross_profit_cents = Decimal("100") - total
        fee_cents = self._fee * 2  # buying both sides
        net_profit_cents = gross_profit_cents - fee_cents

        if net_profit_cents <= Decimal("0"):
            return None

        return EdgeEstimate(
            market_id="arb",
            side="both",
            action="buy",
            market_prob=implied.yes_prob,
            model_prob=Decimal("1"),
            raw_edge=(gross_profit_cents / Decimal("100")).quantize(Decimal("0.0001")),
            fee_drag=(fee_cents / Decimal("100")).quantize(Decimal("0.0001")),
            slippage_est=Decimal("0"),
            net_edge=(net_profit_cents / Decimal("100")).quantize(Decimal("0.0001")),
            edge_type="arb",
            confidence=Decimal("0.99"),
        )

    # ------------------------------------------------------------------
    # Snapshot builder
    # ------------------------------------------------------------------

    def build_snapshot(
        self,
        market_id: str,
        event_id: str,
        title: str,
        status: str,
        yes_bid: Optional[Decimal],
        yes_ask: Optional[Decimal],
        volume: Decimal = Decimal("0"),
        open_interest: Decimal = Decimal("0"),
        close_time: Optional[datetime] = None,
        resolution: Optional[str] = None,
        category: Optional[str] = None,
    ) -> MarketSnapshot:
        """Build a complete MarketSnapshot from raw Kalshi data."""
        implied = self.implied_probabilities(yes_bid, yes_ask)
        state = self.determine_state(status, close_time, resolution=resolution)

        hours_left = None
        if close_time:
            now = datetime.now(timezone.utc)
            hours_left = Decimal(str(
                max(0, (close_time - now).total_seconds() / 3600)
            )).quantize(Decimal("0.01"))

        edges = []
        if state in (ContractState.TRADING, ContractState.CLOSING):
            for side in ("yes", "no"):
                edge = self.compute_edge(market_id, implied, side=side, action="buy")
                if edge.is_actionable:
                    edges.append(edge)
            arb = self.detect_arb(implied)
            if arb:
                edges.append(arb)

        return MarketSnapshot(
            market_id=market_id,
            event_id=event_id,
            title=title,
            state=state,
            implied=implied,
            volume=volume,
            open_interest=open_interest,
            time_to_expiry_hours=hours_left,
            close_time=close_time,
            category=category,
            edges=edges,
        )
