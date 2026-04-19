"""Unit tests for Crypto15M validation module.

Test coverage:
1. Upstream validation (intent metadata, agent tracking)
2. Downstream validation (exposure invariants)
3. Cross-check with reconciliation
4. Violation recording and severity
"""

from __future__ import annotations

import pytest
import time

from merid.prediction.crypto15m_validation import (
    UpstreamValidator,
    DownstreamValidator,
    Crypto15MValidator,
    ValidationViolation,
    CycleValidationState,
    get_crypto15m_validator,
    reset_crypto15m_validator_for_testing,
)


class TestUpstreamValidator:
    """Test upstream validation (before allocation)."""
    
    def setup_method(self):
        """Create fresh validator for each test."""
        self.validator = UpstreamValidator()
    
    def test_record_valid_intent(self):
        """Test recording a valid intent."""
        is_valid, error = self.validator.record_intent_received(
            agent_id="BTC15M",
            intent_id="test-1",
            ticker="KXBTC15M-26APR191400-00",
            timeframe="15m",
            expiry_id="CRYPTO_15M:26APR191400",
            asset="BTC",
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        assert is_valid is True
        assert error is None
    
    def test_record_intent_invalid_timeframe(self):
        """Test that invalid timeframe is rejected."""
        is_valid, error = self.validator.record_intent_received(
            agent_id="BTC15M",
            intent_id="test-1",
            ticker="KXBTC15M-26APR191400-00",
            timeframe="1h",  # Wrong timeframe
            expiry_id="CRYPTO_15M:26APR191400",
            asset="BTC",
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        assert is_valid is False
        assert "timeframe" in error.lower()
    
    def test_record_intent_invalid_expiry(self):
        """Test that invalid expiry_id is rejected."""
        is_valid, error = self.validator.record_intent_received(
            agent_id="BTC15M",
            intent_id="test-1",
            ticker="KXBTC15M-26APR191400-00",
            timeframe="15m",
            expiry_id="INVALID:26APR191400",  # Wrong prefix
            asset="BTC",
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        assert is_valid is False
        assert "expiry" in error.lower()
    
    def test_validate_before_allocation_success(self):
        """Test successful upstream validation with all expected agents."""
        # Record intents from ALL expected agents to avoid missing agent warnings
        expected_agents = ["BTC15M", "ETH15M", "SOL15M", "XRP15M", "DOGE15M", "CRYPTO15MMM"]
        for agent in expected_agents:
            # Handle CRYPTO15MMM specially (it's a market maker, uses BTC as representative)
            if agent == "CRYPTO15MMM":
                asset = "BTC"
                ticker = "KXBTC15M-26APR191400-MM"
            else:
                asset = agent.replace("15M", "")
                ticker = f"KX{asset}15M-26APR191400-00"
            self.validator.record_intent_received(
                agent_id=agent,
                intent_id=f"test-{agent}",
                ticker=ticker,
                timeframe="15m",
                expiry_id="CRYPTO_15M:26APR191400",
                asset=asset,
                bucket_start=1713549600,
                bucket_iso="20240419_1800",
            )
        
        is_valid, warnings = self.validator.validate_before_allocation(
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        assert is_valid is True
        assert len(warnings) == 0
    
    def test_validate_missing_agents_warning(self):
        """Test warning when expected agents are missing."""
        # Record only one intent
        self.validator.record_intent_received(
            agent_id="BTC15M",
            intent_id="test-1",
            ticker="KXBTC15M-26APR191400-00",
            timeframe="15m",
            expiry_id="CRYPTO_15M:26APR191400",
            asset="BTC",
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        is_valid, warnings = self.validator.validate_before_allocation(
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        # Should have warnings for missing agents but still be "valid"
        assert len(warnings) > 0
        assert any("missing" in w.lower() for w in warnings)
    
    def test_validate_no_intents_warning(self):
        """Test warning when no intents received."""
        is_valid, warnings = self.validator.validate_before_allocation(
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        # Should have at least 1 warning (no intents + possibly missing agents)
        assert len(warnings) >= 1
        assert any("no intents" in w.lower() for w in warnings)
    
    def test_validate_allocator_logs(self):
        """Test validation of allocator log counts."""
        # Record some intents
        for i in range(3):
            self.validator.record_intent_received(
                agent_id=f"AGENT{i}",
                intent_id=f"test-{i}",
                ticker=f"KXBTC15M-26APR191400-0{i}",
                timeframe="15m",
                expiry_id="CRYPTO_15M:26APR191400",
                asset="BTC",
                bucket_start=1713549600,
                bucket_iso="20240419_1800",
            )
        
        # Validate with correct counts
        is_valid = self.validator.validate_allocator_logs(
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
            candidate_count=3,
            approved_count=1,
            blocked_count=2,
        )
        
        assert is_valid is True
    
    def test_validate_allocator_logs_mismatch(self):
        """Test detection of count mismatch in allocator logs."""
        # Record 3 intents
        for i in range(3):
            self.validator.record_intent_received(
                agent_id=f"AGENT{i}",
                intent_id=f"test-{i}",
                ticker=f"KXBTC15M-26APR191400-0{i}",
                timeframe="15m",
                expiry_id="CRYPTO_15M:26APR191400",
                asset="BTC",
                bucket_start=1713549600,
                bucket_iso="20240419_1800",
            )
        
        # Validate with incorrect counts
        is_valid = self.validator.validate_allocator_logs(
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
            candidate_count=3,
            approved_count=2,
            blocked_count=2,  # 2+2 != 3
        )
        
        assert is_valid is False


class TestDownstreamValidator:
    """Test downstream validation (after orders/fills)."""
    
    def setup_method(self):
        """Create fresh validator for each test."""
        self.validator = DownstreamValidator(
            max_contracts_per_tf=1,
            max_open_per_expiry=1,
        )
    
    def test_record_order_opened(self):
        """Test recording opened orders."""
        self.validator.record_order_opened(
            ticker="KXBTC15M-26APR191400-00",
            contracts=1,
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        state = self.validator._get_or_create_state(1713549600, "20240419_1800")
        assert state.contracts_opened == 1
    
    def test_record_position_closed(self):
        """Test recording position closes."""
        self.validator.record_position_closed(
            ticker="KXBTC15M-26APR191400-00",
            contracts=1,
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        state = self.validator._get_or_create_state(1713549600, "20240419_1800")
        assert state.contracts_closed == 1
    
    def test_validate_post_cycle_success(self):
        """Test successful downstream validation."""
        # Record an order
        self.validator.record_order_opened(
            ticker="KXBTC15M-26APR191400-00",
            contracts=1,
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        # Validate with exposure under cap
        expiry_exposures = {
            "CRYPTO_15M:26APR191400": {"net_open_contracts": 1}
        }
        
        is_valid, violations = self.validator.validate_post_cycle(
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
            expiry_exposures=expiry_exposures,
        )
        
        assert is_valid is True
        assert len(violations) == 0
    
    def test_validate_timeframe_budget_exceeded(self):
        """Test detection of timeframe budget violation."""
        # Record more orders than allowed
        self.validator.record_order_opened(
            ticker="KXBTC15M-26APR191400-00",
            contracts=2,
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        expiry_exposures = {}
        
        is_valid, violations = self.validator.validate_post_cycle(
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
            expiry_exposures=expiry_exposures,
        )
        
        assert is_valid is False
        assert len(violations) == 1
        assert violations[0].violation_type == "timeframe_budget_exceeded"
        assert violations[0].severity == "critical"
    
    def test_validate_expiry_cap_exceeded(self):
        """Test detection of expiry cap violation."""
        # Record an order
        self.validator.record_order_opened(
            ticker="KXBTC15M-26APR191400-00",
            contracts=1,
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        # Simulate exposure over cap
        expiry_exposures = {
            "CRYPTO_15M:26APR191400": {"net_open_contracts": 2}
        }
        
        is_valid, violations = self.validator.validate_post_cycle(
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
            expiry_exposures=expiry_exposures,
        )
        
        assert is_valid is False
        assert len(violations) == 1
        assert violations[0].violation_type == "expiry_cap_exceeded"
        assert violations[0].severity == "critical"
    
    def test_reconciliation_cross_check_success(self):
        """Test successful reconciliation cross-check."""
        # Record a trade
        self.validator.record_order_opened(
            ticker="KXBTC15M-26APR191400-00",
            contracts=1,
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        # Cross-check with matching reconciliation
        reconciled = {"KXBTC15M-26APR191400-00": 1}
        
        is_consistent, discrepancies = self.validator.cross_check_with_reconciliation(
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
            reconciled_positions=reconciled,
        )
        
        assert is_consistent is True
        assert len(discrepancies) == 0
    
    def test_reconciliation_cross_check_mismatch(self):
        """Test detection of reconciliation mismatch."""
        # Record a trade
        self.validator.record_order_opened(
            ticker="KXBTC15M-26APR191400-00",
            contracts=1,
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
        )
        
        # Cross-check with empty reconciliation (missing trade)
        reconciled = {}
        
        is_consistent, discrepancies = self.validator.cross_check_with_reconciliation(
            bucket_start=1713549600,
            bucket_iso="20240419_1800",
            reconciled_positions=reconciled,
        )
        
        assert is_consistent is False
        assert len(discrepancies) > 0


class TestCombinedValidator:
    """Test combined validator (singleton interface)."""
    
    def setup_method(self):
        """Reset singleton before each test."""
        reset_crypto15m_validator_for_testing()
        self.validator = get_crypto15m_validator()
    
    def test_full_cycle_validation(self):
        """Test full upstream + downstream validation cycle."""
        bucket_start = 1713549600
        bucket_iso = "20240419_1800"
        
        # Phase 1: Upstream - record intents from ALL expected agents
        for agent in ["BTC15M", "ETH15M", "SOL15M", "XRP15M", "DOGE15M", "CRYPTO15MMM"]:
            # Handle CRYPTO15MMM specially
            if agent == "CRYPTO15MMM":
                asset = "BTC"
                ticker = "KXBTC15M-26APR191400-MM"
            else:
                asset = agent.replace("15M", "")
                ticker = f"KX{asset}15M-26APR191400-00"
            self.validator.record_intent(
                agent_id=agent,
                intent_id=f"test-{agent}",
                ticker=ticker,
                timeframe="15m",
                expiry_id="CRYPTO_15M:26APR191400",
                asset=asset,
                bucket_start=bucket_start,
                bucket_iso=bucket_iso,
            )
        
        # Phase 2: Validate upstream
        upstream_valid, upstream_warnings = self.validator.validate_before_allocation(
            bucket_start=bucket_start,
            bucket_iso=bucket_iso,
        )
        assert upstream_valid is True
        
        # Phase 3: Validate allocator logs
        logs_valid = self.validator.validate_allocator_logs(
            bucket_start=bucket_start,
            bucket_iso=bucket_iso,
            candidate_count=2,
            approved_count=1,
            blocked_count=1,
        )
        assert logs_valid is True
        
        # Phase 4: Record order
        self.validator.record_order(
            ticker="KXBTC15M-26APR191400-00",
            contracts=1,
            bucket_start=bucket_start,
            bucket_iso=bucket_iso,
        )
        
        # Phase 5: Downstream validation
        expiry_exposures = {
            "CRYPTO_15M:26APR191400": {"net_open_contracts": 1}
        }
        downstream_valid, violations = self.validator.validate_post_cycle(
            bucket_start=bucket_start,
            bucket_iso=bucket_iso,
            expiry_exposures=expiry_exposures,
        )
        assert downstream_valid is True
        assert len(violations) == 0
    
    def test_violation_tracking(self):
        """Test that violations are properly tracked."""
        bucket_start = 1713549600
        bucket_iso = "20240419_1800"
        
        # Record an invalid intent to trigger violation
        self.validator.record_intent(
            agent_id="BTC15M",
            intent_id="test-1",
            ticker="KXBTC15M-26APR191400-00",
            timeframe="1h",  # Invalid
            expiry_id="CRYPTO_15M:26APR191400",
            asset="BTC",
            bucket_start=bucket_start,
            bucket_iso=bucket_iso,
        )
        
        # Should have recorded a violation
        state = self.validator.upstream._get_or_create_state(bucket_start, bucket_iso)
        assert len(state.violations) == 1
        assert state.violations[0].violation_type == "invalid_metadata"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
