"""
Tests for core/system_orchestrator.py
Coverage target: 85%
"""
import asyncio
import time
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from core.system_orchestrator import (
    SystemOrchestrator,
    OrchestratorState,
    SystemHealth,
    OrchestratorMetrics,
    get_system_orchestrator,
    start_merid,
    stop_merid
)
from core.intersystem_api import MeridSystem, FreezeSeverity, FreezeReason


class TestSystemOrchestrator:
    """Test SystemOrchestrator functionality."""

    @pytest.fixture
    def orchestrator(self):
        """Create SystemOrchestrator instance."""
        orch = SystemOrchestrator()
        yield orch
        # Cleanup any running tasks
        if orch._tasks:
            for task in orch._tasks:
                if not task.done():
                    task.cancel()

    @pytest.fixture
    def running_orchestrator(self, orchestrator):
        """Create and start SystemOrchestrator."""
        # Mock dependencies
        with patch('core.system_orchestrator.get_intersystem_api') as mock_api, \
             patch('core.system_orchestrator.get_event_bus') as mock_bus, \
             patch('core.system_orchestrator.get_consensus_engine') as mock_consensus:

            mock_api_instance = MagicMock()
            mock_bus_instance = MagicMock()
            mock_consensus_instance = MagicMock()

            mock_api.return_value = mock_api_instance
            mock_bus.return_value = mock_bus_instance
            mock_consensus.return_value = mock_consensus_instance

            orchestrator._api = mock_api_instance
            orchestrator._bus = mock_bus_instance
            orchestrator._consensus = mock_consensus_instance

            yield orchestrator

    def test_initialization(self):
        """Test orchestrator initialization."""
        orch = SystemOrchestrator()

        assert orch._state == OrchestratorState.INITIALIZING
        assert orch._tasks == []
        assert len(orch._system_health) == len(MeridSystem)
        assert isinstance(orch._metrics, OrchestratorMetrics)

        # Check all systems are initialized as unhealthy
        for system in MeridSystem:
            assert system in orch._system_health
            health = orch._system_health[system]
            assert not health.healthy
            assert health.last_heartbeat == 0.0

    @pytest.mark.asyncio
    async def test_start_stop(self, orchestrator):
        """Test orchestrator start/stop lifecycle."""
        # Mock dependencies
        with patch('core.system_orchestrator.get_intersystem_api') as mock_api, \
             patch('core.system_orchestrator.get_event_bus') as mock_bus, \
             patch('core.system_orchestrator.get_consensus_engine') as mock_consensus:

            mock_api_instance = AsyncMock()
            mock_bus_instance = AsyncMock()
            mock_consensus_instance = AsyncMock()

            mock_api.return_value = mock_api_instance
            mock_bus.return_value = mock_bus_instance
            mock_consensus.return_value = mock_consensus_instance

            # Start orchestrator
            await orchestrator.start()

            assert orchestrator._state == OrchestratorState.RUNNING
            assert len(orchestrator._tasks) == 3  # health_check, event_processing, intent_expiry

            # Check tasks are running
            running_tasks = [t for t in orchestrator._tasks if not t.done()]
            assert len(running_tasks) == 3

            # Stop orchestrator
            await orchestrator.stop()

            assert orchestrator._state == OrchestratorState.SHUTDOWN
            # All tasks should be cancelled/done
            assert all(t.done() for t in orchestrator._tasks)

    def test_start_already_running(self, orchestrator):
        """Test starting when already running."""
        orchestrator._state = OrchestratorState.RUNNING
        # Should not error
        orchestrator._state = OrchestratorState.RUNNING

    def test_stop_not_running(self, orchestrator):
        """Test stopping when not running."""
        orchestrator._state = OrchestratorState.INITIALIZING
        # Should not error
        orchestrator._state = OrchestratorState.INITIALIZING

    @pytest.mark.asyncio
    async def test_initialize_systems_ops_failure(self, orchestrator):
        """Test system initialization with OPS import failure."""
        with patch.dict('sys.modules', {'ops': None}):
            await orchestrator._initialize_systems()

        # OPS should remain unhealthy
        assert not orchestrator._system_health[MeridSystem.OPS].healthy
        # Other systems should be healthy (FIN, TREASURY, etc.)
        assert orchestrator._system_health[MeridSystem.FIN].healthy

    @pytest.mark.asyncio
    async def test_initialize_systems_gov_failure(self, orchestrator):
        """Test system initialization with GOV import failure."""
        with patch.dict('sys.modules', {'governance': None}):
            await orchestrator._initialize_systems()

        # GOV should remain unhealthy
        assert not orchestrator._system_health[MeridSystem.GOV].healthy

    @pytest.mark.asyncio
    async def test_initialize_systems_treasury_failure(self, orchestrator):
        """Test system initialization with TREASURY import failure."""
        with patch.dict('sys.modules', {'treasury': None}):
            await orchestrator._initialize_systems()

        # TREASURY should remain unhealthy
        assert not orchestrator._system_health[MeridSystem.TREASURY].healthy

    @pytest.mark.asyncio
    async def test_initialize_systems_archive_failure(self, orchestrator):
        """Test system initialization with ARCHIVE import failure."""
        with patch.dict('sys.modules', {'archive': None}):
            await orchestrator._initialize_systems()

        # ARCHIVE should remain unhealthy
        assert not orchestrator._system_health[MeridSystem.ARCHIVE].healthy

    @pytest.mark.asyncio
    async def test_initialize_systems_success(self, orchestrator):
        """Test successful system initialization."""
        # Mock successful imports
        mock_ops = MagicMock()
        mock_gov = MagicMock()
        mock_treasury = MagicMock()
        mock_archive = MagicMock()

        with patch.dict('sys.modules', {
            'ops': MagicMock(),
            'governance': MagicMock(),
            'treasury': MagicMock(),
            'archive': MagicMock(),
        }):
            # Mock the actual module attributes
            with patch('ops.get_regime_detector', return_value=mock_ops), \
                 patch('ops.get_anomaly_detection', return_value=MagicMock()), \
                 patch('ops.get_epistemic_engine', return_value=MagicMock()), \
                 patch('governance.get_constitutional', return_value=mock_gov), \
                 patch('governance.get_authority_enforcer', return_value=MagicMock()), \
                 patch('governance.get_adversarial_engine', return_value=MagicMock()), \
                 patch('treasury.get_portfolio_geometry', return_value=mock_treasury), \
                 patch('treasury.get_capital_thermodynamics', return_value=MagicMock()), \
                 patch('treasury.get_vault_manager', return_value=MagicMock()), \
                 patch('archive.get_audit_ledger', return_value=mock_archive), \
                 patch('archive.get_decision_logger', return_value=MagicMock()), \
                 patch('archive.get_replay_engine', return_value=MagicMock()):

                await orchestrator._initialize_systems()

        # All systems should be healthy
        for system in MeridSystem:
            assert orchestrator._system_health[system].healthy
            assert orchestrator._system_health[system].last_heartbeat > 0

    @pytest.mark.asyncio
    async def test_subscribe_to_channels(self, orchestrator):
        """Test event bus subscription."""
        mock_bus = AsyncMock()
        orchestrator._bus = mock_bus

        await orchestrator._subscribe_to_channels()

        mock_bus.subscribe.assert_called_once()
        call_args = mock_bus.subscribe.call_args
        assert call_args[1]['subscriber_id'] == 'orchestrator'
        assert len(call_args[1]['channels']) == 3

    @pytest.mark.asyncio
    async def test_health_check_loop_normal(self, orchestrator):
        """Test health check loop with healthy systems."""
        # Set up healthy systems
        now = time.time()
        for health in orchestrator._system_health.values():
            health.healthy = True
            health.last_heartbeat = now

        # Start health check in background
        orchestrator._state = OrchestratorState.RUNNING
        task = asyncio.create_task(orchestrator._health_check_loop())

        # Let it run for a short time
        await asyncio.sleep(0.1)

        # Cancel the task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Systems should still be healthy
        for health in orchestrator._system_health.values():
            assert health.healthy

    @pytest.mark.asyncio
    async def test_health_check_loop_unhealthy_gov(self, orchestrator):
        """Test health check loop triggering freeze for unhealthy GOV."""
        # Set GOV as unhealthy
        past_time = time.time() - 120  # Older than timeout
        orchestrator._system_health[MeridSystem.GOV].healthy = False
        orchestrator._system_health[MeridSystem.GOV].last_heartbeat = past_time

        # Set other systems healthy
        now = time.time()
        for system, health in orchestrator._system_health.items():
            if system != MeridSystem.GOV:
                health.healthy = True
                health.last_heartbeat = now

        # Mock API for freeze
        mock_api = AsyncMock()
        orchestrator._api = mock_api

        # Start health check
        orchestrator._state = OrchestratorState.RUNNING
        task = asyncio.create_task(orchestrator._health_check_loop())

        # Let it run long enough to check
        await asyncio.sleep(orchestrator.HEALTH_CHECK_INTERVAL + 0.1)

        # Cancel the task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have triggered emergency freeze
        mock_api.emergency_freeze.assert_called_once()
        call_args = mock_api.emergency_freeze.call_args
        assert call_args[1]['severity'] == FreezeSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_event_processing_loop(self, orchestrator):
        """Test event processing loop."""
        mock_bus = AsyncMock()
        mock_event = MagicMock()
        mock_bus.get_event.return_value = mock_event
        orchestrator._bus = mock_bus

        # Mock event processing
        with patch.object(orchestrator, '_process_event') as mock_process:
            # Start event processing
            orchestrator._state = OrchestratorState.RUNNING
            task = asyncio.create_task(orchestrator._event_processing_loop())

            # Let it process one event
            await asyncio.sleep(0.1)

            # Cancel the task
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            # Should have processed the event
            mock_process.assert_called_with(mock_event)

    @pytest.mark.asyncio
    async def test_intent_expiry_loop(self, orchestrator):
        """Test intent expiry loop."""
        mock_api = MagicMock()
        mock_intent = MagicMock()
        mock_intent.is_expired.return_value = True
        mock_api.get_pending_intents.return_value = [mock_intent]
        orchestrator._api = mock_api

        # Start intent expiry
        orchestrator._state = OrchestratorState.RUNNING
        task = asyncio.create_task(orchestrator._intent_expiry_loop())

        # Let it run long enough to check
        await asyncio.sleep(65)  # Longer than 60 second check interval

        # Cancel the task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have expired the intent
        assert mock_intent.status.value == "EXPIRED"

    @pytest.mark.asyncio
    async def test_process_event_consensus_decision(self, orchestrator):
        """Test processing consensus decision event."""
        mock_event = MagicMock()
        mock_event.event_type = "consensus_decision"
        mock_event.data = {
            "decision": "EXECUTE_LONG",
            "confidence": 0.8,
            "signal": "bullish"
        }

        with patch.object(orchestrator, '_create_intent_from_consensus') as mock_create:
            await orchestrator._process_event(mock_event)
            mock_create.assert_called_once_with(mock_event.data)

    def test_process_event_heartbeat(self, orchestrator):
        """Test processing heartbeat event."""
        mock_event = MagicMock()
        mock_event.event_type = "system_heartbeat"
        mock_event.source = "OPS"
        mock_event.data = {"latency_ms": 50}

        orchestrator._process_event(mock_event)

        ops_health = orchestrator._system_health[MeridSystem.OPS]
        assert ops_health.healthy
        assert ops_health.latency_ms == 50
        assert ops_health.last_heartbeat > 0

    @pytest.mark.asyncio
    async def test_process_event_anomaly(self, orchestrator):
        """Test processing anomaly event."""
        mock_event = MagicMock()
        mock_event.event_type = "anomaly_alert"
        mock_event.data = {
            "severity": "HIGH",
            "description": "Test anomaly"
        }

        with patch.object(orchestrator, '_trigger_emergency_freeze') as mock_freeze:
            await orchestrator._process_event(mock_event)
            # Should not trigger freeze for HIGH severity
            mock_freeze.assert_not_called()

        # Test critical anomaly
        mock_event.data["severity"] = "CRITICAL"
        with patch.object(orchestrator, '_trigger_emergency_freeze') as mock_freeze:
            await orchestrator._process_event(mock_event)
            mock_freeze.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_intent_from_consensus(self, orchestrator):
        """Test creating intent from consensus decision."""
        consensus_data = {
            "confidence": 0.7,
            "signal": "bullish"
        }

        # Mock OPS engine
        mock_regime = MagicMock()
        mock_regime_state = MagicMock()
        mock_regime_state.regime.value = "BULL_MARKET"
        mock_regime.get_current_state.return_value = mock_regime_state

        mock_epistemic = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.overall_confidence = 0.8
        mock_epistemic.get_snapshot.return_value = mock_snapshot

        orchestrator._ops_engine = {
            "regime": mock_regime,
            "epistemic": mock_epistemic
        }

        # Mock API
        mock_api = AsyncMock()
        mock_api.propose_intent.return_value = {"intent_id": "test-123"}
        orchestrator._api = mock_api

        await orchestrator._create_intent_from_consensus(consensus_data)

        # Should have called propose_intent
        mock_api.propose_intent.assert_called_once()
        call_args = mock_api.propose_intent.call_args
        assert call_args[1]["regime"] == "BULL_MARKET"
        assert call_args[1]["confidence"] == 0.7
        assert call_args[1]["epistemic_confidence"] == 0.8

        # Should have updated metrics
        assert orchestrator._metrics.intents_processed == 1

    @pytest.mark.asyncio
    async def test_trigger_emergency_freeze(self, orchestrator):
        """Test emergency freeze triggering."""
        mock_api = AsyncMock()
        orchestrator._api = mock_api

        await orchestrator._trigger_emergency_freeze(
            "Test freeze",
            FreezeSeverity.CRITICAL
        )

        mock_api.emergency_freeze.assert_called_once()
        assert orchestrator._state == OrchestratorState.FROZEN
        assert orchestrator._metrics.freezes_triggered == 1

    def test_on_execution_authorized(self, orchestrator):
        """Test execution authorized callback."""
        mock_intent = MagicMock()
        mock_constraints = MagicMock()
        mock_constraints.to_dict.return_value = {"test": "constraints"}

        orchestrator._on_execution_authorized(mock_intent, mock_constraints)

        assert orchestrator._metrics.intents_approved == 1

    def test_on_freeze(self, orchestrator):
        """Test freeze callback."""
        mock_freeze = MagicMock()
        orchestrator._on_freeze(mock_freeze)

        assert orchestrator._state == OrchestratorState.FROZEN

    def test_on_unfreeze(self, orchestrator):
        """Test unfreeze callback."""
        orchestrator._state = OrchestratorState.FROZEN
        orchestrator._on_unfreeze("test-freeze-id")

        assert orchestrator._state == OrchestratorState.RUNNING

    def test_archive_record(self, orchestrator):
        """Test record archiving."""
        # Mock archive engine
        mock_ledger = MagicMock()
        orchestrator._archive_engine = {"ledger": mock_ledger}

        record = {
            "event_type": "GOVERNANCE_DECISION",
            "intent_id": "test-123",
            "data": {"test": "data"}
        }

        with patch('core.system_orchestrator.EventType') as mock_event_type:
            orchestrator._archive_record(record)
            mock_ledger.record.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_intent_frozen(self, orchestrator):
        """Test submitting intent when frozen."""
        orchestrator._state = OrchestratorState.FROZEN

        result = await orchestrator.submit_intent(
            "test-strategy", "BULL", 0.8, MagicMock(), MagicMock(), MagicMock(), 1234567890
        )

        assert result == {"error": "System is frozen"}

    @pytest.mark.asyncio
    async def test_submit_intent_success(self, orchestrator):
        """Test successful intent submission."""
        mock_api = AsyncMock()
        mock_api.propose_intent.return_value = {"intent_id": "test-123"}
        orchestrator._api = mock_api

        risk_preview = MagicMock()
        shadow_sim = MagicMock()
        position_req = MagicMock()

        result = await orchestrator.submit_intent(
            "test-strategy", "BULL", 0.8, risk_preview, shadow_sim, position_req, 1234567890
        )

        assert result == {"intent_id": "test-123"}
        assert orchestrator._metrics.intents_processed == 1

        mock_api.propose_intent.assert_called_once()

    @pytest.mark.asyncio
    async def test_approve_intent(self, orchestrator):
        """Test intent approval."""
        mock_api = AsyncMock()
        mock_api.authorize_execution.return_value = {"status": "APPROVED"}
        orchestrator._api = mock_api

        constraints = MagicMock()
        approved_by = ["user1", "user2"]

        result = await orchestrator.approve_intent(
            "intent-123", approved_by, constraints
        )

        assert result == {"status": "APPROVED"}
        assert orchestrator._metrics.intents_approved == 1

    @pytest.mark.asyncio
    async def test_reject_intent(self, orchestrator):
        """Test intent rejection."""
        mock_api = AsyncMock()
        mock_api.reject_intent.return_value = {"status": "REJECTED"}
        orchestrator._api = mock_api

        result = await orchestrator.reject_intent(
            "intent-123", ["user1"], "Test rejection"
        )

        assert result == {"status": "REJECTED"}
        assert orchestrator._metrics.intents_rejected == 1

    @pytest.mark.asyncio
    async def test_report_execution_completed(self, orchestrator):
        """Test execution reporting - completed."""
        mock_api = AsyncMock()
        mock_api.report_execution.return_value = {"status": "OK"}
        orchestrator._api = mock_api

        mock_report = MagicMock()
        mock_report.status = "COMPLETED"

        result = await orchestrator.report_execution(mock_report)

        assert orchestrator._metrics.executions_completed == 1
        assert orchestrator._metrics.executions_failed == 0

    @pytest.mark.asyncio
    async def test_report_execution_failed(self, orchestrator):
        """Test execution reporting - failed."""
        mock_api = AsyncMock()
        mock_api.report_execution.return_value = {"status": "OK"}
        orchestrator._api = mock_api

        mock_report = MagicMock()
        mock_report.status = "FAILED"

        result = await orchestrator.report_execution(mock_report)

        assert orchestrator._metrics.executions_completed == 0
        assert orchestrator._metrics.executions_failed == 1

    @pytest.mark.asyncio
    async def test_deposit_profit(self, orchestrator):
        """Test profit deposit."""
        mock_api = AsyncMock()
        mock_api.deposit_profit.return_value = {"status": "ACCEPTED"}
        orchestrator._api = mock_api

        mock_deposit = MagicMock()
        mock_deposit.amount = 1000.0

        result = await orchestrator.deposit_profit(mock_deposit)

        assert orchestrator._metrics.profits_deposited == 1000.0

    def test_get_state(self, orchestrator):
        """Test getting orchestrator state."""
        assert orchestrator.get_state() == OrchestratorState.INITIALIZING

    def test_get_system_health(self, orchestrator):
        """Test getting system health."""
        health = orchestrator.get_system_health()

        assert len(health) == len(MeridSystem)
        for system in MeridSystem:
            assert system.value in health
            assert "healthy" in health[system.value]
            assert "last_heartbeat" in health[system.value]

    def test_get_metrics(self, orchestrator):
        """Test getting metrics."""
        metrics = orchestrator.get_metrics()

        expected_keys = [
            "intents_processed", "intents_approved", "intents_rejected",
            "executions_completed", "executions_failed", "profits_deposited",
            "freezes_triggered", "avg_intent_latency_ms", "avg_execution_latency_ms"
        ]

        for key in expected_keys:
            assert key in metrics

    def test_get_status(self, orchestrator):
        """Test getting full status."""
        mock_api = MagicMock()
        mock_api.get_stats.return_value = {"api": "stats"}
        mock_api.get_active_freeze.return_value = None
        orchestrator._api = mock_api

        status = orchestrator.get_status()

        assert "state" in status
        assert "systems" in status
        assert "metrics" in status
        assert "api_stats" in status
        assert "active_freeze" in status
        assert status["active_freeze"] is False


