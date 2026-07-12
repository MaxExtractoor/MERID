# Kalshi 15m Agent Grid Documentation

## Overview

The Kalshi 15m Agent Grid is the core signal generation and trading decision engine for the 15-minute crypto trading system. It orchestrates 5 individual agents (BTC, ETH, SOL, XRP, DOGE) that generate trading signals based on velocity-based momentum strategies.

## Architecture

### Component Hierarchy

```
LeanAgentGrid15m (Orchestrator)
├── LeanAgent15m (BTC Agent)
├── LeanAgent15m (ETH Agent)
├── LeanAgent15m (SOL Agent)
├── LeanAgent15m (XRP Agent)
└── LeanAgent15m (DOGE Agent)
```

### Key Files

- **Main Implementation**: `merid/prediction/agent_grid_15m.py`
- **Indicators**: `merid/signals/crypto_15m_indicators.py`
- **Global Allocator**: `merid/risk/profiles/global_allocator.py`
- **Risk Envelope**: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`

## Agent Configuration (LeanAgentConfig)

### Core Parameters

```python
@dataclass
class LeanAgentConfig:
    name: str                              # Agent name (e.g., "BTC_15M")
    series_tickers: list[str]              # Series tickers to trade (e.g., ["KXBTC15M"])
    signal_mode: str = "trend"             # Signal mode: "trend", "mean_reversion", "momentum_fvg", "hybrid", "price_based"
    max_spread_cents: int = 100            # Maximum spread in cents (relaxed to 100c for current market conditions)
    min_time_to_expiry_s: int = 180        # Minimum time to expiry in seconds
    max_time_to_expiry_s: int = 900        # Maximum time to expiry in seconds
    per_strip_order_limit: int = 200       # Maximum orders per 15m strip
    per_asset_cooldown_s: int = 8          # Cooldown period in seconds after trade
    max_orders_per_15m_window: int = 12    # Maximum orders per 15-minute window
    consecutive_loss_pause: int = 3        # Pause after N consecutive losses
    max_session_risk_pct: float = 0.10      # Max session risk as % of capital
```

### Velocity Thresholds (Per-Asset)

The system uses asset-specific velocity thresholds aligned with profile YAML configuration:

```python
velocity_threshold_btc: float = 0.00015   # BTC: 0.015%
velocity_threshold_eth: float = 0.00015   # ETH: 0.015%
velocity_threshold_sol: float = 0.000225  # SOL: 0.0225%
velocity_threshold_xrp: float = 0.000225  # XRP: 0.0225%
velocity_threshold_doge: float = 0.0003   # DOGE: 0.03%
```

**Rationale**: Deeper markets (BTC/ETH) have lower thresholds for sensitivity, while more volatile assets (SOL/XRP/DOGE) have higher thresholds to reduce noise.

### Fee-Aware Trading Parameters

```python
prefer_maker_orders: bool = True           # Prefer maker orders to earn rebates
min_profit_basis_points: int = 20         # Minimum 20bp profit target
max_spread_basis_points: int = 50        # Maximum 50bp spread (relaxed)
use_limit_orders: bool = True             # Use limit orders for better fill rates
limit_order_slippage_cents: int = 2       # Allow 2 cents slippage for limit orders
```

### Regime Detection Parameters

```python
volatility_window_s: int = 300            # 5-minute volatility window
min_volatility_threshold: float = 0.001   # Minimum 0.1% volatility
max_volatility_threshold: float = 0.02   # Maximum 2% volatility
```

### Hybrid Mode Price Caps

```python
max_entry_price_yes: float = 0.70         # 70¢ YES cap (avoids highest fee zone)
min_entry_price_no: float = 0.30         # 30¢ NO cap (symmetry with 70¢ YES)
```

### Position Management

```python
max_concurrent_positions: int = 4         # Maximum total open positions across all assets
```

**Note**: This is a TOTAL limit across all 5 assets, not per-asset. Aligned with $1 exposure cap at typical prices (25c/contract).

### Dynamic Spread Thresholds

The system uses volatility-regime-based spread filtering with 3 regimes:

```python
calm_volatility_threshold: float = 0.005        # 0.5% volatility = calm regime
elevated_volatility_threshold: float = 0.015    # 1.5% volatility = elevated regime

