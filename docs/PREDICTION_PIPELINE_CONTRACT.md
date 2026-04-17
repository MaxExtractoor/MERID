# Prediction Pipeline Contract

**Version:** 1.0.0  
**Date:** 2026-03-27  
**Status:** Canonical Truth Engine Definition

---

## 1. Single Source of Truth

### 1.1 Realized Outcomes
- **Only source:** Kalshi `/portfolio/settlements` endpoint (`market_result`, `settlement_value` fields)
- **Never from:** Ad-hoc price heuristics, UI toggles, external price oracles, or manual entry
- **Settlement value:** Always in cents (0 or 100 for binary contracts)
- **Identity:** `(venue, market_id, settled_time)` tuple uniquely identifies a settlement

### 1.2 Ticker Identity
- **Canonical format:** `KX{ASSET}-{TENOR}` (e.g., `KXBTC-15M`, `KXETH`, `KXSOL-D1`)
- **Normalization rules:**
  - Uppercase always
  - Asset: BTC, ETH, SOL, XRP, DOGE
  - Tenor: 15M (15m), empty (1h), D1 (daily), W1 (weekly)
- **Single mapping function:** `normalize_kalshi_ticker()` in `market_opinion.py` used by:
  - MarketDiscovery
  - SwarmConsensusAggregator
  - KalshiSettlementPoller
  - SettlementToGradingBridge

---

## 2. Evaluation Window

### 2.1 Opinion Eligibility
- **Valid window:** `issued_at <= market.expiration_time`
- **Grading horizon:** Kalshi market expiration / resolution time (not `settled_time`)
- **Grace period:** None. No re-grading after Kalshi confirms result.
- **Amendment policy:** If Kalshi amends text but not numeric result, original grading stands.

### 2.2 Outcome Unification
```python
class Outcome(Enum):
    YES = 1           # settlement_value == 100
    NO = 0            # settlement_value == 0
    CANCELLED = -1    # market voided, no payout
    INVALID = -2      # data missing/corrupt, exclude from metrics
    PENDING = None    # not yet settled
```

- **Grading exclusion:** `CANCELLED` and `INVALID` outcomes excluded from Brier and ROI denominators
- **No silent defaults:** Never treat `CANCELLED` as `YES` or `NO`

---

## 3. Metric Definitions

### 3.1 Brier Score
**Formula:** \( Brier = \frac{1}{N} \sum_{i=1}^{N} (p_i - o_i)^2 \)

- \( p_i \): Predicted probability (0-1, not 0-100)
- \( o_i \): Observed outcome (1 for YES, 0 for NO)
- **Bounds:** 0 (perfect) to 1 (worst)
- **Random baseline:** 0.25 for binary at p=0.5
- **Good threshold:** < 0.20

### 3.2 Kelly Regret
**Formula:** \( Regret = K_{oracle} - K_{actual} \)

- \( K_{oracle} \): Kelly stake using true outcome probabilities (oracle knowledge)
- \( K_{actual} \): Kelly stake using predicted probabilities
- **Interpretation:** Utility loss from suboptimal sizing
- **Max acceptable:** < 5% average

### 3.3 Direction Accuracy
**Formula:** \( Accuracy = \frac{\text{correct directional predictions}}{\text{total valid predictions}} \)

- **Valid:** Non-neutral opinions with settled outcomes
- **Correct:** (p > 0.5 and outcome=YES) or (p < 0.5 and outcome=NO)
- **Min viable:** > 65% (breakeven post-fees)

### 3.4 ROI
**Formula:** \( ROI = \frac{\text{Realized PnL}}{\text{Capital at Risk}} \times 100\% \)

- Includes Kalshi fees (tiered: 7%/5%/3%)
- **Economic viability:** > 2x fees

---

## 4. Grading Pipeline Guarantees

### 4.1 Exactly-Once Grading
- **Dedupe key:** `(venue, market_id, settled_time)`
- **Storage:** `grading_outcomes` table with uniqueness constraint
- **Contract:** Each valid settlement produces exactly one `ApprovedOpinionRecord` graded event
- **Voided markets:** Produce zero grading events

### 4.2 Idempotency
- Replaying same settlement stream twice yields identical metrics
- Aggregate metrics stable under opinion ordering (within market)

### 4.3 Determinism
- Same input sequence → identical Brier, regret, ROI
- No global mutable state in metric computation

---

## 5. Component Contracts

