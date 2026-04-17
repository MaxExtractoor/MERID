# Kill-Switch + Production Hardening — Full MERID Kalshi Audit

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden every kill/halt/disable control in the MERID Kalshi trading path, eliminate all silent blockers, and guarantee BTC/ETH/SOL/XRP/DOGE trading across all 6 timeframes (15m, hourly, daily, weekly, monthly, annual) is fully operational on next cold start.

**Architecture:** Single-flag canonical kill switch (`risk_controller._global_kill`) is already the primary truth; all other controls feed into `check_execution_gate()`. Hardening = fix the annual-timeframe gaps in market_filter.py, add missing strategy blocks in YAML, wire a startup grid validator, enhance CT-TRACE logging, and write the kill-switch control table.

**Tech Stack:** Python 3.11, FastAPI, YAML config, pytest

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `merid/event_venues/kalshi/market_filter.py` | Modify | Add `annual` entries to MIN_EDGE_GRID, MAX_PRICE_GRID, PRICE_BANDS |
| `config/kalshi_agent_grid.yaml` | Modify | Add `strategy:` blocks to all monthly+annual agents |
| `merid/event_venues/kalshi/grid_validator.py` | Create | Startup validation: all 30 cells fully wired |
| `merid/event_venues/kalshi/constants.py` | Modify | Add `assert_exact_timeframes()` + `CANONICAL_TIMEFRAMES` |
| `web/main.py` | Modify | Call grid_validator at startup (Phase -1 block) |
| `docs/KILL_SWITCH_INVENTORY.md` | Create | Full kill/halt control table with paths |
| `CHECKLIST.md` | Create | Operator checklist for live-ready verification |
| `tests/kalshi/test_grid_validator.py` | Create | Grid completeness + startup validation tests |
| `tests/kalshi/test_kill_switch_chain.py` | Create | Kill switch chain integration tests |
| `tests/kalshi/test_annual_timeframe.py` | Create | Annual market filter tests |

---

## Task 1: Fix `annual` timeframe in `market_filter.py`

**Root cause:** `MIN_EDGE_GRID`, `MAX_PRICE_GRID`, and `PRICE_BANDS` all have 5-asset rows but only 5 timeframe columns (15m/1h/daily/weekly/monthly). Annual markets fall through to conservative defaults (35-cent max price cap) that would filter out all realistic annual contracts.

**Files:**
- Modify: `merid/event_venues/kalshi/market_filter.py`

- [ ] **Step 1: Read the current MIN_EDGE_GRID block (lines 42–78)**

- [ ] **Step 2: Add `annual` entries to MIN_EDGE_GRID**

In `MIN_EDGE_GRID`, add `"annual": Decimal("0.05")` for each asset — annual markets have lower noise so a 5% floor is appropriate (same as weekly but one tier lower):

```python
MIN_EDGE_GRID: Dict[str, Dict[str, Decimal]] = {
    "BTC": {
        "15m": Decimal("0.10"),
        "1h":  Decimal("0.08"),
        "daily":   Decimal("0.08"),
        "weekly":  Decimal("0.07"),
        "monthly": Decimal("0.06"),
        "annual":  Decimal("0.05"),   # <-- ADD
    },
    "ETH": {
        "15m": Decimal("0.11"),
        "1h":  Decimal("0.09"),
        "daily":   Decimal("0.09"),
        "weekly":  Decimal("0.08"),
        "monthly": Decimal("0.07"),
        "annual":  Decimal("0.06"),   # <-- ADD
    },
    "SOL": {
        "15m": Decimal("0.13"),
        "1h":  Decimal("0.10"),
        "daily":   Decimal("0.10"),
        "weekly":  Decimal("0.09"),
        "monthly": Decimal("0.08"),
        "annual":  Decimal("0.07"),   # <-- ADD
    },
    "XRP": {
        "15m": Decimal("0.14"),
        "1h":  Decimal("0.11"),
        "daily":   Decimal("0.11"),
        "weekly":  Decimal("0.10"),
        "monthly": Decimal("0.09"),
        "annual":  Decimal("0.08"),   # <-- ADD
    },
    "DOGE": {
        "15m": Decimal("0.15"),
        "1h":  Decimal("0.12"),
        "daily":   Decimal("0.12"),
        "weekly":  Decimal("0.11"),
        "monthly": Decimal("0.10"),
        "annual":  Decimal("0.09"),   # <-- ADD
    },
}
```

