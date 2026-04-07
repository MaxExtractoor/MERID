"""Aggressively Conservative 15m Kalshi Crypto Strategy.

Profile name: ``kalshi_crypto_15m_conservative``

Assets   : BTC, ETH, SOL, XRP, DOGE
Timeframe: 15m (primary); 1m / 5m / 1h / 4h for context
Goal     : 10–15 high-quality approved trades per hour across all assets.

Design
──────
``Conservative15mStrategy`` is a :class:`~merid.event_venues.kalshi.strategy_grid._CryptoGridStrategy`
subclass wired into ``_STRATEGIES_BY_TIMEFRAME["15m"]``.  It differs from the
baseline ``SpotMomentumStrategy`` in three important ways:

1. **Higher probability bar** — only emits an estimate when the model's
   ``agent_prob`` clears a configurable threshold (default 0.64 for core
   assets, 0.66 for satellites).

2. **HTF/MTF alignment gate** — the estimate is suppressed when the
   higher-timeframe structure score (``multi_tf_alignment`` context key)
   contradicts the signal direction with sufficient strength.

3. **Global rate limiter** — a module-level :class:`GlobalRateTracker`
   singleton counts approved signals across all five 15m agents in a
   rolling 60-minute window.  When the soft target is exceeded, ``min_p``
   is raised dynamically; when the hard cap is breached, the strategy
   returns ``None`` until the window clears.

Config
──────
All thresholds are loaded at first import from
``config/strategies/kalshi_crypto_15m_conservative.yaml`` and cached.
The YAML file can be edited at runtime; call
:func:`reload_conservative_config` to re-read it (or restart the server).

Kill switch
───────────
Set ``enabled: false`` in the YAML and call :func:`reload_conservative_config`
(or restart) to fully disable the profile without any code change.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.strategies.kalshi_crypto_15m_conservative")

# ── Satellite asset set (tighter thresholds) ──────────────────────────────
_SATELLITE_ASSETS = frozenset({"SOL", "XRP", "DOGE"})
_CORE_ASSETS = frozenset({"BTC", "ETH"})

# ── Config loader ─────────────────────────────────────────────────────────

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "config",
    "strategies",
    "kalshi_crypto_15m_conservative.yaml",
)


@dataclass
class Conservative15mConfig:
    """Runtime config for the aggressively conservative 15m profile.

    All fields map 1-to-1 to keys in
    ``config/strategies/kalshi_crypto_15m_conservative.yaml``.
    """

    enabled: bool = True

    # Probability thresholds
    min_p: float = 0.64
    min_p_satellite: float = 0.66
    min_edge_bps: int = 50

    # Rate limits
    soft_target_trades_per_hour: int = 12
    global_max_trades_per_hour: int = 30
    per_asset_max_per_15m: int = 2

    # Sizing
    kelly_fraction: float = 0.125
    max_risk_per_trade_pct: float = 0.25

    # HTF alignment
    htf_alignment_key: str = "multi_tf_alignment"
    htf_alignment_min: float = 0.30
    htf_contradiction_threshold: float = -0.50

    # Dynamic tightening when rate target exceeded
    rate_tighten_delta: float = 0.005

    # Drawdown tightening
    drawdown_warning_pct: float = 3.0
    drawdown_pause_pct: float = 6.0
    drawdown_min_p_delta: float = 0.02
    drawdown_kelly_scale: float = 0.5

    # Liquidity sanity
    min_contract_volume: float = 30.0
    min_contract_oi: float = 5.0
    max_spread_cents: float = 10.0


def _load_config_from_yaml(path: str) -> Conservative15mConfig:
    """Load ``Conservative15mConfig`` from a YAML file.

    Falls back to defaults on any error so that the strategy is never
    silently broken by a bad config file.
    """
    try:
        import yaml  # type: ignore[import]
    except ImportError:
        logger.warning("PyYAML not installed — using default conservative-15m config")
        return Conservative15mConfig()

    try:
        with open(path) as fh:
            raw = yaml.safe_load(fh) or {}
    except (OSError, Exception) as exc:
        logger.warning("Failed to read conservative-15m config %s: %s — using defaults", path, exc)
        return Conservative15mConfig()

    try:
        return Conservative15mConfig(
            enabled=bool(raw.get("enabled", True)),
            min_p=float(raw.get("min_p", 0.64)),
            min_p_satellite=float(raw.get("min_p_satellite", 0.66)),
            min_edge_bps=int(raw.get("min_edge_bps", 50)),
            soft_target_trades_per_hour=int(raw.get("soft_target_trades_per_hour", 12)),
            global_max_trades_per_hour=int(raw.get("global_max_trades_per_hour", 30)),
            per_asset_max_per_15m=int(raw.get("per_asset_max_per_15m", 2)),
            kelly_fraction=float(raw.get("kelly_fraction", 0.125)),
            max_risk_per_trade_pct=float(raw.get("max_risk_per_trade_pct", 0.25)),
            htf_alignment_key=str(raw.get("htf_alignment_key", "multi_tf_alignment")),
            htf_alignment_min=float(raw.get("htf_alignment_min", 0.30)),
            htf_contradiction_threshold=float(raw.get("htf_contradiction_threshold", -0.50)),
            rate_tighten_delta=float(raw.get("rate_tighten_delta", 0.005)),
            drawdown_warning_pct=float(raw.get("drawdown_warning_pct", 3.0)),
            drawdown_pause_pct=float(raw.get("drawdown_pause_pct", 6.0)),
            drawdown_min_p_delta=float(raw.get("drawdown_min_p_delta", 0.02)),
            drawdown_kelly_scale=float(raw.get("drawdown_kelly_scale", 0.5)),
            min_contract_volume=float(raw.get("min_contract_volume", 30.0)),
            min_contract_oi=float(raw.get("min_contract_oi", 5.0)),
            max_spread_cents=float(raw.get("max_spread_cents", 10.0)),
        )
    except (TypeError, ValueError) as exc:
        logger.warning("Malformed conservative-15m config: %s — using defaults", exc)
        return Conservative15mConfig()


# Module-level singleton config (lazy-loaded on first use).
_CONFIG: Optional[Conservative15mConfig] = None
_CONFIG_LOCK = threading.Lock()


def get_conservative_config() -> Conservative15mConfig:
    """Return the module-level config singleton, loading on first call."""
    global _CONFIG
    if _CONFIG is None:
        with _CONFIG_LOCK:
            if _CONFIG is None:
                _CONFIG = _load_config_from_yaml(_CONFIG_PATH)
    return _CONFIG


def reload_conservative_config() -> Conservative15mConfig:
    """Force a config reload from disk.  Thread-safe."""
    global _CONFIG
    with _CONFIG_LOCK:
        _CONFIG = _load_config_from_yaml(_CONFIG_PATH)
    logger.info("Conservative 15m config reloaded from %s", _CONFIG_PATH)
    return _CONFIG


# ── Global rate tracker ───────────────────────────────────────────────────


class GlobalRateTracker:
    """Thread-safe rolling-window trade counter shared across all 15m agents.

    Maintains a deque of ``(timestamp, asset)`` tuples for approved signals
    within the last 60 minutes.  Older entries are pruned on every read.

    Usage::

        tracker = get_rate_tracker()
        if not tracker.is_hard_capped(config):
            tracker.record(asset="BTC")
    """

    _HOUR_WINDOW_SECS: float = 3600.0  # 60-minute rolling window

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Each entry: (unix_timestamp_float, asset_str)
        self._history: Deque[tuple[float, str]] = deque()

    def _prune(self, now_ts: float) -> None:
        """Remove entries older than the rolling window.  Caller must hold lock."""
        cutoff = now_ts - self._HOUR_WINDOW_SECS
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

    def record(self, asset: str, now: Optional[datetime] = None) -> None:
        """Record an approved signal for *asset* at *now* (defaults to UTC now)."""
        ts = (now or datetime.now(timezone.utc)).timestamp()
        with self._lock:
            self._prune(ts)
            self._history.append((ts, asset))

    def count_last_hour(self, now: Optional[datetime] = None) -> int:
        """Return the number of approved signals in the last 60 minutes."""
        ts = (now or datetime.now(timezone.utc)).timestamp()
        with self._lock:
            self._prune(ts)
            return len(self._history)

    def count_last_15m_for_asset(self, asset: str, now: Optional[datetime] = None) -> int:
        """Return the number of approved signals for *asset* in the last 15 minutes."""
        ts = (now or datetime.now(timezone.utc)).timestamp()
        cutoff_15m = ts - 900.0  # 15 minutes
        with self._lock:
            self._prune(ts)
            return sum(1 for (t, a) in self._history if t >= cutoff_15m and a == asset)

    def is_hard_capped(
        self,
        config: Optional[Conservative15mConfig] = None,
        now: Optional[datetime] = None,
    ) -> bool:
        """Return True if the hard cap has been reached or exceeded."""
        cfg = config or get_conservative_config()
        return self.count_last_hour(now) >= cfg.global_max_trades_per_hour

    def is_soft_exceeded(
        self,
        config: Optional[Conservative15mConfig] = None,
        now: Optional[datetime] = None,
    ) -> bool:
        """Return True if the soft target has been exceeded."""
        cfg = config or get_conservative_config()
        return self.count_last_hour(now) >= cfg.soft_target_trades_per_hour

    def excess_over_soft(
        self,
        config: Optional[Conservative15mConfig] = None,
        now: Optional[datetime] = None,
    ) -> int:
        """Return how many trades above the soft target are in the window (≥ 0)."""
        cfg = config or get_conservative_config()
        return max(0, self.count_last_hour(now) - cfg.soft_target_trades_per_hour)

    def dynamic_min_p_increment(
        self,
        asset: str,
        config: Optional[Conservative15mConfig] = None,
        now: Optional[datetime] = None,
    ) -> float:
        """Return the additional min_p increment from rate tightening.

        For each trade over the soft target the increment is
        ``config.rate_tighten_delta``, capped at ``0.05`` (5%).
        """
        cfg = config or get_conservative_config()
        excess = self.excess_over_soft(cfg, now)
        return min(excess * cfg.rate_tighten_delta, 0.05)

    def reset(self) -> None:
        """Clear all history.  Primarily for tests."""
        with self._lock:
            self._history.clear()


# Module-level singleton.
_RATE_TRACKER: Optional[GlobalRateTracker] = None
_TRACKER_LOCK = threading.Lock()


def get_rate_tracker() -> GlobalRateTracker:
    """Return the module-level ``GlobalRateTracker`` singleton."""
    global _RATE_TRACKER
    if _RATE_TRACKER is None:
        with _TRACKER_LOCK:
            if _RATE_TRACKER is None:
                _RATE_TRACKER = GlobalRateTracker()
    return _RATE_TRACKER


# ── DrawdownState ──────────────────────────────────────────────────────────


@dataclass
class DrawdownState:
    """Tracks per-strategy PnL and drawdown for threshold tightening.

    Callers should call :meth:`record_pnl` after each settled trade and
    :meth:`drawdown_pct` before each trade evaluation.
    """

    _peak_bankroll: float = field(default=0.0, repr=False)
    _current_bankroll: float = field(default=0.0, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set_bankroll(self, value: float) -> None:
        """Set absolute bankroll value (and update peak if higher)."""
        with self._lock:
            if value > self._peak_bankroll:
                self._peak_bankroll = value
            self._current_bankroll = value

    def record_pnl(self, pnl_cents: float, bankroll: float) -> None:
        """Update bankroll from a settled trade PnL.

        *pnl_cents* is signed (negative = loss, positive = gain).
        *bankroll* is the new absolute bankroll in cents.
        """
        with self._lock:
            if bankroll > self._peak_bankroll:
                self._peak_bankroll = bankroll
            self._current_bankroll = bankroll

    def drawdown_pct(self) -> float:
        """Return current drawdown from peak as a percentage (≥ 0)."""
        with self._lock:
            if self._peak_bankroll <= 0:
                return 0.0
            loss = self._peak_bankroll - self._current_bankroll
            return max(0.0, loss / self._peak_bankroll * 100.0)

    def is_warning(self, config: Optional[Conservative15mConfig] = None) -> bool:
        cfg = config or get_conservative_config()
        return self.drawdown_pct() >= cfg.drawdown_warning_pct

    def is_pause(self, config: Optional[Conservative15mConfig] = None) -> bool:
        cfg = config or get_conservative_config()
        return self.drawdown_pct() >= cfg.drawdown_pause_pct


# Module-level singleton drawdown state (shared across all 15m agents).
_DRAWDOWN: Optional[DrawdownState] = None
_DRAWDOWN_LOCK = threading.Lock()


def get_drawdown_state() -> DrawdownState:
    """Return the module-level ``DrawdownState`` singleton."""
    global _DRAWDOWN
    if _DRAWDOWN is None:
        with _DRAWDOWN_LOCK:
            if _DRAWDOWN is None:
                _DRAWDOWN = DrawdownState()
    return _DRAWDOWN


# ── Conservative15mStrategy ───────────────────────────────────────────────


def _safe_float(ctx: Dict[str, Any], key: str, default: float = 0.0) -> float:
    """Extract a float from context without raising."""
    try:
        return float(ctx.get(key, default))
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _min_p_for_asset(asset: str, config: Conservative15mConfig) -> float:
    """Return the configured min_p threshold for *asset*."""
    return config.min_p_satellite if asset in _SATELLITE_ASSETS else config.min_p


def _effective_min_p(
    asset: str,
    config: Conservative15mConfig,
    rate_increment: float = 0.0,
    drawdown_increment: float = 0.0,
) -> float:
    """Return the effective min_p after dynamic tightening."""
    base = _min_p_for_asset(asset, config)
    return _clamp(base + rate_increment + drawdown_increment, 0.0, 0.99)


class Conservative15mStrategy:
    """Aggressively conservative 15-minute Kalshi crypto opinion strategy.

    This class is designed to be appended to
    ``_STRATEGIES_BY_TIMEFRAME["15m"]`` in the strategy grid so that the
    trading agent can call it alongside (or instead of) the baseline
    ``SpotMomentumStrategy``.

    What makes it "aggressively conservative"
    ------------------------------------------
    * **High probability bar** — only emits a directional opinion when
      ``agent_prob`` clears a per-asset threshold (0.64–0.66 by default).
    * **HTF alignment gate** — suppresses the opinion when
      ``multi_tf_alignment`` (or the configured key) contradicts the
      signal direction.
    * **Rate-aware tightening** — raises the probability threshold
      dynamically when the global 60-minute approval count exceeds the
      soft target.
    * **Drawdown protection** — tightens or pauses when strategy PnL
      drawdown exceeds configured bands.

    Signal derivation
    -----------------
    Edge is computed from three components (all read from the ``context``
    dict passed by the trading agent):

    1. **Spot momentum** (``spot_return_pct``): recent % price change.
    2. **Orderbook imbalance** (``orderbook_imbalance``): bid/ask depth
       asymmetry in range [-1, 1].
    3. **Structure confluence** (``multi_tf_alignment``): composite
       multi-timeframe alignment score in [-1, 1].  Acts as an amplifier
       when confirming and a suppressor when contradicting.

    Returns ``None`` when:
    * Liquidity is insufficient (inherited gate).
    * Edge is below ``min_edge``.
    * ``agent_prob`` is below the effective ``min_p``.
    * HTF structure strongly contradicts the signal.
    * Global hard cap is reached.
    * Drawdown pause threshold is breached.
    """

    name: str = "conservative_15m"
    min_edge: float = 0.015

    # Weight allocation across the three edge components.
    _MOMENTUM_W: float = 0.45
    _IMBALANCE_W: float = 0.25
    _STRUCTURE_W: float = 0.30

    # Spot return normaliser: ±3% return maps to ±1.0 momentum signal.
    _SPOT_NORMALISER: float = 0.03

    # Maximum edge this strategy will emit (before attenuation).
    _MAX_EDGE: float = 0.09

    def _compute_raw_edge(
        self,
        asset: str,
        context: Dict[str, Any],
        config: Conservative15mConfig,
    ) -> float:
        """Derive a raw directional edge signal.

        Returns a signed float in [-_MAX_EDGE, _MAX_EDGE].
        Positive → bullish (lean YES); negative → bearish (lean NO).
        """
        spot_ret = _safe_float(context, "spot_return_pct", 0.0) / 100.0
        ob_imbalance = _safe_float(context, "orderbook_imbalance", 0.0)
        alignment = _safe_float(context, config.htf_alignment_key, 0.0)

        mom = _clamp(spot_ret / self._SPOT_NORMALISER, -1.0, 1.0)
        ob = _clamp(ob_imbalance, -1.0, 1.0)
        struct = _clamp(alignment, -1.0, 1.0)

        raw = (
            self._MOMENTUM_W * mom
            + self._IMBALANCE_W * ob
            + self._STRUCTURE_W * struct
        )
        return _clamp(raw * self._MAX_EDGE, -self._MAX_EDGE, self._MAX_EDGE)

    def _htf_veto(
        self,
        signal_direction: str,
        context: Dict[str, Any],
        config: Conservative15mConfig,
    ) -> bool:
        """Return True if HTF structure vetoes this signal direction.

        A veto is issued when the alignment score contradicts the signal
        AND the contradiction exceeds the configured threshold.
        """
        alignment = _safe_float(context, config.htf_alignment_key, 0.0)
        # For a YES (bullish) signal, strong negative alignment = veto.
        # For a NO (bearish) signal, strong positive alignment = veto.
        if signal_direction == "yes" and alignment <= config.htf_contradiction_threshold:
            return True
        if signal_direction == "no" and alignment >= -config.htf_contradiction_threshold:
            return True
        return False

    def _htf_insufficient(
        self,
        context: Dict[str, Any],
        config: Conservative15mConfig,
    ) -> bool:
        """Return True when alignment magnitude is below the minimum required."""
        alignment = _safe_float(context, config.htf_alignment_key, 0.0)
        return abs(alignment) < config.htf_alignment_min

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> "Optional[Any]":  # returns Optional[OpinionEstimate]
        """Compute a conservative opinion estimate.

        Returns ``None`` if any gate rejects the signal; otherwise
        returns an ``OpinionEstimate`` annotated with structure metadata.
        """
        # Lazy import to avoid circular dependencies.
        from merid.prediction.opinion_strategy import OpinionEstimate, OpinionExplanation

        ctx = context or {}
        asset: str = ctx.get("asset", "BTC")
        timeframe: str = ctx.get("timeframe", "15m")

        config = get_conservative_config()

        # ── Kill switch ──────────────────────────────────────────────────
        if not config.enabled:
            return None

        # ── Drawdown pause ───────────────────────────────────────────────
        dd = get_drawdown_state()
        if dd.is_pause(config):
            logger.debug(
                "[CONS15M] %s/%s skip=drawdown_pause dd=%.1f%%",
                asset, timeframe, dd.drawdown_pct(),
            )
            return None

        # ── Hard rate cap ────────────────────────────────────────────────
        tracker = get_rate_tracker()
        now = datetime.now(timezone.utc)
        if tracker.is_hard_capped(config, now):
            logger.debug(
                "[CONS15M] %s/%s skip=hard_cap count=%d",
                asset, timeframe, tracker.count_last_hour(now),
            )
            return None

        # ── Per-asset 15m cap ────────────────────────────────────────────
        if tracker.count_last_15m_for_asset(asset, now) >= config.per_asset_max_per_15m:
            logger.debug(
                "[CONS15M] %s/%s skip=per_asset_15m_cap",
                asset, timeframe,
            )
            return None

        # ── Market-prob extremes guard ───────────────────────────────────
        if market_prob < 0.01 or market_prob > 0.99:
            return None

        # ── Volume / OI liquidity gate ────────────────────────────────────
        vol = _safe_float(ctx, "volume", 0.0)
        oi = _safe_float(ctx, "open_interest", 0.0)
        if vol < config.min_contract_volume or oi < config.min_contract_oi:
            logger.debug(
                "[CONS15M] %s skip=low_liquidity vol=%.1f oi=%.1f",
                asset, vol, oi,
            )
            return None

        # ── Compute raw edge ─────────────────────────────────────────────
        raw_edge = self._compute_raw_edge(asset, ctx, config)

        min_edge_frac = config.min_edge_bps / 10_000.0
        if abs(raw_edge) < max(self.min_edge, min_edge_frac):
            return None

        # ── Build agent_prob ─────────────────────────────────────────────
        agent_prob = _clamp(market_prob + raw_edge, 0.01, 0.99)
        edge = agent_prob - market_prob

        # ── Determine signal direction ───────────────────────────────────
        if edge >= 0:
            signal_dir = "yes"
            directional_p = agent_prob        # P(YES)
        else:
            signal_dir = "no"
            directional_p = 1.0 - agent_prob  # P(NO)

        # ── HTF alignment gate ───────────────────────────────────────────
        if self._htf_insufficient(ctx, config):
            logger.debug(
                "[CONS15M] %s/%s skip=htf_insufficient alignment=%.3f",
                asset, timeframe, _safe_float(ctx, config.htf_alignment_key, 0.0),
            )
            return None

        if self._htf_veto(signal_dir, ctx, config):
            logger.debug(
                "[CONS15M] %s/%s skip=htf_veto dir=%s alignment=%.3f",
                asset, timeframe, signal_dir,
                _safe_float(ctx, config.htf_alignment_key, 0.0),
            )
            return None

        # ── Dynamic min_p (rate + drawdown tightening) ──────────────────
        rate_incr = tracker.dynamic_min_p_increment(asset, config, now)
        dd_incr = config.drawdown_min_p_delta if dd.is_warning(config) else 0.0
        effective_min_p = _effective_min_p(asset, config, rate_incr, dd_incr)

        if directional_p < effective_min_p:
            logger.debug(
                "[CONS15M] %s/%s skip=low_p dir=%s p=%.4f min_p=%.4f "
                "(base=%.4f rate_incr=%.4f dd_incr=%.4f)",
                asset, timeframe, signal_dir,
                directional_p, effective_min_p,
                _min_p_for_asset(asset, config), rate_incr, dd_incr,
            )
            return None

        # ── Kelly scale ──────────────────────────────────────────────────
        # Apply drawdown scaling on top of the already-conservative fraction.
        kelly_scale = config.kelly_fraction
        if dd.is_warning(config):
            kelly_scale *= config.drawdown_kelly_scale

        base_confidence = _clamp(0.40 + abs(edge) * 4.0, 0.30, 0.90)
        confidence = _clamp(base_confidence * kelly_scale / 0.25, 0.10, 0.85)
        # (Dividing by 0.25 normalises against the standard 0.25 Kelly so
        # relative confidence is comparable across strategies.)

        # ── Record in rate tracker ────────────────────────────────────────
        # NOTE: We record here (after all gates pass) so that only
        # genuinely approved signals count against the rate limit.
        tracker.record(asset, now)

        # ── Build structured explanation ─────────────────────────────────
        alignment_val = _safe_float(ctx, config.htf_alignment_key, 0.0)
        explanation = OpinionExplanation(
            inputs_used={
                "asset": asset,
                "timeframe": timeframe,
                "market_prob": market_prob,
                "spot_return_pct": _safe_float(ctx, "spot_return_pct", 0.0),
                "orderbook_imbalance": _safe_float(ctx, "orderbook_imbalance", 0.0),
                "htf_alignment": alignment_val,
                "effective_min_p": round(effective_min_p, 4),
                "rate_increment": round(rate_incr, 4),
                "drawdown_increment": round(dd_incr, 4),
                "drawdown_pct": round(dd.drawdown_pct(), 2),
                "trades_last_hour": tracker.count_last_hour(now),
                "kelly_scale": round(kelly_scale, 4),
            },
            contributions={
                "raw_edge": round(raw_edge, 4),
                "structure_alignment": round(alignment_val, 4),
                "directional_p": round(directional_p, 4),
                "min_p_threshold": round(effective_min_p, 4),
            },
            rationale=self.name,
        )

        return OpinionEstimate(
            agent_prob=round(agent_prob, 4),
            confidence=round(confidence, 4),
            edge=round(edge, 4),
            reasoning_tag=self.name,
            signal_sources=[self.name, asset, timeframe, "htf_structure"],
            explanation=explanation,
        )


# Module-level singleton instance (used by strategy_grid.py).
_CONSERVATIVE_15M = Conservative15mStrategy()


def get_conservative_15m_strategy() -> Conservative15mStrategy:
    """Return the module-level ``Conservative15mStrategy`` singleton."""
    return _CONSERVATIVE_15M
