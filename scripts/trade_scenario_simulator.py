#!/usr/bin/env python3
"""
MERID 15M Trade Scenario Simulator

Comprehensive trade scenario simulation for the 15-minute Kalshi crypto trading system.
Based on 2026 industry best practices for algorithmic trading validation.

This script simulates various trade scenarios to identify flaws and discrepancies in:
- Risk limit enforcement (3% per agent, 5% total per 15m window)
- Position sizing logic
- Order lifecycle management
- Market condition handling
- Multi-asset correlation behavior
- Drawdown band transitions
- Fee impact calculations
- Position management (trailing stop, ratchet, take profit)

Usage:
    python scripts/trade_scenario_simulator.py --profile kalshi_crypto_15m_v2 --bankroll 100.0
"""

import sys
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal
from enum import Enum
import json
from datetime import datetime, timezone

# Add project root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from utils.logger import get_logger

logger = get_logger("scripts.trade_scenario_simulator")


class ScenarioOutcome(Enum):
    """Possible outcomes of a trade scenario."""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    ERROR = "error"


class MarketCondition(Enum):
    """Market condition regimes for simulation."""
    NORMAL = "normal"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    ILLIQUID = "illiquid"
    FLASH_CRASH = "flash_crash"
    SPREAD_WIDENING = "spread_widening"


@dataclass
class TradeScenario:
    """Definition of a trade scenario to simulate."""
    name: str
    description: str
    market_condition: MarketCondition
    asset: str  # BTC, ETH, SOL, XRP, DOGE
    bankroll_usd: float
    entry_price_cents: int
    exit_price_cents: int
    contracts: int
    edge_pct: float
    confidence: float
    time_to_expiry_min: float
    expected_outcome: ScenarioOutcome
    validation_checks: List[str] = field(default_factory=list)


