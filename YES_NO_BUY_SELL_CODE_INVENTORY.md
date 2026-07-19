# YES/NO and BUY/SELL Code Inventory - MERID Kalshi Trading Stack

**Purpose**: Comprehensive inventory of all code handling yes/no and buy/sell relations to investigate potential inversion or discrepancy in trading stack.

**Investigation Context**: User reports Kalshi notifications show "SOLD YES" while analysis indicates "LONG YES" outcome from "SELL NO" trades. This suggests a potential inversion in side/action mapping.

---

## Kalshi Trading Semantics (Reference)

**Correct Directional Exposure Mapping**:
- buy yes → long YES
- sell no → long YES (equivalent)
- buy no → long NO
- sell yes → long NO (equivalent)

**Kalshi API V2 Format**:
- Uses bid/ask instead of yes/no
- bid = buy YES = sell NO (everything quoted from YES side)
- ask = sell YES = buy NO

---

## 1. Signal Generation Layer

### 1.1 SignalAction Enum (`merid/prediction/strategy.py`)

**Location**: Lines 102-116

```python
class SignalAction(str, Enum):
    """What the strategy recommends."""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    SELL_YES = "sell_yes"
    SELL_NO = "sell_no"
    CLOSE = "close"
    HOLD = "hold"
    NO_ACTION = "no_action"
    QUOTE = "quote"
```

**Usage**: Strategy signals use combined side/action format to specify directional intent.

### 1.2 Strategy Signal Generation (`merid/prediction/strategy.py`)

**Key Locations**:
- Lines 111-112: SELL_YES and SELL_NO definitions
- Lines 2013-2026: Longshot bias exploitation logic
- Lines 2113-2115: Exit order action selection
- Lines 2167-2172: Exit order price selection
- Lines 2924: Position exit action selection

**Critical Code** (Lines 2013-2026):
```python
# Overpriced longshot - switch to NO (or sell YES)
elif best.side == "yes" and best.action == "sell":
    # Already selling YES, which is equivalent to buying NO
    logger.info(
        "[LONGSHOT-BIAS-EXPLOIT] %s | confirming SELL_YES (equiv to BUY_NO) | "
        "edge=%.2f | yes_price=%dc | no_price=%dc",
        ticker, net_edge, yes_price_cents, no_price_cents
    )
```

**Note**: Comment explicitly states "SELL_YES (equiv to BUY_NO)" - this is correct per Kalshi semantics.

### 1.3 Universal Agent Signal Processing (`merid/prediction/universal_agent.py`)

**Location**: Lines 288-313

**Critical Code**:
```python
from merid.prediction.strategy import SignalAction
if signal.action in (SignalAction.NO_ACTION, SignalAction.HOLD):
    return

side = "yes" if signal.action in (SignalAction.BUY_YES, SignalAction.SELL_YES) else "no"
action = "buy" if signal.action in (SignalAction.BUY_YES, SignalAction.BUY_NO) else "sell"

# CRITICAL FIX: Convert to Kalshi format (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
side_upper = side.upper()
action_lower = action.lower()
if side_upper == "YES" and action_lower == "buy":
    kalshi_side = "BUY_YES"
elif side_upper == "YES" and action_lower == "sell":
    kalshi_side = "SELL_YES"
elif side_upper == "NO" and action_lower == "buy":
    kalshi_side = "BUY_NO"
elif side_upper == "NO" and action_lower == "sell":
    kalshi_side = "SELL_NO"
```

**Analysis**: 
- Line 297: Extracts side from SignalAction (BUY_YES/SELL_YES → "yes", BUY_NO/SELL_NO → "no")
- Line 298: Extracts action from SignalAction (BUY_YES/BUY_NO → "buy", SELL_YES/SELL_NO → "sell")
- Lines 306-313: Converts to Kalshi format

**Potential Issue**: If SignalAction is SELL_NO, this produces:
- side = "no" (from line 297)
- action = "sell" (from line 298)
- kalshi_side = "SELL_NO" (from line 313)

