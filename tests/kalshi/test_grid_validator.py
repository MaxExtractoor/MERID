"""Tests for the Kalshi 30-cell grid validator.

Verifies that all BTC/ETH/SOL/XRP/DOGE × 15m/1h/daily/weekly/monthly/annual
cells are present and fully configured in the YAML.
"""
import pytest

from merid.event_venues.kalshi.grid_validator import (
    REQUIRED_ASSETS,
    REQUIRED_TIMEFRAMES,
    CellStatus,
    GridValidationError,
    validate_kalshi_grid,
)


# ── Completeness ───────────────────────────────────────────────────────────

def test_all_30_cells_present():
    """All 30 cells must pass validation with no dead cells."""
    status = validate_kalshi_grid(strict=False)
    assert len(status) == len(REQUIRED_ASSETS) * len(REQUIRED_TIMEFRAMES) == 30
    dead = [k for k, s in status.items() if not s.ok]
    assert not dead, f"Dead cells found: {dead}"


def test_all_cells_have_agent():
    """Every cell must map to a named AgentConfig."""
    status = validate_kalshi_grid(strict=False)
    missing = [k for k, s in status.items() if not s.has_agent]
    assert not missing, f"Cells with no agent: {missing}"


def test_all_cells_have_positive_notional():
    """Every cell must have max_notional_usd > 0."""
    status = validate_kalshi_grid(strict=False)
    zero_notional = [k for k, s in status.items() if s.has_agent and s.max_notional_usd <= 0]
    assert not zero_notional, f"Cells with zero notional: {zero_notional}"


def test_all_cells_have_market_filter_freq():
    """Every cell must have the correct market_filter.frequency string."""
    status = validate_kalshi_grid(strict=False)
    missing_freq = [k for k, s in status.items() if s.has_agent and not s.has_market_filter_freq]
    assert not missing_freq, (
        f"Cells with missing/wrong market_filter.frequency: {missing_freq}\n"
        f"This means the agent's market_filter.frequency doesn't match the expected Kalshi freq for that timeframe."
    )


# ── All 5 assets covered ───────────────────────────────────────────────────

@pytest.mark.parametrize("asset", REQUIRED_ASSETS)
def test_asset_fully_covered(asset):
    """Each asset must have all 6 timeframes with OK status."""
    status = validate_kalshi_grid(strict=False)
    for tf in REQUIRED_TIMEFRAMES:
        key = f"{asset}/{tf}"
        assert key in status, f"Cell {key} missing from status map"
        assert status[key].ok, (
            f"Cell {key} not OK: {status[key].errors}"
        )


# ── All 6 timeframes covered ───────────────────────────────────────────────

@pytest.mark.parametrize("tf", REQUIRED_TIMEFRAMES)
def test_timeframe_fully_covered(tf):
    """Each timeframe must have all 5 assets with OK status."""
    status = validate_kalshi_grid(strict=False)
    for asset in REQUIRED_ASSETS:
        key = f"{asset}/{tf}"
        assert key in status, f"Cell {key} missing from status map"
        assert status[key].ok, f"Cell {key} not OK: {status[key].errors}"


# ── Strict mode ───────────────────────────────────────────────────────────

def test_strict_mode_raises_on_missing_cell(monkeypatch):
    """strict=True must raise GridValidationError when a required cell is absent."""
    from merid.prediction import agent_grid_config as agc

    original_load = agc.load_agent_grid_config

    def patched_load(*args, **kwargs):
        cfg = original_load(*args, **kwargs)
        # Remove BTC_15M to simulate a dead cell
        cfg.agents = [a for a in cfg.agents if a.name != "BTC_15M"]
        return cfg

    monkeypatch.setattr(agc, "load_agent_grid_config", patched_load)

    with pytest.raises(GridValidationError) as exc_info:
        validate_kalshi_grid(strict=True)

    assert "BTC/15m" in str(exc_info.value)


def test_non_strict_mode_returns_status_on_error(monkeypatch):
    """strict=False must return the status map even when cells fail."""
    from merid.prediction import agent_grid_config as agc

    original_load = agc.load_agent_grid_config

    def patched_load(*args, **kwargs):
        cfg = original_load(*args, **kwargs)
        cfg.agents = [a for a in cfg.agents if a.name != "ETH_DAILY"]
        return cfg

    monkeypatch.setattr(agc, "load_agent_grid_config", patched_load)

    # Should not raise
    status = validate_kalshi_grid(strict=False)
    assert len(status) == 30

    dead_cell = status.get("ETH/daily")
    assert dead_cell is not None
    assert not dead_cell.ok
    assert not dead_cell.has_agent


def test_strict_mode_raises_on_zero_notional(monkeypatch):
    """strict=True raises when an agent has max_notional_usd=0."""
    from merid.prediction import agent_grid_config as agc
    from decimal import Decimal

    original_load = agc.load_agent_grid_config

    def patched_load(*args, **kwargs):
        cfg = original_load(*args, **kwargs)
        for a in cfg.agents:
            if a.name == "SOL_WEEKLY":
                a.risk_limits.max_notional_usd = Decimal("0")
        return cfg

    monkeypatch.setattr(agc, "load_agent_grid_config", patched_load)

    with pytest.raises(GridValidationError) as exc_info:
        validate_kalshi_grid(strict=True)

    assert "SOL/weekly" in str(exc_info.value)


# ── Strategy coverage ─────────────────────────────────────────────────────

def test_all_monthly_annual_agents_have_strategy():
    """Monthly and annual agents must have explicit strategy: blocks (not default fallback)."""
    status = validate_kalshi_grid(strict=False)
    for tf in ("monthly", "annual"):
        for asset in REQUIRED_ASSETS:
            key = f"{asset}/{tf}"
            s = status[key]
            assert s.has_strategy, (
                f"{key}: agent {s.agent_name!r} has no explicit strategy: block "
                "— add strategy: min_edge_* entries to config/kalshi_agent_grid.yaml"
            )


# ── Specificity: dedicated agents win over catch-all ──────────────────────

def test_dedicated_agent_wins_over_catch_all():
    """BTC_15M (dedicated) must win over SENTIMENT_VOL_BREAKOUT_CRYPTO (catch-all)."""
    status = validate_kalshi_grid(strict=False)
    btc_15m = status.get("BTC/15m")
    assert btc_15m is not None
    # The dedicated BTC_15M agent must be selected, not the catch-all
    assert btc_15m.agent_name == "BTC_15M", (
        f"BTC/15m is served by {btc_15m.agent_name!r} instead of 'BTC_15M'. "
        "Catch-all agent is overwriting dedicated agent — fix grid_validator specificity sort."
    )