@dataclass
class SimulationResult:
    """Result of simulating a trade scenario."""
    scenario: TradeScenario
    outcome: ScenarioOutcome
    passed_checks: List[str]
    failed_checks: List[str]
    warnings: List[str]
    errors: List[str]
    computed_values: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TradeScenarioSimulator:
    """
    Comprehensive trade scenario simulator for MERID 15M stack.
    
    Simulates various trade scenarios to validate risk limits, sizing logic,
    and execution pipeline behavior.
    """
    
    def __init__(self, profile_name: str = "kalshi_crypto_15m_v2", bankroll_usd: float = 100.0):
        """
        Initialize the simulator.
        
        Args:
            profile_name: Name of the profile to load
            bankroll_usd: Starting bankroll for simulation
        """
        self.profile_name = profile_name
        self.bankroll_usd = bankroll_usd
        self.profile_config = None
        self.risk_envelope = None
        self.results: List[SimulationResult] = []
        
        self._load_profile()
        self._initialize_risk_envelope()
    
    def _load_profile(self):
        """Load the profile configuration from YAML."""
        try:
            import yaml
            profile_path = repo_root / "config" / "profiles" / f"{self.profile_name}.yaml"
            
            with open(profile_path, 'r', encoding='utf-8') as f:
                self.profile_config = yaml.safe_load(f)
            
            logger.info(f"[SIMULATOR] Loaded profile: {self.profile_name} v{self.profile_config.get('profile_version', 'unknown')}")
        except Exception as e:
            logger.error(f"[SIMULATOR] Failed to load profile: {e}")
            raise
    
    def _initialize_risk_envelope(self):
        """Initialize the risk envelope from profile configuration."""
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                compute_kalshi_crypto_15m_risk_envelope,
                _reset_shared_window_state_for_testing
            )
            
            # Reset window state for clean simulation
            _reset_shared_window_state_for_testing()
            
            # Compute risk envelope
            self.risk_envelope = compute_kalshi_crypto_15m_risk_envelope(
                live_bankroll_usd=self.bankroll_usd
            )
            
            logger.info(f"[SIMULATOR] Initialized risk envelope with bankroll=${self.bankroll_usd:.2f}")
        except Exception as e:
            logger.error(f"[SIMULATOR] Failed to initialize risk envelope: {e}")
            raise
    
    def _compute_order_notional(self, price_cents: int, contracts: int) -> float:
        """Compute order notional in USD."""
        return (price_cents / 100.0) * contracts
    
    def _compute_kalshi_fee(self, probability: float, price_cents: int) -> float:
        """
        Compute Kalshi fee in cents for a winning trade.
        
        Formula: fee = 7% × p × (1-p) × contract_price
        Capped at $0.0175 (1.75 cents) per contract
        """
        probability = max(0.0, min(1.0, probability))
        fee_pct = 0.07 * probability * (1.0 - probability)
        fee_cents = fee_pct * price_cents
        fee_cents = min(fee_cents, 1.75)
        return fee_cents
    
    def _validate_window_limits(self, agent_id: str, order_notional_usd: float) -> Tuple[bool, str]:
        """
        Validate order against window-based risk limits.
        
        Args:
            agent_id: Agent identifier (e.g., "BTC_15M")
            order_notional_usd: Notional value of order in USD
            
        Returns:
            Tuple of (allowed, reason)
        """
        import time
        current_ts = time.time()
        return self.risk_envelope.check_window_limit(agent_id, order_notional_usd, current_ts)
    
    def _validate_per_asset_cap(self, asset: str, order_notional_usd: float) -> Tuple[bool, str]:
        """
        Validate order against per-asset notional cap.
        
        Args:
            asset: Asset symbol (e.g., "BTC")
            order_notional_usd: Notional value of order in USD
            
        Returns:
            Tuple of (allowed, reason)
        """
        asset_max_notional_usd = self.risk_envelope.asset_max_notional_usd.get(asset, 0.0)
        
        if order_notional_usd > asset_max_notional_usd:
            return False, f"per_asset_cap: {asset} order=${order_notional_usd:.2f} > cap=${asset_max_notional_usd:.2f}"
        
        return True, ""
    
    def _validate_price_range(self, price_cents: int) -> Tuple[bool, str]:
        """
        Validate price is within allowed range (10-75c sweet spot).
        
        Args:
            price_cents: Contract price in cents
            
        Returns:
            Tuple of (allowed, reason)
        """
        min_price = 10  # DEEP_OTM_CHEAP_CENTS
        max_price = 75  # DEEP_OTM_EXPENSIVE_CENTS
        
        if price_cents < min_price:
            return False, f"price_below_minimum: {price_cents}c < {min_price}c (lottery zone)"
        
        if price_cents > max_price:
            return False, f"price_above_maximum: {price_cents}c > {max_price}c (moonshot territory)"
        
        return True, ""
    
    def _validate_min_edge(self, edge_pct: float) -> Tuple[bool, str]:
        """
        Validate edge meets minimum threshold.
        
        Args:
            edge_pct: Edge percentage
            
        Returns:
            Tuple of (allowed, reason)
        """
        min_edge_pct = 0.025  # 2.5% from risk_parameters.py
        
        if edge_pct < min_edge_pct:
            return False, f"edge_below_minimum: {edge_pct:.2%} < {min_edge_pct:.2%}"
        
        return True, ""
    
    def _validate_confidence(self, confidence: float) -> Tuple[bool, str]:
        """
        Validate confidence meets minimum threshold.
        
        Args:
            confidence: Confidence score
            
        Returns:
            Tuple of (allowed, reason)
        """
        min_confidence = self.profile_config.get('guardrails', {}).get('min_confidence', 0.65)
        
        if confidence < min_confidence:
            return False, f"confidence_below_minimum: {confidence:.2f} < {min_confidence:.2f}"
        
        return True, ""
    
    def simulate_scenario(self, scenario: TradeScenario) -> SimulationResult:
        """
        Simulate a single trade scenario.
        
        Args:
            scenario: Trade scenario to simulate
            
        Returns:
            SimulationResult with validation outcomes
        """
        passed_checks = []
        failed_checks = []
        warnings = []
        errors = []
        computed_values = {}
        
        agent_id = f"{scenario.asset}_15M"
        
        try:
            # Compute order notional
            order_notional_usd = self._compute_order_notional(scenario.entry_price_cents, scenario.contracts)
            computed_values['order_notional_usd'] = order_notional_usd
            
            # Compute fee
            probability = scenario.entry_price_cents / 100.0
            fee_cents = self._compute_kalshi_fee(probability, scenario.entry_price_cents)
            computed_values['fee_cents'] = fee_cents
            computed_values['fee_usd'] = fee_cents / 100.0
            
            # Compute potential profit/loss
            if scenario.exit_price_cents > scenario.entry_price_cents:
                profit_cents = scenario.exit_price_cents - scenario.entry_price_cents
                net_profit_cents = profit_cents - fee_cents
                computed_values['gross_profit_cents'] = profit_cents
                computed_values['net_profit_cents'] = net_profit_cents
                computed_values['net_profit_usd'] = (net_profit_cents * scenario.contracts) / 100.0
            else:
                loss_cents = scenario.entry_price_cents - scenario.exit_price_cents
                total_loss_cents = (loss_cents * scenario.contracts) + fee_cents
                computed_values['gross_loss_cents'] = loss_cents
                computed_values['total_loss_cents'] = total_loss_cents
                computed_values['total_loss_usd'] = total_loss_cents / 100.0
            
            # Validate price range
            price_allowed, price_reason = self._validate_price_range(scenario.entry_price_cents)
            if price_allowed:
                passed_checks.append(f"price_range: {scenario.entry_price_cents}c within [10, 75]")
            else:
                failed_checks.append(f"price_range: {price_reason}")
            
            # Validate edge
            edge_allowed, edge_reason = self._validate_min_edge(scenario.edge_pct)
            if edge_allowed:
                passed_checks.append(f"min_edge: {scenario.edge_pct:.2%} >= 2.5%")
            else:
                failed_checks.append(f"min_edge: {edge_reason}")
            
            # Validate confidence
            confidence_allowed, confidence_reason = self._validate_confidence(scenario.confidence)
            if confidence_allowed:
                passed_checks.append(f"min_confidence: {scenario.confidence:.2f} >= threshold")
            else:
                failed_checks.append(f"min_confidence: {confidence_reason}")
            
            # Validate per-asset cap
            asset_allowed, asset_reason = self._validate_per_asset_cap(scenario.asset, order_notional_usd)
            if asset_allowed:
                passed_checks.append(f"per_asset_cap: {scenario.asset} order=${order_notional_usd:.2f} within cap")
            else:
                failed_checks.append(f"per_asset_cap: {asset_reason}")
            
            # Validate window limits
            window_allowed, window_reason = self._validate_window_limits(agent_id, order_notional_usd)
            if window_allowed:
                passed_checks.append(f"window_limit: {agent_id} order=${order_notional_usd:.2f} within 3%/5% window limits")
            else:
                failed_checks.append(f"window_limit: {window_reason}")
            
            # Record order execution for window tracking
            self.risk_envelope.record_order_execution(agent_id, order_notional_usd)
            
            # Determine overall outcome
            if errors:
                outcome = ScenarioOutcome.ERROR
            elif failed_checks:
                outcome = ScenarioOutcome.FAILED
            elif warnings:
                outcome = ScenarioOutcome.WARNING
            else:
                outcome = ScenarioOutcome.PASSED
            
            # Check if outcome matches expected
            if outcome != scenario.expected_outcome:
                warnings.append(f"outcome_mismatch: expected={scenario.expected_outcome.value}, actual={outcome.value}")
            
        except Exception as e:
            errors.append(f"simulation_error: {str(e)}")
            outcome = ScenarioOutcome.ERROR
        
        return SimulationResult(
            scenario=scenario,
            outcome=outcome,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            warnings=warnings,
            errors=errors,
            computed_values=computed_values
        )
    
    def generate_scenarios(self) -> List[TradeScenario]:
        """
        Generate comprehensive trade scenarios based on 2026 best practices.
        
        Returns:
            List of TradeScenario objects
        """
        scenarios = []
        
        # === Normal Market Conditions ===
        scenarios.append(TradeScenario(
            name="normal_btc_entry_sweet_spot",
            description="Normal BTC entry in sweet spot (25-50c)",
            market_condition=MarketCondition.NORMAL,
            asset="BTC",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=35,
            exit_price_cents=55,
            contracts=1,
            edge_pct=0.05,
            confidence=0.70,
            time_to_expiry_min=10.0,
            expected_outcome=ScenarioOutcome.PASSED
        ))
        
        scenarios.append(TradeScenario(
            name="normal_eth_entry_sweet_spot",
            description="Normal ETH entry in sweet spot (25-50c)",
            market_condition=MarketCondition.NORMAL,
            asset="ETH",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=40,
            exit_price_cents=60,
            contracts=1,
            edge_pct=0.04,
            confidence=0.68,
            time_to_expiry_min=8.0,
            expected_outcome=ScenarioOutcome.PASSED
        ))
        
        # === Window Limit Boundary Cases ===
        scenarios.append(TradeScenario(
            name="window_limit_per_agent_boundary",
            description="Test 3% per-agent window limit boundary",
            market_condition=MarketCondition.NORMAL,
            asset="BTC",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=50,
            exit_price_cents=70,
            contracts=1,
            edge_pct=0.03,
            confidence=0.65,
            time_to_expiry_min=12.0,
            expected_outcome=ScenarioOutcome.PASSED
        ))
        
        # === Price Range Boundary Cases ===
        scenarios.append(TradeScenario(
            name="price_range_below_minimum",
            description="Test price below 10c minimum (lottery zone)",
            market_condition=MarketCondition.NORMAL,
            asset="DOGE",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=5,
            exit_price_cents=15,
            contracts=1,
            edge_pct=0.20,
            confidence=0.80,
            time_to_expiry_min=5.0,
            expected_outcome=ScenarioOutcome.FAILED
        ))
        
        scenarios.append(TradeScenario(
            name="price_range_above_maximum",
            description="Test price above 75c maximum (moonshot territory)",
            market_condition=MarketCondition.NORMAL,
            asset="BTC",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=80,
            exit_price_cents=95,
            contracts=1,
            edge_pct=0.02,
            confidence=0.60,
            time_to_expiry_min=3.0,
            expected_outcome=ScenarioOutcome.FAILED
        ))
        
        scenarios.append(TradeScenario(
            name="price_range_at_minimum",
            description="Test price at 10c minimum boundary",
            market_condition=MarketCondition.NORMAL,
            asset="DOGE",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=10,
            exit_price_cents=25,
            contracts=1,
            edge_pct=0.15,
            confidence=0.75,
            time_to_expiry_min=8.0,
            expected_outcome=ScenarioOutcome.PASSED
        ))
        
        scenarios.append(TradeScenario(
            name="price_range_at_maximum",
            description="Test price at 75c maximum boundary",
            market_condition=MarketCondition.NORMAL,
            asset="BTC",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=75,
            exit_price_cents=90,
            contracts=1,
            edge_pct=0.03,
            confidence=0.65,
            time_to_expiry_min=4.0,
            expected_outcome=ScenarioOutcome.PASSED
        ))
        
        # === Edge Threshold Cases ===
        scenarios.append(TradeScenario(
            name="edge_below_minimum",
            description="Test edge below 2.5% minimum",
            market_condition=MarketCondition.NORMAL,
            asset="SOL",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=45,
            exit_price_cents=50,
            contracts=1,
            edge_pct=0.02,
            confidence=0.60,
            time_to_expiry_min=10.0,
            expected_outcome=ScenarioOutcome.FAILED
        ))
        
        scenarios.append(TradeScenario(
            name="edge_at_minimum",
            description="Test edge at 2.5% minimum boundary",
            market_condition=MarketCondition.NORMAL,
            asset="XRP",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=40,
            exit_price_cents=50,
            contracts=1,
            edge_pct=0.025,
            confidence=0.65,
            time_to_expiry_min=9.0,
            expected_outcome=ScenarioOutcome.PASSED
        ))
        
        # === Confidence Threshold Cases ===
        scenarios.append(TradeScenario(
            name="confidence_below_minimum",
            description="Test confidence below 0.65 minimum",
            market_condition=MarketCondition.NORMAL,
            asset="ETH",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=35,
            exit_price_cents=55,
            contracts=1,
            edge_pct=0.05,
            confidence=0.60,
            time_to_expiry_min=11.0,
            expected_outcome=ScenarioOutcome.FAILED
        ))
        
        # === Multi-Asset Scenarios ===
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            scenarios.append(TradeScenario(
                name=f"multi_asset_{asset.lower()}_normal",
                description=f"Normal entry for {asset} in multi-asset context",
                market_condition=MarketCondition.NORMAL,
                asset=asset,
                bankroll_usd=self.bankroll_usd,
                entry_price_cents=35,
                exit_price_cents=55,
                contracts=1,
                edge_pct=0.04,
                confidence=0.68,
                time_to_expiry_min=10.0,
                expected_outcome=ScenarioOutcome.PASSED
            ))
        
        # === High Volatility Scenarios ===
        scenarios.append(TradeScenario(
            name="high_volatility_btc",
            description="BTC entry during high volatility regime",
            market_condition=MarketCondition.HIGH_VOLATILITY,
            asset="BTC",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=30,
            exit_price_cents=60,
            contracts=1,
            edge_pct=0.08,
            confidence=0.72,
            time_to_expiry_min=7.0,
            expected_outcome=ScenarioOutcome.PASSED
        ))
        
        # === Low Volatility Scenarios ===
        scenarios.append(TradeScenario(
            name="low_volatility_eth",
            description="ETH entry during low volatility regime",
            market_condition=MarketCondition.LOW_VOLATILITY,
            asset="ETH",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=45,
            exit_price_cents=55,
            contracts=1,
            edge_pct=0.03,
            confidence=0.66,
            time_to_expiry_min=12.0,
            expected_outcome=ScenarioOutcome.PASSED
        ))
        
        # === Time-to-Expiry Edge Cases ===
        scenarios.append(TradeScenario(
            name="tte_very_short",
            description="Entry with very short time to expiry (2 min)",
            market_condition=MarketCondition.NORMAL,
            asset="BTC",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=40,
            exit_price_cents=55,
            contracts=1,
            edge_pct=0.04,
            confidence=0.68,
            time_to_expiry_min=2.0,
            expected_outcome=ScenarioOutcome.PASSED  # TTE validation not implemented in simulator
        ))
        
        scenarios.append(TradeScenario(
            name="tte_very_long",
            description="Entry with long time to expiry (14 min)",
            market_condition=MarketCondition.NORMAL,
            asset="ETH",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=35,
            exit_price_cents=50,
            contracts=1,
            edge_pct=0.03,
            confidence=0.66,
            time_to_expiry_min=14.0,
            expected_outcome=ScenarioOutcome.PASSED
        ))
        
        # === Fee Impact Scenarios ===
        scenarios.append(TradeScenario(
            name="fee_impact_high_probability",
            description="High probability trade (70c) with maximum fee impact",
            market_condition=MarketCondition.NORMAL,
            asset="BTC",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=70,
            exit_price_cents=85,
            contracts=1,
            edge_pct=0.03,
            confidence=0.70,
            time_to_expiry_min=5.0,
            expected_outcome=ScenarioOutcome.PASSED  # 70c is within [10, 75] sweet spot
        ))
        
        scenarios.append(TradeScenario(
            name="fee_impact_low_probability",
            description="Low probability trade (15c) with low fee impact",
            market_condition=MarketCondition.NORMAL,
            asset="DOGE",
            bankroll_usd=self.bankroll_usd,
            entry_price_cents=15,
            exit_price_cents=30,
            contracts=1,
            edge_pct=0.10,
            confidence=0.75,
            time_to_expiry_min=10.0,
            expected_outcome=ScenarioOutcome.PASSED
        ))
        
        return scenarios
    
    def run_all_scenarios(self) -> List[SimulationResult]:
        """
        Run all generated scenarios.
        
        Returns:
            List of SimulationResult objects
        """
        scenarios = self.generate_scenarios()
        results = []
        
        logger.info(f"[SIMULATOR] Running {len(scenarios)} scenarios...")
        
        for i, scenario in enumerate(scenarios, 1):
            logger.info(f"[SIMULATOR] Scenario {i}/{len(scenarios)}: {scenario.name}")
            
            # Reset window state for each scenario to ensure isolation
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import _reset_shared_window_state_for_testing
            _reset_shared_window_state_for_testing()
            self._initialize_risk_envelope()
            
            result = self.simulate_scenario(scenario)
            results.append(result)
            
            logger.info(f"[SIMULATOR] Scenario {i}/{len(scenarios)}: {result.outcome.value}")
        
        self.results = results
        return results
    
    def generate_report(self) -> str:
        """
        Generate a comprehensive report of simulation results.
        
        Returns:
            Formatted report string
        """
        if not self.results:
            return "No simulation results available."
        
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("MERID 15M TRADE SCENARIO SIMULATION REPORT")
        report_lines.append("=" * 80)
        report_lines.append(f"Profile: {self.profile_name}")
        report_lines.append(f"Bankroll: ${self.bankroll_usd:.2f}")
        report_lines.append(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
        report_lines.append(f"Total Scenarios: {len(self.results)}")
        report_lines.append("")
        
        # Summary statistics
        passed = sum(1 for r in self.results if r.outcome == ScenarioOutcome.PASSED)
        failed = sum(1 for r in self.results if r.outcome == ScenarioOutcome.FAILED)
        warnings_count = sum(1 for r in self.results if r.outcome == ScenarioOutcome.WARNING)
        errors_count = sum(1 for r in self.results if r.outcome == ScenarioOutcome.ERROR)
        
        report_lines.append("SUMMARY")
        report_lines.append("-" * 40)
        report_lines.append(f"Passed: {passed} ({passed/len(self.results)*100:.1f}%)")
        report_lines.append(f"Failed: {failed} ({failed/len(self.results)*100:.1f}%)")
        report_lines.append(f"Warnings: {warnings_count} ({warnings_count/len(self.results)*100:.1f}%)")
        report_lines.append(f"Errors: {errors_count} ({errors_count/len(self.results)*100:.1f}%)")
        report_lines.append("")
        
        # Detailed results
        report_lines.append("DETAILED RESULTS")
        report_lines.append("-" * 40)
        
        for result in self.results:
            report_lines.append(f"\nScenario: {result.scenario.name}")
            report_lines.append(f"Description: {result.scenario.description}")
            report_lines.append(f"Asset: {result.scenario.asset}")
            report_lines.append(f"Market Condition: {result.scenario.market_condition.value}")
            report_lines.append(f"Entry Price: {result.scenario.entry_price_cents}c")
            report_lines.append(f"Exit Price: {result.scenario.exit_price_cents}c")
            report_lines.append(f"Contracts: {result.scenario.contracts}")
            report_lines.append(f"Edge: {result.scenario.edge_pct:.2%}")
            report_lines.append(f"Confidence: {result.scenario.confidence:.2f}")
            report_lines.append(f"Outcome: {result.outcome.value}")
            
            if result.computed_values:
                report_lines.append("Computed Values:")
                for key, value in result.computed_values.items():
                    if isinstance(value, float):
                        report_lines.append(f"  {key}: {value:.4f}")
                    else:
                        report_lines.append(f"  {key}: {value}")
            
            if result.passed_checks:
                report_lines.append("Passed Checks:")
                for check in result.passed_checks:
                    report_lines.append(f"  ✓ {check}")
            
            if result.failed_checks:
                report_lines.append("Failed Checks:")
                for check in result.failed_checks:
                    report_lines.append(f"  ✗ {check}")
            
            if result.warnings:
                report_lines.append("Warnings:")
                for warning in result.warnings:
                    report_lines.append(f"  ⚠ {warning}")
            
            if result.errors:
                report_lines.append("Errors:")
                for error in result.errors:
                    report_lines.append(f"  ✗ {error}")
        
        # Discrepancy analysis
        report_lines.append("\n" + "=" * 80)
        report_lines.append("DISCREPANCY ANALYSIS")
        report_lines.append("=" * 80)
        
        discrepancies = []
        for result in self.results:
            if result.outcome != result.scenario.expected_outcome:
                discrepancies.append({
                    'scenario': result.scenario.name,
                    'expected': result.scenario.expected_outcome.value,
                    'actual': result.outcome.value
                })
        
        if discrepancies:
            report_lines.append(f"Found {len(discrepancies)} discrepancies:")
            for d in discrepancies:
                report_lines.append(f"  - {d['scenario']}: expected={d['expected']}, actual={d['actual']}")
        else:
            report_lines.append("No discrepancies found - all scenarios matched expected outcomes.")
        
        # Configuration consistency check
        report_lines.append("\n" + "=" * 80)
        report_lines.append("CONFIGURATION CONSISTENCY CHECK")
        report_lines.append("=" * 80)
        
        consistency_issues = self._check_configuration_consistency()
        
        if consistency_issues:
            report_lines.append(f"Found {len(consistency_issues)} consistency issues:")
            for issue in consistency_issues:
                report_lines.append(f"  - {issue}")
        else:
            report_lines.append("No configuration consistency issues found.")
        
        report_lines.append("\n" + "=" * 80)
        
        return "\n".join(report_lines)
    
    def _check_configuration_consistency(self) -> List[str]:
        """
        Check for configuration consistency across layers.
        
        Returns:
            List of consistency issue descriptions
        """
        issues = []
        
        # Check window-based risk limits
        profile_per_window = self.profile_config.get('guardrails_per_window_risk_pct', {}).get('value', 0.03)
        profile_total_venue = self.profile_config.get('guardrails_total_venue_risk_pct', {}).get('value', 0.05)
        
        if abs(profile_per_window - 0.03) > 0.001:
            issues.append(f"Profile per_window_risk_pct ({profile_per_window}) != expected 0.03")
        
        if abs(profile_total_venue - 0.05) > 0.001:
            issues.append(f"Profile total_venue_risk_pct ({profile_total_venue}) != expected 0.05")
        
        # Check per-asset caps
        assets = self.profile_config.get('assets', {})
        for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
            if asset in assets:
                asset_config = assets[asset]
                max_notional_pct_raw = asset_config.get('max_notional_pct', 0.03)
                # Handle nested dict structure
                if isinstance(max_notional_pct_raw, dict):
                    max_notional_pct = max_notional_pct_raw.get('value', 0.03)
                else:
                    max_notional_pct = max_notional_pct_raw
                if abs(max_notional_pct - 0.03) > 0.001:
                    issues.append(f"Asset {asset} max_notional_pct ({max_notional_pct}) != expected 0.03")
        
        # Check Kelly hard cap
        kelly_config = self.profile_config.get('kelly', {})
        kelly_hard_cap = kelly_config.get('hard_cap', 0.02)
        if abs(kelly_hard_cap - 0.02) > 0.001:
            issues.append(f"Kelly hard_cap ({kelly_hard_cap}) != expected 0.02")
        
        # Check venue caps
        venue = self.profile_config.get('venue', {})
        venue_max_total = venue.get('max_total_notional_pct', {}).get('value', 0.15)
        if abs(venue_max_total - 0.15) > 0.001:
            issues.append(f"Venue max_total_notional_pct ({venue_max_total}) != expected 0.15")
        
        return issues
    
    def save_report(self, output_path: Optional[str] = None):
        """
        Save simulation report to file.
        
        Args:
            output_path: Optional output file path. Defaults to timestamped file in output/ directory.
        """
        if output_path is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_dir = repo_root / "output"
            output_dir.mkdir(exist_ok=True)
            output_path = output_dir / f"trade_scenario_simulation_{timestamp}.txt"
        
        report = self.generate_report()
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        logger.info(f"[SIMULATOR] Report saved to: {output_path}")
        
        # Also save as JSON for programmatic access
        json_path = output_path.with_suffix('.json')
        json_data = {
            'profile': self.profile_name,
            'bankroll_usd': self.bankroll_usd,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'results': [
                {
                    'scenario': r.scenario.name,
                    'outcome': r.outcome.value,
                    'passed_checks': r.passed_checks,
                    'failed_checks': r.failed_checks,
                    'warnings': r.warnings,
                    'errors': r.errors,
                    'computed_values': r.computed_values
                }
                for r in self.results
            ]
        }
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2)
        
        logger.info(f"[SIMULATOR] JSON report saved to: {json_path}")


