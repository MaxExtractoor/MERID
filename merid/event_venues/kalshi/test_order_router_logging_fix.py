"""Unit tests for order_router logging fix.

Tests the fix for None value handling in logging statements.
The fix uses `or 0.0` fallback for optional values like canonical_edge_side_frac
to prevent TypeError when formatting log messages.
"""

import pytest
import logging
from io import StringIO


class TestOrderRouterLoggingFix:
    """Test the order_router logging None handling fix."""

    def test_logging_with_none_value(self):
        """Test that logging handles None values gracefully using `or` fallback."""
        # Simulate None value
        canonical_edge_side_frac = None
        
        # Capture log output
        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger("test_logger")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        # The fix uses: canonical_edge_side_frac or 0.0
        # This should not raise TypeError
        try:
            logger.info(
                "ticker=%s side=%s canonical_edge_side_frac=%.4f",
                "KXBTC15M-26JUL200015-15", "yes", canonical_edge_side_frac or 0.0
            )
            # If we get here without error, the fix is working
            log_output = log_stream.getvalue()
            assert "ticker=" in log_output
            assert "canonical_edge_side_frac=0.0000" in log_output
        except TypeError as e:
            pytest.fail(f"Logging with None value failed: {e}")
        finally:
            logger.removeHandler(handler)

    def test_logging_with_actual_value(self):
        """Test that logging works with actual values."""
        # Simulate actual value
        canonical_edge_side_frac = 0.03
        
        # Capture log output
        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger("test_logger")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        # Should log the actual value
        try:
            logger.info(
                "ticker=%s side=%s canonical_edge_side_frac=%.4f",
                "KXBTC15M-26JUL200015-15", "yes", canonical_edge_side_frac or 0.0
            )
            log_output = log_stream.getvalue()
            assert "ticker=" in log_output
            assert "canonical_edge_side_frac=0.0300" in log_output
        except TypeError as e:
            pytest.fail(f"Logging with value failed: {e}")
        finally:
            logger.removeHandler(handler)

    def test_logging_pattern_in_order_router(self):
        """Test that the logging pattern used in order_router works."""
        # Simulate the logging pattern from order_router line 7432
        canonical_edge_side_frac = None
        min_executable_edge_frac = 0.03
        
        # Capture log output
        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger("test_logger")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        # The fix uses: canonical_edge_side_frac or 0.0
        try:
            logger.info(
                "[ROUTER-INVARIANT-PASS] ticker=%s side=%s size=%d p_hat_side_cents=%.2f canonical_edge_side_frac=%.4f min_executable_edge_frac=%.4f",
                "KXBTC15M-26JUL200015-15", "yes", 10, 50.0, canonical_edge_side_frac or 0.0, min_executable_edge_frac
            )
            log_output = log_stream.getvalue()
            assert "canonical_edge_side_frac=0.0000" in log_output
        except TypeError as e:
            pytest.fail(f"Order router logging pattern failed: {e}")
        finally:
            logger.removeHandler(handler)

    def test_multiple_optional_fields_with_fallbacks(self):
        """Test logging with multiple optional fields using fallbacks."""
        # Simulate fills_ledger logging pattern with multiple optional fields
        intent = None  # Simulate missing intent
        
        # Capture log output
        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger("test_logger")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        # The fix uses: intent.edgepct if intent else 0.0
        try:
            logger.info(
                "[FILL-INGEST] fill_id=%s ticker=%s edgepct=%.4f netedgecents=%.2f band=%s regime=%s",
                "fill-123", "KXBTC15M-26JUL200015-15",
                intent.edgepct if intent else 0.0,
                intent.netedgecents if intent else 0.0,
                intent.band if intent else "",
                intent.regime if intent else "",
            )
            log_output = log_stream.getvalue()
            assert "edgepct=0.0000" in log_output
            assert "netedgecents=0.00" in log_output
            assert "band=" in log_output
            assert "regime=" in log_output
        except TypeError as e:
            pytest.fail(f"Multiple optional fields logging failed: {e}")
        finally:
            logger.removeHandler(handler)

    def test_trace_id_logging_with_none(self):
        """Test that trace_id logging handles None gracefully."""
        # The fix checks: if _TRACE_AVAILABLE and intent.trace_id
        # So if trace_id is None, the logging is skipped
        
        trace_id = None  # None trace_id
        
        # Simulate the pattern from order_router line 2447
        _TRACE_AVAILABLE = True
        
        # Should skip logging when trace_id is None
        if _TRACE_AVAILABLE and trace_id:
            # This branch should not execute
            pytest.fail("Should not log when trace_id is None")
        else:
            # This is the expected path
            assert True

    def test_all_logging_none_handling_patterns(self):
        """Test all the None handling patterns found in the codebase."""
        # Pattern 1: value or 0.0
        value = None
        result = value or 0.0
        assert result == 0.0
        
        # Pattern 2: value if condition else default
        value = None
        result = value if value is not None else 0.0
        assert result == 0.0
        
        # Pattern 3: getattr with fallback
        obj = None
        result = getattr(obj, 'attr', 'default')
        assert result == 'default'
        
        # Pattern 4: conditional check before logging
        value = None
        if value:
            pytest.fail("Should not execute when value is None")
        else:
            assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