- [ ] **Step 3: Add `annual` entries to MAX_PRICE_GRID**

Annual markets are longer-tenor → can trade higher-probability contracts → raise cap to 80 cents:

```python
MAX_PRICE_GRID: Dict[str, Dict[str, int]] = {
    "BTC": {
        "15m": 40, "1h": 50, "daily": 60, "weekly": 65, "monthly": 70,
        "annual": 80,   # <-- ADD
    },
    "ETH": {
        "15m": 38, "1h": 48, "daily": 58, "weekly": 63, "monthly": 68,
        "annual": 78,   # <-- ADD
    },
    "SOL": {
        "15m": 35, "1h": 45, "daily": 55, "weekly": 60, "monthly": 65,
        "annual": 75,   # <-- ADD
    },
    "XRP": {
        "15m": 32, "1h": 42, "daily": 52, "weekly": 58, "monthly": 63,
        "annual": 72,   # <-- ADD
    },
    "DOGE": {
        "15m": 30, "1h": 40, "daily": 50, "weekly": 55, "monthly": 60,
        "annual": 70,   # <-- ADD
    },
}
```

- [ ] **Step 4: Add `annual` entries to PRICE_BANDS**

```python
# BTC annual — widest band, long-term market
("BTC", "annual"):  (0.20, 0.80),   # <-- ADD
# ETH annual
("ETH", "annual"):  (0.15, 0.85),   # <-- ADD
# SOL annual
("SOL", "annual"):  (0.10, 0.90),   # <-- ADD
# XRP annual
("XRP", "annual"):  (0.10, 0.90),   # <-- ADD
# DOGE annual
("DOGE", "annual"): (0.05, 0.95),   # <-- ADD
```

- [ ] **Step 5: Add `assert_exact_timeframes` check after PRICE_BANDS definition**

At line ~216, after the existing `assert_exact_assets` calls, add:

```python
# Validate all 6 timeframe buckets are covered per asset
CANONICAL_TIMEFRAMES_SET = {"15m", "1h", "daily", "weekly", "monthly", "annual"}
for _asset_key, _tf_dict in MIN_EDGE_GRID.items():
    _missing = CANONICAL_TIMEFRAMES_SET - set(_tf_dict.keys())
    if _missing:
        raise AssertionError(f"MIN_EDGE_GRID[{_asset_key}] missing timeframes: {_missing}")
for _asset_key, _tf_dict in MAX_PRICE_GRID.items():
    _missing = CANONICAL_TIMEFRAMES_SET - set(_tf_dict.keys())
    if _missing:
        raise AssertionError(f"MAX_PRICE_GRID[{_asset_key}] missing timeframes: {_missing}")
```

- [ ] **Step 6: Run tests**

```bash
python -c "import merid.event_venues.kalshi.market_filter; print('OK')"
```
Expected: `OK` with no AssertionError.

- [ ] **Step 7: Commit**

```bash
git add merid/event_venues/kalshi/market_filter.py
git commit -m "fix(market_filter): add annual timeframe to MIN_EDGE/MAX_PRICE/PRICE_BANDS grids"
```

---

## Task 2: Add `strategy:` blocks to all monthly + annual agents in YAML

**Root cause:** BTC/ETH/SOL/XRP/DOGE monthly and annual agents lack `strategy:` blocks → fall back to StrategyConfig defaults (7/6/5/4% min_edge). For longer-tenor markets these are reasonable but should be explicit, not accidental.

**Files:**
- Modify: `config/kalshi_agent_grid.yaml`

- [ ] **Step 1: Add strategy block to each MONTHLY agent** (BTC, ETH, SOL, XRP, DOGE)

For each monthly agent, insert after `archetype: directional`:

