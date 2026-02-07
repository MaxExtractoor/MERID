"""MERID Structured LLM Outputs using Instructor.

Type-safe LLM responses for trading signals, risk assessments,
and agent decisions with automatic validation.
"""

from typing import Literal, Optional, List
from pydantic import BaseModel, Field, field_validator
from enum import Enum
import instructor
from openai import OpenAI
import os
import structlog

logger = structlog.get_logger(__name__)


class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConfidenceLevel(str, Enum):
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


# ========== Structured Output Models ==========

class TradeSignal(BaseModel):
    """Structured trade signal from LLM analysis."""
    
    symbol: str = Field(..., description="Trading symbol (e.g., AAPL, BTC-USD)")
    side: TradeSide = Field(..., description="Trade direction")
    quantity: float = Field(..., gt=0, description="Position size")
    price: Optional[float] = Field(None, ge=0, description="Target price if limit order")
    confidence: float = Field(..., ge=0, le=1, description="Confidence score 0-1")
    confidence_level: ConfidenceLevel = Field(..., description="Qualitative confidence")
    reasoning: str = Field(..., min_length=10, description="Detailed analysis reasoning")
    strategy: str = Field(..., description="Strategy name (momentum, mean_reversion, etc.)")
    timeframe: str = Field(default="1d", description="Analysis timeframe")
    
    @field_validator('symbol')
    @classmethod
    def validate_symbol(cls, v):
        if not v or len(v) < 1:
            raise ValueError('Symbol must not be empty')
        return v.upper()
    
    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "AAPL",
                "side": "buy",
                "quantity": 100.0,
                "confidence": 0.85,
                "confidence_level": "high",
                "reasoning": "Bullish breakout above resistance with volume confirmation",
                "strategy": "momentum",
                "timeframe": "1d"
            }
        }


class RiskAssessment(BaseModel):
    """Structured risk assessment for trade validation."""
    
    approved: bool = Field(..., description="Whether trade is approved")
    risk_score: float = Field(..., ge=0, le=1, description="Risk score 0-1")
    risk_level: RiskLevel = Field(..., description="Qualitative risk level")
    max_position_size: float = Field(..., gt=0, description="Maximum allowed position")
    var_95: Optional[float] = Field(None, ge=0, description="Value at Risk (95%)")
    cvar_95: Optional[float] = Field(None, ge=0, description="Conditional VaR (95%)")
    portfolio_heat: float = Field(..., ge=0, le=1, description="Current portfolio heat")
    correlation_risk: float = Field(..., ge=0, le=1, description="Correlation with existing positions")
    reasoning: str = Field(..., min_length=10, description="Detailed risk analysis")
    conditions: List[str] = Field(default=[], description="Approval conditions if any")
    
    @field_validator('conditions')
    @classmethod
    def validate_conditions(cls, v, values):
        if not values.get('approved') and not v:
            return ["Review required: High risk detected"]
        return v


class MarketAnalysis(BaseModel):
    """Structured market analysis output."""
    
    trend: Literal["bullish", "bearish", "neutral", "volatile"] = Field(...)
    trend_strength: float = Field(..., ge=0, le=1)
    support_levels: List[float] = Field(default=[], description="Key support price levels")
    resistance_levels: List[float] = Field(default=[], description="Key resistance price levels")
    volatility_regime: Literal["low", "normal", "high", "extreme"] = Field(...)
    volume_analysis: str = Field(..., description="Volume trend analysis")
    key_events: List[str] = Field(default=[], description="Upcoming events that may impact price")
    recommendation: str = Field(..., description="Overall trading recommendation")


class AgentDecision(BaseModel):
    """Structured decision from a swarm agent."""
    
    agent_name: str = Field(..., description="Name of the deciding agent")
    decision: Literal["approve", "reject", "hold", "escalate"] = Field(...)
    confidence: float = Field(..., ge=0, le=1)
    reasoning: str = Field(..., min_length=10)
    action_items: List[str] = Field(default=[])
    estimated_impact: Optional[str] = Field(None, description="Expected impact of decision")


# ========== LLM Client with Instructor ==========

