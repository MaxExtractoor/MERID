# Sybil Collusion Runbook

## 1. Incident Response Checklist

### Detect & Confirm
- Trigger: poisoning/Sybil test failures or abnormal trust/weight concentration.
- Run focused suites with `pytest -vv --full-trace --capture=tee-sys`.
- Capture trust graph snapshots and concentration metrics for the incident window.

### Scope & Impact
- List identities, wallets, validators with disproportionate influence.
- Map which subsystems (governance, execution, rewards) consumed the suspect signal.

### Contain
- Clamp per-identity/cluster trust weight and permissions.
- Tighten global risk limits (allocation, order size, governance quotas).
- Default to conservative trust if detection is empty or unstable.

### Eradicate & Remediate
- Patch `SourceAgreementGraph` scoring/clustering thresholds.
- Re-run poisoning simulations; require deterministic detection of labeled colluders.
- Ensure trust penalties persist even if colluders pause activity.
- Update configuration so uncertainty defaults to conservative behavior.

### Recover & Harden
- Restore normal limits only after detection metrics stabilize across M clean windows.
- Add regression tests (micro-graph + integration) and runtime telemetry (trust concentration, cluster counts, correlated behaviors).

### Rollback Plan
- Immediate: flip feature flags or redeploy the last known-good trust/collusion configuration.
- Data cleanup: recompute trust from historical events; invalidate decisions influenced by suspect identities.
- Verification: rerun poisoning suites and live shadow checks before re-enabling new logic.

---

## 2. Logging Requirements

Every high-impact action log must include:
- Identity: `wallet_address`, `account_id`, `node_id`, `validator_id`, `cluster_id` / `trust_cluster`
- Network/Infra: `ip`, `asn`, `region`, `datacenter_provider`
- Economic/Trust: `stake_balance`, `voting_power`, `trust_score`, `reputation_score`, `role`
- Activity: `action_type`, UTC `timestamp` (ms), `tx_hash`/`request_id`, `success/failure`, `latency_ms`

---

## 3. Throttling & Isolation Procedures

### Suspicious Wallets
- Per-identity rate limits (1–2 high-impact actions/min, 1–5 RPS for APIs).
- Cooldown periods between large trades, votes, validator registrations.
- Economic friction: temporarily raise fees/stake minimums for low-reputation/new identities.
- Track counters per `wallet_address` + action; log `throttle_reason` and `throttle_level` when denying.

### New Identity Rate Limits
- Creation caps: ≤3–5 identities per IP/ASN per day (stricter for cloud ranges).
- Warm-up mode (24–72h): lower stake/voting caps, smaller trade sizes, stricter governance action counts.
- All limits configurable via feature flags for rapid adjustments.

### Subnet / Validator Isolation
- Detect suspicious prefixes by aggregating identity creations, validator joins, large trades/votes per `ip_prefix` + `asn`.
- Contain via firewall/WAF rules and additional checks (CAPTCHA, stronger auth).
- Temporarily suspend/down-weight validators in flagged prefixes until review.
- Log each isolation rule with `subnet`, `asn`, `reason`, `expiry`.

---

## 4. Query Patterns

### Bursting Identities Sharing Infra
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

### Cluster Candidates (Same Infra, Same Minute)
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

### Graph Backend Hint
- Build edges between identities acting within short windows on similar targets, then run community detection (Louvain, label propagation) to surface high-agreement clusters.

---

## 5. Acceptance Criteria for SourceAgreementGraph Changes
- ≥ specified fraction of labeled colluders appear in high-risk clusters or are capped below the influence threshold.
- No single colluder/cluster exceeds the max trust share.
- In clean runs, ≥95% honest nodes remain within their normal trust band.
- Empty/error detection output defaults to conservative trust and stricter limits.
- Outputs (clusters, caps) must be deterministic under fixed seeds/fixtures.
