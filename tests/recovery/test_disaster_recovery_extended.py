"""Extended tests for recovery/disaster_recovery.py - Disaster Recovery Coverage."""
import pytest
import time
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from recovery.disaster_recovery import (
    SystemState,
    RecoveryMode,
    ComponentStatus,
    RecoveryPoint,
    ComponentHealth,
    AnomalyEvent,
    StateReconstructor,
    PartialBootManager,
    ShadowPromotionManager,
    CapitalFreezeManager,
    AgentQuarantineManager,
    DisasterRecoveryManager,
    get_disaster_recovery,
)


class TestEnums:
    """Test enum definitions."""

    def test_system_state_values(self):
        """Test SystemState enum values."""
        assert SystemState.HEALTHY.value == "healthy"
        assert SystemState.DEGRADED.value == "degraded"
        assert SystemState.RECOVERING.value == "recovering"
        assert SystemState.PARTIAL_BOOT.value == "partial_boot"
        assert SystemState.COLD_START.value == "cold_start"
        assert SystemState.EMERGENCY.value == "emergency"
        assert SystemState.FROZEN.value == "frozen"

    def test_recovery_mode_values(self):
        """Test RecoveryMode enum values."""
        assert RecoveryMode.FULL.value == "full"
        assert RecoveryMode.PARTIAL.value == "partial"
        assert RecoveryMode.SHADOW_ONLY.value == "shadow_only"
        assert RecoveryMode.READ_ONLY.value == "read_only"
        assert RecoveryMode.SAFE_MODE.value == "safe_mode"

    def test_component_status_values(self):
        """Test ComponentStatus enum values."""
        assert ComponentStatus.RUNNING.value == "running"
        assert ComponentStatus.STOPPED.value == "stopped"
        assert ComponentStatus.FAILED.value == "failed"
        assert ComponentStatus.QUARANTINED.value == "quarantined"
        assert ComponentStatus.RECOVERING.value == "recovering"


class TestRecoveryPoint:
    """Test RecoveryPoint dataclass."""

    def test_creation(self):
        """Test creating recovery point."""
        point = RecoveryPoint(
            point_id="rp_123",
            timestamp=1234567890.0,
            state_hash="abc123",
            components={"trading": "running"},
            data_files=["data/state.json"]
        )
        assert point.point_id == "rp_123"
        assert point.verified is False

    def test_to_dict(self):
        """Test recovery point to_dict."""
        point = RecoveryPoint(
            point_id="rp_456",
            timestamp=1234567890.0,
            state_hash="def456",
            components={"api": "stopped"},
            data_files=[],
            verified=True
        )
        result = point.to_dict()
        
        assert result["point_id"] == "rp_456"
        assert result["verified"] is True


class TestComponentHealth:
    """Test ComponentHealth dataclass."""

    def test_creation(self):
        """Test creating component health."""
        health = ComponentHealth(
            component_id="trading",
            name="Trading Engine",
            status=ComponentStatus.RUNNING,
            last_heartbeat=time.time()
        )
        assert health.component_id == "trading"
        assert health.error_count == 0
        assert health.can_restart is True

    def test_to_dict(self):
        """Test component health to_dict."""
        health = ComponentHealth(
            component_id="api",
            name="API Server",
            status=ComponentStatus.FAILED,
            last_heartbeat=1234567890.0,
            error_count=3,
            last_error="Connection timeout"
        )
        result = health.to_dict()
        
        assert result["status"] == "failed"
        assert result["error_count"] == 3


class TestAnomalyEvent:
    """Test AnomalyEvent dataclass."""

    def test_creation(self):
        """Test creating anomaly event."""
        event = AnomalyEvent(
            event_id="anomaly_001",
            event_type="loss",
            severity="critical",
            description="Large loss detected",
            detected_at=time.time()
        )
        assert event.event_id == "anomaly_001"
        assert event.resolved is False

    def test_to_dict(self):
        """Test anomaly event to_dict."""
        event = AnomalyEvent(
            event_id="anomaly_002",
            event_type="drawdown",
            severity="high",
            description="Drawdown exceeded threshold",
            detected_at=1234567890.0,
            component="risk_engine",
            action_taken="capital_frozen",
            resolved=True
        )
        result = event.to_dict()
        
        assert result["severity"] == "high"
        assert result["resolved"] is True