class StructuredLLMClient:
    """LLM client with structured output support via Instructor."""
    
    def __init__(self, api_key: str = None, base_url: str = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url or "https://api.deepseek.com"
        self.model = model
        self.logger = logger.bind(component="StructuredLLMClient")
        
        # Initialize OpenAI client with Instructor patch
        self.client = instructor.from_openai(
            OpenAI(api_key=self.api_key, base_url=self.base_url)
        )
    
    def generate_trade_signal(
        self,
        symbol: str,
        market_data: dict,
        strategy: str = "momentum"
    ) -> TradeSignal:
        """Generate a structured trade signal from market analysis."""
        
        self.logger.info("generating_trade_signal", symbol=symbol, strategy=strategy)
        
        prompt = f"""Analyze {symbol} and generate a trade signal based on:

Market Data: {market_data}
Strategy: {strategy}

Provide a detailed trade signal with confidence score and clear reasoning.
Consider technical indicators, sentiment, and market regime.
"""
        
        signal = self.client.chat.completions.create(
            model=self.model,
            response_model=TradeSignal,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert quantitative trading analyst. Generate precise trade signals with detailed reasoning."
                },
                {"role": "user", "content": prompt}
            ],
            max_retries=3
        )
        
        self.logger.info(
            "trade_signal_generated",
            symbol=signal.symbol,
            side=signal.side,
            confidence=signal.confidence
        )
        
        return signal
    
    def assess_trade_risk(
        self,
        trade_signal: TradeSignal,
        portfolio_context: dict
    ) -> RiskAssessment:
        """Assess risk for a proposed trade."""
        
        self.logger.info(
            "assessing_trade_risk",
            symbol=trade_signal.symbol,
            quantity=trade_signal.quantity
        )
        
        prompt = f"""Assess the risk for the following trade:

Trade: {trade_signal.model_dump_json()}
Portfolio Context: {portfolio_context}

Risk Rules:
- Max 2% risk per trade
- Portfolio heat must stay below 20%
- Check correlation with existing positions
- Consider market volatility regime

Provide a detailed risk assessment with specific metrics.
"""
        
        assessment = self.client.chat.completions.create(
            model=self.model,
            response_model=RiskAssessment,
            messages=[
                {
                    "role": "system",
                    "content": "You are a conservative risk manager focused on capital preservation. Enforce strict risk limits."
                },
                {"role": "user", "content": prompt}
            ],
            max_retries=3
        )
        
        self.logger.info(
            "risk_assessment_complete",
            approved=assessment.approved,
            risk_score=assessment.risk_score,
            risk_level=assessment.risk_level
        )
        
        return assessment
    
    def analyze_market_conditions(
        self,
        symbol: str,
        price_data: list,
        volume_data: list
    ) -> MarketAnalysis:
        """Generate structured market analysis."""
        
        self.logger.info("analyzing_market", symbol=symbol)
        
        prompt = f"""Analyze market conditions for {symbol}:

Price Data (last 20 periods): {price_data}
Volume Data: {volume_data}

Identify trend, support/resistance levels, volatility regime, and volume patterns.
Provide actionable trading insights.
"""
        
        analysis = self.client.chat.completions.create(
            model=self.model,
            response_model=MarketAnalysis,
            messages=[
                {
                    "role": "system",
                    "content": "You are a technical analysis expert. Identify key market levels and trends."
                },
                {"role": "user", "content": prompt}
            ],
            max_retries=2
        )
        
        return analysis
    
    def get_agent_decision(
        self,
        agent_name: str,
        context: dict,
        decision_type: str = "trade_approval"
    ) -> AgentDecision:
        """Get a structured decision from a swarm agent."""
        
        prompt = f"""As {agent_name}, make a decision on:

Context: {context}
Decision Type: {decision_type}

Provide clear decision with reasoning and action items.
"""
        
        decision = self.client.chat.completions.create(
            model=self.model,
            response_model=AgentDecision,
            messages=[
                {
                    "role": "system",
                    "content": f"You are {agent_name} in a trading swarm. Make data-driven decisions."
                },
                {"role": "user", "content": prompt}
            ],
            max_retries=2
        )
        
        return decision


# ========== Prompt Versioning & Management ==========

class PromptVersion:
    """Version control for prompts."""
    
    def __init__(self, name: str, version: str, template: str, metadata: dict = None):
        self.name = name
        self.version = version
        self.template = template
        self.metadata = metadata or {}
    
    def render(self, **kwargs) -> str:
        """Render prompt with variables."""
        return self.template.format(**kwargs)


class PromptRegistry:
    """Registry for versioned prompts."""
    
    def __init__(self):
        self.prompts: dict[str, PromptVersion] = {}
        self.logger = logger.bind(component="PromptRegistry")
    
    def register(self, prompt: PromptVersion):
        """Register a prompt version."""
        key = f"{prompt.name}@{prompt.version}"
        self.prompts[key] = prompt
        self.logger.info("prompt_registered", name=prompt.name, version=prompt.version)
    
    def get(self, name: str, version: str = "latest") -> Optional[PromptVersion]:
        """Get a prompt by name and version."""
        if version == "latest":
            # Find highest version
            versions = [k for k in self.prompts.keys() if k.startswith(f"{name}@")]
            if versions:
                return self.prompts[sorted(versions)[-1]]
            return None
        
        key = f"{name}@{version}"
        return self.prompts.get(key)


# Pre-defined MERID prompts
MERID_PROMPTS = {
    "trade_signal_v1": PromptVersion(
        name="trade_signal",
        version="1.0.0",
        template="""Analyze {symbol} for a {strategy} strategy.

Market Context:
- Current Price: ${current_price}
- Volume: {volume}
- Trend: {trend}

Generate a trade signal with detailed reasoning and confidence assessment.
""",
        metadata={"author": "MERID Team", "tested": True, "accuracy": 0.87}
    ),
    
    "risk_assessment_v1": PromptVersion(
        name="risk_assessment",
        version="1.0.0",
        template="""Assess risk for {symbol} position of {quantity} units.

Portfolio State:
- Current Exposure: {current_exposure}%
- Cash Available: ${cash}
- Open Positions: {open_positions}

Apply MERID risk rules and provide detailed assessment.
""",
        metadata={"author": "Risk Team", "tested": True}
    )
}


# Initialize global registry
prompt_registry = PromptRegistry()
for prompt in MERID_PROMPTS.values():
    prompt_registry.register(prompt)
