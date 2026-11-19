# Lead-lag shadow lane — engineering acceptance checklist

Window: starts at next production restart (emitter code merged into working
tree 2026-11-13 ~08:0x UTC; running process pid 13196 started 04:47 UTC
predates it). 24h acceptance clock starts when the emitter is confirmed
writing `logs/leadlag_shadow.jsonl` in production.

## Emitter (merid/prediction/leadlag_shadow.py)

| # | Check | How | Pass criterion |
|---|-------|-----|----------------|
| 1 | Records emitted | count lines in logs/leadlag_shadow.jsonl | >0 within first eval cycle for ETH/SOL/XRP/DOGE |
| 2 | Queue bounded | MERID_LEADLAG_SHADOW_QUEUE_MAX=20000; writer daemon | queue never blocks decision path (put_nowait) |
| 3 | Drop counters | record["quality"] + in-process stats | dropped_queue_full/write_errors/emit_errors == 0 or explained |
| 4 | Live isolation | code review: outputs only to JSONL; no reads by gates | shadow probs never enter decision/sizing/risk |
| 5 | Error isolation | all exceptions swallowed + counted | zero decision-path impact; emit_errors counter visible |
| 6 | Model frozen | model_hash a9e32477... in every record; artifact immutable | hash constant across window |
| 7 | Lane identity | decision_lane, route, candidate_id, decision_id per record | non-null for production/research-eligible rows |
| 8 | Incumbent parity | p_lane_incumbent == decision.p_yes_calibrated | exact match per record |
| 9 | Timestamps | decision_ts, feature_ts, emitted_at, rti source/observed ts | populated; feature_age_ms recorded |
| 10 | Abstention | feature_status ok / partial_missing_* / abstain_* | missing RTI -> explicit abstain, never fabricated |
| 11 | Prediction parity | offline replay of emitted features vs artifact coefs | max |dp| ~1e-16 (verified pre-deploy on 1538 preds) |
| 12 | Latency impact | compare decision-loop timing pre/post | no material degradation (measure via audit timestamps) |

## Archivers (acceptance gate)

| Source | State at handoff | Invalid interval |
|--------|------------------|------------------|
| RTI (cf_rti_ticks.db) | restarted ~08:32 UTC via 'MERID RTI archiver' task; writing 1Hz | ~05:02->08:32 UTC gap (archiver dead; production RTI feed unaffected - rti_stream_fresh passed at 04:47 startup) |
| Book (kalshi_book_archive_live2.db) | DEAD since 00:53 UTC; 71GB un-checkpointed WAL hung every restart | 00:53 UTC -> 09:07 UTC gap |
| Book (kalshi_book_archive_live3.db) | NEW collector pid 13004 healthy since 09:07 UTC; q=332, drop=0, 15 markets covering | n/a (fresh DB; pre-gap data stays in live2 pending manual checkpoint) |

Book-archive repair notes:
- Root cause: live2.db-wal = 71GB un-checkpointed; every collector start
  blocked in DB open/WAL recovery (hung pid 13744 for 4.5h; scheduled-task
  instances refused on single-collector lock).
- Fix applied: .env MERID_BOOK_ARCHIVE_DB -> kalshi_book_archive_live3.db
  (fresh DB); killed hung pid; task supervision resumed collector.
- live2.db + 71GB WAL preserved for later offline checkpoint/forensics;
  do NOT delete. depth_replay_valid=false for the entire invalid interval.
- forecast_valid remains true for RTI-sourced features where RTI coverage
  exists; top_quote_economics_valid / depth_replay_valid /
  maker_execution_valid must be joined per-interval downstream.

## Prospective program (per capture directive)

- Engineering acceptance: first 24h after emitter confirmed live.
- First research review: 14 complete UTC days (freeze date at review setup).
- One prespecified extension to 28 days max if inconclusive-but-sound.
- Primary question: does BTC add value beyond matched no-BTC control
  (p_shadow_btc_* vs p_shadow_nobtc_*), against lane-relative incumbent.
- Promotion requires: repeatable improvement, no single-day dependence,
  settlement-phase sense, observed-latency robustness, plausible economics.
- Live release additionally requires settled-fill + veto-counterfactual
  evidence, execution justification, risk review, model-release approval.
