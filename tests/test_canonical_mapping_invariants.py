"""
Tests for canonical_mapping_invariants.py

Pure unit tests with synthetic inputs, no I/O, fully deterministic.
"""

import pytest

from merid.validation.canonical_mapping_invariants import (
    CanonicalMappingTable,
    ThesisSide,
    ContractType,
    PositionType,
    OrderAction,
    CanonicalMappingViolation,
    CanonicalMappingCheckResult,
    check_canonical_mapping,
    validate_semantic_combination,
    validate_intent_to_order_mapping,
    generate_synthetic_mapping_test_cases,
)


class TestCanonicalMappingInvariants:
    """Test suite for canonical mapping invariants."""
    
    def test_bullish_intent_produces_yes_buy_order(self):
        """
        intent=BULLISH, thesis_side=UP, edge>0 → contract=YES, order=buy_yes.
        """
        # Valid case: bullish entry
        result = CanonicalMappingTable.validate_semantic_combination(
            thesis_side=ThesisSide.UP,
            contract_type=ContractType.YES,
            position_type=PositionType.LONG_YES,
            order_action=OrderAction.BUY_YES,
            is_entry=True,
        )
        assert result.is_valid
        assert result.violation_type is None
        
        # Verify canonical mapping methods
        assert CanonicalMappingTable.get_contract_type(ThesisSide.UP) == ContractType.YES
        assert CanonicalMappingTable.get_position_type(ThesisSide.UP) == PositionType.LONG_YES
        assert CanonicalMappingTable.get_enter_order(ThesisSide.UP) == OrderAction.BUY_YES
    
    def test_bearish_intent_produces_no_buy_order(self):
        """
        intent=BEARISH, thesis_side=DOWN, edge<0 → contract=NO, order=buy_no.
        """
        # Valid case: bearish entry
        result = CanonicalMappingTable.validate_semantic_combination(
            thesis_side=ThesisSide.DOWN,
            contract_type=ContractType.NO,
            position_type=PositionType.LONG_NO,
            order_action=OrderAction.BUY_NO,
            is_entry=True,
        )
        assert result.is_valid
        assert result.violation_type is None
        
        # Verify canonical mapping methods
        assert CanonicalMappingTable.get_contract_type(ThesisSide.DOWN) == ContractType.NO
        assert CanonicalMappingTable.get_position_type(ThesisSide.DOWN) == PositionType.LONG_NO
        assert CanonicalMappingTable.get_enter_order(ThesisSide.DOWN) == OrderAction.BUY_NO
    
    def test_illegal_semantic_combinations_flagged(self):
        """
        BULLISH + buy_no, or edge>0 on UP + short YES → ILLEGAL_SEMANTIC_COMBINATION.
        """
        # Invalid case: bullish intent + buy_no
        result = CanonicalMappingTable.validate_semantic_combination(
            thesis_side=ThesisSide.UP,
            contract_type=ContractType.YES,
            position_type=PositionType.LONG_YES,
            order_action=OrderAction.BUY_NO,
            is_entry=True,
        )
        assert not result.is_valid
        assert result.violation_type == CanonicalMappingViolation.ILLEGAL_SEMANTIC_COMBINATION
        
        # Invalid case: bearish intent + buy_yes
        result = CanonicalMappingTable.validate_semantic_combination(
            thesis_side=ThesisSide.DOWN,
            contract_type=ContractType.NO,
            position_type=PositionType.LONG_NO,
            order_action=OrderAction.BUY_YES,
            is_entry=True,
        )
        assert not result.is_valid
        assert result.violation_type == CanonicalMappingViolation.ILLEGAL_SEMANTIC_COMBINATION
        
        # Invalid case: edge>0 on UP + short YES
        result = CanonicalMappingTable.validate_semantic_combination(
            thesis_side=ThesisSide.UP,
            contract_type=ContractType.YES,
            position_type=PositionType.SHORT_YES,
            order_action=OrderAction.SELL_YES,
            is_entry=True,
        )
        assert not result.is_valid
        assert result.violation_type == CanonicalMappingViolation.ILLEGAL_SEMANTIC_COMBINATION
        
        # Invalid case: edge<0 on DOWN + short NO
        result = CanonicalMappingTable.validate_semantic_combination(
            thesis_side=ThesisSide.DOWN,
            contract_type=ContractType.NO,
            position_type=PositionType.SHORT_NO,
            order_action=OrderAction.SELL_NO,
            is_entry=True,
        )
        assert not result.is_valid
        assert result.violation_type == CanonicalMappingViolation.ILLEGAL_SEMANTIC_COMBINATION
    
    def test_contract_type_mismatch(self):
        """Test that contract type mismatches are caught."""
        # Invalid case: bullish thesis with NO contract
        result = CanonicalMappingTable.validate_semantic_combination(
            thesis_side=ThesisSide.UP,
            contract_type=ContractType.NO,
            position_type=PositionType.LONG_YES,
            order_action=OrderAction.BUY_YES,
            is_entry=True,
        )
        assert not result.is_valid
        assert result.violation_type == CanonicalMappingViolation.CONTRACT_TYPE_MISMATCH
        
        # Invalid case: bearish thesis with YES contract
        result = CanonicalMappingTable.validate_semantic_combination(
            thesis_side=ThesisSide.DOWN,
            contract_type=ContractType.YES,
            position_type=PositionType.LONG_NO,
            order_action=OrderAction.BUY_NO,
            is_entry=True,
        )
        assert not result.is_valid
        assert result.violation_type == CanonicalMappingViolation.CONTRACT_TYPE_MISMATCH
    
    def test_position_type_mismatch(self):
        """Test that position type mismatches are caught."""
        # Invalid case: bullish thesis with LONG_NO position
        result = CanonicalMappingTable.validate_semantic_combination(
            thesis_side=ThesisSide.UP,
            contract_type=ContractType.YES,
            position_type=PositionType.LONG_NO,
            order_action=OrderAction.BUY_YES,
            is_entry=True,
        )
        assert not result.is_valid
        assert result.violation_type == CanonicalMappingViolation.POSITION_TYPE_MISMATCH
    
    def test_order_action_mismatch(self):
        """Test that order action mismatches are caught."""
        # Invalid case: bullish entry with SELL_YES action
        result = CanonicalMappingTable.validate_semantic_combination(
            thesis_side=ThesisSide.UP,
            contract_type=ContractType.YES,
            position_type=PositionType.LONG_YES,
            order_action=OrderAction.SELL_YES,
            is_entry=True,
        )
        assert not result.is_valid
        assert result.violation_type == CanonicalMappingViolation.ORDER_ACTION_MISMATCH
    
    def test_exit_orders(self):
        """Test that exit orders use correct actions."""
        # Valid case: bullish exit with SELL_YES
        result = CanonicalMappingTable.validate_semantic_combination(
            thesis_side=ThesisSide.UP,
            contract_type=ContractType.YES,
            position_type=PositionType.LONG_YES,
            order_action=OrderAction.SELL_YES,
            is_entry=False,
        )
        assert result.is_valid
        
        # Valid case: bearish exit with SELL_NO
        result = CanonicalMappingTable.validate_semantic_combination(
            thesis_side=ThesisSide.DOWN,
            contract_type=ContractType.NO,
            position_type=PositionType.LONG_NO,
            order_action=OrderAction.SELL_NO,
            is_entry=False,
        )
        assert result.is_valid
    
    def test_is_illegal_combination(self):
        """Test illegal combination detection."""
        # Illegal: bullish + buy_no
        assert CanonicalMappingTable.is_illegal_combination(
            thesis_side=ThesisSide.UP,
            order_action=OrderAction.BUY_NO,
        )
        
        # Illegal: bearish + buy_yes
        assert CanonicalMappingTable.is_illegal_combination(
            thesis_side=ThesisSide.DOWN,
            order_action=OrderAction.BUY_YES,
        )
        
        # Illegal: bullish + short_yes
        assert CanonicalMappingTable.is_illegal_combination(
            thesis_side=ThesisSide.UP,
            position_type=PositionType.SHORT_YES,
        )
        
        # Illegal: bearish + short_no
        assert CanonicalMappingTable.is_illegal_combination(
            thesis_side=ThesisSide.DOWN,
            position_type=PositionType.SHORT_NO,
        )
        
        # Legal: bullish + buy_yes
        assert not CanonicalMappingTable.is_illegal_combination(
            thesis_side=ThesisSide.UP,
            order_action=OrderAction.BUY_YES,
        )
        
        # Legal: bearish + buy_no
        assert not CanonicalMappingTable.is_illegal_combination(
            thesis_side=ThesisSide.DOWN,
            order_action=OrderAction.BUY_NO,
        )
    
    def test_canonical_mapping_table_completeness(self):
        """Test that canonical mapping table is complete."""
        # Check that all thesis sides have mappings
        assert ThesisSide.UP in CanonicalMappingTable.CANONICAL_MAPPING
        assert ThesisSide.DOWN in CanonicalMappingTable.CANONICAL_MAPPING
        
        # Check that all required fields are present
        for thesis_side, mapping in CanonicalMappingTable.CANONICAL_MAPPING.items():
            assert "contract_type" in mapping
            assert "position_type" in mapping
            assert "enter_order" in mapping
            assert "exit_order" in mapping
            assert "hedge_order" in mapping
    
    def test_validate_intent_to_order_mapping(self):
        """Test intent to order mapping validation."""
        # Valid case: bullish intent → buy_yes
        result = CanonicalMappingTable.validate_intent_to_order_mapping(
            intent="bullish",
            order_action=OrderAction.BUY_YES,
            is_entry=True,
        )
        assert result.is_valid
        
        # Valid case: bearish intent → buy_no
        result = CanonicalMappingTable.validate_intent_to_order_mapping(
            intent="bearish",
            order_action=OrderAction.BUY_NO,
            is_entry=True,
        )
        assert result.is_valid
        
        # Invalid case: bullish intent → buy_no
        result = CanonicalMappingTable.validate_intent_to_order_mapping(
            intent="bullish",
            order_action=OrderAction.BUY_NO,
            is_entry=True,
        )
        assert not result.is_valid


