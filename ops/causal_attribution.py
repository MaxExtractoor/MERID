"""
MERID-OPS Causal Attribution Engine

Phase 2.4 of Master Build Directive

Implements:
- Strategy → outcome causality
- Counterfactual analysis
- Regret vs inaction modeling

This module answers: "Why did this happen?"

Understanding causality is essential for learning from mistakes.
"""

from __future__ import annotations

import threading
import time
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from collections import deque

from utils.logger import get_logger

logger = get_logger("ops.causal_attribution")


class CausalFactor(Enum):
    """Types of causal factors."""
    STRATEGY = "strategy"
    MARKET_REGIME = "market_regime"
    EXECUTION = "execution"
    TIMING = "timing"
    SIZING = "sizing"
    EXTERNAL_EVENT = "external_event"
    DATA_QUALITY = "data_quality"
    MODEL_ERROR = "model_error"
    UNKNOWN = "unknown"


class OutcomeType(Enum):
    """Types of outcomes."""
    PROFIT = "profit"
    LOSS = "loss"
    BREAK_EVEN = "break_even"
    MISSED_OPPORTUNITY = "missed_opportunity"
    AVOIDED_LOSS = "avoided_loss"


@dataclass
class CausalLink:
    """A causal link between factor and outcome."""
    factor: CausalFactor
    contribution: float  # -1.0 to 1.0 (negative = hurt, positive = helped)
    confidence: float    # 0.0 to 1.0
    evidence: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "factor": self.factor.value,
            "contribution": round(self.contribution, 4),
            "confidence": round(self.confidence, 4),
            "evidence": self.evidence,
        }


@dataclass
class Counterfactual:
    """A counterfactual scenario."""
    scenario_id: str
    description: str
    
    # What would have been different
    alternative_action: str
    
    # Estimated outcomes
    estimated_pnl: float
    actual_pnl: float
    pnl_difference: float
    
    # Confidence in estimate
    confidence: float
    
    # Regret analysis
    regret_score: float  # 0 = no regret, 1 = maximum regret
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "description": self.description,
            "alternative_action": self.alternative_action,
            "estimated_pnl": round(self.estimated_pnl, 2),
            "actual_pnl": round(self.actual_pnl, 2),
            "pnl_difference": round(self.pnl_difference, 2),
            "confidence": round(self.confidence, 4),
            "regret_score": round(self.regret_score, 4),
        }


@dataclass
class CausalAnalysis:
    """Complete causal analysis of an outcome."""
    analysis_id: str
    trade_id: str
    analyzed_at: float
    
    # Outcome
    outcome_type: OutcomeType
    pnl: float
    
    # Causal factors
    causal_links: List[CausalLink] = field(default_factory=list)
    primary_cause: Optional[CausalFactor] = None
    
    # Counterfactuals
    counterfactuals: List[Counterfactual] = field(default_factory=list)
    
    # Regret analysis
    action_regret: float = 0.0      # Regret from taking action
    inaction_regret: float = 0.0   # Regret from not acting differently
    net_regret: float = 0.0
    
    # Lessons
    lessons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "trade_id": self.trade_id,
            "analyzed_at": self.analyzed_at,
            "outcome_type": self.outcome_type.value,
            "pnl": round(self.pnl, 2),
            "causal_links": [cl.to_dict() for cl in self.causal_links],
            "primary_cause": self.primary_cause.value if self.primary_cause else None,
            "counterfactuals": [cf.to_dict() for cf in self.counterfactuals],
            "action_regret": round(self.action_regret, 4),
            "inaction_regret": round(self.inaction_regret, 4),
            "net_regret": round(self.net_regret, 4),
            "lessons": self.lessons,
        }