class TestStateReconstructor:
    """Test StateReconstructor class."""

    @pytest.fixture
    def reconstructor(self, tmp_path):
        """Create reconstructor with temp directories."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        return StateReconstructor(str(log_dir), str(data_dir))

    def test_initialization(self, reconstructor):
        """Test reconstructor initialization."""
        assert reconstructor._reconstruction_log == []

    def test_scan_logs_empty(self, reconstructor):
        """Test scanning empty logs directory."""
        events = reconstructor.scan_logs()
        
        assert events["trades"] == []
        assert events["orders"] == []

    def test_scan_logs_with_content(self, tmp_path):
        """Test scanning logs with content."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        
        # Create a log file with content
        log_file = log_dir / "test.log"
        log_file.write_text("2024-01-01 | TRADE executed\n2024-01-01 | ORDER placed\n")
        
        reconstructor = StateReconstructor(str(log_dir), str(tmp_path / "data"))
        events = reconstructor.scan_logs()
        
        assert len(events["trades"]) > 0 or len(events["orders"]) > 0

    def test_scan_logs_nonexistent_dir(self):
        """Test scanning nonexistent directory."""
        reconstructor = StateReconstructor("nonexistent_dir", "nonexistent_data")
        events = reconstructor.scan_logs()
        
        assert events["trades"] == []

    def test_reconstruct_positions(self, reconstructor):
        """Test reconstructing positions."""
        positions = reconstructor.reconstruct_positions()
        
        assert isinstance(positions, dict)
        assert len(reconstructor._reconstruction_log) > 0

    def test_reconstruct_consensus_chain(self, reconstructor):
        """Test reconstructing consensus chain."""
        blocks = reconstructor.reconstruct_consensus_chain()
        
        assert isinstance(blocks, list)

    def test_verify_reconstruction(self, reconstructor):
        """Test verifying reconstruction."""
        result = reconstructor.verify_reconstruction()
        assert result is True

    def test_get_reconstruction_log(self, reconstructor):
        """Test getting reconstruction log."""
        reconstructor.reconstruct_positions()
        log = reconstructor.get_reconstruction_log()
        
        assert len(log) > 0
        assert log[0]["action"] == "reconstruct_positions"


class TestPartialBootManager:
    """Test PartialBootManager class."""

    @pytest.fixture
    def manager(self):
        return PartialBootManager()

    def test_initialization(self, manager):
        """Test manager initialization."""
        assert manager._boot_mode == RecoveryMode.FULL
        assert manager._failed_components == set()

    def test_register_component(self, manager):
        """Test registering component."""
        manager.register_component("trading", "Trading Engine")
        
        assert "trading" in manager._component_status
        assert manager._component_status["trading"].status == ComponentStatus.STOPPED

    def test_register_component_with_dependencies(self, manager):
        """Test registering component with custom dependencies."""
        manager.register_component("custom", "Custom Component", ["dep1", "dep2"])
        
        assert manager._component_status["custom"].dependencies == ["dep1", "dep2"]

    def test_report_health_healthy(self, manager):
        """Test reporting healthy status."""
        manager.register_component("api", "API Server")
        manager.report_health("api", healthy=True)
        
        assert manager._component_status["api"].status == ComponentStatus.RUNNING

    def test_report_health_unhealthy(self, manager):
        """Test reporting unhealthy status."""
        manager.register_component("trading", "Trading Engine")
        
        # Report unhealthy 3 times to trigger failure
        manager.report_health("trading", healthy=False, error="Error 1")
        manager.report_health("trading", healthy=False, error="Error 2")
        manager.report_health("trading", healthy=False, error="Error 3")
        
        assert manager._component_status["trading"].status == ComponentStatus.FAILED
        assert "trading" in manager._failed_components

    def test_report_health_unknown_component(self, manager):
        """Test reporting health for unknown component."""
        manager.report_health("unknown", healthy=True)
        # Should not raise error

    def test_determine_boot_mode_full(self, manager):
        """Test determining full boot mode."""
        mode = manager.determine_boot_mode()
        assert mode == RecoveryMode.FULL

    def test_determine_boot_mode_partial(self, manager):
        """Test determining partial boot mode with optional failure."""
        manager._failed_components.add("arbitrage")
        mode = manager.determine_boot_mode()
        
        assert mode == RecoveryMode.PARTIAL

    def test_determine_boot_mode_safe(self, manager):
        """Test determining safe mode with critical failures."""
        manager._failed_components.add("market_data")
        manager._failed_components.add("risk_engine")
        mode = manager.determine_boot_mode()
        
        assert mode == RecoveryMode.SAFE_MODE

    def test_get_bootable_components_full(self, manager):
        """Test getting bootable components in full mode."""
        manager.register_component("api", "API Server")
        manager.register_component("trading", "Trading Engine")
        
        bootable = manager.get_bootable_components()
        
        assert "api" in bootable
        assert "trading" in bootable

    def test_get_bootable_components_partial(self, manager):
        """Test getting bootable components with failures."""
        manager.register_component("trading", "Trading Engine")
        manager.register_component("arbitrage", "Arbitrage Engine")
        manager._failed_components.add("market_data")
        manager._boot_mode = RecoveryMode.PARTIAL
        
        bootable = manager.get_bootable_components()
        
        # Components depending on market_data should not be bootable
        assert isinstance(bootable, list)

    def test_get_status(self, manager):
        """Test getting status."""
        manager.register_component("api", "API Server")
        status = manager.get_status()
        
        assert "boot_mode" in status
        assert "failed_components" in status
        assert "component_status" in status