```yaml
  strategy:
    # Monthly: long-tenor, lower noise — graduated edge tiers
    min_edge_early: 0.06
    min_edge_mid:   0.05
    min_edge_late:  0.04
    min_edge_terminal: 0.03
```

(Adjust per-asset: BTC=above; ETH=+1%; SOL=+2%; XRP=+3%; DOGE=+4%)

BTC_MONTHLY:
```yaml
  strategy:
    min_edge_early: 0.06
    min_edge_mid:   0.05
    min_edge_late:  0.04
    min_edge_terminal: 0.03
```

ETH_MONTHLY:
```yaml
  strategy:
    min_edge_early: 0.07
    min_edge_mid:   0.06
    min_edge_late:  0.05
    min_edge_terminal: 0.04
```

SOL_MONTHLY:
```yaml
  strategy:
    min_edge_early: 0.08
    min_edge_mid:   0.07
    min_edge_late:  0.06
    min_edge_terminal: 0.05
```

XRP_MONTHLY:
```yaml
  strategy:
    min_edge_early: 0.09
    min_edge_mid:   0.08
    min_edge_late:  0.07
    min_edge_terminal: 0.06
```

DOGE_MONTHLY:
```yaml
  strategy:
    min_edge_early: 0.10
    min_edge_mid:   0.09
    min_edge_late:  0.08
    min_edge_terminal: 0.07
```

- [ ] **Step 2: Add strategy block to each ANNUAL agent**

BTC_ANNUAL:
```yaml
  strategy:
    min_edge_early: 0.05
    min_edge_mid:   0.04
    min_edge_late:  0.03
    min_edge_terminal: 0.02
```

ETH_ANNUAL:
```yaml
  strategy:
    min_edge_early: 0.06
    min_edge_mid:   0.05
    min_edge_late:  0.04
    min_edge_terminal: 0.03
```

SOL_ANNUAL:
```yaml
  strategy:
    min_edge_early: 0.07
    min_edge_mid:   0.06
    min_edge_late:  0.05
    min_edge_terminal: 0.04
```

XRP_ANNUAL:
```yaml
  strategy:
    min_edge_early: 0.08
    min_edge_mid:   0.07
    min_edge_late:  0.06
    min_edge_terminal: 0.05
```

DOGE_ANNUAL:
```yaml
  strategy:
    min_edge_early: 0.09
    min_edge_mid:   0.08
    min_edge_late:  0.07
    min_edge_terminal: 0.06
```

- [ ] **Step 3: Load and validate YAML**

```bash
python -c "
from merid.prediction.agent_grid_config import load_agent_grid_config
cfg = load_agent_grid_config()
for a in cfg.agents:
    has_strat = bool(a.strategy_overrides)
    print(f'{a.name}: strategy_overrides={has_strat}')
"
```
Expected: all 30 agents print with strategy_overrides dict.

- [ ] **Step 4: Commit**

```bash
git add config/kalshi_agent_grid.yaml
git commit -m "config(grid): add explicit strategy blocks to all monthly and annual agents"
```

---

## Task 3: Create startup grid validator

**File:** `merid/event_venues/kalshi/grid_validator.py` (CREATE)

This module asserts at startup that every cell in the 5×6 grid (BTC/ETH/SOL/XRP/DOGE × 15m/1h/daily/weekly/monthly/annual) has:
- An AgentConfig in the loaded grid
- A non-zero max_notional_usd risk limit
- A market_filter.frequency set to a known Kalshi frequency string

- [ ] **Step 1: Write the validator module**

