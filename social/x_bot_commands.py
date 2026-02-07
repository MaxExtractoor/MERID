from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict

from social.social_aware_quant import BotCommandType


class XBotRole(Enum):
    """Role mapping for X bot users."""

    PUBLIC = "public"
    USER = "user"
    OPS = "ops"
    ADMIN = "admin"


@dataclass
class CommandDefinition:
    """Describes a bot command and its backend mapping."""

    name: str
    endpoint: str
    method: str
    required_role: XBotRole
    command_type: BotCommandType
    description: str
    risk_level: str = "low"


def get_default_commands() -> Dict[str, CommandDefinition]:
    """Return default command registry for the X bot."""
    return {
        "status": CommandDefinition(
            name="status",
            endpoint="/x/status",
            method="GET",
            required_role=XBotRole.PUBLIC,
            command_type=BotCommandType.READ_ONLY,
            description="High-level MERID system status",
        ),
        "portfolio": CommandDefinition(
            name="portfolio",
            endpoint="/x/portfolio",
            method="GET",
            required_role=XBotRole.OPS,
            command_type=BotCommandType.READ_ONLY,
            description="Aggregate portfolio metrics",
            risk_level="medium",
        ),
        "risk": CommandDefinition(
            name="risk",
            endpoint="/x/risk",
            method="GET",
            required_role=XBotRole.OPS,
            command_type=BotCommandType.READ_ONLY,
            description="Risk limits and usage",
            risk_level="medium",
        ),
        "incidents": CommandDefinition(
            name="incidents",
            endpoint="/x/incidents",
            method="GET",
            required_role=XBotRole.OPS,
            command_type=BotCommandType.READ_ONLY,
            description="Incident summaries",
            risk_level="high",
        ),
        "social-intel": CommandDefinition(
            name="social-intel",
            endpoint="/x/social-intel",
            method="GET",
            required_role=XBotRole.USER,
            command_type=BotCommandType.READ_ONLY,
            description="Advisory social sentiment summary",
        ),
        "help": CommandDefinition(
            name="help",
            endpoint="/x/help",
            method="GET",
            required_role=XBotRole.PUBLIC,
            command_type=BotCommandType.READ_ONLY,
            description="List available commands",
        ),
    }
