"""Backward-compatible wrapper for the trading circuit breaker."""

from utils.logger import get_logger

from merid.governance.trading_circuit_breaker import (
    TradingCircuitBreaker,
    get_trading_circuit_breaker,
)

logger = get_logger("merid.governance.adaptive_risk_limits")


class AdaptiveRiskLimits:
    """Legacy interface used by position_cache and other modules.

    Mirrors the previous ``emergency_halt`` / ``emergency_halt_reason`` API while
    delegating to the authoritative ``TradingCircuitBreaker``.
    """

    def __init__(self, breaker: TradingCircuitBreaker):
        self._breaker = breaker

    @property
    def emergency_halt(self) -> bool:
        return self._breaker.halted

    @emergency_halt.setter
    def emergency_halt(self, value: bool) -> None:
        if value:
            if not self._breaker.halted:
                self._breaker.halt(reason="legacy_emergency_halt_set_true")
        else:
            # 2026-09-03: Clearing a halt through the legacy boolean setter is
            # no longer allowed.  Use TradingCircuitBreaker.admin_release() with
            # a valid approval token, run ID, and safety checks.
            logger.warning(
                "[ADAPTIVE-RISK-LIMITS] emergency_halt=False ignored; "
                "use admin_release() to clear the circuit breaker"
            )

    @property
    def emergency_halt_reason(self) -> str:
        return self._breaker.reason or ""

    @emergency_halt_reason.setter
    def emergency_halt_reason(self, value: str) -> None:
        # Reason is captured at halt time; this setter is a compatibility shim.
        pass

    def get_halt_info(self) -> dict:
        return self._breaker.halt_info or {"halted": False}


# Singleton instance shared with the breaker.
_risk_limits_instance: AdaptiveRiskLimits | None = None


def get_adaptive_risk_limits() -> AdaptiveRiskLimits:
    global _risk_limits_instance
    if _risk_limits_instance is None:
        _risk_limits_instance = AdaptiveRiskLimits(get_trading_circuit_breaker())
    return _risk_limits_instance
