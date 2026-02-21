"""
MERID Agent Prompts Module.

Provides ReAct-style prompting templates for multi-agent trading.
"""

from agents.prompts.react_templates import (
    AgentRole,
    REACT_SYSTEM_TEMPLATE,
    ROLE_PROMPTS,
    ROLE_TOOLS,
    build_react_prompt,
    build_consensus_request_prompt,
    build_risk_review_prompt,
    get_role_from_agent_id,
    parse_react_response,
)

__all__ = [
    "AgentRole",
    "REACT_SYSTEM_TEMPLATE",
    "ROLE_PROMPTS",
    "ROLE_TOOLS",
    "build_react_prompt",
    "build_consensus_request_prompt",
    "build_risk_review_prompt",
    "get_role_from_agent_id",
    "parse_react_response",
]
