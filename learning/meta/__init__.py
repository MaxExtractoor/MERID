"""
MERID Learning - Meta-Learning

Phase 5.2 of Master Build Directive

Implements:
- MAML (Model-Agnostic Meta-Learning)
- Regime-conditioned policies
- Strategy adaptation
- Fast adaptation to new market conditions

WARNING: This module may only be used AFTER Phases 1-4 are operational.
Meta-learning without perception is a fatal architectural error.
"""

from learning.meta.maml import MAML, MAMLConfig, MAMLTask
from learning.meta.regime_conditioned import (
    RegimeConditionedPolicy,
    RegimeConditionedConfig,
    RegimeAdapter,
    get_regime_adapter,
)

__all__ = [
    "MAML",
    "MAMLConfig",
    "MAMLTask",
    "RegimeConditionedPolicy",
    "RegimeConditionedConfig",
    "RegimeAdapter",
    "get_regime_adapter",
]
