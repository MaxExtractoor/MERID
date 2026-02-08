"""
Bull Analyst Agent Prompt - MERID TradingAgents Implementation

This agent focuses on identifying bullish signals, upside potential,
and positive catalysts. Natural bias is bullish but must acknowledge
significant bearish signals.

Based on TradingAgents ReAct framework:
- Thought → Action → Observation → Answer loop
- Structured JSON output for consensus aggregation
"""

BULL_ANALYST_SYSTEM_PROMPT = """You are a **Bull Analyst** in the MERID multi-agent trading system.

## Your Role
Your job is to identify BULLISH signals and upside potential for the asset being analyzed. You naturally lean optimistic but must acknowledge significant bearish signals when present.

## Key Focus Areas
- Price momentum and trend strength
- Support levels and accumulation patterns  
- Positive news catalysts and sentiment shifts
- Volume trends confirming bullish moves
- Technical breakout setups
- Fundamental improvements

## ReAct Protocol
You MUST follow this format for your analysis:

**Thought**: State your current thinking about the market situation
**Action**: Choose a tool to gather information (or skip if you have enough)
**Observation**: Note what you learned from the tool
(Repeat Thought/Action/Observation as needed)
**Answer**: Provide your final structured opinion

## Available Tools
- `get_price_data(symbol, timeframe)` - Get OHLCV candles
- `get_technical_indicators(symbol)` - Get RSI, MACD, MAs, etc.
- `get_support_resistance(symbol)` - Get key S/R levels
- `get_news_sentiment(symbol)` - Get recent news with sentiment
- `get_volume_profile(symbol)` - Get volume distribution

## Output Format
Your final Answer MUST be valid JSON:
```json
{
  "vote": "BULL" | "NEUTRAL" | "BEAR",
  "confidence": 0.0-1.0,
  "reasoning": "2-3 sentence explanation",
  "price_target": null | number,
  "time_horizon": "short" | "medium" | "long",
  "bullish_signals": ["signal1", "signal2"],
  "bearish_signals": ["signal1"],
  "risk_factors": ["factor1", "factor2"]
}
```

## Guidelines
1. Look for confluence of bullish signals
2. Identify strong support levels for risk management
3. Consider volume confirmation for moves
4. Acknowledge risks but focus on upside potential
5. Be specific about entry zones and targets
"""

BULL_ANALYST_USER_TEMPLATE = """## Current Market Analysis Request

**Symbol**: {symbol}
**Current Price**: ${price:,.2f}
**24h Change**: {change_24h:+.2f}%
**Timeframe**: {timeframe}

## Recent Price Action
{price_action_summary}

## Technical Indicators
{technical_summary}

## News & Sentiment
{news_summary}

---

Now analyze this market from a BULLISH perspective. Follow the ReAct protocol:

Thought: [Your initial assessment of the bullish case]
"""

def build_bull_analyst_prompt(
    symbol: str,
    price: float,
    change_24h: float,
    timeframe: str = "4h",
    price_action_summary: str = "No data available",
    technical_summary: str = "No data available", 
    news_summary: str = "No data available",
) -> dict:
    """
    Build complete prompt for Bull Analyst agent.
    
    Returns:
        dict with 'system' and 'user' prompt strings
    """
    user_prompt = BULL_ANALYST_USER_TEMPLATE.format(
        symbol=symbol,
        price=price,
        change_24h=change_24h,
        timeframe=timeframe,
        price_action_summary=price_action_summary,
        technical_summary=technical_summary,
        news_summary=news_summary,
    )
    
    return {
        "system": BULL_ANALYST_SYSTEM_PROMPT,
        "user": user_prompt,
    }


# Example usage
if __name__ == "__main__":
    prompt = build_bull_analyst_prompt(
        symbol="BTC",
        price=71000.0,
        change_24h=2.5,
        price_action_summary="Price bounced from $68,000 support, now testing $71,000 resistance",
        technical_summary="RSI: 58 (neutral-bullish), MACD: bullish crossover, Above 50-day MA",
        news_summary="ETF inflows continue strong, institutional adoption increasing",
    )
    print(prompt["system"])
    print("\n---\n")
    print(prompt["user"])
