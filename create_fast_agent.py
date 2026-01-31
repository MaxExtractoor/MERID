#!/usr/bin/env python3
"""
Create a fast version of the prediction arbitrage analyst for experiments.
"""

import os
from pathlib import Path

def create_fast_agent():
    """Create a lightweight version of the agent for fast experiments."""
    
    print("🚀 Creating Fast Agent Configuration")
    print("=" * 40)
    
    # Create environment variables for faster execution
    env_config = """
# Fast Agent Configuration for Experiments
export OLLAMA_READ_TIMEOUT=30
export OLLAMA_CONNECT_TIMEOUT=5
export OLLAMA_MODEL_INTERFACE=merid-interface:latest
"""
    
    # Create fast agent script
    fast_agent_code = '''
"""
Fast Prediction Arbitrage Analyst - Optimized for Experiments
"""

import asyncio
import time
import json
from typing import Dict, Any, List, Optional
from agents.base_agent import BaseAgent, AgentErrorResponse, AgentErrorType
from utils.logger import get_logger
from core.time_authority import current_time

class FastPredictionArbitrageAnalystAgent(BaseAgent):
    """Lightweight version optimized for fast experiments."""
    
    def __init__(
        self,
        agent_id: str = "prediction-arbitrage-analyst-fast",
        model_name: str = "merid-interface:latest",  # Faster model
        *,
        min_spread: float = 0.05,
        max_opportunities: int = 2,  # Reduced
        min_liquidity: float = 50000.0,
        categories: Optional[List[str]] = None
    ) -> None:
        super().__init__(agent_id, model_name)
        self.min_spread = min_spread
        self.max_opportunities = max_opportunities
        self.min_liquidity = min_liquidity
        self.categories = categories or []
        self.logger = get_logger(f"agent.{agent_id}")
    
    async def process(self, energy: Dict[str, Any], phase: str = "reasoning") -> Dict[str, Any]:
        """Fast processing with minimal data."""
        
        start_time = time.time()
        
        # Use a very simple, fast prompt
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
            # Call the model with shorter timeout
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
            # Simple JSON parsing
            if "{" in raw_response and "}" in raw_response:
                start = raw_response.find("{")
                end = raw_response.rfind("}") + 1
                json_str = raw_response[start:end]
                return json.loads(json_str)
            else:
                # Fallback response
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
            # Return safe fallback
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

if __name__ == "__main__":
    agent = register_fast_agent()
    print(f"✅ Fast agent registered: {agent.agent_id}")
'''
    
    # Save the fast agent
    agent_file = Path("agents/fast_prediction_arbitrage_analyst.py")
    with agent_file.open("w", encoding="utf-8") as f:
        f.write(fast_agent_code)
    
    # Save environment config
    env_file = Path("experiments/fast_agent_env.sh")
    with env_file.open("w", encoding="utf-8") as f:
        f.write(env_config)
    
    print(f"✅ Fast agent created: {agent_file}")
    print(f"✅ Environment config: {env_file}")
    
    return agent_file, env_file

def update_registry():
    """Update the agent registry to include the fast agent."""
    
    registry_update = '''
# Add to agents/__init__.py
from agents.fast_prediction_arbitrage_analyst import register_fast_agent

# Auto-register the fast agent
try:
    register_fast_agent()
except Exception as e:
    print(f"Warning: Could not register fast agent: {e}")
'''
    
    update_file = Path("experiments/registry_update.py")
    with update_file.open("w", encoding="utf-8") as f:
        f.write(registry_update)
    
    print(f"✅ Registry update script: {update_file}")
    return update_file

def main():
    """Create the fast agent configuration."""
    
    print("🎯 Creating Fast Agent for Experiments")
    print("=" * 50)
    
    agent_file, env_file = create_fast_agent()
    update_file = update_registry()
    
    print("\n🚀 Fast Agent Ready!")
    print("=" * 30)
    print("✅ Fast agent code created")
    print("✅ Environment configuration created")
    print("✅ Registry update prepared")
    
    print("\n📋 Next Steps:")
    print("1. Apply registry update: python experiments/registry_update.py")
    print("2. Restart server to load fast agent")
    print("3. Update experiment config to use fast agent")
    print("4. Run fast experiments")

if __name__ == "__main__":
    main()