class TestShadowPromotionManager:
    """Test ShadowPromotionManager class."""

    @pytest.fixture
    def manager(self):
        return ShadowPromotionManager()

    def test_initialization(self, manager):
        """Test manager initialization."""
        assert manager._is_shadow is True

    def test_check_promotion_eligibility_pass(self, manager):
        """Test eligibility check that passes."""
        eligible, issues = manager.check_promotion_eligibility(
            shadow_hours=48.0,
            divergence_pct=2.0,
            trade_count=20
        )
        
        assert eligible is True
        assert issues == []

    def test_check_promotion_eligibility_fail_hours(self, manager):
        """Test eligibility fail due to insufficient hours."""
        eligible, issues = manager.check_promotion_eligibility(
            shadow_hours=12.0,
            divergence_pct=2.0,
            trade_count=20
        )
        
        assert eligible is False
        assert any("shadow time" in i.lower() for i in issues)

    def test_check_promotion_eligibility_fail_divergence(self, manager):
        """Test eligibility fail due to high divergence."""
        eligible, issues = manager.check_promotion_eligibility(
            shadow_hours=48.0,
            divergence_pct=10.0,
            trade_count=20
        )
        
        assert eligible is False
        assert any("divergence" in i.lower() for i in issues)

    def test_check_promotion_eligibility_fail_trades(self, manager):
        """Test eligibility fail due to insufficient trades."""
        eligible, issues = manager.check_promotion_eligibility(
            shadow_hours=48.0,
            divergence_pct=2.0,
            trade_count=5
        )
        
        assert eligible is False
        assert any("trades" in i.lower() for i in issues)

    def test_promote_to_primary_without_approval(self, manager):
        """Test promotion without approval."""
        result = manager.promote_to_primary()
        
        assert result is False
        assert manager._is_shadow is True

    def test_promote_to_primary_with_approval(self, manager):
        """Test promotion with approval."""
        result = manager.promote_to_primary("signature_abc123456789012345")
        
        assert result is True
        assert manager._is_shadow is False

    def test_demote_to_shadow(self, manager):
        """Test demotion to shadow."""
        manager._is_shadow = False
        manager.demote_to_shadow("System anomaly detected")
        
        assert manager._is_shadow is True
        assert len(manager._promotion_history) > 0

    def test_get_status(self, manager):
        """Test getting status."""
        status = manager.get_status()
        
        assert status["is_shadow"] is True
        assert status["mode"] == "shadow"
        assert "requirements" in status


