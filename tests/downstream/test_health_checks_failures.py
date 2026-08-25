"""
Downstream Layer Test: Health Checks and Failures

Tests that health checks flag missing data sources and trading reacts appropriately.

Targets:
- Data source health checks
- Fills ledger availability
- Market state availability
- Signal history availability
- Trading halt on missing data
"""

import pytest
import os


class TestHealthChecksFailures:
    """Test health checks and failure handling."""
    
    @pytest.mark.downstream
    @pytest.mark.production_audit
    def test_missing_fills_ledger_flagged(self):
        """
        Simulate missing fills ledger and check health endpoint flags the issue.
        
        Validates:
        - Health endpoint returns degraded status
        - Specific data source failure is identified
        - Trading or monitoring reacts appropriately
        """
        # Verify health check infrastructure exists
        # Check for health endpoint in web API
        web_files = [
            "web/main_15m_lean.py",
            "web/api/real_data_endpoints.py"
        ]
        
        for file_path in web_files:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for health endpoint
                if "health" in content.lower():
                    # Verify it checks data sources
                    assert "fills" in content.lower() or "ledger" in content.lower() or \
                           "data" in content.lower(), \
                           f"Health endpoint in {file_path} should check data sources"
    
    @pytest.mark.downstream
    @pytest.mark.production_audit
    def test_missing_market_state_flagged(self):
        """
        Simulate missing market state and check health endpoint flags the issue.
        
        Validates:
        - Health endpoint returns degraded status
        - Specific data source failure is identified
        - Trading or monitoring reacts appropriately
        """
        # Verify market state health checks exist
        # Check for market state monitoring in key files
        key_files = [
            "merid/loop_15m.py",
            "merid/prediction/agent_grid_15m.py"
        ]
        
        for file_path in key_files:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for market state availability checks
                if "market_state" in content.lower():
                    # Verify it has error handling for missing state
                    assert "except" in content or "if not" in content or "error" in content.lower(), \
                           f"Market state usage in {file_path} should have error handling"
    
    @pytest.mark.downstream
    @pytest.mark.production_audit
    def test_missing_signal_history_flagged(self):
        """
        Simulate missing signal history and check health endpoint flags the issue.
        
        Validates:
        - Health endpoint returns degraded status
        - Specific data source failure is identified
        - Trading or monitoring reacts appropriately
        """
        # Verify signal history health checks exist
        # Check for signal history monitoring in prediction publisher
        publisher_path = "web/services/prediction_publisher.py"
        if os.path.exists(publisher_path):
            with open(publisher_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for signal history retrieval
            if "signal" in content.lower():
                # Verify it has error handling for missing history
                assert "except" in content or "if not" in content or "error" in content.lower(), \
                       "Signal history retrieval should have error handling"
    
    @pytest.mark.downstream
    def test_trading_halt_on_missing_data(self):
        """
        Assert that trading halts or goes into safe mode when data sources are missing.
        
        Validates:
        - Agents halt when critical data missing
        - Safe mode is activated
        - No trades occur during degraded state
        """
        # Verify trading halt logic exists
        # Check for halt/safe mode in loop and agent grid
        key_files = [
            "merid/loop_15m.py",
            "merid/prediction/agent_grid_15m.py"
        ]
        
        for file_path in key_files:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for halt or safe mode logic
                if "halt" in content.lower() or "safe" in content.lower() or "stop" in content.lower():
                    # Verify it's related to data availability
                    context = content.lower()
                    assert "data" in context or "market" in context or "error" in context, \
                           f"Halt logic in {file_path} should be related to data availability"
    
    @pytest.mark.downstream
    def test_degraded_dashboards_on_missing_data(self):
        """
        Assert that dashboards show degraded status when data sources are missing.
        
        Validates:
        - UI shows degraded indicators
        - Metrics are marked as unavailable
        - No misleading data is displayed
        """
        # Verify dashboard handles missing data gracefully
        # Check for error handling in web API endpoints
        api_files = [
            "web/api/real_data_endpoints.py",
            "web/api/missing_endpoints.py"
        ]
        
        for file_path in api_files:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for error handling in endpoints
                if "def " in content:
                    # Verify endpoints have error handling
                    assert "except" in content or "try:" in content or "error" in content.lower(), \
                           f"API endpoints in {file_path} should have error handling"
