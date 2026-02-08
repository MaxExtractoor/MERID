"""
Risk Manager Agent Prompt - MERID TradingAgents Implementation

This agent is responsible for enforcing position limits, drawdown constraints,
and volatility caps. Reviews proposed trades and either approves, adjusts, or
vetoes them based on portfolio risk.

Based on TradingAgents ReAct framework:
- Thought → Action → Observation → Answer loop
- Structured JSON output for risk decisions
"""

RISK_MANAGER_SYSTEM_PROMPT = """You are the **Risk Manager** in the MERID multi-agent trading system.

## Your Role
You are the final gatekeeper before any trade is executed. Your job is to:
1. Enforce position limits and concentration rules
2. Monitor portfolio drawdown against limits
3. Assess volatility and adjust position sizing
4. Approve, adjust, or VETO proposed trades

You are CONSERVATIVE by nature. Your primary goal is CAPITAL PRESERVATION.

## Key Responsibilities
- Position sizing based on volatility and portfolio risk
- Drawdown limit enforcement (hard stop at max drawdown)
- Correlation analysis to avoid concentrated risk
- Liquidity assessment for trade execution
- Leverage monitoring and limits

## Risk Parameters to Enforce
- Max single position: 10% of portfolio
- Max sector exposure: 30% of portfolio
- Max drawdown: 20% (trigger review at 10%, hard stop at 20%)
- Min Sharpe threshold: 0.5 for new positions
- Leverage limit: 2x maximum

## ReAct Protocol
You MUST follow this format:

**Thought**: Assess the proposed trade against risk parameters
**Action**: Query risk metrics or portfolio state
**Observation**: Note the results
(Repeat as needed)
**Answer**: Provide your risk decision

## Available Tools
- `get_portfolio_risk()` - Current portfolio metrics (equity, drawdown, exposure)
- `get_position_limits(symbol)` - Check position limits for symbol
- `get_correlation_matrix()` - Asset correlations in portfolio
- `get_volatility(symbol)` - Current and historical volatility
- `check_liquidity(symbol, size)` - Liquidity assessment for trade size
- `get_agent_performance(agent_id)` - Performance metrics for proposing agent

## Output Format
Your final Answer MUST be valid JSON:
```json
{
  "decision": "approve" | "adjust" | "veto",
  "adjusted_size": null | number,
  "adjusted_leverage": null | number,
  "reasoning": "Clear explanation of decision",
  "risk_concerns": ["concern1", "concern2"],
  "conditions": ["condition1"],
  "risk_score": 1-10,
  "portfolio_impact": {
    "new_exposure": number,
    "new_drawdown_risk": number,
    "correlation_impact": "low" | "medium" | "high"
  }
}
```

## Decision Guidelines

### APPROVE when:
- Trade fits within all position limits
- Portfolio drawdown is healthy (< 10%)
- Proposing agent has good track record (Sharpe > 1)
- Adequate liquidity exists
- Low correlation with existing positions

### ADJUST when:
- Trade exceeds position limits → reduce size
- High volatility environment → reduce size by volatility ratio
- Moderate drawdown (10-15%) → reduce size by 50%
- High correlation with existing → reduce or hedge

### VETO when:
- Portfolio at max drawdown (> 20%)
- Trade would exceed sector concentration limit
- Proposing agent has poor track record (Sharpe < 0)
- Insufficient liquidity for safe execution
- Trade conflicts with active risk-off signals
"""

RISK_MANAGER_TRADE_REVIEW_TEMPLATE = """## Trade Review Request

### Proposed Trade
- **Symbol**: {symbol}
- **Direction**: {direction}
- **Size**: {size} ({size_pct:.1f}% of portfolio)
- **Proposed Entry**: ${entry_price:,.2f}
- **Proposing Agent**: {agent_id}
- **Consensus Score**: {consensus_score:.0%}

### Supporting Analysis
- **Bull Agents**: {bull_agents}
- **Bear Agents**: {bear_agents}
- **Rationale**: {rationale}

### Current Portfolio State
- **Total Equity**: ${total_equity:,.2f}
- **Current Drawdown**: {current_drawdown:.1%}
- **Max Drawdown Limit**: {max_drawdown_limit:.1%}
- **Open Positions**: {open_positions}
- **Current Exposure**: {current_exposure:.1%}

### Agent Performance (Proposer)
- **Sharpe Ratio**: {agent_sharpe:.2f}
- **Win Rate**: {agent_win_rate:.1%}
- **Max Drawdown**: {agent_max_drawdown:.1%}

### Market Conditions
- **Symbol Volatility**: {volatility:.2%} (daily)
- **Liquidity Score**: {liquidity_score}/10
- **Correlation with Portfolio**: {correlation:.2f}

---

Review this trade proposal. Follow the ReAct protocol:

Thought: [Initial risk assessment of this trade]
"""

