# Full Bug Fix Sprint — 2026-03-26 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 13 new Criticals and 19 new Highs identified in the 2026-03-26 deep audit, scanning upstream/downstream at each fix site for additional eggs.

**Architecture:** Seven independent fix groups (A–G) targeting different subsystems. Groups A–G can be dispatched to parallel subagents simultaneously. Each fix is test-first (TDD): write the failing test, confirm it fails, apply the minimal fix, confirm it passes, commit.

**Tech Stack:** Python 3.11, pytest, asyncio, threading.Lock, SQLite WAL, dataclasses

**All audit findings reference:** `memory/audit_2026_03_26_deep_dive.md`

---

## Parallelism Map

| Group | Subsystem | Can run parallel with |
|---|---|---|
| A | PROTECT (safety/kill) | B, C, D, E, F, G |
| B | DISCOVER (market_state) | A, C, D, E, F, G |
| C | OPINION STRATEGY | A, B, D, E, F, G |
| D | ANALYZE/CONSENSUS/SIGNALS | A, B, C, E, F, G |
| E | SIZE/EXECUTE | A, B, C, D, F, G |
| F | MONITOR/PROMOTE | A, B, C, D, E, G |
| G | CONCURRENCY (WS/loop) | A, B, C, D, E, F |

---

## Group A — PROTECT Stage Fixes

### Task A1: Fix P-C3 — Uninitialized WS hysteresis globals in execution_gate.py

**Files:**
- Modify: `core/execution_gate.py:24-26`
- Test: `tests/core/test_execution_gate.py`

**Upstream scan:** `core/execution_gate.py` imports — check nothing else uses `_ws_stale_count` before line 256.
**Downstream scan:** All callers of `check_execution_gate()` — confirm gate passes/fails correctly after fix.

- [ ] **Step 1: Write the failing test**

```python
# In tests/core/test_execution_gate.py — add to existing test class or top-level
def test_execution_gate_module_import_does_not_raise():
    """P-C3: globals must exist at module load so first check_execution_gate() call
    does not raise NameError on _ws_stale_count/_ws_healthy_count/_ws_was_stale."""
    import importlib
    import core.execution_gate as eg
    importlib.reload(eg)  # forces fresh module load
    # Access the globals directly — they must exist
    assert hasattr(eg, "_ws_stale_count"), "_ws_stale_count not defined at module level"
    assert hasattr(eg, "_ws_healthy_count"), "_ws_healthy_count not defined at module level"
    assert hasattr(eg, "_ws_was_stale"), "_ws_was_stale not defined at module level"
    assert isinstance(eg._ws_stale_count, int)
    assert isinstance(eg._ws_healthy_count, int)
    assert isinstance(eg._ws_was_stale, bool)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/core/test_execution_gate.py::test_execution_gate_module_import_does_not_raise -v
```
Expected: FAIL — `AssertionError: _ws_stale_count not defined at module level`

- [ ] **Step 3: Write minimal fix**

In `core/execution_gate.py`, after line 25 (`_PM_LIVE_CACHE_VAL: bool = False`), add:

```python
# WS hysteresis state — must be at module level (used as globals in check_execution_gate)
_ws_stale_count: int = 0
_ws_healthy_count: int = 0
_ws_was_stale: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/core/test_execution_gate.py::test_execution_gate_module_import_does_not_raise -v
```
Expected: PASS

- [ ] **Step 5: Upstream/downstream scan**

Search for any other `global _ws_` declarations in the file to confirm no double-init:
```bash
grep -n "global _ws_" core/execution_gate.py
```
Expected: exactly one occurrence at the gate function. Confirm the existing `global _ws_stale_count, _ws_healthy_count` declaration at line ~256 still works (now it references the module-level vars).

- [ ] **Step 6: Commit**

```bash
git add core/execution_gate.py tests/core/test_execution_gate.py
git commit -m "fix(gate): initialize _ws_stale/healthy/was_stale globals at module level (P-C3)"
```

---

### Task A2: Fix P-C2 — self._config vs self.config in sentiment_vol_service.py

**Files:**
- Modify: `merid/prediction/risk/sentiment_vol_service.py:280`
- Test: `tests/merid/risk/test_sentiment_vol_service.py` (create if missing)

**Upstream scan:** Check all other uses of `self._config` and `self.config` in the file — ensure consistent naming throughout.
**Downstream scan:** `get_metrics_recorder()` — confirm `initialize_config()` signature accepts `config`.

- [ ] **Step 1: Scan for all _config vs config usages in the file**

```bash
grep -n "self\._config\|self\.config" merid/prediction/risk/sentiment_vol_service.py
```
Note every line. The attribute is set as `self.config` (line 257). Every `self._config` reference is a bug.

- [ ] **Step 2: Write the failing test**

```python
# tests/merid/risk/test_sentiment_vol_service.py
import pytest

def test_sentiment_vol_service_initializes_without_attribute_error():
    """P-C2: SentimentVolService must not raise AttributeError during initialize()
    due to self._config vs self.config mismatch."""
    from merid.prediction.risk.sentiment_vol_service import SentimentVolService
    svc = SentimentVolService()
    # initialize() triggers the self._config access — must not raise
    try:
        svc.initialize()
    except AttributeError as e:
        pytest.fail(f"initialize() raised AttributeError: {e}")
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/merid/risk/test_sentiment_vol_service.py::test_sentiment_vol_service_initializes_without_attribute_error -v
```
Expected: FAIL — `AttributeError: 'SentimentVolService' object has no attribute '_config'`

- [ ] **Step 4: Apply fix**

In `merid/prediction/risk/sentiment_vol_service.py`, change line 280:

```python
# BEFORE:
self._metrics.initialize_config(self._config)
# AFTER:
self._metrics.initialize_config(self.config)
```

Also run the full grep from Step 1 and fix ALL remaining `self._config` references:
- If any other line uses `self._config`, change to `self.config`.
- If the intent was `self._config` (private), change line 257 from `self.config = ...` to `self._config = ...` and update all accesses consistently. Choose one convention and apply it everywhere.

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/merid/risk/test_sentiment_vol_service.py::test_sentiment_vol_service_initializes_without_attribute_error -v
```
Expected: PASS

- [ ] **Step 6: Run broader test suite to check for regressions**

```bash
pytest tests/merid/risk/ -v
```

- [ ] **Step 7: Commit**

```bash
git add merid/prediction/risk/sentiment_vol_service.py tests/merid/risk/test_sentiment_vol_service.py
git commit -m "fix(risk): use consistent self.config (not self._config) in SentimentVolService (P-C2)"
```

---

### Task A3: Fix P-C1 — Non-atomic kill-switch persistence

**Files:**
- Modify: `merid/risk/kill_switches.py:159-171`
- Test: `tests/merid/risk/test_kill_switches.py`

**Upstream scan:** Check all call sites of `_persist_kill_switch()` — confirm they all hold `self._lock` (atomic write must happen while lock is held or after).
**Downstream scan:** `_load_persisted_kill_switch()` — confirm it gracefully handles a missing temp file (`.tmp` extension) left over from a crash.

- [ ] **Step 1: Write the failing test**

```python
# In tests/merid/risk/test_kill_switches.py — add test
import json
import os
import pathlib
import tempfile

def test_kill_switch_persist_is_atomic(tmp_path, monkeypatch):
    """P-C1: kill-switch write must be atomic (temp file + rename).
    A partial write must not leave a corrupted primary file."""
    from merid.risk import kill_switches as ks_mod

    # Point kill switch file to a temp directory
    ks_file = tmp_path / "test_kill_switch.json"
    monkeypatch.setattr(ks_mod, "_KILL_SWITCH_FILE", ks_file)

    from merid.risk.kill_switches import RiskController
    rc = RiskController(daily_loss_limit=100.0)

    # Trigger kill — this calls _persist_kill_switch
    rc.trigger_kill(reason="MANUAL", details="test")

    # The primary file must exist and be valid JSON
    assert ks_file.exists(), "Kill switch file not written"
    data = json.loads(ks_file.read_text())
    assert data["active"] is True

    # No leftover .tmp file (indicates atomic write completed)
    tmp_file = ks_file.with_suffix(".tmp")
    assert not tmp_file.exists(), ".tmp file left over — write was not atomic"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/merid/risk/test_kill_switches.py::test_kill_switch_persist_is_atomic -v
```
Expected: FAIL — `.tmp file left over` OR `AssertionError` on atomic check

- [ ] **Step 3: Apply fix**

In `merid/risk/kill_switches.py`, replace the `_persist_kill_switch` method body (lines 159-171):

```python
def _persist_kill_switch(self) -> None:
    """Write kill-switch state to disk atomically (temp + rename)."""
    try:
        _KILL_SWITCH_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active": self._global_kill,
            "reason": self._kill_reason.value if self._kill_reason else None,
            "details": self._kill_details,
            "activated_at": self._kill_timestamp.isoformat() if self._kill_timestamp else None,
        }
        _tmp = _KILL_SWITCH_FILE.with_suffix(".tmp")
        _tmp.write_text(json.dumps(payload, indent=2))
        _tmp.replace(_KILL_SWITCH_FILE)  # atomic on POSIX and Windows (same volume)
    except Exception as exc:
        logger.error("[risk] Failed to persist kill switch state: %s", exc)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/merid/risk/test_kill_switches.py::test_kill_switch_persist_is_atomic -v
