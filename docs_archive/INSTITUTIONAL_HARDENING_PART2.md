# MERID INSTITUTIONAL HARDENING IMPLEMENTATION - PART 2
## Risk Envelopes, Tool Architecture, and Custody Systems

---

# SECTION 3: HARD RISK ENVELOPES AND KILL-SWITCHES

## 3.1 Risk Envelope - UN-BYPASSABLE LAYER

```python
# core/risk_envelope.py

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time
from enum import Enum

class RiskViolationType(Enum):
    """Types of risk limit violations."""
    POSITION_SIZE = "position_size"
    LEVERAGE = "leverage"
    NOTIONAL = "notional"
    CONCENTRATION = "concentration"
    DRAWDOWN = "drawdown"
    FREQUENCY = "frequency"


@dataclass
class RiskLimit:
    """Individual risk limit definition."""
    limit_id: str
    limit_type: RiskViolationType
    threshold: float
    current_value: float = 0.0
    utilization_pct: float = 0.0
    
    def check_violation(self) -> bool:
        """Check if limit is violated."""
        return self.current_value > self.threshold
    
    def update_utilization(self) -> None:
        """Update utilization percentage."""
        if self.threshold > 0:
            self.utilization_pct = (self.current_value / self.threshold) * 100


@dataclass
class RiskEnvelope:
    """
    Hard risk envelope - CANNOT BE BYPASSED.
    
    All limits are deterministic checks that do NOT depend on AI models.
    """
    # Per-asset limits
    max_position_size_usd: float = 10_000.0  # $10k per asset
    max_position_pct: float = 0.10  # 10% of portfolio
    
    # Per-strategy limits
    max_strategy_exposure_usd: float = 25_000.0  # $25k per strategy
    
    # Portfolio-level limits
    max_gross_exposure_usd: float = 100_000.0  # $100k gross
    max_net_exposure_usd: float = 50_000.0  # $50k net
    max_leverage: float = 2.0  # 2x max leverage
    
    # Notional limits
    max_trade_notional_usd: float = 5_000.0  # $5k per trade
    max_hourly_notional_usd: float = 10_000.0  # $10k per hour
    max_daily_notional_usd: float = 20_000.0  # $20k per day
    
    # Drawdown limits
    max_intraday_drawdown_pct: float = 0.05  # 5% intraday
    max_weekly_drawdown_pct: float = 0.10  # 10% weekly
    max_monthly_drawdown_pct: float = 0.15  # 15% monthly
    
    # Frequency limits
    max_trades_per_hour: int = 20
    max_trades_per_day: int = 100
    
    # Current state (in-memory cache)
    current_positions: Dict[str, float] = field(default_factory=dict)
    current_strategy_exposure: Dict[str, float] = field(default_factory=dict)
    hourly_notional: List[tuple] = field(default_factory=list)  # (timestamp, notional)
    daily_notional: List[tuple] = field(default_factory=list)
    hourly_trades: List[float] = field(default_factory=list)  # timestamps
    daily_trades: List[float] = field(default_factory=list)
    
    # Portfolio metrics
    portfolio_value: float = 100_000.0
    starting_portfolio_value: float = 100_000.0
    peak_portfolio_value: float = 100_000.0
    daily_starting_value: float = 100_000.0
    weekly_starting_value: float = 100_000.0
    monthly_starting_value: float = 100_000.0


class RiskEnvelopeManager:
    """
    Manages risk envelope with deterministic checks.
    
    CRITICAL: All checks are code-based, not model-based.
    """
    
    def __init__(self):
        self.envelope = RiskEnvelope()
        self.violation_history: List[Dict] = []
        
        # Load from persistent storage
        self._load_state()
    
    async def check_proposal(
        self,
        proposal: TradeProposal
    ) -> Dict[str, Any]:
        """
        Check if proposal violates risk envelope.
        
        DETERMINISTIC: No AI model involvement.
        
        Returns:
            approved: bool
            violations: List[RiskViolation]
            reason: str
        """
        violations = []
        
        # Calculate proposal impact
        estimated_notional = proposal.size * (proposal.price_limit or await self._get_current_price(proposal.instrument))
        
        # Check 1: Per-trade notional limit
        if estimated_notional > self.envelope.max_trade_notional_usd:
            violations.append({
                "type": RiskViolationType.NOTIONAL,
                "limit": self.envelope.max_trade_notional_usd,
                "value": estimated_notional,
                "message": f"Trade notional ${estimated_notional:.2f} exceeds limit ${self.envelope.max_trade_notional_usd:.2f}"
            })
        
        # Check 2: Hourly notional limit
        current_time = time.time()
        hourly_total = self._calculate_window_notional(
            self.envelope.hourly_notional,
            current_time - 3600
        )
        if hourly_total + estimated_notional > self.envelope.max_hourly_notional_usd:
            violations.append({
                "type": RiskViolationType.NOTIONAL,
                "limit": self.envelope.max_hourly_notional_usd,
                "value": hourly_total + estimated_notional,
                "message": f"Hourly notional would exceed limit"
            })
        
        # Check 3: Daily notional limit
        daily_total = self._calculate_window_notional(
            self.envelope.daily_notional,
            current_time - 86400
        )
        if daily_total + estimated_notional > self.envelope.max_daily_notional_usd:
            violations.append({
                "type": RiskViolationType.NOTIONAL,
                "limit": self.envelope.max_daily_notional_usd,
                "value": daily_total + estimated_notional,
                "message": f"Daily notional would exceed limit"
            })
        
        # Check 4: Position size limit
        current_position = self.envelope.current_positions.get(proposal.instrument, 0.0)
        new_position = current_position + (proposal.size if proposal.side == "BUY" else -proposal.size)
        position_value = abs(new_position) * (proposal.price_limit or await self._get_current_price(proposal.instrument))
        
        if position_value > self.envelope.max_position_size_usd:
            violations.append({
                "type": RiskViolationType.POSITION_SIZE,
                "limit": self.envelope.max_position_size_usd,
                "value": position_value,
                "message": f"Position size ${position_value:.2f} exceeds limit"
            })
        
        # Check 5: Position concentration
        position_pct = position_value / self.envelope.portfolio_value
        if position_pct > self.envelope.max_position_pct:
            violations.append({
                "type": RiskViolationType.CONCENTRATION,
                "limit": self.envelope.max_position_pct,
                "value": position_pct,
                "message": f"Position concentration {position_pct:.1%} exceeds limit"
            })
        
        # Check 6: Strategy exposure
        strategy_exposure = self.envelope.current_strategy_exposure.get(proposal.strategy, 0.0)
        new_strategy_exposure = strategy_exposure + estimated_notional
        if new_strategy_exposure > self.envelope.max_strategy_exposure_usd:
            violations.append({
                "type": RiskViolationType.CONCENTRATION,
                "limit": self.envelope.max_strategy_exposure_usd,
                "value": new_strategy_exposure,
                "message": f"Strategy exposure would exceed limit"
            })
        
        # Check 7: Gross exposure
        gross_exposure = sum(abs(pos) for pos in self.envelope.current_positions.values())
        new_gross = gross_exposure + estimated_notional
        if new_gross > self.envelope.max_gross_exposure_usd:
            violations.append({
                "type": RiskViolationType.LEVERAGE,
                "limit": self.envelope.max_gross_exposure_usd,
                "value": new_gross,
                "message": f"Gross exposure would exceed limit"
            })
        
        # Check 8: Leverage
        leverage = gross_exposure / self.envelope.portfolio_value
        new_leverage = new_gross / self.envelope.portfolio_value
        if new_leverage > self.envelope.max_leverage:
            violations.append({
                "type": RiskViolationType.LEVERAGE,
                "limit": self.envelope.max_leverage,
                "value": new_leverage,
                "message": f"Leverage {new_leverage:.2f}x exceeds limit"
            })
        
        # Check 9: Trade frequency
        hourly_trade_count = len([t for t in self.envelope.hourly_trades if t > current_time - 3600])
        if hourly_trade_count >= self.envelope.max_trades_per_hour:
            violations.append({
                "type": RiskViolationType.FREQUENCY,
                "limit": self.envelope.max_trades_per_hour,
                "value": hourly_trade_count,
                "message": f"Hourly trade limit reached"
            })
        
        daily_trade_count = len([t for t in self.envelope.daily_trades if t > current_time - 86400])
        if daily_trade_count >= self.envelope.max_trades_per_day:
            violations.append({
                "type": RiskViolationType.FREQUENCY,
                "limit": self.envelope.max_trades_per_day,
                "value": daily_trade_count,
                "message": f"Daily trade limit reached"
            })
        
        # Check 10: Drawdown limits
        drawdown_violations = self._check_drawdown_limits()
        violations.extend(drawdown_violations)
        
        # Record violations
        if violations:
            self.violation_history.append({
                "timestamp": current_time,
                "proposal_id": proposal.proposal_id,
                "violations": violations
            })
        
        return {
            "approved": len(violations) == 0,
            "violations": violations,
            "reason": violations[0]["message"] if violations else "All checks passed"
        }
    
    def _check_drawdown_limits(self) -> List[Dict]:
        """Check drawdown limits."""
        violations = []
        current_value = self.envelope.portfolio_value
        
        # Intraday drawdown
        intraday_dd = (self.envelope.daily_starting_value - current_value) / self.envelope.daily_starting_value
        if intraday_dd > self.envelope.max_intraday_drawdown_pct:
            violations.append({
                "type": RiskViolationType.DRAWDOWN,
                "limit": self.envelope.max_intraday_drawdown_pct,
                "value": intraday_dd,
                "message": f"Intraday drawdown {intraday_dd:.1%} exceeds limit"
            })
        
        # Weekly drawdown
        weekly_dd = (self.envelope.weekly_starting_value - current_value) / self.envelope.weekly_starting_value
        if weekly_dd > self.envelope.max_weekly_drawdown_pct:
            violations.append({
                "type": RiskViolationType.DRAWDOWN,
                "limit": self.envelope.max_weekly_drawdown_pct,
                "value": weekly_dd,
                "message": f"Weekly drawdown {weekly_dd:.1%} exceeds limit"
            })
        
        # Monthly drawdown
        monthly_dd = (self.envelope.monthly_starting_value - current_value) / self.envelope.monthly_starting_value
        if monthly_dd > self.envelope.max_monthly_drawdown_pct:
            violations.append({
                "type": RiskViolationType.DRAWDOWN,
                "limit": self.envelope.max_monthly_drawdown_pct,
                "value": monthly_dd,
                "message": f"Monthly drawdown {monthly_dd:.1%} exceeds limit"
            })
        
        return violations
    
    async def update_position(
        self,
        proposal: TradeProposal,
        execution_result: Dict[str, Any]
    ) -> None:
        """Update risk state after execution."""
        current_time = time.time()
        
        # Update position
        current_position = self.envelope.current_positions.get(proposal.instrument, 0.0)
        filled_size = execution_result.get("filled_size", 0.0)
        
        if proposal.side == "BUY":
            self.envelope.current_positions[proposal.instrument] = current_position + filled_size
        else:
            self.envelope.current_positions[proposal.instrument] = current_position - filled_size
        
        # Update strategy exposure
        notional = filled_size * execution_result.get("avg_price", 0.0)
        current_strategy = self.envelope.current_strategy_exposure.get(proposal.strategy, 0.0)
        self.envelope.current_strategy_exposure[proposal.strategy] = current_strategy + notional
        
        # Update notional tracking
        self.envelope.hourly_notional.append((current_time, notional))
        self.envelope.daily_notional.append((current_time, notional))
        
        # Update trade frequency tracking
        self.envelope.hourly_trades.append(current_time)
        self.envelope.daily_trades.append(current_time)
        
        # Clean old entries
        self._cleanup_old_entries()
        
        # Persist state
        await self._persist_state()
    
    def _calculate_window_notional(
        self,
        notional_list: List[tuple],
        cutoff_time: float
    ) -> float:
        """Calculate total notional in time window."""
        return sum(notional for timestamp, notional in notional_list if timestamp > cutoff_time)
    
    def _cleanup_old_entries(self) -> None:
        """Remove entries outside tracking windows."""
        current_time = time.time()
        
        # Keep only last 24 hours
        self.envelope.hourly_notional = [
            (ts, n) for ts, n in self.envelope.hourly_notional
            if ts > current_time - 86400
        ]
        self.envelope.daily_notional = [
            (ts, n) for ts, n in self.envelope.daily_notional
            if ts > current_time - 86400
        ]
        self.envelope.hourly_trades = [
            ts for ts in self.envelope.hourly_trades
            if ts > current_time - 86400
        ]
        self.envelope.daily_trades = [
            ts for ts in self.envelope.daily_trades
            if ts > current_time - 86400
        ]
    
    async def _get_current_price(self, instrument: str) -> float:
        """Get current market price for instrument."""
        from trading.market_data import get_market_data_manager
        md = get_market_data_manager()
        return await md.get_current_price(instrument)
    
    def _load_state(self) -> None:
        """Load risk state from persistent storage."""
        # Implementation: Load from database
        pass
    
    async def _persist_state(self) -> None:
        """Persist risk state to storage."""
        # Implementation: Save to database
        pass


# Singleton
_risk_envelope_manager = None

def get_risk_envelope() -> RiskEnvelopeManager:
    global _risk_envelope_manager
    if _risk_envelope_manager is None:
        _risk_envelope_manager = RiskEnvelopeManager()
    return _risk_envelope_manager
```

