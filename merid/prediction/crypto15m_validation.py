"""Crypto15M Validation — Upstream and downstream checks for cross-asset risk allocator.

PRODUCTION IMPLEMENTATION SPEC: Section 7

Upstream checks (before orders):
- Validate all 15m crypto agents publish intents with correct metadata
- Validate allocator has received intents before consensus/ordering
- Validate allocator logs show candidate_count, approved_count, blocked_count

Downstream checks (after orders and positions):
- Assert sum of newly opened contracts per timeframe ≤ max_contracts_per_tf_crypto_15m
- Assert net_open_contracts(expiry_id) ≤ max_open_contracts_per_expiry_crypto_15m
- Cross-check with reconciliation infrastructure

This module provides:
1. Pre-cycle validation (upstream)
2. Post-cycle validation (downstream)
3. Invariant checking
4. Alert emission on violations
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.crypto15m_validation")


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class ValidationViolation:
    """A validation violation record."""
    timestamp: float
    check_type: str  # "upstream" | "downstream"
    violation_type: str
    details: Dict[str, Any]
    severity: str = "warning"  # "warning" | "error" | "critical"


@dataclass
class CycleValidationState:
    """Validation state for a 15m cycle."""
    bucket_start: int
    bucket_iso: str
    
    # Upstream tracking
    intents_received: Set[str] = field(default_factory=set)
    agents_reported: Set[str] = field(default_factory=set)
    expected_agents: Set[str] = field(default_factory=lambda: {
        "BTC15M", "ETH15M", "SOL15M", "XRP15M", "DOGE15M", "CRYPTO15MMM"
    })
    
    # Downstream tracking
    contracts_opened: int = 0
    contracts_closed: int = 0
    markets_traded: Set[str] = field(default_factory=set)
    
    # Validation flags
    upstream_validated: bool = False
    downstream_validated: bool = False
    violations: List[ValidationViolation] = field(default_factory=list)
    
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


# =============================================================================
# UPSTREAM VALIDATION
# =============================================================================

class UpstreamValidator:
    """Validates upstream intent flow before orders are submitted.
    
    Responsibilities:
    1. Track which agents have submitted intents for each cycle
    2. Validate intent metadata (timeframe, expiry_id, asset)
    3. Ensure allocator logs show required counts
    4. Fail fast if validations fail
    """
    
    def __init__(self):
        self._cycle_states: Dict[int, CycleValidationState] = {}
        self._lock = threading.RLock()
        self._last_error: Optional[str] = None
    
    def _get_or_create_state(self, bucket_start: int, bucket_iso: str) -> CycleValidationState:
        """Get or create validation state for a cycle."""
        with self._lock:
            if bucket_start not in self._cycle_states:
                self._cycle_states[bucket_start] = CycleValidationState(
                    bucket_start=bucket_start,
                    bucket_iso=bucket_iso,
                )
                logger.info(
                    "[CRYPTO15M-VALIDATION] Created validation state for bucket=%s",
                    bucket_iso
                )
            return self._cycle_states[bucket_start]
    
    def record_intent_received(
        self,
        agent_id: str,
        intent_id: str,
        ticker: str,
        timeframe: str,
        expiry_id: str,
        asset: str,
        bucket_start: int,
        bucket_iso: str,
    ) -> Tuple[bool, Optional[str]]:
        """Record that an intent was received from an agent.
        
        Args:
            agent_id: Agent that submitted the intent
            intent_id: Unique intent identifier
            ticker: Market ticker
            timeframe: Should be "15m"
            expiry_id: Expiry identifier
            asset: Asset symbol
            bucket_start: Timeframe bucket start timestamp
            bucket_iso: ISO formatted bucket string
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        state = self._get_or_create_state(bucket_start, bucket_iso)
        
        with self._lock:
            state.intents_received.add(intent_id)
            state.agents_reported.add(agent_id)
            state.updated_at = time.time()
            
            # Validate metadata
            errors = []
            
            if timeframe != "15m":
                errors.append(f"Invalid timeframe: {timeframe} (expected '15m')")
            
            if not expiry_id or not expiry_id.startswith("CRYPTO_15M:"):
                errors.append(f"Invalid expiry_id: {expiry_id}")
            
            if asset not in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                errors.append(f"Invalid asset: {asset}")
            
            if not ticker or "15M" not in ticker.upper():
                errors.append(f"Invalid ticker for 15m: {ticker}")
            
            if errors:
                violation = ValidationViolation(
                    timestamp=time.time(),
                    check_type="upstream",
                    violation_type="invalid_metadata",
                    details={
                        "agent_id": agent_id,
                        "intent_id": intent_id,
                        "errors": errors,
                    },
                    severity="error",
                )
                state.violations.append(violation)
                logger.error(
                    "[CRYPTO15M-VALIDATION] UPSTREAM INVALID_METADATA intent=%s agent=%s errors=%s",
                    intent_id, agent_id, errors
                )
                return False, f"Invalid metadata: {', '.join(errors)}"
            
            logger.debug(
                "[CRYPTO15M-VALIDATION] UPSTREAM OK intent=%s agent=%s ticker=%s",
                intent_id, agent_id, ticker
            )
            return True, None
    
    def validate_before_allocation(
        self,
        bucket_start: int,
        bucket_iso: str,
        expected_candidate_count: Optional[int] = None,
    ) -> Tuple[bool, List[str]]:
        """Validate upstream state before running allocation.
        
        Args:
            bucket_start: Timeframe bucket start
            bucket_iso: ISO formatted bucket string
            expected_candidate_count: Optional expected number of candidates
            
        Returns:
            Tuple of (is_valid, list_of_warnings)
        """
        state = self._get_or_create_state(bucket_start, bucket_iso)
        warnings = []
        
        with self._lock:
            # Check if we have intents from expected agents
            missing_agents = state.expected_agents - state.agents_reported
            if missing_agents:
                warning = f"Missing intents from agents: {missing_agents}"
                warnings.append(warning)
                logger.warning(
                    "[CRYPTO15M-VALIDATION] UPSTREAM MISSING_AGENTS bucket=%s missing=%s",
                    bucket_iso, missing_agents
                )
            
            # Check if we have any intents at all
            if not state.intents_received:
                warning = f"No intents received for bucket={bucket_iso}"
                warnings.append(warning)
                logger.warning(
                    "[CRYPTO15M-VALIDATION] UPSTREAM NO_INTENTS bucket=%s",
                    bucket_iso
                )
            
            # Log validation result
            if warnings:
                logger.info(
                    "[CRYPTO15M-VALIDATION] UPSTREAM VALIDATION bucket=%s warnings=%d "
                    "intents=%d agents=%d",
                    bucket_iso, len(warnings), len(state.intents_received),
                    len(state.agents_reported)
                )
            else:
                logger.info(
                    "[CRYPTO15M-VALIDATION] UPSTREAM VALIDATED bucket=%s intents=%d agents=%d",
                    bucket_iso, len(state.intents_received), len(state.agents_reported)
                )
                state.upstream_validated = True
            
            return len(warnings) == 0, warnings
    
    def validate_allocator_logs(
        self,
        bucket_start: int,
        bucket_iso: str,
        candidate_count: int,
        approved_count: int,
        blocked_count: int,
    ) -> bool:
        """Validate that allocator has logged required counts.
        
        Args:
            bucket_start: Timeframe bucket start
            bucket_iso: ISO formatted bucket string
            candidate_count: Number of candidate intents
            approved_count: Number of approved intents
            blocked_count: Number of blocked intents
            
        Returns:
            True if logs are valid
        """
        state = self._get_or_create_state(bucket_start, bucket_iso)
        
        with self._lock:
            # Verify counts are consistent
            if candidate_count != len(state.intents_received):
                logger.warning(
                    "[CRYPTO15M-VALIDATION] LOG_MISMATCH bucket=%s "
                    "logged_candidates=%d actual_intents=%d",
                    bucket_iso, candidate_count, len(state.intents_received)
                )
            
            total_processed = approved_count + blocked_count
            if total_processed != candidate_count:
                violation = ValidationViolation(
                    timestamp=time.time(),
                    check_type="upstream",
                    violation_type="count_mismatch",
                    details={
                        "candidate_count": candidate_count,
                        "approved_count": approved_count,
                        "blocked_count": blocked_count,
                        "total_processed": total_processed,
                    },
                    severity="error",
                )
                state.violations.append(violation)
                logger.error(
                    "[CRYPTO15M-VALIDATION] UPSTREAM COUNT_MISMATCH bucket=%s "
                    "candidates=%d approved=%d blocked=%d total=%d",
                    bucket_iso, candidate_count, approved_count, blocked_count, total_processed
                )
                return False
            
            logger.info(
                "[CRYPTO15M-VALIDATION] UPSTREAM LOGS_VALIDATED bucket=%s "
                "candidates=%d approved=%d blocked=%d",
                bucket_iso, candidate_count, approved_count, blocked_count
            )
            return True


