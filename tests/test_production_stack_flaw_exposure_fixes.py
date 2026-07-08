"""
Tests for production stack flaw exposure script fixes.

This test file validates that all the fixes made to the production_stack_flaw_exposure.py
script work correctly and that the script can successfully run without critical/high flaws.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestProfileYAMLEncoding:
    """Test that profile YAML can be loaded with UTF-8 encoding."""
    
    def test_profile_yaml_exists(self):
        """Test that the profile YAML file exists."""
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        assert profile_path.exists(), f"Profile YAML not found at {profile_path}"
    
    def test_profile_yaml_loadable_with_utf8(self):
        """Test that profile YAML can be loaded with UTF-8 encoding."""
        import yaml
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_config = yaml.safe_load(f)
        
        assert profile_config is not None, "Profile YAML loaded as None"
        assert 'profile_name' in profile_config, "Profile YAML missing profile_name"
        assert profile_config['profile_name'] == 'kalshi_crypto_15m_v2', "Profile name mismatch"


class TestUnifiedSizingModule:
    """Test that unified_sizing module has required functions."""
    
    def test_unified_sizing_module_importable(self):
        """Test that unified_sizing module can be imported."""
        from merid.prediction import unified_sizing
        assert unified_sizing is not None
    
    def test_unified_sizing_has_required_functions(self):
        """Test that unified_sizing has all required functions."""
        from merid.prediction import unified_sizing
        
        required_functions = [
            'compute_order_size',
            'compute_min_notional_for_venue',
            '_get_bankroll_cap_pct',
            '_get_per_asset_risk_pct',
            '_get_per_trade_risk_pct',
        ]
        
        for func_name in required_functions:
            assert hasattr(unified_sizing, func_name), f"Missing function: {func_name}"
    
    def test_dynamic_sizing_disabled(self):
        """Test that dynamic sizing is disabled to prevent interference with risk limits."""
        from merid.prediction import unified_sizing
        
        dynamic_enabled = unified_sizing._is_dynamic_sizing_enabled()
        assert not dynamic_enabled, "Dynamic sizing should be disabled to prevent interference with 3% per asset / 5% per 15m window limits"


class TestKillSwitchImplementation:
    """Test that kill switch implementation has required functions."""
    
    def test_kill_switch_module_importable(self):
        """Test that kill_switches module can be imported."""
        from merid.risk import kill_switches
        assert kill_switches is not None
    
    def test_kill_switch_has_required_functions(self):
        """Test that kill_switches has all required functions."""
        from merid.risk import kill_switches
        
        required_functions = ['can_trade', 'emergency_stop', 'get_risk_status']
        
        for func_name in required_functions:
            assert hasattr(kill_switches, func_name), f"Missing function: {func_name}"


class TestCircuitBreakerImplementation:
    """Test that circuit breaker implementation exists."""
    
    def test_circuit_breaker_importable(self):
        """Test that CircuitBreaker can be imported from correct location."""
        from merid.resilience.circuit_breaker import CircuitBreaker
        assert CircuitBreaker is not None


class TestDisasterRecoveryImplementation:
    """Test that disaster recovery implementation exists."""
    
    def test_disaster_recovery_importable(self):
        """Test that DisasterRecoveryManager can be imported."""
        from recovery.disaster_recovery import DisasterRecoveryManager
        assert DisasterRecoveryManager is not None


class TestLatencyMonitoringImplementation:
    """Test that latency monitoring implementation exists."""
    
    def test_brier_metrics_importable(self):
        """Test that BrierMetricsTracker can be imported."""
        from monitoring.brier_metrics import BrierMetricsTracker
        assert BrierMetricsTracker is not None


class TestProductionStackFlawExposureScript:
    """Test that the production stack flaw exposure script runs successfully."""
    
    def test_script_runs_without_critical_flaws(self):
        """Test that the script runs and reports no critical flaws."""
        import subprocess
        import json
        from pathlib import Path
        
        script_path = Path(__file__).parent.parent / "scripts" / "production_stack_flaw_exposure.py"
        
        result = subprocess.run(
            ["py", str(script_path)],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent
        )
        
        # Script should exit with 0 (no critical flaws)
        assert result.returncode == 0, f"Script exited with code {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        
        # Parse the output to find the report file
        output_lines = result.stdout.split('\n')
        report_line = [line for line in output_lines if 'Report saved to:' in line]
        
        if report_line:
            report_path = report_line[0].split('Report saved to: ')[1].strip()
            
            # Read and parse the report
            with open(report_path, 'r') as f:
                report = json.load(f)
            
            # Check that there are no critical or high flaws
            assert report['summary']['total_flaws'] == 0, f"Script reported {report['summary']['total_flaws']} flaws"
            assert report['severity_breakdown'].get('CRITICAL', 0) == 0, "Critical flaws found"
            assert report['severity_breakdown'].get('HIGH', 0) == 0, "High flaws found"
    
    def test_script_all_tests_pass(self):
        """Test that all tests in the script pass."""
        import subprocess
        import json
        from pathlib import Path
        
        script_path = Path(__file__).parent.parent / "scripts" / "production_stack_flaw_exposure.py"
        
        result = subprocess.run(
            ["py", str(script_path)],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent
        )
        
        # Parse the output to find the report file
        output_lines = result.stdout.split('\n')
        report_line = [line for line in output_lines if 'Report saved to:' in line]
        
        if report_line:
            report_path = report_line[0].split('Report saved to: ')[1].strip()
            
            # Read and parse the report
            with open(report_path, 'r') as f:
                report = json.load(f)
            
            # Check that all tests passed
            assert report['summary']['passed_tests'] == report['summary']['total_tests'], \
                f"Not all tests passed: {report['summary']['passed_tests']}/{report['summary']['total_tests']}"


class TestAssetTracking:
    """Test that all 5 assets are properly tracked."""
    
    def test_all_5_assets_have_agents(self):
        """Test that all 5 assets (BTC, ETH, SOL, XRP, DOGE) have agent modules."""
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in required_assets:
            agent_module = f"merid.agents.{asset.lower()}_15m_agent"
            try:
                __import__(agent_module)
            except ImportError:
                pytest.fail(f"Asset agent module not found: {agent_module}")
    
    def test_unified_spot_service_exists(self):
        """Test that unified spot service exists."""
        try:
            from data.unified_spot_service import get_unified_spot_service
        except ImportError:
            pytest.fail("Unified spot service not found")


class TestRiskEnvelopeConsistency:
    """Test that risk envelope is consistent across layers."""
    
    def test_window_limits_configured_correctly(self):
        """Test that window-based risk limits are configured correctly (3% per agent, 5% total)."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
        
        test_bankroll = 1000.0
        envelope = compute_kalshi_crypto_15m_risk_envelope(test_bankroll)
        
        # Check per-agent window limit (3%)
        expected_per_agent = test_bankroll * 0.03
        assert abs(envelope.per_agent_window_limit_usd - expected_per_agent) < 0.01, \
            f"Per-agent window limit mismatch: {envelope.per_agent_window_limit_usd} vs {expected_per_agent}"
        
        # Check total venue window limit (5%)
        expected_total = test_bankroll * 0.05
        assert abs(envelope.total_venue_window_limit_usd - expected_total) < 0.01, \
            f"Total venue window limit mismatch: {envelope.total_venue_window_limit_usd} vs {expected_total}"
    
    def test_all_5_assets_have_caps(self):
        """Test that all 5 assets have per-asset caps in the risk envelope."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
        
        test_bankroll = 1000.0
        envelope = compute_kalshi_crypto_15m_risk_envelope(test_bankroll)
        
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in required_assets:
            assert asset in envelope.asset_max_notional_usd, f"Asset {asset} missing from risk envelope caps"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
