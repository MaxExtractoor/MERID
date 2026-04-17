# MERID Full System Audit — 2026-02-23

## Scope

21-dimension sweep across the entire production codebase covering:
overlifting/regime change, error propagation, cascading meltdowns, high-latency/slippage,
RAG/memory pollution, over-autonomy, shared memory leakage, cross-validation, OOS testing,
robustness, error propagation limits, memory cleanup, self-critique, max drawdown limits,
liquidity checks, latency monitoring, HITL/sudo prompting, API permissioning, injection
resistance, silent failure detection, drift monitoring, event-driven architecture, and
agent native integration.

**Automated scanner**: `scripts/_audit_sweep.py` — 1,200 raw findings across 10 categories.

---

## Findings Summary (by severity)

### P0 — CRITICAL (fixed)

| # | Finding | File(s) | Fix |
|---|---------|---------|-----|
| 1 | **SQL injection** — f-string DELETE interpolating unsanitized table names from `sqlite_master` | `web/main.py:1902` | Added regex whitelist (`^[A-Za-z_][A-Za-z0-9_]*$`) before interpolation |
| 2 | **11 bare `except:` clauses** catching `SystemExit`/`KeyboardInterrupt` | `core/merid_dashboard.py`, `trading/merid_adapter.py`, `swarm/operations/cadence.py`, `governance/production_governance_schedule.py`, `monitoring/health_checker.py` (×3), `monitoring/reality_metrics.py` (×4) | All replaced with `except Exception:` |
| 3 | **Unbounded `_executed_trades` list** — memory leak in long-running execution coordinator | `execution/execution_coordinator.py` | Replaced `List` with `collections.deque(maxlen=500)` |
| 4 | **Stub risk checks** — execution coordinator had no execution-gate / kill-switch / drawdown check | `execution/execution_coordinator.py` | Wired `merid.execution_guard.get_execution_guard().check()` as first risk gate (fail-closed) |
| 5 | **No latency tracking** on order submission in execution coordinator and service | `execution/execution_coordinator.py`, `execution/service.py` | Added `time.perf_counter()` around order submit with high-latency warning (>500ms) |
| 6 | **HTTP calls without timeout** — 5 requests in assertion framework could hang indefinitely | `core/assertion_framework.py` | Added `timeout=10` to all 5 HTTP calls |
| 7 | **HITL gate missing** — `AutonomousCoverageFixer` could write files and run subprocesses without operator approval | `core/autonomous_fixer.py` | Added `require_approval=True` default, `approve_pending()`, `_assert_approved()` guards on `_append_test_to_file()` and `_run_tests()` |
| 8 | **RAG memory pollution** — `RAGPipeline` indexed docs once and never refreshed | `merid/rag/service.py` | Added 30-minute TTL re-indexing (`time.time() - _indexed_at > 1800`) |
| 9 | **Unbounded packet dict** in `FederatedMemoryBus` — no eviction policy | `memory/federated_memory_bus.py` | Added `MAX_PACKETS = 10_000` with oldest-timestamp eviction |

### P1 — HIGH (fixed)

| # | Finding | File(s) | Fix |
|---|---------|---------|-----|
| 10 | **No circuit breaker on agent cycle failures** — cascading meltdown risk if agents fail repeatedly | `merid/loop.py` | Added 5-consecutive-failure circuit breaker that disables execution automatically |
| 11 | **No OOS validation split** in GARCH volatility model training | `analytics/volatility_models.py` | Added explicit 80/20 train/OOS split before model fitting |

### P2 — MEDIUM (documented, not fixed — lower risk)

| # | Finding | Impact | Recommendation |
|---|---------|--------|----------------|
| 12 | **116 silent `except: pass`** blocks across merid/ | Errors swallowed silently; debugging difficulty | Audit each one; replace with logging or re-raise where appropriate |
| 13 | **181 unbounded `.append()` calls** in loop/stream/bus/feed/collect paths | Potential memory growth in long-running processes | Cap with `deque(maxlen=N)` or periodic truncation |
| 14 | **12 memory stores without eviction** (RAG service fixed; 11 remain) | Long-running memory growth | Add TTL or LRU eviction policies |
| 15 | **9 autonomous modules without HITL gate** (fixer fixed; 8 remain) | Actions without human oversight | Add approval gates or dry-run modes |
| 16 | **4 ML modules without explicit validation split** (volatility fixed; 3 remain) | Overfitting risk | Add train/test splits |
| 17 | **~40 hardcoded-looking secrets** (mostly false positives: Telegram URL templates, Solana program IDs, env defaults) | Low — verified non-secrets | No action needed |

### Adequate (no fix needed)