## 3.2 Circuit Breakers

```python
# core/circuit_breakers.py

from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Callable
import time

class CircuitBreakerType(Enum):
    """Types of circuit breakers."""
    DRAWDOWN = "drawdown"
    ERROR_RATE = "error_rate"
    SLIPPAGE = "slippage"
    LATENCY = "latency"
    ENTROPY = "entropy"


@dataclass
class CircuitBreaker:
    """Individual circuit breaker definition."""
    breaker_id: str
    breaker_type: CircuitBreakerType
    threshold: float
    window_seconds: int
    action: str  # "halt_trading", "reduce_size", "alert_only"
    
    # State
    triggered: bool = False
    trigger_time: Optional[float] = None
    trigger_reason: Optional[str] = None


class CircuitBreakerManager:
    """
    Manages circuit breakers for system protection.
    """
    
    def __init__(self):
        self.breakers: Dict[str, CircuitBreaker] = {}
        self.trigger_handlers: Dict[str, Callable] = {}
        
        # Initialize standard breakers
        self._initialize_breakers()
    
    def _initialize_breakers(self) -> None:
        """Initialize standard circuit breakers."""
        
        # Drawdown breaker
        self.breakers["intraday_drawdown"] = CircuitBreaker(
            breaker_id="intraday_drawdown",
            breaker_type=CircuitBreakerType.DRAWDOWN,
            threshold=0.05,  # 5%
            window_seconds=86400,  # 1 day
            action="halt_trading"
        )
        
        # Error rate breaker
        self.breakers["execution_error_rate"] = CircuitBreaker(
            breaker_id="execution_error_rate",
            breaker_type=CircuitBreakerType.ERROR_RATE,
            threshold=0.20,  # 20%
            window_seconds=3600,  # 1 hour
            action="halt_trading"
        )
        
        # Slippage breaker
        self.breakers["abnormal_slippage"] = CircuitBreaker(
            breaker_id="abnormal_slippage",
            breaker_type=CircuitBreakerType.SLIPPAGE,
            threshold=2.0,  # 2x expected
            window_seconds=1800,  # 30 minutes
            action="reduce_size"
        )
        
        # Latency breaker
        self.breakers["data_latency"] = CircuitBreaker(
            breaker_id="data_latency",
            breaker_type=CircuitBreakerType.LATENCY,
            threshold=1000.0,  # 1000ms
            window_seconds=300,  # 5 minutes
            action="halt_trading"
        )
        
        # Entropy breaker (blindness mode)
        self.breakers["regime_entropy"] = CircuitBreaker(
            breaker_id="regime_entropy",
            breaker_type=CircuitBreakerType.ENTROPY,
            threshold=0.7,  # 70% of max entropy
            window_seconds=60,  # 1 minute
            action="halt_trading"
        )
    
    async def check_breaker(
        self,
        breaker_id: str,
        current_value: float
    ) -> Dict[str, Any]:
        """
        Check if circuit breaker should trigger.
        
        Returns:
            triggered: bool
            action: str
            reason: str
        """
        breaker = self.breakers.get(breaker_id)
        if not breaker:
            return {"triggered": False}
        
        # Check threshold
        if current_value > breaker.threshold:
            # Trigger breaker
            breaker.triggered = True
            breaker.trigger_time = time.time()
            breaker.trigger_reason = f"{breaker.breaker_type.value} exceeded threshold: {current_value:.4f} > {breaker.threshold:.4f}"
            
            # Execute action
            await self._execute_breaker_action(breaker)
            
            return {
                "triggered": True,
                "action": breaker.action,
                "reason": breaker.trigger_reason
            }
        
        return {"triggered": False}
    
    async def _execute_breaker_action(
        self,
        breaker: CircuitBreaker
    ) -> None:
        """Execute circuit breaker action."""
        if breaker.action == "halt_trading":
            # Activate kill switch
            from core.execution_controller import get_execution_controller
            controller = get_execution_controller()
            controller.activate_kill_switch(
                f"Circuit breaker triggered: {breaker.breaker_id}"
            )
        
        elif breaker.action == "reduce_size":
            # Reduce position sizes by 50%
            from core.risk_envelope import get_risk_envelope
            risk_envelope = get_risk_envelope()
            risk_envelope.envelope.max_trade_notional_usd *= 0.5
        
        # Always send alert
        from core.alerting import get_alert_manager
        alert_manager = get_alert_manager()
        await alert_manager.send_critical_alert(
            title=f"Circuit Breaker Triggered: {breaker.breaker_id}",
            message=breaker.trigger_reason,
            action=breaker.action
        )
    
    def reset_breaker(
        self,
        breaker_id: str,
        operator_id: str,
        justification: str
    ) -> None:
        """Reset circuit breaker - requires operator approval."""
        breaker = self.breakers.get(breaker_id)
        if not breaker:
            return
        
        breaker.triggered = False
        breaker.trigger_time = None
        breaker.trigger_reason = None
        
        # Log reset
        from core.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()
        audit_logger.log_breaker_reset(
            breaker_id,
            operator_id,
            justification
        )


# Singleton
_circuit_breaker_manager = None

def get_circuit_breaker_manager() -> CircuitBreakerManager:
    global _circuit_breaker_manager
    if _circuit_breaker_manager is None:
        _circuit_breaker_manager = CircuitBreakerManager()
    return _circuit_breaker_manager
```

