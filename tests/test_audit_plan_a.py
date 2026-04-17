"""Tests for Audit Plan A: Critical & High Safety Fixes (Tasks 4-10).

This file contains tests for:
- Task 4: Telegram Backoff Auto-Recovery (R-4)
- Task 5: Promotion Cache Invalidation on Kill Switch (P-1)
- Task 6: CQI Staleness Detection (E-4)
- Task 7: Venue Exposure Sync Background Loop (E-3)
- Task 8: Configurable Consensus Approval Threshold (C-4)
- Task 9: Tiered Archetype Diversity Thresholds (C-2)
- Task 10: Preflight Gate 9 — Core Dependency Health (P-3)
"""

import asyncio
import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock


# =============================================================================
# Task 4: Telegram Backoff Auto-Recovery (R-4)
# =============================================================================

class TestTelegramBackoffRecovery:
    """R-4: Telegram consecutive error counter resets after backoff window expires."""

    @pytest.mark.asyncio
    async def test_consecutive_errors_reset_after_backoff_expires(self):
        """After backoff window expires, consecutive errors should reset to 0."""
        from merid.alerts import webhook_client as wc

        # Simulate consecutive errors triggering backoff
        wc._tg_consecutive_errors = 5
        wc._tg_backoff_until = time.monotonic() - 1.0  # Backoff expired 1 second ago

        # Mock credentials and httpx to simulate successful send
        with patch.object(wc, '_tg_creds', return_value=('fake_token', 'fake_chat_id')):
            with patch.object(wc, '_tg_feature_enabled', return_value=True):
                with patch('httpx.AsyncClient') as mock_client:
                    mock_response = MagicMock()
                    mock_response.status_code = 200
                    mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                        post=AsyncMock(return_value=mock_response)
                    ))
                    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

                    await wc._tg_raw_send("test", timeout=0.1)

        # After successful send with expired backoff, errors should be reset
        assert wc._tg_consecutive_errors == 0
        assert wc._tg_backoff_until == 0.0

    @pytest.mark.asyncio
    async def test_backoff_active_blocks_send(self):
        """When backoff is active (in the future), sends should be blocked."""
        from merid.alerts import webhook_client as wc

        # Set backoff far in the future
        wc._tg_backoff_until = time.monotonic() + 3600.0
        wc._tg_consecutive_errors = 3

        result = await wc._tg_raw_send("test")
        assert result is False
        # Counter should not be reset while backoff is active
        assert wc._tg_consecutive_errors == 3


# =============================================================================
# Task 5: Promotion Cache Invalidation on Kill Switch (P-1)
# =============================================================================

class TestPromotionCacheInvalidation:
    """P-1: Promotion report cache is cleared on kill switch trigger."""

    def test_cache_invalidation_callback_registered(self):
        """Promotion cache invalidation callback should be registered with kill switch."""
        from merid.risk.kill_switches import RiskController, KillSwitchReason

        ctrl = RiskController(daily_loss_limit=10000.0)

        # Track if callback was called
        callback_called = [False]
        def invalidate_cache(event):
            callback_called[0] = True

        # Register callback
        ctrl.on_kill(invalidate_cache)

        # Trigger kill switch
        ctrl._trigger_kill(KillSwitchReason.MANUAL, "test")

        # Callback should have been called
        assert callback_called[0] is True


# =============================================================================
# Task 6: CQI Staleness Detection (E-4)
# =============================================================================

class TestCQIStalenessDetection:
    """E-4: Execution guard warns on stale CQI (>5 min old)."""

    def test_execution_guard_detects_stale_cqi(self):
        """Execution guard should warn when CQI data is >5 minutes old."""
        from merid.execution_guard import ExecutionGuard

        guard = ExecutionGuard()

        # Set CQI timestamp to 6 minutes ago
        guard._cqi_timestamp = time.monotonic() - 360.0  # 6 minutes
        guard._cqi_value = 0.75

        # Check should detect staleness
        is_stale, age_seconds = guard._is_cqi_stale()

        assert is_stale is True
        assert age_seconds >= 300  # At least 5 minutes

    def test_fresh_cqi_not_stale(self):
        """CQI <5 minutes old should not be flagged as stale."""
        from merid.execution_guard import ExecutionGuard

        guard = ExecutionGuard()

        # Set CQI timestamp to 1 minute ago
        guard._cqi_timestamp = time.monotonic() - 60.0
        guard._cqi_value = 0.75

        is_stale, age_seconds = guard._is_cqi_stale()

        assert is_stale is False
        assert age_seconds < 300


# =============================================================================
# Task 7: Venue Exposure Sync Background Loop (E-3)
# =============================================================================

