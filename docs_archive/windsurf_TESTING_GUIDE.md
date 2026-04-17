# Kalshi Swarm Testing Guide
Complete validation and observation plan for live system

---

## Pass 1: End-to-End Test (Paper → Demo Live)

### Prerequisites

```bash
# Install dependencies
pip install nats-py websockets cryptography requests

# Set environment variables (demo)
export KALSHI_API_KEY_ID="your_demo_key"
export KALSHI_PRIVATE_KEY_PATH="/path/to/demo_key.pem"
export KALSHI_ENV="demo"
export ENABLE_LIVE_TRADING="false"  # Start with paper
```

### Step 1: Paper Mode Test

```bash
# Terminal 1: Start NATS
docker run -p 4222:4222 nats:latest

# Terminal 2: Run test
cd c:\Dev\MERID
python tests\test_end_to_end_kalshi.py
```

**Expected output:**
```
✓ REST Client tests passed
✓ Event bus test passed
✓ Execution pipeline test passed
✓ Full flow test passed (paper mode)

Total: 4/4 tests passed
🎉 All tests passed! System is operational.
```

### Step 2: Demo Live Test

```bash
# Enable live mode
export ENABLE_LIVE_TRADING="true"

# Re-run test
python tests\test_end_to_end_kalshi.py
```

**Watch for:**
- ✅ Kalshi order response with `order_id`
- ✅ No authentication errors (403, 401)
- ✅ Proper price conversion (0.01 → 1¢)
- ⚠️ Expected rejection if market closed/invalid

**Check Kalshi demo account:**
- Visit https://demo.kalshi.com/portfolio/orders
- Verify test order appears (likely unfilled at 1¢)

---

## Pass 2: Constrained Demo Run (30-60 minutes)

### Configuration

**Create `.env.demo.constrained`:**
```bash
# Kalshi credentials
KALSHI_API_KEY_ID=your_demo_key
KALSHI_PRIVATE_KEY_PATH=/path/to/demo_key.pem
KALSHI_ENV=demo

# Safety limits (very conservative for first run)
ENABLE_LIVE_TRADING=true
MAX_POSITION_SIZE=5          # 5 contracts max per market
MAX_VENUE_EXPOSURE=100       # $100 total exposure
MAX_DAILY_LOSS=50            # $50 daily loss limit

# Target markets (1 crypto + 1 election)
KALSHI_MARKETS=KXBTCD-24FEB16,KXHARRIS24-LSV

# Agent configuration
KELLY_BASE_FRACTION=0.2      # Very conservative (20% of Kelly)
MIN_NET_EDGE=0.03            # 3% minimum net edge after fees
```

### Step 1: Start Full Stack

```bash
# Terminal 1: NATS
docker run -p 4222:4222 nats

# Terminal 2: Python bridge
source .env.demo.constrained
python infra/kalshi_bridge_entrypoint.py

# Terminal 3: TS agents
source .env.demo.constrained
node infra/swarm_agents_entrypoint.js

# Terminal 4: Monitoring (see below)
python scripts/monitor_live_run.py
```

### Step 2: Collect Metrics

**Monitor these for 30-60 minutes:**

**From Python Bridge:**
- WS messages received/published
- Reconnection count
- Last message timestamp

**From Execution Pipeline:**
- Intents received
- Intents executed vs rejected (risk/rate limit)
- Current positions
- Daily PnL

**From Kalshi API:**
- Orders placed
- Orders filled
- Actual fees paid
- Fill prices vs expected

### Step 3: Record Observations

**Create `observations_log.txt`:**
```
Timestamp: 2026-02-16T20:00:00
Duration: 60 minutes
Markets: KXBTCD-24FEB16, KXHARRIS24-LSV

Metrics:
- Intents generated: X
- Intents executed: Y
- Intents rejected (risk): Z
- Orders placed: A
- Orders filled: B
- Total fees: $C
- Fill ratio: B/A
- Avg slippage: X¢

Issues observed:
- [ ] None
- [ ] Fee higher than expected
- [ ] Latency spikes
- [ ] WS disconnections
- [ ] Risk rejections

Notes:
...
```

---

## Pass 3: Analysis & Optimization Decision

### Analyze Collected Data

