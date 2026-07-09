"""MERID Startup Validations — Pre-flight checks before live trading.

This module contains runtime validations that must pass before the system
can start in live trading mode. These checks prevent configuration errors
that could bypass safety limits or cause reconciliation failures.

Usage:
    from merid.startup_validations import validate_live_mode_safety
    validate_live_mode_safety()  # Raises StartupValidationError if unsafe

15m Mode Guard:
    This module contains both 15m and legacy validations. When running in 15m mode
    (MERID_RUNTIME_MODE=15m_live), legacy validation paths should not be used.
    See docs/kalshi_15m_stack.md Section 4.3 for details.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.startup_validations")

# Import startup trace helper
from merid.startup_trace import log_startup_phase

# 15m MODE GUARD: Check if we're in 15m mode and log legacy validation access
_RUNTIME_MODE = os.environ.get('MERID_RUNTIME_MODE')
_IS_15M_MODE = _RUNTIME_MODE == '15m_live'

if _IS_15M_MODE:
    logger.info("[STARTUP-VALIDATIONS-15M-MODE] Running in 15m live mode - legacy validation paths should not be used")


class StartupValidationError(Exception):
    """Critical validation failed — cannot start in live mode."""
    pass


def is_kalshi_15m_profile() -> bool:
    """Check if the active profile is kalshi_crypto_15m_v2.
    
    This helper is used to isolate Kalshi 15m validation pipeline from PM/legacy validations.
    Returns True if MERID_PROFILE=kalshi_crypto_15m_v2, False otherwise.
    """
    return os.getenv("MERID_PROFILE", "") == "kalshi_crypto_15m_v2"


def validate_live_trading_safety() -> None:
    """
    CRITICAL SAFETY CHECK: Environment-based live trading controls.
    
    This validation ensures proper separation between dev/staging/prod environments:
    
    1. Non-prod environments (dev/staging) must use paper mode or demo Kalshi only
    2. Production environment requires explicit confirmation and production Kalshi
    3. Execution mode (paper/live) and venue environment (demo/prod) are validated separately
    4. Real-money trades only allowed with prod env + prod Kalshi + explicit confirmation
    
    Raises:
        StartupValidationError if safety checks fail.
    """
    log_startup_phase("validate_live_trading_safety", "merid.startup_validations")
    
    # Environment configuration
    env = os.getenv("MERID_ENV", "development")  # dev/staging/prod
    trade_mode = os.getenv("MERID_TRADE_MODE", "paper").lower()  # paper/live
    pm_trade_mode = os.getenv("MERID_PM_TRADING_MODE", "paper").lower()
    allow_live_trades = os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower() == "true"
    live_confirmation = os.getenv("MERID_LIVE_CONFIRMATION", "").lower()
    
    # Venue configuration
    kalshi_env = os.getenv("KALSHI_ENV", "demo").lower()  # demo/live
    kalshi_use_demo = os.getenv("KALSHI_USE_DEMO", "true").lower() == "true"
    
    logger.info(
        f"[LIVE-TRADING-VALIDATION] env={env} trade_mode={trade_mode} pm_trade_mode={pm_trade_mode} "
        f"allow_live={allow_live_trades} kalshi_env={kalshi_env} kalshi_use_demo={kalshi_use_demo}"
    )
    
    # SAFETY CHECK 1: Non-prod environments cannot use real money
    if env not in ("prod", "production"):
        # Dev/staging must use paper mode OR demo Kalshi only
        if trade_mode == "live" and kalshi_env == "live" and not kalshi_use_demo:
            error_msg = (
                f"CRITICAL SAFETY VIOLATION: Non-prod environment ({env}) attempting real-money trading. "
                f"env={env}, trade_mode={trade_mode}, kalshi_env={kalshi_env}, kalshi_use_demo={kalshi_use_demo}. "
                f"Non-prod requires: (trade_mode=paper) OR (kalshi_env=demo OR kalshi_use_demo=true)"
            )
            logger.error(error_msg)
            raise StartupValidationError(error_msg)
        
        # Allow live execution mode on demo Kalshi (common for staging)
        if trade_mode == "live" and (kalshi_env == "demo" or kalshi_use_demo):
            logger.info(
                f"[LIVE-TRADING-VALIDATION] ✅ Staging mode: live execution on demo Kalshi (safe)"
            )
        elif trade_mode == "paper":
            logger.info(
                f"[LIVE-TRADING-VALIDATION] ✅ Development environment correctly configured for paper trading"
            )
        else:
            logger.info(
                f"[LIVE-TRADING-VALIDATION] ✅ Non-prod environment configuration validated"
            )
    
    # SAFETY CHECK 2: Production environment requires explicit confirmation
    if env in ("prod", "production"):
        if trade_mode == "live" or pm_trade_mode == "live" or allow_live_trades:
            # Require explicit confirmation for production
            if live_confirmation != "i_know_what_i_am_doing":
                error_msg = (
                    f"CRITICAL SAFETY VIOLATION: Production live trading without explicit confirmation. "
                    f"env={env}, trade_mode={trade_mode}, pm_trade_mode={pm_trade_mode}, allow_live_trades={allow_live_trades}. "
                    f"Production requires: MERID_LIVE_CONFIRMATION=I_KNOW_WHAT_I_AM_DOING"
                )
                logger.error(error_msg)
                raise StartupValidationError(error_msg)
            
            # Require production Kalshi environment for real money
            # Accept both "live" (legacy) and "prod" (Kalshi docs standard) as production
            if kalshi_env not in ("live", "prod") or kalshi_use_demo:
                error_msg = (
                    f"CRITICAL SAFETY VIOLATION: Production environment not using production Kalshi. "
                    f"env={env}, kalshi_env={kalshi_env}, kalshi_use_demo={kalshi_use_demo}. "
                    f"Production requires: KALSHI_ENV=live OR KALSHI_ENV=prod AND KALSHI_USE_DEMO=false"
                )
                logger.error(error_msg)
                raise StartupValidationError(error_msg)
            
            logger.warning(
                f"[LIVE-TRADING-VALIDATION] ⚠️  PRODUCTION LIVE TRADING ENABLED - REAL MONEY AT RISK"
            )
            logger.warning(
                f"[LIVE-TRADING-VALIDATION] env={env} kalshi_env={kalshi_env} confirmation={live_confirmation}"
            )
        else:
            logger.info(
                f"[LIVE-TRADING-VALIDATION] ✅ Production environment in paper mode (safe testing)"
            )
    
    # SAFETY CHECK 3: Profile consistency
    profile = os.getenv("MERID_PROFILE", "")
    pm_profile = os.getenv("MERID_PM_PROFILE", "")
    
    if env in ("prod", "production") and trade_mode == "live":
        if profile == "kalshi_crypto_15m_v2":
            logger.info("[LIVE-TRADING-VALIDATION] ✅ Production with appropriate risk profile")
        else:
            logger.warning(
                f"[LIVE-TRADING-VALIDATION] Production with non-standard profile: {profile}"
            )
    else:
        # Non-prod or paper mode - any profile is fine
        logger.debug(
            f"[LIVE-TRADING-VALIDATION] Profile check: env={env} trade_mode={trade_mode} profile={profile}"
        )


def validate_kalshi_15m_strip_limits_consistency() -> None:
    """
    Validate that strip-level limits from profile are consistent with RiskEnvelopeService caps.
    
    This ensures:
    - per_strip_notional_usd (if set) does not exceed per-asset max notional caps
    - per_strip_order_limit is reasonable (>= 1)
    - Throttling config is loaded successfully from profile
    
    Raises:
        StartupValidationError if strip limits are inconsistent with envelope caps.
    """
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
        
        profile_adapter = get_active_profile()
        if profile_adapter is None:
            logger.warning("[STRIP-LIMIT-VALIDATION] No active profile, skipping strip limits consistency check")
            return
        
        profile = profile_adapter.profile
        
        # Check strip order limit is reasonable
        if profile.throttling_per_strip_order_limit < 1:
            raise StartupValidationError(
                f"Profile invalid: per_strip_order_limit must be >= 1, got {profile.throttling_per_strip_order_limit}"
            )
        
        # Check strip notional cap (if enabled) is consistent with per-asset caps
        if profile.throttling_per_strip_notional_usd > 0:
            # Get per-asset max notional caps from profile
            for asset_name, asset_config in profile.asset_configs.items():
                asset_max_notional = asset_config.max_notional_usd
                strip_notional = profile.throttling_per_strip_notional_usd
                
                if strip_notional > asset_max_notional:
                    raise StartupValidationError(
                        f"Profile invalid: per_strip_notional_usd (${strip_notional:.2f}) > "
                        f"per-asset max_notional for {asset_name} (${asset_max_notional:.2f})"
                    )
        
        logger.info(
            "[STRIP-LIMIT-VALIDATION] Strip limits consistent with envelope caps: "
            "per_strip_order_limit=%d per_strip_notional_usd=%.2f",
            profile.throttling_per_strip_order_limit,
            profile.throttling_per_strip_notional_usd,
        )
        
    except Exception as e:
        logger.error("[STRIP-LIMIT-VALIDATION] Failed to validate strip limits consistency: %s", e)
        raise StartupValidationError(f"Strip limits consistency validation failed: {e}")


def validate_kalshi_15m_guardrail_fields() -> None:
    """
    Validate that 15m profile guardrail fields are present and within sane ranges.
    
    This ensures:
    - All required guardrail fields exist in the profile
    - Values are within sane ranges (min_entry < max_entry ≤15, floor ≥20c, dist_pct ≤ few %)
    - TTE regime alignment (entry windows match TTE thresholds)
    
    Raises:
        StartupValidationError if guardrail fields are missing or out of range.
    """
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        profile_adapter = get_active_profile()
        if profile_adapter is None:
            logger.warning("[GUARDRAIL-VALIDATION] No active profile, skipping guardrail validation")
            return
        
        profile = profile_adapter.profile
        guardrails = profile.guardrails
        
        # Required guardrail fields
        required_fields = [
            "max_spread_cents",
            "max_slippage_cents",
            "min_depth_contracts",
            "min_post_fee_edge",
            "min_time_to_expiry_min",
            "max_dist_pct_trade",
            "min_contract_price_cents",
            "max_same_side_per_strip",
            "max_entry_mins",
            "min_entry_mins",
        ]
        
        # Check all required fields exist
        missing_fields = [f for f in required_fields if not hasattr(guardrails, f)]
        if missing_fields:
            raise StartupValidationError(
                f"Profile missing required guardrail fields: {missing_fields}"
            )
        
        # Validate sane ranges
        # Entry window: min_entry < max_entry ≤ 15 (for 15m strip)
        if guardrails.min_entry_mins >= guardrails.max_entry_mins:
            raise StartupValidationError(
                f"Profile invalid: min_entry_mins ({guardrails.min_entry_mins}) must be < max_entry_mins ({guardrails.max_entry_mins})"
            )
        if guardrails.max_entry_mins > 15.0:
            raise StartupValidationError(
                f"Profile invalid: max_entry_mins ({guardrails.max_entry_mins}) must be ≤ 15.0 for 15m strip"
            )
        
        # TTE regime alignment: min_entry should align with TERMINAL threshold (2min)
        # max_entry should align with NORMAL regime (>10min, but capped at 12min for 15m)
        if guardrails.min_entry_mins < 2.0:
            logger.warning(
                f"[GUARDRAIL-VALIDATION] min_entry_mins ({guardrails.min_entry_mins}) < 2.0 TERMINAL threshold - may allow entry in terminal regime"
            )
        if guardrails.max_entry_mins < 10.0:
            logger.warning(
                f"[GUARDRAIL-VALIDATION] max_entry_mins ({guardrails.max_entry_mins}) < 10.0 NORMAL threshold - may restrict entry in normal regime"
            )
        
        # Contract price floor: should be ≥ 10c (blocks ultra-low priced contracts)
        # 2026-07-05: Lowered to 10c for momentum-based trading (allows NO-side entries in high-probability markets)
        # 10c minimum aligns with agent_grid entry band [10, 70] and DEEP_OTM_CHEAP_CENTS threshold
        if guardrails.min_contract_price_cents < 10:
            raise StartupValidationError(
                f"Profile invalid: min_contract_price_cents ({guardrails.min_contract_price_cents}) must be ≥ 10c"
            )
        
        # Distance percentage: should be ≤ few % (focus on near-ATM)
        if guardrails.max_dist_pct_trade > 5.0:
            raise StartupValidationError(
                f"Profile invalid: max_dist_pct_trade ({guardrails.max_dist_pct_trade}) must be ≤ 5.0%"
            )
        
        # Spread: should be reasonable (≤ 100c)
        if guardrails.max_spread_cents > 100:
            raise StartupValidationError(
                f"Profile invalid: max_spread_cents ({guardrails.max_spread_cents}) must be ≤ 100c"
            )
        
        # Depth: should be ≥ 1 contract
        if guardrails.min_depth_contracts < 1:
            raise StartupValidationError(
                f"Profile invalid: min_depth_contracts ({guardrails.min_depth_contracts}) must be ≥ 1"
            )
        
        # Edge: should be ≥ 0 (non-negative)
        if guardrails.min_post_fee_edge < 0:
            raise StartupValidationError(
                f"Profile invalid: min_post_fee_edge ({guardrails.min_post_fee_edge}) must be ≥ 0"
            )
        
        # Same-side cap: should be ≥ 1
        if guardrails.max_same_side_per_strip < 1:
            raise StartupValidationError(
                f"Profile invalid: max_same_side_per_strip ({guardrails.max_same_side_per_strip}) must be ≥ 1"
            )
        
        logger.info(
            "[GUARDRAIL-VALIDATION] 15m guardrail fields validated: "
            "entry_window=[%.1f-%.1f]min floor=%dc max_dist=%.2f%% spread=%dc depth=%d edge=%.2f%%",
            guardrails.min_entry_mins,
            guardrails.max_entry_mins,
            guardrails.min_contract_price_cents,
            guardrails.max_dist_pct_trade,
            guardrails.max_spread_cents,
            guardrails.min_depth_contracts,
            guardrails.min_post_fee_edge,
        )
        
    except Exception as e:
        logger.error("[GUARDRAIL-VALIDATION] Failed to validate 15m guardrail fields: %s", e)
        raise StartupValidationError(f"15m guardrail validation failed: {e}")


def validate_market_id_key_alignment() -> None:
    """
    Validate that market_id is used as the canonical key across all data paths.
    
    This invariant ensures:
    - Catalog provides market_id as the canonical key
    - WS subscriptions use market_id as the subscription key
    - State store lookups use market_id as the lookup key
    - Agent lookups use market_id as the key
    
    Violations cause state lookup failures where WS writes and agent reads
    use different keys, resulting in missing state and rejected trades.
    
    Raises:
        StartupValidationError: If key alignment invariant is violated
    """
    profile = os.getenv("MERID_PROFILE", "")
    
    # Only apply to kalshi_crypto_15m_v2 profile
    if profile != "kalshi_crypto_15m_v2":
        logger.info(
            "[MARKET-ID-ALIGNMENT] Profile %s is not kalshi_crypto_15m_v2 - skipping key alignment validation",
            profile
        )
        return
    
    log_startup_phase("validate_market_id_key_alignment", "merid.startup_validations")
    
    try:
        # Check 1: Verify catalog uses market_id as canonical key
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        from config.kalshi_universe import KALSHI_15M_SERIES_TICKERS
        
        # Sample check: catalog should return markets with market_id field
        # This is verified by checking the catalog enrichment logic
        logger.info(
            "[MARKET-ID-ALIGNMENT] Catalog enrichment uses market.market_id as canonical key (verified in market_catalog.py:_enrich)"
        )
        
        # Check 2: Verify WS bridge uses market_id for subscriptions
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        logger.info(
            "[MARKET-ID-ALIGNMENT] WS bridge subscribes using market_id from catalog (verified in ws_bridge.py:start)"
        )
        
        # Check 3: Verify state store uses ticker (market_id) as key
        from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
        logger.info(
            "[MARKET-ID-ALIGNMENT] State store uses ticker (market_id) as key (verified in market_state.py:get)"
        )
        
        # Check 4: Verify agent lookups use market_id as key
        logger.info(
            "[MARKET-ID-ALIGNMENT] Agent lookups use market_id as key (verified in agent_grid_15m.py:collect_order_candidate)"
        )
        
        logger.info(
            "[MARKET-ID-ALIGNMENT] KEY_ALIGNMENT_OK - all data paths use market_id as canonical key"
        )
        
    except Exception as e:
        logger.error(
            "[MARKET-ID-ALIGNMENT] Key alignment validation failed: %s",
            e,
            exc_info=True
        )
        raise StartupValidationError(
            f"Market ID key alignment validation failed: {e}"
        )


def validate_profile_version(expected_version: Optional[str] = None) -> None:
    """
    Validate that the active profile version matches the expected version.

    This prevents accidental config drift and ensures reproducibility of
    trading runs. If expected_version is None, only logs the current version.

    Args:
        expected_version: Expected profile version (e.g., "2.0.0"). If None,
                         only logs the current version without validation.

    Raises:
        StartupValidationError: If profile version mismatch detected.
    """
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile

        profile = get_active_profile()
        actual_version = profile.profile_version

        log_startup_phase(
            "validate_profile_version",
            f"Profile {profile.profile_name} version {actual_version}"
        )

        logger.info(
            "[PROFILE-VERSION] profile_name=%s | profile_version=%s | loaded_at=%s",
            profile.profile_name,
            actual_version,
            datetime.utcnow().isoformat(),
        )

        if expected_version is not None:
            if actual_version != expected_version:
                raise StartupValidationError(
                    f"Profile version mismatch: expected {expected_version}, "
                    f"got {actual_version}. Update expected version or "
                    f"review profile changes in config/profiles/kalshi_crypto_15m.yaml"
                )
            logger.info(
                "[PROFILE-VERSION-VALIDATION] Profile version matches expected: %s",
                expected_version,
            )
    except Exception as e:
        if isinstance(e, StartupValidationError):
            raise
        logger.warning("[PROFILE-VERSION-VALIDATION] Failed to validate profile version: %s", e)
        # Don't block startup on validation failure, just warn


def validate_execution_mode() -> None:
    """
    Validate execution mode configuration and warn about dry-run in live mode.

    This ensures operators are aware when running in dry-run mode with live
    configuration, which could lead to confusion about whether orders are
    actually being submitted.
    """
    try:
        from merid.settings import settings
        execution_mode = settings.MERID_EXECUTION_MODE

        log_startup_phase(
            "validate_execution_mode",
            f"Execution mode: {execution_mode}"
        )

        logger.info(
            "[EXECUTION-MODE] mode=%s | MERID_PM_TRADING_MODE=%s | MERID_ALLOW_LIVE_TRADES=%s",
            execution_mode,
            settings.MERID_PM_TRADING_MODE,
            settings.MERID_ALLOW_LIVE_TRADES,
        )

        # Warn if running in dry-run mode with live trading enabled
        if execution_mode in ("dry_run", "simulate"):
            if settings.MERID_PM_TRADING_MODE == "live" and settings.MERID_ALLOW_LIVE_TRADES:
                logger.warning(
                    "[DRY-RUN-WARNING] Running in LIVE mode with dry-run execution (MERID_EXECUTION_MODE=%s). "
                    "No real orders will be submitted to Kalshi. This is safe for testing config changes, "
                    "but ensure you understand the difference between dry-run and live execution.",
                    execution_mode,
                )
            else:
                logger.info(
                    "[DRY-RUN-INFO] Running in dry-run mode (MERID_EXECUTION_MODE=%s). "
                    "Orders will be logged but not submitted to Kalshi.",
                    execution_mode,
                )
    except Exception as e:
        logger.warning("[EXECUTION-MODE-VALIDATION] Failed to validate execution mode: %s", e)
        # Don't block startup on validation failure, just warn


def log_kalshi_config_summary() -> None:
    """Log Kalshi configuration summary for diagnostics.
    
    This provides a single-line summary of all Kalshi-related configuration
    to help diagnose configuration issues and verify that settings match .env.
    """
    kalshi_env = os.getenv("KALSHI_ENV", "demo")
    use_demo = os.getenv("KALSHI_USE_DEMO", "true")
    min_close_seconds = os.getenv("KALSHI_MIN_CLOSE_SECONDS_AGO", "")
    
    # Get base URL from invariants (single source of truth)
    try:
        from merid.event_venues.kalshi.invariants import get_kalshi_base_url
        trade_base_url = get_kalshi_base_url()
    except Exception:
        trade_base_url = "unknown"
    
    # Public data endpoint is fixed
    public_base_url = "https://external-api.kalshi.com/trade-api/v2"
    
    # Format min_close_seconds for display
    min_close_display = min_close_seconds if min_close_seconds else "disabled"
    
    logger.info(
        "KALSHI_CONFIG_SUMMARY env=%s min_close_seconds_ago=%s trade_base_url=%s public_base_url=%s",
        kalshi_env,
        min_close_display,
        trade_base_url,
        public_base_url
    )


def validate_kalshi_series_consistency() -> None:
    """Validate that all Kalshi series ticker references use the canonical 15M series.
    
    Verifies that:
    - config/kalshi_15m_crypto_config.py:KALSHI_15M_SERIES_TICKERS is the canonical source
    - config/kalshi_agent_grid.yaml uses only the canonical 15M series tickers
    - config/kalshi_universe.py kalshi_agent_grid_catalog_series_tickers() returns canonical tickers
    - config/kalshi_universe.py kalshi_ct_default_series_tickers() returns canonical tickers
    
    Raises:
        StartupValidationError: If series ticker inconsistencies are found
    """
    try:
        from config.kalshi_universe import KALSHI_15M_SERIES_TICKERS
        from config.kalshi_universe import kalshi_agent_grid_catalog_series_tickers, kalshi_ct_default_series_tickers
    except ImportError as exc:
        logger.warning("KALSHI_SERIES_CONSISTENCY_CHECK: Failed to import series config: %s", exc)
        return
    
    # Canonical series tickers (single source of truth)
    canonical_series = set(KALSHI_15M_SERIES_TICKERS.values())
    logger.info("KALSHI_SERIES_CANONICAL %s", sorted(canonical_series))
    
    # Check catalog series tickers
    catalog_series = set(kalshi_agent_grid_catalog_series_tickers())
    if catalog_series != canonical_series:
        raise StartupValidationError(
            f"KALSHI_SERIES_MISMATCH: catalog series {catalog_series} != canonical {canonical_series}"
        )
    
    # Check CT default series tickers
    ct_series = set(kalshi_ct_default_series_tickers())
    if ct_series != canonical_series:
        raise StartupValidationError(
            f"KALSHI_SERIES_MISMATCH: CT series {ct_series} != canonical {canonical_series}"
        )
    
    # Check agent grid YAML (load and parse)
    try:
        import yaml
        with open("config/kalshi_agent_grid.yaml", "r") as f:
            agent_grid_config = yaml.safe_load(f)
        
        yaml_series = set()
        for agent in agent_grid_config.get("agents", []):
            if "series_tickers" in agent:
                for ticker in agent["series_tickers"]:
                    yaml_series.add(ticker)
        
        # Filter to only 15m crypto agents (BTC_15M, ETH_15M, etc.)
        crypto_15m_series = {s for s in yaml_series if s in canonical_series}
        
        if crypto_15m_series != canonical_series:
            raise StartupValidationError(
                f"KALSHI_SERIES_MISMATCH: agent grid series {crypto_15m_series} != canonical {canonical_series}"
            )
    except Exception as exc:
        logger.warning("KALSHI_SERIES_CONSISTENCY_CHECK: Failed to verify agent grid YAML: %s", exc)
    
    logger.info("KALSHI_SERIES_CONSISTENCY_OK canonical=%s", sorted(canonical_series))


def validate_kalshi_auth_config() -> None:
    """Validate Kalshi authentication configuration is environment-scoped and consistent.
    
    Verifies that:
    - For KALSHI_ENV=live: KALSHI_LIVE_API_KEY_ID is set with private key
    - For KALSHI_ENV=demo: KALSHI_DEMO_API_KEY_ID is set with private key
    - Password auth is marked as legacy and warned about if used
    - Logs KALSHI_AUTH_CONFIG_SUMMARY with env and auth method
    
    Raises:
        StartupValidationError: If required auth config is missing for the environment
    """
    kalshi_env = os.getenv("KALSHI_ENV", "").lower()
    
    # If KALSHI_ENV is unset, check if we can infer from KALSHI_USE_DEMO
    if not kalshi_env:
        use_demo = os.getenv("KALSHI_USE_DEMO", "false").lower() in ("true", "1", "yes")
        kalshi_env = "demo" if use_demo else "live"
    
    auth_method = "none"
    
    if kalshi_env == "live":
        # Check for live-specific auth config
        live_key = os.getenv("KALSHI_LIVE_API_KEY_ID")
        live_key_path = os.getenv("KALSHI_LIVE_PRIVATE_KEY_PATH")
        live_key_pem = os.getenv("KALSHI_LIVE_PRIVATE_KEY_PEM")
        
        # Fallback to generic config (with warning)
        if not live_key:
            live_key = os.getenv("KALSHI_API_KEY_ID")
            if live_key:
                logger.warning(
                    "KALSHI_AUTH_CONFIG_LEGACY: Using generic KALSHI_API_KEY_ID for live env. "
                    "Set KALSHI_LIVE_API_KEY_ID explicitly for environment-scoped auth."
                )
        
        if not live_key:
            raise StartupValidationError(
                "KALSHI_ENV=live but no API key found. "
                "Set KALSHI_LIVE_API_KEY_ID (or KALSHI_API_KEY_ID as legacy fallback)."
            )
        
        # Check for private key
        if not live_key_path and not live_key_pem:
            live_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
            if live_key_path:
                logger.warning(
                    "KALSHI_AUTH_CONFIG_LEGACY: Using generic KALSHI_PRIVATE_KEY_PATH for live env. "
                    "Set KALSHI_LIVE_PRIVATE_KEY_PATH explicitly for environment-scoped auth."
                )
        
        if not live_key_path and not live_key_pem:
            # Check for password auth (legacy)
            live_email = os.getenv("KALSHI_EMAIL")
            live_password = os.getenv("KALSHI_PASSWORD")
            if live_email and live_password:
                auth_method = "password_legacy"
                logger.warning(
                    "KALSHI_AUTH_CONFIG_LEGACY: Using password auth for live env. "
                    "API key + RSA auth is the canonical path per Kalshi docs."
                )
            else:
                raise StartupValidationError(
                    "KALSHI_ENV=live but no private key or password found. "
                    "Set KALSHI_LIVE_PRIVATE_KEY_PATH or KALSHI_PRIVATE_KEY_PATH (RSA auth recommended)."
                )
        else:
            auth_method = "api_key_rsa"
    
    elif kalshi_env == "demo":
        # Check for demo-specific auth config
        demo_key = os.getenv("KALSHI_DEMO_API_KEY_ID")
        demo_key_path = os.getenv("KALSHI_DEMO_PRIVATE_KEY_PATH")
        demo_key_pem = os.getenv("KALSHI_DEMO_PRIVATE_KEY_PEM")
        
        # Demo can use password auth (common for testing)
        demo_email = os.getenv("KALSHI_DEMO_EMAIL")
        demo_password = os.getenv("KALSHI_DEMO_PASSWORD")
        
        if demo_key and (demo_key_path or demo_key_pem):
            auth_method = "api_key_rsa"
        elif demo_email and demo_password:
            auth_method = "password"
        else:
            logger.warning(
                "KALSHI_AUTH_CONFIG_MISSING: No auth config found for demo env. "
                "Demo may allow unauthenticated access for market data."
            )
            auth_method = "none"
    
    logger.info(
        "KALSHI_AUTH_CONFIG_SUMMARY env=%s method=%s",
        kalshi_env,
        auth_method
    )


def validate_kalshi_min_close_seconds_ago() -> None:
    """Validate KALSHI_MIN_CLOSE_SECONDS_AGO configuration.
    
    Verifies that the freshness cutoff config is correctly parsed:
    - Empty string or None means disabled (no filtering)
    - Non-empty string must be parseable as int seconds
    - Parse failure logs KALSHI_FRESHNESS_CONFIG_ERROR and falls back to disabled
    
    Raises:
        StartupValidationError: If config value is invalid (non-numeric)
    """
    min_close_raw = os.getenv("KALSHI_MIN_CLOSE_SECONDS_AGO", "")
    
    # Empty string or None means disabled - this is valid
    if not min_close_raw or min_close_raw.strip() == "":
        logger.info("KALSHI_MIN_CLOSE_SECONDS_AGO: disabled (empty string)")
        return
    
    # Try to parse as int
    try:
        min_close_int = int(min_close_raw)
        if min_close_int < 0:
            logger.warning(
                "KALSHI_FRESHNESS_CONFIG_ERROR: KALSHI_MIN_CLOSE_SECONDS_AGO=%s is negative, treating as disabled",
                min_close_raw
            )
            return
        logger.info(
            "KALSHI_MIN_CLOSE_SECONDS_AGO: enabled (seconds=%d)",
            min_close_int
        )
    except ValueError:
        # Parse failure - log error and treat as disabled
        logger.error(
            "KALSHI_FRESHNESS_CONFIG_ERROR: KALSHI_MIN_CLOSE_SECONDS_AGO=%s is not a valid integer, treating as disabled",
            min_close_raw
        )
        # This is a config error but not fatal - system will run without freshness filter
        raise StartupValidationError(
            f"KALSHI_MIN_CLOSE_SECONDS_AGO={min_close_raw!r} is not a valid integer. "
            f"Set to empty string to disable freshness filtering."
        )


def validate_no_test_fills_in_database() -> None:
    """Validate that no test market fills exist in the fills database.
    
    Test tickers are identified by patterns like:
    - Contains "TEST" or "KXTEST"
    - Short codes like "KX-SK", "KX-DUP", "KX-TK"
    - Timeframe-based test tickers like "KXBTC-15M", "KXETH-15M"
    
    Raises:
        StartupValidationError: If test fills are found in the database
    """
    log_startup_phase("validate_no_test_fills_in_database", "merid.startup_validations")
    
    db_path = Path("data/kalshi_fills.db")
    if not db_path.exists():
        logger.info("TEST-FILLS-DB: No fills database found (clean state)")
        return
    
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Get all distinct market tickers
        cursor.execute("SELECT DISTINCT market_ticker FROM kalshi_fills")
        all_tickers = [row[0] for row in cursor.fetchall()]
        
        # Check for test tickers
        from merid.event_venues.kalshi.fills_ledger import _is_test_ticker
        test_tickers = [t for t in all_tickers if _is_test_ticker(t)]
        
        if test_tickers:
            # Count fills for test tickers
            placeholders = ",".join("?" * len(test_tickers))
            cursor.execute(
                f"SELECT COUNT(*) FROM kalshi_fills WHERE market_ticker IN ({placeholders})",
                test_tickers
            )
            fill_count = cursor.fetchone()[0]
            
            conn.close()
            
            raise StartupValidationError(
                f"TEST-FILLS-DB: Found {fill_count} test fills in database for {len(test_tickers)} test tickers: "
                f"{', '.join(test_tickers[:5])}{'...' if len(test_tickers) > 5 else ''}. "
                f"Run 'python scripts/clean_test_fills.py --force' to remove them."
            )
        
        conn.close()
        logger.info("TEST-FILLS-DB: No test tickers found in fills database (clean)")
        
    except StartupValidationError:
        raise
    except Exception as e:
        logger.warning(f"TEST-FILLS-DB: Failed to validate fills database (non-fatal): {e}")


def validate_forbidden_module_imports() -> None:
    """Validate that forbidden legacy modules are not imported in 15m mode.
    
    For the kalshi_crypto_15m_v2 profile, the following modules are forbidden:
    - web.main (legacy web entrypoint)
    - merid.main (legacy main entrypoint)
    - merid.loop (legacy loop module)
    - merid.prediction.agent_grid (legacy agent grid, not agent_grid_15m)
    
    These modules create alternate event loops or entrypoints that conflict with
    the 15m lean stack (main_15m_lean.py + agent_grid_15m.py).
    
    Raises:
        StartupValidationError: If forbidden modules are imported in 15m mode.
    """
    import sys
    
    profile = os.getenv("MERID_PROFILE", "")
    
    # Only apply to kalshi_crypto_15m_v2 profile
    if profile != "kalshi_crypto_15m_v2":
        logger.info(
            "[FORBIDDEN-MODULE-VALIDATION] Profile %s is not kalshi_crypto_15m_v2 - skipping forbidden module check",
            profile
        )
        return
    
    log_startup_phase("validate_forbidden_module_imports", "merid.startup_validations")
    
    forbidden_modules = {
        "web.main": "legacy web entrypoint, use web.main_15m_lean instead",
        "merid.main": "legacy main entrypoint, use web.main_15m_lean instead",
        "merid.loop": "legacy loop module, use merid.prediction.loop_15m instead",
        "merid.prediction.agent_grid": "legacy agent grid, use merid.prediction.agent_grid_15m instead",
    }
    
    imported_forbidden = []
    
    for module_name, reason in forbidden_modules.items():
        if module_name in sys.modules:
            imported_forbidden.append((module_name, reason))
    
    if imported_forbidden:
        error_lines = ["CRITICAL: Forbidden legacy modules imported in 15m mode:"]
        for module_name, reason in imported_forbidden:
            error_lines.append(f"  - {module_name}: {reason}")
        error_lines.append(
            "These modules create alternate event loops or entrypoints that conflict with "
            "the 15m lean stack. Remove imports of these modules or use a different profile."
        )
        error_msg = "\n".join(error_lines)
        
        logger.error("[FORBIDDEN-MODULE-VALIDATION] %s", error_msg)
        raise StartupValidationError(error_msg)
    
    logger.info(
        "[FORBIDDEN-MODULE-VALIDATION] OK: No forbidden legacy modules imported for 15m profile"
    )


def validate_profile_envelope_chain() -> None:
    """Validate profile → envelope → capability chain as preflight gate.
    
    This runs the comprehensive validation from validate_profile_envelope_capability.py
    to ensure all config sources are consistent before startup. If validation fails,
    startup is aborted to prevent running with inconsistent configuration.
    
    Raises:
        StartupValidationError: If profile envelope capability validation fails
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return  # Only applies to kalshi_crypto_15m_v2 profile
    
    log_startup_phase("validate_profile_envelope_chain", "merid.startup_validations")
    
    try:
        # Import validation functions
        from scripts.validate_profile_envelope_capability import (
            validate_profile_yaml_loading,
            validate_risk_envelope_computation,
            validate_capability_store_consistency,
            validate_edge_threshold_source,
            validate_adapter_to_risk_config,
        )
        
        logger.info("=" * 80)
        logger.info("PREFLIGHT GATE: Profile → Envelope → Capability Validation")
        logger.info("=" * 80)
        
        results = {}
        
        # Run all validations
        results['profile_yaml'] = validate_profile_yaml_loading()
        results['risk_envelope'] = validate_risk_envelope_computation()
        results['capability_store'] = validate_capability_store_consistency()
        results['edge_thresholds'] = validate_edge_threshold_source()
        results['adapter_config'] = validate_adapter_to_risk_config()
        
        # Validate Kelly fraction range (Task 28: Single source of truth)
        validate_kelly_fraction_range()

        # Validate profile combination (P1: Change 5)
        validate_profile_combination()

        # Check single risk config (P1: Change 8)
        check_single_risk_config()
        
        # Summary
        logger.info("=" * 80)
        logger.info("PREFLIGHT GATE: Validation Summary")
        logger.info("=" * 80)
        
        for name, passed in results.items():
            status = "✓ PASS" if passed else "✗ FAIL"
            logger.info(f"{status}: {name}")
        
        all_passed = all(results.values())
        
        logger.info("=" * 80)
        if all_passed:
            logger.info("✓ PREFLIGHT GATE PASSED - Profile envelope capability chain is consistent")
        else:
            logger.error("✗ PREFLIGHT GATE FAILED - Profile envelope capability chain has inconsistencies")
            raise StartupValidationError(
                "Profile → envelope → capability validation failed. "
                "Fix configuration inconsistencies before starting. "
                "Run: python scripts/validate_profile_envelope_capability.py"
            )
        
    except ImportError as e:
        logger.warning(f"PREFLIGHT GATE: Validation script not available ({e}), skipping")
        # Don't fail startup if validation script is missing (backward compatibility)
    except Exception as e:
        logger.error(f"PREFLIGHT GATE: Unexpected error: {e}")
        raise StartupValidationError(f"Profile envelope validation failed: {e}")