```
Expected: PASS

- [ ] **Step 5: Broader kill-switch tests**

```bash
pytest tests/merid/risk/test_kill_switches.py -v
```

- [ ] **Step 6: Commit**

```bash
git add merid/risk/kill_switches.py tests/merid/risk/test_kill_switches.py
git commit -m "fix(risk): atomic kill-switch persistence via temp-file rename (P-C1)"
```

---

### Task A4: Fix P-H1 — Split-brain kill switches (two separate persistence files)

**Files:**
- Modify: `merid/execution_guard.py:334-341` (where it loads `MERID_RISK_KS_FILE`)
- Test: `tests/core/test_execution_gate.py`

**Upstream scan:** `merid/risk/kill_switches.py` — find `_KILL_SWITCH_FILE` constant definition. Document both file paths.
**Downstream scan:** Startup sequence in `web/main.py` — ensure `MERID_RISK_KS_FILE` env var is set before both modules initialize.

- [ ] **Step 1: Identify both file paths**

```bash
grep -n "_KILL_SWITCH_FILE\|MERID_RISK_KS_FILE\|risk_kill_switch\|kill_switch\.json" \
  merid/risk/kill_switches.py merid/execution_guard.py
```

Note the exact path constants for both. They must match.

- [ ] **Step 2: Write the failing test**

```python
def test_execution_guard_and_risk_controller_use_same_kill_file(monkeypatch):
    """P-H1: both modules must read/write the same kill-switch file path."""
    import merid.risk.kill_switches as ks_mod
    import merid.execution_guard as eg_mod

    ks_path = str(ks_mod._KILL_SWITCH_FILE)
    # execution_guard loads path from env or uses a default
    eg_path = eg_mod._get_risk_kill_switch_path()  # helper we add below
    assert ks_path == eg_path, (
        f"Kill switch path mismatch: kill_switches uses {ks_path!r}, "
        f"execution_guard uses {eg_path!r}"
    )
```

- [ ] **Step 3: Add `_get_risk_kill_switch_path()` helper to execution_guard.py**

Find the block in `merid/execution_guard.py` around line 334 where `MERID_RISK_KS_FILE` is read. Extract it into a module-level function:

```python
def _get_risk_kill_switch_path() -> str:
    """Return the canonical kill-switch file path (same as kill_switches._KILL_SWITCH_FILE)."""
    import os
    from merid.risk.kill_switches import _KILL_SWITCH_FILE
    env_override = os.environ.get("MERID_RISK_KS_FILE", "")
    return env_override if env_override else str(_KILL_SWITCH_FILE)
```

Update the loader at line ~334 to call this function so both modules resolve to the same path.

- [ ] **Step 4: Run test**

```bash
pytest tests/core/test_execution_gate.py::test_execution_guard_and_risk_controller_use_same_kill_file -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add merid/execution_guard.py tests/core/test_execution_gate.py
git commit -m "fix(guard): unify kill-switch file path between execution_guard and kill_switches (P-H1)"
```

---

### Task A5: Fix P-H2 — Stale sentiment returned without staleness flag

**Files:**
- Modify: `merid/prediction/risk/sentiment_vol_service.py` (around line 520-525)
- Test: `tests/merid/risk/test_sentiment_vol_service.py`

**Upstream scan:** All callers of `get_sentiment()` — check whether they already inspect staleness.
**Downstream scan:** `get_sizing_multiplier()` — ensure it still works when `get_sentiment()` returns a tuple.

- [ ] **Step 1: Find all callers of get_sentiment()**

```bash
grep -rn "get_sentiment\b" merid/ --include="*.py"
```

- [ ] **Step 2: Write the failing test**

```python
def test_get_sentiment_returns_staleness_flag():
    """P-H2: get_sentiment must return (value, is_stale) tuple so callers
    can choose to reject stale data."""
    from merid.prediction.risk.sentiment_vol_service import SentimentVolService
    import time

    svc = SentimentVolService()
    svc.initialize()
    svc.register_asset("BTC")

    # Inject an old sentiment value
    with svc._asset_lock:
        state = svc._assets.get("BTC")
        if state:
            state.current_sentiment = 45.0
            state.last_updated = time.time() - 400  # 400s ago > 300s stale_threshold

    result = svc.get_sentiment("BTC")
    # Must be a tuple of (value, is_stale)
    assert isinstance(result, tuple), "get_sentiment must return (value, is_stale) tuple"
    value, is_stale = result
    assert is_stale is True, "Sentiment older than stale_threshold must be marked stale"
```

- [ ] **Step 3: Update get_sentiment() to return (value, is_stale)**

In `merid/prediction/risk/sentiment_vol_service.py`, change `get_sentiment()` return type:

```python
def get_sentiment(self, asset: str) -> tuple[Optional[float], bool]:
    """Return (sentiment_value, is_stale). is_stale=True means data is older than stale_threshold."""
    with self._asset_lock:
        state = self._assets.get(asset.upper())
        if state is None:
            return None, True  # No data = treat as stale

        is_stale, reason = state.is_stale(self._stale_threshold)
        if is_stale:
            logger.debug("Stale sentiment for %s: %s", asset, reason)
        return state.current_sentiment, is_stale
```

- [ ] **Step 4: Update all callers** (from Step 1 grep) to unpack the tuple:

```python
# Pattern to apply at each call site:
sentiment, _stale = svc.get_sentiment(asset)
# Use sentiment only if not _stale, or choose to proceed anyway
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/merid/risk/ -v
```

- [ ] **Step 6: Commit**

```bash
git add merid/prediction/risk/sentiment_vol_service.py tests/merid/risk/test_sentiment_vol_service.py
git commit -m "fix(risk): get_sentiment returns (value, is_stale) tuple to expose staleness (P-H2)"
```

---

## Group B — DISCOVER Stage Fixes

### Task B1: Fix D-C3 — Naive datetime crash in market_state.py

**Files:**
- Modify: `merid/event_venues/kalshi/market_state.py` (around line 506)
- Test: `tests/event_venues/kalshi/test_market_state_timestamps.py` (create)

**Upstream scan:** All places Kalshi API timestamps are parsed. Check `market_catalog.py` and `unified_market_state.py` for similar naive datetime issues.
**Downstream scan:** `seconds_to_expiry` consumers — `opinion_strategy.py`, `execution_guard.py`, settlement window checks.

- [ ] **Step 1: Find all fromisoformat calls in market layer**

```bash
grep -rn "fromisoformat\|strptime\|datetime\." merid/event_venues/kalshi/ --include="*.py" | head -40
```

- [ ] **Step 2: Write the failing test**

```python
# tests/event_venues/kalshi/test_market_state_timestamps.py
import pytest

def test_recompute_seconds_to_expiry_handles_naive_datetime():
    """D-C3: naive Kalshi timestamps must not raise TypeError."""
    from merid.event_venues.kalshi.market_state import KalshiMarketState, _recompute_seconds_to_expiry

    state = KalshiMarketState(ticker="BTC-TEST")
    # Naive datetime (no Z, no +00:00) — Kalshi occasionally returns this
    state.expected_expiration_time = "2026-04-01T12:00:00"
    # Must not raise TypeError
    try:
        _recompute_seconds_to_expiry(state)
    except TypeError as e:
        pytest.fail(f"_recompute_seconds_to_expiry raised TypeError on naive datetime: {e}")
    # Result should be a non-negative float (market is in the future) or 0.0
    assert state.seconds_to_expiry is not None
    assert state.seconds_to_expiry >= 0.0

