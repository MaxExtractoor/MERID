"""
Intent-to-Exposure Contract — Semantic invariants for binary options trading.

This module formalizes the contract between strategy intent and venue exposure,
ensuring that every order executes exactly as intended.

CRITICAL FIX (2026-07-19): Prevents "buy NO" → "buy YES" mapping bugs by
enforcing explicit semantic contracts at every layer.

Key Invariants:
- BULLISH_EVENT ⇒ net +YES exposure (buy_yes or sell_no)
- BEARISH_EVENT ⇒ net +NO exposure (buy_no or sell_yes)
- Entry: must increase absolute exposure on intended leg
- Exit: must reduce exposure on the leg you're currently holding

Usage::

    from merid.prediction.intent_contract import (
        IntentContract, ExposureChange, KalshiSidePayload,
        map_intent_to_exposure, map_exposure_to_kalshi_side,
        validate_intent_exposure_consistency
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from typing import Literal, Optional, Dict, Any, Tuple
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("intent_contract")

try:
    from merid.event_venues.kalshi.binary_price_space import (
        yes_delta,
        to_signed_yes_exposure,
        from_signed_yes_exposure,
    )
    BINARY_PRICE_SPACE_AVAILABLE = True
except ImportError:
    BINARY_PRICE_SPACE_AVAILABLE = False

try:
    from merid.prediction.signal_terminology import (
        StrategyIntent, Side, Action
    )
except ImportError:
    # Fallback definitions if signal_terminology not available
    class StrategyIntent(str, Enum):
        BULLISH_EVENT = "bullish_event"
        BEARISH_EVENT = "bearish_event"
        NEUTRAL = "neutral"
    
    class Side(str, Enum):
        YES = "yes"
        NO = "no"
    
    class Action(str, Enum):
        BUY = "buy"
        SELL = "sell"


class EntryExit(str, Enum):
    """Entry vs exit classification."""
    ENTRY = "entry"
    EXIT = "exit"


class ExitReason(str, Enum):
    """Reason for exit order - must be set for EXIT direction."""
    EXIT_TP = "exit_tp"  # Take profit
    EXIT_SL = "exit_sl"  # Stop loss
    EXIT_99C = "exit_99c"  # Cash out at 99c
    EXIT_MANUAL = "exit_manual"  # Manual close
    EXIT_EXPIRY = "exit_expiry"  # Market closing
    EXIT_RISK_LIMIT = "exit_risk_limit"  # Risk limit triggered
    NONE = "none"  # For entry orders


class ExposureLeg(str, Enum):
    """Which leg of the binary pair we're exposed to."""
    YES = "yes"  # Exposed to YES occurring
    NO = "no"    # Exposed to NO occurring


@dataclass
class ExposureChange:
    """Net exposure change from an order.
    
    This is the canonical representation of what an order does to our position,
    independent of the specific side/action combination used to achieve it.
    """
    leg: ExposureLeg  # Which leg we're changing
    direction: Literal["increase", "decrease"]  # Are we adding or removing exposure
    magnitude: int  # Number of contracts
    
    def net_exposure_sign(self) -> int:
        """Return +1 for net positive exposure, -1 for net negative exposure."""
        return 1 if self.direction == "increase" else -1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "leg": self.leg.value,
            "direction": self.direction,
            "magnitude": self.magnitude,
        }


@dataclass
class KalshiSidePayload:
    """Kalshi venue payload (side + action).
    
    This is what actually gets sent to Kalshi's API.
    """
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    price_cents: int
    
    def to_kalshi_format(self) -> str:
        """Convert to Kalshi's combined format (BUY_YES, SELL_NO, etc.)."""
        return f"{self.action.upper()}_{self.side.upper()}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "side": self.side,
            "action": self.action,
            "price_cents": self.price_cents,
            "kalshi_format": self.to_kalshi_format(),
        }


