-- ═══════════════════════════════════════════════════════════════════════════════
-- Edge audit: SQL queries for Layers 2, 3, and 5
-- 
-- These queries require decision-time telemetry joined to settlement / fills.
-- Expected source tables (rename/alias to your actual schema):
--   - decisions: one row per selected asset/cycle from decision_telemetry
--   - round_trips: one row per round trip from fills/ledger reconciliation
--   - fills: one row per fill with created_time, ingested_at, execution_price
--
-- Run these after decision_telemetry carries non-null:
--   model_prob_selected, market_p_selected, raw_edge_cents, edge_pct,
--   confidence, selected_side, selected_outcome_price_cents, ticker
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── Layer 2: Model calibration — reliability diagram per asset ────────────────
-- Bin predicted probabilities and compare to observed win frequency.
-- outcome = 1 when the selected side was the settled side, 0 otherwise.

WITH selected_decisions AS (
    SELECT
        d.asset,
        d.ticker,
        d.selected_side,
        d.model_prob_selected,
        d.market_p_selected,
        rt.market_result,
        CASE
            WHEN LOWER(d.selected_side) = 'yes'  AND LOWER(rt.market_result) = 'yes' THEN 1
            WHEN LOWER(d.selected_side) = 'no'   AND LOWER(rt.market_result) = 'no'  THEN 1
            WHEN LOWER(d.selected_side) = 'yes'  AND LOWER(rt.market_result) = 'no'  THEN 0
            WHEN LOWER(d.selected_side) = 'no'   AND LOWER(rt.market_result) = 'yes' THEN 0
            ELSE NULL
        END AS outcome,
        d.raw_edge_cents,
        d.edge_pct
    FROM decisions d
    LEFT JOIN round_trips rt
        ON rt.ticker = d.ticker
       AND rt.entry_time BETWEEN d.event_ts_utc - INTERVAL '30 seconds' AND d.event_ts_utc + INTERVAL '90 seconds'
    WHERE d.allocator_selected = TRUE
),
binned AS (
    SELECT
        asset,
        CASE
            WHEN model_prob_selected < 0.40 THEN 'p<0.40'
            WHEN model_prob_selected < 0.45 THEN '0.40-0.44'
            WHEN model_prob_selected < 0.50 THEN '0.45-0.49'
            WHEN model_prob_selected < 0.55 THEN '0.50-0.54'
            WHEN model_prob_selected < 0.60 THEN '0.55-0.59'
            WHEN model_prob_selected < 0.65 THEN '0.60-0.64'
            WHEN model_prob_selected < 0.70 THEN '0.65-0.69'
            ELSE 'p>=0.70'
        END AS prob_bucket,
        model_prob_selected,
        outcome,
        raw_edge_cents,
        edge_pct
    FROM selected_decisions
    WHERE outcome IS NOT NULL
)
SELECT
    asset,
    prob_bucket,
    COUNT(*) AS n_trades,
    ROUND(AVG(model_prob_selected) * 100, 2) AS avg_predicted_pct,
    ROUND(SUM(outcome) * 100.0 / COUNT(*), 2) AS observed_win_rate_pct,
    ROUND((AVG(model_prob_selected) - SUM(outcome) * 1.0 / COUNT(*)) * 100, 2) AS calibration_gap_pct,
    ROUND(AVG(raw_edge_cents), 4) AS avg_raw_edge_cents,
    ROUND(AVG(edge_pct) * 100, 4) AS avg_edge_pct
FROM binned
GROUP BY asset, prob_bucket
ORDER BY asset,
    CASE prob_bucket
        WHEN 'p<0.40' THEN 1
        WHEN '0.40-0.44' THEN 2
        WHEN '0.45-0.49' THEN 3
        WHEN '0.50-0.54' THEN 4
        WHEN '0.55-0.59' THEN 5
        WHEN '0.60-0.64' THEN 6
        WHEN '0.65-0.69' THEN 7
        ELSE 8
    END;


-- ── Layer 2: Brier score per asset ───────────────────────────────────────────
-- Brier = mean((model_prob - outcome)^2). Lower is better; 0.25 is a coin flip.

