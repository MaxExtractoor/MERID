"""
Test suite for per-asset best-edge selection algorithm (2026-07-16).

This test suite validates the _select_best_edge_per_asset method which ensures
only 1 contract per asset per 15-minute window is executed, selecting the
optimal combination of edge quality and price efficiency.

Based on prediction market execution research:
- Edge is the primary signal (model probability vs market probability)
- Among similar edges, cheaper contracts provide better risk-adjusted returns
- Lower capital exposure improves Kelly criterion sizing and reduces tail risk
"""

import pytest
from typing import Dict, List
from pathlib import Path


class TestBestEdgePerAssetSelection:
    """Test suite for _select_best_edge_per_asset method."""

    def test_selects_best_edge_single_asset(self):
        """Test that the candidate with highest edge is selected for a single asset."""
        # Mock agent grid instance
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        # Create a minimal mock
        class MockAgentGrid:
            def _select_best_edge_per_asset(self, candidates: List[Dict]) -> List[Dict]:
                # Import the actual implementation
                from merid.prediction.agent_grid_15m import LeanAgentGrid15m
                # Create a real instance to access the method
                grid = LeanAgentGrid15m.__new__(LeanAgentGrid15m)
                return LeanAgentGrid15m._select_best_edge_per_asset(grid, candidates)
        
        mock_grid = MockAgentGrid()
        
        candidates = [
            {
                'agent_id': 'BTC_15M',
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 30,
                'edge_pct': 0.05,  # 5% edge
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'BTC_15M',
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 40,
                'edge_pct': 0.03,  # 3% edge (lower)
                'count': 1,
                'action': 'buy'
            }
        ]
        
        filtered = mock_grid._select_best_edge_per_asset(candidates)
        
        assert len(filtered) == 1, "Should select exactly 1 candidate"
        assert filtered[0]['edge_pct'] == 0.05, "Should select candidate with highest edge"
        assert filtered[0]['price_cents'] == 30, "Should select the 5% edge candidate"

    def test_selects_cheapest_among_similar_edges(self):
        """Test that cheapest contract is selected when edges are similar (within 1% threshold)."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        class MockAgentGrid:
            def _select_best_edge_per_asset(self, candidates: List[Dict]) -> List[Dict]:
                grid = LeanAgentGrid15m.__new__(LeanAgentGrid15m)
                return LeanAgentGrid15m._select_best_edge_per_asset(grid, candidates)
        
        mock_grid = MockAgentGrid()
        
        candidates = [
            {
                'agent_id': 'ETH_15M',
                'asset': 'ETH',
                'ticker': 'KXETH15M-TEST',
                'side': 'yes',
                'price_cents': 50,
                'edge_pct': 0.05,  # 5% edge
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'ETH_15M',
                'asset': 'ETH',
                'ticker': 'KXETH15M-TEST',
                'side': 'yes',
                'price_cents': 30,  # Cheaper
                'edge_pct': 0.051,  # 5.1% edge (within 1% threshold)
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'ETH_15M',
                'asset': 'ETH',
                'ticker': 'KXETH15M-TEST',
                'side': 'yes',
                'price_cents': 40,
                'edge_pct': 0.049,  # 4.9% edge (within 1% threshold)
                'count': 1,
                'action': 'buy'
            }
        ]
        
        filtered = mock_grid._select_best_edge_per_asset(candidates)
        
        assert len(filtered) == 1, "Should select exactly 1 candidate"
        assert filtered[0]['price_cents'] == 30, "Should select cheapest among similar edges"
        # Should be one of the similar edges (5.1%, 5.0%, or 4.9%)
        assert filtered[0]['edge_pct'] >= 0.049, "Edge should be within similar range"

    def test_selects_one_per_asset_multiple_assets(self):
        """Test that exactly 1 candidate is selected per asset when multiple assets have candidates."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        class MockAgentGrid:
            def _select_best_edge_per_asset(self, candidates: List[Dict]) -> List[Dict]:
                grid = LeanAgentGrid15m.__new__(LeanAgentGrid15m)
                return LeanAgentGrid15m._select_best_edge_per_asset(grid, candidates)
        
        mock_grid = MockAgentGrid()
        
        candidates = [
            # BTC candidates
            {
                'agent_id': 'BTC_15M',
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 30,
                'edge_pct': 0.05,
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'BTC_15M',
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 40,
                'edge_pct': 0.03,
                'count': 1,
                'action': 'buy'
            },
            # ETH candidates
            {
                'agent_id': 'ETH_15M',
                'asset': 'ETH',
                'ticker': 'KXETH15M-TEST',
                'side': 'yes',
                'price_cents': 25,
                'edge_pct': 0.04,
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'ETH_15M',
                'asset': 'ETH',
                'ticker': 'KXETH15M-TEST',
                'side': 'yes',
                'price_cents': 35,
                'edge_pct': 0.06,
                'count': 1,
                'action': 'buy'
            },
            # SOL candidates
            {
                'agent_id': 'SOL_15M',
                'asset': 'SOL',
                'ticker': 'KXSOL15M-TEST',
                'side': 'yes',
                'price_cents': 20,
                'edge_pct': 0.07,
                'count': 1,
                'action': 'buy'
            }
        ]
        
        filtered = mock_grid._select_best_edge_per_asset(candidates)
        
        assert len(filtered) == 3, "Should select 1 candidate per asset (BTC, ETH, SOL)"
        
        # Verify we have exactly one per asset
        assets = {c['asset'] for c in filtered}
        assert assets == {'BTC', 'ETH', 'SOL'}, "Should have one candidate for each asset"
        
        # Verify best edges were selected
        btc_candidate = next(c for c in filtered if c['asset'] == 'BTC')
        eth_candidate = next(c for c in filtered if c['asset'] == 'ETH')
        sol_candidate = next(c for c in filtered if c['asset'] == 'SOL')
        
        assert btc_candidate['edge_pct'] == 0.05, "BTC should have 5% edge (best)"
        assert eth_candidate['edge_pct'] == 0.06, "ETH should have 6% edge (best)"
        assert sol_candidate['edge_pct'] == 0.07, "SOL should have 7% edge (best)"

    def test_filters_unknown_assets(self):
        """Test that unknown assets are filtered out."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        class MockAgentGrid:
            def _select_best_edge_per_asset(self, candidates: List[Dict]) -> List[Dict]:
                grid = LeanAgentGrid15m.__new__(LeanAgentGrid15m)
                return LeanAgentGrid15m._select_best_edge_per_asset(grid, candidates)
        
        mock_grid = MockAgentGrid()
        
        candidates = [
            {
                'agent_id': 'BTC_15M',
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 30,
                'edge_pct': 0.05,
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'UNKNOWN_15M',
                'asset': 'UNKNOWN',
                'ticker': 'KXUNKNOWN-TEST',
                'side': 'yes',
                'price_cents': 30,
                'edge_pct': 0.05,
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'INVALID',
                'asset': 'INVALID',
                'ticker': 'KXINVALID-TEST',
                'side': 'yes',
                'price_cents': 30,
                'edge_pct': 0.05,
                'count': 1,
                'action': 'buy'
            }
        ]
        
        filtered = mock_grid._select_best_edge_per_asset(candidates)
        
        assert len(filtered) == 1, "Should filter out unknown assets"
        assert filtered[0]['asset'] == 'BTC', "Should only keep BTC"

    def test_handles_empty_candidates(self):
        """Test that empty candidate list returns empty list."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        class MockAgentGrid:
            def _select_best_edge_per_asset(self, candidates: List[Dict]) -> List[Dict]:
                grid = LeanAgentGrid15m.__new__(LeanAgentGrid15m)
                return LeanAgentGrid15m._select_best_edge_per_asset(grid, candidates)
        
        mock_grid = MockAgentGrid()
        
        filtered = mock_grid._select_best_edge_per_asset([])
        
        assert len(filtered) == 0, "Empty input should return empty output"

    def test_handles_all_five_crypto_assets(self):
        """Test that all 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) are handled correctly."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        class MockAgentGrid:
            def _select_best_edge_per_asset(self, candidates: List[Dict]) -> List[Dict]:
                grid = LeanAgentGrid15m.__new__(LeanAgentGrid15m)
                return LeanAgentGrid15m._select_best_edge_per_asset(grid, candidates)
        
        mock_grid = MockAgentGrid()
        
        candidates = [
            {
                'agent_id': 'BTC_15M',
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 30,
                'edge_pct': 0.05,
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'ETH_15M',
                'asset': 'ETH',
                'ticker': 'KXETH15M-TEST',
                'side': 'yes',
                'price_cents': 25,
                'edge_pct': 0.04,
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'SOL_15M',
                'asset': 'SOL',
                'ticker': 'KXSOL15M-TEST',
                'side': 'yes',
                'price_cents': 20,
                'edge_pct': 0.07,
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'XRP_15M',
                'asset': 'XRP',
                'ticker': 'KXXRP15M-TEST',
                'side': 'yes',
                'price_cents': 15,
                'edge_pct': 0.06,
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'DOGE_15M',
                'asset': 'DOGE',
                'ticker': 'KXDOGE15M-TEST',
                'side': 'yes',
                'price_cents': 10,
                'edge_pct': 0.08,
                'count': 1,
                'action': 'buy'
            }
        ]
        
        filtered = mock_grid._select_best_edge_per_asset(candidates)
        
        assert len(filtered) == 5, "Should select 1 candidate for each of 5 assets"
        assets = {c['asset'] for c in filtered}
        assert assets == {'BTC', 'ETH', 'SOL', 'XRP', 'DOGE'}, "Should have all 5 crypto assets"

    def test_edge_similarity_threshold_boundary(self):
        """Test edge similarity threshold behavior at boundary (1% = 0.01)."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        class MockAgentGrid:
            def _select_best_edge_per_asset(self, candidates: List[Dict]) -> List[Dict]:
                grid = LeanAgentGrid15m.__new__(LeanAgentGrid15m)
                return LeanAgentGrid15m._select_best_edge_per_asset(grid, candidates)
        
        mock_grid = MockAgentGrid()
        
        candidates = [
            {
                'agent_id': 'BTC_15M',
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 50,
                'edge_pct': 0.05,  # 5% edge
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'BTC_15M',
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 30,  # Cheaper
                'edge_pct': 0.051,  # 5.1% edge (within 1% threshold: 0.051 - 0.05 = 0.001 < 0.01)
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'BTC_15M',
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 40,
                'edge_pct': 0.061,  # 6.1% edge (outside 1% threshold: 0.061 - 0.05 = 0.011 > 0.01)
                'count': 1,
                'action': 'buy'
            }
        ]
        
        filtered = mock_grid._select_best_edge_per_asset(candidates)
        
        assert len(filtered) == 1, "Should select exactly 1 candidate"
        # Should select the 6.1% edge (best edge, outside similarity threshold)
        assert filtered[0]['edge_pct'] == 0.061, "Should select edge outside similarity threshold"

    def test_preserves_candidate_fields(self):
        """Test that all candidate fields are preserved in filtered output."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        class MockAgentGrid:
            def _select_best_edge_per_asset(self, candidates: List[Dict]) -> List[Dict]:
                grid = LeanAgentGrid15m.__new__(LeanAgentGrid15m)
                return LeanAgentGrid15m._select_best_edge_per_asset(grid, candidates)
        
        mock_grid = MockAgentGrid()
        
        candidates = [
            {
                'agent_id': 'BTC_15M',
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 30,
                'edge_pct': 0.05,
                'count': 1,
                'action': 'buy',
                'model_prob': 0.55,
                'confidence': 0.8,
                'custom_field': 'test_value'
            }
        ]
        
        filtered = mock_grid._select_best_edge_per_asset(candidates)
        
        assert len(filtered) == 1
        assert filtered[0]['agent_id'] == 'BTC_15M'
        assert filtered[0]['ticker'] == 'KXBTC15M-TEST'
        assert filtered[0]['side'] == 'yes'
        assert filtered[0]['price_cents'] == 30
        assert filtered[0]['edge_pct'] == 0.05
        assert filtered[0]['count'] == 1
        assert filtered[0]['action'] == 'buy'
        assert filtered[0]['model_prob'] == 0.55
        assert filtered[0]['confidence'] == 0.8
        assert filtered[0]['custom_field'] == 'test_value'

    def test_handles_agent_id_without_underscore(self):
        """Test asset extraction when agent_id doesn't have underscore."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        class MockAgentGrid:
            def _select_best_edge_per_asset(self, candidates: List[Dict]) -> List[Dict]:
                grid = LeanAgentGrid15m.__new__(LeanAgentGrid15m)
                return LeanAgentGrid15m._select_best_edge_per_asset(grid, candidates)
        
        mock_grid = MockAgentGrid()
        
        candidates = [
            {
                'agent_id': 'BTC',  # No underscore
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 30,
                'edge_pct': 0.05,
                'count': 1,
                'action': 'buy'
            }
        ]
        
        filtered = mock_grid._select_best_edge_per_asset(candidates)
        
        assert len(filtered) == 1, "Should handle agent_id without underscore"
        assert filtered[0]['asset'] == 'BTC'

    def test_handles_missing_agent_id(self):
        """Test asset extraction when agent_id is missing."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        class MockAgentGrid:
            def _select_best_edge_per_asset(self, candidates: List[Dict]) -> List[Dict]:
                grid = LeanAgentGrid15m.__new__(LeanAgentGrid15m)
                return LeanAgentGrid15m._select_best_edge_per_asset(grid, candidates)
        
        mock_grid = MockAgentGrid()
        
        candidates = [
            {
                'asset': 'ETH',  # Asset field present, agent_id missing
                'ticker': 'KXETH15M-TEST',
                'side': 'yes',
                'price_cents': 30,
                'edge_pct': 0.05,
                'count': 1,
                'action': 'buy'
            }
        ]
        
        filtered = mock_grid._select_best_edge_per_asset(candidates)
        
        assert len(filtered) == 1, "Should handle missing agent_id"
        assert filtered[0]['asset'] == 'ETH'


class TestBestEdgeIntegrationWithDeduplication:
    """Test integration of best-edge selection with existing deduplication mechanism."""

    def test_best_edge_filter_reduces_duplicate_executions(self):
        """Test that best-edge filter reduces need for deduplication."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        class MockAgentGrid:
            def _select_best_edge_per_asset(self, candidates: List[Dict]) -> List[Dict]:
                grid = LeanAgentGrid15m.__new__(LeanAgentGrid15m)
                return LeanAgentGrid15m._select_best_edge_per_asset(grid, candidates)
        
        mock_grid = MockAgentGrid()
        
        # Multiple candidates for same asset at different prices
        candidates = [
            {
                'agent_id': 'BTC_15M',
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 30,
                'edge_pct': 0.05,
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'BTC_15M',
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 40,
                'edge_pct': 0.04,
                'count': 1,
                'action': 'buy'
            },
            {
                'agent_id': 'BTC_15M',
                'asset': 'BTC',
                'ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'price_cents': 50,
                'edge_pct': 0.03,
                'count': 1,
                'action': 'buy'
            }
        ]
        
        filtered = mock_grid._select_best_edge_per_asset(candidates)
        
        assert len(filtered) == 1, "Should reduce 3 candidates to 1"
        # Deduplication key would be different for each original candidate
        # But after filtering, only 1 remains, so deduplication is less critical

    def test_loop_15m_no_duplicate_best_edge_selection(self):
        """Test that loop_15m.py no longer has duplicate best-edge selection logic.
        
        CRITICAL FIX (2026-07-16): loop_15m.py previously had its own best-edge
        selection logic that conflicted with agent_grid_15m._select_best_edge_per_asset.
        This test verifies that loop_15m.py now defers to agent_grid_15m for
        per-asset filtering and only handles swing mode and edge validation.
        """
        loop_path = Path('merid/loop_15m.py')
        if not loop_path.exists():
            pytest.skip("loop_15m.py not found")
        
        source = loop_path.read_text(encoding='utf-8')
        
        # Verify that loop_15m.py has the CRITICAL FIX comment indicating it defers to agent_grid_15m
        assert "CRITICAL FIX (2026-07-16): Best-edge selection is now handled in agent_grid_15m" in source, \
            "loop_15m.py should have comment indicating best-edge selection is handled in agent_grid_15m"
        
        # Verify that loop_15m.py no longer has the old best-edge comparison logic
        # The old logic had: "if abs(edge) > min_edge_threshold or abs(edge) > abs(current_best_edge)"
        # This should NOT be present in the execution loop anymore
        assert "abs(edge) > abs(current_best_edge)" not in source, \
            "loop_15m.py should not have old best-edge comparison logic (delegated to agent_grid_15m)"
        
        # Verify that loop_15m.py still has swing mode logic (this is the only per-asset check it should do)
        assert "swing_mode" in source, \
            "loop_15m.py should still have swing mode logic"
        
        # Verify that loop_15m.py still has edge validation (this is separate from best-edge selection)
        assert "validate_edge" in source, \
            "loop_15m.py should still have edge validation"
        
        # Verify that loop_15m.py has the simplified position check
        assert "if has_position and not is_swing_reversal" in source, \
            "loop_15m.py should have simplified position check (only skip if has position and not swing reversal)"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