class TestCapitalFreezeManager:
    """Test CapitalFreezeManager class."""

    @pytest.fixture
    def manager(self):
        return CapitalFreezeManager()

    def test_initialization(self, manager):
        """Test manager initialization."""
        assert manager._frozen is False

    def test_freeze(self, manager):
        """Test freezing capital."""
        manager.freeze("Test freeze")
        
        assert manager._frozen is True
        assert manager._freeze_reason == "Test freeze"

    def test_unfreeze_without_approval(self, manager):
        """Test unfreezing without approval."""
        manager.freeze("Test")
        result = manager.unfreeze("")
        
        assert result is False
        assert manager._frozen is True

    def test_unfreeze_with_approval(self, manager):
        """Test unfreezing with approval."""
        manager.freeze("Test")
        result = manager.unfreeze("approval_signature_123456")
        
        assert result is True
        assert manager._frozen is False

    def test_is_frozen(self, manager):
        """Test is_frozen check."""
        assert manager.is_frozen() is False
        manager.freeze("Test")
        assert manager.is_frozen() is True

    def test_detect_anomaly_loss(self, manager):
        """Test detecting loss anomaly."""
        anomaly = manager.detect_anomaly(
            event_type="loss",
            value=10.0,
            threshold_key="max_loss_pct"
        )
        
        assert anomaly is not None
        assert anomaly.severity in ["high", "critical"]

    def test_detect_anomaly_critical_triggers_freeze(self, manager):
        """Test critical anomaly triggers freeze."""
        anomaly = manager.detect_anomaly(
            event_type="loss",
            value=15.0,  # > 5 * 2 = 10, should be critical
            threshold_key="max_loss_pct"
        )
        
        assert anomaly is not None
        assert manager.is_frozen() is True

    def test_detect_anomaly_no_threshold(self, manager):
        """Test detecting anomaly with unknown threshold."""
        anomaly = manager.detect_anomaly(
            event_type="unknown",
            value=100.0,
            threshold_key="nonexistent"
        )
        
        assert anomaly is None

    def test_detect_anomaly_below_threshold(self, manager):
        """Test no anomaly when below threshold."""
        anomaly = manager.detect_anomaly(
            event_type="loss",
            value=2.0,
            threshold_key="max_loss_pct"
        )
        
        assert anomaly is None

    def test_detect_anomaly_drawdown(self, manager):
        """Test detecting drawdown anomaly."""
        anomaly = manager.detect_anomaly(
            event_type="drawdown",
            value=15.0,
            threshold_key="max_drawdown_pct"
        )
        
        assert anomaly is not None

    def test_detect_anomaly_position_size(self, manager):
        """Test detecting position size anomaly."""
        anomaly = manager.detect_anomaly(
            event_type="position_size",
            value=60.0,
            threshold_key="max_position_size_pct"
        )
        
        assert anomaly is not None

    def test_detect_anomaly_consecutive_losses(self, manager):
        """Test detecting consecutive losses anomaly."""
        anomaly = manager.detect_anomaly(
            event_type="consecutive_losses",
            value=5,
            threshold_key="max_consecutive_losses"
        )
        
        assert anomaly is not None

    def test_detect_anomaly_unusual_volume(self, manager):
        """Test detecting unusual volume anomaly."""
        anomaly = manager.detect_anomaly(
            event_type="unusual_volume",
            value=15.0,
            threshold_key="unusual_volume_multiplier"
        )
        
        assert anomaly is not None

    def test_get_status(self, manager):
        """Test getting status."""
        status = manager.get_status()
        
        assert "frozen" in status
        assert "thresholds" in status
        assert "recent_anomalies" in status


class TestAgentQuarantineManager:
    """Test AgentQuarantineManager class."""

    @pytest.fixture
    def manager(self):
        return AgentQuarantineManager()

    def test_initialization(self, manager):
        """Test manager initialization."""
        assert manager._quarantined == {}

    def test_quarantine_agent(self, manager):
        """Test quarantining an agent."""
        manager.quarantine_agent("agent_001", "Bad decisions")
        
        assert "agent_001" in manager._quarantined
        assert manager._quarantine_reasons["agent_001"] == ["Bad decisions"]

    def test_release_agent(self, manager):
        """Test releasing agent from quarantine."""
        manager.quarantine_agent("agent_002", "Test")
        result = manager.release_agent("agent_002")
        
        assert result is True
        assert "agent_002" not in manager._quarantined

    def test_release_agent_not_quarantined(self, manager):
        """Test releasing non-quarantined agent."""
        result = manager.release_agent("unknown_agent")
        
        assert result is False

    def test_release_agent_cannot_release(self, manager):
        """Test releasing agent that cannot be released."""
        manager.quarantine_agent("agent_003", "Permanent ban")
        manager._quarantined["agent_003"]["can_release"] = False
        
        result = manager.release_agent("agent_003")
        
        assert result is False

    def test_is_quarantined(self, manager):
        """Test is_quarantined check."""
        assert manager.is_quarantined("agent_004") is False
        manager.quarantine_agent("agent_004", "Test")
        assert manager.is_quarantined("agent_004") is True

    def test_check_agent_health_bad_decisions(self, manager):
        """Test quarantine for bad decisions."""
        reason = manager.check_agent_health(
            agent_id="agent_005",
            bad_decisions=10,
            consensus_rejections=0,
            trust_score=0.8
        )
        
        assert reason is not None
        assert "bad decisions" in reason.lower()
        assert manager.is_quarantined("agent_005")

    def test_check_agent_health_consensus_rejections(self, manager):
        """Test quarantine for consensus rejections."""
        reason = manager.check_agent_health(
            agent_id="agent_006",
            bad_decisions=0,
            consensus_rejections=15,
            trust_score=0.8
        )
        
        assert reason is not None
        assert "consensus" in reason.lower()

    def test_check_agent_health_low_trust(self, manager):
        """Test quarantine for low trust score."""
        reason = manager.check_agent_health(
            agent_id="agent_007",
            bad_decisions=0,
            consensus_rejections=0,
            trust_score=0.1
        )
        
        assert reason is not None
        assert "trust" in reason.lower()

    def test_check_agent_health_healthy(self, manager):
        """Test healthy agent check."""
        reason = manager.check_agent_health(
            agent_id="agent_008",
            bad_decisions=2,
            consensus_rejections=3,
            trust_score=0.9
        )
        
        assert reason is None
        assert not manager.is_quarantined("agent_008")

    def test_get_status(self, manager):
        """Test getting status."""
        manager.quarantine_agent("agent_009", "Test")
        status = manager.get_status()
        
        assert status["quarantined_count"] == 1
        assert "thresholds" in status


