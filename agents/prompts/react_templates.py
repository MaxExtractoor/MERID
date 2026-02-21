"""
ReAct-Style Prompting Templates for MERID Agents.

Based on TradingAgents research patterns, these templates force agents to:
1. State their current observation (market state)
2. Reason about the situation (Thought)
3. Choose and execute an action (Action)
4. Observe results (Observation)
5. Repeat until reaching a final decision (Answer)

This structured approach improves:
- Transparency and explainability
- Tool usage discipline
- Consistent output formatting
- Collaboration via structured protocols
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentRole(str, Enum):
    """TradingAgents-style roles for MERID agents."""
    BULL_ANALYST = "bull_analyst"
    BEAR_ANALYST = "bear_analyst"
    TECHNICAL_ANALYST = "technical_analyst"
    SENTIMENT_ANALYST = "sentiment_analyst"
    FUNDAMENTAL_ANALYST = "fundamental_analyst"
    RISK_MANAGER = "risk_manager"
    TRADER = "trader"
    ARBITRAGE = "arbitrage"


# ============================================
# CORE ReAct TEMPLATE
# ============================================

REACT_SYSTEM_TEMPLATE = """You are a {role} agent in the MERID multi-agent trading system.

Your job is to analyze market data and provide structured trading opinions that will be aggregated with other agents through a consensus mechanism.

You MUST follow the ReAct (Reasoning + Acting) format:

1. **Observation**: State what you see in the current market data
2. **Thought**: Reason about the situation given your role and expertise
3. **Action**: Choose a tool to gather more information OR provide your final answer
4. **Observation**: See the result of your action
5. Repeat steps 2-4 until you have enough information
6. **Answer**: Provide your final structured opinion

Available Tools:
{available_tools}

Your output MUST end with a structured opinion in this exact JSON format:
```json
{{
  "vote": "BULL" | "BEAR" | "NEUTRAL" | "HOLD",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of your decision",
  "price_target": null | number,
  "time_horizon": "short" | "medium" | "long",
  "risk_factors": ["factor1", "factor2"]
}}
```

