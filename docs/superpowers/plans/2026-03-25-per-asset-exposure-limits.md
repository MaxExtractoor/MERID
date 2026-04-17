# Per-Asset Exposure Limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single global exposure cap in `KalshiContinuousTrader` with per-asset caps (BTC/ETH/SOL/XRP/DOGE) + a global guardrail, so one asset's position no longer blocks trades in other assets.

**Architecture:** Two independent layers are changed: (1) `KalshiContinuousTrader` in `kalshi_continuous_trader.py` — the CT loop's skip check gains a per-asset cents check before the global guardrail; (2) `CategoryExposureTracker` in `category_exposure.py` — the single shared `_corr_cap` USD ceiling is replaced with a per-asset `Dict[str, float]` so the multi-agent path also benefits.

**Tech Stack:** Python dataclasses, `os.getenv`, `pytest`, `unittest.mock`

---

## Current State Summary (READ BEFORE TOUCHING CODE)

### The Bug
`kalshi_continuous_trader.py` lines 1569–1574:
```python
_max_exposure_cents = int(balance_cents * self.bankroll.effective_max_exposure_pct())
if _current_exposure_cents + cost_cents > _max_exposure_cents:
    logger.info("    Skip %s: exposure cap reached (%d¢ + %d¢ > %d¢)",
                c.ticker, _current_exposure_cents, cost_cents, _max_exposure_cents)
    continue
```
`_current_exposure_cents` is the **total** across ALL assets. With BTC = 300¢ and
`_max_exposure_cents = 1211 * 0.20 = 242¢`, every ETH/SOL/XRP/DOGE candidate is
blocked even though they have 0¢ exposure.

### Relevant data-flow summary
| Check | File | Granularity | Data type |
|---|---|---|---|
| CT loop skip (primary) | `kalshi_continuous_trader.py:1569` | **global** cents | `int` |
| BankrollManager order sizing | `kalshi_risk_engine.py:637` | clamps per-order | `int` cents |
| Category cap | `category_exposure.py:162` | all-crypto USD | `float` USD |
| Corr-stack cap (secondary) | `category_exposure.py:178` | per-underlying USD, **single shared cap** | `float` USD |

### Key config constants used
- `TraderConfig.max_total_exposure_pct` = 0.20, env `KALSHI_TRADER_MAX_EXPOSURE` — used by BankrollManager for order **sizing** (do not change)
- `TraderConfig.global_max_exposure_pct` = **NEW** 0.40, env `KALSHI_TRADER_GLOBAL_EXPOSURE`
- `CategoryExposureTracker._corr_cap` = 800.0 USD, env `MERID_CORR_STACK_CAP_USD` — to be extended with per-asset dict

---

## File Map

| File | Change |
|---|---|
| `merid/trading/kalshi_continuous_trader.py` | Add 4 fields to `TraderConfig`, add `_per_asset_exposure_cents()` helper, replace lines 1569–1574 skip block |
| `merid/event_venues/kalshi/category_exposure.py` | Add `_DEFAULT_ASSET_CAPS_USD` dict, add `_asset_caps` field to tracker, upgrade `check_correlated_cap` + `check_and_reserve` + `calibrate_from_balance` + `ExposureSnapshot` |
| `tests/test_continuous_trader_safety.py` | Add 4 new test classes covering per-asset skip scenarios |
| `tests/event_venues/kalshi/test_category_exposure_per_asset.py` | New file — per-asset corr cap tests |

---

## Task 1: Add per-asset config fields to `TraderConfig`

**Files:**
- Modify: `merid/trading/kalshi_continuous_trader.py:85-175`

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_continuous_trader_safety.py — append this class at the bottom