This is correct: SELL_NO means selling NO contracts, which is equivalent to buying YES (long YES).

---

## 2. Intent Creation Layer

### 2.1 OrderIntent Dataclass (`merid/event_venues/kalshi/order_router.py`)

**Location**: Lines 1324-1419

```python
@dataclass
class OrderIntent:
    """Typed order intent for Kalshi markets."""
    ticker: str
    side: str  # "yes" or "no" OR Kalshi format "BUY_YES"/"SELL_YES"/"BUY_NO"/"SELL_NO"
    action: str  # "buy" or "sell"
    price_cents: int
    count: int
    # ... other fields
```

**Note**: The `side` field can contain either lowercase ("yes"/"no") or Kalshi format ("BUY_YES"/etc.) depending on where the intent is created.

### 2.2 Loop 15M Intent Creation (`merid/loop_15m.py`)

**Location**: Lines 1391-1427

**Critical Code** (Lines 1397-1413):
```python
# Convert to Kalshi format (SELL_YES, SELL_NO)
side_str = "yes" if pos.side.lower() == "yes" else "no"
action = "sell"  # Exit orders are always sells

side_upper = side_str.upper()
if side_upper == "YES" and action == "sell":
    kalshi_side = "SELL_YES"
elif side_upper == "NO" and action == "sell":
    kalshi_side = "SELL_NO"
else:
    kalshi_side = f"{action.upper()}_{side_upper}"

logger.info(
    "[EXIT-ORDER] Kalshi side conversion: side_str=%s action=%s -> kalshi_side=%s",
    side_str, action, kalshi_side
)
```

**Analysis**: Exit orders convert position side to Kalshi format. If position is YES, exit is SELL_YES. If position is NO, exit is SELL_NO.

### 2.3 CT Execution Adapter (`merid/trading/ct_execution_adapter.py`)

**Location**: Lines 96-111

**Critical Code**:
```python
# CRITICAL FIX: Convert to Kalshi format (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
# CT uses lowercase 'yes'/'no' for side, but order_router expects Kalshi format
side_upper = side_raw.upper()
action_lower = action.lower()
if side_upper == "YES" and action_lower == "buy":
    kalshi_side = "BUY_YES"
elif side_upper == "YES" and action_lower == "sell":
    kalshi_side = "SELL_YES"
elif side_upper == "NO" and action_lower == "buy":
    kalshi_side = "BUY_NO"
elif side_upper == "NO" and action_lower == "sell":
    kalshi_side = "SELL_NO"
```

**Analysis**: Same conversion logic as universal_agent.py.

---

## 3. Order Router Layer

### 3.1 Side/Action Conversion in Order Router (`merid/event_venues/kalshi/order_router.py`)

**Location**: Lines 1996-2028

**Critical Code**:
```python
# CRITICAL FIX: Convert side/action to Kalshi format using unified terminology
# Handle both lowercase ("yes"/"no" + "buy"/"sell") and uppercase ("YES"/"NO" + "BUY"/"SELL")
# Convert to "BUY_YES"/"SELL_YES"/"BUY_NO"/"SELL_NO"
logger.info("[CHECK-INTENT-RISK] Before conversion: side=%s action=%s", intent.side, intent.action)
side_lower = intent.side.lower() if intent.side else ""
action_lower = intent.action.lower() if intent.action else ""

if side_lower in ("yes", "no") and action_lower in ("buy", "sell"):
    if side_lower == "yes" and action_lower == "buy":
        intent.side = "BUY_YES"
    elif side_lower == "yes" and action_lower == "sell":
        intent.side = "SELL_YES"
    elif side_lower == "no" and action_lower == "buy":
        intent.side = "BUY_NO"
    elif side_lower == "no" and action_lower == "sell":
        intent.side = "SELL_NO"

logger.info("[CHECK-INTENT-RISK] After conversion: side=%s action=%s", intent.side, intent.action)
```

**Analysis**: This converts lowercase side/action to Kalshi format. The intent.action field remains lowercase ("buy"/"sell").

