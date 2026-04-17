"""§2 Prediction Market Model — Implied probabilities, edge, and lifecycle.

Converts Kalshi prices to implied odds, tracks contract lifecycle,
and computes expected edge after fees and slippage.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger
from monitoring.metrics import record_pm_spot_staleness_violation, update_pm_spot_age

logger = get_logger("merid.prediction.model")

# Throttle repetitive stale-spot warnings when the event loop is lagged or the feed is behind.
_stale_spot_log_at: Dict[str, float] = {}
PM_STALE_SPOT_LOG_INTERVAL_SEC = float(os.getenv("MERID_PM_STALE_SPOT_LOG_INTERVAL_SEC", "25.0"))

# Kalshi fee schedule (per contract, in cents)
KALSHI_FEE_PER_CONTRACT_CENTS = Decimal("2")  # $0.02 per contract
KALSHI_TICK_SIZE_CENTS = Decimal("1")          # 1 cent tick

# Maximum age (seconds) for a cached spot price used in compute_edge().
# Prices older than this are treated as stale and the spot-relative model
# is skipped, falling back to the Kalshi implied probability.
# BUG-EL12 FIX: Increased from 30s to 120s to be resilient to event-loop lag.
MAX_PRICE_AGE_SECONDS: int = 120


def max_spot_age_seconds() -> int:
    """Upper bound on spot quote age for ``get_spot_price`` (shared by all PM paths).

    Override with ``MERID_PM_MAX_SPOT_AGE_SECONDS`` so AgentGrid and helpers stay aligned
    without duplicating literals.
    """
    try:
        return int(os.getenv("MERID_PM_MAX_SPOT_AGE_SECONDS", str(MAX_PRICE_AGE_SECONDS)))
    except ValueError:
        return MAX_PRICE_AGE_SECONDS


def pm_spot_feed_symbol_candidates(asset: str) -> tuple[str, ...]:
    """LivePriceFeed cache keys to try for PM crypto spot (BTC, ETH, SOL, XRP, DOGE, …).

    Coinbase Advanced Trade polls ``BTC-USD`` etc.; :class:`data.live_price_feed.LivePriceFeed`
    stores the result under ``BTC/USD``.  We return **only** the USD key so the PM
    model is always consistent with the Coinbase primary source and Kalshi strike units.
    USDT fallback removed: USDT pairs are a different price series (tether premium/discount)
    and caused systematic drift vs the USD-denominated Kalshi settlement price.
    """
    au = (asset or "").strip().upper()
    if not au:
        return ()
    return (f"{au}/USD",)


def spot_dist_prob_scale() -> Decimal:
    """Maps fractional distance (spot-strike)/strike to YES-probability nudge.

    Default ``10`` means a 1% distance shifts implied YES by ~10 percentage points
    before clamping — tunable via ``MERID_PM_SPOT_DIST_PROB_SCALE`` (not a hidden literal).
    """
    try:
        return Decimal(os.getenv("MERID_PM_SPOT_DIST_PROB_SCALE", "10"))
    except Exception:
        return Decimal("10")


class ContractState(str, Enum):
    """Lifecycle states for a prediction market contract."""
    LISTED = "listed"          # Market created, not yet trading
    TRADING = "trading"        # Active trading
    CLOSING = "closing"        # Near expiry, reduced liquidity expected
    CLOSED = "closed"          # Trading halted, awaiting resolution
    SETTLED_YES = "settled_yes"
    SETTLED_NO = "settled_no"
    SETTLED_UNKNOWN = "settled_unknown"  # Settled but resolution ambiguous/missing
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

    # H9: tracks whether kalshi_prob_adjustment has already been applied so
    # forecasters and opinion strategies skip it and avoid double-counting.
    sentiment_adjusted: bool = False
    # Age of the sentiment context at snapshot build time (seconds).
    # None means sentiment was unavailable or stale-gated (H2).
    sentiment_age_seconds: Optional[float] = None

    # Spot/strike diagnostics (AgentGrid PM — ``trading_agent._build_snapshot``)
    resolved_asset: Optional[str] = None
    resolved_timeframe: Optional[str] = None
    spot_price_usd: Optional[Decimal] = None
    strike_price_usd: Optional[float] = None
    # Fractional (spot−strike)/strike — same units as ``distance_to_strike_pct()`` in spot_strike_context.
    distance_to_strike_pct: Optional[Decimal] = None
    # Why distance is missing: missing_spot | missing_strike | ok | … (observability for [PM_SIGNAL]).
    spot_strike_basis_note: str = ""
    spot_strike_veto: bool = False
    spot_strike_veto_reason: str = ""

    # Strike selection metadata (``merid.prediction.kalshi_strike_selector``)
    strike_in_target_band: bool = False   # True if strike is within preferred ATM band
    strike_risk_capped: bool = False      # True if deep-OTM accepted with capped risk

    # Crypto PM vol bridge (``merid.signals.crypto_pm_vol_bridge``) — realized vol band → sizing
    crypto_vol_band: Optional[str] = None  # low | mid | high
    crypto_vol_size_mult: Optional[float] = None  # applied in KalshiStrategy / MM depth
    crypto_realized_vol_annualized: Optional[float] = None
    crypto_vol_bars_available: Optional[int] = None


_active_snapshots: List[MarketSnapshot] = []


def snapshot_timestamp_utc_epoch_seconds(ts: Optional[Any]) -> float:
    """''snapshot.timestamp'' is a :class:`~datetime.datetime`; use this for ``time.time() - ts`` age checks.

    Naive datetimes are treated as UTC. Non-datetime values are cast to ``float`` when possible.
    """
    import time as _time
    from datetime import datetime, timezone

    if ts is None:
        return _time.time()
    if isinstance(ts, datetime):
        aware = ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
        return float(aware.timestamp())
    try:
        return float(ts)
    except (TypeError, ValueError):
        return _time.time()


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
        price_feed=None,
    ):
        self._fee = fee_per_contract
        self._default_slippage = default_slippage_cents
        self._model_probs: Dict[str, Decimal] = {}

        # Integration with external price feeds.
        # Accept an explicit feed for testing/injection; fall back to the
        # live singleton when none is provided.
        if price_feed is not None:
            self._price_feed = price_feed
        else:
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
            if resolution:
                _r = resolution.strip().lower()
                # Broad yes-resolution detection: covers "yes", "y", "1",
                # "true", "outcome_yes", "winner", etc.
                _yes_tokens = {"yes", "y", "1", "true", "winner", "outcome_yes"}
                _no_tokens = {"no", "n", "0", "false", "loser", "outcome_no"}
                if _r in _yes_tokens or "yes" in _r:
                    return ContractState.SETTLED_YES
                if _r in _no_tokens or "no" in _r:
                    return ContractState.SETTLED_NO
            # FLAW-03 fix: do NOT default to SETTLED_YES for ambiguous/missing
            # resolution — return SETTLED_UNKNOWN so callers can handle it
            # explicitly rather than silently corrupting Brier calibration and
            # realized PnL records.
            return ContractState.SETTLED_UNKNOWN

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

    def get_spot_price(self, asset: str, market_id: str = "") -> Optional[Decimal]:
        """Fetch and validate a spot price from the external feed.

        Returns the spot as a ``Decimal``, or ``None`` if the feed is
        unavailable, the asset is not found, or the price is stale.
        Staleness uses ``max_spot_age_seconds()`` (``MERID_PM_MAX_SPOT_AGE_SECONDS``,
        default ``MAX_PRICE_AGE_SECONDS``) — the same bound for all PM callers.

        Callers should call this **once per snapshot** and pass the result
        to every ``compute_edge()`` invocation via ``spot_override`` so the
        feed is not hit multiple times for the same market cycle.
        """
        if not asset:
            return None
        if not self._price_feed:
            logger.debug(
                "[model] get_spot_price: no price feed for %s — check data.live_price_feed wiring",
                asset,
            )
            return None
        try:
            price_data = None
            _tried: list[str] = []
            for _sym in pm_spot_feed_symbol_candidates(asset):
                _tried.append(_sym)
                price_data = self._price_feed.get_current_price(_sym)
                if price_data:
                    break
            if not price_data:
                logger.debug(
                    "[model] get_spot_price: no quote yet for %s (tried %s) — feed empty or rate-limited",
                    asset,
                    _tried,
                )
                return None
            from data.live_price_feed import _utc_age_seconds

            _age = _utc_age_seconds(price_data.timestamp)
            _max_age = max_spot_age_seconds()
            _mk = (market_id or "").strip()

            # P0-001: Always update spot age gauge for observability
            update_pm_spot_age(asset, _age)

            if _age > _max_age:
                _log_key = f"{(asset or '').upper()}|{_mk}"
                _now = time.monotonic()
                _last = _stale_spot_log_at.get(_log_key, 0.0)
                if _now - _last >= PM_STALE_SPOT_LOG_INTERVAL_SEC:
                    _stale_spot_log_at[_log_key] = _now
                    if _mk:
                        logger.warning(
                            "[model] Stale spot price for asset=%s market=%s (age=%.0fs > %ds) — "
                            "skipping spot-relative model (raise MERID_PM_MAX_SPOT_AGE_SECONDS or fix feed / loop lag)",
                            asset,
                            _mk,
                            _age,
                            _max_age,
                        )
                    else:
                        logger.warning(
                            "[model] Stale spot price for asset=%s (age=%.0fs > %ds) — "
                            "skipping spot-relative model (raise MERID_PM_MAX_SPOT_AGE_SECONDS or fix feed / loop lag)",
                            asset,
                            _age,
                            _max_age,
                        )
                # P0-001: Record staleness violation metric
                record_pm_spot_staleness_violation(asset, _mk)
                return None
            return Decimal(str(price_data.price))
        except Exception as _exc:
            logger.debug("[model] get_spot_price error for %s: %s", asset, _exc)
            return None

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
        spot_override: Optional[Decimal] = None,
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
            spot_override: Pre-fetched spot price (avoids a second feed call when
                computing both YES and NO edges for the same snapshot).
        """
        mp = model_prob or self._model_probs.get(market_id)

        # If no explicit model prob, derive from spot price (passed in or fetched once).
        # spot_override lets build_snapshot() call get_spot_price() exactly once and
        # share the result across both YES and NO edge computations, preventing
        # divergent model probabilities from different feed timestamps.
        if mp is None and strike_price is not None:
            spot = spot_override
            if spot is None and self._price_feed and asset:
                spot = self.get_spot_price(asset, market_id)
            if spot is not None:
                strike = Decimal(str(strike_price))
                dist_pct = (spot - strike) / strike
                # Use a timeframe-aware scale so the linear spot→prob map is
                # calibrated per horizon.  For short tenors (15m) even a small
                # spot/strike gap is highly predictive; for monthly/annual a
                # 10% gap is modest and should not push probability to the clamp.
                # Fallback: global MERID_PM_SPOT_DIST_PROB_SCALE (default 10).
                _tf_scale_map = {
                    "15m": Decimal("10"),
                    "1h": Decimal("6"),
                    "daily": Decimal("3"),
                    "weekly": Decimal("1.5"),
                    "monthly": Decimal("1.0"),
                    "annual": Decimal("0.5"),
                }
                scale = spot_dist_prob_scale()  # env override always wins
                _env_default = Decimal("10")
                if scale == _env_default:
                    # No custom override set — use per-timeframe calibrated scale
                    try:
                        from merid.event_venues.kalshi.market_filter import get_series_timeframe_bucket as _gstb
                        _inferred_tf = _gstb(market_id)
                        if _inferred_tf in _tf_scale_map:
                            scale = _tf_scale_map[_inferred_tf]
                    except Exception:
                        pass
                yes_prob = Decimal("0.5") + (dist_pct * scale)
                yes_prob = min(max(yes_prob, Decimal("0.05")), Decimal("0.95"))
                derived_prob = yes_prob if side == "yes" else Decimal("1.0") - yes_prob
                mp = derived_prob
                logger.debug(
                    "[model] Derived %s prob %s for %s from spot %s vs strike %s (tf_scale=%s)",
                    side, mp, market_id, spot, strike, scale,
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

        # Fee drag: Kalshi charges ceil(0.07 × C × P × (1−P)) cents per leg.
        # Express as a fraction of the 100¢ max payout so it's in the same units
        # as raw_edge (probability space).  The flat KALSHI_FEE_PER_CONTRACT_CENTS
        # constant is correct at 50¢ but overestimates at extreme prices (5¢, 95¢
        # where the actual fee is only 1¢); use the formula directly instead.
        import math as _fee_math
        _price_cents_f = float(market_prob) * 100.0
        _price_frac_f = float(market_prob)
        _fee_per_contract = _fee_math.ceil(
            0.07 * _price_cents_f * (1.0 - _price_frac_f)
        )
        fee_drag = (Decimal(str(_fee_per_contract)) / Decimal("100")).quantize(
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
        asset: Optional[str] = None,
        strike_price: Optional[float] = None,
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
            # Fetch spot price once and share across both YES and NO edge computations
            # so they are derived from the same feed timestamp (H02 fix).
            _spot = self.get_spot_price(asset, market_id) if asset else None
            for side in ("yes", "no"):
                edge = self.compute_edge(
                    market_id, implied, side=side, action="buy",
                    asset=asset, strike_price=strike_price, spot_override=_spot,
                )
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
