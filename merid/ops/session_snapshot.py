"""
Session Snapshot Logger

Captures pre-run and post-run snapshots of critical trading state for
operational monitoring and live-run reporting.

This module provides functions to log structured snapshots of:
- Bankroll and equity
- Kelly fraction and risk parameters
- Drawdown metrics
- Per-asset exposure
- Open positions and pending orders
- System health indicators

Snapshots are logged in JSON format for easy parsing and are stored
with timestamps for time-series analysis.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from decimal import Decimal

logger = logging.getLogger(__name__)


def capture_session_snapshot(
    run_id: str,
    phase: str,  # "pre_run" or "post_run"
    bankroll_usd: Optional[float] = None,
    kelly_fraction: Optional[float] = None,
    max_drawdown_pct: Optional[float] = None,
    asset_exposure: Optional[Dict[str, Dict[str, float]]] = None,
    open_positions: Optional[int] = None,
    pending_orders: Optional[int] = None,
    additional_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Capture a structured snapshot of session state.

    Args:
        run_id: Unique identifier for the trading session
        phase: "pre_run" or "post_run"
        bankroll_usd: Current bankroll in USD
        kelly_fraction: Current Kelly fraction
        max_drawdown_pct: Maximum drawdown percentage
        asset_exposure: Dict of asset exposure data
            {"BTC": {"exposure_usd": 100.0, "exposure_pct": 0.5}, ...}
        open_positions: Number of open positions
        pending_orders: Number of pending orders
        additional_metrics: Any additional metrics to include

    Returns:
        Dict containing the snapshot data
    """
    snapshot = {
        "run_id": run_id,
        "phase": phase,
        "timestamp": datetime.utcnow().isoformat(),
        "bankroll_usd": bankroll_usd,
        "kelly_fraction": kelly_fraction,
        "max_drawdown_pct": max_drawdown_pct,
        "asset_exposure": asset_exposure or {},
        "open_positions": open_positions,
        "pending_orders": pending_orders,
        "additional_metrics": additional_metrics or {},
    }

    # Log the snapshot
    logger.info(
        "[SESSION-SNAPSHOT] phase=%s | run_id=%s | bankroll=%.2f | kelly=%.3f | "
        "drawdown=%.2f%% | positions=%d | pending=%d | assets=%d",
        phase,
        run_id,
        bankroll_usd or 0.0,
        kelly_fraction or 0.0,
        max_drawdown_pct or 0.0,
        open_positions or 0,
        pending_orders or 0,
        len(asset_exposure or {}),
    )

    # Also log as JSON for structured parsing
    logger.debug("[SESSION-SNAPSHOT-JSON] %s", json.dumps(snapshot, indent=2))

    return snapshot


def capture_pre_run_snapshot(
    run_id: str,
    bankroll_service=None,
    position_cache=None,
    risk_manager=None,
) -> Dict[str, Any]:
    """
    Capture pre-run snapshot by querying live services.

    Args:
        run_id: Unique identifier for the trading session
        bankroll_service: Bankroll service instance (optional)
        position_cache: Position cache instance (optional)
        risk_manager: Risk manager instance (optional)

    Returns:
        Dict containing the pre-run snapshot data
    """
    bankroll_usd = None
    kelly_fraction = None
    max_drawdown_pct = None
    asset_exposure = {}
    open_positions = 0
    pending_orders = 0

    # Try to get bankroll from service
    if bankroll_service:
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            bankroll_usd = get_equity_for_risk_calc_sync()
        except Exception as e:
            logger.warning("[SESSION-SNAPSHOT] Failed to get bankroll: %s", e)

    # Try to get exposure from position cache
    if position_cache:
        try:
            # Get per-asset exposure
            assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
            for asset in assets:
                exposure = position_cache.get_asset_exposure(asset)
                if exposure:
                    asset_exposure[asset] = {
                        "exposure_usd": float(exposure.get("exposure_usd", 0)),
                        "exposure_pct": float(exposure.get("exposure_pct", 0)),
                    }
            open_positions = len(position_cache.get_all_positions())
        except Exception as e:
            logger.warning("[SESSION-SNAPSHOT] Failed to get exposure: %s", e)
            open_positions = 0

    # Try to get risk parameters from risk manager
    if risk_manager:
        try:
            risk_config = risk_manager._config
            if risk_config:
                kelly_fraction = float(risk_config.kelly_fraction) if hasattr(risk_config, 'kelly_fraction') else None
        except Exception as e:
            logger.warning("[SESSION-SNAPSHOT] Failed to get risk config: %s", e)

    return capture_session_snapshot(
        run_id=run_id,
        phase="pre_run",
        bankroll_usd=bankroll_usd,
        kelly_fraction=kelly_fraction,
        max_drawdown_pct=max_drawdown_pct,
        asset_exposure=asset_exposure,
        open_positions=open_positions,
        pending_orders=pending_orders,
    )


