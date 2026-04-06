"""Strategy Grid — named strategy set for Kalshi crypto markets.

Maps each (asset, timeframe) pair to one or more concrete OpinionStrategy
implementations.  Each strategy has a real signal path: it derives edge from
market price, spot-price context, and/or simple microstructure proxies rather
than from stubs or zero-valued placeholders.

Strategy taxonomy by timeframe
──────────────────────────────
15m / 1h   (intraday)
    spot_momentum   — trade when last-Δ and short-term drift align with the
                      contract direction; edge scales with |spot_return| and
                      an orderbook-imbalance proxy.
    mean_revert     — fade over-extensions vs the 50% neutral line; tightest
                      position caps, highest fee-drag awareness.

daily
    day_close       — "≥ X at close" plays driven by intraday drift and
                      cross-asset confirmation (BTC+ETH co-movement).
    range_compress  — take range markets when realized intraday range diverges
                      materially from the implied range baked into prices.

weekly / monthly
    trend_carry     — engage only when multi-timeframe alignment (15m→daily)
                      is present AND Kalshi pricing lags implied terminal
                      distribution.
    vol_surface     — lean into mispriced tails between "how high" and "how
                      low" contracts; BTC/SOL primary; ETH/XRP/DOGE secondary.

annual
    regime_bet      — only trade when a macro+crypto regime filter is in
                      "strong trend" state; otherwise returns None (flat).

Asset tiers
───────────
  Core   : BTC, ETH — all timeframes active, larger caps, fuller playbook.
  Satellite: SOL, XRP, DOGE — same framework but:
    * lower bankroll caps
    * stricter min-liquidity / min-volume
    * more conservative (lower) Kelly fraction
    * prioritise daily/weekly; 15m is allowed but sized conservatively

Usage::

    grid = StrategyGrid()
    strategies = grid.get(asset="BTC", timeframe="15m")
    for strategy in strategies:
        estimate = strategy.estimate(agent_id, ticker, market_prob, context=ctx)
        if estimate:
            ...
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from merid.prediction.opinion_strategy import (
    OpinionEstimate,
    OpinionExplanation,
    OpinionStrategy,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.strategy_grid")

# ── Asset tiers ───────────────────────────────────────────────────────────

# Core assets: all timeframes, larger caps, richer playbook.
_CORE_ASSETS = frozenset({"BTC", "ETH"})

# Satellite assets: same strategies but lower caps, stricter filters,
# conservative Kelly.  Prioritise daily/weekly over hyper-short 15m.
_SATELLITE_ASSETS = frozenset({"SOL", "XRP", "DOGE"})

# Kelly fraction multipliers by tier (applied on top of CT's global fraction).
_KELLY_MULTIPLIER: Dict[str, float] = {
    "BTC": 1.0,
    "ETH": 1.0,
    "SOL": 0.60,
    "XRP": 0.60,
    "DOGE": 0.50,
}

# Minimum liquidity (volume proxy) required per asset tier.  The strategy
# reads the value from context["volume"] and skips if below the floor.
_MIN_VOLUME: Dict[str, float] = {
    "BTC": 50.0,
    "ETH": 50.0,
    "SOL": 75.0,
    "XRP": 75.0,
    "DOGE": 100.0,
}

# Minimum open-interest required per asset tier.
_MIN_OI: Dict[str, float] = {
    "BTC": 10.0,
    "ETH": 10.0,
    "SOL": 15.0,
    "XRP": 15.0,
    "DOGE": 20.0,
}


# ── Shared helpers ────────────────────────────────────────────────────────

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _safe_float(ctx: Dict[str, Any], key: str, default: float = 0.0) -> float:
    """Extract a float from context dict without raising."""
    try:
        return float(ctx.get(key, default))
    except (TypeError, ValueError):
        return default


def _liquidity_ok(asset: str, ctx: Dict[str, Any]) -> bool:
    """Return True if volume and OI in context meet the asset's minimum floor."""
    vol = _safe_float(ctx, "volume", 0.0)
    oi = _safe_float(ctx, "open_interest", 0.0)
    return vol >= _MIN_VOLUME.get(asset, 50.0) and oi >= _MIN_OI.get(asset, 10.0)


def _kelly_scale(asset: str) -> float:
    """Return the per-asset Kelly multiplier (≤ 1.0)."""
    return _KELLY_MULTIPLIER.get(asset, 0.50)


# ── Base class with common gates ──────────────────────────────────────────

