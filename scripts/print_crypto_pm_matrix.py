#!/usr/bin/env python3
"""Print BTC/ETH/SOL/XRP/DOGE × configured timeframes (AgentGrid YAML matrix).

Run::

    python scripts/print_crypto_pm_matrix.py

Columns match ops expectations: asset, timeframe, agent_id, enabled, min_edge (strategy),
entry_window minutes_before_expiry (before = window opens relative to expiry).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from merid.prediction.agent_grid_config import get_agent_grid_config
from merid.prediction.strategy import StrategyConfig
from merid.pm_crypto_ops import default_strategy_min_edge_floor_bps, is_core_crypto_pm_config


def main() -> None:
    cfg = get_agent_grid_config()
    sc = StrategyConfig()
    floor = default_strategy_min_edge_floor_bps()
    print(
        f"KalshiStrategy min_edge (fraction as bps): early={float(sc.min_edge_early)*10000:.0f} "
        f"mid={float(sc.min_edge_mid)*10000:.0f} late={float(sc.min_edge_late)*10000:.0f} "
        f"terminal={float(sc.min_edge_terminal)*10000:.0f} (floor_early~{floor:.0f} bps)\n"
    )
    print(
        f"{'asset':<6} {'tf':<8} {'agent_id':<28} {'en':<5} "
        f"{'edge_early_bps':<14} {'ew_before':<10} {'ew_cutoff':<10}"
    )
    for a in sorted(
        (x for x in cfg.agents if is_core_crypto_pm_config(x)),
        key=lambda x: (x.assets[0] if x.assets else "", x.name),
    ):
        tf = a.timeframes[0] if a.timeframes else ""
        ast = a.assets[0] if a.assets else ""
        print(
            f"{ast:<6} {tf:<8} {a.agent_id:<28} {str(a.enabled):<5} "
            f"{float(sc.min_edge_early)*10000:<14.0f} "
            f"{a.entry_window.minutes_before_expiry!s:<10} "
            f"{a.entry_window.cutoff_minutes_before_expiry!s:<10}"
        )


if __name__ == "__main__":
    main()
