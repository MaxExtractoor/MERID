#!/usr/bin/env python3
"""
MERID Assertion Framework - Comprehensive Test Suite

Tests the complete assertion system including templates, registry, client,
and integration with existing MERID components.
"""

import pytest
import time
import json
from typing import Dict, Any, List
from unittest.mock import Mock, patch

from core.assertion_framework import (
    Assertion, AssertionTemplate, AssertionStatus, AssertionSeverity,
    AssertionCategory, TemplateLifecycle, AssertionClient,
    assert_not_null, assert_timeout, assert_resource_limits,
    CORE_TEMPLATES, load_templates_from_config
)
from core.assertion_bindings import (
    assertion_template, null_check, timeout_check, resource_monitor,
    assert_forecast_must_resolve, assert_risk_limits,
    assert_data_quality_probabilities_sum_to_one,
    ci_assertion_decorator
)
from services.assertion_registry import (
    init_database, AssertionRegistration, AssertionUpdate, AssertionRecord
)


class TestAssertionFrameworkCore:
    """Test core assertion framework functionality."""
    
    def test_assertion_creation_and_serialization(self):
        """Test assertion dataclass creation and JSON serialization."""
        assertion = Assertion(
            template_id="test.template",
            severity=AssertionSeverity.MAJOR,
            subject={"market_id": "test_123"},
            parameters={"threshold": 0.5}
        )
        
        # Test serialization
        data = assertion.to_dict()
        assert data["template_id"] == "test.template"
        assert data["severity"] == "major"
        assert data["status"] == "pending"
        assert isinstance(data["subject"], dict)
        assert isinstance(data["parameters"], dict)
        
        # Test status update
        assertion.update_status(AssertionStatus.PASSED, "Test passed")
        assert assertion.status == AssertionStatus.PASSED
        assert assertion.resolved_at is not None
        assert assertion.resolution_details == "Test passed"
    
    def test_template_creation_and_validation(self):
        """Test assertion template creation and validation."""
        template = AssertionTemplate(
            template_id="test.template",
            version=1,
            library_version="1.0.0",
            description="Test template",
            category=AssertionCategory.CI,
            severity_default=AssertionSeverity.MAJOR,
            parameters=[
                {"name": "param1", "type": "string", "required": True},
                {"name": "param2", "type": "float", "required": False}
            ],
            tags={"env": ["test"], "language": ["python"]},
            owner_team="test"
        )
        
        # Test serialization
        data = template.to_dict()
        assert data["template_id"] == "test.template"
        assert data["category"] == "ci"
        assert data["severity_default"] == "major"
        assert len(data["parameters"]) == 2
    
    def test_assertion_client_interface(self):
        """Test assertion client interface methods."""
        client = AssertionClient("http://test.example.com")
        
        # Test template loading (mocked)
        with patch.object(client, '_send_to_registry') as mock_send:
            mock_send.return_value = {
                "template": {
                    "template_id": "test.template",
                    "version": 1,
                    "library_version": "1.0.0",
                    "description": "Test",
                    "category": "ci",
                    "severity_default": "major",
                    "parameters": [],
                    "tags": {},
                    "owner_team": "test"
                }
            }
            
            template = client.get_template("test.template")
            assert template.template_id == "test.template"
            assert template.version == 1
    
    def test_core_templates_loading(self):
        """Test loading of core assertion templates."""
        templates = load_templates_from_config(CORE_TEMPLATES)
        
        assert len(templates) > 0
        assert all(isinstance(t, AssertionTemplate) for t in templates)
        
        # Check specific templates exist
        template_ids = [t.template_id for t in templates]
        assert "core.nulls.value_must_not_be_null" in template_ids
        assert "ci.timeout.operation_must_complete_within_sla" in template_ids
        assert "ci.resources.job_resource_usage_within_limits" in template_ids