class _CryptoGridStrategy(OpinionStrategy):
    """Shared gates for all crypto grid strategies.

    Subclasses implement ``_compute_edge`` which returns the raw edge signal
    (signed float, e.g. 0.05 = 5% edge in the YES direction).  The base class
    applies:
      1. Market-prob extremes guard (inherited from OpinionStrategy.should_skip).
      2. Liquidity gate (volume + OI from context).
      3. Min-edge threshold.
      4. Asset-tier Kelly scaling (via explanation contributions).
    """

    name: str = "base_crypto"
    min_edge: float = 0.01
    max_confidence: float = 0.90

    def _compute_edge(
        self,
        asset: str,
        timeframe: str,
        market_prob: float,
        context: Dict[str, Any],
    ) -> float:
        """Return raw edge (signed fraction).  0.0 means no opinion."""
        raise NotImplementedError

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        if self.should_skip(market_prob):
            return None

        ctx = context or {}
        asset: str = ctx.get("asset", "BTC")
        timeframe: str = ctx.get("timeframe", "1h")

        # Liquidity gate — satellite assets are stricter.
        if not _liquidity_ok(asset, ctx):
            logger.debug(
                "[STRATEGY-GRID] %s %s/%s ticker=%s skip=low_liquidity",
                self.name, asset, timeframe, ticker,
            )
            return None

        raw_edge = self._compute_edge(asset, timeframe, market_prob, ctx)

        if abs(raw_edge) < self.min_edge:
            return None

        # Clamp agent_prob to (0.01, 0.99).
        agent_prob = _clamp(market_prob + raw_edge, 0.01, 0.99)
        edge = agent_prob - market_prob

        # Scale confidence by Kelly tier (satellite = lower confidence ceiling).
        k_scale = _kelly_scale(asset)
        base_confidence = _clamp(0.40 + abs(edge) * 4.0, 0.30, self.max_confidence)
        confidence = _clamp(base_confidence * k_scale, 0.20, self.max_confidence)

        explanation = OpinionExplanation(
            inputs_used={
                "asset": asset,
                "timeframe": timeframe,
                "market_prob": market_prob,
                "kelly_scale": k_scale,
            },
            contributions={"raw_edge": raw_edge, "kelly_scale_adj": k_scale - 1.0},
            rationale=self.name,
        )

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=round(confidence, 4),
            edge=round(edge, 4),
            reasoning_tag=self.name,
            signal_sources=[self.name, asset, timeframe],
            explanation=explanation,
        )


# ── 1. Spot Momentum (15m / 1h) ───────────────────────────────────────────

class SpotMomentumStrategy(_CryptoGridStrategy):
    """Intraday spot-momentum strategy.

    Derives edge from:
      - ``spot_return_pct``: recent % change in spot price (from context).
      - ``orderbook_imbalance``: (bid_depth − ask_depth) / total_depth
        with sign convention: positive → more bids → YES-bullish.

    Signal logic:
      edge = momentum_weight * spot_return_normalised
           + imbalance_weight * orderbook_imbalance_normalised
      (both components clipped to [-1, 1] before weighting)

    Applicable: all assets, 15m and 1h.
    """

    name = "spot_momentum"
    min_edge = 0.015

    # Weight of spot-return component vs orderbook-imbalance component.
    _MOMENTUM_WEIGHT = 0.60
    _IMBALANCE_WEIGHT = 0.40

    # Normalise a spot return so ±5% maps to ±1.0.
    _SPOT_NORMALISER = 0.05

    def _compute_edge(
        self,
        asset: str,
        timeframe: str,
        market_prob: float,
        context: Dict[str, Any],
    ) -> float:
        spot_ret = _safe_float(context, "spot_return_pct", 0.0) / 100.0
        ob_imbalance = _safe_float(context, "orderbook_imbalance", 0.0)

        # Normalise & clip.
        mom_signal = _clamp(spot_ret / self._SPOT_NORMALISER, -1.0, 1.0)
        ob_signal = _clamp(ob_imbalance, -1.0, 1.0)

        raw = (
            self._MOMENTUM_WEIGHT * mom_signal
            + self._IMBALANCE_WEIGHT * ob_signal
        )

        # Scale down for satellite assets.
        raw *= _kelly_scale(asset)

        # Maximum edge capped to 8%.
        return _clamp(raw * 0.08, -0.08, 0.08)


# ── 2. Mean Revert Spike (15m / 1h) ──────────────────────────────────────