**1. Fill Rate Analysis**
```python
fill_rate = orders_filled / orders_placed
if fill_rate < 0.1:
    # Issue: Orders not filling
    # Possible causes:
    # - Prices too aggressive (out of market)
    # - Markets illiquid
    # - Arb opportunities disappearing fast
```

**2. Fee Impact Analysis**
```python
fee_ratio = total_fees / gross_profit
if fee_ratio > 0.5:
    # Issue: Fees eating > 50% of edge
    # Actions:
    # - Increase MIN_NET_EDGE threshold
    # - Tune maker/taker preference
    # - Focus on wider spreads
```

**3. Risk Rejection Analysis**
```python
rejection_rate = intents_rejected / intents_received
if rejection_rate > 0.8:
    # Issue: Risk too tight
    # Actions:
    # - Review position limits
    # - Check daily loss not hit early
    # - Verify capital allocation
```

### Decision Tree

**If fills are rare or fee-heavy:**
→ Tune arb thresholds:
  - Increase `MIN_NET_EDGE` (0.03 → 0.05)
  - Adjust `KELLY_BASE_FRACTION` (0.2 → 0.15)
  - Add maker preference logic

**If latency/WS stability issues:**
→ Focus on infrastructure:
  - Monitor WS reconnection frequency
  - Check message processing latency
  - Review NATS queue depth

**If behavior seems solid:**
→ Define Phase 1 live plan:
  - Expand to 3-5 markets
  - Increase position limits gradually
  - Run 24-48 hour demo session
  - Collect full episode data for analysis

---

## Recommended Next Actions

**After 60-minute run:**

1. **Stop system gracefully**
   ```bash
   # Ctrl-C in each terminal
   # Or send SIGTERM
   ```

2. **Export metrics**
   ```bash
   # Bridge stats
   curl http://localhost:8000/api/kalshi/bridge/stats > bridge_stats.json
   
   # Execution stats
   curl http://localhost:8000/api/kalshi/execution/stats > execution_stats.json
   ```

3. **Analyze Kalshi account**
   - Check actual orders placed
   - Verify fees charged match expectations
   - Review fill details

4. **Decide on iteration**
   - If good: extend to longer runs
   - If issues: tune based on Pass 3 analysis
   - If major problems: debug specific component

---

## Safety Checklist

**Before ANY live run (even demo):**
- [ ] Verified `KALSHI_ENV=demo` (not prod)
- [ ] Confirmed position limits in place
- [ ] Set daily loss limit
- [ ] Used conservative Kelly fraction
- [ ] Tested paper mode first
- [ ] Have kill switch ready (Ctrl-C)
- [ ] Monitoring in place

**Never:**
- Run prod before 7+ days successful demo
- Disable risk checks
- Use full Kelly on first runs
- Deploy without monitoring
- Run overnight without supervision (first runs)

---

## Troubleshooting

**Test fails on authentication:**
- Verify key_id matches Kalshi account
- Check private key file permissions
- Confirm demo vs prod environment

**Event bus connection fails:**
- Verify NATS running (`docker ps`)
- Check port 4222 not in use
- Try: `telnet localhost 4222`

**WS bridge not receiving data:**
- Check Kalshi market is open/active
- Verify subscription sent
- Review bridge logs for errors

**Orders rejected by Kalshi:**
- Check market status (open/closed)
- Verify price range (1-99 cents)
- Ensure sufficient balance
- Review Kalshi error message

---

## Expected First-Run Results

**Realistic expectations for 60-min constrained run:**

**Good scenario:**
- 5-15 intents generated
- 2-5 orders placed
- 0-2 orders filled (low fill rate expected)
- $0.10-$1.00 in fees
- No major errors

**Success criteria:**
- ✅ System runs without crashes
- ✅ WS connection stable
- ✅ Orders reach Kalshi API
- ✅ Risk checks working
- ✅ No authentication errors

**Not expected on first run:**
- High fill rates (arb disappears fast)
- Positive PnL (need larger sample)
- Many opportunities (constrained markets)

---

## Post-Run Checklist

- [ ] Collected all logs
- [ ] Exported metrics
- [ ] Reviewed Kalshi account
- [ ] Documented observations
- [ ] Identified 1-2 improvement areas
- [ ] Updated configuration for next run
- [ ] Backed up test results

**Next iteration:**
Based on Pass 3 analysis, choose ONE focus area and iterate.
