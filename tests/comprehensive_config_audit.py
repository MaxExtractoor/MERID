"""
Comprehensive Configuration Audit Script

Exposes all flaws and discrepancies across max notionals, max contracts, 
max/min thresholds, settings, configurations, and anything else that affects 
the behavior of the production stack.

Audit Scope:
- UPSTREAM: Profile YAML, risk parameters, agent manifests
- MIDSTREAM: Risk envelope, profile adapter
- DOWNSTREAM: Unified sizing, execution logic
- EXECUTION: Agent grid, order gate, order router

Critical Parameters Audited:
1. Max notionals (per asset, per agent, per order, total venue)
2. Max contracts (per order, per asset, total)
3. Risk percentages (per trade, per window, per asset)
4. Thresholds (edge, confidence, price, spread, depth)
5. Velocity thresholds (per asset)
6. Window-based risk limits (3% per agent, 5% total per 15m)
7. Price caps (min/max entry prices)
8. Depth thresholds (per asset)
9. Order rate limits (per minute, per 15m window)
10. Legacy contamination checks
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from decimal import Decimal
import yaml
import re

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Simple logger wrapper to avoid logging module issues
class SimpleLogger:
    def info(self, msg):
        print(f"[INFO] {msg}")
    def error(self, msg):
        print(f"[ERROR] {msg}")
    def warning(self, msg):
        print(f"[WARNING] {msg}")

logger = SimpleLogger()


@dataclass
class ParameterDiscrepancy:
    """Represents a discrepancy found during audit."""
    parameter_name: str
    layer: str  # UPSTREAM, MIDSTREAM, DOWNSTREAM, EXECUTION
    source_file: str
    expected_value: Any
    actual_value: Any
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    description: str
    recommendation: str = ""


@dataclass
class LayerConfiguration:
    """Configuration extracted from a specific layer."""
    layer_name: str
    source_file: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    discrepancies: List[ParameterDiscrepancy] = field(default_factory=list)


class ComprehensiveConfigAudit:
    """Comprehensive audit of all configuration layers."""
    
    def __init__(self):
        self.layers: Dict[str, LayerConfiguration] = {}
        self.all_discrepancies: List[ParameterDiscrepancy] = []
        self.assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
    def run_audit(self) -> Dict[str, Any]:
        """Run comprehensive audit and return results."""
        logger.info("=" * 80)
        logger.info("COMPREHENSIVE CONFIGURATION AUDIT STARTING")
        logger.info("=" * 80)
        
        # Extract configurations from all layers
        self._extract_upstream_config()
        self._extract_midstream_config()
        self._extract_downstream_config()
        self._extract_execution_config()
        
        # Cross-validate across layers
        self._validate_max_notionals()
        self._validate_max_contracts()
        self._validate_risk_percentages()
        self._validate_thresholds()
        self._validate_velocity_thresholds()
        self._validate_window_limits()
        self._validate_price_caps()
        self._validate_depth_thresholds()
        self._validate_order_rate_limits()
        self._check_legacy_contamination()
        self._validate_asset_consistency()
        
        # Generate report
        report = self._generate_report()
        
        logger.info("=" * 80)
        logger.info("COMPREHENSIVE CONFIGURATION AUDIT COMPLETE")
        logger.info("=" * 80)
        
        return report
    
    def _extract_upstream_config(self):
        """Extract configuration from upstream layer (YAML, risk parameters)."""
        logger.info("\n[UPSTREAM] Extracting configuration...")
        
        # Profile YAML
        profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        if profile_path.exists():
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile_config = yaml.safe_load(f)
            
            upstream = LayerConfiguration("UPSTREAM", str(profile_path))
            
            # Extract critical parameters
            upstream.parameters["profile_name"] = profile_config.get("profile_name")
            upstream.parameters["profile_version"] = profile_config.get("profile_version")
            
            # Venue caps
            venue = profile_config.get("venue", {})
            upstream.parameters["venue_max_single_order_pct"] = self._extract_nested_value(venue.get("max_single_order_pct"))
            upstream.parameters["venue_max_total_notional_pct"] = self._extract_nested_value(venue.get("max_total_notional_pct"))
            upstream.parameters["venue_bankroll_cap_pct"] = self._extract_nested_value(venue.get("bankroll_cap_pct"))
            
            # Agent defaults
            agent_defaults = profile_config.get("agent_defaults", {})
            upstream.parameters["agent_max_notional_pct"] = self._extract_nested_value(agent_defaults.get("max_notional_pct"))
            upstream.parameters["agent_max_orders_per_window"] = agent_defaults.get("max_orders_per_window")
            upstream.parameters["agent_max_yes_position"] = agent_defaults.get("max_yes_position")
            upstream.parameters["agent_max_no_position"] = agent_defaults.get("max_no_position")
            
            # Window-based risk limits
            upstream.parameters["guardrails_per_window_risk_pct"] = self._extract_nested_value(profile_config.get("guardrails_per_window_risk_pct"))
            upstream.parameters["guardrails_total_venue_risk_pct"] = self._extract_nested_value(profile_config.get("guardrails_total_venue_risk_pct"))
            
            # Per-asset configurations
            assets = profile_config.get("assets", {})
            for asset in self.assets:
                if asset in assets:
                    asset_config = assets[asset]
                    upstream.parameters[f"{asset}_max_notional_pct"] = self._extract_nested_value(asset_config.get("max_notional_pct"))
                    upstream.parameters[f"{asset}_max_contracts"] = asset_config.get("max_contracts")
                    upstream.parameters[f"{asset}_min_depth_yes"] = asset_config.get("min_depth_yes")
                    upstream.parameters[f"{asset}_min_depth_no"] = asset_config.get("min_depth_no")
            
            # Guardrails
            guardrails = profile_config.get("guardrails", {})
            upstream.parameters["guardrails_per_trade_risk_pct"] = self._extract_nested_value(guardrails.get("per_trade_risk_pct"))
            upstream.parameters["guardrails_max_spread_cents"] = guardrails.get("max_spread_cents")
            upstream.parameters["guardrails_min_contract_price_cents"] = guardrails.get("min_contract_price_cents")
            upstream.parameters["guardrails_max_contract_price_cents"] = guardrails.get("max_contract_price_cents")
            
            # Price range
            price_range = profile_config.get("price_range", {})
            upstream.parameters["price_range_min_cents"] = price_range.get("min_price_cents")
            upstream.parameters["price_range_max_cents"] = price_range.get("max_price_cents")
            
            # Throttling
            throttling = profile_config.get("throttling", {})
            upstream.parameters["throttling_global_orders_limit"] = throttling.get("global_orders_limit")
            upstream.parameters["throttling_max_orders_per_15m_window"] = throttling.get("max_orders_per_15m_window")
            
            # Velocity thresholds
            velocity_thresholds = profile_config.get("velocity_thresholds", {})
            for asset in self.assets:
                if asset.lower() in velocity_thresholds:
                    upstream.parameters[f"{asset}_velocity_threshold"] = velocity_thresholds[asset.lower()]
            
            # Kelly
            kelly = profile_config.get("kelly", {})
            upstream.parameters["kelly_hard_cap"] = kelly.get("kelly_hard_cap")
            upstream.parameters["kelly_global_notional_cap_pct"] = kelly.get("kelly_global_notional_cap_pct")
            
            # Confidence
            confidence = profile_config.get("confidence", {})
            upstream.parameters["confidence_min_confidence_threshold"] = confidence.get("min_confidence_threshold")
            
            self.layers["UPSTREAM"] = upstream
            logger.info(f"[UPSTREAM] Extracted {len(upstream.parameters)} parameters from profile YAML")
        else:
            logger.error(f"[UPSTREAM] Profile YAML not found: {profile_path}")
        
        # Risk parameters (constants file)
        risk_params_path = project_root / "merid" / "event_venues" / "kalshi" / "risk_parameters.py"
        if risk_params_path.exists():
            with open(risk_params_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract constants using regex
            upstream_risk = LayerConfiguration("UPSTREAM_RISK_PARAMS", str(risk_params_path))
            
            # Price bands
            upstream_risk.parameters["DEEP_OTM_CHEAP_CENTS"] = self._extract_constant(content, "DEEP_OTM_CHEAP_CENTS")
            upstream_risk.parameters["DEEP_OTM_EXPENSIVE_CENTS"] = self._extract_constant(content, "DEEP_OTM_EXPENSIVE_CENTS")
            upstream_risk.parameters["MIN_KALSHI_PRICE_CENTS"] = self._extract_constant(content, "MIN_KALSHI_PRICE_CENTS")
            upstream_risk.parameters["MAX_KALSHI_PRICE_CENTS"] = self._extract_constant(content, "MAX_KALSHI_PRICE_CENTS")
            
            # Size thresholds
            upstream_risk.parameters["MIN_CONTRACTS"] = self._extract_constant(content, "MIN_CONTRACTS")
            upstream_risk.parameters["MAX_CONTRACTS_DEFAULT"] = self._extract_constant(content, "MAX_CONTRACTS_DEFAULT")
            
            # Risk percentages
            upstream_risk.parameters["SIZER_MAX_BANKROLL_PCT"] = self._extract_constant(content, "SIZER_MAX_BANKROLL_PCT")
            upstream_risk.parameters["SIZER_MIN_BANKROLL_PCT"] = self._extract_constant(content, "SIZER_MIN_BANKROLL_PCT")
            
            # Edge thresholds
            upstream_risk.parameters["MIN_EDGE_PCT"] = self._extract_constant(content, "MIN_EDGE_PCT")
            
            # Kelly
            upstream_risk.parameters["DEFAULT_KELLY_FRACTION"] = self._extract_constant(content, "DEFAULT_KELLY_FRACTION")
            
            # Deep OTM/ITM thresholds
            upstream_risk.parameters["DEEP_OTM_THRESHOLD_CENTS"] = self._extract_constant(content, "DEEP_OTM_THRESHOLD_CENTS")
            upstream_risk.parameters["DEEP_ITM_THRESHOLD_CENTS"] = self._extract_constant(content, "DEEP_ITM_THRESHOLD_CENTS")
            
            self.layers["UPSTREAM_RISK_PARAMS"] = upstream_risk
            logger.info(f"[UPSTREAM_RISK_PARAMS] Extracted {len(upstream_risk.parameters)} constants from risk_parameters.py")
    
    def _extract_midstream_config(self):
        """Extract configuration from midstream layer (risk envelope, profile adapter)."""
        logger.info("\n[MIDSTREAM] Extracting configuration...")
        
        # Risk envelope - dataclass fields
        risk_envelope_path = project_root / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
        if risk_envelope_path.exists():
            with open(risk_envelope_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            midstream = LayerConfiguration("MIDSTREAM_RISK_ENVELOPE", str(risk_envelope_path))
            
            # Extract dataclass field defaults
            midstream.parameters["default_max_single_order_pct"] = self._extract_dataclass_default(content, "max_single_order_pct")
            midstream.parameters["default_max_total_notional_pct"] = self._extract_dataclass_default(content, "max_total_notional_pct")
            midstream.parameters["default_agent_max_notional_pct"] = self._extract_dataclass_default(content, "agent_max_notional_pct")
            midstream.parameters["default_per_trade_risk_pct"] = self._extract_dataclass_default(content, "per_trade_risk_pct")
            midstream.parameters["default_guardrails_per_window_risk_pct"] = self._extract_dataclass_default(content, "guardrails_per_window_risk_pct")
            midstream.parameters["default_guardrails_total_venue_risk_pct"] = self._extract_dataclass_default(content, "guardrails_total_venue_risk_pct")
            
            self.layers["MIDSTREAM_RISK_ENVELOPE"] = midstream
            logger.info(f"[MIDSTREAM_RISK_ENVELOPE] Extracted {len(midstream.parameters)} default parameters")
        
        # Profile adapter
        profile_adapter_path = project_root / "merid" / "risk" / "profiles" / "crypto_15m_profile.py"
        if profile_adapter_path.exists():
            with open(profile_adapter_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            midstream_adapter = LayerConfiguration("MIDSTREAM_PROFILE_ADAPTER", str(profile_adapter_path))
            
            # Extract default values from dataclass
            midstream_adapter.parameters["default_agent_max_notional_pct"] = self._extract_dataclass_default(content, "agent_max_notional_pct")
            midstream_adapter.parameters["default_venue_max_total_notional_pct"] = self._extract_dataclass_default(content, "venue_max_total_notional_pct")
            midstream_adapter.parameters["default_guardrails_per_trade_risk_pct"] = self._extract_dataclass_default(content, "guardrails_per_trade_risk_pct")
            midstream_adapter.parameters["default_guardrails_per_window_risk_pct"] = self._extract_dataclass_default(content, "guardrails_per_window_risk_pct")
            midstream_adapter.parameters["default_guardrails_total_venue_risk_pct"] = self._extract_dataclass_default(content, "guardrails_total_venue_risk_pct")
            
            self.layers["MIDSTREAM_PROFILE_ADAPTER"] = midstream_adapter
            logger.info(f"[MIDSTREAM_PROFILE_ADAPTER] Extracted {len(midstream_adapter.parameters)} default parameters")
    
    def _extract_downstream_config(self):
        """Extract configuration from downstream layer (unified sizing)."""
        logger.info("\n[DOWNSTREAM] Extracting configuration...")
        
        sizing_path = project_root / "merid" / "prediction" / "unified_sizing.py"
        if sizing_path.exists():
            with open(sizing_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            downstream = LayerConfiguration("DOWNSTREAM_UNIFIED_SIZING", str(sizing_path))
            
            # Extract function return values and hardcoded defaults
            downstream.parameters["regime_multiplier_default"] = self._extract_function_return(content, "_get_regime_position_size_multiplier")
            downstream.parameters["tte_multiplier_default"] = self._extract_function_return(content, "_get_tte_position_size_multiplier")
            
            # Check if dynamic sizing is enabled/disabled
            downstream.parameters["dynamic_sizing_enabled"] = "return 1.0" not in content.split("_get_regime_position_size_multiplier")[1].split("def _get_tte_position_size_multiplier")[0]
            
            self.layers["DOWNSTREAM_UNIFIED_SIZING"] = downstream
            logger.info(f"[DOWNSTREAM_UNIFIED_SIZING] Extracted {len(downstream.parameters)} parameters")
    
    def _extract_execution_config(self):
        """Extract configuration from execution layer (agent grid, order gate, order router)."""
        logger.info("\n[EXECUTION] Extracting configuration...")
        
        # Agent grid
        agent_grid_path = project_root / "merid" / "prediction" / "agent_grid_15m.py"
        if agent_grid_path.exists():
            with open(agent_grid_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            execution_grid = LayerConfiguration("EXECUTION_AGENT_GRID", str(agent_grid_path))
            
            # Extract LeanAgentConfig defaults
            execution_grid.parameters["agent_grid_max_spread_cents"] = self._extract_dataclass_default(content, "max_spread_cents")
            execution_grid.parameters["agent_grid_per_strip_order_limit"] = self._extract_dataclass_default(content, "per_strip_order_limit")
            execution_grid.parameters["agent_grid_max_orders_per_15m_window"] = self._extract_dataclass_default(content, "max_orders_per_15m_window")
            execution_grid.parameters["agent_grid_velocity_threshold"] = self._extract_dataclass_default(content, "velocity_threshold")
            
            # Per-asset velocity thresholds
            for asset in self.assets:
                param_name = f"agent_grid_velocity_threshold_{asset.lower()}"
                execution_grid.parameters[param_name] = self._extract_dataclass_default(content, f"velocity_threshold_{asset.lower()}")
            
            # Hybrid mode price caps
            execution_grid.parameters["agent_grid_max_entry_price_yes"] = self._extract_dataclass_default(content, "max_entry_price_yes")
            execution_grid.parameters["agent_grid_min_entry_price_no"] = self._extract_dataclass_default(content, "min_entry_price_no")
            
            self.layers["EXECUTION_AGENT_GRID"] = execution_grid
            logger.info(f"[EXECUTION_AGENT_GRID] Extracted {len(execution_grid.parameters)} parameters")
        
        # Order gate
        order_gate_path = project_root / "merid" / "event_venues" / "kalshi" / "order_gate.py"
        if order_gate_path.exists():
            with open(order_gate_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            execution_gate = LayerConfiguration("EXECUTION_ORDER_GATE", str(order_gate_path))
            
            # Check for window limit enforcement
            execution_gate.parameters["order_gate_window_limit_enforced"] = "blocked_window_limit" in content
            
            self.layers["EXECUTION_ORDER_GATE"] = execution_gate
            logger.info(f"[EXECUTION_ORDER_GATE] Extracted {len(execution_gate.parameters)} parameters")
        
        # Order router
        order_router_path = project_root / "merid" / "event_venues" / "kalshi" / "order_router.py"
        if order_router_path.exists():
            with open(order_router_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            execution_router = LayerConfiguration("EXECUTION_ORDER_ROUTER", str(order_router_path))
            
            # Extract microstructure defaults
            execution_router.parameters["order_router_max_spread_cents"] = self._extract_function_default(content, "check_market_microstructure", "max_spread_cents")
            execution_router.parameters["order_router_min_depth_usd"] = self._extract_function_default(content, "check_market_microstructure", "min_depth_usd")
            
            self.layers["EXECUTION_ORDER_ROUTER"] = execution_router
            logger.info(f"[EXECUTION_ORDER_ROUTER] Extracted {len(execution_router.parameters)} parameters")
    
    def _validate_max_notionals(self):
        """Validate max notional consistency across layers."""
        logger.info("\n[VALIDATION] Checking max notional consistency...")
        
        upstream = self.layers.get("UPSTREAM")
        if not upstream:
            return
        
        # Expected values from profile YAML
        expected_single_order_pct = upstream.parameters.get("venue_max_single_order_pct")
        expected_total_notional_pct = upstream.parameters.get("venue_max_total_notional_pct")
        expected_agent_notional_pct = upstream.parameters.get("agent_max_notional_pct")
        expected_bankroll_cap_pct = upstream.parameters.get("venue_bankroll_cap_pct")
        
        # Check midstream defaults
        midstream_envelope = self.layers.get("MIDSTREAM_RISK_ENVELOPE")
        if midstream_envelope:
            actual_single_order = midstream_envelope.parameters.get("default_max_single_order_pct")
            if actual_single_order and expected_single_order_pct and actual_single_order != expected_single_order_pct:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="max_single_order_pct",
                    layer="MIDSTREAM",
                    source_file=midstream_envelope.source_file,
                    expected_value=expected_single_order_pct,
                    actual_value=actual_single_order,
                    severity="HIGH",
                    description="Risk envelope default doesn't match profile YAML",
                    recommendation="Update risk envelope default to match profile YAML value"
                ))
            
            actual_total_notional = midstream_envelope.parameters.get("default_max_total_notional_pct")
            if actual_total_notional and expected_total_notional_pct and actual_total_notional != expected_total_notional_pct:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="max_total_notional_pct",
                    layer="MIDSTREAM",
                    source_file=midstream_envelope.source_file,
                    expected_value=expected_total_notional_pct,
                    actual_value=actual_total_notional,
                    severity="HIGH",
                    description="Risk envelope default doesn't match profile YAML",
                    recommendation="Update risk envelope default to match profile YAML value"
                ))
            
            actual_agent_notional = midstream_envelope.parameters.get("default_agent_max_notional_pct")
            if actual_agent_notional and expected_agent_notional_pct and actual_agent_notional != expected_agent_notional_pct:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="agent_max_notional_pct",
                    layer="MIDSTREAM",
                    source_file=midstream_envelope.source_file,
                    expected_value=expected_agent_notional_pct,
                    actual_value=actual_agent_notional,
                    severity="HIGH",
                    description="Risk envelope default doesn't match profile YAML",
                    recommendation="Update risk envelope default to match profile YAML value"
                ))
        
        # Check profile adapter defaults
        midstream_adapter = self.layers.get("MIDSTREAM_PROFILE_ADAPTER")
        if midstream_adapter:
            adapter_single_order = midstream_adapter.parameters.get("default_venue_max_total_notional_pct")
            if adapter_single_order and expected_total_notional_pct and adapter_single_order != expected_total_notional_pct:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="venue_max_total_notional_pct",
                    layer="MIDSTREAM",
                    source_file=midstream_adapter.source_file,
                    expected_value=expected_total_notional_pct,
                    actual_value=adapter_single_order,
                    severity="HIGH",
                    description="Profile adapter default doesn't match profile YAML",
                    recommendation="Update profile adapter default to match profile YAML value"
                ))
    
    def _validate_max_contracts(self):
        """Validate max contract consistency across layers."""
        logger.info("\n[VALIDATION] Checking max contract consistency...")
        
        upstream = self.layers.get("UPSTREAM")
        if not upstream:
            return
        
        # Check per-asset max contracts
        for asset in self.assets:
            expected_contracts = upstream.parameters.get(f"{asset}_max_contracts")
            if expected_contracts:
                # Check if all assets have the same max contracts (should be consistent)
                # Or if they have asset-specific values (should be documented)
                pass
        
        # Check upstream risk parameters
        upstream_risk = self.layers.get("UPSTREAM_RISK_PARAMS")
        if upstream_risk:
            risk_min_contracts = upstream_risk.parameters.get("MIN_CONTRACTS")
            risk_max_contracts = upstream_risk.parameters.get("MAX_CONTRACTS_DEFAULT")
            
            # Check if these match profile YAML
            if risk_min_contracts != 1:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="MIN_CONTRACTS",
                    layer="UPSTREAM_RISK_PARAMS",
                    source_file=upstream_risk.source_file,
                    expected_value=1,
                    actual_value=risk_min_contracts,
                    severity="MEDIUM",
                    description="MIN_CONTRACTS constant doesn't match expected value of 1",
                    recommendation="Update MIN_CONTRACTS to 1 or document why different value is needed"
                ))
    
    def _validate_risk_percentages(self):
        """Validate risk percentage consistency across layers."""
        logger.info("\n[VALIDATION] Checking risk percentage consistency...")
        
        upstream = self.layers.get("UPSTREAM")
        if not upstream:
            return
        
        # Window-based risk limits (CRITICAL)
        expected_per_window = upstream.parameters.get("guardrails_per_window_risk_pct")
        expected_total_venue = upstream.parameters.get("guardrails_total_venue_risk_pct")
        expected_per_trade = upstream.parameters.get("guardrails_per_trade_risk_pct")
        
        # Check midstream
        midstream_envelope = self.layers.get("MIDSTREAM_RISK_ENVELOPE")
        if midstream_envelope:
            actual_per_window = midstream_envelope.parameters.get("default_guardrails_per_window_risk_pct")
            if actual_per_window and expected_per_window and actual_per_window != expected_per_window:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="guardrails_per_window_risk_pct",
                    layer="MIDSTREAM",
                    source_file=midstream_envelope.source_file,
                    expected_value=expected_per_window,
                    actual_value=actual_per_window,
                    severity="CRITICAL",
                    description="Window-based risk limit default doesn't match profile YAML (3% per agent HARD STOP)",
                    recommendation="Update risk envelope default to match profile YAML - this is a HARD STOP limit"
                ))
            
            actual_total_venue = midstream_envelope.parameters.get("default_guardrails_total_venue_risk_pct")
            if actual_total_venue and expected_total_venue and actual_total_venue != expected_total_venue:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="guardrails_total_venue_risk_pct",
                    layer="MIDSTREAM",
                    source_file=midstream_envelope.source_file,
                    expected_value=expected_total_venue,
                    actual_value=actual_total_venue,
                    severity="CRITICAL",
                    description="Total venue window limit default doesn't match profile YAML (5% total HARD STOP)",
                    recommendation="Update risk envelope default to match profile YAML - this is a HARD STOP limit"
                ))
            
            actual_per_trade = midstream_envelope.parameters.get("default_per_trade_risk_pct")
            if actual_per_trade and expected_per_trade and actual_per_trade != expected_per_trade:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="per_trade_risk_pct",
                    layer="MIDSTREAM",
                    source_file=midstream_envelope.source_file,
                    expected_value=expected_per_trade,
                    actual_value=actual_per_trade,
                    severity="HIGH",
                    description="Per-trade risk default doesn't match profile YAML",
                    recommendation="Update risk envelope default to match profile YAML"
                ))
        
        # Check profile adapter
        midstream_adapter = self.layers.get("MIDSTREAM_PROFILE_ADAPTER")
        if midstream_adapter:
            adapter_per_window = midstream_adapter.parameters.get("default_guardrails_per_window_risk_pct")
            if adapter_per_window and expected_per_window and adapter_per_window != expected_per_window:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="guardrails_per_window_risk_pct",
                    layer="MIDSTREAM",
                    source_file=midstream_adapter.source_file,
                    expected_value=expected_per_window,
                    actual_value=adapter_per_window,
                    severity="CRITICAL",
                    description="Profile adapter window limit default doesn't match profile YAML",
                    recommendation="Update profile adapter default to match profile YAML"
                ))
    
    def _validate_thresholds(self):
        """Validate threshold consistency across layers."""
        logger.info("\n[VALIDATION] Checking threshold consistency...")
        
        upstream = self.layers.get("UPSTREAM")
        if not upstream:
            return
        
        # Price range thresholds
        expected_min_price = upstream.parameters.get("price_range_min_cents")
        expected_max_price = upstream.parameters.get("price_range_max_cents")
        expected_min_contract = upstream.parameters.get("guardrails_min_contract_price_cents")
        expected_max_contract = upstream.parameters.get("guardrails_max_contract_price_cents")
        
        # Check upstream risk parameters
        upstream_risk = self.layers.get("UPSTREAM_RISK_PARAMS")
        if upstream_risk:
            risk_deep_otm_cheap = upstream_risk.parameters.get("DEEP_OTM_CHEAP_CENTS")
            risk_deep_otm_expensive = upstream_risk.parameters.get("DEEP_OTM_EXPENSIVE_CENTS")
            
            # DEEP_OTM_EXPENSIVE_CENTS should match max contract price (75c threshold)
            if risk_deep_otm_expensive and expected_max_contract and risk_deep_otm_expensive != expected_max_contract:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="DEEP_OTM_EXPENSIVE_CENTS",
                    layer="UPSTREAM_RISK_PARAMS",
                    source_file=upstream_risk.source_file,
                    expected_value=expected_max_contract,
                    actual_value=risk_deep_otm_expensive,
                    severity="CRITICAL",
                    description="75c threshold strategy violation - DEEP_OTM_EXPENSIVE_CENTS should match max_contract_price_cents",
                    recommendation="Update DEEP_OTM_EXPENSIVE_CENTS to 75 to match profile YAML sweet spot threshold"
                ))
            
            # DEEP_OTM_CHEAP_CENTS should match min contract price (10c threshold)
            if risk_deep_otm_cheap and expected_min_contract and risk_deep_otm_cheap != expected_min_contract:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="DEEP_OTM_CHEAP_CENTS",
                    layer="UPSTREAM_RISK_PARAMS",
                    source_file=upstream_risk.source_file,
                    expected_value=expected_min_contract,
                    actual_value=risk_deep_otm_cheap,
                    severity="HIGH",
                    description="DEEP_OTM_CHEAP_CENTS doesn't match min_contract_price_cents",
                    recommendation="Update DEEP_OTM_CHEAP_CENTS to match profile YAML min contract price"
                ))
        
        # Check execution layer
        execution_grid = self.layers.get("EXECUTION_AGENT_GRID")
        if execution_grid:
            grid_max_yes = execution_grid.parameters.get("agent_grid_max_entry_price_yes")
            grid_min_no = execution_grid.parameters.get("agent_grid_min_entry_price_no")
            
            # Extract hybrid section values from profile YAML (they use decimal, not cents)
            profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profile_config = yaml.safe_load(f)
                
                hybrid = profile_config.get("hybrid", {})
                hybrid_max_yes = hybrid.get("max_entry_price_yes")
                hybrid_min_no = hybrid.get("min_entry_price_no")
                
                # These should match profile YAML hybrid section (decimal values)
                if grid_max_yes and hybrid_max_yes and grid_max_yes != hybrid_max_yes:
                    self.all_discrepancies.append(ParameterDiscrepancy(
                        parameter_name="max_entry_price_yes",
                        layer="EXECUTION",
                        source_file=execution_grid.source_file,
                        expected_value=hybrid_max_yes,
                        actual_value=grid_max_yes,
                        severity="HIGH",
                        description="Agent grid hybrid price cap doesn't match profile YAML hybrid section",
                        recommendation="Update agent grid default to match profile YAML hybrid.max_entry_price_yes"
                    ))
                
                if grid_min_no and hybrid_min_no and grid_min_no != hybrid_min_no:
                    self.all_discrepancies.append(ParameterDiscrepancy(
                        parameter_name="min_entry_price_no",
                        layer="EXECUTION",
                        source_file=execution_grid.source_file,
                        expected_value=hybrid_min_no,
                        actual_value=grid_min_no,
                        severity="HIGH",
                        description="Agent grid hybrid price cap doesn't match profile YAML hybrid section",
                        recommendation="Update agent grid default to match profile YAML hybrid.min_entry_price_no"
                    ))
    
    def _validate_velocity_thresholds(self):
        """Validate velocity threshold consistency across layers."""
        logger.info("\n[VALIDATION] Checking velocity threshold consistency...")
        
        upstream = self.layers.get("UPSTREAM")
        if not upstream:
            return
        
        # Check per-asset velocity thresholds
        for asset in self.assets:
            expected_threshold = upstream.parameters.get(f"{asset}_velocity_threshold")
            
            # Check execution layer
            execution_grid = self.layers.get("EXECUTION_AGENT_GRID")
            if execution_grid:
                grid_threshold = execution_grid.parameters.get(f"agent_grid_velocity_threshold_{asset.lower()}")
                if grid_threshold and expected_threshold and grid_threshold != expected_threshold:
                    self.all_discrepancies.append(ParameterDiscrepancy(
                        parameter_name=f"{asset}_velocity_threshold",
                        layer="EXECUTION",
                        source_file=execution_grid.source_file,
                        expected_value=expected_threshold,
                        actual_value=grid_threshold,
                        severity="HIGH",
                        description=f"Agent grid velocity threshold for {asset} doesn't match profile YAML",
                        recommendation=f"Update agent grid default to match profile YAML velocity_thresholds.{asset.lower()}"
                    ))
    
    def _validate_window_limits(self):
        """Validate window-based risk limit enforcement."""
        logger.info("\n[VALIDATION] Checking window-based risk limit enforcement...")
        
        # Check if order gate enforces window limits
        order_gate = self.layers.get("EXECUTION_ORDER_GATE")
        if order_gate:
            window_enforced = order_gate.parameters.get("order_gate_window_limit_enforced")
            if not window_enforced:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="window_limit_enforcement",
                    layer="EXECUTION",
                    source_file=order_gate.source_file,
                    expected_value=True,
                    actual_value=False,
                    severity="CRITICAL",
                    description="Order gate doesn't enforce window-based risk limits (3% per agent, 5% total per 15m)",
                    recommendation="Add window limit check in order gate to enforce HARD STOP limits"
                ))
    
    def _validate_price_caps(self):
        """Validate price cap consistency."""
        logger.info("\n[VALIDATION] Checking price cap consistency...")
        
        upstream = self.layers.get("UPSTREAM")
        if not upstream:
            return
        
        # Check that price_range matches guardrails contract price limits
        price_min = upstream.parameters.get("price_range_min_cents")
        price_max = upstream.parameters.get("price_range_max_cents")
        contract_min = upstream.parameters.get("guardrails_min_contract_price_cents")
        contract_max = upstream.parameters.get("guardrails_max_contract_price_cents")
        
        if price_min and contract_min and price_min != contract_min:
            self.all_discrepancies.append(ParameterDiscrepancy(
                parameter_name="price_range_min_cents",
                layer="UPSTREAM",
                source_file=upstream.source_file,
                expected_value=contract_min,
                actual_value=price_min,
                severity="MEDIUM",
                description="price_range.min doesn't match guardrails.min_contract_price_cents",
                recommendation="Align price_range.min with guardrails.min_contract_price_cents for consistency"
            ))
        
        if price_max and contract_max and price_max != contract_max:
            self.all_discrepancies.append(ParameterDiscrepancy(
                parameter_name="price_range_max_cents",
                layer="UPSTREAM",
                source_file=upstream.source_file,
                expected_value=contract_max,
                actual_value=price_max,
                severity="MEDIUM",
                description="price_range.max doesn't match guardrails.max_contract_price_cents",
                recommendation="Align price_range.max with guardrails.max_contract_price_cents for consistency"
            ))
    
    def _validate_depth_thresholds(self):
        """Validate depth threshold consistency."""
        logger.info("\n[VALIDATION] Checking depth threshold consistency...")
        
        upstream = self.layers.get("UPSTREAM")
        if not upstream:
            return
        
        # Check per-asset depth thresholds
        for asset in self.assets:
            min_depth_yes = upstream.parameters.get(f"{asset}_min_depth_yes")
            min_depth_no = upstream.parameters.get(f"{asset}_min_depth_no")
            
            # All assets should have depth thresholds defined
            if min_depth_yes is None:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name=f"{asset}_min_depth_yes",
                    layer="UPSTREAM",
                    source_file=upstream.source_file,
                    expected_value="defined",
                    actual_value=None,
                    severity="MEDIUM",
                    description=f"Missing min_depth_yes for {asset}",
                    recommendation="Add min_depth_yes to profile YAML assets section"
                ))
            
            if min_depth_no is None:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name=f"{asset}_min_depth_no",
                    layer="UPSTREAM",
                    source_file=upstream.source_file,
                    expected_value="defined",
                    actual_value=None,
                    severity="MEDIUM",
                    description=f"Missing min_depth_no for {asset}",
                    recommendation="Add min_depth_no to profile YAML assets section"
                ))
    
    def _validate_order_rate_limits(self):
        """Validate order rate limit consistency."""
        logger.info("\n[VALIDATION] Checking order rate limit consistency...")
        
        upstream = self.layers.get("UPSTREAM")
        if not upstream:
            return
        
        # Check throttling parameters
        global_limit = upstream.parameters.get("throttling_global_orders_limit")
        window_limit = upstream.parameters.get("throttling_max_orders_per_15m_window")
        
        # Check execution layer
        execution_grid = self.layers.get("EXECUTION_AGENT_GRID")
        if execution_grid:
            grid_window_limit = execution_grid.parameters.get("agent_grid_max_orders_per_15m_window")
            if grid_window_limit and window_limit and grid_window_limit != window_limit:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="max_orders_per_15m_window",
                    layer="EXECUTION",
                    source_file=execution_grid.source_file,
                    expected_value=window_limit,
                    actual_value=grid_window_limit,
                    severity="HIGH",
                    description="Agent grid order limit doesn't match profile YAML throttling",
                    recommendation="Update agent grid default to match profile YAML throttling.max_orders_per_15m_window"
                ))
    
    def _check_legacy_contamination(self):
        """Check for legacy code contamination."""
        logger.info("\n[VALIDATION] Checking for legacy contamination...")
        
        # Check if main.py is being used instead of main_15m_lean.py
        main_py_path = project_root / "web" / "main.py"
        main_15m_path = project_root / "web" / "main_15m_lean.py"
        
        if main_py_path.exists() and main_15m_path.exists():
            # Check if main_15m_lean.py is the production entry point
            with open(main_15m_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if "main_15m_lean" not in content.lower():
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name="production_entry_point",
                    layer="INFRASTRUCTURE",
                    source_file="web/main_15m_lean.py",
                    expected_value="main_15m_lean.py",
                    actual_value="unclear",
                    severity="CRITICAL",
                    description="Production entry point may not be main_15m_lean.py",
                    recommendation="Verify that main_15m_lean.py is the production entry point, not legacy main.py"
                ))
    
    def _validate_asset_consistency(self):
        """Validate that all 5 assets are treated consistently."""
        logger.info("\n[VALIDATION] Checking asset consistency...")
        
        upstream = self.layers.get("UPSTREAM")
        if not upstream:
            return
        
        # Check that all 5 assets have configurations
        for asset in self.assets:
            has_config = any(f"{asset}_" in key for key in upstream.parameters.keys())
            if not has_config:
                self.all_discrepancies.append(ParameterDiscrepancy(
                    parameter_name=f"{asset}_configuration",
                    layer="UPSTREAM",
                    source_file=upstream.source_file,
                    expected_value="defined",
                    actual_value="missing",
                    severity="CRITICAL",
                    description=f"Asset {asset} is missing from profile configuration",
                    recommendation=f"Add {asset} to profile YAML assets section - all 5 crypto assets must be configured"
                ))
    
    def _generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive audit report."""
        logger.info("\n[REPORT] Generating audit report...")
        
        # Count discrepancies by severity
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for discrepancy in self.all_discrepancies:
            severity_counts[discrepancy.severity] += 1
        
        report = {
            "summary": {
                "total_discrepancies": len(self.all_discrepancies),
                "critical": severity_counts["CRITICAL"],
                "high": severity_counts["HIGH"],
                "medium": severity_counts["MEDIUM"],
                "low": severity_counts["LOW"],
                "layers_audited": list(self.layers.keys()),
                "parameters_extracted": sum(len(layer.parameters) for layer in self.layers.values())
            },
            "discrepancies": [
                {
                    "parameter": d.parameter_name,
                    "layer": d.layer,
                    "source_file": d.source_file,
                    "expected": d.expected_value,
                    "actual": d.actual_value,
                    "severity": d.severity,
                    "description": d.description,
                    "recommendation": d.recommendation
                }
                for d in self.all_discrepancies
            ],
            "layer_configurations": {
                layer_name: {
                    "source_file": layer.source_file,
                    "parameter_count": len(layer.parameters),
                    "parameters": layer.parameters
                }
                for layer_name, layer in self.layers.items()
            }
        }
        
        # Print summary
        print("\n" + "=" * 80)
        print("AUDIT SUMMARY")
        print("=" * 80)
        print(f"Total Discrepancies: {report['summary']['total_discrepancies']}")
        print(f"  CRITICAL: {report['summary']['critical']}")
        print(f"  HIGH: {report['summary']['high']}")
        print(f"  MEDIUM: {report['summary']['medium']}")
        print(f"  LOW: {report['summary']['low']}")
        print(f"\nLayers Audited: {len(report['summary']['layers_audited'])}")
        print(f"Parameters Extracted: {report['summary']['parameters_extracted']}")
        
        # Print discrepancies by severity
        if self.all_discrepancies:
            print("\n" + "=" * 80)
            print("DISCREPANCIES BY SEVERITY")
            print("=" * 80)
            
            for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
                severity_discrepancies = [d for d in self.all_discrepancies if d.severity == severity]
                if severity_discrepancies:
                    print(f"\n{severity} ({len(severity_discrepancies)}):")
                    for d in severity_discrepancies:
                        print(f"  - {d.parameter_name}")
                        print(f"    Layer: {d.layer}")
                        print(f"    File: {d.source_file}")
                        print(f"    Expected: {d.expected_value}")
                        print(f"    Actual: {d.actual_value}")
                        print(f"    Description: {d.description}")
                        print(f"    Recommendation: {d.recommendation}")
                        print()
        
        return report
    
    # Helper methods
    def _extract_nested_value(self, value: Any) -> Any:
        """Extract value from nested dict format."""
        if isinstance(value, dict):
            return value.get("value", value)
        return value
    
    def _extract_constant(self, content: str, constant_name: str) -> Any:
        """Extract constant value from Python file."""
        pattern = rf"{constant_name}\s*:\s*Final\s*\[?\w*\]?\s*=\s*([^#\n]+)"
        match = re.search(pattern, content)
        if match:
            value_str = match.group(1).strip()
            try:
                return eval(value_str)
            except:
                return value_str
        return None
    
    def _extract_default_param(self, content: str, param_name: str) -> Any:
        """Extract default parameter value from function."""
        # Try multiple patterns
        patterns = [
            rf"{param_name}\s*=\s*profile_config\.get\([^,]+,\s*([^)]+)\)",
            rf"{param_name}\s*=\s*profile\.get\([^,]+,\s*([^)]+)\)",
            rf"{param_name}\s*=\s*([^,\n]+)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                value_str = match.group(1).strip()
                try:
                    return eval(value_str)
                except:
                    return value_str
        return None
    
    def _extract_dataclass_default(self, content: str, field_name: str) -> Any:
        """Extract default value from dataclass field."""
        pattern = rf"{field_name}\s*:\s*\w+\s*=\s*([^#\n]+)"
        match = re.search(pattern, content)
        if match:
            value_str = match.group(1).strip()
            try:
                return eval(value_str)
            except:
                return value_str
        return None
    
    def _extract_function_return(self, content: str, function_name: str) -> Any:
        """Extract return value from function."""
        # Find function definition
        pattern = rf"def {function_name}\([^)]*\)[^:]*:[^{{]*?{{([^}}]*)}}"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            function_body = match.group(1)
            # Look for return statement
            return_pattern = r"return\s+([^#\n]+)"
            return_match = re.search(return_pattern, function_body)
            if return_match:
                value_str = return_match.group(1).strip()
                try:
                    return eval(value_str)
                except:
                    return value_str
        return None
    
    def _extract_function_default(self, content: str, function_name: str, param_name: str) -> Any:
        """Extract default parameter value from function."""
        # Find function definition
        pattern = rf"def {function_name}\([^)]*\)"
        match = re.search(pattern, content)
        if match:
            function_sig = match.group(0)
            # Look for parameter default
            param_pattern = rf"{param_name}\s*=\s*([^,)]+)"
            param_match = re.search(param_pattern, function_sig)
            if param_match:
                value_str = param_match.group(1).strip()
                try:
                    return eval(value_str)
                except:
                    return value_str
        return None


def main():
    """Run comprehensive configuration audit."""
    auditor = ComprehensiveConfigAudit()
    report = auditor.run_audit()
    
    # Save report to file
    report_path = project_root / "output" / "comprehensive_config_audit_report.json"
    report_path.parent.mkdir(exist_ok=True)
    
    import json
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"\nReport saved to: {report_path}")
    
    # Exit with error code if critical discrepancies found
    if report['summary']['critical'] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