class TestConvenienceFunctions:
    """Test convenience functions for direct use."""
    
    def test_check_canonical_mapping(self):
        """Test convenience function for canonical mapping."""
        result = check_canonical_mapping(
            thesis_side="up",
            contract_type="yes",
            position_type="long_yes",
            order_action="buy_yes",
            is_entry=True,
        )
        assert result.is_valid
    
    def test_validate_semantic_combination(self):
        """Test convenience function for semantic combination validation."""
        result = validate_semantic_combination(
            thesis_side="up",
            contract_type="yes",
            position_type="long_yes",
            order_action="buy_yes",
            is_entry=True,
        )
        assert result.is_valid
    
    def test_validate_intent_to_order_mapping(self):
        """Test convenience function for intent to order mapping."""
        result = validate_intent_to_order_mapping(
            intent="bullish",
            order_action="buy_yes",
            is_entry=True,
        )
        assert result.is_valid


class TestSyntheticTestCases:
    """Test synthetic test case generator."""
    
    def test_generate_synthetic_mapping_test_cases(self):
        """Test that synthetic test cases are generated correctly."""
        test_cases = generate_synthetic_mapping_test_cases()
        
        assert len(test_cases) > 0
        assert all("thesis_side" in tc for tc in test_cases)
        assert all("contract_type" in tc for tc in test_cases)
        assert all("position_type" in tc for tc in test_cases)
        assert all("order_action" in tc for tc in test_cases)
        assert all("is_entry" in tc for tc in test_cases)
        assert all("expected_valid" in tc for tc in test_cases)
    
    def test_synthetic_test_cases_valid_and_invalid(self):
        """Test that synthetic test cases include both valid and invalid cases."""
        test_cases = generate_synthetic_mapping_test_cases()
        
        valid_cases = [tc for tc in test_cases if tc["expected_valid"]]
        invalid_cases = [tc for tc in test_cases if not tc["expected_valid"]]
        
        assert len(valid_cases) > 0
        assert len(invalid_cases) > 0
    
    def test_synthetic_test_cases_cover_all_combinations(self):
        """Test that synthetic test cases cover all canonical combinations."""
        test_cases = generate_synthetic_mapping_test_cases()
        
        # Check for bullish entry
        bullish_entry = [tc for tc in test_cases if tc["thesis_side"] == "up" and tc["is_entry"]]
        assert len(bullish_entry) > 0
        
        # Check for bearish entry
        bearish_entry = [tc for tc in test_cases if tc["thesis_side"] == "down" and tc["is_entry"]]
        assert len(bearish_entry) > 0
        
        # Check for exit orders
        exit_orders = [tc for tc in test_cases if not tc["is_entry"]]
        assert len(exit_orders) > 0


