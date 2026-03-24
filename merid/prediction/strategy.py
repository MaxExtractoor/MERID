"""§3 Kalshi Strategy — Edge thresholds, time-to-expiry logic, position sizing.

Provides named, testable prediction-market playbooks for Kalshi:
- Same-market consistency checks (multi-outcome arb).
- Time-to-expiry aware behaviour (early speculative vs late arb).
- Explicit position sizing and exit rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Dict, List, Optional

from merid.prediction.model import (
    ContractState,
    EdgeEstimate,
    MarketSnapshot,
    PredictionMarketModel,
)
from utils.logger import get_logger

logger = get_logger("merid.prediction.strategy")


class SignalAction(str, Enum):
    """What the strategy recommends."""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    SELL_YES = "sell_yes"
    SELL_NO = "sell_no"
    CLOSE = "close"
    HOLD = "hold"
    NO_ACTION = "no_action"
    QUOTE = "quote"  # For market making: provides bid/ask


class ExpiryPhase(str, Enum):
    """Time-to-expiry regime."""
    EARLY = "early"        # > 24 h to expiry
    MID = "mid"            # 4–24 h
    LATE = "late"          # 1–4 h
    TERMINAL = "terminal"  # < 1 h


@dataclass
class TimeframeEntryRule:
    """Entry gating per timeframe."""

    min_minutes_to_expiry: int
    min_edge: Decimal
    max_yes_move_pct: Decimal


@dataclass
class StrategyConfig:
    """Tunable parameters for KalshiStrategy."""
    # Edge thresholds (as probability fraction, e.g. 0.03 = 3 %)
    min_edge_early: Decimal = Decimal("0.05")      # 5 % edge required early
    min_edge_mid: Decimal = Decimal("0.04")
    min_edge_late: Decimal = Decimal("0.03")
    min_edge_terminal: Decimal = Decimal("0.02")
    min_arb_edge: Decimal = Decimal("0.005")        # 0.5 % for pure arb

    # Position sizing
    max_contracts_per_market: int = 100
    max_contracts_per_order: int = 25
    kelly_fraction: Decimal = Decimal("0.25")       # Quarter-Kelly

    # Exit rules
    profit_target_pct: Decimal = Decimal("0.15")    # Take profit at 15 %
    stop_loss_pct: Decimal = Decimal("0.10")         # Cut at 10 % loss
    max_hold_hours: Decimal = Decimal("48")          # Force close after 48 h

    # Liquidity
    min_volume: Decimal = Decimal("1000")            # Min market volume
    min_open_interest: Decimal = Decimal("100")
    min_depth_contracts: int = 5                      # Min depth at best price

    # Market Making
    mm_max_spread_cents: Decimal = Decimal("10")     # Don't quote if spread > 10c
    mm_target_spread_cents: Decimal = Decimal("2")   # Try to quote 2c spread
    mm_inventory_limit: int = 50                     # Max contracts to hold per side
    mm_skew_factor: Decimal = Decimal("0.5")         # How much to lean based on inventory

    # Confidence
    min_confidence: Decimal = Decimal("0.5")

    # Entry gating per timeframe
    freshness_max_age_seconds: int = 90
    timeframe_entry_rules: Dict[str, TimeframeEntryRule] = field(default_factory=lambda: {
        "15m": TimeframeEntryRule(min_minutes_to_expiry=4, min_edge=Decimal("0.02"), max_yes_move_pct=Decimal("0.10")),
        "1h": TimeframeEntryRule(min_minutes_to_expiry=15, min_edge=Decimal("0.03"), max_yes_move_pct=Decimal("0.10")),
        "daily": TimeframeEntryRule(min_minutes_to_expiry=90, min_edge=Decimal("0.06"), max_yes_move_pct=Decimal("0.12")),
    })


@dataclass
class StrategySignal:
    """Output of strategy evaluation for one market."""
    market_id: str
    action: SignalAction
    side: str                  # "yes", "no", or "both"
    contracts: int             # Recommended size
    limit_price_cents: Optional[int] = None
    bid_price_cents: Optional[int] = None  # For QUOTE
    ask_price_cents: Optional[int] = None  # For QUOTE
    edge: Optional[EdgeEstimate] = None
    phase: Optional[ExpiryPhase] = None
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "action": self.action.value,
            "side": self.side,
            "contracts": self.contracts,
            "limit_price_cents": self.limit_price_cents,
            "bid_price_cents": self.bid_price_cents,
            "ask_price_cents": self.ask_price_cents,
            "phase": self.phase.value if self.phase else None,
            "reason": self.reason,
            "net_edge": str(self.edge.net_edge) if self.edge else None,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class PositionState:
    """Tracks an open position for exit-rule evaluation."""
    market_id: str
    side: str
    contracts: int
    avg_entry_cents: Decimal
    opened_at: datetime
    current_price_cents: Optional[Decimal] = None
    unrealized_pnl_cents: Optional[Decimal] = None


class KalshiStrategy:
    """Prediction-market strategy dedicated to Kalshi.

    Evaluates MarketSnapshots and produces StrategySignals.
    """

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        model: Optional[PredictionMarketModel] = None,
    ):
        self.config = config or StrategyConfig()
        self.model = model or PredictionMarketModel()
        self._positions: Dict[str, PositionState] = {}

    # ------------------------------------------------------------------
    # Expiry phase
    # ------------------------------------------------------------------

    def _expiry_phase(self, hours_left: Optional[Decimal]) -> ExpiryPhase:
        if hours_left is None:
            return ExpiryPhase.EARLY
        if hours_left > 24:
            return ExpiryPhase.EARLY
        if hours_left > 4:
            return ExpiryPhase.MID
        if hours_left > 1:
            return ExpiryPhase.LATE
        return ExpiryPhase.TERMINAL

    def _min_edge_for_phase(self, phase: ExpiryPhase) -> Decimal:
        return {
            ExpiryPhase.EARLY: self.config.min_edge_early,
            ExpiryPhase.MID: self.config.min_edge_mid,
            ExpiryPhase.LATE: self.config.min_edge_late,
            ExpiryPhase.TERMINAL: self.config.min_edge_terminal,
        }[phase]

    def _timeframe_rule(self, snapshot: MarketSnapshot) -> Optional[TimeframeEntryRule]:
        tf = (snapshot.timeframe or "").lower()
        return self.config.timeframe_entry_rules.get(tf)

    @staticmethod
    def _required_move_pct(snapshot: MarketSnapshot) -> Optional[Decimal]:
        if snapshot.strike_price is None or snapshot.spot_price is None:
            return None
        try:
            if snapshot.spot_price == 0:
                return None
            dist = abs(snapshot.strike_price - snapshot.spot_price)
            return Decimal(str(dist)) / Decimal(str(snapshot.spot_price))
        except Exception:
            return None

    def _passes_timeframe_rules(
        self, snapshot: MarketSnapshot, edge: EdgeEstimate, phase: ExpiryPhase
    ) -> tuple[bool, Optional[str], Optional[Decimal]]:
        rule = self._timeframe_rule(snapshot)
        if not rule:
            return True, None, None

        minutes_left = float(snapshot.minutes_to_expiry) if snapshot.minutes_to_expiry is not None else None
        if minutes_left is not None and minutes_left < rule.min_minutes_to_expiry:
            return False, (
                f"time_to_expiry {minutes_left:.1f}m < min {rule.min_minutes_to_expiry}m"
            ), rule.min_edge

        min_edge = max(self._min_edge_for_phase(phase), rule.min_edge)

        move_pct = self._required_move_pct(snapshot)
        if (
            move_pct is not None
            and edge.side == "yes"
            and snapshot.market_type == "threshold"
            and move_pct > rule.max_yes_move_pct
        ):
            return False, (
                f"catastrophic_yes: requires move {move_pct:.2%} > {rule.max_yes_move_pct:.2%}"
            ), min_edge

        return True, None, min_edge

    # ------------------------------------------------------------------
    # Position sizing (quarter-Kelly)
    # ------------------------------------------------------------------

    def _kelly_size_with_sentiment(
        self, edge: EdgeEstimate, phase: ExpiryPhase, snapshot: "MarketSnapshot"
    ) -> int:
        """Compute sentiment-adjusted position size.

        Wraps _kelly_size() and applies additional sentiment-based adjustments
        using fear/greed index and volatility regime from MarketSnapshot.

        Args:
            edge: Edge estimate
            phase: Expiry phase
            snapshot: Market snapshot with sentiment data

        Returns:
            Adjusted contract count
        """
        # Get base size from Kelly
        base_size = self._kelly_size(edge, phase)

        if base_size <= 0:
            return 0

        # Apply sentiment adjustments
        sentiment_multiplier = 1.0

        # Fear/Greed index adjustment
        if snapshot.sentiment_global is not None:
            fg_score = snapshot.sentiment_global
            if fg_score <= 20 or fg_score >= 80:
                # Extreme fear/greed: reduce size 50%
                sentiment_multiplier *= 0.5
            elif fg_score <= 30 or fg_score >= 70:
                # Moderate fear/greed: reduce size 25%
                sentiment_multiplier *= 0.75

        # Volatility regime adjustment
        if snapshot.sentiment_regime:
            regime = snapshot.sentiment_regime.lower()
            if "extreme" in regime:
                # Extreme regime: further reduce size
                sentiment_multiplier *= 0.7

        adjusted_size = int(base_size * sentiment_multiplier)
        return max(1, adjusted_size)  # Ensure at least 1 contract if non-zero

    def _kelly_size(self, edge: EdgeEstimate, phase: ExpiryPhase) -> int:
        """Compute position size via PositionSizer (fee-aware, adaptive Kelly).

        Delegates to the singleton PositionSizer which applies:
        - Fractional Kelly with Kalshi fee schedule
        - PF/expectancy scaling gates
        - Drawdown and vol-based adaptive shrinkage
        - Per-underlying hourly exposure caps

        Falls back to a simple inline calculation if the sizer is unavailable.
        """
        try:
            from merid.event_venues.kalshi.position_sizer import get_position_sizer
            sizer = get_position_sizer()

            # Convert edge fields to sizer inputs
            edge_pct = float(edge.net_edge) * 100.0  # fraction → percent
            market_prob = float(edge.market_prob)
            price_cents = max(1, min(99, int(round(market_prob * 100))))

            # Phase-based drawdown proxy: terminal = higher perceived vol
            local_vol_pct = {
                ExpiryPhase.EARLY: 10.0,
                ExpiryPhase.MID: 15.0,
                ExpiryPhase.LATE: 20.0,
                ExpiryPhase.TERMINAL: 35.0,
            }.get(phase, 15.0)

            size = sizer.compute(
                agent_name="strategy",
                edge_pct=edge_pct,
                price_cents=price_cents,
                local_vol_pct=local_vol_pct,
            )
            return min(size, self.config.max_contracts_per_order)
        except Exception as _sze:
            logger.debug("position sizer skipped, using fallback Kelly: %s", _sze)

        # Fallback: simple fractional Kelly (no fee/PF awareness)
        p = edge.model_prob
        q = Decimal("1") - p
        market_prob = edge.market_prob
        if market_prob <= Decimal("0") or market_prob >= Decimal("1"):
            return 0
        b = (Decimal("1") / market_prob) - Decimal("1")
        if b <= Decimal("0"):
            return 0
        kelly = (p * b - q) / b
        if kelly <= Decimal("0"):
            return 0
        fraction = self.config.kelly_fraction
        if phase == ExpiryPhase.EARLY:
            fraction = fraction * Decimal("1.5")
        elif phase == ExpiryPhase.MID:
            fraction = fraction * Decimal("1.2")
        elif phase == ExpiryPhase.TERMINAL:
            fraction = fraction / 2
        raw_size = kelly * fraction * self.config.max_contracts_per_market
        size = int(raw_size.quantize(Decimal("1"), ROUND_HALF_UP))
        return min(size, self.config.max_contracts_per_order)

    # ------------------------------------------------------------------
    # Entry evaluation
    # ------------------------------------------------------------------

    def evaluate(self, snapshot: MarketSnapshot, archetype: str = "directional") -> StrategySignal:
        """Evaluate a market snapshot and produce a signal.

        Decision tree based on archetype:
        - directional: Takes YES/NO positions based on speculative edge.
        - market_maker: Quotes two-sided markets.
        - arbitrage: Specifically looks for cross-market or internal arb.
        """
        phase = self._expiry_phase(snapshot.time_to_expiry_hours)

        # 1. State filter
        if snapshot.state not in (ContractState.TRADING, ContractState.CLOSING):
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=f"Market state is {snapshot.state.value}, not tradeable.",
            )

        # Freshness filter
        if snapshot.timestamp:
            age_s = (datetime.now(timezone.utc) - snapshot.timestamp).total_seconds()
            if age_s > self.config.freshness_max_age_seconds:
                return StrategySignal(
                    market_id=snapshot.market_id,
                    action=SignalAction.NO_ACTION,
                    side="none",
                    contracts=0,
                    phase=phase,
                    reason=f"Snapshot stale ({age_s:.0f}s > {self.config.freshness_max_age_seconds}s).",
                )

        # 2. Liquidity filter
        if snapshot.volume < self.config.min_volume:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=f"Volume {snapshot.volume} below minimum {self.config.min_volume}.",
            )

        if snapshot.open_interest < self.config.min_open_interest:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=f"OI {snapshot.open_interest} below minimum {self.config.min_open_interest}.",
            )

        # Dispatch to archetype handler
        if archetype == "market_maker":
            return self._evaluate_mm(snapshot, phase)
        elif archetype == "arbitrage":
            return self._evaluate_arb(snapshot, phase)
        elif archetype == "contrarian":
            return self._evaluate_contrarian(snapshot, phase)
        elif archetype == "regime_switch":
            return self._evaluate_regime_switch(snapshot, phase)
        elif archetype == "vol_breakout":
            return self._evaluate_vol_breakout(snapshot, phase)
        else:
            return self._evaluate_directional(snapshot, phase)

    def _evaluate_directional(self, snapshot: MarketSnapshot, phase: ExpiryPhase) -> StrategySignal:
        """Standard directional strategy."""
        # 3. Arb check (high priority even for directional)
        arb_edges = [e for e in snapshot.edges if e.edge_type == "arb"]
        if arb_edges:
            best_arb = max(arb_edges, key=lambda e: e.net_edge)
            if best_arb.net_edge >= self.config.min_arb_edge:
                return StrategySignal(
                    market_id=snapshot.market_id,
                    action=SignalAction.BUY_YES,  # arb buys both sides
                    side="both",
                    contracts=self.config.max_contracts_per_order,
                    edge=best_arb,
                    phase=phase,
                    reason=f"Pure arb detected: net edge {best_arb.net_edge:.4f}.",
                )

        # 4. Best speculative edge
        spec_edges = [e for e in snapshot.edges if e.edge_type == "speculative"]
        if not spec_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason="No actionable edge found.",
            )

        best = max(spec_edges, key=lambda e: e.net_edge)

        min_edge_phase = self._min_edge_for_phase(phase)
        allowed_tf, tf_reason, tf_min_edge = self._passes_timeframe_rules(snapshot, best, phase)
        min_edge = max(min_edge_phase, tf_min_edge or min_edge_phase)
        if not allowed_tf:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason=tf_reason or "timeframe_gate",
            )
        if best.net_edge < min_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason=f"Edge {best.net_edge:.4f} below threshold {min_edge}.",
            )

        # Confidence filter
        if best.confidence < self.config.min_confidence:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason=f"Confidence {best.confidence} below minimum {self.config.min_confidence}.",
            )

        # 6. Size (with sentiment adjustment)
        size = self._kelly_size_with_sentiment(best, phase, snapshot)
        if size <= 0:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason="Kelly sizing returned 0 contracts.",
            )

        # Determine action
        if best.action == "buy":
            action = SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO
        else:
            action = SignalAction.SELL_YES if best.side == "yes" else SignalAction.SELL_NO

        # Limit price: use the ask for buys, bid for sells
        limit_cents = None
        if best.side == "yes":
            if best.action == "buy" and snapshot.implied.yes_ask is not None:
                limit_cents = int(snapshot.implied.yes_ask)
            elif best.action == "sell" and snapshot.implied.yes_bid is not None:
                limit_cents = int(snapshot.implied.yes_bid)
        else:
            if best.action == "buy" and snapshot.implied.no_ask is not None:
                limit_cents = int(snapshot.implied.no_ask)
            elif best.action == "sell" and snapshot.implied.no_bid is not None:
                limit_cents = int(snapshot.implied.no_bid)

        return StrategySignal(
            market_id=snapshot.market_id,
            action=action,
            side=best.side,
            contracts=size,
            limit_price_cents=limit_cents,
            edge=best,
            phase=phase,
            reason=f"{phase.value} phase, {best.edge_type} edge {best.net_edge:.4f}, Kelly size {size}.",
        )

    # ------------------------------------------------------------------
    # Sentiment helpers
    # ------------------------------------------------------------------

    def _sentiment_size_multiplier(self, snapshot: MarketSnapshot, action: SignalAction) -> Decimal:
        """Return a 0.5–1.5 multiplier applied to Kelly size based on regime.

        Logic:
          extreme_fear  + buying YES (contrarian long) → 1.3× (fear = discount)
          extreme_greed + buying YES (momentum chase)  → 0.6× (crowded, reduce)
          extreme_greed + buying NO  (fade greed)      → 1.2× (contrarian short)
          fear / greed  (moderate)                     → 1.0× (baseline)
          No sentiment data                            → 1.0×
        """
        regime = snapshot.sentiment_regime
        if not regime:
            return Decimal("1.0")
        buying_yes = action in (SignalAction.BUY_YES,)
        buying_no  = action in (SignalAction.BUY_NO,)
        if regime == "extreme_fear":
            return Decimal("1.3") if buying_yes else Decimal("0.8")
        if regime == "extreme_greed":
            if buying_yes:
                return Decimal("0.6")   # reduce momentum chase
            if buying_no:
                return Decimal("1.2")   # reward contrarian fade
        return Decimal("1.0")

    def _sentiment_edge_floor(self, snapshot: MarketSnapshot, phase: ExpiryPhase) -> Decimal:
        """Raise the minimum edge threshold in extreme regimes (more selective)."""
        base = self._min_edge_for_phase(phase)
        regime = snapshot.sentiment_regime
        if regime in ("extreme_fear", "extreme_greed"):
            return base * Decimal("1.25")   # +25% edge required in extreme regimes
        return base

    # ------------------------------------------------------------------
    # Contrarian archetype
    # ------------------------------------------------------------------

    def _evaluate_contrarian(self, snapshot: MarketSnapshot, phase: ExpiryPhase) -> StrategySignal:
        """Contrarian: only trades when local fear/greed >= 75 AND model disagrees by ≥10pp."""
        local = snapshot.sentiment_local
        if local is None or local < 75:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none", contracts=0, phase=phase,
                reason=f"Contrarian requires local sentiment ≥75; got {local}.",
            )

        spec_edges = [e for e in snapshot.edges if e.edge_type == "speculative"]
        if not spec_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none", contracts=0, phase=phase,
                reason="No speculative edge for contrarian.",
            )

        best = max(spec_edges, key=lambda e: e.net_edge)
        model_gap = abs(float(best.model_prob) - float(best.market_prob))
        if model_gap < 0.10:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Contrarian model gap {model_gap:.2%} < 10pp required.",
            )

        min_edge = self._sentiment_edge_floor(snapshot, phase)
        if best.net_edge < min_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Contrarian edge {best.net_edge:.4f} below floor {min_edge}.",
            )

        size = self._kelly_size(best, phase)
        mult = self._sentiment_size_multiplier(snapshot, SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO)
        size = max(1, int(Decimal(str(size)) * mult))
        size = min(size, self.config.max_contracts_per_order)

        action = SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO
        limit_cents = int(snapshot.implied.yes_ask or 50) if best.side == "yes" else int(snapshot.implied.no_ask or 50)

        return StrategySignal(
            market_id=snapshot.market_id,
            action=action, side=best.side, contracts=size,
            limit_price_cents=limit_cents, edge=best, phase=phase,
            reason=f"Contrarian fade: sentiment={local:.0f}/100 gap={model_gap:.2%} size={size}×{mult}.",
        )

    # ------------------------------------------------------------------
    # Regime-switch archetype
    # ------------------------------------------------------------------

    def _evaluate_regime_switch(self, snapshot: MarketSnapshot, phase: ExpiryPhase) -> StrategySignal:
        """Regime-switch: rides momentum when category sentiment shifts fast (Δ > 20 in session).

        Uses category score as the regime signal; falls back to directional if no shift.
        """
        cat_score = snapshot.sentiment_category
        glob_score = snapshot.sentiment_global
        if cat_score is None:
            return self._evaluate_directional(snapshot, phase)

        # Momentum regime: category is greed/extreme_greed → ride YES momentum
        # Fear regime: category is fear/extreme_fear → ride NO momentum (things going lower)
        regime = snapshot.sentiment_regime or "greed"
        spec_edges = [e for e in snapshot.edges if e.edge_type == "speculative"]
        if not spec_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none", contracts=0, phase=phase,
                reason="No speculative edge for regime-switch.",
            )

        best = max(spec_edges, key=lambda e: e.net_edge)
        min_edge = self._min_edge_for_phase(phase)
        if best.net_edge < min_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Regime-switch edge {best.net_edge:.4f} below threshold.",
            )

        # In greed regime, prefer YES; in fear regime, prefer NO
        if regime in ("greed", "extreme_greed") and best.side != "yes":
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Regime-switch: greed regime, skipping NO-side trade.",
            )
        if regime in ("fear", "extreme_fear") and best.side != "no":
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Regime-switch: fear regime, skipping YES-side trade.",
            )

        size = self._kelly_size(best, phase)
        action = SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO
        mult = self._sentiment_size_multiplier(snapshot, action)
        size = max(1, int(Decimal(str(size)) * mult))
        size = min(size, self.config.max_contracts_per_order)
        limit_cents = int(snapshot.implied.yes_ask or 50) if best.side == "yes" else int(snapshot.implied.no_ask or 50)

        return StrategySignal(
            market_id=snapshot.market_id,
            action=action, side=best.side, contracts=size,
            limit_price_cents=limit_cents, edge=best, phase=phase,
            reason=f"Regime-switch: {regime} cat={cat_score:.0f} glob={glob_score:.0f} size={size}.",
        )

    # ------------------------------------------------------------------
    # Vol-breakout archetype
    # ------------------------------------------------------------------

    def _evaluate_vol_breakout(self, snapshot: MarketSnapshot, phase: ExpiryPhase) -> StrategySignal:
        """Vol-breakout: trades when volatility component is high AND book is imbalanced.

        Scales risk with sentiment intensity — higher score = larger size up to cap.
        """
        local = snapshot.sentiment_local
        if local is None:
            return self._evaluate_directional(snapshot, phase)

        # Require elevated sentiment (either direction) to signal vol breakout
        if 35 <= local <= 65:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none", contracts=0, phase=phase,
                reason=f"Vol-breakout requires sentiment outside 35–65; got {local:.0f}.",
            )

        spec_edges = [e for e in snapshot.edges if e.edge_type == "speculative"]
        if not spec_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none", contracts=0, phase=phase,
                reason="No speculative edge for vol-breakout.",
            )

        best = max(spec_edges, key=lambda e: e.net_edge)
        min_edge = self._min_edge_for_phase(phase)
        if best.net_edge < min_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Vol-breakout edge {best.net_edge:.4f} below threshold.",
            )

        # Scale size by sentiment intensity (distance from 50)
        intensity = abs(local - 50) / 50.0   # 0–1
        size = self._kelly_size(best, phase)
        scaled = max(1, int(size * (1.0 + intensity * 0.5)))   # up to 1.5× at extremes
        scaled = min(scaled, self.config.max_contracts_per_order)

        action = SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO
        limit_cents = int(snapshot.implied.yes_ask or 50) if best.side == "yes" else int(snapshot.implied.no_ask or 50)

        return StrategySignal(
            market_id=snapshot.market_id,
            action=action, side=best.side, contracts=scaled,
            limit_price_cents=limit_cents, edge=best, phase=phase,
            reason=f"Vol-breakout: sentiment={local:.0f} intensity={intensity:.2f} size={scaled}.",
        )

    def _evaluate_mm(self, snapshot: MarketSnapshot, phase: ExpiryPhase) -> StrategySignal:
        """Market Maker strategy: quote bid and ask."""
        # Check spread
        if snapshot.implied.spread_cents is None or snapshot.implied.spread_cents > self.config.mm_max_spread_cents:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=f"Spread {snapshot.implied.spread_cents} exceeds MM limit.",
            )

        # Simple mid-price based quoting
        yes_mid = (snapshot.implied.yes_bid + snapshot.implied.yes_ask) / 2 if snapshot.implied.yes_bid and snapshot.implied.yes_ask else Decimal("50")
        
        # Apply target spread
        half_spread = self.config.mm_target_spread_cents / 2
        bid = int((yes_mid - half_spread).quantize(Decimal("1"), ROUND_HALF_UP))
        ask = int((yes_mid + half_spread).quantize(Decimal("1"), ROUND_HALF_UP))

        # Clamp to 1-99
        bid = max(1, min(98, bid))
        ask = max(bid + 1, min(99, ask))

        return StrategySignal(
            market_id=snapshot.market_id,
            action=SignalAction.QUOTE,
            side="yes",
            contracts=self.config.min_depth_contracts,
            bid_price_cents=bid,
            ask_price_cents=ask,
            phase=phase,
            reason=f"MM quoting {bid}c/{ask}c around mid {yes_mid:.1f}c.",
        )

    def _evaluate_arb(self, snapshot: MarketSnapshot, phase: ExpiryPhase) -> StrategySignal:
        """Arbitrage strategy: specifically focused on mispricings."""
        arb_edges = [e for e in snapshot.edges if e.edge_type == "arb"]
        if not arb_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason="No arb edge detected.",
            )

        best_arb = max(arb_edges, key=lambda e: e.net_edge)
        if best_arb.net_edge < self.config.min_arb_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=f"Arb edge {best_arb.net_edge:.4f} below threshold.",
            )

        return StrategySignal(
            market_id=snapshot.market_id,
            action=SignalAction.BUY_YES, # Arb usually involves both, buy_yes side used as trigger
            side="both",
            contracts=self.config.max_contracts_per_order,
            edge=best_arb,
            phase=phase,
            reason=f"Arb opportunity: {best_arb.net_edge:.4f} edge.",
        )

    # ------------------------------------------------------------------
    # Exit evaluation
    # ------------------------------------------------------------------

    def register_position(self, pos: PositionState) -> None:
        """Register an open position for exit monitoring."""
        self._positions[pos.market_id] = pos

    def remove_position(self, market_id: str) -> None:
        """Remove a closed position."""
        self._positions.pop(market_id, None)

    def evaluate_exits(self, snapshots: Dict[str, MarketSnapshot]) -> List[StrategySignal]:
        """Check all open positions for exit conditions.

        Exit rules:
        - Profit target: unrealized PnL >= profit_target_pct of entry cost.
        - Stop loss: unrealized PnL <= -stop_loss_pct of entry cost.
        - Max hold: position held longer than max_hold_hours.
        - Market closing: force close if state is CLOSING or CLOSED.
        """
        signals: List[StrategySignal] = []

        for mid, pos in list(self._positions.items()):
            snap = snapshots.get(mid)
            if snap is None:
                continue

            phase = self._expiry_phase(snap.time_to_expiry_hours)

            # Update current price
            if pos.side == "yes" and snap.implied.yes_bid is not None:
                pos.current_price_cents = snap.implied.yes_bid
            elif pos.side == "no" and snap.implied.no_bid is not None:
                pos.current_price_cents = snap.implied.no_bid

            if pos.current_price_cents is not None:
                pnl_per_contract = pos.current_price_cents - pos.avg_entry_cents
                pos.unrealized_pnl_cents = pnl_per_contract * pos.contracts

            reason = None

            # Profit target
            if pos.unrealized_pnl_cents is not None:
                entry_cost = pos.avg_entry_cents * pos.contracts
                if entry_cost > 0:
                    pnl_pct = pos.unrealized_pnl_cents / entry_cost
                    if pnl_pct >= self.config.profit_target_pct:
                        reason = f"Profit target hit: {pnl_pct:.2%} >= {self.config.profit_target_pct:.2%}."
                    elif pnl_pct <= -self.config.stop_loss_pct:
                        reason = f"Stop loss hit: {pnl_pct:.2%} <= -{self.config.stop_loss_pct:.2%}."

            # Max hold
            if reason is None:
                hours_held = Decimal(str(
                    (datetime.now(timezone.utc) - pos.opened_at).total_seconds() / 3600
                ))
                if hours_held >= self.config.max_hold_hours:
                    reason = f"Max hold exceeded: {hours_held:.1f}h >= {self.config.max_hold_hours}h."

            # Market closing
            if reason is None and snap.state in (ContractState.CLOSING, ContractState.CLOSED):
                reason = f"Market state is {snap.state.value}, closing position."

            if reason:
                action = SignalAction.SELL_YES if pos.side == "yes" else SignalAction.SELL_NO
                signals.append(StrategySignal(
                    market_id=mid,
                    action=action,
                    side=pos.side,
                    contracts=pos.contracts,
                    phase=phase,
                    reason=reason,
                ))

        return signals

    # ------------------------------------------------------------------
    # Batch evaluation
    # ------------------------------------------------------------------

    def scan_markets(self, snapshots: List[MarketSnapshot]) -> List[StrategySignal]:
        """Evaluate multiple markets and return actionable signals only."""
        signals = []
        for snap in snapshots:
            sig = self.evaluate(snap)
            if sig.action != SignalAction.NO_ACTION:
                signals.append(sig)
        return signals
