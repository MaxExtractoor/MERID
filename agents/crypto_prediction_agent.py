"""
Crypto Prediction Agent Implementation

Concrete implementation of AgentInterface for cryptocurrency market analysis and prediction.
Consumes market data streams and produces governance decisions with confidence scoring.
"""

import asyncio
import time
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import statistics

from agents.interface import (
    AgentInterface, AgentVote, AgentState, VoteDecision, 
    MarketState, Proposal, Outcome
)
from core.events import EventEnvelope, EventType
from utils.logger import get_logger

logger = get_logger("crypto_prediction_agent")

@dataclass
class AnalysisResult:
    """Structured analysis result from agent"""
    agent_id: str
    timestamp: datetime
    symbol: str
    signal: str  # "buy", "sell", "hold"
    confidence: float  # 0.0 to 1.0
    price_target: Optional[float]
    reasoning: str
    technical_indicators: Dict[str, float]
    market_context: Dict[str, Any]
    risk_score: float  # 0.0 to 1.0
    time_horizon: str  # "short", "medium", "long"

@dataclass
class DecisionContext:
    """Context for decision making"""
    current_price: float
    price_history: List[float]
    volume_history: List[float]
    market_events: List[EventEnvelope]
    oracle_prices: Dict[str, float]
    internal_state: Dict[str, Any]
    risk_limits: Dict[str, float]

