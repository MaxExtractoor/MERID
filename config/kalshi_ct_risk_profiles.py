"""Kalshi Continuous Trader — tunable risk profiles (min-edge grid, floors).

Profiles are selected with ``KALSHI_CT_PROFILE``:

- ``modern_tradeable_kalshi_v1`` (PRODUCTION DEFAULT): unified profile with confidence
  bands, fee-aware cent edge, and tiered Kelly. Uses ``crypto_threshold_matrix.yaml``
  schema v2. This is the recommended profile for full-live trading.
- ``production`` (legacy): uses ``MIN_EDGE_GRID`` / ``MIN_EDGE_GLOBAL_FLOOR`` in
  ``merid.event_venues.kalshi.market_filter`` (tight, capital-preservation-first).
- ``initial_live``: permissive thresholds for proving fills and telemetry on a small
  bankroll while keeping Kelly fraction and per-order caps conservative. **Tighten
  back to modern_tradeable_kalshi_v1 once PnL and fee drag look acceptable.**
- ``diagnostic``: low ``min_edge`` for wiring and venue/API health checks. Pair with
  ``KALSHI_TRADER_MAX_POSITION=1``, small bankroll, and dry-run or demo unless you
  explicitly accept tiny live notional.

Recommended environment for full-live trading::

    KALSHI_CT_PROFILE=modern_tradeable_kalshi_v1
    MERID_CRYPTO_EDGE_PRODUCTION_PROFILE=modern_tradeable_kalshi_v1

Legacy environment for initial proving::

    KALSHI_CT_PROFILE=initial_live
    KALSHI_TRADER_MIN_EDGE=0.012
    KALSHI_CT_BIAS_NET_THRESHOLD=0.18
    KALSHI_CT_DIRECTIONAL_MAX_TILT=0.18
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Dict

# ── initial_live: small edge bars (probability points, not Kalshi price bps) ──
# Values are *minimum model–market edge* required at the NearSpotSelector stage.
# Pair with KALSHI_TRADER_MIN_EDGE ≈ 0.012 so bankroll.min_edge_for_price aligns.
INITIAL_LIVE_MIN_EDGE_GRID: Dict[str, Dict[str, Decimal]] = {
    "BTC": {
        "15m": Decimal("0.012"),
        "1h": Decimal("0.010"),
        "daily": Decimal("0.010"),
        "weekly": Decimal("0.010"),
        "monthly": Decimal("0.010"),
        "annual": Decimal("0.012"),
    },
    "ETH": {
        "15m": Decimal("0.014"),
        "1h": Decimal("0.012"),
        "daily": Decimal("0.012"),
        "weekly": Decimal("0.011"),
        "monthly": Decimal("0.011"),
        "annual": Decimal("0.014"),
    },
    "SOL": {
        "15m": Decimal("0.016"),
        "1h": Decimal("0.014"),
        "daily": Decimal("0.014"),
        "weekly": Decimal("0.013"),
        "monthly": Decimal("0.013"),
        "annual": Decimal("0.016"),
    },
    "XRP": {
        "15m": Decimal("0.017"),
        "1h": Decimal("0.015"),
        "daily": Decimal("0.015"),
        "weekly": Decimal("0.014"),
        "monthly": Decimal("0.014"),
        "annual": Decimal("0.017"),
    },
    "DOGE": {
        "15m": Decimal("0.018"),
        "1h": Decimal("0.015"),
        "daily": Decimal("0.015"),
        "weekly": Decimal("0.014"),
        "monthly": Decimal("0.014"),
        "annual": Decimal("0.018"),
    },
}

INITIAL_LIVE_GLOBAL_FLOOR: Decimal = Decimal("0.010")


def active_profile() -> str:
    return os.getenv("KALSHI_CT_PROFILE", "modern_tradeable_kalshi_v1").strip().lower() or "modern_tradeable_kalshi_v1"


def initial_live_min_edge(asset_upper: str, tf_bucket: str) -> Decimal:
    """Return tiered min edge for *initial_live* profile."""
    g = INITIAL_LIVE_MIN_EDGE_GRID.get(asset_upper.upper(), {})
    tiered = g.get(tf_bucket, INITIAL_LIVE_GLOBAL_FLOOR)
    return max(tiered, INITIAL_LIVE_GLOBAL_FLOOR)


def effective_global_min_edge_floor() -> Decimal:
    """Floor used for warnings / consistency checks (TraderConfig vs filter)."""
    prof = active_profile()
    if prof == "initial_live":
        return INITIAL_LIVE_GLOBAL_FLOOR
    if prof == "diagnostic":
        return Decimal(os.getenv("KALSHI_CT_DIAGNOSTIC_MIN_EDGE", "0.008"))
    if prof == "modern_tradeable_kalshi_v1":
        # Uses crypto_threshold_matrix.yaml schema v2 — lowest threshold is BTC 15m = 0.011
        return Decimal("0.011")
    from merid.event_venues.kalshi.market_filter import MIN_EDGE_GLOBAL_FLOOR

    return MIN_EDGE_GLOBAL_FLOOR
