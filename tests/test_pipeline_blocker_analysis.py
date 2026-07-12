"""
Tests for Trading Pipeline Blocker Analysis Script

Tests the comprehensive pipeline analysis that covers:
- Upstream (Configuration Layer)
- Midstream (Risk Envelope Layer)
- Downstream (Sizing & Execution Layer)
- End-to-End (Latency, State, Network)
"""

import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from analyze_trading_pipeline_blockers import (
    TradingPipelineAnalyzer,
    PipelineIssue,
    PipelineMetrics
)


class TestTradingPipelineAnalyzer(unittest.TestCase):
    """Test cases for TradingPipelineAnalyzer."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.analyzer = TradingPipelineAnalyzer()
    
    def test_analyzer_initialization(self):
        """Test analyzer initializes correctly."""
        self.assertIsNotNone(self.analyzer)
        self.assertEqual(len(self.analyzer.issues), 0)
        self.assertIsNotNone(self.analyzer.metrics)
    
    def test_percentile_calculation(self):
        """Test percentile calculation accuracy."""
        data = [10, 20, 30, 40, 50]
        
        p50 = self.analyzer._percentile(data, 50)
        self.assertEqual(p50, 30)
        
        p95 = self.analyzer._percentile(data, 95)
        self.assertEqual(p95, 48.0)  # Linear interpolation
        
        p99 = self.analyzer._percentile(data, 99)
        self.assertEqual(p99, 49.6)  # Linear interpolation
    
    def test_percentile_empty_data(self):
        """Test percentile with empty data returns 0."""
        result = self.analyzer._percentile([], 50)
        self.assertEqual(result, 0.0)
    
    def test_pipeline_issue_creation(self):
        """Test PipelineIssue dataclass creation."""
        issue = PipelineIssue(
            layer="upstream",
            severity="critical",
            category="config",
            description="Test issue",
            details="Test details"
        )
        
        self.assertEqual(issue.layer, "upstream")
        self.assertEqual(issue.severity, "critical")
        self.assertEqual(issue.category, "config")
        self.assertEqual(issue.description, "Test issue")
        self.assertEqual(issue.details, "Test details")
    
    @patch('analyze_trading_pipeline_blockers.Path')
    def test_profile_validation_missing_file(self, mock_path):
        """Test profile validation when file is missing."""
        mock_path.return_value.exists.return_value = False
        
        result = self.analyzer._validate_profile_structure({})
        
        self.assertFalse(result["valid"])
        self.assertIn("Missing required field", result["errors"][0])
    
    def test_profile_validation_missing_fields(self):
        """Test profile validation with missing required fields."""
        profile_data = {"profile_name": "test"}  # Missing other required fields
        
        result = self.analyzer._validate_profile_structure(profile_data)
        
        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)
    
    def test_profile_validation_valid(self):
        """Test profile validation with valid data."""
        profile_data = {
            "profile_name": "kalshi_crypto_15m_v2",
            "profile_version": "2.4.0",
            "description": "Test profile",
            "operation_mode": "prod",
            "guardrails": {}
        }
        
        result = self.analyzer._validate_profile_structure(profile_data)
        
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["errors"]), 0)
    
    @patch('analyze_trading_pipeline_blockers.os.environ.get')
    def test_environment_validation(self, mock_get):
        """Test environment variable validation."""
        mock_get.side_effect = lambda k, d=None: "kalshi_crypto_15m_v2" if k == "MERID_PROFILE" else d
        
        result = self.analyzer._validate_environment()
        
        self.assertIn("current_values", result)
        self.assertIn("MERID_PROFILE", result["current_values"])
    
    def test_risk_limits_consistency_bankroll_not_ready(self):
        """Test risk limits check handles bankroll not ready gracefully."""
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get:
            mock_get.side_effect = RuntimeError("Bankroll not ready: $None")
            
            result = self.analyzer._check_risk_limits_consistency()
            
            self.assertIn("Bankroll not ready", result["issues"][0])
            # Should be low severity, not critical
            bankroll_issue = [i for i in self.analyzer.issues if "Bankroll not ready" in i.description]
            self.assertEqual(len(bankroll_issue), 1)
            self.assertEqual(bankroll_issue[0].severity, "low")
    
    def test_profile_adapter_check(self):
        """Test profile adapter consistency check."""
        with patch('merid.risk.profiles.crypto_15m_profile.Crypto15mProfileAdapter') as mock_adapter:
            mock_instance = Mock()
            mock_instance.profile = Mock()
            mock_adapter.return_value = mock_instance
            
            result = self.analyzer._check_profile_adapter()
            
            self.assertTrue(result["profile_loaded"])
            self.assertEqual(len(result["adapter_issues"]), 0)
    
    def test_unified_sizing_verification(self):
        """Test unified sizing logic verification."""
        with patch('merid.prediction.unified_sizing.compute_order_size', return_value=Mock()):
            result = self.analyzer._verify_unified_sizing()
            
            self.assertTrue(result["sizing_module_loaded"])
            self.assertEqual(len(result["sizing_issues"]), 0)
    
    def test_order_queue_analysis(self):
        """Test order queue depth analysis."""
        with patch('merid.event_venues.kalshi.order_router_15m.Kalshi15mOrderRouter'):
            result = self.analyzer._analyze_order_queues()
            
            self.assertIn("queue_depths", result)
            self.assertIn("order_queue", result["queue_depths"])
            self.assertIn("fill_queue", result["queue_depths"])
    
    def test_latency_measurement(self):
        """Test latency percentile measurements."""
        result = self.analyzer._measure_latency()
        
        self.assertIn("p50_ms", result)
        self.assertIn("p95_ms", result)
        self.assertIn("p99_ms", result)
        self.assertIn("p999_ms", result)
        self.assertGreater(result["p50_ms"], 0)
        self.assertGreaterEqual(result["p99_ms"], result["p50_ms"])
    
    def test_sequence_gap_detection(self):
        """Test sequence gap detection."""
        result = self.analyzer._detect_sequence_gaps()
        
        self.assertIn("feeds_checked", result)
        self.assertIn("gaps_found", result)
        self.assertEqual(result["feeds_checked"], 5)  # BTC, ETH, SOL, XRP, DOGE
    
    def test_state_drift_analysis(self):
        """Test state drift analysis."""
        result = self.analyzer._analyze_state_drift()
        
        self.assertIn("components_checked", result)
        self.assertIn("drift_detected", result)
        self.assertFalse(result["drift_detected"])
    
    def test_memory_pattern_analysis(self):
        """Test memory allocation pattern analysis."""
        result = self.analyzer._analyze_memory_patterns()
        
        self.assertIn("memory_usage_mb", result)
        self.assertIn("gc_collections", result)
        self.assertGreater(result["memory_usage_mb"], 0)
    
    def test_thread_blocking_detection(self):
        """Test thread blocking detection."""
        result = self.analyzer._detect_thread_blocking()
        
        self.assertIn("threads_checked", result)
        self.assertIn("blocked_threads", result)
        self.assertEqual(result["blocked_threads"], 0)
    
    @patch('analyze_trading_pipeline_blockers.open', create=True)
    @patch('analyze_trading_pipeline_blockers.yaml.safe_load')
    @patch('analyze_trading_pipeline_blockers.Path')
    def test_upstream_analysis_with_valid_profile(self, mock_path, mock_yaml, mock_open):
        """Test upstream analysis with valid profile."""
        mock_path.return_value.exists.return_value = True
        mock_yaml.return_value = {
            "profile_name": "kalshi_crypto_15m_v2",
            "profile_version": "2.4.0",
            "description": "Test",
            "operation_mode": "prod",
            "guardrails": {}
        }
        mock_open.return_value.__enter__.return_value = Mock()
        
        result = self.analyzer.analyze_upstream()
        
        self.assertIn("profile_validation", result)
        self.assertIn("risk_limits", result)
        self.assertIn("asset_config", result)
        self.assertIn("environment", result)
    
    def test_midstream_analysis(self):
        """Test midstream analysis."""
        with patch.object(self.analyzer, '_verify_risk_envelope', return_value={"bankroll": None, "calculation_issues": []}), \
             patch.object(self.analyzer, '_check_profile_adapter', return_value={"profile_loaded": True, "adapter_issues": []}), \
             patch.object(self.analyzer, '_verify_conversions', return_value={"test_conversions": [], "conversion_issues": []}), \
             patch.object(self.analyzer, '_verify_asset_caps', return_value={"caps_enforced": True, "enforcement_issues": []}):
            
            result = self.analyzer.analyze_midstream()
            
            self.assertIn("risk_envelope", result)
            self.assertIn("profile_adapter", result)
            self.assertIn("conversions", result)
            self.assertIn("asset_caps", result)
    
    def test_downstream_analysis(self):
        """Test downstream analysis."""
        with patch.object(self.analyzer, '_verify_unified_sizing', return_value={"sizing_module_loaded": True, "sizing_issues": []}), \
             patch.object(self.analyzer, '_check_position_multipliers', return_value={"multipliers_disabled": True, "multiplier_issues": []}), \
             patch.object(self.analyzer, '_analyze_order_queues', return_value={"queue_depths": {}, "queue_issues": []}), \
             patch.object(self.analyzer, '_detect_lock_contention', return_value={"locks_analyzed": 1, "contention_detected": False, "contention_issues": []}), \
             patch.object(self.analyzer, '_monitor_buffer_status', return_value={"buffers_checked": 3, "buffer_status": {}, "buffer_issues": []}):
            
            result = self.analyzer.analyze_downstream()
            
            self.assertIn("unified_sizing", result)
            self.assertIn("position_multipliers", result)
            self.assertIn("order_queues", result)
            self.assertIn("lock_contention", result)
            self.assertIn("buffer_status", result)
    
    def test_end_to_end_analysis(self):
        """Test end-to-end analysis."""
        with patch.object(self.analyzer, '_measure_latency', return_value={"p50_ms": 10, "p95_ms": 15, "p99_ms": 20, "p999_ms": 25, "latency_issues": []}), \
             patch.object(self.analyzer, '_detect_sequence_gaps', return_value={"feeds_checked": 5, "gaps_found": 0, "gap_details": [], "sequence_issues": []}), \
             patch.object(self.analyzer, '_analyze_state_drift', return_value={"components_checked": 3, "drift_detected": False, "drift_details": [], "state_issues": []}), \
             patch.object(self.analyzer, '_analyze_memory_patterns', return_value={"memory_usage_mb": 100, "gc_collections": 50, "memory_issues": []}), \
             patch.object(self.analyzer, '_detect_thread_blocking', return_value={"threads_checked": 1, "blocked_threads": 0, "blocking_details": [], "blocking_issues": []}):
            
            result = self.analyzer.analyze_end_to_end()
            
            self.assertIn("latency_analysis", result)
            self.assertIn("sequence_validation", result)
            self.assertIn("state_drift", result)
            self.assertIn("memory_patterns", result)
            self.assertIn("thread_blocking", result)
    
    def test_analyze_all_integration(self):
        """Test full analysis integration."""
        with patch.object(self.analyzer, 'analyze_upstream', return_value={}), \
             patch.object(self.analyzer, 'analyze_midstream', return_value={}), \
             patch.object(self.analyzer, 'analyze_downstream', return_value={}), \
             patch.object(self.analyzer, 'analyze_end_to_end', return_value={}):
            
            result = self.analyzer.analyze_all()
            
            self.assertIn("timestamp", result)
            self.assertIn("analysis_duration_seconds", result)
            self.assertIn("issues", result)
            self.assertIn("metrics", result)
            self.assertIn("upstream", result)
            self.assertIn("midstream", result)
            self.assertIn("downstream", result)
            self.assertIn("end_to_end", result)


class TestPipelineIssue(unittest.TestCase):
    """Test cases for PipelineIssue dataclass."""
    
    def test_issue_creation(self):
        """Test creating a pipeline issue."""
        issue = PipelineIssue(
            layer="upstream",
            severity="critical",
            category="config",
            description="Test",
            details="Test details"
        )
        
        self.assertEqual(issue.layer, "upstream")
        self.assertEqual(issue.severity, "critical")
        self.assertEqual(issue.category, "config")
    
    def test_issue_with_evidence(self):
        """Test creating issue with evidence."""
        evidence = {"test_key": "test_value"}
        issue = PipelineIssue(
            layer="midstream",
            severity="high",
            category="memory",
            description="Memory issue",
            details="Out of memory",
            evidence=evidence
        )
        
        self.assertEqual(issue.evidence, evidence)


class TestPipelineMetrics(unittest.TestCase):
    """Test cases for PipelineMetrics dataclass."""
    
    def test_metrics_initialization(self):
        """Test metrics initialization."""
        metrics = PipelineMetrics()
        
        self.assertEqual(metrics.latency_samples, [])
        self.assertEqual(metrics.queue_depths, {})
        self.assertEqual(metrics.lock_contention_counts, {})
        self.assertEqual(metrics.buffer_usage, {})
        self.assertEqual(metrics.sequence_gaps, [])
        self.assertEqual(metrics.memory_allocations, {})
        self.assertEqual(metrics.thread_states, {})
    
    def test_metrics_with_data(self):
        """Test metrics with sample data."""
        metrics = PipelineMetrics(
            latency_samples=[10.5, 12.3, 11.8],
            queue_depths={"order_queue": 5},
            lock_contention_counts={"mutex1": 10}
        )
        
        self.assertEqual(len(metrics.latency_samples), 3)
        self.assertEqual(metrics.queue_depths["order_queue"], 5)
        self.assertEqual(metrics.lock_contention_counts["mutex1"], 10)


if __name__ == '__main__':
    unittest.main()