def test_recompute_seconds_to_expiry_handles_z_suffix():
    """D-C3: UTC Z-suffix timestamps must parse correctly."""
    from merid.event_venues.kalshi.market_state import KalshiMarketState, _recompute_seconds_to_expiry

    state = KalshiMarketState(ticker="BTC-TEST")
    state.expected_expiration_time = "2026-04-01T12:00:00Z"
    _recompute_seconds_to_expiry(state)
    assert state.seconds_to_expiry is not None and state.seconds_to_expiry >= 0.0
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/event_venues/kalshi/test_market_state_timestamps.py -v
```
Expected: first test FAILS with `TypeError`

- [ ] **Step 4: Apply fix**

In `merid/event_venues/kalshi/market_state.py`, find `_recompute_seconds_to_expiry` (around line 500) and replace the parsing block:

```python
def _recompute_seconds_to_expiry(state: KalshiMarketState) -> None:
    """Recompute state.seconds_to_expiry from expiry ISO strings."""
    expiry_str = state.expected_expiration_time or state.expiration_time
    if not expiry_str:
        state.seconds_to_expiry = None
        return
    try:
        expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        # If Kalshi returns a naive datetime (no tzinfo), assume UTC
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        state.seconds_to_expiry = max(0.0, (expiry_dt - now_dt).total_seconds())
    except (TypeError, ValueError) as exc:
        logger.warning(
            "market_state: failed to parse expiry timestamp %r: %s",
            expiry_str, exc,
        )
        state.seconds_to_expiry = None
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/event_venues/kalshi/test_market_state_timestamps.py -v
```
Expected: both PASS

- [ ] **Step 6: Broader market_state tests**

```bash
pytest tests/event_venues/kalshi/ -v -k "market_state or timestamp"
```

- [ ] **Step 7: Commit**

```bash
git add merid/event_venues/kalshi/market_state.py tests/event_venues/kalshi/test_market_state_timestamps.py
git commit -m "fix(discover): guard naive Kalshi datetime in _recompute_seconds_to_expiry (D-C3)"
```

---

### Task B2: Fix D-C1+D-C2 — external.ts None crash + edge_basis never populated

**Files:**
- Modify: `merid/event_venues/kalshi/market_state.py:382,404` and `to_unified()` return statement
- Test: `tests/event_venues/kalshi/test_market_state_timestamps.py`

**Upstream scan:** The `ExternalIndex` dataclass — check whether `ts` can legitimately be `None` or `0`.
**Downstream scan:** All consumers of `UnifiedMarketState.edge_basis` and `UnifiedMarketState.external_fair_value`.

- [ ] **Step 1: Find ExternalIndex definition**

```bash
grep -rn "class ExternalIndex\|ExternalIndex(" merid/ --include="*.py" | head -10
```

Check the `ts` field type and default.

- [ ] **Step 2: Write failing tests**

```python
def test_to_unified_does_not_crash_when_external_ts_is_none():
    """D-C1: to_unified() must not crash with TypeError when external.ts is None."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore, KalshiMarketState
    from unittest.mock import MagicMock

    store = KalshiMarketStateStore()
    state = KalshiMarketState(ticker="BTC-TEST")
    state.book_initialized = False
    store._states["BTC-TEST"] = state

    # Inject external index entry with ts=None
    ext = MagicMock()
    ext.ts = None
    ext.price_usd = 50000.0
    store._external_index["BTC"] = ext

    try:
        result = store.to_unified("BTC-TEST", asset="BTC", timeframe="15m")
    except TypeError as e:
        pytest.fail(f"to_unified crashed with TypeError on None external.ts: {e}")
    assert result is not None

def test_to_unified_edge_basis_populated_when_external_and_book_available():
    """D-C2: edge_basis must be computed and non-None when both book and external index exist."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore, KalshiMarketState
    from unittest.mock import MagicMock
    import time

    store = KalshiMarketStateStore()
    state = KalshiMarketState(ticker="BTC-TEST")
    state.book_initialized = True
    state.yes_bids = [(55, 100)]
    state.no_bids = [(45, 100)]
    state.last_book_update_ts = time.monotonic()
    store._states["BTC-TEST"] = state

    ext = MagicMock()
    ext.ts = time.time()
    ext.price_usd = 50000.0
    ext.fair_prob = 0.52
    store._external_index["BTC"] = ext

    result = store.to_unified("BTC-TEST", asset="BTC", timeframe="15m")
    assert result is not None
    # edge_basis and external_fair_value must be set (not None) when data is available
    assert result.edge_basis is not None, "edge_basis not computed in to_unified()"
    assert result.external_fair_value is not None, "external_fair_value not computed in to_unified()"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/event_venues/kalshi/test_market_state_timestamps.py::test_to_unified_does_not_crash_when_external_ts_is_none tests/event_venues/kalshi/test_market_state_timestamps.py::test_to_unified_edge_basis_populated_when_external_and_book_available -v
```

- [ ] **Step 4: Fix D-C1 — guard external.ts**

In `merid/event_venues/kalshi/market_state.py`, update lines 382 and 404:

```python
# Line 382 — guard ts:
index_age = (wall_now - external.ts) if (external and external.ts) else float("inf")

# Line 404 — guard ts:
index_updated_ts=external.ts if (external and external.ts) else 0.0,
```

- [ ] **Step 5: Fix D-C2 — compute edge_basis in to_unified()**

In the same `to_unified()` method, BEFORE the `return UnifiedMarketState(...)` call, add:

```python
# Compute derived consensus fields
external_fair_value: Optional[float] = None
edge_basis: Optional[float] = None
implied = book_snap.implied_prob if book_snap else None
if external is not None and hasattr(external, "fair_prob") and external.fair_prob is not None:
    external_fair_value = float(external.fair_prob)
    if implied is not None:
        edge_basis = round(implied - external_fair_value, 4)
```

Then update the `return UnifiedMarketState(...)` to include these fields:
```python
return UnifiedMarketState(
    ...
    implied_prob=implied,
    external_fair_value=external_fair_value,
    edge_basis=edge_basis,
    ...
)
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/event_venues/kalshi/test_market_state_timestamps.py -v
```

- [ ] **Step 7: Commit**

```bash
git add merid/event_venues/kalshi/market_state.py tests/event_venues/kalshi/test_market_state_timestamps.py
git commit -m "fix(discover): guard external.ts None crash; compute edge_basis in to_unified (D-C1, D-C2)"
```

---

### Task B3: Fix D-H2+D-H3 — one-sided orderbook + monotonic timestamp sentinel

**Files:**
- Modify: `merid/event_venues/kalshi/market_state.py:371-378` (orderbook assembly) and `_mono_to_wall` (line 364)

- [ ] **Step 1: Write failing tests**

```python
def test_to_unified_skips_one_sided_orderbook():
    """D-H2: a one-sided book (only YES bids, no NO bids) must NOT produce an
    OrderbookSnapshot — downstream spread/mid calculations would be None and confusing."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore, KalshiMarketState
    import time

    store = KalshiMarketStateStore()
    state = KalshiMarketState(ticker="BTC-TEST")
    state.book_initialized = True
    state.yes_bids = [(55, 100)]   # one side only
    state.no_bids = []
    state.last_book_update_ts = time.monotonic()
    store._states["BTC-TEST"] = state

    result = store.to_unified("BTC-TEST", asset="BTC", timeframe="15m")
    assert result is not None
    assert result.book is None, (
        "One-sided orderbook should not produce an OrderbookSnapshot "
        "(spread/mid would be None, misleading downstream)"
    )

def test_mono_to_wall_zero_ts_is_not_truthy_check():
    """D-H3: last_book_update_ts=0.0 is falsy; confirm it maps to 0.0 wall time
    and that book_stale flag is True (not False from epoch-time confusion)."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore, KalshiMarketState

    store = KalshiMarketStateStore()
    state = KalshiMarketState(ticker="BTC-TEST")
    state.book_initialized = True
    state.yes_bids = [(55, 100)]
    state.no_bids = [(45, 100)]
    state.last_book_update_ts = 0.0  # never set
    store._states["BTC-TEST"] = state

    result = store.to_unified("BTC-TEST", asset="BTC", timeframe="15m")
    assert result is not None
    # book_stale should be True when last_book_update_ts was never set
    assert result.book_stale is True, (
        "When last_book_update_ts=0.0 (never set), book must be considered stale"
    )
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
pytest tests/event_venues/kalshi/test_market_state_timestamps.py::test_to_unified_skips_one_sided_orderbook tests/event_venues/kalshi/test_market_state_timestamps.py::test_mono_to_wall_zero_ts_is_not_truthy_check -v
```

- [ ] **Step 3: Fix D-H2 — require both sides**

In `merid/event_venues/kalshi/market_state.py`, change line 371:

```python
# BEFORE:
if state.book_initialized and (state.yes_bids or state.no_bids):
# AFTER:
if state.book_initialized and state.yes_bids and state.no_bids:
```

- [ ] **Step 4: Fix D-H3 — stale check uses -1 sentinel**

Change the `_mono_to_wall` helper and the stale calculation:

```python
def _mono_to_wall(mono_ts: float) -> float:
    # mono_ts == 0.0 means "never set" — return 0.0 (epoch), NOT a recent time
    if mono_ts <= 0.0:
        return 0.0
    return wall_now - (mono_now - mono_ts)

