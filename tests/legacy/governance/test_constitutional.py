"""Tests for governance/constitutional.py."""
import pytest
import time
from unittest.mock import Mock, patch
from governance.constitutional import (
    InvariantSeverity, InvariantViolation, ConstitutionalInvariants, get_constitutional, _constitutional
)


class TestInvariantSeverity:
    """Test InvariantSeverity enum."""

    def test_severity_values(self):
        """Test severity enum values."""
        assert InvariantSeverity.CRITICAL.value == "critical"
        assert InvariantSeverity.HIGH.value == "high"
        assert InvariantSeverity.MEDIUM.value == "medium"
        assert InvariantSeverity.LOW.value == "low"


class TestInvariantViolation:
    """Test InvariantViolation dataclass."""

    def test_creation(self):
        """Test InvariantViolation creation."""
        violation = InvariantViolation(
            violation_id="viol_123",
            invariant_name="MAX_POSITION_SIZE",
            severity=InvariantSeverity.HIGH,
            description="Position too large",
            actual_value=15.0,
            limit_value=10.0,
            context={"symbol": "BTC/USD"},
            timestamp=1234567890.0,
        )
        assert violation.violation_id == "viol_123"
        assert violation.invariant_name == "MAX_POSITION_SIZE"
        assert violation.severity == InvariantSeverity.HIGH
        assert violation.resolved is False

    def test_to_dict(self):
        """Test InvariantViolation to_dict."""
        violation = InvariantViolation(
            violation_id="viol_123",
            invariant_name="MAX_POSITION_SIZE",
            severity=InvariantSeverity.HIGH,
            description="Position too large",
            actual_value=15.0,
            limit_value=10.0,
            context={"symbol": "BTC/USD"},
            timestamp=1234567890.0,
        )
        d = violation.to_dict()
        assert d["violation_id"] == "viol_123"
        assert d["severity"] == "high"
        assert d["resolved"] is False


