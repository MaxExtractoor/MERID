# P4 consumer-patch draft — REVIEW ARTIFACT (not applied)

Shared contract (reference impl: `_audit_p4_canonical.py`):
verified_venue | mirror_matched | mirror_partial | side_conflict |
unpaired_provisional | non_execution. Authoritative financial view =
verified_venue only. Mirrors are telemetry; conflicts quarantine BOTH sides;
unpaired provisional reported separately; trade_id is the dedup key
(never order+qty+second).

## Site 1 — `fills_ledger.py` `_market_fill_totals` (~L7280)

Current: iterates `self._fills.values()`, sums proceeds + canonical delta
unfiltered. Feeds `get_market_realized_pnl` (post-loss cooldown) and
`get_market_residual_yes_cc` (settlement_poller residual check).

```diff
         for fill in list(self._fills.values()):
             if fill.market_ticker != market_ticker:
                 continue
+            if self._canonical_fill_class(fill) == "excluded":
+                continue   # superseded mirrors / conflict-quarantined rows
             if asof_ts is not None:
                 ...
```

Also extend `_canonical_fill_class` (~L3287) so "excluded" additionally covers
conflict-quarantined rows, not just superseded mirrors:

```diff
     def _canonical_fill_class(self, fill: KalshiFill) -> str:
         fid = str(getattr(fill, "fill_id", "") or "")
         src = (getattr(fill, "ingestion_source", "") or "").lower()
+        if self._order_rows_conflict(fill):
+            return "excluded"
         if self._is_superseded_live_router_fill(fill):
             return "excluded"
         if fid.startswith("live_router_") or src == "order_router":
             return "provisional"
         return "authoritative"
```

New helper (per-order signed-delta conflict — the d3ae case):

```python
    def _order_rows_conflict(self, fill: KalshiFill) -> bool:
        """True when a mirror's signed delta opposes the venue aggregate
        on the same order — direction contested; quarantine all rows on
        the order pending order-ack resolution."""
        oid = getattr(fill, "order_id", None)
        if not oid:
            return False
        mirror_d = 0
        venue_d = 0
        has_mirror = has_venue = False
        for other in self._fills.values():
            if getattr(other, "order_id", None) != oid:
                continue
            fid2 = str(getattr(other, "fill_id", "") or "")
            src2 = (getattr(other, "ingestion_source", "") or "").lower()
            d = getattr(other, "canonical_yes_delta_cc", 0) or 0
            if fid2.startswith("live_router_") or src2 == "order_router":
                mirror_d += d
                has_mirror = True
            else:
                venue_d += d
                has_venue = True
        return (has_mirror and has_venue
                and ((mirror_d > 0) != (venue_d > 0))
                and mirror_d != 0 and venue_d != 0)
```

Unpaired provisional remains `provisional` for _market_fill_totals purposes
(same treatment as `_prior_signed_yes_cc`: pending exposure evidence). NOTE:
for authoritative realized-PnL/residual consumers that should report
coverage status, an unresolved-provisional flag should surface separately —
see `unresolved_router_fills()` which already does this.

## Site 2 — `fills_ledger.py` `summary()` realized-PnL/fee loop (~L4670)

```diff
         for fill in fills_snapshot:
-            total_fees += fill.fee_cost
+            if self._canonical_fill_class(fill) == "excluded":
+                continue   # one economic execution counts once
+            total_fees += fill.fee_cost
```
(Provisional mirrors keep counting as pending exposure — consistent with
_prior_signed_yes_cc; alternatively restrict realized-PnL sums to
"authoritative" only and report provisional separately. Decide per the
metric contract in MERID_P4_FINANCIAL_CORRECTNESS.md.)

## Site 3 — `analysis/calibration_report.py` (~L431)

```diff
         FROM kalshi_fills
+        WHERE fill_id NOT LIKE 'live_router_%'
+          AND COALESCE(ingestion_source,'') != 'order_router'
+          AND order_id NOT IN (
+              SELECT order_id FROM kalshi_fills
+              WHERE fill_id LIKE 'live_router_%'
+                AND sign(COALESCE(canonical_yes_delta_cc,0)) !=
+                    sign((SELECT SUM(canonical_yes_delta_cc) FROM kalshi_fills v2
+                          WHERE v2.order_id = kalshi_fills.order_id
+                            AND v2.fill_id NOT LIKE 'live_router_%')))
         GROUP BY market_ticker
```
(If the conflict subquery proves fragile on large scans, materialize the
conflict-order set in Python first — there is currently exactly one.)

## Site 4 — `execution/decision_audit_ledger.py` `_capital_realized_from_fills_db` (~L2092)

Same predicate added to the per-ticker fills SELECT (mirror-source +
conflict-order exclusion). The trust-state filter alone is insufficient:
all 24 mirror rows carry TRUSTED_LIVE_V1.

## Downstream trace (rehearsed on read-only copy — `_audit_p4_rehearse.py`)

- Cooldown input `get_market_realized_pnl`: 22 markets corrected; largest
  sign-mask: XRP-210915 +162.4c -> -29.6c (real loss shown as gain —
  cooldown would under-trigger historically).
- Settlement residual `get_market_residual_yes_cc`: 22 phantom +-100cc
  residuals -> 0; removes false settlement_mismatch candidates.
- summary()/API/Prometheus: total_fees -0.3748; realized totals corrected.
- Episode aggregation: partial_exit 25 -> 4; fully_exited 461 -> 482.
- exit_counterfactuals.jsonl: 14 records on changed markets flagged for
  regeneration (e.g. cf-747d51e46919 exited 1.99 vs true 1.00).
- bankroll_reconciliation.jsonl: 468 settlement-trigger records on changed
  markets — realized_pnl/expected_change values embed pollution; mark
  ineligible for learning, keep as telemetry.
- calibration_report per-market fills/fees/proceeds corrected on 22 markets.

## Not in scope for the patch

- Loss gates (disabled, stay disabled).
- Exit policy / stop paths / exposure — unchanged.
- No row deletion: mirrors stay in the ledger as telemetry.
- Side-conflict rows stay quarantined until order-ack evidence resolves
  d3ae direction; unpaired provisional reported with coverage status.