class TestDisasterRecoveryManager:
    """Test DisasterRecoveryManager class."""

    @pytest.fixture
    def manager(self):
        return DisasterRecoveryManager()

    def test_initialization(self, manager):
        """Test manager initialization."""
        assert manager._system_state == SystemState.HEALTHY
        assert manager.state_reconstructor is not None
        assert manager.partial_boot is not None
        assert manager.shadow_promotion is not None
        assert manager.capital_freeze is not None
        assert manager.agent_quarantine is not None

    def test_playbooks_initialized(self, manager):
        """Test playbooks are initialized."""
        assert "database_failure" in manager._playbooks
        assert "exchange_disconnect" in manager._playbooks
        assert "agent_cascade_failure" in manager._playbooks
        assert "capital_anomaly" in manager._playbooks
        assert "full_system_restart" in manager._playbooks

    def test_create_recovery_point(self, manager):
        """Test creating recovery point."""
        point = manager.create_recovery_point()
        
        assert point.point_id.startswith("rp_")
        assert point.verified is True
        assert len(manager._recovery_points) == 1

    def test_create_recovery_point_limits(self, manager):
        """Test recovery point limiting."""
        for _ in range(105):
            manager.create_recovery_point()
        
        assert len(manager._recovery_points) == 100

    def test_get_recovery_points(self, manager):
        """Test getting recovery points."""
        manager.create_recovery_point()
        manager.create_recovery_point()
        
        points = manager.get_recovery_points(limit=1)
        
        assert len(points) == 1

    def test_execute_playbook(self, manager):
        """Test executing playbook."""
        result = manager.execute_playbook("database_failure")
        
        assert result["playbook"] == "database_failure"
        assert result["status"] == "completed"
        assert len(result["steps_completed"]) > 0

    def test_execute_playbook_not_found(self, manager):
        """Test executing unknown playbook."""
        result = manager.execute_playbook("nonexistent_playbook")
        
        assert "error" in result

    def test_set_system_state(self, manager):
        """Test setting system state."""
        manager.set_system_state(SystemState.DEGRADED)
        
        assert manager._system_state == SystemState.DEGRADED

    def test_get_status(self, manager):
        """Test getting status."""
        manager.create_recovery_point()
        status = manager.get_status()
        
        assert status["system_state"] == "healthy"
        assert "partial_boot" in status
        assert "shadow_promotion" in status
        assert "capital_freeze" in status
        assert "agent_quarantine" in status
        assert status["recovery_points"] == 1
        assert "available_playbooks" in status


class TestSingleton:
    """Test singleton pattern."""

    def test_get_disaster_recovery_singleton(self):
        """Test get_disaster_recovery returns singleton."""
        import recovery.disaster_recovery as dr_module
        dr_module._disaster_recovery = None
        
        manager1 = get_disaster_recovery()
        manager2 = get_disaster_recovery()
        
        assert manager1 is manager2
        
        # Cleanup
        dr_module._disaster_recovery = None
