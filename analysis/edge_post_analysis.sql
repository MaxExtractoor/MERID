-- ═══════════════════════════════════════════════════════════════════════════════
-- KALSHI 15M MICRO-SCALPING: Post-Trade Edge Analysis Queries
-- Run after 100+ trades to validate edge model and calibrate per-asset thresholds
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── 1. Edge Bucket Performance by Asset ─────────────────────────────────────
-- Groups trades by asset and edge bucket to validate model accuracy
-- Target: EV_net > 0 in 4-6% bucket, increasing with edge

WITH edge_buckets AS (
    SELECT
        asset,
        CASE
            WHEN edge < 0.04 THEN '0-4% (below)'
            WHEN edge < 0.06 THEN '4-6% (target)'
            WHEN edge < 0.08 THEN '6-8% (strong)'
            ELSE '8%+ (very_strong)'
        END AS edge_bucket,
        edge,
        ev_net,
        pnl_realized,
        delta_bps,
        z_score
    FROM (
        -- Parse TRADE_ENTRY logs (import into temp table via ETL)
        SELECT
            json_extract(metrics, '$.asset') AS asset,
            json_extract(metrics, '$.edge') AS edge,
            json_extract(metrics, '$.ev_net') AS ev_net,
            json_extract(metrics, '$.delta_bps') AS delta_bps,
            json_extract(metrics, '$.z_score') AS z_score,
            -- Join to fills for realized PnL
            (SELECT pnl FROM fills f WHERE f.correlation_id = trade.corr_id) AS pnl_realized
        FROM trade_entries trade
        WHERE tf = '15m'
    )
)
SELECT
    asset,
    edge_bucket,
    COUNT(*) AS n_trades,
    ROUND(AVG(edge) * 100, 2) AS avg_edge_pct,
    ROUND(AVG(ev_net) * 100, 2) AS avg_ev_net_pct,
    ROUND(AVG(pnl_realized), 4) AS avg_realized_pnl,
    ROUND(SUM(pnl_realized), 2) AS total_pnl,
    ROUND(AVG(ABS(delta_bps)), 1) AS avg_distance_bps,
    ROUND(AVG(z_score), 2) AS avg_z_score
FROM edge_buckets
GROUP BY asset, edge_bucket
ORDER BY asset, 
    CASE edge_bucket
        WHEN '0-4% (below)' THEN 1
        WHEN '4-6% (target)' THEN 2
        WHEN '6-8% (strong)' THEN 3
        WHEN '8%+ (very_strong)' THEN 4
    END;


-- ── 2. Distance Bucket Calibration ───────────────────────────────────────────
-- Analyzes performance by spot-to-strike distance to calibrate z-score bands

