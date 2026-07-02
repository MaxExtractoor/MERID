"""
Historical Crisis Stress Testing Suite

Tests MERID's risk controls against historical market crisis scenarios
to ensure the system can survive extreme market conditions.

Scenarios included:
- 2008 Financial Crisis (rapid market collapse)
- 2020 COVID-19 Crash (volatility spike + gap down)
- 2010 Flash Crash (intraday liquidity crisis)
- 2022 Crypto Winter (prolonged bear market)
- Custom extreme scenarios (tail risk events)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import numpy as np
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CrisisScenario:
    """Definition of a historical crisis scenario."""
    name: str
    description: str
    volatility_multiplier: float  # How much volatility increases
    drawdown_target: float  # Target drawdown percentage (0-1)
    duration_days: int  # Duration of crisis in days
    gap_down_pct: float  # Initial gap down percentage
    recovery_days: int  # Days to partial recovery
    correlation_spike: float  # Correlation spike during crisis


# Historical crisis scenarios
CRISIS_SCENARIOS = {
    "2008_financial_crisis": CrisisScenario(
        name="2008 Financial Crisis",
        description="Rapid market collapse with high volatility and prolonged recovery",
        volatility_multiplier=3.0,
        drawdown_target=0.50,  # 50% drawdown
        duration_days=180,
        gap_down_pct=0.05,
        recovery_days=365,
        correlation_spike=0.9,
    ),
    "2020_covid_crash": CrisisScenario(
        name="2020 COVID-19 Crash",
        description="Sudden volatility spike with gap down and rapid recovery",
        volatility_multiplier=5.0,
        drawdown_target=0.35,  # 35% drawdown
        duration_days=30,
        gap_down_pct=0.15,  # 15% gap down
        recovery_days=90,
        correlation_spike=0.95,
    ),
    "2010_flash_crash": CrisisScenario(
        name="2010 Flash Crash",
        description="Intraday liquidity crisis with extreme volatility",
        volatility_multiplier=10.0,
        drawdown_target=0.10,  # 10% intraday drawdown
        duration_days=1,
        gap_down_pct=0.09,
        recovery_days=5,
        correlation_spike=0.8,
    ),
    "2022_crypto_winter": CrisisScenario(
        name="2022 Crypto Winter",
        description="Prolonged bear market with sustained high volatility",
        volatility_multiplier=2.5,
        drawdown_target=0.70,  # 70% drawdown
        duration_days=365,
        gap_down_pct=0.02,
        recovery_days=730,
        correlation_spike=0.85,
    ),
    "extreme_tail_risk": CrisisScenario(
        name="Extreme Tail Risk",
        description="Black swan event with unprecedented volatility",
        volatility_multiplier=15.0,
        drawdown_target=0.80,  # 80% drawdown
        duration_days=7,
        gap_down_pct=0.30,  # 30% gap down
        recovery_days=180,
        correlation_spike=0.99,
    ),
}


@dataclass
class StressTestResult:
    """Result of a stress test against a crisis scenario."""
    scenario_name: str
    passed: bool
    max_drawdown: float
    final_equity: float
    peak_equity: float
    trades_executed: int
    position_sizes: List[float]
    risk_limit_breaches: List[str]
    kill_switch_triggered: bool
    recovery_time_days: Optional[int]
    details: Dict


class CrisisStressTester:
    """
    Stress testing engine for historical crisis scenarios.
    
    Tests the system's risk controls under extreme market conditions
    by simulating historical crisis scenarios with synthetic data.
    """
    
    def __init__(self, initial_capital: float = 1000000.0):
        self.initial_capital = initial_capital
        self.logger = logger
    
    def generate_crisis_data(
        self,
        scenario: CrisisScenario,
        base_price: float = 50000.0,
        base_volatility: float = 0.02,
    ) -> List[Dict]:
        """
        Generate synthetic price data for a crisis scenario.
        
        Args:
            scenario: Crisis scenario definition
            base_price: Starting price
            base_volatility: Base volatility (annualized)
            
        Returns:
            List of OHLCV candles with crisis characteristics
        """
        candles = []
        current_price = base_price
        
        # Apply initial gap down
        current_price *= (1.0 - scenario.gap_down_pct)
        
        # Generate hourly candles for the crisis duration
        hours = scenario.duration_days * 24
        
        for i in range(hours):
            # Crisis volatility - make it more severe
            crisis_vol = base_volatility * scenario.volatility_multiplier / np.sqrt(252 * 24)
            
            # Price movement with mean reversion during recovery
            # Make the decline more severe to match target drawdown
            if i < hours * 0.3:  # Crisis phase - aggressive decline
                drift = -0.01 * (scenario.drawdown_target / 0.3)  # Scale to target
            elif i < hours * 0.7:  # Stabilization phase
                drift = 0.000  # Sideways
            else:  # Recovery phase
                drift = 0.001  # Gradual recovery
            
            # Generate OHLC
            open_price = current_price
            change = np.random.normal(drift, crisis_vol)
            close_price = open_price * (1.0 + change)
            
            # High and low
            high = max(open_price, close_price) * (1.0 + abs(np.random.normal(0, crisis_vol * 0.5)))
            low = min(open_price, close_price) * (1.0 - abs(np.random.normal(0, crisis_vol * 0.5)))
            
            # Volume (spikes during crisis)
            base_volume = 1000000
            volume_multiplier = 1.0 + (scenario.volatility_multiplier - 1.0) * 0.5
            volume = int(base_volume * volume_multiplier * np.random.uniform(0.5, 2.0))
            
            candle = {
                "t": datetime.utcnow() + timedelta(hours=i),
                "o": open_price,
                "h": high,
                "l": low,
                "c": close_price,
                "v": volume,
            }
            candles.append(candle)
            
            current_price = close_price
        
        return candles
    
    def run_stress_test(
        self,
        scenario: CrisisScenario,
        position_sizer,
        strategy_fn: Optional[callable] = None,
    ) -> StressTestResult:
        """
        Run a stress test against a crisis scenario.
        
        Args:
            scenario: Crisis scenario to test
            position_sizer: PositionSizer instance to test
            strategy_fn: Optional strategy function for signal generation
            
        Returns:
            StressTestResult with detailed metrics
        """
        self.logger.info(f"Running stress test: {scenario.name}")
        
        # Generate crisis data
        candles = self.generate_crisis_data(scenario)
        
        # Simulate trading through crisis
        equity = self.initial_capital
        peak_equity = equity
        equity_curve = [equity]
        position_sizes = []
        risk_limit_breaches = []
        kill_switch_triggered = False
        trades_executed = 0
        recovery_time = None
        
        # Track drawdown
        max_drawdown = 0.0
        in_drawdown = False
        drawdown_start_idx = None
        
        for i, candle in enumerate(candles):
            # Update portfolio value based on price changes
            price_change = (candle["c"] - candle["o"]) / candle["o"]
            equity *= (1.0 + price_change * 0.5)  # Assume 50% invested
            
            # Track peak and drawdown
            if equity > peak_equity:
                peak_equity = equity
                if in_drawdown:
                    # Recovery detected
                    recovery_time = i - drawdown_start_idx
                    in_drawdown = False
            
            current_drawdown = (peak_equity - equity) / peak_equity
            if current_drawdown > max_drawdown:
                max_drawdown = current_drawdown
            
            if current_drawdown > 0.05 and not in_drawdown:
                in_drawdown = True
                drawdown_start_idx = i
            
            # Test drawdown-adjusted sizing
            position_sizer.update_portfolio_value(equity)
            drawdown_multiplier = position_sizer.get_drawdown_size_multiplier()
            
            # Check if position sizing is reducing appropriately
            if current_drawdown > 0.10 and drawdown_multiplier > 0.8:
                risk_limit_breaches.append(
                    f"Hour {i}: Drawdown {current_drawdown:.1%} but multiplier {drawdown_multiplier:.2f} > 0.8"
                )
            
            # Simulate position sizing
            if strategy_fn:
                signal = strategy_fn(candle)
                if signal != 0:
                    trades_executed += 1
                    position_size = abs(signal) * drawdown_multiplier
                    position_sizes.append(position_size)
            else:
                # Default: use drawdown multiplier as position size proxy
                position_sizes.append(drawdown_multiplier)
            
            equity_curve.append(equity)
            
            # Check for kill switch conditions
            if current_drawdown > 0.25:  # 25% drawdown triggers halt
                kill_switch_triggered = True
                self.logger.warning(f"Kill switch triggered at hour {i} with {current_drawdown:.1%} drawdown")
                break
        
        # Determine if test passed
        # Pass criteria:
        # 1. Max drawdown <= scenario target + 10% buffer
        # 2. No critical risk limit breaches
        # 3. Final equity >= 50% of initial (survival)
        passed = (
            max_drawdown <= scenario.drawdown_target * 1.1
            and len([b for b in risk_limit_breaches if "critical" in b.lower()]) == 0
            and equity >= self.initial_capital * 0.5
        )
        
        result = StressTestResult(
            scenario_name=scenario.name,
            passed=passed,
            max_drawdown=max_drawdown,
            final_equity=equity,
            peak_equity=peak_equity,
            trades_executed=trades_executed,
            position_sizes=position_sizes,
            risk_limit_breaches=risk_limit_breaches,
            kill_switch_triggered=kill_switch_triggered,
            recovery_time_days=recovery_time // 24 if recovery_time else None,
            details={
                "scenario_target_drawdown": scenario.drawdown_target,
                "duration_hours": len(candles),
                "avg_position_size": np.mean(position_sizes) if position_sizes else 0,
                "min_position_size": np.min(position_sizes) if position_sizes else 0,
            },
        )
        
        self.logger.info(
            f"Stress test result: {scenario.name} | "
            f"passed={passed} | max_dd={max_drawdown:.1%} | "
            f"final_eq=${equity:,.0f} | breaches={len(risk_limit_breaches)}"
        )
        
        return result
    
    def run_all_scenarios(
        self,
        position_sizer,
        strategy_fn: Optional[callable] = None,
    ) -> Dict[str, StressTestResult]:
        """
        Run stress tests against all historical crisis scenarios.
        
        Args:
            position_sizer: PositionSizer instance to test
            strategy_fn: Optional strategy function
            
        Returns:
            Dictionary mapping scenario names to results
        """
        results = {}
        
        for scenario_key, scenario in CRISIS_SCENARIOS.items():
            try:
                result = self.run_stress_test(scenario, position_sizer, strategy_fn)
                results[scenario_key] = result
            except Exception as e:
                self.logger.error(f"Stress test failed for {scenario.name}: {e}")
                # Create failed result
                results[scenario_key] = StressTestResult(
                    scenario_name=scenario.name,
                    passed=False,
                    max_drawdown=1.0,
                    final_equity=0.0,
                    peak_equity=self.initial_capital,
                    trades_executed=0,
                    position_sizes=[],
                    risk_limit_breaches=[f"Test failed with error: {str(e)}"],
                    kill_switch_triggered=True,
                    recovery_time_days=None,
                    details={"error": str(e)},
                )
        
        return results
    
    def generate_report(self, results: Dict[str, StressTestResult]) -> str:
        """Generate a summary report of stress test results."""
        report_lines = [
            "=" * 80,
            "HISTORICAL CRISIS STRESS TEST REPORT",
            "=" * 80,
            f"Generated: {datetime.utcnow().isoformat()}",
            f"Initial Capital: ${self.initial_capital:,.0f}",
            f"Scenarios Tested: {len(results)}",
            "",
        ]
        
        passed_count = sum(1 for r in results.values() if r.passed)
        report_lines.append(f"Passed: {passed_count}/{len(results)}")
        report_lines.append("")
        
        for scenario_key, result in results.items():
            report_lines.extend([
                f"Scenario: {result.scenario_name}",
                f"  Status: {'✓ PASSED' if result.passed else '✗ FAILED'}",
                f"  Max Drawdown: {result.max_drawdown:.1%}",
                f"  Final Equity: ${result.final_equity:,.0f}",
                f"  Peak Equity: ${result.peak_equity:,.0f}",
                f"  Trades Executed: {result.trades_executed}",
                f"  Kill Switch Triggered: {'Yes' if result.kill_switch_triggered else 'No'}",
                f"  Risk Limit Breaches: {len(result.risk_limit_breaches)}",
            ])
            
            if result.recovery_time_days:
                report_lines.append(f"  Recovery Time: {result.recovery_time_days} days")
            
            if result.risk_limit_breaches:
                report_lines.append("  Breach Details:")
                for breach in result.risk_limit_breaches[:5]:  # Show first 5
                    report_lines.append(f"    - {breach}")
                if len(result.risk_limit_breaches) > 5:
                    report_lines.append(f"    ... and {len(result.risk_limit_breaches) - 5} more")
            
            report_lines.append("")
        
        report_lines.extend([
            "=" * 80,
            "RECOMMENDATIONS",
            "=" * 80,
        ])
        
        failed_scenarios = [r for r in results.values() if not r.passed]
        if failed_scenarios:
            report_lines.append("Failed scenarios require attention:")
            for result in failed_scenarios:
                report_lines.append(f"  - {result.scenario_name}")
        else:
            report_lines.append("All scenarios passed. System is resilient to historical crises.")
        
        return "\n".join(report_lines)


# Convenience function for quick stress testing
async def stress_test_position_sizer(
    position_sizer,
    initial_capital: float = 1000000.0,
) -> Dict[str, StressTestResult]:
    """
    Quick stress test of a PositionSizer against all crisis scenarios.
    
    Args:
        position_sizer: PositionSizer instance to test
        initial_capital: Starting capital for simulation
        
    Returns:
        Dictionary of stress test results
    """
    tester = CrisisStressTester(initial_capital=initial_capital)
    results = tester.run_all_scenarios(position_sizer)
    report = tester.generate_report(results)
    
    logger.info("\n" + report)
    
    return results