class TestCanonicalMappingCheckResult:
    """Test CanonicalMappingCheckResult dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = CanonicalMappingCheckResult(
            is_valid=True,
            violation_type=None,
            message="Test message",
            context={"key": "value"},
        )
        
        result_dict = result.to_dict()
        assert result_dict["is_valid"] is True
        assert result_dict["violation_type"] is None
        assert result_dict["message"] == "Test message"
        assert result_dict["context"] == {"key": "value"}
    
    def test_to_dict_with_violation(self):
        """Test conversion to dictionary with violation."""
        result = CanonicalMappingCheckResult(
            is_valid=False,
            violation_type=CanonicalMappingViolation.ILLEGAL_SEMANTIC_COMBINATION,
            message="Test violation",
            context={},
        )
        
        result_dict = result.to_dict()
        assert result_dict["is_valid"] is False
        assert result_dict["violation_type"] == "illegal_semantic_combination"


class TestEnums:
    """Test enum values."""
    
    def test_thesis_side_enum(self):
        """Test ThesisSide enum values."""
        assert ThesisSide.UP.value == "up"
        assert ThesisSide.DOWN.value == "down"
    
    def test_contract_type_enum(self):
        """Test ContractType enum values."""
        assert ContractType.YES.value == "yes"
        assert ContractType.NO.value == "no"
    
    def test_position_type_enum(self):
        """Test PositionType enum values."""
        assert PositionType.LONG_YES.value == "long_yes"
        assert PositionType.LONG_NO.value == "long_no"
        assert PositionType.SHORT_YES.value == "short_yes"
        assert PositionType.SHORT_NO.value == "short_no"
    
    def test_order_action_enum(self):
        """Test OrderAction enum values."""
        assert OrderAction.BUY_YES.value == "buy_yes"
        assert OrderAction.BUY_NO.value == "buy_no"
        assert OrderAction.SELL_YES.value == "sell_yes"
        assert OrderAction.SELL_NO.value == "sell_no"
