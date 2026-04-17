"""Tests for defi/yield_vaults.py."""
import pytest
from decimal import Decimal
from datetime import datetime
from unittest.mock import Mock, patch
from defi.yield_vaults import (
    VaultType, YieldStrategy, RebalanceReason, YieldAllocation, VaultStrategy,
    UserVaultPosition, RebalanceProposal, YieldVaults, get_yield_vaults, _yield_vaults
)


class TestVaultType:
    """Test VaultType enum."""

    def test_vault_type_values(self):
        """Test vault type enum values."""
        assert VaultType.CONSERVATIVE.value == "conservative"
        assert VaultType.BALANCED.value == "balanced"
        assert VaultType.AGGRESSIVE.value == "aggressive"
        assert VaultType.CUSTOM.value == "custom"


class TestYieldStrategy:
    """Test YieldStrategy enum."""

    def test_yield_strategy_values(self):
        """Test yield strategy enum values."""
        assert YieldStrategy.STAKING.value == "staking"
        assert YieldStrategy.LIQUID_STAKING.value == "liquid_staking"
        assert YieldStrategy.RESTAKING.value == "restaking"
        assert YieldStrategy.LENDING.value == "lending"
        assert YieldStrategy.LP_FARMING.value == "lp_farming"
        assert YieldStrategy.CONCENTRATED_LIQUIDITY.value == "concentrated_liquidity"
        assert YieldStrategy.RWA_YIELD.value == "rwa_yield"


class TestRebalanceReason:
    """Test RebalanceReason enum."""

    def test_rebalance_reason_values(self):
        """Test rebalance reason enum values."""
        assert RebalanceReason.SCHEDULED.value == "scheduled"
        assert RebalanceReason.DRIFT_THRESHOLD.value == "drift_threshold"
        assert RebalanceReason.REGIME_CHANGE.value == "regime_change"
        assert RebalanceReason.RISK_LIMIT.value == "risk_limit"
        assert RebalanceReason.OPPORTUNITY.value == "opportunity"
        assert RebalanceReason.EMERGENCY.value == "emergency"


class TestYieldAllocation:
    """Test YieldAllocation dataclass."""

    def test_creation(self):
        """Test YieldAllocation creation."""
        now = datetime.utcnow()
        alloc = YieldAllocation(
            strategy=YieldStrategy.LENDING,
            protocol="aave",
            asset="USDC",
            target_percentage=Decimal("40.0"),
            current_percentage=Decimal("40.0"),
            current_value_usd=Decimal("4000.0"),
            apy=Decimal("4.2"),
            realized_yield_usd=Decimal("100.0"),
            unrealized_pnl_usd=Decimal("50.0"),
            risk_score=0.3,
            tvl_usd=Decimal("5000000000"),
            protocol_risk="low",
            last_rebalance=now,
            last_compound=now,
        )
        assert alloc.strategy == YieldStrategy.LENDING
        assert alloc.protocol == "aave"
        assert alloc.asset == "USDC"
        assert alloc.target_percentage == Decimal("40.0")
        assert alloc.risk_score == 0.3


class TestVaultStrategy:
    """Test VaultStrategy dataclass."""

    def test_creation(self):
        """Test VaultStrategy creation."""
        vault = VaultStrategy(
            vault_id="test_vault",
            vault_type=VaultType.CONSERVATIVE,
            name="Test Vault",
            description="A test vault",
        )
        assert vault.vault_id == "test_vault"
        assert vault.vault_type == VaultType.CONSERVATIVE
        assert vault.name == "Test Vault"
        assert vault.max_protocol_concentration == Decimal("30.0")
        assert vault.max_strategy_concentration == Decimal("40.0")
        assert vault.max_risk_score == 0.7


class TestUserVaultPosition:
    """Test UserVaultPosition dataclass."""

    def test_creation(self):
        """Test UserVaultPosition creation."""
        position = UserVaultPosition(
            position_id="pos_123",
            user_id="user_456",
            vault_id="vault_789",
            shares=Decimal("1000.0"),
            deposited_usd=Decimal("1000.0"),
            current_value_usd=Decimal("1050.0"),
            realized_yield_usd=Decimal("30.0"),
            unrealized_pnl_usd=Decimal("20.0"),
            total_return_percentage=Decimal("5.0"),
        )
        assert position.position_id == "pos_123"
        assert position.user_id == "user_456"
        assert position.vault_id == "vault_789"
        assert position.shares == Decimal("1000.0")