class TestAssertionHelpers:
    """Test assertion helper functions."""
    
    def test_assert_not_null_success(self):
        """Test successful null assertion."""
        with patch('core.assertion_framework.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            result = assert_not_null("test_key", "valid_value", "test_context")
            assert result == "valid_value"
    
    def test_assert_not_null_failure(self):
        """Test null assertion failure."""
        with patch('core.assertion_framework.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            with pytest.raises(AssertionError):
                assert_not_null("test_key", None, "test_context")
    
    def test_assert_not_null_nan(self):
        """Test NaN assertion failure."""
        import math
        with patch('core.assertion_framework.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            with pytest.raises(AssertionError):
                assert_not_null("test_key", math.nan, "test_context")
    
    def test_assert_timeout_success(self):
        """Test successful timeout assertion."""
        with patch('core.assertion_framework.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            result = assert_timeout("test_op", 100, 200, "test_context")
            assert result is True
    
    def test_assert_timeout_failure(self):
        """Test timeout assertion failure."""
        with patch('core.assertion_framework.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            result = assert_timeout("test_op", 300, 200, "test_context")
            assert result is False
    
    def test_assert_resource_limits_success(self):
        """Test successful resource limits assertion."""
        with patch('core.assertion_framework.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            result = assert_resource_limits("test_job", 50, 512, 100, 1024)
            assert result is True
    
    def test_assert_resource_limits_failure(self):
        """Test resource limits assertion failure."""
        with patch('core.assertion_framework.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            # CPU exceeded
            result = assert_resource_limits("test_job", 150, 512, 100, 1024)
            assert result is False
            
            # Memory exceeded
            result = assert_resource_limits("test_job", 50, 1536, 100, 1024)
            assert result is False


class TestAssertionDecorators:
    """Test assertion decorators and context managers."""
    
    def test_assertion_template_decorator_success(self):
        """Test assertion template decorator on successful function."""
        with patch('core.assertion_bindings.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            @assertion_template("test.template", AssertionSeverity.MINOR)
            def test_function(x, y):
                return x + y
            
            result = test_function(2, 3)
            assert result == 5
            mock_client.return_value.record.assert_called()
    
    def test_assertion_template_decorator_failure(self):
        """Test assertion template decorator on failed function."""
        with patch('core.assertion_bindings.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            @assertion_template("test.template", on_failure="log")
            def test_function(x):
                raise ValueError("Test error")
            
            result = test_function(None)
            assert result is None
            mock_client.return_value.record.assert_called()
    
    def test_null_check_decorator(self):
        """Test null check decorator."""
        with patch('core.assertion_framework.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            @null_check("result", "test_function")
            def test_function():
                return "valid_result"
            
            result = test_function()
            assert result == "valid_result"
    
    def test_timeout_check_decorator(self):
        """Test timeout check decorator."""
        with patch('core.assertion_framework.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            @timeout_check(max_duration_ms=1000)
            def test_function():
                time.sleep(0.01)  # 10ms
                return "success"
            
            result = test_function()
            assert result == "success"
    
    def test_ci_assertion_decorator(self):
        """Test CI assertion decorator."""
        with patch('core.assertion_bindings.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            @ci_assertion_decorator("unit_tests", "pipeline-123")
            def run_tests():
                return "tests_passed"
            
            result = run_tests()
            assert result == "tests_passed"


class TestMERIDSpecificAssertions:
    """Test MERID-specific assertion functions."""
    
    def test_assert_forecast_must_resolve(self):
        """Test forecast resolution assertion."""
        with patch('core.assertion_bindings.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            assertion_id = assert_forecast_must_resolve(
                market_id="market_123",
                forecast_time=time.time(),
                max_resolution_lag_hours=72,
                resolution_source="polymarket"
            )
            
            assert assertion_id.startswith("forecast_resolve_")
            mock_client.return_value.record.assert_called()
    
    def test_assert_risk_limits(self):
        """Test risk limits assertion."""
        with patch('core.assertion_bindings.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            # Within limits
            result = assert_risk_limits("BTC", 50000, 100000)
            assert result is True
            
            # Exceeds limits
            result = assert_risk_limits("BTC", 150000, 100000)
            assert result is False
    
    def test_assert_data_quality_probabilities(self):
        """Test data quality probabilities assertion."""
        with patch('core.assertion_bindings.get_assertion_client') as mock_client:
            mock_client.return_value.record.return_value = True
            
            # Valid probabilities
            probs = {"yes": 0.65, "no": 0.35}
            result = assert_data_quality_probabilities_sum_to_one("market_123", probs)
            assert result is True
            
            # Invalid probabilities
            probs = {"yes": 0.7, "no": 0.4}  # Sum = 1.1
            result = assert_data_quality_probabilities_sum_to_one("market_123", probs)
            assert result is False


class TestAssertionRegistryAPI:
    """Test assertion registry API endpoints."""
    
    def setup_method(self):
        """Set up test database."""
        # Use in-memory database for testing
        with patch('services.assertion_registry.get_db_connection') as mock_db:
            mock_conn = Mock()
            mock_db.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.fetchone.return_value = [0]  # No templates exist
            init_database()
    
    def test_register_assertion_endpoint(self):
        """Test assertion registration endpoint."""
        request = AssertionRegistration(
            template_id="core.nulls.value_must_not_be_null",
            subject={"key": "test"},
            parameters={"key": "test", "context": "test"},
            severity="major"
        )
        
        # Mock the database operations
        with patch('services.assertion_registry.get_db_connection') as mock_db:
            mock_conn = Mock()
            mock_db.return_value.__enter__.return_value = mock_conn
            
            # Mock template exists
            mock_conn.cursor.return_value.fetchone.return_value = {
                "template_id": "core.nulls.value_must_not_be_null",
                "version": 1,
                "severity_default": "major",
                "owner_team": "core"
            }
            
            # Mock successful insert
            mock_conn.cursor.return_value.lastrowid = 1
            
            from services.assertion_registry import register_assertion
            result = register_assertion(request)
            
            assert result["success"] is True
            assert "assertion_id" in result
    
    def test_update_assertion_endpoint(self):
        """Test assertion update endpoint."""
        request = AssertionUpdate(
            assertion_id="test-123",
            status="passed",
            details="Test completed successfully",
            timestamp=time.time()
        )
        
        with patch('services.assertion_registry.get_db_connection') as mock_db:
            mock_conn = Mock()
            mock_db.return_value.__enter__.return_value = mock_conn
            
            # Mock assertion exists
            mock_conn.cursor.return_value.fetchone.return_value = {
                "assertion_id": "test-123",
                "status": "pending"
            }
            
            from services.assertion_registry import update_assertion_status
            result = update_assertion_status(request)
            
            assert result["success"] is True
            assert result["status"] == "passed"
    
    def test_record_assertion_endpoint(self):
        """Test assertion record endpoint."""
        request = AssertionRecord(
            assertion_id="test-123",
            template_id="test.template",
            status="passed",
            parameters={"test": "value"},
            timestamp=time.time()
        )
        
        with patch('services.assertion_registry.get_db_connection') as mock_db:
            mock_conn = Mock()
            mock_db.return_value.__enter__.return_value = mock_conn
            
            # Mock assertion doesn't exist (will be created)
            mock_conn.cursor.return_value.fetchone.return_value = None
            
            # Mock template exists
            mock_conn.cursor.return_value.fetchone.side_effect = [
                None,  # Assertion doesn't exist
                {     # Template exists
                    "template_id": "test.template",
                    "version": 1,
                    "severity_default": "major",
                    "owner_team": "test"
                }
            ]
            
            from services.assertion_registry import record_assertion
            result = record_assertion(request)
            
            assert result["success"] is True
            assert result["action"] == "created"
    
    def test_list_assertions_endpoint(self):
        """Test assertion listing endpoint."""
        with patch('services.assertion_registry.get_db_connection') as mock_db:
            mock_conn = Mock()
            mock_db.return_value.__enter__.return_value = mock_conn
            
            # Mock assertion rows
            mock_rows = [
                {
                    "assertion_id": "test-1",
                    "template_id": "test.template",
                    "status": "passed",
                    "severity": "major",
                    "subject": '{"key": "value"}',
                    "parameters": '{"param": "value"}',
                    "extra": "{}"
                }
            ]
            mock_conn.cursor.return_value.fetchall.return_value = mock_rows
            
            from services.assertion_registry import list_assertions
            result = list_assertions(status="passed", limit=10)
            
            assert result["success"] is True
            assert result["count"] == 1
            assert len(result["assertions"]) == 1
            assert result["assertions"][0]["status"] == "passed"
    
    def test_get_template_endpoint(self):
        """Test template retrieval endpoint."""
        with patch('services.assertion_registry.get_db_connection') as mock_db:
            mock_conn = Mock()
            mock_db.return_value.__enter__.return_value = mock_conn
            
            # Mock template row
            mock_conn.cursor.return_value.fetchone.return_value = {
                "template_id": "test.template",
                "version": 1,
                "library_version": "1.0.0",
                "description": "Test template",
                "category": "ci",
                "severity_default": "major",
                "parameters": '[{"name": "param", "type": "string"}]',
                "tags": '{"env": ["test"]}',
                "owner_team": "test",
                "bindings": '{"python": {"module": "test"}}'
            }
            
            from services.assertion_registry import get_template
            result = get_template("test.template")
            
            assert result["success"] is True
            assert result["template"]["template_id"] == "test.template"
            assert isinstance(result["template"]["parameters"], list)
            assert isinstance(result["template"]["tags"], dict)
    
    def test_get_metrics_endpoint(self):
        """Test metrics retrieval endpoint."""
        with patch('services.assertion_registry.get_db_connection') as mock_db:
            mock_conn = Mock()
            mock_db.return_value.__enter__.return_value = mock_conn
            
            # Mock metric queries
            mock_conn.cursor.return_value.fetchall.side_effect = [
                [{"status": "passed", "count": 10}],  # status counts
                [{"template_id": "test.template", "description": "Test", "count": 5}],  # template counts
                [{"severity": "major", "count": 2}]  # severity breakdown
            ]
            
            from services.assertion_registry import get_assertion_metrics
            result = get_assertion_metrics()
            
            assert result["success"] is True
            assert "status_counts" in result
            assert "template_counts" in result
            assert "severity_breakdown" in result
            assert result["period_hours"] == 24


class TestIntegrationWithMERID:
    """Test integration with existing MERID components."""
    
    def test_integration_with_reality_auditor(self):
        """Test integration with Reality Auditor."""
        with patch('core.assertion_bindings.get_reality_auditor') as mock_auditor:
            mock_registry = Mock()
            mock_auditor.return_value.registry = mock_registry
            mock_registry.register_assertion.return_value = "reality-assertion-123"
            
            from core.assertion_bindings import integrate_with_reality_auditor
            integrate_with_reality_auditor()
            
            # Verify assertions were registered
            assert mock_registry.register_assertion.call_count == 2
    
    def test_prediction_agent_integration(self):
        """Test integration with prediction agents."""
        from core.assertion_bindings import integrate_with_prediction_agents
        
        wrapper = integrate_with_prediction_agents()
        
        # Test wrapper function
        with patch('core.assertion_bindings.assert_forecast_must_resolve') as mock_assert:
            mock_assert.return_value = "assertion-123"
            
            @wrapper
            def mock_forecast(market_id="test_123"):
                return {"prediction": 0.65}
            
            result = mock_forecast(market_id="test_123")
            
            assert result["prediction"] == 0.65
            assert result["assertion_id"] == "assertion-123"
            mock_assert.assert_called_once()


class TestAssertionTemplatesConfig:
    """Test assertion templates configuration loading."""
    
    def test_load_templates_from_yaml(self):
        """Test loading templates from YAML configuration."""
        # This would normally load from config/assertion_templates.yml
        # For testing, we'll use the CORE_TEMPLATES
        templates = load_templates_from_config(CORE_TEMPLATES)
        
        assert len(templates) >= 3  # At least the core templates
        
        # Verify template structure
        for template in templates:
            assert isinstance(template, AssertionTemplate)
            assert template.template_id
            assert template.version
            assert template.category
            assert template.severity_default
            assert isinstance(template.parameters, list)
            assert isinstance(template.tags, dict)
    
    def test_template_parameter_validation(self):
        """Test template parameter validation."""
        templates = load_templates_from_config(CORE_TEMPLATES)
        
        # Find null check template
        null_template = next((t for t in templates if t.template_id == "core.nulls.value_must_not_be_null"), None)
        assert null_template is not None
        
        # Verify required parameters
        param_names = [p["name"] for p in null_template.parameters]
        assert "key" in param_names
        assert "context" in param_names
        
        # Verify parameter types
        key_param = next(p for p in null_template.parameters if p["name"] == "key")
        assert key_param["type"] == "string"
        assert key_param["required"] is True


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