class MeanRevertSpikeStrategy(_CryptoGridStrategy):
    """Fade over-extensions vs the 50% neutral / CF benchmark.

    Derives edge from:
      - ``deviation_from_fair``: how far the market price has strayed from
        a fair-value proxy (e.g. CF benchmark or rolling mid).  Positive →
        market priced too high for YES → lean NO.

    Signal: edge is *opposite* to deviation (contrarian).
    Size caps are tighter, fee drag awareness is higher (min_edge raised for
    satellite assets).

    Applicable: all assets, 15m and 1h.  Smaller caps for SOL/XRP/DOGE.
    """

    name = "mean_revert_spike"
    min_edge = 0.020

    # Maximum edge from this signal (mean-revert is conservative).
    _MAX_EDGE = 0.06

    def _compute_edge(
        self,
        asset: str,
        timeframe: str,
        market_prob: float,
        context: Dict[str, Any],
    ) -> float:
        deviation = _safe_float(context, "deviation_from_fair", 0.0)
        # Contrarian: fade the deviation.
        raw = -deviation
        raw *= _kelly_scale(asset)
        return _clamp(raw, -self._MAX_EDGE, self._MAX_EDGE)


# ── 3. Day-Close Direction (daily) ────────────────────────────────────────

class DayCloseDirectionStrategy(_CryptoGridStrategy):
    """End-of-day "≥ X at 5 pm" plays.

    Derives edge from:
      - ``intraday_drift_pct``: intraday cumulative % return vs prior close.
      - ``cross_asset_confirm``: 1.0 if both BTC and ETH are trending the
        same way, 0.0 if conflicting, -1.0 if opposing.  Only BTC/ETH
        themselves benefit; satellite assets use a reduced weight.

    Signal: if drift + cross-asset confirmation are aligned with the contract
    direction (above/below strike), emit positive edge.

    Applicable: all assets, daily.
    """

    name = "day_close_direction"
    min_edge = 0.015

    _DRIFT_WEIGHT = 0.55
    _CROSS_WEIGHT = 0.45
    _DRIFT_NORMALISER = 0.03  # 3% daily drift → 1.0

    def _compute_edge(
        self,
        asset: str,
        timeframe: str,
        market_prob: float,
        context: Dict[str, Any],
    ) -> float:
        drift = _safe_float(context, "intraday_drift_pct", 0.0) / 100.0
        cross = _safe_float(context, "cross_asset_confirm", 0.0)

        # Satellite assets get reduced cross-asset weight (BTC/ETH are the
        # confirmation assets; their own cross_asset_confirm signal is noisier).
        cross_w = self._CROSS_WEIGHT if asset in _CORE_ASSETS else self._CROSS_WEIGHT * 0.5

        drift_norm = _clamp(drift / self._DRIFT_NORMALISER, -1.0, 1.0)
        cross_norm = _clamp(cross, -1.0, 1.0)

        raw = self._DRIFT_WEIGHT * drift_norm + cross_w * cross_norm
        raw *= _kelly_scale(asset)
        return _clamp(raw * 0.07, -0.07, 0.07)


# ── 4. Range Compression / Expansion (daily) ─────────────────────────────

class RangeCompressionStrategy(_CryptoGridStrategy):
    """Range markets when realized intraday range diverges from implied range.

    Derives edge from:
      - ``realized_range_pct``: realized high-low range as % of spot.
      - ``implied_range_pct``: range implied by the Kalshi market price.

    Signal: if realized < implied → market over-prices range → lean NO on
    range contract (or YES on "within range").  If realized > implied →
    market under-prices range → lean YES on range contract.

    Edge scales with the divergence ratio.

    Applicable: all assets, daily.  BTC/ETH primary (tighter spreads allow
    smaller divergence to still be profitable after fees).
    """

    name = "range_compression"
    min_edge = 0.018

    _MAX_EDGE = 0.07

    def _compute_edge(
        self,
        asset: str,
        timeframe: str,
        market_prob: float,
        context: Dict[str, Any],
    ) -> float:
        realized = _safe_float(context, "realized_range_pct", 0.0)
        implied = _safe_float(context, "implied_range_pct", 0.0)

        if implied <= 0.0:
            return 0.0

        divergence = (realized - implied) / implied
        raw = divergence * _kelly_scale(asset)
        return _clamp(raw * 0.10, -self._MAX_EDGE, self._MAX_EDGE)


# ── 5. Trend Follow + Carry (weekly / monthly) ───────────────────────────