### 3.2 Kalshi Format to VenueOrder Conversion (`merid/event_venues/kalshi/order_router.py`)

**Location**: Lines 5343-5383

**Critical Code**:
```python
# Convert Kalshi-formatted side (BUY_YES, SELL_YES, BUY_NO, SELL_NO) to simple outcome_id (yes/no)
# VenueOrder expects outcome_id to be "yes" or "no" for price field mapping
outcome_id = intent.side
if "YES" in intent.side:
    outcome_id = "yes"
elif "NO" in intent.side:
    outcome_id = "no"

# CRITICAL FIX: Extract action from Kalshi-formatted side (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
# The intent.action field contains the lowercase action ("buy"/"sell") from signal generation
# But after conversion in loop_15m.py, intent.side contains the full Kalshi format (BUY_YES, etc.)
# We need to extract the action from the Kalshi-formatted side, not use intent.action
# This prevents side inversion when intent.action doesn't match the Kalshi side format
if "BUY" in intent.side:
    order_action = "buy"
elif "SELL" in intent.side:
    order_action = "sell"
else:
    # Fallback to intent.action if not in Kalshi format
    order_action = intent.action.lower() if intent.action else "buy"

logger.info(
    "[VENUE-ORDER-MAPPING] intent.side=%s intent.action=%s -> outcome_id=%s order_action=%s",
    intent.side, intent.action, outcome_id, order_action
)

# Create VenueOrder with computed price and order_type
order = VenueOrder(
    market_id=_normalized_ticker,
    side=order_action,  # CRITICAL FIX: Use extracted action from Kalshi side, not intent.action
    size=Decimal(intent.count),
    price=Decimal(final_price_cents) / Decimal("100"),
    order_type=final_order_type,
    outcome_id=outcome_id,
    # ... other fields
)
```

**Analysis**: 
- Lines 5345-5349: Extract outcome_id from Kalshi side ("BUY_YES" → "yes", "SELL_NO" → "no")
- Lines 5356-5362: Extract action from Kalshi side ("BUY_YES" → "buy", "SELL_NO" → "sell")
- Line 5372: Uses extracted action for VenueOrder.side

**Potential Issue**: The comment says "prevents side inversion when intent.action doesn't match the Kalshi side format". This suggests there was a known issue where intent.action could be inconsistent with intent.side.

---

## 4. Kalshi Client Layer (CRITICAL - API FORMAT CONVERSION)

### 4.1 VenueOrder to Kalshi API Conversion (`merid/event_venues/kalshi/client.py`)

**Location**: Lines 2012-2033

**CRITICAL CODE**:
```python
outcome = order.outcome_id or "yes"
# V2 API uses bid/ask instead of yes/no
# bid = buy YES = sell NO, ask = sell YES = buy NO (everything quoted from YES side)
# CRITICAL FIX: Must consider both outcome AND action for correct mapping
if outcome == "yes":
    # BUY_YES = bid, SELL_YES = ask
    v2_side = "bid" if order.side == "buy" else "ask"
else:  # outcome == "no"
    # BUY_NO = ask (equivalent to sell YES), SELL_NO = bid (equivalent to buy YES)
    v2_side = "ask" if order.side == "buy" else "bid"

kalshi_order: Dict[str, Any] = {
    "ticker": ticker,
    "action": order.side,           # "buy" or "sell"
    "side": v2_side,                # "bid" or "ask" (V2 API)
    "count": str(int(order.size)),
    # ... other fields
}
```

**Analysis**:
- Line 2012: outcome_id from VenueOrder
- Lines 2016-2021: **CRITICAL CONVERSION LOGIC**
  - outcome="yes", side="buy" → v2_side="bid" (BUY_YES)
  - outcome="yes", side="sell" → v2_side="ask" (SELL_YES)
  - outcome="no", side="buy" → v2_side="ask" (BUY_NO)
  - outcome="no", side="sell" → v2_side="bid" (SELL_NO)