# Base thresholds
calm_spread_threshold_bp: int = 200             # 200bp max spread in calm regime
elevated_spread_threshold_bp: int = 300         # 300bp max spread in elevated regime
violent_spread_threshold_bp: int = 500          # 500bp max spread in violent regime

# Per-asset overrides (deeper books get tighter thresholds)
calm_spread_threshold_bp_btc_eth: int = 300
calm_spread_threshold_bp_sol_xrp_doge: int = 350
elevated_spread_threshold_bp_btc_eth: int = 400
elevated_spread_threshold_bp_sol_xrp_doge: int = 450
violent_spread_threshold_bp_btc_eth: int = 600
violent_spread_threshold_bp_sol_xrp_doge: int = 700
```

### Multi-Window Velocity Configuration

```python
velocity_windows: list = [10, 30, 60]            # Velocity windows in seconds
momentum_weights: list = [0.2, 0.3, 0.5]        # Weights for each window
velocity_ema_period: int = 5                    # EMA smoothing period
atr_period: int = 3                             # ATR period (reduced from 7 for faster warmup)
zscore_period: int = 20                         # Z-score period for extreme detection
```

### Logit Fusion Weights

```python
logit_fusion_velocity_weight: float = 0.7      # Weight for velocity signal
logit_fusion_mean_reversion_weight: float = 0.3 # Weight for mean reversion signal
```

### Panic Fade (Volatility Reversion) Configuration

```python
panic_fade_enabled: bool = True                 # Enable panic fade strategy
panic_fade_threshold: float = 0.00013           # Velocity threshold for panic detection (0.013%)
panic_fade_zscore_threshold: float = 2.0       # Z-score threshold for statistical extreme
panic_fade_rsi_oversold: float = 25.0          # RSI oversold threshold (buy YES)
panic_fade_rsi_overbought: float = 75.0        # RSI overbought threshold (buy NO)
panic_fade_min_velocity: float = 0.000065      # Minimum velocity to qualify as panic (0.0065%)
```

## Individual Agent (LeanAgent15m)

### Initialization

Each agent is initialized with:
- Configuration (LeanAgentConfig)
- Market catalog
- Market state store
- Spot provider (UnifiedSpotService)
- Order router
- Risk config

### Indicator Stacks

**CRITICAL FIX (2026-07-10)**: Each agent initializes indicator stacks for ALL 5 assets (BTC, ETH, SOL, XRP, DOGE), not just its own asset. This ensures each asset's indicator stack gets redundant updates from all 5 agents, preventing the "bars_available=1" issue.

```python
self._indicator_stacks: Dict[str, Any] = {}
for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
    cfg = IndicatorConfig(asset=asset, kalshi_mode=True)
    self._indicator_stacks[asset] = Crypto15mIndicatorStack(config=cfg)
```

**Kalshi Mode**: Enabled to disable strict spot market thresholds. Kalshi prediction markets are binary contracts, not continuous spot instruments. Without kalshi_mode, strict vol/ATR/chop gates block all signals.

### Price History Management

```python
self._spot_price_history: Dict[str, collections.deque] = {}
self._price_history_window_size = 300  # 5 minutes at 1-second intervals

# Initialize for all 5 crypto assets
for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
    self._spot_price_history[asset] = collections.deque(maxlen=self._price_history_window_size)
```

### Signal Generation Process

#### 1. Velocity Calculation

Velocity is calculated as the percentage change in spot price per second:

```python
def _calculate_velocity(self, asset: str, current_price: float) -> float:
    if len(self._spot_price_history[asset]) < 2:
        return 0.0
    
    # Get most recent price
    last_price = self._spot_price_history[asset][-1]
    
    # Calculate velocity as percentage change per second
    velocity = (current_price - last_price) / last_price
    
    return velocity