class CounterfactualSimulator:
    """
    Simulates counterfactual scenarios.
    
    "What would have happened if we had done X instead?"
    """
    
    def __init__(self):
        self._scenario_count = 0
        
        logger.info("Counterfactual simulator initialized")
    
    def simulate_no_action(
        self,
        trade_context: Dict[str, Any],
        actual_pnl: float,
    ) -> Counterfactual:
        """Simulate what would have happened with no action."""
        self._scenario_count += 1
        
        # If we didn't trade, PnL would be 0
        estimated_pnl = 0.0
        pnl_diff = estimated_pnl - actual_pnl
        
        # Regret: if actual was negative, no regret for inaction
        # if actual was positive, regret for missing out
        if actual_pnl > 0:
            regret = min(1.0, actual_pnl / 1000)  # Normalize
        else:
            regret = 0.0
        
        return Counterfactual(
            scenario_id=f"cf_no_action_{self._scenario_count}",
            description="No action taken",
            alternative_action="Hold / Do nothing",
            estimated_pnl=estimated_pnl,
            actual_pnl=actual_pnl,
            pnl_difference=pnl_diff,
            confidence=0.95,  # High confidence in "do nothing" outcome
            regret_score=regret,
        )
    
    def simulate_opposite_action(
        self,
        trade_context: Dict[str, Any],
        actual_pnl: float,
    ) -> Counterfactual:
        """Simulate what would have happened with opposite action."""
        self._scenario_count += 1
        
        # Opposite action would have opposite PnL (simplified)
        estimated_pnl = -actual_pnl
        pnl_diff = estimated_pnl - actual_pnl
        
        # Regret: if opposite would have been better
        if estimated_pnl > actual_pnl:
            regret = min(1.0, (estimated_pnl - actual_pnl) / 1000)
        else:
            regret = 0.0
        
        return Counterfactual(
            scenario_id=f"cf_opposite_{self._scenario_count}",
            description="Opposite position taken",
            alternative_action="Take opposite side of trade",
            estimated_pnl=estimated_pnl,
            actual_pnl=actual_pnl,
            pnl_difference=pnl_diff,
            confidence=0.6,  # Medium confidence
            regret_score=regret,
        )
    
    def simulate_different_size(
        self,
        trade_context: Dict[str, Any],
        actual_pnl: float,
        size_multiplier: float = 0.5,
    ) -> Counterfactual:
        """Simulate what would have happened with different position size."""
        self._scenario_count += 1
        
        # Scale PnL by size multiplier
        estimated_pnl = actual_pnl * size_multiplier
        pnl_diff = estimated_pnl - actual_pnl
        
        # Regret depends on outcome
        if actual_pnl < 0:
            # Loss was reduced
            regret = 0.0 if size_multiplier < 1 else min(1.0, abs(pnl_diff) / 500)
        else:
            # Profit was reduced
            regret = min(1.0, abs(pnl_diff) / 500) if size_multiplier < 1 else 0.0
        
        return Counterfactual(
            scenario_id=f"cf_size_{self._scenario_count}",
            description=f"Position size at {size_multiplier:.0%}",
            alternative_action=f"Use {size_multiplier:.0%} of actual size",
            estimated_pnl=estimated_pnl,
            actual_pnl=actual_pnl,
            pnl_difference=pnl_diff,
            confidence=0.8,
            regret_score=regret,
        )
    
    def simulate_different_timing(
        self,
        trade_context: Dict[str, Any],
        actual_pnl: float,
        price_at_alternative_time: Optional[float] = None,
    ) -> Counterfactual:
        """Simulate what would have happened with different timing."""
        self._scenario_count += 1
        
        # Estimate based on price difference if available
        if price_at_alternative_time and "entry_price" in trade_context:
            entry_price = trade_context["entry_price"]
            size = trade_context.get("size", 1.0)
            direction = trade_context.get("direction", 1)  # 1 = long, -1 = short
            
            price_diff = price_at_alternative_time - entry_price
            estimated_pnl = actual_pnl + (price_diff * size * direction)
        else:
            # Assume 10% better/worse
            estimated_pnl = actual_pnl * 1.1 if actual_pnl > 0 else actual_pnl * 0.9
        
        pnl_diff = estimated_pnl - actual_pnl
        
        regret = min(1.0, max(0, pnl_diff) / 500) if pnl_diff > 0 else 0.0
        
        return Counterfactual(
            scenario_id=f"cf_timing_{self._scenario_count}",
            description="Different entry/exit timing",
            alternative_action="Enter/exit at different time",
            estimated_pnl=estimated_pnl,
            actual_pnl=actual_pnl,
            pnl_difference=pnl_diff,
            confidence=0.5,  # Low confidence in timing counterfactuals
            regret_score=regret,
        )


