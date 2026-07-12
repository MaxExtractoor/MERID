# Orderbook Delta Flaw Detection Report

Generated: 2026-07-08 02:18:18
Tests Run: 18
Tests Passed: 18
Tests Failed: 0
Flaws Found: 57

## Flaws by Severity

### CRITICAL (1 flaws)

#### CROSSED_MARKET_INVARIANT

**Layer:** MIDSTREAM
**Description:** Crossed market detected: yes_bid=60c + no_bid=45c = 105c > 100c
**Location:** merid/event_venues/kalshi/orderbook.py:_check_crossed_market

**Evidence:**
```json
{
  "yes_bid": 60,
  "no_bid": 45,
  "sum": 105
}
```

---

### HIGH (3 flaws)

#### SEQUENCE_GAP_DETECTION

**Layer:** UPSTREAM
**Description:** Sequence gaps detected: [(4, 4), (7, 9)]
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "sequences": [
    1,
    2,
    3,
    5,
    6,
    10
  ],
  "gaps": [
    [
      4,
      4
    ],
    [
      7,
      9
    ]
  ]
}
```

---

#### PRICE_BOUNDARY_VALIDATION

**Layer:** MIDSTREAM
**Description:** Invalid price 0.5 (50c) was accepted
**Location:** merid/event_venues/kalshi/orderbook.py:apply_snapshot

**Evidence:**
```json
{
  "price_dollars": 0.5,
  "price_cents": 50
}
```

---

#### BID_ASK_DERIVATION

**Layer:** DOWNSTREAM
**Description:** Invalid NO price (0c) did not return None for best_ask
**Location:** merid/event_venues/kalshi/orderbook.py:get_best_ask

**Evidence:**
```json
{
  "no_price": 0,
  "best_ask": [
    99,
    10
  ]
}
```

---

### MEDIUM (53 flaws)

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8563302 < 1783491497.9434485
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 1,
  "current": 1783491497.8563302,
  "previous": 1783491497.9434485
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8402557 < 1783491497.8563302
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 2,
  "current": 1783491497.8402557,
  "previous": 1783491497.8563302
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8598304 < 1783491497.8858204
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 4,
  "current": 1783491497.8598304,
  "previous": 1783491497.8858204
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8132615 < 1783491497.886409
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 6,
  "current": 1783491497.8132615,
  "previous": 1783491497.886409
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8400178 < 1783491497.9396465
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 8,
  "current": 1783491497.8400178,
  "previous": 1783491497.9396465
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.9193904 < 1783491497.9215293
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 10,
  "current": 1783491497.9193904,
  "previous": 1783491497.9215293
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.9115372 < 1783491497.9490483
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 12,
  "current": 1783491497.9115372,
  "previous": 1783491497.9490483
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8900206 < 1783491497.9115372
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 13,
  "current": 1783491497.8900206,
  "previous": 1783491497.9115372
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8867335 < 1783491497.8900206
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 14,
  "current": 1783491497.8867335,
  "previous": 1783491497.8900206
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8439415 < 1783491497.8867335
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 15,
  "current": 1783491497.8439415,
  "previous": 1783491497.8867335
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.7959647 < 1783491497.9057539
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 18,
  "current": 1783491497.7959647,
  "previous": 1783491497.9057539
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.86202 < 1783491497.9885113
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 21,
  "current": 1783491497.86202,
  "previous": 1783491497.9885113
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8834689 < 1783491497.9922717
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 24,
  "current": 1783491497.8834689,
  "previous": 1783491497.9922717
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.976137 < 1783491497.9814613
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 26,
  "current": 1783491497.976137,
  "previous": 1783491497.9814613
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.9591246 < 1783491497.976137
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 27,
  "current": 1783491497.9591246,
  "previous": 1783491497.976137
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.894738 < 1783491497.986309
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 29,
  "current": 1783491497.894738,
  "previous": 1783491497.986309
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.9389727 < 1783491497.946297
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 31,
  "current": 1783491497.9389727,
  "previous": 1783491497.946297
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.92265 < 1783491497.9389727
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 32,
  "current": 1783491497.92265,
  "previous": 1783491497.9389727
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8428195 < 1783491497.92265
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 33,
  "current": 1783491497.8428195,
  "previous": 1783491497.92265
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.841772 < 1783491497.9689922
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 35,
  "current": 1783491497.841772,
  "previous": 1783491497.9689922
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.7979536 < 1783491497.841772
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 36,
  "current": 1783491497.7979536,
  "previous": 1783491497.841772
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8675911 < 1783491497.9471858
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 39,
  "current": 1783491497.8675911,
  "previous": 1783491497.9471858
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.9129503 < 1783491497.9170454
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 42,
  "current": 1783491497.9129503,
  "previous": 1783491497.9170454
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8718958 < 1783491497.9129503
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 43,
  "current": 1783491497.8718958,
  "previous": 1783491497.9129503
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8725812 < 1783491497.9626958
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 45,
  "current": 1783491497.8725812,
  "previous": 1783491497.9626958
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.823842 < 1783491497.8725812
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 46,
  "current": 1783491497.823842,
  "previous": 1783491497.8725812
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8563733 < 1783491497.970106
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 48,
  "current": 1783491497.8563733,
  "previous": 1783491497.970106
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8071735 < 1783491497.8563733
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 49,
  "current": 1783491497.8071735,
  "previous": 1783491497.8563733
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.9309707 < 1783491497.962223
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 51,
  "current": 1783491497.9309707,
  "previous": 1783491497.962223
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8772395 < 1783491497.9552217
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 53,
  "current": 1783491497.8772395,
  "previous": 1783491497.9552217
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8738308 < 1783491497.8772395
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 54,
  "current": 1783491497.8738308,
  "previous": 1783491497.8772395
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.9368706 < 1783491497.9917831
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 56,
  "current": 1783491497.9368706,
  "previous": 1783491497.9917831
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8051386 < 1783491497.9706316
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 58,
  "current": 1783491497.8051386,
  "previous": 1783491497.9706316
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8063946 < 1783491497.8845646
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 60,
  "current": 1783491497.8063946,
  "previous": 1783491497.8845646
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8292577 < 1783491497.9391344
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 64,
  "current": 1783491497.8292577,
  "previous": 1783491497.9391344
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.868793 < 1783491497.9820404
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 68,
  "current": 1783491497.868793,
  "previous": 1783491497.9820404
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8220634 < 1783491497.9262946
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 70,
  "current": 1783491497.8220634,
  "previous": 1783491497.9262946
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8287885 < 1783491497.9857876
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 73,
  "current": 1783491497.8287885,
  "previous": 1783491497.9857876
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.7938988 < 1783491497.949497
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 75,
  "current": 1783491497.7938988,
  "previous": 1783491497.949497
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.9112983 < 1783491497.9523907
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 77,
  "current": 1783491497.9112983,
  "previous": 1783491497.9523907
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8550856 < 1783491497.937402
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 79,
  "current": 1783491497.8550856,
  "previous": 1783491497.937402
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.9494915 < 1783491497.9743338
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 82,
  "current": 1783491497.9494915,
  "previous": 1783491497.9743338
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.869831 < 1783491497.9494915
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 83,
  "current": 1783491497.869831,
  "previous": 1783491497.9494915
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8382065 < 1783491497.869831
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 84,
  "current": 1783491497.8382065,
  "previous": 1783491497.869831
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.83724 < 1783491497.8382065
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 85,
  "current": 1783491497.83724,
  "previous": 1783491497.8382065
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.9259183 < 1783491497.9270873
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 87,
  "current": 1783491497.9259183,
  "previous": 1783491497.9270873
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8155358 < 1783491497.9259183
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 88,
  "current": 1783491497.8155358,
  "previous": 1783491497.9259183
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.9277158 < 1783491497.9383981
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 92,
  "current": 1783491497.9277158,
  "previous": 1783491497.9383981
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8202648 < 1783491497.9277158
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 93,
  "current": 1783491497.8202648,
  "previous": 1783491497.9277158
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.9238672 < 1783491497.9532883
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 95,
  "current": 1783491497.9238672,
  "previous": 1783491497.9532883
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.8601635 < 1783491497.9238672
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 96,
  "current": 1783491497.8601635,
  "previous": 1783491497.9238672
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491497.977457 < 1783491497.9795506
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 98,
  "current": 1783491497.977457,
  "previous": 1783491497.9795506
}
```

---

#### MESSAGE_DEDUPLICATION

**Layer:** UPSTREAM
**Description:** Duplicate delta messages are not being deduplicated
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "size_after_first": 15,
  "size_after_second": 20,
  "expected": 15
}
```

---