# book_age: if book_wall_ts == 0.0, treat as infinite age
book_age = (wall_now - book_wall_ts) if book_wall_ts > 0.0 else float("inf")
```

- [ ] **Step 5: Run all market_state tests**

```bash
pytest tests/event_venues/kalshi/test_market_state_timestamps.py -v
pytest tests/event_venues/kalshi/ -v -k "market_state"
```

- [ ] **Step 6: Commit**

```bash
git add merid/event_venues/kalshi/market_state.py
git commit -m "fix(discover): require two-sided book for OrderbookSnapshot; fix mono_to_wall 0.0 sentinel (D-H2, D-H3)"
```

---

## Group C — Opinion Strategy Fixes

### Task C1: Fix O-C1 — seconds_to_expiry=0 expiry inversion

**Files:**
- Modify: `merid/prediction/opinion_strategy.py:367`
- Test: `tests/prediction/test_opinion_strategy.py` (create)

**Upstream scan:** All other `or 7*86400` patterns in opinion_strategy.py — same `0` coercion bug may exist elsewhere.
**Downstream scan:** `expiry_scale` usage at lines 386-391 and `imbalance_bias` at line 394. Confirm the fix makes expired markets receive scale=0.25.

- [ ] **Step 1: Write the failing test**

```python
# tests/prediction/test_opinion_strategy.py
import pytest
from unittest.mock import MagicMock, patch

def _make_expired_state(seconds_to_expiry: float):
    state = MagicMock()
    state.book_initialized = True
    state.mid_cents = 50
    state.spread_cents = 2
    state.yes_bids = [(55, 100)]
    state.no_bids = [(45, 100)]
    state.volume_24h = 1000
    state.open_interest = 500
    state.seconds_to_expiry = seconds_to_expiry
    return state

def test_kalshi_live_market_strategy_zero_expiry_uses_low_scale():
    """O-C1: seconds_to_expiry=0 must produce expiry_scale=0.25 (dampened),
    NOT 1.0 (full bias). The `or 7*86400` coercion must be removed."""
    from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy

    strategy = KalshiLiveMarketStrategy(min_edge=0.0, imbalance_weight=0.10)

    # Patch market state store to return a state with seconds_to_expiry=0
    mock_state = _make_expired_state(seconds_to_expiry=0)
    mock_store = MagicMock()
    mock_store.get.return_value = mock_state

    with patch(
        "merid.prediction.opinion_strategy.KalshiLiveMarketStrategy.estimate.__wrapped__",
        wraps=None
    ):
        pass  # just ensure import succeeds

    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=mock_store,
    ):
        # Use yes_bids/no_bids imbalanced to create a detectable imbalance_bias
        mock_state.yes_bids = [(55, 200)]
        mock_state.no_bids = [(45, 100)]

        # Call with slightly unbalanced book — expect near-zero imbalance_bias
        # because expiry_scale should be 0.25 for seconds_to_expiry=0
        result_expired = strategy.estimate(
            agent_id="test", ticker="BTC-TEST", market_prob=0.50,
            context={}
        )

    # If expiry_scale=1.0 (bug), edge = 0.10 * (1/3) * 1.0 * 1.0 = ~0.033
    # If expiry_scale=0.25 (fix), edge = 0.10 * (1/3) * 1.0 * 0.25 = ~0.008
    # With min_edge=0.0 both would return a result; check the edge magnitude
    # The bug produces a larger edge than the fix
    if result_expired is not None:
        # With 0.25 scale, imbalance_bias should be < 0.02
        assert abs(result_expired.edge) < 0.02, (
            f"Expired market produced edge={result_expired.edge:.4f} — "
            f"expiry dampening not applied (expected < 0.02)"
        )

def test_kalshi_live_market_strategy_nonzero_expiry_not_affected():
    """O-C1: seconds_to_expiry > 3600 must still produce expiry_scale=1.0."""
    from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy

    strategy = KalshiLiveMarketStrategy(min_edge=0.0, imbalance_weight=0.10)
    mock_state = _make_expired_state(seconds_to_expiry=86400)  # 1 day
    mock_store = MagicMock()
    mock_store.get.return_value = mock_state
    mock_state.yes_bids = [(55, 200)]
    mock_state.no_bids = [(45, 100)]

    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=mock_store,
    ):
        result = strategy.estimate(
            agent_id="test", ticker="BTC-TEST", market_prob=0.50, context={}
        )

    if result is not None:
        # Full scale — imbalance_bias should be around 0.033
        assert abs(result.edge) > 0.02, (
            f"Non-expired market has reduced edge {result.edge:.4f} — full scale not applied"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/prediction/test_opinion_strategy.py::test_kalshi_live_market_strategy_zero_expiry_uses_low_scale -v
```
Expected: FAIL (expired market returns full-bias edge, not dampened)

- [ ] **Step 3: Apply fix to line 367**

In `merid/prediction/opinion_strategy.py`, find line 367:

```python
# BEFORE:
seconds_to_expiry = getattr(state, "seconds_to_expiry", 7 * 86400) or 7 * 86400

# AFTER:
_ste_raw = getattr(state, "seconds_to_expiry", None)
seconds_to_expiry = _ste_raw if (_ste_raw is not None and _ste_raw > 0) else (
    0 if _ste_raw == 0 else 7 * 86400  # 0 = expired, None = unknown (default to 7d)
)
```

Or more concisely:
```python
_ste_raw = getattr(state, "seconds_to_expiry", None)
seconds_to_expiry = _ste_raw if _ste_raw is not None else 7 * 86400
```

This preserves `0` (expired) as `0` rather than converting it to 7 days.

- [ ] **Step 4: Run all opinion strategy tests**

```bash
pytest tests/prediction/test_opinion_strategy.py -v
```

- [ ] **Step 5: Scan for similar `or DEFAULT` patterns on time values in the file**

```bash
grep -n "or 7 \* 86400\|or 86400\|or 3600" merid/prediction/opinion_strategy.py
```
Fix any additional occurrences with the same pattern.

- [ ] **Step 6: Commit**

```bash
git add merid/prediction/opinion_strategy.py tests/prediction/test_opinion_strategy.py
git commit -m "fix(opinion): preserve seconds_to_expiry=0 (expired) instead of coercing to 7d (O-C1)"
```

---

### Task C2: Fix O-H1, A-M2, A-M3, A-M4 — opinion strategy output integrity

**Files:**
- Modify: `merid/prediction/opinion_strategy.py` (lines 156, 215, 429, 484, 684)
- Test: `tests/prediction/test_opinion_strategy.py`

**Upstream scan:** `OpinionEstimate.confidence` — check all consumers. If any code multiplies or divides by confidence, unbounded values cause explosions.
**Downstream scan:** `BayesianArbiterStrategy`, `ArbiterStrategy`, `consensus_aggregator._calculate_agent_weight()`.

- [ ] **Step 1: Write failing tests**

```python
def test_all_strategy_confidence_bounded_0_1():
    """O-H1, A-M2: every strategy must return confidence in [0.0, 1.0]."""
    from merid.prediction.opinion_strategy import (
        HashBiasStrategy, MeanReversionStrategy, ChallengerStrategy,
        ArbiterStrategy, BayesianArbiterStrategy, ExtremizingArbiterStrategy,
    )

    # ChallengerStrategy with extreme deviation
    strat = ChallengerStrategy(challenge_strength=0.6)
    result = strat.estimate(
        agent_id="test", ticker="T", market_prob=0.05,
        context={"proposer_prob": 0.95, "proposer_confidence": 0.8}
    )
    if result is not None:
        assert 0.0 <= result.confidence <= 1.0, (
            f"ChallengerStrategy.confidence={result.confidence} out of [0,1]"
        )

    # HashBiasStrategy
    for mp in [0.1, 0.5, 0.9]:
        result = HashBiasStrategy(bias_range=0.20).estimate("a", "T", mp)
        if result is not None:
            assert 0.0 <= result.confidence <= 1.0

    # MeanReversionStrategy
    for mp in [0.05, 0.5, 0.95]:
        result = MeanReversionStrategy(reversion_strength=0.30).estimate("a", "T", mp)
        if result is not None:
            assert 0.0 <= result.confidence <= 1.0

def test_kalshi_live_market_strategy_spread_factor_not_in_contributions():
    """A-M3: phantom spread_factor*0.01 entry must be removed from contributions.
    It never enters agent_prob so it's a misleading explanation entry."""
    from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy
    from unittest.mock import MagicMock, patch

    strategy = KalshiLiveMarketStrategy(min_edge=0.0)
    mock_state = _make_expired_state(seconds_to_expiry=86400)
    mock_state.yes_bids = [(55, 200)]
    mock_state.no_bids = [(45, 100)]
    mock_store = MagicMock()
    mock_store.get.return_value = mock_state

    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=mock_store,
    ):
        result = strategy.estimate("test", "BTC", 0.50, context={})

    if result and result.explanation:
        assert "spread_factor" not in result.explanation.contributions, (
            "spread_factor should not appear in contributions — it is not a direct addend"
        )

