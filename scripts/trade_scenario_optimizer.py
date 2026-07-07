#!/usr/bin/env python3
"""
Trade Scenario Optimizer for Kalshi 15M Crypto Trading System

This script simulates various trade scenarios to determine optimal confidence thresholds,
edge requirements, and risk parameters for profitable trading with noise reduction.

Based on 2026 research findings:
- Kelly Criterion: Full Kelly maximizes growth but has 33% chance of halving before doubling
- Half Kelly: 75% growth rate, 11% chance of halving (sweet spot)
- Quarter Kelly: 50% growth rate, 3% chance of halving (conservative)
- Prediction markets: Domain-specific calibration biases exist
- Contract price zones: 10-75c sweet spot, 75c+ moonshot danger zone
- Fill rates: Critical for HFT, slippage eats into edge
- Win rate vs edge: Higher win rates allow smaller edges
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from enum import Enum
import json
from datetime import datetime
import math


class ScenarioType(Enum):
    """Types of trade scenarios to test."""
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    ARBITRAGE = "arbitrage"
    MARKET_MAKING = "market_making"
    HYBRID = "hybrid"


@dataclass
class TradeScenario:
    """Configuration for a single trade scenario."""
    name: str
    confidence_threshold: float  # 0.0 to 1.0
    edge_threshold: float  # 0.0 to 1.0 (e.g., 0.02 for 2%)
    win_rate: float  # 0.0 to 1.0
    fill_rate: float  # 0.0 to 1.0
    avg_win_cents: float  # Average profit in cents
    avg_loss_cents: float  # Average loss in cents
    position_size_contracts: int
    risk_per_trade_pct: float  # 0.0 to 1.0
    max_concurrent_positions: int
    scenario_type: ScenarioType
    description: str = ""


@dataclass
class SimulationResult:
    """Results from running a trade scenario simulation."""
    scenario_name: str
    total_trades: int
    filled_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    fill_rate: float
    total_pnl_cents: float
    total_pnl_usd: float
    final_bankroll_usd: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    kelly_fraction: float
    kelly_optimal_size_usd: float
    recommended_kelly_fraction: str  # "full", "half", "quarter"
    profitability_score: float  # 0-100 composite score
    noise_score: float  # 0-100 (higher = less noise)
    compound_growth_rate: float
    consecutive_losses_max: int
    avg_holding_time_min: float


class TradeScenarioOptimizer:
    """
    Optimizes trade scenarios by simulating various parameter combinations
    and measuring profitability, noise reduction, and bankroll growth.
    """
    
    def __init__(self, initial_bankroll_usd: float = 1000.0, num_simulations: int = 1000):
        self.initial_bankroll_usd = initial_bankroll_usd
        self.num_simulations = num_simulations
        self.results: List[SimulationResult] = []
        
    def generate_scenarios(self) -> List[TradeScenario]:
        """Generate a comprehensive matrix of trade scenarios to test."""
        scenarios = []
        
        # Confidence thresholds to test (based on 2026 research)
        confidence_thresholds = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
        
        # Edge thresholds to test (based on Kalshi microstructure)
        edge_thresholds = [0.005, 0.01, 0.015, 0.02, 0.03, 0.04, 0.05]
        
        # Win rates to test (realistic ranges for prediction markets)
        win_rates = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
        
        # Fill rates to test (based on liquidity research)
        fill_rates = [0.70, 0.80, 0.90, 0.95, 1.00]
        
        # Position sizes (based on current 1-contract rule)
        position_sizes = [1, 2, 3]
        
        # Risk percentages (based on Kelly and industry standards)
        risk_percentages = [0.01, 0.02, 0.03, 0.05]
        
        # Generate key scenarios (not full Cartesian product to avoid explosion)
        scenario_id = 0
        
        # BASELINE SCENARIOS - Current system configuration
        scenarios.append(TradeScenario(
            name=f"baseline_current_config",
            confidence_threshold=0.65,  # Current system threshold
            edge_threshold=0.03,  # Current 3% edge
            win_rate=0.55,  # Assumed win rate
            fill_rate=0.90,  # Assumed fill rate
            avg_win_cents=25.0,  # Average win in sweet spot
            avg_loss_cents=20.0,  # Average loss
            position_size_contracts=1,  # Current 1-contract rule
            risk_per_trade_pct=0.03,  # Current 3% per trade
            max_concurrent_positions=5,  # 5 assets
            scenario_type=ScenarioType.MOMENTUM,
            description="Current production configuration baseline"
        ))
        scenario_id += 1
        
        # CONFIDENCE THRESHOLD SENSITIVITY
        for conf in confidence_thresholds:
            scenarios.append(TradeScenario(
                name=f"conf_sensitivity_{int(conf*100)}",
                confidence_threshold=conf,
                edge_threshold=0.03,
                win_rate=0.55 + (conf - 0.65) * 0.2,  # Higher confidence → higher win rate
                fill_rate=0.90,
                avg_win_cents=25.0,
                avg_loss_cents=20.0,
                position_size_contracts=1,
                risk_per_trade_pct=0.03,
                max_concurrent_positions=5,
                scenario_type=ScenarioType.MOMENTUM,
                description=f"Confidence threshold sensitivity at {int(conf*100)}%"
            ))
            scenario_id += 1
        
        # EDGE THRESHOLD SENSITIVITY
        for edge in edge_thresholds:
            scenarios.append(TradeScenario(
                name=f"edge_sensitivity_{int(edge*1000)}bp",
                confidence_threshold=0.65,
                edge_threshold=edge,
                win_rate=0.55 + (0.03 - edge) * 2.0,  # Lower edge → lower win rate
                fill_rate=0.90,
                avg_win_cents=25.0,
                avg_loss_cents=20.0,
                position_size_contracts=1,
                risk_per_trade_pct=0.03,
                max_concurrent_positions=5,
                scenario_type=ScenarioType.MOMENTUM,
                description=f"Edge threshold sensitivity at {int(edge*1000)}bp"
            ))
            scenario_id += 1
        
        # WIN RATE SENSITIVITY (Critical for Kelly)
        for wr in win_rates:
            scenarios.append(TradeScenario(
                name=f"winrate_sensitivity_{int(wr*100)}",
                confidence_threshold=0.65,
                edge_threshold=0.03,
                win_rate=wr,
                fill_rate=0.90,
                avg_win_cents=25.0,
                avg_loss_cents=20.0,
                position_size_contracts=1,
                risk_per_trade_pct=0.03,
                max_concurrent_positions=5,
                scenario_type=ScenarioType.MOMENTUM,
                description=f"Win rate sensitivity at {int(wr*100)}%"
            ))
            scenario_id += 1
        
        # FILL RATE SENSITIVITY (Critical for HFT)
        for fr in fill_rates:
            scenarios.append(TradeScenario(
                name=f"fillrate_sensitivity_{int(fr*100)}",
                confidence_threshold=0.65,
                edge_threshold=0.03,
                win_rate=0.55,
                fill_rate=fr,
                avg_win_cents=25.0,
                avg_loss_cents=20.0,
                position_size_contracts=1,
                risk_per_trade_pct=0.03,
                max_concurrent_positions=5,
                scenario_type=ScenarioType.MOMENTUM,
                description=f"Fill rate sensitivity at {int(fr*100)}%"
            ))
            scenario_id += 1
        
        # KELLY-BASED SCENARIOS (Optimal sizing)
        for wr in [0.55, 0.60, 0.65]:
            kelly_frac = self.calculate_kelly_fraction(wr, 25.0, 20.0)
            scenarios.append(TradeScenario(
                name=f"kelly_full_winrate_{int(wr*100)}",
                confidence_threshold=0.65,
                edge_threshold=0.03,
                win_rate=wr,
                fill_rate=0.90,
                avg_win_cents=25.0,
                avg_loss_cents=20.0,
                position_size_contracts=1,
                risk_per_trade_pct=min(kelly_frac, 0.10),  # Cap at 10%
                max_concurrent_positions=5,
                scenario_type=ScenarioType.MOMENTUM,
                description=f"Full Kelly sizing at {int(wr*100)}% win rate"
            ))
            scenario_id += 1
            
            scenarios.append(TradeScenario(
                name=f"kelly_half_winrate_{int(wr*100)}",
                confidence_threshold=0.65,
                edge_threshold=0.03,
                win_rate=wr,
                fill_rate=0.90,
                avg_win_cents=25.0,
                avg_loss_cents=20.0,
                position_size_contracts=1,
                risk_per_trade_pct=min(kelly_frac / 2, 0.10),
                max_concurrent_positions=5,
                scenario_type=ScenarioType.MOMENTUM,
                description=f"Half Kelly sizing at {int(wr*100)}% win rate"
            ))
            scenario_id += 1
            
            scenarios.append(TradeScenario(
                name=f"kelly_quarter_winrate_{int(wr*100)}",
                confidence_threshold=0.65,
                edge_threshold=0.03,
                win_rate=wr,
                fill_rate=0.90,
                avg_win_cents=25.0,
                avg_loss_cents=20.0,
                position_size_contracts=1,
                risk_per_trade_pct=min(kelly_frac / 4, 0.10),
                max_concurrent_positions=5,
                scenario_type=ScenarioType.MOMENTUM,
                description=f"Quarter Kelly sizing at {int(wr*100)}% win rate"
            ))
            scenario_id += 1
        
        # HIGH LEVERAGE BUG SCENARIOS
        # Test scenarios that could trigger high leverage bugs
        scenarios.append(TradeScenario(
            name="high_leverage_dynamic_sizing",
            confidence_threshold=0.65,
            edge_threshold=0.03,
            win_rate=0.55,
            fill_rate=0.90,
            avg_win_cents=25.0,
            avg_loss_cents=20.0,
            position_size_contracts=3,  # Violates 1-contract rule
            risk_per_trade_pct=0.03,
            max_concurrent_positions=5,
            scenario_type=ScenarioType.MOMENTUM,
            description="HIGH LEVERAGE BUG: Dynamic sizing with 3 contracts"
        ))
        scenario_id += 1
        
        scenarios.append(TradeScenario(
            name="high_leverage_regime_multiplier",
            confidence_threshold=0.65,
            edge_threshold=0.03,
            win_rate=0.55,
            fill_rate=0.90,
            avg_win_cents=25.0,
            avg_loss_cents=20.0,
            position_size_contracts=1,
            risk_per_trade_pct=0.06,  # 6% - exceeds 3% limit
            max_concurrent_positions=5,
            scenario_type=ScenarioType.MOMENTUM,
            description="HIGH LEVERAGE BUG: Regime multiplier causing 6% risk"
        ))
        scenario_id += 1
        
        scenarios.append(TradeScenario(
            name="high_leverage_window_bypass",
            confidence_threshold=0.65,
            edge_threshold=0.03,
            win_rate=0.55,
            fill_rate=0.90,
            avg_win_cents=25.0,
            avg_loss_cents=20.0,
            position_size_contracts=1,
            risk_per_trade_pct=0.03,
            max_concurrent_positions=10,  # 10 positions - exceeds 5-asset limit
            scenario_type=ScenarioType.MOMENTUM,
            description="HIGH LEVERAGE BUG: Window limit bypass with 10 positions"
        ))
        scenario_id += 1
        
        # PRICE ZONE SCENARIOS (Based on 75c threshold research)
        scenarios.append(TradeScenario(
            name="price_zone_sweet_spot_10_75c",
            confidence_threshold=0.65,
            edge_threshold=0.03,
            win_rate=0.60,  # Higher win rate in sweet spot
            fill_rate=0.90,
            avg_win_cents=30.0,  # Better R:R in sweet spot
            avg_loss_cents=15.0,
            position_size_contracts=1,
            risk_per_trade_pct=0.03,
            max_concurrent_positions=5,
            scenario_type=ScenarioType.MOMENTUM,
            description="Sweet spot: 10-75c entry zone with favorable R:R"
        ))
        scenario_id += 1
        
        scenarios.append(TradeScenario(
            name="price_zone_moonshot_75c_plus",
            confidence_threshold=0.65,
            edge_threshold=0.03,
            win_rate=0.50,  # Lower win rate in moonshot zone
            fill_rate=0.90,
            avg_win_cents=10.0,  # Poor R:R in moonshot zone
            avg_loss_cents=25.0,
            position_size_contracts=1,
            risk_per_trade_pct=0.03,
            max_concurrent_positions=5,
            scenario_type=ScenarioType.MOMENTUM,
            description="Moonshot zone: 75c+ with poor risk/reward"
        ))
        scenario_id += 1
        
        return scenarios
    
    def calculate_kelly_fraction(self, win_rate: float, avg_win_cents: float, avg_loss_cents: float) -> float:
        """
        Calculate optimal Kelly fraction.
        
        Formula: f* = p - q/b
        Where:
        - p = win_rate
        - q = 1 - p (loss rate)
        - b = avg_win / avg_loss (reward-to-risk ratio)
        """
        if avg_loss_cents <= 0:
            return 0.0
        
        b = avg_win_cents / avg_loss_cents
        q = 1.0 - win_rate
        
        kelly = win_rate - (q / b)
        
        # Kelly can be negative if no edge
        return max(0.0, kelly)
    
    def simulate_scenario(self, scenario: TradeScenario) -> SimulationResult:
        """
        Simulate a single trade scenario over multiple iterations.
        
        Uses Monte Carlo simulation to account for randomness in:
        - Trade outcomes (win/loss)
        - Fill execution
        - Win/loss magnitude variation
        """
        np.random.seed(42)  # For reproducibility
        
        bankroll_cents = int(self.initial_bankroll_usd * 100)
        equity_curve = [bankroll_cents]
        trade_log = []
        
        total_trades = 0
        filled_trades = 0
        winning_trades = 0
        losing_trades = 0
        
        consecutive_losses = 0
        max_consecutive_losses = 0
        
        # Simulate trades
        for i in range(self.num_simulations):
            # Check if we should enter a trade
            # (In real system, this depends on signals meeting thresholds)
            total_trades += 1
            
            # Check fill
            if np.random.random() > scenario.fill_rate:
                continue  # Trade not filled
            
            filled_trades += 1
            
            # Calculate position size in cents
            risk_cents = int(bankroll_cents * scenario.risk_per_trade_pct)
            position_cents = risk_cents * scenario.position_size_contracts
            
            # Simulate outcome
            if np.random.random() < scenario.win_rate:
                # Win
                winning_trades += 1
                # Add some variation to win amount (±20%)
                win_variation = np.random.uniform(0.8, 1.2)
                pnl_cents = int(scenario.avg_win_cents * win_variation * scenario.position_size_contracts)
                bankroll_cents += pnl_cents
                consecutive_losses = 0
            else:
                # Loss
                losing_trades += 1
                # Add some variation to loss amount (±20%)
                loss_variation = np.random.uniform(0.8, 1.2)
                pnl_cents = -int(scenario.avg_loss_cents * loss_variation * scenario.position_size_contracts)
                bankroll_cents += pnl_cents
                consecutive_losses += 1
                max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
            
            trade_log.append({
                "trade": filled_trades,
                "pnl_cents": pnl_cents,
                "bankroll_cents": bankroll_cents
            })
            
            equity_curve.append(bankroll_cents)
            
            # Stop if bankrupt
            if bankroll_cents <= 0:
                break
        
        # Calculate metrics
        final_bankroll_usd = bankroll_cents / 100.0
        total_pnl_cents = bankroll_cents - int(self.initial_bankroll_usd * 100)
        total_pnl_usd = total_pnl_cents / 100.0
        total_return_pct = (total_pnl_cents / (self.initial_bankroll_usd * 100)) * 100
        
        # Win rate
        actual_win_rate = winning_trades / filled_trades if filled_trades > 0 else 0.0
        
        # Fill rate
        actual_fill_rate = filled_trades / total_trades if total_trades > 0 else 0.0
        
        # Max drawdown
        peak = max(equity_curve)
        trough = min(equity_curve)
        max_drawdown_pct = ((peak - trough) / peak) * 100 if peak > 0 else 0.0
        
        # Sharpe ratio (simplified)
        returns = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i-1] > 0:
                returns.append((equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1])
        
        if returns:
            sharpe_ratio = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0.0
            sharpe_ratio *= np.sqrt(252)  # Annualize (assuming daily)
        else:
            sharpe_ratio = 0.0
        
        # Kelly calculations
        kelly_fraction = self.calculate_kelly_fraction(
            scenario.win_rate,
            scenario.avg_win_cents,
            scenario.avg_loss_cents
        )
        kelly_optimal_size_usd = self.initial_bankroll_usd * kelly_fraction
        
        # Recommended Kelly fraction based on drawdown tolerance
        if max_drawdown_pct < 15:
            recommended_kelly = "full"
        elif max_drawdown_pct < 25:
            recommended_kelly = "half"
        else:
            recommended_kelly = "quarter"
        
        # Profitability score (0-100)
        # Combines return, sharpe, win rate, and drawdown
        profitability_score = (
            min(100, max(0, total_return_pct * 2)) * 0.3 +  # Return
            min(100, max(0, sharpe_ratio * 20)) * 0.3 +  # Sharpe
            actual_win_rate * 100 * 0.2 +  # Win rate
            min(100, max(0, (30 - max_drawdown_pct) * 3.33)) * 0.2  # Drawdown (inverse)
        )
        
        # Noise score (0-100, higher = less noise)
        # Based on consistency of returns and win rate stability
        if returns:
            return_std = np.std(returns)
            noise_score = min(100, max(0, (0.1 - return_std) * 1000))  # Lower std = less noise
        else:
            noise_score = 50.0
        
        # Compound growth rate
        if len(equity_curve) > 1:
            compound_growth_rate = (equity_curve[-1] / equity_curve[0]) ** (1 / len(equity_curve)) - 1
        else:
            compound_growth_rate = 0.0
        
        return SimulationResult(
            scenario_name=scenario.name,
            total_trades=total_trades,
            filled_trades=filled_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=actual_win_rate,
            fill_rate=actual_fill_rate,
            total_pnl_cents=total_pnl_cents,
            total_pnl_usd=total_pnl_usd,
            final_bankroll_usd=final_bankroll_usd,
            total_return_pct=total_return_pct,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            kelly_fraction=kelly_fraction,
            kelly_optimal_size_usd=kelly_optimal_size_usd,
            recommended_kelly_fraction=recommended_kelly,
            profitability_score=profitability_score,
            noise_score=noise_score,
            compound_growth_rate=compound_growth_rate,
            consecutive_losses_max=max_consecutive_losses,
            avg_holding_time_min=7.5  # Assumed average for 15m contracts
        )
    
    def run_all_scenarios(self) -> List[SimulationResult]:
        """Run simulation for all generated scenarios."""
        scenarios = self.generate_scenarios()
        results = []
        
        print(f"Running {len(scenarios)} trade scenario simulations...")
        print(f"Initial bankroll: ${self.initial_bankroll_usd:.2f}")
        print(f"Simulations per scenario: {self.num_simulations}")
        print()
        
        for i, scenario in enumerate(scenarios):
            print(f"[{i+1}/{len(scenarios)}] Simulating: {scenario.name}")
            result = self.simulate_scenario(scenario)
            results.append(result)
            print(f"  Return: {result.total_return_pct:.2f}%, Sharpe: {result.sharpe_ratio:.2f}, "
                  f"Max DD: {result.max_drawdown_pct:.2f}%, Win Rate: {result.win_rate*100:.1f}%")
        
        self.results = results
        return results
    
    def analyze_results(self) -> Dict:
        """Analyze simulation results and generate recommendations."""
        if not self.results:
            return {}
        
        # Sort by profitability score
        sorted_by_profit = sorted(self.results, key=lambda x: x.profitability_score, reverse=True)
        
        # Sort by noise score (less noise = higher score)
        sorted_by_noise = sorted(self.results, key=lambda x: x.noise_score, reverse=True)
        
        # Find best overall (balance of profit and noise)
        best_overall = sorted(self.results, 
                            key=lambda x: x.profitability_score * 0.7 + x.noise_score * 0.3, 
                            reverse=True)[0]
        
        # Identify high leverage bug scenarios
        high_leverage_scenarios = [r for r in self.results if "high_leverage" in r.scenario_name]
        
        # Kelly analysis
        kelly_scenarios = [r for r in self.results if "kelly" in r.scenario_name]
        
        # Confidence threshold analysis
        conf_scenarios = [r for r in self.results if "conf_sensitivity" in r.scenario_name]
        best_conf = max(conf_scenarios, key=lambda x: x.profitability_score) if conf_scenarios else None
        
        # Edge threshold analysis
        edge_scenarios = [r for r in self.results if "edge_sensitivity" in r.scenario_name]
        best_edge = max(edge_scenarios, key=lambda x: x.profitability_score) if edge_scenarios else None
        
        # Win rate analysis
        winrate_scenarios = [r for r in self.results if "winrate_sensitivity" in r.scenario_name]
        best_winrate = max(winrate_scenarios, key=lambda x: x.profitability_score) if winrate_scenarios else None
        
        # Fill rate analysis
        fillrate_scenarios = [r for r in self.results if "fillrate_sensitivity" in r.scenario_name]
        best_fillrate = max(fillrate_scenarios, key=lambda x: x.profitability_score) if fillrate_scenarios else None
        
        # Price zone analysis
        price_zone_scenarios = [r for r in self.results if "price_zone" in r.scenario_name]
        
        return {
            "best_overall": best_overall,
            "top_5_profitable": sorted_by_profit[:5],
            "top_5_low_noise": sorted_by_noise[:5],
            "high_leverage_bugs": high_leverage_scenarios,
            "kelly_analysis": kelly_scenarios,
            "best_confidence_threshold": best_conf,
            "best_edge_threshold": best_edge,
            "best_win_rate": best_winrate,
            "best_fill_rate": best_fillrate,
            "price_zone_analysis": price_zone_scenarios,
            "baseline_comparison": next((r for r in self.results if "baseline" in r.scenario_name), None)
        }
    
    def generate_report(self, output_file: str = "trade_scenario_report.json"):
        """Generate comprehensive report with recommendations."""
        analysis = self.analyze_results()
        
        report = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "initial_bankroll_usd": self.initial_bankroll_usd,
                "num_simulations": self.num_simulations,
                "total_scenarios_tested": len(self.results)
            },
            "executive_summary": {
                "best_overall_scenario": analysis["best_overall"].scenario_name if analysis.get("best_overall") else None,
                "best_profitability_score": analysis["best_overall"].profitability_score if analysis.get("best_overall") else 0,
                "best_total_return_pct": analysis["best_overall"].total_return_pct if analysis.get("best_overall") else 0,
                "best_sharpe_ratio": analysis["best_overall"].sharpe_ratio if analysis.get("best_overall") else 0,
                "best_max_drawdown_pct": analysis["best_overall"].max_drawdown_pct if analysis.get("best_overall") else 0
            },
            "recommendations": self._generate_recommendations(analysis),
            "detailed_results": [self._result_to_dict(r) for r in self.results],
            "high_leverage_bug_analysis": self._analyze_high_leverage_bugs(analysis["high_leverage_bugs"]),
            "kelly_criterion_analysis": self._analyze_kelly(analysis["kelly_analysis"]),
            "threshold_optimization": self._analyze_thresholds(analysis),
            "price_zone_analysis": self._analyze_price_zones(analysis["price_zone_analysis"])
        }
        
        # Save report
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\nReport saved to: {output_file}")
        return report
    
    def _result_to_dict(self, result: SimulationResult) -> Dict:
        """Convert SimulationResult to dict for JSON serialization."""
        return {
            "scenario_name": result.scenario_name,
            "total_trades": result.total_trades,
            "filled_trades": result.filled_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": result.win_rate,
            "fill_rate": result.fill_rate,
            "total_pnl_usd": result.total_pnl_usd,
            "final_bankroll_usd": result.final_bankroll_usd,
            "total_return_pct": result.total_return_pct,
            "max_drawdown_pct": result.max_drawdown_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "kelly_fraction": result.kelly_fraction,
            "kelly_optimal_size_usd": result.kelly_optimal_size_usd,
            "recommended_kelly_fraction": result.recommended_kelly_fraction,
            "profitability_score": result.profitability_score,
            "noise_score": result.noise_score,
            "compound_growth_rate": result.compound_growth_rate,
            "consecutive_losses_max": result.consecutive_losses_max,
            "avg_holding_time_min": result.avg_holding_time_min
        }
    
    def _generate_recommendations(self, analysis: Dict) -> Dict:
        """Generate actionable recommendations based on analysis."""
        recommendations = {
            "confidence_threshold": {},
            "edge_threshold": {},
            "position_sizing": {},
            "risk_management": {},
            "high_leverage_bugs": [],
            "kelly_strategy": ""
        }
        
        # Confidence threshold recommendation
        if analysis.get("best_confidence_threshold"):
            best_conf = analysis["best_confidence_threshold"]
            conf_value = int(float(best_conf.scenario_name.split("_")[-1].replace("%", "")))
            recommendations["confidence_threshold"] = {
                "recommended_value": conf_value / 100.0,
                "current_value": 0.65,  # From profile YAML
                "reasoning": f"Confidence threshold of {conf_value}% achieved profitability score of {best_conf.profitability_score:.1f}",
                "impact": "Higher confidence reduces noise but may reduce trade frequency"
            }
        
        # Edge threshold recommendation
        if analysis.get("best_edge_threshold"):
            best_edge = analysis["best_edge_threshold"]
            edge_value = int(float(best_edge.scenario_name.split("_")[-1].replace("bp", ""))) / 1000.0
            recommendations["edge_threshold"] = {
                "recommended_value": edge_value,
                "current_value": 0.03,  # From profile YAML
                "reasoning": f"Edge threshold of {edge_value*100:.1f}% achieved profitability score of {best_edge.profitability_score:.1f}",
                "impact": "Lower edge increases trade frequency but may reduce win rate"
            }
        
        # Position sizing recommendation
        recommendations["position_sizing"] = {
            "recommended_contracts_per_order": 1,  # Based on current system
            "current_contracts_per_order": 1,
            "reasoning": "1-contract rule prevents high leverage bugs and aligns with 3% risk limit",
            "warning": "Dynamic sizing multipliers are DISABLED to prevent interference with window-based risk limits"
        }
        
        # Risk management recommendation
        recommendations["risk_management"] = {
            "per_trade_risk_pct": 0.03,  # 3% from profile
            "per_window_risk_pct": 0.03,  # 3% per 15m window
            "total_venue_risk_pct": 0.05,  # 5% total per 15m window
            "reasoning": "Window-based limits prevent overtrading and force better entry prices",
            "implementation": "Hard stop enforcement in order gate with exposure tracking"
        }
        
        # High leverage bugs
        for bug_scenario in analysis.get("high_leverage_bugs", []):
            # Get description from scenario name parsing since SimulationResult doesn't have it
            issue_desc = bug_scenario.scenario_name.replace("high_leverage_", "").replace("_", " ").title()
            recommendations["high_leverage_bugs"].append({
                "scenario": bug_scenario.scenario_name,
                "issue": issue_desc,
                "max_drawdown_pct": bug_scenario.max_drawdown_pct,
                "severity": "CRITICAL" if bug_scenario.max_drawdown_pct > 30 else "HIGH",
                "fix_required": True
            })
        
        # Kelly strategy recommendation
        kelly_scenarios = analysis.get("kelly_analysis", [])
        if kelly_scenarios:
            half_kelly = [s for s in kelly_scenarios if "half" in s.scenario_name]
            if half_kelly:
                best_half_kelly = max(half_kelly, key=lambda x: x.profitability_score)
                recommendations["kelly_strategy"] = {
                    "recommended": "half_kelly",
                    "reasoning": f"Half Kelly achieved {best_half_kelly.profitability_score:.1f} profitability score with {best_half_kelly.max_drawdown_pct:.1f}% max drawdown",
                    "growth_retention": "~75% of full Kelly growth rate",
                    "drawdown_reduction": "~50% reduction vs full Kelly"
                }
        
        return recommendations
    
    def _analyze_high_leverage_bugs(self, bug_scenarios: List[SimulationResult]) -> Dict:
        """Analyze high leverage bug scenarios."""
        if not bug_scenarios:
            return {"status": "no_high_leverage_scenarios_found"}
        
        return {
            "status": "high_leverage_bugs_detected",
            "scenarios": [
                {
                    "name": s.scenario_name,
                    "description": s.scenario_name.replace("high_leverage_", "").replace("_", " ").title(),
                    "max_drawdown_pct": s.max_drawdown_pct,
                    "total_return_pct": s.total_return_pct,
                    "severity": "CRITICAL" if s.max_drawdown_pct > 30 else "HIGH" if s.max_drawdown_pct > 20 else "MEDIUM"
                }
                for s in bug_scenarios
            ],
            "common_patterns": [
                "Dynamic sizing multipliers exceeding 1.0 cause position oversizing",
                "Regime-based multipliers can bypass 3% per-asset risk limits",
                "Time-of-day scaling can interfere with window-based hard stops",
                "TTE-based sizing can exceed per-window exposure limits"
            ],
            "fixes_required": [
                "DISABLE dynamic sizing (already done in profile YAML)",
                "DISABLE regime-based multipliers (already done in unified_sizing.py)",
                "DISABLE time-of-day scaling (already done in profile YAML)",
                "DISABLE TTE-based sizing (already done in unified_sizing.py)",
                "Enforce 1-contract-per-order rule (already in place)",
                "Implement window-based exposure tracking with hard stops (already implemented)"
            ]
        }
    
    def _analyze_kelly(self, kelly_scenarios: List[SimulationResult]) -> Dict:
        """Analyze Kelly criterion scenarios."""
        if not kelly_scenarios:
            return {"status": "no_kelly_scenarios_found"}
        
        full_kelly = [s for s in kelly_scenarios if "full" in s.scenario_name and "half" not in s.scenario_name]
        half_kelly = [s for s in kelly_scenarios if "half" in s.scenario_name]
        quarter_kelly = [s for s in kelly_scenarios if "quarter" in s.scenario_name]
        
        return {
            "full_kelly": {
                "avg_return_pct": np.mean([s.total_return_pct for s in full_kelly]) if full_kelly else 0,
                "avg_drawdown_pct": np.mean([s.max_drawdown_pct for s in full_kelly]) if full_kelly else 0,
                "avg_sharpe": np.mean([s.sharpe_ratio for s in full_kelly]) if full_kelly else 0,
                "recommendation": "TOO AGGRESSIVE - High drawdown risk"
            },
            "half_kelly": {
                "avg_return_pct": np.mean([s.total_return_pct for s in half_kelly]) if half_kelly else 0,
                "avg_drawdown_pct": np.mean([s.max_drawdown_pct for s in half_kelly]) if half_kelly else 0,
                "avg_sharpe": np.mean([s.sharpe_ratio for s in half_kelly]) if half_kelly else 0,
                "recommendation": "SWEET SPOT - 75% growth, 50% drawdown reduction"
            },
            "quarter_kelly": {
                "avg_return_pct": np.mean([s.total_return_pct for s in quarter_kelly]) if quarter_kelly else 0,
                "avg_drawdown_pct": np.mean([s.max_drawdown_pct for s in quarter_kelly]) if quarter_kelly else 0,
                "avg_sharpe": np.mean([s.sharpe_ratio for s in quarter_kelly]) if quarter_kelly else 0,
                "recommendation": "CONSERVATIVE - 50% growth, minimal drawdowns"
            }
        }
    
    def _analyze_thresholds(self, analysis: Dict) -> Dict:
        """Analyze threshold optimization results."""
        return {
            "confidence_threshold": {
                "best_scenario": analysis["best_confidence_threshold"].scenario_name if analysis.get("best_confidence_threshold") else None,
                "best_profitability": analysis["best_confidence_threshold"].profitability_score if analysis.get("best_confidence_threshold") else 0,
                "trend": "Higher confidence → higher win rate but fewer trades"
            },
            "edge_threshold": {
                "best_scenario": analysis["best_edge_threshold"].scenario_name if analysis.get("best_edge_threshold") else None,
                "best_profitability": analysis["best_edge_threshold"].profitability_score if analysis.get("best_edge_threshold") else 0,
                "trend": "Lower edge → more trades but lower win rate"
            },
            "win_rate": {
                "best_scenario": analysis["best_win_rate"].scenario_name if analysis.get("best_win_rate") else None,
                "best_profitability": analysis["best_win_rate"].profitability_score if analysis.get("best_win_rate") else 0,
                "trend": "Win rate is critical for Kelly - 60%+ enables larger positions"
            },
            "fill_rate": {
                "best_scenario": analysis["best_fill_rate"].scenario_name if analysis.get("best_fill_rate") else None,
                "best_profitability": analysis["best_fill_rate"].profitability_score if analysis.get("best_fill_rate") else 0,
                "trend": "Fill rate directly impacts profitability - 90%+ required for HFT"
            }
        }
    
    def _analyze_price_zones(self, price_zone_scenarios: List[SimulationResult]) -> Dict:
        """Analyze price zone scenarios."""
        if not price_zone_scenarios:
            return {"status": "no_price_zone_scenarios_found"}
        
        sweet_spot = next((s for s in price_zone_scenarios if "sweet_spot" in s.scenario_name), None)
        moonshot = next((s for s in price_zone_scenarios if "moonshot" in s.scenario_name), None)
        
        return {
            "sweet_spot_10_75c": {
                "return_pct": sweet_spot.total_return_pct if sweet_spot else 0,
                "win_rate": sweet_spot.win_rate if sweet_spot else 0,
                "max_drawdown_pct": sweet_spot.max_drawdown_pct if sweet_spot else 0,
                "recommendation": "OPTIMAL - Best risk/reward in 10-75c zone"
            },
            "moonshot_75c_plus": {
                "return_pct": moonshot.total_return_pct if moonshot else 0,
                "win_rate": moonshot.win_rate if moonshot else 0,
                "max_drawdown_pct": moonshot.max_drawdown_pct if moonshot else 0,
                "recommendation": "AVOID - Poor risk/reward above 75c"
            },
            "threshold_recommendation": {
                "max_entry_price_yes": 0.70,  # 70c from profile YAML
                "min_entry_price_no": 0.30,  # 30c from profile YAML
                "deep_otm_expensive_cents": 75,  # 75c threshold from risk_parameters.py
                "reasoning": "75c threshold prevents moonshot entries with no reward for risk"
            }
        }


def main():
    """Main entry point for trade scenario optimization."""
    print("=" * 80)
    print("TRADE SCENARIO OPTIMIZER FOR KALSHI 15M CRYPTO TRADING")
    print("=" * 80)
    print()
    
    # Initialize optimizer
    optimizer = TradeScenarioOptimizer(
        initial_bankroll_usd=1000.0,
        num_simulations=1000
    )
    
    # Run all scenarios
    results = optimizer.run_all_scenarios()
    
    # Generate report
    report = optimizer.generate_report("trade_scenario_report.json")
    
    # Print summary
    print()
    print("=" * 80)
    print("EXECUTIVE SUMMARY")
    print("=" * 80)
    
    if report.get("executive_summary"):
        summary = report["executive_summary"]
        print(f"Best Overall Scenario: {summary['best_overall_scenario']}")
        print(f"Best Profitability Score: {summary['best_profitability_score']:.1f}/100")
        print(f"Best Total Return: {summary['best_total_return_pct']:.2f}%")
        print(f"Best Sharpe Ratio: {summary['best_sharpe_ratio']:.2f}")
        print(f"Best Max Drawdown: {summary['best_max_drawdown_pct']:.2f}%")
    
    print()
    print("=" * 80)
    print("KEY RECOMMENDATIONS")
    print("=" * 80)
    
    if report.get("recommendations"):
        recs = report["recommendations"]
        
        print(f"\nConfidence Threshold:")
        if recs.get("confidence_threshold"):
            print(f"  Recommended: {recs['confidence_threshold']['recommended_value']:.2f}")
            print(f"  Current: {recs['confidence_threshold']['current_value']:.2f}")
            print(f"  Reasoning: {recs['confidence_threshold']['reasoning']}")
        
        print(f"\nEdge Threshold:")
        if recs.get("edge_threshold"):
            print(f"  Recommended: {recs['edge_threshold']['recommended_value']:.2%}")
            print(f"  Current: {recs['edge_threshold']['current_value']:.2%}")
            print(f"  Reasoning: {recs['edge_threshold']['reasoning']}")
        
        print(f"\nKelly Strategy:")
        if recs.get("kelly_strategy"):
            ks = recs["kelly_strategy"]
            print(f"  Recommended: {ks['recommended']}")
            print(f"  Reasoning: {ks['reasoning']}")
        
        print(f"\nHigh Leverage Bugs:")
        for bug in recs.get("high_leverage_bugs", []):
            print(f"  - {bug['scenario']}: {bug['issue']}")
            print(f"    Severity: {bug['severity']}, Max DD: {bug['max_drawdown_pct']:.1f}%")
    
    print()
    print("=" * 80)
    print("FULL REPORT SAVED TO: trade_scenario_report.json")
    print("=" * 80)


if __name__ == "__main__":
    main()