WITH selected_decisions AS (
    SELECT
        d.asset,
        d.model_prob_selected,
        CASE
            WHEN LOWER(d.selected_side) = 'yes'  AND LOWER(rt.market_result) = 'yes' THEN 1.0
            WHEN LOWER(d.selected_side) = 'no'   AND LOWER(rt.market_result) = 'no'  THEN 1.0
            WHEN LOWER(d.selected_side) = 'yes'  AND LOWER(rt.market_result) = 'no'  THEN 0.0
            WHEN LOWER(d.selected_side) = 'no'   AND LOWER(rt.market_result) = 'yes' THEN 0.0
            ELSE NULL
        END AS outcome
    FROM decisions d
    LEFT JOIN round_trips rt
        ON rt.ticker = d.ticker
       AND rt.entry_time BETWEEN d.event_ts_utc - INTERVAL '30 seconds' AND d.event_ts_utc + INTERVAL '90 seconds'
    WHERE d.allocator_selected = TRUE
)
SELECT
    asset,
    COUNT(*) AS n,
    ROUND(AVG(POWER(model_prob_selected - outcome, 2)) * 100, 4) AS brier_score_x100,
    ROUND(0.25 * 100, 4) AS coin_flip_brier_x100,
    ROUND((0.25 - AVG(POWER(model_prob_selected - outcome, 2))) * 100, 4) AS brier_improvement_x100
FROM selected_decisions
WHERE outcome IS NOT NULL
GROUP BY asset
ORDER BY brier_score_x100;


-- ── Layer 2: Hosmer–Lemeshow style decile test per asset ─────────────────────
-- Sort predictions into 10 equal-size bins and test calibration per bin.

WITH selected_decisions AS (
    SELECT
        d.asset,
        d.model_prob_selected,
        CASE
            WHEN LOWER(d.selected_side) = 'yes'  AND LOWER(rt.market_result) = 'yes' THEN 1.0
            WHEN LOWER(d.selected_side) = 'no'   AND LOWER(rt.market_result) = 'no'  THEN 1.0
            WHEN LOWER(d.selected_side) = 'yes'  AND LOWER(rt.market_result) = 'no'  THEN 0.0
            WHEN LOWER(d.selected_side) = 'no'   AND LOWER(rt.market_result) = 'yes' THEN 0.0
            ELSE NULL
        END AS outcome,
        NTILE(10) OVER (PARTITION BY d.asset ORDER BY d.model_prob_selected) AS decile
    FROM decisions d
    LEFT JOIN round_trips rt
        ON rt.ticker = d.ticker
       AND rt.entry_time BETWEEN d.event_ts_utc - INTERVAL '30 seconds' AND d.event_ts_utc + INTERVAL '90 seconds'
    WHERE d.allocator_selected = TRUE
)
SELECT
    asset,
    decile,
    COUNT(*) AS n,
    ROUND(MIN(model_prob_selected) * 100, 2) AS min_pred_pct,
    ROUND(MAX(model_prob_selected) * 100, 2) AS max_pred_pct,
    ROUND(AVG(model_prob_selected) * 100, 2) AS avg_pred_pct,
    ROUND(SUM(outcome) * 100.0 / COUNT(*), 2) AS observed_pct,
    ROUND((AVG(model_prob_selected) - SUM(outcome) * 1.0 / COUNT(*)) * 100, 2) AS gap_pct
FROM selected_decisions
WHERE outcome IS NOT NULL
GROUP BY asset, decile
ORDER BY asset, decile;


-- ── Layer 3: Edge decay / implementation shortfall ───────────────────────────
-- Compare decision-time edge to the edge implied by the actual fill price and
-- the final settlement. Positive implementation shortfall = worse fill than intended.