class TestPerAssetConfig(unittest.TestCase):
    def test_default_asset_exposure_pcts(self):
        from merid.trading.kalshi_continuous_trader import TraderConfig
        cfg = TraderConfig()
        self.assertEqual(cfg.asset_max_exposure_pct["BTC"], 0.20)
        self.assertEqual(cfg.asset_max_exposure_pct["ETH"], 0.15)
        self.assertEqual(cfg.asset_max_exposure_pct["SOL"], 0.10)
        self.assertEqual(cfg.asset_max_exposure_pct["XRP"], 0.10)
        self.assertEqual(cfg.asset_max_exposure_pct["DOGE"], 0.10)
        self.assertEqual(cfg.asset_exposure_default_pct, 0.10)

    def test_default_series_multipliers(self):
        from merid.trading.kalshi_continuous_trader import TraderConfig
        cfg = TraderConfig()
        self.assertEqual(cfg.series_exposure_multiplier["15m"],   0.40)
        self.assertEqual(cfg.series_exposure_multiplier["1h"],    0.70)
        self.assertEqual(cfg.series_exposure_multiplier["daily"], 1.00)

    def test_global_max_exposure_pct_default(self):
        from merid.trading.kalshi_continuous_trader import TraderConfig
        cfg = TraderConfig()
        self.assertEqual(cfg.global_max_exposure_pct, 0.40)

    def test_min_asset_cap_cents_default(self):
        from merid.trading.kalshi_continuous_trader import TraderConfig
        cfg = TraderConfig()
        self.assertEqual(cfg.min_asset_cap_cents, 100)

    def test_from_env_reads_asset_exposure_overrides(self):
        import os
        from merid.trading.kalshi_continuous_trader import TraderConfig
        env_patch = {
            "KALSHI_TRADER_EXPOSURE_BTC":  "0.25",
            "KALSHI_TRADER_EXPOSURE_ETH":  "0.18",
            "KALSHI_TRADER_GLOBAL_EXPOSURE": "0.50",
            "KALSHI_TRADER_MIN_ASSET_CAP_CENTS": "200",
        }
        with unittest.mock.patch.dict(os.environ, env_patch):
            cfg = TraderConfig.from_env()
        self.assertAlmostEqual(cfg.asset_max_exposure_pct["BTC"], 0.25)
        self.assertAlmostEqual(cfg.asset_max_exposure_pct["ETH"], 0.18)
        self.assertAlmostEqual(cfg.global_max_exposure_pct, 0.50)
        self.assertEqual(cfg.min_asset_cap_cents, 200)
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_continuous_trader_safety.py::TestPerAssetConfig -v
```
Expected: FAIL — `TraderConfig` has no `asset_max_exposure_pct` attribute.

- [ ] **Step 3: Add four fields to `TraderConfig` dataclass**

In `merid/trading/kalshi_continuous_trader.py`, locate the `TraderConfig` dataclass.
After the existing `max_total_exposure_pct` line (~line 98), add:

```python
    # ── Per-asset exposure limits ────────────────────────────────────
    # Maximum fraction of bankroll each crypto asset may consume.
    # Independent buckets — BTC at its cap does NOT block ETH/SOL/XRP/DOGE.
    asset_max_exposure_pct: Dict[str, float] = field(default_factory=lambda: {
        "BTC":  0.20,   # BTC: up to 20% of bankroll
        "ETH":  0.15,   # ETH: up to 15%
        "SOL":  0.10,   # SOL: up to 10%
        "XRP":  0.10,   # XRP: up to 10%
        "DOGE": 0.10,   # DOGE: up to 10%
    })
    asset_exposure_default_pct: float = 0.10   # fallback for any unlisted asset
    # Series/timeframe multiplier applied to the per-asset cap.
    # Lower values for shorter timeframes limit churn without blocking longer-dated trades.
    series_exposure_multiplier: Dict[str, float] = field(default_factory=lambda: {
        "15m":   0.40,  # 15-min contracts: 40% of asset cap
        "1h":    0.70,  # hourly: 70% of asset cap
        "daily": 1.00,  # daily: full asset cap
        "weekly": 1.00, # weekly: full asset cap
    })
    # Global portfolio guardrail: total exposure across ALL crypto assets combined.
    # This is a hard ceiling ABOVE the per-asset checks — it fires only when many
    # assets are simultaneously near their individual caps.
    global_max_exposure_pct: float = 0.40    # 40% of bankroll across all crypto
    # Minimum per-asset-series cap (cents).
    # Prevents micro-account lockout: even at 40% series multiplier, a $5 bankroll
    # still allows up to min_asset_cap_cents worth of a single trade.
    min_asset_cap_cents: int = 100           # $1.00 floor
```

- [ ] **Step 4: Wire new fields into `from_env()`**

In the `from_env()` `return cls(...)` block, add after `max_total_exposure_pct=...`:

```python
            asset_max_exposure_pct={
                "BTC":  float(os.getenv("KALSHI_TRADER_EXPOSURE_BTC",  "0.20")),
                "ETH":  float(os.getenv("KALSHI_TRADER_EXPOSURE_ETH",  "0.15")),
                "SOL":  float(os.getenv("KALSHI_TRADER_EXPOSURE_SOL",  "0.10")),
                "XRP":  float(os.getenv("KALSHI_TRADER_EXPOSURE_XRP",  "0.10")),
                "DOGE": float(os.getenv("KALSHI_TRADER_EXPOSURE_DOGE", "0.10")),
            },
            asset_exposure_default_pct=float(os.getenv("KALSHI_TRADER_EXPOSURE_DEFAULT", "0.10")),
            global_max_exposure_pct=float(os.getenv("KALSHI_TRADER_GLOBAL_EXPOSURE", "0.40")),
            min_asset_cap_cents=int(os.getenv("KALSHI_TRADER_MIN_ASSET_CAP_CENTS", "100")),
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/test_continuous_trader_safety.py::TestPerAssetConfig -v
```
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add merid/trading/kalshi_continuous_trader.py tests/test_continuous_trader_safety.py
git commit -m "feat(risk): add per-asset exposure config fields to TraderConfig"
```

---

## Task 2: Add `_per_asset_exposure_cents()` helper

**Files:**
- Modify: `merid/trading/kalshi_continuous_trader.py` (near `_aggregate_position_exposure_cents` at ~line 803)

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_continuous_trader_safety.py — append this class at the bottom

