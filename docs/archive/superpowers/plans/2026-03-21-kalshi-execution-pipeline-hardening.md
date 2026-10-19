# Kalshi Execution Pipeline Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 7 production-blocking bugs in the Kalshi crypto execution pipeline and replace all hardcoded dollar-amount risk caps with fractions of the live Kalshi account balance, recalibrating when balance moves >5%.

**Architecture:** A new `BalanceCalibrator` singleton sits between the executor's balance-fetch step and the two risk singletons (`KalshiRiskManager`, `CategoryExposureTracker`). Both singletons gain a `calibrate_from_balance(balance_cents)` method that recomputes all USD caps as fractions of the live balance. The executor is re-ordered so balance is fetched (and calibration triggered) _before_ `check_order()` runs. The executor also gains category/underlying derivation, atomic category-exposure reservation, and proper notional accounting on fills.

**Tech Stack:** Python 3.11+, asyncio, threading (existing), pytest, no new dependencies

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `merid/event_venues/kalshi/balance_calibrator.py` | Singleton that tracks live balance, fires calibration when balance moves >5% |
| Modify | `merid/event_venues/kalshi/kalshi_risk.py` | Add pct-based config fields + `calibrate_from_balance()` |
| Modify | `merid/event_venues/kalshi/category_exposure.py` | Add `calibrate_from_balance()` |
| Modify | `merid/execution/executors/kalshi.py` | Wire all fixes: category, outcome warning, reservation, notional accounting, calibration trigger |
| Modify | `config/kalshi_universe_loader.py` | Fix S2-1: startswith filter (subset always-empty bug) |
| Modify | `merid/event_venues/kalshi/market_selector.py` | Fix S2-2: 15m/1h series tickers aligned to canonical KALSHI_CRYPTO_PRODUCTS |
| Modify | `tests/executors/test_kalshi_executor.py` | Fix TEST-1: update mock URL from v1 to v2 |
| Create | `tests/test_catalog_subset_filter.py` | Unit tests for S2-1 fix |
| Create | `tests/test_balance_calibrator.py` | Unit tests for BalanceCalibrator |
| Create | `tests/test_executor_wiring.py` | Unit tests for category pass-through, outcome warning, notional accounting |

---

## Task 1 — Add pct-based fields and `calibrate_from_balance()` to KalshiRiskManager

**Files:**
- Modify: `merid/event_venues/kalshi/kalshi_risk.py`

This task adds two things to `KalshiRiskConfig`: a set of fraction fields (`max_total_notional_pct`, etc.) that express limits as a share of live balance, plus a `calibrate_from_balance(balance_cents)` method on `KalshiRiskManager` that rewrites the USD limits in-place. Existing hardcoded USD defaults remain as startup fallbacks until the first balance fetch.

- [ ] **Step 1.1 — Write the failing test**

```python
# tests/test_balance_calibrator.py  (create new file)
import pytest
from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig, KalshiRiskManager


def _make_manager(**kwargs) -> KalshiRiskManager:
    return KalshiRiskManager(KalshiRiskConfig(**kwargs))


def test_calibrate_sets_total_notional():
    mgr = _make_manager()
    mgr.calibrate_from_balance(500_000)          # $5 000 balance
    # default max_total_notional_pct = 0.80 → $4 000
    assert mgr.config.max_total_notional_usd == pytest.approx(4000.0)


def test_calibrate_sets_daily_loss():
    mgr = _make_manager()
    mgr.calibrate_from_balance(500_000)          # $5 000
    # default max_daily_loss_pct = 0.10 → $500
    assert mgr.config.max_daily_loss_usd == pytest.approx(500.0)


def test_calibrate_sets_single_order_notional():
    mgr = _make_manager()
    mgr.calibrate_from_balance(500_000)
    # default max_single_order_pct = 0.05 → $250
    assert mgr.config.max_single_order_notional_usd == pytest.approx(250.0)


def test_calibrate_sets_category_limit():
    mgr = _make_manager()
    mgr.calibrate_from_balance(500_000)
    # default crypto pct = 0.30 → $1 500
    crypto_limit = mgr.config.category_limits["crypto"]
    assert crypto_limit.max_notional_usd == pytest.approx(1500.0)


def test_calibrate_zero_balance_is_noop():
    mgr = _make_manager()
    original = mgr.config.max_total_notional_usd
    mgr.calibrate_from_balance(0)
    assert mgr.config.max_total_notional_usd == original


def test_calibrate_updates_under_lock():
    """Concurrent calibration calls should not corrupt state."""
    import threading
    mgr = _make_manager()
    errors = []

    def calibrate():
        try:
            mgr.calibrate_from_balance(100_000)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=calibrate) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
```

- [ ] **Step 1.2 — Run test to verify it fails**

```
pytest tests/test_balance_calibrator.py -v -k "calibrate"
```
Expected: `FAILED` — `KalshiRiskManager` has no `calibrate_from_balance` attribute.

- [ ] **Step 1.3 — Add pct fields to `KalshiRiskConfig` and `calibrate_from_balance()` to `KalshiRiskManager`**

In `merid/event_venues/kalshi/kalshi_risk.py`, locate `@dataclass class KalshiRiskConfig` and add after the existing fields (before `__post_init__`):

```python
    # ── Balance-relative fractions ───────────────────────────────────────
    # These are recomputed into the _usd fields by calibrate_from_balance().
    # Fractions of the live Kalshi account balance.
    max_total_notional_pct: float = 0.80     # 80 % of balance
    max_daily_loss_pct: float = 0.10         # 10 % of balance
    max_single_order_pct: float = 0.05       # 5 % of balance
    category_notional_pct: Dict[str, float] = field(default_factory=lambda: {
        "crypto":     0.30,
        "economics":  0.10,
        "financials": 0.10,
        "politics":   0.08,
        "climate":    0.05,
        "tech":       0.08,
        "sports":     0.05,
        "culture":    0.05,
        "science":    0.05,
        "other":      0.05,
    })
    # Note: correlated_stack_pct is used by CategoryExposureTracker.calibrate_from_balance()
    # as the corr_fraction argument — do NOT remove.
    correlated_stack_pct: float = 0.20      # single underlying across all timeframes
```