@dataclass
class IntentContract:
    """Complete intent-to-exposure contract for a single order.
    
    This is the single source of truth for what an order should achieve,
    from strategy intent through to venue payload.
    
    CRITICAL FIX (2026-07-21): Added outcome_side and thesis_side for canonical
    direction tracking per Kalshi's order-direction semantics. outcome_side is the
    canonical field expressing which outcome the user is long. thesis_side is the
    immutable strategy thesis set once and never mutated.
    
    Reference: https://docs.kalshi.com/getting_started/order_direction
    """
    # Intent level (non-default fields first)
    strategy_intent: StrategyIntent
    entry_or_exit: EntryExit
    target_leg: ExposureLeg
    exposure_change: ExposureChange
    
    # Venue level
    kalshi_payload: KalshiSidePayload
    
    # Context
    asset: str
    ticker: str
    
    # Optional/default fields
    exit_reason: ExitReason = ExitReason.NONE  # Required for EXIT direction
    current_position: Optional[ExposureLeg] = None  # None if flat
    pre_position_size: int = 0
    expected_post_position_size: int = 0
    
    # Metadata
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    client_order_id: Optional[str] = None
    rationale: str = ""

    # CRITICAL FIX (2026-08-07): outcome_side and thesis_side default to the
    # kalshi_payload side when not supplied.  This keeps the dataclass ergonomic
    # for tests and internal call sites while preserving the canonical invariant.
    outcome_side: str = field(default="")
    thesis_side: str = field(default="")

    def __post_init__(self):
        """Derive outcome_side and thesis_side when omitted."""
        if not self.outcome_side:
            if self.kalshi_payload and self.kalshi_payload.side in ("yes", "no"):
                self.outcome_side = self.kalshi_payload.side
            elif self.target_leg:
                self.outcome_side = self.target_leg.value
            else:
                self.outcome_side = ""
        if not self.thesis_side:
            if self.outcome_side in ("yes", "no"):
                self.thesis_side = self.outcome_side
            elif self.kalshi_payload and self.kalshi_payload.side in ("yes", "no"):
                self.thesis_side = self.kalshi_payload.side
            elif self.target_leg:
                self.thesis_side = self.target_leg.value
            else:
                self.thesis_side = ""
    
    def validate(self) -> Tuple[bool, Optional[str]]:
        """Validate the complete contract for consistency.
        
        Returns:
            (is_valid, error_message)
        """
        # CRITICAL FIX (2026-07-21): Validate outcome_side and thesis_side consistency
        # outcome_side must match thesis_side (both canonical direction fields)
        # NOTE: This thesis_side is derived from strategy intent (BULLISH_EVENT → yes, BEARISH_EVENT → no)
        # This is a semantic invariant, NOT the velocity-derived thesis_side from agent_grid_15m.py
        if self.outcome_side.lower() != self.thesis_side.lower():
            return False, f"outcome_side={self.outcome_side} must match thesis_side={self.thesis_side}"
        
        # Validate outcome_side is valid
        if self.outcome_side.lower() not in ("yes", "no"):
            return False, f"Invalid outcome_side={self.outcome_side}, must be 'yes' or 'no'"
        
        # Validate thesis_side is valid
        if self.thesis_side.lower() not in ("yes", "no"):
            return False, f"Invalid thesis_side={self.thesis_side}, must be 'yes' or 'no'"
        
        # Check 1: Strategy intent → target leg consistency
        # CORRECT MAPPING (2026-07-23): BULLISH_EVENT → YES leg, BEARISH_EVENT → NO leg
        if self.strategy_intent == StrategyIntent.BULLISH_EVENT:
            if self.target_leg != ExposureLeg.YES:
                return False, f"BULLISH_EVENT requires YES leg, got {self.target_leg}"
            if self.thesis_side.lower() != "yes":
                return False, f"BULLISH_EVENT requires thesis_side=yes, got {self.thesis_side}"
        elif self.strategy_intent == StrategyIntent.BEARISH_EVENT:
            if self.target_leg != ExposureLeg.NO:
                return False, f"BEARISH_EVENT requires NO leg, got {self.target_leg}"
            if self.thesis_side.lower() != "no":
                return False, f"BEARISH_EVENT requires thesis_side=no, got {self.thesis_side}"
        
        # Check 2: Entry/exit → position state consistency
        if self.entry_or_exit == EntryExit.ENTRY:
            if self.current_position is not None:
                return False, f"ENTRY requires flat position, got {self.current_position}"
            if self.exposure_change.direction != "increase":
                return False, f"ENTRY must increase exposure, got {self.exposure_change.direction}"
            if self.exit_reason != ExitReason.NONE:
                return False, f"ENTRY orders must have exit_reason=NONE, got {self.exit_reason}"
        elif self.entry_or_exit == EntryExit.EXIT:
            if self.current_position is None:
                return False, f"EXIT requires existing position, got None"
            if self.exposure_change.direction != "decrease":
                return False, f"EXIT must decrease exposure, got {self.exposure_change.direction}"
            if self.exit_reason == ExitReason.NONE:
                return False, f"EXIT orders must have a valid exit_reason, got NONE"
        
        # Check 2a: Position-delta invariant (direction-delta invariant)
        # ENTRY: applying fill must strictly increase position magnitude
        # EXIT: applying fill must strictly decrease position magnitude
        if self.entry_or_exit == EntryExit.ENTRY:
            # Entry: from 0 to >0, or |pos_after| > |pos_before| with same sign
            if self.pre_position_size != 0:
                return False, f"ENTRY requires pre_position_size=0, got {self.pre_position_size}"
            if self.expected_post_position_size <= 0:
                return False, f"ENTRY must result in positive position, got {self.expected_post_position_size}"
            if self.expected_post_position_size != self.exposure_change.magnitude:
                return False, f"ENTRY post-position mismatch: expected {self.exposure_change.magnitude}, got {self.expected_post_position_size}"
        elif self.entry_or_exit == EntryExit.EXIT:
            # Exit: |pos_after| < |pos_before|, must never go from 0 to nonzero
            if self.pre_position_size <= 0:
                return False, f"EXIT requires pre_position_size>0, got {self.pre_position_size}"
            if self.expected_post_position_size < 0:
                return False, f"EXIT cannot result in negative position, got {self.expected_post_position_size}"
            if self.expected_post_position_size >= self.pre_position_size:
                return False, f"EXIT must decrease position: pre={self.pre_position_size}, post={self.expected_post_position_size}"
            # Check for position flip (e.g., +5 -> -1) - this is an exit trying to open opposite leg
            if self.expected_post_position_size < 0:
                return False, f"EXIT cannot flip position sign: pre={self.pre_position_size}, post={self.expected_post_position_size}"
        
        # Check 3: Exposure change → target leg consistency
        if self.exposure_change.leg != self.target_leg:
            return False, f"Exposure leg mismatch: {self.exposure_change.leg} vs {self.target_leg}"
        
        # Check 4: Kalshi payload → exposure change consistency
        # For exits, allow economically equivalent opposite actions (e.g., buy NO to exit YES)
        # The key is that the net exposure change must match, not necessarily the leg
        payload_exposure = _payload_to_exposure(self.kalshi_payload)
        
        if self.entry_or_exit == EntryExit.EXIT:
            # For exits, check that the net exposure change is correct
            # Direct action: SELL YES (decrease YES) - leg matches
            # Equivalent action: BUY NO (increase NO) - leg differs but net effect is same
            # Both are valid as long as they reduce the position we're holding
            if self.current_position == ExposureLeg.YES:
                # Exiting YES: either SELL YES or BUY NO are valid
                if not ((self.kalshi_payload.side == "yes" and self.kalshi_payload.action == "sell") or
                        (self.kalshi_payload.side == "no" and self.kalshi_payload.action == "buy")):
                    return False, f"Invalid exit action for YES position: {self.kalshi_payload.to_kalshi_format()}"
            elif self.current_position == ExposureLeg.NO:
                # Exiting NO: either SELL NO or BUY YES are valid
                if not ((self.kalshi_payload.side == "no" and self.kalshi_payload.action == "sell") or
                        (self.kalshi_payload.side == "yes" and self.kalshi_payload.action == "buy")):
                    return False, f"Invalid exit action for NO position: {self.kalshi_payload.to_kalshi_format()}"
        else:
            # For entries, payload must exactly match exposure change
            if payload_exposure.leg != self.exposure_change.leg:
                return False, f"Payload leg mismatch: {payload_exposure.leg} vs {self.exposure_change.leg}"
            if payload_exposure.direction != self.exposure_change.direction:
                return False, f"Payload direction mismatch: {payload_exposure.direction} vs {self.exposure_change.direction}"
        
        # Check 5: Post-position size consistency
        if self.entry_or_exit == EntryExit.ENTRY:
            expected_post = self.pre_position_size + self.exposure_change.magnitude
        else:  # EXIT
            expected_post = self.pre_position_size - self.exposure_change.magnitude
        
        if self.expected_post_position_size != expected_post:
            return False, f"Post-position size mismatch: expected {expected_post}, got {self.expected_post_position_size}"
        
        return True, None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        is_valid, error = self.validate()
        return {
            "strategy_intent": self.strategy_intent.value,
            "entry_or_exit": self.entry_or_exit.value,
            "target_leg": self.target_leg.value,
            "exposure_change": self.exposure_change.to_dict(),
            "kalshi_payload": self.kalshi_payload.to_dict(),
            "asset": self.asset,
            "ticker": self.ticker,
            "current_position": self.current_position.value if self.current_position else None,
            "pre_position_size": self.pre_position_size,
            "expected_post_position_size": self.expected_post_position_size,
            "timestamp": self.timestamp,
            "client_order_id": self.client_order_id,
            "rationale": self.rationale,
            "is_valid": is_valid,
            "validation_error": error,
        }


