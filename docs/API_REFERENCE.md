# MERID API Reference

**Version:** 2.0.0  
**Base URL:** `http://localhost:8000`  
**Documentation:** `/docs` (Swagger UI), `/redoc` (ReDoc)

---

## Authentication

Currently, the API does not require authentication for local development. Production deployments should implement API key authentication.

---

## Unified Pipeline

#### GET `/api/v1/pipeline/summary`
Full pipeline status (domains, venues, instruments, proposals).

#### GET `/api/v1/pipeline/risk`
Global risk manager summary (domain exposure, daily loss, position counts).

#### GET `/api/v1/pipeline/risk-context`
Live RiskContext snapshot (CQI, size_scale_factor, approval_threshold_boost, kill switch status).

#### GET `/api/v1/pipeline/instruments`
Instrument registry (merid_symbol ↔ venue:native_symbol mappings).

#### GET `/api/v1/pipeline/venues`
Venue configs + adapter health status.

#### GET `/api/v1/pipeline/proposals`
Recent trade proposal history.

#### POST `/api/v1/pipeline/domain/enable`
Enable a trade domain. Body: `{"domain": "crypto"}`

#### POST `/api/v1/pipeline/domain/disable`
Disable a trade domain.

#### POST `/api/v1/pipeline/domain/halt`
Halt a domain (emergency).

#### POST `/api/v1/pipeline/venue/mode`
Set venue mode. Body: `{"venue": "alpaca", "mode": "paper"}`

---

## Prediction Markets

#### GET `/api/v1/prediction-markets/summary`
Full prediction markets dashboard summary.

#### GET `/api/v1/prediction-markets/risk`
Risk summary + breach log.

#### GET `/api/v1/prediction-markets/alerts`
Alert history.

#### GET `/api/v1/prediction-markets/venue-gate`
Mode/venue status (SIM/PAPER/LIVE, blocked venues).

#### POST `/api/v1/prediction-markets/mode`
Set prediction market mode. Body: `{"mode": "paper"}`

#### POST `/api/v1/prediction-markets/kill-switch`
Activate/deactivate kill switch. Body: `{"activate": true}`

---

## Wallet & Treasury

#### GET `/api/v1/wallet/balances`
Wallet balances (paper engine cash + positions + vault balances + guard cap usage).

#### GET `/api/v1/treasury/overview`
Treasury overview (equity + positions + guard domain caps + strategy proposals + session stats).

---

## Operator

#### GET `/api/operator/summary`
Bundled operator dashboard (portfolio + risk + swarm + system status).

#### GET `/api/operator/audit-trail`
Operator audit trail entries.

---

## Betting Consensus

#### GET `/api/v1/betting/consensus/summary`
All events with merged consensus (sportsbook + prediction market + swarm).

#### GET `/api/v1/betting/consensus/live/{event_id}`
Single event live consensus.

#### GET `/api/v1/betting/consensus/metrics`
Performance metrics (win rate, ROI, PnL).

#### POST `/api/v1/betting/consensus/opinion`
Submit swarm opinion for an event.

#### POST `/api/v1/betting/consensus/plan`
Submit a betting plan.

#### POST `/api/v1/betting/consensus/settle`
Settle a bet.

---

## Signal Layer & Flow

#### GET `/api/v1/signals/dashboard`
Signal layer dashboard (features, arb opportunities, CQI, drift).

#### GET `/api/v1/flow/radar`
Flow radar view (capital flows, consensus state).

---

## Health & System

#### GET `/healthz`
Health check.

#### GET `/risk/status`
Circuit breaker + kill switch status.

#### GET `/risk/commitments`
Historical commitments audit trail.

#### POST `/risk/kill-switch/enable`
Emergency stop — halt all trading.

---

## Dev Swarm

#### GET `/api/dev-swarm/tasks`
Dev Swarm task list.

#### GET `/api/dev-swarm/stats`
Dev Swarm statistics.

#### GET `/api/dev-swarm/codebase-drift`
Codebase drift audit results.

#### POST `/api/dev-swarm/pause`
Pause the Dev Swarm.

#### POST `/api/dev-swarm/resume`
Resume the Dev Swarm.

---

## WebSocket Endpoints

#### WS `/ws/market/{symbol}`
Real-time market data stream for a symbol.

---

## Error Responses

All endpoints return errors in this format:

```json
{
  "detail": "Error message"
}
```

**HTTP Status Codes:**
- `200` - Success
- `400` - Bad Request
- `404` - Not Found
- `422` - Validation Error
- `500` - Internal Server Error

---

## Rate Limits

No rate limits in development mode. Production deployments should implement appropriate rate limiting.

---

*For the full interactive API docs, start the server (`make serve`) and visit http://localhost:8000/docs*
