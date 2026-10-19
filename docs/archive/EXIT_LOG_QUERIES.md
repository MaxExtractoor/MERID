# Exit Decision Log Queries

This document provides predefined log queries for analyzing exit decisions in the Kalshi 15-minute crypto trading system.

## Log Schema

### EXIT-INTENT Logs (position_monitor)
```
[EXIT-INTENT] position=%s market=%s side=%s reason=%s priority=%d source=%s 
exit_price=%dc entry_price=%dc pnl=%dc R=%.2f size=%d type=FULL_EXIT|PARTIAL_EXIT
```

### EXIT-RESOLVER Logs (exit_resolver)
```
[EXIT-RESOLVER] position=%s reason=%s priority=%d source=%s from [%s]
```

### STALE_DATA Special Logging
```
[EXIT-RESOLVER] STALE_DATA exit: position=%s md_age_ms=%s max_age_ms=%s 
time_to_expiry=%s metadata=%s
```

### EXIT-POLICY-RESOLVER Logs
```
[EXIT-POLICY-RESOLVER] position=%s reason=%s priority=%d source=%s R=%.2f metadata=%s
```

## Predefined Queries

### 1. All Exits by Reason (Last N Windows)
**Purpose:** Understand which exit reasons are most frequently triggered.

**Query (grep):**
```bash
grep "\[EXIT-INTENT\]" logs/*.log | grep "reason=" | \
  sed 's/.*reason=\([^ ]*\).*/\1/' | sort | uniq -c | sort -rn
```

**Query (PowerShell):**
```powershell
Select-String -Path "logs\*.log" -Pattern "\[EXIT-INTENT\]" | 
  Select-String -Pattern "reason=" | 
  ForEach-Object { $_.Line -match 'reason=([a-z_]+)' | Out-Null; $matches[1] } | 
  Group-Object | Sort-Object Count -Descending
```

**Expected Output:**
```
reason          count
----            -----
time_stop       45
edge_decay      23
stale_data      12
risk            5
candle_reversal 3
```

### 2. STALE_DATA Exits with MD Age > SLA
**Purpose:** Identify when market data staleness is causing exits and whether SLA thresholds are appropriate.

**Query (grep):**
```bash
grep "STALE_DATA exit" logs/*.log | \
  awk '{print $1, $2, $4, $6, $8}' | \
  awk '$4 > $6 {print $0}'
```

**Query (PowerShell):**
```powershell
Select-String -Path "logs\*.log" -Pattern "STALE_DATA exit" | 
  ForEach-Object { 
    $line = $_.Line
    if ($line -match 'md_age_ms=(\d+)') { $md_age = [int]$matches[1] }
    if ($line -match 'max_age_ms=(\d+)') { $max_age = [int]$matches[1] }
    if ($md_age -gt $max_age) { 
      Write-Output "$line (exceeded by $($md_age - $max_age)ms)"
    }
  }
```

**Expected Output:**
```
2026-07-16 10:15:23 STALE_DATA exit: position=abc123 md_age_ms=10000 max_age_ms=5000 (exceeded by 5000ms)
2026-07-16 10:20:45 STALE_DATA exit: position=def456 md_age_ms=12000 max_age_ms=5000 (exceeded by 7000ms)
```

### 3. TIME_STOP Exits with R Multiple Distribution
**Purpose:** Analyze whether TIME_STOP exits are occurring at appropriate R-multiple levels.

**Query (grep):**
```bash
grep "\[EXIT-INTENT\].*reason=time_stop" logs/*.log | \
  sed 's/.*R=\([0-9.-]*\).*/\1/' | \
  awk '{bucket=int($1*10)/10; buckets[bucket]++} END {for (b in buckets) print b, buckets[b]}'
```

**Query (PowerShell):**
```powershell
Select-String -Path "logs\*.log" -Pattern "\[EXIT-INTENT\].*reason=time_stop" | 
  ForEach-Object { 
    if ($_.Line -match 'R=([0-9.-]+)') { 
      $r = [double]$matches[1]
      $bucket = [math]::Floor($r * 10) / 10
      $buckets[$bucket]++
    }
  } | 
  ForEach-Object { 
    $buckets.GetEnumerator() | Sort-Object Name
  }
```