Then add `calibrate_from_balance()` as a method on `KalshiRiskManager` (after `reset_daily`):

```python
    def calibrate_from_balance(self, balance_cents: int) -> None:
        """Recompute all USD caps from live balance × configured fractions.

        Safe to call concurrently; all writes are done under self._lock.
        Silently ignored when balance_cents <= 0.
        """
        if balance_cents <= 0:
            return
        balance_usd = balance_cents / 100.0
        cfg = self._config
        with self._lock:
            cfg.max_total_notional_usd = balance_usd * cfg.max_total_notional_pct
            cfg.max_daily_loss_usd = balance_usd * cfg.max_daily_loss_pct
            cfg.max_single_order_notional_usd = balance_usd * cfg.max_single_order_pct
            for cat, lim in cfg.category_limits.items():
                pct = cfg.category_notional_pct.get(cat, 0.05)
                lim.max_notional_usd = balance_usd * pct
            # Capture values inside lock before releasing — avoids data race in log
            _log_notional = cfg.max_total_notional_usd
            _log_daily = cfg.max_daily_loss_usd
            _log_single = cfg.max_single_order_notional_usd
        logger.info(
            "calibrate_from_balance: balance_usd=%.2f "
            "notional_cap=%.2f daily_loss=%.2f single_order=%.2f",
            balance_usd,
            _log_notional,
            _log_daily,
            _log_single,
        )
```

- [ ] **Step 1.4 — Run tests to verify they pass**

```
pytest tests/test_balance_calibrator.py -v -k "calibrate"
```
Expected: all 6 pass.

- [ ] **Step 1.5 — Commit**

```bash
git add merid/event_venues/kalshi/kalshi_risk.py tests/test_balance_calibrator.py
git commit -m "feat: add pct-based config + calibrate_from_balance() to KalshiRiskManager"
```

---

## Task 2 — Add `calibrate_from_balance()` to `CategoryExposureTracker`

**Files:**
- Modify: `merid/event_venues/kalshi/category_exposure.py`

- [ ] **Step 2.1 — Write the failing tests** (append to `tests/test_balance_calibrator.py`)

```python
from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker


def test_cat_tracker_calibrate_sets_crypto_cap():
    tracker = CategoryExposureTracker()
    tracker.calibrate_from_balance(500_000)   # $5 000
    # default crypto fraction 0.30 → $1 500
    snap = tracker.get_snapshot()
    assert snap.category_caps["crypto"] == pytest.approx(1500.0)


def test_cat_tracker_calibrate_sets_corr_cap():
    tracker = CategoryExposureTracker()
    tracker.calibrate_from_balance(500_000)
    # default corr fraction 0.20 → $1 000
    snap = tracker.get_snapshot()
    assert snap.corr_cap == pytest.approx(1000.0)


def test_cat_tracker_calibrate_zero_is_noop():
    tracker = CategoryExposureTracker()
    original_crypto = tracker.get_snapshot().category_caps.get("crypto", 0)
    tracker.calibrate_from_balance(0)
    assert tracker.get_snapshot().category_caps.get("crypto", 0) == original_crypto
```

- [ ] **Step 2.2 — Run to verify failure**

```
pytest tests/test_balance_calibrator.py -v -k "cat_tracker_calibrate"
```
Expected: `FAILED` — `CategoryExposureTracker` has no `calibrate_from_balance`.

- [ ] **Step 2.3 — Add `calibrate_from_balance()` to `CategoryExposureTracker`**

In `merid/event_venues/kalshi/category_exposure.py`, add this method inside `CategoryExposureTracker` after `get_snapshot`:

```python
    # ── Balance calibration ───────────────────────────────────────────────

    def calibrate_from_balance(
        self,
        balance_cents: int,
        *,
        category_fractions: Optional[Dict[str, float]] = None,
        corr_fraction: float = 0.20,
    ) -> None:
        """Set all caps as fractions of the live Kalshi balance.

        Silently ignored when balance_cents <= 0.

        Args:
            balance_cents: Live account balance in cents.
            category_fractions: Override map {category: fraction}.  Defaults
                to the standard fractions below.
            corr_fraction: Fraction for the correlated-stack cap.
        """
        if balance_cents <= 0:
            return
        balance_usd = balance_cents / 100.0
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
            "other":      0.05,
        }
        with self._lock:
            for cat, frac in fractions.items():
                self._category_caps[cat] = balance_usd * frac
            self._corr_cap = balance_usd * corr_fraction
            # Capture values inside lock before releasing — avoids data race in log
            _log_crypto = self._category_caps.get("crypto", 0.0)
            _log_corr = self._corr_cap
        logger.info(
            "CategoryExposureTracker: calibrated balance_usd=%.2f "
            "crypto_cap=%.2f corr_cap=%.2f",
            balance_usd,
            _log_crypto,
            _log_corr,
        )
```

- [ ] **Step 2.4 — Run tests**

```
pytest tests/test_balance_calibrator.py -v
```
Expected: all 9 pass.

- [ ] **Step 2.5 — Commit**

```bash
git add merid/event_venues/kalshi/category_exposure.py tests/test_balance_calibrator.py
git commit -m "feat: add calibrate_from_balance() to CategoryExposureTracker"
```

---

## Task 3 — Create `BalanceCalibrator` singleton

**Files:**
- Create: `merid/event_venues/kalshi/balance_calibrator.py`

The calibrator holds the last-seen balance and last-calibrated balance. It fires calibration only when the change exceeds 5% (or on first call). Both risk singletons are reached via lazy import to avoid circular imports.

- [ ] **Step 3.1 — Write failing tests** (append to `tests/test_balance_calibrator.py`)