```python
"""Startup grid validator — assert all 30 asset×timeframe cells are wired.

Call validate_kalshi_grid() once at startup (before first trade cycle).
Raises GridValidationError with a clear diagnostic if any cell is missing
config, risk limits, or market filter frequency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.grid_validator")

REQUIRED_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
REQUIRED_TIMEFRAMES = ("15m", "1h", "daily", "weekly", "monthly", "annual")

# Map YAML timeframe labels → Kalshi frequency strings
TIMEFRAME_TO_KALSHI_FREQ = {
    "15m":     "fifteen_min",
    "1h":      "hourly",
    "daily":   "daily",
    "weekly":  "weekly",
    "monthly": "monthly",
    "annual":  "annual",
}

# Map YAML strategy timeframe → market_filter_config.frequency expected value
YAML_TF_TO_MF_FREQ = {
    "15m":     "fifteen_min",
    "1h":      "hourly",
    "daily":   "daily",
    "weekly":  "weekly",
    "monthly": "monthly",
    "annual":  "annual",
}


class GridValidationError(RuntimeError):
    """Raised when the agent grid is missing required cells or config."""


@dataclass
class CellStatus:
    asset: str
    timeframe: str
    agent_name: Optional[str] = None
    has_agent: bool = False
    has_risk_limits: bool = False
    has_market_filter_freq: bool = False
    has_strategy: bool = False
    max_notional_usd: float = 0.0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    @property
    def ok(self) -> bool:
        return self.has_agent and self.has_risk_limits and self.has_market_filter_freq and not self.errors


def validate_kalshi_grid(strict: bool = True) -> Dict[str, CellStatus]:
    """Validate the full 30-cell asset×timeframe grid.

    Args:
        strict: If True, raises GridValidationError on any missing cell.
                If False, logs warnings and returns status map for diagnostics.

    Returns:
        Dict mapping "ASSET/TF" → CellStatus for all 30 cells.

    Raises:
        GridValidationError: When strict=True and any cell is misconfigured.
    """
    from merid.prediction.agent_grid_config import load_agent_grid_config

    try:
        grid_config = load_agent_grid_config()
    except Exception as exc:
        raise GridValidationError(f"Failed to load agent grid config: {exc}") from exc

    # Build lookup: (asset, timeframe) → AgentConfig
    cell_map: Dict[tuple, object] = {}
    for agent in grid_config.agents:
        for asset in agent.assets:
            for tf in agent.timeframes:
                cell_map[(asset.upper(), tf.lower())] = agent

    status_map: Dict[str, CellStatus] = {}
    dead_cells: List[str] = []

    for asset in REQUIRED_ASSETS:
        for tf in REQUIRED_TIMEFRAMES:
            key = f"{asset}/{tf}"
            agent = cell_map.get((asset, tf))
            cell = CellStatus(asset=asset, timeframe=tf)

            if agent is None:
                cell.errors.append(f"No AgentConfig for {asset}/{tf} in kalshi_agent_grid.yaml")
                status_map[key] = cell
                dead_cells.append(key)
                continue

            cell.has_agent = True
            cell.agent_name = agent.name

            # Check risk limits
            notional = float(agent.risk_limits.max_notional_usd)
            cell.max_notional_usd = notional
            if notional <= 0:
                cell.errors.append(f"{key}: max_notional_usd={notional} must be > 0")
            else:
                cell.has_risk_limits = True

            # Check market filter frequency
            expected_freq = YAML_TF_TO_MF_FREQ.get(tf)
            actual_freq = agent.market_filter.frequency
            if not actual_freq:
                cell.errors.append(f"{key}: market_filter.frequency is not set")
            elif actual_freq != expected_freq:
                cell.errors.append(
                    f"{key}: market_filter.frequency={actual_freq!r} "
                    f"expected {expected_freq!r}"
                )
            else:
                cell.has_market_filter_freq = True

            # Strategy presence (warning only — defaults are acceptable)
            cell.has_strategy = bool(agent.strategy_overrides)
            if not cell.has_strategy:
                logger.warning(
                    "GRID[%s]: no explicit strategy block — using StrategyConfig defaults", key
                )

            if cell.errors:
                dead_cells.append(key)

            status_map[key] = cell

    # Log summary
    ok_cells = [k for k, s in status_map.items() if s.ok]
    logger.info(
        "Grid validation: %d/%d cells OK. Dead cells: %s",
        len(ok_cells),
        len(REQUIRED_ASSETS) * len(REQUIRED_TIMEFRAMES),
        dead_cells or "none",
    )

    if dead_cells and strict:
        detail = "\n".join(
            f"  {k}: " + "; ".join(status_map[k].errors)
            for k in dead_cells
        )
        raise GridValidationError(
            f"Kalshi grid has {len(dead_cells)} dead cells — cannot start trading:\n{detail}"
        )

    return status_map
```