WITH joined AS (
    SELECT
        d.asset,
        d.ticker,
        d.selected_side,
        d.model_prob_selected,
        d.market_p_selected,
        d.selected_outcome_price_cents AS intended_price_cents,
        d.raw_edge_cents AS decision_raw_edge_cents,
        d.edge_pct AS decision_edge_pct,
        f.execution_price_cents AS fill_price_cents,
        rt.market_result,
        rt.settlement_value_cents,
        rt.hold_time_seconds,
        rt.net_pnl_cents,
        f.ingested_at - f.created_time AS exchange_to_ingestion_latency,
        d.event_ts_utc - f.created_time AS decision_to_fill_latency
    FROM decisions d
    JOIN fills f
        ON f.decision_trace_id = d.decision_id
    LEFT JOIN round_trips rt
        ON rt.entry_fill_id = f.fill_id
    WHERE d.allocator_selected = TRUE
)
SELECT
    asset,
    COUNT(*) AS n,
    ROUND(AVG(decision_raw_edge_cents), 4) AS avg_decision_raw_edge_cents,
    ROUND(AVG(
        CASE
            WHEN LOWER(selected_side) = 'yes' THEN (settlement_value_cents - fill_price_cents)
            WHEN LOWER(selected_side) = 'no'  THEN ((100 - settlement_value_cents) - fill_price_cents)
            ELSE NULL
        END
    ), 4) AS avg_realized_edge_cents,
    ROUND(AVG(fill_price_cents - intended_price_cents), 4) AS avg_implementation_shortfall_cents,
    ROUND(AVG(decision_raw_edge_cents - (
        CASE
            WHEN LOWER(selected_side) = 'yes' THEN (settlement_value_cents - fill_price_cents)
            WHEN LOWER(selected_side) = 'no'  THEN ((100 - settlement_value_cents) - fill_price_cents)
            ELSE NULL
        END
    )), 4) AS avg_edge_decay_cents,
    ROUND(AVG(EXTRACT(EPOCH FROM decision_to_fill_latency)), 2) AS avg_decision_to_fill_latency_s,
    ROUND(CORR(
        EXTRACT(EPOCH FROM decision_to_fill_latency),
        decision_raw_edge_cents - (
            CASE
                WHEN LOWER(selected_side) = 'yes' THEN (settlement_value_cents - fill_price_cents)
                WHEN LOWER(selected_side) = 'no'  THEN ((100 - settlement_value_cents) - fill_price_cents)
                ELSE NULL
            END
        )
    ), 4) AS latency_vs_edge_decay_corr
FROM joined
WHERE market_result IS NOT NULL
GROUP BY asset
ORDER BY asset;


-- ── Layer 3: Decision-edge vs fill-edge bucket analysis ──────────────────────
-- Bucket by decision edge and see how much is lost to fill and to final outcome.

WITH joined AS (
    SELECT
        d.asset,
        d.raw_edge_cents AS decision_raw_edge_cents,
        f.execution_price_cents AS fill_price_cents,
        d.selected_outcome_price_cents AS intended_price_cents,
        d.model_prob_selected * 100.0 - f.execution_price_cents AS fill_implied_edge_cents,
        rt.net_pnl_cents,
        f.ingested_at - f.created_time AS latency
    FROM decisions d
    JOIN fills f ON f.decision_trace_id = d.decision_id
    LEFT JOIN round_trips rt ON rt.entry_fill_id = f.fill_id
    WHERE d.allocator_selected = TRUE
),
bucketed AS (
    SELECT
        asset,
        CASE
            WHEN decision_raw_edge_cents < 2  THEN '<2c'
            WHEN decision_raw_edge_cents < 4  THEN '2-4c'
            WHEN decision_raw_edge_cents < 6  THEN '4-6c'
            WHEN decision_raw_edge_cents < 8  THEN '6-8c'
            WHEN decision_raw_edge_cents < 10 THEN '8-10c'
            ELSE '10c+'
        END AS edge_bucket,
        decision_raw_edge_cents,
        fill_implied_edge_cents,
        fill_price_cents - intended_price_cents AS slippage_cents,
        net_pnl_cents,
        EXTRACT(EPOCH FROM latency) AS latency_s
    FROM joined
)
SELECT
    asset,
    edge_bucket,
    COUNT(*) AS n,
    ROUND(AVG(decision_raw_edge_cents), 4) AS avg_decision_edge_cents,
    ROUND(AVG(fill_implied_edge_cents), 4) AS avg_fill_edge_cents,
    ROUND(AVG(slippage_cents), 4) AS avg_slippage_cents,
    ROUND(AVG(net_pnl_cents), 4) AS avg_net_pnl_cents,
    ROUND(AVG(latency_s), 2) AS avg_latency_s
