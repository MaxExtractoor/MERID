"""MERID Runtime Profiles — Configuration profiles for different operational modes.

Profiles:
  - default: Standard MERID operation
  - kalshi_only: Kalshi-focused with legacy components suppressed
  - kalshi_swarm: Full swarm with social advisory + incentives (Loop 5)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class ProfileConfig:
    """Configuration for a MERID runtime profile (ENV-DRIVEN)."""
    name: str
    description: str
    
    # Component enablement
    enabled_routers: Set[str] = field(default_factory=set)
    disabled_routers: Set[str] = field(default_factory=set)
    
    # Social advisory settings (ENV-DRIVEN)
    social_advisory_enabled: bool = field(default_factory=lambda: os.getenv("MERID_SOCIAL_ADVISORY_ENABLED", "false").lower() == "true")
    social_advisory_weights: Dict[str, float] = field(default_factory=dict)
    social_advisory_max_nudge: float = field(default_factory=lambda: float(os.getenv("MERID_SOCIAL_ADVISORY_MAX_NUDGE", "0.1")))
    
    # Incentive ledger settings (ENV-DRIVEN)
    incentive_ledger_enabled: bool = field(default_factory=lambda: os.getenv("MERID_INCENTIVE_LEDGER_ENABLED", "false").lower() == "true")
    incentives_live: bool = field(default_factory=lambda: os.getenv("MERID_INCENTIVES_LIVE", "false").lower() == "true")  # If False, feedback is dry-run only
    
    # Feedback scheduler settings (ENV-DRIVEN)
    feedback_scheduler_enabled: bool = field(default_factory=lambda: os.getenv("MERID_FEEDBACK_SCHED_ENABLED", "false").lower() == "true")
    feedback_scheduler_dry_run: bool = field(default_factory=lambda: os.getenv("MERID_FEEDBACK_SCHED_DRY_RUN", "true").lower() == "true")
    feedback_scheduler_interval_rounds: int = field(default_factory=lambda: int(os.getenv("MERID_FEEDBACK_SCHED_ROUNDS", "10")))
    feedback_scheduler_interval_seconds: float = field(default_factory=lambda: float(os.getenv("MERID_FEEDBACK_SCHED_SEC", "300.0")))
    
    # Mode restrictions (ENV-DRIVEN)
    allowed_modes: List[str] = field(default_factory=lambda: os.getenv("MERID_ALLOWED_MODES", "mock,paper,live").split(","))
    
    # Safety flags (ENV-DRIVEN)
    allow_live_trading: bool = field(default_factory=lambda: os.getenv("MERID_ALLOW_LIVE_TRADING", "true").lower() == "true")
    replay_isolated: bool = field(default_factory=lambda: os.getenv("MERID_REPLAY_ISOLATED", "false").lower() == "true")


# Define profile configurations
PROFILES: Dict[str, ProfileConfig] = {
    "default": ProfileConfig(
        name="default",
        description="Standard MERID operation with all features",
        allowed_modes=["mock", "paper", "live"],
        allow_live_trading=True,
    ),
    
    "kalshi_only": ProfileConfig(
        name="kalshi_only",
        description="Kalshi-focused with legacy components suppressed",
        disabled_routers={
            "prediction", "betting", "mining", "wallet", "treasury",
            "rewards", "cognitive", "devswarm", "simulation", "neo4j",
            "x_bot", "moat",
        },
        allowed_modes=["mock", "paper", "live"],
        allow_live_trading=True,
    ),
    
    "kalshi_crypto_15m_v2": ProfileConfig(
        name="kalshi_crypto_15m_v2",
        description="Production 15-minute Kalshi crypto trading stack (BTC/ETH/SOL/XRP/DOGE). Uses web.main_15m_lean entrypoint with Kalshi15mLoop.",
        disabled_routers={
            "prediction", "betting", "mining", "wallet", "treasury",
            "rewards", "cognitive", "devswarm", "simulation", "neo4j",
            "x_bot", "moat",
        },
        allowed_modes=["live"],  # Live trading only for production 15m stack
        allow_live_trading=True,
    ),
    
    "kalshi_swarm": ProfileConfig(
        name="kalshi_swarm",
        description="Full Kalshi swarm with social advisory + incentives (Loop 5)",
        # Enable social advisory with conservative defaults
        social_advisory_enabled=True,
        social_advisory_weights={
            "twitter": 0.1,
            "reddit": 0.1,
            "newsapi": 0.05,
        },
        social_advisory_max_nudge=0.05,  # Small nudges only (5%)
        
        # Enable incentive ledger
        incentive_ledger_enabled=True,
        incentives_live=False,  # Dry-run by default for safety
        
        # Feedback scheduler settings
        feedback_scheduler_enabled=True,
        feedback_scheduler_dry_run=True,  # Log only, don't apply
        feedback_scheduler_interval_rounds=10,
        feedback_scheduler_interval_seconds=300.0,  # 5 minutes
        
        # Mode restrictions - mock/paper only for now
        allowed_modes=["mock", "paper"],
        allow_live_trading=False,
        replay_isolated=True,
        
        # Suppress legacy components
        disabled_routers={
            "prediction", "betting", "mining", "wallet", "treasury",
            "rewards", "cognitive", "devswarm", "simulation", "neo4j",
            "x_bot", "moat",
        },
    ),
}


class ProfileManager:
    """Manages runtime profile configuration."""
    
    def __init__(self):
        self._current_profile: Optional[str] = None
        self._config: Optional[ProfileConfig] = None
    
    def load_profile(self, profile_name: Optional[str] = None) -> ProfileConfig:
        """Load a profile from env var or explicit name."""
        # Priority: explicit name > env var > default
        name = profile_name or os.getenv("MERID_PROFILE", "default")
        
        if name not in PROFILES:
            raise ValueError(f"Unknown profile: {name}. Available: {list(PROFILES.keys())}")
        
        self._current_profile = name
        self._config = PROFILES[name]
        return self._config
    
    def get_current(self) -> Optional[ProfileConfig]:
        """Get currently loaded profile config."""
        return self._config
    
    def get_current_name(self) -> Optional[str]:
        """Get currently loaded profile name."""
        return self._current_profile
    
    def is_router_enabled(self, router_name: str) -> bool:
        """Check if a router should be enabled in current profile."""
        if self._config is None:
            return True
        
        # Explicitly enabled takes precedence
        if router_name in self._config.enabled_routers:
            return True
        
        # Explicitly disabled
        if router_name in self._config.disabled_routers:
            return False
        
        return True
    
    def is_mode_allowed(self, mode: str) -> bool:
        """Check if a mode is allowed in current profile."""
        if self._config is None:
            return True
        return mode in self._config.allowed_modes
    
    def can_trade_live(self) -> bool:
        """Check if live trading is allowed."""
        if self._config is None:
            return True
        return self._config.allow_live_trading
    
    def set_incentives_live(self, live: bool) -> None:
        """Enable/disable live incentives (requires explicit opt-in)."""
        if self._config is None:
            raise RuntimeError("No profile loaded")
        
        # Additional safety: require ALLOW_LIVE_INCENTIVES env var for live mode
        if live and not os.getenv("ALLOW_LIVE_INCENTIVES"):
            raise PermissionError(
                "Live incentives require ALLOW_LIVE_INCENTIVES=1 environment variable"
            )
        
        self._config.incentives_live = live
        self._config.feedback_scheduler_dry_run = not live
    
    def get_status(self) -> Dict[str, Any]:
        """Get current profile status for health endpoints."""
        if self._config is None:
            return {"profile": None, "loaded": False}
        
        return {
            "profile": self._current_profile,
            "loaded": True,
            "description": self._config.description,
            "social_advisory_enabled": self._config.social_advisory_enabled,
            "incentive_ledger_enabled": self._config.incentive_ledger_enabled,
            "incentives_live": self._config.incentives_live,
            "feedback_scheduler_enabled": self._config.feedback_scheduler_enabled,
            "feedback_scheduler_dry_run": self._config.feedback_scheduler_dry_run,
            "allowed_modes": self._config.allowed_modes,
            "allow_live_trading": self._config.allow_live_trading,
        }


# Singleton instance
_profile_manager: Optional[ProfileManager] = None


def get_profile_manager() -> ProfileManager:
    """Get or create the global profile manager."""
    global _profile_manager
    if _profile_manager is None:
        _profile_manager = ProfileManager()
    return _profile_manager


def load_profile(profile_name: Optional[str] = None) -> ProfileConfig:
    """Convenience function to load a profile."""
    return get_profile_manager().load_profile(profile_name)


def get_current_profile() -> Optional[ProfileConfig]:
    """Get currently loaded profile."""
    return get_profile_manager().get_current()