def _payload_to_exposure(payload: KalshiSidePayload) -> ExposureChange:
    """Convert Kalshi payload to exposure change.
    
    Venue semantics:
    - BUY YES: increase YES exposure
    - SELL YES: decrease YES exposure
    - BUY NO: increase NO exposure
    - SELL NO: decrease NO exposure
    """
    if payload.side == "yes":
        leg = ExposureLeg.YES
    else:  # "no"
        leg = ExposureLeg.NO
    
    if payload.action == "buy":
        direction = "increase"
    else:  # "sell"
        direction = "decrease"
    
    return ExposureChange(leg=leg, direction=direction, magnitude=1)  # magnitude not known from payload alone


def map_intent_to_exposure(
    intent: StrategyIntent,
    current_position: Optional[ExposureLeg],
    magnitude: int = 1,
) -> ExposureChange:
    """Map strategy intent to exposure change.
    
    This is the SINGLE SOURCE OF TRUTH for intent → exposure mapping.
    All code should use this function instead of hand-coding the logic.
    
    Args:
        intent: Strategy intent (BULLISH_EVENT or BEARISH_EVENT)
        current_position: Current position leg (None if flat)
        magnitude: Number of contracts
        
    Returns:
        ExposureChange representing the net exposure change
        
    Raises:
        ValueError: If intent is NEUTRAL or mapping is invalid
    """
    if intent == StrategyIntent.NEUTRAL:
        raise ValueError("NEUTRAL intent cannot be mapped to exposure change")
    
    # Determine target leg from intent
    # CORRECT MAPPING (2026-07-23): BULLISH_EVENT → YES leg, BEARISH_EVENT → NO leg
    if intent == StrategyIntent.BULLISH_EVENT:
        target_leg = ExposureLeg.YES
    elif intent == StrategyIntent.BEARISH_EVENT:
        target_leg = ExposureLeg.NO
    else:
        raise ValueError(f"Unknown intent: {intent}")
    
    # Determine direction from current position
    if current_position is None:
        # Entry: increase exposure on target leg
        direction = "increase"
    elif current_position == target_leg:
        # Adding to existing position: increase exposure
        direction = "increase"
    else:
        # Exiting opposite position: decrease exposure on current leg
        # This is the economically equivalent action to close the position
        direction = "decrease"
        target_leg = current_position  # We're reducing the leg we hold
    
    # SIDE-PRESERVATION-CHECK: Log intent → exposure mapping
    logger.info(
        "[SIDE-PRESERVATION-CHECK] "
        "intent=%s "
        "target_leg=%s "
        "direction=%s "
        "current_position=%s "
        "magnitude=%d",
        intent.value,
        target_leg.value,
        direction,
        current_position.value if current_position else "None",
        magnitude
    )
    
    return ExposureChange(leg=target_leg, direction=direction, magnitude=magnitude)