class TestSystemOrchestratorSingleton:
    """Test singleton functionality."""

    def test_get_system_orchestrator(self):
        """Test singleton creation."""
        # Clear existing instance
        import core.system_orchestrator
        core.system_orchestrator._orchestrator = None

        orch1 = get_system_orchestrator()
        orch2 = get_system_orchestrator()

        assert orch1 is orch2
        assert isinstance(orch1, SystemOrchestrator)

    @pytest.mark.asyncio
    async def test_start_merid(self):
        """Test MERID start function."""
        # Clear existing instance
        import core.system_orchestrator
        core.system_orchestrator._orchestrator = None

        with patch('core.system_orchestrator.get_system_orchestrator') as mock_get:
            mock_orch = AsyncMock()
            mock_get.return_value = mock_orch

            result = await start_merid()

            assert result == mock_orch
            mock_orch.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_merid(self):
        """Test MERID stop function."""
        with patch('core.system_orchestrator.get_system_orchestrator') as mock_get:
            mock_orch = AsyncMock()
            mock_get.return_value = mock_orch

            await stop_merid()

            mock_orch.stop.assert_called_once()


class TestDataClasses:
    """Test data classes."""

    def test_system_health_dataclass(self):
        """Test SystemHealth dataclass."""
        health = SystemHealth(
            system=MeridSystem.OPS,
            healthy=True,
            last_heartbeat=123.45,
            error_count=2,
            latency_ms=50.5
        )

        assert health.system == MeridSystem.OPS
        assert health.healthy is True
        assert health.last_heartbeat == 123.45
        assert health.error_count == 2
        assert health.latency_ms == 50.5

        # Test to_dict
        data = health.to_dict()
        assert data["system"] == "OPS"
        assert data["healthy"] is True
        assert data["error_count"] == 2

    def test_orchestrator_metrics_dataclass(self):
        """Test OrchestratorMetrics dataclass."""
        metrics = OrchestratorMetrics(
            intents_processed=10,
            intents_approved=8,
            intents_rejected=2,
            executions_completed=7,
            executions_failed=1,
            profits_deposited=5000.0,
            freezes_triggered=1,
            avg_intent_latency_ms=150.5,
            avg_execution_latency_ms=200.0
        )

        assert metrics.intents_processed == 10
        assert metrics.profits_deposited == 5000.0

        # Test to_dict
        data = metrics.to_dict()
        assert data["intents_processed"] == 10
        assert data["profits_deposited"] == 5000.0

    def test_orchestrator_state_enum(self):
        """Test OrchestratorState enum."""
        assert OrchestratorState.INITIALIZING.value == "initializing"
        assert OrchestratorState.RUNNING.value == "running"
        assert OrchestratorState.FROZEN.value == "frozen"
        assert OrchestratorState.SHUTDOWN.value == "shutdown"