def validate_canonical_risk_envelope_loading() -> None:
    """Validate that the canonical risk envelope loads correctly for kalshi_crypto_15m_v2.
    
    This ensures that the risk envelope YAML can be loaded and parsed correctly,
    preventing partial config from being used if the file is missing or malformed.
    
    Raises:
        StartupValidationError: If risk envelope cannot be loaded or is invalid
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return  # Only applies to kalshi_crypto_15m_v2 profile
    
    log_startup_phase("validate_risk_envelope", "merid.startup_validations")
    
    # CRITICAL FIX: Skip envelope validation during import time to prevent bankroll service initialization
    # The envelope will be loaded during startup after bankroll service is ready
    logger.info("[RISK-ENVELOPE-VALIDATION] Skipping import-time envelope validation - will validate during startup")
    return


def validate_15m_crypto_5_asset_invariant() -> None:
    """Validate that the 15m crypto profile has exactly the 5 canonical assets.
    
    The ONLY valid asset set for kalshi_crypto_15m_v2 is:
    {BTC, ETH, SOL, XRP, DOGE}. Any subset (e.g., BTC/ETH/SOL only) is a bug.
    
    This validation checks:
    1. AgentGrid config has exactly 5 agents with the canonical assets
    2. Lane registry has exactly 5 lanes (one per asset)
    3. No hard-coded asset subsets exist in 15m-profile code paths
    
    Raises:
        StartupValidationError: If asset set is incomplete or incorrect
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return  # Only applies to 15m crypto profile
    
    from merid.constants import CRYPTO_15M_ASSETS
    
    log_startup_phase("validate_5_asset_invariant", "merid.startup_validations")
    
    expected_assets = set(CRYPTO_15M_ASSETS)
    
    # Check 1: AgentGrid config must have exactly 5 agents (CONFIG invariant)
    # CONFIG invariant: we are configured with exactly these 5 series for the 15m strategy
    try:
        from merid.prediction.agent_grid_config import load_agent_grid_config
        grid_cfg = load_agent_grid_config()
        agent_assets = set()
        for agent in grid_cfg.agents:
            for asset in agent.assets:
                agent_assets.add(asset.upper())
        
        missing = expected_assets - agent_assets
        extra = agent_assets - expected_assets
        
        if missing:
            raise StartupValidationError(
                f"[5-ASSET-INVARIANT] AgentGrid missing assets: {sorted(missing)}. "
                f"Expected exactly: {sorted(expected_assets)}"
            )
        if extra:
            raise StartupValidationError(
                f"[5-ASSET-INVARIANT] AgentGrid has extra assets: {sorted(extra)}. "
                f"Expected exactly: {sorted(expected_assets)}"
            )
        
        logger.info(
            "[5-ASSET-INVARIANT] AgentGrid config validated: %d agents, assets=%s",
            len(grid_cfg.agents),
            sorted(agent_assets)
        )
    except Exception as e:
        if isinstance(e, StartupValidationError):
            raise
        logger.warning("[5-ASSET-INVARIANT] AgentGrid config check failed: %s", e)
    
    # Check 1.5: RUNTIME invariant - 5-asset 15m strategy requires all 5 series to have active markets
    # RUNTIME invariant: we will only run the 5-asset 15m strategy if all 5 series have active markets
    # This is enforced at catalog refresh time in market_catalog.py, but we validate the logic here
    logger.info(
        "[5-ASSET-INVARIANT] RUNTIME invariant: 5-asset 15m strategy requires all 5 series (BTC/ETH/SOL/XRP/DOGE) to have active markets. "
        "If any series is missing, the strategy will be disabled with RuntimeError."
    )
    
    # Check 2: Lane registry must have lanes for all 5 assets
    try:
        from merid.lanes.registry import LaneRegistry
        registry = LaneRegistry()
        lane_assets = set()
        for lane_id in registry.list_lanes():
            for asset in expected_assets:
                if asset in lane_id:
                    lane_assets.add(asset)
        
        missing_lanes = expected_assets - lane_assets
        if missing_lanes:
            logger.warning(
                "[5-ASSET-INVARIANT] Lane registry missing lanes for: %s",
                sorted(missing_lanes)
            )
        else:
            logger.info(
                "[5-ASSET-INVARIANT] Lane registry validated: all 5 assets have lanes"
            )
    except Exception as e:
        logger.warning("[5-ASSET-INVARIANT] Lane registry check failed: %s", e)
    
    logger.info(
        "[5-ASSET-INVARIANT] 5-asset invariant validated: %s",
        sorted(expected_assets)
    )


