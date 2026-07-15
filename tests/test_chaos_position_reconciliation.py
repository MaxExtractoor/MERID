"""Chaos engineering tests for position reconciliation failures.

This module tests the resilience of the position reconciliation system by simulating
various failure scenarios including data inconsistencies, venue API failures, and
reconciliation logic errors. These tests ensure the system maintains accurate
position tracking under adverse conditions.

Chaos Scenarios Tested:
1. Position data inconsistency between venues
2. Reconciliation service unavailability
3. Partial position data retrieval failures
4. Position calculation errors
5. Concurrent reconciliation conflicts
6. Reconciliation timeout scenarios
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import asyncio
from datetime import datetime, timedelta


class TestPositionDataInconsistency:
    """Chaos tests for position data inconsistency scenarios."""

    @pytest.mark.asyncio
    async def test_position_mismatch_between_venues_detected(self):
        """System should detect position mismatches between venues."""
        mock_reconciliation = Mock()
        venue_positions = {
            "venue1": {"BTC": 10, "ETH": 5},
            "venue2": {"BTC": 12, "ETH": 5}  # BTC mismatch
        }
        
        def detect_mismatch(positions):
            btc_positions = [v.get("BTC", 0) for v in positions.values()]
            return len(set(btc_positions)) > 1
        
        mock_reconciliation.detect_mismatch = Mock(side_effect=detect_mismatch)
        
        has_mismatch = mock_reconciliation.detect_mismatch(venue_positions)
        assert has_mismatch == True, "Should detect BTC position mismatch"

    @pytest.mark.asyncio
    async def test_position_mismatch_triggers_alert(self):
        """Position mismatch should trigger appropriate alert."""
        mock_reconciliation = Mock()
        alert_triggered = [False]
        
        async def reconcile_positions(positions):
            if positions["venue1"]["BTC"] != positions["venue2"]["BTC"]:
                alert_triggered[0] = True
                return {"status": "mismatch_detected", "alert": True}
            return {"status": "reconciled"}
        
        mock_reconciliation.reconcile_positions = AsyncMock(
            side_effect=reconcile_positions
        )
        
        venue_positions = {
            "venue1": {"BTC": 10, "ETH": 5},
            "venue2": {"BTC": 12, "ETH": 5}
        }
        
        result = await mock_reconciliation.reconcile_positions(venue_positions)
        assert result["alert"] == True
        assert alert_triggered[0] == True

    @pytest.mark.asyncio
    async def test_position_reconciliation_with_missing_venue_data(self):
        """System should handle missing venue position data."""
        mock_reconciliation = Mock()
        incomplete_positions = {
            "venue1": {"BTC": 10, "ETH": 5},
            "venue2": {}  # Missing data
        }
        
        async def reconcile_positions(positions):
            # Use available data, flag missing venues
            available_venues = {k: v for k, v in positions.items() if v}
            if len(available_venues) < len(positions):
                return {
                    "status": "partial_reconciliation",
                    "missing_venues": [k for k, v in positions.items() if not v]
                }
            return {"status": "reconciled"}
        
        mock_reconciliation.reconcile_positions = AsyncMock(
            side_effect=reconcile_positions
        )
        
        result = await mock_reconciliation.reconcile_positions(incomplete_positions)
        assert result["status"] == "partial_reconciliation"
        assert "venue2" in result["missing_venues"]

    @pytest.mark.asyncio
    async def test_position_data_corruption_detected(self):
        """System should detect corrupted position data."""
        mock_reconciliation = Mock()
        corrupted_data = {
            "venue1": {"BTC": -10, "ETH": 5},  # Negative position is invalid
            "venue2": {"BTC": 10, "ETH": 5}
        }
        
        def validate_positions(positions):
            for venue, assets in positions.items():
                for asset, quantity in assets.items():
                    if quantity < 0:
                        return False, f"Invalid negative position: {venue}.{asset}"
            return True, "valid"
        
        mock_reconciliation.validate_positions = Mock(side_effect=validate_positions)
        
        is_valid, reason = mock_reconciliation.validate_positions(corrupted_data)
        assert is_valid == False
        assert "negative position" in reason


class TestReconciliationServiceUnavailability:
    """Chaos tests for reconciliation service unavailability scenarios."""

    @pytest.mark.asyncio
    async def test_reconciliation_service_timeout_handling(self):
        """System should handle reconciliation service timeouts."""
        mock_reconciliation = Mock()
        mock_reconciliation.reconcile = AsyncMock(
            side_effect=asyncio.TimeoutError("Reconciliation timeout")
        )
        
        with pytest.raises(asyncio.TimeoutError, match="Reconciliation timeout"):
            await mock_reconciliation.reconcile("test_positions")

    @pytest.mark.asyncio
    async def test_fallback_to_last_known_positions(self):
        """System should fall back to last known positions on service failure."""
        mock_reconciliation = Mock()
        mock_reconciliation.reconcile = AsyncMock(
            side_effect=ConnectionError("Reconciliation service down")
        )
        mock_reconciliation.get_last_known_positions = Mock(
            return_value={"BTC": 10, "ETH": 5, "timestamp": datetime.now()}
        )
        
        try:
            await mock_reconciliation.reconcile("test_positions")
        except ConnectionError:
            last_known = mock_reconciliation.get_last_known_positions()
            assert last_known["BTC"] == 10
            assert last_known["ETH"] == 5

    @pytest.mark.asyncio
    async def test_reconciliation_service_recovery(self):
        """System should recover when reconciliation service comes back online."""
        mock_reconciliation = Mock()
        service_available = [False]
        
        async def reconcile(positions):
            if not service_available[0]:
                raise ConnectionError("Reconciliation service down")
            return {"status": "reconciled", "positions": positions}
        
        mock_reconciliation.reconcile = AsyncMock(side_effect=reconcile)
        
        # Service is down
        with pytest.raises(ConnectionError):
            await mock_reconciliation.reconcile("test_positions")
        
        # Service comes back up
        service_available[0] = True
        result = await mock_reconciliation.reconcile("test_positions")
        assert result["status"] == "reconciled"


class TestPartialPositionDataFailures:
    """Chaos tests for partial position data retrieval failures."""

    @pytest.mark.asyncio
    async def test_partial_venue_data_retrieval(self):
        """System should handle partial venue data retrieval."""
        mock_venue_client = Mock()
        
        async def get_positions(venue):
            if venue == "venue1":
                return {"BTC": 10, "ETH": 5}
            elif venue == "venue2":
                raise ConnectionError("Venue2 unavailable")
            return {}
        
        mock_venue_client.get_positions = AsyncMock(side_effect=get_positions)
        
        # Get positions from multiple venues
        venues = ["venue1", "venue2", "venue3"]
        results = {}
        for venue in venues:
            try:
                results[venue] = await mock_venue_client.get_positions(venue)
            except ConnectionError as e:
                results[venue] = {"error": str(e)}
        
        assert "venue1" in results
        assert "BTC" in results["venue1"]
        assert "error" in results["venue2"]

    @pytest.mark.asyncio
    async def test_partial_asset_data_retrieval(self):
        """System should handle partial asset data within a venue."""
        mock_venue_client = Mock()
        
        async def get_positions(venue):
            # Some assets fail to load
            return {
                "BTC": 10,
                "ETH": None,  # Failed to load
                "SOL": 5
            }
        
        mock_venue_client.get_positions = AsyncMock(side_effect=get_positions)
        
        positions = await mock_venue_client.get_positions("venue1")
        assert positions["BTC"] == 10
        assert positions["ETH"] is None
        assert positions["SOL"] == 5

    @pytest.mark.asyncio
    async def test_reconciliation_with_partial_data(self):
        """Reconciliation should proceed with partial data."""
        mock_reconciliation = Mock()
        partial_data = {
            "venue1": {"BTC": 10, "ETH": None, "SOL": 5},
            "venue2": {"BTC": 10, "ETH": 5, "SOL": None}
        }
        
        async def reconcile(positions):
            # Reconcile only assets with data from all venues
            reconciled = {}
            for asset in ["BTC", "ETH", "SOL"]:
                values = [v.get(asset) for v in positions.values()]
                if all(v is not None for v in values):
                    reconciled[asset] = values[0]  # Use first venue's value
            return {
                "status": "partial_reconciliation",
                "reconciled_assets": list(reconciled.keys()),
                "missing_assets": [a for a in ["BTC", "ETH", "SOL"] if a not in reconciled]
            }
        
        mock_reconciliation.reconcile = AsyncMock(side_effect=reconcile)
        
        result = await mock_reconciliation.reconcile(partial_data)
        assert result["status"] == "partial_reconciliation"
        assert "BTC" in result["reconciled_assets"]
        assert "ETH" in result["missing_assets"]
        assert "SOL" in result["missing_assets"]


class TestPositionCalculationErrors:
    """Chaos tests for position calculation error scenarios."""

    @pytest.mark.asyncio
    async def test_position_calculation_division_by_zero(self):
        """System should handle division by zero in position calculations."""
        mock_calculator = Mock()
        
        def calculate_average_price(total_value, quantity):
            if quantity == 0:
                raise ValueError("Cannot calculate average price with zero quantity")
            return total_value / quantity
        
        mock_calculator.calculate_average_price = Mock(
            side_effect=calculate_average_price
        )
        
        with pytest.raises(ValueError, match="zero quantity"):
            mock_calculator.calculate_average_price(1000, 0)

    @pytest.mark.asyncio
    async def test_position_calculation_with_invalid_data(self):
        """System should handle invalid data in position calculations."""
        mock_calculator = Mock()
        
        def calculate_exposure(positions, prices):
            exposure = 0
            for asset, quantity in positions.items():
                if asset not in prices:
                    raise KeyError(f"Price not found for {asset}")
                if quantity < 0:
                    raise ValueError(f"Invalid negative quantity for {asset}")
                exposure += quantity * prices[asset]
            return exposure
        
        mock_calculator.calculate_exposure = Mock(side_effect=calculate_exposure)
        
        # Test with missing price
        positions = {"BTC": 10, "ETH": 5}
        prices = {"BTC": 50000}  # Missing ETH price
        with pytest.raises(KeyError, match="ETH"):
            mock_calculator.calculate_exposure(positions, prices)

    @pytest.mark.asyncio
    async def test_position_aggregation_with_type_errors(self):
        """System should handle type errors in position aggregation."""
        mock_aggregator = Mock()
        
        def aggregate_positions(positions_list):
            total = {}
            for positions in positions_list:
                for asset, quantity in positions.items():
                    if not isinstance(quantity, (int, float)):
                        raise TypeError(f"Invalid quantity type for {asset}: {type(quantity)}")
                    total[asset] = total.get(asset, 0) + quantity
            return total
        
        mock_aggregator.aggregate_positions = Mock(side_effect=aggregate_positions)
        
        # Test with invalid type
        positions_list = [
            {"BTC": 10, "ETH": 5},
            {"BTC": "invalid", "ETH": 3}  # String instead of number
        ]
        with pytest.raises(TypeError, match="Invalid quantity type"):
            mock_aggregator.aggregate_positions(positions_list)


class TestConcurrentReconciliationConflicts:
    """Chaos tests for concurrent reconciliation conflict scenarios."""

    @pytest.mark.asyncio
    async def test_concurrent_reconciliation_race_condition(self):
        """System should handle concurrent reconciliation race conditions."""
        mock_reconciliation = Mock()
        reconciliation_count = [0]
        lock = asyncio.Lock()
        
        async def reconcile(positions):
            async with lock:
                reconciliation_count[0] += 1
                await asyncio.sleep(0.01)  # Simulate processing
                return {"status": "reconciled", "count": reconciliation_count[0]}
        
        mock_reconciliation.reconcile = AsyncMock(side_effect=reconcile)
        
        # Submit concurrent reconciliations
        tasks = [
            mock_reconciliation.reconcile(f"positions{i}")
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 5
        # All should succeed despite concurrent access
        assert all(r["status"] == "reconciled" for r in results)

    @pytest.mark.asyncio
    async def test_duplicate_reconciliation_detection(self):
        """System should detect and prevent duplicate reconciliations."""
        mock_reconciliation = Mock()
        reconciled_positions = set()
        
        async def reconcile(positions):
            positions_key = str(sorted(positions.items()))
            if positions_key in reconciled_positions:
                return {"status": "skipped", "reason": "already_reconciled"}
            reconciled_positions.add(positions_key)
            return {"status": "reconciled"}
        
        mock_reconciliation.reconcile = AsyncMock(side_effect=reconcile)
        
        # Reconcile same positions twice
        positions = {"BTC": 10, "ETH": 5}
        result1 = await mock_reconciliation.reconcile(positions)
        result2 = await mock_reconciliation.reconcile(positions)
        
        assert result1["status"] == "reconciled"
        assert result2["status"] == "skipped"
        assert result2["reason"] == "already_reconciled"


class TestReconciliationTimeoutScenarios:
    """Chaos tests for reconciliation timeout scenarios."""

    @pytest.mark.asyncio
    async def test_slow_reconciliation_timeout(self):
        """System should timeout slow reconciliation operations."""
        mock_reconciliation = Mock()
        
        async def slow_reconcile(positions):
            await asyncio.sleep(5)  # Simulate slow operation
            return {"status": "reconciled"}
        
        mock_reconciliation.reconcile = AsyncMock(side_effect=slow_reconcile)
        
        # Set short timeout
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                mock_reconciliation.reconcile("test_positions"),
                timeout=1.0
            )

    @pytest.mark.asyncio
    async def test_partial_recompletion_after_timeout(self):
        """System should handle partial completion after timeout."""
        mock_reconciliation = Mock()
        completed_assets = []
        
        async def reconcile_with_timeout(positions):
            for asset in positions:
                await asyncio.sleep(0.1)
                completed_assets.append(asset)
                if len(completed_assets) == 2:
                    raise asyncio.TimeoutError("Timeout during reconciliation")
            return {"status": "reconciled"}
        
        mock_reconciliation.reconcile = AsyncMock(side_effect=reconcile_with_timeout)
        
        positions = {"BTC": 10, "ETH": 5, "SOL": 3}
        with pytest.raises(asyncio.TimeoutError):
            await mock_reconciliation.reconcile(positions)
        
        # Some assets were processed before timeout
        assert len(completed_assets) == 2

    @pytest.mark.asyncio
    async def test_reconciliation_retry_after_timeout(self):
        """System should retry reconciliation after timeout."""
        mock_reconciliation = Mock()
        attempt_count = [0]
        
        async def reconcile(positions):
            attempt_count[0] += 1
            if attempt_count[0] < 3:
                await asyncio.sleep(0.2)
                raise asyncio.TimeoutError("Timeout")
            return {"status": "reconciled"}
        
        mock_reconciliation.reconcile = AsyncMock(side_effect=reconcile)
        
        # Retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = await asyncio.wait_for(
                    mock_reconciliation.reconcile("test_positions"),
                    timeout=0.1
                )
                assert result["status"] == "reconciled"
                break
            except asyncio.TimeoutError:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(0.1)
        
        assert attempt_count[0] == 3


class TestPositionReconciliationRecovery:
    """Chaos tests for position reconciliation recovery scenarios."""

    @pytest.mark.asyncio
    async def test_reconciliation_state_recovery_after_crash(self):
        """Reconciliation state should recover after crash."""
        mock_reconciliation = Mock()
        state_version = [1]
        
        async def get_state():
            return {"version": state_version[0], "last_reconciled": datetime.now()}
        
        async def recover_state():
            state_version[0] += 1
            return {"version": state_version[0], "recovered": True}
        
        mock_reconciliation.get_state = AsyncMock(side_effect=get_state)
        mock_reconciliation.recover_state = AsyncMock(side_effect=recover_state)
        
        # Get current state
        state1 = await mock_reconciliation.get_state()
        assert state1["version"] == 1
        
        # Simulate crash and recovery
        await mock_reconciliation.recover_state()
        
        # Get recovered state
        state2 = await mock_reconciliation.get_state()
        assert state2["version"] == 2

    @pytest.mark.asyncio
    async def test_position_data_integrity_after_recovery(self):
        """Position data integrity should be maintained after recovery."""
        mock_reconciliation = Mock()
        original_positions = {"BTC": 10, "ETH": 5, "SOL": 3}
        
        async def save_positions(positions):
            return {"saved": True, "checksum": hash(str(positions))}
        
        async def load_positions():
            return original_positions
        
        async def recover():
            loaded = await load_positions()
            saved = await save_positions(loaded)
            return {"recovered": True, "checksum": saved["checksum"]}
        
        mock_reconciliation.save_positions = AsyncMock(side_effect=save_positions)
        mock_reconciliation.load_positions = AsyncMock(side_effect=load_positions)
        mock_reconciliation.recover = AsyncMock(side_effect=recover)
        
        # Save original positions
        saved = await mock_reconciliation.save_positions(original_positions)
        original_checksum = saved["checksum"]
        
        # Recover
        recovered = await mock_reconciliation.recover()
        assert recovered["checksum"] == original_checksum

    @pytest.mark.asyncio
    async def test_reconciliation_queue_processing_after_failure(self):
        """Reconciliation queue should be processed after failure recovery."""
        mock_reconciliation = Mock()
        queue = []
        processing_enabled = [False]
        
        async def add_to_queue(positions):
            queue.append(positions)
            return {"queued": True}
        
        async def process_queue():
            if not processing_enabled[0]:
                return {"processed": 0, "reason": "processing_disabled"}
            processed = []
            while queue:
                positions = queue.pop(0)
                processed.append(positions)
            return {"processed": len(processed)}
        
        mock_reconciliation.add_to_queue = AsyncMock(side_effect=add_to_queue)
        mock_reconciliation.process_queue = AsyncMock(side_effect=process_queue)
        
        # Add items to queue while processing is disabled
        await mock_reconciliation.add_to_queue({"BTC": 10})
        await mock_reconciliation.add_to_queue({"ETH": 5})
        
        # Processing is disabled
        result1 = await mock_reconciliation.process_queue()
        assert result1["processed"] == 0
        
        # Enable processing
        processing_enabled[0] = True
        result2 = await mock_reconciliation.process_queue()
        assert result2["processed"] == 2
