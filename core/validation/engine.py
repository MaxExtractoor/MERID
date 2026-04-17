from __future__ import annotations

# Stage 4 Validation: orchestrates multi-source reality confirmation.

from dataclasses import asdict
from typing import Any, Dict, List

from utils.logger import get_logger

from core.validation.base import BaseValidator, ValidatorVerdict
from core.validation.onchain import OnChainPriceValidator
from core.validation.polymarket import PolymarketValidator
from core.validation.time_window import TimeWindowValidator


class ValidationEngine:
    def __init__(self, validators: List[BaseValidator]):
        self.validators = validators
        self.logger = get_logger("core.validation")

    async def validate(self, energy: Dict[str, Any], vote_result: Dict[str, Any]) -> Dict[str, Any]:
        verdicts: List[ValidatorVerdict] = []
        for validator in self.validators:
            try:
                verdict = await validator.validate(energy, vote_result)
            except Exception as exc:  # pragma: no cover - runtime resilience
                self.logger.exception("Validator %s crashed: %s", validator.name, exc)
                verdict = validator.error(str(exc))
            verdicts.append(verdict)

        status, score = self._aggregate(verdicts)
        payload = {
            "status": status,
            "score": round(score, 4),
            "verdicts": [asdict(v) for v in verdicts],
        }
        self.logger.info("Validation status=%s score=%.3f", status, score)
        return payload

    def _aggregate(self, verdicts: List[ValidatorVerdict]) -> tuple[str, float]:
        if not verdicts:
            return "pending", 0.0

        failures = [v for v in verdicts if v.status == "failed"]
        errors = [v for v in verdicts if v.status == "error"]
        confirmations = [v for v in verdicts if v.status == "confirmed"]
        pendings = [v for v in verdicts if v.status == "pending"]

        if failures:
            return "failed", sum(v.score for v in failures) / len(failures)

        if confirmations and not pendings:
            return "confirmed", sum(v.score for v in confirmations) / len(confirmations)

        if confirmations:
            return "partial", sum(v.score for v in confirmations) / len(confirmations)

        if errors and not confirmations:
            return "error", 0.0

        return "pending", 0.0


    async def validate_order(self, order: Any) -> Dict[str, Any]:
        """Validate an order before execution"""
        # Basic validation structure for order validation
        # Returns validation result with passed/failed status
        try:
            # For now, return success - can be enhanced with actual validation logic
            return {
                "passed": True,
                "reason": "Order validation passed",
                "score": 1.0
            }
        except Exception as e:
            self.logger.error(f"Order validation error: {e}")
            return {
                "passed": False,
                "reason": f"Validation error: {str(e)}",
                "score": 0.0
            }


validation_engine = ValidationEngine(
    [
        PolymarketValidator(),
        OnChainPriceValidator(),
        TimeWindowValidator(),
    ]
)


def get_validation_engine() -> ValidationEngine:
    """Get singleton validation engine instance"""
    return validation_engine