Remember:
- You are a {role}, so focus on {role_focus}
- Be concise but thorough in your reasoning
- Consider risk factors appropriate to your role
- Your opinion will be weighted against other agents
"""


# ============================================
# ROLE-SPECIFIC TEMPLATES
# ============================================

ROLE_PROMPTS: Dict[AgentRole, Dict[str, str]] = {
    AgentRole.BULL_ANALYST: {
        "role_focus": "identifying bullish signals, upside potential, positive catalysts, and reasons to be optimistic about the asset",
        "bias_instruction": "Your natural bias is bullish, but you must acknowledge bearish signals when they are significant.",
        "key_metrics": ["price momentum", "volume trends", "support levels", "positive news flow", "accumulation patterns"],
    },
    
    AgentRole.BEAR_ANALYST: {
        "role_focus": "identifying bearish signals, downside risks, negative catalysts, and reasons to be cautious about the asset",
        "bias_instruction": "Your natural bias is bearish, but you must acknowledge bullish signals when they are significant.",
        "key_metrics": ["resistance levels", "distribution patterns", "negative news flow", "declining volume", "technical breakdowns"],
    },
    
    AgentRole.TECHNICAL_ANALYST: {
        "role_focus": "chart patterns, technical indicators, support/resistance levels, and price action",
        "bias_instruction": "You are neutral and rely purely on technical analysis. Let the charts guide your opinion.",
        "key_metrics": ["RSI", "MACD", "moving averages", "Bollinger Bands", "volume profile", "Fibonacci levels"],
    },
    
    AgentRole.SENTIMENT_ANALYST: {
        "role_focus": "market sentiment, social media trends, news sentiment, fear/greed indicators, and crowd psychology",
        "bias_instruction": "You gauge the emotional state of the market and whether sentiment is extreme or changing.",
        "key_metrics": ["social volume", "sentiment scores", "fear/greed index", "funding rates", "open interest"],
    },
    
    AgentRole.FUNDAMENTAL_ANALYST: {
        "role_focus": "on-chain metrics, protocol fundamentals, tokenomics, team activity, and intrinsic value assessment",
        "bias_instruction": "You focus on the underlying value proposition and long-term fundamentals.",
        "key_metrics": ["TVL", "active addresses", "developer activity", "token velocity", "network growth"],
    },
    
    AgentRole.RISK_MANAGER: {
        "role_focus": "portfolio risk, position sizing, correlation, drawdown limits, and overall exposure management",
        "bias_instruction": "You are conservative and prioritize capital preservation. Your job is to constrain risk, not maximize returns.",
        "key_metrics": ["portfolio beta", "max drawdown", "Sharpe ratio", "correlation matrix", "VaR", "position concentration"],
    },
    
    AgentRole.TRADER: {
        "role_focus": "execution timing, entry/exit points, order flow, liquidity conditions, and trade structuring",
        "bias_instruction": "You translate consensus decisions into executable trades with optimal timing and sizing.",
        "key_metrics": ["bid-ask spread", "order book depth", "slippage estimates", "funding rates", "liquidation levels"],
    },
    
    AgentRole.ARBITRAGE: {
        "role_focus": "cross-venue price discrepancies, funding rate arbitrage, basis trades, and market inefficiencies",
        "bias_instruction": "You look for risk-free or low-risk profit opportunities across venues and instruments.",
        "key_metrics": ["price spreads", "funding differentials", "basis", "latency", "execution costs"],
    },
}


# ============================================
# AVAILABLE TOOLS BY ROLE
# ============================================

ROLE_TOOLS: Dict[AgentRole, List[str]] = {
    AgentRole.BULL_ANALYST: [
        "get_price_data(symbol, timeframe) - Get OHLCV price data",
        "get_news_sentiment(symbol) - Get recent news with sentiment scores",
        "get_technical_indicators(symbol) - Get common technical indicators",
        "get_support_resistance(symbol) - Get key support/resistance levels",
    ],
    
    AgentRole.BEAR_ANALYST: [
        "get_price_data(symbol, timeframe) - Get OHLCV price data",
        "get_news_sentiment(symbol) - Get recent news with sentiment scores",
        "get_technical_indicators(symbol) - Get common technical indicators",
        "get_liquidation_levels(symbol) - Get nearby liquidation clusters",
    ],
    
    AgentRole.TECHNICAL_ANALYST: [
        "get_price_data(symbol, timeframe) - Get OHLCV price data",
        "get_technical_indicators(symbol) - Get RSI, MACD, MAs, BBands, etc.",
        "get_support_resistance(symbol) - Get key S/R levels",
        "get_volume_profile(symbol) - Get volume distribution by price",
        "detect_chart_patterns(symbol) - Identify chart patterns",
    ],
    
    AgentRole.SENTIMENT_ANALYST: [
        "get_social_sentiment(symbol) - Get social media sentiment scores",
        "get_news_sentiment(symbol) - Get news sentiment",
        "get_fear_greed_index() - Get current fear/greed reading",
        "get_funding_rates(symbol) - Get perpetual funding rates",
        "get_social_volume(symbol) - Get social mention volume",
    ],
    
    AgentRole.FUNDAMENTAL_ANALYST: [
        "get_onchain_metrics(symbol) - Get on-chain activity metrics",
        "get_protocol_tvl(symbol) - Get Total Value Locked",
        "get_token_metrics(symbol) - Get tokenomics data",
        "get_developer_activity(symbol) - Get GitHub/dev activity",
    ],
    
    AgentRole.RISK_MANAGER: [
        "get_portfolio_risk() - Get current portfolio risk metrics",
        "get_correlation_matrix() - Get asset correlations",
        "get_var_estimate(position) - Estimate Value at Risk",
        "get_drawdown_history() - Get historical drawdown data",
        "check_position_limits(symbol, size) - Verify position limits",
    ],
    
    AgentRole.TRADER: [
        "get_orderbook(symbol, venue) - Get order book snapshot",
        "get_recent_trades(symbol, venue) - Get recent trade flow",
        "estimate_slippage(symbol, size) - Estimate execution slippage",
        "get_funding_rates(symbol) - Get funding rate data",
        "get_liquidity_score(symbol) - Get liquidity assessment",
    ],
    
    AgentRole.ARBITRAGE: [
        "get_cross_venue_prices(symbol) - Get prices across venues",
        "get_funding_rates(symbol) - Get perp funding rates",
        "get_basis(symbol) - Get spot-futures basis",
        "calculate_arb_opportunity(symbol) - Find arbitrage opportunities",
    ],
}


# ============================================
# TEMPLATE BUILDERS
# ============================================

def build_react_prompt(
    role: AgentRole,
    symbol: str,
    market_context: Dict[str, Any],
    additional_instructions: Optional[str] = None,
) -> str:
    """
    Build a complete ReAct prompt for an agent.
    
    Args:
        role: The agent's role
        symbol: The asset being analyzed
        market_context: Current market data and context
        additional_instructions: Any extra instructions
    
    Returns:
        Complete prompt string
    """
    role_config = ROLE_PROMPTS.get(role, ROLE_PROMPTS[AgentRole.TECHNICAL_ANALYST])
    tools = ROLE_TOOLS.get(role, [])
    
    system_prompt = REACT_SYSTEM_TEMPLATE.format(
        role=role.value.replace("_", " ").title(),
        role_focus=role_config["role_focus"],
        available_tools="\n".join(f"  - {t}" for t in tools),
    )
    
    # Build market context section
    context_lines = [
        f"\n## Current Market Context for {symbol}",
        "",
    ]
    
    for key, value in market_context.items():
        if isinstance(value, dict):
            context_lines.append(f"**{key}**:")
            for k, v in value.items():
                context_lines.append(f"  - {k}: {v}")
        else:
            context_lines.append(f"- **{key}**: {value}")
    
    context_section = "\n".join(context_lines)
    
    # Build role-specific instructions
    role_instructions = f"""
