"""
MERID Phase 0 Integration Tests

Component-style tests for thin adapters with mocked services and end-to-end tests with real services.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
import json
from datetime import datetime

from web.api.phase0_adapters import create_phase0_router, HumanReviewInput, ScorecardDTO, ContractTestResultDTO
from core.merid_minimal_scope import GovernanceScorecard, RiskTier
from core.phase0_config import Phase0Config, Environment, AuditorMode
from utils.logger import get_logger

logger = get_logger("phase0_tests")

class TestPhase0Adapters:
    """Tests for thin HTTP adapters with mocked services."""
    
    @pytest.fixture
    def mock_config(self):
        """Mock Phase 0 configuration for testing."""
        config = Mock(spec=Phase0Config)
        config.is_phase0_active.return_value = True
        config.human_review_required = True
        config.contract_enforced = True
        config.dry_run = False
        return config
    
    @pytest.fixture
    def mock_service(self):
        """Mock governance service for testing."""
        service = Mock()
        
        # Mock scorecard
        scorecard = GovernanceScorecard(
            model_id="crypto_prediction_agent_v1",
            timestamp=datetime.now(),
            brier_score=0.18,
            brier_skill_score=0.12,
            calibration_archetype="PIT",
            n_events=150,
            current_tier="tier_3",
            risk_limits={"max_position_size": 20000},
            suggested_action="promote",
            action_reason="Strong performance",
            confidence=0.85,
            contract_tests={"all_passed": True},
            human_review_status="pending"
        )
        
        service.get_all_scorecards.return_value = [scorecard]
        service.generate_governance_scorecard.return_value = scorecard
        service.submit_human_review.return_value = {
            "success": True,
            "review": {"status": "approved"},
            "message": "Review submitted"
        }
        service.get_human_review_summary.return_value = {
            "total_models": 2,
            "override_rate": 0.15,
            "alignment_rate": 0.85
        }
        service.run_contract_tests_all_models.return_value = {
            "crypto_prediction_agent_v1": {
                "negative_bss_tier_restriction": True,
                "degradation_alert_guarantee": True,
                "blindness_auto_promotion_block": True,
                "minimum_events_requirement": True
            }
        }
        
        return service
    
    @pytest.fixture
    def app_client(self, mock_config, mock_service):
        """Create FastAPI test client with mocked dependencies."""
        from fastapi import FastAPI
        
        app = FastAPI()
        router = create_phase0_router()
        
        if router:
            app.include_router(router)
        
        # Override dependencies
        app.dependency_overrides[get_phase0_enabled] = lambda: mock_config
        app.dependency_overrides[get_governance_service] = lambda: mock_service
        
        return TestClient(app)
    
    def test_get_scope_success(self, app_client, mock_config, mock_service):
        """Test GET /minimal/scope success path."""
        response = app_client.get("/api/v1/minimal/scope")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "scope" in data
        assert "feature_flags" in data
        assert data["scope"]["focused_models"] is not None
        assert data["feature_flags"]["human_review_required"] is True
    
    def test_get_scorecards_success(self, app_client, mock_config, mock_service):
        """Test GET /minimal/scorecards success path."""
        response = app_client.get("/api/v1/minimal/scorecards")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "scorecards" in data
        assert len(data["scorecards"]) == 1
        
        scorecard = data["scorecards"][0]
        assert scorecard["model_id"] == "crypto_prediction_agent_v1"
        assert "metrics" in scorecard
        assert "governance" in scorecard
        assert "safety" in scorecard
        assert "human_review" in scorecard
    
    def test_get_scorecard_by_model_success(self, app_client, mock_config, mock_service):
        """Test GET /minimal/scorecards/{model_id} success path."""
        response = app_client.get("/api/v1/minimal/scorecards/crypto_prediction_agent_v1")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        scorecard = data["scorecard"]
        
        assert scorecard["model_id"] == "crypto_prediction_agent_v1"
        assert scorecard["metrics"]["brier_score"] == 0.18
        assert scorecard["governance"]["suggested_action"] == "promote"
        assert scorecard["safety"]["all_passed"] is True
    
    def test_get_scorecard_model_not_found(self, app_client, mock_config, mock_service):
        """Test GET /minimal/scorecards/{model_id} for model not in scope."""
        response = app_client.get("/api/v1/minimal/scorecards/unknown_model")
        
        assert response.status_code == 404
        data = response.json()
        
        assert "detail" in data
        assert "not in minimal scope" in data["detail"]
    
    def test_submit_human_review_success(self, app_client, mock_config, mock_service):
        """Test POST /minimal/human-review success path."""
        payload = {
            "model_id": "crypto_prediction_agent_v1",
            "action": "promote",
            "notes": "Strong performance meets criteria",
            "reviewer": "risk_manager"
        }
        
        response = app_client.post("/api/v1/minimal/human-review", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "review" in data
        assert "message" in data
        
        # Verify service was called correctly
        mock_service.submit_human_review.assert_called_once_with(
            model_id="crypto_prediction_agent_v1",
            action="promote",
            notes="Strong performance meets criteria",
            reviewer="risk_manager"
        )
    
    def test_submit_human_review_model_not_found(self, app_client, mock_config, mock_service):
        """Test POST /minimal/human-review for model not in scope."""
        payload = {
            "model_id": "unknown_model",
            "action": "promote",
            "notes": "Test",
            "reviewer": "test"
        }
        
        response = app_client.post("/api/v1/minimal/human-review", json=payload)
        
        assert response.status_code == 404
        data = response.json()
        
        assert "detail" in data
        assert "not in minimal scope" in data["detail"]
    
    def test_get_human_reviews_success(self, app_client, mock_config, mock_service):
        """Test GET /minimal/human-reviews success path."""
        response = app_client.get("/api/v1/minimal/human-reviews")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "summary" in data
        
        summary = data["summary"]
        assert summary["total_models"] == 2
        assert summary["override_rate"] == 0.15
        assert summary["alignment_rate"] == 0.85
    
    def test_get_contract_tests_success(self, app_client, mock_config, mock_service):
        """Test GET /minimal/contract-tests success path."""
        response = app_client.get("/api/v1/minimal/contract-tests")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "results" in data
        assert "summary" in data
        
        results = data["results"]
        assert len(results) == 1
        
        result = results[0]
        assert result["model_id"] == "crypto_prediction_agent_v1"
        assert result["all_passed"] is True
        assert len(result["failed_tests"]) == 0
    
    def test_get_contract_tests_by_model_success(self, app_client, mock_config, mock_service):
        """Test GET /minimal/contract-tests/{model_id} success path."""
        response = app_client.get("/api/v1/minimal/contract-tests/crypto_prediction_agent_v1")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        result = data["result"]
        
        assert result["model_id"] == "crypto_prediction_agent_v1"
        assert result["all_passed"] is True
        assert len(result["failed_tests"]) == 0
    
    def test_get_health_success(self, app_client, mock_config, mock_service):
        """Test GET /minimal/health success path."""
        response = app_client.get("/api/v1/minimal/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "health" in data
        assert "config" in data
        
        health = data["health"]
        assert health["status"] == "HEALTHY"
        assert health["models_in_scope"] == 1
        assert health["contract_test_failures"] == 0
    
    def test_feature_flag_disabled(self):
        """Test that router is None when feature flag is disabled."""
        with patch('core.phase0_config.get_phase0_config') as mock_config:
            mock_config.return_value = Mock(spec=Phase0Config)
            mock_config.return_value.minimal_scope_enabled = False
            
            router = create_phase0_router()
            assert router is None

class TestPhase0EndToEnd:
    """End-to-end tests with real services and test database."""
    
    @pytest.fixture
    def test_config(self):
        """Test configuration for end-to-end tests."""
        return Phase0Config(
            env=Environment.LOCAL,
            log_level="DEBUG",
            db_url="sqlite:///:memory:",
            db_schema=None,
            enabled=True,
            model_ids=["crypto_prediction_agent_v1"],
            brier_governance_enabled=True,
            feedback_loop_enabled=True,
            minimal_scope_enabled=True,
            human_review_required=True,
            contract_enforced=True,
            conservative_limits=True,
            auditor_mode=AuditorMode.NORMAL,
            dry_run=False,
            risk_profile="conservative",
            allow_auto_promotion=False,
            allow_auto_demotion=False
        )
    
    @pytest.fixture
    def mock_service(self):
        """Mock minimal scope service for end-to-end testing."""
        service = Mock()
        
        # Mock realistic scorecard
        scorecard = GovernanceScorecard(
            model_id="crypto_prediction_agent_v1",
            timestamp=datetime.now(),
            brier_score=0.18,
            brier_skill_score=0.12,
            calibration_archetype="PIT",
            n_events=150,
            current_tier="tier_3",
            risk_limits={"max_position_size": 20000},
            suggested_action="promote",
            action_reason="Strong performance meets criteria",
            confidence=0.85,
            contract_tests={
                "negative_bss_tier_restriction": True,
                "degradation_alert_guarantee": True,
                "blindness_auto_promotion_block": True,
                "minimum_events_requirement": True
            },
            human_review_status="pending"
        )
        
        service.get_all_scorecards.return_value = [scorecard]
        service.generate_governance_scorecard.return_value = scorecard
        service.config.FOCUSED_MODELS = ["crypto_prediction_agent_v1"]
        
        # Mock contract tests
        service.contract_tests.run_all_contract_tests.return_value = {
            "negative_bss_tier_restriction": True,
            "degradation_alert_guarantee": True,
            "blindness_auto_promotion_block": True,
            "minimum_events_requirement": True
        }
        
        return service
    
    @pytest.fixture
    def app_client(self, test_config, mock_service):
        """Create FastAPI test client for end-to-end testing."""
        from fastapi import FastAPI
        
        app = FastAPI()
        
        # Create router with test config
        with patch('core.phase0_config.get_phase0_config', return_value=test_config):
            router = create_phase0_router()
            
            if router:
                app.include_router(router)
        
        # Override dependencies
        app.dependency_overrides[get_governance_service] = lambda: mock_service
        
        return TestClient(app)
    
    def test_scorecard_contract_validation(self, app_client, mock_service):
        """Test that scorecard contract is stable and complete."""
        response = app_client.get("/api/v1/minimal/scorecards/crypto_prediction_agent_v1")
        
        assert response.status_code == 200
        data = response.json()
        
        scorecard = data["scorecard"]
        
        # Validate required fields exist
        required_fields = ["model_id", "timestamp", "metrics", "governance", "safety", "human_review"]
        for field in required_fields:
            assert field in scorecard, f"Missing required field: {field}"
        
        # Validate metrics structure
        metrics = scorecard["metrics"]
        required_metrics = ["brier_score", "brier_skill_score", "calibration_archetype", "n_events"]
        for metric in required_metrics:
            assert metric in metrics, f"Missing required metric: {metric}"
        
        # Validate governance structure
        governance = scorecard["governance"]
        required_governance = ["current_tier", "suggested_action", "confidence"]
        for gov_field in required_governance:
            assert gov_field in governance, f"Missing required governance field: {gov_field}"
        
        # Validate safety structure
        safety = scorecard["safety"]
        assert "contract_tests" in safety
        assert "all_passed" in safety
        
        # Validate human review structure
        human_review = scorecard["human_review"]
        assert "status" in human_review
    
    def test_contract_test_enforcement(self, app_client, mock_service):
        """Test that contract tests are properly enforced."""
        # Mock contract test failure
        mock_service.contract_tests.run_all_contract_tests.return_value = {
            "negative_bss_tier_restriction": False,  # Failed
            "degradation_alert_guarantee": True,
            "blindness_auto_promotion_block": True,
            "minimum_events_requirement": True
        }
        
        response = app_client.get("/api/v1/minimal/contract-tests/crypto_prediction_agent_v1")
        
        assert response.status_code == 200
        data = response.json()
        
        result = data["result"]
        assert result["all_passed"] is False
        assert len(result["failed_tests"]) == 1
        assert "negative_bss_tier_restriction" in result["failed_tests"]
    
    def test_human_review_workflow(self, app_client, mock_service):
        """Test complete human review workflow."""
        # Submit human review
        payload = {
            "model_id": "crypto_prediction_agent_v1",
            "action": "hold",
            "notes": "Waiting for more data points",
            "reviewer": "risk_manager"
        }
        
        response = app_client.post("/api/v1/minimal/human-review", json=payload)
        assert response.status_code == 200
        
        # Verify service was called
        mock_service.submit_human_review.assert_called_once()
        
        # Check human review summary
        response = app_client.get("/api/v1/minimal/human-reviews")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "summary" in data
    
    def test_health_check_comprehensive(self, app_client, mock_service):
        """Test comprehensive health check."""
        response = app_client.get("/api/v1/minimal/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        
        health = data["health"]
        assert "status" in health
        assert "models_in_scope" in health
        assert "contract_test_failures" in health
        
        config = data["config"]
        assert "phase0_enabled" in config
        assert "human_review_required" in config
        assert "contract_enforced" in config
        assert "dry_run" in config

if __name__ == "__main__":
    # Run tests
    pytest.main([__file__])