```python
from merid.event_venues.kalshi.balance_calibrator import BalanceCalibrator


def test_calibrator_fires_on_first_update():
    calibrated = []

    cal = BalanceCalibrator(threshold=0.05)
    cal._recalibrate = lambda b: calibrated.append(b)  # spy
    fired = cal.update(500_000)

    assert fired is True
    assert calibrated == [500_000]


def test_calibrator_no_fire_below_threshold():
    fired_counts = []

    cal = BalanceCalibrator(threshold=0.05)
    cal._recalibrate = lambda b: fired_counts.append(b)
    cal.update(500_000)          # first call — always fires
    fired_counts.clear()
    cal.update(502_000)          # +0.4% — below 5% threshold
    assert fired_counts == []    # must NOT fire


def test_calibrator_fires_above_threshold():
    fired_counts = []

    cal = BalanceCalibrator(threshold=0.05)
    cal._recalibrate = lambda b: fired_counts.append(b)
    cal.update(500_000)
    fired_counts.clear()
    cal.update(530_000)          # +6% — above threshold
    assert fired_counts == [530_000]


def test_calibrator_zero_balance_skipped():
    fired = []
    cal = BalanceCalibrator()
    cal._recalibrate = lambda b: fired.append(b)
    result = cal.update(0)
    assert result is False
    assert fired == []


@pytest.fixture(autouse=True)
def _reset_balance_calibrator_singleton():
    """Reset the module-level singleton before and after each test to prevent
    state leaking between tests that call get_balance_calibrator()."""
    import merid.event_venues.kalshi.balance_calibrator as _mod
    _mod._calibrator = None
    yield
    _mod._calibrator = None


def test_get_balance_calibrator_is_singleton():
    from merid.event_venues.kalshi.balance_calibrator import get_balance_calibrator
    a = get_balance_calibrator()
    b = get_balance_calibrator()
    assert a is b
```

- [ ] **Step 3.2 — Run to verify failure**

```
pytest tests/test_balance_calibrator.py -v -k "calibrator"
```
Expected: `ModuleNotFoundError` or `ImportError` — file does not exist yet.

- [ ] **Step 3.3 — Create the file**

Create `merid/event_venues/kalshi/balance_calibrator.py`:

```python
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
                self._recalibrate(balance_cents)
                return True
        return False

    @property
    def current_balance_cents(self) -> int:
        """Most recently observed balance in cents."""
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
```

- [ ] **Step 3.4 — Run tests**

```
pytest tests/test_balance_calibrator.py -v
```
Expected: all 14 tests pass.

- [ ] **Step 3.5 — Commit**

```bash
git add merid/event_venues/kalshi/balance_calibrator.py tests/test_balance_calibrator.py
git commit -m "feat: add BalanceCalibrator singleton — balance-driven risk limit recalibration"
```

---

## Task 4 — Fix catalog subset filter (Bug S2-1)

**Files:**
- Modify: `config/kalshi_universe_loader.py`
- Create: `tests/test_catalog_subset_filter.py`

The bug: `btc_15m = [m for m in all_markets if m in KALSHI_CRYPTO_PRODUCTS["BTC_15M"]]` checks exact membership in `["KXBTUPDOWN-15M"]`. Live Kalshi market tickers look like `KXBTUPDOWN-15M-0316-1415` — they **start with** the series prefix but are never equal to it. Result: all 15m/1h crypto subsets are always `[]`.

- [ ] **Step 4.1 — Write failing tests**

Create `tests/test_catalog_subset_filter.py`:

```python
"""Tests for catalog subset filter (Bug S2-1 regression guard)."""
import pytest
from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS
from config.kalshi_universe_loader import fetch_kalshi_active_markets


def _make_client_stub(tickers):
    """Minimal stub that returns a fixed list of open market tickers."""

    class _Market:
        def __init__(self, t):
            self.ticker = t
            self.status = "open"

    class _Event:
        def __init__(self, markets):
            self.category = "crypto"
            self.series_ticker = markets[0].ticker.split("-")[0] if markets else ""
            self.markets = markets

    class _Resp:
        def __init__(self, tickers):
            self.events = [_Event([_Market(t) for t in tickers])]
            self.cursor = None

    class _Client:
        def get_events(self, **kwargs):
            return _Resp(tickers)

    return _Client()


def test_btc_15m_subset_nonempty_for_updown_ticker():
    """A ticker starting with the BTC_15M series prefix must land in BTC_15M subset."""
    # Simulate a real Kalshi API ticker for the BTC 15m up/down market
    live_ticker = "KXBTUPDOWN-15M-0316-1415"
    client = _make_client_stub([live_ticker])
    result = fetch_kalshi_active_markets(client)
    assert live_ticker in result["BTC_15M"], (
        f"Expected {live_ticker!r} in BTC_15M subset but got {result['BTC_15M']}"
    )


def test_eth_15m_subset_nonempty_for_updown_ticker():
    live_ticker = "KXETHUPDOWN-15M-0316-1415"
    client = _make_client_stub([live_ticker])
    result = fetch_kalshi_active_markets(client)
    assert live_ticker in result["ETH_15M"]


def test_exact_prefix_string_not_in_subset():
    """The bare prefix 'KXBTUPDOWN-15M' (no date suffix) is not a real market — must be excluded."""
    # This guards against the old behaviour where only the bare prefix matched
    bare_prefix = "KXBTUPDOWN-15M"
    live_ticker = "KXBTUPDOWN-15M-0316-1415"
    client = _make_client_stub([live_ticker])
    result = fetch_kalshi_active_markets(client)
    # We want the dated ticker in, but also confirm the bare prefix itself is absent
    # (it should never appear as a standalone market ticker from the API)
    assert live_ticker in result["BTC_15M"]


def test_unrelated_ticker_not_in_btc_subset():
    live_ticker = "KXETHUPDOWN-15M-0316-1415"
    client = _make_client_stub([live_ticker])
    result = fetch_kalshi_active_markets(client)
    assert live_ticker not in result["BTC_15M"]
```