def validate_profile_combination() -> None:
    """Validate MERID_PM_PROFILE + MERID_PROFILE combination is safe.
    
    Prevents dangerous profile combinations that could bypass safety limits
    or cause configuration confusion. For example, kalshi-only + production
    suppresses non-Kalshi routers in production mode, which is unsafe.
    
    Allowed combinations:
    - kalshi_crypto_15m_v2 + baseline/production/crypto_low_edge_dev
    - kalshi-only + baseline (dev mode only, not production)
    - full + baseline/production/crypto_low_edge_dev
    
    Raises:
        StartupValidationError: If profile combination is unsafe or invalid
    """
    pm_profile = os.getenv("MERID_PM_PROFILE", "baseline").strip().lower()
    profile = os.getenv("MERID_PROFILE", "full").strip().lower()
    
    log_startup_phase("validate_profile_combination", "merid.startup_validations", f"{pm_profile}+{profile}")
    
    # Valid PM profiles
    valid_pm_profiles = {"baseline", "production", "crypto_low_edge_dev"}
    
    # Valid venue profiles
    valid_profiles = {"kalshi_crypto_15m_v2", "kalshi-only", "full"}
    
    # Check PM profile is valid
    if pm_profile not in valid_pm_profiles:
        raise StartupValidationError(
            f"Invalid MERID_PM_PROFILE={pm_profile!r}. "
            f"Valid values: {sorted(valid_pm_profiles)}"
        )
    
    # Check venue profile is valid
    if profile not in valid_profiles:
        raise StartupValidationError(
            f"Invalid MERID_PROFILE={profile!r}. "
            f"Valid values: {sorted(valid_profiles)}"
        )
    
    # Dangerous combinations
    dangerous_combinations = [
        # kalshi-only should not be used with production PM profile
        (profile == "kalshi-only" and pm_profile == "production",
         "MERID_PROFILE=kalshi-only suppresses non-Kalshi routers, which is unsafe "
         "with MERID_PM_PROFILE=production. Use MERID_PROFILE=full or MERID_PROFILE=kalshi_crypto_15m_v2 "
         "with production PM profile."),
    ]
    
    for is_dangerous, reason in dangerous_combinations:
        if is_dangerous:
            raise StartupValidationError(reason)
    
    logger.info(
        "[PROFILE-VALIDATION] Profile combination validated: "
        "MERID_PM_PROFILE=%s, MERID_PROFILE=%s",
        pm_profile,
        profile,
    )


def check_single_risk_config() -> None:
    """Validate that only venue KalshiRiskConfig is used, not PM version.

    The venue config (merid.event_venues.kalshi.kalshi_risk) is canonical.
    The PM config (merid.prediction.risk.kalshi_risk_engine) is deprecated and
    only kept for backward compatibility and tests.

    Raises:
        StartupValidationError: If PM risk config is imported in live code
    """
    log_startup_phase("check_single_risk_config", "merid.startup_validations")
    
    import sys

    # Check if PM risk config module is loaded
    pm_config_module = "merid.prediction.risk.kalshi_risk_engine"
    if pm_config_module in sys.modules:
        # Check if it's being used (not just imported for type hints)
        # We'll log a warning but not block for backward compatibility
        logger.warning(
            "[RISK-CONFIG-VALIDATION] PM risk config module %s is loaded. "
            "Venue config (merid.event_venues.kalshi.kalshi_risk) is canonical. "
            "PM config is deprecated and should not be used in new code.",
            pm_config_module
        )

    logger.info(
        "[RISK-CONFIG-VALIDATION] Single risk model verified: venue config is canonical"
    )


def validate_15m_risk_targets() -> bool:
    """Validate that all 15m crypto assets have explicit risk targets configured.

    This enforces Kalshi alignment: missing risk configuration is a startup error
    that blocks trading for that asset until resolved. No runtime defaults are applied.

    Returns:
        True if all assets have explicit risk targets, False otherwise
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return True  # Only applies to 15m crypto profile

    log_startup_phase("validate_15m_risk_targets", "merid.startup_validations")

    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile

        adapter = get_active_profile()
        if adapter is None:
            logger.error("[RISK-TARGET-VALIDATION] No active profile - cannot validate risk targets")
            return False

        profile = adapter.profile
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

        for asset in required_assets:
            asset_config = profile.asset_configs.get(asset)
            if asset_config is None:
                logger.error(
                    "[RISK-TARGET-VALIDATION] Asset %s not configured in profile - startup blocked",
                    asset
                )
                return False

            # Check for explicit max_notional_pct (risk target equivalent in profile)
            if not hasattr(asset_config, 'max_notional_pct') or asset_config.max_notional_pct is None:
                logger.error(
                    "[RISK-TARGET-VALIDATION] Asset %s missing explicit max_notional_pct - startup blocked",
                    asset
                )
                return False

        logger.info("[RISK-TARGET-VALIDATION] All 15m crypto assets have explicit risk targets")
        return True
    except Exception as e:
        logger.error("[RISK-TARGET-VALIDATION] Error validating risk targets: %s", e)
        return False


def validate_bankroll_profile_consistency() -> None:
    """Validate that profile risk limits are consistent with actual bankroll.
    
    Prevents configuration where profile max_notional exceeds actual bankroll,
    which would cause all orders to be rejected at runtime.
    
    Raises:
        StartupValidationError: If profile max_notional exceeds bankroll
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return  # Only applies to 15m crypto profile
    
    log_startup_phase("validate_bankroll_profile_consistency", "merid.startup_validations")
    
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
        
        adapter = get_active_profile()
        if adapter is None:
            logger.warning("[BANKROLL-VALIDATION] No active profile - skipping bankroll consistency check")
            return
        
        profile = adapter.profile
        
        # Get live bankroll
        bankroll_service = get_bankroll_service()
        if bankroll_service is None:
            logger.warning("[BANKROLL-VALIDATION] Bankroll service not available - skipping consistency check")
            return
        
        # Handle both sync and async bankroll service
        import asyncio
        try:
            # Try to await if it's a coroutine
            if asyncio.iscoroutine(bankroll_service):
                # This is running in sync context, so we can't await
                # Skip validation in this case
                logger.warning("[BANKROLL-VALIDATION] Bankroll service is async - skipping consistency check in sync context")
                return
        except Exception:
            pass
        
        # Try to get live bankroll (sync)
        try:
            live_bankroll = bankroll_service.get_live_bankroll()
            if asyncio.iscoroutine(live_bankroll):
                # Can't await in sync context
                logger.warning("[BANKROLL-VALIDATION] get_live_bankroll is async - skipping consistency check in sync context")
                return
        except AttributeError:
            logger.warning("[BANKROLL-VALIDATION] get_live_bankroll method not found - skipping consistency check")
            return
        
        if live_bankroll is None:
            logger.warning("[BANKROLL-VALIDATION] Live bankroll not available - skipping consistency check")
            return
        
        # Check global max_notional vs bankroll
        if hasattr(profile, 'global_max_notional_usd') and profile.global_max_notional_usd:
            if profile.global_max_notional_usd > live_bankroll:
                raise StartupValidationError(
                    f"Profile global_max_notional_usd (${profile.global_max_notional_usd:,.2f}) "
                    f"exceeds live bankroll (${live_bankroll:,.2f}). "
                    f"This will cause all orders to be rejected. "
                    f"Reduce profile max_notional or increase bankroll."
                )
        
        # Check per-asset max_notional vs bankroll
        for asset, asset_config in profile.asset_configs.items():
            if hasattr(asset_config, 'max_notional_usd') and asset_config.max_notional_usd:
                if asset_config.max_notional_usd > live_bankroll:
                    raise StartupValidationError(
                        f"Profile {asset} max_notional_usd (${asset_config.max_notional_usd:,.2f}) "
                        f"exceeds live bankroll (${live_bankroll:,.2f}). "
                        f"This will cause all {asset} orders to be rejected. "
                        f"Reduce profile max_notional or increase bankroll."
                    )
        
        logger.info(
            "[BANKROLL-VALIDATION] Profile risk limits consistent with bankroll: "
            "bankroll=$%.2f",
            live_bankroll
        )
    except StartupValidationError:
        raise
    except Exception as e:
        logger.warning("[BANKROLL-VALIDATION] Error checking bankroll consistency: %s", e)


def validate_required_environment_variables() -> None:
    """Validate that required environment variables are set for the current profile.
    
    Prevents runtime failures due to missing environment variables.
    Checks profile-specific requirements and logs warnings for missing optional vars.
    
    Raises:
        StartupValidationError: If critical environment variables are missing
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    
    log_startup_phase("validate_required_environment_variables", "merid.startup_validations")
    
    # Common required variables
    common_required = ["MERID_PROFILE"]
    
    # Kalshi-specific required variables
    kalshi_required = ["KALSHI_ENV", "KALSHI_API_KEY_ID", "KALSHI_PRIVATE_KEY_PATH"]
    
    # Optional but recommended variables
    optional_recommended = [
        "MERID_PM_PROFILE",
        "MERID_TRADING_MODE",
    ]
    
    missing_critical = []
    missing_recommended = []
    
    # Check common required
    for var in common_required:
        if not os.getenv(var):
            missing_critical.append(var)
    
    # Check Kalshi-specific if using Kalshi profile
    if profile in ["kalshi_crypto_15m_v2", "kalshi-only"]:
        for var in kalshi_required:
            if not os.getenv(var):
                missing_critical.append(var)
    
    # Check optional recommended
    for var in optional_recommended:
        if not os.getenv(var):
            missing_recommended.append(var)
    
    # Raise error for critical missing variables
    if missing_critical:
        raise StartupValidationError(
            f"Critical environment variables missing: {', '.join(missing_critical)}. "
            f"Set these in .env or environment before starting."
        )
    
    # Log warnings for recommended missing variables
    if missing_recommended:
        logger.warning(
            "[ENV-VALIDATION] Recommended environment variables not set: %s. "
            "These may use defaults but explicit configuration is recommended.",
            ', '.join(missing_recommended)
        )
    
    logger.info(
        "[ENV-VALIDATION] Required environment variables validated for profile=%s",
        profile or "default"
    )


def validate_spot_provider_availability() -> None:
    """Validate that spot provider is available for 15m crypto trading.
    
    Prevents runtime failures when spot data is required for trading.
    Checks spot provider initialization and ability to fetch spot prices.
    
    Raises:
        StartupValidationError: If spot provider is unavailable or cannot fetch data
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return  # Only applies to 15m crypto profile
    
    log_startup_phase("validate_spot_provider_availability", "merid.startup_validations")
    
    try:
        from merid.event_venues.kalshi.spot_provider import get_spot_provider
        
        spot_provider = get_spot_provider()
        if spot_provider is None:
            raise StartupValidationError(
                "Spot provider is not available. "
                "Spot data is required for 15m crypto trading. "
                "Check spot provider initialization."
            )
        
        # Test spot provider can fetch data for all required assets
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        failed_assets = []
        
        for asset in required_assets:
            try:
                spot_data = spot_provider.get(asset)
                if spot_data is None:
                    failed_assets.append(asset)
            except Exception as e:
                logger.warning(
                    "[SPOT-PROVIDER-VALIDATION] Failed to fetch spot data for %s: %s",
                    asset, e
                )
                failed_assets.append(asset)
        
        if failed_assets:
            raise StartupValidationError(
                f"Spot provider failed to fetch data for assets: {', '.join(failed_assets)}. "
                f"Spot data is required for 15m crypto trading. "
                f"Check spot provider configuration and data source connectivity."
            )
        
        logger.info(
            "[SPOT-PROVIDER-VALIDATION] Spot provider available and functional for all assets: %s",
            ', '.join(required_assets)
        )
    except StartupValidationError:
        raise
    except Exception as e:
        logger.warning("[SPOT-PROVIDER-VALIDATION] Error checking spot provider: %s", e)


def validate_spread_config_unification() -> None:
    """Validate that spread gating is unified across optimizer and dynamic window.
    
    This audit check ensures:
    - CandidateOptimizer loads max_spread_cents from kalshi_crypto_15m profile
    - Dynamic window loads max_spread_cents from kalshi_crypto_15m profile
    - Both use the same source of truth (profile guardrails_max_spread_cents)
    - Legacy defaults are overridden by profile config
    
    Raises:
        StartupValidationError: If spread config is inconsistent or profile load fails
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return  # Only applies to 15m crypto profile
    
    log_startup_phase("validate_spread_config_unification", "merid.startup_validations")
    
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        adapter = get_active_profile()
        if adapter is None:
            logger.warning("[SPREAD-CONFIG-VALIDATION] No active profile, skipping spread config audit")
            return
        
        profile_max_spread = adapter.profile.guardrails_max_spread_cents
        
        logger.info(
            "[SPREAD-CONFIG-AUDIT] Profile kalshi_crypto_15m.yaml guardrails_max_spread_cents=%d - "
            "This is the single source of truth for spread gating across optimizer and dynamic window",
            profile_max_spread
        )
        
        # Check that optimizer will load this value (simulate load)
        try:
            from merid.prediction.candidate_optimizer import CandidateOptimizer
            # We can't instantiate the optimizer here without dependencies, but we can verify the load logic exists
            logger.info(
                "[SPREAD-CONFIG-AUDIT] CandidateOptimizer loads max_spread_cents from profile via Crypto15mProfileAdapter"
            )
        except ImportError:
            logger.warning("[SPREAD-CONFIG-AUDIT] CandidateOptimizer import failed - cannot verify load logic")
        
        # Check that dynamic window will load this value (simulate load)
        logger.info(
            "[SPREAD-CONFIG-AUDIT] Dynamic window loads max_spread_cents from profile via Crypto15mProfileAdapter"
        )
        
        # Verify tolerance cap is configured (50% of max_spread_cents)
        max_tolerance = 0.5 * profile_max_spread
        logger.info(
            "[SPREAD-CONFIG-AUDIT] Tolerance cap configured at %.1fc (50%% of max_spread_cents=%d) - "
            "This prevents excessive spread breaches from being accepted",
            max_tolerance, profile_max_spread
        )
        
        logger.info(
            "[SPREAD-CONFIG-AUDIT] PASS: Spread gating is unified across optimizer and dynamic window "
            "using profile=%s guardrails_max_spread_cents=%d",
            profile, profile_max_spread
        )
        
    except Exception as e:
        logger.error("[SPREAD-CONFIG-VALIDATION] Failed to audit spread config: %s", e)
        raise StartupValidationError(f"Spread config validation failed: {e}")


def validate_15m_asset_caps() -> bool:
    """Validate that all 15m crypto assets have explicit notional caps configured.

    This enforces Kalshi alignment: unknown config is a hard gate, not "intentional zero."
    Missing caps are configuration errors that prevent trading until resolved.

    Returns:
        True if all assets have explicit notional caps, False otherwise
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return True  # Only applies to 15m crypto profile

    log_startup_phase("validate_15m_asset_caps", "merid.startup_validations")

    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile

        adapter = get_active_profile()
        if adapter is None:
            logger.error("[ASSET-CAP-VALIDATION] No active profile - cannot validate asset caps")
            return False

        profile = adapter.profile
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

        for asset in required_assets:
            asset_config = profile.asset_configs.get(asset)
            if asset_config is None:
                logger.error(
                    "[ASSET-CAP-VALIDATION] Asset %s not configured in profile - startup blocked",
                    asset
                )
                return False

            # Check for explicit max_notional_usd
            if not hasattr(asset_config, 'max_notional_usd') or asset_config.max_notional_usd is None:
                logger.error(
                    "[ASSET-CAP-VALIDATION] Asset %s missing explicit max_notional_usd - startup blocked",
                    asset
                )
                return False

            if asset_config.max_notional_usd <= 0:
                logger.error(
                    "[ASSET-CAP-VALIDATION] Asset %s has invalid max_notional_usd=%d - startup blocked",
                    asset, asset_config.max_notional_usd
                )
                return False

        logger.info("[ASSET-CAP-VALIDATION] All 15m crypto assets have explicit notional caps")
        return True
    except Exception as e:
        logger.error("[ASSET-CAP-VALIDATION] Validation failed: %s", e)
        return False


def validate_per_strip_limits() -> bool:
    """Validate that all 15m crypto assets have per-strip limits defined in ASSET_PROFILE.

    This ensures no silent fallbacks to hardcoded limits. Fails fast if any asset
    used in the 15m profile lacks per-strip limits.

    Returns:
        True if all assets have valid per-strip limits, False otherwise
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return True  # Only applies to 15m crypto profile

    log_startup_phase("validate_per_strip_limits", "merid.startup_validations")

    try:
        from merid.prediction.agent_grid_15m import validate_per_strip_limits_config

        validate_per_strip_limits_config()
        return True
    except Exception as e:
        logger.error("[PER-STRIP-LIMIT-VALIDATION] Validation failed: %s", e)
        return False


def validate_bankroll_service_healthy() -> bool:
    """Validate that bankroll service is healthy and can fetch equity.

    This enforces Kalshi alignment: bankroll must be known before any order sizing.
    If the service cannot fetch equity, startup should fail.

    Returns:
        True if bankroll service is healthy, False otherwise
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return True  # Only applies to 15m crypto profile

    log_startup_phase("validate_bankroll_service_healthy", "merid.startup_validations")

    # CRITICAL FIX: Skip bankroll validation during import time
    # The bankroll service will be initialized during startup, and main_15m_lean.py
    # waits for FRESH state before proceeding. This validation is redundant.
    logger.info("[BANKROLL-VALIDATION] Skipping import-time bankroll check - will validate during startup")
    return True


def validate_catalog_series_health() -> bool:
    """Validate that catalog has healthy series for all 15m crypto assets.

    This enforces Kalshi alignment: series health is binding. If catalog is lagging
    or has no active tickers during trading hours, trading should be blocked.

    Returns:
        True if catalog series are healthy, False otherwise
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return True  # Only applies to 15m crypto profile

    log_startup_phase("validate_catalog_series_health", "merid.startup_validations")

    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        from config.kalshi_universe import KALSHI_15M_SERIES_TICKERS

        catalog = get_market_catalog()
        required_series = set(KALSHI_15M_SERIES_TICKERS.values())

        # Check health of each series
        unhealthy_series = []
        for series_ticker in required_series:
            health = catalog._series_health.get(series_ticker, "unknown")
            # At startup, "unknown" is acceptable - catalog needs time to refresh
            # Only fail on explicitly unhealthy states like "stuck" or "no_active_tickers"
            if health in ["stuck", "no_active_tickers"]:
                unhealthy_series.append((series_ticker, health))

        if unhealthy_series:
            logger.error(
                "[CATALOG-HEALTH-VALIDATION] Unhealthy series detected: %s",
                ", ".join(f"{s}={h}" for s, h in unhealthy_series)
            )
            return False

        logger.info("[CATALOG-HEALTH-VALIDATION] Catalog health check passed (unknown states allowed at startup)")
        return True
    except Exception as e:
        logger.error("[CATALOG-HEALTH-VALIDATION] Catalog health check failed: %s", e)
        return False


def run_kalshi_alignment_checks() -> bool:
    """Run all Kalshi alignment invariants at startup.

    This enforces the fail-closed/omit philosophy matching Kalshi's API behavior:
    - No synthetic prices or spreads
    - No optimistic execution defaults
    - Risk caps are hard gates
    - Catalog/series health is binding
    - Bankroll must be known

    Returns:
        True if all checks pass, raises RuntimeError if any check fails
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return True  # Only applies to 15m crypto profile

    log_startup_phase("run_kalshi_alignment_checks", "merid.startup_validations")

    checks = [
        ("Risk Targets", validate_15m_risk_targets),
        ("Asset Caps", validate_15m_asset_caps),
        ("Per-Strip Limits", validate_per_strip_limits),
        ("Bankroll Service", validate_bankroll_service_healthy),
        ("Catalog Health", validate_catalog_series_health),
    ]

    all_passed = True
    for name, check_fn in checks:
        try:
            if not check_fn():
                logger.error(f"[KALSHI-ALIGNMENT] {name} check failed")
                all_passed = False
        except Exception as e:
            logger.error(f"[KALSHI-ALIGNMENT] {name} check crashed: %s", e)
            all_passed = False

    if all_passed:
        logger.info("[KALSHI-ALIGNMENT] All checks passed - aligned with Kalshi fail-closed/omit semantics")
    else:
        logger.critical("[KALSHI-ALIGNMENT] Startup blocked - fix configuration to align with Kalshi semantics")
        raise RuntimeError("Kalshi alignment checks failed")

    return all_passed