# =============================================================================
# DOWNSTREAM VALIDATION
# =============================================================================

class DownstreamValidator:
    """Validates downstream exposure after orders and fills.
    
    Responsibilities:
    1. Track contracts opened per timeframe
    2. Track open exposure per expiry
    3. Assert invariants are not violated
    4. Cross-check with reconciliation
    """
    
    def __init__(self, max_contracts_per_tf: int = 1, max_open_per_expiry: int = 1):
        self.max_contracts_per_tf = max_contracts_per_tf
        self.max_open_per_expiry = max_open_per_expiry
        self._cycle_states: Dict[int, CycleValidationState] = {}
        self._lock = threading.RLock()
    
    def _get_or_create_state(self, bucket_start: int, bucket_iso: str) -> CycleValidationState:
        """Get or create validation state for a cycle."""
        with self._lock:
            if bucket_start not in self._cycle_states:
                self._cycle_states[bucket_start] = CycleValidationState(
                    bucket_start=bucket_start,
                    bucket_iso=bucket_iso,
                )
            return self._cycle_states[bucket_start]
    
    def record_order_opened(
        self,
        ticker: str,
        contracts: int,
        bucket_start: int,
        bucket_iso: str,
    ) -> None:
        """Record that an order opened new contracts.
        
        Args:
            ticker: Market ticker
            contracts: Number of contracts opened
            bucket_start: Timeframe bucket start
            bucket_iso: ISO formatted bucket string
        """
        state = self._get_or_create_state(bucket_start, bucket_iso)
        
        with self._lock:
            state.contracts_opened += contracts
            state.markets_traded.add(ticker)
            state.updated_at = time.time()
            
            logger.debug(
                "[CRYPTO15M-VALIDATION] DOWNSTREAM ORDER_OPENED bucket=%s "
                "ticker=%s contracts=%d total_opened=%d",
                bucket_iso, ticker, contracts, state.contracts_opened
            )
    
    def record_position_closed(
        self,
        ticker: str,
        contracts: int,
        bucket_start: int,
        bucket_iso: str,
    ) -> None:
        """Record that a position was closed.
        
        Args:
            ticker: Market ticker
            contracts: Number of contracts closed
            bucket_start: Timeframe bucket start
            bucket_iso: ISO formatted bucket string
        """
        state = self._get_or_create_state(bucket_start, bucket_iso)
        
        with self._lock:
            state.contracts_closed += contracts
            state.updated_at = time.time()
            
            logger.debug(
                "[CRYPTO15M-VALIDATION] DOWNSTREAM POSITION_CLOSED bucket=%s "
                "ticker=%s contracts=%d total_closed=%d",
                bucket_iso, ticker, contracts, state.contracts_closed
            )
    
    def validate_post_cycle(
        self,
        bucket_start: int,
        bucket_iso: str,
        expiry_exposures: Dict[str, Dict[str, Any]],
    ) -> Tuple[bool, List[ValidationViolation]]:
        """Validate downstream invariants after a cycle.
        
        Args:
            bucket_start: Timeframe bucket start
            bucket_iso: ISO formatted bucket string
            expiry_exposures: Dict of expiry_id -> exposure state
            
        Returns:
            Tuple of (is_valid, list_of_violations)
        """
        state = self._get_or_create_state(bucket_start, bucket_iso)
        violations = []
        
        with self._lock:
            # Check 1: Timeframe contract budget
            if state.contracts_opened > self.max_contracts_per_tf:
                violation = ValidationViolation(
                    timestamp=time.time(),
                    check_type="downstream",
                    violation_type="timeframe_budget_exceeded",
                    details={
                        "bucket_iso": bucket_iso,
                        "contracts_opened": state.contracts_opened,
                        "max_allowed": self.max_contracts_per_tf,
                    },
                    severity="critical",
                )
                violations.append(violation)
                logger.error(
                    "[CRYPTO15M-VALIDATION] DOWNSTREAM INVARIANT_VIOLATION bucket=%s "
                    "type=timeframe_budget_exceeded opened=%d max=%d",
                    bucket_iso, state.contracts_opened, self.max_contracts_per_tf
                )
            
            # Check 2: Per-expiry open exposure caps
            for expiry_id, exposure in expiry_exposures.items():
                net_open = exposure.get("net_open_contracts", 0)
                if net_open > self.max_open_per_expiry:
                    violation = ValidationViolation(
                        timestamp=time.time(),
                        check_type="downstream",
                        violation_type="expiry_cap_exceeded",
                        details={
                            "bucket_iso": bucket_iso,
                            "expiry_id": expiry_id,
                            "net_open": net_open,
                            "max_allowed": self.max_open_per_expiry,
                        },
                        severity="critical",
                    )
                    violations.append(violation)
                    logger.error(
                        "[CRYPTO15M-VALIDATION] DOWNSTREAM INVARIANT_VIOLATION bucket=%s "
                        "type=expiry_cap_exceeded expiry=%s net_open=%d max=%d",
                        bucket_iso, expiry_id, net_open, self.max_open_per_expiry
                    )
            
            # Record violations in state
            state.violations.extend(violations)
            
            if violations:
                logger.error(
                    "[CRYPTO15M-VALIDATION] DOWNSTREAM VALIDATION_FAILED bucket=%s "
                    "violations=%d",
                    bucket_iso, len(violations)
                )
                return False, violations
            
            state.downstream_validated = True
            logger.info(
                "[CRYPTO15M-VALIDATION] DOWNSTREAM VALIDATED bucket=%s "
                "opened=%d markets=%d",
                bucket_iso, state.contracts_opened, len(state.markets_traded)
            )
            return True, []
    
    def cross_check_with_reconciliation(
        self,
        bucket_start: int,
        bucket_iso: str,
        reconciled_positions: Dict[str, int],  # ticker -> contracts
    ) -> Tuple[bool, List[str]]:
        """Cross-check calculated exposures with reconciliation data.
        
        Args:
            bucket_start: Timeframe bucket start
            bucket_iso: ISO formatted bucket string
            reconciled_positions: Positions from reconciliation
            
        Returns:
            Tuple of (is_consistent, list_of_discrepancies)
        """
        state = self._get_or_create_state(bucket_start, bucket_iso)
        discrepancies = []
        
        with self._lock:
            # Compare markets traded vs reconciled
            for ticker in state.markets_traded:
                if ticker not in reconciled_positions:
                    discrepancies.append(f"Market {ticker} in trades but not in reconciliation")
            
            if discrepancies:
                logger.warning(
                    "[CRYPTO15M-VALIDATION] DOWNSTREAM RECONCILIATION_MISMATCH bucket=%s "
                    "discrepancies=%d",
                    bucket_iso, len(discrepancies)
                )
                return False, discrepancies
            
            logger.info(
                "[CRYPTO15M-VALIDATION] DOWNSTREAM RECONCILIATION_OK bucket=%s",
                bucket_iso
            )
            return True, []


