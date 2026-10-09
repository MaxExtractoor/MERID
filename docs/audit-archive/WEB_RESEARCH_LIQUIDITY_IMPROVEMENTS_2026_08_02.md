# Web Research-Based Liquidity Improvements

**Date**: 2026-08-02
**Research Sources**: Electronic Trading Hub, Markaicode, DEV Community, GitHub repositories
**Objective**: Implement industry best practices for liquidity management in binary options trading

## Executive Summary

Based on extensive web research into high-frequency trading, market making, and binary options systems, we have implemented three critical improvements to our trading stack:

1. **Refill Time Detector** - Classifies toxic vs uninformed flow in sparse liquidity
2. **Tiered Fallback Executor** - Multi-tier execution strategies for liquidity crisis management
3. **Integration into Signal Generation and Order Routing** - Seamless deployment across the stack

These improvements address the fundamental problem identified in the research: **the issue isn't the strategy, it's the lack of fallback logic when liquidity disappears**.

---

## Research Findings

### 1. Refill Time Detection (Electronic Trading Hub, 2023)

**Key Insight**: In thin order books, OFI (Order Flow Imbalance) of zero doesn't mean equilibrium—it means the metric is stale. Refill time is the real-time classifier that works on sparse books.

**Research Quote**:
> "What actually works as a real-time classifier on a sparse book is refill time. When a level is swept and the book refills in milliseconds, the flow was uninformed — a participant exiting a position, not moving on superior information. When the level stays empty for minutes after a sweep, the fill was likely toxic."

**Implementation**:
- Track when liquidity is depleted (depth drops to zero)
- Measure time until liquidity returns (refill time)
- Classify as toxic if refill time exceeds threshold (default: 1000ms)
- Apply penalty to signal generation during toxic periods

**Files Created**:
- `merid/event_venues/kalshi/refill_detector.py` (235 lines)

### 2. Tiered Fallback Logic (Markaicode, 2024)

**Key Insight**: Multi-tier fallback strategies that activate automatically based on liquidity conditions, with emergency shutdown at crisis levels.

**Research Quote**:
> "The issue wasn't my strategy. It was that I had zero fallback logic for when liquidity disappeared and bid-ask spreads exploded from $0.02 to $4.50."

**Implementation**:
- Calculate real-time liquidity score (0-100) based on spread, depth, and stability
- Map score to execution tier (NORMAL → CAUTIOUS → DEFENSIVE → EMERGENCY → HALT)
- Each tier has pre-configured limits for order size, spread tolerance, and execution parameters
- Automatic tier transitions based on liquidity conditions

**Execution Tiers**:

| Tier | Score Range | Max Order Size | Max Spread | Order Type | Limit Offset | Timeout |
|------|-------------|----------------|------------|-------------|--------------|----------|
| NORMAL | 70-100 | $50,000 | 0.5% | limit | 10 bps | 30s |
| CAUTIOUS | 40-70 | $10,000 | 1.0% | limit | 25 bps | 20s |
| DEFENSIVE | 20-40 | $2,000 | 2.0% | limit | 50 bps | 15s |
| EMERGENCY | <20 | $500 | 5.0% | limit | 100 bps | 10s |
| HALT | - | $0 | 0% | halt | - | 0s |

**Files Created**:
- `merid/risk/liquidity_fallback.py` (303 lines)

### 3. Fail-Open Patterns (DEV Community, 2024)

**Key Insight**: Graceful degradation instead of fail-closed. Tiered model fallbacks with position scaling.

**Research Quote**:
> "In production AI trading systems, the question isn't if components will fail—it's whether your architecture lets you trade another day. Most developers obsess over fail-closed patterns: circuit breakers that halt everything, kill switches that shut down positions, hard stops that protect capital at the cost of opportunity."

**Implementation**:
- Our tiered fallback system implements fail-open patterns
- Instead of hard-blocking on liquidity issues, the system degrades gracefully
- Position sizing is automatically reduced based on liquidity tier
- Trading continues in degraded mode instead of complete shutdown

### 4. VPIN (Volume-Synchronized Probability of Informed Trading)

**Research Finding**: Volume-time accumulation instead of clock-time for sparse liquidity. Prevents false equilibrium readings from stale clock-time OFI.

