"""
MarketAnalyst Agent - Price pattern detection per MASTER_SPEC v1.0

Agent ID: market-analyst-01
Role: Price pattern detection and technical analysis
Expertise: 0.92
Risk Factor: 0.4

This agent:
- Observes market data streams (price, volume, funding)
- Detects technical patterns (trends, support/resistance, momentum)
- Votes on proposals based on market structure
- Reflects on prediction accuracy to improve

Reference: MASTER_SPEC.md Section 4.1
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from agents.interface import (
    AgentInterface,
    AgentVote,
    VoteDecision,
    MarketState,
    Proposal,
    Outcome,
    AgentState,
)
from utils.logger import get_logger

logger = get_logger("agents.market_analyst")


@dataclass
class PricePoint:
    """Single price observation."""
    timestamp: float
    price: float
    volume: float
    source: str


@dataclass
class TechnicalSignal:
    """Technical analysis signal."""
    signal_type: str
    direction: str
    strength: float
    timeframe: str
    details: Dict[str, object] = field(default_factory=dict)


class MarketAnalystAgent(AgentInterface):
    """
    Market Analyst Agent - Specializes in price pattern detection.
    
    Capabilities:
    - Trend detection (bullish/bearish/neutral)
    - Support/resistance identification
    - Momentum analysis
    - Volume profile analysis
    - Funding rate interpretation
    
    This agent consumes market data events and generates
    technical analysis signals for consensus voting.
    """
    
    AGENT_ID = "market-analyst-01"
    EXPERTISE_SCORE = 0.92
    RISK_FACTOR = 0.4
    
    PRICE_HISTORY_LIMIT = 1000
    TREND_WINDOW = 20
    MOMENTUM_WINDOW = 14
    VOLUME_WINDOW = 10
    
    def __init__(self) -> None:
        """Initialize market analyst agent."""
        super().__init__(
            agent_id=self.AGENT_ID,
            expertise_score=self.EXPERTISE_SCORE,
            risk_factor=self.RISK_FACTOR,
        )
        
        self._price_history: Dict[str, List[PricePoint]] = {}
        self._current_signals: List[TechnicalSignal] = []
        self._last_analysis: Optional[Dict[str, object]] = None
        self._prediction_history: List[Dict[str, object]] = []
    
    async def observe(self, market_state: MarketState) -> None:
        """
        Ingest market state and update price history.
        
        Args:
            market_state: Current market snapshot
        """
        self._state = AgentState.PROCESSING
        self.heartbeat()
        
        for symbol, price in market_state.prices.items():
            if symbol not in self._price_history:
                self._price_history[symbol] = []
            
            point = PricePoint(
                timestamp=market_state.timestamp,
                price=price,
                volume=market_state.volumes.get(symbol, 0.0),
                source="market_state",
            )
            
            self._price_history[symbol].append(point)
            
            if len(self._price_history[symbol]) > self.PRICE_HISTORY_LIMIT:
                self._price_history[symbol] = self._price_history[symbol][-self.PRICE_HISTORY_LIMIT:]
        
        self.set_working_memory("last_market_state", {
            "timestamp": market_state.timestamp,
            "price_count": len(market_state.prices),
            "symbols": list(market_state.prices.keys()),
        })
        
        self._logger.debug(
            "Observed market state: %d symbols, volatility=%.4f",
            len(market_state.prices), market_state.volatility_index
        )
    
    async def analyze(self) -> Dict[str, object]:
        """
        Generate technical analysis from observations.
        
        Returns:
            Analysis results with detected signals
        """
        self._state = AgentState.PROCESSING
        start_time = time.time()
        
        self._current_signals.clear()
        symbol_analyses: Dict[str, Dict[str, object]] = {}
        
        for symbol, history in self._price_history.items():
            if len(history) < self.TREND_WINDOW:
                continue
            
            analysis = self._analyze_symbol(symbol, history)
            symbol_analyses[symbol] = analysis
        
        overall_bias = self._calculate_overall_bias(symbol_analyses)
        
        self._last_analysis = {
            "timestamp": time.time(),
            "symbols_analyzed": len(symbol_analyses),
            "symbol_analyses": symbol_analyses,
            "signals": [self._signal_to_dict(s) for s in self._current_signals],
            "overall_bias": overall_bias,
            "confidence": self._calculate_analysis_confidence(),
        }
        
        latency_ms = (time.time() - start_time) * 1000
        self._record_processing(latency_ms, True)
        
        self._logger.info(
            "Analysis complete: %d symbols, %d signals, bias=%s, confidence=%.2f",
            len(symbol_analyses), len(self._current_signals),
            overall_bias["direction"], overall_bias["strength"]
        )
        
        return self._last_analysis
    
    async def vote(self, proposal: Proposal) -> AgentVote:
        """
        Cast vote on proposal based on market analysis.
        
        Args:
            proposal: Proposal to vote on
            
        Returns:
            Agent's vote with reasoning
        """
        self._state = AgentState.VOTING
        self.heartbeat()
        
        if proposal.is_expired():
            return AgentVote(
                agent_id=self._agent_id,
                decision=VoteDecision.ABSTAIN,
                confidence=0.0,
                reasoning="Proposal expired before vote could be cast",
            )
        
        if self._last_analysis is None:
            return AgentVote(
                agent_id=self._agent_id,
                decision=VoteDecision.ABSTAIN,
                confidence=0.3,
                reasoning="Insufficient market data for informed vote",
            )
        
        proposal_type = proposal.proposal_type
        payload = proposal.payload
        
        decision, confidence, reasoning = self._evaluate_proposal(
            proposal_type, payload
        )
        
        self._prediction_history.append({
            "proposal_id": proposal.proposal_id,
            "decision": decision.value,
            "confidence": confidence,
            "timestamp": time.time(),
            "market_bias": self._last_analysis.get("overall_bias", {}),
        })
        
        if len(self._prediction_history) > 100:
            self._prediction_history = self._prediction_history[-100:]
        
        self._state = AgentState.READY
        
        return AgentVote(
            agent_id=self._agent_id,
            decision=decision,
            confidence=confidence,
            reasoning=reasoning,
        )
    
    async def reflect(self, outcome: Outcome) -> None:
        """
        Update internal state based on outcome.
        
        Args:
            outcome: Outcome of the proposal
        """
        self._state = AgentState.REFLECTING
        self.heartbeat()
        
        matching_prediction = None
        for pred in self._prediction_history:
            if pred.get("proposal_id") == outcome.proposal_id:
                matching_prediction = pred
                break
        
        if matching_prediction is None:
            self._logger.debug("No matching prediction for outcome %s", outcome.outcome_id)
            return
        
        was_correct = self._evaluate_prediction_accuracy(
            matching_prediction, outcome
        )
        
        self.set_working_memory(f"outcome:{outcome.proposal_id}", {
            "prediction": matching_prediction["decision"],
            "actual": outcome.result,
            "correct": was_correct,
            "timestamp": time.time(),
        })
        
        if was_correct:
            self._logger.info(
                "Prediction correct for %s (predicted=%s, actual=%s)",
                outcome.proposal_id, matching_prediction["decision"], outcome.result
            )
        else:
            self._logger.info(
                "Prediction incorrect for %s (predicted=%s, actual=%s)",
                outcome.proposal_id, matching_prediction["decision"], outcome.result
            )
        
        self._state = AgentState.READY
    
    def _analyze_symbol(
        self,
        symbol: str,
        history: List[PricePoint],
    ) -> Dict[str, object]:
        """
        Perform technical analysis on a single symbol.
        
        Args:
            symbol: Trading symbol
            history: Price history
            
        Returns:
            Analysis results for symbol
        """
        prices = [p.price for p in history]
        volumes = [p.volume for p in history]
        
        trend = self._detect_trend(prices)
        momentum = self._calculate_momentum(prices)
        support, resistance = self._find_support_resistance(prices)
        volume_trend = self._analyze_volume(volumes)
        
        if trend["direction"] != "neutral" and trend["strength"] > 0.6:
            self._current_signals.append(TechnicalSignal(
                signal_type="trend",
                direction=trend["direction"],
                strength=trend["strength"],
                timeframe="short",
                details={"symbol": symbol, "slope": trend.get("slope", 0)},
            ))
        
        if abs(momentum["rsi"] - 50) > 20:
            direction = "overbought" if momentum["rsi"] > 70 else "oversold"
            self._current_signals.append(TechnicalSignal(
                signal_type="momentum",
                direction=direction,
                strength=abs(momentum["rsi"] - 50) / 50,
                timeframe="short",
                details={"symbol": symbol, "rsi": momentum["rsi"]},
            ))
        
        return {
            "symbol": symbol,
            "current_price": prices[-1] if prices else 0,
            "trend": trend,
            "momentum": momentum,
            "support": support,
            "resistance": resistance,
            "volume_trend": volume_trend,
            "data_points": len(history),
        }
    
    def _detect_trend(self, prices: List[float]) -> Dict[str, object]:
        """
        Detect price trend using simple moving average crossover.
        
        Args:
            prices: List of prices
            
        Returns:
            Trend analysis
        """
        if len(prices) < self.TREND_WINDOW:
            return {"direction": "neutral", "strength": 0.0}
        
        recent = prices[-self.TREND_WINDOW:]
        sma_short = sum(recent[-5:]) / 5
        sma_long = sum(recent) / len(recent)
        
        diff_pct = (sma_short - sma_long) / sma_long if sma_long != 0 else 0
        
        if diff_pct > 0.01:
            direction = "bullish"
            strength = min(abs(diff_pct) * 10, 1.0)
        elif diff_pct < -0.01:
            direction = "bearish"
            strength = min(abs(diff_pct) * 10, 1.0)
        else:
            direction = "neutral"
            strength = 0.0
        
        slope = (recent[-1] - recent[0]) / recent[0] if recent[0] != 0 else 0
        
        return {
            "direction": direction,
            "strength": strength,
            "slope": slope,
            "sma_short": sma_short,
            "sma_long": sma_long,
        }
    
    def _calculate_momentum(self, prices: List[float]) -> Dict[str, object]:
        """
        Calculate momentum indicators (RSI-like).
        
        Args:
            prices: List of prices
            
        Returns:
            Momentum analysis
        """
        if len(prices) < self.MOMENTUM_WINDOW + 1:
            return {"rsi": 50.0, "momentum": 0.0}
        
        changes = [
            prices[i] - prices[i-1]
            for i in range(1, len(prices))
        ]
        
        recent_changes = changes[-self.MOMENTUM_WINDOW:]
        
        gains = [c for c in recent_changes if c > 0]
        losses = [-c for c in recent_changes if c < 0]
        
        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        
        if avg_loss == 0:
            rsi = 100.0
        elif avg_gain == 0:
            rsi = 0.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        
        momentum = sum(recent_changes) / len(recent_changes) if recent_changes else 0
        
        return {
            "rsi": rsi,
            "momentum": momentum,
            "avg_gain": avg_gain,
            "avg_loss": avg_loss,
        }
    
    def _find_support_resistance(
        self,
        prices: List[float],
    ) -> tuple[float, float]:
        """
        Find support and resistance levels.
        
        Args:
            prices: List of prices
            
        Returns:
            Tuple of (support, resistance)
        """
        if len(prices) < 10:
            return (0.0, 0.0)
        
        recent = prices[-50:] if len(prices) >= 50 else prices
        
        support = min(recent)
        resistance = max(recent)
        
        return (support, resistance)
    
    def _analyze_volume(self, volumes: List[float]) -> Dict[str, object]:
        """
        Analyze volume trend.
        
        Args:
            volumes: List of volumes
            
        Returns:
            Volume analysis
        """
        if len(volumes) < self.VOLUME_WINDOW:
            return {"trend": "neutral", "avg": 0.0}
        
        recent = volumes[-self.VOLUME_WINDOW:]
        avg_volume = sum(recent) / len(recent)
        
        first_half = sum(recent[:len(recent)//2]) / (len(recent)//2)
        second_half = sum(recent[len(recent)//2:]) / (len(recent) - len(recent)//2)
        
        if second_half > first_half * 1.2:
            trend = "increasing"
        elif second_half < first_half * 0.8:
            trend = "decreasing"
        else:
            trend = "stable"
        
        return {
            "trend": trend,
            "avg": avg_volume,
            "recent": recent[-1] if recent else 0,
        }
    
    def _calculate_overall_bias(
        self,
        symbol_analyses: Dict[str, Dict[str, object]],
    ) -> Dict[str, object]:
        """
        Calculate overall market bias from all symbol analyses.
        
        Args:
            symbol_analyses: Per-symbol analysis results
            
        Returns:
            Overall bias assessment
        """
        if not symbol_analyses:
            return {"direction": "neutral", "strength": 0.0}
        
        bullish_count = 0
        bearish_count = 0
        total_strength = 0.0
        
        for analysis in symbol_analyses.values():
            trend = analysis.get("trend", {})
            direction = trend.get("direction", "neutral")
            strength = trend.get("strength", 0.0)
            
            if direction == "bullish":
                bullish_count += 1
                total_strength += strength
            elif direction == "bearish":
                bearish_count += 1
                total_strength -= strength
        
        total = bullish_count + bearish_count
        if total == 0:
            return {"direction": "neutral", "strength": 0.0}
        
        if bullish_count > bearish_count:
            direction = "bullish"
            strength = total_strength / total
        elif bearish_count > bullish_count:
            direction = "bearish"
            strength = abs(total_strength) / total
        else:
            direction = "neutral"
            strength = 0.0
        
        return {
            "direction": direction,
            "strength": min(strength, 1.0),
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
        }
    
    def _calculate_analysis_confidence(self) -> float:
        """Calculate confidence in current analysis."""
        if not self._price_history:
            return 0.3
        
        total_points = sum(len(h) for h in self._price_history.values())
        data_confidence = min(total_points / 500, 1.0)
        
        signal_confidence = min(len(self._current_signals) / 5, 1.0)
        
        return (data_confidence * 0.6 + signal_confidence * 0.4) * self._expertise_score
    
    def _evaluate_proposal(
        self,
        proposal_type: str,
        payload: Dict[str, object],
    ) -> tuple[VoteDecision, float, str]:
        """
        Evaluate proposal and determine vote.
        
        Args:
            proposal_type: Type of proposal
            payload: Proposal content
            
        Returns:
            Tuple of (decision, confidence, reasoning)
        """
        if self._last_analysis is None:
            return (
                VoteDecision.ABSTAIN,
                0.3,
                "No analysis available",
            )
        
        bias = self._last_analysis.get("overall_bias", {})
        bias_direction = bias.get("direction", "neutral")
        bias_strength = bias.get("strength", 0.0)
        
        if proposal_type in ("buy", "long", "bullish_bet"):
            if bias_direction == "bullish" and bias_strength > 0.5:
                return (
                    VoteDecision.APPROVE,
                    min(0.5 + bias_strength * 0.4, 0.95),
                    f"Market bias is {bias_direction} with strength {bias_strength:.2f}. "
                    f"Technical signals support bullish position.",
                )
            elif bias_direction == "bearish" and bias_strength > 0.5:
                return (
                    VoteDecision.REJECT,
                    min(0.5 + bias_strength * 0.4, 0.95),
                    f"Market bias is {bias_direction} with strength {bias_strength:.2f}. "
                    f"Technical signals contradict bullish position.",
                )
            else:
                return (
                    VoteDecision.ABSTAIN,
                    0.4,
                    f"Market bias is {bias_direction} with insufficient strength ({bias_strength:.2f}). "
                    f"Cannot confidently support or reject.",
                )
        
        elif proposal_type in ("sell", "short", "bearish_bet"):
            if bias_direction == "bearish" and bias_strength > 0.5:
                return (
                    VoteDecision.APPROVE,
                    min(0.5 + bias_strength * 0.4, 0.95),
                    f"Market bias is {bias_direction} with strength {bias_strength:.2f}. "
                    f"Technical signals support bearish position.",
                )
            elif bias_direction == "bullish" and bias_strength > 0.5:
                return (
                    VoteDecision.REJECT,
                    min(0.5 + bias_strength * 0.4, 0.95),
                    f"Market bias is {bias_direction} with strength {bias_strength:.2f}. "
                    f"Technical signals contradict bearish position.",
                )
            else:
                return (
                    VoteDecision.ABSTAIN,
                    0.4,
                    f"Market bias is {bias_direction} with insufficient strength ({bias_strength:.2f}). "
                    f"Cannot confidently support or reject.",
                )
        
        return (
            VoteDecision.ABSTAIN,
            0.3,
            f"Proposal type '{proposal_type}' not in market analyst domain.",
        )
    
    def _evaluate_prediction_accuracy(
        self,
        prediction: Dict[str, object],
        outcome: Outcome,
    ) -> bool:
        """
        Evaluate if prediction was correct.
        
        Args:
            prediction: Original prediction
            outcome: Actual outcome
            
        Returns:
            True if prediction was correct
        """
        pred_decision = prediction.get("decision", "abstain")
        actual_result = outcome.result
        
        if pred_decision == "approve" and actual_result in ("success", "profit", "correct"):
            return True
        if pred_decision == "reject" and actual_result in ("failure", "loss", "incorrect"):
            return True
        
        return False
    
    def _signal_to_dict(self, signal: TechnicalSignal) -> Dict[str, object]:
        """Convert signal to dictionary."""
        return {
            "signal_type": signal.signal_type,
            "direction": signal.direction,
            "strength": signal.strength,
            "timeframe": signal.timeframe,
            "details": signal.details,
        }


_market_analyst: Optional[MarketAnalystAgent] = None
_market_analyst_lock = threading.Lock()


def get_market_analyst() -> MarketAnalystAgent:
    """Get or create market analyst agent singleton."""
    global _market_analyst
    if _market_analyst is None:
        with _market_analyst_lock:
            if _market_analyst is None:
                _market_analyst = MarketAnalystAgent()
    return _market_analyst