RISK_MANAGER_PORTFOLIO_CHECK_TEMPLATE = """## Portfolio Risk Check

### Current State
- **Total Equity**: ${total_equity:,.2f}
- **Starting Equity**: ${starting_equity:,.2f}
- **Total P&L**: ${total_pnl:+,.2f} ({pnl_pct:+.1%})

### Drawdown Status
- **Peak Equity**: ${peak_equity:,.2f}
- **Current Drawdown**: {current_drawdown:.1%}
- **Max Allowed**: {max_drawdown_limit:.1%}
- **Drawdown Buffer**: {drawdown_buffer:.1%}

### Position Summary
{position_summary}

### Exposure Analysis
- **Long Exposure**: {long_exposure:.1%}
- **Short Exposure**: {short_exposure:.1%}
- **Net Exposure**: {net_exposure:.1%}
- **Gross Exposure**: {gross_exposure:.1%}

### Risk Metrics
- **Portfolio VaR (95%)**: ${var_95:,.2f}
- **Portfolio Sharpe**: {portfolio_sharpe:.2f}
- **Correlation Risk**: {correlation_risk}

---

Assess overall portfolio risk and provide recommendations:

Thought: [Assess current portfolio risk state]
"""

def build_risk_review_prompt(
    symbol: str,
    direction: str,
    size: float,
    size_pct: float,
    entry_price: float,
    agent_id: str,
    consensus_score: float,
    bull_agents: list,
    bear_agents: list,
    rationale: str,
    total_equity: float,
    current_drawdown: float,
    max_drawdown_limit: float = 0.20,
    open_positions: int = 0,
    current_exposure: float = 0.0,
    agent_sharpe: float = 0.0,
    agent_win_rate: float = 0.5,
    agent_max_drawdown: float = 0.0,
    volatility: float = 0.02,
    liquidity_score: int = 5,
    correlation: float = 0.0,
) -> dict:
    """
    Build complete prompt for Risk Manager trade review.
    
    Returns:
        dict with 'system' and 'user' prompt strings
    """
    user_prompt = RISK_MANAGER_TRADE_REVIEW_TEMPLATE.format(
        symbol=symbol,
        direction=direction,
        size=size,
        size_pct=size_pct,
        entry_price=entry_price,
        agent_id=agent_id,
        consensus_score=consensus_score,
        bull_agents=", ".join(bull_agents) if bull_agents else "None",
        bear_agents=", ".join(bear_agents) if bear_agents else "None",
        rationale=rationale,
        total_equity=total_equity,
        current_drawdown=current_drawdown,
        max_drawdown_limit=max_drawdown_limit,
        open_positions=open_positions,
        current_exposure=current_exposure,
        agent_sharpe=agent_sharpe,
        agent_win_rate=agent_win_rate,
        agent_max_drawdown=agent_max_drawdown,
        volatility=volatility,
        liquidity_score=liquidity_score,
        correlation=correlation,
    )
    
    return {
        "system": RISK_MANAGER_SYSTEM_PROMPT,
        "user": user_prompt,
    }


def build_portfolio_check_prompt(
    total_equity: float,
    starting_equity: float,
    total_pnl: float,
    pnl_pct: float,
    peak_equity: float,
    current_drawdown: float,
    max_drawdown_limit: float,
    drawdown_buffer: float,
    position_summary: str,
    long_exposure: float,
    short_exposure: float,
    net_exposure: float,
    gross_exposure: float,
    var_95: float,
    portfolio_sharpe: float,
    correlation_risk: str,
) -> dict:
    """
    Build prompt for portfolio-wide risk check.
    
    Returns:
        dict with 'system' and 'user' prompt strings
    """
    user_prompt = RISK_MANAGER_PORTFOLIO_CHECK_TEMPLATE.format(
        total_equity=total_equity,
        starting_equity=starting_equity,
        total_pnl=total_pnl,
        pnl_pct=pnl_pct,
        peak_equity=peak_equity,
        current_drawdown=current_drawdown,
        max_drawdown_limit=max_drawdown_limit,
        drawdown_buffer=drawdown_buffer,
        position_summary=position_summary,
        long_exposure=long_exposure,
        short_exposure=short_exposure,
        net_exposure=net_exposure,
        gross_exposure=gross_exposure,
        var_95=var_95,
        portfolio_sharpe=portfolio_sharpe,
        correlation_risk=correlation_risk,
    )
    
    return {
        "system": RISK_MANAGER_SYSTEM_PROMPT,
        "user": user_prompt,
    }


# Example usage
if __name__ == "__main__":
    prompt = build_risk_review_prompt(
        symbol="BTC",
        direction="LONG",
        size=0.5,
        size_pct=5.0,
        entry_price=71000.0,
        agent_id="bull-analyst-01",
        consensus_score=0.72,
        bull_agents=["bull-analyst-01", "technical-01"],
        bear_agents=["bear-analyst-01"],
        rationale="Strong support bounce with volume confirmation",
        total_equity=100000.0,
        current_drawdown=0.05,
        open_positions=3,
        current_exposure=0.35,
        agent_sharpe=1.2,
        agent_win_rate=0.58,
        agent_max_drawdown=0.08,
        volatility=0.025,
        liquidity_score=8,
        correlation=0.15,
    )
    print(prompt["system"][:500] + "...")
    print("\n---\n")
    print(prompt["user"])
