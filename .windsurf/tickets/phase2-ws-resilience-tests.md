# Phase 2: WS Resilience Tests

**Priority:** High  
**Baseline:** Commit `c25d2702` - Kalshi WS bridge + explainability integration  
**Component:** `merid/event_venues/kalshi/ws_bridge.py`, `merid/event_venues/kalshi/ws.py`

## Summary

Add comprehensive WebSocket resilience tests covering disconnect/reconnect, sequence gap recovery, and malformed message handling to ensure production-grade reliability for Kalshi orderbook ingestion.

## Acceptance Criteria

### 1. Disconnect → Exponential Backoff Reconnect
- [ ] Test disconnect → reconnect respects exponential backoff (e.g., 1s, 2s, 4s, 8s, capped at 60s)
- [ ] Assert backoff does not exceed Kalshi's documented rate limits/tier caps (Basic: 20 read requests/sec)
- [ ] Verify reconnect re-subscribes to all previously tracked orderbook channels
- [ ] Test repeated failures → backoff continues doubling until max cap

**Reference:** [Kalshi Rate Limits](https://docs.kalshi.com/getting_started/rate_limits)

### 2. Sequence Gap Recovery
- [ ] Simulate gap in orderbook delta sequence numbers
- [ ] Assert bridge invalidates cached orderbook state
- [ ] Verify bridge triggers fresh REST snapshot via `GET /markets/{ticker}/orderbook`
- [ ] Confirm snapshot response conforms to orderbook schema: `yes_bid + no_bid <= 100 + ε`
- [ ] Test deltas resume processing after snapshot refresh

**Reference:** [Kalshi Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses)

### 3. Malformed Message Handling
- [ ] Send WS messages with missing required fields
- [ ] Send invalid JSON payloads
- [ ] Send messages with incorrect event types
- [ ] Assert bridge drops each malformed message + logs error
- [ ] Verify bridge continues processing subsequent valid messages without crash
- [ ] Confirm no event bus pollution from malformed data

## Test File Location

`tests/event_venues/kalshi/test_ws_resilience.py`

## Implementation Notes

- Use `AsyncMock` and `patch` to simulate WebSocket disconnect/reconnect scenarios
- Mock REST orderbook endpoint for snapshot refresh tests
- Inject sequence gaps by manipulating delta message sequence numbers
- Use pytest fixtures for WS bridge setup with configurable backoff parameters

## Definition of Done

- [ ] All test scenarios pass
- [ ] Test coverage for resilience paths >80%
- [ ] No degradation in existing WS bridge tests
- [ ] CI green
