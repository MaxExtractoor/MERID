"""
BTC-Anchored Cross-Asset Move Model
====================================
Estimates how each alt-coin (ETH, SOL, XRP, DOGE) co-moves with BTC,
per timeframe, so the trading pipeline can:

  1. Sanity-check strike distance and expected-move assumptions per asset/tf.
  2. Inform the edge model's *expected_move* input based on empirical BTC-anchored
     relationships instead of assuming independent vol.
  3. Dynamically adjust per-asset strike bands when BTC is making large moves.

Model
-----
For each asset A ∈ {ETH, SOL, XRP, DOGE} and timeframe T:

    r_A ≈ α_A,T + β_A,T · r_BTC + ε

    β_A,T = Cov(r_A, r_BTC) / Var(r_BTC)   (OLS slope)
    α_A,T = mean(r_A) - β_A,T · mean(r_BTC) (intercept)

Given current spot prices P_BTC, P_A and a BTC move ΔP_BTC:

    r_BTC  = ΔP_BTC / P_BTC
    ΔP_A   ≈ β_A,T · r_BTC · P_A

Conditional bands: we also bucket BTC moves into magnitude ranges
(e.g. |r_BTC| ∈ [0.5%, 1%), [1%, 2%), [2%, ∞)) and report average/median
alt response in each bucket for non-linear regime awareness.

Usage::

    from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

    model = BtcAnchoredMoveModel()
    model.record_returns({"BTC": 0.003, "ETH": 0.0045, "SOL": 0.005})
    ...  # after enough observations

    snap = model.snapshot("ETH", "15m")
    # snap.beta = 1.52, snap.expected_alt_move_pct(btc_move_pct=0.01) → 0.0152

    dollar = model.expected_dollar_move(
        asset="ETH", btc_delta_usd=250.0,
        btc_spot=84000.0, alt_spot=2100.0, timeframe="15m",
    )
    # dollar ≈ $6.38

Env vars:
    BTC_ANCHOR_WINDOW:       Rolling window size (default 100)
    BTC_ANCHOR_MIN_OBS:      Minimum observations for valid beta (default 20)
    BTC_ANCHOR_CACHE_TTL:    Cache TTL in seconds (default 30)
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.signals.btc_anchored_move")

# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

ANCHOR_ASSET = "BTC"

SUPPORTED_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")

# BTC move magnitude buckets (lower bound inclusive, upper bound exclusive)
# e.g. (0.005, 0.01) = |r_BTC| ∈ [0.5%, 1%)
MOVE_BUCKETS: List[Tuple[float, float]] = [
    (0.0000, 0.0025),  # 0–0.25%  (noise)
    (0.0025, 0.0050),  # 0.25–0.5%
    (0.0050, 0.0100),  # 0.5–1%
    (0.0100, 0.0200),  # 1–2%
    (0.0200, 0.0500),  # 2–5%
    (0.0500, float("inf")),  # 5%+ (extreme)
]

DEFAULT_WINDOW = int(os.getenv("BTC_ANCHOR_WINDOW", "100"))
MIN_OBSERVATIONS = int(os.getenv("BTC_ANCHOR_MIN_OBS", "20"))
CACHE_TTL = float(os.getenv("BTC_ANCHOR_CACHE_TTL", "30"))

# Prior beta estimates (used when insufficient data)
# Source: empirical 15m/1h rolling betas from 2025 crypto data
PRIOR_BETAS: Dict[str, Dict[str, float]] = {
    "ETH": {"15m": 1.15, "1h": 1.20, "daily": 1.25, "weekly": 1.30},
    "SOL": {"15m": 1.40, "1h": 1.50, "daily": 1.55, "weekly": 1.60},
    "XRP": {"15m": 1.10, "1h": 1.25, "daily": 1.35, "weekly": 1.40},
    "DOGE": {"15m": 1.30, "1h": 1.45, "daily": 1.60, "weekly": 1.70},
}

# BTC beta is always 1.0 by definition
PRIOR_BETAS["BTC"] = {"15m": 1.0, "1h": 1.0, "daily": 1.0, "weekly": 1.0}

# Prior alpha (intercept) — assume zero drift on short timeframes
PRIOR_ALPHA: float = 0.0

# ═══════════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class BetaEstimate:
    """OLS regression result: r_A = alpha + beta * r_BTC + epsilon."""
    asset: str
    timeframe: str
    beta: float
    alpha: float
    r_squared: float
    residual_std: float
    sample_count: int
    is_prior: bool  # True if using prior (insufficient data)
    timestamp: float = 0.0

    def expected_alt_move_pct(self, btc_move_pct: float) -> float:
        """Given a BTC % move, predict the alt's % move.

        Args:
            btc_move_pct: BTC return as a fraction (e.g., 0.01 = 1%).

        Returns:
            Expected alt return as a fraction.
        """
        return self.alpha + self.beta * btc_move_pct

    def expected_alt_dollar_move(
        self,
        btc_delta_usd: float,
        btc_spot: float,
        alt_spot: float,
    ) -> float:
        """Given a BTC USD move, predict the alt's USD move.

        Args:
            btc_delta_usd: BTC price change in USD.
            btc_spot: Current BTC price in USD.
            alt_spot: Current alt price in USD.

        Returns:
            Expected alt price change in USD.
        """
        if btc_spot <= 0:
            return 0.0
        r_btc = btc_delta_usd / btc_spot
        r_alt = self.expected_alt_move_pct(r_btc)
        return r_alt * alt_spot

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "beta": round(self.beta, 4),
            "alpha": round(self.alpha, 6),
            "r_squared": round(self.r_squared, 4),
            "residual_std": round(self.residual_std, 6),
            "sample_count": self.sample_count,
            "is_prior": self.is_prior,
        }


@dataclass
class BucketStats:
    """Conditional alt-move statistics for a given BTC move magnitude bucket."""
    bucket_label: str
    bucket_lo: float
    bucket_hi: float
    count: int
    mean_btc_return: float
    mean_alt_return: float
    median_alt_return: float
    std_alt_return: float

    def to_dict(self) -> dict:
        return {
            "bucket": self.bucket_label,
            "count": self.count,
            "mean_btc_pct": round(self.mean_btc_return * 100, 3),
            "mean_alt_pct": round(self.mean_alt_return * 100, 3),
            "median_alt_pct": round(self.median_alt_return * 100, 3),
            "std_alt_pct": round(self.std_alt_return * 100, 3),
        }


@dataclass
class AnchoredSnapshot:
    """Full snapshot for one asset on one timeframe."""
    beta: BetaEstimate
    conditional_bands: List[BucketStats]
    btc_vol_annualized: float = 0.0
    alt_vol_annualized: float = 0.0
    correlation: float = 0.0

    def to_dict(self) -> dict:
        return {
            "beta": self.beta.to_dict(),
            "conditional_bands": [b.to_dict() for b in self.conditional_bands],
            "btc_vol_ann": round(self.btc_vol_annualized, 4),
            "alt_vol_ann": round(self.alt_vol_annualized, 4),
            "correlation": round(self.correlation, 4),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Core Model
# ═══════════════════════════════════════════════════════════════════════════


class BtcAnchoredMoveModel:
    """Rolling BTC-anchored beta regression model for crypto alts.

    Maintains per-timeframe return buffers and computes OLS beta + conditional
    bands on demand.  Thread-safe via internal lock.
    """

    def __init__(self, window: int = DEFAULT_WINDOW, min_obs: int = MIN_OBSERVATIONS):
        self._window = window
        self._min_obs = min_obs

        # returns[timeframe][asset] = List[float]
        self._returns: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._timestamps: Dict[str, List[float]] = defaultdict(list)

        # Cache: (asset, timeframe) -> BetaEstimate
        self._cache: Dict[Tuple[str, str], BetaEstimate] = {}
        self._cache_ts: float = 0.0

        self._lock = threading.Lock()

    # ── Data ingestion ────────────────────────────────────────────────────

    def record_returns(
        self,
        returns: Dict[str, float],
        timeframe: str = "15m",
        ts: Optional[float] = None,
    ) -> None:
        """Record a simultaneous return observation for multiple assets.

        All assets in this call are assumed to share the same time interval.

        Args:
            returns: Dict mapping asset symbol → period return (e.g., {"BTC": 0.003, "ETH": 0.0045}).
            timeframe: Timeframe label (e.g., "15m", "1h", "daily").
            ts: Optional timestamp; defaults to now.
        """
        ts = ts or time.time()
        with self._lock:
            for asset, ret in returns.items():
                asset = asset.upper()
                if asset not in SUPPORTED_ASSETS:
                    continue
                buf = self._returns[timeframe][asset]
                buf.append(ret)
                if len(buf) > self._window:
                    self._returns[timeframe][asset] = buf[-self._window:]

            self._timestamps[timeframe].append(ts)
            if len(self._timestamps[timeframe]) > self._window:
                self._timestamps[timeframe] = self._timestamps[timeframe][-self._window:]

            # Invalidate cache
            self._cache_ts = 0.0

    def record_prices(
        self,
        prices: Dict[str, float],
        timeframe: str = "15m",
        ts: Optional[float] = None,
    ) -> None:
        """Record spot prices and auto-derive returns from previous observation.

        Convenience wrapper: internally stores last price and computes returns
        on second+ calls.
        """
        ts = ts or time.time()
        key = f"_last_price_{timeframe}"
        returns = {}
        with self._lock:
            prev = getattr(self, key, None)
            if prev is not None:
                for asset, price in prices.items():
                    asset = asset.upper()
                    if asset in prev and prev[asset] > 0 and price > 0:
                        returns[asset] = (price - prev[asset]) / prev[asset]
            setattr(self, key, {a.upper(): p for a, p in prices.items()})

        # Record outside lock (record_returns acquires its own lock)
        if returns:
            self.record_returns(returns, timeframe=timeframe, ts=ts)

    # ── Beta estimation ───────────────────────────────────────────────────

    def get_beta(self, asset: str, timeframe: str = "15m") -> BetaEstimate:
        """Get the BTC-anchored beta estimate for an asset on a timeframe.

        Returns prior estimate if insufficient data.
        """
        asset = asset.upper()
        if asset == ANCHOR_ASSET:
            return BetaEstimate(
                asset="BTC", timeframe=timeframe,
                beta=1.0, alpha=0.0, r_squared=1.0,
                residual_std=0.0, sample_count=0,
                is_prior=False, timestamp=time.time(),
            )

        now = time.time()
        key = (asset, timeframe)

        with self._lock:
            # Check cache
            if now - self._cache_ts < CACHE_TTL and key in self._cache:
                return self._cache[key]

            btc_rets = self._returns[timeframe].get(ANCHOR_ASSET, [])
            alt_rets = self._returns[timeframe].get(asset, [])
            n = min(len(btc_rets), len(alt_rets))

            if n < self._min_obs:
                # Fall back to prior
                prior_beta = PRIOR_BETAS.get(asset, {}).get(timeframe, 1.0)
                est = BetaEstimate(
                    asset=asset, timeframe=timeframe,
                    beta=prior_beta, alpha=PRIOR_ALPHA,
                    r_squared=0.0, residual_std=0.0,
                    sample_count=n, is_prior=True,
                    timestamp=now,
                )
                self._cache[key] = est
                self._cache_ts = now
                return est

            # OLS: beta = Cov(r_A, r_BTC) / Var(r_BTC)
            xb = btc_rets[-n:]
            xa = alt_rets[-n:]

            mean_b = sum(xb) / n
            mean_a = sum(xa) / n

            cov_ab = sum((xa[i] - mean_a) * (xb[i] - mean_b) for i in range(n)) / n
            var_b = sum((x - mean_b) ** 2 for x in xb) / n

            if var_b < 1e-18:
                beta = PRIOR_BETAS.get(asset, {}).get(timeframe, 1.0)
                est = BetaEstimate(
                    asset=asset, timeframe=timeframe,
                    beta=beta, alpha=0.0, r_squared=0.0,
                    residual_std=0.0, sample_count=n,
                    is_prior=True, timestamp=now,
                )
                self._cache[key] = est
                self._cache_ts = now
                return est

            beta = cov_ab / var_b
            alpha = mean_a - beta * mean_b

            # R² = 1 - SS_res / SS_tot
            ss_res = sum((xa[i] - (alpha + beta * xb[i])) ** 2 for i in range(n))
            ss_tot = sum((x - mean_a) ** 2 for x in xa)
            r_sq = 1.0 - ss_res / ss_tot if ss_tot > 1e-18 else 0.0
            r_sq = max(0.0, min(1.0, r_sq))

            resid_std = math.sqrt(ss_res / max(n - 2, 1)) if n > 0 else 0.0

            est = BetaEstimate(
                asset=asset, timeframe=timeframe,
                beta=beta, alpha=alpha,
                r_squared=r_sq, residual_std=resid_std,
                sample_count=n, is_prior=False,
                timestamp=now,
            )
            self._cache[key] = est
            self._cache_ts = now
            return est

    # ── Conditional bands ─────────────────────────────────────────────────

    def get_conditional_bands(
        self, asset: str, timeframe: str = "15m"
    ) -> List[BucketStats]:
        """Compute conditional alt-move distribution by BTC move magnitude.

        Buckets BTC returns by absolute magnitude and reports average/median
        alt response in each bucket.
        """
        asset = asset.upper()
        with self._lock:
            btc_rets = self._returns[timeframe].get(ANCHOR_ASSET, [])
            alt_rets = self._returns[timeframe].get(asset, [])

        n = min(len(btc_rets), len(alt_rets))
        if n < 5:
            return []

        xb = btc_rets[-n:]
        xa = alt_rets[-n:]

        results: List[BucketStats] = []
        for lo, hi in MOVE_BUCKETS:
            # Select observations where |r_BTC| falls in this bucket
            indices = [
                i for i in range(n)
                if lo <= abs(xb[i]) < hi
            ]
            if not indices:
                label = _bucket_label(lo, hi)
                results.append(BucketStats(
                    bucket_label=label, bucket_lo=lo, bucket_hi=hi,
                    count=0, mean_btc_return=0.0,
                    mean_alt_return=0.0, median_alt_return=0.0,
                    std_alt_return=0.0,
                ))
                continue

            btc_sub = [xb[i] for i in indices]
            alt_sub = [xa[i] for i in indices]

            mean_btc = sum(btc_sub) / len(btc_sub)
            mean_alt = sum(alt_sub) / len(alt_sub)
            sorted_alt = sorted(alt_sub)
            median_alt = sorted_alt[len(sorted_alt) // 2]
            std_alt = math.sqrt(
                sum((x - mean_alt) ** 2 for x in alt_sub) / len(alt_sub)
            ) if len(alt_sub) > 1 else 0.0

            label = _bucket_label(lo, hi)
            results.append(BucketStats(
                bucket_label=label, bucket_lo=lo, bucket_hi=hi,
                count=len(indices),
                mean_btc_return=mean_btc,
                mean_alt_return=mean_alt,
                median_alt_return=median_alt,
                std_alt_return=std_alt,
            ))

        return results

    # ── Full snapshot ─────────────────────────────────────────────────────

    def snapshot(self, asset: str, timeframe: str = "15m") -> AnchoredSnapshot:
        """Get a full anchored snapshot for one asset/timeframe.

        Includes beta estimate, conditional bands, realized vols, and correlation.
        """
        asset = asset.upper()
        beta = self.get_beta(asset, timeframe)
        bands = self.get_conditional_bands(asset, timeframe)

        # Realized vols
        with self._lock:
            btc_rets = self._returns[timeframe].get(ANCHOR_ASSET, [])
            alt_rets = self._returns[timeframe].get(asset, [])

        btc_vol = _annualize_vol(btc_rets, timeframe)
        alt_vol = _annualize_vol(alt_rets, timeframe)
        corr = _pearson(btc_rets, alt_rets)

        return AnchoredSnapshot(
            beta=beta,
            conditional_bands=bands,
            btc_vol_annualized=btc_vol,
            alt_vol_annualized=alt_vol,
            correlation=corr,
        )

    # ── Convenience methods ───────────────────────────────────────────────

    def expected_dollar_move(
        self,
        asset: str,
        btc_delta_usd: float,
        btc_spot: float,
        alt_spot: float,
        timeframe: str = "15m",
    ) -> float:
        """Predict the alt's USD move given a BTC USD move.

        Args:
            asset: Alt asset symbol (e.g., "ETH").
            btc_delta_usd: BTC price change in USD (e.g., +250.0).
            btc_spot: Current BTC spot price in USD.
            alt_spot: Current alt spot price in USD.
            timeframe: Timeframe to use for beta lookup.

        Returns:
            Expected alt price change in USD.
        """
        beta = self.get_beta(asset, timeframe)
        return beta.expected_alt_dollar_move(btc_delta_usd, btc_spot, alt_spot)

    def expected_pct_move(
        self,
        asset: str,
        btc_move_pct: float,
        timeframe: str = "15m",
    ) -> float:
        """Predict the alt's % move given a BTC % move.

        Args:
            asset: Alt asset symbol (e.g., "SOL").
            btc_move_pct: BTC return as fraction (e.g., 0.01 = 1%).
            timeframe: Timeframe for beta lookup.

        Returns:
            Expected alt return as fraction.
        """
        beta = self.get_beta(asset, timeframe)
        return beta.expected_alt_move_pct(btc_move_pct)

    def adjusted_expected_move(
        self,
        asset: str,
        timeframe: str,
        base_expected_move: float,
        btc_return_current: float,
    ) -> float:
        """Adjust the edge model's expected_move using BTC-anchored beta.

        When the edge model computes expected_move from per-asset realized vol,
        this method blends in the BTC-anchored expectation for a more accurate
        estimate.

        Formula:
            adjusted = w * (β * r_BTC * P_A/P_A) + (1-w) * base_expected_move

        where w = min(R², 0.7) so we only lean on the beta as much as it explains.

        Args:
            asset: Alt asset symbol.
            timeframe: Timeframe label.
            base_expected_move: The current expected_move from independent vol model.
            btc_return_current: BTC's return for the current period.

        Returns:
            Blended expected move (as fraction of alt price).
        """
        beta_est = self.get_beta(asset, timeframe)

        if beta_est.is_prior or beta_est.r_squared < 0.1:
            # Insufficient data or poor fit — don't adjust
            return base_expected_move

        # Weight = capped R² (don't over-lean on beta)
        w = min(beta_est.r_squared, 0.70)

        btc_implied_move = abs(beta_est.beta * btc_return_current)
        adjusted = w * btc_implied_move + (1.0 - w) * base_expected_move

        return max(adjusted, base_expected_move * 0.5)  # Floor at 50% of base

    def suggested_strike_distance_pct(
        self,
        asset: str,
        timeframe: str,
        btc_atr_pct: float,
        base_distance_pct: float,
    ) -> float:
        """Suggest a strike distance band that accounts for BTC-anchored moves.

        When BTC ATR is elevated, alts with high beta should have wider bands.

        Args:
            asset: Alt asset symbol.
            timeframe: Timeframe label.
            btc_atr_pct: BTC's ATR as a fraction of price.
            base_distance_pct: The current static strike distance band.

        Returns:
            Suggested strike distance as fraction (e.g., 0.05 = 5%).
        """
        beta_est = self.get_beta(asset, timeframe)

        # Expected alt ATR = β * BTC_ATR
        alt_atr_implied = beta_est.beta * btc_atr_pct

        # Use the larger of base distance and 2× implied alt ATR
        suggested = max(base_distance_pct, 2.0 * alt_atr_implied)

        # Cap at 3× base to avoid runaway widening
        capped = min(suggested, 3.0 * base_distance_pct)

        return capped

    def all_betas_snapshot(self, timeframe: str = "15m") -> Dict[str, dict]:
        """Get beta estimates for all supported assets on a timeframe."""
        result = {}
        for asset in SUPPORTED_ASSETS:
            result[asset] = self.get_beta(asset, timeframe).to_dict()
        return result

    @property
    def observation_counts(self) -> Dict[str, Dict[str, int]]:
        """Return observation counts per (timeframe, asset)."""
        with self._lock:
            result: Dict[str, Dict[str, int]] = {}
            for tf, asset_map in self._returns.items():
                result[tf] = {a: len(v) for a, v in asset_map.items()}
            return result

    def reset(self) -> None:
        """Clear all stored data and cache."""
        with self._lock:
            self._returns.clear()
            self._timestamps.clear()
            self._cache.clear()
            self._cache_ts = 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

_TF_PERIODS_PER_YEAR: Dict[str, float] = {
    "15m": 365.25 * 24 * 4,     # ~35,064
    "1h": 365.25 * 24,           # ~8,766
    "daily": 365.25,
    "weekly": 52.18,
}


def _annualize_vol(returns: List[float], timeframe: str) -> float:
    """Compute annualized volatility from a return series."""
    if len(returns) < 5:
        return 0.0
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    if var <= 0:
        return 0.0
    periods = _TF_PERIODS_PER_YEAR.get(timeframe, 365.25 * 24)
    return math.sqrt(var * periods)


def _pearson(xs: List[float], ys: List[float]) -> float:
    """Pearson correlation between two series (tail-aligned)."""
    n = min(len(xs), len(ys))
    if n < 5:
        return 0.0
    xa = xs[-n:]
    ya = ys[-n:]
    mx = sum(xa) / n
    my = sum(ya) / n
    cov = sum((xa[i] - mx) * (ya[i] - my) for i in range(n)) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xa) / n)
    sy = math.sqrt(sum((y - my) ** 2 for y in ya) / n)
    if sx < 1e-15 or sy < 1e-15:
        return 0.0
    return max(-1.0, min(1.0, cov / (sx * sy)))


def _bucket_label(lo: float, hi: float) -> str:
    """Human-readable label for a BTC move magnitude bucket."""
    lo_pct = lo * 100
    if hi == float("inf"):
        return f"{lo_pct:.1f}%+"
    hi_pct = hi * 100
    return f"{lo_pct:.2f}–{hi_pct:.1f}%"


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════

_model: Optional[BtcAnchoredMoveModel] = None
_model_lock = threading.Lock()


def get_btc_anchored_model() -> BtcAnchoredMoveModel:
    """Get or create the singleton BtcAnchoredMoveModel."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = BtcAnchoredMoveModel()
                logger.info(
                    "BtcAnchoredMoveModel initialized (window=%d, min_obs=%d)",
                    DEFAULT_WINDOW, MIN_OBSERVATIONS,
                )
    return _model