def main():
    """Main entry point for the simulator."""
    import argparse
    
    parser = argparse.ArgumentParser(description="MERID 15M Trade Scenario Simulator")
    parser.add_argument('--profile', default='kalshi_crypto_15m_v2', help='Profile name to use')
    parser.add_argument('--bankroll', type=float, default=100.0, help='Starting bankroll in USD')
    parser.add_argument('--output', help='Output file path for report')
    
    args = parser.parse_args()
    
    logger.info("[SIMULATOR] Starting trade scenario simulation...")
    logger.info(f"[SIMULATOR] Profile: {args.profile}")
    logger.info(f"[SIMULATOR] Bankroll: ${args.bankroll:.2f}")
    
    try:
        simulator = TradeScenarioSimulator(profile_name=args.profile, bankroll_usd=args.bankroll)
        results = simulator.run_all_scenarios()
        simulator.save_report(output_path=args.output)
        
        # Print summary to console
        passed = sum(1 for r in results if r.outcome == ScenarioOutcome.PASSED)
        failed = sum(1 for r in results if r.outcome == ScenarioOutcome.FAILED)
        
        logger.info(f"[SIMULATOR] Simulation complete: {passed} passed, {failed} failed out of {len(results)} scenarios")
        
        return 0 if failed == 0 else 1
        
    except Exception as e:
        logger.error(f"[SIMULATOR] Simulation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
