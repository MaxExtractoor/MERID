"""
Data classification and permission enforcement for MERID.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

from utils.logger import get_logger

logger = get_logger("core.data_permissions")


class DataClassification(str, Enum):
    """Levels of data sensitivity."""

    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    SECRET = "secret"


@dataclass
class DataAccessPolicy:
    """Policy describing who can access a dataset."""

    dataset: str
    classification: DataClassification
    allowed_roles: set[str]
    mask_function: Optional[Callable[[Any], Any]] = None


class DataAccessController:
    """Central controller enforcing data permissions."""

    def __init__(self) -> None:
        self._policies: Dict[str, DataAccessPolicy] = {}

    def register_policy(self, policy: DataAccessPolicy) -> None:
        self._policies[policy.dataset] = policy
        logger.info(
            "Data policy registered dataset=%s classification=%s roles=%s",
            policy.dataset,
            policy.classification.value,
            sorted(policy.allowed_roles),
        )

    def access(self, dataset: str, role: str, data: Any) -> Any:
        policy = self._policies.get(dataset)
        if not policy:
            logger.warning("No policy for dataset=%s, denying access", dataset)
            raise PermissionError(f"No access policy for dataset {dataset}")
        if role not in policy.allowed_roles:
            logger.error("Role %s denied for dataset %s", role, dataset)
            raise PermissionError(f"Role {role} not allowed for dataset {dataset}")
        if policy.classification == DataClassification.SECRET and policy.mask_function:
            return policy.mask_function(data)
        if policy.classification == DataClassification.SECRET:
            return None
        if policy.classification == DataClassification.SENSITIVE and policy.mask_function:
            return policy.mask_function(data)
        return data


_controller: Optional[DataAccessController] = None


def get_data_access_controller() -> DataAccessController:
    global _controller
    if _controller is None:
        _controller = DataAccessController()
    return _controller