def capture_post_run_snapshot(
    run_id: str,
    pre_run_snapshot: Dict[str, Any],
    bankroll_service=None,
    position_cache=None,
    risk_manager=None,
) -> Dict[str, Any]:
    """
    Capture post-run snapshot and compute deltas from pre-run.

    Args:
        run_id: Unique identifier for the trading session
        pre_run_snapshot: Pre-run snapshot for delta computation
        bankroll_service: Bankroll service instance (optional)
        position_cache: Position cache instance (optional)
        risk_manager: Risk manager instance (optional)

    Returns:
        Dict containing the post-run snapshot data with deltas
    """
    snapshot = capture_pre_run_snapshot(
        run_id=run_id,
        bankroll_service=bankroll_service,
        position_cache=position_cache,
        risk_manager=risk_manager,
    )
    snapshot["phase"] = "post_run"

    # Compute deltas
    pre_bankroll = pre_run_snapshot.get("bankroll_usd") or 0.0
    post_bankroll = snapshot.get("bankroll_usd") or 0.0
    bankroll_delta = post_bankroll - pre_bankroll

    pre_exposure = pre_run_snapshot.get("asset_exposure", {})
    post_exposure = snapshot.get("asset_exposure", {})

    exposure_deltas = {}
    for asset in set(list(pre_exposure.keys()) + list(post_exposure.keys())):
        pre_exp = pre_exposure.get(asset, {}).get("exposure_usd", 0)
        post_exp = post_exposure.get(asset, {}).get("exposure_usd", 0)
        exposure_deltas[asset] = post_exp - pre_exp

    snapshot["deltas"] = {
        "bankroll_usd": bankroll_delta,
        "asset_exposure_usd": exposure_deltas,
    }

    logger.info(
        "[SESSION-SNAPSHOT-DELTA] run_id=%s | bankroll_delta=%.2f | "
        "asset_deltas=%s",
        run_id,
        bankroll_delta,
        json.dumps(exposure_deltas),
    )

    # Add fill statistics from order lifecycle tracker
    try:
        from merid.ops.order_lifecycle_tracker import get_order_lifecycle_tracker
        tracker = get_order_lifecycle_tracker()
        fill_stats = tracker.get_fill_statistics()
        snapshot["fill_statistics"] = fill_stats
        logger.info(
            "[SESSION-SNAPSHOT-FILL] run_id=%s | fill_rate=%.2f%% | avg_time_on_book=%.2fs",
            run_id,
            fill_stats.get("total", {}).get("fill_rate_pct", 0),
            fill_stats.get("total", {}).get("avg_time_on_book_seconds", 0),
        )
    except Exception as e:
        logger.warning("[SESSION-SNAPSHOT] Failed to get fill statistics: %s", e)
        snapshot["fill_statistics"] = None

    # Add profile version for reproducibility
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        profile = get_active_profile()
        snapshot["profile_version"] = profile.profile_version
        snapshot["profile_name"] = profile.profile_name
        logger.info(
            "[SESSION-SNAPSHOT-PROFILE] run_id=%s | profile_name=%s | profile_version=%s",
            run_id,
            profile.profile_name,
            profile.profile_version,
        )
    except Exception as e:
        logger.warning("[SESSION-SNAPSHOT] Failed to get profile version: %s", e)
        snapshot["profile_version"] = None
        snapshot["profile_name"] = None

    # Add execution mode for run documentation
    try:
        from merid.settings import get_settings
        settings = get_settings()
        snapshot["execution_mode"] = settings.MERID_EXECUTION_MODE
        logger.info(
            "[SESSION-SNAPSHOT-EXECUTION] run_id=%s | execution_mode=%s",
            run_id,
            settings.MERID_EXECUTION_MODE,
        )
    except Exception as e:
        logger.warning("[SESSION-SNAPSHOT] Failed to get execution mode: %s", e)
        snapshot["execution_mode"] = None

    return snapshot


def generate_run_id() -> str:
    """
    Generate a unique run ID for the session.

    Returns:
        UUID string for the run
    """
    import uuid
    return str(uuid.uuid4())


def save_snapshot_to_file(snapshot: Dict[str, Any], output_dir: str = "data/session_snapshots") -> str:
    """
    Save snapshot to a JSON file for persistence.

    Args:
        snapshot: Snapshot data to save
        output_dir: Directory to save snapshots in

    Returns:
        Path to the saved file
    """
    import os
    from pathlib import Path

    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Generate filename
    run_id = snapshot.get("run_id", "unknown")
    phase = snapshot.get("phase", "unknown")
    timestamp = snapshot.get("timestamp", datetime.utcnow().isoformat())
    filename = f"{run_id}_{phase}_{timestamp.replace(':', '-')}.json"
    filepath = os.path.join(output_dir, filename)

    # Write snapshot
    with open(filepath, "w") as f:
        json.dump(snapshot, f, indent=2)

    logger.info("[SESSION-SNAPSHOT] Saved snapshot to %s", filepath)
    return filepath
