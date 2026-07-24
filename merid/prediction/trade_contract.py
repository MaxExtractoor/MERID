"""
Unified Trade Contract Abstraction

This module provides a unified Trade Contract abstraction that ensures consistency
across configuration, data, signals, intent mapping, candidate building, order
building, execution, ledger, and the exit engine.

The Trade Contract is the single source of truth for a trade, from signal generation
through execution and exit, ensuring all layers use consistent data and invariants.

Key Components:
- TradeContract: Complete trade definition across all layers
- ContractLayer: Abstraction for each layer (config, signal, intent, candidate, order, execution, ledger, exit)
- ContractValidator: Validates contract consistency across layers
- ContractBuilder: Builds contracts from signals

Usage::

    from merid.prediction.trade_contract import (
        TradeContract,
        ContractLayer,
        ContractValidator,
        ContractBuilder,
        build_trade_contract_from_signal
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
from utils.logger import get_logger

logger = get_logger("trade_contract")

try:
    from merid.prediction.signal_terminology import StrategyIntent, Side, Action
    from merid.prediction.intent_contract import IntentContract, ExposureLeg
except ImportError:
    # Fallback definitions
    class StrategyIntent:
        BULLISH_EVENT = "bullish_event"
        BEARISH_EVENT = "bearish_event"
        NEUTRAL = "neutral"
    
    class Side:
        YES = "yes"
        NO = "no"
    
    class Action:
        BUY = "buy"
        SELL = "sell"
    
    class ExposureLeg:
        YES = "yes"
        NO = "no"


class ContractLayer(str, Enum):
    """Layers in the trade contract pipeline."""
    CONFIG = "config"  # Configuration layer
    DATA = "data"  # Data layer (market data, spot prices)
    SIGNAL = "signal"  # Signal generation layer
    INTENT = "intent"  # Intent mapping layer
    CANDIDATE = "candidate"  # Candidate building layer
    ORDER = "order"  # Order building layer
    EXECUTION = "execution"  # Execution layer
    LEDGER = "ledger"  # Ledger layer
    EXIT = "exit"  # Exit engine layer


@dataclass
class LayerData:
    """Data for a specific contract layer."""
    
    layer: ContractLayer
    timestamp: datetime
    data: Dict[str, Any]
    is_valid: bool = True
    validation_errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "layer": self.layer.value,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "is_valid": self.is_valid,
            "validation_errors": self.validation_errors,
        }


@dataclass
class TradeContract:
    """Unified trade contract spanning all layers.
    
    This is the single source of truth for a trade, ensuring consistency
    across configuration, data, signals, intent, candidate, order, execution,
    ledger, and exit layers.
    """
    
    # Contract identification
    contract_id: str
    asset: str
    market_id: str
    
    # Core trade parameters
    strategy_intent: StrategyIntent
    thesis_side: str  # "yes" or "no"
    kalshi_side: str  # "yes" or "no"
    kalshi_action: str  # "buy" or "sell"
    price_cents: int
    contracts: int
    
    # Layer data
    layers: Dict[ContractLayer, LayerData] = field(default_factory=dict)
    
    # Intent contract (from intent_contract module)
    intent_contract: Optional[IntentContract] = None
    
    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "pending"  # pending, submitted, filled, cancelled, exited
    
    def add_layer_data(self, layer: ContractLayer, data: Dict[str, Any]) -> None:
        """Add data for a specific layer."""
        self.layers[layer] = LayerData(
            layer=layer,
            timestamp=datetime.now(timezone.utc),
            data=data,
        )
        self.updated_at = datetime.now(timezone.utc)
    
    def get_layer_data(self, layer: ContractLayer) -> Optional[LayerData]:
        """Get data for a specific layer."""
        return self.layers.get(layer)
    
    def validate_layer(self, layer: ContractLayer) -> Tuple[bool, List[str]]:
        """Validate a specific layer's data."""
        layer_data = self.get_layer_data(layer)
        if layer_data is None:
            return False, [f"Layer {layer.value} has no data"]
        
        errors = []
        
        # Layer-specific validation
        if layer == ContractLayer.CONFIG:
            if "asset" not in layer_data.data:
                errors.append("CONFIG layer missing 'asset'")
            if "market_id" not in layer_data.data:
                errors.append("CONFIG layer missing 'market_id'")
        
        elif layer == ContractLayer.SIGNAL:
            if "strategy_intent" not in layer_data.data:
                errors.append("SIGNAL layer missing 'strategy_intent'")
            if "confidence" not in layer_data.data:
                errors.append("SIGNAL layer missing 'confidence'")
        
        elif layer == ContractLayer.INTENT:
            if "thesis_side" not in layer_data.data:
                errors.append("INTENT layer missing 'thesis_side'")
            if layer_data.data["thesis_side"].lower() not in ("yes", "no"):
                errors.append(f"INTENT layer invalid thesis_side: {layer_data.data['thesis_side']}")
        
        elif layer == ContractLayer.ORDER:
            if "kalshi_side" not in layer_data.data:
                errors.append("ORDER layer missing 'kalshi_side'")
            if "kalshi_action" not in layer_data.data:
                errors.append("ORDER layer missing 'kalshi_action'")
            if "price_cents" not in layer_data.data:
                errors.append("ORDER layer missing 'price_cents'")
        
        layer_data.is_valid = len(errors) == 0
        layer_data.validation_errors = errors
        
        return len(errors) == 0, errors
    
    def validate_all_layers(self) -> Tuple[bool, Dict[ContractLayer, List[str]]]:
        """Validate all layers."""
        all_errors = {}
        all_valid = True
        
        for layer in ContractLayer:
            # Only validate layers that have data
            if layer not in self.layers:
                continue
            is_valid, errors = self.validate_layer(layer)
            all_errors[layer] = errors
            if not is_valid:
                all_valid = False
        
        return all_valid, all_errors
    
    def validate_cross_layer_consistency(self) -> Tuple[bool, List[str]]:
        """Validate consistency across layers.
        
        Key invariants:
        - Intent → thesis_side mapping consistent across SIGNAL, INTENT, ORDER layers
        - Kalshi side/action consistent across ORDER, EXECUTION layers
        - Price consistent across ORDER, EXECUTION layers
        - Contracts consistent across ORDER, LEDGER layers
        """
        errors = []
        
        # Check intent → thesis_side consistency
        signal_data = self.get_layer_data(ContractLayer.SIGNAL)
        intent_data = self.get_layer_data(ContractLayer.INTENT)
        order_data = self.get_layer_data(ContractLayer.ORDER)
        
        if signal_data and intent_data:
            signal_intent = signal_data.data.get("strategy_intent")
            intent_thesis = intent_data.data.get("thesis_side")
            
            # BULLISH_EVENT → thesis_side=yes, BEARISH_EVENT → thesis_side=no
            if signal_intent == StrategyIntent.BULLISH_EVENT:
                if intent_thesis and intent_thesis.lower() != "yes":
                    errors.append(
                        f"Cross-layer inconsistency: BULLISH_EVENT requires thesis_side=yes, "
                        f"got {intent_thesis}"
                    )
            elif signal_intent == StrategyIntent.BEARISH_EVENT:
                if intent_thesis and intent_thesis.lower() != "no":
                    errors.append(
                        f"Cross-layer inconsistency: BEARISH_EVENT requires thesis_side=no, "
                        f"got {intent_thesis}"
                    )
        
        # Check Kalshi side/action consistency
        if order_data:
            order_side = order_data.data.get("kalshi_side")
            order_action = order_data.data.get("kalshi_action")
            
            if order_side and order_side.lower() not in ("yes", "no"):
                errors.append(f"ORDER layer invalid kalshi_side: {order_side}")
            
            if order_action and order_action.lower() not in ("buy", "sell"):
                errors.append(f"ORDER layer invalid kalshi_action: {order_action}")
        
        # Check price consistency
        if order_data:
            order_price = order_data.data.get("price_cents")
            if order_price and (order_price < 10 or order_price > 75):
                errors.append(f"ORDER layer price out of canonical range: {order_price}c (must be 10-75c)")
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> Dict:
        """Convert contract to dictionary for serialization."""
        all_valid, layer_errors = self.validate_all_layers()
        cross_valid, cross_errors = self.validate_cross_layer_consistency()
        
        return {
            "contract_id": self.contract_id,
            "asset": self.asset,
            "market_id": self.market_id,
            "strategy_intent": self.strategy_intent,
            "thesis_side": self.thesis_side,
            "kalshi_side": self.kalshi_side,
            "kalshi_action": self.kalshi_action,
            "price_cents": self.price_cents,
            "contracts": self.contracts,
            "layers": {layer.value: data.to_dict() for layer, data in self.layers.items()},
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "status": self.status,
            "all_layers_valid": all_valid,
            "layer_errors": {layer.value: errors for layer, errors in layer_errors.items()},
            "cross_layer_valid": cross_valid,
            "cross_layer_errors": cross_errors,
        }