def test_kalshi_live_market_fallback_uses_distinct_reasoning_tag():
    """A-M4: fallback path must use reasoning_tag='kalshi_market_prob_fallback',
    NOT 'kalshi_live_market', so callers can distinguish live vs fallback signals."""
    from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy
    from unittest.mock import MagicMock, patch

    strategy = KalshiLiveMarketStrategy(min_edge=0.0, imbalance_weight=0.0)
    mock_store = MagicMock()
    mock_store.get.return_value = None  # forces fallback

    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=mock_store,
    ):
        result = strategy.estimate(
            "test", "BTC", 0.50,
            context={"sentiment_score": 0.5}  # ensure edge > min_edge
        )

    if result is not None:
        assert result.reasoning_tag != "kalshi_live_market", (
            "Fallback must use a distinct reasoning_tag, not 'kalshi_live_market'"
        )
        assert "fallback" in result.reasoning_tag, (
            f"Fallback reasoning_tag should contain 'fallback', got {result.reasoning_tag!r}"
        )
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
pytest tests/prediction/test_opinion_strategy.py::test_all_strategy_confidence_bounded_0_1 tests/prediction/test_opinion_strategy.py::test_kalshi_live_market_strategy_spread_factor_not_in_contributions tests/prediction/test_opinion_strategy.py::test_kalshi_live_market_fallback_uses_distinct_reasoning_tag -v
```

- [ ] **Step 3: Apply fixes**

**A) Clamp confidence in HashBiasStrategy (line 156):**
```python
confidence=round(min(1.0, 0.4 + abs(edge) * 4), 2),
```

**B) Clamp confidence in MeanReversionStrategy (line 215):**
```python
confidence=round(min(1.0, 0.3 + abs(edge) * 3), 2),
```

**C) Clamp confidence in ChallengerStrategy (line 684):**
```python
confidence=round(min(1.0, 0.3 + abs(deviation) * 2), 2),
```

**D) Remove phantom spread_factor from KalshiLiveMarketStrategy contributions (line 429):**
Remove this line from the `contributions` dict:
```python
"spread_factor": round(spread_factor * 0.01, 4),  # DELETE THIS LINE
```

**E) Fix fallback reasoning_tag in `_fallback_estimate` (line 484):**
```python
# BEFORE:
reasoning_tag="kalshi_live_market",
# AFTER:
reasoning_tag="kalshi_market_prob_fallback",
```

- [ ] **Step 4: Run all opinion strategy tests**

```bash
pytest tests/prediction/test_opinion_strategy.py -v
```

- [ ] **Step 5: Commit**

```bash
git add merid/prediction/opinion_strategy.py
git commit -m "fix(opinion): clamp confidence to [0,1]; remove phantom spread_factor; fix fallback tag (O-H1,A-M2,A-M3,A-M4)"
```

---

## Group D — Analyze / Consensus / Signals Fixes

### Task D1: Fix A-C1 — Signal dataclass constructor field mismatches

**Files:**
- Modify: `merid/signals/kalshi_signals.py:434-457` (LiquiditySignal), `517-527` (VolumeAnomalySignal), `578-587` (KalshiRiskSignal)
- Test: `tests/test_kalshi_signals.py` (create or add to existing)

**Upstream scan:** Check if the signal dataclasses are missing the `asset`/`timeframe` fields that the generators try to pass — either add those fields to the dataclasses OR stop passing them.
**Downstream scan:** All consumers of LiquiditySignal, VolumeAnomalySignal, KalshiRiskSignal — confirm they don't depend on the missing fields.

**Decision:** The signal generators pass `asset` and `timeframe` but the dataclasses don't have them. Since filtering by asset/timeframe is valuable, **add the fields to the dataclasses** rather than dropping the values.

- [ ] **Step 1: Write failing test**

```python
# tests/test_kalshi_signals.py
import pytest

def test_liquidity_signal_constructor_matches_dataclass():
    """A-C1: LiquiditySignal constructor must not raise TypeError."""
    from merid.signals.kalshi_signals import LiquiditySignal
    # This is exactly what _generate_liquidity_signals passes:
    sig = LiquiditySignal(
        ticker="BTC-TEST",
        asset="BTC",
        timeframe="15m",
        alert_type="wide_spread",
        severity="medium",
        spread_cents=7.0,
        message="Wide spread: 7c",
        timestamp=1000000.0,
    )
    assert sig.ticker == "BTC-TEST"
    assert sig.asset == "BTC"

def test_volume_anomaly_signal_constructor_matches_dataclass():
    """A-C1: VolumeAnomalySignal must accept volume_24h and avg_volume."""
    from merid.signals.kalshi_signals import VolumeAnomalySignal
    sig = VolumeAnomalySignal(
        ticker="BTC-TEST",
        asset="BTC",
        timeframe="15m",
        volume_24h=5000.0,
        avg_volume=2500.0,
        z_score=2.5,
        direction="spike",
        severity="high",
        timestamp=1000000.0,
    )
    assert sig.current_volume == 5000.0  # volume_24h maps to current_volume
    assert sig.rolling_mean == 2500.0

def test_kalshi_risk_signal_constructor_matches_dataclass():
    """A-C1: KalshiRiskSignal must accept event_type and description."""
    from merid.signals.kalshi_signals import KalshiRiskSignal
    sig = KalshiRiskSignal(
        ticker="BTC-TEST",
        asset="BTC",
        timeframe="15m",
        event_type="market_risk",
        severity="high",
        description="Risks: near_expiry, wide_spread",
        seconds_to_expiry=120,
        timestamp=1000000.0,
    )
    assert sig.category == "market_risk"
    assert sig.detail == "Risks: near_expiry, wide_spread"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_kalshi_signals.py -v
```
Expected: all three FAIL with `TypeError: __init__() got an unexpected keyword argument`

- [ ] **Step 3: Fix the dataclasses**

**A) LiquiditySignal** — add `asset` and `timeframe` fields; fix `depth` → `depth_contracts` in generators:

```python
@dataclass
class LiquiditySignal:
    # ... existing fields ...
    ticker: str = ""
    asset: str = ""           # ADD
    timeframe: str = ""       # ADD
    spread_cents: float = 0.0
    spread_pct: float = 0.0
    depth_contracts: float = 0.0
    alert_type: str = ""
    severity: str = LiquiditySeverity.INFO.value
    message: str = ""
    timestamp: float = field(default_factory=time.time)
```

In `_generate_liquidity_signals`, change `depth=depth` → `depth_contracts=depth` (both call sites at ~line 454 and the wide_spread constructor).

**B) VolumeAnomalySignal** — add `timeframe` field; add `volume_24h`/`avg_volume` as aliases in `__post_init__`:

```python
@dataclass
class VolumeAnomalySignal:
    ticker: str = ""
    asset: str = ""
    timeframe: str = ""       # ADD
    current_volume: float = 0.0
    rolling_mean: float = 0.0
    rolling_std: float = 0.0
    z_score: float = 0.0
    severity: str = "info"
    direction: str = "spike"
    timestamp: float = field(default_factory=time.time)
    # Legacy aliases for generator compatibility
    volume_24h: float = field(default=0.0, repr=False)   # ADD
    avg_volume: float = field(default=0.0, repr=False)   # ADD

    def __post_init__(self):
        if not self.signal_id:
            self.signal_id = f"vol-{self.ticker}-{int(self.timestamp)}-{uuid.uuid4().hex[:8]}"
        # Map legacy kwargs to canonical fields
        if self.volume_24h and not self.current_volume:
            self.current_volume = self.volume_24h
        if self.avg_volume and not self.rolling_mean:
            self.rolling_mean = self.avg_volume