FROM bucketed
GROUP BY asset, edge_bucket
ORDER BY asset,
    CASE edge_bucket
        WHEN '<2c'   THEN 1
        WHEN '2-4c'  THEN 2
        WHEN '4-6c'  THEN 3
        WHEN '6-8c'  THEN 4
        WHEN '8-10c' THEN 5
        ELSE 6
    END;


-- ── Layer 4 (SQL variant): Cost-wall threshold test with decision-time edge ──
-- This is the decision-time version of scripts/edge_cost_wall_audit.py.
-- It compares the model's predicted net edge to the realized round-trip fee.

WITH joined AS (
    SELECT
        d.asset,
        d.ticker,
        d.raw_edge_cents,
        d.selected_outcome_price_cents,
        d.edge_pct,
        rt.total_fee_cents,
        rt.quantity_contracts,
        rt.gross_pnl_cents,
        rt.net_pnl_cents,
        d.selected_side,
        d.market_p_selected
    FROM decisions d
    JOIN fills f ON f.decision_trace_id = d.decision_id
    LEFT JOIN round_trips rt ON rt.entry_fill_id = f.fill_id
    WHERE d.allocator_selected = TRUE
)
SELECT
    asset,
    COUNT(*) AS n,
    ROUND(AVG(raw_edge_cents), 4) AS avg_decision_raw_edge_cents,
    ROUND(AVG(gross_pnl_cents / NULLIF(quantity_contracts, 0)), 4) AS avg_realized_gross_edge_cents,
    ROUND(AVG(total_fee_cents / NULLIF(quantity_contracts, 0)), 4) AS avg_fee_drag_cents,
    ROUND(AVG(net_pnl_cents / NULLIF(quantity_contracts, 0)), 4) AS avg_realized_net_edge_cents,
    ROUND(SUM(CASE WHEN raw_edge_cents < (total_fee_cents / NULLIF(quantity_contracts, 0)) THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS pct_predicted_edge_below_fee_pct,
    ROUND(SUM(CASE WHEN net_pnl_cents > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS net_win_rate_pct
FROM joined
GROUP BY asset
ORDER BY asset;


-- ── Layer 4 (SQL variant): Per-asset threshold sensitivity sweep ─────────────
-- Sweep a gross-edge threshold and recompute PnL, win rate, exit fraction.
-- Forward-looking: replace threshold literal with decision.raw_edge_cents.

WITH joined AS (
    SELECT
        d.asset,
        d.raw_edge_cents AS decision_edge_cents,
        rt.gross_pnl_cents,
        rt.net_pnl_cents,
        rt.total_fee_cents,
        rt.quantity_contracts,
        rt.status
    FROM decisions d
    JOIN fills f ON f.decision_trace_id = d.decision_id
    LEFT JOIN round_trips rt ON rt.entry_fill_id = f.fill_id
    WHERE d.allocator_selected = TRUE
),
thresholds AS (
    SELECT generate_series(0, 150) / 10.0 AS threshold_cents  -- 0.0 to 15.0 step 0.1
),
sweep AS (
    SELECT
        t.threshold_cents,
        j.asset,
        COUNT(*) FILTER (WHERE j.decision_edge_cents >= t.threshold_cents) AS n_trades,
        SUM(j.net_pnl_cents) FILTER (WHERE j.decision_edge_cents >= t.threshold_cents) AS net_pnl_cents,
        SUM(j.gross_pnl_cents) FILTER (WHERE j.decision_edge_cents >= t.threshold_cents) AS gross_pnl_cents,
        SUM(j.total_fee_cents) FILTER (WHERE j.decision_edge_cents >= t.threshold_cents) AS total_fee_cents,
        SUM(j.quantity_contracts) FILTER (WHERE j.decision_edge_cents >= t.threshold_cents) AS contracts,
        SUM(CASE WHEN j.net_pnl_cents > 0 AND j.decision_edge_cents >= t.threshold_cents THEN 1 ELSE 0 END) AS net_wins,
        SUM(CASE WHEN j.status = 'closed_by_exit' AND j.decision_edge_cents >= t.threshold_cents THEN 1 ELSE 0 END) AS exits
    FROM thresholds t
    CROSS JOIN joined j
    GROUP BY t.threshold_cents, j.asset
)
SELECT
    threshold_cents,
    asset,
    n_trades,
    contracts,
    ROUND(gross_pnl_cents, 2) AS gross_pnl_cents,
    ROUND(total_fee_cents, 2) AS total_fee_cents,
    ROUND(net_pnl_cents, 2) AS net_pnl_cents,
    ROUND(net_wins * 1.0 / NULLIF(n_trades, 0), 4) AS net_win_rate,
    ROUND(exits * 1.0 / NULLIF(n_trades, 0), 4) AS exit_fraction
FROM sweep
WHERE n_trades > 0
ORDER BY asset, threshold_cents;


-- ── Layer 5: Execution fidelity ─ did the fill match the decision? ───────────

WITH joined AS (
    SELECT
        d.asset,
        d.ticker,
        d.selected_side AS intended_side,
        f.execution_action,
        f.execution_outcome_side AS executed_side,
        d.raw_edge_cents,
        d.edge_pct,
        d.confidence,
        d.confidence_valid,
        d.min_required_edge,
        rt.net_pnl_cents,
        f.execution_price_cents
    FROM decisions d
    JOIN fills f ON f.decision_trace_id = d.decision_id
    LEFT JOIN round_trips rt ON rt.entry_fill_id = f.fill_id
    WHERE d.allocator_selected = TRUE
)
SELECT
    asset,
    COUNT(*) AS n_fills,
    ROUND(SUM(CASE WHEN LOWER(intended_side) = LOWER(executed_side) THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS side_fidelity_pct,
    ROUND(SUM(CASE WHEN raw_edge_cents >= min_required_edge * 100.0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS edge_gate_pass_pct,
    ROUND(SUM(CASE WHEN confidence_valid = TRUE AND confidence >= 0.5 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS confidence_gate_pass_pct,
    ROUND(SUM(CASE WHEN raw_edge_cents < min_required_edge * 100.0 THEN 1 ELSE 0 END), 0) AS n_edge_violations,
    ROUND(SUM(CASE WHEN confidence_valid = FALSE OR confidence < 0.5 THEN 1 ELSE 0 END), 0) AS n_confidence_violations,
    ROUND(SUM(CASE WHEN LOWER(intended_side) != LOWER(executed_side) THEN 1 ELSE 0 END), 0) AS n_side_mismatches
FROM joined
GROUP BY asset
ORDER BY asset;


-- ── Layer 5: Trades that violated an execution gate ──────────────────────────
-- List fills where the executed side/price/edge/confidence does not match the decision.

SELECT
    d.asset,
    d.ticker,
    d.decision_id,
    f.fill_id,
    d.selected_side AS intended_side,
    f.execution_outcome_side AS executed_side,
    d.selected_outcome_price_cents AS intended_price_cents,
    f.execution_price_cents,
    d.raw_edge_cents AS decision_edge_cents,
    d.min_required_edge * 100.0 AS required_edge_cents,
    d.confidence,
    d.confidence_valid,
    rt.net_pnl_cents
FROM decisions d
JOIN fills f ON f.decision_trace_id = d.decision_id
LEFT JOIN round_trips rt ON rt.entry_fill_id = f.fill_id
WHERE d.allocator_selected = TRUE
  AND (
      LOWER(d.selected_side) != LOWER(f.execution_outcome_side)
      OR d.raw_edge_cents < d.min_required_edge * 100.0
      OR d.confidence_valid = FALSE
      OR d.confidence < 0.5
  )
ORDER BY d.event_ts_utc;