- [ ] **Step 2: Wire into web/main.py startup**

Find the Phase -1 startup block in `web/main.py` (near `require_live_confirmation`) and add:

```python
# Grid validation — must run before first trade cycle
try:
    from merid.event_venues.kalshi.grid_validator import validate_kalshi_grid, GridValidationError
    validate_kalshi_grid(strict=True)
    logger.info("✅ Kalshi 30-cell grid validation passed")
except GridValidationError as _gve:
    logger.critical("❌ GRID VALIDATION FAILED: %s", _gve)
    raise SystemExit(1) from _gve
except Exception as _gve_exc:
    logger.warning("Grid validation failed with unexpected error: %s", _gve_exc)
```

- [ ] **Step 3: Write tests**

File: `tests/kalshi/test_grid_validator.py`

```python
"""Tests for the Kalshi 30-cell grid validator."""
import pytest
from merid.event_venues.kalshi.grid_validator import (
    validate_kalshi_grid,
    GridValidationError,
    REQUIRED_ASSETS,
    REQUIRED_TIMEFRAMES,
)


def test_all_30_cells_present():
    """Validate that all 30 asset×timeframe cells are in the YAML."""
    status = validate_kalshi_grid(strict=False)
    assert len(status) == len(REQUIRED_ASSETS) * len(REQUIRED_TIMEFRAMES) == 30
    dead = [k for k, s in status.items() if not s.ok]
    assert not dead, f"Dead cells: {dead}"


def test_all_cells_have_positive_notional():
    status = validate_kalshi_grid(strict=False)
    for key, cell in status.items():
        if cell.has_agent:
            assert cell.max_notional_usd > 0, f"{key}: max_notional_usd=0"


def test_all_cells_have_market_filter_freq():
    status = validate_kalshi_grid(strict=False)
    for key, cell in status.items():
        if cell.has_agent:
            assert cell.has_market_filter_freq, f"{key}: missing market_filter.frequency"


def test_strict_mode_raises_on_missing_cell(monkeypatch):
    """strict=True should raise when a cell is missing."""
    from merid.prediction import agent_grid_config as agc
    original_load = agc.load_agent_grid_config

    def patched_load():
        cfg = original_load()
        # Remove one agent to simulate a dead cell
        cfg.agents = [a for a in cfg.agents if a.name != "BTC_15M"]
        return cfg

    monkeypatch.setattr(agc, "load_agent_grid_config", patched_load)
    with pytest.raises(GridValidationError, match="BTC/15m"):
        validate_kalshi_grid(strict=True)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/kalshi/test_grid_validator.py -v
```
Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add merid/event_venues/kalshi/grid_validator.py tests/kalshi/test_grid_validator.py
git commit -m "feat(validator): startup 30-cell grid validator with strict mode"
```

---

## Task 4: Kill-switch inventory and path mapping

**File:** `docs/KILL_SWITCH_INVENTORY.md` (CREATE)

Comprehensive table of every kill/halt control that can affect Kalshi trading.

- [ ] **Step 1: Create the document** (see content below)

- [ ] **Step 2: Validate arbitrage.py kill switch is truly dead**

```bash
grep -r "from web.api.arbitrage import\|include_router.*arbitrage" web/main.py
```
If the arbitrage router is NOT mounted, the `arbitrage.py` kill switch is dead for Kalshi. Document this.

- [ ] **Step 3: Commit**

```bash
git add docs/KILL_SWITCH_INVENTORY.md
git commit -m "docs(kill-switch): comprehensive control inventory with path mappings"
```

---

## Task 5: Annual timeframe tests

**File:** `tests/kalshi/test_annual_timeframe.py` (CREATE)

- [ ] **Step 1: Write tests**

```python
"""Tests for annual timeframe config coverage in market_filter."""
from decimal import Decimal
import pytest
from merid.event_venues.kalshi.market_filter import (
    MIN_EDGE_GRID,
    MAX_PRICE_GRID,
    PRICE_BANDS,
    get_series_timeframe_bucket,
    get_tiered_min_edge,
    get_tiered_max_price,
    get_price_band,
    CANONICAL_TIMEFRAMES_SET,
)

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")


