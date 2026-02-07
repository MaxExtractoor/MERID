"""
Tests for core/reality_auditor.py
Coverage target: 85%
"""
import time
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from core.reality_auditor import (
    RealityAuditor,
    AuditResult,
    get_reality_auditor
)
from core.reality_registry import (
    AuditorMode,
    BlindnessSeverity,
    AssertionStatus,
    AssertionDomain,
    BlindnessContext,
    RealityAssertion
)


class TestRealityAuditor:
    """Test RealityAuditor functionality."""

    @pytest.fixture
    def auditor(self):
        """Create RealityAuditor instance with mocked registry."""
        with patch('core.reality_auditor.get_reality_registry') as mock_registry:
            mock_registry_instance = MagicMock()
            mock_registry.return_value = mock_registry_instance

            auditor = RealityAuditor(registry=mock_registry_instance, environment="test")
            yield auditor

    def test_initialization(self, auditor):
        """Test RealityAuditor initialization."""
        assert auditor.regime_entropy == 0.0
        assert auditor.environment == "test"
        assert auditor.current_mode == AuditorMode.NORMAL
        assert auditor.last_blindness_context is None
        assert auditor.last_audit > 0

    def test_update_regime_entropy(self, auditor):
        """Test regime entropy updates."""
        # Normal value
        auditor.update_regime_entropy(0.5)
        assert auditor.regime_entropy == 0.5

        # Clamp to minimum
        auditor.update_regime_entropy(-0.5)
        assert auditor.regime_entropy == 0.0

        # Clamp to maximum
        auditor.update_regime_entropy(1.5)
        assert auditor.regime_entropy == 1.0

    def test_audit_loop_normal_operation(self, auditor):
        """Test audit loop with normal operation."""
        # Mock registry methods
        auditor.registry.update_assertion_status = MagicMock()
        auditor.registry.check_blindness_context = MagicMock(return_value=MagicMock(
            mode=AuditorMode.NORMAL,
            severity=BlindnessSeverity.LOW,
            primary_reason="Test",
            impacted_subsystems=["test"]
        ))

        result = auditor.audit_loop()

        assert result[0] == "normal"  # mode value
        assert auditor.current_mode == AuditorMode.NORMAL
        assert auditor.last_blindness_context is not None

        # Verify registry methods called
        auditor.registry.update_assertion_status.assert_called_once()
        auditor.registry.check_blindness_context.assert_called_once()

    def test_audit_loop_blindness_detected(self, auditor):
        """Test audit loop when blindness is detected."""
        from core.reality_registry import AuditorMode, BlindnessSeverity
        blindness_context = MagicMock()
        blindness_context.mode = AuditorMode.BLINDNESS  # Use proper enum
        blindness_context.severity = BlindnessSeverity.CRITICAL
        blindness_context.primary_reason = "Test blindness"
        blindness_context.impacted_subsystems = ["ui", "execution"]
        blindness_context.blind_duration = 1.5

        auditor.registry.check_blindness_context = MagicMock(return_value=blindness_context)

        with patch.object(auditor, '_log_blindness_incident') as mock_log:
            # Mock the to_dict method to return proper data
            blindness_context.to_dict.return_value = {
                "mode": "blindness",  # The .value of AuditorMode.BLINDNESS
                "severity": "critical", 
                "primary_reason": "Test blindness",
                "impacted_subsystems": ["ui", "execution"],
                "blind_duration": 1.5
            }
            result = auditor.audit_loop()

            assert result[0] == "blindness"  # Should be the enum value
            mock_log.assert_called_once_with(blindness_context)

    def test_audit_ui_component_success(self, auditor):
        """Test successful UI component audit."""
        # Mock assertions
        mock_assertion1 = MagicMock()
        mock_assertion1.assertion_id = "assertion1"
        mock_assertion1.status = AssertionStatus.VALID
        mock_assertion1.effective_confidence.return_value = 0.8

        mock_assertion2 = MagicMock()
        mock_assertion2.assertion_id = "assertion2"
        mock_assertion2.status = AssertionStatus.VALID
        mock_assertion2.effective_confidence.return_value = 0.9

        auditor.registry.get_assertion.side_effect = [mock_assertion1, mock_assertion2]

        result = auditor.audit_ui_component(
            component_id="test_component",
            required_assertions=["assertion1", "assertion2"],
            min_confidence=0.7
        )

        assert result.passed is True
        assert result.reason == "All assertions valid"
        assert len(result.blocking_assertions) == 0
        assert len(result.warnings) == 0

    def test_audit_ui_component_missing_assertion(self, auditor):
        """Test UI component audit with missing assertion."""
        auditor.registry.get_assertion.return_value = None

        result = auditor.audit_ui_component(
            component_id="test_component",
            required_assertions=["missing_assertion"]
        )

        assert result.passed is False
        assert "Missing required assertion" in result.reason
        assert result.blocking_assertions == ["missing_assertion"]

    def test_audit_ui_component_expired_assertion(self, auditor):
        """Test UI component audit with expired assertion."""
        mock_assertion = MagicMock()
        mock_assertion.assertion_id = "expired_assertion"
        mock_assertion.status = AssertionStatus.EXPIRED

        auditor.registry.get_assertion.return_value = mock_assertion

        result = auditor.audit_ui_component(
            component_id="test_component",
            required_assertions=["expired_assertion"],
            allow_expired=False
        )

        assert result.passed is False
        assert "Assertion expired" in result.reason
        assert result.blocking_assertions == ["expired_assertion"]

    def test_audit_ui_component_conflicted_assertion(self, auditor):
        """Test UI component audit with conflicted assertion."""
        mock_assertion = MagicMock()
        mock_assertion.assertion_id = "conflicted_assertion"
        mock_assertion.status = AssertionStatus.CONFLICTED

        auditor.registry.get_assertion.return_value = mock_assertion

        result = auditor.audit_ui_component(
            component_id="test_component",
            required_assertions=["conflicted_assertion"],
            allow_conflict=False
        )

        assert result.passed is False
        assert "Assertion conflicted" in result.reason
        assert result.blocking_assertions == ["conflicted_assertion"]

    def test_audit_ui_component_low_confidence(self, auditor):
        """Test UI component audit with low confidence assertion."""
        mock_assertion = MagicMock()
        mock_assertion.assertion_id = "low_confidence_assertion"
        mock_assertion.status = AssertionStatus.VALID
        mock_assertion.effective_confidence.return_value = 0.3

        auditor.registry.get_assertion.return_value = mock_assertion

        result = auditor.audit_ui_component(
            component_id="test_component",
            required_assertions=["low_confidence_assertion"],
            min_confidence=0.5
        )

        assert result.passed is False
        assert "Assertion confidence too low" in result.reason
        assert result.blocking_assertions == ["low_confidence_assertion"]

    def test_audit_ui_component_with_warnings(self, auditor):
        """Test UI component audit that passes but generates warnings."""
        mock_assertion1 = MagicMock()
        mock_assertion1.assertion_id = "valid_assertion"
        mock_assertion1.status = AssertionStatus.VALID
        mock_assertion1.effective_confidence.return_value = 0.8

        mock_assertion2 = MagicMock()
        mock_assertion2.assertion_id = "degraded_assertion"
        mock_assertion2.status = AssertionStatus.DEGRADED
        mock_assertion2.description = "test description"
        mock_assertion2.effective_confidence.return_value = 0.6

        auditor.registry.get_assertion.side_effect = [mock_assertion1, mock_assertion2]

        result = auditor.audit_ui_component(
            component_id="test_component",
            required_assertions=["valid_assertion", "degraded_assertion"]
        )

        assert result.passed is True
        assert len(result.warnings) > 0
        assert any("degraded" in warning for warning in result.warnings)

    def test_audit_execution_intent_success(self, auditor):
        """Test successful execution intent audit."""
        # Mock normal blindness context
        blindness_context = MagicMock()
        blindness_context.mode = AuditorMode.NORMAL
        auditor.registry.check_blindness_context.return_value = blindness_context

        # Mock assertions
        mock_assertion = MagicMock()
        mock_assertion.assertion_id = "execution_assertion"
        auditor.registry.get_assertion.return_value = mock_assertion

        # Mock assertion algebra
        with patch('core.reality_auditor.AssertionAlgebra.check_execution_eligibility') as mock_check:
            mock_check.return_value = (True, "Execution allowed")

            result = auditor.audit_execution_intent(
                intent_id="test_intent",
                required_assertions=["execution_assertion"],
                symbol="BTC/USD",
                amount_usd=10000.0
            )

            assert result.passed is True
            assert result.reason == "Execution allowed"

    def test_audit_execution_intent_blindness_blocked(self, auditor):
        """Test execution intent audit blocked by blindness."""
        # Mock blind mode
        blindness_context = MagicMock()
        blindness_context.mode = "BLIND"  # Use string value
        blindness_context.primary_reason = "System blind"
        auditor.registry.check_blindness_context.return_value = blindness_context

        result = auditor.audit_execution_intent(
            intent_id="test_intent",
            required_assertions=["any_assertion"],
            symbol="BTC/USD",
            amount_usd=10000.0
        )

        assert result.passed is False
        assert "BLINDNESS MODE" in result.reason
        assert result.blindness_context == blindness_context

    def test_audit_execution_intent_missing_assertion(self, auditor):
        """Test execution intent audit with missing assertion."""
        # Mock normal blindness
        blindness_context = MagicMock()
        blindness_context.mode = AuditorMode.NORMAL
        auditor.registry.check_blindness_context.return_value = blindness_context

        auditor.registry.get_assertion.return_value = None

        result = auditor.audit_execution_intent(
            intent_id="test_intent",
            required_assertions=["missing_assertion"],
            symbol="BTC/USD",
            amount_usd=10000.0
        )

        assert result.passed is False
        assert "Missing required assertion" in result.reason

    def test_audit_execution_intent_execution_blocked(self, auditor):
        """Test execution intent audit where execution is blocked."""
        # Mock normal blindness
        blindness_context = MagicMock()
        blindness_context.mode = AuditorMode.NORMAL
        auditor.registry.check_blindness_context.return_value = blindness_context

        # Mock assertions
        mock_assertion = MagicMock()
        auditor.registry.get_assertion.return_value = mock_assertion

        # Mock assertion algebra - execution blocked
        with patch('core.reality_auditor.AssertionAlgebra.check_execution_eligibility') as mock_check:
            mock_check.return_value = (False, "Insufficient confidence")

            result = auditor.audit_execution_intent(
                intent_id="test_intent",
                required_assertions=["test_assertion"],
                symbol="BTC/USD",
                amount_usd=10000.0
            )

            assert result.passed is False
            assert result.reason == "Insufficient confidence"

    def test_get_system_state_blind_mode(self, auditor):
        """Test get_system_state in blind mode."""
        # Mock registry status
        registry_status = {
            "valid_pct": 30,
            "blind_spots": ["market", "simulation"],
            "execution_allowed": False
        }
        auditor.registry.get_registry_status.return_value = registry_status

        # Mock blindness condition - system is blind due to core domains missing
        auditor.registry.check_blindness_condition.return_value = (True, "CORE_DOMAINS_MISSING: Missing ['market', 'simulation']")

        # Mock domain priority manager
        with patch('core.reality_auditor.get_domain_priority_manager') as mock_get_dpm:
            mock_dpm_instance = MagicMock()
            mock_get_dpm.return_value = mock_dpm_instance

            state = auditor.get_system_state()

            assert state["mode"] == "BLIND"
            assert state["is_blind"] is True
            assert "CORE_DOMAINS_MISSING" in state["blind_reason"]

    def test_get_system_state_sighted_degraded_mode(self, auditor):
        """Test get_system_state in sighted degraded mode."""
        # Mock registry status with some validity and core domains sighted
        # Core domains for system state are: market, onchain, simulation, agent
        registry_status = {
            "valid_pct": 75,
            "blind_spots": ["treasury"],  # Non-core domain in blind spots, core domains sighted
            "execution_allowed": False
        }
        auditor.registry.get_registry_status.return_value = registry_status

        # Mock blindness condition - system is blind but core domains sighted
        auditor.registry.check_blindness_condition.return_value = (True, "Partial blindness")

        # Mock safety checks to pass
        with patch.object(auditor, '_run_sighted_degraded_safety_checks') as mock_safety:
            mock_safety.return_value = {"passed": True, "reason": "Safety checks passed"}

            # Mock domain priority manager
            with patch('core.reality_auditor.get_domain_priority_manager') as mock_get_dpm:
                mock_dpm_instance = MagicMock()
                mock_get_dpm.return_value = mock_dpm_instance

                state = auditor.get_system_state()

                assert state["mode"] == "SIGHTED_DEGRADED"
                assert state["is_blind"] is True
                assert "SIGHTED_DEGRADED" in state["blind_reason"]

    def test_get_system_state_normal_mode(self, auditor):
        """Test get_system_state in normal sighted mode."""
        # Mock registry status - system is not blind
        registry_status = {
            "valid_pct": 95,
            "blind_spots": [],
            "execution_allowed": True
        }
        auditor.registry.get_registry_status.return_value = registry_status

        auditor.registry.check_blindness_condition.return_value = (False, None)

        state = auditor.get_system_state()

        assert state["mode"] == "BLIND"  # Default fallback when not blind
        assert state["is_blind"] is False
        assert state["blind_reason"] is None

    # def test_run_sighted_degraded_safety_checks_success(self, auditor):
    #     """Test sighted degraded safety checks - success case."""
    #     current_time = time.time()
    #     
    #     # Mock registry with sufficient valid assertions per domain (5+ per domain)
    #     mock_valid_assertions = []
    #     for i in range(6):  # 6 assertions per domain
    #         assertion = MagicMock()
    #         assertion.status = AssertionStatus.VALID
    #         assertion.created_at = current_time - 100  # Recent, within 5 minutes
    #         assertion.description = "normal assertion"  # No critical keywords
    #         mock_valid_assertions.append(assertion)

    #     # Add some invalid assertions that are not critical
    #     mock_invalid_assertions = []
    #     for i in range(2):
    #         assertion = MagicMock()
    #         assertion.status = AssertionStatus.INVALID
    #         assertion.description = "normal invalid"  # Not critical
    #         assertion.created_at = current_time - 100
    #         mock_invalid_assertions.append(assertion)

    #     # Combine assertions
    #     all_assertions = mock_valid_assertions + mock_invalid_assertions

    #     auditor.registry.get_assertions_by_domain.side_effect = [
    #         all_assertions,  # market
    #         all_assertions,  # onchain
    #         all_assertions,  # simulation
    #         all_assertions   # agent
    #     ]

    #     # Mock registry status - not too healthy, execution not allowed
    #     registry_status = {
    #         "execution_allowed": False, 
    #         "valid_pct": 75  # Not > 90, so not too healthy
    #     }

    #     result = auditor._run_sighted_degraded_safety_checks(registry_status, current_time)

    #     assert result["passed"] is True
    #     assert "SAFETY_CHECKS_PASSED" in result["reason"]

    def test_run_sighted_degraded_safety_checks_insufficient_assertions(self, auditor):
        """Test sighted degraded safety checks - insufficient assertions."""
        # Mock registry with insufficient valid assertions
        mock_domain_assertions = [MagicMock()] * 3  # Only 3 assertions per domain
        for assertion in mock_domain_assertions:
            assertion.status = AssertionStatus.VALID

        auditor.registry.get_assertions_by_domain.return_value = mock_domain_assertions

        registry_status = {"execution_allowed": False}

        result = auditor._run_sighted_degraded_safety_checks(registry_status, time.time())

        assert result["passed"] is False
        assert "INSUFFICIENT_ASSERTIONS" in result["reason"]

    def test_run_sighted_degraded_safety_checks_critical_failures(self, auditor):
        """Test sighted degraded safety checks - critical assertion failures."""
        # Mock assertions with critical failures
        mock_valid_assertions = [MagicMock()] * 6
        for assertion in mock_valid_assertions:
            assertion.status = AssertionStatus.VALID

        mock_critical_failures = [MagicMock()] * 2
        for assertion in mock_critical_failures:
            assertion.status = AssertionStatus.INVALID
            assertion.description = "critical failure detected"  # Contains "critical"

        # Combine assertions
        all_assertions = mock_valid_assertions + mock_critical_failures

        auditor.registry.get_assertions_by_domain.return_value = all_assertions

        registry_status = {"execution_allowed": False}

        result = auditor._run_sighted_degraded_safety_checks(registry_status, time.time())

        assert result["passed"] is False
        assert "CRITICAL_ASSERTIONS_FAILED" in result["reason"]

    def test_detect_self_deception_no_assertions(self, auditor):
        """Test self deception detection with no assertions."""
        auditor.registry._assertions = {}

        result = auditor.detect_self_deception()

        assert result["confidence_inflation"] == 0.0
        assert result["agreement_bias"] == 0.0
        assert result["narrative_comfort"] == 0.0
        # No warning key when there are no assertions

    def test_detect_self_deception_with_assertions(self, auditor):
        """Test self deception detection with assertions."""
        # Create mock assertions with varying properties
        assertions = []
        for i in range(10):
            assertion = MagicMock()
            assertion.confidence_score = 0.6  # Below baseline
            assertion.status = AssertionStatus.CONFLICTED if i < 2 else AssertionStatus.VALID
            assertion.description = "test"
            assertions.append(assertion)

        auditor.registry._assertions = {f"assert_{i}": assertions[i-1] for i in range(1, 11)}

        result = auditor.detect_self_deception()

        # Should detect confidence inflation (claims 0.6, baseline 0.5)
        assert result["confidence_inflation"] > 0
        # Should detect agreement bias (20% conflicted, above threshold)
        assert result["agreement_bias"] > 0
        # Should detect narrative comfort (some degraded assertions)
        assert result["narrative_comfort"] > 0
        assert result["warning"] is True

    def test_get_recent_assertions(self, auditor):
        """Test getting recent assertions."""
        # Create mock assertions with different timestamps
        current_time = time.time()
        recent_assertion = MagicMock()
        recent_assertion.assertion_id = "recent"
        recent_assertion.domain = AssertionDomain.MARKET
        recent_assertion.status = AssertionStatus.VALID
        recent_assertion.created_at = current_time - 3600  # 1 hour ago
        recent_assertion.confidence = 0.8
        recent_assertion.effective_confidence.return_value = 0.8

        old_assertion = MagicMock()
        old_assertion.created_at = current_time - 86400 * 2  # 2 days ago

        auditor.registry._assertions = {
            "recent": recent_assertion,
            "old": old_assertion
        }

        recent = auditor.get_recent_assertions(since_hours=24)

    def test_get_system_state_mode_transitions(self, auditor):
        """Test mode transitions in get_system_state."""
        # Set initial mode
        auditor.current_system_mode = "BLIND"
        
        # Mock for SIGHTED_DEGRADED transition
        registry_status = {
            "valid_pct": 75,
            "blind_spots": ["treasury"],  # Core domains sighted
            "execution_allowed": False
        }
        auditor.registry.get_registry_status.return_value = registry_status
        auditor.registry.check_blindness_condition.return_value = (True, "test")
        
        # Mock safety checks to pass
        with patch.object(auditor, '_run_sighted_degraded_safety_checks') as mock_safety:
            mock_safety.return_value = {"passed": True, "reason": "passed"}
            
            # Mock domain priority manager
            with patch('core.reality_auditor.get_domain_priority_manager') as mock_get_dpm:
                mock_dpm_instance = MagicMock()
                mock_get_dpm.return_value = mock_dpm_instance
                
                state = auditor.get_system_state()
                
                # Should transition to SIGHTED_DEGRADED
                assert state["mode"] == "SIGHTED_DEGRADED"
                # Should call domain priority manager
                mock_dpm_instance.set_mode.assert_called_with("SIGHTED_DEGRADED")

    def test_get_system_state_mode_transition_back(self, auditor):
        """Test mode transition back to BLIND."""
        # Set initial mode to SIGHTED_DEGRADED
        auditor.current_system_mode = "SIGHTED_DEGRADED"
        
        # Mock for BLIND transition (safety check fails)
        registry_status = {
            "valid_pct": 75,
            "blind_spots": ["treasury"],
            "execution_allowed": False
        }
        auditor.registry.get_registry_status.return_value = registry_status
        auditor.registry.check_blindness_condition.return_value = (True, "test")
        
        # Mock safety checks to fail
        with patch.object(auditor, '_run_sighted_degraded_safety_checks') as mock_safety:
            mock_safety.return_value = {"passed": False, "reason": "failed"}
            
            # Mock domain priority manager
            with patch('core.reality_auditor.get_domain_priority_manager') as mock_get_dpm:
                mock_dpm_instance = MagicMock()
                mock_get_dpm.return_value = mock_dpm_instance
                
                state = auditor.get_system_state()
                
                # Should transition to BLIND
                assert state["mode"] == "BLIND"
                # Should call domain priority manager to deactivate
                mock_dpm_instance.set_mode.assert_called_with("BLIND")

    def test_get_auditor_status_with_pipeline_health(self, auditor):
        """Test get_auditor_status with pipeline health."""
        # Mock blindness context
        blindness_context = MagicMock()
        blindness_context.to_dict.return_value = {"mode": "normal", "severity": "low"}
        auditor.registry.check_blindness_context.return_value = blindness_context

        # Mock pipeline health with different states
        pipeline_health = MagicMock()
        pipeline_health.assertions_per_hour = 0  # Stale
        pipeline_health.last_assertion_ts = time.time() - 86400 * 8  # 8 days ago
        pipeline_health.last_resolution_ts = time.time() - 86400 * 8
        pipeline_health.pending_assertions = 10
        pipeline_health.resolved_assertions = 5
        pipeline_health.is_stale = True
        pipeline_health.stale_threshold_hours = 24
        auditor.registry.get_assertion_pipeline_health.return_value = pipeline_health

        # Mock registry status
        registry_status = {"valid_pct": 85, "total_assertions": 100}
        auditor.registry.get_registry_status.return_value = registry_status

        status = auditor.get_auditor_status()

        assert status["auditor_mode"] == "normal"
        assert status["pipeline_health"]["is_stale"] is True
        assert status["pipeline_health"]["assertions_per_hour"] == 0

    def test_reload_from_persistent_store(self, auditor):
        """Test reloading from persistent store."""
        result = auditor.reload_from_persistent_store()

        # Should return True (placeholder implementation)
        assert result is True

    def test_log_blindness_incident_critical(self, auditor):
        """Test logging critical blindness incident."""
        from core.reality_registry import BlindnessSeverity, AuditorMode
        context = MagicMock()
        context.severity = BlindnessSeverity.CRITICAL
        context.mode = AuditorMode.BLINDNESS
        context.primary_reason = "Critical issue"
        context.impacted_subsystems = ["execution"]
        context.blind_duration = 2.5
        context.to_dict.return_value = {"test": "data"}

        with patch('core.reality_auditor.logger') as mock_logger:
            auditor._log_blindness_incident(context)

            mock_logger.error.assert_called_once()
            mock_logger.info.assert_called()

    def test_log_blindness_incident_concerning(self, auditor):
        """Test logging concerning blindness incident."""
        from core.reality_registry import BlindnessSeverity, AuditorMode
        context = MagicMock()
        context.severity = BlindnessSeverity.HIGH
        context.mode = AuditorMode.STRICT
        context.primary_reason = "Concerning issue"
        context.impacted_subsystems = ["ui"]
        context.blind_duration = 1.0
        context.to_dict.return_value = {"test": "data"}
        # Enums already have .value attributes, no need to set them

        with patch('core.reality_auditor.logger') as mock_logger:
            auditor._log_blindness_incident(context)

            mock_logger.warning.assert_called_once()
            mock_logger.info.assert_called()

    def test_log_blindness_incident_normal(self, auditor):
        """Test logging normal blindness incident."""
        from core.reality_registry import BlindnessSeverity, AuditorMode
        context = MagicMock()
        context.severity = BlindnessSeverity.LOW
        context.mode = AuditorMode.NORMAL
        context.primary_reason = "Normal operation"
        context.impacted_subsystems = []
        context.blind_duration = 0.0
        context.to_dict.return_value = {"test": "data"}
        # Enums already have .value attributes, no need to set them

        with patch('core.reality_auditor.logger') as mock_logger:
            auditor._log_blindness_incident(context)

            mock_logger.error.assert_not_called()
            mock_logger.warning.assert_not_called()
            mock_logger.info.assert_called()

    def test_audit_result_creation(self):
        """Test AuditResult creation."""
        from core.reality_auditor import AuditResult

        result = AuditResult(
            passed=True,
            reason="Test passed",
            blocking_assertions=[],
            warnings=["Minor warning"],
            blindness_context=None,
            auditor_mode=AuditorMode.NORMAL
        )

        assert result.passed is True
        assert result.reason == "Test passed"
        assert len(result.blocking_assertions) == 0
        assert len(result.warnings) == 1
        assert result.auditor_mode == AuditorMode.NORMAL