class CausalAttributor:
    """
    Attributes outcomes to causal factors.
    """
    
    def __init__(self):
        # Factor weights for attribution
        self._factor_priors = {
            CausalFactor.STRATEGY: 0.25,
            CausalFactor.MARKET_REGIME: 0.20,
            CausalFactor.EXECUTION: 0.15,
            CausalFactor.TIMING: 0.15,
            CausalFactor.SIZING: 0.10,
            CausalFactor.EXTERNAL_EVENT: 0.05,
            CausalFactor.DATA_QUALITY: 0.05,
            CausalFactor.MODEL_ERROR: 0.05,
        }
        
        logger.info("Causal attributor initialized")
    
    def attribute(
        self,
        trade_context: Dict[str, Any],
        outcome: OutcomeType,
        pnl: float,
    ) -> List[CausalLink]:
        """
        Attribute outcome to causal factors.
        
        Returns list of causal links with contributions.
        """
        links = []
        
        # Strategy attribution
        strategy_contribution = self._assess_strategy_contribution(trade_context, pnl)
        links.append(CausalLink(
            factor=CausalFactor.STRATEGY,
            contribution=strategy_contribution,
            confidence=0.7,
            evidence=self._gather_strategy_evidence(trade_context),
        ))
        
        # Market regime attribution
        regime_contribution = self._assess_regime_contribution(trade_context, pnl)
        links.append(CausalLink(
            factor=CausalFactor.MARKET_REGIME,
            contribution=regime_contribution,
            confidence=0.6,
            evidence=self._gather_regime_evidence(trade_context),
        ))
        
        # Execution attribution
        execution_contribution = self._assess_execution_contribution(trade_context, pnl)
        links.append(CausalLink(
            factor=CausalFactor.EXECUTION,
            contribution=execution_contribution,
            confidence=0.8,
            evidence=self._gather_execution_evidence(trade_context),
        ))
        
        # Timing attribution
        timing_contribution = self._assess_timing_contribution(trade_context, pnl)
        links.append(CausalLink(
            factor=CausalFactor.TIMING,
            contribution=timing_contribution,
            confidence=0.5,
            evidence=self._gather_timing_evidence(trade_context),
        ))
        
        # Sizing attribution
        sizing_contribution = self._assess_sizing_contribution(trade_context, pnl)
        links.append(CausalLink(
            factor=CausalFactor.SIZING,
            contribution=sizing_contribution,
            confidence=0.7,
            evidence=self._gather_sizing_evidence(trade_context),
        ))
        
        return links
    
    def _assess_strategy_contribution(
        self,
        context: Dict[str, Any],
        pnl: float,
    ) -> float:
        """Assess strategy's contribution to outcome."""
        # Check if strategy signal was correct
        signal_direction = context.get("signal_direction", 0)
        actual_direction = 1 if pnl > 0 else -1 if pnl < 0 else 0
        
        if signal_direction == actual_direction:
            return 0.5  # Strategy was right
        elif signal_direction == -actual_direction:
            return -0.5  # Strategy was wrong
        return 0.0
    
    def _assess_regime_contribution(
        self,
        context: Dict[str, Any],
        pnl: float,
    ) -> float:
        """Assess market regime's contribution to outcome."""
        regime = context.get("market_regime", "unknown")
        strategy_type = context.get("strategy_type", "unknown")
        
        # Check regime-strategy alignment
        favorable_combos = {
            ("trending_bull", "momentum"): 0.3,
            ("trending_bear", "momentum"): 0.2,
            ("mean_reverting", "mean_reversion"): 0.3,
            ("high_volatility", "volatility"): 0.2,
        }
        
        combo = (regime, strategy_type)
        if combo in favorable_combos:
            return favorable_combos[combo] if pnl > 0 else -favorable_combos[combo]
        
        return 0.0
    
    def _assess_execution_contribution(
        self,
        context: Dict[str, Any],
        pnl: float,
    ) -> float:
        """Assess execution quality's contribution to outcome."""
        slippage = context.get("slippage", 0)
        expected_slippage = context.get("expected_slippage", 0)
        
        if slippage > expected_slippage * 1.5:
            return -0.2  # Bad execution hurt
        elif slippage < expected_slippage * 0.5:
            return 0.1  # Good execution helped
        return 0.0
    
    def _assess_timing_contribution(
        self,
        context: Dict[str, Any],
        pnl: float,
    ) -> float:
        """Assess timing's contribution to outcome."""
        # Check if entry was near local extremum
        entry_price = context.get("entry_price", 0)
        high_since_entry = context.get("high_since_entry", entry_price)
        low_since_entry = context.get("low_since_entry", entry_price)
        
        if entry_price == 0:
            return 0.0
        
        direction = context.get("direction", 1)
        
        if direction > 0:  # Long
            # Good timing if entered near low
            range_pct = (high_since_entry - low_since_entry) / entry_price
            entry_position = (entry_price - low_since_entry) / (high_since_entry - low_since_entry + 0.0001)
            
            if entry_position < 0.3:
                return 0.2  # Good timing
            elif entry_position > 0.7:
                return -0.2  # Bad timing
        
        return 0.0
    
    def _assess_sizing_contribution(
        self,
        context: Dict[str, Any],
        pnl: float,
    ) -> float:
        """Assess position sizing's contribution to outcome."""
        size = context.get("size", 0)
        recommended_size = context.get("recommended_size", size)
        
        if recommended_size == 0:
            return 0.0
        
        size_ratio = size / recommended_size
        
        if pnl > 0:
            # Profit: larger size helped
            if size_ratio > 1.2:
                return 0.15
            elif size_ratio < 0.8:
                return -0.1  # Could have made more
        else:
            # Loss: larger size hurt
            if size_ratio > 1.2:
                return -0.2
            elif size_ratio < 0.8:
                return 0.1  # Saved some loss
        
        return 0.0
    
    def _gather_strategy_evidence(self, context: Dict[str, Any]) -> List[str]:
        """Gather evidence for strategy attribution."""
        evidence = []
        if "strategy_name" in context:
            evidence.append(f"Strategy: {context['strategy_name']}")
        if "signal_strength" in context:
            evidence.append(f"Signal strength: {context['signal_strength']:.2f}")
        return evidence
    
    def _gather_regime_evidence(self, context: Dict[str, Any]) -> List[str]:
        """Gather evidence for regime attribution."""
        evidence = []
        if "market_regime" in context:
            evidence.append(f"Regime: {context['market_regime']}")
        if "volatility" in context:
            evidence.append(f"Volatility: {context['volatility']:.2%}")
        return evidence
    
    def _gather_execution_evidence(self, context: Dict[str, Any]) -> List[str]:
        """Gather evidence for execution attribution."""
        evidence = []
        if "slippage" in context:
            evidence.append(f"Slippage: {context['slippage']:.4f}")
        if "fill_time_ms" in context:
            evidence.append(f"Fill time: {context['fill_time_ms']}ms")
        return evidence
    
    def _gather_timing_evidence(self, context: Dict[str, Any]) -> List[str]:
        """Gather evidence for timing attribution."""
        evidence = []
        if "entry_price" in context:
            evidence.append(f"Entry price: {context['entry_price']:.4f}")
        if "time_of_day" in context:
            evidence.append(f"Time: {context['time_of_day']}")
        return evidence
    
    def _gather_sizing_evidence(self, context: Dict[str, Any]) -> List[str]:
        """Gather evidence for sizing attribution."""
        evidence = []
        if "size" in context:
            evidence.append(f"Size: {context['size']}")
        if "recommended_size" in context:
            evidence.append(f"Recommended: {context['recommended_size']}")
        return evidence


