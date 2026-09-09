"""Shared P0 preflight assertions.

Used by both the standalone ``scripts/p0_preflight.py`` read-only script and by
the server lifespan.  This module does not create or stop services; callers are
responsible for providing a live client, an initialized catalog, a started
bankroll service, and an RTI stream.
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.preflight.p0")


def _check(label: str, ok: bool, detail: str = "") -> Tuple[bool, str]:
    status = "PASS" if ok else "FAIL"
    msg = f"[{status}] {label}"
    if detail:
        msg += f": {detail}"
    logger.info("[P0-PREFLIGHT] %s", msg)
    return ok, msg


async def run_p0_preflight_checks(
    client: Any,
    bankroll: Any,
    catalog: Any,
    rti_adapter: Optional[Dict[str, Any]] = None,
    required_assets: Optional[List[str]] = None,
    max_wait_rti: float = 30.0,
    rti_max_age_ms: int = 2000,
    max_position_cap_usd: Decimal = Decimal("2.00"),
    max_riskable_frac: Decimal = Decimal("0.02"),
) -> List[Tuple[bool, str]]:
    """Run the P0 preflight assertions and return (ok, message) pairs.

    Services must already be initialized before calling this function.  No
    state-machine transitions are performed here.
    """
    from merid.event_venues.kalshi.types import BalanceState
    from merid.event_venues.kalshi.position_cache import get_position_cache
    from merid.event_venues.kalshi.fills_ledger import get_fills_ledger

    results: List[Tuple[bool, str]] = []

    # 1. Client ready.
    results.append(_check("kalshi_client ready", client is not None))

    # 2. Balance and positions.
    try:
        balance = await client.get_balance()
        positions = await client.get_positions()
        results.append(
            _check(
                "kalshi_balance_fetch",
                bool(balance and balance.get("USD") is not None),
                f"USD={balance.get('USD')}" if balance and balance.get("USD") is not None else "",
            )
        )
        results.append(
            _check("kalshi_positions_fetch", positions is not None, f"count={len(positions) if positions else 0}")
        )
    except Exception as e:
        results.append(_check("kalshi_balance_fetch", False, str(e)))
        results.append(_check("kalshi_positions_fetch", False, str(e)))

    # 3. Catalog initialized.
    catalog_detail = ""
    try:
        markets = catalog.get_all_markets() if hasattr(catalog, "get_all_markets") else []
        catalog_detail = f"{len(markets)} markets"
        results.append(_check("market_catalog_initialized", len(markets) > 0, catalog_detail))
    except Exception as e:
        results.append(_check("market_catalog_initialized", False, str(e)))

    # 4. Bankroll service fresh.
    try:
        summary = await bankroll.get_summary(caller_module="p0_preflight")
        bankroll_ok = summary.state == BalanceState.FRESH and summary.equity_usd is not None
        results.append(
            _check(
                "bankroll_service_fresh",
                bankroll_ok,
                f"state={summary.state.name} equity={summary.equity_usd}",
            )
        )
    except Exception as e:
        results.append(_check("bankroll_service_fresh", False, str(e)))

    # 5. Direct exchange reconciliation and cancel-all capability.
    try:
        open_orders = await client.get_open_orders()
        positions = await client.get_positions()
        fills_result = await client.get_fills(limit=20)
        fills = fills_result.unwrap_or([]) if hasattr(fills_result, "unwrap_or") else list(fills_result)

        cache = get_position_cache()
        ledger = get_fills_ledger()

        # Ensure the ledger is loaded from its durable store before comparing.
        if hasattr(ledger, "load_from_db"):
            try:
                await ledger.load_from_db()
            except Exception as load_err:
                logger.warning("[P0-PREFLIGHT] fills_ledger load_from_db failed: %s", load_err)

        # Load the position cache from the exchange so internal state is fresh.
        if hasattr(cache, "load_from_exchange"):
            try:
                await cache.load_from_exchange(client)
            except Exception as load_err:
                logger.warning("[P0-PREFLIGHT] position_cache load_from_exchange failed: %s", load_err)

        internal_positions = list(cache.positions.values()) if hasattr(cache, "positions") else []
        internal_fills = ledger.get_fills() if hasattr(ledger, "get_fills") else []

        recon_detail = (
            f"external_open_orders={len(open_orders)} external_positions={len(positions)} "
            f"external_fills={len(fills)} internal_positions={len(internal_positions)} "
            f"internal_fills={len(internal_fills)}"
        )
        recon_ok = (
            len(positions) == len(internal_positions)
            and len(open_orders) == 0
            and len(fills) == len(internal_fills)
        )
        results.append(_check("exchange_reconciliation", recon_ok, recon_detail))

        cancel_all_result = await client.cancel_all_open_orders(dry_run=True)
        results.append(
            _check(
                "cancel_all_capability",
                cancel_all_result.get("dry_run", False) or cancel_all_result.get("count", 0) == 0,
                f"would_cancel={len(cancel_all_result.get('would_cancel', []))} dry_run={cancel_all_result.get('dry_run')}",
            )
        )
    except Exception as e:
        results.append(_check("exchange_reconciliation", False, str(e)))

    # 6. RTI stream fresh.
    rti_detail = ""
    try:
        if rti_adapter is None:
            from merid.data.cf_rti_adapter import get_live_rti

            rti_adapter = get_live_rti

        assets = required_assets or ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        observations: Dict[str, Any] = {}
        deadline = time.time() + max_wait_rti
        while time.time() < deadline and len(observations) < len(assets):
            for asset in assets:
                if asset not in observations:
                    obs = rti_adapter(asset)
                    if obs is not None:
                        observations[asset] = obs
            await __import__("asyncio").sleep(0.2)

        if observations:
            execution_ok = all(getattr(o, "execution_eligible", False) for o in observations.values())
            ages = [getattr(o, "observed_ts_ms", 0) for o in observations.values()]
            now_ms = int(time.time() * 1000)
            max_age = max((now_ms - a for a in ages if a), default=0)
            rti_ok = execution_ok and max_age <= rti_max_age_ms
            rti_detail = f"assets={len(observations)} max_age_ms={max_age}"
        else:
            rti_detail = "no RTI observations received"
            rti_ok = False
        results.append(_check("rti_stream_fresh", rti_ok, rti_detail))
    except Exception as e:
        results.append(_check("rti_stream_fresh", False, f"{e} {rti_detail}".strip()))

    return results
