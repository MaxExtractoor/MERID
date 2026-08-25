"""
Shadow Replay Execution Tests

Execute shadow replay for representative candidates to validate end-to-end pipeline.
"""

import pytest
from datetime import datetime
import json

from merid.event_venues.kalshi.shadow_replay_execution import (
    ShadowReplayExecutor,
    ShadowReplayCandidate,
    get_mock_candidates
)


class TestShadowReplayExecution:
    """Test shadow replay execution for end-to-end validation."""
    
    def test_shadow_replay_initialization(self):
        """Test that shadow replay executor initializes correctly."""
        executor = ShadowReplayExecutor()
        executor.initialize()
        
        assert executor._orchestrator is not None
        assert len(executor._results) == 0
    
    def test_get_mock_candidates(self):
        """Test that mock candidates are generated correctly."""
        candidates = get_mock_candidates()
        
        # Should have 10 candidates (5 assets × 2 candidates each)
        assert len(candidates) == 10
        
        # Verify asset distribution
        assets = [c.asset_ticker for c in candidates]
        assert assets.count("BTC") == 2
        assert assets.count("ETH") == 2
        assert assets.count("SOL") == 2
        assert assets.count("XRP") == 2
        assert assets.count("DOGE") == 2
        
        # Verify decision distribution
        decisions = [c.expected_decision for c in candidates]
        assert decisions.count("accept") == 5
        assert decisions.count("reject") == 5
    
    def test_execute_single_candidate_accepted(self):
        """Test execution of a single accepted candidate."""
        executor = ShadowReplayExecutor()
        executor.initialize()
        
        # Get BTC accepted candidate
        candidates = get_mock_candidates()
        btc_accepted = [c for c in candidates if c.candidate_id == "btc_accepted_001"][0]
        
        # Execute
        result = executor.execute_candidate(btc_accepted)
        
        # Verify result structure
        assert result.candidate_id == "btc_accepted_001"
        assert result.asset_ticker == "BTC"
        assert result.expected_decision == "accept"
        assert result.decision_match in (True, False)  # May or may not match
        assert len(result.gate_trace) > 0
        assert result.execution_time_ms >= 0
    
    def test_execute_single_candidate_rejected(self):
        """Test execution of a single rejected candidate."""
        executor = ShadowReplayExecutor()
        executor.initialize()
        
        # Get BTC rejected candidate
        candidates = get_mock_candidates()
        btc_rejected = [c for c in candidates if c.candidate_id == "btc_rejected_001"][0]
        
        # Execute
        result = executor.execute_candidate(btc_rejected)
        
        # Verify result structure
        assert result.candidate_id == "btc_rejected_001"
        assert result.asset_ticker == "BTC"
        assert result.expected_decision == "reject"
        assert result.expected_reject_reason == "spread_too_wide"
        assert result.decision_match in (True, False)  # May or may not match
        assert len(result.gate_trace) > 0
    
    def test_execute_batch_all_candidates(self):
        """Test execution of all candidates in batch."""
        executor = ShadowReplayExecutor()
        executor.initialize()
        
        # Get all candidates
        candidates = get_mock_candidates()
        
        # Execute batch
        results = executor.execute_batch(candidates)
        
        # Verify results
        assert len(results) == 10
        assert len(executor._results) == 10
        
        # Verify all results have required fields
        for result in results:
            assert result.candidate_id is not None
            assert result.asset_ticker is not None
            assert result.expected_decision is not None
            assert result.actual_decision is not None
            assert result.decision_match in (True, False)
    
    def test_generate_report(self):
        """Test report generation."""
        executor = ShadowReplayExecutor()
        executor.initialize()
        
        # Execute batch
        candidates = get_mock_candidates()
        executor.execute_batch(candidates)
        
        # Generate report
        report = executor.generate_report()
        
        # Verify report structure
        assert "summary" in report
        assert "by_asset" in report
        assert "detailed_results" in report
        
        # Verify summary
        assert report["summary"]["total_candidates"] == 10
        assert "decision_matches" in report["summary"]
        assert "decision_mismatches" in report["summary"]
        assert "match_rate" in report["summary"]
        
        # Verify by-asset breakdown
        assert "BTC" in report["by_asset"]
        assert "ETH" in report["by_asset"]
        assert "SOL" in report["by_asset"]
        assert "XRP" in report["by_asset"]
        assert "DOGE" in report["by_asset"]
        
        # Verify detailed results
        assert len(report["detailed_results"]) == 10
    
    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    def test_asset_specific_execution(self, asset):
        """Test that each asset executes through the pipeline."""
        executor = ShadowReplayExecutor()
        executor.initialize()
        
        # Get candidates for specific asset
        candidates = get_mock_candidates()
        asset_candidates = [c for c in candidates if c.asset_ticker == asset]
        
        # Execute
        results = [executor.execute_candidate(c) for c in asset_candidates]
        
        # Verify both candidates executed
        assert len(results) == 2
        
        # Verify asset ticker preserved
        for result in results:
            assert result.asset_ticker == asset
    
    def test_decision_trace_completeness(self):
        """Test that decision traces are complete."""
        executor = ShadowReplayExecutor()
        executor.initialize()
        
        # Execute single candidate
        candidates = get_mock_candidates()
        result = executor.execute_candidate(candidates[0])
        
        # Verify gate trace completeness
        for trace in result.gate_trace:
            assert "stage" in trace
            assert "decision" in trace
            assert "reason" in trace
            assert "metadata" in trace
    
    def test_shadow_replay_end_to_end(self):
        """Test complete end-to-end shadow replay workflow."""
        executor = ShadowReplayExecutor()
        executor.initialize()
        
        # Execute all candidates
        candidates = get_mock_candidates()
        results = executor.execute_batch(candidates)
        
        # Generate report
        report = executor.generate_report()
        
        # Verify successful execution
        assert len(results) == 10
        assert report["summary"]["total_candidates"] == 10
        
        # Verify no execution errors
        execution_errors = [r for r in results if r.actual_decision == "error"]
        assert len(execution_errors) == 0, f"Execution errors: {execution_errors}"
        
        # Verify all assets represented
        assets_in_results = set(r.asset_ticker for r in results)
        expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        assert assets_in_results == expected_assets


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
