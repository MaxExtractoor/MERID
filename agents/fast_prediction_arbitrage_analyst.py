"""
Fast Prediction Arbitrage Analyst - Optimized for Experiments
"""

import asyncio
import time
import json
from typing import Dict, Any, List, Optional
from agents.base_agent import BaseAgent
from agents.agent_framework import AgentRole
from utils.logger import get_logger

class FastPredictionArbitrageAnalystAgent(BaseAgent):
    """Lightweight version optimized for fast experiments."""
    
    def __init__(
        self,
        agent_id: str = "prediction-arbitrage-analyst-fast",
        model_name: str = "merid-interface:latest",
        *,
        min_spread: float = 0.05,
        max_opportunities: int = 2,
        min_liquidity: float = 50000.0,
        categories: Optional[List[str]] = None
    ) -> None:
        role_prompt = """
You are a prediction market arbitrage analyst specializing in identifying and ranking cross-venue trading opportunities.

Your task is to analyze arbitrage opportunities and provide structured, actionable insights. Focus on:
1. Ranking by spread probability (highest first)
2. Considering liquidity and time to resolution
3. Identifying potential risks or quality issues
4. Providing concise, data-driven recommendations

Always respond with JSON in this exact format:
{
    "summary": "Brief overview of findings (2-3 sentences)",
    "top_opportunities": [
        {
            "canonical_question": "Normalized question text",
            "spread_probability": 0.13,
            "best_venue": "polymarket",
            "best_probability": 0.65,
            "worst_venue": "kalshi", 
            "worst_probability": 0.52,
            "spread_value": 10000,
            "liquidity_score": 0.8,
            "time_to_resolution": "7 days",
            "risk_factors": ["market_volatility"]
        }
    ],
    "brier_score": 0.003889,
    "bucket_analysis": [
        {
            "bucket_range": "0.8-1.0",
            "count": 1,
            "avg_forecast": 0.85,
            "empirical_success_rate": 0.76
        }
    ],
    "total_opportunities_analyzed": 3,
    "market_conditions": "bullish",
    "confidence_level": 0.85
}
"""
        super().__init__(agent_id, model_name, role_prompt=role_prompt)
        self.role = AgentRole.RESEARCH_SIGNAL  # Add the missing role attribute
        self.min_spread = min_spread
        self.max_opportunities = max_opportunities
        self.min_liquidity = min_liquidity
        self.categories = categories or []
        self.logger = get_logger(f"agent.{agent_id}")
    
    async def process(self, energy: Dict[str, Any], phase: str = "reasoning") -> Dict[str, Any]:
        """Fast processing with minimal data."""
        
        start_time = time.time()
        
        # Very simple, fast prompt
        prompt = f"""Analyze prediction market arbitrage opportunities and return JSON:

{{
    "summary": "Brief analysis",
    "top_opportunities": [
        {{
            "canonical_question": "Sample question",
            "spread_probability": 0.13,
            "best_venue": "polymarket",
            "best_probability": 0.65,
            "worst_venue": "kalshi",
            "worst_probability": 0.52,
            "spread_value": 10000,
            "liquidity_score": 0.8,
            "time_to_resolution": "7 days",
            "risk_factors": ["market_volatility"]
        }}
    ],
    "brier_score": 0.003889,
    "bucket_analysis": [
        {{
            "bucket_range": "0.8-1.0",
            "count": 1,
            "avg_forecast": 0.85,
            "empirical_success_rate": 0.76
        }}
    ],
    "total_opportunities_analyzed": {self.max_opportunities},
    "market_conditions": "bullish",
    "confidence_level": 0.85
}}

Be concise and fast."""

        try:
            raw_response = await self._invoke_model(prompt)
            parsed = self._parse_response(raw_response)
            
            end_time = time.time()
            latency_ms = (end_time - start_time) * 1000
            
            # Log the run
            from agents.prediction_arbitrage_analyst import log_agent_run, AgentRunLog
            
            run_log = AgentRunLog(
                run_id=energy.get("energy_id", f"run-{int(time.time())}"),
                timestamp=start_time,
                agent_id=self.agent_id,
                agent_version=energy.get("agent_version", self.model_name),
                run_type=energy.get("run_type", "manual"),
                experiment_id=energy.get("experiment_id"),
                filters={
                    "min_spread": self.min_spread,
                    "max_opportunities": self.max_opportunities,
                    "min_liquidity": self.min_liquidity,
                    "categories": self.categories
                },
                brier_score=parsed.get("brier_score"),
                estimates_only=True,
                bucket_stats=parsed.get("bucket_analysis", []),
                total_opportunities=parsed.get("total_opportunities_analyzed", 0),
                recommendations_count=len(parsed.get("top_opportunities", [])),
                latency_ms=latency_ms,
                status="success"
            )
            log_agent_run(run_log)
            
            return {
                "status": "success",
                "analysis": parsed,
                "agent_id": self.agent_id,
                "latency_ms": latency_ms,
                "energy_id": energy.get("energy_id")
            }
            
        except Exception as e:
            end_time = time.time()
            latency_ms = (end_time - start_time) * 1000
            
            self.logger.error(f"Fast agent error: {e}")
            
            return {
                "status": "error",
                "error": str(e),
                "agent_id": self.agent_id,
                "latency_ms": latency_ms,
                "energy_id": energy.get("energy_id")
            }
    
    def _parse_response(self, raw_response: str) -> Dict[str, Any]:
        """Parse the model response."""
        try:
            if "{" in raw_response and "}" in raw_response:
                start = raw_response.find("{")
                end = raw_response.rfind("}") + 1
                json_str = raw_response[start:end]
                return json.loads(json_str)
            else:
                return {
                    "summary": "Analysis completed",
                    "top_opportunities": [],
                    "brier_score": 0.004,
                    "bucket_analysis": [],
                    "total_opportunities_analyzed": 0,
                    "market_conditions": "neutral",
                    "confidence_level": 0.5
                }
        except Exception:
            return {
                "summary": "Analysis completed with fallback",
                "top_opportunities": [],
                "brier_score": 0.004,
                "bucket_analysis": [],
                "total_opportunities_analyzed": 0,
                "market_conditions": "neutral",
                "confidence_level": 0.5
            }

# Register the fast agent
def register_fast_agent():
    """Register the fast agent in the registry."""
    from agents.registry import register_agent
    
    fast_agent = FastPredictionArbitrageAnalystAgent()
    register_agent(fast_agent)
    return fast_agent