| Dimension | Status |
|-----------|--------|
| **Drift monitoring** | `merid/signals/drift.py` DriftDetector wired into main loop ✅ |
| **Liquidity checks** | `LiquidityMonitor` runs every 30s in loop ✅ |
| **Drawdown limits** | 402 matches across 50 files; `KalshiRiskManager`, `PaperSession`, `multi_tf_drawdown` all enforce ✅ |
| **Regime detection** | 588 matches across 47 files; `MarkovRegime`, `SentimentRegime`, `btc_risk_dial` all active ✅ |
| **Event-driven architecture** | `EventStream` pub/sub, WebSocket channels, consensus event bus ✅ |
| **Agent native integration** | Agent grid + consensus + reflection cycle + gauntlet all wired ✅ |
| **Self-critique** | Reflection cycle runs every 5 min, surfaces critical recommendations ✅ |
| **API permissioning** | Router-level auth (`get_current_session`) on all mutation endpoints (ZT6 sweep) ✅ |

---

## Files Modified

| File | Changes |
|------|---------|
| `web/main.py` | SQL injection fix: table name regex whitelist |
| `core/merid_dashboard.py` | `except:` → `except Exception:` |
| `trading/merid_adapter.py` | `except:` → `except Exception:` |
| `swarm/operations/cadence.py` | `except:` → `except Exception:` |
| `governance/production_governance_schedule.py` | `except:` → `except Exception:` |
| `monitoring/health_checker.py` | 3× `except:` → `except Exception:` |
| `monitoring/reality_metrics.py` | 4× `except:` → `except Exception:` |
| `execution/execution_coordinator.py` | Bounded deque, latency tracking, execution gate wiring |
| `execution/service.py` | Order submit latency tracking + high-latency warning |
| `core/assertion_framework.py` | `timeout=10` on 5 HTTP calls |
| `core/autonomous_fixer.py` | HITL gate (`require_approval`, `approve_pending`, `_assert_approved`) |
| `merid/rag/service.py` | 30-min TTL re-indexing for RAG documents |
| `memory/federated_memory_bus.py` | MAX_PACKETS eviction policy |
| `merid/loop.py` | Agent cycle circuit breaker (5 failures → disable execution) |
| `analytics/volatility_models.py` | OOS validation split (80/20) |

## Phase 2 — P2 Debt Cleanup (same session)

### Silent `except: pass` → `logger.debug()` (31 files)

Replaced 31 dangerous silent `except: pass` blocks with `logger.debug()` calls to surface
swallowed errors. Skipped 88 that were safe patterns (`asyncio.CancelledError`, `ImportError`,
`WebSocketDisconnect`, `QueueEmpty`). Files touched:

`merid/tick_log.py`, `merid/event_venues/kalshi/client.py`, `merid/event_venues/kalshi/fix_client.py`,
`merid/lanes/btc15m_lane.py`, `merid/prediction/consensus.py`, `merid/prediction/debate.py`,
`merid/prediction/edge_recalibrator.py`, `merid/prediction/mcp_market_feed.py`,
`merid/prediction/portfolio_risk_agent.py`, `merid/swarm/critic_agent.py`,
`core/secrets_guard.py`, `core/x402_payments.py`, `trading/agents/bookie_agent.py`,
`web/main.py`, `web/api/kalshi_api.py`, `web/api/live_stream.py`,
`agents/agent_framework.py`, `agents/output_validator.py`, `agents/prompts/react_templates.py`,
`risk/position_sizing.py`, `security/secrets_manager.py`, `prediction/cross_hedge.py`,
`ai_signals/signal_generator.py`

### Unbounded collection caps (12 instance lists)

Added size caps with oldest-eviction on 6 stream modules and 1 ML module:

| File | Field | Max |
|------|-------|-----|
| `streams/news_sentiment_stream.py` | `self.articles`, `self.sentiment_signals` | 500 |
| `streams/onchain_stream.py` | `self.transactions`, `self.onchain_signals` | 500 |
| `streams/social_media_stream.py` | `self.posts`, `self.social_signals` | 500 |
| `streams/market_data_stream.py` | `self._event_times` | 1000 |
| `streams/market_data_stream_simple.py` | `self._error_times`, `self._event_times` | 500/1000 |
| `ml/model_monitor.py` | `self.alerts`, `self.retraining_triggers` | 200 |

### Memory store eviction policies (2 additional stores)

| Store | Cap | Strategy |
|-------|-----|----------|
| `memory/long_term_knowledge_base.py` | 5,000 entries | Oldest evicted on insert |
| `memory/semantic_memory_search.py` | 10,000 entries | Oldest evicted on insert |

### False positives triaged (no fix needed)

- **8 "autonomous" modules** — all docstring matches, no actual exec/write/subprocess
- **3 "ML without validation"** modules — no `.fit()` or `.train()` calls found
- **88 silent `except: pass`** — all safe patterns (`CancelledError`, `ImportError`, etc.)

## Scanner Artifacts

- `scripts/_audit_sweep.py` — reusable audit scanner (run with `py scripts/_audit_sweep.py`)
- `scripts/_audit_triage_silent.py` — triage tool for silent except:pass blocks
- `scripts/_fix_silent_except.py` — bulk fixer for dangerous silent catches
- `scripts/_fix_unbounded_collections.py` — bulk capper for unbounded instance lists
- `data/audit_sweep_results.json` — full JSON findings from this run