class TestConstitutionalInvariants:
    """Test ConstitutionalInvariants class."""

    def test_initialization(self):
        """Test constitutional invariants initialization."""
        invariants = ConstitutionalInvariants()
        assert invariants._halted is False
        assert invariants._violation_count == 0
        assert len(invariants._violations) == 0
        assert len(invariants._bypass_attempts) == 0

    def test_invariant_values(self):
        """Test default invariant values."""
        invariants = ConstitutionalInvariants()
        assert invariants.MAX_SINGLE_POSITION_PCT == 10.0
        assert invariants.MAX_LEVERAGE == 3.0
        assert invariants.REQUIRE_HUMAN_ABOVE_USD == 100000.0
        assert invariants.COLD_WALLET_MIN_PCT == 50.0
        assert invariants.MAX_SLIPPAGE_PCT == 2.0

    def test_compute_invariants_hash(self):
        """Test hash computation."""
        invariants = ConstitutionalInvariants()
        hash1 = invariants._compute_invariants_hash()
        hash2 = invariants._compute_invariants_hash()
        
        # Hash should be deterministic
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex

    def test_verify_integrity(self):
        """Test integrity verification."""
        invariants = ConstitutionalInvariants()
        assert invariants.verify_integrity() is True

    def test_is_halted(self):
        """Test is_halted method."""
        invariants = ConstitutionalInvariants()
        assert invariants.is_halted() is False
        
        invariants._halted = True
        assert invariants.is_halted() is True

    def test_get_halt_reason(self):
        """Test get_halt_reason method."""
        invariants = ConstitutionalInvariants()
        assert invariants.get_halt_reason() is None
        
        invariants._halt("Critical violation")
        assert invariants.get_halt_reason() == "Critical violation"

    def test_check_position_size_pass(self):
        """Test position size check passes."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_position_size(5000.0, 100000.0)
        
        assert ok is True
        assert violation is None

    def test_check_position_size_fail(self):
        """Test position size check fails."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_position_size(15000.0, 100000.0)
        
        assert ok is False
        assert violation is not None
        assert violation.invariant_name == "MAX_SINGLE_POSITION_PCT"
        assert violation.severity == InvariantSeverity.HIGH

    def test_check_daily_drawdown_pass(self):
        """Test daily drawdown check passes."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_daily_drawdown(3.0)
        
        assert ok is True
        assert violation is None

    def test_check_daily_drawdown_fail(self):
        """Test daily drawdown check fails."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_daily_drawdown(6.0)
        
        assert ok is False
        assert violation is not None
        assert violation.severity == InvariantSeverity.CRITICAL
        assert invariants.is_halted() is True

    def test_check_leverage_pass(self):
        """Test leverage check passes."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_leverage(2.5)
        
        assert ok is True
        assert violation is None

    def test_check_leverage_fail(self):
        """Test leverage check fails."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_leverage(4.0)
        
        assert ok is False
        assert violation is not None
        assert violation.invariant_name == "MAX_LEVERAGE"
        assert invariants.is_halted() is True

    def test_check_human_approval_required_value(self):
        """Test human approval required for high value."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_human_approval_required(
            150000.0, "trade", False
        )
        
        assert ok is False
        assert violation is not None

    def test_check_human_approval_required_withdrawal(self):
        """Test human approval required for withdrawal."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_human_approval_required(
            5000.0, "withdrawal", False
        )
        
        assert ok is False
        assert "withdrawal" in violation.description.lower()

    def test_check_human_approval_pass(self):
        """Test human approval passes when provided."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_human_approval_required(
            150000.0, "trade", True
        )
        
        assert ok is True
        assert violation is None

    def test_check_cold_wallet_minimum_pass(self):
        """Test cold wallet minimum check passes."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_cold_wallet_minimum(60.0)
        
        assert ok is True
        assert violation is None

    def test_check_cold_wallet_minimum_fail(self):
        """Test cold wallet minimum check fails."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_cold_wallet_minimum(40.0)
        
        assert ok is False
        assert violation is not None

    def test_check_slippage_pass(self):
        """Test slippage check passes."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_slippage(1.5)
        
        assert ok is True
        assert violation is None

    def test_check_slippage_fail(self):
        """Test slippage check fails."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_slippage(3.0)
        
        assert ok is False
        assert violation is not None
        assert violation.severity == InvariantSeverity.MEDIUM

    def test_check_approval_expiry_pass(self):
        """Test approval expiry check passes."""
        invariants = ConstitutionalInvariants()
        now = time.time()
        ok, violation = invariants.check_approval_expiry(now - 30)  # 30 seconds ago
        
        assert ok is True
        assert violation is None

    def test_check_approval_expiry_fail(self):
        """Test approval expiry check fails."""
        invariants = ConstitutionalInvariants()
        now = time.time()
        ok, violation = invariants.check_approval_expiry(now - 120)  # 2 minutes ago
        
        assert ok is False
        assert violation is not None

    def test_check_consensus_quorum_pass(self):
        """Test consensus quorum check passes."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_consensus_quorum(75.0, 5)
        
        assert ok is True
        assert violation is None

    def test_check_consensus_quorum_low_agents(self):
        """Test consensus quorum fails with too few agents."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_consensus_quorum(75.0, 2)
        
        assert ok is False
        assert violation.invariant_name == "MIN_AGENTS_FOR_CONSENSUS"

    def test_check_consensus_quorum_low_pct(self):
        """Test consensus quorum fails with low percentage."""
        invariants = ConstitutionalInvariants()
        ok, violation = invariants.check_consensus_quorum(50.0, 5)
        
        assert ok is False
        assert violation.invariant_name == "CONSENSUS_QUORUM_PCT"

    def test_get_all_invariants(self):
        """Test get_all_invariants method."""
        invariants = ConstitutionalInvariants()
        all_invs = invariants.get_all_invariants()
        
        assert "capital_protection" in all_invs
        assert "leverage_risk" in all_invs
        assert "human_approval" in all_invs
        assert "custody" in all_invs
        assert "execution" in all_invs
        assert "system" in all_invs

    def test_get_violations(self):
        """Test get_violations method."""
        invariants = ConstitutionalInvariants()
        
        # Create some violations
        invariants.check_position_size(15000.0, 100000.0)
        invariants.check_slippage(3.0)
        
        violations = invariants.get_violations()
        assert len(violations) == 2

    def test_get_violations_with_limit(self):
        """Test get_violations with limit."""
        invariants = ConstitutionalInvariants()
        
        # Create multiple violations
        for i in range(5):
            invariants.check_slippage(3.0 + i)
        
        violations = invariants.get_violations(limit=3)
        assert len(violations) == 3

    def test_get_bypass_attempts(self):
        """Test get_bypass_attempts method."""
        invariants = ConstitutionalInvariants()
        
        # Record a bypass attempt
        invariants._record_bypass_attempt(
            "MAX_LEVERAGE", "agent_1", {"attempted": True}
        )
        
        attempts = invariants.get_bypass_attempts()
        assert len(attempts) == 1
        assert attempts[0]["invariant_name"] == "MAX_LEVERAGE"

    def test_get_status(self):
        """Test get_status method."""
        invariants = ConstitutionalInvariants()
        status = invariants.get_status()
        
        assert "halted" in status
        assert "invariants_hash" in status
        assert "integrity_valid" in status
        assert "total_violations" in status

    def test_critical_violation_triggers_halt(self):
        """Test that critical violation halts system."""
        invariants = ConstitutionalInvariants()
        assert invariants.is_halted() is False
        
        invariants.check_daily_drawdown(10.0)  # Exceeds 5% limit
        
        assert invariants.is_halted() is True
        assert "Critical invariant violation" in invariants.get_halt_reason()


class TestGetConstitutional:
    """Test get_constitutional function."""

    def setup_method(self):
        """Reset singleton before each test."""
        global _constitutional
        import governance.constitutional as gc
        gc._constitutional = None

    def test_singleton(self):
        """Test get_constitutional returns singleton."""
        invariants1 = get_constitutional()
        invariants2 = get_constitutional()
        assert invariants1 is invariants2