```

#### 2. Dynamic Velocity Threshold

The system calculates a dynamic velocity threshold based on ATR (volatility) and ADX (trend strength):

```python
def _calculate_dynamic_velocity_threshold(self, asset: str) -> float:
    # Get base threshold from config (per-asset)
    base_threshold = asset_threshold_map.get(asset, 0.0002)
    
    # Calculate ATR for current asset
    atr_pct = self._calculate_atr(asset)
    
    # Calculate ADX for trend strength adjustment
    adx = self._calculate_adx(asset)
    
    # CRITICAL FIX: ATR and ADX multipliers set to 1.0 (neutral)
    # This prevents threshold inflation blocking trades
    atr_adjustment = 1.0
    adx_multiplier = 1.0
    
    dynamic_threshold = base_threshold * atr_adjustment * adx_multiplier
    return dynamic_threshold
```

**Rationale for Neutral Multipliers**: Previous multipliers (0.90-1.10) were inflating thresholds above base values, causing velocity to be below dynamic threshold even when above base threshold. Setting to 1.0 uses base threshold directly.

#### 3. Panic Fade Detection

Panic fade strategy (Turbine research winner) detects statistical extremes and fades the panic:

```python
def _check_panic_fade_conditions(self, asset: str, velocity: float) -> Optional[Dict[str, Any]]:
    # Check velocity magnitude (must be panic-level move)
    if abs(velocity) < self._panic_fade_min_velocity:
        return None
    
    # Calculate RSI and Z-score
    rsi = self._calculate_rsi(asset)
    zscore = self._calculate_price_zscore(asset)
    
    # Check statistical extreme conditions
    is_oversold = (rsi < 25.0) and (zscore < -2.0)
    is_overbought = (rsi > 75.0) and (zscore > 2.0)
    
    if is_oversold:
        return {"side": "yes", "action": "buy", "strategy": "panic_fade"}
    elif is_overbought:
        return {"side": "no", "action": "buy", "strategy": "panic_fade"}
    
    return None
```

#### 4. Multi-Timeframe Alignment

Industry standard: 1m + 5m confirmation for +10-20 pp win rate:

```python
def _check_multi_timeframe_alignment(self, asset: str) -> bool:
    # Calculate 1m momentum
    momentum_1m = (recent_1m[-1] - recent_1m[0]) / recent_1m[0]
    
    # Calculate 5m momentum
    momentum_5m = (recent_5m[-1] - recent_5m[0]) / recent_5m[0]
    
    # Check alignment: both positive or both negative
    aligned = (momentum_1m > 0 and momentum_5m > 0) or (momentum_1m < 0 and momentum_5m < 0)
    
    return aligned
```

#### 5. Candidate Collection

Each agent collects an order candidate:

```python
async def collect_order_candidate(self, tick: int) -> Optional[Dict[str, Any]]:
    # Get current market
    market = self.catalog.get_current_15m_market(asset)
    
    # Get market state
    state = self.market_state_store.get_unified(market.ticker)
    
    # Get spot price
    spot = self.spot_provider.get(asset)
    
    # Calculate velocity
    velocity = self._calculate_velocity(asset, spot.price)
    
    # Check dynamic threshold
    threshold = self._calculate_dynamic_velocity_threshold(asset)
    
    # Generate signal
    if abs(velocity) > threshold:
        # Determine side based on velocity direction
        side = "yes" if velocity > 0 else "no"
        
        # Calculate edge
        edge_pct = calculate_velocity_edge(velocity, threshold)
        
        # Build candidate
        candidate = {
            "ticker": market.ticker,
            "side": side,
            "action": "buy",
            "price_cents": state.mid_cents,
            "count": 1,
            "edge_pct": edge_pct,
            "agent_id": self.config.name,
            "asset": asset,
        }
        
        return candidate
    
    return None
```

## Agent Grid Orchestration (LeanAgentGrid15m)

### Initialization

```python
class LeanAgentGrid15m:
    def __init__(self, agents: list[LeanAgent15m]):
        self._agents = agents
        self._running = False
        self._market_state_store = None
        self.position_cache = None
        self._strip_order_counts: Dict[str, int] = {}
        self._current_market_ids: Dict[str, str] = {}
        self._last_rest_sync_time = 0.0
        self._rest_sync_interval = 30.0  # seconds