---

# SECTION 4: TOOL-FIRST AGENT ARCHITECTURE

## 4.1 Tool Schema Definitions

```python
# agents/tools/schemas.py

from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional
from enum import Enum

class ToolCategory(Enum):
    """Categories of tools available to agents."""
    MARKET_DATA = "market_data"
    ANALYSIS = "analysis"
    PROPOSAL = "proposal"
    RISK = "risk"
    SIMULATION = "simulation"


class MarketDataRequest(BaseModel):
    """Request market data."""
    instruments: List[str] = Field(..., description="List of instrument addresses")
    data_types: List[str] = Field(..., description="Types: price, volume, orderbook, trades")
    timeframe: Optional[str] = Field(None, description="Timeframe: 1m, 5m, 1h, 1d")
    
    @validator("instruments")
    def validate_instruments(cls, v):
        if len(v) == 0:
            raise ValueError("At least one instrument required")
        if len(v) > 10:
            raise ValueError("Maximum 10 instruments per request")
        return v


class MarketDataResponse(BaseModel):
    """Market data response."""
    success: bool
    data: Dict[str, Any]
    timestamp: float
    latency_ms: float


class AnalysisRequest(BaseModel):
    """Request technical/fundamental analysis."""
    instrument: str
    analysis_types: List[str] = Field(..., description="Types: technical, sentiment, onchain")
    lookback_periods: Optional[int] = Field(None, description="Number of periods to analyze")


class AnalysisResponse(BaseModel):
    """Analysis response."""
    success: bool
    instrument: str
    analysis: Dict[str, Any]
    confidence: float = Field(..., ge=0.0, le=1.0)
    supporting_evidence: List[str]
    timestamp: float


class ProposalRequest(BaseModel):
    """Submit trade proposal."""
    instrument: str = Field(..., description="Instrument contract address")
    side: str = Field(..., description="BUY or SELL")
    size: float = Field(..., gt=0, description="Position size")
    venue: str = Field(..., description="Execution venue")
    strategy: str = Field(..., description="Strategy identifier")
    reasoning: str = Field(..., min_length=50, description="Detailed reasoning")
    confidence: float = Field(..., ge=0.0, le=1.0)
    supporting_features: Dict[str, Any] = Field(default_factory=dict)
    
    @validator("side")
    def validate_side(cls, v):
        if v not in ["BUY", "SELL"]:
            raise ValueError("Side must be BUY or SELL")
        return v
    
    @validator("reasoning")
    def validate_reasoning(cls, v):
        if len(v) < 50:
            raise ValueError("Reasoning must be at least 50 characters")
        return v


class ProposalResponse(BaseModel):
    """Proposal submission response."""
    accepted: bool
    proposal_id: Optional[str]
    status: str
    reason: str
    violations: List[Dict[str, Any]] = Field(default_factory=list)


class RiskCheckRequest(BaseModel):
    """Request risk check."""
    proposal_id: str
    check_types: List[str] = Field(..., description="Types: limits, concentration, correlation")


class RiskCheckResponse(BaseModel):
    """Risk check response."""
    approved: bool
    violations: List[Dict[str, Any]]
    risk_metrics: Dict[str, float]
    reason: str


class SimulationRequest(BaseModel):
    """Request trade simulation."""
    instrument: str
    side: str
    size: float
    venue: str
    market_conditions: Optional[Dict[str, Any]] = None


class SimulationResponse(BaseModel):
    """Simulation response."""
    success: bool
    expected_price: float
    expected_slippage: float
    expected_fees: float
    liquidity_score: float
    warnings: List[str]
```