def map_exposure_to_kalshi_side(
    exposure: ExposureChange,
    price_cents: int,
    prefer_liquidity_side: Optional[Literal["yes", "no"]] = None,
) -> KalshiSidePayload:
    """Map exposure change to Kalshi side/action payload.
    
    This is the SINGLE SOURCE OF TRUTH for exposure → Kalshi mapping.
    All code should use this function instead of hand-coding the logic.
    
    Args:
        exposure: Desired exposure change
        price_cents: Limit price in cents
        prefer_liquidity_side: If both sides are economically equivalent,
                               prefer this side for liquidity (optional)
        
    Returns:
        KalshiSidePayload with side, action, and price
        
    Note:
        For exits, there are two economically equivalent actions:
        - To reduce YES exposure: SELL YES or BUY NO (at 1-price)
        - To reduce NO exposure: SELL NO or BUY YES (at 1-price)
        
        This function defaults to the direct action (SELL the leg you hold),
        but can be overridden with prefer_liquidity_side.
    """
    if exposure.leg == ExposureLeg.YES:
        if exposure.direction == "increase":
            # Increase YES: BUY YES
            payload = KalshiSidePayload(side="yes", action="buy", price_cents=price_cents)
        else:
            # Decrease YES: SELL YES (direct) or BUY NO (equivalent)
            if prefer_liquidity_side == "no":
                # Buy NO at complementary price
                payload = KalshiSidePayload(side="no", action="buy", price_cents=100 - price_cents)
            else:
                # Default: SELL YES
                payload = KalshiSidePayload(side="yes", action="sell", price_cents=price_cents)
    else:  # ExposureLeg.NO
        if exposure.direction == "increase":
            # Increase NO: BUY NO
            payload = KalshiSidePayload(side="no", action="buy", price_cents=price_cents)
        else:
            # Decrease NO: SELL NO (direct) or BUY YES (equivalent)
            if prefer_liquidity_side == "yes":
                # Buy YES at complementary price
                payload = KalshiSidePayload(side="yes", action="buy", price_cents=100 - price_cents)
            else:
                # Default: SELL NO
                payload = KalshiSidePayload(side="no", action="sell", price_cents=price_cents)
    
    # SIDE-PRESERVATION-CHECK: Log exposure → Kalshi side mapping
    logger.info(
        "[SIDE-PRESERVATION-CHECK] "
        "exposure_leg=%s "
        "exposure_direction=%s "
        "kalshi_side=%s "
        "kalshi_action=%s "
        "price_cents=%d "
        "prefer_liquidity_side=%s",
        exposure.leg.value,
        exposure.direction,
        payload.side,
        payload.action,
        payload.price_cents,
        prefer_liquidity_side or "None"
    )
    
    return payload