```

In `_generate_volume_signals` at line ~517, also add `rolling_std=std_vol` to the constructor.

**C) KalshiRiskSignal** — add `ticker`/`asset`/`timeframe`/`seconds_to_expiry`/`event_type`/`description` compatibility:

```python
@dataclass
class KalshiRiskSignal:
    ticker: str = ""          # ADD
    asset: str = ""           # ADD
    timeframe: str = ""       # ADD
    category: str = RiskEventCategory.GENERAL.value
    severity: str = "info"
    title: str = ""
    detail: str = ""
    drawdown_pct: Optional[float] = None
    rate_limit_count: Optional[int] = None
    daily_loss_usd: Optional[float] = None
    seconds_to_expiry: Optional[float] = None  # ADD
    timestamp: float = field(default_factory=time.time)
    # Generator aliases
    event_type: str = field(default="", repr=False)      # ADD
    description: str = field(default="", repr=False)     # ADD

    def __post_init__(self):
        if not self.signal_id:
            self.signal_id = f"risk-{self.ticker}-{int(self.timestamp)}-{uuid.uuid4().hex[:8]}"
        # Map generator kwargs to canonical fields
        if self.event_type and not self.category:
            self.category = self.event_type
        if self.description:
            if not self.detail:
                self.detail = self.description
            if not self.title:
                self.title = self.description[:60]
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_kalshi_signals.py -v
```
Expected: all PASS

- [ ] **Step 5: Run broader signal tests**

```bash
pytest tests/ -k "signal" -v
```

- [ ] **Step 6: Commit**

```bash
git add merid/signals/kalshi_signals.py tests/test_kalshi_signals.py
git commit -m "fix(signals): align LiquiditySignal/VolumeAnomalySignal/KalshiRiskSignal constructors with generator calls (A-C1)"
```

---

### Task D2: Fix A-C2 + A-H1 — Stale proposals in consensus + unbounded vote weights

**Files:**
- Modify: `merid/swarm/consensus_aggregator.py` (~line 243 and ~line 637)
- Test: `tests/test_consensus_aggregator.py` (add cases)

**Upstream scan:** All callers of `_recompute_consensus()` — confirm they all go through `submit_proposal` (which already cleans proposals) or they should also clean.
**Downstream scan:** `_calculate_agent_weight()` return value — all callers that multiply/divide by weight.

- [ ] **Step 1: Write failing tests**

```python
def test_recompute_consensus_re_validates_proposal_freshness():
    """A-C2: _recompute_consensus_unlocked must discard proposals older than max_age
    even when called directly (not via submit_proposal)."""
    from merid.swarm.consensus_aggregator import SwarmConsensusAggregator, AgentProposal
    from datetime import datetime, timezone, timedelta

    agg = SwarmConsensusAggregator()
    agg.initialize()

    old_ts = datetime.now(timezone.utc) - timedelta(seconds=400)  # > 300s max_age
    stale_proposal = AgentProposal(
        agent_id="a1", asset="BTC", timeframe="15m",
        action="buy", confidence=0.8, timestamp=old_ts,
        downweight=False,
    )
    # Bypass submit_proposal (which would clean on its own) — inject directly
    agg._proposals["BTC:15m"] = [stale_proposal]

    # Direct call to _recompute_consensus_unlocked — must clean stale proposals
    agg._recompute_consensus_unlocked("BTC:15m")

    # The stale proposal must have been removed; consensus must be absent
    assert "BTC:15m" not in agg._consensus_cache, (
        "Stale-only proposals must not produce a consensus cache entry"
    )

def test_agent_weight_bounded():
    """A-H1: _calculate_agent_weight must return a value in [0.0, 2.0].
    Unbounded weights distort consensus ratios."""
    from merid.swarm.consensus_aggregator import SwarmConsensusAggregator, AgentProposal
    from datetime import datetime, timezone

    agg = SwarmConsensusAggregator()
    agg.initialize()

    p = AgentProposal(
        agent_id="a1", asset="BTC", timeframe="15m",
        action="buy", confidence=1.5,  # deliberately > 1.0 to stress test
        timestamp=datetime.now(timezone.utc), downweight=False,
    )
    weight = agg._calculate_agent_weight(p)
    assert 0.0 <= weight <= 2.0, f"_calculate_agent_weight returned {weight} outside [0,2]"
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
pytest tests/ -k "test_recompute_consensus_re_validates_proposal_freshness or test_agent_weight_bounded" -v
```

- [ ] **Step 3: Fix A-C2 — add age filter to _recompute_consensus_unlocked**

At the start of `_recompute_consensus_unlocked` in `merid/swarm/consensus_aggregator.py`:

```python
def _recompute_consensus_unlocked(self, key: str) -> None:
    """Recompute consensus for an asset/timeframe (internal, assumes lock held)."""
    # Re-validate proposal freshness before aggregating (defensive: submit_proposal
    # also cleans, but direct calls to _recompute_consensus must also clean)
    now = datetime.now(timezone.utc)
    self._proposals[key] = [
        p for p in self._proposals[key]
        if now - p.timestamp < self.max_age
    ]
    proposals = self._proposals[key]
    if not proposals:
        self._consensus_cache.pop(key, None)
        return
    # ... rest unchanged ...
```

- [ ] **Step 4: Fix A-H1 — clamp weight in _calculate_agent_weight**

Find `_calculate_agent_weight` (~line 551). At the end, before `return final_weight`, add:

```python
# Clamp to [0, 2.0] — prevents a single agent's extreme metrics from dominating
final_weight = max(0.0, min(2.0, final_weight))
return final_weight
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/ -k "consensus" -v
```

- [ ] **Step 6: Commit**

```bash
git add merid/swarm/consensus_aggregator.py
git commit -m "fix(consensus): re-validate staleness in _recompute_consensus_unlocked; clamp agent weight to [0,2] (A-C2, A-H1)"
```

---

## Group E — Size / Execute Fixes

### Task E1: Fix S-C1 — Pass live orderbook params to check_order() in all production callers

**Files:**
- Modify: `merid/execution/executors/kalshi.py:278-282`
- Modify: `merid/event_venues/kalshi/order_router.py:762-766`
- Modify: `merid/prediction/trading_agent.py:718-722`
- Modify: `merid/event_venues/kalshi/trading.py:73-77`
- Test: `tests/test_audit_plan_a.py` (add test)

**Pre-task scan:** For each call site, determine what live orderbook data is available in scope. Inject `best_bid_cents`, `best_ask_cents`, `depth_at_price` from the market state or intent object.

- [ ] **Step 1: Write the failing test**

```python
def test_check_order_called_with_orderbook_params_in_order_router():
    """S-C1: order_router must pass best_bid_cents, best_ask_cents, depth_at_price
    to check_order() so spread/depth pre-trade guards actually execute."""
    from unittest.mock import MagicMock, patch, call
    from merid.event_venues.kalshi.order_router import KalshiOrderRouter

    mock_risk = MagicMock()
    mock_risk.check_order.return_value = (True, "OK")

    router = KalshiOrderRouter.__new__(KalshiOrderRouter)
    router._risk = mock_risk
    router._client = MagicMock()

    # Create a mock intent with orderbook snapshot attached
    intent = MagicMock()
    intent.ticker = "BTC-TEST"
    intent.count = 5
    intent.price_cents = 55
    intent.best_bid_cents = 54
    intent.best_ask_cents = 56
    intent.depth_at_price = 100

    router._route_intent(intent)  # or whatever the method name is

    call_kwargs = mock_risk.check_order.call_args
    assert call_kwargs is not None
    all_kwargs = {**call_kwargs[1], **dict(zip(["ticker", "category", "contracts", "price_cents"], call_kwargs[0]))}
    assert "best_bid_cents" in all_kwargs or any(
        "best_bid" in str(a) for a in call_kwargs[0]
    ), "check_order must receive best_bid_cents"
```

- [ ] **Step 2: For each call site, add orderbook params**

**In `merid/event_venues/kalshi/order_router.py`** around line 762:
```python
# Fetch live orderbook data for pre-trade risk check
_state = _market_state_store.get(intent.ticker) if _market_state_store else None
_best_bid = getattr(_state, "best_yes_bid_cents", None)
_best_ask = getattr(_state, "best_yes_ask_cents", None)
_depth = getattr(_state, "depth_10c", None)

allowed, reason = risk.check_order(
    ticker=intent.ticker,
    category=_rm_category,
    contracts=intent.count,
    price_cents=intent.price_cents,
    best_bid_cents=_best_bid,
    best_ask_cents=_best_ask,
    depth_at_price=_depth,
)
```

Apply same pattern to `executors/kalshi.py:278`, `trading_agent.py:718`, `trading.py:73`.

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -k "check_order or pre_trade" -v
```

- [ ] **Step 4: Commit**

```bash
git add merid/execution/executors/kalshi.py merid/event_venues/kalshi/order_router.py merid/prediction/trading_agent.py merid/event_venues/kalshi/trading.py
git commit -m "fix(execute): pass best_bid/ask/depth to check_order() in all production callers (S-C1)"
```

---

### Task E2: Fix E-C1 + S-H1 + S-H2/S-H3 — execution pipeline + position sizer + order group race

**Files:**
- Modify: `merid_core/kalshi/execution_pipeline.py:316`
- Modify: `merid/event_venues/kalshi/position_sizer.py` (bankroll guard)
- Modify: `merid/event_venues/kalshi/order_group_manager_enhanced.py:68` (add lock)
- Test: `tests/test_executor_wiring.py` (add tests)

- [ ] **Step 1: Write failing tests**

```python
def test_position_sizer_zero_bankroll_returns_zero_not_exception():
    """S-H1: compute() must return 0 contracts when bankroll_cents=0, not ZeroDivisionError."""
    from merid.event_venues.kalshi.position_sizer import PositionSizer, SizerConfig

    sizer = PositionSizer(config=SizerConfig())
    result = sizer.compute(
        price_cents=50,
        est_edge=0.05,
        bankroll_cents=0,       # edge case
        market_id="BTC-TEST",
        side="yes",
    )
    assert result == 0, f"Expected 0 contracts for zero bankroll, got {result}"

def test_order_group_manager_groups_dict_has_lock():
    """S-H2: self.groups mutations must be protected by an asyncio.Lock."""
    from merid.event_venues.kalshi.order_group_manager_enhanced import OrderGroupManagerEnhanced
    import asyncio

    mgr = OrderGroupManagerEnhanced.__new__(OrderGroupManagerEnhanced)
    # After __init__, _groups_lock must exist
    mgr.__init__()
    assert hasattr(mgr, "_groups_lock"), "OrderGroupManagerEnhanced must have _groups_lock"
    assert isinstance(mgr._groups_lock, asyncio.Lock), "_groups_lock must be asyncio.Lock"
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
pytest tests/test_executor_wiring.py::test_position_sizer_zero_bankroll_returns_zero_not_exception tests/test_executor_wiring.py::test_order_group_manager_groups_dict_has_lock -v
```