## 4.2 Tool Registry with Access Control

```python
# agents/tools/registry.py

from typing import Dict, List, Callable, Optional
from enum import Enum

class AgentRole(Enum):
    """Agent roles with different tool access."""
    ANALYST = "analyst"
    RISK = "risk"
    SKEPTIC = "skeptic"
    EXECUTION = "execution"
    GOVERNANCE = "governance"


class Tool:
    """Tool definition with access control."""
    
    def __init__(
        self,
        tool_id: str,
        name: str,
        description: str,
        category: ToolCategory,
        handler: Callable,
        allowed_roles: List[AgentRole],
        rate_limit: Optional[int] = None
    ):
        self.tool_id = tool_id
        self.name = name
        self.description = description
        self.category = category
        self.handler = handler
        self.allowed_roles = allowed_roles
        self.rate_limit = rate_limit  # calls per minute
        
        # Usage tracking
        self.call_count = 0
        self.last_call_times: List[float] = []


class ToolRegistry:
    """
    Central registry of tools with access control.
    
    CRITICAL: Enforces which agents can call which tools.
    """
    
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self._register_standard_tools()
    
    def _register_standard_tools(self) -> None:
        """Register standard tools."""
        
        # Market data tools (all agents)
        self.register_tool(Tool(
            tool_id="get_market_data",
            name="Get Market Data",
            description="Retrieve current market data for instruments",
            category=ToolCategory.MARKET_DATA,
            handler=self._handle_market_data,
            allowed_roles=[
                AgentRole.ANALYST,
                AgentRole.RISK,
                AgentRole.SKEPTIC,
                AgentRole.EXECUTION
            ],
            rate_limit=60  # 60 calls per minute
        ))
        
        # Analysis tools (analyst, skeptic)
        self.register_tool(Tool(
            tool_id="run_analysis",
            name="Run Analysis",
            description="Perform technical/fundamental analysis",
            category=ToolCategory.ANALYSIS,
            handler=self._handle_analysis,
            allowed_roles=[
                AgentRole.ANALYST,
                AgentRole.SKEPTIC
            ],
            rate_limit=30
        ))
        
        # Proposal tools (analyst only)
        self.register_tool(Tool(
            tool_id="submit_proposal",
            name="Submit Trade Proposal",
            description="Submit trade proposal for review",
            category=ToolCategory.PROPOSAL,
            handler=self._handle_proposal,
            allowed_roles=[
                AgentRole.ANALYST
            ],
            rate_limit=10
        ))
        
        # Risk tools (risk agent only)
        self.register_tool(Tool(
            tool_id="check_risk",
            name="Check Risk",
            description="Perform risk checks on proposal",
            category=ToolCategory.RISK,
            handler=self._handle_risk_check,
            allowed_roles=[
                AgentRole.RISK
            ],
            rate_limit=30
        ))
        
        # Simulation tools (analyst, risk)
        self.register_tool(Tool(
            tool_id="simulate_trade",
            name="Simulate Trade",
            description="Simulate trade execution",
            category=ToolCategory.SIMULATION,
            handler=self._handle_simulation,
            allowed_roles=[
                AgentRole.ANALYST,
                AgentRole.RISK
            ],
            rate_limit=20
        ))
        
        # NO EXECUTION TOOLS FOR NON-EXECUTION AGENTS
        # Execution is ONLY through ExecutionController
    
    def register_tool(self, tool: Tool) -> None:
        """Register a tool."""
        self.tools[tool.tool_id] = tool
    
    async def call_tool(
        self,
        tool_id: str,
        agent_role: AgentRole,
        agent_id: str,
        request: BaseModel
    ) -> BaseModel:
        """
        Call tool with access control and rate limiting.
        
        ENFORCES:
        - Role-based access control
        - Rate limiting
        - Input validation
        - Audit logging
        """
        tool = self.tools.get(tool_id)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_id}")
        
        # Check access control
        if agent_role not in tool.allowed_roles:
            raise PermissionError(
                f"Agent role {agent_role.value} not allowed to call {tool_id}"
            )
        
        # Check rate limit
        if tool.rate_limit:
            current_time = time.time()
            recent_calls = [
                t for t in tool.last_call_times
                if t > current_time - 60
            ]
            
            if len(recent_calls) >= tool.rate_limit:
                raise RateLimitError(
                    f"Rate limit exceeded for {tool_id}: {tool.rate_limit}/min"
                )
            
            tool.last_call_times.append(current_time)
        
        # Validate request
        if not isinstance(request, BaseModel):
            raise ValueError("Request must be Pydantic model")
        
        # Log tool call
        from core.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()
        await audit_logger.log_tool_call(
            tool_id=tool_id,
            agent_id=agent_id,
            agent_role=agent_role.value,
            request=request.dict()
        )
        
        # Execute tool
        try:
            response = await tool.handler(request)
            tool.call_count += 1
            return response
        except Exception as e:
            # Log error
            await audit_logger.log_tool_error(
                tool_id=tool_id,
                agent_id=agent_id,
                error=str(e)
            )
            raise
    
    async def _handle_market_data(
        self,
        request: MarketDataRequest
    ) -> MarketDataResponse:
        """Handle market data request."""
        from trading.market_data import get_market_data_manager
        md = get_market_data_manager()
        
        start_time = time.time()
        data = await md.get_data(
            instruments=request.instruments,
            data_types=request.data_types,
            timeframe=request.timeframe
        )
        latency = (time.time() - start_time) * 1000
        
        return MarketDataResponse(
            success=True,
            data=data,
            timestamp=time.time(),
            latency_ms=latency
        )
    
    async def _handle_analysis(
        self,
        request: AnalysisRequest
    ) -> AnalysisResponse:
        """Handle analysis request."""
        from analysis.engine import get_analysis_engine
        engine = get_analysis_engine()
        
        result = await engine.analyze(
            instrument=request.instrument,
            analysis_types=request.analysis_types,
            lookback_periods=request.lookback_periods
        )
        
        return AnalysisResponse(
            success=True,
            instrument=request.instrument,
            analysis=result["analysis"],
            confidence=result["confidence"],
            supporting_evidence=result["evidence"],
            timestamp=time.time()
        )
    
    async def _handle_proposal(
        self,
        request: ProposalRequest
    ) -> ProposalResponse:
        """Handle proposal submission."""
        from core.execution_controller import get_execution_controller
        from core.explainability import create_reasoning_record
        
        # Create reasoning record
        reasoning_id = await create_reasoning_record(
            agent_id=request.instrument,  # Will be set by caller
            decision_type="TRADE",
            reasoning=request.reasoning,
            confidence=request.confidence,
            supporting_features=request.supporting_features
        )
        
        # Create proposal
        proposal = TradeProposal(
            proposal_id=str(uuid.uuid4()),
            created_at=time.time(),
            created_by="analyst_agent",  # Will be set by caller
            instrument=request.instrument,
            side=request.side,
            size=request.size,
            venue=request.venue,
            strategy=request.strategy,
            reasoning_link=reasoning_id,
            confidence=request.confidence,
            supporting_features=request.supporting_features
        )
        
        # Submit to execution controller
        controller = get_execution_controller()
        result = await controller.submit_proposal(proposal)
        
        return ProposalResponse(
            accepted=result["accepted"],
            proposal_id=result.get("proposal_id"),
            status=result.get("status", "rejected"),
            reason=result.get("reason", ""),
            violations=result.get("violations", [])
        )
    
    async def _handle_risk_check(
        self,
        request: RiskCheckRequest
    ) -> RiskCheckResponse:
        """Handle risk check request."""
        from core.risk_envelope import get_risk_envelope
        risk_envelope = get_risk_envelope()
        
        # Get proposal
        from core.execution_controller import get_execution_controller
        controller = get_execution_controller()
        proposal = controller.proposals.get(request.proposal_id)
        
        if not proposal:
            return RiskCheckResponse(
                approved=False,
                violations=[],
                risk_metrics={},
                reason="Proposal not found"
            )
        
        # Check risk
        result = await risk_envelope.check_proposal(proposal)
        
        return RiskCheckResponse(
            approved=result["approved"],
            violations=result["violations"],
            risk_metrics={},  # Add metrics
            reason=result["reason"]
        )
    
    async def _handle_simulation(
        self,
        request: SimulationRequest
    ) -> SimulationResponse:
        """Handle simulation request."""
        from core.simulation_engine import get_simulation_engine
        simulator = get_simulation_engine()
        
        result = await simulator.simulate_trade_simple(
            instrument=request.instrument,
            side=request.side,
            size=request.size,
            venue=request.venue
        )
        
        return SimulationResponse(
            success=result["success"],
            expected_price=result["expected_price"],
            expected_slippage=result["expected_slippage"],
            expected_fees=result["expected_fees"],
            liquidity_score=result["liquidity_score"],
            warnings=result.get("warnings", [])
        )


# Singleton
_tool_registry = None

def get_tool_registry() -> ToolRegistry:
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
    return _tool_registry
```

---

*[Document continues with Sections 5-10 covering Wallet/Custody, Observability, Progressive Rollout, Testing, Compliance, and Module Implementations]*

**[IMPLEMENTATION CONTINUES]**