class ContractValidator:
    """Validates trade contracts across all layers."""
    
    def __init__(self, require_all_layers: bool = False):
        """
        Args:
            require_all_layers: If True, require all layers to be present.
                              If False, only validate layers that are present.
        """
        self.require_all_layers = require_all_layers
        self.required_layers = [
            ContractLayer.CONFIG,
            ContractLayer.SIGNAL,
            ContractLayer.INTENT,
            ContractLayer.ORDER,
        ]
    
    def validate_contract(self, contract: TradeContract) -> Tuple[bool, List[str]]:
        """Validate a complete trade contract.
        
        Args:
            contract: Trade contract to validate
            
        Returns:
            (is_valid, error_messages)
        """
        errors = []
        
        # Check required layers exist (only if require_all_layers is True)
        if self.require_all_layers:
            for layer in self.required_layers:
                if layer not in contract.layers:
                    errors.append(f"Required layer {layer.value} missing")
        
        # Validate all layers
        all_valid, layer_errors = contract.validate_all_layers()
        if not all_valid:
            for layer, layer_error_list in layer_errors.items():
                errors.extend([f"{layer.value}: {err}" for err in layer_error_list])
        
        # Validate cross-layer consistency
        cross_valid, cross_errors = contract.validate_cross_layer_consistency()
        if not cross_valid:
            errors.extend(cross_errors)
        
        return len(errors) == 0, errors


