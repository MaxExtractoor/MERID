# 2026-11-05 — orderbook_delta SID never learned: readiness halt + recovery dead-end

## Summary

Two independent control-plane defects — not strategy economics — blocked all
live entries for ~38 hours and then trapped the process in an unrecoverable
halt state:

1. **Missing SID learning**: Kalshi answers `orderbook_delta` batch
   `subscribe` commands with `type=ok` frames (`msg.market_tickers`, no
   `channel`, usually no `sid`). The client only recorded subscription
   evidence from `type=subscribed` frames with `msg.channel`/`msg.sid`, so
   `_subscription_ids["orderbook_delta"]` was never set.
   `is_orderbook_subscription_confirmed()` returned False for every ticker →
   `ws_subscribed` failed on all 5 markets → `all_markets_unready:ws_subscribed=5`
   → `allow_new_entries=False` → every candidate rejected `ENTRIES_DISABLED`.

2. **Recovery dead-end**: feed-recovery paths in `ws_bridge.py` and
   `market_state.py` called `complete_preflight(auto_enable=True)` from
   `RECOVERY_RUNNING`. That API is designed to refuse in that state, and the
   refusal transition overwrote `reason_codes` with
   `RECOVERY_VERIFICATION_REQUIRED` — so the recoverable-reason retry checks
   (`WS_DATA_PLANE_DEAD`, `STALE_MARKET_DATA`, `BOOK_FEED_DEGRADED`) could
   never match again. Permanent halt until restart.

## Timeline (UTC)

- 2026-11-03 22:49 — last real fill (ETH YES buy @75c).
- 2026-11-04 ~01:11 — last order attempt (REJECTED).
- 2026-11-04 13:53 — `type=subscribed` acks for `orderbook_delta` observed
  (sid=1); connection churn produced first-subscribe acks.
- 2026-11-04 ~21:27 — last observed `subscribed` ack; long-lived connections
  only get `ok` acks thereafter.
- 2026-11-05 12:26 — pid 12664 preflight passed → `LIVE_ENTRIES_ENABLED`.
- 2026-11-05 12:26→15:26 — entries "enabled" but `allow_new_entries=False`
  on every cycle with candidates (`all_markets_unready:ws_subscribed=5`).
- 2026-11-05 15:26:32 — halt `ws_io_thread_exited` (`WS_DATA_PLANE_DEAD`,
  `STALE_MARKET_DATA`).
- 2026-11-05 15:31:00 — `ws_data_plane_recovered` → `RECOVERY_RUNNING` →
  `complete_preflight` refusal → `RECOVERY_VERIFICATION_REQUIRED` →
  permanently halted.

## Funnel evidence (enabled window, 1587 cycles)

| Stage | Count | Terminal reason |
|---|---|---|
| decision telemetry records | ~7,900 | 5 assets × cycles |
| signal-stage rejections | ~7,351 | `no_positive_executable_edge` 5,075; `price_band_both_sides_disabled` 1,524; TTE cutoffs ~900; `market_discovered` 238; `book_not_trusted` 184; `pinned_fav_maker_only` 164 |
| route-variant ENTER/selected rows | ~1,261 | ≈315 unique candidates (3–4 route rows each) |
| allocator-stage decisions | 24 | all `ENTRIES_DISABLED` |
| order attempts | 0 | none reached router |

The 24 allocator-stage decisions are **not** 24 guaranteed orders or missed
fills — they are candidates killed by the readiness gate before sizing,
intent persistence, or submission.

## Cascading damage from the missing SID

- `request_orderbook_snapshot` fell back to REST all day
  (`[WS-GET-SNAPSHOT] No subscription ID tracked`) → `book_source_degraded`,
  `REST_VERIFIED_DEGRADED` quote ownership → extra signal rejections.
- Rollover `update_subscription`/`delete_markets` was skipped (sid None) →
  expired tickers kept streaming → queue pressure and drop-untrusted storms.
  This is a **plausible contributing mechanism** to the 15:26
  `ws_io_thread_exited`, not a proven cause.
- `order_router.py` applies the same confirmation gate — even a passed
  candidate would have died at submission.

## Root cause detail