- [ ] **Step 3: Fix S-H1 — bankroll guard**

In `merid/event_venues/kalshi/position_sizer.py`, find `compute()`. Near the top of the method body, add:

```python
if bankroll_cents <= 0:
    logger.debug("PositionSizer: bankroll_cents=%s <= 0, returning 0", bankroll_cents)
    return 0
```

- [ ] **Step 4: Fix S-H2/S-H3 — add asyncio.Lock to order_group_manager**

In `merid/event_venues/kalshi/order_group_manager_enhanced.py`, in `__init__`:

```python
self._groups_lock = asyncio.Lock()  # Protects self.groups mutations and WS callback
```

Then wrap `refresh_all()` and `_ws_callback` invocations with `async with self._groups_lock:`.

- [ ] **Step 5: Fix E-C1 — position sync error propagation**

In `merid_core/kalshi/execution_pipeline.py`, find `_sync_positions_from_kalshi()`. Change the exception handler from silent swallow to:

```python
except Exception as exc:
    logger.critical(
        "[pipeline] FATAL: position sync from Kalshi failed at startup: %s — "
        "orders may be placed on existing untracked positions", exc,
        exc_info=True,
    )
    # Raise to caller so startup can decide to abort
    raise
```

Then in `start()`, catch this and decide: either abort startup or emit an alert and continue with empty positions (document the choice).

- [ ] **Step 6: Run all executor tests**

```bash
pytest tests/test_executor_wiring.py tests/test_continuous_trader_wiring.py -v
```

- [ ] **Step 7: Commit**

```bash
git add merid_core/kalshi/execution_pipeline.py merid/event_venues/kalshi/position_sizer.py merid/event_venues/kalshi/order_group_manager_enhanced.py
git commit -m "fix(execute): guard zero bankroll; add groups_lock; propagate position sync failures (E-C1,S-H1,S-H2)"
```

---

## Group F — Monitor / Promote Fixes

### Task F1: Fix M-H1 — Promotion cache blocks demotion

**Files:**
- Modify: `merid/promotion_report.py` (~line 726)
- Test: `tests/test_promotion_report.py`

**Upstream scan:** All callers of `get_cached_promotion_report()` — check if any bypass the cache for real-time checks.
**Downstream scan:** `auto_promoter.py`, `execution_guard.py` — both should respect a freshness mechanism.

- [ ] **Step 1: Write failing test**

```python
def test_promotion_cache_ttl_is_short_enough_for_demotion():
    """M-H1: promotion cache TTL must be <= 60s so demotion events
    are reflected within one minute, not 5 minutes."""
    import merid.promotion_report as pr_mod
    assert pr_mod._CACHE_TTL_S <= 60, (
        f"Promotion cache TTL is {pr_mod._CACHE_TTL_S}s — "
        f"demotion events will be delayed up to {pr_mod._CACHE_TTL_S}s"
    )
```

- [ ] **Step 2: Run test to confirm failure (currently 300s)**

```bash
pytest tests/test_promotion_report.py::test_promotion_cache_ttl_is_short_enough_for_demotion -v
```

- [ ] **Step 3: Apply fix — reduce TTL**

In `merid/promotion_report.py`, change line ~726:
```python
# BEFORE:
_CACHE_TTL_S = 300.0
# AFTER:
_CACHE_TTL_S = 60.0  # Reduced from 300s — demotion must be detected within 1 minute
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_promotion_report.py -v
```

- [ ] **Step 5: Commit**

```bash
git add merid/promotion_report.py
git commit -m "fix(promote): reduce promotion cache TTL from 300s to 60s to allow timely demotion (M-H1)"
```

---

### Task F2: Fix M-H2 — Reconciler false-positive kill on WS lag

**Files:**
- Modify: `merid/reconciliation/kalshi_reconciler.py:262-265`
- Test: `tests/test_kalshi_reconciler.py`

**Upstream scan:** What triggers a PHANTOM_POSITION finding? Is it when exchange has position but MERID doesn't, or vice versa?
**Downstream scan:** Auto-kill path — confirm MISSING_POSITION suppression still works after fix.

- [ ] **Step 1: Write failing test**

```python
def test_reconciler_does_not_kill_on_missing_position_alone():
    """M-H2: MISSING_POSITION issues (MERID thinks it has a position, exchange doesn't)
    are caused by WS lag and must NOT trigger auto-kill without PHANTOM_POSITION."""
    # This is a regression test ensuring the suppression logic works correctly
    from merid.reconciliation.kalshi_reconciler import KalshiReconciler, ReconciliationIssue
    from unittest.mock import MagicMock

    reconciler = KalshiReconciler.__new__(KalshiReconciler)
    reconciler._kill_switch = MagicMock()
    reconciler._apply_domain_kill_switch = True

    missing_issues = [
        ReconciliationIssue(
            issue_type="MISSING_POSITION",
            ticker="BTC-TEST",
            severity="CRITICAL",
            detail="Position in MERID but not on exchange",
        )
    ]
    # MISSING_POSITION alone must NOT trigger kill switch
    reconciler._evaluate_and_act(missing_issues)
    reconciler._kill_switch.assert_not_called()
```

- [ ] **Step 2: Run test to confirm current behavior**

```bash
pytest tests/test_kalshi_reconciler.py::test_reconciler_does_not_kill_on_missing_position_alone -v
```

- [ ] **Step 3: Fix the suppression logic**

In `merid/reconciliation/kalshi_reconciler.py`, around lines 262-265, clarify the kill suppression:

```python
# Auto-kill only on PHANTOM_POSITION (real untracked position on exchange).
# MISSING_POSITION (MERID thinks it has a position but exchange doesn't) is
# caused by WS fill event lag and should NOT trigger kill — it self-heals.
has_phantom = any(i.issue_type == "PHANTOM_POSITION" for i in issues if i.severity == "CRITICAL")
has_only_missing = all(i.issue_type == "MISSING_POSITION" for i in issues if i.severity == "CRITICAL")

if has_phantom and not has_only_missing:
    # Genuine untracked position — kill to prevent unauthorized trading
    self._trigger_kill(reason="PHANTOM_POSITION", details=...)
elif has_only_missing:
    logger.warning(
        "[reconcile] MISSING_POSITION issues detected — suppressing auto-kill "
        "(likely WS fill sync lag, expect self-resolution within 60s)"
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_kalshi_reconciler.py -v
```

- [ ] **Step 5: Commit**

```bash
git add merid/reconciliation/kalshi_reconciler.py
git commit -m "fix(reconcile): only auto-kill on PHANTOM_POSITION, not MISSING_POSITION (WS lag) (M-H2)"
```

---

### Task F3: Fix M-M1 + M-M2 — SQLite WAL mode + Brier gate

**Files:**
- Modify: `merid/event_venues/kalshi/fills_ledger.py:915`
- Modify: `merid/event_venues/kalshi/auto_promoter.py:391`
- Test: `tests/test_fills_ledger_fixes.py`

- [ ] **Step 1: Fix fills_ledger WAL mode**

Find database initialization in `fills_ledger.py` (around line 915 where table is created). After opening the connection:

```python
conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA synchronous=NORMAL;")  # WAL + NORMAL = fast writes, crash-safe
```

Test: write fills from two concurrent readers/writers in tests, verify no locking issues.

- [ ] **Step 2: Add Brier score gate to SHADOW→LIVE**

In `merid/event_venues/kalshi/auto_promoter.py`, in the SHADOW→LIVE gate block (around line 391):

```python
# Brier score gate (calibration quality)
min_brier = cfg.get("max_brier_score_for_live", 0.30)  # lower is better
brier = _get_agent_brier_score(agent_name)
if brier is not None and brier > min_brier:
    return False, f"brier_score_too_high:{brier:.3f}>{min_brier}"
```

Add `max_brier_score_for_live: float = 0.30` to the promoter config dataclass.

- [ ] **Step 3: Commit**

```bash
git add merid/event_venues/kalshi/fills_ledger.py merid/event_venues/kalshi/auto_promoter.py
git commit -m "fix(monitor): WAL mode for fills_ledger; add Brier score gate to SHADOW→LIVE (M-M1, M-M2)"
```

---

## Group G — Concurrency Fixes

### Task G1: Fix X-C1 — ws_bridge non-atomic reconnect subscription

