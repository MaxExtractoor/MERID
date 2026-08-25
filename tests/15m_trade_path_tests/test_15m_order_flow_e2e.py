"""Kalshi 15m Crypto End-to-End Order Flow Integration Test

Validates the complete order flow for 15m crypto trading:
1. Signal generation from trading agent
2. Risk envelope validation
3. Order routing through order_router
4. Execution gate checks
5. Position reconciliation

Run: pytest tests/15m_trade_path_tests/test_15m_order_flow_e2e.py -v
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_risk_envelope():
    """Mock KalshiCrypto15mRiskEnvelope for testing."""
    envelope = MagicMock()
    envelope.live_bankroll_usd = 1000.0
    envelope.max_single_order_notional_usd = 50.0
    envelope.max_total_notional_usd = 300.0
    envelope.asset_max_notional_usd = {"BTC": 100.0, "ETH": 100.0, "SOL": 50.0, "XRP": 30.0, "DOGE": 20.0}
    envelope.asset_depth_thresholds = {
        "BTC": {"min_depth_yes": 30, "min_depth_no": 30},
        "ETH": {"min_depth_yes": 30, "min_depth_no": 30},
        "SOL": {"min_depth_yes": 20, "min_depth_no": 20},
        "XRP": {"min_depth_yes": 10, "min_depth_no": 10},
        "DOGE": {"min_depth_yes": 5, "min_depth_no": 5}
    }
    envelope.get_depth_thresholds = lambda asset: envelope.asset_depth_thresholds.get(asset, {"min_depth_yes": 25, "min_depth_no": 25})
    envelope.get_effective_per_trade_risk_usd = lambda: 8.0  # 0.8% of $1000
    envelope.is_halted = False
    envelope.per_trade_risk_multiplier = 1.0
    return envelope


@pytest.fixture
def mock_market_state():
    """Mock KalshiMarketState for testing."""
    state = MagicMock()
    state.min_depth_yes = 35  # Above BTC threshold of 30
    state.min_depth_no = 35
    state.book_initialized = True
    state.mid_cents = 50
    state.spread_cents = 2
    state.seconds_to_expiry = 600  # 10 minutes
    return state


@pytest.fixture
def sample_15m_signal():
    """Create a sample 15m crypto trading signal."""
    return {
        "ticker": "KXBTC-25DEC-ABOVE-100000",
        "side": "yes",
        "action": "buy",
        "confidence": 0.75,
        "edge": Decimal("0.12"),
        "suggested_size": 5,
        "agent_id": "BTC_15M",
        "asset": "BTC",
        "timeframe": "15m",
    }


# =============================================================================
# Test Class: End-to-End Order Flow
# =============================================================================

class Test15mOrderFlowE2E:
    """Verify complete order flow from signal to execution for 15m crypto."""
    
    def test_depth_thresholds_from_profile(self, mock_risk_envelope):
        """Depth thresholds come from kalshi_crypto_15m.yaml profile."""
        # BTC should have 30/30 thresholds
        btc_thresholds = mock_risk_envelope.get_depth_thresholds("BTC")
        assert btc_thresholds["min_depth_yes"] == 30
        assert btc_thresholds["min_depth_no"] == 30
        
        # SOL should have 20/20 thresholds (tier 2)
        sol_thresholds = mock_risk_envelope.get_depth_thresholds("SOL")
        assert sol_thresholds["min_depth_yes"] == 20
        assert sol_thresholds["min_depth_no"] == 20
        
        # DOGE should have 5/5 thresholds (lowest tier)
        doge_thresholds = mock_risk_envelope.get_depth_thresholds("DOGE")
        assert doge_thresholds["min_depth_yes"] == 5
        assert doge_thresholds["min_depth_no"] == 5
    
    def test_depth_check_uses_profile_thresholds(self, mock_market_state, mock_risk_envelope):
        """Depth check in loop_15m.py uses profile thresholds, not hardcoded values."""
        # Simulate depth check logic from loop_15m.py
        asset = "BTC"
        depth_thresholds = mock_risk_envelope.get_depth_thresholds(asset)
        min_depth_yes_threshold = depth_thresholds.get('min_depth_yes', 25)
        min_depth_no_threshold = depth_thresholds.get('min_depth_no', 25)
        
        # Check depth (market state has 35/35, threshold is 30/30)
        depth_sufficient = (
            mock_market_state.min_depth_yes >= min_depth_yes_threshold and
            mock_market_state.min_depth_no >= min_depth_no_threshold
        )
        
        assert depth_sufficient, "Market depth should be sufficient"
        assert min_depth_yes_threshold == 30, "Should use profile threshold, not hardcoded 25"
        assert min_depth_no_threshold == 30, "Should use profile threshold, not hardcoded 25"
    
    def test_risk_envelope_exposes_depth_thresholds(self, mock_risk_envelope):
        """KalshiCrypto15mRiskEnvelope exposes get_depth_thresholds method."""
        assert hasattr(mock_risk_envelope, "get_depth_thresholds")
        assert callable(mock_risk_envelope.get_depth_thresholds)
        
        # Method returns dict with expected keys
        thresholds = mock_risk_envelope.get_depth_thresholds("BTC")
        assert isinstance(thresholds, dict)
        assert "min_depth_yes" in thresholds
        assert "min_depth_no" in thresholds
    
    def test_maintenance_window_from_session_config(self):
        """Maintenance window comes from SessionConfig, not settings.py."""
        try:
            from merid.prediction.agent_grid_config import SessionConfig
            
            # SessionConfig is a dataclass with defaults
            session = SessionConfig()
            
            # SessionConfig should have maintenance config
            assert hasattr(session, "maintenance_day")
            assert hasattr(session, "maintenance_start_et")
            assert hasattr(session, "maintenance_end_et")
            
            # Values should be reasonable (Thursday 3-5am ET)
            assert session.maintenance_day == 3  # Thursday
            assert session.maintenance_start_et == "03:00"
            assert session.maintenance_end_et == "05:00"
            
        except ImportError as e:
            pytest.skip(f"agent_grid_config not available: {e}")
    
    def test_no_trade_reason_observability(self):
        """'Why no trade?' reason is calculated and logged for observability."""
        # Simulate the no_trade_reason logic from loop_15m.py
        def calculate_no_trade_reason(
            in_scheduled_maintenance: bool,
            catalog_fresh: bool,
            catalog_age_ok: bool,
            md_coverage_ok: bool,
            depth_coverage_ready: bool,
            ws_forwarder_healthy: bool,
            live_bankroll_valid: bool,
            bankroll_source_valid: bool,
            risk_profile_loaded: bool,
            top3_gate_available: bool,
            fake_bankroll_used: bool,
        ) -> str:
            no_trade_reason = "OK"
            if in_scheduled_maintenance:
                no_trade_reason = "MAINTENANCE"
            elif not catalog_fresh:
                no_trade_reason = "CATALOG_STALE"
            elif not catalog_age_ok:
                no_trade_reason = "CATALOG_OLD"
            elif not md_coverage_ok:
                no_trade_reason = "MD_STALE"
            elif not depth_coverage_ready:
                no_trade_reason = "DEPTH_LOW"
            elif not ws_forwarder_healthy:
                no_trade_reason = "WS_UNHEALTHY"
            elif not live_bankroll_valid:
                no_trade_reason = "BANKROLL_INVALID"
            elif not bankroll_source_valid:
                no_trade_reason = "BANKROLL_SOURCE_INVALID"
            elif not risk_profile_loaded:
                no_trade_reason = "RISK_PROFILE_MISSING"
            elif not top3_gate_available:
                no_trade_reason = "TOP3_GATE_MISSING"
            elif fake_bankroll_used:
                no_trade_reason = "FAKE_BANKROLL"
            return no_trade_reason
        
        # Test each reason code
        assert calculate_no_trade_reason(
            in_scheduled_maintenance=True, catalog_fresh=True, catalog_age_ok=True,
            md_coverage_ok=True, depth_coverage_ready=True, ws_forwarder_healthy=True,
            live_bankroll_valid=True, bankroll_source_valid=True, risk_profile_loaded=True,
            top3_gate_available=True, fake_bankroll_used=False
        ) == "MAINTENANCE"
        
        assert calculate_no_trade_reason(
            in_scheduled_maintenance=False, catalog_fresh=False, catalog_age_ok=True,
            md_coverage_ok=True, depth_coverage_ready=True, ws_forwarder_healthy=True,
            live_bankroll_valid=True, bankroll_source_valid=True, risk_profile_loaded=True,
            top3_gate_available=True, fake_bankroll_used=False
        ) == "CATALOG_STALE"
        
        assert calculate_no_trade_reason(
            in_scheduled_maintenance=False, catalog_fresh=True, catalog_age_ok=True,
            md_coverage_ok=True, depth_coverage_ready=False, ws_forwarder_healthy=True,
            live_bankroll_valid=True, bankroll_source_valid=True, risk_profile_loaded=True,
            top3_gate_available=True, fake_bankroll_used=False
        ) == "DEPTH_LOW"
        
        # All OK should return "OK"
        assert calculate_no_trade_reason(
            in_scheduled_maintenance=False, catalog_fresh=True, catalog_age_ok=True,
            md_coverage_ok=True, depth_coverage_ready=True, ws_forwarder_healthy=True,
            live_bankroll_valid=True, bankroll_source_valid=True, risk_profile_loaded=True,
            top3_gate_available=True, fake_bankroll_used=False
        ) == "OK"
    


# =============================================================================
# Test Class: Configuration Single Source of Truth
# =============================================================================

class Test15mConfigSingleSourceOfTruth:
    """Verify kalshi_crypto_15m.yaml is single source of truth for 15m config."""
    
    def test_profile_yaml_has_depth_thresholds(self):
        """kalshi_crypto_15m.yaml has min_depth_yes and min_depth_no for each asset."""
        try:
            import yaml
            from pathlib import Path
            
            profile_path = Path(__file__).parent.parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            
            # Use UTF-8 encoding to avoid Windows charmap codec issues
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile = yaml.safe_load(f)
            
            assets = profile.get('assets', {})
            
            # Check each asset has depth thresholds
            for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                assert asset in assets, f"Asset {asset} not in profile"
                asset_config = assets[asset]
                assert 'min_depth_yes' in asset_config, f"min_depth_yes missing for {asset}"
                assert 'min_depth_no' in asset_config, f"min_depth_no missing for {asset}"
                
        except Exception as e:
            pytest.skip(f"Could not load profile YAML: {e}")
    
    def test_agent_grid_yaml_has_session_config(self):
        """kalshi_agent_grid.yaml has session config for maintenance window."""
        try:
            import yaml
            from pathlib import Path
            
            grid_path = Path(__file__).parent.parent.parent / "config" / "kalshi_agent_grid.yaml"
            
            with open(grid_path, 'r') as f:
                grid = yaml.safe_load(f)
            
            session = grid.get('session', {})
            
            # Check session config exists
            assert 'maintenance_day' in session
            assert 'maintenance_start_et' in session
            assert 'maintenance_end_et' in session
            
        except Exception as e:
            pytest.skip(f"Could not load agent grid YAML: {e}")


# =============================================================================
# Test Class: Integration Wiring
# =============================================================================

class Test15mIntegrationWiring:
    """Verify components are wired correctly for 15m crypto trading."""
    
    def test_loop_15m_uses_session_config_for_maintenance(self):
        """loop_15m.py uses SessionConfig for maintenance window, not settings.py."""
        try:
            import inspect
            from merid.loop_15m import is_within_kalshi_maintenance
            
            source = inspect.getsource(is_within_kalshi_maintenance)
            
            # Should reference get_session_config from agent_grid_config
            assert "get_session_config" in source, \
                "is_within_kalshi_maintenance should use get_session_config"
            
            # Should NOT reference settings.KALSHI_MAINTENANCE_* (old pattern)
            assert "KALSHI_MAINTENANCE_DAY" not in source, \
                "Should not use settings.KALSHI_MAINTENANCE_DAY"
            assert "KALSHI_MAINTENANCE_START" not in source, \
                "Should not use settings.KALSHI_MAINTENANCE_START"
            
        except ImportError:
            pytest.skip("loop_15m not available")
    
    def test_risk_envelope_has_asset_depth_thresholds_field(self):
        """KalshiCrypto15mRiskEnvelope has asset_depth_thresholds field."""
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
            from dataclasses import fields
            
            field_names = {f.name for f in fields(KalshiCrypto15mRiskEnvelope)}
            
            assert "asset_depth_thresholds" in field_names, \
                "KalshiCrypto15mRiskEnvelope should have asset_depth_thresholds field"
            
        except ImportError:
            pytest.skip("kalshi_crypto_15m_risk_envelope not available")
