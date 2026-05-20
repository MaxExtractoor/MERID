"""Startup grid validator — assert 5 asset × 15m timeframe cells are wired.

Call ``validate_kalshi_grid()`` once at startup (before first trade cycle) to
guarantee the 5×1 grid (BTC/ETH/SOL/XRP/DOGE × 15m)
is fully configured.  Any dead cell raises ``GridValidationError`` in strict mode
so the process fails fast with a clear diagnostic instead of silently skipping markets.

FOCUS: 15m timeframe only for trading. All other timeframes are signal-only.

Usage (web/main.py startup)::

    from merid.event_venues.kalshi.grid_validator import validate_kalshi_grid, GridValidationError
    try:
        validate_kalshi_grid(strict=True)
    except GridValidationError as exc:
        logger.critical("Grid validation failed: %s", exc)
        raise SystemExit(1) from exc
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.grid_validator")

# ── Canonical grid dimensions ──────────────────────────────────────────────

# FOCUS: 5 assets (BTC, ETH, SOL, XRP, DOGE) x 15m timeframe only for trading
# All other timeframes are signal-only
REQUIRED_ASSETS: tuple = ("BTC", "ETH", "SOL", "XRP", "DOGE")
REQUIRED_TIMEFRAMES: tuple = ("15m",)

# Map YAML timeframe label → expected market_filter.frequency value
# FOCUS: 15m timeframe only for trading
TIMEFRAME_TO_MF_FREQ: Dict[str, str] = {
    "15m":     "fifteen_min",
}


class GridValidationError(RuntimeError):
    """Raised when the agent grid is missing required cells or config.

    The message contains a human-readable list of all dead cells and the
    specific problem with each one so the operator can fix them precisely.
    """


@dataclass
class CellStatus:
    """Validation result for a single asset×timeframe cell."""

    asset: str
    timeframe: str
    agent_name: Optional[str] = None
    has_agent: bool = False
    has_risk_limits: bool = False
    has_market_filter_freq: bool = False
    has_strategy: bool = False
    max_notional_usd: float = 0.0
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.has_agent
            and self.has_risk_limits
            and self.has_market_filter_freq
            and not self.errors
        )


def validate_kalshi_grid(strict: bool = True) -> Dict[str, CellStatus]:
    """Validate the 5-cell asset×15m timeframe grid.

    For each of the 5 cells the check verifies:
      1. An ``AgentConfig`` entry exists in ``kalshi_agent_grid.yaml``.
      2. ``risk_limits.max_notional_usd > 0`` — agent can actually size trades.
      3. ``market_filter.frequency`` matches the expected Kalshi frequency string
         for the timeframe (e.g. "fifteen_min" for 15m).
      4. (Warning only) An explicit ``strategy:`` block is present — if absent the
         agent falls back to ``StrategyConfig`` defaults which may be too aggressive.

    FOCUS: 5 assets (BTC, ETH, SOL, XRP, DOGE) x 15m timeframe only for trading.
    All other timeframes are signal-only.

    Args:
        strict: If ``True`` (default), raises ``GridValidationError`` when any cell
                fails checks 1–3.  If ``False``, logs warnings and returns the full
                status map for programmatic inspection without raising.

    Returns:
        ``Dict[str, CellStatus]`` mapping ``"ASSET/TF"`` → status for all 5 cells.

    Raises:
        GridValidationError: When ``strict=True`` and any cell fails a required check.
    """
    from merid.prediction.agent_grid_config import load_agent_grid_config

    try:
        grid_config = load_agent_grid_config()
    except Exception as exc:
        raise GridValidationError(f"Failed to load agent grid config: {exc}") from exc

    # Build lookup: (asset_upper, tf_lower) → AgentConfig
    # Dedicated agents (exactly 1 asset AND 1 timeframe) win over catch-all overlays.
    # Sort agents by specificity: single-cell agents first; then any that cover fewer
    # cells; catch-alls (0 assets or many) last.  Last-write wins within the same tier
    # so dedicated agents are never overwritten by a subsequent catch-all.
    def _agent_specificity(a) -> int:
        """Lower = more specific. Single-cell dedicated agent = 0."""
        return len(a.assets) * len(a.timeframes) if (a.assets and a.timeframes) else 9999

    sorted_agents = sorted(grid_config.agents, key=_agent_specificity, reverse=True)

    cell_map: Dict[tuple, object] = {}
    for agent in sorted_agents:
        for asset in agent.assets:
            for tf in agent.timeframes:
                key = (asset.upper(), tf.lower())
                # Only overwrite if the incoming agent is strictly more specific
                existing = cell_map.get(key)
                if existing is None or _agent_specificity(agent) < _agent_specificity(existing):
                    cell_map[key] = agent

    status_map: Dict[str, CellStatus] = {}
    dead_cells: List[str] = []

    for asset in REQUIRED_ASSETS:
        for tf in REQUIRED_TIMEFRAMES:
            key = f"{asset}/{tf}"
            agent = cell_map.get((asset, tf))
            cell = CellStatus(asset=asset, timeframe=tf)

            if agent is None:
                cell.errors.append(
                    f"No AgentConfig for {key} — add an entry to config/kalshi_agent_grid.yaml"
                )
                status_map[key] = cell
                dead_cells.append(key)
                continue

            cell.has_agent = True
            cell.agent_name = agent.name

            # ── Check 2: risk limits ──────────────────────────────────
            notional = float(agent.risk_limits.max_notional_usd)
            # If 0, derive from live bankroll via bankroll_service_v2 (3% for top-3 edge strategy)
            if notional == 0:
                try:
                    from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                    bankroll_usd = get_equity_for_risk_calc_sync()
                    if bankroll_usd is None or bankroll_usd <= 0:
                        # Fail closed - no bankroll available
                        notional = 0.0
                    else:
                        risk_fraction = getattr(settings, 'MERID_MAX_RISK_FRACTION_PER_CYCLE', 0.03)
                        notional = bankroll_usd * risk_fraction
                except Exception:
                    notional = 0.0  # Fail closed on error
            cell.max_notional_usd = notional
            if notional < 0:
                cell.errors.append(
                    f"{key}: max_notional_usd={notional} must be >= 0 "
                    "(agent cannot size any trade)"
                )
            else:
                cell.has_risk_limits = True

            # ── Check 3: market filter frequency ─────────────────────
            expected_freq = TIMEFRAME_TO_MF_FREQ.get(tf)
            actual_freq = agent.market_filter.frequency
            if not actual_freq:
                cell.errors.append(
                    f"{key}: market_filter.frequency is not set "
                    f"(expected {expected_freq!r} for {tf} timeframe)"
                )
            elif actual_freq != expected_freq:
                cell.errors.append(
                    f"{key}: market_filter.frequency={actual_freq!r} "
                    f"expected {expected_freq!r} — Kalshi catalog lookup will miss markets"
                )
            else:
                cell.has_market_filter_freq = True

            # ── Check 4: strategy block (warning only) ─────────────
            cell.has_strategy = bool(agent.strategy_overrides)
            if not cell.has_strategy:
                logger.warning(
                    "GRID[%s] agent=%s: no explicit strategy: block — "
                    "using StrategyConfig defaults (7%%/6%%/5%%/4%% min_edge tiers). "
                    "Add a strategy: block to kalshi_agent_grid.yaml for explicit control.",
                    key,
                    agent.name,
                )

            if cell.errors:
                dead_cells.append(key)

            status_map[key] = cell

    # ── Summary log ────────────────────────────────────────────────────
    total = len(REQUIRED_ASSETS) * len(REQUIRED_TIMEFRAMES)
    ok_count = sum(1 for s in status_map.values() if s.ok)
    if dead_cells:
        logger.error(
            "GRID VALIDATION: %d/%d cells OK — %d dead: %s",
            ok_count, total, len(dead_cells), dead_cells,
        )
    else:
        logger.info(
            "GRID VALIDATION: all %d/%d cells OK — BTC/ETH/SOL/XRP/DOGE × 6 timeframes",
            ok_count, total,
        )

    if dead_cells and strict:
        detail_lines = []
        for k in dead_cells:
            errs = "; ".join(status_map[k].errors)
            detail_lines.append(f"  {k}: {errs}")
        raise GridValidationError(
            f"Kalshi grid has {len(dead_cells)} dead cell(s) — "
            f"cannot start trading:\n" + "\n".join(detail_lines)
        )

    return status_map


def log_grid_summary(status_map: Dict[str, CellStatus]) -> None:
    """Log a one-line summary per cell — useful for startup health panels."""
    for key in sorted(status_map.keys()):
        s = status_map[key]
        state = "OK" if s.ok else "DEAD"
        issues = "; ".join(s.errors) if s.errors else "—"
        logger.info(
            "GRID[%s] agent=%s state=%s notional=$%.0f strategy=%s issues=%s",
            key,
            s.agent_name or "(none)",
            state,
            s.max_notional_usd,
            "explicit" if s.has_strategy else "default",
            issues,
        )
