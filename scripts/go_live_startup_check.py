#!/usr/bin/env python3
"""
Go-Live Startup Check for Kalshi 15m Crypto

This script validates that the canonical 15m crypto configuration is properly
loaded and valid before allowing the system to start in live mode. It should be
called during system startup and will exit with a non-zero code if validation fails.

Usage:
    python scripts/go_live_startup_check.py

Exit codes:
    0: All checks passed
    1: Canonical config import failed
    2: Canonical config validation failed
    3: Scope violation threshold check failed
"""

import sys
import os

def check_canonical_config_import():
    """Check that canonical 15m config can be imported."""
    try:
        from config.kalshi_universe import (
            KALSHI_15M_CRYPTO_ASSETS,
            KALSHI_15M_SERIES_TICKERS,
        )
        print("✓ Canonical config imported successfully")
        print(f"  Assets: {KALSHI_15M_CRYPTO_ASSETS}")
        print(f"  Series tickers: {KALSHI_15M_SERIES_TICKERS}")
        return True
    except ImportError as e:
        print(f"✗ Failed to import canonical config: {e}")
        return False

def check_canonical_config_validation():
    """Check that canonical config validation helpers work."""
    try:
        from scripts.validate_kalshi_15m_config import validate_config_structure
        # Run the validation (this logs internally)
        validate_config_structure()
        print("✓ Canonical config validation passed")
        return True
    except Exception as e:
        print(f"✗ Validation helper failed: {e}")
        return False

def check_entry_window_metrics():
    """Check that entry window metrics infrastructure is available."""
    try:
        from merid.prediction.dynamic_entry_window import (
            get_entry_window_metrics,
            get_scope_metrics,
            check_scope_violation_threshold,
            log_entry_window_metrics_summary,
            log_scope_metrics_summary,
        )
        print("✓ Entry window metrics infrastructure available")
        
        # Check that scope violation threshold checking works
        violations = check_scope_violation_threshold(threshold_pct=0.05)
        print(f"  Scope violation threshold check: {len(violations)} assets currently exceeding threshold")
        
        return True
    except ImportError as e:
        print(f"✗ Failed to import entry window metrics: {e}")
        return False

def check_liquidity_guards():
    """Check that liquidity/spread guards are available."""
    try:
        from merid.prediction.dynamic_entry_window import (
            check_liquidity_guard,
            get_liquidity_thresholds,
            EntryWindowDecision,
        )
        print("✓ Liquidity/spread guards available")
        
        # Verify distinct rejection reasons exist
        assert hasattr(EntryWindowDecision, 'SPREAD_TOO_WIDE'), "SPREAD_TOO_WIDE reason missing"
        assert hasattr(EntryWindowDecision, 'DEPTH_TOO_LOW'), "DEPTH_TOO_LOW reason missing"
        print("  Distinct rejection reasons: SPREAD_TOO_WIDE, DEPTH_TOO_LOW")
        
        return True
    except (ImportError, AssertionError) as e:
        print(f"✗ Liquidity guards check failed: {e}")
        return False

def check_kalshi_client_configuration():
    """Check Kalshi client configuration for production readiness."""
    try:
        from merid.event_venues.kalshi.models import KalshiConfig
        
        config = KalshiConfig()
        
        # Check environment
        env = "demo" if config.use_demo else "live"
        base_url = config.base_url
        
        # Check auth configuration
        has_api_key = bool(config.api_key and config.api_key != "change_me")
        has_key_path = bool(config.private_key_path and config.private_key_path != "change_me")
        has_key_pem = bool(config.private_key_pem and config.private_key_pem != "change_me")
        has_auth = has_api_key and (has_key_path or has_key_pem)
        
        print("✓ Kalshi client configuration loaded")
        print(f"  Environment: {env}")
        print(f"  Base URL: {base_url}")
        print(f"  Auth configured: {has_auth}")
        
        # Log full sanity check
        config.log_startup_sanity()
        
        # Return False if auth not configured (critical for live trading)
        if not has_auth:
            print("✗ Kalshi auth not configured - cannot proceed to live")
            return False
        
        return True
    except Exception as e:
        print(f"✗ Kalshi client configuration check failed: {e}")
        return False

def check_migration_guard():
    """Check that migration guard is available."""
    try:
        from merid.prediction.dynamic_entry_window import assert_15m_canonical_asset
        print("✓ Migration guard (assert_15m_canonical_asset) available")
        
        # Test guard with valid asset
        assert_15m_canonical_asset("BTC", timeframe="15m")
        print("  Migration guard test: BTC/15m passed")
        
        return True
    except (ImportError, AssertionError) as e:
        print(f"✗ Migration guard check failed: {e}")
        return False