class TestRebalanceProposal:
    """Test RebalanceProposal dataclass."""

    def test_creation(self):
        """Test RebalanceProposal creation."""
        now = datetime.utcnow()
        proposal = RebalanceProposal(
            proposal_id="rebalance_123",
            vault_id="vault_456",
            reason=RebalanceReason.SCHEDULED,
            current_allocations=[],
            proposed_allocations=[],
            expected_apy_change=Decimal("1.5"),
            expected_risk_change=0.1,
            estimated_gas_cost_usd=Decimal("50.0"),
            ai_rationale="Optimize for higher yield",
            market_conditions={"trend": "bullish"},
            created_at=now,
        )
        assert proposal.proposal_id == "rebalance_123"
        assert proposal.vault_id == "vault_456"
        assert proposal.reason == RebalanceReason.SCHEDULED
        assert proposal.approved is False


class TestYieldVaults:
    """Test YieldVaults class."""

    def test_initialization(self):
        """Test YieldVaults initialization."""
        vaults = YieldVaults()
        assert len(vaults._vaults) == 3  # 3 default vaults
        assert "conservative_yield_v1" in vaults._vaults
        assert "balanced_yield_v1" in vaults._vaults
        assert "aggressive_yield_v1" in vaults._vaults

    def test_create_vault(self):
        """Test create_vault method."""
        vaults = YieldVaults()
        now = datetime.utcnow()
        
        allocation = YieldAllocation(
            strategy=YieldStrategy.STAKING,
            protocol="lido",
            asset="ETH",
            target_percentage=Decimal("100.0"),
            current_percentage=Decimal("0"),
            current_value_usd=Decimal("0"),
            apy=Decimal("5.0"),
            realized_yield_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0"),
            risk_score=0.2,
            tvl_usd=Decimal("1000000000"),
            protocol_risk="low",
            last_rebalance=now,
            last_compound=now,
        )
        
        vault = vaults.create_vault(
            vault_id="custom_vault",
            vault_type=VaultType.CUSTOM,
            name="Custom Vault",
            description="A custom vault",
            target_allocations=[allocation],
            max_risk_score=0.5,
        )
        
        assert vault.vault_id == "custom_vault"
        assert vault.vault_type == VaultType.CUSTOM
        assert vault in vaults._vaults.values()

    def test_deposit_first_deposit(self):
        """Test deposit with first deposit (1:1 shares)."""
        vaults = YieldVaults()
        
        position = vaults.deposit(
            user_id="user_123",
            vault_id="conservative_yield_v1",
            amount_usd=Decimal("10000.0"),
        )
        
        assert position.user_id == "user_123"
        assert position.vault_id == "conservative_yield_v1"
        assert position.shares == Decimal("10000.0")
        assert position.deposited_usd == Decimal("10000.0")

    def test_deposit_subsequent_deposit(self):
        """Test deposit with subsequent deposit (proportional shares)."""
        vaults = YieldVaults()
        
        # First deposit
        vaults.deposit("user_1", "conservative_yield_v1", Decimal("10000.0"))
        
        # Increase vault value
        vault = vaults._vaults["conservative_yield_v1"]
        vault.total_value_usd = Decimal("12000.0")  # Gained 20%
        
        # Second deposit
        position = vaults.deposit("user_2", "conservative_yield_v1", Decimal("5000.0"))
        
        # Shares should be less than deposit due to value increase
        assert position.shares < Decimal("5000.0")

    def test_deposit_vault_not_found(self):
        """Test deposit with non-existent vault."""
        vaults = YieldVaults()
        
        with pytest.raises(ValueError, match="Vault 'non_existent' not found"):
            vaults.deposit("user_123", "non_existent", Decimal("1000.0"))

    def test_get_vault(self):
        """Test get_vault method."""
        vaults = YieldVaults()
        
        vault = vaults.get_vault("conservative_yield_v1")
        assert vault is not None
        assert vault.vault_id == "conservative_yield_v1"
        
        # Non-existent vault
        assert vaults.get_vault("non_existent") is None

    def test_get_all_vaults(self):
        """Test get_all_vaults method."""
        vaults = YieldVaults()
        
        all_vaults = vaults.get_all_vaults()
        assert len(all_vaults) == 3

    def test_get_user_positions(self):
        """Test get_user_positions method."""
        vaults = YieldVaults()
        
        # Create positions
        vaults.deposit("user_1", "conservative_yield_v1", Decimal("1000.0"))
        vaults.deposit("user_1", "balanced_yield_v1", Decimal("2000.0"))
        vaults.deposit("user_2", "conservative_yield_v1", Decimal("500.0"))
        
        positions = vaults.get_user_positions("user_1")
        assert len(positions) == 2
        assert all(p.user_id == "user_1" for p in positions)

    def test_compound_vault(self):
        """Test compound_vault method."""
        vaults = YieldVaults()
        vault = vaults._vaults["conservative_yield_v1"]
        
        # Add yield to allocations
        for alloc in vault.target_allocations:
            alloc.realized_yield_usd = Decimal("100.0")
        
        compounded = vaults.compound_vault("conservative_yield_v1")
        
        # Should compound 300 (100 from each of 3 allocations)
        assert compounded == Decimal("300.0")
        assert vault.total_value_usd == Decimal("300.0")

    def test_compound_vault_below_min(self):
        """Test compound_vault when yield below minimum."""
        vaults = YieldVaults()
        
        # Yield below minimum
        compounded = vaults.compound_vault("conservative_yield_v1")
        
        assert compounded == Decimal("0")

    def test_compound_vault_auto_compound_disabled(self):
        """Test compound_vault when auto-compound disabled."""
        vaults = YieldVaults()
        vault = vaults._vaults["conservative_yield_v1"]
        vault.auto_compound = False
        
        compounded = vaults.compound_vault("conservative_yield_v1")
        
        assert compounded == Decimal("0")

    def test_calculate_weighted_apy(self):
        """Test _calculate_weighted_apy method."""
        vaults = YieldVaults()
        
        now = datetime.utcnow()
        allocations = [
            YieldAllocation(
                strategy=YieldStrategy.LENDING,
                protocol="aave",
                asset="USDC",
                target_percentage=Decimal("50.0"),
                current_percentage=Decimal("50.0"),
                current_value_usd=Decimal("5000.0"),
                apy=Decimal("4.0"),
                realized_yield_usd=Decimal("0"),
                unrealized_pnl_usd=Decimal("0"),
                risk_score=0.3,
                tvl_usd=Decimal("1000000000"),
                protocol_risk="low",
                last_rebalance=now,
                last_compound=now,
            ),
            YieldAllocation(
                strategy=YieldStrategy.STAKING,
                protocol="lido",
                asset="ETH",
                target_percentage=Decimal("50.0"),
                current_percentage=Decimal("50.0"),
                current_value_usd=Decimal("5000.0"),
                apy=Decimal("6.0"),
                realized_yield_usd=Decimal("0"),
                unrealized_pnl_usd=Decimal("0"),
                risk_score=0.2,
                tvl_usd=Decimal("1000000000"),
                protocol_risk="low",
                last_rebalance=now,
                last_compound=now,
            ),
        ]
        
        weighted_apy = vaults._calculate_weighted_apy(allocations)
        
        # (4.0 * 0.5) + (6.0 * 0.5) = 5.0
        assert weighted_apy == Decimal("5.0")

    def test_calculate_weighted_risk(self):
        """Test _calculate_weighted_risk method."""
        vaults = YieldVaults()
        
        now = datetime.utcnow()
        allocations = [
            YieldAllocation(
                strategy=YieldStrategy.LENDING,
                protocol="aave",
                asset="USDC",
                target_percentage=Decimal("50.0"),
                current_percentage=Decimal("50.0"),
                current_value_usd=Decimal("5000.0"),
                apy=Decimal("4.0"),
                realized_yield_usd=Decimal("0"),
                unrealized_pnl_usd=Decimal("0"),
                risk_score=0.3,
                tvl_usd=Decimal("1000000000"),
                protocol_risk="low",
                last_rebalance=now,
                last_compound=now,
            ),
            YieldAllocation(
                strategy=YieldStrategy.STAKING,
                protocol="lido",
                asset="ETH",
                target_percentage=Decimal("50.0"),
                current_percentage=Decimal("50.0"),
                current_value_usd=Decimal("5000.0"),
                apy=Decimal("6.0"),
                realized_yield_usd=Decimal("0"),
                unrealized_pnl_usd=Decimal("0"),
                risk_score=0.2,
                tvl_usd=Decimal("1000000000"),
                protocol_risk="low",
                last_rebalance=now,
                last_compound=now,
            ),
        ]
        
        weighted_risk = vaults._calculate_weighted_risk(allocations)
        
        # (0.3 * 0.5) + (0.2 * 0.5) = 0.25
        assert weighted_risk == 0.25


class TestGetYieldVaults:
    """Test get_yield_vaults function."""

    def setup_method(self):
        """Reset singleton before each test."""
        global _yield_vaults
        import defi.yield_vaults as yv
        yv._yield_vaults = None

    def test_singleton(self):
        """Test get_yield_vaults returns singleton."""
        vaults1 = get_yield_vaults()
        vaults2 = get_yield_vaults()
        assert vaults1 is vaults2