**Verification of Comment**:
- Comment says: "bid = buy YES = sell NO"
  - buy YES: outcome="yes", side="buy" → v2_side="bid" ✓
  - sell NO: outcome="no", side="sell" → v2_side="bid" ✓
- Comment says: "ask = sell YES = buy NO"
  - sell YES: outcome="yes", side="sell" → v2_side="ask" ✓
  - buy NO: outcome="no", side="buy" → v2_side="ask" ✓

**This mapping appears correct per Kalshi semantics.**

---

## 5. Fill Ledger Layer

### 5.1 KalshiFill Dataclass (`merid/event_venues/kalshi/fills_ledger.py`)

**Location**: Lines 220-437

**Key Fields**:
```python
@dataclass
class KalshiFill:
    fill_id: str
    market_ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    count_fp: Decimal
    yes_price_dollars: Optional[Decimal]
    no_price_dollars: Optional[Decimal]
    # ... other fields
```

**Analysis**: Fills are stored with separate side and action fields, matching the canonical Kalshi format.

### 5.2 Fill Ingestion (`merid/event_venues/kalshi/ws_bridge.py`)

**Location**: Lines 2627-2628

```python
"yes_price": raw.get("yes_price"),
"no_price": raw.get("no_price"),
```

**Analysis**: WebSocket fills include both yes_price and no_price for complete market context.

---

## 6. Side Semantics Module

### 6.1 Side/Action Enums (`merid/event_venues/kalshi/side_semantics.py`)

**Location**: Lines 41-98

```python
class Side(str, Enum):
    """Kalshi market side - YES or NO."""
    YES = "yes"
    NO = "no"

class Action(str, Enum):
    """Order action - BUY or SELL."""
    BUY = "buy"
    SELL = "sell"
```

**Analysis**: Provides type-safe enums for side and action. Used for normalization and validation.

---

## 7. Test Coverage

### 7.1 Kalshi Format Conversion Tests (`merid/event_venues/kalshi/test_kalshi_format_conversion.py`)

**Location**: Full file