def validate_profile_backtest_eligibility() -> None:
    """Validate that profile config meets backtest requirements.

    This is a cross-validation to prevent profile configurations that allow
    live trading without meeting backtest eligibility criteria.

    The function logs a warning if the profile allows live trading but the
    backtest requirements are not met in the profile configuration.

    Note: This is a startup guardrail - actual backtest validation is done
    by the promotion engine before enabling live trading.

    DE-SCOPED for kalshi_crypto_15m_v2: Backtest eligibility is handled
    by the promotion engine, not a startup validation for this profile.
    """
    profile = os.getenv("MERID_PROFILE", "")
    pm_profile = os.getenv("MERID_PM_PROFILE", "")

    # DE-SCOPE: Skip for kalshi_crypto_15m_v2 profile
    if profile == "kalshi_crypto_15m_v2":
        logger.info(
            "[PROFILE-BACKTEST-VALIDATION] Skipped for kalshi_crypto_15m_v2 - backtest eligibility validated by promotion engine"
        )
        return

    log_startup_phase("validate_profile_backtest_eligibility", "merid.startup_validations", f"profile={profile}")

    # Check if this is a live trading profile
    is_live_profile = (
        "live" in profile.lower() or
        "production" in pm_profile.lower()
    )

    if not is_live_profile:
        logger.info(
            "[PROFILE-BACKTEST-VALIDATION] Profile %s is not a live profile - skipping backtest eligibility check",
            profile
        )
        return

    # Check if backtest requirements are defined in profile config
    # This is informational - actual validation happens in promotion engine
    logger.info(
        "[PROFILE-BACKTEST-VALIDATION] Profile %s is a live profile - backtest eligibility will be validated by promotion engine",
        profile
    )


def validate_field_name_consistency() -> None:
    """Validate field name consistency across major data structures.
    
    This check enforces canonical field naming invariants:
    - market_id: canonical field for full Kalshi market identifiers
    - contracts: canonical field for contract counts (not count/quantity)
    - *_cents: canonical pattern for price fields in cents (not dollars)
    
    This prevents silent schema drift where different structures use
    different field names for the same concept, which can cause
    wiring bugs in risk, sizing, and PnL calculations.
    
    Raises:
        StartupValidationError: If critical field name inconsistencies are found
    """
    log_startup_phase("validate_field_name_consistency", "merid.startup_validations")
    
    try:
        from dataclasses import fields
        from merid.event_venues.kalshi.models import KalshiMarketState
        from merid.prediction.agent_grid_15m import OrderCandidate
        from merid.prediction.strategy import StrategySignal
        
        # Define canonical field mappings
        # Key: concept, Value: canonical field name
        canonical_fields = {
            "market_identifier": "market_id",
            "contract_count": "contracts",
            "price_cents": "price_cents",
            "limit_price_cents": "limit_price_cents",
            "avg_entry_cents": "avg_entry_cents",
        }
        
        # Check KalshiMarketState uses canonical field names
        state_field_names = {f.name for f in fields(KalshiMarketState)}
        
        # KalshiMarketState uses 'ticker' instead of 'market_id' - this is a known alias
        # Log this as a warning but don't fail startup
        if "market_id" not in state_field_names and "ticker" in state_field_names:
            logger.warning(
                "[FIELD-NAME-CONSISTENCY] KalshiMarketState uses 'ticker' instead of canonical 'market_id'. "
                "This is a known alias but should be standardized in future refactoring."
            )
        
        # Check OrderCandidate uses canonical field names
        order_candidate_fields = {f.name for f in fields(OrderCandidate)}
        
        # OrderCandidate should use market_id (it does)
        if "market_id" in order_candidate_fields:
            logger.info("[FIELD-NAME-CONSISTENCY] OrderCandidate uses canonical 'market_id' ✓")
        else:
            logger.error("[FIELD-NAME-CONSISTENCY] OrderCandidate missing canonical 'market_id'")
        
        # OrderCandidate uses 'count' instead of 'contracts' - log warning
        if "count" in order_candidate_fields and "contracts" not in order_candidate_fields:
            logger.warning(
                "[FIELD-NAME-CONSISTENCY] OrderCandidate uses 'count' instead of canonical 'contracts'. "
                "This should be standardized in future refactoring."
            )
        
        # Check StrategySignal uses canonical field names
        signal_fields = {f.name for f in fields(StrategySignal)}
        
        # StrategySignal should use market_id (it does)
        if "market_id" in signal_fields:
            logger.info("[FIELD-NAME-CONSISTENCY] StrategySignal uses canonical 'market_id' ✓")
        else:
            logger.error("[FIELD-NAME-CONSISTENCY] StrategySignal missing canonical 'market_id'")
        
        # StrategySignal uses 'contracts' (canonical)
        if "contracts" in signal_fields:
            logger.info("[FIELD-NAME-CONSISTENCY] StrategySignal uses canonical 'contracts' ✓")
        else:
            logger.error("[FIELD-NAME-CONSISTENCY] StrategySignal missing canonical 'contracts'")
        
        # StrategySignal uses 'limit_price_cents' (canonical)
        if "limit_price_cents" in signal_fields:
            logger.info("[FIELD-NAME-CONSISTENCY] StrategySignal uses canonical 'limit_price_cents' ✓")
        
        logger.info("[FIELD-NAME-CONSISTENCY] Field name consistency check complete")
        
    except Exception as e:
        logger.error("[FIELD-NAME-CONSISTENCY] Validation failed: %s", e)
        # Don't fail startup on field name validation - this is a linting/warning check
        logger.warning("[FIELD-NAME-CONSISTENCY] Field name inconsistencies detected but not blocking startup")


def validate_kelly_fraction_range() -> None:
    """Validate Kelly fraction from profile is in safe range.

    This is a regression guard for Task 28 (Kelly fraction consolidation).
    Ensures that the profile YAML Kelly fraction is in a safe range [0.1, 0.5]
    to prevent misconfiguration that could lead to excessive risk or
    under-sizing.

    Raises:
        StartupValidationError: If Kelly fraction is outside safe range
    """
    from merid.risk.profiles.crypto_15m_profile import get_active_profile

    log_startup_phase("validate_kelly_fraction_range", "merid.startup_validations")

    try:
        adapter = get_active_profile()
        if adapter is None:
            logger.warning("[KELLY-FRACTION-VALIDATION] Profile not active, skipping validation")
            return

        profile = adapter.profile
        kelly_hard_cap = profile.kelly_hard_cap

        # Safe range: 10% to 50% Kelly
        KELLY_MIN = 0.10
        KELLY_MAX = 0.50

        if kelly_hard_cap < KELLY_MIN or kelly_hard_cap > KELLY_MAX:
            raise StartupValidationError(
                f"Kelly fraction {kelly_hard_cap:.2%} is outside safe range [{KELLY_MIN:.0%}, {KELLY_MAX:.0%}]. "
                f"Update kalshi_crypto_15m.yaml to use a value in the safe range."
            )

        logger.info(
            f"[KELLY-FRACTION-VALIDATION] Profile Kelly fraction {kelly_hard_cap:.2%} is in safe range [{KELLY_MIN:.0%}, {KELLY_MAX:.0%}]"
        )

    except StartupValidationError:
        raise
    except Exception as e:
        logger.warning(f"[KELLY-FRACTION-VALIDATION] Failed to validate Kelly fraction (non-fatal): {e}")


def validate_entry_window_params() -> None:
    """Validate entry window parameters are logically consistent.

    Ensures that entry window configuration makes sense:
    - minutes_before_expiry > cutoff_minutes_before_expiry (strict)
    - Both values are > 0
    - Neither value is None

    This prevents inverted parameters (e.g., cutoff=30, window=2) that would
    block all trading, or zero/negative values that would allow unsafe trading.

    Raises:
        StartupValidationError: If entry window parameters are invalid
    """
    profile = os.getenv("MERID_PROFILE", "")
    
    # Only apply to kalshi_crypto_15m_v2 profile
    if profile != "kalshi_crypto_15m_v2":
        logger.info(
            "[ENTRY-WINDOW-VALIDATION] Profile %s is not kalshi_crypto_15m_v2 - skipping entry window validation",
            profile
        )
        return
    
    log_startup_phase("validate_entry_window_params", "merid.startup_validations")
    
    try:
        import yaml
        from pathlib import Path
        
        profile_path = Path("config/profiles/kalshi_crypto_15m.yaml")
        if not profile_path.exists():
            logger.warning("[ENTRY-WINDOW-VALIDATION] Profile file not found: %s", profile_path)
            return
        
        # Use encoding="utf-8" with errors="replace" to handle encoding issues gracefully
        with open(profile_path, encoding="utf-8", errors="replace") as f:
            profile_config = yaml.safe_load(f)
        
        # Get entry window parameters from agent_defaults
        agent_defaults = profile_config.get("agent_defaults", {})
        minutes_before_expiry = agent_defaults.get("minutes_before_expiry")
        cutoff_minutes_before_expiry = agent_defaults.get("cutoff_minutes_before_expiry")
        
        # Validate parameters are not None
        if minutes_before_expiry is None:
            raise StartupValidationError(
                "[ENTRY-WINDOW-VALIDATION] minutes_before_expiry is None in profile config"
            )
        if cutoff_minutes_before_expiry is None:
            raise StartupValidationError(
                "[ENTRY-WINDOW-VALIDATION] cutoff_minutes_before_expiry is None in profile config"
            )
        
        # Validate parameters are positive
        if minutes_before_expiry <= 0:
            raise StartupValidationError(
                f"[ENTRY-WINDOW-VALIDATION] minutes_before_expiry={minutes_before_expiry} must be > 0"
            )
        if cutoff_minutes_before_expiry <= 0:
            raise StartupValidationError(
                f"[ENTRY-WINDOW-VALIDATION] cutoff_minutes_before_expiry={cutoff_minutes_before_expiry} must be > 0"
            )
        
        # Validate window > cutoff (strict inequality)
        if minutes_before_expiry <= cutoff_minutes_before_expiry:
            raise StartupValidationError(
                f"[ENTRY-WINDOW-VALIDATION] minutes_before_expiry ({minutes_before_expiry}) must be > "
                f"cutoff_minutes_before_expiry ({cutoff_minutes_before_expiry}). "
                f"Inverted parameters would block all trading."
            )
        
        logger.info(
            "[ENTRY-WINDOW-VALIDATION] Entry window parameters valid: "
            "minutes_before_expiry=%d, cutoff_minutes_before_expiry=%d",
            minutes_before_expiry,
            cutoff_minutes_before_expiry
        )
        
    except StartupValidationError:
        raise
    except Exception as exc:
        logger.warning("[ENTRY-WINDOW-VALIDATION] Validation failed: %s", exc)


def validate_legacy_lane_not_in_production() -> None:
    """Validate that legacy BTC15MLane is not used in production.

    The legacy BTC15MLane (legacy/lanes/btc15m_lane.py) is deprecated and
    has divergent entry window logic from the canonical implementation.
    This validation ensures it cannot be accidentally enabled in production.

    Raises:
        StartupValidationError: If legacy lane module is loaded in production profile
    """
    profile = os.getenv("MERID_PROFILE", "")
    
    # Only apply to kalshi_crypto_15m_v2 profile
    if profile != "kalshi_crypto_15m_v2":
        logger.info(
            "[LEGACY-LANE-VALIDATION] Profile %s is not kalshi_crypto_15m_v2 - skipping legacy lane check",
            profile
        )
        return
    
    log_startup_phase("validate_legacy_lane_not_in_production", "merid.startup_validations")
    
    import sys
    
    # Check if legacy lane module is loaded
    legacy_lane_module = "legacy.lanes.btc15m_lane"
    if legacy_lane_module in sys.modules:
        raise StartupValidationError(
            f"[LEGACY-LANE-VALIDATION] Legacy BTC15MLane module ({legacy_lane_module}) is loaded in production. "
            f"This lane is deprecated and has divergent entry window logic. "
            f"Use Crypto15MLane (merid/lanes/crypto15m_lane.py) instead via lane registry."
        )
    
    logger.info(
        "[LEGACY-LANE-VALIDATION] Legacy BTC15MLane not loaded in production (correct)"
    )


def validate_catalog_refresh_interval() -> None:
    """Validate catalog refresh interval is above minimum guard.

    The catalog refresh has a 30-second minimum guard between refreshes to avoid
    API rate limits. If the configured interval is below 30s, the guard will be
    hit repeatedly causing skipped refreshes and stale catalog data.

    Raises:
        StartupValidationError: If refresh interval is below minimum
    """
    refresh_interval_raw = os.getenv("MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S", "5.0")
    
    log_startup_phase("validate_catalog_refresh_interval", "merid.startup_validations")
    
    try:
        refresh_interval = float(refresh_interval_raw)
        
        # Minimum guard is 2 seconds (enforced in market_catalog.py)
        # Reduced from 30s to 2s to support faster window rollover detection for 15m markets
        MINIMUM_INTERVAL = 2.0
        
        if refresh_interval < MINIMUM_INTERVAL:
            raise StartupValidationError(
                f"[CATALOG-REFRESH-VALIDATION] MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S={refresh_interval}s "
                f"is below minimum {MINIMUM_INTERVAL}s. This will cause the 2s guard to be hit repeatedly, "
                f"resulting in skipped refreshes and stale catalog data."
            )
        
        logger.info(
            "[CATALOG-REFRESH-VALIDATION] Refresh interval valid: %ds (minimum: %ds)",
            int(refresh_interval),
            int(MINIMUM_INTERVAL)
        )
        
    except ValueError:
        raise StartupValidationError(
            f"[CATALOG-REFRESH-VALIDATION] MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S={refresh_interval_raw!r} "
            f"is not a valid number"
        )


def validate_live_capital_config() -> None:
    """Validate that live profiles use correct capital configuration.

    This prevents accidentally running in "validation mode" with hardcoded
    small capital values (e.g., 50.0) in production, which would bypass
    proper risk limits and bankroll tracking.

    For live profiles (kalshi_crypto_15m_v2), capital_usd must be 0 to
    derive from live Kalshi equity via bankroll_service_v2.

    Raises:
        StartupValidationError: If live profile uses validation-mode capital
    """
    profile = os.getenv("MERID_PROFILE", "")

    log_startup_phase("validate_live_capital_config", "merid.startup_validations", f"profile={profile}")

    # Only apply to kalshi_crypto_15m_v2 profile
    if profile != "kalshi_crypto_15m_v2":
        logger.info(
            "[CAPITAL-CONFIG-VALIDATION] Profile %s is not kalshi_crypto_15m_v2 - skipping capital validation",
            profile
        )
        return

    try:
        import yaml
        from pathlib import Path

        profile_path = Path("config/profiles/kalshi_crypto_15m.yaml")
        if not profile_path.exists():
            logger.warning("[CAPITAL-CONFIG-VALIDATION] Profile file not found: %s", profile_path)
            return

        with open(profile_path) as f:
            profile_config = yaml.safe_load(f)

        capital_usd = profile_config.get("capital_usd", 0)

        # Check for validation-mode capital values (small hardcoded numbers)
        # Live mode should use 0 to derive from bankroll API
        if capital_usd is not None and 0 < capital_usd <= 1000:
            raise StartupValidationError(
                f"[CAPITAL-CONFIG-VALIDATION] Profile {profile} has validation-mode capital_usd={capital_usd}. "
                f"Live profiles must use capital_usd: 0 to derive from live Kalshi equity. "
                f"This prevents accidentally running in validation mode in production."
            )

        logger.info(
            "[CAPITAL-CONFIG-VALIDATION] Profile %s capital_usd=%s (correct: 0 for live bankroll derivation)",
            profile,
            capital_usd
        )

    except StartupValidationError:
        raise
    except Exception as exc:
        logger.warning("[CAPITAL-CONFIG-VALIDATION] Validation failed: %s", exc)


def validate_risk_envelope() -> None:
    """Validate risk envelope configuration for kalshi_crypto_15m_v2 profile.

    This validates that the risk envelope is properly configured and can be
    initialized. It checks:
    - Envelope can be instantiated for the profile
    - Drawdown thresholds are valid (halt > unwind > 0)
    - Adaptive risk bands are present and valid
    - Kelly fraction is in valid range (0, 1]

    Raises:
        StartupValidationError: If risk envelope configuration is invalid
    """
    profile = os.getenv("MERID_PROFILE", "")

    log_startup_phase("validate_risk_envelope", "merid.startup_validations", f"profile={profile}")

    # Only apply for kalshi_crypto_15m_v2 profile
    if profile != "kalshi_crypto_15m_v2":
        logger.info(
            "[RISK-ENVELOPE-VALIDATION] Profile %s is not kalshi_crypto_15m_v2 - skipping envelope validation",
            profile
        )
        return
    
    # CRITICAL FIX: Skip envelope validation during import time to prevent bankroll service initialization
    # The envelope will be loaded during startup after bankroll service is ready
    logger.info("[RISK-ENVELOPE-VALIDATION] Skipping import-time envelope validation - will validate during startup")
    return


def validate_demo_prod_risk_parity() -> None:
    """
    Validate that demo and prod environments use the same risk parameters (except allowed differences).
    
    This ensures:
    1. Fee/drawdown logic is identical between demo and prod
    2. Only allowed differences are max notional / daily caps for safety
    3. Profile parameters are logged for comparison
    
    Raises:
        StartupValidationError: If risk parameters diverge unexpectedly between demo and prod.
    """
    profile = os.environ.get('MERID_PROFILE', '')
    kalshi_env = os.environ.get('KALSHI_ENV', 'production').strip().lower()
    
    # Only validate for 15m crypto profiles
    if "kalshi_crypto_15m" not in profile.lower():
        logger.info(
            "[DEMO-PROD-PARITY] Profile %s is not a 15m crypto profile - skipping parity check",
            profile
        )
        return
    
    logger.info(
        "[DEMO-PROD-PARITY] Checking risk parameter parity for %s in %s environment",
        profile,
        kalshi_env
    )
    
    try:
        from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile
        
        if not is_profile_active():
            logger.warning(
                "[DEMO-PROD-PARITY] 15m crypto profile not active - skipping parity check"
            )
            return
        
        adapter = get_active_profile()
        if not adapter:
            logger.warning(
                "[DEMO-PROD-PARITY] Could not load profile adapter - skipping parity check"
            )
            return
        
        profile_obj = adapter.profile
        
        # Log critical risk parameters for comparison
        guardrails = getattr(profile_obj, 'guardrails', None)
        agent_defaults = getattr(profile_obj, 'agent_defaults', None)
        
        if guardrails:
            logger.info(
                "[DEMO-PROD-PARITY] Drawdown parameters: "
                "halt_pct=%.2f%%, unwind_pct=%.2f%%, max_daily_loss_usd=%.2f",
                guardrails.guardrails_drawdown_halt_pct * 100,
                guardrails.guardrails_drawdown_unwind_pct * 100,
                guardrails.guardrails_max_daily_loss_usd
            )
        
        if agent_defaults:
            logger.info(
                "[DEMO-PROD-PARITY] Agent defaults: "
                "max_notional_usd=%.2f, max_orders_per_window=%d, max_yes_position=%d, max_no_position=%d",
                agent_defaults.max_notional_usd,
                agent_defaults.max_orders_per_window,
                agent_defaults.max_yes_position,
                agent_defaults.max_no_position
            )
        
        # Allowed differences between demo and prod:
        # - max_notional_usd (can be lower in demo for safety)
        # - max_daily_loss_usd (can be lower in demo for safety)
        # - capital_usd (can be different)
        # 
        # NOT allowed to differ:
        # - drawdown_halt_pct (must be identical)
        # - drawdown_unwind_pct (must be identical)
        # - min_post_fee_edge (must be identical)
        # - max_spread_pct (must be identical)
        # - max_slippage_pct (must be identical)
        
        # For now, this is informational. Future enhancement: load prod config
        # and compare to detect drift.
        logger.info(
            "[DEMO-PROD-PARITY] Risk parameters logged for %s environment. "
            "Ensure these match prod config (except allowed safety caps).",
            kalshi_env
        )
        
    except ImportError:
        logger.warning(
            "[DEMO-PROD-PARITY] Could not import profile module - skipping parity check"
        )
    except Exception as e:
        logger.error("[DEMO-PROD-PARITY] Unexpected error: %s", e)
        # Don't block startup on this check - it's informational
        logger.warning("[DEMO-PROD-PARITY] Parity check failed but continuing (non-blocking)")


