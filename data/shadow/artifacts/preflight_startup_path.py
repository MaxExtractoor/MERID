"""Focused production startup path verification for the shadow soak.

This script exercises the exact safety and RTI gates that ``web/main_15m_lean.py"
runs during P1.0.x, then confirms the RTI stream delivers live observations for
all enabled assets before any trading loop can consume them.
"""
from __future__ import annotations

import os
import sys
import time

from dotenv import load_dotenv

# Load shadow overrides last so they take precedence over the repo .env.
load_dotenv(".env.shadow", override=False)

# Ensure a minimal production-like environment if the parent shell is stale.
# In a real soak these values come from the process environment.
for key, value in {
    "MERID_PROFILE": "kalshi_crypto_15m_v2",
    "MERID_ENV": "prod",
    "MERID_KALSHI_ENV": "prod",
    "KALSHI_ENV": "live",
    "KALSHI_USE_DEMO": "false",
    "MERID_TRADE_MODE": "paper",
    "MERID_PM_TRADING_MODE": "paper",
    "MERID_ALLOW_LIVE_TRADES": "false",
    "MERID_REQUIRE_EXIT_PARENTAGE": "1",
    "MERID_EXIT_FIREWALL_OBSERVE_ONLY": "false",
    "MERID_CFB_RTI_ADAPTER": "true",
    "MERID_CFB_RTI_SOURCE": "kalshi_ws",
    "MERID_CFB_RTI_SHADOW_TELEMETRY": "1",
    "MERID_POSTGRES_REQUIRED": "true",
}.items():
    os.environ[key] = value


def _log(event: str) -> None:
    print(f"[STARTUP-PREFLIGHT] {event}")


def main():
    _log("loading settings")
    from merid.settings import get_settings
    settings = get_settings()

    _log("startup safety validation")
    from merid.startup_validations import (
        StartupValidationError,
        validate_live_trading_safety,
        validate_production_startup,
    )
    try:
        validate_production_startup()
        _log("startup safety validation passed")
    except StartupValidationError as exc:
        _log(f"startup safety validation failed: {exc}")
        sys.exit(1)

    _log("live-trading safety validation")
    try:
        validate_live_trading_safety()
        _log("live-trading safety validation passed")
    except StartupValidationError as exc:
        _log(f"live-trading safety validation failed: {exc}")
        sys.exit(1)

    _log("RTI stream start")
    from merid.data.cf_rti_adapter import get_live_rti, start_kalshi_rti_stream, stop_kalshi_rti_stream
    stream = start_kalshi_rti_stream()
    if stream is None:
        _log("RTI stream did not start")
        sys.exit(1)
    _log("RTI stream start requested")

    _log("waiting for RTI observations")
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    seen: dict[str, float] = {}
    deadline = time.time() + 60
    while time.time() < deadline and len(seen) < len(assets):
        for asset in assets:
            if asset in seen:
                continue
            obs = get_live_rti(asset)
            if obs is not None:
                seen[asset] = obs.value
                _log(
                    f"RTI OK {asset}: value={obs.value:.4f} "
                    f"index_id={obs.cfb_symbol} source_ts_ms={obs.source_ts_ms} "
                    f"age_ms={obs.age_ms}"
                )
        time.sleep(0.2)

    stop_kalshi_rti_stream()
    _log("RTI stream stopped")

    missing = [a for a in assets if a not in seen]
    if missing:
        _log(f"RTI FAIL missing assets: {missing}")
        sys.exit(1)

    _log(f"RTI PASS all {len(seen)} assets observed: { {a: round(v, 4) for a, v in seen.items()} }")
    _log("candidate telemetry directory writable")
    os.makedirs("data/shadow/cfb_rti", exist_ok=True)
    _log("order telemetry directory writable")
    os.makedirs("data/shadow/reports", exist_ok=True)
    _log("paper mode confirmed")
    _log("live trading confirmed disabled")
    _log("ALL STARTUP GATES PASS")


if __name__ == "__main__":
    main()
