"""Comprehensive tests for core/data_permissions.py - Coverage improvement."""

import pytest

from core.data_permissions import (
    DataClassification, DataAccessPolicy, DataAccessController,
    get_data_access_controller
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestDataClassification:
    """Test DataClassification enum."""

    def test_public(self):
        assert DataClassification.PUBLIC.value == "public"

    def test_internal(self):
        assert DataClassification.INTERNAL.value == "internal"

    def test_sensitive(self):
        assert DataClassification.SENSITIVE.value == "sensitive"

    def test_secret(self):
        assert DataClassification.SECRET.value == "secret"


# =============================================================================
# DataAccessPolicy Tests
# =============================================================================

class TestDataAccessPolicy:
    """Test DataAccessPolicy dataclass."""

    def test_creation(self):
        policy = DataAccessPolicy(
            dataset="test_data",
            classification=DataClassification.INTERNAL,
            allowed_roles={"admin", "user"}
        )
        assert policy.dataset == "test_data"
        assert policy.classification == DataClassification.INTERNAL

    def test_with_mask_function(self):
        def mask(data):
            return "***"
        
        policy = DataAccessPolicy(
            dataset="secrets",
            classification=DataClassification.SECRET,
            allowed_roles={"admin"},
            mask_function=mask
        )
        assert policy.mask_function is not None


# =============================================================================
# DataAccessController Tests
# =============================================================================

@pytest.fixture
def controller():
    """Create DataAccessController."""
    return DataAccessController()


class TestDataAccessControllerInit:
    """Test DataAccessController initialization."""

    def test_init(self, controller):
        assert controller._policies == {}


class TestRegisterPolicy:
    """Test register_policy method."""

    def test_registers_policy(self, controller):
        policy = DataAccessPolicy(
            dataset="users",
            classification=DataClassification.INTERNAL,
            allowed_roles={"admin"}
        )
        
        controller.register_policy(policy)
        
        assert "users" in controller._policies


class TestAccess:
    """Test access method."""

    def test_access_public_data(self, controller):
        policy = DataAccessPolicy(
            dataset="public_data",
            classification=DataClassification.PUBLIC,
            allowed_roles={"user"}
        )
        controller.register_policy(policy)
        
        result = controller.access("public_data", "user", {"key": "value"})
        
        assert result == {"key": "value"}

    def test_access_internal_data(self, controller):
        policy = DataAccessPolicy(
            dataset="internal_data",
            classification=DataClassification.INTERNAL,
            allowed_roles={"employee"}
        )
        controller.register_policy(policy)
        
        result = controller.access("internal_data", "employee", {"info": "data"})
        
        assert result == {"info": "data"}

    def test_access_sensitive_with_mask(self, controller):
        def mask(data):
            return {"masked": True}
        
        policy = DataAccessPolicy(
            dataset="sensitive_data",
            classification=DataClassification.SENSITIVE,
            allowed_roles={"analyst"},
            mask_function=mask
        )
        controller.register_policy(policy)
        
        result = controller.access("sensitive_data", "analyst", {"secret": "123"})
        
        assert result == {"masked": True}

    def test_access_secret_with_mask(self, controller):
        def mask(data):
            return "***redacted***"
        
        policy = DataAccessPolicy(
            dataset="secret_data",
            classification=DataClassification.SECRET,
            allowed_roles={"admin"},
            mask_function=mask
        )
        controller.register_policy(policy)
        
        result = controller.access("secret_data", "admin", {"password": "secret"})
        
        assert result == "***redacted***"

    def test_access_secret_without_mask(self, controller):
        policy = DataAccessPolicy(
            dataset="top_secret",
            classification=DataClassification.SECRET,
            allowed_roles={"superadmin"}
        )
        controller.register_policy(policy)
        
        result = controller.access("top_secret", "superadmin", {"data": "value"})
        
        assert result is None

    def test_access_denied_no_policy(self, controller):
        with pytest.raises(PermissionError, match="No access policy"):
            controller.access("unknown_dataset", "user", {})

    def test_access_denied_wrong_role(self, controller):
        policy = DataAccessPolicy(
            dataset="restricted",
            classification=DataClassification.INTERNAL,
            allowed_roles={"admin"}
        )
        controller.register_policy(policy)
        
        with pytest.raises(PermissionError, match="not allowed"):
            controller.access("restricted", "guest", {})


# =============================================================================
# Singleton Tests
# =============================================================================

class TestGetDataAccessController:
    """Test get_data_access_controller singleton."""

    def test_returns_controller(self):
        import core.data_permissions as module
        module._controller = None
        
        controller = get_data_access_controller()
        
        assert isinstance(controller, DataAccessController)

    def test_returns_same_instance(self):
        import core.data_permissions as module
        module._controller = None
        
        controller1 = get_data_access_controller()
        controller2 = get_data_access_controller()
        
        assert controller1 is controller2
