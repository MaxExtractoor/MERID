"""Risk-core tests for data access control policies."""

from __future__ import annotations

import pytest

from core.data_permissions import (
    DataAccessController,
    DataAccessPolicy,
    DataClassification,
)


pytestmark = pytest.mark.risk_core


def _controller() -> DataAccessController:
    ctrl = DataAccessController()
    ctrl.register_policy(
        DataAccessPolicy(
            dataset="orders",
            classification=DataClassification.INTERNAL,
            allowed_roles={"risk", "ops"},
        )
    )
    ctrl.register_policy(
        DataAccessPolicy(
            dataset="vault",
            classification=DataClassification.SECRET,
            allowed_roles={"risk"},
            mask_function=lambda data: "***masked***",
        )
    )
    return ctrl


def test_acl_allows_whitelisted_role() -> None:
    ctrl = _controller()
    data = ctrl.access("orders", role="risk", data={"foo": 1})
    assert data == {"foo": 1}


def test_acl_denies_unauthorized_role() -> None:
    ctrl = _controller()
    with pytest.raises(PermissionError):
        ctrl.access("orders", role="guest", data={"foo": 1})


def test_secret_data_masked() -> None:
    ctrl = _controller()
    masked = ctrl.access("vault", role="risk", data="sensitive_secret")
    assert masked == "***masked***"

    # Secret dataset with no mask would return None, ensure allowed roles still enforced
    ctrl.register_policy(
        DataAccessPolicy(
            dataset="vault_nomask",
            classification=DataClassification.SECRET,
            allowed_roles={"risk"},
        )
    )
    assert ctrl.access("vault_nomask", role="risk", data="secret") is None