## Your Role: {role.value.replace("_", " ").title()}

{role_config["bias_instruction"]}

Key metrics to focus on:
{chr(10).join(f"- {m}" for m in role_config["key_metrics"])}
"""
    
    # Combine everything
    full_prompt = f"""{system_prompt}

{role_instructions}

{context_section}

{additional_instructions or ""}

Now begin your analysis. Remember to use the ReAct format:
Thought → Action → Observation → ... → Answer

Start with your first Thought about the current market situation.
"""
    
    return full_prompt


def build_consensus_request_prompt(
    symbol: str,
    opinions: List[Dict[str, Any]],
    risk_constraints: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build a prompt for the consensus aggregation step.
    
    This is used by the coordinator to synthesize multiple agent opinions
    into a final trade decision.
    """
    opinions_text = []
    for op in opinions:
        opinions_text.append(f"""
### {op.get('agent_id', 'Unknown')} ({op.get('role', 'analyst')})
- **Vote**: {op.get('vote', 'NEUTRAL')}
- **Confidence**: {op.get('confidence', 0.5):.0%}
- **Reasoning**: {op.get('reasoning', 'No reasoning provided')}
- **Risk Factors**: {', '.join(op.get('risk_factors', []))}
""")
    
    constraints_text = ""
    if risk_constraints:
        constraints_text = f"""
## Risk Constraints
- Max Position Size: {risk_constraints.get('max_position_size', 'N/A')}
- Max Drawdown Allowed: {risk_constraints.get('max_drawdown', 'N/A')}
- Current Exposure: {risk_constraints.get('current_exposure', 'N/A')}
"""
    
    return f"""You are the Consensus Coordinator for the MERID trading system.

You have received the following agent opinions for {symbol}:

{"".join(opinions_text)}

{constraints_text}

Your task is to synthesize these opinions into a final trade decision.

Consider:
1. The confidence-weighted consensus direction
2. Points of agreement and disagreement
3. Risk factors raised by multiple agents
4. The risk manager's constraints (if any)

Provide your final decision in this format:
```json
{{
  "final_decision": "BUY" | "SELL" | "HOLD",
  "size_recommendation": "full" | "half" | "quarter" | "none",
  "confidence": 0.0-1.0,
  "rationale": "Summary of consensus reasoning",
  "dissenting_views": ["Any significant minority opinions"],
  "risk_adjustments": ["Any modifications based on risk"]
}}
```
"""