### 5.1 KalshiSettlementPoller
| Aspect | Contract |
|--------|----------|
| Polling | `GET /portfolio/settlements` with cursor pagination |
| Lookback | 24 hours (configurable) |
| Cursor | Resume from last cursor on restart |
| Deduplication | `seen_market_ids` set + DB unique constraint |
| Voided handling | Emit `Outcome.CANCELLED`, do not grade |

### 5.2 SettlementToGradingBridge
| Aspect | Contract |
|--------|----------|
| Input | `KalshiSettlement` with `status == SETTLED` and `settlement_value` in {0, 100} |
| Output | `GradingOutcome` record inserted to DB |
| Ticker mapping | Use `normalize_kalshi_ticker()` only |
| Time alignment | Use `expiration_time` (horizon), not `settled_time` |

### 5.3 GradingObserver
| Aspect | Contract |
|--------|----------|
| Metric source | `market_opinion.py` canonical definitions only |
| Classification | Use `BenchmarkThresholds` from domain module |
| Aggregation | Per-market, per-source, per-strategy_version |

### 5.4 ConsensusSignalProcessor (UI)
| Aspect | Contract |
|--------|----------|
| Projection | Pure function of backend state |
| No local compute | UI never computes direction accuracy or ROI independently |
| Real-time | Push updates via WebSocket; snapshot on connect |

---

## 6. Health and Observability

### 6.1 Health Endpoint `/api/v1/pipeline/health`
```json
{
  "status": "healthy|degraded|down",
  "settlement_poller": {
    "last_poll": "2026-03-27T12:00:00Z",
    "settled_but_ungraded": 3
  },
  "grading": {
    "last_graded": "2026-03-27T11:58:00Z",
    "pending_count": 5
  },
  "consensus": {
    "active_markets": 12,
    "ready_consensus": 8
  }
}
```

### 6.2 Critical Alerts
- Settlement poller stalled (>5 min since last poll)
- Settled-but-ungraded backlog growing
- Metric computation errors
- Ticker normalization mismatches

---

## 7. Environment Safety

### 7.1 Environment Flags
| Env | Settlement Source | Grading DB | Action |
|-----|-------------------|------------|--------|
| prod | Live Kalshi | Production | Grade and report |
| paper | Live Kalshi (read-only) | Sandbox | Grade only, no real PnL |
| dev | Mock/simulated | In-memory/Ephemeral | Test grading logic |
| replay | Historical file | Isolated run_id | Replay analysis only |

### 7.2 Isolation Rules
- Replay jobs never write to production grading tables
- Paper mode never submits orders but grades against live settlements
- Dev mode uses synthetic settlements, never polls live

---

## 8. Invariant Checklist

### 8.1 Data Invariants
- [ ] Ticker normalization idempotent: `normalize(normalize(x)) == normalize(x)`
- [ ] All probabilities in [0, 1]
- [ ] Settlement values in {0, 100, None}
- [ ] Opinion `issued_at <= expiration_time` for grading eligibility
- [ ] No NaN/None in metric computation

### 8.2 Pipeline Invariants
- [ ] Each settlement → exactly one grading event (or zero for voided)
- [ ] Grading never uses future information (no time-travel)
- [ ] UI state = projection of backend state (no divergence)
- [ ] Metric definitions identical across all components

### 8.3 Operational Invariants
- [ ] Health endpoint reflects true pipeline state
- [ ] Replay isolation: no pollution of production metrics
- [ ] Environment-appropriate data sources

---

## 9. Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-03-27 | Initial canonical truth engine contract |

---

## Appendix: Ticker Normalization Reference

```python
def normalize_kalshi_ticker(ticker: str) -> str:
    """
    Normalize any Kalshi ticker variation to canonical form.
    
    Input variations:
      - "kxbtc-15m" → "KXBTC-15M"
      - "KXBTC" → "KXBTC" (1h implied)
      - "KXETHD1" → "KXETH-D1"
      - "BTC-15M" → "KXBTC-15M"
    
    Output: Canonical uppercase format with KX prefix.
    """
    ticker = ticker.upper().strip()
    
    # Ensure KX prefix
    if not ticker.startswith("KX"):
        ticker = "KX" + ticker
    
    # Normalize separators
    ticker = ticker.replace("-", "").replace("_", "")
    
    # Extract components
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    for asset in assets:
        if asset in ticker:
            # Determine tenor
            if "15M" in ticker or "15" in ticker:
                return f"KX{asset}-15M"
            elif "D1" in ticker or "DAILY" in ticker:
                return f"KX{asset}-D1"
            elif "W1" in ticker or "WEEKLY" in ticker:
                return f"KX{asset}-W1"
            else:
                return f"KX{asset}"  # 1h default
    
    return ticker  # Fallback: return as-is with KX prefix
```