**Expected Output:**
```
R Bucket    Count
---------    -----
-2.0         2
-1.5         5
-1.0         8
-0.5         12
0.0          3
```

### 4. Exits by Asset (Market/Series)
**Purpose:** Understand exit behavior across different crypto assets (BTC, ETH, SOL, XRP, DOGE).

**Query (grep):**
```bash
grep "\[EXIT-INTENT\]" logs/*.log | \
  sed 's/.*market=\([^ ]*\).*/\1/' | \
  sort | uniq -c | sort -rn
```

**Query (PowerShell):**
```powershell
Select-String -Path "logs\*.log" -Pattern "\[EXIT-INTENT\]" | 
  ForEach-Object { 
    if ($_.Line -match 'market=([A-Z0-9_-]+)') { 
      $matches[1]
    }
  } | 
  Group-Object | Sort-Object Count -Descending
```

**Expected Output:**
```
market              count
------              -----
KXBTC15M           35
KXETH15M           28
KXSOL15M           15
KXXRP15M           8
KXDOGE15M          3
```

### 5. Full Exit vs Partial Exit Breakdown
**Purpose:** Understand the ratio of full position exits vs partial trims.

**Query (grep):**
```bash
grep "\[EXIT-INTENT\]" logs/*.log | \
  sed 's/.*type=\([^ ]*\).*/\1/' | \
  sort | uniq -c
```

**Query (PowerShell):**
```powershell
Select-String -Path "logs\*.log" -Pattern "\[EXIT-INTENT\]" | 
  ForEach-Object { 
    if ($_.Line -match 'type=([A-Z_]+)') { 
      $matches[1]
    }
  } | 
  Group-Object
```

**Expected Output:**
```
type          count
----          -----
FULL_EXIT     78
PARTIAL_EXIT  12
```

### 6. Exit Priority Distribution
**Purpose:** Verify that higher priority exits (RISK, STALE_DATA) are behaving as expected.

**Query (grep):**
```bash
grep "\[EXIT-INTENT\]" logs/*.log | \
  sed 's/.*priority=\([0-9]*\).*/\1/' | \
  sort | uniq -c | sort -rn
```

**Query (PowerShell):**
```powershell
Select-String -Path "logs\*.log" -Pattern "\[EXIT-INTENT\]" | 
  ForEach-Object { 
    if ($_.Line -match 'priority=(\d+)') { 
      $matches[1]
    }
  } | 
  Group-Object | Sort-Object Name -Descending
```

**Expected Output:**
```
priority    count
--------    -----
100         5    (RISK)
85          12   (STALE_DATA)
50          8    (CANDLE_REVERSAL)
45          15   (ADAPTIVE_TIMING)
40          35   (TIME_STOP)
35          23   (EDGE_DECAY)
30          12   (SCALE_OUT)
20          10   (MANUAL)
```

### 7. Position-Level vs Policy-Level Exit Sources
**Purpose:** Understand the balance between position-level exits (extreme profit, ratchets) and policy-layer exits.

**Query (grep):**
```bash
grep "\[EXIT-INTENT\]" logs/*.log | \
  sed 's/.*source=\([^ ]*\).*/\1/' | \
  sort | uniq -c
```

**Query (PowerShell):**
```powershell
Select-String -Path "logs\*.log" -Pattern "\[EXIT-INTENT\]" | 
  ForEach-Object { 
    if ($_.Line -match 'source=([a-z_]+)') { 
      $matches[1]
    }
  } | 
  Group-Object
```

**Expected Output:**
```
source           count
------           -----
position_level   45
policy_layer     45
```

### 8. Exit Resolver Decision History
**Purpose:** Analyze the ExitResolver's decision-making process when multiple exits compete.

**Query (grep):**
```bash
grep "\[EXIT-RESOLVER\]" logs/*.log | \
  grep "from \[" | \
  sed 's/.*from \[\(.*\)\].*/\1/' | \
  sort | uniq -c | sort -rn
```

**Query (PowerShell):**
```powershell
Select-String -Path "logs\*.log" -Pattern "\[EXIT-RESOLVER\].*from \[" | 
  ForEach-Object { 
    if ($_.Line -match 'from \[(.*)\]') { 
      $matches[1]
    }
  } | 
  Group-Object | Sort-Object Count -Descending
```

