"""
Determinism replay — run the production binary from an ingress tape.

This is the Phase 2 runtime mode.  It does not simulate anything; it swaps the
four ingress points (Kalshi WS, Kalshi REST, CF Benchmarks RTI WS, CF
Benchmarks RTI REST) to read from a captured JSON-line tape.  The rest of the
production stack — parser, book builder, strategy, risk, router — runs
unchanged, and wall-clock / random calls are seeded from the tape.

Usage:
    python -m merid.tools.determinism_replay --replay-tape data/ingress/20260827
    python -m merid.tools.determinism_replay --replay-tape data/ingress/20260827 --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from merid.data.ingress_replay import get_replay_dispatcher
from merid.data.replay_config_snapshot import apply_snapshot
from utils.logger import get_logger

logger = get_logger("merid.tools.determinism_replay")


def _fail_if_live_latches() -> None:
    """Make sure this runtime is not accidentally allowed to trade."""
    live_latches = [
        os.getenv("TRADING_ENABLED", "").lower() in ("1", "true"),
        os.getenv("MERID_PM_LIVE_ENABLED", "").lower() in ("1", "true"),
        os.getenv("MERID_ALLOW_LIVE_TRADES", "").lower() in ("1", "true"),
        os.getenv("MERID_PM_TRADING_MODE", "").lower() == "live",
    ]
    if any(live_latches):
        logger.critical(
            "[REPLAY-SECURITY] Replay cannot be combined with live trading latches. "
            "Set MERID_ALLOW_LIVE_TRADES=false, MERID_PM_TRADING_MODE=dry_run."
        )
        sys.exit(1)


def configure_replay_environment(tape_dir: Path) -> None:
    """Set the environment variables needed to run the binary in replay mode."""
    # Set safety latches first so apply_snapshot cannot overwrite them.
    protected = {
        "MERID_REPLAY_TAPE",
        "MERID_INGRESS_RECORDING",
        "TRADING_ENABLED",
        "MERID_PM_LIVE_ENABLED",
        "MERID_ALLOW_LIVE_TRADES",
        "MERID_EXECUTION_MODE",
        "MERID_LOOP_DRY_RUN",
        "MERID_ALLOW_CT_SCRIPT_BYPASS",
        "MERID_REQUIRE_EXIT_PARENTAGE",
        "MERID_EXIT_FIREWALL_OBSERVE_ONLY",
        "MERID_CIRCUIT_BREAKER_DISABLED",
        "MERID_PM_TRADING_MODE",
    }
    os.environ["MERID_REPLAY_TAPE"] = str(tape_dir.resolve())
    os.environ["MERID_INGRESS_RECORDING"] = "false"
    os.environ["TRADING_ENABLED"] = "false"
    os.environ["MERID_PM_LIVE_ENABLED"] = "false"
    os.environ["MERID_ALLOW_LIVE_TRADES"] = "false"
    os.environ["MERID_EXECUTION_MODE"] = "dry_run"
    os.environ["MERID_LOOP_DRY_RUN"] = "true"
    os.environ["MERID_ALLOW_CT_SCRIPT_BYPASS"] = "false"
    os.environ["MERID_REQUIRE_EXIT_PARENTAGE"] = "1"
    os.environ["MERID_EXIT_FIREWALL_OBSERVE_ONLY"] = "true"
    os.environ["MERID_CIRCUIT_BREAKER_DISABLED"] = "false"
    # Make sure the production startup guard does not see this as live.
    if os.getenv("MERID_PM_TRADING_MODE", "").lower() == "live":
        os.environ["MERID_PM_TRADING_MODE"] = "dry_run"

    # Pin the captured config/reference data so it is replayed verbatim.
    apply_snapshot(tape_dir, protected_keys=protected)


def replay_bundle(
    tape_dir: Path,
    host: str = "0.0.0.0",
    port: int = 8000,
    one_shot: bool = False,
    smoke: bool = False,
) -> None:
    """Run the production binary from the captured ingress tape.

    This sets replay env, pre-loads the dispatcher, and starts the FastAPI
    application via uvicorn.  In one-shot mode, the process exits after the
    dispatcher reports the tape is exhausted (the WS/RTI loops stop themselves).
    In smoke mode, the dispatcher is loaded and validated but the server is not
    started; useful for CI and for verifying a tape without running the app.
    """
    if not tape_dir.exists() or not tape_dir.is_dir():
        logger.error("[REPLAY] Tape directory does not exist: %s", tape_dir)
        sys.exit(1)

    configure_replay_environment(tape_dir)
    _fail_if_live_latches()

    # Pre-load the dispatcher so the heavy file scan happens once at startup,
    # not on the first ingress read.
    dispatcher = get_replay_dispatcher()
    if dispatcher is None:
        logger.error("[REPLAY] Failed to load replay dispatcher for %s", tape_dir)
        sys.exit(1)

    logger.info(
        "[REPLAY] bundle tape_dir=%s records=%d active=%s one_shot=%s smoke=%s",
        tape_dir,
        len(dispatcher._records),
        sorted(dispatcher._active_sources),
        one_shot,
        smoke,
    )

    if smoke:
        logger.info("[REPLAY-SMOKE] dispatcher validated; smoke mode exits without starting server")
        return

    try:
        import uvicorn
    except ImportError as exc:
        logger.error("[REPLAY] uvicorn is required to run the production binary: %s", exc)
        sys.exit(1)

    if one_shot:
        # Start a watcher that exits the process once the tape is consumed.
        # This is a best-effort background task: the replay loops themselves
        # already stop on ReplayExhausted; this task catches any tail.
        _start_one_shot_watcher()

    uvicorn.run(
        "web.main_15m_lean:app",
        host=host,
        port=port,
        lifespan="on",
    )


def _start_one_shot_watcher() -> None:
    """Attach a background task that exits the process when the tape ends."""
    import asyncio
    import threading

    async def _watcher() -> None:
        while True:
            await asyncio.sleep(1.0)
            dispatcher = get_replay_dispatcher()
            if dispatcher is None:
                continue
            # If every active source has seen the end of the tape, we are done.
            if dispatcher._next_index >= len(dispatcher._records):
                logger.info("[REPLAY-ONE-SHOT] tape exhausted, exiting")
                os._exit(0)

    def _run_watcher() -> None:
        try:
            asyncio.new_event_loop().run_until_complete(_watcher())
        except Exception as exc:
            logger.warning("[REPLAY-ONE-SHOT] watcher error: %s", exc)

    watcher_thread = threading.Thread(target=_run_watcher, daemon=True)
    watcher_thread.start()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic replay of a captured ingress tape through the production binary."
    )
    parser.add_argument(
        "--replay-tape",
        type=Path,
        required=True,
        help="Path to an ingress JSON-line tape directory captured by the ingress recorder.",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind the replayed production server on (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the replayed production server on (default: 8000).",
    )
    parser.add_argument(
        "--one-shot",
        action="store_true",
        help="Exit the process once the tape is exhausted.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Load the dispatcher and exit without starting the server; for CI tape validation.",
    )
    parser.add_argument(
        "--active-sources",
        type=str,
        default=None,
        help="Comma-separated source IDs to replay (default: all sources in the tape).",
    )
    args = parser.parse_args()

    if args.active_sources:
        os.environ["MERID_REPLAY_ACTIVE_SOURCES"] = args.active_sources

    replay_bundle(
        tape_dir=args.replay_tape,
        host=args.host,
        port=args.port,
        one_shot=args.one_shot,
        smoke=args.smoke,
    )


if __name__ == "__main__":
    main()