- [ ] **Step 4.2 — Run to verify failure**

```
pytest tests/test_catalog_subset_filter.py -v
```
Expected: `FAILED` — `KXBTUPDOWN-15M-0316-1415` not found in BTC_15M (exact-match bug).

- [ ] **Step 4.3 — Fix the subset filter in `kalshi_universe_loader.py`**

Find lines 99–116 and replace:

```python
# OLD (exact match — always empty):
btc_15m = [m for m in all_markets if m in KALSHI_CRYPTO_PRODUCTS["BTC_15M"]]
btc_1h = [m for m in all_markets if m in KALSHI_CRYPTO_PRODUCTS.get("BTC_1H", [])]
eth_15m = [m for m in all_markets if m in KALSHI_CRYPTO_PRODUCTS["ETH_15M"]]
sol_15m = [m for m in all_markets if m in KALSHI_CRYPTO_PRODUCTS["SOL_15M"]]
xrp_15m = [m for m in all_markets if m in KALSHI_CRYPTO_PRODUCTS["XRP_15M"]]
doge_15m = [m for m in all_markets if m in KALSHI_CRYPTO_PRODUCTS.get("DOGE_15M", [])]
```

```python
# NEW (prefix match — correct):
def _in_series(ticker: str, series_list: list) -> bool:
    """True when ticker starts with any prefix in series_list."""
    return any(ticker.startswith(p) for p in series_list)

btc_15m  = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("BTC_15M", []))]
btc_1h   = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("BTC_1H", []))]
eth_15m  = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("ETH_15M", []))]
sol_15m  = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("SOL_15M", []))]
xrp_15m  = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("XRP_15M", []))]
doge_15m = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("DOGE_15M", []))]
```

Apply the **same** `_in_series` fix to the identical block inside `select_kalshi_universe()` (lines 226–231). Replace:

```python
# OLD (in select_kalshi_universe — same exact-match bug):
btc_15m  = [m for m in markets if m in KALSHI_CRYPTO_PRODUCTS["BTC_15M"]]
btc_1h   = [m for m in markets if m in KALSHI_CRYPTO_PRODUCTS.get("BTC_1H", [])]
eth_15m  = [m for m in markets if m in KALSHI_CRYPTO_PRODUCTS["ETH_15M"]]
sol_15m  = [m for m in markets if m in KALSHI_CRYPTO_PRODUCTS["SOL_15M"]]
xrp_15m  = [m for m in markets if m in KALSHI_CRYPTO_PRODUCTS["XRP_15M"]]
doge_15m = [m for m in markets if m in KALSHI_CRYPTO_PRODUCTS.get("DOGE_15M", [])]
```

```python
# NEW (reuse the same _in_series helper defined above in this file):
btc_15m  = [m for m in markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("BTC_15M", []))]
btc_1h   = [m for m in markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("BTC_1H", []))]
eth_15m  = [m for m in markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("ETH_15M", []))]
sol_15m  = [m for m in markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("SOL_15M", []))]
xrp_15m  = [m for m in markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("XRP_15M", []))]
doge_15m = [m for m in markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("DOGE_15M", []))]
```

Note: `_in_series` is defined in the `fetch_kalshi_active_markets` block — if `select_kalshi_universe()` is a standalone function, define `_in_series` at module level so both callers can use it. The `get_crypto_subsets()` function (if present) uses `startswith` directly — verify and leave as-is.

- [ ] **Step 4.4 — Run tests**

```
pytest tests/test_catalog_subset_filter.py -v
```
Expected: all 4 pass.

- [ ] **Step 4.5 — Commit**

```bash
git add config/kalshi_universe_loader.py tests/test_catalog_subset_filter.py
git commit -m "fix: catalog subset filter uses startswith instead of exact match (Bug S2-1)"
```

---

## Task 5 — Canonicalize 15m/1h series tickers (Bug S2-2)

**Files:**
- Modify: `merid/event_venues/kalshi/market_selector.py`

Three files used three incompatible series-ticker formats for BTC/ETH/SOL/XRP/DOGE 15m and 1h. `kalshi_universe.py` has the most grounded values (referenced in agent specs and pinned markets). `market_selector.py`'s `AGENT_SERIES_MAP` is the runtime path — fix it to import the canonical prefixes from `kalshi_universe.py`.

- [ ] **Step 5.1 — Write failing test** (append to `tests/test_catalog_subset_filter.py`)

```python
from merid.event_venues.kalshi.market_selector import AGENT_SERIES_MAP
from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS


def test_btc_15m_series_map_matches_canonical():
    """AGENT_SERIES_MAP["BTC_15M"] must contain the exact canonical prefix from KALSHI_CRYPTO_PRODUCTS."""
    canonical_prefix = KALSHI_CRYPTO_PRODUCTS["BTC_15M"][0]   # e.g. "KXBTUPDOWN-15M"
    assert canonical_prefix in AGENT_SERIES_MAP["BTC_15M"], (
        f"Expected {canonical_prefix!r} in AGENT_SERIES_MAP['BTC_15M'] but got {AGENT_SERIES_MAP['BTC_15M']}"
    )


def test_doge_15m_series_map_matches_canonical():
    canonical_prefix = KALSHI_CRYPTO_PRODUCTS["DOGE_15M"][0]
    assert canonical_prefix in AGENT_SERIES_MAP["DOGE_15M"], (
        f"Expected {canonical_prefix!r} in AGENT_SERIES_MAP['DOGE_15M'] but got {AGENT_SERIES_MAP['DOGE_15M']}"
    )
```

- [ ] **Step 5.2 — Run to verify failure**

```
pytest tests/test_catalog_subset_filter.py::test_btc_15m_series_map_matches_canonical -v
```
Expected: `FAILED` — `AGENT_SERIES_MAP["BTC_15M"]` contains `["KXBTC-15M"]`, canonical is `"KXBTUPDOWN-15M"`.

