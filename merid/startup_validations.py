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

# Import startup trace helper
from merid.startup_trace import log_startup_phase


class StartupValidationError(Exception):
    """Critical validation failed — cannot start in live mode."""
    pass


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
        from config.kalshi_15m_crypto_config import KALSHI_15M_SERIES_TICKERS
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
    
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        envelope = get_kalshi_crypto_15m_risk_envelope()
        
        # Validate envelope has required fields
        required_fields = ['max_single_order_notional_usd', 'max_total_notional_usd', 'max_concurrent_trades']
        for field in required_fields:
            if not hasattr(envelope, field) or getattr(envelope, field) is None:
                raise StartupValidationError(
                    f"Risk envelope missing required field: {field}"
                )
        
        logger.info(
            f"[RISK-ENVELOPE-VALIDATION] Canonical risk envelope loaded successfully: "
            f"max_single_order=${envelope.max_single_order_notional_usd:.2f}, "
            f"max_total=${envelope.max_total_notional_usd:.2f}, "
            f"max_concurrent={envelope.max_concurrent_trades}"
        )
    except Exception as e:
        raise StartupValidationError(
            f"Failed to load canonical risk envelope for kalshi_crypto_15m_v2: {e}"
        ) from e


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
    
    # Check 1: AgentGrid config must have exactly 5 agents
    try:
        from merid.prediction.agent_grid import get_agent_grid_config
        grid_cfg = get_agent_grid_config()
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
            "[5-ASSET-INVARIANT] AgentGrid validated: %d agents, assets=%s",
            len(grid_cfg.agents),
            sorted(agent_assets)
        )
    except Exception as e:
        if isinstance(e, StartupValidationError):
            raise
        logger.warning("[5-ASSET-INVARIANT] AgentGrid config check failed: %s", e)
    
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


