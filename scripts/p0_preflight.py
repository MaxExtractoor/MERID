#!/usr/bin/env python3
"""P0 read-only preflight for MERID 15m Kalshi crypto.

This script performs the same startup reconciliation and data-provenance checks
that the server runs, but it never enables live entries and it never submits an
order.  It is intended to be run after the P0 defensive patch to verify that:

- Credentials authenticate against the live Kalshi account.
- The market catalog can be fetched and populated.
- Portfolio reconciliation runs against the live venue.
- The CF-RTI stream connects and produces fresh observations.
- The live runtime state remains ``LIVE_ENTRIES_HALTED``.

It updates ``data/live_runtime_state.json`` with a preflight snapshot id and the
result, but it does **not** transition to ``LIVE_ENTRIES_ENABLED``.

Usage::

    py scripts/p0_preflight.py
    py scripts/p0_preflight.py --max-wait-rti 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Force observe-only for the entire run.
os.environ["MERID_OBSERVE_ONLY"] = "1"

from utils.logger import get_logger

logger = get_logger("scripts.p0_preflight")


def _check(label: str, ok: bool, detail: str = "") -> Tuple[bool, str]:
    status = "PASS" if ok else "FAIL"
    msg = f"[{status}] {label}"
    if detail:
        msg += f": {detail}"
    print(msg)
    logger.info("[P0-PREFLIGHT] %s", msg)
    return ok, msg


async def _run_preflight(args: argparse.Namespace) -> int:
    results: List[Tuple[bool, str]] = []

    # 1. Live runtime state: must be halted at entry.
    from merid.observability.live_runtime_state import get_live_runtime_state

    live_state = get_live_runtime_state()
    print(f"[INFO] live_runtime_state = {live_state.state}")
    results.append(_check("live_runtime_state is halted", not live_state.live_entries_enabled()))

    # 2. Kalshi client and authentication.
    from merid.event_venues.kalshi.client import get_kalshi_client

    client = get_kalshi_client()
    if client is not None:
        print("[INFO] Kalshi client ready")

    # 3. Market catalog: start and set singleton; the shared check will verify it.
    catalog_detail = ""
    try:
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, set_market_catalog

        catalog = KalshiMarketCatalog(client=client, refresh_interval_s=30.0)
        catalog.start()
        catalog._first_refresh_completed.wait(timeout=args.max_wait_catalog)
        markets = catalog.get_all_markets()
        set_market_catalog(catalog)
        catalog_detail = f"{len(markets)} markets"
    except Exception as e:
        results.append(_check("market_catalog_initialized", False, str(e)))

    # 4. Bankroll service.
    try:
        from decimal import Decimal
        from merid.event_venues.kalshi.bankroll_service_v2 import BankrollServiceV2, set_bankroll_service

        bankroll = BankrollServiceV2(
            max_riskable_frac=Decimal("0.02"),
            max_position_cap_usd=Decimal("2.00"),
        )
        set_bankroll_service(bankroll)
        await bankroll.start()
    except Exception as e:
        results.append(_check("bankroll_service_setup", False, str(e)))

    # 5. CF-RTI stream.
    try:
        from merid.data.cf_rti_adapter import start_kalshi_rti_stream

        start_kalshi_rti_stream()
    except Exception as e:
        results.append(_check("rti_stream_start", False, str(e)))

    # 6. Shared P0 checks.
    try:
        from merid.preflight.p0 import run_p0_preflight_checks

        check_results = await run_p0_preflight_checks(
            client=client,
            bankroll=bankroll,
            catalog=catalog,
            max_wait_rti=args.max_wait_rti,
        )
        results.extend(check_results)
    except Exception as e:
        results.append(_check("p0_preflight_checks", False, str(e)))

    # 7. Final state must remain halted.
    results.append(_check("live_runtime_state still halted", not live_state.live_entries_enabled()))

    # 8. Cleanup: stop services started for preflight.
    try:
        if 'bankroll' in locals():
            await bankroll.stop()
    except Exception:
        pass
    try:
        if 'catalog' in locals():
            catalog.stop()
    except Exception:
        pass
    try:
        from merid.data.cf_rti_adapter import stop_kalshi_rti_stream

        stop_kalshi_rti_stream()
    except Exception:
        pass

    # Summarize and persist.
    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    all_pass = passed == total
    snapshot_id = f"p0_preflight_{time.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    preflight_record = {
        "snapshot_id": snapshot_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "all_pass": all_pass,
        "passed": passed,
        "total": total,
        "results": [{"ok": ok, "msg": msg} for ok, msg in results],
        "rti_detail": (
            next((msg.split(": ", 1)[1] for ok, msg in results if "rti_stream_fresh" in msg and ": " in msg), "")
        ),
        "catalog_detail": catalog_detail,
    }

    live_state.halt_entries(
        f"p0_preflight_complete: {passed}/{total} passed",
        ["P0_PREFLIGHT_COMPLETE", "HALTED_BY_OPERATOR"],
    )
    live_state._release_assertion = {  # type: ignore[attr-defined]
        "snapshot_id": snapshot_id,
        "preflight_record": preflight_record,
        "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    live_state._persist()  # type: ignore[attr-defined]

    snapshot_path = Path("data/p0_preflight_snapshots")
    snapshot_path.mkdir(parents=True, exist_ok=True)
    (snapshot_path / f"{snapshot_id}.json").write_text(
        json.dumps(preflight_record, indent=2), encoding="utf-8"
    )

    print("=" * 60)
    for _, msg in results:
        print(msg)
    print("=" * 60)
    if all_pass:
        print(f"P0 PREFLIGHT PASSED: {passed}/{total}")
        print("Live entries remain HALTED. Manual operator release still required.")
        logger.info("[P0-PREFLIGHT] PASSED %d/%d", passed, total)
        return 0
    else:
        print(f"P0 PREFLIGHT FAILED: {passed}/{total} passed")
        logger.warning("[P0-PREFLIGHT] FAILED %d/%d", passed, total)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="P0 read-only preflight")
    parser.add_argument(
        "--max-wait-catalog",
        type=int,
        default=30,
        help="Seconds to wait for the first catalog refresh (default: 30)",
    )
    parser.add_argument(
        "--max-wait-rti",
        type=int,
        default=30,
        help="Seconds to wait for RTI observations (default: 30)",
    )
    args = parser.parse_args()
    return asyncio.run(_run_preflight(args))


if __name__ == "__main__":
    raise SystemExit(main())