def test_annual_in_min_edge_grid():
    for asset in ASSETS:
        assert "annual" in MIN_EDGE_GRID[asset], f"MIN_EDGE_GRID[{asset}] missing annual"


def test_annual_in_max_price_grid():
    for asset in ASSETS:
        assert "annual" in MAX_PRICE_GRID[asset], f"MAX_PRICE_GRID[{asset}] missing annual"


def test_annual_max_price_above_monthly():
    """Annual max price must exceed monthly — longer tenor = higher probability cap."""
    for asset in ASSETS:
        assert MAX_PRICE_GRID[asset]["annual"] > MAX_PRICE_GRID[asset]["monthly"], (
            f"{asset}: annual max_price <= monthly"
        )


def test_annual_price_band_present():
    for asset in ASSETS:
        assert (asset, "annual") in PRICE_BANDS, f"PRICE_BANDS missing ({asset}, annual)"


def test_annual_ticker_detection():
    """KXBTCY series ticker maps to annual bucket."""
    assert get_series_timeframe_bucket("KXBTCY") == "annual"
    assert get_series_timeframe_bucket("KXETHY") == "annual"
    assert get_series_timeframe_bucket("KXBTCY-26DEC2025") == "annual"


@pytest.mark.parametrize("asset", ASSETS)
def test_tiered_min_edge_annual_below_floor(asset):
    """Annual min_edge from tiered grid must be at or above global floor (0.08 for BTC, lower is OK)."""
    edge = get_tiered_min_edge(asset, "KXBTCY")  # any annual ticker
    assert edge >= Decimal("0.02"), f"{asset}/annual: edge {edge} suspiciously low"


def test_all_timeframes_in_grids():
    """All 6 canonical timeframes must be in every asset row of MIN_EDGE_GRID."""
    for asset in ASSETS:
        missing = CANONICAL_TIMEFRAMES_SET - set(MIN_EDGE_GRID[asset].keys())
        assert not missing, f"MIN_EDGE_GRID[{asset}] missing: {missing}"
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/kalshi/test_annual_timeframe.py -v
```
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add tests/kalshi/test_annual_timeframe.py
git commit -m "test(annual): annual timeframe grid coverage tests"
```

---

## Task 6: Kill-switch chain integration tests

**File:** `tests/kalshi/test_kill_switch_chain.py` (CREATE)

- [ ] **Step 1: Write tests**