**Status**: Not yet implemented (future enhancement)

### 5. Orderbook Checksum Validation (Moonbase)

**Research Finding**: CRC32 checksums to detect orderbook state drift. Prevents trading on stale/incorrect data.

**Status**: Not yet implemented (future enhancement)

---

## Implementation Details

### Refill Detector Integration

**Location**: `merid/prediction/agent_grid_15m.py`

**Changes**:
1. Added import for `RefillDetector` (lines 82-87)
2. Initialized `_refill_detector` in `LeanAgent15m.__init__()` (lines 1040-1056)
3. Integrated refill detection in momentum_fvg signal generation (lines 4617-4652)

**Behavior**:
- When extreme OBI (≥0.9) is detected, refill detector is invoked
- If toxic flow is detected (slow refill), signal is suppressed
- If safe refill is detected (fast refill), signal proceeds
- Logs refill time for analysis

**Configuration** (via `LeanAgentConfig`):
- `advanced_liquidity_enabled`: Enable/disable advanced liquidity tools
- `refill_toxic_threshold_ms`: Threshold for toxic classification (default: 1000ms)
- `refill_window_ms`: Time window for tracking refill times (default: 60000ms)
- `refill_min_samples`: Minimum samples before statistics (default: 3)

### Liquidity Fallback Executor Integration

**Location**: `merid/event_venues/kalshi/order_router.py`

**Changes**:
1. Added import for `LiquidityFallbackExecutor` (lines 71-77)
2. Added liquidity fallback check in `route_order_async()` (lines 9883-9944)

**Behavior**:
- Before order execution, liquidity score is computed
- If score is in HALT tier, order is rejected
- If score is in lower tiers, order size is adjusted
- Logs tier and score for monitoring

**Configuration** (via `LiquidityFallbackExecutor`):
- Custom tier configurations can be provided
- Score averaging window (default: 5 snapshots)
- Per-tier limits for order size, spread, timeout

### Singleton Pattern

**Location**: `merid/risk/liquidity_fallback.py`

**Functions**:
- `get_liquidity_fallback_executor()`: Get singleton instance
- `init_liquidity_fallback_executor()`: Initialize singleton

**Usage**:
```python
from merid.risk.liquidity_fallback import init_liquidity_fallback_executor

# Initialize during system startup
executor = init_liquidity_fallback_executor()

# Access from anywhere
from merid.risk.liquidity_fallback import get_liquidity_fallback_executor
executor = get_liquidity_fallback_executor()
```

---

## Testing and Validation

### Manual Testing Steps

1. **Refill Detector**:
   - Monitor logs for `[REFILL-DETECTOR]` messages
   - Verify toxic flow detection when refill time > 1000ms
   - Verify safe refill detection when refill time < 1000ms
   - Check signal suppression during toxic periods

2. **Liquidity Fallback**:
   - Monitor logs for `[LIQUIDITY-FALLBACK]` messages
   - Verify tier transitions based on liquidity score
   - Verify order size adjustments in lower tiers
   - Verify order rejection in HALT tier

3. **Integration**:
   - Run system with `advanced_liquidity_enabled=True`
   - Verify no trade blocking on one-sided liquidity (unless toxic)
   - Verify graceful degradation during liquidity crises
   - Compare trade rate before/after implementation

### Expected Outcomes

1. **Reduced False Rejections**: One-sided liquidity no longer blocks trades (unless toxic)
2. **Toxic Flow Detection**: Signals suppressed during toxic flow periods
3. **Graceful Degradation**: System continues trading in degraded mode during crises
4. **Improved Risk Management**: Automatic position sizing based on liquidity conditions

---

## Configuration

### Enabling Advanced Liquidity Tools

In your agent configuration (e.g., `kalshi_crypto_15m_v2.yaml`):

```yaml
# Advanced liquidity management (web research-based)
advanced_liquidity_enabled: true

# Refill detector configuration
refill_toxic_threshold_ms: 1000  # 1 second = toxic
refill_window_ms: 60000  # 1 minute window
refill_min_samples: 3  # Minimum samples before statistics

# Liquidity fallback configuration
liquidity_score_window: 5  # Number of snapshots to average
```

### Custom Tier Configuration

