"""§1 Venue Gate — Mode gating (SIM/PAPER/LIVE) and US-compliance guardrails.

Ensures:
- Only Kalshi is allowed for prediction market trading (US-compliant).
- Polymarket / on-chain venues are blocked at the gate level.
- Trading mode (SIM/PAPER/LIVE) is enforced before any order reaches the adapter.
"""

from __future__ import annotations

import threading
import os
from typing import Optional

from trading.trade_mode import TradeMode
from utils.logger import get_logger

logger = get_logger("merid.prediction.venue_gate")

# Venues that are explicitly blocked for US compliance
_BLOCKED_VENUES = frozenset({
    "polymarket", "augur", "predictit", "forecastex",
    "metaculus", "draftkings", "fanduel",
})

_ALLOWED_VENUES = frozenset({"kalshi"})


# Use canonical TradingMode from merid.prediction.trading_mode
from merid.prediction.trading_mode import TradingMode


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
        if mode is None:
            try:
                from merid.settings import settings
                raw_mode_str = settings.MERID_PM_TRADING_MODE
            except Exception as _se:
                logger.debug("VenueGate: settings unavailable for mode, using env: %s", _se)
                raw_mode_str = os.getenv("MERID_PM_TRADING_MODE", "mock")
            # CRITICAL FIX: Validate trading mode is valid
            valid_modes = ["mock", "paper", "live", "sim"]
            if raw_mode_str.lower() not in valid_modes:
                logger.warning(
                    "VenueGate: Invalid MERID_PM_TRADING_MODE=%s - using default 'mock'",
                    raw_mode_str
                )
                raw_mode_str = "mock"
            val = raw_mode_str.lower()
            if val == "sim":
                val = "mock"  # legacy alias
            raw_mode = TradingMode(val)
        else:
            raw_mode = mode
            if isinstance(raw_mode, str):
                val = raw_mode.lower()
                if val == "sim":
                    val = "mock"
                raw_mode = TradingMode(val)
        self._mode: TradingMode = raw_mode

        if live_enabled is not None:
            self._live_enabled = live_enabled
        else:
            try:
                from merid.settings import settings
                self._live_enabled = settings.MERID_PM_LIVE_ENABLED
            except Exception as _se:
                logger.debug("VenueGate: settings unavailable for live_enabled, using env: %s", _se)
                self._live_enabled = os.getenv(
                    "MERID_PM_LIVE_ENABLED", "false"
                ).lower() == "true"

        # SAFETY: MERID_ALLOW_LIVE_TRADES must be set for LIVE (shared with
        # trading.trade_mode.get_trade_mode initial resolution and set_trade_mode).
        if self._mode == TradingMode.LIVE:
            # Check settings first, then env var
            try:
                from merid.settings import settings
                allow_live = str(settings.MERID_ALLOW_LIVE_TRADES).lower()
            except Exception:
                allow_live = os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower()
            if allow_live not in ("1", "true", "yes", "on"):
                logger.warning(
                    "VenueGate: mode resolved to LIVE but MERID_ALLOW_LIVE_TRADES is not set — "
                    "forcing PAPER mode for safety"
                )
                self._mode = TradingMode.PAPER
                self._live_enabled = False

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
        # BUG-S fix: apply the same MERID_ALLOW_LIVE_TRADES guard that the
        # constructor enforces — direct setter calls previously bypassed it.
        if value == TradingMode.LIVE:
            # Check settings first, then env var
            try:
                from merid.settings import settings
                allow_live = str(settings.MERID_ALLOW_LIVE_TRADES).lower()
            except Exception:
                allow_live = os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower()
            if allow_live not in ("1", "true", "yes", "on"):
                logger.warning(
                    "VenueGate.mode setter: refusing LIVE — MERID_ALLOW_LIVE_TRADES not set, "
                    "keeping %s",
                    self._mode.value,
                )
                return
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
        if self._mode == TradingMode.MOCK:
            raise self.ModeBlockedError(
                "Trading mode is MOCK — no orders will be sent. "
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
        return self._mode in (TradingMode.MOCK, TradingMode.PAPER)

    def reload(self) -> None:
        """Re-read mode and live_enabled from settings/env.

        Call this after a runtime mode change (e.g. via API) so the singleton
        reflects the new configuration without a process restart.
        """
        try:
            from merid.settings import settings
            raw = settings.MERID_PM_TRADING_MODE.lower()
            if raw == "sim":
                raw = "mock"
            self._mode = TradingMode(raw)
            self._live_enabled = settings.MERID_PM_LIVE_ENABLED
        except Exception as _se:
            raw = os.getenv("MERID_PM_TRADING_MODE", "mock").lower()
            if raw == "sim":
                raw = "mock"
            self._mode = TradingMode(raw)
            self._live_enabled = os.getenv("MERID_PM_LIVE_ENABLED", "false").lower() == "true"
        # Re-apply the same MERID_ALLOW_LIVE_TRADES safety guard as the constructor.
        # reload() was previously writing self._mode directly (bypassing the mode.setter),
        # so a LIVE value from settings could be accepted even without the platform-wide latch.
        if self._mode == TradingMode.LIVE:
            allow_live = os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower()
            if allow_live not in ("1", "true", "yes", "on"):
                logger.warning(
                    "VenueGate.reload: settings say LIVE but MERID_ALLOW_LIVE_TRADES not set — "
                    "forcing PAPER for safety"
                )
                self._mode = TradingMode.PAPER
                self._live_enabled = False
        logger.info("VenueGate reloaded: mode=%s live_enabled=%s", self._mode.value, self._live_enabled)

    def summary(self) -> dict:
        """Return a JSON-serialisable summary for dashboards."""
        return {
            "mode": self._mode.value,
            "live_enabled": self._live_enabled,
            "is_live": self.is_live,
            "allowed_venues": sorted(_ALLOWED_VENUES),
            "blocked_venues": sorted(_BLOCKED_VENUES),
        }

    def log_order_decision(
        self,
        *,
        decision: str,
        reason: str,
        venue: str,
        size: int,
        notional_usd: float,
        caps: str = "",
    ) -> None:
        """Structured log for CT → router audit trail (never silent drops)."""
        logger.info(
            "[VENUE-GATE] decision=%s reason=%s venue=%s size=%s notional_usd=%.4f caps=%s",
            decision,
            reason[:300] if reason else "",
            venue,
            size,
            notional_usd,
            caps or f"mode={self._mode.value} live_enabled={self._live_enabled}",
        )


# Module-level singleton (lazy)
_gate: Optional[VenueGate] = None
# LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
# Single-threaded FastAPI startup doesn't need lock protection


def get_venue_gate() -> VenueGate:
    """Get or create the VenueGate singleton."""
    global _gate
    if _gate is None:
        _gate = VenueGate()
    return _gate