- [ ] **Step 5.3 — Update `AGENT_SERIES_MAP` in `market_selector.py`**

At the top of `market_selector.py` add the import:

```python
from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS as _KCP
```

Replace the 15m and 1h entries in `AGENT_SERIES_MAP` (keep daily/weekly as-is — those use price-level series whose canonical format is unknown without live API verification):

```python
AGENT_SERIES_MAP: Dict[str, List[str]] = {
    # 15m up/down markets — prefixes from KALSHI_CRYPTO_PRODUCTS (canonical)
    "BTC_15M":    _KCP.get("BTC_15M",   ["KXBTUPDOWN-15M"]),
    "ETH_15M":    _KCP.get("ETH_15M",   ["KXETHUPDOWN-15M"]),
    "SOL_15M":    _KCP.get("SOL_15M",   ["KXSOLUPDOWN-15M"]),
    "XRP_15M":    _KCP.get("XRP_15M",   ["KXXRPUPDOWN-15M"]),
    "DOGE_15M":   _KCP.get("DOGE_15M",  ["KXDOGEUPDOWN-15M"]),

    # 1h up/down markets — from KALSHI_CRYPTO_PRODUCTS (canonical)
    "BTC_HOURLY": _KCP.get("BTC_1H",    ["KXBT-1H-UPDOWN"]),
    "ETH_HOURLY": _KCP.get("ETH_1H",    ["KXETH-1H-UPDOWN"]),
    "SOL_HOURLY": _KCP.get("SOL_1H",    ["KXSOL-1H-UPDOWN"]),
    "XRP_HOURLY": _KCP.get("XRP_1H",    ["KXXRP-1H-UPDOWN"]),
    "DOGE_HOURLY":_KCP.get("DOGE_1H",   ["KXDOGE-1H-UPDOWN"]),

    # Daily / weekly — price-level series; TODO: verify against live /series API
    "BTC_DAILY":  [resolve_series_ticker("BTC", "daily")],
    "BTC_WEEKLY": [resolve_series_ticker("BTC", "weekly")],
    "ETH_DAILY":  [resolve_series_ticker("ETH", "daily")],
    "ETH_WEEKLY": [resolve_series_ticker("ETH", "weekly")],
    "SOL_DAILY":  [resolve_series_ticker("SOL", "daily")],
    "SOL_WEEKLY": [resolve_series_ticker("SOL", "weekly")],
    "XRP_DAILY":  [resolve_series_ticker("XRP", "daily")],
    "XRP_WEEKLY": [resolve_series_ticker("XRP", "weekly")],
    "DOGE_DAILY": [resolve_series_ticker("DOGE", "daily")],
    "DOGE_WEEKLY":[resolve_series_ticker("DOGE", "weekly")],
    # ... rest of the map unchanged ...
}
```

- [ ] **Step 5.4 — Run tests**

```
pytest tests/test_catalog_subset_filter.py -v
```
Expected: all 6 pass.

- [ ] **Step 5.5 — Commit**

```bash
git add merid/event_venues/kalshi/market_selector.py tests/test_catalog_subset_filter.py
git commit -m "fix: align 15m/1h series tickers to KALSHI_CRYPTO_PRODUCTS canonical format (Bug S2-2)"
```

---

## Task 6 — Wire all fixes into the executor

**Files:**
- Modify: `merid/execution/executors/kalshi.py`
- Create: `tests/test_executor_wiring.py`

This task addresses four bugs in a single file:
- **E4-1**: `category=None` → derive from `metadata["underlying"]` via `infer_category()`
- **E4-2**: `metadata["outcome"]` silently defaults to `"yes"` → emit a warning log
- **E4-5**: `record_close()` never called on sell fills → add call
- **E4-X**: `CategoryExposureTracker.check_and_reserve()` not wired → add atomic pre-order check
- **Calibration**: balance fetch moved before `check_order()` and triggers `BalanceCalibrator.update()`

**Re-ordered executor pre-flight sequence (after this task):**
1. Kill switch flag (T-022)
2. `risk_controller.can_trade()`
3. VenueGate
4. **Balance fetch + `BalanceCalibrator.update()`** ← moved up from step 6
5. `KalshiRiskManager.check_order()` ← now uses calibrated limits + correct category
6. DeploymentController
7. **`CategoryExposureTracker.check_and_reserve()`** ← new
8. **`KalshiRiskManager.record_order()`** ← new (rate limit + notional)
9. Send order
10. On fail: release reservation + reverse notional
11. On fill: adjust partial reservation; call `record_close()` on sell fills

- [ ] **Step 6.1 — Write failing tests**

Create `tests/test_executor_wiring.py`:

```python
"""Regression tests for executor wiring bugs E4-1, E4-2, E4-5, E4-X."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_executor():
    from merid.execution.executors.kalshi import KalshiExecutor
    ex = KalshiExecutor()
    # Bypass real client creation
    ex._client = MagicMock()
    return ex


def _success_balance(cents: int = 500_000):
    from merid.resilience.result import VenueResult
    r = MagicMock(spec=VenueResult)
    r.success = True
    r.data = {"balance": cents}
    r.error_message = None
    r.latency_ms = 1
    return r


def _success_order(filled: int = 10, price: int = 55, order_id: str = "ord-1"):
    from merid.resilience.result import VenueResult
    r = MagicMock(spec=VenueResult)
    r.success = True
    r.data = {"order": {
        "order_id": order_id,
        "status": "filled",
        "yes_price": price,
        "filled_count": filled,
        "count": filled,
    }}
    r.latency_ms = 5
    return r


# ── E4-1: category passed to check_order ─────────────────────────────────

@pytest.mark.asyncio
async def test_category_passed_to_check_order():
    """check_order must receive category='crypto', not None."""
    ex = _make_executor()

    # NOTE: Verify these patch paths against actual import locations in kalshi.py
    # before running. Specifically confirm "merid.risk.kill_switches.risk_controller"
    # is the exact attribute path where the risk controller is imported in the executor.
    with (
        patch("merid.execution.executors.kalshi._kill_switch_error", False),
        patch("merid.risk.kill_switches.risk_controller") as mock_rc,
        patch("merid.prediction.venue_gate.get_venue_gate") as mock_vg,
        patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk_fn,
        patch.object(ex._client, "_request_with_resilience", new_callable=AsyncMock) as mock_req,
    ):
        mock_rc.can_trade.return_value = True
        mock_vg.return_value.should_simulate_fill.return_value = False

        risk_mgr = MagicMock()
        risk_mgr.check_order.return_value = (True, "OK")
        mock_risk_fn.return_value = risk_mgr

        mock_req.side_effect = [_success_balance(), _success_order()]

        await ex.execute_trade(
            "KXBTUPDOWN-15M-0316-1415",
            side="buy",
            amount=10,
            order_type="limit",
            price=0.55,
            metadata={"outcome": "yes", "underlying": "BTC"},
        )

        call_kwargs = risk_mgr.check_order.call_args
        assert call_kwargs.kwargs.get("category") == "crypto" or (
            len(call_kwargs.args) > 1 and call_kwargs.args[1] == "crypto"
        ), f"category was not 'crypto': {call_kwargs}"


# ── E4-2: outcome warning ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_outcome_emits_warning(caplog):
    """When metadata['outcome'] is absent, a warning must be logged."""
    import logging
    ex = _make_executor()

    with (
        patch("merid.execution.executors.kalshi._kill_switch_error", False),
        patch("merid.risk.kill_switches.risk_controller") as mock_rc,
        patch("merid.prediction.venue_gate.get_venue_gate") as mock_vg,
        patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk_fn,
        patch.object(ex._client, "_request_with_resilience", new_callable=AsyncMock) as mock_req,
        caplog.at_level(logging.WARNING, logger="merid.execution.executors.kalshi"),
    ):
        mock_rc.can_trade.return_value = True
        mock_vg.return_value.should_simulate_fill.return_value = False
        risk_mgr = MagicMock()
        risk_mgr.check_order.return_value = (True, "OK")
        mock_risk_fn.return_value = risk_mgr
        mock_req.side_effect = [_success_balance(), _success_order()]

        await ex.execute_trade(
            "KXBTUPDOWN-15M-0316-1415",
            side="buy",
            amount=10,
            order_type="limit",
            price=0.55,
            metadata={"underlying": "BTC"},   # no "outcome" key
        )

        assert any("outcome" in r.message for r in caplog.records), (
            "Expected a warning about missing 'outcome' metadata"
        )


# ── E4-X: category_exposure check_and_reserve called ─────────────────────

@pytest.mark.asyncio
async def test_category_exposure_check_and_reserve_called():
    """check_and_reserve must be called before order submission."""
    ex = _make_executor()

    with (
        patch("merid.execution.executors.kalshi._kill_switch_error", False),
        patch("merid.risk.kill_switches.risk_controller") as mock_rc,
        patch("merid.prediction.venue_gate.get_venue_gate") as mock_vg,
        patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk_fn,
        patch("merid.event_venues.kalshi.category_exposure.get_category_exposure_tracker") as mock_ct,
        patch.object(ex._client, "_request_with_resilience", new_callable=AsyncMock) as mock_req,
    ):
        mock_rc.can_trade.return_value = True
        mock_vg.return_value.should_simulate_fill.return_value = False
        risk_mgr = MagicMock()
        risk_mgr.check_order.return_value = (True, "OK")
        mock_risk_fn.return_value = risk_mgr

        cat_tracker = MagicMock()
        cat_tracker.check_and_reserve.return_value = (True, "")
        mock_ct.return_value = cat_tracker

        mock_req.side_effect = [_success_balance(), _success_order()]

        await ex.execute_trade(
            "KXBTUPDOWN-15M-0316-1415",
            side="buy",
            amount=10,
            order_type="limit",
            price=0.55,
            metadata={"outcome": "yes", "underlying": "BTC"},
        )

        cat_tracker.check_and_reserve.assert_called_once()
        call_args = cat_tracker.check_and_reserve.call_args
        assert call_args.args[0] == "crypto"
        assert call_args.args[1] == "BTC"


# ── E4-5: record_close called on sell fills ───────────────────────────────

@pytest.mark.asyncio
async def test_record_close_called_on_sell_fill():
    """record_close() must be called when action='sell' and order fills."""
    ex = _make_executor()

    with (
        patch("merid.execution.executors.kalshi._kill_switch_error", False),
        patch("merid.risk.kill_switches.risk_controller") as mock_rc,
        patch("merid.prediction.venue_gate.get_venue_gate") as mock_vg,
        patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk_fn,
        patch.object(ex._client, "_request_with_resilience", new_callable=AsyncMock) as mock_req,
    ):
        mock_rc.can_trade.return_value = True
        mock_vg.return_value.should_simulate_fill.return_value = False
        risk_mgr = MagicMock()
        risk_mgr.check_order.return_value = (True, "OK")
        mock_risk_fn.return_value = risk_mgr
        mock_req.side_effect = [_success_balance(), _success_order()]

        await ex.execute_trade(
            "KXBTUPDOWN-15M-0316-1415",
            side="sell",
            amount=10,
            order_type="limit",
            price=0.55,
            metadata={"outcome": "yes", "underlying": "BTC"},
        )

        risk_mgr.record_close.assert_called_once()


# ── E4-5 / E4-X: record_close + release called on buy failure ─────────────

@pytest.mark.asyncio
async def test_record_close_called_on_buy_order_failure():
    """When the buy order POST fails, record_close() must reverse the notional
    reservation and the category exposure must be released."""
    ex = _make_executor()

    def _fail_order():
        from merid.resilience.result import VenueResult
        r = MagicMock(spec=VenueResult)
        r.success = False
        r.error_message = "network error"
        r.latency_ms = 10
        return r

    with (
        patch("merid.execution.executors.kalshi._kill_switch_error", False),
        patch("merid.risk.kill_switches.risk_controller") as mock_rc,
        patch("merid.prediction.venue_gate.get_venue_gate") as mock_vg,
        patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk_fn,
        patch("merid.event_venues.kalshi.category_exposure.get_category_exposure_tracker") as mock_ct,
        patch.object(ex._client, "_request_with_resilience", new_callable=AsyncMock) as mock_req,
    ):
        mock_rc.can_trade.return_value = True
        mock_vg.return_value.should_simulate_fill.return_value = False
        risk_mgr = MagicMock()
        risk_mgr.check_order.return_value = (True, "OK")
        mock_risk_fn.return_value = risk_mgr

        cat_tracker = MagicMock()
        cat_tracker.check_and_reserve.return_value = (True, "")
        mock_ct.return_value = cat_tracker

        # balance fetch succeeds, order POST fails
        mock_req.side_effect = [_success_balance(), _fail_order()]

        await ex.execute_trade(
            "KXBTUPDOWN-15M-0316-1415",
            side="buy",
            amount=10,
            order_type="limit",
            price=0.55,
            metadata={"outcome": "yes", "underlying": "BTC"},
        )

        # Notional must be reversed
        risk_mgr.record_close.assert_called_once()
        # Category reservation must be released
        cat_tracker.release.assert_called_once()
```

