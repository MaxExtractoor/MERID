# Maker execution audit — actual orders only

Generated: 2026-11-13T11:51:30.171058+00:00

Cohort: entry orders, `resolved_execution_mode=maker` (231 attempts, 129 markets with settled outcomes)

## Headline

- Live attempts (excl. REJECTED): 122
- Any fill: 85 (69.7% of live)
- Full fill: 85 (69.7%)
- Partial: 0  Unfilled: 37
- Filled-cohort win rate: 75.3% vs mean p_selected 0.758
- Mean net payoff per filled contract: 23.99c  (total 6950.0c)

## Fill rate by segment

| segment | n | fill_any | win_rate | mean_p | payoff_c |
|---|---|---|---|---|---|
| by_side:no | 71 | 64.8% | 75.6% | 0.729 | 45.32 |
| by_side:yes | 51 | 76.5% | 75.0% | 0.791 | -3.33 |
| by_price_band:0-49 | 10 | 70.0% | 42.9% | 0.313 | -27.62 |
| by_price_band:50-79 | 79 | 69.6% | 72.9% | 0.724 | 22.18 |
| by_price_band:80-89 | 1 | 0.0% | nan% | 0.869 | nan |
| by_price_band:90-94 | 7 | 57.1% | 100.0% | 0.947 | 64.67 |
| by_price_band:95+ | 25 | 76.0% | 93.3% | 0.971 | 45.73 |
| by_asset:BTC | 6 | 16.7% | 100.0% | 0.796 | 53.00 |
| by_asset:DOGE | 20 | 85.0% | 80.0% | 0.917 | 25.92 |
| by_asset:ETH | 12 | 50.0% | 60.0% | 0.696 | 11.13 |
| by_asset:SOL | 19 | 79.0% | 64.3% | 0.623 | 16.20 |
| by_asset:XRP | 65 | 70.8% | 79.0% | 0.750 | 27.03 |
| by_lane:cheap_no_settle | 10 | 70.0% | 42.9% | 0.313 | -27.62 |
| by_lane:current_build_provisional | 8 | 25.0% | 0.0% | 0.707 | -62.50 |
| by_lane:drift_fav | 69 | 73.9% | 75.0% | 0.727 | 25.63 |
| by_lane:evidence_cell_escape | 1 | 100.0% | 100.0% | 0.835 | 24.00 |
| by_lane:maker_bid | 1 | 100.0% | 100.0% | 0.660 | 38.00 |
| by_lane:pinned_fav | 32 | 71.9% | 94.4% | 0.966 | 48.89 |
| by_lane:threshold_cell | 1 | 0.0% | nan% | 0.766 | nan |
| by_p_selected_bucket:0.90-0.94 | 5 | 80.0% | 100.0% | 0.939 | 72.75 |
| by_p_selected_bucket:<0.90 | 90 | 68.9% | 69.1% | 0.680 | 15.84 |
| by_p_selected_bucket:>=0.95 | 27 | 70.4% | 92.9% | 0.971 | 42.07 |
| by_tte_bucket:120-600s | 60 | 66.7% | 72.7% | 0.819 | 18.92 |
| by_tte_bucket:>=600s | 62 | 72.6% | 77.5% | 0.692 | 28.17 |

## Post-fill RTI reference movement (filled cohort)

- rti_chg_30s_bp: mean +1.5bp median +0.2bp (n=3)
- rti_chg_60s_bp: mean +5.6bp median -0.5bp (n=3)
- rti_chg_300s_bp: mean +20.8bp median +20.0bp (n=3)

## Limitations

- book-quote post-fill movement unavailable: book archive was down for most of the cohort window (invalid intervals recorded in the lead-lag capture acceptance notes); RTI reference movement is the adverse-selection proxy used instead
- cancel request vs ack timing not separately persisted in order_attempts (status + updated_at only)
- quote state at submission not reconstructed (payload carries admitting economics, not book depth)