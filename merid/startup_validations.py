"""MERID Startup Validations — Pre-flight checks before live trading.

This module contains runtime validations that must pass before the system
can start in live trading mode. These checks prevent configuration errors
that could bypass safety limits or cause reconciliation failures.

Usage:
    from merid.startup_validations import validate_live_mode_safety
    validate_live_mode_safety()  # Raises StartupValidationError if unsafe
"""

import os
from pathlib import Path
from typing import List, Tuple

from utils.logger import get_logger

logger = get_logger("merid.startup_validations")


class StartupValidationError(Exception):
    """Critical validation failed — cannot start in live mode."""
    pass


def validate_env_for_live_mode() -> None:
    """Validate environment variables are safe for live trading.
    
    Checks:
    - BUG-0324-0002: Smoke test mode must not be enabled with live trading
    - BUG-0324-0005: Promotion grace window must not exceed 60s in live mode
    
    Raises:
        StartupValidationError: If any critical safety check fails
    """
    errors: List[str] = []
    
    # BUG-0324-0002: Smoke test interlock
    smoke_test = os.getenv("KALSHI_TRADER_SMOKE_TEST", "").lower() in ("true", "1", "yes")
    if smoke_test:
        errors.append(
            "KALSHI_TRADER_SMOKE_TEST is set - this bypasses safety limits "
            "(8% edge → 1%, 35¢ max → 99¢, position limits reduced). "
            "Remove this flag before live deployment."
        )
    
    # BUG-0324-0005: Grace window sanity check
    try:
        grace_s = float(os.getenv("MERID_PROMOTION_GRACE_S", "30"))
        if grace_s > 60:
            errors.append(
                f"MERID_PROMOTION_GRACE_S={grace_s}s exceeds 60s maximum for live mode. "
                f"Long grace windows allow unvalidated trading. Set to 30 or less."
            )
    except ValueError:
        errors.append("MERID_PROMOTION_GRACE_S is not a valid number")
    
    # Trading mode consistency check
    pm_mode = os.getenv("MERID_PM_TRADING_MODE", "paper").lower()
    pm_live_enabled = os.getenv("MERID_PM_LIVE_ENABLED", "").lower() in ("true", "1", "yes")
    
    if pm_mode == "live" and not pm_live_enabled:
        errors.append(
            "MERID_PM_TRADING_MODE=live but MERID_PM_LIVE_ENABLED is not true. "
            "This is a safety interlock violation."
        )

    prof = os.getenv("MERID_PM_PROFILE", "development").strip().lower()
    if prof == "production":
        if pm_mode != "live" or not pm_live_enabled:
            errors.append(
                "MERID_PM_PROFILE=production requires MERID_PM_TRADING_MODE=live "
                "and MERID_PM_LIVE_ENABLED=true"
            )
        ws_prod = os.getenv("MERID_KALSHI_WS_CLIENT", "ws").strip().lower()
        if ws_prod != "ws":
            errors.append(
                "MERID_PM_PROFILE=production requires MERID_KALSHI_WS_CLIENT=ws "
                f"(got {ws_prod!r})"
            )
        ct_on = os.getenv("MERID_ENABLE_KALSHI_CT", "false").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if ct_on:
            errors.append(
                "MERID_PM_PROFILE=production is incompatible with MERID_ENABLE_KALSHI_CT=true"
            )

    # Kalshi WS stack: websocket_service trade channel is a stub — live should use ws.py client.
    ws_impl = os.getenv("MERID_KALSHI_WS_CLIENT", "ws").strip().lower()
    if pm_mode == "live" and ws_impl == "websocket_service":
        errors.append(
            "MERID_KALSHI_WS_CLIENT=websocket_service is unsafe for live trading "
            "(trade events are not fully handled). Set MERID_KALSHI_WS_CLIENT=ws."
        )

    # KALSHI_ENV / KALSHI_USE_DEMO consistency guard.
    # KALSHI_USE_DEMO and KALSHI_ENV must agree on live vs demo so the client
    # connects to the right endpoint with the right credentials.
    kalshi_env_raw = os.getenv("KALSHI_ENV", "").strip().lower()
    use_demo_raw = os.getenv("KALSHI_USE_DEMO", "").strip().lower()
    use_demo = use_demo_raw in ("true", "1", "yes")
    if kalshi_env_raw == "live" and use_demo:
        errors.append(
            "KALSHI_ENV=live but KALSHI_USE_DEMO is truthy — these are contradictory. "
            "Set KALSHI_USE_DEMO=false when KALSHI_ENV=live."
        )
    if kalshi_env_raw == "demo" and use_demo_raw in ("false", "0", "no"):
        # Non-fatal but noteworthy: KALSHI_ENV=demo + KALSHI_USE_DEMO=false is unusual.
        # Log a warning, do not block, to avoid false-positive on partial env setups.
        logger.warning(
            "KALSHI_ENV=demo but KALSHI_USE_DEMO=false — unusual combination. "
            "Verify both vars are intentional (demo client will be used regardless)."
        )

    # Live RSA credential presence check.
    # When KALSHI_ENV=live, at least one live API key must be configured or startup
    # will fail at the first authenticated Kalshi REST call (silent runtime failure).
    if kalshi_env_raw == "live":
        has_live_key = bool(
            os.getenv("KALSHI_LIVE_API_KEY_ID")
            or os.getenv("KALSHI_API_KEY_ID")
        )
        has_live_pem = bool(
            os.getenv("KALSHI_LIVE_PRIVATE_KEY_PATH")
            or os.getenv("KALSHI_PRIVATE_KEY_PATH")
            or os.getenv("KALSHI_LIVE_PRIVATE_KEY_PEM")
            or os.getenv("KALSHI_PRIVATE_KEY_PEM")
        )
        if not has_live_key:
            errors.append(
                "KALSHI_ENV=live but no Kalshi API key ID is set. "
                "Set KALSHI_LIVE_API_KEY_ID (preferred) or KALSHI_API_KEY_ID."
            )
        if not has_live_pem:
            errors.append(
                "KALSHI_ENV=live but no Kalshi RSA private key is configured. "
                "Set KALSHI_LIVE_PRIVATE_KEY_PATH (preferred) or KALSHI_PRIVATE_KEY_PATH."
            )

    # KalshiContinuousTrader: legacy runner; live execution is AgentGrid PM. CT live orders
    # require research flag when PM is live (see merid.prediction.pm_ct_policy).
    kalshi_env = os.getenv("KALSHI_ENV", "demo").lower()
    if kalshi_env == "live":
        bypass = os.getenv("KALSHI_CT_BYPASS_PM_LIVE_GATE", "").lower() in ("true", "1", "yes")
        ct_research = os.getenv("MERID_CT_RESEARCH_ALLOW_LOOP", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if pm_mode == "live" and pm_live_enabled and not ct_research:
            logger.info(
                "KALSHI_ENV=live with AgentGrid PM live: KalshiContinuousTrader is suppressed "
                "unless MERID_CT_RESEARCH_ALLOW_LOOP=true ([CT-LEGACY] research only)."
            )
        elif (pm_mode != "live" or not pm_live_enabled) and not bypass:
            logger.warning(
                "KALSHI_ENV=live but portfolio mode is not fully live "
                "(MERID_PM_TRADING_MODE=%r, MERID_PM_LIVE_ENABLED=%s). "
                "[CT-LEGACY] KalshiContinuousTrader will skip live entry orders unless you enable PM live "
                "or set KALSHI_CT_BYPASS_PM_LIVE_GATE=true.",
                pm_mode,
                pm_live_enabled,
            )

    if errors:
        raise StartupValidationError(
            f"LIVE MODE STARTUP BLOCKED ({len(errors)} violations):\n  - " +
            "\n  - ".join(errors)
        )


def log_kalshi_credential_summary() -> None:
    """Emit which Kalshi credential pattern is active (no key material)."""
    kalshi_env = os.getenv("KALSHI_ENV", "").strip().lower() or "(unset)"
    live_id = bool(os.getenv("KALSHI_LIVE_API_KEY_ID"))
    demo_id = bool(os.getenv("KALSHI_DEMO_API_KEY_ID"))
    path_live = os.getenv("KALSHI_LIVE_PRIVATE_KEY_PATH")
    path_demo = os.getenv("KALSHI_DEMO_PRIVATE_KEY_PATH")
    path_legacy = os.getenv("KALSHI_PRIVATE_KEY_PATH")

    if kalshi_env == "live":
        pattern = (
            "KALSHI_LIVE_*"
            if live_id or path_live
            else "legacy KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_*"
        )
        key_path = path_live or path_legacy or ""
    elif kalshi_env == "demo":
        pattern = "KALSHI_DEMO_*" if demo_id or path_demo else "legacy"
        key_path = path_demo or path_legacy or ""
    else:
        pattern = "mixed/legacy"
        key_path = path_legacy or path_live or path_demo or ""

    exists = None
    if key_path:
        try:
            exists = Path(key_path).expanduser().is_file()
        except OSError:
            exists = False

    logger.info(
        "Kalshi credentials: KALSHI_ENV=%s pattern=%s private_key_path=%r file_exists=%s",
        kalshi_env,
        pattern,
        key_path or "(none)",
        exists,
    )


def validate_paper_engine_identity() -> Tuple[bool, str]:
    """Validate paper engine balance identity holds.
    
    The invariant is: cash + margin_locked + total_fees = starting_balance + realized_pnl
    
    Returns:
        Tuple of (is_valid, message)
    """
    try:
        from trading.paper_trading import get_paper_engine
        
        engine = get_paper_engine()
        violations = []
        
        for uid, portfolio in engine.portfolios.items():
            margin_locked = sum(
                p.size_usd / max(p.leverage, 1) 
                for p in portfolio.positions.values()
            )
            realized = sum(
                getattr(cp, "realized_pnl", 0.0) 
                for cp in portfolio.closed_positions
            )
            expected_cash = (
                portfolio.starting_balance + 
                realized - 
                margin_locked - 
                portfolio.total_fees
            )
            
            tolerance = 0.01
            if abs(portfolio.current_balance - expected_cash) > tolerance:
                violations.append(
                    f"Portfolio {uid}: cash {portfolio.current_balance:.4f} != "
                    f"expected {expected_cash:.4f} (margin={margin_locked:.4f}, "
                    f"fees={portfolio.total_fees:.4f}, realized={realized:.4f})"
                )
        
        if violations:
            return False, "Balance identity violated:\n  - " + "\n  - ".join(violations)
        
        return True, f"OK ({len(engine.portfolios)} portfolios checked)"
        
    except Exception as e:
        return False, f"Failed to validate paper engine: {e}"


def validate_all() -> None:
    """Run all startup validations.
    
    This is the main entry point called from web/main.py lifespan.
    
    Raises:
        StartupValidationError: If any validation fails
    """
    log_kalshi_credential_summary()
    # Always validate environment (catches smoke test in any mode)
    validate_env_for_live_mode()
    
    # Validate paper engine integrity (only if paper engine is enabled)
    ok, msg = validate_paper_engine_identity()
    if not ok:
        # Log warning but don't block — paper engine can be repaired on load
        import logging
        logging.getLogger("merid.startup").warning(f"Paper engine needs repair: {msg}")