class RegretCalculator:
    """
    Calculates regret for decisions.
    
    Regret = max(0, best_alternative_outcome - actual_outcome)
    """
    
    def __init__(self):
        self._regret_history: deque = deque(maxlen=1000)
        
        logger.info("Regret calculator initialized")
    
    def calculate_regret(
        self,
        actual_pnl: float,
        counterfactuals: List[Counterfactual],
    ) -> Tuple[float, float, float]:
        """
        Calculate action regret, inaction regret, and net regret.
        
        Returns (action_regret, inaction_regret, net_regret).
        """
        if not counterfactuals:
            return 0.0, 0.0, 0.0
        
        # Best alternative outcome
        best_alternative = max(cf.estimated_pnl for cf in counterfactuals)
        
        # Action regret: regret from taking the action
        # (how much better could we have done?)
        action_regret = max(0, best_alternative - actual_pnl)
        
        # Inaction regret: regret from not taking action
        # (for missed opportunities)
        no_action_cf = next(
            (cf for cf in counterfactuals if "no_action" in cf.scenario_id),
            None
        )
        if no_action_cf:
            inaction_regret = max(0, actual_pnl - no_action_cf.estimated_pnl)
        else:
            inaction_regret = max(0, actual_pnl)  # vs doing nothing
        
        # Net regret
        net_regret = action_regret - inaction_regret
        
        # Normalize
        normalizer = max(abs(actual_pnl), 100)
        action_regret = min(1.0, action_regret / normalizer)
        inaction_regret = min(1.0, inaction_regret / normalizer)
        net_regret = max(-1.0, min(1.0, net_regret / normalizer))
        
        # Track history
        self._regret_history.append({
            "action_regret": action_regret,
            "inaction_regret": inaction_regret,
            "net_regret": net_regret,
            "timestamp": time.time(),
        })
        
        return action_regret, inaction_regret, net_regret
    
    def get_average_regret(self) -> Dict[str, float]:
        """Get average regret metrics."""
        if not self._regret_history:
            return {"action": 0.0, "inaction": 0.0, "net": 0.0}
        
        history = list(self._regret_history)
        
        return {
            "action": np.mean([h["action_regret"] for h in history]),
            "inaction": np.mean([h["inaction_regret"] for h in history]),
            "net": np.mean([h["net_regret"] for h in history]),
        }