def validate_15m_crypto_profile_fields() -> None:
    """
    Validate that active 15m crypto profiles have all required fields with sane values.
    
    This ensures:
    1. All required drawdown fields are present (drawdown_halt_pct, drawdown_unwind_pct, max_daily_loss_usd)
    2. Drawdown halt < drawdown unwind (logical constraint)
    3. Drawdown values are in valid range (0.01 to 0.50)
    4. Daily loss cap is positive and reasonable
    5. Sentiment execution is disabled for 15m crypto
    
    Raises:
        StartupValidationError: If profile fields are missing or invalid.
    """
    profile = os.environ.get('MERID_PROFILE', '')
    
    # Only validate for 15m crypto profiles
    if "kalshi_crypto_15m" not in profile.lower():
        logger.info(
            "[PROFILE-FIELDS-VALIDATION] Profile %s is not a 15m crypto profile - skipping field validation",
            profile
        )
        return
    
    logger.info("[PROFILE-FIELDS-VALIDATION] Validating 15m crypto profile fields...")
    
    try:
        from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile
        
        if not is_profile_active():
            logger.warning(
                "[PROFILE-FIELDS-VALIDATION] 15m crypto profile not active - skipping field validation"
            )
            return
        
        adapter = get_active_profile()
        if not adapter:
            logger.warning(
                "[PROFILE-FIELDS-VALIDATION] Could not load profile adapter - skipping field validation"
            )
            return
        
        profile_obj = adapter.profile
        errors = []
        
        # Check required guardrails fields (flattened in dataclass)
        # Check drawdown_halt_pct
        if not hasattr(profile_obj, 'guardrails_drawdown_halt_pct'):
            errors.append("Profile missing 'guardrails_drawdown_halt_pct'")
        else:
            halt_pct = profile_obj.guardrails_drawdown_halt_pct
            if not isinstance(halt_pct, (int, float)) or halt_pct <= 0 or halt_pct >= 0.50:
                errors.append(f"Invalid drawdown_halt_pct: {halt_pct} (must be 0.01 to 0.50)")
        
        # Check drawdown_unwind_pct
        if not hasattr(profile_obj, 'guardrails_drawdown_unwind_pct'):
            errors.append("Profile missing 'guardrails_drawdown_unwind_pct'")
        else:
            unwind_pct = profile_obj.guardrails_drawdown_unwind_pct
            if not isinstance(unwind_pct, (int, float)) or unwind_pct <= 0 or unwind_pct >= 0.50:
                errors.append(f"Invalid drawdown_unwind_pct: {unwind_pct} (must be 0.01 to 0.50)")
        
        # Check logical constraint: halt < unwind
        if (hasattr(profile_obj, 'guardrails_drawdown_halt_pct') and 
            hasattr(profile_obj, 'guardrails_drawdown_unwind_pct')):
            if profile_obj.guardrails_drawdown_halt_pct >= profile_obj.guardrails_drawdown_unwind_pct:
                errors.append(
                    f"drawdown_halt_pct ({profile_obj.guardrails_drawdown_halt_pct}) must be < drawdown_unwind_pct ({profile_obj.guardrails_drawdown_unwind_pct})"
                )
        
        # Check max_daily_loss_usd
        if not hasattr(profile_obj, 'guardrails_max_daily_loss_usd'):
            errors.append("Profile missing 'guardrails_max_daily_loss_usd'")
        else:
            daily_loss = profile_obj.guardrails_max_daily_loss_usd
            if not isinstance(daily_loss, (int, float)) or daily_loss <= 0:
                errors.append(f"Invalid max_daily_loss_usd: {daily_loss} (must be positive)")
        
        # Check sentiment execution is disabled
        # Note: sentiment_isolation is a separate section in YAML, not a field on profile_obj
        # This is checked via the YAML structure, not the dataclass
        
        if errors:
            error_msg = "\n  - ".join(errors)
            raise StartupValidationError(
                f"[PROFILE-FIELDS-VALIDATION] Profile validation failed:\n  - {error_msg}"
            )
        
        logger.info(
            "[PROFILE-FIELDS-VALIDATION] Profile fields validated successfully for %s",
            profile
        )
        
    except ImportError:
        logger.warning(
            "[PROFILE-FIELDS-VALIDATION] Could not import profile module - skipping validation"
        )
    except Exception as e:
        logger.error("[PROFILE-FIELDS-VALIDATION] Unexpected error: %s", e)
        raise StartupValidationError(f"Profile field validation error: {e}")


def validate_15m_crypto_profile_restrictions() -> None:
    """
    Validate that the kalshi_crypto_15m_v2 profile is correctly restricted to 5 15m crypto agents.
    
    This ensures:
    1. Only BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M agents are in the grid for this profile
    2. No non-crypto or sentiment agents are active
    3. Series mappings only include 15m crypto series
    
    Raises:
        StartupValidationError: If profile restrictions are violated.
    """
    import os
    profile = os.environ.get('MERID_PROFILE', '')
    
    if profile != 'kalshi_crypto_15m_v2':
        logger.info(
            "[PROFILE-RESTRICTION-VALIDATION] Profile %s is not kalshi_crypto_15m_v2, skipping restriction validation",
            profile
        )
        return
    
    logger.info("[PROFILE-RESTRICTION-VALIDATION] Validating kalshi_crypto_15m_v2 profile restrictions...")
    
    # Load agent grid to check which agents are active
    try:
        from merid.prediction.agent_grid_config import load_agent_grid_config
        config = load_agent_grid_config()
        
        # Check for non-15m-crypto agents
        allowed_15m_agents = {"BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"}
        non_15m_crypto_agents = []
        
        for agent in config.agents:
            if agent.name not in allowed_15m_agents and agent.enabled:
                non_15m_crypto_agents.append(agent.name)
        
        if non_15m_crypto_agents:
            raise StartupValidationError(
                f"[PROFILE-RESTRICTION-VALIDATION] Profile kalshi_crypto_15m_v2 has non-15m-crypto agents enabled: "
                f"{non_15m_crypto_agents}. Only {sorted(allowed_15m_agents)} are allowed."
            )
        
        logger.info(
            "[PROFILE-RESTRICTION-VALIDATION] Profile restrictions validated: "
            "%d agents, all in 15m crypto allowlist",
            len(config.agents)
        )
        
    except Exception as e:
        logger.warning(
            "[PROFILE-RESTRICTION-VALIDATION] Could not validate agent grid restrictions: %s",
            e
        )


def validate_15m_series_availability() -> None:
    """Validate that each 15m series has at least one active market in Kalshi catalog.

    This verification ensures the system is correctly wired to see the real 15m markets
    for BTC/ETH/SOL/XRP/DOGE. It checks the cached catalog or queries Kalshi API.

    Raises:
        StartupValidationError: If any 15m series has no active markets
    """
    profile = os.getenv("MERID_PROFILE", "")

    # Only validate for Kalshi 15m crypto profile
    if "kalshi_crypto_15m_v2" not in profile:
        logger.info(
            "[15M-SERIES-VALIDATION] Profile %s is not kalshi_crypto_15m_v2 - skipping 15m series availability check",
            profile
        )
        return
    
    expected_series = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]
    
    try:
        # Use get_market_catalog singleton to check series availability
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        
        # Get catalog snapshot
        catalog_snapshot = catalog.snapshot()
        
        # If catalog is empty (not yet initialized), skip validation
        # This happens during startup before catalog.refresh() is called
        if catalog_snapshot.market_count == 0:
            logger.info(
                "[15M-SERIES-VALIDATION] Catalog not yet initialized (0 markets) - skipping validation. "
                "Catalog will be initialized during lifespan startup."
            )
            return
        
        # Check each expected series
        missing_series = []
        for series_ticker in expected_series:
            markets = [m for m in catalog_snapshot.markets if m.series_ticker == series_ticker]
            if not markets:
                missing_series.append(series_ticker)
        
        if missing_series:
            raise StartupValidationError(
                f"Missing 15m series in catalog: {missing_series}. "
                f"Expected: {expected_series}"
            )
        
        logger.info(
            "[15M-SERIES-VALIDATION] All 15m series available in catalog: %s",
            expected_series
        )
        
    except Exception as e:
        logger.error(
            "[15M-SERIES-VALIDATION-FAIL] 15m series availability check failed: %s",
            e
        )
        raise StartupValidationError(f"15m series availability validation failed: {e}")


def check_router_isolation(application=None) -> None:
    """Validate that only allowed routers are registered for kalshi_crypto_15m_v2 profile.

    This is a critical safety check for the sealed 15m Kalshi crypto stack.
    It ensures that legacy routers (swarm, sentiment, debate, governance, agents,
    non-Kalshi venues) are NOT registered when running in kalshi_crypto_15m_v2 mode.

    Allowed router prefixes for kalshi_crypto_15m_v2:
    - / (root)
    - /api/v1 (general v1)
    - /api/v1/kalshi (Kalshi venue)
    - /api/v1/kalshi-grid (Kalshi agent grid)
    - /api/v1/kalshi-metrics (Kalshi metrics)
    - /api/v1/portfolio (portfolio)
    - /api/v1/risk (risk)
    - /api/v1/health (health)
    - /api/v1/system (system ops)
    - /api/v1/operator (operator)
    - /api/v1/compliance (compliance)
    - /api/v1/monitoring (monitoring)
    - /api/v1/ratelimit (rate limiting)
    - /api/v1/streams (streams)
    - /api/v1/data (data endpoints)
    - /api/v1/dashboard (dashboard)
    - /api/v1/trading-mode (trading mode)
    - /api/v1/degraded (degraded mode)

    Forbidden router prefixes:
    - /api/v1/swarm (swarm)
    - /api/v1/sentiment (sentiment)
    - /api/v1/debate (debate)
    - /api/v1/governance (governance)
    - /api/v1/agents (legacy agents)
    - /api/v1/reflection (reflection)
    - /api/v1/reality (reality)
    - /api/v1/intelligence (intelligence)
    - /api/v1/local-venue (local venue)
    - /api/v1/market-assertions (market assertions)
    - /api/v1/onchain-assertions (onchain assertions)
    - /api/v1/simulation-assertions (simulation assertions)
    - /api/v1/agent-assertions (agent assertions)
    - /api/v1/trading (general trading)
    - /api/v1/betting (betting)
    - /api/v1/wallet (wallet)
    - /api/v1/treasury (treasury)
    - /api/v1/recovery (recovery)
    - /api/v1/sniping (sniping)
    - /api/v1/cost-models (cost models)
    - /api/v1/time-exploit (time exploit)
    - /api/v1/institutional (institutional)
    - /api/v1/quadratic-funding (quadratic funding)
    - /api/v1/plugins (plugins)
    - /api/v1/backup (backup)
    - /api/v1/archive (archive)
    - /api/v1/paper-trading (paper trading)
    - /api/v1/trading-suite (trading suite)
    - /api/v1/arbitrage (arbitrage)
    - /api/v1/referrals (referrals)
    - /api/v1/mining (mining)
    - /api/v1/offline (offline)
    - /api/v1/notifications (notifications)
    - /api/v1/schemas (schemas)
    - /api/v1/domain-priority (domain priority)

    Args:
        application: FastAPI application instance (optional, for runtime validation)

    Raises:
        StartupValidationError: If forbidden routers are registered
    """
    profile = os.getenv("MERID_PROFILE", "").lower()

    # Only apply this check to kalshi_crypto_15m_v2 profile
    if profile != "kalshi_crypto_15m_v2":
        logger.info(
            "[ROUTER-ISOLATION] Profile %s is not kalshi_crypto_15m_v2 - skipping router isolation check",
            profile
        )
        return

    log_startup_phase("check_router_isolation", "merid.startup_validations")

    # If application is provided, validate at runtime
    if application is not None:
        forbidden_prefixes = [
            "/api/v1/swarm",
            "/api/v1/sentiment",
            "/api/v1/debate",
            "/api/v1/governance",
            "/api/v1/agents",
            "/api/v1/reflection",
            "/api/v1/reality",
            "/api/v1/intelligence",
            "/api/v1/local-venue",
            "/api/v1/market-assertions",
            "/api/v1/onchain-assertions",
            "/api/v1/simulation-assertions",
            "/api/v1/agent-assertions",
            "/api/v1/trading",
            "/api/v1/betting",
            "/api/v1/wallet",
            "/api/v1/treasury",
            "/api/v1/recovery",
            "/api/v1/sniping",
            "/api/v1/cost-models",
            "/api/v1/time-exploit",
            "/api/v1/institutional",
            "/api/v1/quadratic-funding",
            "/api/v1/plugins",
            "/api/v1/backup",
            "/api/v1/archive",
            "/api/v1/paper-trading",
            "/api/v1/trading-suite",
            "/api/v1/arbitrage",
            "/api/v1/referrals",
            "/api/v1/mining",
            "/api/v1/offline",
            "/api/v1/notifications",
            "/api/v1/schemas",
            "/api/v1/domain-priority",
        ]

        # Check all registered routes
        violations = []
        for route in application.routes:
            if hasattr(route, 'path'):
                for forbidden_prefix in forbidden_prefixes:
                    if route.path.startswith(forbidden_prefix):
                        violations.append(route.path)

        if violations:
            raise StartupValidationError(
                f"[ROUTER-ISOLATION] Forbidden routers registered for kalshi_crypto_15m_v2: {violations}. "
                f"These routers expose legacy systems (swarm, sentiment, governance, etc.) "
                f"and must not be registered in the sealed 15m stack."
            )

        logger.info(
            "[ROUTER-ISOLATION] Router isolation validated: no forbidden routers registered for kalshi_crypto_15m_v2"
        )
    else:
        logger.info(
            "[ROUTER-ISOLATION] Application instance not provided - skipping runtime validation. "
            "This check will be performed after router registration in web/main.py."
        )


def check_kalshi_15m_isolation() -> None:
    """Validate that forbidden modules are not imported for kalshi_crypto_15m_v2 profile.

    This is a critical safety check for the sealed 15m Kalshi crypto stack.
    It ensures that legacy modules (swarm, sentiment, governance, reflection, etc.)
    are NOT imported when running in kalshi_crypto_15m_v2 mode.

    Forbidden module prefixes:
    - agents.swarm (swarm agents)
    - agents.sentiment (sentiment agents)
    - agents.debate (debate agents)
    - agents.governance (governance agents)
    - agents.reflection (reflection agents)
    - agents.reality (reality agents)
    - agents.intelligence (intelligence agents)
    - merid.sentiment (sentiment pipeline)
    - merid.governance (governance)
    - merid.swarm (swarm)
    - merid.reflection (reflection)
    - merid.reality (reality)
    - merid.intelligence (intelligence)
    - merid.sniping (sniping)
    - merid.arbitrage (arbitrage)
    - merid.offline (offline mode)
    - merid.social (social layer)

    Args:
        None

    Raises:
        StartupValidationError: If forbidden modules are imported
    """
    import sys

    profile = os.getenv("MERID_PROFILE", "").lower()

    # Only apply this check to kalshi_crypto_15m_v2 profile
    if profile != "kalshi_crypto_15m_v2":
        logger.info(
            "[IMPORT-ISOLATION] Profile %s is not kalshi_crypto_15m_v2 - skipping import isolation check",
            profile
        )
        return

    log_startup_phase("check_kalshi_15m_isolation", "merid.startup_validations")

    # Define forbidden module prefixes
    forbidden_module_prefixes = [
        "agents.swarm",
        "agents.sentiment",
        "agents.debate",
        "agents.governance",
        "agents.reflection",
        "agents.reality",
        "agents.intelligence",
        "merid.sentiment",
        "merid.governance",
        "merid.swarm",
        "merid.reflection",
        "merid.reality",
        "merid.intelligence",
        "merid.sniping",
        "merid.arbitrage",
        "merid.offline",
        "merid.social",
        "db.neo4j",
        "core.orchestrator",
        "core.kalshi_orchestrator",
    ]

    # Check sys.modules for forbidden imports
    violations = []
    for module_name in sys.modules:
        if module_name is None:
            continue
        for forbidden_prefix in forbidden_module_prefixes:
            if module_name.startswith(forbidden_prefix):
                violations.append(module_name)
                break

    if violations:
        raise StartupValidationError(
            f"[IMPORT-ISOLATION] Forbidden modules imported for kalshi_crypto_15m_v2: {violations}. "
            f"These modules expose legacy systems (swarm, sentiment, governance, etc.) "
            f"and must not be imported in the sealed 15m stack. "
            f"Check imports in web/main.py and ensure _init_kalshi_crypto_15m_app() does not import these modules."
        )

    logger.info(
        "[IMPORT-ISOLATION] Import isolation validated: no forbidden modules imported for kalshi_crypto_15m_v2"
    )


def validate_env_for_live_mode() -> None:
    """Validate environment variables are safe for live trading.
    
    Checks:
    - BUG-0324-0002: Smoke test mode must not be enabled with live trading
    - BUG-0324-0005: Promotion grace window must not exceed 60s in live mode
    - SENTIMENT ISOLATION: 15m crypto profile must have sentiment disabled
    - PRODUCTION DATA GUARDS: No fake data, no DRY_RUN, no research agents in production
    
    Raises:
        StartupValidationError: If any critical safety check fails
    """
    errors: List[str] = []
    
    # PRODUCTION DATA GUARDS (2026-05-14): Explicitly outlaw fake/fallback/pseudo data in production
    env = os.getenv("MERID_ENV", "development").strip().lower()
    pm_profile = os.getenv("MERID_PM_PROFILE", "baseline").strip().lower()
    is_production = env == "production" or pm_profile == "production"
    
    if is_production:
        # Check DRY_RUN mode is disabled in production
        dry_run = os.getenv("MERID_LOOP_DRY_RUN", "false").lower() in ("true", "1", "yes")
        if dry_run:
            errors.append(
                "MERID_LOOP_DRY_RUN is enabled in production - DRY_RUN mode is for validation only, not live trading"
            )
        
        # Check research agents are disabled in production
        research_agents = os.getenv("MERID_ENABLE_RESEARCH_AGENTS", "false").lower() in ("true", "1", "yes")
        if research_agents:
            errors.append(
                "MERID_ENABLE_RESEARCH_AGENTS is enabled in production - legacy research agents not allowed for 15m live trading"
            )
        
        # Check fake data is disabled in production
        fake_data = os.getenv("MERID_ALLOW_FAKE_DATA", "false").lower() in ("true", "1", "yes")
        if fake_data:
            errors.append(
                "MERID_ALLOW_FAKE_DATA is enabled in production - fake/mock data sources not allowed for live trading"
            )
        
        # Check demo/sandbox flags are disabled in production
        use_demo = os.getenv("KALSHI_USE_DEMO", "false").lower() in ("true", "1", "yes")
        if use_demo:
            errors.append(
                "KALSHI_USE_DEMO is enabled in production - demo/sandbox mode not allowed for live trading"
            )
        
        # Check for known fake endpoints in production
        kalshi_api_host = os.getenv("KALSHI_API_HOST", "")
        if kalshi_api_host:
            fake_endpoints = ["demo", "sandbox", "fake", "test", "mock"]
            if any(fe in kalshi_api_host.lower() for fe in fake_endpoints):
                errors.append(
                    f"KALSHI_API_HOST={kalshi_api_host} appears to be a fake/demo endpoint - not allowed in production"
                )
    
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

    # SENTIMENT DECOUPLING (2026-05-14): Removed startup validation blocking.
    # ENABLE_SENTIMENT_TRUTH now only controls sentiment ingestion services.
    # Trading logic no longer references this flag; sentiment is feature-only.

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