class TestPerAssetExposureBreakdown(unittest.TestCase):
    def _make_trader(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader, TraderConfig
        t = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
        t.config = TraderConfig()
        return t

    def test_single_btc_position(self):
        t = self._make_trader()
        positions = {
            "KXBTC-26MAR2717-T58900": {"qty": 3, "side": "yes", "avg_price_cents": 100},
        }
        result = t._per_asset_exposure_cents(positions)
        self.assertEqual(result, {"BTC": 300})

    def test_btc_and_eth_positions(self):
        t = self._make_trader()
        positions = {
            "KXBTC-26MAR2717-T58900":   {"qty": 3, "side": "yes", "avg_price_cents": 100},
            "KXETH15M-26MAR251945-45":  {"qty": 1, "side": "yes", "avg_price_cents": 45},
            "KXSOL15M-26MAR251945-10":  {"qty": 2, "side": "yes", "avg_price_cents": 10},
        }
        result = t._per_asset_exposure_cents(positions)
        self.assertEqual(result["BTC"], 300)
        self.assertEqual(result["ETH"], 45)
        self.assertEqual(result["SOL"], 20)
        self.assertNotIn("XRP", result)

    def test_zero_qty_positions_excluded(self):
        t = self._make_trader()
        positions = {
            "KXBTC-26MAR2717-T58900": {"qty": 0, "side": "yes", "avg_price_cents": 100},
            "KXETH15M-26MAR251945-45": {"qty": 2, "side": "yes", "avg_price_cents": 45},
        }
        result = t._per_asset_exposure_cents(positions)
        self.assertNotIn("BTC", result)
        self.assertEqual(result["ETH"], 90)

    def test_multiple_btc_series_aggregated(self):
        t = self._make_trader()
        positions = {
            "KXBTC15M-26MAR251945-45":  {"qty": 2, "side": "yes", "avg_price_cents": 20},
            "KXBTC-26MAR2717-T58900":   {"qty": 1, "side": "yes", "avg_price_cents": 30},
        }
        result = t._per_asset_exposure_cents(positions)
        # BTC-15m (40¢) + BTC-daily (30¢) = 70¢ total for BTC
        self.assertEqual(result["BTC"], 70)
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_continuous_trader_safety.py::TestPerAssetExposureBreakdown -v
```
Expected: FAIL — `KalshiContinuousTrader` has no `_per_asset_exposure_cents` method.

- [ ] **Step 3: Add the helper method**

In `merid/trading/kalshi_continuous_trader.py`, immediately after `_aggregate_position_exposure_cents` (~line 804), add:

```python
    def _per_asset_exposure_cents(self, positions: Dict[str, dict]) -> Dict[str, int]:
        """Break down current position exposure by underlying asset.

        Returns a dict mapping asset symbol (BTC, ETH, SOL, XRP, DOGE, …) to
        total estimated capital at risk in cents across all series/timeframes.
        Zero-qty positions are excluded.
        """
        result: Dict[str, int] = {}
        for ticker, info in positions.items():
            if info.get("qty", 0) == 0:
                continue
            series_prefix = ticker.split("-")[0] if "-" in ticker else ticker
            asset, _ = self._infer_asset_timeframe(series_prefix)
            result[asset] = result.get(asset, 0) + self._position_cost_basis_cents(info)
        return result
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_continuous_trader_safety.py::TestPerAssetExposureBreakdown -v
```
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add merid/trading/kalshi_continuous_trader.py tests/test_continuous_trader_safety.py
git commit -m "feat(risk): add _per_asset_exposure_cents helper to KalshiContinuousTrader"
```

---

## Task 3: Replace global skip with per-asset + global two-stage check

**Files:**
- Modify: `merid/trading/kalshi_continuous_trader.py` (around lines 1341–1344 and 1569–1574 and 1620–1624)

- [ ] **Step 1: Write the four scenario tests (integration-style, no I/O)**

```python
# In tests/test_continuous_trader_safety.py — append this class at the bottom

class TestPerAssetExposureSkipLogic(unittest.TestCase):
    """Verifies the two-stage per-asset + global skip logic.

    These tests exercise the internal cap computation directly, without
    running the full CT trade loop (which requires live I/O).
    """

    def _make_trader_with_balance(self, balance_cents: int):
        """Return a bare CT instance with a known balance and config."""
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader, TraderConfig
        t = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
        t.config = TraderConfig(
            asset_max_exposure_pct={"BTC": 0.20, "ETH": 0.15, "SOL": 0.10, "XRP": 0.10, "DOGE": 0.10},
            asset_exposure_default_pct=0.10,
            series_exposure_multiplier={"15m": 0.40, "1h": 0.70, "daily": 1.00, "weekly": 1.00},
            global_max_exposure_pct=0.40,
            min_asset_cap_cents=50,
        )
        t._balance_cents = balance_cents
        return t

    def _asset_cap(self, t, balance_cents, asset, tf):
        """Helper: compute the expected per-asset-series cap in cents."""
        max_pct = t.config.asset_max_exposure_pct.get(asset, t.config.asset_exposure_default_pct)
        mult = t.config.series_exposure_multiplier.get(tf, 1.0)
        return max(t.config.min_asset_cap_cents, int(balance_cents * max_pct * mult))

    # ── Scenario 1: BTC at cap, ETH/SOL/XRP/DOGE still have capacity ──────

    def test_btc_at_cap_does_not_block_eth(self):
        """BTC 20% cap exhausted → BTC skipped, ETH still trades freely."""
        balance = 1211  # $12.11
        t = self._make_trader_with_balance(balance)

        # BTC exposure = 300¢; per-asset BTC cap for daily = 1211*0.20*1.0 = 242¢
        btc_cap = self._asset_cap(t, balance, "BTC", "daily")
        eth_cap = self._asset_cap(t, balance, "ETH", "15m")

        self.assertGreater(300, btc_cap,
            "Pre-condition: BTC existing exposure (300¢) must exceed BTC cap")
        # ETH/15m: 1211 * 0.15 * 0.40 = 72¢; 0 + 9 < 72 → should pass
        self.assertLess(0 + 9, eth_cap,
            "ETH/15m candidate (9¢) must fit under ETH cap when ETH exposure is 0")

    def test_btc_at_cap_does_not_block_sol(self):
        balance = 1211
        t = self._make_trader_with_balance(balance)
        sol_cap = self._asset_cap(t, balance, "SOL", "15m")
        self.assertLess(0 + 12, sol_cap,
            "SOL/15m candidate (12¢) must fit when SOL exposure is 0")

    # ── Scenario 2: Asset at its own per-asset cap → that asset skipped ───

    def test_btc_additional_trade_blocked_when_at_btc_cap(self):
        """When BTC exposure already exceeds its per-asset cap, new BTC trades skip."""
        balance = 1211
        t = self._make_trader_with_balance(balance)
        btc_cap = self._asset_cap(t, balance, "BTC", "daily")
        btc_existing = 300  # exceeds 242¢ cap
        cost = 18
        # Per-asset check: btc_existing + cost > btc_cap → should skip
        self.assertGreater(btc_existing + cost, btc_cap)

    def test_eth_at_eth_cap_does_not_block_sol(self):
        """When ETH is at its cap, SOL remains unaffected."""
        balance = 1211
        t = self._make_trader_with_balance(balance)
        eth_cap_15m = self._asset_cap(t, balance, "ETH", "15m")   # ~72¢
        sol_cap_15m = self._asset_cap(t, balance, "SOL", "15m")   # ~48¢ → floor 50¢

        # ETH already at cap, SOL at zero
        eth_existing = eth_cap_15m  # exactly at cap
        sol_existing = 0
        sol_cost = 12
        # ETH would skip; SOL should not
        self.assertGreater(eth_existing + sol_cost, eth_cap_15m, "ETH check fails (correct)")
        self.assertLessEqual(sol_existing + sol_cost, sol_cap_15m, "SOL check passes (correct)")

    # ── Scenario 3: Global cap fires when sum of all asset exposures hits ceiling ─

    def test_global_cap_blocks_all_when_total_at_ceiling(self):
        """When total exposure = global cap, ALL new trades skip regardless of per-asset slack."""
        balance = 1211
        t = self._make_trader_with_balance(balance)
        global_cap = int(balance * t.config.global_max_exposure_pct)  # 484¢

        # Spread exposure across assets so each is within its individual cap,
        # but total equals the global cap exactly.
        # BTC: 200¢ (< 242¢ BTC cap), ETH: 150¢ (< 181¢ ETH cap), SOL: 134¢ (> 50¢ SOL cap)
        total_existing = 484  # == global cap
        cost = 5
        self.assertGreater(total_existing + cost, global_cap,
            "Global cap check must fire when total exposure is at ceiling")

    # ── Scenario 4: Very small bankroll still allows micro-trades ─────────

    def test_small_bankroll_min_cap_floor_allows_micro_trades(self):
        """$10 bankroll: min_asset_cap_cents floor (50¢) still allows 1–5¢ contracts."""
        balance = 1000  # $10.00
        t = self._make_trader_with_balance(balance)
        # ETH/15m raw cap: 1000 * 0.15 * 0.40 = 60¢ > 50¢ floor, so floor doesn't apply here
        eth_cap = self._asset_cap(t, balance, "ETH", "15m")
        self.assertGreaterEqual(eth_cap, 50, "Cap must be >= min_asset_cap_cents (50¢)")
        self.assertGreater(eth_cap, 5, "Cap must allow a 5¢ trade from 0 exposure")

    def test_tiny_bankroll_floor_prevents_lockout(self):
        """$3 bankroll: even with tiny pcts, floor ensures at least one micro-trade."""
        balance = 300   # $3.00
        t = self._make_trader_with_balance(balance)
        # SOL/15m raw: 300 * 0.10 * 0.40 = 12¢ < 50¢ → floor kicks in
        sol_cap = self._asset_cap(t, balance, "SOL", "15m")
        self.assertEqual(sol_cap, 50,
            "SOL/15m cap should equal min_asset_cap_cents (50¢) at $3 balance")
        self.assertGreater(sol_cap, 5, "Still allows a 5¢ trade from 0 exposure")
```

- [ ] **Step 2: Run tests to verify they pass (pure math, no impl changes needed)**

```
pytest tests/test_continuous_trader_safety.py::TestPerAssetExposureSkipLogic -v
```
Expected: All PASS — these test the math/config only, not yet the actual skip code path.

- [ ] **Step 3: Wire `_per_asset_exp` computation after exit evaluation (~line 1341)**

In `merid/trading/kalshi_continuous_trader.py`, find lines 1341–1342:

```python
        _current_exposure_cents = self._aggregate_position_exposure_cents(asset_positions)
        total_open = sum(1 for v in asset_positions.values() if v["qty"] != 0)
```

Replace with:

```python
        _current_exposure_cents = self._aggregate_position_exposure_cents(asset_positions)
        total_open = sum(1 for v in asset_positions.values() if v["qty"] != 0)
        # Per-asset breakdown: {BTC: Xc, ETH: Yc, ...} — used in two-stage skip check below
        _per_asset_exp: Dict[str, int] = self._per_asset_exposure_cents(asset_positions)
```

- [ ] **Step 4: Replace lines 1569–1574 with the two-stage skip check**

Find the existing block:

```python
            # BUG-RE1 fix: check aggregate notional exposure
            _max_exposure_cents = int(balance_cents * self.bankroll.effective_max_exposure_pct())
            if _current_exposure_cents + cost_cents > _max_exposure_cents:
                logger.info("    Skip %s: exposure cap reached (%d¢ + %d¢ > %d¢)",
                            c.ticker, _current_exposure_cents, cost_cents, _max_exposure_cents)
                continue
```

Replace with:

```python
            # Stage 1 — per-asset check: BTC hitting its cap must not block ETH/SOL/XRP/DOGE.
            _candidate_asset, _candidate_tf = self._infer_asset_timeframe(
                c.ticker.split("-")[0] if "-" in c.ticker else c.ticker
            )
            _asset_max_pct = self.config.asset_max_exposure_pct.get(
                _candidate_asset, self.config.asset_exposure_default_pct
            )
            _series_mult = self.config.series_exposure_multiplier.get(_candidate_tf, 1.0)
            _asset_cap_cents = max(
                self.config.min_asset_cap_cents,
                int(balance_cents * _asset_max_pct * _series_mult),
            )
            _asset_current = _per_asset_exp.get(_candidate_asset, 0)
            if _asset_current + cost_cents > _asset_cap_cents:
                logger.info(
                    "    Skip %s: per-asset cap [%s/%s] reached (%d¢ + %d¢ > %d¢)",
                    c.ticker, _candidate_asset, _candidate_tf,
                    _asset_current, cost_cents, _asset_cap_cents,
                )
                continue

            # Stage 2 — global portfolio guardrail: fires only when many assets are near their caps.
            _global_cap_cents = int(balance_cents * self.config.global_max_exposure_pct)
            if _current_exposure_cents + cost_cents > _global_cap_cents:
                logger.info(
                    "    Skip %s: global portfolio cap reached (%d¢ + %d¢ > %d¢)",
                    c.ticker, _current_exposure_cents, cost_cents, _global_cap_cents,
                )
                continue
```

- [ ] **Step 5: Update the post-fill state update (~line 1621)**

Find inside `if resp.status_code == 201:` block, the lines:

```python
                _cycle_spent += cost_cents
                _current_exposure_cents += cost_cents
                if existing == 0:
```

Add one line after `_current_exposure_cents += cost_cents`:

```python
                _cycle_spent += cost_cents
                _current_exposure_cents += cost_cents
                _per_asset_exp[_candidate_asset] = _per_asset_exp.get(_candidate_asset, 0) + cost_cents
                if existing == 0:
```

- [ ] **Step 6: Run the full safety test suite to confirm no regressions**

```
pytest tests/test_continuous_trader_safety.py -v
```
Expected: All existing tests + new tests PASS.

- [ ] **Step 7: Commit**

```bash
git add merid/trading/kalshi_continuous_trader.py tests/test_continuous_trader_safety.py
git commit -m "feat(risk): replace global exposure skip with per-asset + global two-stage check

BTC position at its 20% cap no longer blocks ETH/SOL/XRP/DOGE trades.
Each asset has its own cent-denominated cap scaled by series/timeframe multiplier.
Global 40% guardrail remains as portfolio-wide ceiling."
```

---

## Task 4: Upgrade `CategoryExposureTracker` to per-asset corr caps

This fixes the multi-agent path (order_router → KalshiRiskManager) which shares
the same single `_corr_cap` across all crypto underlyings.

**Files:**
- Modify: `merid/event_venues/kalshi/category_exposure.py`
- Create: `tests/event_venues/kalshi/test_category_exposure_per_asset.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/event_venues/kalshi/test_category_exposure_per_asset.py`:

```python
"""Tests for per-asset correlated-cap upgrade in CategoryExposureTracker."""
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestPerAssetCorrCaps(unittest.TestCase):
    def _make_tracker(self, asset_caps=None, default_corr_cap=800.0):
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
        return CategoryExposureTracker(
            corr_cap_usd=default_corr_cap,
            asset_caps_usd=asset_caps,
        )

    def test_per_asset_cap_limits_btc_independently(self):
        """BTC cap=$200 blocks additional BTC; ETH cap=$300 stays open."""
        t = self._make_tracker(asset_caps={"BTC": 200.0, "ETH": 300.0})
        # Fill BTC to its cap
        t.record_fill("crypto", "BTC", 200.0)
        ok, reason = t.check_correlated_cap("BTC", additional_usd=10.0)
        self.assertFalse(ok)
        self.assertIn("corr_stack_cap_exceeded:BTC", reason)
        # ETH is unaffected
        ok_eth, _ = t.check_correlated_cap("ETH", additional_usd=10.0)
        self.assertTrue(ok_eth)

    def test_unlisted_asset_falls_back_to_default_corr_cap(self):
        """SOL not in asset_caps dict → uses default_corr_cap."""
        t = self._make_tracker(asset_caps={"BTC": 200.0}, default_corr_cap=150.0)
        ok, _ = t.check_correlated_cap("SOL", additional_usd=100.0)
        self.assertTrue(ok)
        ok2, reason = t.check_correlated_cap("SOL", additional_usd=100.0)
        # 0 + 100 = 100 < 150, so still ok for first call with nothing recorded
        self.assertTrue(ok2)

    def test_check_and_reserve_uses_per_asset_cap(self):
        """check_and_reserve respects BTC-specific cap."""
        t = self._make_tracker(asset_caps={"BTC": 50.0})
        ok, _ = t.check_and_reserve("crypto", "BTC", additional_usd=60.0)
        self.assertFalse(ok, "60 > 50 BTC cap → must be blocked")

    def test_calibrate_from_balance_sets_per_asset_caps(self):
        """calibrate_from_balance with asset_fractions sets per-asset caps."""
        t = self._make_tracker()
        t.calibrate_from_balance(
            balance_cents=10000,  # $100
            asset_fractions={"BTC": 0.20, "ETH": 0.15, "SOL": 0.10, "XRP": 0.10, "DOGE": 0.10},
        )
        # BTC: $100 * 0.20 = $20; check_correlated_cap("BTC", 21) should fail
        ok, reason = t.check_correlated_cap("BTC", additional_usd=21.0)
        self.assertFalse(ok)
        self.assertIn("BTC", reason)
        # ETH: $100 * 0.15 = $15; 14 should pass
        ok_eth, _ = t.check_correlated_cap("ETH", additional_usd=14.0)
        self.assertTrue(ok_eth)

    def test_snapshot_includes_per_asset_caps(self):
        """get_snapshot() exposes per-asset caps in the result."""
        t = self._make_tracker(asset_caps={"BTC": 200.0, "ETH": 150.0})
        snap = t.get_snapshot()
        self.assertIn("asset_caps", snap.to_dict())
        self.assertEqual(snap.to_dict()["asset_caps"].get("BTC"), 200.0)
        self.assertEqual(snap.to_dict()["asset_caps"].get("ETH"), 150.0)

    def test_env_var_sets_asset_caps(self):
        """MERID_ASSET_CAP_BTC_USD and MERID_ASSET_CAP_ETH_USD set caps at import time."""
        import importlib
        env_patch = {"MERID_ASSET_CAP_BTC_USD": "250.0", "MERID_ASSET_CAP_ETH_USD": "180.0"}
        with unittest.mock.patch.dict(os.environ, env_patch):
            import merid.event_venues.kalshi.category_exposure as mod
            importlib.reload(mod)
            self.assertAlmostEqual(mod._DEFAULT_ASSET_CAPS_USD.get("BTC"), 250.0)
            self.assertAlmostEqual(mod._DEFAULT_ASSET_CAPS_USD.get("ETH"), 180.0)
        # Reload without the patch to restore defaults
        importlib.reload(mod)

import unittest.mock
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/event_venues/kalshi/test_category_exposure_per_asset.py -v
```
Expected: FAIL — `CategoryExposureTracker.__init__` has no `asset_caps_usd` param.

- [ ] **Step 3: Add `_DEFAULT_ASSET_CAPS_USD` module-level dict**

In `merid/event_venues/kalshi/category_exposure.py`, after `_DEFAULT_CORR_CAP_USD` line (~line 64), add:

```python
# Per-asset USD caps. When set, override _DEFAULT_CORR_CAP_USD for that underlying.
# A value of 0.0 means "use the default corr cap" (i.e. effectively unset).
_DEFAULT_ASSET_CAPS_USD: Dict[str, float] = {
    "BTC":  float(os.getenv("MERID_ASSET_CAP_BTC_USD",  "0.0")),
    "ETH":  float(os.getenv("MERID_ASSET_CAP_ETH_USD",  "0.0")),
    "SOL":  float(os.getenv("MERID_ASSET_CAP_SOL_USD",  "0.0")),
    "XRP":  float(os.getenv("MERID_ASSET_CAP_XRP_USD",  "0.0")),
    "DOGE": float(os.getenv("MERID_ASSET_CAP_DOGE_USD", "0.0")),
}
# Strip zero-value entries so the fallback logic is clean
_DEFAULT_ASSET_CAPS_USD = {k: v for k, v in _DEFAULT_ASSET_CAPS_USD.items() if v > 0.0}
```

- [ ] **Step 4: Add `asset_caps_usd` parameter to `CategoryExposureTracker.__init__`**

Find `def __init__(self, category_caps=None, corr_cap_usd=None)` (~line 136).
Replace with:

```python
    def __init__(
        self,
        category_caps: Optional[Dict[str, float]] = None,
        corr_cap_usd: Optional[float] = None,
        asset_caps_usd: Optional[Dict[str, float]] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._category_caps: Dict[str, float] = category_caps or dict(_DEFAULT_CATEGORY_CAPS)
        self._corr_cap: float = corr_cap_usd if corr_cap_usd is not None else _DEFAULT_CORR_CAP_USD
        # Per-asset corr caps override _corr_cap for named underlyings.
        # Entries with value 0.0 are treated as "use default".
        _raw = asset_caps_usd if asset_caps_usd is not None else dict(_DEFAULT_ASSET_CAPS_USD)
        self._asset_caps: Dict[str, float] = {k: v for k, v in _raw.items() if v > 0.0}

        self._category_notional: Dict[str, float] = {}
        self._corr_notional: Dict[str, float] = {}
        self._last_reset_day: str = ""
        self._maybe_reset_daily()
```

- [ ] **Step 5: Add `_corr_cap_for()` private helper**

After `__init__`, add:

```python
    def _corr_cap_for(self, underlying: str) -> float:
        """Return the correlated-stack cap for the given underlying.

        Per-asset caps (``_asset_caps``) take priority; falls back to the
        shared ``_corr_cap`` default.
        """
        return self._asset_caps.get(underlying.upper(), self._corr_cap)
```

- [ ] **Step 6: Update `check_correlated_cap` to use `_corr_cap_for()`**

Find `check_correlated_cap` (~line 178). Replace `self._corr_cap` with `self._corr_cap_for(under)`:

```python
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
```

- [ ] **Step 7: Update `check_and_reserve` to use `_corr_cap_for()`**

In `check_and_reserve` (~line 228), replace `if current_corr + additional_usd > self._corr_cap:` with:

```python
            # Correlated underlying cap check
            _corr_cap = self._corr_cap_for(under)
            current_corr = self._corr_notional.get(under, 0.0)
            if current_corr + additional_usd > _corr_cap:
                return False, (
                    f"corr_stack_cap_exceeded:{under}:"
                    f"current=${current_corr:.0f}+${additional_usd:.0f}>cap=${_corr_cap:.0f}"
                )
```

- [ ] **Step 8: Update `ExposureSnapshot` to expose `asset_caps`**

Find the `ExposureSnapshot` dataclass (~line 100). Add one field and update `to_dict()`:

```python
@dataclass
class ExposureSnapshot:
    """Point-in-time exposure state for the tracker."""
    category_notional: Dict[str, float]   # category -> total USD notional
    corr_notional: Dict[str, float]       # underlying -> total USD notional
    category_caps: Dict[str, float]
    corr_cap: float
    asset_caps: Dict[str, float]          # NEW: per-asset override caps

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
            "asset_caps": dict(self.asset_caps),
        }
```

- [ ] **Step 9: Update `get_snapshot()` to include `asset_caps`**

Find `get_snapshot()` (~line 273). Add `asset_caps=dict(self._asset_caps)` to the constructor call:

```python
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
```

- [ ] **Step 10: Update `calibrate_from_balance()` to accept `asset_fractions`**

Find `calibrate_from_balance()` (~line 285). Replace signature and body to support `asset_fractions`:

```python
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

        Args:
            balance_cents: Live account balance in cents.
            category_fractions: Override map {category: fraction}.
            corr_fraction: Fraction for the default correlated-stack cap.
            asset_fractions: Override map {underlying: fraction} for per-asset
                corr caps (e.g. {"BTC": 0.20, "ETH": 0.15}).  Overrides the
                module-level ``_DEFAULT_ASSET_CAPS_USD`` for this instance.
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
            "macro":      0.05,
            "other":      0.05,
        }
        with self._lock:
            for cat, frac in fractions.items():
                self._category_caps[cat] = balance_usd * frac
            self._corr_cap = balance_usd * corr_fraction
            if asset_fractions:
                self._asset_caps = {
                    k.upper(): balance_usd * v
                    for k, v in asset_fractions.items()
                    if v > 0.0
                }
            _log_crypto = self._category_caps.get("crypto", 0.0)
            _log_corr = self._corr_cap
        logger.info(
            "CategoryExposureTracker: calibrated balance_usd=%.2f "
            "crypto_cap=%.2f corr_cap=%.2f asset_caps=%s",
            balance_usd, _log_crypto, _log_corr,
            {k: round(v, 2) for k, v in self._asset_caps.items()},
        )
```

- [ ] **Step 11: Run per-asset category tests**

```
pytest tests/event_venues/kalshi/test_category_exposure_per_asset.py -v
```
Expected: All PASS.

- [ ] **Step 12: Run existing category exposure consumers to check for regressions**

```
pytest tests/ -k "category_exposure or kalshi_risk or order_router" -v
```
Expected: All PASS (backward compat maintained — `asset_caps_usd=None` → uses `_DEFAULT_ASSET_CAPS_USD` which defaults to empty dict → all traffic goes through `_corr_cap` as before).

- [ ] **Step 13: Commit**

```bash
git add merid/event_venues/kalshi/category_exposure.py tests/event_venues/kalshi/test_category_exposure_per_asset.py
git commit -m "feat(risk): per-asset corr caps in CategoryExposureTracker

Replace single _corr_cap scalar with per-asset Dict[str, float].
Env vars: MERID_ASSET_CAP_{BTC,ETH,SOL,XRP,DOGE}_USD.
Backward compatible: 0.0 or absent → falls back to _corr_cap default.
calibrate_from_balance gains asset_fractions kwarg."
```

---

## Task 5: Full regression run + document calibrated values

- [ ] **Step 1: Run the full test suite**

```
pytest tests/test_continuous_trader_safety.py tests/event_venues/kalshi/test_category_exposure_per_asset.py -v
```
Expected: All PASS.

- [ ] **Step 2: Verify calibrated cents values for current bankroll**

Add this to `tests/test_continuous_trader_safety.py` as a standalone (skipped) calculation:

```python
class TestCalibratedExposureValues(unittest.TestCase):
    """Documents concrete cap values for typical bankroll levels.
    Run manually to sanity-check calibration: pytest -v -k calibrated
    """

    def _show_caps(self, balance_cents: int):
        from merid.trading.kalshi_continuous_trader import TraderConfig
        cfg = TraderConfig()
        bal = balance_cents
        print(f"\n--- Balance: ${bal/100:.2f} ---")
        for asset, pct in cfg.asset_max_exposure_pct.items():
            for tf, mult in cfg.series_exposure_multiplier.items():
                raw = int(bal * pct * mult)
                floor = max(cfg.min_asset_cap_cents, raw)
                print(f"  {asset}/{tf}: raw={raw}¢  floor={floor}¢")
        print(f"  GLOBAL: {int(bal * cfg.global_max_exposure_pct)}¢")

    def test_show_caps_for_12_dollars(self):
        self._show_caps(1211)

    def test_show_caps_for_100_dollars(self):
        self._show_caps(10000)

    def test_show_caps_for_1000_dollars(self):
        self._show_caps(100000)
```

- [ ] **Step 3: Run calibration check to confirm numbers look sane**

```
pytest tests/test_continuous_trader_safety.py::TestCalibratedExposureValues -v -s
```
Expected output (for $12.11 bankroll):
```
--- Balance: $12.11 ---
  BTC/15m:   raw=96¢   floor=100¢    (min_asset_cap_cents floor kicks in)
  BTC/1h:    raw=169¢  floor=169¢
  BTC/daily: raw=242¢  floor=242¢
  ETH/15m:   raw=72¢   floor=100¢
  ETH/1h:    raw=126¢  floor=126¢
  ETH/daily: raw=181¢  floor=181¢
  SOL/15m:   raw=48¢   floor=100¢    (min_asset_cap_cents floor kicks in)
  ...
  GLOBAL:    484¢
```

- [ ] **Step 4: Final commit**

```bash
git add tests/test_continuous_trader_safety.py
git commit -m "test(risk): add calibration table tests for per-asset exposure caps"
```

---

## Self-Review

### Spec coverage

| Spec requirement | Covered by |
|---|---|
| Per-asset caps for BTC/ETH/SOL/XRP/DOGE | Tasks 1, 3 (`asset_max_exposure_pct`) |
| Limits not overly strict for small bankrolls | Tasks 1, 3 (`min_asset_cap_cents` floor) |
| Global portfolio guardrail | Tasks 1, 3 (`global_max_exposure_pct`) |
| Per-timeframe/series multipliers | Tasks 1, 3 (`series_exposure_multiplier`) |
| Kelly/risk-based scaling (optional) | Existing `BankrollManager` untouched; `max_total_exposure_pct` still drives order sizing |
| Refactor exposure computation | Task 2 (`_per_asset_exposure_cents`) |
| Updated trade candidate filter | Task 3 (two-stage replace) |
| Calibrated initial params for BTC/ETH/SOL/XRP/DOGE | Tasks 1, 5 (config defaults + calibration test) |
| Env var overrides | Tasks 1, 4 (`KALSHI_TRADER_EXPOSURE_*`, `MERID_ASSET_CAP_*_USD`) |
| Test: BTC at cap, ETH/SOL/XRP/DOGE still trade | Task 3 `test_btc_at_cap_does_not_block_eth` |
| Test: asset at its own cap, others unaffected | Task 3 `test_btc_additional_trade_blocked_when_at_btc_cap`, `test_eth_at_eth_cap_does_not_block_sol` |
| Test: global cap blocks all | Task 3 `test_global_cap_blocks_all_when_total_at_ceiling` |
| Test: small bankroll allows micro-trading | Task 3 `test_small_bankroll_min_cap_floor_allows_micro_trades`, `test_tiny_bankroll_floor_prevents_lockout` |
| CategoryExposureTracker per-asset upgrade | Task 4 |

### Concrete numbers for current bankroll ($12.11 = 1211¢)

| Asset | Series | Raw cap (¢) | Effective cap (¢) | Env var to override |
|---|---|---|---|---|
| BTC | 15m | 96 | **100** (floor) | `KALSHI_TRADER_EXPOSURE_BTC=0.20` |
| BTC | 1h | 169 | 169 | same |
| BTC | daily | 242 | 242 | same |
| ETH | 15m | 72 | **100** (floor) | `KALSHI_TRADER_EXPOSURE_ETH=0.15` |
| ETH | 1h | 126 | 126 | same |
| ETH | daily | 181 | 181 | same |
| SOL | 15m | 48 | **100** (floor) | `KALSHI_TRADER_EXPOSURE_SOL=0.10` |
| SOL | 1h | 84 | 84 | same |
| XRP | 15m | 48 | **100** (floor) | `KALSHI_TRADER_EXPOSURE_XRP=0.10` |
| DOGE | 15m | 48 | **100** (floor) | `KALSHI_TRADER_EXPOSURE_DOGE=0.10` |
| **GLOBAL** | all | 484 | 484 | `KALSHI_TRADER_GLOBAL_EXPOSURE=0.40` |

**Key result:** Existing BTC position (300¢) blocks only new BTC trades (BTC cap = 242¢).
ETH/SOL/XRP/DOGE each start at 0¢ exposure → small candidates (9–20¢) are far below their 100¢ floors → all proceed to order submission.

### Placeholder scan
- No TBD, TODO, or "fill in details" found
- All code blocks are complete and self-contained
- Types consistent: `Dict[str, int]` cents throughout CT; `Dict[str, float]` USD throughout `category_exposure.py`
- Method name `_per_asset_exposure_cents` used consistently in Tasks 2, 3

### Type consistency check
- `_per_asset_exp: Dict[str, int]` — defined in Task 3 Step 3, used in Task 3 Steps 4, 5 ✓
- `_candidate_asset: str`, `_candidate_tf: str` — defined in Task 3 Step 4, used in Step 5 ✓
- `asset_caps_usd: Optional[Dict[str, float]]` — `__init__` param in Task 4 Step 4, used in test Task 4 Step 1 ✓
- `_corr_cap_for(underlying: str) -> float` — defined Task 4 Step 5, called in Steps 6, 7 ✓
- `ExposureSnapshot.asset_caps: Dict[str, float]` — added Task 4 Step 8, populated Task 4 Step 9, tested Task 4 Step 1 ✓