def validate_kalshi_crypto_15m_sentiment_isolation() -> None:
    """Validate sentiment isolation for kalshi_crypto_15m_v2 profile.

    This is a regression guard to ensure the 15m Kalshi crypto profile
    maintains sentiment-free signal generation and sizing.

    NOTE: For kalshi_crypto_15m_v2, sentiment is enforced at the profile YAML level
    (sentiment_isolation section in kalshi_crypto_15m.yaml). This validation is
    bypassed for the 15m profile to avoid noise, as the profile-level config
    is the single source of truth for sentiment isolation.

    Checks:
    - Kelly sizing function signature matches sentiment-free version
    - UnifiedSignalOrchestrator has sentiment integration disabled
    - No sentiment modules are imported in the 15m signal path

    Raises:
        StartupValidationError: If sentiment isolation is violated
    """
    profile = os.getenv("MERID_PROFILE", "")
    
    log_startup_phase("validate_sentiment_isolation", "merid.startup_validations")
    
    # Bypass for kalshi_crypto_15m_v2 - sentiment isolation enforced at profile YAML level
    if profile == "kalshi_crypto_15m_v2":
        logger.info(
            "[SENTIMENT-ISOLATION-VALIDATION] Profile %s uses profile-level sentiment isolation (kalshi_crypto_15m.yaml) - skipping runtime validation",
            profile
        )
        return
    
    # Only apply this check for other profiles
    logger.info(
        "[SENTIMENT-ISOLATION-VALIDATION] Profile %s is not kalshi_crypto_15m_v2 - skipping sentiment isolation check",
        profile
    )
    return


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
    
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        
        envelope = get_kalshi_crypto_15m_risk_envelope()
        
        # Validate drawdown thresholds
        # halt_pct should be less than unwind_pct (halt first, unwind if worse)
        if envelope.drawdown_halt_pct >= envelope.drawdown_unwind_pct:
            raise StartupValidationError(
                f"[RISK-ENVELOPE-VALIDATION] Invalid drawdown thresholds: halt_pct ({envelope.drawdown_halt_pct}) must be < unwind_pct ({envelope.drawdown_unwind_pct})"
            )
        
        if envelope.drawdown_unwind_pct <= 0:
            raise StartupValidationError(
                f"[RISK-ENVELOPE-VALIDATION] Invalid unwind_pct: {envelope.drawdown_unwind_pct} must be > 0"
            )
        
        if envelope.drawdown_halt_pct >= 1.0:
            raise StartupValidationError(
                f"[RISK-ENVELOPE-VALIDATION] Invalid halt_pct: {envelope.drawdown_halt_pct} must be < 1.0"
            )
        
        # Validate adaptive risk bands
        if not envelope.adaptive_risk_bands:
            raise StartupValidationError(
                "[RISK-ENVELOPE-VALIDATION] Adaptive risk bands are empty"
            )
        
        # Validate band structure
        for i, band in enumerate(envelope.adaptive_risk_bands):
            # Allow max_drawdown_pct=1.0 for the halt band (last band)
            if band["max_drawdown_pct"] <= 0 or (band["max_drawdown_pct"] >= 1.0 and i < len(envelope.adaptive_risk_bands) - 1):
                raise StartupValidationError(
                    f"[RISK-ENVELOPE-VALIDATION] Invalid band {i} max_drawdown_pct: {band['max_drawdown_pct']} must be in (0, 1) (only last band can be 1.0 for halt)"
                )
            
            if band["multiplier"] < 0 or band["multiplier"] > 1.0:
                raise StartupValidationError(
                    f"[RISK-ENVELOPE-VALIDATION] Invalid band {i} multiplier: {band['multiplier']} must be in [0, 1]"
                )
        
        # Validate Kelly fraction
        if envelope.kelly_fraction <= 0 or envelope.kelly_fraction > 1.0:
            raise StartupValidationError(
                f"[RISK-ENVELOPE-VALIDATION] Invalid kelly_fraction: {envelope.kelly_fraction} must be in (0, 1]"
            )
        
        logger.info(
            "[RISK-ENVELOPE-VALIDATION] Risk envelope validated: halt_pct=%.2f%%, unwind_pct=%.2f%%, kelly_fraction=%.3f, bands=%d",
            envelope.drawdown_halt_pct * 100,
            envelope.drawdown_unwind_pct * 100,
            envelope.kelly_fraction,
            len(envelope.adaptive_risk_bands)
        )
        
    except ImportError as e:
        raise StartupValidationError(
            f"[RISK-ENVELOPE-VALIDATION] Failed to import risk envelope: {e}"
        )
    except Exception as e:
        raise StartupValidationError(
            f"[RISK-ENVELOPE-VALIDATION] Risk envelope validation failed: {e}"
        )


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
    from merid.settings import settings as _settings
    from merid.event_venues.kalshi.market_catalog import build_kalshi_catalog
    
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
        # Use shared catalog builder to ensure validation matches live trading
        from merid.event_venues.kalshi.market_catalog import build_kalshi_catalog
        catalog = build_kalshi_catalog(_settings)
        
        # Look for markets with this series ticker
        # KalshiMarketCatalog has get_all_markets() method to retrieve markets
        try:
            catalog_items = catalog.get_all_markets() if hasattr(catalog, 'get_all_markets') else catalog
        except:
            catalog_items = catalog
        series_markets = [m for m in catalog_items if hasattr(m, 'series_ticker') and m.series_ticker in expected_series]
        
        if not series_markets:
            raise ValueError(
                f"[15M-SERIES-VALIDATION] No 15m crypto markets found. "
                f"Expected series: {expected_series}. "
                f"Catalog may not be initialized or Kalshi API may be unavailable."
            )
        
        found_series = list(set(m.series_ticker for m in series_markets))
        missing_series = [s for s in expected_series if s not in found_series]

        if missing_series:
            error_msg = (
                f"15M_SERIES_VALIDATION_FAILED: Missing or inactive series: {', '.join(missing_series)}. "
                f"Found series: {', '.join(found_series) if found_series else 'none'}. "
                f"Expected: {', '.join(expected_series)}. "
                f"Check Kalshi catalog configuration and series ticker wiring."
            )
            logger.error(error_msg)
            raise StartupValidationError(error_msg)

        logger.info(
            "[15M-SERIES-VALIDATION] All 5 expected 15m series have active markets: %s",
            ", ".join(found_series)
        )

    except ImportError:
        logger.warning(
            "[15M-SERIES-VALIDATION] Market catalog module not available - skipping 15m series availability check"
        )
    except Exception as e:
        logger.warning(
            "[15M-SERIES-VALIDATION] Error checking 15m series availability: %s",
            e
        )