**Expected Output:**
```
competing_decisions                    count
-------------------                    -----
time_stop(prio=40),edge_decay(prio=35)  15
risk(prio=100),time_stop(prio=40)       5
stale_data(prio=85),candle_reversal(prio=50)  3
```

### 9. Volatility Regime Impact on Exits
**Purpose:** Understand how different volatility regimes affect exit behavior.

**Query (grep):**
```bash
grep "\[EXIT-POLICY-RESOLVER\]" logs/*.log | \
  sed 's/.*volatility=\([^,]*\).*/\1/' | \
  sort | uniq -c
```

**Query (PowerShell):**
```powershell
Select-String -Path "logs\*.log" -Pattern "\[EXIT-POLICY-RESOLVER\]" | 
  ForEach-Object { 
    if ($_.Line -match 'volatility=([^,]*)') { 
      $matches[1]
    }
  } | 
  Group-Object
```

**Expected Output:**
```
volatility    count
---------    -----
NORMAL        55
HIGH          20
LOW           10
EXTREME       5
```

### 10. Time-to-Expiry Distribution at Exit
**Purpose:** Analyze whether exits are occurring appropriately relative to contract expiry.

**Query (grep):**
```bash
grep "\[EXIT-POLICY-RESOLVER\]" logs/*.log | \
  sed 's/.*time_to_expiry=\([0-9.]*\).*/\1/' | \
  awk '{bucket=int($1/60); buckets[bucket]++} END {for (b in buckets) print b*60, buckets[b]}'
```

**Query (PowerShell):**
```powershell
Select-String -Path "logs\*.log" -Pattern "\[EXIT-POLICY-RESOLVER\]" | 
  ForEach-Object { 
    if ($_.Line -match 'time_to_expiry=([0-9.]+)') { 
      $t = [double]$matches[1]
      $bucket = [math]::Floor($t / 60)
      $buckets[$bucket]++
    }
  } | 
  ForEach-Object { 
    $buckets.GetEnumerator() | ForEach-Object { 
      "$($_.Name * 60)s $($_.Value)"
    }
  }
```

**Expected Output:**
```
time_to_expiry    count
-------------    -----
0-60s             5
60-120s           15
120-180s          25
180-240s          20
240-300s          10
300-360s          5
```

## Real-Time Monitoring Dashboard

### Key Metrics to Track
1. **Exit Rate by Reason:** Rolling count of exits per reason over last hour
2. **STALE_DATA Alerts:** Real-time alerts when MD age exceeds SLA
3. **R Multiple Distribution:** Histogram of R multiples at exit
4. **Asset Performance:** Win rate and PnL by asset (BTC, ETH, SOL, XRP, DOGE)
5. **Precedence Validation:** Verify higher priority exits are overriding lower priority correctly

### Alert Thresholds
- **STALE_DATA Rate:** > 5% of all exits indicates MD health issues
- **RISK Exits:** Any RISK exit requires immediate investigation
- **TIME_STOP Rate:** > 40% of all exits may indicate hold time too aggressive
- **EDGE_DECAY Rate:** > 30% of all exits may indicate edge threshold too high

## Integration with Log Aggregation

For production monitoring, these queries can be integrated with:
- **Elasticsearch/Logstash:** Use Kibana dashboards for visualization
- **Grafana/Loki:** Use LogQL for real-time queries
- **Splunk:** Use SPL for advanced analytics
- **CloudWatch Logs:** Use metric filters for alerting

## Sample Kibana Dashboard Queries

### Exit Rate Over Time
```json
{
  "query": {
    "bool": {
      "must": [
        { "match": { "message": "[EXIT-INTENT]" } }
      ]
    }
  },
  "aggs": {
    "exits_over_time": {
      "date_histogram": {
        "field": "@timestamp",
        "interval": "5m"
      },
      "aggs": {
        "by_reason": {
          "terms": {
            "field": "message",
            "script": "doc['message'].value =~ /reason=([a-z_]+)/ ? doc['message'].value : ''"
          }
        }
      }
    }
  }
}
```

### STALE_DATA Alert
```json
{
  "query": {
    "bool": {
      "must": [
        { "match": { "message": "STALE_DATA exit" } },
        { "range": { "@timestamp": { "gte": "now-5m" } } }
      ]
    }
  }
}
```
