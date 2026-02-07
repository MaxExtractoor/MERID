# Security Playbook

## Sybil Collusion Incident Playbook

### 1. Detect & Confirm
1. Trigger: abnormal trust/weight concentration or failing Sybil/poisoning test suites.
2. Action: rerun the focused suites with `pytest -vv --full-trace --capture=tee-sys`; archive logs, metrics, and trust-graph snapshots for the affected window.

### 2. Scope & Impact
1. Enumerate identities / wallets with outsized influence.
2. Map which subsystems (governance, execution, rewards, etc.) consumed that trust signal.

### 3. Contain
1. Apply emergency caps on trust weight, voting power, and permissions for suspicious clusters.
2. Tighten global risk limits (allocation, order size, proposal quotas) until detection quality is verified restored.
3. If detection output is empty/unstable, default to conservative trust (no boosts) and stricter limits.

### 4. Eradicate & Remediate
1. Patch `SourceAgreementGraph` scoring/clustering thresholds.
2. Re-run Sybil/poisoning simulations; require deterministic clusters containing the labeled colluders.
3. Confirm trust penalties stick: colluders stay capped even if they stop broadcasting temporarily.
4. Update configs so uncertainty = conservative behavior (no automatic re-enablement).

### 5. Recover & Harden
1. Restore normal limits only after detection metrics stabilize over M clean windows.
2. Add regression tests + telemetry:
   - Micro-graph unit tests (honest vs colluders)
   - Integration tests (poisoning, clean, slow infiltration scenarios)
   - Runtime monitors (trust concentration, cluster counts, correlated actions)

### 6. Rollback Plan
1. Immediate: flip feature flags or redeploy the last known-good detection/trust configuration that predates the regression.
2. Data cleanup: recompute trust from historical events with the stable algorithm; invalidate decisions that relied on suspect identities.
3. Post-rollback: rerun poisoning suites, verify baseline metrics, only then reintroduce new logic.

### 7. Safely Restoring Consensus
1. Rebuild validator/committee membership from identities passing stricter reputation, stake, or external verification; explicitly exclude quarantined clusters.
2. Gradually relax caps (voting weight, order size) while monitoring trust concentration, edge weights, and correlated behaviors.
3. Acceptance criteria for `SourceAgreementGraph` patches:
   - Known colluders cannot achieve majority influence or committee control under attack scenarios.
   - Trust concentration metrics (top-k share, Gini/HHI) stay within tighter bounds than pre-incident baseline.
   - In clean scenarios, ≥ honest majority maintains normal consensus throughput with minimal false positives.
   - Fail-safe: empty/error detection output must default to conservative trust + stricter limits, never elevated privileges.

## Sybil Collusion Logging & Throttle Guidance

### Required Log Fields
Every high-impact action must emit:

| Context | Fields |
| --- | --- |
| Identity | `wallet_address`, `account_id`, `node_id`, `validator_id`, `cluster_id` / `trust_cluster` |
| Network / Infra | `ip`, `asn`, `region`, `datacenter_provider` |
| Economic / Trust | `stake_balance`, `voting_power`, `trust_score`, `reputation_score`, `role` (validator/trader/oracle/governor) |
| Activity | `action_type`, UTC `timestamp` (ms precision), `tx_hash` / `request_id`, `success/failure`, `latency_ms` |

### Temporary Throttles for Suspicious Wallets
1. **Per-identity rate limits**
   - Flagged wallets: cap to X high-impact actions/min (e.g., ≤2 large trades, ≤1 proposal, limited votes).
   - Global API throttles: 1–5 RPS depending on severity.
2. **Cooldown periods**
   - Enforce delays between critical actions (large transfer, validator registration) to block rapid iteration.
3. **Economic friction**
   - Temporarily raise fees, minimum stake, or required deposits for high-impact actions from low-reputation or newly created identities.

Implementation hint: maintain counters per `wallet_address` + `action_type` (e.g., Redis). Increment on each request and enforce limits; log `throttle_reason` + `throttle_level` when denying.

### Network Rate Limits for New Identities
1. Creation caps: limit identities per IP/ASN per window (≤3–5/day/IP; stricter for cloud ranges).
2. Warm-up mode: identities younger than 24–72h operate with lower stake/voting caps, smaller trade sizes, and stricter governance action counts.
3. Expose limits via config/feature flags for rapid tightening during incidents.

### Subnet / Validator Isolation
1. Detect: aggregate metrics by `ip_prefix` + `asn`; flag bursts in identity creation, validator joins, large trades/votes.
2. Contain:
   - Firewall/WAF rules to drop or throttle suspicious prefixes/providers.
   - Require extra checks (CAPTCHA, stronger auth, stake) for those ranges.
   - Temporarily suspend or down-weight validators in flagged prefixes until reviewed.
3. Log every isolation rule with `subnet`, `asn`, `reason`, `expiry`.

### Query Patterns for Correlated Identities

**Bursting identities sharing infra:**
```sql
SELECT wallet_address, node_id, ip, asn,
       COUNT(*) AS action_count,
       MIN(timestamp) AS first_seen,
       MAX(timestamp) AS last_seen
FROM activity_logs
WHERE timestamp >= now() - INTERVAL '1 hour'
  AND action_type IN ('vote', 'large_trade', 'validator_join')
GROUP BY wallet_address, node_id, ip, asn
HAVING COUNT(*) > 10;
```

**Cluster candidates (same infra, same minute):**
```sql
SELECT ip, asn, date_trunc('minute', timestamp) AS minute_bucket,
       ARRAY_AGG(DISTINCT wallet_address) AS wallets,
       COUNT(*) AS total_actions
FROM activity_logs
WHERE timestamp >= now() - INTERVAL '30 minutes'
  AND action_type IN ('vote', 'large_trade', 'stake')
GROUP BY ip, asn, date_trunc('minute', timestamp)
HAVING COUNT(DISTINCT wallet_address) >= 3
   AND COUNT(*) >= 20;
```

For graph backends (Neo4j/etc.), connect identities that act within short windows on similar targets, then run community detection (Louvain, label propagation) to surface high-agreement clusters.