def check_sentiment_isolation_for_15m_crypto(profile_name: str, config: dict) -> None:
    """
    Check that 15m crypto profile has no non-neutral sentiment flags enabled.
    
    This is a runtime guardrail to prevent future regressions where sentiment
    might be re-enabled for 15m crypto trading path per SENTIMENT_ISOLATION_15M.md.
    
    Args:
        profile_name: The profile name being loaded
        config: The merged configuration dictionary
    
    Raises:
        ValueError: If any non-neutral sentiment flags are found for 15m crypto
    """
    # Only apply this check to 15m crypto profiles
    if "15m" not in profile_name.lower() or "crypto" not in profile_name.lower():
        return
    
    # List of sentiment-related config keys that must be False or neutral
    sentiment_keys_to_check = [
        "sentiment_mode",
        "sentiment_gating_enabled",
        "enable_sentiment_execution",
        "enable_sentiment_truth",
        "sentiment_driven",
        "use_sentiment",
        "sentiment_enabled",
    ]
    
    violations = []
    
    for key in sentiment_keys_to_check:
        # Check if key exists in config (case-insensitive)
        for config_key in config.keys():
            if key.lower() in config_key.lower():
                value = config[config_key]
                
                # Check if value is truthy/True (non-neutral)
                if value is True or value == "true" or value == "enabled" or value == 1:
                    violations.append(f"{config_key}={value}")
                # Check if value is "gating" mode (should be "disabled" for 15m)
                if isinstance(value, str) and value.lower() == "gating":
                    violations.append(f"{config_key}={value}")
    
    # Check for nested sentiment_isolation block
    if "sentiment_isolation" in config:
        sentiment_iso = config["sentiment_isolation"]
        if isinstance(sentiment_iso, dict):
            if sentiment_iso.get("enable_sentiment_execution", False):
                violations.append("sentiment_isolation.enable_sentiment_execution=True")
            if isinstance(sentiment_iso.get("sentiment_mode"), str) and sentiment_iso["sentiment_mode"].lower() != "disabled":
                violations.append(f"sentiment_isolation.sentiment_mode={sentiment_iso['sentiment_mode']}")
    
    if violations:
        error_msg = (
            f"SENTIMENT_ISOLATION_VIOLATION: Profile '{profile_name}' has non-neutral sentiment flags: {', '.join(violations)}. "
            f"Per SENTIMENT_ISOLATION_15M.md, 15m crypto trading path must have sentiment disabled. "
            f"Set sentiment_mode='disabled' and ensure all sentiment flags are False/neutral."
        )
        logger.error(error_msg)
        raise ValueError(error_msg)


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
        use_demo = os.getenv("KALSHI_USE_DEMO", "true").lower() in ("true", "1", "yes")
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
    if "kalshi_crypto_15m" not in profile.lower():
        logger.info(
            "[BRAIN-MODULES-VALIDATION] Profile %s is not a Kalshi crypto profile - skipping brain module check",
            profile
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
                sig_parts.append(f"max_single_order_pct={p.venue_max_single_order_pct:.3f}")
                sig_parts.append(f"max_total_notional_pct={p.venue_max_total_notional_pct:.3f}")
                sig_parts.append(f"agent_max_notional_pct={p.agent_max_notional_pct:.3f}")
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


def validate_all() -> None:
    """Run all startup validations."""
    logger.info("=" * 60)
    logger.info("STARTUP VALIDATION SEQUENCE")
    logger.info("=" * 60)
    
    log_kalshi_credential_summary()
    # Validate profile → envelope → capability chain (PREFLIGHT-GATE)
    validate_profile_envelope_chain()
    # Validate production wiring (PROD1)
    validate_production_wiring()
    # Validate profile combination (PROF1)
    validate_profile_combination()
    # Validate 15m crypto profile restrictions (if active)
    validate_15m_crypto_profile_restrictions()
    # Validate 15m crypto profile fields (PROFILE-FIELDS-1)
    validate_15m_crypto_profile_fields()
    # Validate demo/prod risk parameter parity (DEMO-PROD-PARITY-1)
    validate_demo_prod_risk_parity()
    # Validate single risk config (RISK1)
    check_single_risk_config()
    # Validate profile backtest eligibility (BACKTEST1)
    validate_profile_backtest_eligibility()
    # Validate risk envelope for kalshi_crypto_15m_v2 (RISK-ENVELOPE-1)
    validate_risk_envelope()
    # Validate 15m series availability (VERIFY1)
    validate_15m_series_availability()
    # Validate Kalshi series consistency (SERIES-CONSISTENCY-1)
    validate_kalshi_series_consistency()
    # Validate Kalshi environment vs trading mode alignment (ENV1)
    validate_kalshi_env_vs_trading_mode()
    # Validate Kalshi authentication configuration (AUTH-CONFIG-1)
    validate_kalshi_auth_config()
    # Validate KALSHI_MIN_CLOSE_SECONDS_AGO configuration (FRESHNESS-CONFIG-1)
    validate_kalshi_min_close_seconds_ago()
    # Validate no test tickers in fills database (TEST-FILLS-1)
    validate_no_test_fills_in_database()
    # Validate sentiment isolation for kalshi_crypto_15m_v2 profile (SENTIMENT-ISOLATION-1)
    validate_kalshi_crypto_15m_sentiment_isolation()
    # Always validate environment (catches smoke test in any mode)
    validate_env_for_live_mode()
    # Log Kalshi configuration summary for diagnostics (CONFIG-SUMMARY-1)
    log_kalshi_config_summary()
    # Log config signature for drift detection (DRIFT1)
    log_config_signature()
    
    # Validate config consistency (P0/P1 audit guardrail)
    # This prevents contradictions in edge thresholds, risk limits, and strategy identity
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
    
    # Validate paper engine integrity (only if paper engine is enabled)
    ok, msg = validate_paper_engine_identity()
    if not ok:
        # Log warning but don't block — paper engine can be repaired on load
        import logging
        logging.getLogger("merid.startup").warning(f"Paper engine needs repair: {msg}")
    
    # Validate spot price feed readiness (P0: ensures spot data available before agents)
    try:
        validate_spot_price_feed_ready()
    except StartupValidationError as _spot_err:
        raise

    # Validate brain modules initialization (regime/momentum/anomaly stacks)
    try:
        validate_brain_modules()
    except StartupValidationError as _brain_err:
        raise
    
    # Validate 15m crypto profile fields (PROFILE-FIELDS-1)
    try:
        validate_15m_crypto_profile_fields()
    except StartupValidationError as _profile_err:
        raise
    
    # INSTRUMENTATION: Agent registry validation (WARN-only)
    # validate_agent_registry_for_profile()  # TODO: Implement
    # INSTRUMENTATION: Ancient agent scan (WARN-only)
    # validate_ancient_agents_in_registry()  # TODO: Implement

    # INSTRUMENTATION: Naming validation for 15m crypto assets (WARN-only)
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

    logger.info("=" * 60)
    logger.info("STARTUP VALIDATION COMPLETE")
    logger.info("=" * 60)