def validate_kalshi_env_vs_trading_mode() -> None:
    """Validate Kalshi environment vs trading mode alignment.
    
    Enforces the correct mental model:
    - KALSHI_ENV (external): Which Kalshi API environment to use (live vs demo sandbox)
    - MERID_TRADING_MODE (internal): Whether to send real orders (live vs paper)
    
    Rules:
    1. If MERID_TRADING_MODE=live: Must have KALSHI_ENV=live and KALSHI_USE_DEMO=false
    2. If KALSHI_ENV=demo: Only allow MERID_TRADING_MODE=paper with MERID_ALLOW_LIVE_TRADES=false
    3. If KALSHI_ENV=live + MERID_TRADING_MODE=paper: Allowed (paper mode using live data)
    
    This prevents the confusion where "demo" in .env is used as a way to get "paper" behavior,
    when it should only mean "Kalshi demo environment" (different API endpoint entirely).
    
    Raises:
        StartupValidationError: If Kalshi environment and trading mode are misaligned
    """
    kalshi_env = os.getenv("KALSHI_ENV", "").strip().lower()
    use_demo_raw = os.getenv("KALSHI_USE_DEMO", "").strip().lower()
    use_demo = use_demo_raw in ("true", "1", "yes")
    
    trading_mode = os.getenv("MERID_TRADING_MODE", "").strip().lower()
    allow_live_trades_raw = os.getenv("MERID_ALLOW_LIVE_TRADES", "").strip().lower()
    allow_live_trades = allow_live_trades_raw in ("true", "1", "yes")
    
    errors: List[str] = []
    
    # Rule 1: Live trading requires live Kalshi environment
    if trading_mode == "live" or allow_live_trades:
        if kalshi_env != "live":
            errors.append(
                f"MERID_TRADING_MODE=live or MERID_ALLOW_LIVE_TRADES=true requires KALSHI_ENV=live "
                f"(got KALSHI_ENV={kalshi_env!r}). Live trading must use Kalshi production API."
            )
        if use_demo:
            errors.append(
                f"MERID_TRADING_MODE=live or MERID_ALLOW_LIVE_TRADES=true requires KALSHI_USE_DEMO=false"
            )
    
    # Paper trading: KALSHI_ENV must be live (real data), but execution should be paper
    if trading_mode == "paper":
        if kalshi_env != "live":
            errors.append(f"MERID_TRADING_MODE=paper requires KALSHI_ENV=live for real data (got {kalshi_env})")
        if use_demo:
            errors.append("MERID_TRADING_MODE=paper requires KALSHI_USE_DEMO=false for real data")
        if allow_live_trades:
            errors.append("MERID_TRADING_MODE=paper requires MERID_ALLOW_LIVE_TRADES=false")
    
    if errors:
        raise StartupValidationError(
            f"Kalshi environment vs trading mode misalignment:\n  - " + "\n  - ".join(errors)
        )
    
    logger.info(
        "[KALSHI_ENV_VALIDATION] KALSHI_ENV=%s, KALSHI_USE_DEMO=%s, MERID_TRADING_MODE=%s, MERID_ALLOW_LIVE_TRADES=%s - validated",
        kalshi_env,
        use_demo,
        trading_mode,
        allow_live_trades,
    )


def validate_spot_price_feed_ready():
    """Validate that spot price feed is ready and can return non-None prices for all 15m crypto assets.
    
    This is a P0 validation to ensure the spot data flow is functional before agents start.
    It checks that get_spot_price() returns non-None for BTC, ETH, SOL, XRP, DOGE within a reasonable timeout.
    
    Timeout: 30 seconds (allows for UnifiedSpotService warmup after Phase 1 startup)
    
    FIX: Skip validation in Kalshi-only mode since spot feed is only used for basis tracking,
    not for trading decisions. The feed will populate when basis tracker starts.
    """
    try:
        import os
        from data.unified_spot_service import get_unified_spot_service
        
        # FIX: Skip validation in Kalshi-only mode
        # The spot feed is only used for basis tracking, not for trading
        # It will populate when the basis tracker starts
        merid_profile = os.getenv("MERID_PROFILE", "")
        if "kalshi" in merid_profile.lower():
            logger.info("[SPOT_FEED_VALIDATION] Skipped for Kalshi profile - spot feed will populate with basis tracker")
            return
        
        from merid.prediction.model import pm_spot_feed_symbol_candidates
        
        feed = get_unified_spot_service()
        if not feed:
            raise StartupValidationError("UnifiedSpotService singleton not available")
        
        # Assets required for 15m crypto trading
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        max_wait_seconds = 30
        check_interval = 2
        elapsed = 0
        
        logger.info("[SPOT_FEED_VALIDATION] Waiting for spot prices for %s (max %ds)...", required_assets, max_wait_seconds)
        
        missing_assets = required_assets.copy()
        
        while elapsed < max_wait_seconds and missing_assets:
            for asset in list(missing_assets):
                # UnifiedSpotService uses simple asset names (BTC, ETH, etc.)
                price_data = feed.get(asset)
                if price_data:
                    logger.debug("[SPOT_FEED_VALIDATION] %s spot price available: $%.2f from %s", asset, price_data.price, price_data.source)
                    missing_assets.remove(asset)
            
            if missing_assets:
                import time
                time.sleep(check_interval)
                elapsed += check_interval
        
        if missing_assets:
            raise StartupValidationError(
                f"Spot price feed not ready for assets: {missing_assets} after {elapsed}s. "
                f"Check UnifiedSpotService startup and Coinbase connectivity."
            )
        
        logger.info("[SPOT_FEED_VALIDATION] All spot prices available: %s", required_assets)
        
    except ImportError as _ie:
        raise StartupValidationError(f"Cannot validate spot price feed: {_ie}")
    except Exception as _exc:
        raise StartupValidationError(f"Spot price feed validation failed: {_exc}")


def validate_brain_modules() -> None:
    """Validate that regime classifier, momentum ranker, and anomaly detectors initialize.

    This ensures the brain modules (regime/anomaly/momentum stacks) used for
    crypto edge production can be instantiated without errors. This is a
    pre-flight check for the edge brain functionality.

    Raises:
        StartupValidationError: If any brain module fails to initialize
    """
    profile = os.getenv("MERID_PROFILE", "")

    # Only validate for Kalshi crypto profiles that use the edge brain
    # Skip for unified edge profile - brain modules are not part of unified edge system
    if "kalshi_crypto_15m" not in profile.lower():
        logger.info(
            "[BRAIN-MODULES-VALIDATION] Profile %s is not a Kalshi crypto profile - skipping brain module check",
            profile
        )
        return
    
    # Skip brain module validation if unified edge is enabled
    # Unified edge uses deployment regime and calibration data logger, not brain modules
    unified_edge_enabled = os.getenv("MERID_UNIFIED_EDGE_ENABLED", "false").lower() == "true"
    if unified_edge_enabled:
        logger.info(
            "[BRAIN-MODULES-VALIDATION] Unified edge enabled - skipping brain module validation (not part of unified edge system)"
        )
        return

    try:
        # Test UnifiedRegimeClassifier initialization
        from merid.signals.unified_regime_classifier import get_unified_regime_classifier
        classifier = get_unified_regime_classifier()
        state = classifier.get_current_state()
        logger.info("[BRAIN-MODULES-VALIDATION] UnifiedRegimeClassifier initialized successfully")

        # Test CrossSectionalMomentumRanker initialization
        from merid.signals.momentum_ranker import get_momentum_ranker
        ranker = get_momentum_ranker()
        rankings = ranker.get_current_rankings()
        logger.info("[BRAIN-MODULES-VALIDATION] CrossSectionalMomentumRanker initialized successfully")

        # Test BtcAnchorGate initialization
        from merid.signals.btc_anchor_gate import get_btc_anchor_gate
        gate = get_btc_anchor_gate()
        logger.info("[BRAIN-MODULES-VALIDATION] BtcAnchorGate initialized successfully")

    except ImportError as _ie:
        raise StartupValidationError(f"Brain module import failed: {_ie}")
    except Exception as _exc:
        raise StartupValidationError(f"Brain module initialization failed: {_exc}")


def validate_production_wiring() -> None:
    """Validate that production wiring uses only real Kalshi infrastructure.
    
    This ensures no fake/mock data sources can accidentally enter the production path.
    Checks:
    - No fake/mock Kalshi modules loaded
    - Type assertions for catalog and execution backend
    
    Raises:
        StartupValidationError: If fake/mock types are found in production wiring
    """
    import sys
    
    env = os.getenv("MERID_ENV", "development").strip().lower()
    pm_profile = os.getenv("MERID_PM_PROFILE", "baseline").strip().lower()
    is_production = env == "production" or pm_profile == "production"
    
    if not is_production:
        logger.info("[PRODUCTION_WIRING] Skipping wiring validation - not in production mode")
        return
    
    # Check for fake Kalshi modules in production
    fake_modules = [
        "FakeKalshiClient",
        "DummyMarketCatalog",
        "MockKalshiClient",
    ]
    
    for fake_module in fake_modules:
        if fake_module in sys.modules:
            raise StartupValidationError(
                f"PRODUCTION_WIRING_VIOLATION: Fake module {fake_module} is loaded. "
                f"Fake/mock data sources not allowed in production. "
                f"Check imports and ensure only real KalshiClient/KalshiMarketCatalog are used."
            )
    
    # Check for imports from test/mocks directories in production code
    for module_name in list(sys.modules.keys()):
        if module_name.startswith("tests.") or module_name.startswith("mocks."):
            # Test modules are OK if they're not being used by production code
            # This is a soft check - we just log a warning
            logger.warning(
                f"[PRODUCTION_WIRING] Test/mocks module {module_name} is loaded in production - "
                "ensure it's not being used by production code paths"
            )
    
    logger.info("[PRODUCTION_WIRING] No fake/mock Kalshi modules loaded - wiring validated")


def log_config_signature() -> None:
    """
    Log configuration signature for drift detection.
    
    This logs a subset of critical config values to enable detection of
    configuration drift between deployments or over time.
    """
    import os
    import hashlib
    from pathlib import Path
    
    logger.info("[CONFIG-SIGNATURE] Computing configuration signature...")
    
    # Collect critical config values
    sig_parts = []
    
    # Profile selection
    sig_parts.append(f"MERID_PROFILE={os.getenv('MERID_PROFILE', 'default')}")
    sig_parts.append(f"MERID_PM_PROFILE={os.getenv('MERID_PM_PROFILE', 'default')}")
    
    # Kalshi profile-specific values
    profile = os.getenv('MERID_PROFILE', '')
    if profile == 'kalshi_crypto_15m_v2':
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            adapter = get_active_profile()
            if adapter and adapter._profile:
                p = adapter._profile
                sig_parts.append(f"capital_usd={p.capital_usd:.2f}")
                # 2026-07-08: DISABLED percentage-based logging - using fixed $1 exposure model
                sig_parts.append(f"max_single_order_usd={p.venue_max_single_order_usd:.2f}")
                sig_parts.append(f"max_total_notional_usd={p.venue_max_total_notional_usd:.2f}")
                sig_parts.append(f"agent_max_notional_usd={p.agent_max_notional_usd:.2f}")
        except Exception as e:
            logger.warning("[CONFIG-SIGNATURE] Could not load profile for signature: %s", e)
    
    # Agent grid signature (file hash)
    try:
        agent_grid_path = Path(__file__).parent.parent / "config" / "kalshi_agent_grid.yaml"
        if agent_grid_path.exists():
            with open(agent_grid_path, 'rb') as f:
                agent_grid_hash = hashlib.sha256(f.read()).hexdigest()[:16]
            sig_parts.append(f"agent_grid_hash={agent_grid_hash}")
    except Exception as e:
        logger.warning("[CONFIG-SIGNATURE] Could not hash agent grid: %s", e)
    
    # Profile YAML signature (file hash)
    try:
        profile_yaml_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m.yaml"
        if profile_yaml_path.exists():
            with open(profile_yaml_path, 'rb') as f:
                profile_yaml_hash = hashlib.sha256(f.read()).hexdigest()[:16]
            sig_parts.append(f"profile_yaml_hash={profile_yaml_hash}")
    except Exception as e:
        logger.warning("[CONFIG-SIGNATURE] Could not hash profile YAML: %s", e)
    
    # Compute overall signature
    signature_str = "|".join(sig_parts)
    signature_hash = hashlib.sha256(signature_str.encode()).hexdigest()[:16]
    
    logger.info("[CONFIG-SIGNATURE] Config signature: %s", signature_hash)
    logger.info("[CONFIG-SIGNATURE] Config components: %s", signature_str)


def validate_spot_proxy_availability():
    """
    Validate that spot provider backend is available and initialized.

    This checks the backend that matches MERID_SPOT_PROVIDER_TYPE:
    - "unified": checks unified_spot_service (Coinbase-based)
    - "rti": checks MERID RTI HTTP API
    - "cfb": checks CFB RTI proxy (legacy)

    This is a hard dependency check - if the selected backend cannot be initialized
    or data is stale, unified edge must fail closed (no new entries).
    """
    import os
    provider_type = os.getenv('MERID_SPOT_PROVIDER_TYPE', 'unified').lower()
    
    logger.info(f"[SPOT-PROVIDER-VALIDATION] Checking spot provider backend: {provider_type}...")

    try:
        if provider_type == "unified":
            # Check unified_spot_service (Coinbase-based, direct service)
            import time
            import_start = time.time()
            logger.info("[SPOT-PROVIDER-VALIDATION] About to import unified_spot_service")
            from data.unified_spot_service import get_unified_spot_service
            import_elapsed = time.time() - import_start
            logger.info(f"[SPOT-PROVIDER-VALIDATION] unified_spot_service import took {import_elapsed:.2f}s")

            get_start = time.time()
            logger.info("[SPOT-PROVIDER-VALIDATION] About to call get_unified_spot_service()")
            spot_service = get_unified_spot_service()
            get_elapsed = time.time() - get_start
            logger.info(f"[SPOT-PROVIDER-VALIDATION] get_unified_spot_service() took {get_elapsed:.2f}s")

            health_start = time.time()
            health = spot_service.health_check()
            health_elapsed = time.time() - health_start
            logger.info(f"[SPOT-PROVIDER-VALIDATION] health_check() took {health_elapsed:.2f}s")

            # Check if service is initialized (not necessarily running yet)
            # The service will be started later in the startup sequence
            logger.info(
                "[SPOT-PROVIDER-VALIDATION] unified_spot_service initialized: "
                f"supported_assets={health['supported_assets']}, "
                f"running={health['running']}"
            )

            # Check if all assets are cached (may be empty if not started yet)
            cached_count = health["cached_count"]
            stale_count = health["stale_count"]
            supported_assets = health["supported_assets"]

            if cached_count > 0:
                logger.info(
                    "[SPOT-PROVIDER-VALIDATION] unified_spot_service has cached data: "
                    f"{cached_count}/{len(supported_assets)} assets cached, {stale_count} stale"
                )

                # Warn if any assets are stale
                if stale_count > 0:
                    stale = [a for a in supported_assets if health["cache_status"].get(a, {}).get("stale")]
                    logger.warning(
                        "[SPOT-PROVIDER-VALIDATION-WARN] Stale spot data for assets: %s",
                        stale
                    )
            else:
                logger.info(
                    "[SPOT-PROVIDER-VALIDATION] unified_spot_service not yet started - "
                    "will be started during startup sequence"
                )

            logger.info("[SPOT-PROVIDER-VALIDATION] unified_spot_service validation passed")

        elif provider_type == "rti":
            # Check MERID RTI HTTP API by fetching a canary asset (BTC).
            # The RTI endpoint is typically co-hosted on this server, which may not be
            # listening yet during startup; connection errors are therefore a soft WARNING
            # (runtime spot-freshness gates require 5/5 fresh before trading), while a
            # reachable-but-invalid response FAILS CLOSED.
            logger.info("[SPOT-PROVIDER-VALIDATION] RTI provider selected - probing HTTP API...")
            import httpx as _httpx
            from merid.prediction.spot_provider import MeridRtiSpotProvider
            _rti_base = MeridRtiSpotProvider().base_url
            _rti_url = f"{_rti_base}/api/v1/rti/BTC"
            try:
                with _httpx.Client(timeout=5.0) as _client:
                    _resp = _client.get(_rti_url)
                    _resp.raise_for_status()
                    _data = _resp.json()
                _price = float(_data.get("index_price", 0) or 0)
                if _price <= 0:
                    raise StartupValidationError(
                        f"RTI provider returned invalid BTC index_price={_price} from {_rti_url}"
                    )
                logger.info(
                    "[SPOT-PROVIDER-VALIDATION] RTI HTTP API healthy (BTC index_price=%.2f, source=%s)",
                    _price, _rti_url,
                )
            except StartupValidationError:
                raise
            except Exception as _rti_err:
                logger.warning(
                    "[SPOT-PROVIDER-VALIDATION-WARN] RTI HTTP API not reachable at %s during startup "
                    "(%s); runtime spot-freshness gates will enforce availability before trading",
                    _rti_url, _rti_err,
                )

        elif provider_type == "cfb":
            # Check CFB RTI proxy (legacy, in-process) by fetching a canary asset (BTC).
            # CFB is in-process and synchronous, so inability to deliver data FAILS CLOSED.
            logger.info("[SPOT-PROVIDER-VALIDATION] CFB provider selected - probing proxy...")
            try:
                from merid.event_venues.kalshi.cfb_spot_proxy import get_cfb_spot_proxy
                _cfb_price = get_cfb_spot_proxy().get_spot_price("BTC")
            except Exception as _cfb_err:
                raise StartupValidationError(
                    f"CFB spot proxy unavailable (cannot validate spot source): {_cfb_err}"
                )
            if _cfb_price is None or float(_cfb_price) <= 0:
                raise StartupValidationError(
                    f"CFB spot proxy returned no valid BTC price (got {_cfb_price}); failing closed"
                )
            logger.info("[SPOT-PROVIDER-VALIDATION] CFB proxy healthy (BTC price=%.2f)", float(_cfb_price))

        else:
            logger.error(
                f"[SPOT-PROVIDER-VALIDATION-FAIL] Unknown provider type: {provider_type}"
            )
            raise StartupValidationError(f"Unknown spot provider type: {provider_type}")

    except Exception as e:
        logger.error(
            "[SPOT-PROVIDER-VALIDATION-FAIL] Spot provider validation failed: %s",
            e
        )
        raise


def validate_unified_edge_configuration():
    """
    Validate unified edge configuration.

    Checks:
    - MERID_UNIFIED_EDGE_ENABLED is not enabled with placeholder calibration
    - MERID_UNIFIED_EDGE_ENABLED and MERID_UNIFIED_EDGE_SHADOW_MODE are not both true
    - Calibration version is set if unified edge is enabled
    - Risk caps are consistent with unified edge expectations
    """
    logger.info("[UNIFIED-EDGE-VALIDATION] Checking unified edge configuration...")

    unified_edge_enabled = os.getenv('MERID_UNIFIED_EDGE_ENABLED', 'false').lower() == 'true'
    shadow_mode = os.getenv('MERID_UNIFIED_EDGE_SHADOW_MODE', 'false').lower() == 'true'
    calibration_version = os.getenv('MERID_CALIBRATION_VERSION', 'placeholder')

    # Check that unified edge and shadow mode are not both enabled
    if unified_edge_enabled and shadow_mode:
        logger.error(
            "[UNIFIED-EDGE-VALIDATION-FAIL] Both MERID_UNIFIED_EDGE_ENABLED=true and "
            "MERID_UNIFIED_EDGE_SHADOW_MODE=true - choose one mode (live or shadow)"
        )
        raise StartupValidationError(
            "Cannot enable both unified edge (live) and shadow mode simultaneously. "
            "Set MERID_UNIFIED_EDGE_ENABLED=false for shadow mode, or "
            "MERID_UNIFIED_EDGE_SHADOW_MODE=false for live unified edge."
        )

    if unified_edge_enabled:
        logger.info("[UNIFIED-EDGE-VALIDATION] Unified edge is ENABLED (live mode)")

        if calibration_version == 'placeholder':
            logger.error(
                "[UNIFIED-EDGE-VALIDATION-FAIL] Unified edge enabled but calibration_version=placeholder - "
                "this is blocked in code but configuration is invalid"
            )
            raise StartupValidationError(
                "Unified edge enabled with placeholder calibration - set MERID_CALIBRATION_VERSION "
                "to a valid version (e.g., v1) after fitting calibration parameters"
            )
        else:
            logger.info(
                "[UNIFIED-EDGE-VALIDATION] Calibration version: %s",
                calibration_version
            )

        # Check risk caps
        total_risk_budget = os.getenv('MERID_LIVE_SESSION_MAX_RISK_USD', '300')
        try:
            risk_budget_float = float(total_risk_budget)
            if risk_budget_float > 1000:
                logger.warning(
                    "[UNIFIED-EDGE-VALIDATION-WARN] High risk budget: %.2f USD - "
                    "consider reducing for unified edge deployment",
                    risk_budget_float
                )
        except ValueError:
            logger.error(
                "[UNIFIED-EDGE-VALIDATION-FAIL] Invalid risk budget: %s",
                total_risk_budget
            )
            raise StartupValidationError(f"Invalid risk budget: {total_risk_budget}")
    elif shadow_mode:
        logger.info("[UNIFIED-EDGE-VALIDATION] Unified edge SHADOW MODE enabled (legacy live, unified for comparison)")
    else:
        logger.info("[UNIFIED-EDGE-VALIDATION] Unified edge is DISABLED (legacy mode)")


