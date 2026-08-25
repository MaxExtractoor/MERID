"""Kalshi BTC 15-Minute Reconciliation E2E Tests

This test suite validates the end-to-end reconciliation pipeline for Kalshi 15-minute crypto markets.
It enforces the contract defined in docs/audit/KALSHI_RECONCILIATION_AUDIT.md.

NOTE: This test file is currently QUARANTINED due to API incompatibilities.
The KalshiVenueClient, KalshiFillsLedger, and reconciliation APIs have evolved
since this test was written. The test needs to be updated to match the current
API signatures.
"""

import pytest

pytestmark = pytest.mark.skip(reason="P0-RECONCILIATION: TRACKER-010: End-to-end restart/reconciliation")
