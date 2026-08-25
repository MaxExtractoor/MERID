# Deterministic Replay-Test Proposal for Exit Order Validation

## Test Case: Confirmed Same-Leg Exit
Based on production fill: 83a4a457-5d2a-4a3d-214f-a4f331a6cbca

## Fixture Inputs

### Initial Position State
```python
initial_position = {
    'market_id': 'KXDOGE15M-26JUL130100-00',
    'signed_yes_exposure': 3,  # Long YES position
    'yes_qty': 0,
    'no_qty': -3,  # 3 SELL NO fills created NO leg
    'avg_price_cents': 41,  # YES price from entry
    'processed_fill_ids': {
        '004db561-c1b2-73bc-e074-dc990b4af514',
        '3898f341-725e-6654-e411-6542f0599500',
        '51ec625a-2ddb-6b01-2a84-32af77c5bc25'
    }
}
```

### Exit Fill Payload (Sanitized)
```python
exit_fill = {
    'fill_id': '83a4a457-5d2a-4a3d-214f-a4f331a6cbca',
    'order_id': '48e3c4c0-b847-4034-ac5c-8fa1b523e4cb',
    'market_ticker': 'KXDOGE15M-26JUL130100-00',
    'side': 'yes',
    'action': 'sell',
    'count_fp': 3,
    'yes_price_dollars': 0.41,
    'no_price_dollars': 0.59,
    'fee_cost': 0.02,
    'created_time': '2026-07-13T04:57:27.631519+00:00',
    'raw_payload': {
        'action': 'sell',
        'book_side': 'bid',
        'outcome_side': 'yes',
        'count_fp': '3.00',
        'yes_price_dollars': '0.41',
        'no_price_dollars': '0.59'
    }
}
```

### Deterministic Event Ordering Key
- Primary: `created_time` (ISO 8601 timestamp)
- Secondary: `fill_id` (UUID for tie-breaking)
- Tertiary: `order_id` (for same-timestamp fills)

## Assertions

### Post-Fill Inventory
```python
expected_post_state = {
    'signed_yes_exposure': 0,  # Position closed
    'yes_qty': -3,  # YES leg reduced by 3
    'no_qty': -3,  # NO leg unchanged
    'contracts': 0,  # Flat position
    'avg_price_cents': None  # No position = no cost basis
}
```

### Realized PnL
```python
expected_realized_pnl = {
    'gross_pnl': (0.41 - 0.41) * 3 = 0.00,  # Entry at 41c, exit at 41c
    'fees': 0.02,
    'net_pnl': -0.02  # Break-even minus fees
}
```

### Fee Posting
```python
expected_fee_posting = {
    'fee_cents': 2,
    'fee_type': 'taker',
    'fee_accounted': True
}
```

### Lot Consumption
```python
expected_lot_state = {
    'open_lots': [],  # All lots closed
    'lot_consumption': [
        {'lot_id': 'lot_1', 'consumed_qty': 1},
        {'lot_id': 'lot_2', 'consumed_qty': 1},
        {'lot_id': 'lot_3', 'consumed_qty': 1}
    ]
}
```

### Cache Version
```python
expected_cache_version = {
    'pre_version': 3,  # After 3 entry fills
    'post_version': 4,  # After exit fill
    'version_increment': 1
}
```

### Dedupe State
```python
expected_dedupe_state = {
    'processed_fill_ids': {
        '004db561-c1b2-73bc-e074-dc990b4af514',
        '3898f341-725e-6654-e411-6542f0599500',
        '51ec625a-2ddb-6b01-2a84-32af77c5bc25',
        '83a4a457-5d2a-4a3d-214f-a4f331a6cbca'  # Exit fill added
    },
    'duplicate_detection': True,
    'idempotency_key': '83a4a457-5d2a-4a3d-214f-a4f331a6cbca'
}
```

## Negative Cases

### 1. Duplicate Fill Replay
**Input:** Same exit fill processed twice
**Expected:** No state change on second processing
**Assertions:**
- Position remains flat (contracts=0)
- Realized PnL unchanged
- Fees not posted twice
- Cache version unchanged on second attempt

### 2. Partial Fill
**Input:** Exit fill with count=1 (partial close)
**Expected:** Position reduced but not closed
**Assertions:**
- Signed YES: 3 -> 2
- Contracts: 3 -> 2
- Realized PnL proportional to partial close
- Residual cost basis preserved

### 3. Out-of-Order Delivery
**Input:** Exit fill arrives before entry fills
**Expected:** Deferred or rejected processing
**Assertions:**
- Exit fill rejected (no position to close)
- Error logged: "Exit fill without corresponding entry"
- Position state unchanged
- Fill queued for reprocessing when entry arrives

### 4. Invalid Cross-Leg Exit
**Input:** SELL NO when position is long YES
**Expected:** Rejected per direction policy
**Assertions:**
- Fill rejected with DIRECTION-POLICY-BREACH error
- Position unchanged (long YES maintained)
- Rejection logged to audit trail
- No PnL or fee posting

### 5. Over-Close (Exit > Inventory)
**Input:** SELL YES with count=10 when position is 3
**Expected:** Rejected or explicit reversal
**Assertions:**
- Fill rejected (count > position)
- Position unchanged (3 contracts)
- Error logged: "Exit quantity exceeds position"
- No silent position flip

### 6. Restart/Replay
**Input:** System restart with in-flight exit fill
**Expected:** Idempotent reprocessing
**Assertions:**
- Fill deduplication prevents double-processing
- Final state matches expected post-state
- No duplicate PnL or fee postings
- Cache version consistency maintained

## Isolation Plan

### No Production Database Writes
- Use in-memory SQLite database for test
- All operations contained within test process
- No external database connections
- Test data cleaned up on completion

### No Live Kalshi Requests
- Mock all Kalshi API responses
- Use sanitized production payloads
- No network calls to Kalshi servers
- Test environment completely isolated

### No Shared Data-Directory Artifacts
- Test fixtures generated in-memory
- No file system pollution
- Temporary files cleaned up
- No shared state between test runs

### Deterministic Execution
- Fixed seed for random number generation
- Deterministic event ordering
- Reproducible test results
- No external dependencies on timing

## Implementation Notes

### Test Framework
- Use pytest for test structure
- Fixture-based test data management
- Parameterized tests for negative cases
- Comprehensive assertion coverage

### Mock Strategy
- Mock position cache methods
- Mock fills ledger database
- Mock Kalshi API client
- Preserve business logic, mock external dependencies

### Validation Strategy
- Compare actual vs expected state at each step
- Validate intermediate states, not just final state
- Check audit trail for correct logging
- Verify idempotency through repeated processing

### Success Criteria
- All positive case assertions pass
- All negative case rejections work correctly
- Idempotency verified for duplicate processing
- No side effects outside test environment
- Tests complete in reasonable time (< 5 seconds)
