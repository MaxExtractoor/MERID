"""
MERID Cognitive Core v2.0
Sovereign, local-first decision organism cognitive engine.

Architecture:
- 6 independent agents (Logic, Intuition, Adversarial, Market, Simulation, Governance)
- Bayesian belief updating
- Monte Carlo simulation (fat-tailed distributions)
- Risk modeling (fractional Kelly, tail risk)
- Spine Bus arbitration
- Charter enforcement
- SLP-1 lockdown authority

Constraints:
- Local only (no cloud)
- Advisory only (no autonomous execution)
- Human primacy (all execution requires approval)
- Distillation gate (all outputs human-legible)
"""

__version__ = "2.0.0"
__charter_version__ = "2.0"

from .agents.base import Agent, BeliefVector
from .spine.bus import SpineBus, Message
from .governance.charter import Charter, SLP1Lockdown
from .simulation.monte_carlo import MonteCarloEngine
from .risk.kelly import KellyCriterion, TailRiskAnalyzer

__all__ = [
    "Agent",
    "BeliefVector",
    "SpineBus",
    "Message",
    "Charter",
    "SLP1Lockdown",
    "MonteCarloEngine",
    "KellyCriterion",
    "TailRiskAnalyzer",
]
