#!/usr/bin/env python3
"""For each core crypto PM agent, show catalog coverage (active markets, sample ticker).

Run from repo root::

    python scripts/diagnose_crypto_pm_catalog.py

Requires Kalshi API credentials / network like other catalog refresh paths.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS
from merid.prediction.agent_grid_config import get_agent_grid_config
from merid.pm_crypto_ops import crypto_product_key, is_core_crypto_pm_config


async def _main() -> None:
    from merid.event_venues.kalshi.market_catalog import get_market_catalog

    cfg = get_agent_grid_config()
    cat = get_market_catalog()
    await cat.start()
    await cat.refresh()

    now = datetime.now(timezone.utc)

    for agent in sorted(
        (x for x in cfg.agents if is_core_crypto_pm_config(x)),
        key=lambda x: (x.assets[0] if x.assets else "", x.name),
    ):
        asset = agent.assets[0] if agent.assets else ""
        tf = agent.timeframes[0] if agent.timeframes else ""
        prod_key = crypto_product_key(asset, tf)
        series_ids = KALSHI_CRYPTO_PRODUCTS.get(prod_key, [])

        rows = cat.get_active_markets(asset=asset, timeframe=tf)
        sample = rows[0].market.market_id if rows else "(none)"
        expirations: list = []
        for em in rows[:80]:
            dt = em.market.close_time or em.market.end_date
            if dt:
                expirations.append(dt)
        tte: list[float] = []
        for dt in expirations:
            if hasattr(dt, "timestamp"):
                tte.append((dt - now).total_seconds() / 3600.0)
        if tte:
            tte_str = f"min_h={min(tte):.1f} max_h={max(tte):.1f} n={len(tte)}"
        else:
            tte_str = "n/a"

        print(
            f"{agent.name:<16} asset={asset:<5} tf={tf:<8} prod_key={prod_key} "
            f"series={series_ids} active_n={len(rows)} sample={sample} {tte_str}"
        )

    await cat.stop()


if __name__ == "__main__":
    asyncio.run(_main())
