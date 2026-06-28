"""
Tests for observability metrics added to agent_grid_15m.py and loop_15m.py.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestAgentGrid15mMetrics:
    """Test Prometheus metrics in agent_grid_15m.py."""
    
    def test_prometheus_metrics_imported(self):
        """Test that Prometheus metrics are imported and available."""
        try:
            from merid.prediction.agent_grid_15m import (
                signals_total,
                orders_total,
                guard_denials_total,
                PROMETHEUS_AVAILABLE,
            )
            # If prometheus_client is available, these should be real counters
            if PROMETHEUS_AVAILABLE:
                from prometheus_client import Counter
                assert isinstance(signals_total, Counter)
                assert isinstance(orders_total, Counter)
                assert isinstance(guard_denials_total, Counter)
            else:
                # Fallback to DummyCounter
                assert hasattr(signals_total, 'labels')
                assert hasattr(orders_total, 'labels')
                assert hasattr(guard_denials_total, 'labels')
        except ImportError as e:
            pytest.fail(f"Failed to import metrics: {e}")
    
    def test_metrics_have_correct_labels(self):
        """Test that metrics have the expected label names."""
        from merid.prediction.agent_grid_15m import (
            signals_total,
            orders_total,
            guard_denials_total,
        )
        
        # Check label names by inspecting the metric
        if hasattr(signals_total, '_labelnames'):
            assert 'asset' in signals_total._labelnames
            assert 'phase' in signals_total._labelnames
        
        if hasattr(orders_total, '_labelnames'):
            assert 'asset' in orders_total._labelnames
        
        if hasattr(guard_denials_total, '_labelnames'):
            assert 'asset' in guard_denials_total._labelnames
            assert 'reason' in guard_denials_total._labelnames
    
    def test_metrics_can_be_incremented(self):
        """Test that metrics can be incremented without errors."""
        from merid.prediction.agent_grid_15m import (
            signals_total,
            orders_total,
            guard_denials_total,
        )
        
        # Test incrementing with valid labels
        try:
            signals_total.labels(asset="BTC", phase="pre_ev").inc()
            orders_total.labels(asset="BTC").inc()
            guard_denials_total.labels(asset="BTC", reason="test").inc()
        except Exception as e:
            pytest.fail(f"Failed to increment metrics: {e}")


class TestLoop15mMetrics:
    """Test Prometheus metrics in loop_15m.py."""
    
    def test_cycle_duration_histogram_imported(self):
        """Test that cycle duration histogram is imported and available."""
        try:
            from merid.loop_15m import (
                cycle_duration_hist,
                PROMETHEUS_AVAILABLE,
            )
            if PROMETHEUS_AVAILABLE:
                from prometheus_client import Histogram
                assert isinstance(cycle_duration_hist, Histogram)
            else:
                # Fallback to DummyHistogram
                assert hasattr(cycle_duration_hist, 'observe')
        except ImportError as e:
            pytest.fail(f"Failed to import histogram: {e}")
    
    def test_histogram_has_correct_buckets(self):
        """Test that histogram has the expected buckets."""
        from merid.loop_15m import cycle_duration_hist
        
        if hasattr(cycle_duration_hist, '_upper_bounds'):
            expected_buckets = [0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]
            # Check that expected buckets are present
            for bucket in expected_buckets:
                assert bucket in cycle_duration_hist._upper_bounds
    
    def test_histogram_can_observe(self):
        """Test that histogram can observe values without errors."""
        from merid.loop_15m import cycle_duration_hist
        
        try:
            cycle_duration_hist.observe(0.5)
            cycle_duration_hist.observe(1.0)
            cycle_duration_hist.observe(2.5)
        except Exception as e:
            pytest.fail(f"Failed to observe histogram values: {e}")
    
    def test_loop_has_cycle_duration_history(self):
        """Test that Kalshi15mLoop has cycle duration history tracking."""
        from merid.loop_15m import Kalshi15mLoop
        
        mock_agent_grid = MagicMock()
        mock_bankroll_service = MagicMock()
        mock_risk_config = MagicMock()
        
        loop = Kalshi15mLoop(
            agent_grid=mock_agent_grid,
            bankroll_service=mock_bankroll_service,
            risk_config=mock_risk_config,
            cadence_seconds=5.0,
        )
        
        # Verify history tracking attributes exist
        assert hasattr(loop, '_cycle_duration_history')
        assert hasattr(loop, '_max_history_length')
        assert loop._max_history_length == 200
        assert loop._cycle_duration_history == []


class TestGrafanaDashboard:
    """Test Grafana dashboard JSON."""
    
    def test_dashboard_json_valid(self):
        """Test that Grafana dashboard JSON is valid."""
        import json
        import os
        
        dashboard_path = "grafana/dashboards/merid_kalshi_recon_gate.json"
        assert os.path.exists(dashboard_path), f"Dashboard file not found: {dashboard_path}"
        
        with open(dashboard_path, 'r') as f:
            dashboard = json.load(f)
        
        # Verify dashboard structure
        assert 'dashboard' in dashboard
        assert 'panels' in dashboard['dashboard']
    
    def test_per_asset_panels_exist(self):
        """Test that per-asset panels were added to dashboard."""
        import json
        
        dashboard_path = "grafana/dashboards/merid_kalshi_recon_gate.json"
        with open(dashboard_path, 'r') as f:
            dashboard = json.load(f)
        
        panels = dashboard['dashboard']['panels']
        panel_titles = [p.get('title', '') for p in panels]
        
        # Check for new per-asset panels
        assert "Per-Asset Signal Funnel (Pre-EV vs Post-EV)" in panel_titles
        assert "Per-Asset Orders Submitted" in panel_titles
        assert "Per-Asset Guard Denials" in panel_titles
    
    def test_per_asset_panels_use_correct_metrics(self):
        """Test that per-asset panels use the new metrics."""
        import json
        
        dashboard_path = "grafana/dashboards/merid_kalshi_recon_gate.json"
        with open(dashboard_path, 'r') as f:
            dashboard = json.load(f)
        
        panels = dashboard['dashboard']['panels']
        
        # Find per-asset panels
        signal_panel = next((p for p in panels if "Signal Funnel" in p.get('title', '')), None)
        orders_panel = next((p for p in panels if "Orders Submitted" in p.get('title', '')), None)
        guard_panel = next((p for p in panels if "Guard Denials" in p.get('title', '')), None)
        
        # Verify they use the new metrics
        assert signal_panel is not None
        assert orders_panel is not None
        assert guard_panel is not None
        
        # Check metric names in queries
        signal_queries = [t.get('expr', '') for t in signal_panel.get('targets', [])]
        assert any('merid_15m_signals_total' in q for q in signal_queries)
        
        orders_queries = [t.get('expr', '') for t in orders_panel.get('targets', [])]
        assert any('merid_15m_orders_total' in q for q in orders_queries)
        
        guard_queries = [t.get('expr', '') for t in guard_panel.get('targets', [])]
        assert any('merid_15m_guard_denials_total' in q for q in guard_queries)


class TestPrometheusAlertRules:
    """Test Prometheus alert rules."""
    
    def test_alert_rules_yaml_valid(self):
        """Test that alert rules YAML is valid."""
        import yaml
        import os
        
        rules_path = "prometheus/alert_rules.yml"
        assert os.path.exists(rules_path), f"Alert rules file not found: {rules_path}"
        
        with open(rules_path, 'r') as f:
            rules = yaml.safe_load(f)
        
        # Verify rules structure
        assert 'groups' in rules
        assert len(rules['groups']) > 0
    
    def test_loop_health_alert_exists(self):
        """Test that loop health alert was added."""
        import yaml
        
        rules_path = "prometheus/alert_rules.yml"
        with open(rules_path, 'r') as f:
            rules = yaml.safe_load(f)
        
        # Find the loop health alert
        all_alerts = []
        for group in rules['groups']:
            for rule in group.get('rules', []):
                all_alerts.append(rule.get('alert', ''))
        
        assert "Loop15mCycleDurationHigh" in all_alerts
    
    def test_loop_health_alert_uses_correct_metric(self):
        """Test that loop health alert uses the cycle duration histogram."""
        import yaml
        
        rules_path = "prometheus/alert_rules.yml"
        with open(rules_path, 'r') as f:
            rules = yaml.safe_load(f)
        
        # Find the loop health alert
        loop_alert = None
        for group in rules['groups']:
            for rule in group.get('rules', []):
                if rule.get('alert') == "Loop15mCycleDurationHigh":
                    loop_alert = rule
                    break
        
        assert loop_alert is not None
        assert 'merid_15m_cycle_duration_seconds' in loop_alert.get('expr', '')
        assert 'quantile_over_time' in loop_alert.get('expr', '')
