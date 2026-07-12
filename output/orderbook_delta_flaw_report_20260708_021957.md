# Orderbook Delta Flaw Detection Report

Generated: 2026-07-08 02:19:57
Tests Run: 18
Tests Passed: 18
Tests Failed: 0
Flaws Found: 48

## Flaws by Severity

### HIGH (1 flaws)

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

### MEDIUM (47 flaws)

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7085707 < 1783491596.7172263
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 1,
  "current": 1783491596.7085707,
  "previous": 1783491596.7172263
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.8083136 < 1783491596.8394773
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 4,
  "current": 1783491596.8083136,
  "previous": 1783491596.8394773
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7189445 < 1783491596.8499353
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 6,
  "current": 1783491596.7189445,
  "previous": 1783491596.8499353
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.751002 < 1783491596.753268
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 8,
  "current": 1783491596.751002,
  "previous": 1783491596.753268
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.684414 < 1783491596.7610753
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 10,
  "current": 1783491596.684414,
  "previous": 1783491596.7610753
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7774625 < 1783491596.8295789
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 12,
  "current": 1783491596.7774625,
  "previous": 1783491596.8295789
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7026508 < 1783491596.7774625
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 13,
  "current": 1783491596.7026508,
  "previous": 1783491596.7774625
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7146893 < 1783491596.7524357
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 15,
  "current": 1783491596.7146893,
  "previous": 1783491596.7524357
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6930451 < 1783491596.7146893
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 16,
  "current": 1783491596.6930451,
  "previous": 1783491596.7146893
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7028666 < 1783491596.8134673
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 20,
  "current": 1783491596.7028666,
  "previous": 1783491596.8134673
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.712213 < 1783491596.7753124
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 22,
  "current": 1783491596.712213,
  "previous": 1783491596.7753124
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7313123 < 1783491596.7971303
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 24,
  "current": 1783491596.7313123,
  "previous": 1783491596.7971303
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7148328 < 1783491596.7313123
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 25,
  "current": 1783491596.7148328,
  "previous": 1783491596.7313123
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7481241 < 1783491596.8291698
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 27,
  "current": 1783491596.7481241,
  "previous": 1783491596.8291698
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7870471 < 1783491596.7929604
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 29,
  "current": 1783491596.7870471,
  "previous": 1783491596.7929604
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6762228 < 1783491596.7870471
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 30,
  "current": 1783491596.6762228,
  "previous": 1783491596.7870471
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6934276 < 1783491596.75044
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 32,
  "current": 1783491596.6934276,
  "previous": 1783491596.75044
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6696672 < 1783491596.7754838
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 34,
  "current": 1783491596.6696672,
  "previous": 1783491596.7754838
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.686546 < 1783491596.8068388
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 38,
  "current": 1783491596.686546,
  "previous": 1783491596.8068388
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6729634 < 1783491596.686546
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 39,
  "current": 1783491596.6729634,
  "previous": 1783491596.686546
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6991067 < 1783491596.842013
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 41,
  "current": 1783491596.6991067,
  "previous": 1783491596.842013
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6933053 < 1783491596.6991067
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 42,
  "current": 1783491596.6933053,
  "previous": 1783491596.6991067
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.67037 < 1783491596.6933053
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 43,
  "current": 1783491596.67037,
  "previous": 1783491596.6933053
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7968879 < 1783491596.8025112
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 48,
  "current": 1783491596.7968879,
  "previous": 1783491596.8025112
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.836199 < 1783491596.8539245
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 51,
  "current": 1783491596.836199,
  "previous": 1783491596.8539245
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7181756 < 1783491596.836199
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 52,
  "current": 1783491596.7181756,
  "previous": 1783491596.836199
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7159576 < 1783491596.7181756
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 53,
  "current": 1783491596.7159576,
  "previous": 1783491596.7181756
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.8343053 < 1783491596.838683
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 56,
  "current": 1783491596.8343053,
  "previous": 1783491596.838683
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.8044472 < 1783491596.8343053
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 57,
  "current": 1783491596.8044472,
  "previous": 1783491596.8343053
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7652576 < 1783491596.8044472
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 58,
  "current": 1783491596.7652576,
  "previous": 1783491596.8044472
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6947443 < 1783491596.7925987
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 60,
  "current": 1783491596.6947443,
  "previous": 1783491596.7925987
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6655219 < 1783491596.8439102
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 65,
  "current": 1783491596.6655219,
  "previous": 1783491596.8439102
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7569442 < 1783491596.849193
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 68,
  "current": 1783491596.7569442,
  "previous": 1783491596.849193
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.845718 < 1783491596.8535247
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 71,
  "current": 1783491596.845718,
  "previous": 1783491596.8535247
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.753462 < 1783491596.845718
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 72,
  "current": 1783491596.753462,
  "previous": 1783491596.845718
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7462728 < 1783491596.8493776
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 75,
  "current": 1783491596.7462728,
  "previous": 1783491596.8493776
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6672359 < 1783491596.7462728
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 76,
  "current": 1783491596.6672359,
  "previous": 1783491596.7462728
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6747777 < 1783491596.8427875
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 79,
  "current": 1783491596.6747777,
  "previous": 1783491596.8427875
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.8088121 < 1783491596.8129413
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 81,
  "current": 1783491596.8088121,
  "previous": 1783491596.8129413
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.772106 < 1783491596.8088121
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 82,
  "current": 1783491596.772106,
  "previous": 1783491596.8088121
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6908286 < 1783491596.7913578
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 84,
  "current": 1783491596.6908286,
  "previous": 1783491596.7913578
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6830542 < 1783491596.7128096
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 86,
  "current": 1783491596.6830542,
  "previous": 1783491596.7128096
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7726607 < 1783491596.836482
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 88,
  "current": 1783491596.7726607,
  "previous": 1783491596.836482
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7701342 < 1783491596.7726607
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 89,
  "current": 1783491596.7701342,
  "previous": 1783491596.7726607
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.7131886 < 1783491596.7701342
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 90,
  "current": 1783491596.7131886,
  "previous": 1783491596.7701342
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.67663 < 1783491596.7131886
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 91,
  "current": 1783491596.67663,
  "previous": 1783491596.7131886
}
```

---

#### TIMESTAMP_MONOTONICITY

**Layer:** UPSTREAM
**Description:** Non-monotonic timestamp detected: 1783491596.6659586 < 1783491596.8099675
**Location:** WebSocket message processing

**Evidence:**
```json
{
  "index": 97,
  "current": 1783491596.6659586,
  "previous": 1783491596.8099675
}
```

---