def build_entry_order(
    intent: StrategyIntent,
    asset: str,
    ticker: str,
    price_cents: int,
    magnitude: int = 1,
    client_order_id: Optional[str] = None,
    rationale: str = "",
) -> IntentContract:
    """Build an entry order contract.
    
    Entry rules:
    - Current position must be flat
    - BULLISH_EVENT → increase YES exposure (correct 2026-07-23)
    - BEARISH_EVENT → increase NO exposure (correct 2026-07-23)
    
    Args:
        intent: Strategy intent (BULLISH_EVENT or BEARISH_EVENT)
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        ticker: Kalshi market ticker
        price_cents: Limit price in cents
        magnitude: Number of contracts
        client_order_id: Optional idempotency key
        rationale: Human-readable reason
        
    Returns:
        IntentContract for the entry order
        
    Raises:
        ValueError: If intent is invalid or position state is wrong
    """
    if intent == StrategyIntent.NEUTRAL:
        raise ValueError("Cannot build entry order for NEUTRAL intent")
    
    # Map intent to exposure
    exposure = map_intent_to_exposure(intent, current_position=None, magnitude=magnitude)
    
    # Map exposure to Kalshi payload
    payload = map_exposure_to_kalshi_side(exposure, price_cents)
    
    # Entry orders can use any economically-equivalent form (BUY_YES, SELL_NO,
    # BUY_NO, SELL_YES) because all four map to a signed YES exposure.  The
    # canonical signed exposure is what matters, not the raw action.
    
    # Determine target leg
    # CORRECT MAPPING (2026-07-23): BULLISH_EVENT → YES leg, BEARISH_EVENT → NO leg
    target_leg = ExposureLeg.YES if intent == StrategyIntent.BULLISH_EVENT else ExposureLeg.NO
    
    # CORRECT MAPPING (2026-07-23): BULLISH_EVENT → YES thesis, BEARISH_EVENT → NO thesis
    outcome_side = "yes" if intent == StrategyIntent.BULLISH_EVENT else "no"
    thesis_side = outcome_side  # For entry, thesis_side == outcome_side
    
    # VERIFICATION: Telemetry logging on intent creation
    logger.info(
        "[INTENT-CREATION] ticker=%s signal=%s thesis_side=%s outcome_side=%s magnitude=%d price_cents=%d",
        ticker, intent.value, thesis_side, outcome_side, magnitude, price_cents
    )
    
    return IntentContract(
        strategy_intent=intent,
        entry_or_exit=EntryExit.ENTRY,
        target_leg=target_leg,
        exposure_change=exposure,
        outcome_side=outcome_side,  # CRITICAL FIX
        thesis_side=thesis_side,  # CRITICAL FIX
        kalshi_payload=payload,
        asset=asset,
        ticker=ticker,
        current_position=None,
        pre_position_size=0,
        expected_post_position_size=magnitude,
        client_order_id=client_order_id,
        rationale=rationale,
    )


