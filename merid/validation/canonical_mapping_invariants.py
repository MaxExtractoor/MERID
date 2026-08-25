"""
Canonical Mapping Table Invariants for Kalshi Binary Options

This module provides the SINGLE SOURCE OF TRUTH for semantic mappings between
trading concepts: long/short, yes/no, up/down, buy/sell.

Canonical Mapping Table (Kalshi Binary Options):

| Concept        | "Up" / Bullish Thesis                   | "Down" / Bearish Thesis                   |
|----------------|-----------------------------------------|-------------------------------------------|
| Thesis_side    | UP                                      | DOWN                                      |
| Contract       | YES (event happens)                     | NO (event does not happen)                |
| Position       | Long YES                                | Long NO                                   |
| Enter Order    | buy_yes                                 | buy_no                                    |
| Exit Order     | sell_yes (close long YES)               | sell_no (close long NO)                   |
| Hedge Order    | buy_no (hedge long YES)                 | buy_yes (hedge long NO)                   |

Key Invariants:
- Given a bullish intent and positive edge on event happening: thesis_side must be UP, contract must be YES, order must be buy_yes
- Strictly forbid illegal combos like bullish intent + buy_no or edge>0 on UP + short YES
- Canonical mapping must be strictly followed (no semantic flips)
- All code paths must use this mapping table as the single source of truth

Usage::

    from merid.validation.canonical_mapping_invariants import (
        CanonicalMappingTable,
        check_canonical_mapping,
        validate_semantic_combination,
        generate_synthetic_mapping_test_cases
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any, Literal
from enum import Enum
from utils.logger import get_logger

logger = get_logger("merid.validation.canonical_mapping_invariants")


class ThesisSide(str, Enum):
    """Canonical thesis side values."""
    UP = "up"
    DOWN = "down"


class ContractType(str, Enum):
    """Canonical contract type values."""
    YES = "yes"
    NO = "no"


class PositionType(str, Enum):
    """Canonical position type values."""
    LONG_YES = "long_yes"
    LONG_NO = "long_no"
    SHORT_YES = "short_yes"
    SHORT_NO = "short_no"


class OrderAction(str, Enum):
    """Canonical order action values."""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    SELL_YES = "sell_yes"
    SELL_NO = "sell_no"


class CanonicalMappingViolation(str, Enum):
    """Types of canonical mapping violations."""
    ILLEGAL_SEMANTIC_COMBINATION = "illegal_semantic_combination"
    THESIS_SIDE_MISMATCH = "thesis_side_mismatch"
    CONTRACT_TYPE_MISMATCH = "contract_type_mismatch"
    POSITION_TYPE_MISMATCH = "position_type_mismatch"
    ORDER_ACTION_MISMATCH = "order_action_mismatch"
    ENTRY_EXIT_INVERSION = "entry_exit_inversion"


@dataclass
class CanonicalMappingCheckResult:
    """Result of canonical mapping check."""
    is_valid: bool
    violation_type: Optional[CanonicalMappingViolation]
    message: str
    context: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "violation_type": self.violation_type.value if self.violation_type else None,
            "message": self.message,
            "context": self.context,
        }


class CanonicalMappingTable:
    """Single source of truth for canonical semantic mappings.
    
    This class enforces the canonical mapping table and provides
    validation methods to ensure all code paths follow it.
    """
    
    # Canonical mapping table (immutable)
    CANONICAL_MAPPING = {
        # Bullish / Up thesis
        ThesisSide.UP: {
            "contract_type": ContractType.YES,
            "position_type": PositionType.LONG_YES,
            "enter_order": OrderAction.BUY_YES,
            "exit_order": OrderAction.SELL_YES,
            "hedge_order": OrderAction.BUY_NO,
        },
        # Bearish / Down thesis
        ThesisSide.DOWN: {
            "contract_type": ContractType.NO,
            "position_type": PositionType.LONG_NO,
            "enter_order": OrderAction.BUY_NO,
            "exit_order": OrderAction.SELL_NO,
            "hedge_order": OrderAction.BUY_YES,
        },
    }
    
    # Illegal combinations (forbidden by invariants)
    ILLEGAL_COMBINATIONS = [
        # Bullish intent + buy_no
        (ThesisSide.UP, OrderAction.BUY_NO),
        # Bearish intent + buy_yes
        (ThesisSide.DOWN, OrderAction.BUY_YES),
        # Edge > 0 on UP + short YES
        (ThesisSide.UP, PositionType.SHORT_YES),
        # Edge < 0 on DOWN + short NO
        (ThesisSide.DOWN, PositionType.SHORT_NO),
    ]
    
    @classmethod
    def get_contract_type(cls, thesis_side: ThesisSide) -> ContractType:
        """Get canonical contract type for thesis side."""
        return cls.CANONICAL_MAPPING[thesis_side]["contract_type"]
    
    @classmethod
    def get_position_type(cls, thesis_side: ThesisSide) -> PositionType:
        """Get canonical position type for thesis side."""
        return cls.CANONICAL_MAPPING[thesis_side]["position_type"]
    
    @classmethod
    def get_enter_order(cls, thesis_side: ThesisSide) -> OrderAction:
        """Get canonical enter order for thesis side."""
        return cls.CANONICAL_MAPPING[thesis_side]["enter_order"]
    
    @classmethod
    def get_exit_order(cls, thesis_side: ThesisSide) -> OrderAction:
        """Get canonical exit order for thesis side."""
        return cls.CANONICAL_MAPPING[thesis_side]["exit_order"]
    
    @classmethod
    def get_hedge_order(cls, thesis_side: ThesisSide) -> OrderAction:
        """Get canonical hedge order for thesis side."""
        return cls.CANONICAL_MAPPING[thesis_side]["hedge_order"]
    
    @classmethod
    def is_illegal_combination(
        cls,
        thesis_side: ThesisSide,
        order_action: Optional[OrderAction] = None,
        position_type: Optional[PositionType] = None,
    ) -> bool:
        """Check if a combination is illegal per canonical mapping."""
        if order_action:
            if (thesis_side, order_action) in cls.ILLEGAL_COMBINATIONS:
                return True
        
        if position_type:
            if (thesis_side, position_type) in cls.ILLEGAL_COMBINATIONS:
                return True
        
        return False
    
    @classmethod
    def validate_semantic_combination(
        cls,
        thesis_side: ThesisSide,
        contract_type: ContractType,
        position_type: PositionType,
        order_action: OrderAction,
        is_entry: bool,
    ) -> CanonicalMappingCheckResult:
        """Validate a complete semantic combination against canonical mapping.
        
        Args:
            thesis_side: Thesis side (UP/DOWN)
            contract_type: Contract type (YES/NO)
            position_type: Position type (LONG_YES/LONG_NO/SHORT_YES/SHORT_NO)
            order_action: Order action (BUY_YES/BUY_NO/SELL_YES/SELL_NO)
            is_entry: True if this is an entry order, False if exit
            
        Returns:
            CanonicalMappingCheckResult with validation result
        """
        context = {
            "thesis_side": thesis_side.value,
            "contract_type": contract_type.value,
            "position_type": position_type.value,
            "order_action": order_action.value,
            "is_entry": is_entry,
        }
        
        # Check illegal combinations
        if cls.is_illegal_combination(thesis_side, order_action):
            return CanonicalMappingCheckResult(
                is_valid=False,
                violation_type=CanonicalMappingViolation.ILLEGAL_SEMANTIC_COMBINATION,
                message=f"Illegal semantic combination: thesis_side={thesis_side.value} + order_action={order_action.value}",
                context=context,
            )
        
        if cls.is_illegal_combination(thesis_side, position_type):
            return CanonicalMappingCheckResult(
                is_valid=False,
                violation_type=CanonicalMappingViolation.ILLEGAL_SEMANTIC_COMBINATION,
                message=f"Illegal semantic combination: thesis_side={thesis_side.value} + position_type={position_type.value}",
                context=context,
            )
        
        # Check contract type matches thesis side
        expected_contract = cls.get_contract_type(thesis_side)
        if contract_type != expected_contract:
            return CanonicalMappingCheckResult(
                is_valid=False,
                violation_type=CanonicalMappingViolation.CONTRACT_TYPE_MISMATCH,
                message=f"Contract type mismatch: thesis_side={thesis_side.value} expects {expected_contract.value}, got {contract_type.value}",
                context=context,
            )
        
        # Check position type matches thesis side
        expected_position = cls.get_position_type(thesis_side)
        if position_type != expected_position:
            return CanonicalMappingCheckResult(
                is_valid=False,
                violation_type=CanonicalMappingViolation.POSITION_TYPE_MISMATCH,
                message=f"Position type mismatch: thesis_side={thesis_side.value} expects {expected_position.value}, got {position_type.value}",
                context=context,
            )
        
        # Check order action matches thesis side and entry/exit
        if is_entry:
            expected_order = cls.get_enter_order(thesis_side)
        else:
            expected_order = cls.get_exit_order(thesis_side)
        
        if order_action != expected_order:
            # Allow hedge orders as equivalent exit actions
            if not is_entry:
                hedge_order = cls.get_hedge_order(thesis_side)
                if order_action == hedge_order:
                    # Hedge order is valid for exit
                    return CanonicalMappingCheckResult(
                        is_valid=True,
                        violation_type=None,
                        message="Hedge order is valid for exit",
                        context=context,
                    )
            
            return CanonicalMappingCheckResult(
                is_valid=False,
                violation_type=CanonicalMappingViolation.ORDER_ACTION_MISMATCH,
                message=f"Order action mismatch: thesis_side={thesis_side.value} is_entry={is_entry} expects {expected_order.value}, got {order_action.value}",
                context=context,
            )
        
        return CanonicalMappingCheckResult(
            is_valid=True,
            violation_type=None,
            message="Semantic combination matches canonical mapping",
            context=context,
        )
    
    @classmethod
    def validate_intent_to_order_mapping(
        cls,
        intent: str,  # "bullish" or "bearish"
        order_action: OrderAction,
        is_entry: bool,
    ) -> CanonicalMappingCheckResult:
        """Validate intent → order action mapping.
        
        This is a convenience method for validating the intent → order path.
        """
        # Map intent to thesis side
        thesis_side = ThesisSide.UP if intent == "bullish" else ThesisSide.DOWN
        
        # Derive contract type and position type from thesis side
        contract_type = cls.get_contract_type(thesis_side)
        position_type = cls.get_position_type(thesis_side)
        
        return cls.validate_semantic_combination(
            thesis_side, contract_type, position_type, order_action, is_entry
        )


# Convenience functions for direct use

def check_canonical_mapping(
    thesis_side: str,
    contract_type: str,
    position_type: str,
    order_action: str,
    is_entry: bool,
) -> CanonicalMappingCheckResult:
    """Check canonical mapping invariant."""
    thesis_side_enum = ThesisSide(thesis_side.lower())
    contract_type_enum = ContractType(contract_type.lower())
    position_type_enum = PositionType(position_type.lower())
    order_action_enum = OrderAction(order_action.lower())
    
    return CanonicalMappingTable.validate_semantic_combination(
        thesis_side_enum, contract_type_enum, position_type_enum, order_action_enum, is_entry
    )


def validate_semantic_combination(
    thesis_side: str,
    contract_type: str,
    position_type: str,
    order_action: str,
    is_entry: bool,
) -> CanonicalMappingCheckResult:
    """Validate semantic combination (alias for check_canonical_mapping)."""
    return check_canonical_mapping(
        thesis_side, contract_type, position_type, order_action, is_entry
    )


def validate_intent_to_order_mapping(
    intent: str,
    order_action: str,
    is_entry: bool,
) -> CanonicalMappingCheckResult:
    """Validate intent → order action mapping."""
    order_action_enum = OrderAction(order_action.lower())
    return CanonicalMappingTable.validate_intent_to_order_mapping(
        intent, order_action_enum, is_entry
    )


# Synthetic test data generator for invariant testing

def generate_synthetic_mapping_test_cases() -> List[Dict[str, Any]]:
    """Generate synthetic test cases for canonical mapping invariants.
    
    Returns:
        List of test case dictionaries with controlled semantic combinations.
    """
    test_cases = []
    
    # Valid cases
    test_cases.append({
        "thesis_side": "up",
        "contract_type": "yes",
        "position_type": "long_yes",
        "order_action": "buy_yes",
        "is_entry": True,
        "expected_valid": True,
        "description": "Bullish entry: UP → YES → LONG_YES → BUY_YES - valid",
    })
    
    test_cases.append({
        "thesis_side": "down",
        "contract_type": "no",
        "position_type": "long_no",
        "order_action": "buy_no",
        "is_entry": True,
        "expected_valid": True,
        "description": "Bearish entry: DOWN → NO → LONG_NO → BUY_NO - valid",
    })
    
    test_cases.append({
        "thesis_side": "up",
        "contract_type": "yes",
        "position_type": "long_yes",
        "order_action": "sell_yes",
        "is_entry": False,
        "expected_valid": True,
        "description": "Bullish exit: UP → YES → LONG_YES → SELL_YES - valid",
    })
    
    test_cases.append({
        "thesis_side": "down",
        "contract_type": "no",
        "position_type": "long_no",
        "order_action": "sell_no",
        "is_entry": False,
        "expected_valid": True,
        "description": "Bearish exit: DOWN → NO → LONG_NO → SELL_NO - valid",
    })
    
    test_cases.append({
        "thesis_side": "up",
        "contract_type": "yes",
        "position_type": "long_yes",
        "order_action": "buy_no",
        "is_entry": False,
        "expected_valid": True,
        "description": "Bullish hedge exit: UP → YES → LONG_YES → BUY_NO (hedge) - valid",
    })
    
    # Invalid cases (should trigger violations)
    test_cases.append({
        "thesis_side": "up",
        "contract_type": "yes",
        "position_type": "long_yes",
        "order_action": "buy_no",
        "is_entry": True,
        "expected_valid": False,
        "description": "Bullish entry with BUY_NO - illegal combination",
    })
    
    test_cases.append({
        "thesis_side": "down",
        "contract_type": "no",
        "position_type": "long_no",
        "order_action": "buy_yes",
        "is_entry": True,
        "expected_valid": False,
        "description": "Bearish entry with BUY_YES - illegal combination",
    })
    
    test_cases.append({
        "thesis_side": "up",
        "contract_type": "no",
        "position_type": "long_yes",
        "order_action": "buy_yes",
        "is_entry": True,
        "expected_valid": False,
        "description": "Bullish thesis with NO contract - contract type mismatch",
    })
    
    test_cases.append({
        "thesis_side": "down",
        "contract_type": "yes",
        "position_type": "long_no",
        "order_action": "buy_no",
        "is_entry": True,
        "expected_valid": False,
        "description": "Bearish thesis with YES contract - contract type mismatch",
    })
    
    test_cases.append({
        "thesis_side": "up",
        "contract_type": "yes",
        "position_type": "short_yes",
        "order_action": "sell_yes",
        "is_entry": True,
        "expected_valid": False,
        "description": "Bullish thesis with SHORT_YES - illegal combination",
    })
    
    test_cases.append({
        "thesis_side": "down",
        "contract_type": "no",
        "position_type": "short_no",
        "order_action": "sell_no",
        "is_entry": True,
        "expected_valid": False,
        "description": "Bearish thesis with SHORT_NO - illegal combination",
    })
    
    return test_cases


# Invariant documentation

CANONICAL_MAPPING_INVARIANTS = """
Canonical Mapping Invariants for Kalshi Binary Options (2026-07-23)