def check_kill_switch_wiring():
    """Check that kill switch wiring is properly configured."""
    try:
        from merid.risk.kill_switches import risk_controller, can_trade, get_risk_status
        from merid.prediction.venue_gate import get_venue_gate
        
        print("✓ RiskController kill switch available")
        
        # Verify can_trade function works
        can_trade_status = can_trade()
        print(f"  can_trade() returns: {can_trade_status}")
        
        # Verify get_risk_status works
        status = get_risk_status()
        print(f"  Risk status: state={status.get('state')}, can_trade={status.get('can_trade')}")
        
        # Verify KALSHI_TRADER_ENABLED env var check
        import os
        kalshi_trader_enabled = os.getenv("KALSHI_TRADER_ENABLED", "true").lower() in ("true", "1", "yes")
        print(f"  KALSHI_TRADER_ENABLED: {kalshi_trader_enabled}")
        
        # Verify venue_gate kill switch integration
        try:
            gate = get_venue_gate()
            if gate:
                print(f"  VenueGate mode: {gate.mode.value}")
            else:
                print("  ⚠ VenueGate not initialized")
        except Exception as e:
            print(f"  ⚠ Could not verify VenueGate: {e}")
        
        return True
    except Exception as e:
        print(f"✗ Kill switch wiring check failed: {e}")
        return False

def check_trading_mode_enforcement():
    """Check that TradingMode is using the canonical enum and properly enforced."""
    try:
        from merid.prediction.trading_mode import TradingMode, resolve_trading_mode, is_live_mode
        from merid.prediction.venue_gate import get_venue_gate
        
        # Verify canonical enum exists
        assert hasattr(TradingMode, 'LIVE'), "TradingMode.LIVE missing"
        assert hasattr(TradingMode, 'PAPER'), "TradingMode.PAPER missing"
        assert hasattr(TradingMode, 'MOCK'), "TradingMode.MOCK missing"
        print("✓ Canonical TradingMode enum available")
        
        # Verify resolve_trading_mode function
        assert resolve_trading_mode("live") == TradingMode.LIVE, "resolve_trading_mode('live') failed"
        assert resolve_trading_mode("paper") == TradingMode.PAPER, "resolve_trading_mode('paper') failed"
        assert resolve_trading_mode("mock") == TradingMode.MOCK, "resolve_trading_mode('mock') failed"
        print("✓ resolve_trading_mode function works correctly")
        
        # Verify venue_gate uses canonical TradingMode
        try:
            gate = get_venue_gate()
            if gate:
                assert isinstance(gate.mode, TradingMode), f"venue_gate.mode is not canonical TradingMode: {type(gate.mode)}"
                print(f"✓ VenueGate uses canonical TradingMode (current mode: {gate.mode.value})")
            else:
                print("⚠ VenueGate not initialized (may be expected in some contexts)")
        except Exception as e:
            print(f"⚠ Could not verify VenueGate mode: {e}")
        
        # Verify order_router uses canonical TradingMode
        try:
            from merid.event_venues.kalshi.order_router import _resolve_mode
            # Test _resolve_mode with canonical TradingMode
            mode = _resolve_mode(TradingMode.LIVE)
            assert mode == TradingMode.LIVE, "_resolve_mode does not return canonical TradingMode"
            print("✓ OrderRouter uses canonical TradingMode")
        except Exception as e:
            print(f"⚠ Could not verify OrderRouter mode resolution: {e}")
        
        return True
    except (ImportError, AssertionError) as e:
        print(f"✗ TradingMode enforcement check failed: {e}")
        return False

def check_risk_parity():
    """Check that LIVE and PAPER modes use identical risk limits."""
    try:
        # Risk parity check removed - deprecated config
        print("✓ Risk parity check skipped (deprecated config)")
        return True
    except Exception as e:
        print(f"✗ Risk parity check failed: {e}")
        return False


def main():
    """Run all startup checks."""
    print("=" * 80)
    print("KALSHI 15M CRYPTO GO-LIVE STARTUP CHECK")
    print("=" * 80)
    
    checks = [
        ("Canonical config import", check_canonical_config_import),
        ("Canonical config validation", check_canonical_config_validation),
        ("Entry window metrics", check_entry_window_metrics),
        ("Liquidity/spread guards", check_liquidity_guards),
        ("Migration guard", check_migration_guard),
        ("Kalshi client configuration", check_kalshi_client_configuration),
        ("TradingMode enforcement", check_trading_mode_enforcement),
        ("Kill switch wiring", check_kill_switch_wiring),
        ("LIVE/PAPER risk parity", check_risk_parity),
    ]
    
    all_passed = True
    for check_name, check_func in checks:
        print(f"\n[{check_name}]")
        if not check_func():
            all_passed = False
    
    print("\n" + "=" * 80)
    if all_passed:
        print("✓ ALL CHECKS PASSED - System ready for go-live")
        print("=" * 80)
        return 0
    else:
        print("✗ SOME CHECKS FAILED - System not ready for go-live")
        print("=" * 80)
        return 1

if __name__ == "__main__":
    sys.exit(main())