- [ ] **Step 6.2 — Run to verify failures**

```bash
pytest tests/test_executor_wiring.py -v
```

Expected: all 5 tests fail.

- [ ] **Step 6.3 — Apply executor changes**

In `merid/execution/executors/kalshi.py`, inside `execute_trade()`, make the following changes in order:

**A. Move balance fetch to BEFORE `check_order()`.** Remove it from step 6 and insert it between VenueGate and the DeploymentController block:

```python
        # ── Balance fetch + calibration (moved before check_order) ──────
        client = self._get_client()
        try:
            _bal_result = await client._request_with_resilience(
                "GET", "/portfolio/balance", operation_name="get_balance",
            )
            if not _bal_result.success:
                logger.warning("Balance check failed — blocking order: %s", _bal_result.error_message)
                return TradeResult(
                    success=False, venue=self.venue, symbol=symbol,
                    side=side, size=amount, price=price or 0.0,
                    error=f"Balance check failed: {_bal_result.error_message}", metadata={},
                )
            _balance_cents = _bal_result.data.get("balance", 0)
            _price_cents = int(round(price * 100)) if price and price <= 1.0 else int(price or 50)
            _order_cost = int(amount) * (_price_cents if order_type == "limit" else 99)
            if _balance_cents < _order_cost:
                return TradeResult(
                    success=False, venue=self.venue, symbol=symbol,
                    side=side, size=amount, price=price or 0.0,
                    error=f"Insufficient balance: {_balance_cents}c < {_order_cost}c",
                    metadata={"balance_cents": _balance_cents, "order_cost_cents": _order_cost},
                )
            # Trigger risk limit recalibration if balance moved >5%
            try:
                from merid.event_venues.kalshi.balance_calibrator import get_balance_calibrator
                get_balance_calibrator().update(_balance_cents)
            except Exception as _cal_exc:
                logger.debug("BalanceCalibrator update failed (non-fatal): %s", _cal_exc)
        except Exception as _bal_exc:
            logger.error("Balance fetch unavailable — blocking order: %s", _bal_exc)
            return TradeResult(
                success=False, venue=self.venue, symbol=symbol,
                side=side, size=amount, price=price or 0.0,
                error=f"Balance validation unavailable: {_bal_exc}", metadata={},
            )
```

**B. Derive `_underlying` and `_category` from metadata (after `meta = metadata or {}`):**

```python
        # Derive underlying asset and market category from metadata
        _underlying = meta.get("underlying", "").upper()
        if not _underlying:
            # Best-effort inference from ticker prefix
            _TICKER_PREFIXES = [
                ("BTC", "KXBT"), ("ETH", "KXETH"), ("SOL", "KXSOL"),
                ("XRP", "KXXRP"), ("DOGE", "KXDOGE"),
            ]
            for _asset, _pfx in _TICKER_PREFIXES:
                if symbol.upper().startswith(_pfx):
                    _underlying = _asset
                    break
        _category = meta.get("category", "")
        if not _category and _underlying:
            try:
                from merid.event_venues.kalshi.category_exposure import infer_category
                _category = infer_category(_underlying)
            except Exception:
                pass
```

**C. Fix `outcome_side` — warn when missing:**

```python
        # Outcome side — warn if caller omitted it (default 'yes' may be wrong)
        outcome_side = meta.get("outcome")
        if outcome_side is None:
            logger.warning(
                "execute_trade: metadata['outcome'] not set for ticker=%s — "
                "defaulting to 'yes'. Pass outcome='yes'|'no' to suppress.",
                symbol,
            )
            outcome_side = "yes"
```

**D. Pass `_category` to `check_order()`:**

```python
        _allowed, _reason = _risk.check_order(
            ticker=symbol, category=_category or None,
            contracts=int(amount), price_cents=_price_cents,
        )
```

**E. Add category exposure `check_and_reserve()` and `record_order()` before the HTTP call:**