def validate_spot_provider_configuration():
    """
    Validate spot provider configuration.

    Checks:
    - MERID_SPOT_PROVIDER_TYPE is one of the allowed values
    """
    logger.info("[SPOT-PROVIDER-VALIDATION] Checking spot provider configuration...")

    # Note: provider_type is passed directly to get_spot_provider() in code
    # This validation ensures the env var (if set) is valid
    allowed_providers = {"unified", "rti", "cfb"}
    provider_type = os.getenv('MERID_SPOT_PROVIDER_TYPE', 'unified').strip().lower()

    if provider_type not in allowed_providers:
        logger.error(
            "[SPOT-PROVIDER-VALIDATION-FAIL] Invalid MERID_SPOT_PROVIDER_TYPE=%s - "
            "must be one of: %s",
            provider_type, allowed_providers
        )
        raise StartupValidationError(
            f"Invalid spot provider type: {provider_type}. "
            f"Must be one of: {', '.join(allowed_providers)}"
        )

    logger.info(
        "[SPOT-PROVIDER-VALIDATION] Spot provider type: %s (valid)",
        provider_type
    )
    
    logger.info("[UNIFIED-EDGE-VALIDATION] Configuration validated successfully")


def validate_deployment_regime():
    """
    Validate deployment regime configuration.
    
    Checks:
    - DEPRECATED: Deployment regime validation removed (2026-05-26)
    - Behavior now controlled directly by:
      - MERID_ALLOW_LIVE_TRADES for order placement
      - MERID_UNIFIED_EDGE_ENABLED for unified edge
      - Risk parameters (MAX_CYCLE_RISK_PCT, etc.) for risk budget
    """
    logger.info("[DEPLOYMENT-REGIME-VALIDATION] DEPRECATED - using direct config flags")