# =============================================================================
# COMBINED VALIDATOR
# =============================================================================

class Crypto15MValidator:
    """Combined upstream and downstream validator.
    
    Provides a single interface for all 15m crypto validation needs.
    """
    
    def __init__(
        self,
        max_contracts_per_tf: int = 1,
        max_open_per_expiry: int = 1,
    ):
        self.upstream = UpstreamValidator()
        self.downstream = DownstreamValidator(max_contracts_per_tf, max_open_per_expiry)
        self._lock = threading.RLock()
    
    def record_intent(self, agent_id: str, intent_id: str, ticker: str,
                      timeframe: str, expiry_id: str, asset: str,
                      bucket_start: int, bucket_iso: str) -> Tuple[bool, Optional[str]]:
        """Record an intent for upstream validation."""
        return self.upstream.record_intent_received(
            agent_id, intent_id, ticker, timeframe, expiry_id, asset,
            bucket_start, bucket_iso
        )
    
    def validate_before_allocation(self, bucket_start: int, bucket_iso: str,
                                   expected_candidate_count: Optional[int] = None) -> Tuple[bool, List[str]]:
        """Validate upstream before allocation."""
        return self.upstream.validate_before_allocation(bucket_start, bucket_iso, expected_candidate_count)
    
    def validate_allocator_logs(self, bucket_start: int, bucket_iso: str,
                              candidate_count: int, approved_count: int,
                              blocked_count: int) -> bool:
        """Validate allocator logged counts."""
        return self.upstream.validate_allocator_logs(bucket_start, bucket_iso,
                                                     candidate_count, approved_count, blocked_count)
    
    def record_order(self, ticker: str, contracts: int,
                    bucket_start: int, bucket_iso: str) -> None:
        """Record an order for downstream tracking."""
        self.downstream.record_order_opened(ticker, contracts, bucket_start, bucket_iso)
    
    def record_close(self, ticker: str, contracts: int,
                    bucket_start: int, bucket_iso: str) -> None:
        """Record a position close for downstream tracking."""
        self.downstream.record_position_closed(ticker, contracts, bucket_start, bucket_iso)
    
    def validate_post_cycle(self, bucket_start: int, bucket_iso: str,
                         expiry_exposures: Dict[str, Dict[str, Any]]) -> Tuple[bool, List[ValidationViolation]]:
        """Validate downstream after cycle."""
        return self.downstream.validate_post_cycle(bucket_start, bucket_iso, expiry_exposures)
    
    def cross_check_reconciliation(self, bucket_start: int, bucket_iso: str,
                                  reconciled_positions: Dict[str, int]) -> Tuple[bool, List[str]]:
        """Cross-check with reconciliation data."""
        return self.downstream.cross_check_with_reconciliation(bucket_start, bucket_iso, reconciled_positions)


# =============================================================================
# GLOBAL SINGLETON
# =============================================================================

_validator_instance: Optional[Crypto15MValidator] = None
_validator_lock = threading.Lock()


def get_crypto15m_validator() -> Crypto15MValidator:
    """Get the global Crypto15MValidator singleton."""
    global _validator_instance
    if _validator_instance is not None:
        return _validator_instance
    
    with _validator_lock:
        if _validator_instance is None:
            _validator_instance = Crypto15MValidator()
        return _validator_instance


def reset_crypto15m_validator_for_testing() -> None:
    """Reset the global singleton (testing only)."""
    global _validator_instance
    with _validator_lock:
        _validator_instance = None