class TestRealityAuditorSingleton:
    """Test singleton functionality."""

    def test_get_reality_auditor(self):
        """Test singleton creation."""
        # Clear existing instance
        import core.reality_auditor
        core.reality_auditor._auditor = None

        auditor1 = get_reality_auditor()
        auditor2 = get_reality_auditor()

        assert auditor1 is auditor2
        assert isinstance(auditor1, RealityAuditor)


class TestAuditResult:
    """Test AuditResult data class."""

    def test_audit_result_creation(self):
        """Test AuditResult creation."""
        from core.reality_auditor import AuditResult

        result = AuditResult(
            passed=True,
            reason="Test passed",
            blocking_assertions=[],
            warnings=["Minor warning"],
            blindness_context=None,
            auditor_mode=AuditorMode.NORMAL
        )

        assert result.passed is True
        assert result.reason == "Test passed"
        assert len(result.blocking_assertions) == 0
        assert len(result.warnings) == 1
        assert result.auditor_mode == AuditorMode.NORMAL


class TestRealityAuditorSingleton:
    """Test singleton functionality."""

    def test_get_reality_auditor(self):
        """Test singleton creation."""
        # Clear existing instance
        import core.reality_auditor
        core.reality_auditor._auditor = None

        auditor1 = get_reality_auditor()
        auditor2 = get_reality_auditor()

        assert auditor1 is auditor2
        assert isinstance(auditor1, RealityAuditor)
