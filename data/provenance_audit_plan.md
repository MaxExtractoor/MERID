# Read-Only Historical Provenance Audit Plan

## Objective
Identify one confirmed same-leg exit from the fills ledger using read-only analysis.

## Audit Methodology

### Step 1: Identify Candidate Normalized SELL Fills
- Query fills ledger for `action='sell'` fills
- Extract: fill_id, order_id, client_order_id, market_ticker, side, action, count
- Sort by created_time to establish chronological order

### Step 2: Reconstruct Complete Per-Ticker Fill History
- For each candidate ticker, get ALL fills from ledger (not just recent window)
- Group by market_ticker and sort by created_time
- Calculate cumulative position deltas using signed YES exposure

### Step 3: Determine Cache State Before Each Candidate
- Reconstruct position state by processing fills in chronological order
- For each candidate fill, calculate:
  - Pre-fill position: per-leg quantity, cost basis, open lots
  - Expected post-fill position if applied
  - Whether fill would be valid per direction policy

### Step 4: Locate Original Order Intent
- Match fills to order intents using client_order_id or order_id
- Classify intent as: ENTRY, EXIT, HEDGE, REBALANCE, or unclassified
- Check intent metadata for explicit direction classification

### Step 5: Report Cache Behavior
- Determine if fill was: applied, rejected, deduplicated, or deferred
- Provide exact reason/log evidence from fills ledger
- Cross-reference with position cache logs if available

## Classification Criteria

- **Confirmed same-leg exit**: 
  - Pre-fill position exists on same leg (side)
  - Fill quantity ≤ pre-fill quantity
  - Post-fill position ≥ 0
  - Intent classified as EXIT

- **Confirmed independent entry**:
  - Pre-fill position is zero
  - Fill opens new position
  - Intent classified as ENTRY

- **Rejected invalid cross-leg exit**:
  - Pre-fill position exists on opposite leg
  - Fill would violate direction policy
  - Evidence of rejection in logs

- **Reversal**:
  - Fill quantity > pre-fill quantity
  - Position would cross through zero
  - Explicit reversal authorization present

- **Unresolved**:
  - Insufficient evidence for classification
  - Missing intent linkage
  - Ambiguous position state

## Audit Output Format

For each candidate fill:
```
Fill ID: {fill_id}
Order ID: {order_id}
Client Order ID: {client_order_id}
Ticker: {market_ticker}
Normalized: side={side}, action={sell}, count={count}
Raw API: action={raw_action}, book_side={book_side}, outcome_side={outcome_side}

Pre-fill Position:
  YES qty: {yes_qty}, NO qty: {no_qty}
  Cost basis: {avg_cost_cents}
  Open lots: {lot_details}

Intent Classification: {ENTRY/EXIT/HEDGE/REBALANCE/UNCLASSIFIED}
Intent Evidence: {intent_metadata}

Cache Behavior: {APPLIED/REJECTED/DEDUPLICATED/DEFERRED}
Reason: {exact_reason}
Log Evidence: {log_snippet}

Final Classification: {CONFIRMED_SAME_LEG_EXIT/CONFIRMED_INDEPENDENT_ENTRY/REJECTED_CROSS_LEGIT/REVERSAL/UNRESOLVED}
```

## Isolation Guarantees

- Read-only operations only (no database writes)
- No live Kalshi API requests
- No modification of production data
- No shared data-directory artifacts
- Only queries existing fills ledger database