def build_exit_order(
    current_position: ExposureLeg,
    asset: str,
    ticker: str,
    price_cents: int,
    magnitude: int = 1,
    client_order_id: Optional[str] = None,
    rationale: str = "",
    prefer_liquidity_side: Optional[Literal["yes", "no"]] = None,
    exit_reason: ExitReason = ExitReason.EXIT_MANUAL,
) -> IntentContract:
    """Build an exit order contract.
    
    Exit rules:
    - Current position must not be flat
    - Must reduce exposure on the leg you're currently holding
    - Can use direct action (SELL the leg you hold) or equivalent opposite action
    - Must specify exit_reason (TP, SL, 99C, MANUAL, EXPIRY, RISK_LIMIT)
    
    Args:
        current_position: Current position leg (YES or NO)
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        ticker: Kalshi market ticker
        price_cents: Limit price in cents
        magnitude: Number of contracts
        client_order_id: Optional idempotency key
        rationale: Human-readable reason
        prefer_liquidity_side: Prefer this side for economically equivalent exits
        exit_reason: Reason for exit (required for EXIT direction)
        
    Returns:
        IntentContract for the exit order
        
    Raises:
        ValueError: If position state is invalid
    """
    # Map to exposure (exit always decreases current leg)
    exposure = ExposureChange(
        leg=current_position,
        direction="decrease",
        magnitude=magnitude,
    )
    
    # Map exposure to Kalshi payload (direct action by default)
    # If prefer_liquidity_side is specified, use the equivalent opposite action
    # but the exposure change remains the same (decrease current leg)
    if prefer_liquidity_side:
        # Use equivalent opposite action for liquidity
        if current_position == ExposureLeg.YES:
            # Exit YES by buying NO (economically equivalent)
            payload = KalshiSidePayload(
                side="no",
                action="buy",
                price_cents=100 - price_cents  # Complementary price
            )
        else:  # ExposureLeg.NO
            # Exit NO by buying YES (economically equivalent)
            payload = KalshiSidePayload(
                side="yes",
                action="buy",
                price_cents=100 - price_cents  # Complementary price
            )
    else:
        # Use direct action (sell the leg you hold)
        payload = map_exposure_to_kalshi_side(exposure, price_cents)
    
    # Infer intent from position (exit doesn't have a directional bias)
    # We use NEUTRAL to indicate this is a pure exit, not a new directional bet
    intent = StrategyIntent.NEUTRAL
    
    # CRITICAL FIX (2026-07-21): Set outcome_side and thesis_side from current position
    # Exit should preserve the thesis_side of the position being closed
    outcome_side = current_position.value  # "yes" or "no"
    thesis_side = outcome_side  # For exit, thesis_side == outcome_side (preserving position thesis)
    
    # VERIFICATION: Telemetry logging on intent creation
    logger.info(
        "[INTENT-CREATION-EXIT] ticker=%s exit_reason=%s thesis_side=%s outcome_side=%s magnitude=%d price_cents=%d",
        ticker, exit_reason.value, thesis_side, outcome_side, magnitude, price_cents
    )
    
    return IntentContract(
        strategy_intent=intent,
        entry_or_exit=EntryExit.EXIT,
        exit_reason=exit_reason,
        target_leg=current_position,
        exposure_change=exposure,
        outcome_side=outcome_side,  # CRITICAL FIX
        thesis_side=thesis_side,  # CRITICAL FIX
        kalshi_payload=payload,
        asset=asset,
        ticker=ticker,
        current_position=current_position,
        pre_position_size=magnitude,  # Assuming we're exiting full position
        expected_post_position_size=0,
        client_order_id=client_order_id,
        rationale=rationale,
    )


