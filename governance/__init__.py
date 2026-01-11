"""
MERID Governance Module

Constitutional invariants, authority boundaries, and system oversight.
"""

from governance.constitutional import (
    ConstitutionalInvariants,
    InvariantSeverity,
    InvariantViolation,
    get_constitutional,
)
from governance.authority_boundary import (
    AuthorityBoundaryEnforcer,
    MeridSystem,
    ActionType,
    BoundaryViolation,
    get_authority_enforcer,
)
from governance.time_decay import (
    TimeDecayManager,
    DecayType,
    TimedAuthority,
    get_time_decay_manager,
)

__all__ = [
    "ConstitutionalInvariants",
    "InvariantSeverity",
    "InvariantViolation",
    "get_constitutional",
    "AuthorityBoundaryEnforcer",
    "MeridSystem",
    "ActionType",
    "BoundaryViolation",
    "get_authority_enforcer",
    "TimeDecayManager",
    "DecayType",
    "TimedAuthority",
    "get_time_decay_manager",
]
