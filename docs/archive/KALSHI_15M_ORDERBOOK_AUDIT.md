# Kalshi 15M Order Book Audit

**Objective:** Verify that bid/ask/depth is treated as first-class data across all layers (Kalshi API → unified edge → sizing/risk → router/exits) and ensure every layer interprets the book consistently.

**Date:** 2026-05-28
**Scope:** BTC/ETH/SOL/XRP/DOGE 15-minute Kalshi markets

---

## Executive Summary

**CRITICAL FINDING:** Multiple conflicting `OrderBookSnapshot` definitions exist across the codebase, creating a risk of inconsistent book interpretation between layers.

**Primary Concerns:**
1. **Three different `OrderBookSnapshot` dataclasses** with different field types and semantics
2. **Spread calculation inconsistencies** between layers
3. **Depth definition mismatches** between unified edge and router
4. **Kalshi YES/NO duality not consistently applied** across all consumers

**Recommendation:** Consolidate to a single canonical `OrderBookSnapshot` definition derived from `LocalOrderbook` in `orderbook.py`.

---

## 1) Upstream: Order Book Ingestion and Representation

### 1.1 Kalshi API Usage

**Kalshi API Contract (per docs.kalshi.com):**
- Orderbook is **bid-only** for YES/NO sides
- `yes_dollars` = YES bids (array of [price_dollars, size])
- `no_dollars` = NO bids (array of [price_dollars, size])
- **Derived asks:**
  - YES ask = `1 - best_no_bid` (complement relationship)
  - NO ask = `1 - best_yes_bid` (complement relationship)

**Current Implementation:**

**File:** `merid/event_venues/kalshi/orderbook.py` (Canonical Source)

```python
class LocalOrderbook:
    """Local orderbook state maintained from WebSocket updates."""
    
    def __init__(self, ticker: str):
        self.yes_levels: Dict[int, int] = defaultdict(int)  # price_cents -> size
        self.no_levels: Dict[int, int] = defaultdict(int)
    
    def get_best_bid(self) -> Optional[Tuple[int, int]]:
        """Get best bid (highest yes price with size)."""
        if not self.yes_levels:
            return None
        best_price = max(self.yes_levels.keys())
        return (best_price, self.yes_levels[best_price])
    
    def get_best_ask(self) -> Optional[Tuple[int, int]]:
        """Get best ask (lowest no complement price with size).
        
        Kalshi YES/NO Symmetry (per Kalshi docs):
        - YES and NO prices are duals: YES_bid + NO_ask = 100 cents
        - The orderbook is bid-side-only; we derive the opposite side from 100 - price
        - NO_ask (selling NO) is equivalent to YES_ask (buying YES)
        - We convert NO prices to YES-equivalent: yes_equivalent = 100 - no_price
        """
        if not self.no_levels:
            return None
        best_no_price = min(self.no_levels.keys())
        yes_equivalent = 100 - best_no_price
        return (yes_equivalent, self.no_levels[best_no_price])
    
    def get_spread(self) -> Optional[int]:
        """Get bid-ask spread in cents."""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid is None or best_ask is None:
            return None
        return best_ask[0] - best_bid[0]
```

**Status:** ✅ **CORRECT** - Implements Kalshi's bid-only YES/NO duality correctly.

---

### 1.2 Internal Data Structures

**PROBLEM:** Three different `OrderBookSnapshot` definitions exist:

#### Definition 1: `merid/prediction/unified_edge.py` (lines 101-108)

```python
@dataclass
class OrderBookSnapshot:
    """Kalshi order book snapshot for microstructure analysis."""
    best_bid: int  # cents
    best_ask: int  # cents
    best_bid_size: int
    best_ask_size: int
    spread_cents: int
    timestamp: datetime
```

