"""
MERID-GOV Module

Governance, Oversight, Defense - "Are we allowed to act, and should we trust ourselves?"

Phase 2 of Master Build Directive - GOVERNANCE & DEFENSE (BLOCKING)

MERID-GOV outranks all other systems.

Components:
- Constitutional Invariants: Unoverrideable system rules
- Authority Boundaries: System isolation enforcement
- Time Decay: Authority expiration and renewal
- Adversarial Intelligence: Behavioral randomization, honeytokens, deception detection
- Model Risk Management: Versioning, validation, kill authority
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
from governance.adversarial import (
    AdversarialIntelligenceEngine,
    AdversaryType,
    ThreatLevel,
    DeceptionType,
    AdversaryFingerprint,
    Honeytoken,
    DeceptionEvent,
    BehavioralRandomizer,
    HoneytokenManager,
    DeceptionDetector,
    AdversaryTracker,
    get_adversarial_engine,
)
from governance.model_risk import (
    ModelRiskManager,
    ModelStatus,
    RiskLevel,
    ValidationResult,
    ModelVersion,
    ModelRiskProfile,
    ValidationReport,
    get_model_risk_manager,
)
from governance.intent_review import (
    IntentReviewEngine,
    ReviewDecision,
    RejectionReason,
    ReviewCriteria,
    ReviewResult,
    get_intent_review_engine,
)

__all__ = [
    # Constitutional
    "ConstitutionalInvariants",
    "InvariantSeverity",
    "InvariantViolation",
    "get_constitutional",
    # Authority Boundary
    "AuthorityBoundaryEnforcer",
    "MeridSystem",
    "ActionType",
    "BoundaryViolation",
    "get_authority_enforcer",
    # Time Decay
    "TimeDecayManager",
    "DecayType",
    "TimedAuthority",
    "get_time_decay_manager",
    # Adversarial Intelligence
    "AdversarialIntelligenceEngine",
    "AdversaryType",
    "ThreatLevel",
    "DeceptionType",
    "AdversaryFingerprint",
    "Honeytoken",
    "DeceptionEvent",
    "BehavioralRandomizer",
    "HoneytokenManager",
    "DeceptionDetector",
    "AdversaryTracker",
    "get_adversarial_engine",
    # Model Risk Management
    "ModelRiskManager",
    "ModelStatus",
    "RiskLevel",
    "ValidationResult",
    "ModelVersion",
    "ModelRiskProfile",
    "ValidationReport",
    "get_model_risk_manager",
    # Intent Review
    "IntentReviewEngine",
    "ReviewDecision",
    "RejectionReason",
    "ReviewCriteria",
    "ReviewResult",
    "get_intent_review_engine",
]