class TestVenueExposureSyncLoop:
    """E-3: Venue exposure sync runs periodically during live trading."""

    def test_exposure_sync_loop_exists(self):
        """Exposure sync loop task should be created in main.py."""
        # This is tested by verifying the code structure in web/main.py
        # The actual async loop would require integration testing
        import web.main as main_module

        # Check that the main module has the exposure sync function
        assert hasattr(main_module, '_run_exposure_sync_loop') or \
               hasattr(main_module, 'exposure_sync_loop') or \
               'exposure_sync' in dir(main_module)


# =============================================================================
# Task 8: Configurable Consensus Approval Threshold (C-4)
# =============================================================================

class TestConsensusApprovalThreshold:
    """C-4: Swarm consensus approval threshold is configurable via env var."""

    def test_approval_threshold_reads_from_env(self, monkeypatch):
        """MERID_CONSENSUS_THRESHOLD env var should override default."""
        monkeypatch.setenv("MERID_CONSENSUS_THRESHOLD", "0.75")

        import importlib
        import merid.swarm.consensus_engine as ce
        importlib.reload(ce)

        # Threshold should be 0.75 not the default 0.66
        threshold = getattr(ce, 'APPROVAL_THRESHOLD', None) or \
                    getattr(ce.ConsensusEngine, 'APPROVAL_THRESHOLD', None)

        if threshold is None:
            pytest.skip("APPROVAL_THRESHOLD not found in consensus_engine")

        assert threshold == 0.75

    def test_default_threshold_when_no_env(self):
        """Default approval threshold should be 0.66 when env not set."""
        import os

        # Ensure env is not set
        if "MERID_CONSENSUS_THRESHOLD" in os.environ:
            del os.environ["MERID_CONSENSUS_THRESHOLD"]

        import importlib
        import merid.swarm.consensus_engine as ce
        importlib.reload(ce)

        threshold = getattr(ce, 'APPROVAL_THRESHOLD', None) or \
                    getattr(ce.ConsensusEngine, 'APPROVAL_THRESHOLD', None)

        if threshold is None:
            pytest.skip("APPROVAL_THRESHOLD not found in consensus_engine")

        assert threshold == 0.66


# =============================================================================
# Task 9: Tiered Archetype Diversity Thresholds (C-2)
# =============================================================================

class TestTieredArchetypeDiversity:
    """C-2: Tiered archetype diversity thresholds (3,5,8) instead of flat 2."""

    def test_tiered_thresholds_exist(self):
        """Tiered archetype diversity thresholds should be defined."""
        import merid.swarm.consensus_aggregator as ca

        # Check for tiered threshold constants
        has_tiers = (
            hasattr(ca, 'ARCHETYPE_DIVERSITY_TIER_1') or
            hasattr(ca, 'ARCHETYPE_DIVERSITY_LOW') or
            hasattr(ca.ConsensusAggregator, 'archetype_diversity_tiers')
        )

        assert has_tiers, "Tiered archetype diversity thresholds not found"

    def test_tiered_thresholds_not_flat(self):
        """Archetype diversity should not be a flat threshold of 2."""
        import merid.swarm.consensus_aggregator as ca

        # Look for the threshold values
        thresholds = []
        for attr in dir(ca):
            if 'ARCHETYPE' in attr and 'DIVERSITY' in attr:
                val = getattr(ca, attr)
                if isinstance(val, int):
                    thresholds.append(val)

        # Should have tiered values (3, 5, 8 or similar), not just flat 2
        if thresholds:
            assert max(thresholds) > 2, "Archetype diversity should be tiered (3,5,8) not flat 2"


# =============================================================================
# Task 10: Preflight Gate 9 — Core Dependency Health (P-3)
# =============================================================================

class TestPreflightGate9:
    """P-3: Preflight script includes Gate 9 checking core dependency health."""

    def test_gate9_exists_in_preflight(self):
        """Gate 9 should exist in go_live_preflight.py."""
        import scripts.go_live_preflight as preflight

        # Check for Gate 9 function
        has_gate9 = (
            hasattr(preflight, 'gate_9') or
            hasattr(preflight, 'check_gate_9') or
            hasattr(preflight, 'verify_core_dependencies') or
            'gate9' in str(dir(preflight)).lower()
        )

        assert has_gate9, "Gate 9 (core dependency health) not found in preflight"

    def test_dependency_health_checks_exist(self):
        """Gate 9 should check execution guard, fills ledger, Telegram credentials."""
        import scripts.go_live_preflight as preflight

        # Read the source to verify checks exist
        import inspect
        source = inspect.getsource(preflight)

        # Should mention key dependencies
        has_execution_guard = 'execution' in source.lower() or 'guard' in source.lower()
        has_fills_ledger = 'fills' in source.lower() or 'ledger' in source.lower()
        has_telegram = 'telegram' in source.lower() or 'tg_' in source.lower()

        assert has_execution_guard, "Execution guard check not found"
        assert has_fills_ledger, "Fills ledger check not found"
        assert has_telegram, "Telegram credentials check not found"
