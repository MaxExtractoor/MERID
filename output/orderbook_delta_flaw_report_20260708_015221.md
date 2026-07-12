# Orderbook Delta Flaw Detection Report

Generated: 2026-07-08 01:52:21
Tests Run: 18
Tests Passed: 18
Tests Failed: 0
Flaws Found: 52

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

### MEDIUM (48 flaws)

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.3329544 < 1783489941.383549
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 2,
  "current": 1783489941.3329544,
  "previous": 1783489941.383549
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.262615 < 1783489941.3607187
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 4,
  "current": 1783489941.262615,
  "previous": 1783489941.3607187
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2053912 < 1783489941.262615
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 5,
  "current": 1783489941.2053912,
  "previous": 1783489941.262615
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2855978 < 1783489941.369126
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 7,
  "current": 1783489941.2855978,
  "previous": 1783489941.369126
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.3246489 < 1783489941.3567564
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 9,
  "current": 1783489941.3246489,
  "previous": 1783489941.3567564
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.207849 < 1783489941.3876994
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 11,
  "current": 1783489941.207849,
  "previous": 1783489941.3876994
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2081954 < 1783489941.301377
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 14,
  "current": 1783489941.2081954,
  "previous": 1783489941.301377
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2818565 < 1783489941.2873676
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 16,
  "current": 1783489941.2818565,
  "previous": 1783489941.2873676
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2718024 < 1783489941.2907782
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 18,
  "current": 1783489941.2718024,
  "previous": 1783489941.2907782
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2488995 < 1783489941.2991214
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 20,
  "current": 1783489941.2488995,
  "previous": 1783489941.2991214
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.347024 < 1783489941.3661788
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 22,
  "current": 1783489941.347024,
  "previous": 1783489941.3661788
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2122643 < 1783489941.347024
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 23,
  "current": 1783489941.2122643,
  "previous": 1783489941.347024
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.3182418 < 1783489941.32787
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 25,
  "current": 1783489941.3182418,
  "previous": 1783489941.32787
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2943954 < 1783489941.3182418
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 26,
  "current": 1783489941.2943954,
  "previous": 1783489941.3182418
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2657351 < 1783489941.2943954
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 27,
  "current": 1783489941.2657351,
  "previous": 1783489941.2943954
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.241877 < 1783489941.2874744
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 29,
  "current": 1783489941.241877,
  "previous": 1783489941.2874744
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.230261 < 1783489941.2850018
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 31,
  "current": 1783489941.230261,
  "previous": 1783489941.2850018
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2517288 < 1783489941.349596
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 34,
  "current": 1783489941.2517288,
  "previous": 1783489941.349596
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2554314 < 1783489941.3861117
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 36,
  "current": 1783489941.2554314,
  "previous": 1783489941.3861117
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.297938 < 1783489941.3602962
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 39,
  "current": 1783489941.297938,
  "previous": 1783489941.3602962
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2213619 < 1783489941.297938
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 40,
  "current": 1783489941.2213619,
  "previous": 1783489941.297938
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.321755 < 1783489941.3772607
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 42,
  "current": 1783489941.321755,
  "previous": 1783489941.3772607
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.257834 < 1783489941.321755
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 43,
  "current": 1783489941.257834,
  "previous": 1783489941.321755
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2422457 < 1783489941.257834
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 44,
  "current": 1783489941.2422457,
  "previous": 1783489941.257834
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2142015 < 1783489941.2422457
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 45,
  "current": 1783489941.2142015,
  "previous": 1783489941.2422457
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.3062 < 1783489941.33665
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 48,
  "current": 1783489941.3062,
  "previous": 1783489941.33665
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2863307 < 1783489941.3062
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 49,
  "current": 1783489941.2863307,
  "previous": 1783489941.3062
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2901518 < 1783489941.3346329
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 51,
  "current": 1783489941.2901518,
  "previous": 1783489941.3346329
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.3029253 < 1783489941.3521116
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 53,
  "current": 1783489941.3029253,
  "previous": 1783489941.3521116
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2209868 < 1783489941.379869
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 55,
  "current": 1783489941.2209868,
  "previous": 1783489941.379869
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.3250577 < 1783489941.352902
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 57,
  "current": 1783489941.3250577,
  "previous": 1783489941.352902
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2395895 < 1783489941.3250577
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 58,
  "current": 1783489941.2395895,
  "previous": 1783489941.3250577
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.1999624 < 1783489941.382731
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 62,
  "current": 1783489941.1999624,
  "previous": 1783489941.382731
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.3186276 < 1783489941.3897598
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 67,
  "current": 1783489941.3186276,
  "previous": 1783489941.3897598
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2029068 < 1783489941.323505
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 70,
  "current": 1783489941.2029068,
  "previous": 1783489941.323505
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2437055 < 1783489941.2949295
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 74,
  "current": 1783489941.2437055,
  "previous": 1783489941.2949295
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.3374631 < 1783489941.3659742
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 77,
  "current": 1783489941.3374631,
  "previous": 1783489941.3659742
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.3306413 < 1783489941.3374631
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 78,
  "current": 1783489941.3306413,
  "previous": 1783489941.3374631
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.258291 < 1783489941.3306413
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 79,
  "current": 1783489941.258291,
  "previous": 1783489941.3306413
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.323446 < 1783489941.3581285
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 82,
  "current": 1783489941.323446,
  "previous": 1783489941.3581285
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2602675 < 1783489941.323446
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 83,
  "current": 1783489941.2602675,
  "previous": 1783489941.323446
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.231612 < 1783489941.384777
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 86,
  "current": 1783489941.231612,
  "previous": 1783489941.384777
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2039173 < 1783489941.3813696
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 88,
  "current": 1783489941.2039173,
  "previous": 1783489941.3813696
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.3172038 < 1783489941.3308764
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 91,
  "current": 1783489941.3172038,
  "previous": 1783489941.3308764
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2240925 < 1783489941.3268533
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 93,
  "current": 1783489941.2240925,
  "previous": 1783489941.3268533
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.274041 < 1783489941.3114548
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 96,
  "current": 1783489941.274041,
  "previous": 1783489941.3114548
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783489941.2201111 < 1783489941.2943988
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 98,
  "current": 1783489941.2201111,
  "previous": 1783489941.2943988
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

