"""
Secure yield contract design system for MERID.

Implements:
- Hardened yield contract architecture
- Explicit yield sources and caps
- Safety states and circuit breakers
- Solidity security checklist enforcement
"""

import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class YieldSource(Enum):
    """Yield source type."""
    TRADING_FEES = "trading_fees"
    LENDING_INTEREST = "lending_interest"
    PERP_FUNDING = "perp_funding"
    LP_FEES = "lp_fees"
    RWA_COUPONS = "rwa_coupons"
    STAKING_REWARDS = "staking_rewards"


class SafetyState(Enum):
    """Contract safety state."""
    NORMAL = "normal"
    PAUSED = "paused"
    DEPOSITS_PAUSED = "deposits_paused"
    WITHDRAWALS_ONLY = "withdrawals_only"
    EMERGENCY = "emergency"


class SecurityCheckType(Enum):
    """Security check type."""
    REENTRANCY = "reentrancy"
    ACCESS_CONTROL = "access_control"
    UPGRADE_SAFETY = "upgrade_safety"
    EXTERNAL_CALLS = "external_calls"
    ARITHMETIC = "arithmetic"
    ACCOUNTING = "accounting"


@dataclass
class YieldContractSpec:
    """Yield contract specification."""
    contract_id: str
    contract_name: str
    
    # Architecture
    core_accounting_module: str = ""
    strategy_adapters: List[str] = field(default_factory=list)
    
    # Yield sources
    yield_sources: List[YieldSource] = field(default_factory=list)
    
    # Limits
    max_leverage: Decimal = Decimal("1.0")  # No leverage by default
    max_external_protocol_exposure_pct: float = 50.0
    max_per_strategy_loss_usd: Decimal = Decimal("10000")
    max_per_epoch_loss_pct: float = 5.0
    
    # Safety
    pause_roles: List[str] = field(default_factory=list)
    circuit_breaker_thresholds: Dict[str, Any] = field(default_factory=dict)
    
    # Upgrade
    upgrade_delay_hours: int = 48
    timelock_address: Optional[str] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SecurityCheck:
    """Security check result."""
    check_id: str
    contract_id: str
    check_type: SecurityCheckType
    
    # Result
    passed: bool = False
    severity: str = "info"  # info, warning, critical
    
    # Details
    findings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    # Evidence
    code_locations: List[str] = field(default_factory=list)
    
    executed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CircuitBreaker:
    """Circuit breaker configuration."""
    breaker_id: str
    contract_id: str
    
    # Trigger
    metric: str  # slippage, utilization, price_deviation, loss_rate
    threshold: float
    
    # Action
    action: SafetyState
    
    # Status
    triggered: bool = False
    triggered_at: Optional[datetime] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""
    limit_id: str
    contract_id: str
    
    # Limit type
    limit_type: str  # withdrawal, mint, leverage_change
    
    # Parameters
    max_amount_per_block: Decimal = Decimal("0")
    max_amount_per_hour: Decimal = Decimal("0")
    max_amount_per_day: Decimal = Decimal("0")
    
    # Cooldown
    cooldown_seconds: int = 0
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class SecureYieldContractDesigner:
    """
    Secure yield contract design system.
    
    Ensures all MERID yield contracts follow:
    - Hardened architecture patterns
    - Explicit yield sources and caps
    - Safety states and circuit breakers
    - Solidity security best practices
    """
    
    def __init__(self):
        self._contract_specs: Dict[str, YieldContractSpec] = {}
        self._security_checks: List[SecurityCheck] = []
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._rate_limits: Dict[str, RateLimitConfig] = {}
    
    def create_contract_spec(
        self,
        contract_name: str,
        yield_sources: List[YieldSource],
        max_leverage: Decimal = Decimal("1.0"),
        max_external_exposure_pct: float = 50.0,
    ) -> YieldContractSpec:
        """Create yield contract specification."""
        contract_id = f"contract_{int(datetime.utcnow().timestamp())}"
        
        spec = YieldContractSpec(
            contract_id=contract_id,
            contract_name=contract_name,
            yield_sources=yield_sources,
            max_leverage=max_leverage,
            max_external_protocol_exposure_pct=max_external_exposure_pct,
        )
        
        # Set default architecture
        spec.core_accounting_module = f"{contract_name}Accounting"
        spec.strategy_adapters = [f"{contract_name}StrategyAdapter"]
        
        # Set default pause roles
        spec.pause_roles = ["GUARDIAN", "EMERGENCY_ADMIN"]
        
        # Set default circuit breakers
        spec.circuit_breaker_thresholds = {
            "max_slippage_bps": 100,  # 1%
            "max_utilization_pct": 90,
            "max_price_deviation_pct": 5,
            "max_loss_rate_per_hour_pct": 2,
        }
        
        self._contract_specs[contract_id] = spec
        
        logger.info(
            f"Created contract spec '{contract_id}': {contract_name} "
            f"(sources: {[s.value for s in yield_sources]})"
        )
        
        return spec
    
    def run_security_checklist(
        self,
        contract_id: str,
        contract_code: Optional[str] = None,
    ) -> List[SecurityCheck]:
        """Run Solidity security checklist."""
        checks = []
        
        # Reentrancy check
        checks.append(self._check_reentrancy(contract_id, contract_code))
        
        # Access control check
        checks.append(self._check_access_control(contract_id, contract_code))
        
        # Upgrade safety check
        checks.append(self._check_upgrade_safety(contract_id, contract_code))
        
        # External calls check
        checks.append(self._check_external_calls(contract_id, contract_code))
        
        # Arithmetic check
        checks.append(self._check_arithmetic(contract_id, contract_code))
        
        # Accounting check
        checks.append(self._check_accounting(contract_id, contract_code))
        
        self._security_checks.extend(checks)
        
        # Log results
        critical_findings = sum(1 for c in checks if not c.passed and c.severity == "critical")
        
        logger.info(
            f"Ran security checklist for contract '{contract_id}': "
            f"{len(checks)} checks, {critical_findings} critical findings"
        )
        
        return checks
    
    def _check_reentrancy(
        self,
        contract_id: str,
        contract_code: Optional[str],
    ) -> SecurityCheck:
        """Check for reentrancy vulnerabilities."""
        check_id = f"check_reentrancy_{int(datetime.utcnow().timestamp())}"
        
        findings = []
        recommendations = []
        passed = True
        
        if contract_code:
            # Check for external calls before state changes
            if "call.value" in contract_code or ".call{" in contract_code:
                if "balance = 0" in contract_code:
                    findings.append("Potential reentrancy: external call before state update")
                    recommendations.append("Use checks-effects-interactions pattern")
                    recommendations.append("Add ReentrancyGuard modifier")
                    passed = False
        
        return SecurityCheck(
            check_id=check_id,
            contract_id=contract_id,
            check_type=SecurityCheckType.REENTRANCY,
            passed=passed,
            severity="critical" if not passed else "info",
            findings=findings,
            recommendations=recommendations,
        )
    
    def _check_access_control(
        self,
        contract_id: str,
        contract_code: Optional[str],
    ) -> SecurityCheck:
        """Check access control."""
        check_id = f"check_access_{int(datetime.utcnow().timestamp())}"
        
        findings = []
        recommendations = []
        passed = True
        
        spec = self._contract_specs.get(contract_id)
        
        if spec and not spec.pause_roles:
            findings.append("No pause roles defined")
            recommendations.append("Define GUARDIAN and EMERGENCY_ADMIN roles")
            passed = False
        
        if contract_code:
            # Check for role-based access control
            if "onlyOwner" in contract_code and "AccessControl" not in contract_code:
                findings.append("Using simple Ownable instead of role-based access")
                recommendations.append("Use AccessControl for granular permissions")
        
        return SecurityCheck(
            check_id=check_id,
            contract_id=contract_id,
            check_type=SecurityCheckType.ACCESS_CONTROL,
            passed=passed,
            severity="warning" if not passed else "info",
            findings=findings,
            recommendations=recommendations,
        )
    
    def _check_upgrade_safety(
        self,
        contract_id: str,
        contract_code: Optional[str],
    ) -> SecurityCheck:
        """Check upgrade safety."""
        check_id = f"check_upgrade_{int(datetime.utcnow().timestamp())}"
        
        findings = []
        recommendations = []
        passed = True
        
        spec = self._contract_specs.get(contract_id)
        
        if spec:
            if spec.upgrade_delay_hours < 24:
                findings.append(f"Upgrade delay too short: {spec.upgrade_delay_hours}h")
                recommendations.append("Set upgrade delay to at least 24-48 hours")
                passed = False
            
            if not spec.timelock_address:
                findings.append("No timelock configured for upgrades")
                recommendations.append("Use timelock contract for upgrade governance")
        
        return SecurityCheck(
            check_id=check_id,
            contract_id=contract_id,
            check_type=SecurityCheckType.UPGRADE_SAFETY,
            passed=passed,
            severity="warning" if not passed else "info",
            findings=findings,
            recommendations=recommendations,
        )
    
    def _check_external_calls(
        self,
        contract_id: str,
        contract_code: Optional[str],
    ) -> SecurityCheck:
        """Check external call safety."""
        check_id = f"check_external_{int(datetime.utcnow().timestamp())}"
        
        findings = []
        recommendations = []
        passed = True
        
        if contract_code:
            # Check for unbounded external calls
            if ".call(" in contract_code and "require(" not in contract_code:
                findings.append("External calls without return value checks")
                recommendations.append("Always validate external call return values")
                passed = False
            
            # Check for arbitrary callbacks
            if "callback" in contract_code.lower():
                findings.append("Potential arbitrary callback vulnerability")
                recommendations.append("Use pull-over-push pattern for withdrawals")
        
        return SecurityCheck(
            check_id=check_id,
            contract_id=contract_id,
            check_type=SecurityCheckType.EXTERNAL_CALLS,
            passed=passed,
            severity="critical" if not passed else "info",
            findings=findings,
            recommendations=recommendations,
        )
    
    def _check_arithmetic(
        self,
        contract_id: str,
        contract_code: Optional[str],
    ) -> SecurityCheck:
        """Check arithmetic safety."""
        check_id = f"check_arithmetic_{int(datetime.utcnow().timestamp())}"
        
        findings = []
        recommendations = []
        passed = True
        
        if contract_code:
            # Check for safe math usage
            if ("+" in contract_code or "-" in contract_code or "*" in contract_code):
                if "SafeMath" not in contract_code and "pragma solidity ^0.8" not in contract_code:
                    findings.append("Arithmetic operations without SafeMath or Solidity 0.8+")
                    recommendations.append("Use Solidity 0.8+ or SafeMath library")
                    passed = False
        
        return SecurityCheck(
            check_id=check_id,
            contract_id=contract_id,
            check_type=SecurityCheckType.ARITHMETIC,
            passed=passed,
            severity="critical" if not passed else "info",
            findings=findings,
            recommendations=recommendations,
        )
    
    def _check_accounting(
        self,
        contract_id: str,
        contract_code: Optional[str],
    ) -> SecurityCheck:
        """Check yield accounting correctness."""
        check_id = f"check_accounting_{int(datetime.utcnow().timestamp())}"
        
        findings = []
        recommendations = []
        passed = True
        
        spec = self._contract_specs.get(contract_id)
        
        if spec:
            if not spec.core_accounting_module:
                findings.append("No separate accounting module defined")
                recommendations.append("Separate core accounting from strategy logic")
                passed = False
        
        if contract_code:
            # Check for share price calculation
            if "sharePrice" in contract_code or "pricePerShare" in contract_code:
                if "totalSupply" not in contract_code or "totalAssets" not in contract_code:
                    findings.append("Incomplete share price calculation")
                    recommendations.append("Ensure correct share price = totalAssets / totalSupply")
        
        return SecurityCheck(
            check_id=check_id,
            contract_id=contract_id,
            check_type=SecurityCheckType.ACCOUNTING,
            passed=passed,
            severity="critical" if not passed else "info",
            findings=findings,
            recommendations=recommendations,
        )
    
    def add_circuit_breaker(
        self,
        contract_id: str,
        metric: str,
        threshold: float,
        action: SafetyState,
    ) -> CircuitBreaker:
        """Add circuit breaker."""
        breaker_id = f"breaker_{int(datetime.utcnow().timestamp())}"
        
        breaker = CircuitBreaker(
            breaker_id=breaker_id,
            contract_id=contract_id,
            metric=metric,
            threshold=threshold,
            action=action,
        )
        
        self._circuit_breakers[breaker_id] = breaker
        
        logger.info(
            f"Added circuit breaker '{breaker_id}' for contract '{contract_id}': "
            f"{metric} > {threshold} -> {action.value}"
        )
        
        return breaker
    
    def trigger_circuit_breaker(
        self,
        breaker_id: str,
    ) -> CircuitBreaker:
        """Trigger circuit breaker."""
        breaker = self._circuit_breakers.get(breaker_id)
        
        if not breaker:
            raise ValueError(f"Circuit breaker '{breaker_id}' not found")
        
        breaker.triggered = True
        breaker.triggered_at = datetime.utcnow()
        
        logger.warning(
            f"Circuit breaker '{breaker_id}' triggered: "
            f"{breaker.metric} > {breaker.threshold} -> {breaker.action.value}"
        )
        
        return breaker
    
    def add_rate_limit(
        self,
        contract_id: str,
        limit_type: str,
        max_amount_per_block: Decimal = Decimal("0"),
        max_amount_per_hour: Decimal = Decimal("0"),
        cooldown_seconds: int = 0,
    ) -> RateLimitConfig:
        """Add rate limit."""
        limit_id = f"limit_{int(datetime.utcnow().timestamp())}"
        
        limit = RateLimitConfig(
            limit_id=limit_id,
            contract_id=contract_id,
            limit_type=limit_type,
            max_amount_per_block=max_amount_per_block,
            max_amount_per_hour=max_amount_per_hour,
            cooldown_seconds=cooldown_seconds,
        )
        
        self._rate_limits[limit_id] = limit
        
        logger.info(
            f"Added rate limit '{limit_id}' for contract '{contract_id}': "
            f"{limit_type} (per_block: {max_amount_per_block}, per_hour: {max_amount_per_hour})"
        )
        
        return limit
    
    def get_contract_security_report(
        self,
        contract_id: str,
    ) -> Dict[str, Any]:
        """Get contract security report."""
        spec = self._contract_specs.get(contract_id)
        
        if not spec:
            return {}
        
        checks = [c for c in self._security_checks if c.contract_id == contract_id]
        breakers = [b for b in self._circuit_breakers.values() if b.contract_id == contract_id]
        limits = [l for l in self._rate_limits.values() if l.contract_id == contract_id]
        
        return {
            "contract_id": contract_id,
            "contract_name": spec.contract_name,
            "yield_sources": [s.value for s in spec.yield_sources],
            "limits": {
                "max_leverage": str(spec.max_leverage),
                "max_external_exposure_pct": spec.max_external_protocol_exposure_pct,
                "max_per_strategy_loss_usd": str(spec.max_per_strategy_loss_usd),
            },
            "security_checks": {
                "total": len(checks),
                "passed": sum(1 for c in checks if c.passed),
                "critical_findings": sum(1 for c in checks if not c.passed and c.severity == "critical"),
            },
            "circuit_breakers": {
                "total": len(breakers),
                "triggered": sum(1 for b in breakers if b.triggered),
            },
            "rate_limits": {
                "total": len(limits),
            },
        }


_secure_yield_contract_designer: Optional[SecureYieldContractDesigner] = None


def get_secure_yield_contract_designer() -> SecureYieldContractDesigner:
    """Get global SecureYieldContractDesigner instance."""
    global _secure_yield_contract_designer
    if _secure_yield_contract_designer is None:
        _secure_yield_contract_designer = SecureYieldContractDesigner()
    return _secure_yield_contract_designer