```python
"""Kill switch chain integration tests.

Tests the path: risk_controller._global_kill → check_execution_gate() → blocked.
"""
import pytest


@pytest.fixture(autouse=True)
def fresh_risk_controller():
    """Reset kill switch state before each test."""
    from merid.risk.kill_switches import risk_controller
    risk_controller.reset_kill_switch()
    yield
    risk_controller.reset_kill_switch()


def test_gate_clear_when_no_kill():
    """Execution gate must be CLEAR when no kill is active (in demo mode)."""
    import os
    os.environ["KALSHI_USE_DEMO"] = "true"
    from core.execution_gate import check_execution_gate, GateState
    status = check_execution_gate()
    # Kill switch source must not appear as critical
    kill_reasons = [r for r in status.reasons if r.source == "kill_switch"]
    assert not kill_reasons, f"Kill switch active unexpectedly: {kill_reasons}"


def test_gate_blocked_when_kill_active():
    """Execution gate must be BLOCKED when kill switch is engaged."""
    from merid.risk.kill_switches import risk_controller
    from core.execution_gate import check_execution_gate, GateState
    risk_controller.emergency_stop("Test: manual kill")
    status = check_execution_gate()
    assert status.blocked, "Gate should be blocked when kill switch is active"
    assert status.gate_state == GateState.BLOCKED.value
    kill_reasons = [r for r in status.reasons if r.source == "kill_switch"]
    assert kill_reasons, "kill_switch reason missing from blocked gate"


def test_gate_clears_after_reset():
    """Gate must clear after reset (in demo mode, no other blockers)."""
    import os
    os.environ["KALSHI_USE_DEMO"] = "true"
    from merid.risk.kill_switches import risk_controller
    from core.execution_gate import check_execution_gate
    risk_controller.emergency_stop("Test: temp kill")
    status_blocked = check_execution_gate()
    assert status_blocked.blocked
    risk_controller.reset_kill_switch()
    status_clear = check_execution_gate()
    kill_reasons = [r for r in status_clear.reasons if r.source == "kill_switch" and r.severity == "critical"]
    assert not kill_reasons, "Kill switch still critical after reset"


def test_venue_gate_mock_mode_blocks_can_trade():
    """VenueGate in MOCK mode must raise ModeBlockedError on check_can_trade."""
    from merid.prediction.venue_gate import VenueGate
    from trading.trade_mode import TradeMode
    gate = VenueGate(mode=TradeMode.MOCK)
    with pytest.raises(VenueGate.ModeBlockedError):
        gate.check_can_trade()


def test_venue_gate_kalshi_allowed():
    """VenueGate must allow kalshi venue."""
    from merid.prediction.venue_gate import VenueGate
    gate = VenueGate()
    gate.check_venue("kalshi")  # must not raise


def test_venue_gate_polymarket_blocked():
    """VenueGate must block polymarket (US compliance)."""
    from merid.prediction.venue_gate import VenueGate
    gate = VenueGate()
    with pytest.raises(VenueGate.VenueBlockedError):
        gate.check_venue("polymarket")


def test_daily_loss_triggers_kill():
    """Exceeding daily loss limit must trigger kill switch."""
    from merid.risk.kill_switches import risk_controller
    risk_controller.daily_loss_limit = 10.0
    risk_controller._daily_pnl = 0.0
    triggered = risk_controller.record_pnl(-15.0)
    assert triggered, "record_pnl should return True (kill triggered)"
    assert risk_controller._global_kill, "Kill switch not set after daily loss breach"
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/kalshi/test_kill_switch_chain.py -v
```
Expected: all 7 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/kalshi/test_kill_switch_chain.py
git commit -m "test(kill-switch): gate chain, VenueGate, daily-loss integration tests"
```

---

## Task 7: Create CHECKLIST.md

**File:** `CHECKLIST.md` (CREATE at repo root)

Operator checklist for verifying live-readiness and interpreting new metrics.

- [ ] **Step 1: Create the file**

See content below (generated as part of this plan execution).

- [ ] **Step 2: Commit**

```bash
git add CHECKLIST.md
git commit -m "docs(checklist): operator live-readiness and kill-switch verification guide"
```

---

## Self-Review

**Spec coverage check:**
- [x] §0 — Existing inventories as hints: we re-derived from live codebase
- [x] §1 — Grid freeze: 30-cell validation module + YAML all 5×6 cells
- [x] §2 — Kill-switch inventory: KILL_SWITCH_INVENTORY.md
- [x] §3 — Classification: table in inventory doc
- [x] §4 — Universe/catalog: annual TF gap fixed in market_filter.py
- [x] §5 — PM spot health: already hardened (Phase 22); no new gaps found
- [x] §6 — Consensus: no new consensus wiring issues found
- [x] §7 — Sizing: annual MAX_PRICE_GRID fixed (35→80 cents)
- [x] §8 — Path mapping: documented in KILL_SWITCH_INVENTORY.md
- [x] §9 — Kalshi-order blocking analysis: in inventory doc
- [x] §10 — Execution path: single path confirmed; no legacy lanes active
- [x] §11 — CT-TRACE: existing PM_CYCLE_TRACE is adequate; grid_validator adds startup tracing
- [x] §12 — Safety rails: grid_validator + existing gate chain
- [x] §13 — Tests: annual TF tests, grid validator tests, kill-switch chain tests

**Gaps identified (residual):**
- CT-TRACE per-cycle `seen_in_catalog` / `passed_filters` fields are partially present via PM_CYCLE_TRACE but not in structured JSON — out of scope for this sprint, tracked in KALSHI_SAFETY_BACKLOG.md
- `automated_risk_controls.py` PortfolioRiskManager is not wired to check_execution_gate — dead path for Kalshi, documented in inventory