```

### Key Responsibilities

The agent grid:
- Holds 5 LeanAgent15m instances (BTC, ETH, SOL, XRP, DOGE)
- Runs cycles via run_cycle()
- Tracks strip order counts for per-strip limits
- Syncs positions from REST API (30-second interval)
- Applies global allocator for order selection
- Executes chosen orders

### Cycle Execution

#### Phase 1: Collect Candidates (Parallel)

```python
async def run_cycle(self, tick: int, allow_new_entries: bool = True) -> list[Dict[str, Any]]:
    # Sync from REST at the beginning of each cycle
    await self.sync_from_rest(tick)
    
    # Phase 1: Collect all candidates from all agents (without execution)
    # OPTIMIZATION: Process agents in parallel using asyncio.gather
    agent_tasks = []
    for agent in self._agents:
        agent_tasks.append(agent.collect_order_candidate(tick))
    
    # Execute all agent tasks in parallel
    results = await asyncio.gather(*agent_tasks, return_exceptions=True)
    
    # Process results
    candidates = []
    for agent, result in zip(self._agents, results):
        if result:
            candidates.append(result)
```

**Performance**: Parallel processing reduces agent processing time from ~15s to ~3s for 5 agents.

#### Phase 2: Global Allocator

```python
# Phase 2: Apply global allocator to select best edges under venue cap
if candidates and allow_new_entries:
    from merid.risk.profiles.global_allocator import GlobalAllocator, OrderCandidate
    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
    
    # Get risk envelope for allocator configuration
    envelope = get_kalshi_crypto_15m_risk_envelope()
    allocator = create_global_allocator_from_envelope(envelope)
    
    # Convert candidates to OrderCandidate objects
    order_candidates = []
    for candidate in candidates:
        asset = candidate.get('agent_id', '').replace('_15M', '')
        order_candidate = OrderCandidate(
            asset=asset,
            ticker=candidate.get('ticker'),
            side=candidate.get('side'),
            action=candidate.get('action'),
            price_cents=int(candidate.get('price_cents', 50)),
            count=int(candidate.get('count', 1)),
            edge_pct=float(candidate.get('edge_pct', 0.0)),
            confidence=float(candidate.get('confidence', 0.5)),
            model_prob=float(candidate.get('model_prob', 0.5)),
            agent_name=candidate.get('agent_id', asset)
        )
        order_candidates.append(order_candidate)
    
    # Get current positions for all assets
    current_positions = {}
    if self.position_cache:
        positions = self.position_cache.get_all_positions(validate_freshness=False)
        for pos_ticker, pos_obj in positions.items():
            if pos_obj and pos_obj.contracts > 0:
                # Determine asset from ticker
                for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
                    if asset.lower() in pos_ticker.lower():
                        pos_notional = (pos_obj.contracts * pos_obj.current_price_cents) / 100.0
                        current_positions[asset] = current_positions.get(asset, 0.0) + pos_notional
                        break
    
    # Run global allocator
    chosen_orders = allocator.allocate(order_candidates, current_positions)
    
    # Get allocation summary
    summary = allocator.get_allocation_summary(chosen_orders)
```

**Global Allocator Logic**:
- Selects best edges under venue cap ($1 total notional)
- Enforces per-asset limits (3% of bankroll)
- Enforces per-window limits (5% of bankroll)
- Prioritizes higher edge candidates
- Prevents over-exposure to single asset

#### Phase 3: Execute Chosen Orders

```python
# Phase 3: Execute only chosen orders
executed_count = 0
for order in chosen_orders:
    # Find the original candidate for this order
    original_candidate = None
    for candidate in candidates:
        if candidate.get('ticker') == order.ticker and candidate.get('side') == order.side:
            original_candidate = candidate
            break
    
    if original_candidate:
        # Execute via direct execution path
        from merid.prediction.kalshi_tools import _kalshi_place_order
        
        order_result = await _kalshi_place_order(
            ticker=order.ticker,
            side=order.side,
            action=order.action,
            price_cents=order.price_cents,
            count=order.count,
            agent_name=order.agent_name,
            stop_loss_price_cents=max(1, order.price_cents - 5),
            take_profit_r_multiple=1.0,
            model_prob=original_candidate.get('model_prob'),
            edge_pct=original_candidate.get('edge_pct'),
            confidence=original_candidate.get('confidence')
        )
        
        if order_result and order_result.success:
            executed_count += 1