class CryptoPredictionAgent(AgentInterface):
    """
    Concrete agent for cryptocurrency market analysis and prediction.
    
    Capabilities:
    - Technical analysis on market data
    - Signal generation with confidence scoring
    - Risk assessment and position sizing
    - Learning from outcomes
    """
    
    def __init__(self, config: Dict[str, Any]):
        # Extract required parameters from config
        agent_id = config.get("agent_id", "crypto_prediction_agent_v1")
        expertise_score = config.get("expertise_score", 0.7)  # 0.0 to 1.0
        risk_factor = config.get("risk_factor", 0.5)  # 0.0 to 1.0
        
        # Initialize parent class
        super().__init__(agent_id, expertise_score, risk_factor)
        
        # Additional configuration
        if "symbols" not in config:
            try:
                from data.asset_universe import get_swarm_eligible
                _default_syms = [a.symbol for a in get_swarm_eligible()
                                  if "/" in a.symbol and ":" not in a.symbol]
            except Exception:
                _default_syms = ["BTC/USD", "ETH/USD"]
        else:
            _default_syms = config["symbols"]
        self.symbols = _default_syms
        self.confidence_threshold = config.get("confidence_threshold", 0.6)
        self.max_position_size = config.get("max_position_size", 0.1)  # 10% of portfolio
        
        # Internal state
        self._price_history: Dict[str, List[float]] = {symbol: [] for symbol in self.symbols}
        self._volume_history: Dict[str, List[float]] = {symbol: [] for symbol in self.symbols}
        self._recent_events: List[EventEnvelope] = []
        self._oracle_prices: Dict[str, float] = {}
        self._learning_state: Dict[str, Any] = {
            "successful_predictions": 0,
            "failed_predictions": 0,
            "total_predictions": 0,
            "accuracy_score": 0.0,
            "last_updated": datetime.now()
        }
        
        # Technical analysis parameters
        self._ma_short_window = 10
        self._ma_long_window = 30
        self._rsi_window = 14
        self._volatility_window = 20
        
        logger.info(f"CryptoPredictionAgent initialized: {self.agent_id}")
        logger.info(f"Monitoring symbols: {self.symbols}")
        logger.info(f"Expertise score: {self.expertise_score:.2f}, Risk factor: {self.risk_factor:.2f}")
        
        # Set initial state
        self._state = AgentState.READY
    
    async def observe(self, market_state: MarketState) -> None:
        """
        Ingest current market state for analysis.
        
        This is the first step in the observe-analyze-vote loop.
        Agents should store relevant observations in working memory.
        
        Args:
            market_state: Current market snapshot
        """
        try:
            self._state = AgentState.PROCESSING
            
            # Update price history from market state
            for symbol, price in market_state.prices.items():
                if symbol in self._price_history:
                    self._price_history[symbol].append(price)
                    if len(self._price_history[symbol]) > 100:
                        self._price_history[symbol].pop(0)
            
            # Update volume history from market state
            for symbol, volume in market_state.volumes.items():
                if symbol in self._volume_history:
                    self._volume_history[symbol].append(volume)
                    if len(self._volume_history[symbol]) > 100:
                        self._volume_history[symbol].pop(0)
            
            # Store in working memory
            self._working_memory["last_market_state"] = market_state
            self._working_memory["last_update"] = time.time()
            
            logger.debug(f"Observed market state for {len(market_state.prices)} symbols")
            
        except Exception as e:
            logger.error(f"Observe failed: {e}")
            self._state = AgentState.ERROR
            raise
    
    async def analyze(self) -> Dict[str, object]:
        """
        Generate analysis from observations.
        
        This is the second step in the observe-analyze-vote loop.
        Agents should process observations and generate insights.
        
        Returns:
            Analysis results dictionary
        """
        try:
            self._state = AgentState.PROCESSING
            start_time = time.time()
            
            # Get market state from working memory
            market_state = self._working_memory.get("last_market_state")
            if not market_state:
                raise ValueError("No market state available for analysis")
            
            # Build decision context
            decision_context = self._build_decision_context_from_market_state(market_state)
            
            # Perform technical analysis
            technical_analysis = self._perform_technical_analysis(decision_context)
            
            # Generate signal
            signal = self._generate_signal(technical_analysis, decision_context)
            
            # Calculate confidence
            confidence = self._calculate_confidence(signal, technical_analysis, decision_context)
            
            # Assess risk
            risk_score = self._assess_risk(signal, technical_analysis, decision_context)
            
            # Generate reasoning
            reasoning = self._generate_reasoning(signal, technical_analysis, decision_context)
            
            # Create analysis result
            result = {
                "agent_id": self.agent_id,
                "timestamp": datetime.now().isoformat(),
                "symbol": decision_context.current_symbol,
                "signal": signal,
                "confidence": confidence,
                "price_target": technical_analysis.get("price_target"),
                "reasoning": reasoning,
                "technical_indicators": technical_analysis,
                "market_context": {
                    "current_price": decision_context.current_price,
                    "volume": decision_context.volume_history[-1] if decision_context.volume_history else 0,
                    "price_change_24h": self._calculate_price_change(decision_context.price_history),
                    "volatility": self._calculate_volatility(decision_context.price_history)
                },
                "risk_score": risk_score,
                "time_horizon": "short",
                "processing_time_ms": (time.time() - start_time) * 1000
            }
            
            logger.info(f"Analysis completed: {signal} with {confidence:.2f} confidence")
            return result
            
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            self._state = AgentState.ERROR
            raise
    
    async def vote(self, proposal: Proposal) -> AgentVote:
        """
        Cast vote on a proposal.
        
        This is the third step in the observe-analyze-vote loop.
        Agents must return a valid AgentVote with reasoning.
        
        Args:
            proposal: Proposal to vote on
            
        Returns:
            Agent's vote with confidence and reasoning
        """
        try:
            self._state = AgentState.VOTING
            start_time = time.time()
            
            # Extract proposal data
            proposal_data = proposal.payload
            signal = proposal_data.get("signal", "hold")
            confidence = proposal_data.get("confidence", 0.0)
            reasoning = proposal_data.get("reasoning", "")
            
            # Validate confidence threshold
            if confidence < self.confidence_threshold:
                logger.warning(f"Low confidence {confidence:.2f} below threshold {self.confidence_threshold}")
                vote = AgentVote(
                    agent_id=self.agent_id,
                    decision=VoteDecision.ABSTAIN,
                    confidence=confidence,
                    reasoning=f"Confidence {confidence:.2f} below threshold {self.confidence_threshold}",
                    timestamp=time.time()
                )
                self._record_processing((time.time() - start_time) * 1000, True)
                return vote
            
            # Convert signal to governance decision
            decision = self._signal_to_vote_decision(signal)
            
            # Calculate position size based on confidence and risk
            position_size = self._calculate_position_size(confidence, self.risk_factor)
            
            # Create vote
            vote = AgentVote(
                agent_id=self.agent_id,
                decision=decision,
                confidence=confidence,
                reasoning=reasoning,
                timestamp=time.time()
            )
            
            logger.info(f"Vote cast: {decision} with {confidence:.2f} confidence")
            self._record_processing((time.time() - start_time) * 1000, True)
            return vote
            
        except Exception as e:
            logger.error(f"Voting failed: {e}")
            self._state = AgentState.ERROR
            # Return safe default vote
            vote = AgentVote(
                agent_id=self.agent_id,
                decision=VoteDecision.ABSTAIN,
                confidence=0.0,
                reasoning=f"Voting failed: {str(e)}",
                timestamp=time.time()
            )
            self._record_processing(0, False)
            return vote
    
    async def reflect(self, outcome: Outcome) -> None:
        """
        Update internal state based on outcome.
        
        Called after consensus is reached and outcome is known.
        Agents should update learned patterns and adjust behavior.
        
        Args:
            outcome: Outcome of the proposal
        """
        try:
            self._state = AgentState.REFLECTING
            start_time = time.time()
            
            # Extract outcome data
            success = outcome.result == "success"
            prediction_accuracy = outcome.metadata.get("prediction_accuracy", 0.0)
            
            # Update learning state
            self._learning_state["total_predictions"] += 1
            
            if success:
                self._learning_state["successful_predictions"] += 1
                logger.info(f"Successful prediction for proposal {outcome.proposal_id}")
            else:
                self._learning_state["failed_predictions"] += 1
                logger.info(f"Failed prediction for proposal {outcome.proposal_id}")
            
            # Update accuracy score
            total = self._learning_state["total_predictions"]
            if total > 0:
                self._learning_state["accuracy_score"] = (
                    self._learning_state["successful_predictions"] / total
                )
            
            # Update last updated timestamp
            self._learning_state["last_updated"] = datetime.now()
            
            # Log learning metrics
            logger.info(f"Learning metrics: {self._learning_state['accuracy_score']:.2f} accuracy, "
                       f"{self._learning_state['successful_predictions']}/{total} successful")
            
            # Adjust parameters based on performance
            await self._adjust_parameters(outcome)
            
            self._record_processing((time.time() - start_time) * 1000, True)
            self._state = AgentState.READY
            
        except Exception as e:
            logger.error(f"Reflection failed: {e}")
            self._state = AgentState.ERROR
            self._record_processing(0, False)
    
    def _build_decision_context_from_market_state(self, market_state: MarketState) -> DecisionContext:
        """Build decision context from MarketState"""
        try:
            # Extract current symbol (use first available)
            current_symbol = self.symbols[0] if self.symbols else "BTC/USD"
            
            # Get current price from market state
            current_price = market_state.prices.get(current_symbol, 45000.0)
            
            # Get price and volume history
            price_history = self._price_history.get(current_symbol, [])
            volume_history = self._volume_history.get(current_symbol, [])
            
            # Get market events
            market_events = self._recent_events
            
            # Get oracle prices
            oracle_prices = self._oracle_prices
            
            # Internal state
            internal_state = {
                "learning_metrics": self._learning_state,
                "risk_tolerance": self.risk_factor,
                "confidence_threshold": self.confidence_threshold
            }
            
            # Risk limits
            risk_limits = {
                "max_position_size": self.max_position_size,
                "max_risk_per_trade": 0.02,  # 2% max risk per trade
                "max_daily_loss": 0.05  # 5% max daily loss
            }
            
            return DecisionContext(
                current_price=current_price,
                price_history=price_history,
                volume_history=volume_history,
                market_events=market_events,
                oracle_prices=oracle_prices,
                internal_state=internal_state,
                risk_limits=risk_limits
            )
            
        except Exception as e:
            logger.error(f"Failed to build decision context: {e}")
            # Return safe default context
            return DecisionContext(
                current_price=45000.0,
                price_history=[],
                volume_history=[],
                market_events=[],
                oracle_prices={},
                internal_state={},
                risk_limits={}
            )
    
    def _signal_to_vote_decision(self, signal: str) -> VoteDecision:
        """Convert trading signal to VoteDecision"""
        try:
            # Map signals to vote decisions
            signal_map = {
                "buy": VoteDecision.APPROVE,
                "sell": VoteDecision.REJECT, 
                "hold": VoteDecision.ABSTAIN
            }
            return signal_map.get(signal.lower(), VoteDecision.ABSTAIN)
                
        except Exception as e:
            logger.error(f"Signal to decision conversion failed: {e}")
            return VoteDecision.ABSTAIN
    
    def _perform_technical_analysis(self, context: DecisionContext) -> Dict[str, float]:
        """Perform technical analysis on market data"""
        try:
            indicators = {}
            
            if len(context.price_history) >= self._ma_short_window:
                # Moving averages
                ma_short = statistics.mean(context.price_history[-self._ma_short_window:])
                ma_long = statistics.mean(context.price_history[-self._ma_long_window:])
                indicators["ma_short"] = ma_short
                indicators["ma_long"] = ma_long
                indicators["ma_crossover"] = (ma_short - ma_long) / ma_long
            
            if len(context.price_history) >= self._rsi_window:
                # RSI calculation (simplified)
                price_changes = []
                for i in range(1, len(context.price_history[-self._rsi_window - 1:])):
                    price_changes.append(context.price_history[-i] - context.price_history[-i-1])
                
                gains = [change for change in price_changes if change > 0]
                losses = [abs(change) for change in price_changes if change < 0]
                
                avg_gain = statistics.mean(gains) if gains else 0
                avg_loss = statistics.mean(losses) if losses else 0
                
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                else:
                    rsi = 100 if avg_gain > 0 else 50
                
                indicators["rsi"] = rsi
            
            # Volatility
            if len(context.price_history) >= self._volatility_window:
                volatility = self._calculate_volatility(context.price_history[-self._volatility_window:])
                indicators["volatility"] = volatility
            
            # Price momentum
            if len(context.price_history) >= 5:
                momentum = (context.price_history[-1] - context.price_history[-5]) / context.price_history[-5]
                indicators["momentum"] = momentum
            
            # Volume analysis
            if context.volume_history:
                avg_volume = statistics.mean(context.volume_history[-10:])
                current_volume = context.volume_history[-1]
                volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
                indicators["volume_ratio"] = volume_ratio
            
            return indicators
            
        except Exception as e:
            logger.error(f"Technical analysis failed: {e}")
            return {}
    
    def _generate_signal(self, indicators: Dict[str, float], context: DecisionContext) -> str:
        """Generate trading signal based on technical indicators"""
        try:
            signal_score = 0.0
            
            # MA crossover signal
            if "ma_crossover" in indicators:
                crossover = indicators["ma_crossover"]
                if crossover > 0.01:  # Short MA above long MA
                    signal_score += 0.3
                elif crossover < -0.01:  # Short MA below long MA
                    signal_score -= 0.3
            
            # RSI signal
            if "rsi" in indicators:
                rsi = indicators["rsi"]
                if rsi < 30:  # Oversold
                    signal_score += 0.2
                elif rsi > 70:  # Overbought
                    signal_score -= 0.2
            
            # Momentum signal
            if "momentum" in indicators:
                momentum = indicators["momentum"]
                signal_score += momentum * 0.2  # Scale momentum
            
            # Volume signal
            if "volume_ratio" in indicators:
                volume_ratio = indicators["volume_ratio"]
                if volume_ratio > 1.5:  # High volume
                    signal_score *= 1.1  # Boost signal confidence
                elif volume_ratio < 0.5:  # Low volume
                    signal_score *= 0.9  # Reduce signal confidence
            
            # Convert score to signal
            if signal_score > 0.3:
                return "buy"
            elif signal_score < -0.3:
                return "sell"
            else:
                return "hold"
                
        except Exception as e:
            logger.error(f"Signal generation failed: {e}")
            return "hold"
    
    def _calculate_confidence(self, signal: str, indicators: Dict[str, float], context: DecisionContext) -> float:
        """Calculate confidence score for the signal"""
        try:
            confidence = 0.5  # Base confidence
            
            # Increase confidence for strong indicators
            if "ma_crossover" in indicators:
                crossover_strength = abs(indicators["ma_crossover"])
                confidence += crossover_strength * 0.2
            
            # RSI confidence
            if "rsi" in indicators:
                rsi = indicators["rsi"]
                if rsi < 20 or rsi > 80:  # Extreme RSI
                    confidence += 0.1
                elif 30 <= rsi <= 70:  # Neutral RSI
                    confidence -= 0.1
            
            # Volume confidence
            if "volume_ratio" in indicators:
                volume_ratio = indicators["volume_ratio"]
                if volume_ratio > 2.0:  # Very high volume
                    confidence += 0.1
            
            # Learning-based confidence adjustment
            accuracy = self._learning_state.get("accuracy_score", 0.5)
            confidence = confidence * (0.5 + accuracy)  # Adjust based on historical accuracy
            
            # Cap confidence at 1.0
            confidence = min(1.0, max(0.0, confidence))
            
            return confidence
            
        except Exception as e:
            logger.error(f"Confidence calculation failed: {e}")
            return 0.5
    
    def _assess_risk(self, signal: str, indicators: Dict[str, float], context: DecisionContext) -> float:
        """Assess risk score for the signal"""
        try:
            risk_score = 0.3  # Base risk
            
            # Volatility risk
            if "volatility" in indicators:
                volatility = indicators["volatility"]
                risk_score += volatility * 0.3
            
            # Signal consistency risk
            if "ma_crossover" in indicators:
                crossover = indicators["ma_crossover"]
                if abs(crossover) < 0.01:  # Weak signal
                    risk_score += 0.2
            
            # Volume risk
            if "volume_ratio" in indicators:
                volume_ratio = indicators["volume_ratio"]
                if volume_ratio < 0.5:  # Low volume
                    risk_score += 0.1
            
            # Historical performance risk
            accuracy = self._learning_state.get("accuracy_score", 0.5)
            if accuracy < 0.4:  # Poor historical performance
                risk_score += 0.2
            
            # Cap risk score at 1.0
            risk_score = min(1.0, max(0.0, risk_score))
            
            return risk_score
            
        except Exception as e:
            logger.error(f"Risk assessment failed: {e}")
            return 0.5
    
    def _generate_reasoning(self, signal: str, indicators: Dict[str, float], context: DecisionContext) -> str:
        """Generate human-readable reasoning for the signal"""
        try:
            reasons = []
            
            # MA crossover reasoning
            if "ma_crossover" in indicators:
                crossover = indicators["ma_crossover"]
                if crossover > 0.01:
                    reasons.append(f"Short MA ({indicators.get('ma_short', 0):.2f}) above long MA ({indicators.get('ma_long', 0):.2f})")
                elif crossover < -0.01:
                    reasons.append(f"Short MA ({indicators.get('ma_short', 0):.2f}) below long MA ({indicators.get('ma_long', 0):.2f})")
            
            # RSI reasoning
            if "rsi" in indicators:
                rsi = indicators["rsi"]
                if rsi < 30:
                    reasons.append(f"RSI ({rsi:.1f}) indicates oversold conditions")
                elif rsi > 70:
                    reasons.append(f"RSI ({rsi:.1f}) indicates overbought conditions")
            
            # Momentum reasoning
            if "momentum" in indicators:
                momentum = indicators["momentum"]
                if momentum > 0.02:
                    reasons.append(f"Positive momentum ({momentum:.2%})")
                elif momentum < -0.02:
                    reasons.append(f"Negative momentum ({momentum:.2%})")
            
            # Volume reasoning
            if "volume_ratio" in indicators:
                volume_ratio = indicators["volume_ratio"]
                if volume_ratio > 1.5:
                    reasons.append(f"High volume ({volume_ratio:.1f}x average)")
            
            # Add learning context
            accuracy = self._learning_state.get("accuracy_score", 0.5)
            reasons.append(f"Historical accuracy: {accuracy:.1%}")
            
            return "; ".join(reasons) if reasons else "Insufficient data for detailed analysis"
            
        except Exception as e:
            logger.error(f"Reasoning generation failed: {e}")
            return f"Analysis completed with {signal} signal"
    
    def _signal_to_decision(self, signal: str, risk_score: float) -> str:
        """Convert trading signal to governance decision"""
        try:
            # High risk signals become more conservative
            if risk_score > 0.7:
                if signal == "buy":
                    return "hold"  # Too risky to buy
                elif signal == "sell":
                    return "demote"  # Conservative sell
                else:
                    return "hold"
            else:
                # Normal risk mapping
                signal_map = {
                    "buy": "promote",
                    "sell": "demote", 
                    "hold": "hold"
                }
                return signal_map.get(signal, "hold")
                
        except Exception as e:
            logger.error(f"Signal to decision conversion failed: {e}")
            return "hold"
    
    def _calculate_position_size(self, confidence: float, risk_score: float) -> float:
        """Calculate position size based on confidence and risk"""
        try:
            # Base position size
            base_size = self.max_position_size
            
            # Adjust for confidence
            confidence_adjustment = confidence
            
            # Adjust for risk (inverse relationship)
            risk_adjustment = 1.0 - risk_score
            
            # Calculate final position size
            position_size = base_size * confidence_adjustment * risk_adjustment
            
            # Ensure minimum and maximum limits
            position_size = max(0.01, min(self.max_position_size, position_size))
            
            return position_size
            
        except Exception as e:
            logger.error(f"Position size calculation failed: {e}")
            return 0.05  # Conservative default
    
    def _calculate_price_change(self, price_history: List[float]) -> float:
        """Calculate 24-hour price change"""
        try:
            if len(price_history) < 2:
                return 0.0
            
            current_price = price_history[-1]
            previous_price = price_history[0]
            
            if previous_price == 0:
                return 0.0
            
            return (current_price - previous_price) / previous_price
            
        except Exception as e:
            logger.error(f"Price change calculation failed: {e}")
            return 0.0
    
    def _calculate_volatility(self, price_history: List[float]) -> float:
        """Calculate price volatility"""
        try:
            if len(price_history) < 2:
                return 0.0
            
            returns = []
            for i in range(1, len(price_history)):
                if price_history[i-1] != 0:
                    returns.append((price_history[i] - price_history[i-1]) / price_history[i-1])
            
            if not returns:
                return 0.0
            
            return statistics.stdev(returns)
            
        except Exception as e:
            logger.error(f"Volatility calculation failed: {e}")
            return 0.0
    
    async def _adjust_parameters(self, outcome: Dict[str, Any]) -> None:
        """Adjust internal parameters based on outcomes"""
        try:
            success = outcome.get("success", False)
            confidence = outcome.get("confidence", 0.5)
            
            # Adjust confidence threshold based on performance
            if success and confidence > 0.8:
                # Successful high-confidence prediction - slightly lower threshold
                self.confidence_threshold = max(0.4, self.confidence_threshold - 0.01)
            elif not success and confidence > 0.8:
                # Failed high-confidence prediction - raise threshold
                self.confidence_threshold = min(0.8, self.confidence_threshold + 0.01)
            
            logger.debug(f"Adjusted confidence threshold to {self.confidence_threshold:.2f}")
            
        except Exception as e:
            logger.error(f"Parameter adjustment failed: {e}")
    
    def get_state(self) -> AgentState:
        """Get current agent state"""
        return self._state
    
    def get_learning_metrics(self) -> Dict[str, Any]:
        """Get learning performance metrics"""
        return self._learning_state.copy()
    
    def update_market_data(self, events: List[EventEnvelope]) -> None:
        """Update internal market data from events"""
        try:
            self._recent_events = events[-100:]  # Keep last 100 events
            
            for event in events:
                if event.event_type == EventType.MARKET_DATA:
                    tick = event.data
                    symbol = tick.symbol
                    
                    # Update price history
                    if symbol in self._price_history:
                        self._price_history[symbol].append(tick.price)
                        if len(self._price_history[symbol]) > 100:
                            self._price_history[symbol].pop(0)
                    
                    # Update volume history
                    if symbol in self._volume_history:
                        self._volume_history[symbol].append(tick.volume)
                        if len(self._volume_history[symbol]) > 100:
                            self._volume_history[symbol].pop(0)
            
        except Exception as e:
            logger.error(f"Market data update failed: {e}")
    
    def update_oracle_prices(self, prices: Dict[str, float]) -> None:
        """Update oracle price data"""
        try:
            self._oracle_prices.update(prices)
            logger.debug(f"Updated oracle prices: {len(prices)} symbols")
        except Exception as e:
            logger.error(f"Oracle price update failed: {e}")