If you need custom tier configurations:

```python
from merid.risk.liquidity_fallback import (
    LiquidityFallbackExecutor,
    FallbackConfig,
    ExecutionTier,
    init_liquidity_fallback_executor,
)

custom_configs = {
    ExecutionTier.NORMAL: FallbackConfig(
        tier=ExecutionTier.NORMAL,
        max_order_size_usd=100000,  # Higher limit
        max_spread_pct=0.3,  # Tighter spread
        order_type='limit',
        limit_offset_bps=5,
        max_clip_size_pct=0.30,
        timeout_seconds=30,
        min_confidence=0.50,
    ),
    # ... other tiers
}

executor = init_liquidity_fallback_executor(configs=custom_configs)
```

---

## Future Enhancements

### 1. Orderbook Checksum Validation

**Research**: Moonbase documentation on CRC32 checksums for orderbook state drift detection.

**Implementation Plan**:
- Add checksum calculation to `OrderbookSnapshot`
- Verify checksum on each update
- Reject trades if checksum mismatch detected
- Log checksum validation results

### 2. VPIN (Volume-Synchronized Probability of Informed Trading)

**Research**: Easley, Lopez de Prado, and O'Hara (2012) - VPIN for sparse liquidity.

**Implementation Plan**:
- Implement volume-time accumulation instead of clock-time
- Calculate VPIN metric for orderbook
- Use VPIN as additional liquidity quality signal
- Integrate with fallback executor

### 3. Fail-Open Pattern Expansion

**Research**: DEV Community on tiered model fallbacks.

**Implementation Plan**:
- Implement tiered model fallbacks (primary → distilled → heuristic → rules)
- Position scaling based on model tier
- Shadow trading for empirical validation
- Cross-exchange reconciliation for price feed failures

---

## References

1. **Electronic Trading Hub** - "Illiquid Market Making: When the Feature Pipeline, Not the Model, Determines Whether You Survive" (2023)
   - Refill time detection for toxic vs uninformed flow
   - URL: https://electronictradinghub.com/illiquid-market-making-when-the-feature-pipeline-not-the-model-determines-whether-you-survive/

2. **Markaicode** - "Stop Flash Crashes from Destroying Your Trading System in 90 Seconds" (2024)
   - Tiered fallback logic for liquidity crisis detection
   - URL: https://markaicode.com/flash-crash-fallback-strategies/

3. **DEV Community** - "Fail-Open Patterns: When Your AI Trading System Must Choose Graceful Degradation Over Perfection" (2024)
   - Graceful degradation instead of fail-closed
   - URL: https://dev.to/a3e_ecosystem/fail-open-patterns-when-your-ai-trading-system-must-choose-graceful-degradation-over-perfection-337e

4. **Moonbase** - Orderbook Checksum Documentation
   - CRC32 checksums for state drift detection
   - URL: https://docs.moonbase.vn/docs/websocket/checksum

5. **Easley, Lopez de Prado, O'Hara** - "Volume-Synchronized Probability of Informed Trading" (2012)
   - VPIN for sparse liquidity
   - Review of Financial Studies 25(5): 1457-1493

6. **GitHub Repositories**:
   - `leionion/orderbook-imbalance-indicator-hft` - Refill detection implementation
   - `mikegianfelice/Hunter` - Tiered position sizing system
   - `YISOWAK/polybot-market-maker` - Polymarket binary options market making

---

## Conclusion

These web research-based improvements represent a significant upgrade to our liquidity management capabilities. By implementing industry best practices from high-frequency trading and market making research, we have:

1. **Solved the one-sided liquidity blocking issue** - No longer hard-block on zero depth
2. **Added toxic flow detection** - Classify and suppress signals during toxic periods
3. **Implemented graceful degradation** - Multi-tier fallback instead of hard shutdown
4. **Improved risk management** - Automatic position sizing based on liquidity conditions

The system is now more robust, adaptive, and aligned with industry best practices for trading in sparse liquidity conditions.

---

**Next Steps**:
1. Enable `advanced_liquidity_enabled` in production configuration
2. Monitor logs for refill detection and fallback events
3. Validate that trade rate improves without increasing risk
4. Consider implementing orderbook checksum validation and VPIN for future enhancements