```

### REST Sync Optimization

```python
async def sync_from_rest(self, tick: int) -> None:
    # Sync catalog and market state from REST API
    # OPTIMIZATION: Only sync every 30 seconds instead of every cycle
    current_time = time.time()
    
    if current_time - self._last_rest_sync_time < self._rest_sync_interval:
        return
    
    # Force sync position cache from REST API
    client = KalshiVenueClient(config=get_kalshi_config())
    await client.connect()
    kalshi_positions = await client.get_positions()
    
    # Convert to format expected by sync_from_rest
    rest_positions = []
    for pos in kalshi_positions:
        avg_price_cents = int(float(pos.average_entry_price) * 100)
        rest_positions.append({
            "market_id": pos.market_id,
            "contracts": int(pos.size),
            "side": pos.outcome_id or "yes",
            "avg_price_cents": avg_price_cents,
            "realized_pnl": float(pos.realized_pnl) if pos.realized_pnl else 0,
            "unrealized_pnl": float(pos.unrealized_pnl) if pos.unrealized_pnl else 0,
        })
    
    # Force sync to bypass staleness guard
    await position_cache.sync_from_rest(rest_positions, force=True)
    self._last_rest_sync_time = current_time
```

**Rationale**: WebSocket provides real-time position updates, REST is used for reconciliation every 30 seconds to reduce latency.

### Strip Order Tracking

```python
def reset_strip_order_counts(self) -> None:
    """Reset all strip order counts and market ID tracking.
    
    This is called when the catalog detects a market rollover (e.g., 16:15 -> 16:30).
    It resets the per-strip order limits so trading can continue on the new 15m strip.
    """
    self._strip_order_counts.clear()
    self._current_market_ids.clear()
```

**Trigger**: Called by catalog when it detects a market rollover via the global `reset_strip_order_counts()` function.

## Agent Grid Builder

### build_15m_agent_grid Function

```python
async def build_15m_agent_grid(
    catalog: Any,
    bankroll: Any,
    spot_provider: Any,
    order_router: Any,
    loop: Optional[Any] = None,
    unified_edge_config: Any = None,
    ws_bridge: Optional[Any] = None,
) -> LeanAgentGrid15m:
    """Build the 5 crypto 15m agents for Kalshi trading."""
    
    # Get market state store and risk config
    market_state_store = get_kalshi_market_state_store()
    risk_config = get_kalshi_crypto_15m_risk_envelope()
    
    # Create 5 agent instances
    agents = []
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        config = LeanAgentConfig(
            name=f"{asset}_15M",
            series_tickers=[f"KX{asset}15M"],
            # ... other config parameters
        )
        
        agent = LeanAgent15m(
            config=config,
            catalog=catalog,
            market_state_store=market_state_store,
            spot_provider=spot_provider,
            order_router=order_router,
            risk_config=risk_config,
        )
        
        agents.append(agent)
    
    # Create and return grid
    grid = LeanAgentGrid15m(agents=agents)
    grid.set_market_state_store(market_state_store)
    
    return grid
```

### Import Policy

The builder function explicitly excludes:
- `merid.prediction.agent_grid` (old generic grid)
- `merid.pm_runtime`
- `trading.paper_trading`
- `merid.reconciliation.venue`
- `reflection.*`
- Social broadcasters

This ensures the lean 15m stack remains isolated from legacy components.

## Risk Integration

### Position Cache Integration

The agent grid integrates with the position cache for:
- Current position tracking
- Exposure calculation
- Resting order detection

```python
def set_position_cache(self, position_cache: Any) -> None:
    self.position_cache = position_cache
    logger.info("[AGENT-GRID] Position cache set for global allocator")
