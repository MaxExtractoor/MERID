"""DrawdownZoneManager — portfolio-level drawdown zone classification and sizing.

Implements a 4-zone drawdown model for BTC/ETH/SOL/XRP/DOGE across all
configured timeframes (15m, 1h, 4h, 1d).  The zones replace the old single
10% brick-wall halt with a graduated response:

  Green  (0 – YELLOW):   Full normal sizing (multiplier 1.0).
  Yellow (YELLOW – SOFT): Scale sizes by 0.50–0.75 (multiplier 0.625 default).
  Orange (SOFT – HARD):   Aggressively defensive, 0.25–0.33 sizing (0.30 default).
  Red    (> HARD):        drawdown_halt_active = True; no new risk-adding orders.

The thresholds are stored in a central ``DrawdownConfig`` that can be tuned
per-asset and per-timeframe.  A single portfolio-level ``DrawdownZoneManager``
singleton is the canonical source-of-truth for all agents.

Usage::

    from merid.risk.drawdown_zones import get_drawdown_zone_manager, DrawdownZone

    mgr = get_drawdown_zone_manager()
    zone = mgr.classify(current_drawdown=0.12)  # DrawdownZone.YELLOW
    mult = mgr.size_multiplier(current_drawdown=0.12)  # 0.625
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported assets and timeframes (mirrors btc_promotion_config)
# ---------------------------------------------------------------------------
SUPPORTED_ASSETS = frozenset({"BTC", "ETH", "SOL", "XRP", "DOGE"})
SUPPORTED_TIMEFRAMES = frozenset({"15m", "1h", "4h", "1d"})


# ---------------------------------------------------------------------------
# Drawdown zones
# ---------------------------------------------------------------------------

class DrawdownZone(str, Enum):
    """Portfolio-level drawdown zone.

    GREEN  — Normal operation; full-size trading.
    YELLOW — Caution; reduced sizes (50–75% of normal).
    ORANGE — Defensive; minimum viable sizes (25–33% of normal).
    RED    — Hard halt; no new risk-adding orders.
    """
    GREEN = "green"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Default thresholds (portfolio-level); can be overridden per-asset/timeframe.
MAX_DRAWDOWN_GREEN: float = 0.10   # 0–10%: full normal sizing
MAX_DRAWDOWN_SOFT: float = 0.15    # 10–15%: yellow (soft limit)
MAX_DRAWDOWN_HARD: float = 0.20    # 15–20%: orange; >20%: red (hard halt)

# Profit-lock defaults
LOCK_FRACTION: float = 0.60          # Lock 60% of session peak realized P&L
MAX_GIVEBACK_FRACTION: float = 0.40  # Allow at most 40% of locked profit to be given back


@dataclass
class DrawdownConfig:
    """Per-lane drawdown configuration.

    Thresholds are expressed as fractions (0.0–1.0), not percentages.
    """
    # Zone thresholds
    green_pct: float = MAX_DRAWDOWN_GREEN   # Green → Yellow boundary
    soft_pct: float = MAX_DRAWDOWN_SOFT     # Yellow → Orange boundary (MAX_DRAWDOWN_SOFT)
    hard_pct: float = MAX_DRAWDOWN_HARD     # Orange → Red boundary (MAX_DRAWDOWN_HARD)

    # Size multipliers per zone
    mult_green: float = 1.00    # Green: full normal sizing
    mult_yellow: float = 0.625  # Yellow: 50–75%; use midpoint 62.5%
    mult_orange: float = 0.30   # Orange: 25–33%; use ~30%
    mult_red: float = 0.00      # Red: halt — no new risk-adding orders

    # Profit-lock
    lock_fraction: float = LOCK_FRACTION
    max_giveback_fraction: float = MAX_GIVEBACK_FRACTION


@dataclass
class CryptoRiskMatrix:
    """Central risk matrix for BTC/ETH/SOL/XRP/DOGE × timeframe.

    Provides a single-stop configuration point to tune all risk parameters.
    All assets share the same DrawdownConfig by default; override individual
    entries via ``asset_overrides`` or ``timeframe_overrides`` as needed.
    """
    default: DrawdownConfig = field(default_factory=DrawdownConfig)

    # Optional per-asset overrides (asset → DrawdownConfig)
    asset_overrides: Dict[str, DrawdownConfig] = field(default_factory=dict)

    # Optional per-timeframe overrides (timeframe → DrawdownConfig)
    timeframe_overrides: Dict[str, DrawdownConfig] = field(default_factory=dict)

    def get(self, asset: Optional[str] = None, timeframe: Optional[str] = None) -> DrawdownConfig:
        """Return the most specific DrawdownConfig for the given (asset, timeframe) pair.

        Priority: asset_override > timeframe_override > default.
        """
        if asset and asset in self.asset_overrides:
            return self.asset_overrides[asset]
        if timeframe and timeframe in self.timeframe_overrides:
            return self.timeframe_overrides[timeframe]
        return self.default


# ---------------------------------------------------------------------------
# Zone manager
# ---------------------------------------------------------------------------

class DrawdownZoneManager:
    """Classify portfolio drawdown into zones and return sizing multipliers.

    This is the canonical portfolio-level gate.  Individual agents should call
    ``size_multiplier()`` to get their zone-based size reduction factor and
    combine it with the profit-lock multiplier from ``ProfitLockEngine``.
    """

    def __init__(self, matrix: Optional[CryptoRiskMatrix] = None) -> None:
        self._matrix = matrix or CryptoRiskMatrix()
        self._current_zone: DrawdownZone = DrawdownZone.GREEN
        self._current_drawdown: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────

    def classify(
        self,
        current_drawdown: float,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> DrawdownZone:
        """Classify the current drawdown into a zone.

        Args:
            current_drawdown: Peak-to-trough drawdown as a fraction (0.0–1.0).
            asset:            Optional asset filter (uses asset_override if set).
            timeframe:        Optional timeframe filter.

        Returns:
            DrawdownZone enum value.
        """
        cfg = self._matrix.get(asset, timeframe)
        dd = max(0.0, float(current_drawdown))

        if dd >= cfg.hard_pct:
            zone = DrawdownZone.RED
        elif dd >= cfg.soft_pct:
            zone = DrawdownZone.ORANGE
        elif dd >= cfg.green_pct:
            zone = DrawdownZone.YELLOW
        else:
            zone = DrawdownZone.GREEN

        # Log zone transitions
        if zone != self._current_zone:
            logger.warning(
                "[DrawdownZones] Zone change: %s → %s  (dd=%.1f%%  thresholds="
                "green=%.0f%% soft=%.0f%% hard=%.0f%%)",
                self._current_zone.value, zone.value,
                dd * 100,
                cfg.green_pct * 100, cfg.soft_pct * 100, cfg.hard_pct * 100,
            )
            self._current_zone = zone

        self._current_drawdown = dd
        return zone

    def size_multiplier(
        self,
        current_drawdown: float,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> float:
        """Return the zone-based sizing multiplier for the given drawdown level.

        Returns a value in [0.0, 1.0]:
          GREEN  → 1.00
          YELLOW → 0.625 (configurable)
          ORANGE → 0.30  (configurable)
          RED    → 0.00  (halt)
        """
        cfg = self._matrix.get(asset, timeframe)
        zone = self.classify(current_drawdown, asset=asset, timeframe=timeframe)
        return {
            DrawdownZone.GREEN: cfg.mult_green,
            DrawdownZone.YELLOW: cfg.mult_yellow,
            DrawdownZone.ORANGE: cfg.mult_orange,
            DrawdownZone.RED: cfg.mult_red,
        }[zone]

    def get_status(self) -> dict:
        """Return a status dict for dashboards."""
        cfg = self._matrix.default
        return {
            "current_zone": self._current_zone.value,
            "current_drawdown_pct": round(self._current_drawdown * 100, 2),
            "thresholds": {
                "green_pct": cfg.green_pct,
                "soft_pct": cfg.soft_pct,
                "hard_pct": cfg.hard_pct,
            },
            "multipliers": {
                "green": cfg.mult_green,
                "yellow": cfg.mult_yellow,
                "orange": cfg.mult_orange,
                "red": cfg.mult_red,
            },
        }

    @property
    def current_zone(self) -> DrawdownZone:
        return self._current_zone

    @property
    def matrix(self) -> CryptoRiskMatrix:
        return self._matrix


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager: Optional[DrawdownZoneManager] = None


def get_drawdown_zone_manager() -> DrawdownZoneManager:
    """Return the process-level DrawdownZoneManager singleton."""
    global _manager
    if _manager is None:
        _manager = DrawdownZoneManager()
    return _manager