`ws.py::_record_subscription_confirmation` was invoked only for
`msg_type == "subscribed"` and required `msg.channel`. Kalshi's observed
2026-11-05 behavior: batch orderbook subscribes return `type=ok` with only
`msg.market_tickers` (add-markets joins the existing per-connection SID, so
no sid is even sent). `list_subscriptions` was issued at 12:25:55 and its
`ok` response (`msg=[{channel, sid}, ...]`) was likewise ignored.

## Fixes

`merid/event_venues/kalshi/ws.py`
- `_record_ok_confirmation()`: learns sids from all `ok` shapes —
  `msg` list (`list_subscriptions`), `msg` dict, top-level `data.sid`,
  and a pending `cmd id → channel` map populated at every `subscribe`
  send site. Fail-closed when no channel or sid can be resolved.
- `_note_orderbook_subscription_observation`: when no SID was ever acked,
  adopts the sid from live orderbook frames **only** for tickers already
  claimed in `_orderbook_tickers` (Kalshi only streams orderbook frames for
  subscribed markets — traffic for a claimed ticker is the acknowledgement).
- `_record_subscription_sid`: extracted shared recorder; an orderbook sid
  change revokes all per-ticker observation evidence.
- `_reset_subscription_evidence` (called on every `connect()` and session
  recycle) clears sids, per-ticker observations, and the pending map;
  `is_orderbook_subscription_confirmed` additionally requires the
  observation to match the current connection generation.
- Error responses drop pending cmd-id mappings so a later unrelated `ok`
  cannot bind the wrong channel.

Transport evidence stays separate from book trust: SID adoption only affects
the subscription-identity gate. `ws_snapshot_complete`, `quote_fresh`,
`quote_coherent`, `quote_owner_trusted`, `market_state_applied` remain
independent per-ticker readiness checks.

`merid/observability/live_runtime_state.py`
- `collect_runtime_recovery_evidence()` probes real subsystems:
  fills-poller reconciliation freshness, circuit-breaker fill watermark
  (with ledger fallback), canonical portfolio authority, position cache +
  client availability for exits, router availability, and
  `auto_execution_mode`/`observe_only` for `production_live`.
- `runtime_recovery_evidence_missing()` mirrors the
  `complete_runtime_recovery` gate for pre-screening.

`merid/event_venues/kalshi/ws_bridge.py` + `market_state.py`
- Recovery attempts now pre-screen evidence; if incomplete they stay halted
  with original reason codes (no transition churn).
- `RECOVERY_RUNNING → complete_runtime_recovery(evidence)`; on refusal they
  transition back to `LIVE_ENTRIES_HALTED` **preserving the original reason
  codes** so the retry matchers keep working.

## Tests / verification

- `tests/event_venues/kalshi/test_ws_subscription_evidence.py` — +5 cases:
  ok-frame sid via pending map, list-subscriptions array, dict-msg ok,
  fail-closed no-sid, pending-map cleanup on error.
- `tests/test_runtime_recovery_evidence.py` — refusal with missing evidence,
  success with complete evidence, original-code preservation on bounce-back.
- Frame fixtures: `tests/fixtures/kalshi-incidents/2026-11-05-orderbook-sid-ack-frames.json`
- State snapshot: `tests/fixtures/kalshi-incidents/2026-11-05-halt-state-snapshot.json`

## Not demonstrated defects

- `no_positive_executable_edge` (5,075 signal rejections) is legitimate
  economics — executable EV after costs was negative. Thresholds unchanged.
- `audit_writer_unhealthy` fired once; tracked separately — the 17.5GB audit
  DB alone does not establish the cause.

## Deployment acceptance checklist

Readiness restored when the patched process shows: `orderbook_delta` SID
learned (ack or frame bootstrap); per-ticker `ws_subscribed=True`; WS
snapshot path used instead of REST fallback (for legitimate reasons only);
rollover `delete_markets` targets the live SID; reconnect invalidates and
rebuilds evidence; recovery refusals preserve original reasons.

Execution path verified when a naturally eligible candidate traces:
selected → allocator approval → router approval → persisted intent →
submission attempt → explicit venue outcome → reconciled state. If no
eligible candidate appears, report "readiness restored, execution awaiting
an eligible opportunity" — do not force a trade to close the incident.