def validate_intent_exposure_consistency(
    intent: StrategyIntent,
    kalshi_side: str,
    kalshi_action: str,
    current_position: Optional[ExposureLeg] = None,
) -> Tuple[bool, Optional[str]]:
    """Validate that a Kalshi side/action matches the strategy intent.
    
    This is a tripwire function to catch intent → exposure mismatches
    before orders are sent to the venue.
    
    Args:
        intent: Strategy intent (BULLISH_EVENT or BEARISH_EVENT)
        kalshi_side: Kalshi side ("yes" or "no")
        kalshi_action: Kalshi action ("buy" or "sell")
        current_position: Current position leg (None if flat)
        
    Returns:
        (is_valid, error_message)
    """
    # Map intent to expected exposure
    try:
        expected_exposure = map_intent_to_exposure(intent, current_position)
    except ValueError as e:
        return False, f"Intent mapping error: {e}"
    
    # Convert Kalshi payload to exposure
    payload = KalshiSidePayload(side=kalshi_side, action=kalshi_action, price_cents=0)
    actual_exposure = _payload_to_exposure(payload)
    
    # Check consistency
    if expected_exposure.leg != actual_exposure.leg:
        return False, (
            f"Intent/Exposure leg mismatch: intent={intent.value} expects {expected_exposure.leg.value}, "
            f"but payload would produce {actual_exposure.leg.value} "
            f"(kalshi_side={kalshi_side}, kalshi_action={kalshi_action})"
        )
    
    if expected_exposure.direction != actual_exposure.direction:
        return False, (
            f"Intent/Exposure direction mismatch: intent={intent.value} expects {expected_exposure.direction}, "
            f"but payload would produce {actual_exposure.direction} "
            f"(kalshi_side={kalshi_side}, kalshi_action={kalshi_action})"
        )
    
    return True, None


def compute_net_exposure_from_fill(
    fill_side: str,
    fill_action: str,
    fill_quantity: int,
) -> Dict[str, int]:
    """Compute net exposure change from a fill notification.
    
    Args:
        fill_side: Fill side ("yes" or "no")
        fill_action: Fill action ("buy" or "sell")
        fill_quantity: Number of contracts filled
        
    Returns:
        Dict with "yes" and "no" exposure changes (+/-)
    """
    exposure = {"yes": 0, "no": 0}
    
    if fill_side == "yes":
        if fill_action == "buy":
            exposure["yes"] += fill_quantity
        else:  # sell
            exposure["yes"] -= fill_quantity
    else:  # "no"
        if fill_action == "buy":
            exposure["no"] += fill_quantity
        else:  # sell
            exposure["no"] -= fill_quantity
    
    return exposure


def compute_yes_delta_from_fill(
    fill_side: str,
    fill_action: str,
    fill_quantity: int,
) -> int:
    """Compute signed YES-exposure change from a fill.

    Collapses the four economically-equivalent order forms into a single
    signed YES delta.  This is the canonical exposure unit for fills.

    BUY YES  -> +qty  (long YES)
    SELL NO  -> +qty  (long YES, equivalent to BUY YES)
    SELL YES -> -qty  (long NO / short YES)
    BUY NO   -> -qty  (long NO, equivalent to SELL YES)
    """
    if BINARY_PRICE_SPACE_AVAILABLE:
        return yes_delta(fill_action, fill_side, fill_quantity)

    # Fallback if binary_price_space is unavailable (should not happen in prod)
    action = fill_action.lower()
    side = fill_side.lower()
    if (action, side) in {("buy", "yes"), ("sell", "no")}:
        return +fill_quantity
    if (action, side) in {("sell", "yes"), ("buy", "no")}:
        return -fill_quantity
    raise ValueError(f"Unsupported fill: side={fill_side} action={fill_action}")


def validate_fill_against_intent(
    intent_contract: IntentContract,
    fill_side: str,
    fill_action: str,
    fill_quantity: int,
) -> Tuple[bool, Optional[str]]:
    """Validate that a fill matches the expected intent contract.
    
    This is the downstream tripwire to catch venue echo mismatches.
    It uses the canonical signed YES delta so economically-equivalent
    fills (e.g. BUY YES vs. SELL NO) are treated as the same exposure.
    
    Args:
        intent_contract: Original intent contract
        fill_side: Fill side from venue ("yes" or "no")
        fill_action: Fill action from venue ("buy" or "sell")
        fill_quantity: Number of contracts filled
        
    Returns:
        (is_valid, error_message)
    """
    # Compute actual signed YES delta from fill
    actual_yes_delta = compute_yes_delta_from_fill(fill_side, fill_action, fill_quantity)
    
    # Compute expected signed YES delta from contract
    expected_yes_delta = 0
    if intent_contract.exposure_change.leg == ExposureLeg.YES:
        sign = 1
    else:
        sign = -1
    
    if intent_contract.exposure_change.direction == "increase":
        expected_yes_delta = sign * intent_contract.exposure_change.magnitude
    else:  # "decrease"
        expected_yes_delta = -sign * intent_contract.exposure_change.magnitude
    
    if actual_yes_delta != expected_yes_delta:
        return False, (
            f"Fill/Intent exposure mismatch: "
            f"expected_yes_delta={expected_yes_delta}, got {actual_yes_delta} "
            f"(fill_side={fill_side}, fill_action={fill_action}, fill_quantity={fill_quantity})"
        )
    
    return True, None


