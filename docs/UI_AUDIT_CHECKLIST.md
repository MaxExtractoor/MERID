# UI Audit Checklist

## Purpose

This checklist ensures all UI components are properly wired to live data sources.

## Kalshi Dashboard

- [x] Market list loads from `/api/v1/kalshi/markets`
- [x] Order form posts to `/api/v1/kalshi/orders`
- [x] Portfolio positions update via WebSocket
- [x] PnL chart wired to paper trading engine
- [x] Risk feed shows real-time risk metrics

## Operator Control Plane

- [x] Mode switch (paper/live) calls `/api/v1/operator/mode`
- [x] Kill switch wired to execution gate
- [x] Audit trail loads from operator API
- [x] Equity series chart renders P&L over time

## Agent Performance

- [x] Agent grid shows live predictions
- [x] Debate view shows consensus rounds
- [x] Calibration dashboard shows Brier scores

## Signals & Sentiment

- [x] Sentiment bundle card shows real scores
- [x] Kalshi signals feed updating
- [x] Correlation panel wired to data

## Monitoring

- [x] Venue health grid shows circuit breaker states
- [x] Alert history panel loads from `/api/v1/alerts`
- [x] SLO monitor visible in operator view

## Known Gaps

None at time of audit.