**Issues:**
- No explicit YES/NO side distinction
- Assumes explicit asks (Kalshi doesn't provide these)
- Used by unified edge for microstructure checks

#### Definition 2: `merid/event_venues/kalshi/liquidity_monitor.py` (lines 41-51)

```python
@dataclass
class OrderBookSnapshot:
    """Point-in-time orderbook top-of-book for a Kalshi market."""
    market_id: str
    best_bid: float  # Different type (float vs int)
    best_ask: float  # Different type (float vs int)
    bid_size: int
    ask_size: int
    ts: float = field(default_factory=time.time)
```

**Issues:**
- Uses `float` for prices (others use `int` cents)
- Different field names (`bid_size` vs `best_bid_size`)
- Used by liquidity monitor for alerts

#### Definition 3: `merid/event_venues/kalshi/unified_market_state.py` (lines 44-104)

```python
@dataclass(frozen=True)
class OrderbookSnapshot:
    """Typed, immutable L2 orderbook snapshot for one market.

    Kalshi's YES-centric convention:
      ``yes_bids`` — descending by price (index 0 = best YES bid)
      ``no_bids``  — descending by price (index 0 = best NO bid →
                     best YES ask = 100 − no_bids[0].price_cents)
    """
    ticker: str
    yes_bids: Tuple[OrderbookLevel, ...]  # sorted descending
    no_bids: Tuple[OrderbookLevel, ...]   # sorted descending
    seq: int = 0
    ts: float = 0.0
    
    @property
    def best_yes_bid(self) -> Optional[int]:
        return self.yes_bids[0].price_cents if self.yes_bids else None
    
    @property
    def best_yes_ask(self) -> Optional[int]:
        """Best YES ask = 100 − best NO bid (Kalshi binary duality)."""
        return (100 - self.no_bids[0].price_cents) if self.no_bids else None
    
    @property
    def spread_cents(self) -> Optional[float]:
        ask, bid = self.best_yes_ask, self.best_yes_bid
        return float(ask - bid) if ask is not None and bid is not None else None
```

**Status:** ✅ **CORRECT** - Implements Kalshi YES/NO duality correctly with full L2 depth.

---

### 1.3 KalshiMarketState (Unified State)

**File:** `merid/event_venues/kalshi/models.py` (lines 345-444)

```python
class KalshiMarketState:
    """Live per-ticker state maintained by KalshiMarketStateStore.
    
    Two independent write paths own disjoint slices:
    - WS orderbook path: book_initialized, best_bid/ask_cents, mid_cents,
      spread_cents, top_of_book_size, depth_10c, yes_bids, no_bids,
      last_book_update_ts.
    - REST path: volume_24h, open_interest, notional_value_cents, all three
      expiry fields, seconds_to_expiry, last_rest_update_ts,
      underlying, strike_price, floor_strike, cap_strike.
    """
    ticker: str
    
    # Book-owned fields (dynamic from WS orderbook)
    book_initialized: bool = False
    best_bid_cents: Optional[int] = None
    best_ask_cents: Optional[int] = None
    mid_cents: Optional[int] = None
    spread_cents: Optional[float] = None
    top_of_book_size: int = 0
    depth_10c: int = 0
    yes_bids: List[Any] = field(default_factory=list)
    no_bids: List[Any] = field(default_factory=list)
    
    @property
    def yes_bid(self) -> Optional[float]:
        """Best yes bid price as float (0-1 range), or None."""
        if self.best_bid_cents is None:
            return None
        return self.best_bid_cents / 100.0
    
    @property
    def yes_ask(self) -> Optional[float]:
        """Best yes ask price as float (0-1 range), or None."""
        if self.best_ask_cents is None:
            return None
        return self.best_ask_cents / 100.0
    
    @property
    def no_bid(self) -> Optional[float]:
        """Best no bid price as float (0-1 range), derived from yes ask."""
        yes_ask = self.yes_ask
        if yes_ask is None:
            return None
        return 1.0 - yes_ask
    
    @property
    def no_ask(self) -> Optional[float]:
        """Best no ask price as float (0-1 range), derived from yes bid."""
        yes_bid = self.yes_bid
        if yes_bid is None:
            return None
        return 1.0 - yes_bid
```

**Status:** ✅ **CORRECT** - Implements Kalshi YES/NO duality correctly with derived properties.

---

### 1.4 Duplicate Parsing Search

**Search Results:**
- `merid/event_venues/kalshi/orderbook.py` - Canonical `LocalOrderbook` implementation
- `merid/event_venues/kalshi/market_state.py` - Uses `LocalOrderbook` via `MultiMarketOrderbook`
- `merid/event_venues/kalshi/ws_bridge.py` - Feeds `LocalOrderbook` from WS messages
- `merid/event_venues/kalshi/client.py` - REST fallback to `GET /markets/{ticker}/orderbook`

**Status:** ✅ **NO DUPLICATE PARSING** - All paths converge on `LocalOrderbook` in `orderbook.py`.

---

## 2) Midstream: Unified Definition of Spread and Depth

### 2.1 Spread Definition

**Kalshi Binary Contract Spread (Correct Definition):**

For a binary option, the effective spread depends on which side you're trading:

- **Buying YES:**
  - You cross at `yes_ask = 100 - best_no_bid`
  - Your mark-to-market is at `best_yes_bid`
  - Effective spread = `yes_ask - best_yes_bid`

- **Buying NO:**
  - You cross at `no_ask = 100 - best_yes_bid`
  - Your mark-to-market is at `best_no_bid`
  - Effective spread = `no_ask - best_no_bid`

**Current Implementations:**

#### Unified Edge (`merid/prediction/unified_edge.py`)

```python
def compute_spread_pct(self, contract: ContractState) -> Optional[float]:
    """Compute spread as percentage of mid price."""
    if contract.orderbook is None:
        return None
    
    bid = contract.orderbook.best_bid
    ask = contract.orderbook.best_ask
    
    if bid <= 0 or ask <= 0:
        return None
    
    mid = (bid + ask) / 2.0
    if mid == 0:
        return None
    
    spread_pct = (ask - bid) / mid
    return spread_pct
```

**Status:** ⚠️ **POTENTIAL ISSUE** - Uses `best_bid` and `best_ask` from its own `OrderBookSnapshot` which doesn't distinguish YES/NO sides. May not correctly handle Kalshi's bid-only structure.

#### LocalOrderbook (`merid/event_venues/kalshi/orderbook.py`)

```python
def get_spread(self) -> Optional[int]:
    """Get bid-ask spread in cents."""
    best_bid = self.get_best_bid()
    best_ask = self.get_best_ask()
    if best_bid is None or best_ask is None:
        return None
    return best_ask[0] - best_bid[0]
```

**Status:** ✅ **CORRECT** - Implements YES/NO duality correctly.

---

### 2.2 Depth Definition

**Current Implementations:**

#### LocalOrderbook (`merid/event_venues/kalshi/orderbook.py`)

```python
def get_depth(self, side: str, price_limit: Optional[int] = None) -> int:
    """Get total size at price levels up to limit.
    
    Args:
        side: "yes" or "no"
        price_limit: Maximum (for yes) or minimum (for no) price to include
    
    Returns:
        Total contracts at specified price levels
    """
    levels = self.yes_levels if side == "yes" else self.no_levels
    
    if price_limit is None:
        return sum(levels.values())
    
    if side == "yes":
        # For yes, sum levels at or below price_limit
        return sum(size for price, size in levels.items() if price <= price_limit)
    else:
        # For no, sum levels at or above price_limit
        return sum(size for price, size in levels.items() if price >= price_limit)
```

**Status:** ✅ **CORRECT** - Depth calculation is side-aware and price-limit aware.

#### Unified Edge (`merid/prediction/unified_edge.py`)

```python
# Check depth at target price (use order_size from metadata or default to 1)
order_size = edge_result.metadata.get("order_size", 1)
required_depth = int(depth_multiplier * order_size)

depth_yes = contract.orderbook.best_bid_size
depth_no = contract.orderbook.best_ask_size

# For YES contracts, check depth_yes; for NO contracts, check depth_no
if contract.side == "yes" and depth_yes < required_depth:
    return EdgeCheckResult(
        passes=False,
        reason=f"microstructure_trap_insufficient_depth: asset={asset} side=yes depth_yes={depth_yes} < required={required_depth} (order_size={order_size} multiplier={depth_multiplier})",
        ...
    )
```

**Status:** ⚠️ **POTENTIAL ISSUE** - Uses `best_bid_size` and `best_ask_size` from its own `OrderBookSnapshot` which are L1-only. Doesn't aggregate depth across price levels like `LocalOrderbook.get_depth()` does.

---

### 2.3 Guardrails vs Routing Consistency

**Unified Edge Depth Check:**
- Uses `best_bid_size` / `best_ask_size` (L1 only)
- Multiplies by `depth_multiplier` (e.g., 3x)
- Checks if `depth >= required_depth`

**Order Router Depth Check:**
```python
# From agent_grid_15m.py
depth_yes = getattr(state, "min_depth_yes", 0)
depth_no = getattr(state, "min_depth_no", 0)

# Use config-driven depth thresholds (per-asset base * regime multiplier)
depth_ok, depth_reason = _check_per_asset_depth_by_tier(asset, depth_yes, depth_no)
```

**Status:** ⚠️ **INCONSISTENT** - Unified edge uses L1 depth with multiplier, router uses `min_depth_yes/no` from `KalshiMarketState` (also L1). Both are L1-only, but the multiplier logic may differ.

---

## 3) Strategy/Risk: Book Usage in Trade Decisions

### 3.1 Entry Price Selection

**Current Implementation (`merid/event_venues/kalshi/order_router.py`):**

```python
def _price_for_side(
    price_cents: int,
    side: str,
    action: str,
    best_bid_cents: Optional[int] = None,
    best_ask_cents: Optional[int] = None,
    maker_bias_cents: int = 1,
) -> int:
    """Adjust order price for maker-friendly placement.
    
    For buy orders: place at or below best bid to be maker
    For sell orders: place at or above best ask to be maker
    """
    if best_bid_cents is None or best_ask_cents is None:
        # No market data, return original price
        return price_cents
    
    if action == "buy":
        # Buy at or below best bid to be maker
        maker_price = min(price_cents, best_bid_cents - maker_bias_cents)
        return max(1, maker_price)  # Ensure minimum price of 1 cent
    else:  # sell
        # Sell at or above best ask to be maker
        maker_price = max(price_cents, best_ask_cents + maker_bias_cents)
        return min(99, maker_price)  # Ensure maximum price of 99 cents
```

**Status:** ✅ **CORRECT** - Uses best bid/ask for maker-friendly placement.

---

### 3.2 Depth-Aware Sizing

**Current Implementation (`merid/prediction/unified_edge.py`):**

```python
# Check depth at target price (use order_size from metadata or default to 1)
order_size = edge_result.metadata.get("order_size", 1)
required_depth = int(depth_multiplier * order_size)

depth_yes = contract.orderbook.best_bid_size
depth_no = contract.orderbook.best_ask_size

# For YES contracts, check depth_yes; for NO contracts, check depth_no
if contract.side == "yes" and depth_yes < required_depth:
    return EdgeCheckResult(passes=False, reason="insufficient_depth")
```

**Status:** ⚠️ **LIMITED** - Only checks L1 depth, doesn't aggregate across price levels. May reject trades that could be filled by walking the book.

---

### 3.3 Risk Caps vs Depth

**Current Implementation:**
- Risk caps are enforced by `GlobalRiskGuard` and `KalshiRiskManager`
- Depth checks are separate in unified edge
- No explicit logic to take the minimum of (risk cap size, depth-limited size)

**Status:** ⚠️ **MISSING** - Should enforce `min(risk_cap_size, depth_limited_size)` but currently these are independent checks.

---

## 4) Downstream: Router and Exit Behavior

### 4.1 Execution Price vs TP/SL

**Current Implementation:**
- TP/SL are set in cents based on entry price
- Router uses `KalshiMarketState` for current market data during exit checks
- Position cache monitors positions and forces exits near expiry

**Status:** ⚠️ **NEEDS VERIFICATION** - Need to confirm TP/SL checks use the same book view as entry.

---

### 4.2 Partial Fills and Depth

**Current Implementation:**
- Kalshi API handles partial fills natively
- No explicit logic in router to break large orders into smaller child orders based on depth
- Position cache tracks filled count vs remaining count

**Status:** ⚠️ **MISSING** - No depth-aware order splitting for large orders.

---

### 4.3 Order Book Monitoring During Trade Life

**Current Implementation:**
- Position cache subscribes to `KalshiMarketStateStore` for price updates
- PnL computer updates unrealized PnL on every price tick
- Forced exits use current market state from `KalshiMarketStateStore`

**Status:** ✅ **CORRECT** - Uses same `KalshiMarketStateStore` for monitoring.

---

## 5) Sanity Patterns to Watch

### 5.1 Repeated `[DEPTH-REJECT]` in Liquid Markets

**Potential Cause:** Depth calculation mismatch (e.g., using wrong side of YES/NO duality).

**Action:** Monitor logs for depth rejections and cross-reference with `KalshiMarketState` depth fields.

---

### 5.2 TP Never Hit Despite Price Crossing Target

**Potential Cause:** Exits watching wrong side of book (YES vs NO) or using stale snapshots.

**Action:** Add logging to show which side's bid/ask is being monitored for TP/SL triggers.

---

### 5.3 High Slippage Relative to Implied Spread

**Potential Cause:** Expected spread (unified edge) vs actual execution cost (router) misalignment.

**Action:** Log expected spread at entry time and actual execution price to compute realized slippage.

---

## 6) Concrete Next Actions

### 6.1 ✅ COMPLETED: Consolidate OrderBookSnapshot Definitions

**Status:** COMPLETED (2026-05-28)

**Actions Taken:**
1. ✅ Created canonical microstructure utility in `merid/event_venues/kalshi/microstructure.py`
   - `compute_side_microstructure()` - Single source for spread/depth calculations
   - `compute_effective_spread()` - Side-aware spread calculation
   - `compute_depth_at_price()` - Depth aggregation at specific prices
   - `cents_to_dollars()` / `dollars_to_cents()` - Unit conversion utilities

2. ✅ Removed local `OrderBookSnapshot` from `unified_edge.py`
   - Replaced with import from `unified_market_state.OrderbookSnapshot`
   - Updated all spread/depth calculations to use canonical microstructure utilities
   - Changed `best_bid`/`best_ask` to `best_yes_bid`/`best_yes_ask` (YES-centric)

3. ✅ Removed custom `OrderBookSnapshot` from `liquidity_monitor.py`
   - Replaced with import from `unified_market_state.OrderbookSnapshot`
   - Updated all alert logic to use canonical microstructure utilities
   - Added cents-to-dollars conversion for threshold comparisons

4. ✅ Added unit tests in `tests/event_venues/kalshi/test_microstructure.py`
   - Tests for YES/NO duality invariant
   - Tests for spread calculation consistency
   - Tests for depth aggregation logic
   - Tests for fillability checks
   - Tests for effective spread per side/action

**Result:** All components now use the single canonical `OrderbookSnapshot` from `unified_market_state.py` with consistent microstructure calculations.

---

### 6.2 Implement Fill-Level Diagnostics

**Action:** Add `FillDiagnostic` dataclass to log per-fill:
- Best YES/NO bids at entry and exit
- Implied YES/NO asks
- Depth at those levels
- Planned vs actual size and average fill price

**Priority:** MEDIUM

---

### 6.3 Verify Spread/Depth Consistency

**Action:** Run a test suite that:
1. Creates a synthetic orderbook with known YES/NO levels
2. Passes it through unified edge, router, and risk layers
3. Verifies all layers compute the same spread and depth values

**Priority:** HIGH

---

### 6.4 Add Depth-Aware Order Splitting

**Action:** Implement logic in router to:
1. Check if order size > depth at best bid/ask
2. If yes, split into smaller child orders within depth guardrails
3. Log split decisions for observability

**Priority:** MEDIUM

---

### 6.5 Add Risk Cap vs Depth Min Logic

**Action:** Implement `min(risk_cap_size, depth_limited_size)` logic in unified edge to ensure the smaller constraint always wins.

**Priority:** MEDIUM

---

## 7) Test Plan

### 7.1 Unit Tests

1. **OrderBookSnapshot Consistency Test**
   - Create same orderbook in all three formats
   - Verify spread/depth calculations match
   - Verify YES/NO duality is applied correctly

2. **Spread Calculation Test**
   - Test spread calculation for YES and NO sides
   - Verify effective spread = crossing cost - mark-to-market
   - Test edge cases (wide spread, narrow spread)

3. **Depth Calculation Test**
   - Test L1 depth (best bid/ask size)
   - Test L2 depth (sum across price levels)
   - Verify depth aggregation logic

---

### 7.2 Integration Tests

1. **End-to-End Book Flow Test**
   - Simulate WS orderbook snapshot
   - Verify it flows through `LocalOrderbook` → `KalshiMarketState` → unified edge → router
   - Verify spread/depth values are consistent at each layer

2. **Entry-to-Exit Book Consistency Test**
   - Simulate trade entry with known book state
   - Simulate book updates during trade life
   - Verify exit logic uses same book interpretation

---

## 8) Open Questions

1. **Why does unified edge have its own `OrderBookSnapshot` instead of using `unified_market_state.OrderbookSnapshot`?**
   - This suggests a historical separation that should be consolidated.

2. **Why does liquidity monitor use `float` prices instead of `int` cents?**
   - This type inconsistency could cause precision issues.

3. **Should depth checks aggregate across price levels or use L1 only?**
   - Current implementation is L1-only, but L2 aggregation would allow more size.

4. **Should we implement depth-aware order splitting for large orders?**
   - This would improve fill rates for large sizes in thin markets.

---

## 9) Conclusion

**Overall Assessment:** The canonical `LocalOrderbook` implementation in `orderbook.py` correctly handles Kalshi's bid-only YES/NO duality. However, multiple downstream `OrderBookSnapshot` definitions create inconsistency risks.

**Critical Path:**
1. Consolidate to single canonical `OrderBookSnapshot` definition
2. Verify spread/depth calculations are consistent across all layers
3. Add fill-level diagnostics to catch discrepancies in production
4. Implement depth-aware order splitting and risk cap vs depth min logic

**Estimated Effort:** 2-3 days for consolidation and verification, 1-2 days for diagnostics and splitting logic.