class CausalAttributionEngine:
    """
    Main causal attribution engine.
    
    Coordinates attribution, counterfactual analysis, and regret calculation.
    """
    
    def __init__(self):
        self.attributor = CausalAttributor()
        self.simulator = CounterfactualSimulator()
        self.regret_calculator = RegretCalculator()
        
        # Analysis history
        self._analyses: List[CausalAnalysis] = []
        self._analysis_count = 0
        
        # Aggregated learnings
        self._factor_performance: Dict[CausalFactor, List[float]] = {
            f: [] for f in CausalFactor
        }
        
        logger.info("Causal attribution engine initialized")
    
    def analyze_outcome(
        self,
        trade_id: str,
        trade_context: Dict[str, Any],
        pnl: float,
    ) -> CausalAnalysis:
        """
        Perform complete causal analysis of a trade outcome.
        """
        self._analysis_count += 1
        analysis_id = f"causal_{trade_id}_{self._analysis_count}"
        
        # Determine outcome type
        if pnl > 10:
            outcome_type = OutcomeType.PROFIT
        elif pnl < -10:
            outcome_type = OutcomeType.LOSS
        else:
            outcome_type = OutcomeType.BREAK_EVEN
        
        # Attribute to causal factors
        causal_links = self.attributor.attribute(trade_context, outcome_type, pnl)
        
        # Find primary cause
        primary_cause = max(causal_links, key=lambda cl: abs(cl.contribution))
        
        # Generate counterfactuals
        counterfactuals = [
            self.simulator.simulate_no_action(trade_context, pnl),
            self.simulator.simulate_opposite_action(trade_context, pnl),
            self.simulator.simulate_different_size(trade_context, pnl, 0.5),
            self.simulator.simulate_different_size(trade_context, pnl, 1.5),
        ]
        
        # Calculate regret
        action_regret, inaction_regret, net_regret = self.regret_calculator.calculate_regret(
            pnl, counterfactuals
        )
        
        # Generate lessons
        lessons = self._generate_lessons(causal_links, counterfactuals, pnl)
        
        analysis = CausalAnalysis(
            analysis_id=analysis_id,
            trade_id=trade_id,
            analyzed_at=time.time(),
            outcome_type=outcome_type,
            pnl=pnl,
            causal_links=causal_links,
            primary_cause=primary_cause.factor,
            counterfactuals=counterfactuals,
            action_regret=action_regret,
            inaction_regret=inaction_regret,
            net_regret=net_regret,
            lessons=lessons,
        )
        
        self._analyses.append(analysis)
        
        # Update factor performance tracking
        for link in causal_links:
            self._factor_performance[link.factor].append(link.contribution)
        
        logger.info(
            "Causal analysis complete: %s - Primary cause: %s, Net regret: %.3f",
            trade_id, primary_cause.factor.value, net_regret
        )
        
        return analysis
    
    def _generate_lessons(
        self,
        causal_links: List[CausalLink],
        counterfactuals: List[Counterfactual],
        pnl: float,
    ) -> List[str]:
        """Generate lessons from analysis."""
        lessons = []
        
        # Lessons from causal factors
        for link in causal_links:
            if link.contribution < -0.3:
                lessons.append(
                    f"{link.factor.value} hurt performance significantly "
                    f"(contribution: {link.contribution:.2f})"
                )
            elif link.contribution > 0.3:
                lessons.append(
                    f"{link.factor.value} helped performance "
                    f"(contribution: {link.contribution:.2f})"
                )
        
        # Lessons from counterfactuals
        best_cf = max(counterfactuals, key=lambda cf: cf.estimated_pnl)
        if best_cf.estimated_pnl > pnl + 100:
            lessons.append(
                f"Better alternative: {best_cf.alternative_action} "
                f"(estimated +${best_cf.pnl_difference:.2f})"
            )
        
        # Lessons from regret
        if pnl < 0:
            no_action_cf = next(
                (cf for cf in counterfactuals if "no_action" in cf.scenario_id),
                None
            )
            if no_action_cf and no_action_cf.estimated_pnl > pnl:
                lessons.append("Inaction would have been better than this trade")
        
        return lessons
    
    def get_factor_summary(self) -> Dict[str, Any]:
        """Get summary of factor contributions."""
        summary = {}
        
        for factor, contributions in self._factor_performance.items():
            if contributions:
                summary[factor.value] = {
                    "avg_contribution": round(np.mean(contributions), 4),
                    "std_contribution": round(np.std(contributions), 4),
                    "positive_rate": round(
                        sum(1 for c in contributions if c > 0) / len(contributions), 4
                    ),
                    "sample_size": len(contributions),
                }
        
        return summary
    
    def get_recent_analyses(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent analyses."""
        return [a.to_dict() for a in self._analyses[-limit:]]
    
    def get_status(self) -> Dict[str, Any]:
        """Get engine status."""
        return {
            "total_analyses": len(self._analyses),
            "average_regret": self.regret_calculator.get_average_regret(),
            "factor_summary": self.get_factor_summary(),
        }


# Singleton instance
_causal_engine: Optional[CausalAttributionEngine] = None
_causal_engine_lock = threading.Lock()


def get_causal_engine() -> CausalAttributionEngine:
    """Get the singleton causal attribution engine."""
    global _causal_engine
    if _causal_engine is None:
        with _causal_engine_lock:
            if _causal_engine is None:
                _causal_engine = CausalAttributionEngine()
    return _causal_engine
