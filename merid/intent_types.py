"""Canonical intent-side exposure types.

Exposes the exposure-change vocabulary used by OrderIntent and position
management. Kept in its own module so it can be imported without pulling in
the full order_router dependency tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExposureLeg(Enum):
    """Which side of a binary market a position/exposure lives on."""
    YES = "yes"
    NO = "no"


class ExposureDirection(Enum):
    """Direction of an exposure change relative to the current position."""
    INCREASE = "increase"
    DECREASE = "decrease"


@dataclass
class ExposureChange:
    """Description of how an order changes market exposure."""
    leg: ExposureLeg
    direction: ExposureDirection | str
    magnitude: int