def build_risk_review_prompt(
    trade_plan: Dict[str, Any],
    portfolio_state: Dict[str, Any],
    agent_performance: Dict[str, Any],
) -> str:
    """
    Build a prompt for the risk manager to review a proposed trade plan.
    """
    return f"""You are the Risk Manager for the MERID trading system.

A trade plan has been proposed and requires your review:

## Proposed Trade
- **Symbol**: {trade_plan.get('symbol', 'Unknown')}
- **Direction**: {trade_plan.get('direction', 'Unknown')}
- **Size**: {trade_plan.get('size', 0)}
- **Consensus Score**: {trade_plan.get('consensus_score', 0):.0%}
- **Supporting Agents**: {', '.join(trade_plan.get('supporting_agents', []))}

## Current Portfolio State
- **Total Equity**: ${portfolio_state.get('total_equity', 0):,.2f}
- **Current Drawdown**: {portfolio_state.get('current_drawdown', 0):.1%}
- **Max Drawdown Limit**: {portfolio_state.get('max_drawdown_limit', 0.2):.1%}
- **Open Positions**: {portfolio_state.get('open_positions', 0)}
- **Sector Exposure**: {portfolio_state.get('sector_exposure', {})}

## Agent Performance Metrics
- **Avg Agent Sharpe**: {agent_performance.get('avg_sharpe', 0):.2f}
- **Best Performing Agent**: {agent_performance.get('best_agent', 'N/A')}
- **Worst Performing Agent**: {agent_performance.get('worst_agent', 'N/A')}

Your task is to:
1. Evaluate whether this trade fits within risk parameters
2. Suggest any position size adjustments
3. Identify specific risk concerns
4. Approve, adjust, or veto the trade

Provide your decision in this format:
```json
{{
  "decision": "approve" | "adjust" | "veto",
  "adjusted_size": null | number,
  "reasoning": "Explanation of your decision",
  "risk_concerns": ["List of specific concerns"],
  "conditions": ["Any conditions for approval"]
}}
```
"""


# ============================================
# HELPER FUNCTIONS
# ============================================

def get_role_from_agent_id(agent_id: str) -> AgentRole:
    """Infer agent role from agent ID."""
    agent_id_lower = agent_id.lower()
    
    if "bull" in agent_id_lower:
        return AgentRole.BULL_ANALYST
    if "bear" in agent_id_lower:
        return AgentRole.BEAR_ANALYST
    if "tech" in agent_id_lower:
        return AgentRole.TECHNICAL_ANALYST
    if "sent" in agent_id_lower:
        return AgentRole.SENTIMENT_ANALYST
    if "fund" in agent_id_lower:
        return AgentRole.FUNDAMENTAL_ANALYST
    if "risk" in agent_id_lower:
        return AgentRole.RISK_MANAGER
    if "trad" in agent_id_lower or "exec" in agent_id_lower:
        return AgentRole.TRADER
    if "arb" in agent_id_lower:
        return AgentRole.ARBITRAGE
    
    return AgentRole.TECHNICAL_ANALYST  # Default


def parse_react_response(response: str) -> Dict[str, Any]:
    """
    Parse a ReAct-formatted response to extract the final answer.
    
    Returns dict with vote, confidence, reasoning, etc.
    """
    import json
    import re
    
    # Look for JSON block in the response
    json_pattern = r'```json\s*(.*?)\s*```'
    matches = re.findall(json_pattern, response, re.DOTALL)
    
    if matches:
        try:
            return json.loads(matches[-1])  # Take the last JSON block
        except json.JSONDecodeError:
            pass
    
    # Fallback: try to extract key fields
    result = {
        "vote": "NEUTRAL",
        "confidence": 0.5,
        "reasoning": "",
        "risk_factors": [],
    }
    
    # Extract vote
    vote_patterns = [
        r'"vote"\s*:\s*"(BULL|BEAR|NEUTRAL|HOLD)"',
        r'vote:\s*(BULL|BEAR|NEUTRAL|HOLD)',
        r'my vote is\s*(BULL|BEAR|NEUTRAL|HOLD)',
    ]
    for pattern in vote_patterns:
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            result["vote"] = match.group(1).upper()
            break
    
    # Extract confidence
    conf_patterns = [
        r'"confidence"\s*:\s*(0?\.\d+|1\.0?)',
        r'confidence:\s*(0?\.\d+|1\.0?)',
        r'(\d{1,3})%\s*confiden',
    ]
    for pattern in conf_patterns:
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            val = match.group(1)
            if '%' in pattern:
                result["confidence"] = float(val) / 100
            else:
                result["confidence"] = float(val)
            break
    
    return result