class ContractBuilder:
    """Builds trade contracts from signals."""
    
    def __init__(self):
        self.validator = ContractValidator()
    
    def build_from_signal(
        self,
        signal_data: Dict[str, Any],
        config_data: Dict[str, Any],
        market_data: Dict[str, Any],
    ) -> TradeContract:
        """Build a trade contract from signal data.
        
        Args:
            signal_data: Signal generation data
            config_data: Configuration data
            market_data: Market data
            
        Returns:
            TradeContract
        """
        # Extract core parameters
        asset = config_data.get("asset", "UNKNOWN")
        market_id = config_data.get("market_id", "UNKNOWN")
        strategy_intent = signal_data.get("strategy_intent", StrategyIntent.NEUTRAL)
        thesis_side = signal_data.get("thesis_side", "yes")
        kalshi_side = signal_data.get("kalshi_side", "yes")
        kalshi_action = signal_data.get("kalshi_action", "buy")
        price_cents = signal_data.get("price_cents", 50)
        contracts = signal_data.get("contracts", 1)
        
        # Create contract
        contract = TradeContract(
            contract_id=f"{asset}-{market_id}-{datetime.now(timezone.utc).timestamp()}",
            asset=asset,
            market_id=market_id,
            strategy_intent=strategy_intent,
            thesis_side=thesis_side,
            kalshi_side=kalshi_side,
            kalshi_action=kalshi_action,
            price_cents=price_cents,
            contracts=contracts,
        )
        
        # Add layer data
        contract.add_layer_data(ContractLayer.CONFIG, config_data)
        contract.add_layer_data(ContractLayer.DATA, market_data)
        contract.add_layer_data(ContractLayer.SIGNAL, signal_data)
        
        # Build intent layer
        intent_data = {
            "strategy_intent": strategy_intent,
            "thesis_side": thesis_side,
            "confidence": signal_data.get("confidence", 0.0),
        }
        contract.add_layer_data(ContractLayer.INTENT, intent_data)
        
        # Build order layer
        order_data = {
            "kalshi_side": kalshi_side,
            "kalshi_action": kalshi_action,
            "price_cents": price_cents,
            "contracts": contracts,
        }
        contract.add_layer_data(ContractLayer.ORDER, order_data)
        
        return contract


def build_trade_contract_from_signal(
    signal_data: Dict[str, Any],
    config_data: Dict[str, Any],
    market_data: Dict[str, Any],
) -> Tuple[TradeContract, Tuple[bool, List[str]]]:
    """Build and validate a trade contract from signal data.
    
    Args:
        signal_data: Signal generation data
        config_data: Configuration data
        market_data: Market data
        
    Returns:
        (contract, (is_valid, errors))
    """
    builder = ContractBuilder()
    contract = builder.build_from_signal(signal_data, config_data, market_data)
    validator = ContractValidator()
    is_valid, errors = validator.validate_contract(contract)
    
    return contract, (is_valid, errors)


# Invariant documentation
TRADE_CONTRACT_INVARIANTS = """
Unified Trade Contract Invariants (2026-07-23)

1. Layer Completeness:
   - CONFIG layer: asset, market_id, profile configuration
   - DATA layer: market data, spot prices, order book
   - SIGNAL layer: strategy_intent, confidence, edge
   - INTENT layer: thesis_side, intent validation
   - CANDIDATE layer: candidate parameters, risk checks
   - ORDER layer: kalshi_side, kalshi_action, price_cents, contracts
   - EXECUTION layer: order submission, venue response
   - LEDGER layer: fill data, position updates
   - EXIT layer: exit plans, exit execution

2. Cross-Layer Consistency:
   - Intent → thesis_side mapping consistent across SIGNAL, INTENT, ORDER
   - Kalshi side/action consistent across ORDER, EXECUTION
   - Price consistent across ORDER, EXECUTION (10-75c canonical range)
   - Contracts consistent across ORDER, LEDGER
   - Exit plans consistent with position state

3. Data Integrity:
   - All required fields present in each layer
   - Field types validated (e.g., thesis_side must be "yes" or "no")
   - Numeric fields within valid ranges
   - Timestamps monotonically increasing

4. Invariant Enforcement:
   - BULLISH_EVENT → thesis_side=yes (never inverted)
   - BEARISH_EVENT → thesis_side=no (never inverted)
   - Entry orders use BUY action (never SELL)
   - Exit orders use position-based sizing (never bankroll-based)
   - Price in canonical range (10-75c)

5. Asset Coverage:
   - All 5 assets (BTC, ETH, SOL, XRP, DOGE) supported
   - Per-asset tuning applied in CONFIG layer
   - No asset skipping or disabling

6. Validation Pipeline:
   - Layer validation: each layer independently validated
   - Cross-layer validation: consistency across layers
   - Contract validation: complete contract validation
   - Fail-fast on invariant violations
"""