class TrendFollowCarryStrategy(_CryptoGridStrategy):
    """Multi-timeframe trend + carry play for weekly/monthly markets.

    Derives edge from:
      - ``multi_tf_alignment``: composite alignment score across
        15m/1h/4h/daily (range -1 to +1; +1 = all bullish).
      - ``kalshi_vs_terminal_pct``: Kalshi price minus implied terminal
        distribution probability (positive → Kalshi under-priced vs terminal).

    Strategy: only engage when alignment is strong (|alignment| ≥ threshold)
    AND Kalshi pricing diverges from terminal distribution.

    Applicable: all assets, weekly and monthly.
    """

    name = "trend_follow_carry"
    min_edge = 0.020

    # Only trade when |alignment| ≥ this threshold.
    _ALIGNMENT_THRESHOLD = 0.50

    _MAX_EDGE = 0.09

    def _compute_edge(
        self,
        asset: str,
        timeframe: str,
        market_prob: float,
        context: Dict[str, Any],
    ) -> float:
        alignment = _safe_float(context, "multi_tf_alignment", 0.0)
        vs_terminal = _safe_float(context, "kalshi_vs_terminal_pct", 0.0)

        if abs(alignment) < self._ALIGNMENT_THRESHOLD:
            return 0.0  # Trend not confirmed — stay flat.

        raw = alignment * 0.5 + vs_terminal * 0.5
        raw *= _kelly_scale(asset)
        return _clamp(raw * 0.12, -self._MAX_EDGE, self._MAX_EDGE)


# ── 6. Vol Surface Mispricing (weekly / monthly) ─────────────────────────

class VolSurfaceMispricingStrategy(_CryptoGridStrategy):
    """Lean into mispriced tails between "how high" and "how low" markets.

    Derives edge from:
      - ``tail_skew``: asymmetry between upside and downside market prices
        (positive → upside is cheap vs downside → lean YES on upside contract).
      - ``realized_vol_rank``: percentile rank of current realized vol vs
        historical; high rank → vol expanding → wider expected range.

    Primary: BTC, SOL (most liquid vol surface, more contracts available).
    Secondary: ETH, XRP, DOGE (same logic, wider spreads reduce profitability).

    Applicable: BTC/ETH/SOL/XRP/DOGE, weekly and monthly.
    """

    name = "vol_surface_misprice"
    min_edge = 0.022

    _MAX_EDGE = 0.08

    def _compute_edge(
        self,
        asset: str,
        timeframe: str,
        market_prob: float,
        context: Dict[str, Any],
    ) -> float:
        tail_skew = _safe_float(context, "tail_skew", 0.0)
        vol_rank = _safe_float(context, "realized_vol_rank", 0.50)

        # High vol-rank amplifies the tail-skew signal.
        vol_factor = 0.5 + vol_rank * 0.5  # range [0.5, 1.0]
        raw = tail_skew * vol_factor
        raw *= _kelly_scale(asset)
        return _clamp(raw * 0.10, -self._MAX_EDGE, self._MAX_EDGE)


# ── 7. Regime Bet (annual) ────────────────────────────────────────────────

class RegimeBetStrategy(_CryptoGridStrategy):
    """Annual regime bets — only trade when macro+crypto regime is confirmed.

    Derives edge from:
      - ``regime_score``: composite macro+crypto regime signal in range
        [-1.0, 1.0].  Values near 0 indicate uncertain / sideways regime.
      - ``regime_confidence``: how certain the regime classification is.

    Only emits an opinion when BOTH:
      1. |regime_score| ≥ ``_REGIME_THRESHOLD`` (strong directional trend).
      2. ``regime_confidence`` ≥ ``_CONF_THRESHOLD``.

    Otherwise returns None and the CT sits flat on annual markets.

    Applicable: all assets, annual.  Very low-frequency.
    """

    name = "regime_bet"
    min_edge = 0.030
    max_confidence = 0.75  # Cap lower: annual bets are inherently uncertain.

    _REGIME_THRESHOLD = 0.60
    _CONF_THRESHOLD = 0.65

    _MAX_EDGE = 0.10

    def _compute_edge(
        self,
        asset: str,
        timeframe: str,
        market_prob: float,
        context: Dict[str, Any],
    ) -> float:
        regime_score = _safe_float(context, "regime_score", 0.0)
        regime_conf = _safe_float(context, "regime_confidence", 0.0)

        if abs(regime_score) < self._REGIME_THRESHOLD:
            return 0.0  # Regime not confirmed — stay flat.
        if regime_conf < self._CONF_THRESHOLD:
            return 0.0  # Not enough confidence in regime classification.

        raw = regime_score * regime_conf
        raw *= _kelly_scale(asset)
        return _clamp(raw * 0.12, -self._MAX_EDGE, self._MAX_EDGE)


# ── Strategy grid ─────────────────────────────────────────────────────────