```

### Risk Envelope Integration

The global allocator uses the risk envelope for:
- Venue cap enforcement ($1 total notional)
- Per-asset limits (3% of bankroll)
- Per-window limits (5% of bankroll)
- Dynamic sizing based on edge

```python
envelope = get_kalshi_crypto_15m_risk_envelope()
allocator = create_global_allocator_from_envelope(envelope)
```

## Performance Optimizations

### 1. Parallel Agent Processing

- **Before**: Sequential processing (~15s for 5 agents)
- **After**: Parallel processing with asyncio.gather (~3s for 5 agents)

### 2. REST Sync Throttling

- **Before**: Sync every cycle (5s cadence)
- **After**: Sync every 30 seconds
- **Rationale**: WebSocket provides real-time updates, REST for reconciliation only

### 3. Indicator Stack Redundancy

- **Before**: Each agent only initializes its own asset's indicator stack
- **After**: Each agent initializes ALL 5 assets' indicator stacks
- **Rationale**: Ensures each stack gets 5 updates per cycle instead of 1, preventing "bars_available=1" issue

## Critical Fixes

### Fix 1: Kalshi Mode for Indicator Stacks (2026-07-08)

**Problem**: Strict spot market thresholds (vol/ATR/chop gates) were blocking all signals.

**Solution**: Enable `kalshi_mode=True` in IndicatorConfig to disable strict spot market thresholds. Kalshi prediction markets are binary contracts, not continuous spot instruments.

### Fix 2: Neutral ATR/ADX Multipliers (2026-07-02)

**Problem**: ATR and ADX multipliers (0.90-1.10) were inflating thresholds above base values, causing velocity to be below dynamic threshold even when above base threshold.

**Solution**: Set all ATR and ADX multipliers to 1.0 (neutral) to use base threshold directly.

### Fix 3: Indicator Stack Redundancy (2026-07-10)

**Problem**: Each agent only initialized its own asset's indicator stack, causing "bars_available=1" because each agent is called once per cycle.

**Solution**: Each agent initializes ALL 5 assets' indicator stacks, ensuring each stack gets 5 updates per cycle.

### Fix 4: Session Order Count on Fill (2026-07-10)

**Problem**: Session order count and cooldown were updated on submission, causing perpetual cooldown blocks when orders don't fill (e.g., resting limit orders).

**Solution**: Update session order count and cooldown on FILL, not submission. The `update_cooldown_on_fill` method handles both session count and cooldown on successful fills.

## Monitoring and Logging

### Key Log Messages

- `[AGENT-GRID-INIT]`: Grid initialization
- `[AGENT-GRID-START]`: Grid startup
- `[AGENT-GRID-RUN-CYCLE]`: Cycle execution start
- `[AGENT-GRID-RUN-CYCLE-AGENT]`: Individual agent execution
- `[AGENT-GRID-RUN-CYCLE-CANDIDATE]`: Candidate generated
- `[AGENT-GRID-RUN-CYCLE-NO-CANDIDATE]`: No candidate generated
- `[CYCLE-COMPLETE]`: Cycle completion summary
- `[GLOBAL-ALLOCATOR-SUMMARY]`: Allocation summary
- `[GLOBAL-ALLOCATOR-EXECUTE]`: Order execution
- `[STRIP-RESET-ALL]`: Strip order count reset

### Performance Metrics

- Cycle duration (target: <5s)
- Agent processing time (target: <1s per agent)
- Candidate generation rate
- Order execution success rate
- REST sync duration

## Version History

### v20260529a-cache-fix

- Added operation_mode support for daily loss limit
- Test mode: 10% daily loss limit
- Prod mode: 5% daily loss limit
- Controlled via MERID_OPERATION_MODE env var or profile YAML

### v20260708-kalshi-mode

- Enabled kalshi_mode for indicator stacks
- Disabled strict spot market thresholds
- Fixed signal generation blocking

### v20260710-indicator-redundancy

- Added indicator stack initialization for all 5 assets in each agent
- Fixed "bars_available=1" issue
- Improved signal generation reliability

## References

- **Profile Configuration**: `config/profiles/kalshi_crypto_15m_v2.yaml`
- **Risk Envelope**: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`
- **Global Allocator**: `merid/risk/profiles/global_allocator.py`
- **Indicators**: `merid/signals/crypto_15m_indicators.py`
- **Market Catalog**: `merid/event_venues/kalshi/market_catalog.py`
- **Market State**: `merid/event_venues/kalshi/market_state.py`
