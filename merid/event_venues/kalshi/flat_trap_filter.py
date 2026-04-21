"""Tick-level flat / trap regime filter for the Kalshi scalper chokepoint.

This module is intentionally narrow and dependency-free so it can be
called from any decision path (continuous trader, pre-trade gate,
ad-hoc maker bots) without pulling in the heavier macro regime
machinery under ``merid.event_venues.kalshi.regime_detection`` or the
quality gates under ``merid.event_venues.kalshi.market_filter``.

Two anti-patterns that this filter is designed to catch:

* **Flat** — the midprice has barely moved over the recent window.
  A scalper that keeps trading through a flat has a negative expected
  value after fees: spread + fees > expected move.
* **Trap** — the midprice has reversed direction more than a healthy
  amount of times in the window.  This is the whipsaw / chop regime
  where any directional scalp is likely to hit the stop before the
  target.

Both checks are **pure functions of a recent price series** so the
tests can pin their behaviour exactly without mocks or time.

Usage
-----
::

    from merid.event_venues.kalshi.flat_trap_filter import (
        FlatTrapFilter, FlatTrapConfig,
    )

    f = FlatTrapFilter()
    verdict = f.evaluate([52, 52, 53, 52, 53, 52, 53, 52])  # trap
    if not verdict.tradeable:
        logger.info("[scalper] skipping order: %s", verdict.reason)
        return
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.flat_trap_filter")


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FlatTrapConfig:
    """Tunable thresholds for the flat + trap detectors.

    All fields have sensible defaults calibrated for Kalshi prices
    quoted in integer cents (0..100).  Consumers that work in a
    different unit (e.g. basis points) should scale accordingly.
    """

    # Minimum number of ticks required to make a decision.  Below this
    # the filter is a no-op (``tradeable=True``, ``reason=None``) rather
    # than rejecting everything — insufficient data must not cause a
    # fail-closed cascade that freezes the scalper on fresh markets.
    min_ticks: int = 6

    # --- Flat detection ------------------------------------------------
    # Price range (max - min) over the window, in whole cents.  If the
    # range is at or below this threshold the market is considered flat.
    # 1 cent ≈ one tick on Kalshi; 2c total movement over a window is
    # noise, not signal.
    flat_range_cents: int = 2

    # --- Trap detection ------------------------------------------------
    # Ratio of direction reversals (first-difference sign changes) to
    # the number of non-zero moves in the window.  A reversal rate
    # strictly greater than this threshold is flagged as a trap.
    trap_reversal_rate: float = 0.5

    # Minimum number of reversals required before the reversal-rate
    # check even fires.  Prevents a two-tick series like ``[50, 51, 50]``
    # from tripping the trap guard on insufficient evidence.
    trap_min_reversals: int = 2


# ═══════════════════════════════════════════════════════════════════════════
# Result
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RegimeCheckResult:
    """Outcome of a :meth:`FlatTrapFilter.evaluate` call."""

    tradeable: bool
    reason: Optional[str]
    details: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def ok(cls, **details: float) -> "RegimeCheckResult":
        return cls(tradeable=True, reason=None, details=dict(details))

    @classmethod
    def block(cls, reason: str, **details: float) -> "RegimeCheckResult":
        return cls(tradeable=False, reason=reason, details=dict(details))


# ═══════════════════════════════════════════════════════════════════════════
# Filter
# ═══════════════════════════════════════════════════════════════════════════


class FlatTrapFilter:
    """Evaluate a recent price series for flat / trap regimes.

    Stateless by design — every call is a pure function of the series
    and the config.  Callers that want per-market state (e.g. a sliding
    window) maintain it themselves and pass a snapshot in.
    """

    # ── Observability counters ───────────────────────────────────────
    # Incremented on every ``evaluate`` call so operator dashboards and
    # tests can see *why* the scalper dropped an order without scraping
    # logs.
    #
    # These are instance attributes so two filters running side-by-side
    # (e.g. BTC and ETH lanes) don't share counters.

    def __init__(self, config: Optional[FlatTrapConfig] = None) -> None:
        self.config = config or FlatTrapConfig()
        self.metrics: Dict[str, int] = {
            "evaluated": 0,
            "insufficient_data": 0,
            "tradeable": 0,
            "blocked_flat": 0,
            "blocked_trap": 0,
        }

    # ── Public API ────────────────────────────────────────────────────

    def evaluate(self, prices: Sequence[int]) -> RegimeCheckResult:
        """Classify ``prices`` as tradeable, flat, or trap.

        ``prices`` is expected to be a chronologically-ordered series
        of midprice ticks in integer cents (newest last).  Empty or
        too-short series return ``tradeable=True`` — the filter does
        not fail-closed on sparse data.
        """
        self.metrics["evaluated"] += 1
        cfg = self.config

        n = len(prices)
        if n < cfg.min_ticks:
            self.metrics["insufficient_data"] += 1
            self.metrics["tradeable"] += 1
            return RegimeCheckResult.ok(ticks=n)

        # --- Flat check --------------------------------------------------
        pmin, pmax = min(prices), max(prices)
        price_range = pmax - pmin
        if price_range <= cfg.flat_range_cents:
            self.metrics["blocked_flat"] += 1
            return RegimeCheckResult.block(
                "flat",
                ticks=n,
                price_range=price_range,
                threshold=cfg.flat_range_cents,
            )

        # --- Trap check --------------------------------------------------
        # Reversal = sign change between two consecutive non-zero diffs.
        # Ignore zero diffs because a flat tick is not a direction vote.
        diffs = [prices[i] - prices[i - 1] for i in range(1, n)]
        nonzero = [d for d in diffs if d != 0]
        reversals = 0
        prev_sign = 0
        for d in nonzero:
            sign = 1 if d > 0 else -1
            if prev_sign and sign != prev_sign:
                reversals += 1
            prev_sign = sign

        moves = len(nonzero)
        reversal_rate = (reversals / moves) if moves else 0.0
        if (
            reversals >= cfg.trap_min_reversals
            and reversal_rate > cfg.trap_reversal_rate
        ):
            self.metrics["blocked_trap"] += 1
            return RegimeCheckResult.block(
                "trap",
                ticks=n,
                reversals=reversals,
                moves=moves,
                reversal_rate=reversal_rate,
                threshold=cfg.trap_reversal_rate,
            )

        self.metrics["tradeable"] += 1
        return RegimeCheckResult.ok(
            ticks=n,
            price_range=price_range,
            reversals=reversals,
            reversal_rate=reversal_rate,
        )

    def reset_metrics(self) -> None:
        for k in self.metrics:
            self.metrics[k] = 0
