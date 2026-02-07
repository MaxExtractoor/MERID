"""§1 Venue Gate — Mode gating (SIM/PAPER/LIVE) and US-compliance guardrails.

Ensures:
- Only Kalshi is allowed for prediction market trading (US-compliant).
- Polymarket / on-chain venues are blocked at the gate level.
- Trading mode (SIM/PAPER/LIVE) is enforced before any order reaches the adapter.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.venue_gate")

# Venues that are explicitly blocked for US compliance
_BLOCKED_VENUES = frozenset({
    "polymarket", "augur", "predictit", "forecastex",
    "metaculus", "draftkings", "fanduel",
})

_ALLOWED_VENUES = frozenset({"kalshi"})


class TradingMode(str, Enum):
    """Prediction market trading modes."""
    SIM = "sim"        # Simulated fills, no API calls
    PAPER = "paper"    # API calls for data only, simulated fills
    LIVE = "live"      # Real orders on Kalshi


class VenueGate:
    """Enforces venue allow-list and trading mode before orders reach adapters.

    Usage::

        gate = VenueGate()
        gate.check_venue("kalshi")        # OK
        gate.check_venue("polymarket")    # raises VenueBlockedError
        gate.check_can_trade()            # raises if mode is SIM
    """

    class VenueBlockedError(Exception):
        """Raised when a non-US-compliant venue is requested."""

    class ModeBlockedError(Exception):
        """Raised when the current mode does not allow live trading."""

    def __init__(
        self,
        mode: Optional[TradingMode] = None,
        live_enabled: Optional[bool] = None,
    ):
        raw_mode = mode or os.getenv("MERID_PM_TRADING_MODE", "sim")
        if isinstance(raw_mode, str):
            raw_mode = TradingMode(raw_mode.lower())
        self._mode: TradingMode = raw_mode

        if live_enabled is not None:
            self._live_enabled = live_enabled
        else:
            self._live_enabled = os.getenv(
                "MERID_PM_LIVE_ENABLED", "false"
            ).lower() == "true"

        logger.info(
            f"VenueGate initialised: mode={self._mode.value}, live_enabled={self._live_enabled}"
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def mode(self) -> TradingMode:
        return self._mode

    @mode.setter
    def mode(self, value: TradingMode) -> None:
        logger.info(f"VenueGate mode changed: {self._mode.value} -> {value.value}")
        self._mode = value

    @property
    def live_enabled(self) -> bool:
        return self._live_enabled

    @property
    def is_live(self) -> bool:
        return self._mode == TradingMode.LIVE and self._live_enabled

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def check_venue(self, venue: str) -> None:
        """Raise VenueBlockedError if *venue* is not US-compliant."""
        venue_lower = venue.lower()
        if venue_lower in _BLOCKED_VENUES:
            raise self.VenueBlockedError(
                f"Venue '{venue}' is blocked for US compliance. "
                f"Only {sorted(_ALLOWED_VENUES)} are allowed."
            )
        if venue_lower not in _ALLOWED_VENUES:
            raise self.VenueBlockedError(
                f"Unknown prediction market venue '{venue}'. "
                f"Allowed: {sorted(_ALLOWED_VENUES)}."
            )

    def check_can_trade(self) -> None:
        """Raise ModeBlockedError if current mode does not allow order submission."""
        if self._mode == TradingMode.SIM:
            raise self.ModeBlockedError(
                "Trading mode is SIM — no orders will be sent. "
                "Switch to PAPER or LIVE to submit orders."
            )
        if self._mode == TradingMode.LIVE and not self._live_enabled:
            raise self.ModeBlockedError(
                "Trading mode is LIVE but MERID_PM_LIVE_ENABLED is false. "
                "Set MERID_PM_LIVE_ENABLED=true to allow live orders."
            )

    def check_order(self, venue: str) -> None:
        """Combined check: venue allowed AND mode allows trading."""
        self.check_venue(venue)
        self.check_can_trade()

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def should_simulate_fill(self) -> bool:
        """Return True if fills should be simulated (SIM or PAPER mode)."""
        return self._mode in (TradingMode.SIM, TradingMode.PAPER)

    def summary(self) -> dict:
        """Return a JSON-serialisable summary for dashboards."""
        return {
            "mode": self._mode.value,
            "live_enabled": self._live_enabled,
            "is_live": self.is_live,
            "allowed_venues": sorted(_ALLOWED_VENUES),
            "blocked_venues": sorted(_BLOCKED_VENUES),
        }


# Module-level singleton (lazy)
_gate: Optional[VenueGate] = None


def get_venue_gate() -> VenueGate:
    """Return the module-level VenueGate singleton."""
    global _gate
    if _gate is None:
        _gate = VenueGate()
    return _gate
