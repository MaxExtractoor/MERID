"""Unified Drawdown Configuration — Single source of truth for all drawdown thresholds.

This module consolidates drawdown settings from:
- KalshiRiskEngine (was 20%/10%)
- CycleDrawdown (was 3-7% variable)
- HedgeConfig (was 40% unused)

Into a unified, hierarchical threshold system.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.risk.drawdown_config")


@dataclass(frozen=True)
class UnifiedDrawdownConfig:
    """Unified drawdown thresholds used across all risk systems.
    
    Thresholds are hierarchical and must satisfy:
        warning < hedge_active < scalp_halt < full_halt
    
    All values are decimal (e.g., 0.05 = 5%).
    
    NOTE: Now reads from core.settings for unified single source of truth.
    """
    
    # Hierarchical thresholds - read from core.settings (single source of truth)
    warning_pct: float = field(default_factory=lambda: _get_warning_pct())
    hedge_active_pct: float = field(default_factory=lambda: _get_hedge_active_pct())
    scalp_halt_pct: float = field(default_factory=lambda: _get_scalp_halt_pct())
    full_halt_pct: float = field(default_factory=lambda: _get_full_halt_pct())
    
    # Recovery thresholds (must recover below these to transition back)
    recovery_hedge_to_scalp_pct: float = field(default_factory=lambda: _get_recovery_hedge_pct())
    recovery_halt_to_hedge_pct: float = field(default_factory=lambda: _get_recovery_halt_pct())
    
    # Validation and methods
    def __post_init__(self):
        # Ensure proper ordering
        thresholds = [
            ("warning", self.warning_pct),
            ("hedge_active", self.hedge_active_pct),
            ("scalp_halt", self.scalp_halt_pct),
            ("full_halt", self.full_halt_pct),
        ]
        
        for i in range(len(thresholds) - 1):
            name_current, val_current = thresholds[i]
            name_next, val_next = thresholds[i + 1]
            if val_current >= val_next:
                raise ValueError(
                    f"Drawdown threshold ordering violated: "
                    f"{name_current} ({val_current}) >= {name_next} ({val_next})"
                )
        
        # Recovery thresholds must be below their corresponding forward thresholds
        if self.recovery_hedge_to_scalp_pct >= self.hedge_active_pct:
            raise ValueError(
                f"recovery_hedge_to_scalp ({self.recovery_hedge_to_scalp_pct}) "
                f"must be < hedge_active ({self.hedge_active_pct})"
            )
        
        if self.recovery_halt_to_hedge_pct >= self.scalp_halt_pct:
            raise ValueError(
                f"recovery_halt_to_hedge ({self.recovery_halt_to_hedge_pct}) "
                f"must be < scalp_halt ({self.scalp_halt_pct})"
            )
    
    def get_threshold_for_level(self, level: str) -> float:
        """Get threshold by level name."""
        levels = {
            "warning": self.warning_pct,
            "hedge_active": self.hedge_active_pct,
            "scalp_halt": self.scalp_halt_pct,
            "full_halt": self.full_halt_pct,
        }
        if level not in levels:
            raise ValueError(f"Unknown level: {level}. Valid: {list(levels.keys())}")
        return levels[level]
    
    def evaluate_drawdown(self, drawdown_pct: float) -> str:
        """Evaluate drawdown level.
        
        Returns one of: "normal", "warning", "hedge_active", "scalp_halt", "full_halt"
        """
        if drawdown_pct >= self.full_halt_pct:
            return "full_halt"
        elif drawdown_pct >= self.scalp_halt_pct:
            return "scalp_halt"
        elif drawdown_pct >= self.hedge_active_pct:
            return "hedge_active"
        elif drawdown_pct >= self.warning_pct:
            return "warning"
        else:
            return "normal"
    
    def to_dict(self) -> dict:
        """Serialize configuration."""
        return {
            "warning_pct": self.warning_pct,
            "hedge_active_pct": self.hedge_active_pct,
            "scalp_halt_pct": self.scalp_halt_pct,
            "full_halt_pct": self.full_halt_pct,
            "recovery_hedge_to_scalp_pct": self.recovery_hedge_to_scalp_pct,
            "recovery_halt_to_hedge_pct": self.recovery_halt_to_hedge_pct,
        }


def _get_warning_pct() -> float:
    """Get warning threshold from core.settings or env var."""
    try:
        from core.settings import DRAWDOWN_HALT_PCT
        # Warning is 1/3 of halt (10% halt → 3% warning)
        return DRAWDOWN_HALT_PCT / 3.0
    except Exception:
        return float(os.getenv("MERID_DD_WARNING_PCT", "0.03"))


def _get_hedge_active_pct() -> float:
    """Get hedge_active threshold from core.settings or env var."""
    try:
        from core.settings import DRAWDOWN_HALT_PCT
        # Hedge active is 1/2 of halt (10% halt → 5% hedge_active)
        return DRAWDOWN_HALT_PCT / 2.0
    except Exception:
        return float(os.getenv("MERID_DD_HEDGE_ACTIVE_PCT", "0.05"))


def _get_scalp_halt_pct() -> float:
    """Get scalp_halt threshold from core.settings or env var."""
    try:
        from core.settings import DRAWDOWN_HALT_PCT
        # Scalp halt is the same as halt (10%)
        return DRAWDOWN_HALT_PCT
    except Exception:
        return float(os.getenv("MERID_DD_SCALP_HALT_PCT", "0.10"))


def _get_full_halt_pct() -> float:
    """Get full_halt threshold from core.settings or env var."""
    try:
        from core.settings import DRAWDOWN_UNWIND_PCT
        # Full halt is the unwind threshold (15%)
        return DRAWDOWN_UNWIND_PCT
    except Exception:
        return float(os.getenv("MERID_DD_FULL_HALT_PCT", "0.15"))


def _get_recovery_hedge_pct() -> float:
    """Get recovery hedge threshold from core.settings or env var."""
    try:
        from core.settings import DRAWDOWN_HALT_PCT
        # Recovery is 1/3 of halt (10% halt → 3% recovery)
        return DRAWDOWN_HALT_PCT / 3.0
    except Exception:
        return float(os.getenv("MERID_DD_RECOVERY_HEDGE_PCT", "0.03"))


def _get_recovery_halt_pct() -> float:
    """Get recovery halt threshold from core.settings or env var."""
    try:
        from core.settings import DRAWDOWN_HALT_PCT
        # Recovery halt is 1/2 of halt (10% halt → 5% recovery)
        return DRAWDOWN_HALT_PCT / 2.0
    except Exception:
        return float(os.getenv("MERID_DD_RECOVERY_HALT_PCT", "0.05"))


# Singleton instance
_config: Optional[UnifiedDrawdownConfig] = None


def get_drawdown_config() -> UnifiedDrawdownConfig:
    """Get singleton unified drawdown configuration."""
    global _config
    if _config is None:
        _config = UnifiedDrawdownConfig()
        logger.info("[drawdown-config] Initialized: %s", _config.to_dict())
    return _config


def reset_drawdown_config() -> None:
    """Reset singleton (for testing)."""
    global _config
    _config = None


def validate_existing_configs() -> list:
    """Validate that existing configs use consistent thresholds.
    
    Returns list of validation messages (empty if all valid).
    """
    unified = get_drawdown_config()
    issues = []
    
    # Check KalshiRiskConfig (venue config is canonical)
    try:
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig
        kcfg = KalshiRiskConfig()
        
        if abs(kcfg.drawdown_halt_pct - unified.full_halt_pct) > 0.001:
            issues.append(
                f"KalshiRiskConfig.drawdown_halt_pct ({kcfg.drawdown_halt_pct}) "
                f"!= unified.full_halt_pct ({unified.full_halt_pct})"
            )
        
        if abs(kcfg.drawdown_unwind_pct - unified.scalp_halt_pct) > 0.001:
            issues.append(
                f"KalshiRiskConfig.drawdown_unwind_pct ({kcfg.drawdown_unwind_pct}) "
                f"!= unified.scalp_halt_pct ({unified.scalp_halt_pct})"
            )
    except Exception as e:
        issues.append(f"Could not validate KalshiRiskConfig: {e}")
    
    # Check CycleDrawdownConfig
    try:
        from merid.event_venues.kalshi.cycle_drawdown import CycleDrawdownConfig
        ccfg = CycleDrawdownConfig()
        
        # Cycle drawdown should use the hedge_active threshold
        max_cycle_dd = max(
            ccfg.cycle_drawdown_pct_small,
            ccfg.cycle_drawdown_pct_medium,
            ccfg.cycle_drawdown_pct_large
        )
        if max_cycle_dd > unified.hedge_active_pct:
            issues.append(
                f"CycleDrawdown max ({max_cycle_dd}) > unified hedge_active "
                f"({unified.hedge_active_pct})"
            )
    except Exception as e:
        issues.append(f"Could not validate CycleDrawdownConfig: {e}")
    
    # Check HedgeConfig (should not have conflicting max_drawdown)
    try:
        from merid.hedging.config import HedgeConfig
        hcfg = HedgeConfig()
        
        # HedgeConfig.max_drawdown_pct was 40%, should be ignored or aligned
        if hcfg.max_drawdown_pct > 0 and hcfg.max_drawdown_pct < 1.0:
            if hcfg.max_drawdown_pct != unified.full_halt_pct:
                issues.append(
                    f"HedgeConfig.max_drawdown_pct ({hcfg.max_drawdown_pct}) "
                    f"should match unified.full_halt_pct ({unified.full_halt_pct}) or be removed"
                )
    except Exception as e:
        issues.append(f"Could not validate HedgeConfig: {e}")
    
    return issues
