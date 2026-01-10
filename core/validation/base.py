from __future__ import annotations

# Stage 4 Validation: common contracts for external reality validators.

from dataclasses import dataclass, field
from typing import Any, Dict, Literal

ValidationStatus = Literal["confirmed", "failed", "pending", "error"]


@dataclass
class ValidatorVerdict:
    name: str
    status: ValidationStatus
    score: float
    details: str
    evidence: Dict[str, Any] = field(default_factory=dict)


class BaseValidator:
    name: str = "base"
    weight: float = 1.0
    requires_metadata: bool = False

    async def validate(self, energy: Dict[str, Any], vote_result: Dict[str, Any]) -> ValidatorVerdict:
        raise NotImplementedError

    def pending(self, details: str, *, evidence: Dict[str, Any] | None = None) -> ValidatorVerdict:
        return ValidatorVerdict(self.name, "pending", 0.0, details, evidence or {})

    def failure(self, details: str, *, score: float = 0.0, evidence: Dict[str, Any] | None = None) -> ValidatorVerdict:
        return ValidatorVerdict(self.name, "failed", max(0.0, score), details, evidence or {})

    def success(self, details: str, *, score: float = 1.0, evidence: Dict[str, Any] | None = None) -> ValidatorVerdict:
        return ValidatorVerdict(self.name, "confirmed", min(1.0, score), details, evidence or {})

    def error(self, details: str, *, evidence: Dict[str, Any] | None = None) -> ValidatorVerdict:
        return ValidatorVerdict(self.name, "error", 0.0, details, evidence or {})