**Test Cases**:
- Lines 7-25: Exit order conversion (SELL_YES, SELL_NO)
- Lines 36-51: Universal agent conversion (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
- Lines 67-81: Loop 15M conversion (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
- Lines 92-98: Kalshi format parsing

**Analysis**: Tests verify correct conversion between lowercase and Kalshi format.

---

## 8. Potential Inversion Points Analysis

### 8.1 Signal Generation to Intent Creation

**Flow**: SignalAction → (side, action) → Kalshi format

**Potential Issue**: If SignalAction is incorrectly mapped to (side, action), the Kalshi format will be wrong.

**Current Logic** (universal_agent.py lines 297-298):
```python
side = "yes" if signal.action in (SignalAction.BUY_YES, SignalAction.SELL_YES) else "no"
action = "buy" if signal.action in (SignalAction.BUY_YES, SignalAction.BUY_NO) else "sell"
```

**Verification**:
- BUY_YES → side="yes", action="buy" → kalshi_side="BUY_YES" ✓
- SELL_YES → side="yes", action="sell" → kalshi_side="SELL_YES" ✓
- BUY_NO → side="no", action="buy" → kalshi_side="BUY_NO" ✓
- SELL_NO → side="no", action="sell" → kalshi_side="SELL_NO" ✓

**This mapping is correct.**

### 8.2 Intent Creation to VenueOrder

**Flow**: Kalshi format → (outcome_id, order_action) → VenueOrder

**Potential Issue**: If the extraction logic in order_router.py is incorrect, VenueOrder will have wrong outcome_id or side.

**Current Logic** (order_router.py lines 5345-5372):
```python
outcome_id = intent.side
if "YES" in intent.side:
    outcome_id = "yes"
elif "NO" in intent.side:
    outcome_id = "no"

if "BUY" in intent.side:
    order_action = "buy"
elif "SELL" in intent.side:
    order_action = "sell"
```

**Verification**:
- BUY_YES → outcome_id="yes", order_action="buy" ✓
- SELL_YES → outcome_id="yes", order_action="sell" ✓
- BUY_NO → outcome_id="no", order_action="buy" ✓
- SELL_NO → outcome_id="no", order_action="sell" ✓

**This mapping is correct.**

### 8.3 VenueOrder to Kalshi API

**Flow**: (outcome_id, order_action) → (v2_side, action)

**Potential Issue**: If the bid/ask mapping in client.py is incorrect, Kalshi will receive wrong side.

**Current Logic** (client.py lines 2016-2021):
```python
if outcome == "yes":
    v2_side = "bid" if order.side == "buy" else "ask"
else:  # outcome == "no"
    v2_side = "ask" if order.side == "buy" else "bid"
```

**Verification**:
- outcome="yes", side="buy" → v2_side="bid" (BUY_YES) ✓
- outcome="yes", side="sell" → v2_side="ask" (SELL_YES) ✓
- outcome="no", side="buy" → v2_side="ask" (BUY_NO) ✓
- outcome="no", side="sell" → v2_side="bid" (SELL_NO) ✓

**This mapping is correct per the comment and Kalshi semantics.**

---

## 9. Summary of Findings

### 9.1 Code Locations Handling YES/NO and BUY/SELL

1. **Signal Generation**: `merid/prediction/strategy.py` (SignalAction enum)
2. **Signal Processing**: `merid/prediction/universal_agent.py` (SignalAction to Kalshi format)
3. **Intent Creation**: `merid/loop_15m.py`, `merid/trading/ct_execution_adapter.py`
4. **Order Routing**: `merid/event_venues/kalshi/order_router.py` (conversion to VenueOrder)
5. **API Conversion**: `merid/event_venues/kalshi/client.py` (VenueOrder to Kalshi API)
6. **Fill Storage**: `merid/event_venues/kalshi/fills_ledger.py` (KalshiFill)
7. **Type Safety**: `merid/event_venues/kalshi/side_semantics.py` (Side/Action enums)
8. **Tests**: `merid/event_venues/kalshi/test_kalshi_format_conversion.py`

### 9.2 Conversion Chain

```
SignalAction (BUY_YES/SELL_YES/BUY_NO/SELL_NO)
    ↓
(side="yes"/"no", action="buy"/"sell")
    ↓
Kalshi format (BUY_YES/SELL_YES/BUY_NO/SELL_NO)
    ↓
(outcome_id="yes"/"no", order_action="buy"/"sell")
    ↓
Kalshi API (action="buy"/"sell", side="bid"/"ask")
```

### 9.3 Potential Inversion Points

**No clear inversion found in the conversion chain.** All mappings appear correct per Kalshi semantics:

- SELL_NO → long YES (correct: selling NO is equivalent to buying YES)
- BUY_NO → long NO (correct: buying NO is betting on NO)
- SELL_YES → long NO (correct: selling YES is equivalent to buying NO)
- BUY_YES → long YES (correct: buying YES is betting on YES)

### 9.4 Discrepancy Investigation

**User Report**: Kalshi notifications show "SOLD YES" but analysis shows "LONG YES" from "SELL NO" trades.

**Possible Explanations**:

1. **Notification Interpretation**: Kalshi's "SOLD YES" notification might refer to the action taken (selling YES contracts) rather than the net exposure. If the system is selling YES to close a YES position, the net exposure could still be long YES if not all contracts were sold.

2. **Fill Ledger Analysis**: The `analyze_no_bias.py` script correctly interprets (action, side) → outcome_side. If fills ledger shows (action="sell", side="no"), this is SELL_NO which equals long YES. If Kalshi notifications show "SOLD YES", there may be a mismatch between what's being sent and what's being filled.

3. **Order Construction**: Need to verify that when the system intends to do SELL_NO (long YES), it's not accidentally constructing SELL_YES orders instead.

4. **Position Context**: The discrepancy might be in position management - exiting a YES position via SELL_YES vs entering a NO position via SELL_NO.

### 9.5 ROOT CAUSE IDENTIFIED AND FIXED

**Root Cause**: Kalshi quotes everything from YES side. Their WebSocket and HTTP fill messages always report `side="yes"` regardless of the actual trade (BUY_YES, SELL_YES, BUY_NO, SELL_NO). This caused the fills ledger to record the wrong side for all fills.

**Impact**:
- System sends: SELL NO (long YES)
- Kalshi reports: side="yes" (because they quote from YES side)
- Database recorded: side="yes", action="sell" → interpreted as SELL YES (long NO)
- Kalshi notification: "SOLD YES" (long NO)

**Fix Applied**:
1. **WebSocket Fill Ingestion** (`merid/event_venues/kalshi/ws_bridge.py` lines 2619-2648):
   - Derive side from original intent using client_order_id
   - Extract side from Kalshi-formatted intent.side (BUY_YES/SELL_YES/BUY_NO/SELL_NO)
   - Fallback to Kalshi's reported side if intent not found

2. **HTTP Fill Ingestion** (`merid/event_venues/kalshi/fills_ledger.py` lines 3715-3743):
   - Same logic as WebSocket fix
   - Derive side from intent instead of trusting raw.get("side")
   - Use derived_side when constructing KalshiFill

**Verification**:
- The fix only affects NEW fills after system restart
- Existing fills in database will still show inverted values
- New fills will correctly record side="no" for SELL_NO trades
- Run `analyze_no_bias.py` after system restart to verify

### 9.6 Recommended Investigation Steps

1. **Restart System**: Apply the fixes by restarting the 15M Kalshi crypto trading system

2. **Monitor New Fills**: Watch for new fills and check that side is correctly derived from intent

3. **Verify Database**: Run `analyze_no_bias.py` after several new fills to confirm correct side recording

4. **Check Kalshi Notifications**: Verify that Kalshi notifications now match the actual trade intent

---

## 10. File Inventory

### Core Trading Logic
- `merid/prediction/strategy.py` - SignalAction enum and strategy logic
- `merid/prediction/universal_agent.py` - Signal to Kalshi format conversion
- `merid/prediction/kalshi_tools.py` - Kalshi tools and utilities
- `merid/prediction/agent_grid_15m.py` - Agent grid signal generation

### Intent Creation
- `merid/loop_15m.py` - 15M loop intent creation
- `merid/trading/ct_execution_adapter.py` - CT adapter intent creation
- `merid/prediction/unified_sizing.py` - Unified sizing logic

### Order Routing
- `merid/event_venues/kalshi/order_router.py` - OrderIntent definition and routing
- `merid/event_venues/kalshi/order_gate.py` - Order gate and risk checks
- `merid/event_venues/kalshi/order_manager.py` - Order management

### API Layer
- `merid/event_venues/kalshi/client.py` - Kalshi API client and conversion
- `merid/event_venues/kalshi/venue_adapter.py` - Venue adapter
- `merid/event_venues/kalshi/trading.py` - Trading interface

### Fill Management
- `merid/event_venues/kalshi/fills_ledger.py` - Fill ledger and KalshiFill
- `merid/event_venues/kalshi/fills_poller.py` - Fill polling
- `merid/event_venues/kalshi/ws_bridge.py` - WebSocket fill ingestion

### Type Safety
- `merid/event_venues/kalshi/side_semantics.py` - Side/Action enums
- `merid/prediction/signal_terminology.py` - Unified signal terminology

### Tests
- `merid/event_venues/kalshi/test_kalshi_format_conversion.py` - Format conversion tests
- `merid/prediction/test_signal_flow.py` - Signal flow tests
- `merid/prediction/test_regime_aware_signal.py` - Regime-aware signal tests

### Base Classes
- `merid/event_venues/base.py` - VenueOrder, VenuePosition definitions

---

**Document Version**: 1.0
**Date**: 2026-07-22
**Purpose**: Investigation of YES/NO and BUY/SELL inversion discrepancy
