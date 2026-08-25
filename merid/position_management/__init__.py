"""
Position Management Module

Provides position tracking, PnL monitoring, and exit management for swing trading.
"""

from merid.position_management.position import Position, PositionSide, TrailingType
from merid.position_management.position_monitor import get_position_monitor, PositionMonitor
from merid.position_management.exit_policy import ExitPolicy, ExitAction, ExitReason
from merid.position_management.exit_policy_resolver import get_exit_policy_resolver, ExitPolicyResolver
from merid.position_management.exit_conditions import ExitCondition, evaluate_exit_conditions, choose_exit_condition

__all__ = [
    "Position",
    "PositionSide",
    "TrailingType",
    "PositionMonitor",
    "get_position_monitor",
    "ExitPolicy",
    "ExitAction",
    "ExitReason",
    "ExitPolicyResolver",
    "get_exit_policy_resolver",
]
