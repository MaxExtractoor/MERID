# MERID — Testing Guide

Testing strategy for the Kalshi swarm intelligence platform.

---

## Quick Commands

```bash
make golden-path              # full test suite
make preflight                # tests + readiness + drift audit + risk context
make risk-context             # print live risk state JSON
make pm-test                  # prediction market tests only
make pipeline-test            # pipeline tests only
pytest tests/ -v --tb=short   # run tests directly
```

---

## Test Suites

| Suite | File | Tests |
|-------|------|-------|
| E2E Golden Path | `tests/test_e2e_golden_path.py` | 25 |
| Signal Layer | `tests/test_signal_layer.py` | 98 |
| Live Feeds | `tests/test_live_feeds.py` | 26 |
| Prediction Markets | `tests/test_prediction_markets.py` | 109 |
| Unified Pipeline | `tests/test_unified_pipeline.py` | 75 |
| Canonical Agents | `tests/test_canonical_agents.py` | 73 |
| Hardening | `tests/test_hardening.py` | 84 |
| Forecasters | `tests/test_forecasters.py` | 22 |
| Sprint D–G | `tests/test_sprint_d_g.py` | 53 |
| Sprint H–I | `tests/test_sprint_h_i.py` | 44 |
| Sprint M | `tests/test_sprint_m.py` | 55 |
| Sprint N–O | `tests/test_sprint_n_o.py` | 46 |
| Sprint Q–R | `tests/test_sprint_q_r.py` | 36 |
| Sidebar Wiring | `tests/test_sidebar_wiring.py` | 36 |

---

## API Smoke Tests

Start the server (`make serve`) and test key endpoints:

```bash
# Health check
curl http://localhost:8000/healthz

# Kalshi markets
curl http://localhost:8000/api/v1/kalshi/markets

# Pipeline status
curl http://localhost:8000/api/v1/pipeline/summary

# Risk context
curl http://localhost:8000/api/v1/pipeline/risk-context

# Operator summary
curl http://localhost:8000/api/operator/summary

# Kill switch status
curl http://localhost:8000/risk/status
```

Full interactive API explorer at [http://localhost:8000/docs](http://localhost:8000/docs).

---

## Frontend Verification

Start the dashboard (`cd web/react && npm run dev`) and verify:

1. **All 17 views load** — Click through every sidebar item
2. **No console errors** — Open DevTools → Console
3. **API polling works** — Network tab shows periodic requests
4. **Kill switch responds** — Toggle in Kill Switch view
5. **Command palette works** — Press `Ctrl+K`, search for views

### Frozen View Checklist

- [ ] Overview
- [ ] Terminal (KalshiTerminal)
- [ ] Markets (KalshiDashboard)
- [ ] Portfolio (KalshiPortfolio)
- [ ] Positions (deep-link to Portfolio)
- [ ] Orders (deep-link to Portfolio)
- [ ] Agent Grid (KalshiGrid)
- [ ] Swarm Matrix (SwarmConsensus)
- [ ] Performance (KalshiPerformance)
- [ ] Calibration (CalibrationDashboard)
- [ ] Lane Control
- [ ] Fear/Greed (KalshiSentiment)
- [ ] Vol & Sizing (KalshiVolDashboard)
- [ ] Operator
- [ ] Kill Switch
- [ ] Logs
- [ ] Settings

---

## Integration Test: Paper Trading Flow

1. `make serve` + `cd web/react && npm run dev`
2. Open Overview — verify health status
3. Navigate to Markets — browse Kalshi markets
4. Navigate to Agent Grid — check agent signals
5. Navigate to Swarm Matrix — verify consensus
6. Navigate to Terminal — check orderbook loads
7. Navigate to Portfolio — verify positions/orders tabs
8. Navigate to Kill Switch — verify toggle works
9. `make loop-start-execute` — start paper trading
10. Return to Portfolio — verify paper positions appear

---

## Pre-Merge Testing

Before every merge:

```bash
make preflight
```

This runs:

- Full golden path test suite
- Readiness auditor
- Codebase drift audit
- RiskContext snapshot

All must pass before merging.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Tests fail with import errors | `pip install -r requirements.txt` |
| API returns 500 | Check `make serve` terminal for traceback |
| Frontend shows loading forever | Verify backend is running on port 8000 |
| Stale test data | `MERID_FRESH_START=1 make serve` |
| Flaky async tests | Run with `pytest -x --timeout=30` |

---

Last updated: 2026-02-21.