WITH distance_buckets AS (
    SELECT
        asset,
        CASE
            WHEN ABS(delta_pct) <= 0.0025 THEN 'A: <=0.25%'
            WHEN ABS(delta_pct) <= 0.0050 THEN 'B: 0.25-0.5%'
            WHEN ABS(delta_pct) <= 0.0100 THEN 'C: 0.5-1.0%'
            ELSE 'D: >1.0%'
        END AS distance_bucket,
        delta_pct,
        delta_bps,
        z_score,
        implied_prob,
        model_prob,
        edge,
        ev_net,
        pnl_realized
    FROM (
        SELECT
            json_extract(metrics, '$.asset') AS asset,
            json_extract(metrics, '$.delta_pct') AS delta_pct,
            json_extract(metrics, '$.delta_bps') AS delta_bps,
            json_extract(metrics, '$.z_score') AS z_score,
            json_extract(metrics, '$.implied_prob') AS implied_prob,
            json_extract(metrics, '$.model_prob') AS model_prob,
            json_extract(metrics, '$.edge') AS edge,
            json_extract(metrics, '$.ev_net') AS ev_net,
            (SELECT pnl FROM fills f WHERE f.correlation_id = trade.corr_id) AS pnl_realized
        FROM trade_entries trade
        WHERE tf = '15m'
    )
)
SELECT
    asset,
    distance_bucket,
    COUNT(*) AS n_trades,
    ROUND(AVG(implied_prob), 3) AS avg_kalshi_price,
    ROUND(AVG(model_prob), 3) AS avg_model_prob,
    ROUND(AVG(edge) * 100, 2) AS avg_edge_pct,
    ROUND(AVG(ev_net) * 100, 2) AS avg_ev_net_pct,
    ROUND(AVG(pnl_realized), 4) AS avg_realized_pnl,
    ROUND(AVG(z_score), 2) AS avg_z_score,
    -- Model accuracy: is realized > implied?
    ROUND(SUM(CASE WHEN pnl_realized > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS win_rate_pct
FROM distance_buckets
GROUP BY asset, distance_bucket
ORDER BY asset, distance_bucket;


-- ── 3. Per-Asset Volatility Scale Validation ────────────────────────────────
-- Validates that sigma_15m assumptions match realized volatility

SELECT
    asset,
    ROUND(AVG(sigma_15m) * 100, 2) AS assumed_sigma_pct,
    ROUND(AVG(ABS(delta_pct)) * 100, 2) AS avg_abs_move_pct,
    ROUND(STDDEV(ABS(delta_pct)) * 100, 2) AS std_move_pct,
    ROUND(AVG(z_score), 2) AS avg_z_score,
    -- Empirical sigma from realized moves
    ROUND((STDDEV(delta_pct) * SQRT(4)) * 100, 2) AS empirical_15m_sigma_pct
FROM (
    SELECT
        json_extract(metrics, '$.asset') AS asset,
        json_extract(metrics, '$.sigma_15m') AS sigma_15m,
        json_extract(metrics, '$.delta_pct') AS delta_pct,
        json_extract(metrics, '$.z_score') AS z_score
    FROM trade_entries
    WHERE tf = '15m'
)
GROUP BY asset
ORDER BY 
    CASE asset
        WHEN 'BTC' THEN 1
        WHEN 'ETH' THEN 2
        WHEN 'SOL' THEN 3
        WHEN 'XRP' THEN 4
        WHEN 'DOGE' THEN 5
    END;


-- ── 4. Time-of-Day Edge Quality (4am Anomaly Detection) ─────────────────────
-- Identifies if edge quality degrades at specific times (e.g., 4am issues)

SELECT
    strftime('%H', entry_time) AS hour_utc,
    asset,
    COUNT(*) AS n_trades,
    ROUND(AVG(edge) * 100, 2) AS avg_edge_pct,
    ROUND(AVG(ev_net) * 100, 2) AS avg_ev_net_pct,
    ROUND(AVG(pnl_realized), 4) AS avg_realized_pnl,
    ROUND(SUM(CASE WHEN pnl_realized > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS win_rate_pct
FROM (
    SELECT
        entry_time,
        json_extract(metrics, '$.asset') AS asset,
        json_extract(metrics, '$.edge') AS edge,
        json_extract(metrics, '$.ev_net') AS ev_net,
        (SELECT pnl FROM fills f WHERE f.correlation_id = trade.corr_id) AS pnl_realized
    FROM trade_entries trade
    WHERE tf = '15m'
)
GROUP BY hour_utc, asset
HAVING n_trades >= 5  -- Minimum sample size
ORDER BY hour_utc, asset;


-- ── 5. Fee Impact Analysis ───────────────────────────────────────────────────
-- Validates that EV_net > 0 after fees in profitable buckets

SELECT
    asset,
    edge_bucket,
    COUNT(*) AS n_trades,
    ROUND(AVG(fee) * 100, 3) AS avg_fee_pct,
    ROUND(AVG(EV_gross) * 100, 2) AS avg_ev_gross_pct,
    ROUND(AVG(EV_net) * 100, 2) AS avg_ev_net_pct,
    ROUND(AVG(EV_net - fee) * 100, 2) AS ev_after_fee_check  -- Should equal EV_net
FROM (
    SELECT
        json_extract(metrics, '$.asset') AS asset,
        json_extract(metrics, '$.fee') AS fee,
        json_extract(metrics, '$.EV_gross') AS EV_gross,
        json_extract(metrics, '$.EV_net') AS EV_net,
        CASE
            WHEN json_extract(metrics, '$.edge') < 0.04 THEN '0-4% (below)'
            WHEN json_extract(metrics, '$.edge') < 0.06 THEN '4-6% (target)'
            WHEN json_extract(metrics, '$.edge') < 0.08 THEN '6-8% (strong)'
            ELSE '8%+ (very_strong)'
        END AS edge_bucket
    FROM trade_entries
    WHERE tf = '15m'
)
GROUP BY asset, edge_bucket
ORDER BY asset, edge_bucket;


-- ── 6. Model Calibration Check ──────────────────────────────────────────────
-- Compares model_prob to realized hit rate by probability bucket

WITH prob_buckets AS (
    SELECT
        asset,
        CASE
            WHEN model_prob < 0.40 THEN 'p<40% (low)'
            WHEN model_prob < 0.50 THEN '40-50% (mod_low)'
            WHEN model_prob < 0.60 THEN '50-60% (neutral)'
            WHEN model_prob < 0.70 THEN '60-70% (mod_high)'
            ELSE 'p>=70% (high)'
        END AS prob_bucket,
        model_prob,
        implied_prob,
        edge,
        pnl_realized,
        -- Did the trade win?
        CASE WHEN pnl_realized > 0 THEN 1 ELSE 0 END AS hit
    FROM (
        SELECT
            json_extract(metrics, '$.asset') AS asset,
            json_extract(metrics, '$.model_prob') AS model_prob,
            json_extract(metrics, '$.implied_prob') AS implied_prob,
            json_extract(metrics, '$.edge') AS edge,
            (SELECT pnl FROM fills f WHERE f.correlation_id = trade.corr_id) AS pnl_realized
        FROM trade_entries trade
        WHERE tf = '15m'
    )
)
SELECT
    asset,
    prob_bucket,
    COUNT(*) AS n_trades,
    ROUND(AVG(model_prob) * 100, 1) AS model_prob_pct,
    ROUND(AVG(implied_prob) * 100, 1) AS kalshi_prob_pct,
    ROUND(SUM(hit) * 100.0 / COUNT(*), 1) AS realized_hit_rate_pct,
    ROUND(AVG(edge) * 100, 2) AS avg_edge_pct,
    -- Calibration gap: realized should match model
    ROUND((AVG(model_prob) - SUM(hit) * 1.0 / COUNT(*)) * 100, 1) AS calibration_gap_pct
FROM prob_buckets
GROUP BY asset, prob_bucket
HAVING n_trades >= 10  -- Minimum for statistical significance
ORDER BY asset, prob_bucket;


-- ═══════════════════════════════════════════════════════════════════════════════
-- PYTHON ANALYSIS TEMPLATE (for Jupyter/polars/pandas)
-- ═══════════════════════════════════════════════════════════════════════════════

/*
import polars as pl
import re

# Parse TRADE_ENTRY logs
def parse_trade_entry_log(line: str) -> dict:
    """Extract metrics from [TRADE_ENTRY] log line."""
    # Example:
    # [TRADE_ENTRY] KXBTC-15M-250501-T85300 | asset_tf=BTC:15m | ... 
    # spot=78320.5 strike=78500.0 delta_pct=0.00229 delta_bps=22.9 z=0.23 ...
    
    pattern = r'\[TRADE_ENTRY\]\s+(\S+)\s+\|\s+asset_tf=(\S+)\s+\|\s+edge=([\d.]+)\s+\|\s+conf=([\d.]+)'
    match = re.search(pattern, line)
    if not match:
        return None
    
    ticker, asset_tf, edge, conf = match.groups()
    
    # Extract metrics section
    metrics_pattern = r'spot=([\d.]+)\s+strike=([\d.]+)\s+delta_pct=([\d.]+)\s+delta_bps=([\d.]+)\s+z=([\d.]+)\s+sigma_15m=([\d.]+)\s+kalshi_price=([\d.]+)\s+implied_prob=([\d.]+)\s+model_prob=([\d.]+)\s+edge=([\d.]+)\s+EV_gross=([\d.-]+)\s+fee=([\d.]+)\s+EV_net=([\d.-]+)'
    m = re.search(metrics_pattern, line)
    
    if m:
        spot, strike, delta_pct, delta_bps, z, sigma, kalshi, implied, model, edge, ev_gross, fee, ev_net = m.groups()
        return {
            'ticker': ticker,
            'asset': asset_tf.split(':')[0],
            'tf': asset_tf.split(':')[1],
            'edge': float(edge),
            'conf': float(conf),
            'spot': float(spot),
            'strike': float(strike),
            'delta_pct': float(delta_pct),
            'delta_bps': float(delta_bps),
            'z_score': float(z),
            'sigma_15m': float(sigma),
            'kalshi_price': float(kalshi),
            'implied_prob': float(implied),
            'model_prob': float(model),
            'edge_calc': float(edge),
            'ev_gross': float(ev_gross),
            'fee': float(fee),
            'ev_net': float(ev_net),
        }
    return None

# Load and parse logs
trades = []
with open('logs/trading_2026-05-01.log') as f:
    for line in f:
        if '[TRADE_ENTRY]' in line:
            parsed = parse_trade_entry_log(line)
            if parsed:
                trades.append(parsed)

df = pl.DataFrame(trades)

# Analysis: Edge buckets by asset
edge_bucket_performance = df.with_columns(
    pl.when(pl.col('edge') < 0.04).then('0-4%')
      .when(pl.col('edge') < 0.06).then('4-6%')
      .when(pl.col('edge') < 0.08).then('6-8%')
      .otherwise('8%+')
      .alias('edge_bucket')
).group_by(['asset', 'edge_bucket']).agg([
    pl.count().alias('n_trades'),
    pl.col('edge').mean().alias('avg_edge'),
    pl.col('ev_net').mean().alias('avg_ev_net'),
    pl.col('z_score').mean().alias('avg_z'),
])

print(edge_bucket_performance.sort(['asset', 'edge_bucket']))
*/
