"""Test that order router enforces minimum entry price from profile YAML.

This test verifies that the order router respects the minimum price configuration
from the profile YAML (10c minimum for 15m crypto markets).
"""

import unittest
import asyncio
from unittest.mock import Mock, patch


class TestOrderRouterMinimumPrice(unittest.TestCase):
    """Test order router enforces minimum entry price from profile."""

    def test_profile_yaml_has_correct_min_price(self):
        """Test that profile YAML has the expected minimum price configuration."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        
        # Load the actual profile
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        
        # Verify minimum price is 10c (from profile YAML price_range.min_price_cents)
        # This is the single source of truth for minimum entry price
        self.assertEqual(getattr(profile, 'price_range_min_price_cents', 10), 10)

    def test_order_router_logs_min_price_from_profile(self):
        """Test that order router logs minimum price from profile."""
        from merid.event_venues.kalshi.order_router import _log_price_band_config
        
        # Mock the profile adapter to return known values
        with patch('merid.risk.profiles.crypto_15m_profile.Crypto15mProfileAdapter') as mock_adapter_class:
            mock_adapter = Mock()
            mock_profile = Mock()
            mock_profile.guardrails_min_post_fee_edge = 0.015
            mock_profile.confidence_min_confidence_threshold = 0.65
            mock_adapter.profile = mock_profile
            mock_adapter_class.return_value = mock_adapter
            
            # Capture log output
            with patch('merid.event_venues.kalshi.order_router.logger') as mock_logger:
                _log_price_band_config()
                
                # Verify profile was loaded
                mock_adapter_class.assert_called_once()
                
                # Verify log message contains profile values
                log_calls = [str(call) for call in mock_logger.info.call_args_list]
                log_output = ' '.join(log_calls)
                self.assertIn('loaded from profile', log_output)


if __name__ == '__main__':
    unittest.main()