1. Single Source of Truth:
   - CanonicalMappingTable.CANONICAL_MAPPING is the authoritative mapping
   - All code paths must use this table for semantic conversions
   - No hand-coded mapping logic allowed

2. Bullish / Up Thesis:
   - thesis_side = UP
   - contract_type = YES
   - position_type = LONG_YES
   - enter_order = BUY_YES
   - exit_order = SELL_YES
   - hedge_order = BUY_NO

3. Bearish / Down Thesis:
   - thesis_side = DOWN
   - contract_type = NO
   - position_type = LONG_NO
   - enter_order = BUY_NO
   - exit_order = SELL_NO
   - hedge_order = BUY_YES

4. Illegal Combinations (Forbidden):
   - Bullish intent + BUY_NO
   - Bearish intent + BUY_YES
   - Edge > 0 on UP + SHORT_YES
   - Edge < 0 on DOWN + SHORT_NO

5. Entry/Exit Invariants:
   - Entry orders must use BUY actions (BUY_YES or BUY_NO)
   - Exit orders must use SELL actions (SELL_YES or SELL_NO) or hedge orders
   - Hedge orders are economically equivalent exit actions

6. Validation Methods:
   - validate_semantic_combination(): Full validation of all fields
   - validate_intent_to_order_mapping(): Intent → order validation
   - is_illegal_combination(): Check for forbidden combos

7. Test Coverage:
   - All valid combinations must pass validation
   - All illegal combinations must fail validation
   - Synthetic test cases cover all edge cases
"""