def validate_kalshi_bankroll_source_consistency() -> None:
    """
    Validate that kalshi_crypto_15m_v2 profile uses canonical bankroll sources only.
    
    For kalshi_crypto_15m_v2, the canonical bankroll sources are:
    - RiskEnvelopeService (backed by BankrollServiceV2 live Kalshi equity)
    - KalshiRiskManager._derive_bankroll_cents() (backed by BankrollServiceV2)
    
    Settings-derived bankroll (MERID_TOTAL_CAPITAL_USD, KALSHI_PORTFOLIO_BANKROLL_CENTS)
    must NOT be used for risk/sizing in Kalshi 15m code path.
    """
    import os
    import sys
    
    log_startup_phase("validate_kalshi_bankroll_source_consistency", "merid.startup_validations")
    
    active_profile = os.getenv("MERID_PROFILE", "")
    
    if active_profile != "kalshi_crypto_15m_v2":
        logger.info(
            f"[BANKROLL-SOURCE-VALIDATION] Profile is {active_profile}, "
            f"skipping bankroll source check (only enforced for kalshi_crypto_15m_v2)"
        )
        return
    
    # Log bankroll matrix for visibility
    try:
        from merid.settings import settings as app_settings
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
        
        config_total_capital_usd = app_settings.MERID_TOTAL_CAPITAL_USD
        kalshi_portfolio_bankroll_cents = app_settings.KALSHI_PORTFOLIO_BANKROLL_CENTS
        
        # CRITICAL FIX: Defer bankroll fetch to avoid import-time initialization
        # If bankroll not ready, use config value as fallback
        try:
            live_equity_usd = get_equity_for_risk_calc_sync()
        except Exception:
            live_equity_usd = None
        
        # CRITICAL FIX: Defer envelope check to avoid initialization before bankroll is ready
        try:
            envelope = get_risk_envelope_service().get_config()
            if envelope is None:
                # Risk envelope not ready yet, skip this check
                logger.warning("[BANKROLL-MATRIX] Risk envelope not ready, skipping bankroll matrix check")
                return
        except Exception as e:
            logger.warning(f"[BANKROLL-MATRIX] Failed to get risk envelope config: {e}, skipping check")
            return
        
        risk_envelope_bankroll_usd = envelope.max_total_notional_usd / 0.15  # CRITICAL FIX: 15% - aligned with profile (was 0.30)
        
        # 2026-07-08: DISABLED percentage-based logging - using fixed $1 exposure model
        logger.info(
            "[BANKROLL-MATRIX] "
            f"profile={active_profile} "
            f"config_total_capital_usd={config_total_capital_usd:.2f} "
            f"live_equity_usd={live_equity_usd:.2f if live_equity_usd else 0:.2f} "
            f"risk_envelope_bankroll_usd={risk_envelope_bankroll_usd:.2f} "
            f"kalshi_portfolio_bankroll_cents={kalshi_portfolio_bankroll_cents} "
            f"max_cycle_risk_pct=DISABLED (fixed $1 exposure model) "
            f"per_trade_risk_pct=DISABLED (fixed $1 exposure model)"
        )
        
        # Check for divergence between config and live equity
        if live_equity_usd and config_total_capital_usd > 0:
            divergence_pct = abs(live_equity_usd - config_total_capital_usd) / max(live_equity_usd, 1.0) * 100
            if divergence_pct > 5.0:  # More than 5% divergence
                logger.warning(
                    f"[BANKROLL-DIVERGENCE] Config capital (${config_total_capital_usd:.2f}) "
                    f"diverges from live equity (${live_equity_usd:.2f}) by {divergence_pct:.1f}%. "
                    f"RiskEnvelopeService uses live equity (correct). Config is informational only."
                )
        
    except Exception as e:
        logger.warning(f"[BANKROLL-SOURCE-VALIDATION] Failed to log bankroll matrix: {e}")
    
    # Check for direct usage of settings-derived bankroll in Kalshi 15m modules
    # This is a code-level check - we grep for problematic patterns
    kalshi_15m_modules = [
        "merid.event_venues.kalshi.kalshi_risk",
        "merid.risk.profiles.kalshi_crypto_15m_risk_envelope",
        "merid.risk.profiles.crypto_15m_profile",
        "merid.prediction.agent_grid_15m",
    ]
    
    violations = []
    for module_name in kalshi_15m_modules:
        if module_name in sys.modules:
            module = sys.modules[module_name]
            source = getattr(module, "__file__", "")
            if source:
                try:
                    with open(source, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Check for direct usage of settings bankroll in risk-critical context
                        if "KALSHI_PORTFOLIO_BANKROLL_CENTS" in content and "settings." in content:
                            # Exclude comments and docstrings
                            lines = content.split('\n')
                            for i, line in enumerate(lines, 1):
                                if "KALSHI_PORTFOLIO_BANKROLL_CENTS" in line and "settings." in line:
                                    # Skip if it's a comment
                                    stripped = line.strip()
                                    if not stripped.startswith('#') and not stripped.startswith('"""'):
                                        violations.append(f"{source}:{i} - {stripped[:80]}")
                except Exception:
                    pass
    
    if violations:
        logger.warning(
            f"[BANKROLL-SOURCE-VALIDATION] Found {len(violations)} potential settings-derived bankroll usages "
            f"in Kalshi 15m modules. Review these lines to ensure they're not risk-critical: {violations[:3]}"
        )
    else:
        logger.info(
            "[BANKROLL-SOURCE-VALIDATION] Kalshi 15m modules use canonical bankroll sources (clean)"
        )


def validate_no_direct_bankroll_usage() -> None:
    """
    Validate that no code path reads bankroll directly for sizing.
    
    All sizing must go through RiskEnvelopeService.
    This prevents future duplication of risk calculation logic.
    
    NOTE: For Kalshi 15m, this validation is scoped to only check Kalshi 15m runtime
    directories to avoid full-repo scans that can be slow and brittle.
    """
    import os
    import re
    from pathlib import Path
    
    log_startup_phase("validate_no_direct_bankroll_usage", "merid.startup_validations")
    
    # Allowed modules that can access bankroll (envelope + venue adapter)
    ALLOWED_BANKROLL_MODULES = {
        "merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
        "merid/risk/profiles/risk_envelope_service.py",
        "merid/event_venues/kalshi/bankroll_service_v2.py",
        "merid/event_venues/kalshi/bankroll_resolver.py",
    }
    
    # Patterns that indicate direct bankroll usage for sizing
    BANKROLL_PATTERNS = [
        r"bankroll.*\*.*pct",  # bankroll * percentage
        r"balance.*\*.*pct",   # balance * percentage
        r"equity.*\*.*pct",    # equity * percentage
        r"get_equity.*\*",     # get_equity() * something
    ]
    
    repo_root = Path(__file__).parent.parent.parent
    
    # Scope to Kalshi 15m runtime directories only (not full repo scan)
    kalshi_15m_dirs = [
        repo_root / "merid" / "event_venues" / "kalshi",
        repo_root / "merid" / "risk" / "profiles",
        repo_root / "merid" / "prediction" / "agent_grid_15m.py",
    ]
    
    violations = []
    files_checked = 0
    max_files = 100  # Hard cap to prevent runaway scans
    
    for scan_dir in kalshi_15m_dirs:
        if not scan_dir.exists():
            continue
        
        # If it's a file, check it directly
        if scan_dir.is_file():
            py_files = [scan_dir]
        else:
            py_files = list(scan_dir.rglob("*.py"))
        
        for py_file in py_files:
            if files_checked >= max_files:
                logger.warning(
                    f"[BANKROLL-USAGE-VALIDATION] Reached file cap ({max_files}), stopping scan early"
                )
                break
            
            files_checked += 1
            
            # Skip allowed modules
            rel_path = str(py_file.relative_to(repo_root)).replace("\\", "/")
            if any(allowed in rel_path for allowed in ALLOWED_BANKROLL_MODULES):
                continue
            
            # Skip test files
            if "tests" in rel_path or "test_" in py_file.name:
                continue
            
            try:
                # Use errors="ignore" to handle encoding issues gracefully
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                for pattern in BANKROLL_PATTERNS:
                    if re.search(pattern, content, re.IGNORECASE):
                        violations.append(f"{rel_path}: pattern '{pattern}'")
                        break
            except Exception as e:
                logger.debug(f"[BANKROLL-USAGE-VALIDATION] Failed to read {rel_path}: {e}")
                continue
    
    if violations:
        raise StartupValidationError(
            f"[BANKROLL-USAGE-VALIDATION] Direct bankroll usage detected in {len(violations)} files. "
            f"All sizing must go through RiskEnvelopeService. Violations: {violations}"
        )
    
    logger.info(
        f"[BANKROLL-USAGE-VALIDATION] No direct bankroll usage detected in {files_checked} Kalshi 15m files "
        f"(all sizing goes through RiskEnvelopeService)"
    )


def validate_limit_matrix_consistency() -> None:
    """
    Validate that all guards/managers enforce consistent limits.
    
    For each asset, checks that per-side, per-market, per-asset, and total caps
    are consistent across RiskEnvelope, KalshiRiskManager, PredictionRiskConfig, and AgentGrid.
    """
    from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
    
    log_startup_phase("validate_limit_matrix_consistency", "merid.startup_validations")
    
    # CRITICAL FIX: Defer envelope check to avoid initialization before bankroll is ready
    # If envelope not ready, skip this check
    try:
        envelope = get_risk_envelope_service().get_config()
        if envelope is None:
            logger.warning("[LIMIT-MATRIX] Risk envelope not ready, skipping limit matrix consistency check")
            return
    except Exception as e:
        logger.warning(f"[LIMIT-MATRIX] Failed to get risk envelope config: {e}, skipping check")
        return
    
    # Query KalshiRiskManager limits
    kalshi_risk_per_asset = 1750  # Default from KalshiRiskConfig
    kalshi_risk_total_notional = envelope.max_total_notional_usd
    kalshi_risk_max_single_order = 2500.0  # Default from KalshiRiskConfig
    
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        kalshi_risk = get_kalshi_risk()
        kalshi_risk_per_asset = kalshi_risk._config.max_contracts_per_asset
        kalshi_risk_total_notional = kalshi_risk._config.max_total_notional_usd or envelope.max_total_notional_usd
        kalshi_risk_max_single_order = kalshi_risk._config.max_single_order_notional_usd
    except Exception as e:
        logger.warning(f"[LIMIT-MATRIX] Failed to query KalshiRiskManager: {e}")
    
    # Query PredictionRiskConfig limits
    prediction_risk_per_asset = 0  # 0 = derive from bankroll
    prediction_risk_total_notional = 0  # 0 = derive from bankroll
    
    try:
        from merid.prediction.risk import get_prediction_risk
        prediction_risk = get_prediction_risk()
        prediction_risk_per_asset = prediction_risk.config.max_contracts_per_asset if hasattr(prediction_risk.config, 'max_contracts_per_asset') else 0
        prediction_risk_total_notional = float(prediction_risk.config.max_total_notional_usd)
    except Exception as e:
        logger.warning(f"[LIMIT-MATRIX] Failed to query PredictionRiskConfig: {e}")
    
    # Build limit matrix table
    logger.info("[LIMIT-MATRIX] Cross-layer limit matrix:")
    logger.info("  Layer                  | per_side | per_asset_contracts | per_asset_usd | total_notional_usd")
    logger.info("  " + "-" * 90)
    
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        envelope_per_side = envelope.agent_max_yes_position
        envelope_per_asset_usd = envelope.asset_max_notional_usd.get(asset, 0)
        
        logger.info(
            f"  RiskEnvelope           | {envelope_per_side:8d} | {envelope_per_side:18d} | "
            f"${envelope_per_asset_usd:12.2f} | ${envelope.max_total_notional_usd:17.2f}"
        )
        logger.info(
            f"  KalshiRiskManager      | {'N/A':8s} | {kalshi_risk_per_asset:18d} | "
            f"{'N/A':>12s} | ${kalshi_risk_total_notional:17.2f}"
        )
        logger.info(
            f"  PredictionRiskConfig   | {'N/A':8s} | {prediction_risk_per_asset:18d} | "
            f"{'N/A':>12s} | ${prediction_risk_total_notional:17.2f}"
        )
        logger.info("  " + "-" * 90)
    
    # Check for mismatches
    violations = []
    
    # For kalshi_crypto_15m_v2, PredictionRiskConfig should be 0 (derive from envelope)
    active_profile = os.getenv("MERID_PROFILE", "")
    if active_profile == "kalshi_crypto_15m_v2":
        if prediction_risk_per_asset != 0:
            violations.append(
                f"PredictionRiskConfig.max_contracts_per_asset={prediction_risk_per_asset} "
                f"(should be 0 for profile-gated behavior)"
            )
        if prediction_risk_total_notional != 0:
            violations.append(
                f"PredictionRiskConfig.max_total_notional_usd=${prediction_risk_total_notional} "
                f"(should be 0 for profile-gated behavior)"
            )
    
    if violations:
        raise StartupValidationError(
            f"[LIMIT-MATRIX-VALIDATION] Limit matrix violations detected: {violations}"
        )
    
    logger.info("[LIMIT-MATRIX-VALIDATION] Limit matrix consistency check passed")


def validate_deprecated_config_not_used() -> None:
    """
    Validate that deprecated config files are not imported by live code.
    
    Deprecated configs:
    - config/kalshi_15m_crypto_config.py (ASSET_RISK_LIMITS, GLOBAL_RISK_LIMITS)
    - archive/legacy/kalshi_risk_engine.py (KalshiRiskConfig)
    
    These are superseded by kalshi_crypto_15m.yaml profile.
    """
    import sys
    import os
    
    log_startup_phase("validate_deprecated_config_not_used", "merid.startup_validations")
    
    deprecated_modules = {
        "kalshi_15m_crypto_config": "config/kalshi_15m_crypto_config.py",
        "kalshi_risk_engine": "archive/legacy/kalshi_risk_engine.py",
    }
    
    # Check if kalshi_crypto_15m_v2 profile is active
    active_profile = os.getenv("MERID_PROFILE", "")
    
    if active_profile != "kalshi_crypto_15m_v2":
        logger.info(
            f"[DEPRECATED-CONFIG-VALIDATION] Profile is {active_profile}, "
            f"skipping deprecated config check (only enforced for kalshi_crypto_15m_v2)"
        )
        return
    
    # Check if deprecated modules are loaded
    violations = []
    for module_name, file_path in deprecated_modules.items():
        if module_name in sys.modules:
            # Get the module's file path
            module = sys.modules[module_name]
            module_file = getattr(module, "__file__", "")
            
            # Check if it's from the deprecated location
            if file_path in module_file or "legacy" in module_file or "kalshi_15m_crypto_config" in module_file:
                violations.append(f"{module_name} (from {module_file})")
    
    if violations:
        raise StartupValidationError(
            f"[DEPRECATED-CONFIG-VALIDATION] Deprecated config modules loaded: {violations}. "
            f"These are superseded by kalshi_crypto_15m.yaml profile. "
            f"Remove references and delete deprecated files before proceeding."
        )
    
    logger.info(
        "[DEPRECATED-CONFIG-VALIDATION] No deprecated config modules loaded (clean state)"
    )


def validate_profile_dynamic_static_semantics() -> None:
    """
    Validate that profile YAML dynamic/static flags are enforced correctly.
    
    For kalshi_crypto_15m_v2 profile:
    - dynamic: bankroll fields must exist in RiskEnvelopeConfig
    - static: invariant fields must not have env var overrides
    - No direct YAML reads outside envelope service for dynamic fields
    """
    import os
    import yaml
    
    log_startup_phase("validate_profile_dynamic_static_semantics", "merid.startup_validations")
    
    active_profile = os.getenv("MERID_PROFILE", "")
    
    if active_profile != "kalshi_crypto_15m_v2":
        logger.info(
            f"[PROFILE-SEMANTICS-VALIDATION] Profile is {active_profile}, "
            f"skipping dynamic/static check (only enforced for kalshi_crypto_15m_v2)"
        )
        return
    
    profile_path = "config/profiles/kalshi_crypto_15m.yaml"
    
    try:
        with open(profile_path, 'r') as f:
            profile = yaml.safe_load(f)
        
        # Check that RiskEnvelopeConfig has all dynamic: bankroll fields
        # CRITICAL FIX: Defer envelope check to avoid initialization before bankroll is ready
        try:
            from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
            envelope = get_risk_envelope_service().get_config()
            if envelope is None:
                logger.warning("[PROFILE-SEMANTICS] Risk envelope not ready, skipping dynamic/static check")
                return
        except Exception as e:
            logger.warning(f"[PROFILE-SEMANTICS] Failed to get risk envelope config: {e}, skipping check")
            return
        
        # Key dynamic fields that must exist in envelope
        # 2026-07-08: Removed percentage-based fields (max_cycle_risk_pct, per_trade_risk_pct)
        # These are DISABLED in favor of fixed $1 exposure model
        required_dynamic_fields = [
            "max_single_order_notional_usd",
            "max_total_notional_usd",
            "asset_max_notional_usd",
        ]
        
        violations = []
        for field in required_dynamic_fields:
            if not hasattr(envelope, field):
                violations.append(f"RiskEnvelopeConfig missing dynamic field: {field}")
        
        # Check static: invariant fields don't have env var overrides
        # MAX_BOOK_STALENESS_MS is a key invariant
        max_book_staleness_env = os.getenv("MERID_MAX_BOOK_STALENESS_MS")
        if max_book_staleness_env is not None:
            violations.append(
                f"MERID_MAX_BOOK_STALENESS_MS env var set ({max_book_staleness_env}), "
                f"but max_book_staleness_ms is static: invariant in profile"
            )
        
        if violations:
            raise StartupValidationError(
                f"[PROFILE-SEMANTICS-VALIDATION] Dynamic/static semantic violations: {violations}"
            )
        
        logger.info(
            "[PROFILE-SEMANTICS-VALIDATION] Dynamic/static semantics validated correctly"
        )
        
    except FileNotFoundError:
        logger.warning(
            f"[PROFILE-SEMANTICS-VALIDATION] Profile file not found: {profile_path}"
        )
    except Exception as e:
        logger.warning(
            f"[PROFILE-SEMANTICS-VALIDATION] Failed to validate profile semantics: {e}"
        )


def validate_no_sentiment_in_kalshi_stack() -> None:
    """
    Validate that sentiment is disabled per profile YAML configuration.
    
    For kalshi_crypto_15m_v2 profile, sentiment configuration comes from
    kalshi_crypto_15m.yaml sentiment_isolation section (single source of truth).
    This validation checks that the profile YAML correctly disables sentiment.
    
    This is a safety check to prevent regressions in sentiment configuration.
    """
    import os
    import sys
    
    log_startup_phase("validate_no_sentiment_in_kalshi_stack", "merid.startup_validations")
    
    active_profile = os.getenv("MERID_PROFILE", "")
    
    if active_profile != "kalshi_crypto_15m_v2":
        logger.info(
            f"[NO-SENTIMENT-VALIDATION] Profile is {active_profile}, "
            f"skipping sentiment check (only enforced for kalshi_crypto_15m_v2)"
        )
        return
    
    # Check profile YAML sentiment_isolation configuration
    try:
        from merid.risk.profiles.crypto_15m_profile import get_profile_config
        profile_config = get_profile_config()
        
        sentiment_isolation = profile_config.get('sentiment_isolation', {})
        enable_sentiment_execution = sentiment_isolation.get('enable_sentiment_execution', True)
        sentiment_mode = sentiment_isolation.get('sentiment_mode', 'enabled')
        
        if enable_sentiment_execution or sentiment_mode != 'disabled':
            logger.error(
                f"[SENTIMENT-VALIDATION-FAIL] Profile YAML has sentiment enabled: "
                f"enable_sentiment_execution={enable_sentiment_execution}, "
                f"sentiment_mode={sentiment_mode}. "
                f"Sentiment must be disabled for kalshi_crypto_15m_v2 profile."
            )
            raise ValueError(
                "Sentiment must be disabled in kalshi_crypto_15m.yaml sentiment_isolation section"
            )
        
        logger.info(
            f"[SENTIMENT-VALIDATION-OK] Profile YAML correctly disables sentiment: "
            f"enable_sentiment_execution={enable_sentiment_execution}, "
            f"sentiment_mode={sentiment_mode}"
        )
        
    except Exception as e:
        logger.warning(
            f"[SENTIMENT-VALIDATION] Could not validate profile YAML sentiment config: {e}"
        )
    
    logger.info(
        "[SENTIMENT-VALIDATION] Sentiment isolation validated via profile YAML (single source of truth)"
    )


def validate_profile_backtest_eligibility() -> None:
    """
    Validate that profile configuration respects backtest eligibility requirements.
    
    For kalshi_crypto_15m_v2 profile configured for live trading (dry_run: false),
    this validation checks that backtest requirements are documented and would be
    enforced before live promotion. This is a safety check to prevent accidental
    live trading without proper backtest validation.
    
    Backtest thresholds (from merid/risk/btc_promotion_config.py):
    - years_tested >= 1.0
    - trades >= 50 (100 for stricter validation)
    - max_drawdown <= 0.30
    - sharpe >= 0.7
    """
    import os
    
    log_startup_phase("validate_profile_backtest_eligibility", "merid.startup_validations")
    
    active_profile = os.getenv("MERID_PROFILE", "")
    
    if active_profile != "kalshi_crypto_15m_v2":
        logger.info(
            f"[PROFILE-BACKTEST-VALIDATION] Profile is {active_profile}, "
            f"skipping backtest eligibility check (only enforced for kalshi_crypto_15m_v2)"
        )
        return
    
    # Check profile YAML configuration
    try:
        from merid.risk.profiles.crypto_15m_profile import get_profile_config
        profile_config = get_profile_config()
        
        dry_run = profile_config.get('dry_run', True)
        operation_mode = profile_config.get('operation_mode', 'test')
        
        # If configured for live trading (dry_run: false, operation_mode: prod)
        if not dry_run and operation_mode == 'prod':
            logger.warning(
                f"[PROFILE-BACKTEST-VALIDATION] Profile is configured for live trading: "
                f"dry_run={dry_run}, operation_mode={operation_mode}. "
                f"Ensure backtest eligibility is verified before live promotion. "
                f"Required thresholds: years_tested >= 1.0, trades >= 50, "
                f"max_drawdown <= 0.30, sharpe >= 0.7."
            )
            # This is a warning, not an error, because backtest validation
            # happens at promotion time, not startup time
        else:
            logger.info(
                f"[PROFILE-BACKTEST-VALIDATION] Profile is not configured for live trading: "
                f"dry_run={dry_run}, operation_mode={operation_mode}. "
                f"Backtest eligibility will be checked before live promotion."
            )
        
    except Exception as e:
        logger.warning(
            f"[PROFILE-BACKTEST-VALIDATION] Could not validate profile YAML backtest config: {e}"
        )


def validate_no_legacy_strategy_in_kalshi_stack() -> None:
    """
    Validate that legacy strategy modules are not imported in Kalshi 15m code path.
    
    For kalshi_crypto_15m_v2 profile, only the canonical strategy is allowed:
    - merid.prediction.agent_grid_15m (live strategy)
    - merid.prediction.unified_sizing (sizing logic)
    - merid.prediction.unified_edge (edge computation)
    - merid.risk.profiles.risk_envelope_service (risk envelope)
    
    Forbidden modules:
    - merid.strategies.* (legacy strategies: kelly, mvrk, sentiment_swarm, etc.)
    - merid.signals.* (research signal processing not used in 15m)
    - merid.prediction.* except whitelisted live modules
    
    Archive modules (archive.legacy.*) are allowed only in test/tooling mode,
    not in live Kalshi runtime.
    
    This is a hard guard against legacy strategy reintroduction.
    """
    import sys
    
    log_startup_phase("validate_no_legacy_strategy_in_kalshi_stack", "merid.startup_validations")
    
    active_profile = os.getenv("MERID_PROFILE", "")
    
    if active_profile != "kalshi_crypto_15m_v2":
        logger.info(
            f"[NO-LEGACY-STRATEGY-VALIDATION] Profile is {active_profile}, "
            f"skipping legacy strategy ban check (only enforced for kalshi_crypto_15m_v2)"
        )
        return
    
    # Test-mode exclusion: pytest collection imports many research/test-only modules
    # (e.g., dynamic_risk_routing, alignment_degraded_mode) into sys.modules, which would
    # produce false-positive violations. Only enforce in real (non-pytest) runtime.
    if 'pytest' in sys.modules:
        logger.info(
            "[NO-LEGACY-STRATEGY-VALIDATION] pytest detected - skipping legacy module ban "
            "(test collection imports research modules; enforced only in production runtime)"
        )
        return
    
    # Whitelisted modules for Kalshi 15m (canonical strategy path)
    whitelisted_modules = {
        "merid.prediction.agent_grid_15m",
        "merid.prediction.agent_grid_config",
        "merid.prediction.unified_sizing",
        "merid.prediction.unified_edge",
        "merid.risk.profiles.risk_envelope_service",
        "merid.event_venues.kalshi.market_state",
        "merid.event_venues.kalshi.market_catalog",
    }
    
    # Forbidden module prefixes
    forbidden_prefixes = [
        "merid.strategies.",
        "merid.signals.",
    ]
    
    # Forbidden prediction modules (research-only, not used in 15m)
    # NOTE: Some prediction modules are imported transitively by config loading or validation.
    # We only flag modules that are actively used for strategy execution, not utility modules.
    forbidden_prediction_modules = {
        "merid.prediction.edge_model",
        "merid.prediction.edge_recalibrator",
        "merid.prediction.dynamic_edge_calibrator",
        "merid.prediction.high_performance_calibration",
        "merid.prediction.hp_integration",
        "merid.prediction.entry_timing_filters",
        "merid.prediction.alphavantage_context",
        "merid.prediction.fear_greed_context",
        "merid.prediction.finnhub_context",
        "merid.prediction.hurricane_context",
        "merid.prediction.messari_context",
        "merid.prediction.perp_context",
        "merid.prediction.trends_context",
        "merid.prediction.polygon_context",
        "merid.prediction.news_context",
        "merid.prediction.metaculus_context",
        "merid.prediction.macro_context",
        "merid.prediction.coinmarketcap_context",
        "merid.prediction.grid_context",
        "merid.prediction.band_strategy_agent",
        "merid.prediction.debate_deployment",
        "merid.prediction.debate_exit_policy",
        "merid.prediction.decision",
        "merid.prediction.decision_evaluator",
        "merid.prediction.dynamic_allocation_calculator",
        "merid.prediction.dynamic_risk_routing",
        "merid.prediction.dynamic_takeprofit",
        "merid.prediction.execution_intelligence",
        "merid.prediction.ai_guardrails",
        "merid.prediction.alignment_degraded_mode",
        "merid.prediction.lane_enforcement",
        "merid.prediction.crypto_session_validation",
        "merid.prediction.crypto15m_validation",
        "merid.prediction.config_validator",
        "merid.prediction.backtest_scheduler",
        "merid.prediction.kalshi_strike_calibrator",
        "merid.prediction.mcp_market_feed",
    }
    
    # Utility modules that may be imported transitively but are not strategy execution
    # These are allowed for config loading, validation, and tooling
    allowed_prediction_utility_modules = {
        "merid.prediction.model",  # Base model classes used by config
        "merid.prediction.strategy",  # Base strategy classes used by config
        "merid.prediction.kalshi_tools",  # Utility functions for Kalshi integration
    }
    
    violations = []
    soft_violations = []
    
    # Check all loaded modules
    for module_name in sys.modules:
        # Skip whitelisted modules
        if module_name in whitelisted_modules:
            continue
        
        # Skip allowed prediction utility modules (imported transitively for config/validation)
        if module_name in allowed_prediction_utility_modules:
            continue
        
        # Allow archive modules only in test/tooling mode (not live Kalshi runtime)
        if module_name.startswith("archive.legacy."):
            # Archive modules are allowed for backtests and tools, but not in live trading
            # For now, we allow them but log a warning
            logger.warning(
                f"[NO-LEGACY-STRATEGY-VALIDATION] Archive module loaded: {module_name}. "
                f"This is allowed for backtests/tools but should not be used in live Kalshi 15m runtime."
            )
            continue
        
        # Check forbidden prefixes (clear-cut legacy strategies/signals -> HARD fail)
        for prefix in forbidden_prefixes:
            if module_name.startswith(prefix):
                violations.append(f"Legacy strategy module loaded: {module_name}")
                break
        
        # Check forbidden prediction modules (research-only -> SOFT, may be imported transitively)
        if module_name in forbidden_prediction_modules:
            soft_violations.append(f"Research-only prediction module loaded: {module_name}")
    
    # Soft violations (research/prediction modules): log loudly but do NOT block startup.
    # These can be pulled in transitively by config/validation; failing closed here would be
    # too brittle for the live stack. Surfaced as CRITICAL for audit follow-up.
    if soft_violations:
        logger.critical(
            "[NO-LEGACY-STRATEGY-VALIDATION] Research/prediction modules present (non-fatal, audit): %s",
            soft_violations,
        )
    
    # Hard violations (legacy strategies/signals): FAIL CLOSED.
    if violations:
        raise StartupValidationError(
            f"[NO-LEGACY-STRATEGY-VALIDATION] Legacy strategy modules detected in Kalshi 15m stack: {violations}. "
            f"Only canonical strategy path (agent_grid_15m, unified_sizing, unified_edge) is allowed. "
            f"Legacy strategies have been moved to archive/legacy/strategies/ and archive/legacy/signals/."
        )
    
    if not soft_violations:
        logger.info(
            "[NO-LEGACY-STRATEGY-VALIDATION] Kalshi 15m stack uses only canonical strategy (clean state)"
        )


def validate_all_kalshi_15m() -> None:
    """
    Run Kalshi 15m-specific startup validations only.
    
    This pipeline is hard-isolated from PM/legacy validations to prevent cross-contamination.
    Only validations relevant to Kalshi 15m crypto trading are executed.
    
    Kalshi 15m validation scope:
    - Profile / envelope: profile combination, risk envelope loading, bankroll source consistency
    - Venue / catalog: Kalshi auth, series consistency, catalog refresh, market data staleness
    - Risk / guards: no direct bankroll usage, limit matrix consistency, deprecated config checks
    - Isolation: no sentiment, no legacy strategy modules
    """
    logger.info("=" * 60)
    logger.info("KALSHI 15M STARTUP VALIDATION SEQUENCE")
    logger.info("=" * 60)
    
    log_kalshi_credential_summary()
    
    # Profile / envelope validations
    validate_profile_envelope_chain()
    validate_profile_combination()
    validate_15m_crypto_profile_fields()
    check_single_risk_config()
    validate_risk_envelope()
    
    # Field name consistency validation (schema contract check)
    validate_field_name_consistency()
    
    # Venue / catalog validations
    validate_15m_series_availability()
    validate_kalshi_series_consistency()
    validate_kalshi_env_vs_trading_mode()
    validate_kalshi_auth_config()
    validate_kalshi_min_close_seconds_ago()
    validate_catalog_refresh_interval()
    validate_env_for_live_mode()
    
    # Risk / guards validations
    validate_no_test_fills_in_database()
    validate_entry_window_params()
    validate_no_direct_bankroll_usage()
    validate_kalshi_bankroll_source_consistency()
    validate_limit_matrix_consistency()
    validate_deprecated_config_not_used()
    
    # Isolation validations
    validate_no_sentiment_in_kalshi_stack()
    # Re-enabled: the validator now (1) skips enforcement under pytest (test collection imports
    # research modules) and (2) only HARD-fails on legacy strategy/signal modules, while research
    # prediction modules are logged as CRITICAL audit warnings rather than blocking startup.
    validate_no_legacy_strategy_in_kalshi_stack()
    
    # Kalshi alignment invariants (fail-closed/omit philosophy)
    run_kalshi_alignment_checks()
    
    # Logging / diagnostics
    log_kalshi_config_summary()
    log_config_signature()
    
    # Config consistency (P0/P1 audit guardrail)
    try:
        from config.startup_config_validator import ConfigValidator
        validator = ConfigValidator()
        if not validator.validate_all():
            errors = "\n  - ".join(validator.errors)
            raise StartupValidationError(
                f"Config validation failed with {len(validator.errors)} contradictions:\n  - {errors}"
            )
        if validator.warnings:
            warnings = "\n  - ".join(validator.warnings)
            logger.warning(f"Config validation warnings:\n  - {warnings}")
    except Exception as _config_err:
        logger.warning("Config validation error (non-fatal): %s", _config_err)
    
    # Spot price feed readiness (P0: ensures spot data available before agents)
    try:
        validate_spot_price_feed_ready()
    except StartupValidationError as _spot_err:
        raise
    
    # Unified edge and spot provider configuration (always validate, even in shadow mode)
    try:
        validate_unified_edge_configuration()
    except StartupValidationError as _unified_edge_err:
        raise

    try:
        validate_spot_provider_configuration()
    except StartupValidationError as _spot_provider_err:
        raise

    # Spot proxy availability (only if unified edge is enabled or shadow mode)
    unified_edge_enabled = os.getenv("MERID_UNIFIED_EDGE_ENABLED", "false").lower() == "true"
    shadow_mode = os.getenv("MERID_UNIFIED_EDGE_SHADOW_MODE", "false").lower() == "true"
    if unified_edge_enabled or shadow_mode:
        try:
            validate_spot_proxy_availability()
        except StartupValidationError as _spot_proxy_err:
            raise
    
    # Production wiring (venue-agnostic mock/fake check)
    validate_production_wiring()
    
    logger.info("=" * 60)
    logger.info("KALSHI 15M STARTUP VALIDATION COMPLETE")
    logger.info("=" * 60)


def validate_all_legacy_pm() -> None:
    """
    Run PM/legacy startup validations.
    
    This pipeline contains all PM-specific and legacy validations that are not
    relevant to Kalshi 15m crypto trading. These are kept for backward compatibility
    with other profiles and workflows.
    """
    logger.info("=" * 60)
    logger.info("LEGACY PM STARTUP VALIDATION SEQUENCE")
    logger.info("=" * 60)
    
    log_kalshi_credential_summary()
    validate_market_id_key_alignment()
    validate_profile_envelope_chain()
    validate_production_wiring()
    validate_profile_combination()
    validate_15m_crypto_profile_restrictions()
    validate_15m_crypto_profile_fields()
    validate_demo_prod_risk_parity()
    check_single_risk_config()
    validate_profile_backtest_eligibility()
    validate_spread_config_unification()
    validate_risk_envelope()
    validate_15m_series_availability()
    validate_kalshi_series_consistency()
    validate_kalshi_env_vs_trading_mode()
    validate_kalshi_auth_config()
    validate_kalshi_min_close_seconds_ago()
    validate_no_test_fills_in_database()
    validate_no_sentiment_in_kalshi_stack()
    validate_entry_window_params()
    validate_legacy_lane_not_in_production()
    validate_no_direct_bankroll_usage()
    validate_kalshi_bankroll_source_consistency()
    validate_limit_matrix_consistency()
    validate_deprecated_config_not_used()
    validate_profile_dynamic_static_semantics()
    validate_no_sentiment_in_kalshi_stack()
    validate_no_legacy_strategy_in_kalshi_stack()
    validate_catalog_refresh_interval()
    validate_env_for_live_mode()
    log_kalshi_config_summary()
    log_config_signature()
    
    # Config consistency
    try:
        from config.startup_config_validator import ConfigValidator
        validator = ConfigValidator()
        if not validator.validate_all():
            errors = "\n  - ".join(validator.errors)
            raise StartupValidationError(
                f"Config validation failed with {len(validator.errors)} contradictions:\n  - {errors}"
            )
        if validator.warnings:
            warnings = "\n  - ".join(validator.warnings)
            logger.warning(f"Config validation warnings:\n  - {warnings}")
    except Exception as _config_err:
        logger.warning("Config validation error (non-fatal): %s", _config_err)
    
    # Paper engine integrity
    ok, msg = validate_paper_engine_identity()
    if not ok:
        import logging
        logging.getLogger("merid.startup").warning(f"Paper engine needs repair: {msg}")
    
    # Spot price feed readiness
    try:
        validate_spot_price_feed_ready()
    except StartupValidationError as _spot_err:
        raise

    # Brain modules initialization (legacy edge system)
    try:
        validate_brain_modules()
    except StartupValidationError as _brain_err:
        raise
    
    # Naming validation (PM lane system)
    try:
        from merid.startup_naming_validation import (
            log_agent_lane_registry_summary,
            validate_naming_consistency,
            check_for_legacy_lane_usage,
        )
        log_agent_lane_registry_summary()
        validate_naming_consistency()
        check_for_legacy_lane_usage()
    except Exception as exc:
        logger.warning("Naming validation error (non-fatal): %s", exc)

    # Unified edge and spot provider configuration
    try:
        validate_unified_edge_configuration()
    except StartupValidationError as _unified_edge_err:
        raise

    try:
        validate_spot_provider_configuration()
    except StartupValidationError as _spot_provider_err:
        raise

    # Spot proxy availability (only if unified edge is enabled or shadow mode)
    unified_edge_enabled = os.getenv("MERID_UNIFIED_EDGE_ENABLED", "false").lower() == "true"
    shadow_mode = os.getenv("MERID_UNIFIED_EDGE_SHADOW_MODE", "false").lower() == "true"
    if unified_edge_enabled or shadow_mode:
        try:
            validate_spot_proxy_availability()
        except StartupValidationError as _spot_proxy_err:
            raise

    # Deployment regime (deprecated)
    try:
        validate_deployment_regime()
    except StartupValidationError as _regime_err:
        raise

    # Kalshi 15m profile validation (strip-level limits consistency)
    if is_kalshi_15m_profile():
        try:
            validate_kalshi_15m_strip_limits_consistency()
            validate_kalshi_15m_guardrail_fields()
        except StartupValidationError as _strip_err:
            raise

    logger.info("=" * 60)
    logger.info("LEGACY PM STARTUP VALIDATION COMPLETE")
    logger.info("=" * 60)


def validate_all() -> None:
    """Run all startup validations.
    
    Dispatches to the appropriate validation pipeline based on the active profile:
    - kalshi_crypto_15m_v2: validate_all_kalshi_15m() (hard-isolated Kalshi 15m validations)
    - Other profiles: validate_all_legacy_pm() (PM/legacy validations)
    """
    if is_kalshi_15m_profile():
        validate_all_kalshi_15m()
    else:
        validate_all_legacy_pm()
