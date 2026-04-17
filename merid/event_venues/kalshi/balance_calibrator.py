"""BalanceCalibrator — single entry point for balance-driven limit recalibration.

Call ``get_balance_calibrator().update(balance_cents)`` after every successful
Kalshi balance fetch.  Recalibration fires only when balance moves by more than
``threshold`` (default 5 %).  Both ``KalshiRiskManager`` and
``CategoryExposureTracker`` are reached via lazy import to avoid circular deps.
"""
from __future__ import annotations

import threading
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.balance_calibrator")

_DEFAULT_THRESHOLD = 0.05  # 5 % balance change triggers recalibration


class BalanceCalibrator:
    """Tracks live Kalshi balance; recalibrates risk limits on significant moves."""

    def __init__(self, threshold: float = _DEFAULT_THRESHOLD) -> None:
        self._threshold = threshold
        self._last_calibrated_cents: int = 0
        self._current_cents: int = 0
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────

    def update(self, balance_cents: int) -> bool:
        """Update balance.  Returns True when recalibration was triggered.

        Thread-safe.  Silently ignores zero or negative balances.
        """
        if balance_cents <= 0:
            return False
        should_recalibrate = False
        with self._lock:
            is_first = self._last_calibrated_cents == 0
            change_pct = (
                abs(balance_cents - self._last_calibrated_cents)
                / self._last_calibrated_cents
                if self._last_calibrated_cents > 0
                else 1.0
            )
            self._current_cents = balance_cents
            if is_first or change_pct >= self._threshold:
                self._last_calibrated_cents = balance_cents
                should_recalibrate = True
        if should_recalibrate:
            self._recalibrate(balance_cents)
            return True
        return False

    @property
    def current_balance_cents(self) -> int:
        """Most recently observed balance in cents."""
        with self._lock:
            return self._current_cents

    # ── Internal ─────────────────────────────────────────────────────────

    def _recalibrate(self, balance_cents: int) -> None:
        """Push new limits to risk singletons (lazy imports, best-effort)."""
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            get_kalshi_risk().calibrate_from_balance(balance_cents)
        except Exception as exc:
            logger.warning("BalanceCalibrator: KalshiRiskManager calibration failed: %s", exc)

        try:
            from merid.event_venues.kalshi.category_exposure import get_category_exposure_tracker
            get_category_exposure_tracker().calibrate_from_balance(balance_cents)
        except Exception as exc:
            logger.warning(
                "BalanceCalibrator: CategoryExposureTracker calibration failed: %s", exc
            )

        logger.info(
            "BalanceCalibrator: recalibrated — balance_cents=%d (%.2f USD)",
            balance_cents, balance_cents / 100.0,
        )


# ── Singleton ─────────────────────────────────────────────────────────────

_calibrator: Optional[BalanceCalibrator] = None
_calibrator_lock = threading.Lock()


def get_balance_calibrator() -> BalanceCalibrator:
    """Return the process-wide BalanceCalibrator singleton."""
    global _calibrator
    if _calibrator is None:
        with _calibrator_lock:
            if _calibrator is None:
                _calibrator = BalanceCalibrator()
    return _calibrator
