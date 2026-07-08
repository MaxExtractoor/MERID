"""Tests for KalshiFillsLedger CSV export functionality.

Tests cover the new CSV export mechanism that writes fills to trade_history_7days.csv.
"""

import unittest
import tempfile
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta


class TestCSVExport:
    """Test CSV export functionality in KalshiFillsLedger."""

    def test_export_to_csv_method_exists(self):
        """Verify export_to_csv method exists in KalshiFillsLedger."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
        ledger = KalshiFillsLedger()
        
        # Verify method exists
        assert hasattr(ledger, 'export_to_csv')
        assert callable(getattr(ledger, 'export_to_csv'))

    def test_export_to_csv_signature(self):
        """Verify export_to_csv has correct signature."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
        import inspect
        
        ledger = KalshiFillsLedger()
        sig = inspect.signature(ledger.export_to_csv)
        params = list(sig.parameters.keys())
        
        # Should have csv_path and days parameters
        assert 'csv_path' in params
        assert 'days' in params

    def test_export_to_csv_creates_file(self):
        """Verify export_to_csv creates a CSV file."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
        
        # Use temporary directory for test
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "test_export.csv")
            ledger = KalshiFillsLedger()
            
            # Export to CSV (should work even with no fills)
            count = ledger.export_to_csv(csv_path, days=7)
            
            # Verify file was created
            assert os.path.exists(csv_path)
            
            # Verify file has header
            with open(csv_path, 'r') as f:
                first_line = f.readline()
                assert 'fill_id' in first_line
                assert 'order_id' in first_line
                assert 'market_ticker' in first_line

    def test_export_to_csv_default_path(self):
        """Verify export_to_csv uses default path when not specified."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
        import inspect
        
        ledger = KalshiFillsLedger()
        sig = inspect.signature(ledger.export_to_csv)
        
        # Check default value for csv_path parameter
        csv_path_param = sig.parameters['csv_path']
        assert csv_path_param.default == "trade_history_7days.csv"
        
        # Check default value for days parameter
        days_param = sig.parameters['days']
        assert days_param.default == 7


if __name__ == "__main__":
    unittest.main()
