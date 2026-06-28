"""Cross-agent category exposure cap and correlated-market stacking guard.

Prevents:
1. Total notional across **all agents** in the same Kalshi category
   (e.g. all crypto markets) from exceeding a configurable USD cap.
2. Total notional across positions on the **same underlying** regardless
   of timeframe (e.g. BTC-15m + BTC-hourly + BTC-daily stacked) from
   exceeding a correlated-stack cap.

Usage::

    from merid.event_venues.kalshi.category_exposure import get_category_exposure_tracker

    tracker = get_category_exposure_tracker()

    # Pre-order checks
    ok, reason = tracker.check_category_cap("crypto", additional_usd=50.0)
    ok, reason = tracker.check_correlated_cap("BTC", additional_usd=50.0)

    # After confirmed fill
    tracker.record_fill("crypto", "BTC", notional_usd=50.0)

    # After position close / cancel
    tracker.release("crypto", "BTC", notional_usd=50.0)

Caps are loaded from environment variables at import time; override via::

    MERID_CAT_CAP_CRYPTO_USD=2000
    MERID_CAT_CAP_MACRO_USD=500
    MERID_CORR_STACK_CAP_USD=800
    MERID_ASSET_CAP_BTC_USD, MERID_ASSET_CAP_ETH_USD, … (per-asset corr stack, **USD**)

**Not** the Continuous Trader per-asset skip caps (those are ``KALSHI_TRADER_EXPOSURE_*`` on ``TraderConfig``, in **cents** of bankroll in the CT loop). This module speaks **USD** throughout.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.category_exposure")


# ── Default caps (overridden by env vars) ─────────────────────────────────
# NOTE: Now reads from core.settings for unified single source of truth
# If env vars are set, they override settings (for backward compatibility)

# CRITICAL: For crypto 15-minute trading (BTC, ETH, SOL, XRP, DOGE only), disable category caps
# These assets trade on 15-minute timeframe with position limits enforced elsewhere
_DEFAULT_CATEGORY_CAPS: Dict[str, float] = {
    "cross_category": float(os.getenv("MERID_CAT_CAP_CROSS_CATEGORY_USD", "500.0")),  # $500 default
    # 0.0 = derive from actual Kalshi bankroll using core.settings.MAX_CATEGORY_CRYPTO_PCT
    "crypto":     float(os.getenv("MERID_CAT_CAP_CRYPTO_USD",    "999999.0")),  # DISABLED for 15m crypto
    "macro":      float(os.getenv("MERID_CAT_CAP_MACRO_USD",     "500.0")),   # $500 default
    "economics":  float(os.getenv("MERID_CAT_CAP_ECONOMICS_USD", "500.0")),   # $500 default
    "financials": float(os.getenv("MERID_CAT_CAP_FINANCIALS_USD","1000.0")),  # $1000 default
    "politics":   float(os.getenv("MERID_CAT_CAP_POLITICS_USD",   "500.0")),   # $500 default
    "climate":    float(os.getenv("MERID_CAT_CAP_CLIMATE_USD",    "300.0")),   # $300 default
    "sports":     float(os.getenv("MERID_CAT_CAP_SPORTS_USD",     "300.0")),   # $300 default
    "tech":       float(os.getenv("MERID_CAT_CAP_TECH_USD",       "300.0")),   # $300 default
    "culture":    float(os.getenv("MERID_CAT_CAP_CULTURE_USD",    "200.0")),   # $200 default
    "science":    float(os.getenv("MERID_CAT_CAP_SCIENCE_USD",    "200.0")),   # $200 default
    "equities":   float(os.getenv("MERID_CAT_CAP_EQUITIES_USD",   "1000.0")),  # $1000 default
    "other":      float(os.getenv("MERID_CAT_CAP_OTHER_USD",      "200.0")),   # $200 default
}

# 50.0 = minimum cap to prevent $0 cap from blocking trades before calibration
# Calibration will override this with balance * CORRELATED_STACK_PCT (20%)
_DEFAULT_CORR_CAP_USD: float = float(os.getenv("MERID_CORR_STACK_CAP_USD", "50.0"))

# Per-asset USD caps for correlated-stack checks. 0.0 from env = use settings-based per-asset caps.
# NOTE: Now reads from core.settings.ASSET_CAP_*_PCT for unified single source of truth
_DEFAULT_ASSET_CAPS_USD: Dict[str, float] = {
    "BTC":  float(os.getenv("MERID_ASSET_CAP_BTC_USD",  "0.0")),  # 0 = derive from settings
    "ETH":  float(os.getenv("MERID_ASSET_CAP_ETH_USD",  "0.0")),  # 0 = derive from settings
    "SOL":  float(os.getenv("MERID_ASSET_CAP_SOL_USD",  "0.0")),  # 0 = derive from settings
    "XRP":  float(os.getenv("MERID_ASSET_CAP_XRP_USD",  "0.0")),  # 0 = derive from settings
    "DOGE": float(os.getenv("MERID_ASSET_CAP_DOGE_USD", "0.0")),  # 0 = derive from settings
}
_DEFAULT_ASSET_CAPS_USD = {k: v for k, v in _DEFAULT_ASSET_CAPS_USD.items() if v > 0.0}

_UNDERLYING_CATEGORY_MAP: Dict[str, str] = {
    # Crypto
    "BTC": "crypto",   "ETH": "crypto",  "SOL": "crypto",  "XRP": "crypto",
    "DOGE": "crypto",  "POL": "crypto",  "AVAX": "crypto", "LINK": "crypto",
    "ADA": "crypto",   "LTC": "crypto",  "PEPE": "crypto", "WIF": "crypto",
    # Economics / macro
    "CPI": "economics",  "GDP": "economics",  "JOBS": "economics",
    "RATES": "economics",
    # Financials / indices
    "SPX": "financials", "NDX": "financials", "DJI": "financials",
    "RUT": "financials",
    # Politics
    "ELECTION": "politics", "SENATE": "politics", "CONGRESS": "politics",
    "SCOTUS": "politics",   "GOV": "politics",
    # Climate / weather
    "WEATHER": "climate",   "CLIMATE": "climate",
    # Sports
    "NBA": "sports",     "NFL": "sports",    "MLB": "sports",
    "NHL": "sports",     "SOCCER": "sports", "TENNIS": "sports",
    "GOLF": "sports",   "MMA": "sports",
    # Tech
    "AI": "tech",   "NVDA": "tech",  "AAPL": "tech",
    "META": "tech", "GOOGL": "tech", "MSFT": "tech",  "TECH": "tech",
}

_CRYPTO_UNDERLYINGS = frozenset(
    k for k, v in _UNDERLYING_CATEGORY_MAP.items() if v == "crypto"
)


# ── Data ─────────────────────────────────────────────────────────────────


@dataclass
class ExposureSnapshot:
    """Point-in-time exposure state for the tracker."""
    category_notional: Dict[str, float]   # category -> total USD notional
    corr_notional: Dict[str, float]       # underlying -> total USD notional
    category_caps: Dict[str, float]
    corr_cap: float
    # Per-underlying correlated-stack cap overrides (USD notional), same units as corr_cap / corr_notional.
    asset_caps: Dict[str, float]

    def category_utilisation(self, category: str) -> float:
        cap = self.category_caps.get(category, 0.0)
        return self.category_notional.get(category, 0.0) / cap if cap > 0 else 0.0

    def to_dict(self) -> Dict:
        cats = {
            c: {
                "notional_usd": round(v, 2),
                "cap_usd": self.category_caps.get(c, 0.0),
                "utilisation": round(self.category_utilisation(c), 4),
            }
            for c, v in self.category_notional.items()
        }
        return {
            "categories": cats,
            "correlated_underlyings": {k: round(v, 2) for k, v in self.corr_notional.items()},
            "corr_cap_usd": self.corr_cap,
            "asset_caps": dict(self.asset_caps),  # underlying -> cap USD (corr stack)
        }


# ── Tracker ───────────────────────────────────────────────────────────────


class CategoryExposureTracker:
    """Thread-safe cross-agent exposure tracker.

    All notional values are in USD.  State resets daily at midnight.
    """

    def __init__(
        self,
        category_caps: Optional[Dict[str, float]] = None,
        corr_cap_usd: Optional[float] = None,
        asset_caps_usd: Optional[Dict[str, float]] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._category_caps: Dict[str, float] = category_caps or dict(_DEFAULT_CATEGORY_CAPS)
        self._corr_cap: float = corr_cap_usd if corr_cap_usd is not None else _DEFAULT_CORR_CAP_USD
        _raw = asset_caps_usd if asset_caps_usd is not None else dict(_DEFAULT_ASSET_CAPS_USD)
        # Env / constructor overrides — reapplied on top of balance-calibrated caps.
        self._asset_caps_env: Dict[str, float] = {k: v for k, v in _raw.items() if v > 0.0}
        self._asset_caps: Dict[str, float] = dict(self._asset_caps_env)

        self._category_notional: Dict[str, float] = {}
        self._corr_notional: Dict[str, float] = {}
        self._last_reset_day: str = ""
        self._maybe_reset_daily()

    def _corr_cap_for(self, underlying: str) -> float:
        """Correlated-stack cap for ``underlying`` (per-asset override or default)."""
        return self._asset_caps.get(underlying.upper(), self._corr_cap)

    # ── Daily reset ──────────────────────────────────────────────────────

    def _maybe_reset_daily(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if today != self._last_reset_day:
            self._category_notional.clear()
            self._corr_notional.clear()
            self._last_reset_day = today
            logger.debug("CategoryExposureTracker: daily reset")

    # ── Checks ───────────────────────────────────────────────────────────

    def check_category_cap(self, category: str, additional_usd: float) -> Tuple[bool, str]:
        """Return (allowed, reason).  Passes if no cap is configured for category."""
        with self._lock:
            self._maybe_reset_daily()
            cat = category.lower()
            cap = self._category_caps.get(cat)
            if cap is None:
                return True, ""
            current = self._category_notional.get(cat, 0.0)
            if current + additional_usd > cap:
                return False, (
                    f"category_cap_exceeded:{cat}:"
                    f"current=${current:.0f}+${additional_usd:.0f}>cap=${cap:.0f}"
                )
            return True, ""

    def check_correlated_cap(self, underlying: str, additional_usd: float) -> Tuple[bool, str]:
        """Return (allowed, reason).  Prevents same-underlying timeframe stacking."""
        with self._lock:
            self._maybe_reset_daily()
            under = underlying.upper()
            cap = self._corr_cap_for(under)
            current = self._corr_notional.get(under, 0.0)
            if current + additional_usd > cap:
                return False, (
                    f"corr_stack_cap_exceeded:{under}:"
                    f"current=${current:.0f}+${additional_usd:.0f}>cap=${cap:.0f}"
                )
            return True, ""

    def check_and_reserve(
        self,
        category: str,
        underlying: str,
        additional_usd: float,
    ) -> Tuple[bool, str]:
        """Atomically check both caps and tentatively reserve notional if allowed.

        This eliminates the TOCTOU race where two concurrent agents each pass
        ``check_category_cap`` + ``check_correlated_cap`` independently before
        either calls ``record_fill``, causing a combined breach.

        On approval the notional is immediately reserved.  The caller **must**
        call ``release()`` if the downstream order is subsequently rejected or
        cancelled, or ``record_fill()`` is NOT called for any other reason.

        Returns:
            (True, "") if both caps pass and notional is reserved.
            (False, reason) if either cap would be exceeded; nothing is reserved.
        """
        with self._lock:
            self._maybe_reset_daily()
            cat = category.lower()
            under = underlying.upper()

            # Category cap check
            cap = self._category_caps.get(cat)
            if cap is not None:
                current_cat = self._category_notional.get(cat, 0.0)
                if current_cat + additional_usd > cap:
                    return False, (
                        f"category_cap_exceeded:{cat}:"
                        f"current=${current_cat:.0f}+${additional_usd:.0f}>cap=${cap:.0f}"
                    )

            # Correlated underlying cap check
            _corr_cap = self._corr_cap_for(under)
            current_corr = self._corr_notional.get(under, 0.0)
            if current_corr + additional_usd > _corr_cap:
                return False, (
                    f"corr_stack_cap_exceeded:{under}:"
                    f"current=${current_corr:.0f}+${additional_usd:.0f}>cap=${_corr_cap:.0f}"
                )

            # Both passed — reserve atomically
            if cap is not None:
                self._category_notional[cat] = self._category_notional.get(cat, 0.0) + additional_usd
            self._corr_notional[under] = self._corr_notional.get(under, 0.0) + additional_usd
            logger.debug(
                "CategoryExposureTracker: reserved cat=%s under=%s +$%.2f",
                cat, under, additional_usd,
            )
            return True, ""

    # ── Recording ────────────────────────────────────────────────────────

    def record_fill(self, category: str, underlying: str, notional_usd: float) -> None:
        """Register a confirmed fill.  Call *after* the order is accepted."""
        with self._lock:
            self._maybe_reset_daily()
            cat = category.lower()
            under = underlying.upper()
            self._category_notional[cat] = self._category_notional.get(cat, 0.0) + notional_usd
            self._corr_notional[under] = self._corr_notional.get(under, 0.0) + notional_usd
            logger.debug(
                "CategoryExposureTracker: fill cat=%s under=%s +$%.2f",
                cat, under, notional_usd,
            )

    def release(self, category: str, underlying: str, notional_usd: float) -> None:
        """Release notional when a position closes or an order is cancelled."""
        with self._lock:
            cat = category.lower()
            under = underlying.upper()
            self._category_notional[cat] = max(
                0.0, self._category_notional.get(cat, 0.0) - notional_usd
            )
            self._corr_notional[under] = max(
                0.0, self._corr_notional.get(under, 0.0) - notional_usd
            )

    # ── Snapshot ─────────────────────────────────────────────────────────

    def get_snapshot(self) -> ExposureSnapshot:
        with self._lock:
            self._maybe_reset_daily()
            return ExposureSnapshot(
                category_notional=dict(self._category_notional),
                corr_notional=dict(self._corr_notional),
                category_caps=dict(self._category_caps),
                corr_cap=self._corr_cap,
                asset_caps=dict(self._asset_caps),
            )

    # ── Balance calibration ───────────────────────────────────────────────

    # Minimum caps to prevent impossibly small trading limits with low balances
    _MIN_CATEGORY_CAP_USD: float = 100.0   # Min $100 per category
    _MIN_CORR_CAP_USD: float = 50.0         # Min $50 for correlated stack
    _MIN_ASSET_CAP_USD: float = 25.0       # Min $25 per asset

    def calibrate_from_balance(
        self,
        balance_cents: int,
        *,
        category_fractions: Optional[Dict[str, float]] = None,
        corr_fraction: float = 0.20,
        asset_fractions: Optional[Dict[str, float]] = None,
    ) -> None:
        """Set all caps as fractions of the live Kalshi balance.

        Silently ignored when balance_cents <= 0.

        NOTE: Now reads from core.settings for unified single source of truth.
        - crypto category uses core.settings.MAX_CATEGORY_CRYPTO_PCT (default 30%)
        - correlated stack uses core.settings.CORRELATED_STACK_PCT (default 2%)
        - per-asset caps use core.settings.ASSET_CAP_*_PCT (BTC/ETH 2%, SOL/XRP 1.5%, DOGE 1%)

        Note: ``max_single_order_contracts`` and ``CategoryLimit.max_contracts``
        (if any) are not touched — they represent fixed venue-level limits.

        Args:
            balance_cents: Live account balance in cents.
            category_fractions: Override map {category: fraction}.  Defaults
                to the standard fractions below.
            corr_fraction: Fraction for the default correlated-stack cap.
                NOTE: Now defaults to core.settings.CORRELATED_STACK_PCT (2%)
            asset_fractions: Optional {underlying: fraction} for per-asset corr caps.
                Merged with live balance; non-zero caps from env/constructor
                (``_asset_caps_env``) override the calibrated value for the same key.
        """
        if balance_cents <= 0:
            return
        balance_usd = balance_cents / 100.0
        
        # NOTE: Read from core.settings for unified single source of truth
        try:
            from core.settings import (
                MAX_CATEGORY_CRYPTO_PCT,
                CORRELATED_STACK_PCT,
                ASSET_CAP_BTC_PCT,
                ASSET_CAP_ETH_PCT,
                ASSET_CAP_SOL_PCT,
                ASSET_CAP_XRP_PCT,
                ASSET_CAP_DOGE_PCT,
            )
            # Use settings defaults if not overridden by category_fractions
            fractions = category_fractions or {
                "crypto":     MAX_CATEGORY_CRYPTO_PCT,  # 30% from settings
                "economics":  0.10,
                "financials": 0.10,
                "politics":   0.08,
                "climate":    0.05,
                "tech":       0.08,
                "sports":     0.05,
                "culture":    0.05,
                "science":    0.05,
                "equities":   0.10,
                "weather":    0.05,
                "macro":      0.05,
                "other":      0.05,
            }
            # Use settings default for corr_fraction if not overridden
            if corr_fraction == 0.20:  # Default value, use settings
                corr_fraction = CORRELATED_STACK_PCT  # 2% from settings
            
            # Use settings defaults for per-asset caps if not overridden by asset_fractions
            asset_fractions = asset_fractions or {
                "BTC":  ASSET_CAP_BTC_PCT,   # 2% from settings
                "ETH":  ASSET_CAP_ETH_PCT,   # 2% from settings
                "SOL":  ASSET_CAP_SOL_PCT,   # 1.5% from settings
                "XRP":  ASSET_CAP_XRP_PCT,   # 1.5% from settings
                "DOGE": ASSET_CAP_DOGE_PCT,  # 1% from settings
            }
        except Exception as e:
            logger.warning("CategoryExposureTracker: failed to read from core.settings, using defaults: %s", e)
            fractions = category_fractions or {
                "crypto":     0.30,
                "economics":  0.10,
                "financials": 0.10,
                "politics":   0.08,
                "climate":    0.05,
                "tech":       0.08,
                "sports":     0.05,
                "culture":    0.05,
                "science":    0.05,
                "equities":   0.10,
                "weather":    0.05,
                "macro":      0.05,
                "other":      0.05,
            }
            if corr_fraction == 0.20:
                corr_fraction = 0.20  # 20% default (increased from 2% to allow trades)
            asset_fractions = asset_fractions or {
                "BTC":  0.02,
                "ETH":  0.02,
                "SOL":  0.015,
                "XRP":  0.015,
                "DOGE": 0.01,
            }
        
        with self._lock:
            for cat, frac in fractions.items():
                # Apply minimum floor to prevent impossibly small caps
                self._category_caps[cat] = max(
                    balance_usd * frac, self._MIN_CATEGORY_CAP_USD
                )
            # Apply minimum floor to correlated stack cap
            self._corr_cap = max(
                balance_usd * corr_fraction, self._MIN_CORR_CAP_USD
            )
            if asset_fractions:
                calibrated = {
                    k.upper(): max(balance_usd * v, self._MIN_ASSET_CAP_USD)
                    for k, v in asset_fractions.items()
                    if v > 0.0
                }
                merged = dict(calibrated)
                for k, v in self._asset_caps_env.items():
                    if v > 0.0:
                        merged[k] = v
                self._asset_caps = merged
            _log_crypto = self._category_caps.get("crypto", 0.0)
            _log_corr = self._corr_cap
            _log_asset_caps = dict(self._asset_caps)
        logger.info(
            "CategoryExposureTracker: calibrated balance_usd=%.2f "
            "crypto_cap=%.2f corr_cap=%.2f asset_caps=%s",
            balance_usd,
            _log_crypto,
            _log_corr,
            {k: round(v, 2) for k, v in _log_asset_caps.items()},
        )


# ── Helpers ───────────────────────────────────────────────────────────────


def infer_category(underlying: str) -> str:
    """Infer Kalshi category from underlying asset symbol (all categories)."""
    return _UNDERLYING_CATEGORY_MAP.get(underlying.upper(), "other")



# ── Singleton ─────────────────────────────────────────────────────────────

_tracker: Optional[CategoryExposureTracker] = None
_tracker_lock = threading.Lock()


def get_category_exposure_tracker() -> CategoryExposureTracker:
    """Return the process-wide singleton tracker."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = CategoryExposureTracker()
    return _tracker
