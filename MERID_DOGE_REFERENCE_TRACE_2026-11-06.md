# Reference Trace — First Verified Pinned-Fav Entry Path (2026-11-06)

Build: `3c24bd02` (post-restart engine, preflight passed, LIVE_ENTRIES_ENABLED).
This is the reference trace for the "six unchanged" sizing path and the first
demonstration that an eligible pinned-fav candidate reaches router → wire →
exchange acknowledgement → resting-order lifecycle on the repaired build.

## DOGE entry — six-unchanged path, VERIFIED through ack

`intent_65b8e6e36f71446ea0863180534b17d5` / `merid_4afc494993e041429fc6` /
`oa_7c27277a13af4c2d8b9fef78cc53b892` / `decision_id=cand_584fc2b1be752bc980d57427:maker_bid`
attempt rowid 25677, `KXDOGE15M-26NOV051930-30` buy_yes @94c × 6.0, GTC post-only.

| Stage (UTC) | Evidence |
|---|---|
| 00:24:03.9 | BOOK-STATE → HEALTHY (ws_orderbook_apply); TTE 356.1s |
| 00:24:03.9 | ONE-SIDED-ALLOW depth_yes=53 depth_no=0 |
| 00:24:04.7 | DUAL-SIDE-PRICE yes=95c no=6c (bid=94 ask=95) |
| 00:24:04.8 | ENTRY-ECONOMICS ask 95c → net_edge −3.72c; ask 95c → −3.33c; bid 94c → −2.83c (ask-basis passes all negative) |
| 00:24:04.98 | CANDIDATE-ADMITTED cid-d455adea6fb1, allocator_selected, count=6.0, edge_pct=−2.8255 |
| 00:24:05.0 | Dynamic sizing: count=6.0 notional=5.64 — **six fits** ($5.64 ≤ ~$6.94 cap on $19.82 shard cash); EV gate ALLOWS net_ev=−0.0593 (generic basis; lane EV was the authority) |
| 00:24:05.0 | BOUNDED-LANE edge authority: lane=pinned_fav edge_yes=0.0174→0.0264 repriced; PIPELINE PASSED_ALL_GATES |
| 00:24:05.0 | SUBMIT-REVALIDATION ok ev_order=15.25c ev_pc=2.542c prob_age=0ms book_age=250ms |
| 00:24:05.9 | ORDER-IDENTITY finalized; EXECUTION-MODE maker post_only tif=GTC; WIRE-INTENT side=bid expected_yes=94c |
| 00:24:07.5 | KALSHI-WIRE count='6' exchange_index=2 (shard 2 confirmed as submission target) |
| 00:24:08.2 | ORDER-ACK order_id=01a1ae3d-cc40-76f0-aa8f-05a05876cef4 status=accepted latency 2078ms; immediate_fill=0 |
| 00:24:09.1 | RESTING_ORDER_REGISTERED original=6; ORDER-RESULT requested=6 executed=0 remaining=6 status=resting |
| 00:24:26.8 | RESTING-ORDER-CHASE 94c→96c (side_ask=97.1c gap=3.1c cap=96c age=17.5s reprice#1) — cap = admission economic_cap, amend acknowledged |
| 00:25:12.2 | RESTING_ORDER_CANCEL_REQUESTED → CANCEL_ACKNOWLEDGED → DEREGISTERED (expired unfilled) |

Result: requested = admissible = wire = acknowledged = **6.0 contracts**, no clip
annotation. Fill: none (rested, repriced once within admission cap, cancelled at
window end). Filled-entry accounting remains NOT_OBSERVED.

## Admitting-economics reconciliation (the +2.64c question)

- `compute_canonical_edges` = gross p−P only. `edge_yes=0.0264` = 0.9664−0.94 =
  **gross edge at the bid, zero cost terms** — a diagnostic, not net EV.
- `SUBMIT-REVALIDATION ev_pc=2.5419c`/contract (15.25c/order) = the actual
  **admitting net EV** at route economics; ~0.10c/contract cost-load vs gross.
- Generic `net_ev=−0.0593` is the taker-basis diagnostic; bypassed by lane
  authority ("lane EV already enforced") — recorded as authoritative in the
  schema-v2 `admitting_economics` block going forward (commit 878c25e2).

## ETH drift_fav rejections — safe-rejection + book-quality ledger

`intent_d7c4ca2348594c85b52a1f63d867cf9c`, `KXETH15M-26NOV051945-45` buy_no ×4.0,
three attempts in ~7s (00:31:30→00:31:37), all REJECTED, no fill, reservation released.

| Attempt | Price | Outcome | Reason |
|---|---|---|---|
| merid_fc86221bcdb04143a8a7 | 64c GTC post-only | Kalshi 400 invalid_order | post-only crossed; WS no=64/65 vs REST no=62/63 (WS-REST divergence, book moving) |
| merid_18dffaad005f404e9182 | 60c GTC post-only | Kalshi 400 invalid_order | same |
| merid_f5464d5e7658432cbc96 | 62c IOC (maker→taker fallback) | router rejected | `max_execution_cost_exceeded: estimated=262.48c cap=262c` — 0.48c over |

Assessment: correct refuse-to-overpay + idempotency release (no orphan
exposure). The WS/REST divergence at decision time stays in the book-quality
ledger — `drain_lag` and the two crossing rejections are freshness findings,
not sizing findings. The 4.0-count was the lane's own requested size, not a
stake-cap clip (6×64c=$3.84 would have fit under the ~$6.94 cap).

## Coverage after this window

- six_contract_path: PASS (this trace)
- clipped_quantity_path: NOT_OBSERVED live
- no_admissible_qty_path: NOT_OBSERVED live
- maker sibling evaluated on taker vetoes: DEMONSTRATED (bid-priced pass runs;
  negative edge −3.2..−3.9c on the 9 in-band vetoed books)
- durable record reproduces admitting economics: FIXED in schema v2 (878c25e2),
  pending deployment on next authorized restart