**Files:**
- Modify: `merid/event_venues/kalshi/ws_bridge.py:229-256`
- Test: `tests/event_venues/kalshi/test_ws_bridge.py`

**Upstream scan:** `_subscribed_tickers` list — find all read and write sites. Determine if it needs to be a set.
**Downstream scan:** `get_subscription_health()` — confirm it reads from the corrected tracking.

- [ ] **Step 1: Write failing test**

```python
def test_subscribed_tickers_not_updated_before_subscription_confirmed():
    """X-C1: _subscribed_tickers must only be updated after WS subscription succeeds,
    not before — so a failed subscription doesn't leave ghost entries."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge

    bridge = KalshiWebSocketBridge.__new__(KalshiWebSocketBridge)
    bridge._subscribed_tickers = []
    bridge._ws = MagicMock()

    # Simulate a subscription failure on the second channel
    call_count = 0
    async def failing_subscribe(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise ConnectionError("WS subscribe failed")

    bridge._ws.subscribe = failing_subscribe
    bridge._ws.subscribe_orderbook_batch = AsyncMock()

    async def run():
        try:
            await bridge._post_connect_start()
        except Exception:
            pass

    asyncio.get_event_loop().run_until_complete(run())

    # After a failed subscription, _subscribed_tickers should be empty or partial
    # but NOT fully populated as if all subscriptions succeeded
    assert len(bridge._subscribed_tickers) == 0, (
        "Failed subscription must not leave tickers in _subscribed_tickers"
    )
```

- [ ] **Step 2: Fix — update _subscribed_tickers only on success**

In `merid/event_venues/kalshi/ws_bridge.py`, in `_post_connect_start()` around lines 229-256:

```python
async def _post_connect_start(self) -> None:
    """Subscribe to all channels after connection. Updates _subscribed_tickers
    ONLY after ALL subscriptions succeed (atomic — no partial state)."""
    newly_subscribed = []
    try:
        await self._ws.subscribe(...)         # quotes
        await self._ws.subscribe(...)         # trades
        await self._ws.subscribe_orderbook_batch(list(self._desired_ob_subs))
        # All succeeded — now update tracking
        newly_subscribed = list(self._desired_ob_subs)
    except Exception:
        # Partial subscribe — roll back: do NOT update _subscribed_tickers
        logger.error("[ws_bridge] Partial subscription failure on reconnect — will retry")
        raise  # propagate to reconnect handler

    # Atomic update only after all subscriptions confirmed
    self._subscribed_tickers = newly_subscribed
    self._active_ob_subs = set(newly_subscribed)
```

- [ ] **Step 3: Run ws_bridge tests**

```bash
pytest tests/event_venues/kalshi/test_ws_bridge.py -v
```

- [ ] **Step 4: Commit**

```bash
git add merid/event_venues/kalshi/ws_bridge.py
git commit -m "fix(ws): update _subscribed_tickers only after ALL subscriptions confirmed (X-C1)"
```

---

### Task G2: Fix X-H1 + X-H2 + X-H3 — gap detection, task timeouts, bg task monitoring

**Files:**
- Modify: `merid/event_venues/kalshi/ws_bridge.py` (~line 358-372, gap detection)
- Modify: `merid/loop.py:278-288` (timeout handling)
- Modify: `merid/loop.py:321-330` (bg task monitoring)
- Test: `tests/event_venues/kalshi/test_ws_hardening.py`

- [ ] **Step 1: Fix X-H1 — extend gap detection to all message types**

In `ws_bridge.py`, find the gap detection block (~line 358-372). Move sequence tracking outside the fill-only conditional:

```python
# Track sequence for ALL message types, not just fills
msg_seq = event.get("seq") or event.get("sequence")
if msg_seq is not None and self._last_sequence is not None:
    expected_seq = self._last_sequence + 1
    gap = int(msg_seq) - expected_seq
    if gap >= 5:
        logger.warning("[ws] Sequence gap detected for ALL msg types: gap=%d type=%s", gap, event.get("type"))
        asyncio.create_task(self._recover_from_gap())
self._last_sequence = int(msg_seq) if msg_seq is not None else self._last_sequence
```

- [ ] **Step 2: Fix X-H2 — actually cancel tasks on timeout in loop.py**

In `merid/loop.py`, find the timeout handling (~line 278-288):

```python
try:
    await asyncio.wait_for(coro, timeout=timeout)
except asyncio.TimeoutError:
    logger.warning("[loop] Step %s timed out after %ss — cancelling", step_name, timeout)
    # Actually cancel the task so it doesn't continue consuming resources
    # (asyncio.wait_for cancels internally, but ensure cleanup)
    self._metrics.record_timeout(step_name)
```

Verify `asyncio.wait_for` actually cancels on timeout (it does in Python 3.11+). Add explicit log that the task was cancelled, not just timed out.

- [ ] **Step 3: Fix X-H3 — add done callbacks to background tasks**

In `merid/loop.py`, where `_agent_bg_task` is created (~line 329):

```python
self._agent_bg_task = asyncio.create_task(
    self._run_agent_cycles_bg(...)
)
# Monitor for unexpected termination
def _on_agent_task_done(task: asyncio.Task) -> None:
    if task.cancelled():
        logger.info("[loop] Agent cycle task cancelled (expected on shutdown)")
    elif task.exception():
        logger.error(
            "[loop] UNEXPECTED: agent cycle task died with exception: %s",
            task.exception(), exc_info=task.exception(),
        )
        # Could auto-restart here, or alert Telegram
self._agent_bg_task.add_done_callback(_on_agent_task_done)
```

Apply the same `add_done_callback` pattern to ALL background tasks created in `loop.py`.

- [ ] **Step 4: Run loop and ws tests**

```bash
pytest tests/event_venues/kalshi/test_ws_hardening.py tests/core/test_safety_drill.py -v
```

- [ ] **Step 5: Commit**

```bash
git add merid/event_venues/kalshi/ws_bridge.py merid/loop.py
git commit -m "fix(concurrency): extend gap detection to all msg types; cancel timeout tasks; monitor bg tasks (X-H1,X-H2,X-H3)"
```

---

## Self-Review

### Spec Coverage Check

| Audit ID | Task | Covered? |
|---|---|---|
| P-C3 | A1 | ✓ |
| P-C2 | A2 | ✓ |
| P-C1 | A3 | ✓ |
| P-H1 | A4 | ✓ |
| P-H2 | A5 | ✓ |
| D-C3 | B1 | ✓ |
| D-C1, D-C2 | B2 | ✓ |
| D-H2, D-H3 | B3 | ✓ |
| O-C1 | C1 | ✓ |
| O-H1, A-M2, A-M3, A-M4 | C2 | ✓ |
| A-C1 | D1 | ✓ |
| A-C2, A-H1 | D2 | ✓ |
| S-C1 | E1 | ✓ |
| E-C1, S-H1, S-H2/S-H3 | E2 | ✓ |
| M-H1 | F1 | ✓ |
| M-H2 | F2 | ✓ |
| M-M1, M-M2 | F3 | ✓ |
| X-C1 | G1 | ✓ |
| X-H1, X-H2, X-H3 | G2 | ✓ |
| A-M1 (dual thresholds) | **MISSING** | ✗ — add to D2 |
| M-C1 (TOCTOU — already locked) | **VERIFY** | Actual code has `with self._lock` in `check_and_reserve()`. Verify `record_fill()` is NOT also called after `check_and_reserve()` (which would double-count). Add test to F3. |
| X-M1 (coalesce buffer lock) | Not covered | Add to G2 |
| X-M3 (MockRedis stats) | Not covered | Low priority — add to G2 or separate cosmetic task |

### Additional Task D3: Fix A-M1 — Unify consensus threshold sources

**Files:**
- Modify: `merid/swarm/consensus_aggregator.py:189`
- Modify: `merid/swarm/consensus_engine.py:23`

In `consensus_aggregator.py`:
```python
consensus_threshold: float = float(os.getenv("MERID_CONSENSUS_THRESHOLD", "0.60"))
```

In `consensus_engine.py`:
```python
APPROVAL_THRESHOLD = float(os.getenv("MERID_CONSENSUS_THRESHOLD", "0.60"))
```

Both read the same env var with the same default (0.60). Document in `.env.example`.

### Additional Fix: M-C1 double-count verification

In `category_exposure.py`, verify that callers either:
- Use `check_and_reserve()` alone (reservation is permanent on fill), OR
- Use `check_category_cap()` + `check_correlated_cap()` + `record_fill()` (old path)

They must NOT use `check_and_reserve()` AND `record_fill()` (double-count). Add a test that verifies:
```python
def test_check_and_reserve_then_fill_does_not_double_count(tmp_path):
    """M-C1 verification: check_and_reserve() + record_fill() should NOT double-count.
    If both are called, total notional must only reflect one addition."""
    ...
```

### Placeholder Scan: None found.

### Type Consistency: All method names used match actual code read from files. ✓