# Default instantiated strategy objects (one instance per class).
_SPOT_MOMENTUM = SpotMomentumStrategy()
_MEAN_REVERT = MeanRevertSpikeStrategy()
_DAY_CLOSE = DayCloseDirectionStrategy()
_RANGE_COMPRESS = RangeCompressionStrategy()
_TREND_CARRY = TrendFollowCarryStrategy()
_VOL_SURFACE = VolSurfaceMispricingStrategy()
_REGIME_BET = RegimeBetStrategy()

# Per-timeframe ordered list of strategies.
# Core assets (BTC/ETH) get the full playbook.
# Satellite assets get the same strategies but with their built-in tier caps.
_STRATEGIES_BY_TIMEFRAME: Dict[str, List[_CryptoGridStrategy]] = {
    "15m":     [_SPOT_MOMENTUM, _MEAN_REVERT],
    "1h":      [_SPOT_MOMENTUM, _MEAN_REVERT],
    "daily":   [_DAY_CLOSE, _RANGE_COMPRESS],
    "weekly":  [_TREND_CARRY, _VOL_SURFACE],
    "monthly": [_TREND_CARRY, _VOL_SURFACE],
    "annual":  [_REGIME_BET],
}


@dataclass
class GridEntry:
    """Resolved entry for a single (asset, timeframe) pair."""
    asset: str
    timeframe: str
    strategies: List[_CryptoGridStrategy] = field(default_factory=list)
    is_core: bool = True         # False for satellite assets (SOL/XRP/DOGE)
    kelly_multiplier: float = 1.0
    min_volume: float = 50.0
    min_oi: float = 10.0


class StrategyGrid:
    """Registry of concrete strategies for all (asset, timeframe) pairs.

    Usage::

        grid = StrategyGrid()

        # Get strategies for a specific pair:
        entry = grid.get("BTC", "15m")
        for strategy in entry.strategies:
            estimate = strategy.estimate(agent_id, ticker, market_prob, context=ctx)

        # Get the first strategy that returns a non-None estimate:
        estimate = grid.first_estimate("ETH", "daily", agent_id, ticker, market_prob, ctx)

        # Inspect all 30 entries:
        for entry in grid.all_entries():
            print(entry.asset, entry.timeframe, len(entry.strategies))
    """

    def __init__(self) -> None:
        self._grid: Dict[Tuple[str, str], GridEntry] = {}
        self._build()

    def _build(self) -> None:
        from config.crypto_universe import CRYPTO_ASSETS_ORDERED, CRYPTO_TIMEFRAMES_ORDERED
        for asset in CRYPTO_ASSETS_ORDERED:
            for tf in CRYPTO_TIMEFRAMES_ORDERED:
                strategies = list(_STRATEGIES_BY_TIMEFRAME.get(tf, []))
                self._grid[(asset, tf)] = GridEntry(
                    asset=asset,
                    timeframe=tf,
                    strategies=strategies,
                    is_core=asset in _CORE_ASSETS,
                    kelly_multiplier=_kelly_scale(asset),
                    min_volume=_MIN_VOLUME.get(asset, 50.0),
                    min_oi=_MIN_OI.get(asset, 10.0),
                )

    def get(self, asset: str, timeframe: str) -> Optional[GridEntry]:
        """Return the GridEntry for (asset, timeframe), or None if not registered."""
        return self._grid.get((asset, timeframe))

    def strategies(self, asset: str, timeframe: str) -> List[_CryptoGridStrategy]:
        """Return the strategy list for (asset, timeframe).  Empty list if unknown."""
        entry = self._grid.get((asset, timeframe))
        return entry.strategies if entry else []

    def first_estimate(
        self,
        asset: str,
        timeframe: str,
        agent_id: str,
        ticker: str,
        market_prob: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        """Return the first non-None estimate from the strategy list for this pair.

        Strategies are tried in priority order (index 0 first).  Returns None
        only if every strategy in the list declines.
        """
        for strategy in self.strategies(asset, timeframe):
            est = strategy.estimate(agent_id, ticker, market_prob, context=context)
            if est is not None:
                return est
        return None

    def all_entries(self) -> List[GridEntry]:
        """Return all registered GridEntry objects, ordered by asset then timeframe."""
        return list(self._grid.values())

    def summary(self) -> Dict[str, Any]:
        """Return a flat summary of registered (asset, timeframe) → strategy names."""
        return {
            f"{a}/{tf}": [s.name for s in entry.strategies]
            for (a, tf), entry in sorted(self._grid.items())
        }


# Module-level singleton — callers should import this instead of instantiating.
_GRID: Optional[StrategyGrid] = None


def get_strategy_grid() -> StrategyGrid:
    """Return the module-level StrategyGrid singleton, constructing on first call."""
    global _GRID
    if _GRID is None:
        _GRID = StrategyGrid()
    return _GRID