@dataclass
class OrderLifecycleEvent:
    """Immutable audit record for a single order lifecycle event.

    Emitted at every transition (intent creation, submission, ack, fill,
    position update) so the full signal -> order -> position chain can be
    reconstructed and invariants checked.

    The canonical signed exposure uses YES-delta:
    - positive == long YES
    - negative == long NO
    """
    client_order_id: str
    ticker: str
    strategy_intent: str
    action: str
    side: str
    price_cents: int
    quantity: int
    normalized_yes_delta: int
    pre_position_yes: int
    post_position_yes_expected: int
    post_position_yes_actual: Optional[int] = None
    reason: str = ""
    parent_order_id: Optional[str] = None
    is_reduce_only_expected: bool = False
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "ticker": self.ticker,
            "strategy_intent": self.strategy_intent,
            "action": self.action,
            "side": self.side,
            "price_cents": self.price_cents,
            "quantity": self.quantity,
            "normalized_yes_delta": self.normalized_yes_delta,
            "pre_position_yes": self.pre_position_yes,
            "post_position_yes_expected": self.post_position_yes_expected,
            "post_position_yes_actual": self.post_position_yes_actual,
            "reason": self.reason,
            "parent_order_id": self.parent_order_id,
            "is_reduce_only_expected": self.is_reduce_only_expected,
            "timestamp": self.timestamp,
        }

    def invariant(self) -> Tuple[bool, Optional[str]]:
        """Check the post-position invariant."""
        expected = self.pre_position_yes + self.normalized_yes_delta
        if self.post_position_yes_actual is None:
            # We haven't received actual position yet; check expected only
            if expected != self.post_position_yes_expected:
                return False, (
                    f"expected_post mismatch: pre {self.pre_position_yes} + "
                    f"delta {self.normalized_yes_delta} = {expected}, "
                    f"but post_position_yes_expected={self.post_position_yes_expected}"
                )
            return True, None
        if self.post_position_yes_actual != expected:
            return False, (
                f"position invariant violated: pre {self.pre_position_yes} + "
                f"delta {self.normalized_yes_delta} = {expected}, "
                f"but actual={self.post_position_yes_actual}"
            )
        return True, None


def emit_order_lifecycle_event(
    client_order_id: str,
    ticker: str,
    strategy_intent: str,
    action: str,
    side: str,
    price_cents: int,
    quantity: int,
    pre_position_yes: int,
    post_position_yes_expected: int,
    reason: str = "",
    parent_order_id: Optional[str] = None,
    is_reduce_only_expected: bool = False,
    post_position_yes_actual: Optional[int] = None,
) -> OrderLifecycleEvent:
    """Emit an immutable order lifecycle audit record.

    Computes the canonical signed YES delta from the raw action/side.
    """
    if BINARY_PRICE_SPACE_AVAILABLE:
        normalized_yes_delta = yes_delta(action, side, quantity)
    else:
        # Fallback for environments without binary_price_space
        a = action.lower()
        s = side.lower()
        if (a, s) in {("buy", "yes"), ("sell", "no")}:
            normalized_yes_delta = +quantity
        elif (a, s) in {("sell", "yes"), ("buy", "no")}:
            normalized_yes_delta = -quantity
        else:
            raise ValueError(f"Unsupported order: action={action} side={side}")

    event = OrderLifecycleEvent(
        client_order_id=client_order_id,
        ticker=ticker,
        strategy_intent=strategy_intent,
        action=action,
        side=side,
        price_cents=price_cents,
        quantity=quantity,
        normalized_yes_delta=normalized_yes_delta,
        pre_position_yes=pre_position_yes,
        post_position_yes_expected=post_position_yes_expected,
        post_position_yes_actual=post_position_yes_actual,
        reason=reason,
        parent_order_id=parent_order_id,
        is_reduce_only_expected=is_reduce_only_expected,
    )

    is_valid, error = event.invariant()
    if not is_valid:
        logger.error("[ORDER-LIFECYCLE-INVARIANT] %s", error)

    logger.info(
        "[ORDER-LIFECYCLE] %s",
        json.dumps(event.to_dict(), sort_keys=True, default=str)
    )
    return event