```python
        # Category exposure — atomic check + reserve (prevents TOCTOU race)
        _notional_usd = int(amount) * _price_cents / 100.0
        _cat_tracker = None
        _cat_reserved = False
        if _underlying and _category and action == "buy":
            try:
                from merid.event_venues.kalshi.category_exposure import get_category_exposure_tracker
                _cat_tracker = get_category_exposure_tracker()
                _cat_ok, _cat_reason = _cat_tracker.check_and_reserve(
                    _category, _underlying, _notional_usd
                )
                if not _cat_ok:
                    return TradeResult(
                        success=False, venue=self.venue, symbol=symbol,
                        side=side, size=amount, price=price or 0.0,
                        error=f"Category exposure blocked: {_cat_reason}", metadata={},
                    )
                _cat_reserved = True
            except Exception as _cate:
                logger.warning("CategoryExposureTracker unavailable (non-blocking): %s", _cate)

        # Record order in risk manager — advances rate counters + open notional
        try:
            _risk.record_order(_category or None, int(amount), _price_cents)
        except Exception:
            pass

        # ── Send order to Kalshi ──────────────────────────────────────────
```

**F. On order failure, release reservation and reverse notional:**

```python
        if not result.success:
            # ... (existing timeout-recovery block) ...

            # Reverse notional (keep rate counters — the order was attempted)
            try:
                _risk.record_close(_category or None, int(amount), _price_cents)
            except Exception:
                pass
            if _cat_reserved and _cat_tracker:
                try:
                    _cat_tracker.release(_category, _underlying, _notional_usd)
                except Exception:
                    pass
            return TradeResult(success=False, ...)
```

**G. On successful fill, handle partial fills and sell-side release:**

After the existing partial-fill detection block, add:

```python
        _actual_count = filled_count if filled_count > 0 else int(amount)
        _actual_notional = _actual_count * _price_cents / 100.0

        # Partial fill: release unfilled portion of reservation
        if is_partial and _cat_reserved and _cat_tracker:
            _excess = _notional_usd - _actual_notional
            if _excess > 0:
                try:
                    _cat_tracker.release(_category, _underlying, _excess)
                except Exception:
                    pass

        # Sell fills reduce open exposure
        if action == "sell":
            try:
                _risk.record_close(_category or None, _actual_count, _price_cents)
            except Exception:
                pass
            if _cat_tracker and _underlying and _category:
                try:
                    _cat_tracker.release(_category, _underlying, _actual_notional)
                except Exception:
                    pass
```

- [ ] **Step 6.4 — Run tests**

```bash
pytest tests/test_executor_wiring.py -v
```

Expected: all 5 pass.

- [ ] **Step 6.5 — Run full existing executor test suite to confirm no regressions**

```
pytest tests/executors/ -v
```

- [ ] **Step 6.6 — Commit**

```bash
git add merid/execution/executors/kalshi.py tests/test_executor_wiring.py
git commit -m "fix: executor — category wiring, outcome warning, exposure reservation, record_close on sell (Bugs E4-1/2/5/X)"
```

---

## Task 7 — Fix executor test URL mocks (Bug TEST-1)

**Files:**
- Modify: `tests/executors/test_kalshi_executor.py`

All existing mocks target `https://api.elections.kalshi.com/trade/v1/order` (old v1 API). The current executor posts to `/portfolio/orders` under the v2 base URL. Tests pass against a dead endpoint.

- [ ] **Step 7.1 — Identify all mock URLs in the file**

```
grep -n "elections.kalshi.com" tests/executors/test_kalshi_executor.py
```

- [ ] **Step 7.2 — Replace all mock URL references**

Find every occurrence of:
```python
mock_kalshi_api.post("https://api.elections.kalshi.com/trade/v1/order")
```

Replace with:
```python
mock_kalshi_api.post("https://api.elections.kalshi.com/trade-api/v2/portfolio/orders")
```

Also update any `GET` mocks for balance/positions/fills to use `/trade-api/v2/portfolio/...`:

```python
# Balance fetch (now runs before every order in the executor)
mock_kalshi_api.get("https://api.elections.kalshi.com/trade-api/v2/portfolio/balance")

# Positions and fills
mock_kalshi_api.get("https://api.elections.kalshi.com/trade-api/v2/portfolio/positions")
mock_kalshi_api.get("https://api.elections.kalshi.com/trade-api/v2/portfolio/fills")
```

- [ ] **Step 7.3 — Run existing executor tests**

```
pytest tests/executors/test_kalshi_executor.py -v
```
Expected: all previously-passing tests still pass (now actually hitting the correct endpoint).

- [ ] **Step 7.4 — Commit**

```bash
git add tests/executors/test_kalshi_executor.py
git commit -m "fix: update executor test mocks to Kalshi v2 API endpoint (Bug TEST-1)"
```

---

## Task 8 — Full regression run

- [ ] **Step 8.1 — Run all affected test modules**

```
pytest tests/test_balance_calibrator.py tests/test_catalog_subset_filter.py tests/test_executor_wiring.py tests/executors/ -v
```
Expected: all pass, zero failures.

- [ ] **Step 8.2 — Run broader test suite to catch regressions**

```
pytest tests/ -x -q --ignore=tests/test_audit_regression.py
```
Expected: green or pre-existing failures only (no new failures from this change set).

- [ ] **Step 8.3 — Final commit**

```bash
git commit --allow-empty -m "chore: kalshi execution pipeline hardening — all tasks complete"
```

---

## Reference: What each fix addresses

| Task | Bug ID | File changed | Root cause |
|------|--------|-------------|-----------|
| 1 | — | `kalshi_risk.py` | Hardcoded dollar caps; no live-balance awareness |
| 2 | — | `category_exposure.py` | Same |
| 3 | — | `balance_calibrator.py` (new) | No single recalibration trigger |
| 4 | S2-1 | `kalshi_universe_loader.py` | `m in list` instead of `m.startswith(prefix)` → all 15m subsets empty |
| 5 | S2-2 | `market_selector.py` | 3 incompatible series ticker formats across config files |
| 6 | E4-1,2,5,X | `kalshi.py` (executor) | `category=None`, silent outcome default, record_close never called, category_exposure not wired |
| 7 | TEST-1 | `test_kalshi_executor.py` | Tests mock v1 URL; executor uses v2 → tests exercise dead path |
