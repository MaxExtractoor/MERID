"""
MERID Phase 0 Configuration and Feature Flags

Environment-based configuration and feature flag management for Phase 0 deployment.
"""

import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

from utils.logger import get_logger

logger = get_logger("phase0_config")

class Environment(Enum):
    """MERID environment types."""
    LOCAL = "local"
    STAGING = "staging"
    PROD = "prod"
    PRODUCTION = "production"

class AuditorMode(Enum):
    """Reality Auditor modes for testing."""
    NORMAL = "NORMAL"
    BLIND = "BLIND"

@dataclass
class Phase0Config:
    """Phase 0 configuration loaded from environment."""
    
    # Core environment
    env: Environment
    log_level: str
    db_url: str
    db_schema: Optional[str]
    
    # Phase 0 scope
    enabled: bool
    model_ids: List[str]
    
    # Feature flags
    brier_governance_enabled: bool
    feedback_loop_enabled: bool
    minimal_scope_enabled: bool
    
    # Phase 0 specific flags
    human_review_required: bool
    contract_enforced: bool
    conservative_limits: bool
    
    # Auditor/safety
    auditor_mode: AuditorMode
    dry_run: bool
    
    # Risk profile
    risk_profile: str  # conservative|standard|aggressive
    allow_auto_promotion: bool
    allow_auto_demotion: bool
    
    @classmethod
    def from_env(cls) -> "Phase0Config":
        """Load configuration from environment variables."""
        try:
            # Core environment - use Phase 0 specific env var, fallback to MERID_ENV, then local
            phase0_env = os.getenv("PHASE0_ENV") or os.getenv("MERID_ENV", "local")
            env = Environment(phase0_env.lower())
            log_level = os.getenv("MERID_LOG_LEVEL", "INFO")
            db_url = os.getenv("MERID_DB_URL", "sqlite:///merid.db")
            db_schema = os.getenv("MERID_DB_SCHEMA")
            
            # Phase 0 scope
            enabled = os.getenv("MERID_PHASE0_ENABLED", "false").lower() == "true"
            model_ids_str = os.getenv("MERID_PHASE0_MODEL_IDS", "crypto_prediction_agent_v1,arbitrage_analyst_v2")
            model_ids = [id.strip() for id in model_ids_str.split(",") if id.strip()]
            
            # Feature flags
            brier_governance_enabled = os.getenv("MERID_FEATURE_BRIER_GOVERNANCE", "false").lower() == "true"
            feedback_loop_enabled = os.getenv("MERID_FEATURE_FEEDBACK_LOOP", "false").lower() == "true"
            minimal_scope_enabled = os.getenv("MERID_FEATURE_MINIMAL_SCOPE", "false").lower() == "true"
            
            # Phase 0 specific flags
            human_review_required = os.getenv("PHASE0_HUMAN_REVIEW_REQUIRED", "true").lower() == "true"
            contract_enforced = os.getenv("MERID_PHASE0_CONTRACT_ENFORCE", "true").lower() == "true"
            conservative_limits = os.getenv("MERID_PHASE0_FORCE_CONSERVATIVE_LIMITS", "false").lower() == "true"
            
            # Auditor/safety
            auditor_mode = AuditorMode(os.getenv("MERID_AUDITOR_MODE", "NORMAL"))
            dry_run = os.getenv("GOVERNANCE_DRY_RUN", "false").lower() == "true"
            
            # Risk profile
            risk_profile = os.getenv("GOVERNANCE_RISK_PROFILE", "conservative")
            allow_auto_promotion = os.getenv("GOVERNANCE_ALLOW_AUTO_PROMOTION", "false").lower() == "true"
            allow_auto_demotion = os.getenv("GOVERNANCE_ALLOW_AUTO_DEMOTION", "false").lower() == "true"
            
            config = cls(
                env=env,
                log_level=log_level,
                db_url=db_url,
                db_schema=db_schema,
                enabled=enabled,
                model_ids=model_ids,
                brier_governance_enabled=brier_governance_enabled,
                feedback_loop_enabled=feedback_loop_enabled,
                minimal_scope_enabled=minimal_scope_enabled,
                human_review_required=human_review_required,
                contract_enforced=contract_enforced,
                conservative_limits=conservative_limits,
                auditor_mode=auditor_mode,
                dry_run=dry_run,
                risk_profile=risk_profile,
                allow_auto_promotion=allow_auto_promotion,
                allow_auto_demotion=allow_auto_demotion
            )
            
            logger.info(f"Phase 0 config loaded: env={env.value}, enabled={enabled}, models={len(model_ids)}")
            return config
            
        except Exception as e:
            logger.error(f"Failed to load Phase 0 config: {e}")
            # Return safe defaults
            return cls(
                env=Environment.LOCAL,
                log_level="INFO",
                db_url="sqlite:///merid.db",
                db_schema=None,
                enabled=False,
                model_ids=[],
                brier_governance_enabled=False,
                feedback_loop_enabled=False,
                minimal_scope_enabled=False,
                human_review_required=True,
                contract_enforced=True,
                conservative_limits=False,
                auditor_mode=AuditorMode.NORMAL,
                dry_run=True,
                risk_profile="conservative",
                allow_auto_promotion=False,
                allow_auto_demotion=False
            )
    
    def is_phase0_active(self) -> bool:
        """Check if Phase 0 is active and all required flags are enabled."""
        return (
            self.enabled and
            self.brier_governance_enabled and
            self.minimal_scope_enabled
        )
    
    def get_risk_limits_multiplier(self) -> float:
        """Get risk limits multiplier based on configuration."""
        if self.conservative_limits:
            return 0.25  # Very conservative for testing
        elif self.risk_profile == "conservative":
            return 0.5
        elif self.risk_profile == "standard":
            return 0.75
        elif self.risk_profile == "aggressive":
            return 1.0
        else:
            return 0.5  # Default to conservative
    
    def can_auto_execute(self, action: str) -> bool:
        """Check if auto-execution is allowed for a given action."""
        if self.dry_run:
            return False
        
        if action == "promote":
            return self.allow_auto_promotion
        elif action == "demote":
            return self.allow_auto_demotion
        else:
            return False
    
    def should_enforce_contracts(self) -> bool:
        """Check if contract tests should be enforced or just logged."""
        return self.contract_enforced
    
    def get_allowed_tiers(self) -> List[str]:
        """Get allowed tiers based on Phase 0 configuration."""
        if self.conservative_limits:
            return ["tier_3", "tier_4"]  # Very conservative
        elif self.is_phase0_active():
            return ["tier_2", "tier_3", "tier_4"]  # Phase 0: no Tier 1
        else:
            return ["tier_1", "tier_2", "tier_3", "tier_4"]  # Full production
    
    def validate_config(self) -> Dict[str, Any]:
        """Validate configuration and return any issues."""
        issues = []
        
        # Check required flags for Phase 0
        if self.enabled:
            if not self.brier_governance_enabled:
                issues.append("Phase 0 enabled but Brier governance feature flag is disabled")
            if not self.minimal_scope_enabled:
                issues.append("Phase 0 enabled but minimal scope feature flag is disabled")
            if not self.model_ids:
                issues.append("Phase 0 enabled but no model IDs configured")
        
        # Check database configuration
        if not self.db_url:
            issues.append("No database URL configured")
        
        # Check risk profile
        valid_profiles = ["conservative", "standard", "aggressive"]
        if self.risk_profile not in valid_profiles:
            issues.append(f"Invalid risk profile: {self.risk_profile}. Valid: {valid_profiles}")
        
        # Check auditor mode
        if self.env == Environment.PROD and self.auditor_mode == AuditorMode.BLIND:
            issues.append("Auditor BLIND mode not allowed in production")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "config_summary": {
                "env": self.env.value,
                "phase0_enabled": self.enabled,
                "model_count": len(self.model_ids),
                "risk_profile": self.risk_profile,
                "dry_run": self.dry_run
            }
        }

# Global configuration instance
_phase0_config: Optional[Phase0Config] = None

def get_phase0_config() -> Phase0Config:
    """Get the global Phase 0 configuration instance."""
    global _phase0_config
    if _phase0_config is None:
        _phase0_config = Phase0Config.from_env()
    return _phase0_config

def reload_phase0_config() -> Phase0Config:
    """Reload Phase 0 configuration from environment."""
    global _phase0_config
    _phase0_config = Phase0Config.from_env()
    return _phase0_config
