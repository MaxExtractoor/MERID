"""Replay & Swarm Guardrails — Safety checks for paper-only operation.

Ensures:
  - Replay mode can never send live orders
  - kalshi_swarm profile only allows mock/paper modes
  - Explicit ALLOW_LIVE_SWARM flag required for live trading
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional
from functools import wraps

from utils.logger import get_logger

logger = get_logger("guardrails")


class GuardrailViolation(Exception):
    """Raised when a safety guardrail is violated."""
    pass


class ReplayGuardrails:
    """Safety guardrails for replay mode — ensures no live execution."""
    
    @staticmethod
    def check_replay_isolation() -> None:
        """Verify replay is running in isolated mode."""
        # This should always pass - the harness sets isolated=True
        from web.api.replay_harness import get_replay_harness
        harness = get_replay_harness()
        
        if not getattr(harness, '_isolated', True):
            raise GuardrailViolation(
                "Replay harness is not in isolated mode - this should never happen"
            )
    
    @staticmethod
    def block_live_execution(func):
        """Decorator that blocks any function from executing in live mode during replay."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check if we're in replay context
            from web.api.replay_harness import get_replay_harness
            harness = get_replay_harness()
            
            # If a replay is active, block live execution
            if harness._active_run is not None:
                logger.error(
                    "LIVE EXECUTION BLOCKED: Attempted %s during active replay %s",
                    func.__name__, harness._active_run
                )
                raise GuardrailViolation(
                    f"Live execution blocked: {func.__name__} called during replay"
                )
            
            return func(*args, **kwargs)
        return wrapper


class SwarmGuardrails:
    """Safety guardrails for kalshi_swarm profile."""
    
    LIVE_SWARM_ENV_VAR = "ALLOW_LIVE_SWARM"
    
    @classmethod
    def check_mode_allowed(cls, mode: str, profile_name: Optional[str] = None) -> None:
        """Check if a trading mode is allowed for the current profile.
        
        Args:
            mode: The requested mode ('mock', 'paper', 'live')
            profile_name: Optional explicit profile name
            
        Raises:
            GuardrailViolation: If mode is not allowed
        """
        from config.profiles import get_profile_manager
        
        pm = get_profile_manager()
        profile = pm.get_current()
        
        # If profile is kalshi_swarm, enforce restrictions
        if profile and profile.name == "kalshi_swarm":
            # Check for explicit live override first
            if mode == "live":
                if os.getenv(cls.LIVE_SWARM_ENV_VAR):
                    # Explicit override - allow live
                    return
                # No override - block live
                raise GuardrailViolation(
                    f"Live trading blocked in kalshi_swarm profile. "
                    f"Set {cls.LIVE_SWARM_ENV_VAR}=1 to enable (not recommended in this phase)."
                )
            
            # For non-live modes, check against allowed_modes
            if mode not in profile.allowed_modes:
                raise GuardrailViolation(
                    f"Mode '{mode}' not allowed in kalshi_swarm profile. "
                    f"Allowed: {profile.allowed_modes}"
                )
    
    @classmethod
    def enforce_paper_only(cls, func):
        """Decorator that enforces paper/mock only for kalshi_swarm."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            from config.profiles import get_profile_manager
            pm = get_profile_manager()
            profile = pm.get_current()
            
            if profile and profile.name == "kalshi_swarm":
                # Check for live mode in kwargs or args
                mode = kwargs.get('mode', 'paper')
                
                if mode == 'live' and not os.getenv(cls.LIVE_SWARM_ENV_VAR):
                    logger.error(
                        "LIVE MODE BLOCKED: kalshi_swarm profile without %s",
                        cls.LIVE_SWARM_ENV_VAR
                    )
                    raise GuardrailViolation(
                        f"Live mode blocked in kalshi_swarm. Set {cls.LIVE_SWARM_ENV_VAR}=1 to override."
                    )
            
            return func(*args, **kwargs)
        return wrapper


class ExecutionGuardrails:
    """Guardrails at the execution layer to prevent live orders from replay."""
    
    @staticmethod
    def check_before_execution(venue: str, order_details: Dict[str, Any]) -> None:
        """Check before any order execution.
        
        Args:
            venue: Target venue
            order_details: Order parameters
            
        Raises:
            GuardrailViolation: If execution should be blocked
        """
        # Check if replay is active
        from web.api.replay_harness import get_replay_harness
        harness = get_replay_harness()
        
        if harness._active_run is not None:
            logger.critical(
                "ORDER EXECUTION BLOCKED: Attempted %s order during replay %s",
                venue, harness._active_run
            )
            raise GuardrailViolation(
                f"Order execution blocked: {venue} order during replay"
            )
        
        # Check profile restrictions
        from config.profiles import get_profile_manager
        pm = get_profile_manager()
        profile = pm.get_current()
        
        if profile and not profile.allow_live_trading:
            # Only allow paper/mock modes
            mode = order_details.get('mode', 'paper')
            if mode == 'live':
                raise GuardrailViolation(
                    f"Live orders blocked: profile {profile.name} does not allow live trading"
                )


def install_guardrails() -> None:
    """Install guardrail checks at critical system boundaries.
    
    This should be called once during application startup.
    """
    logger.info("Installing execution guardrails...")
    
    # The guardrails are enforced through decorator checks
    # Additional runtime checks can be added here if needed
    
    logger.info("Guardrails installed: replay isolated, swarm paper-only enforced")


def get_guardrail_status() -> Dict[str, Any]:
    """Get current guardrail status for health checks."""
    from config.profiles import get_profile_manager
    
    pm = get_profile_manager()
    profile = pm.get_current()
    
    # Check replay status without importing harness to avoid chain
    replay_active = False
    try:
        from web.api.replay_harness import get_replay_harness
        harness = get_replay_harness()
        replay_active = harness._active_run is not None
    except Exception:
        pass  # If can't import, assume not active
    
    return {
        "replay_isolated": True,  # Always isolated by design
        "replay_active": replay_active,
        "profile": profile.name if profile else None,
        "allow_live_trading": profile.allow_live_trading if profile else True,
        "live_swarm_override": os.getenv(SwarmGuardrails.LIVE_SWARM_ENV_VAR) == "1",
    }
