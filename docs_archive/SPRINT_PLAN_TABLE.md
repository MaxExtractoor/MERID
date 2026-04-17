# 🚀 MERID Sprint Plan - GitHub Project Ready

## Sprint Epic 1: Minimal Stream Pipeline (HIGH)

| Task | File | Estimate | Acceptance Criteria | Status |
|------|------|----------|-------------------|--------|
| Implement BaseStream lifecycle | `streams/base_stream.py` | 4-6h | start/stop/subscribe working, internal loop functional | 📋 Backlog |
| Add health checks & metrics | `streams/base_stream.py` | 2-3h | events/sec, error rate, lag metrics exposed | 📋 Backlog |
| Implement MarketDataStream | `streams/market_data_stream.py` | 4-6h | Connects to mock source, normalizes ticks to MarketTick objects | 📋 Backlog |
| Add WebSocket/HTTP source | `streams/market_data_stream.py` | 2-3h | Live data connection with fallback to mock | 📋 Backlog |
| Create event normalization | `streams/market_data_stream.py` | 2-3h | MarketTick objects with proper schema validation | 📋 Backlog |

**Total: 14-21 hours**

---

## Sprint Epic 2: Governance Agent Slice (HIGH)

| Task | File | Estimate | Acceptance Criteria | Status |
|------|------|----------|-------------------|--------|
| Implement BaseAgent.analyze | `agents/interface.py` | 4-6h | Consumes stream events, returns AnalysisResult with signals | 📋 Backlog |
| Implement BaseAgent.vote | `agents/interface.py` | 3-4h | Takes AnalysisResult, produces Decision with confidence | 📋 Backlog |
| Implement BaseAgent.reflect | `agents/interface.py` | 3-4h | Updates internal state from outcomes, logs learning | 📋 Backlog |
| Create CryptoPredictionAgent | `agents/crypto_prediction_agent.py` | 6-8h | Full agent consuming market data and oracle prices | 📋 Backlog |
| Wire to Phase 0 persistence | `agents/crypto_prediction_agent.py` | 2-3h | Decisions persisted with metrics_state and scores | 📋 Backlog |
| Add Neo4j integration | `agents/crypto_prediction_agent.py` | 2-3h | Graph updates for governance decisions | 📋 Backlog |

**Total: 20-28 hours**

---

## Sprint Epic 3: Single Oracle Integration (HIGH)

| Task | File | Estimate | Acceptance Criteria | Status |
|------|------|----------|-------------------|--------|
| Implement _connect_impl | `oracles/base_oracle.py` | 3-4h | Connection handle with health status, retry/backoff | 📋 Backlog |
| Implement _fetch_price_impl | `oracles/base_oracle.py` | 3-4h | Returns PriceQuote with latency/error metrics | 📋 Backlog |
| Create CoinGeckoOracle | `oracles/coingecko_oracle.py` | 4-5h | Live price data from CoinGecko API | 📋 Backlog |
| Add price validation | `oracles/coingecko_oracle.py` | 2-3h | Sanity checks on price data, outlier detection | 📋 Backlog |
| Expose get_price API | `oracles/coingecko_oracle.py` | 1-2h | Simple interface for agents and monitoring | 📋 Backlog |
| Add latency monitoring | `oracles/coingecko_oracle.py` | 1-2h | <100ms target, alerts on degradation | 📋 Backlog |

**Total: 14-20 hours**

---

## Sprint Epic 4: Trading Base Methods (MEDIUM)

| Task | File | Estimate | Acceptance Criteria | Status |
|------|------|----------|-------------------|--------|
| Implement _fetch_markets_live | `trading/perp/base.py` | 4-6h | Returns List[Market] with metadata (size, tick, leverage) | 📋 Backlog |
| Implement _fetch_funding_live | `trading/perp/base.py` | 4-6h | Dict[symbol, FundingInfo] with rates and timing | 📋 Backlog |
| Add venue config support | `trading/perp/base.py` | 2-3h | Configurable endpoints and auth | 📋 Backlog |
| Create BinancePerpTrading | `trading/perp/binance.py` | 6-8h | Concrete implementation for Binance perps | 📋 Backlog |
| Add order validation | `trading/perp/base.py` | 2-3h | Order spec validation before submission | 📋 Backlog |
| Dry-run execution path | `trading/perp/base.py` | 3-4h | Order building and persistence without real trading | 📋 Backlog |

**Total: 21-30 hours**

---

## Sprint Epic 5: Monitoring Skeletons (MEDIUM)

| Task | File | Estimate | Acceptance Criteria | Status |
|------|------|----------|-------------------|--------|
| Complete liquidation monitor | `monitoring/liquidation_monitor.py` | 4-6h | Threshold alerts, position monitoring, margin ratio checks | 📋 Backlog |
| Add whale signal processing | `monitoring/liquidation_monitor.py` | 3-4h | Process Nansen/Arkham signals, generate alerts | 📋 Backlog |
| Complete prediction markets monitor | `monitoring/prediction_markets.py` | 4-6h | Market data fetching, belief updates to agents | 📋 Backlog |
| Add health checks module | `monitoring/health_checks.py` | 2-3h | System-wide health monitoring and alerting | 📋 Backlog |
| Create metrics dashboard | `monitoring/metrics_dashboard.py` | 3-4h | Live metrics for all monitoring components | 📋 Backlog |

**Total: 16-23 hours**

---

## Sprint Epic 6: Web3 Connectivity (MEDIUM)

| Task | File | Estimate | Acceptance Criteria | Status |
|------|------|----------|-------------------|--------|
| Add Web3 provider bootstrap | `web3/provider.py` | 3-4h | Connection to Ethereum node, provider management | 📋 Backlog |
| Implement basic contract calls | `web3/contracts.py` | 4-6h | Read contract state, basic transaction building | 📋 Backlog |
| Add transaction signing | `web3/transactions.py` | 3-4h | Sign transactions, gas estimation, nonce management | 📋 Backlog |
| Create Web3 utilities | `web3/utils.py` | 2-3h | Address conversion, unit handling, validation | 📋 Backlog |
| Add error handling | `web3/errors.py` | 2-3h | RPC errors, network issues, retry logic | 📋 Backlog |

**Total: 14-20 hours**

---

## Sprint Epic 7: Stress & Concurrency Testing (MEDIUM)

| Task | File | Estimate | Acceptance Criteria | Status |
|------|------|----------|-------------------|--------|
| Create load testing framework | `tests/load_test.py` | 3-4h | Concurrent request testing framework | 📋 Backlog |
| Test Phase 0 APIs under load | `tests/api_load_test.py` | 4-6h | 1000+ concurrent requests, response time analysis | 📋 Backlog |
| Add concurrency testing | `tests/concurrency_test.py` | 3-4h | Race condition testing, data consistency | 📋 Backlog |
| Create performance benchmarks | `tests/benchmarks.py` | 2-3h | Response time, throughput, resource usage | 📋 Backlog |
| Add stress test reports | `tests/reports.py` | 2-3h | Automated performance reporting | 📋 Backlog |

**Total: 14-20 hours**

---

## Sprint Epic 8: Neo4j Integration (LOW)

| Task | File | Estimate | Acceptance Criteria | Status |
|------|------|----------|-------------------|--------|
| Hard Neo4j connection | `core/neo4j_client.py` | 2-3h | Robust connection with retry logic | 📋 Backlog |
| Add governance graph updates | `core/governance_graph.py` | 3-4h | Decision persistence, relationship tracking | 📋 Backlog |
| Create graph queries | `core/graph_queries.py` | 2-3h | Common governance queries and analytics | 📋 Backlog |
| Add graph health monitoring | `core/graph_health.py` | 1-2h | Connection status, query performance | 📋 Backlog |

**Total: 8-12 hours**

---

## 📊 Sprint Planning Summary

### **Phase 1: Core Vertical Slice (Week 1)**
**Focus:** Stream → Oracle → Agent → Decision → Persistence
- **Sprint Epic 1:** Minimal Stream Pipeline (14-21h)
- **Sprint Epic 2:** Governance Agent Slice (20-28h) 
- **Sprint Epic 3:** Single Oracle Integration (14-20h)
- **Total:** 48-69 hours (12-17 days)

### **Phase 2: Trading & Monitoring (Week 2-3)**
- **Sprint Epic 4:** Trading Base Methods (21-30h)
- **Sprint Epic 5:** Monitoring Skeletons (16-23h)
- **Total:** 37-53 hours (9-13 days)

### **Phase 3: Advanced Features (Week 4-5)**
- **Sprint Epic 6:** Web3 Connectivity (14-20h)
- **Sprint Epic 7:** Stress & Concurrency Testing (14-20h)
- **Sprint Epic 8:** Neo4j Integration (8-12h)
- **Total:** 36-52 hours (9-13 days)

---

## 🎯 **Immediate Action Plan**

### **Week 1 Priority:**
1. **Sprint Epic 1** - Stream pipeline (focus on BaseStream + MarketDataStream)
2. **Sprint Epic 2** - Agent slice (focus on BaseAgent methods + CryptoPredictionAgent)
3. **Sprint Epic 3** - Oracle integration (focus on BaseOracle + CoinGeckoOracle)

### **Success Criteria Week 1:**
- [ ] Market data flowing through stream
- [ ] Agent analyzing data and making decisions
- [ ] Oracle providing price data
- [ ] End-to-end vertical slice working

### **Technical Debt Discipline:**
- **20-25% capacity** to NotImplemented backlog
- **No new NotImplemented methods** unless Phase 1 critical
- **Weekly metrics** tracking progress

---

## 🚀 **Ready for GitHub Project Board**

Copy this table directly into GitHub Project or Issues:
1. Create 8 epics with the sprint names
2. Break down each epic into individual tasks
3. Assign estimates and acceptance criteria
4. Track progress with status column
5. Focus on Phase 1 epics first

**Total estimated effort: 135-186 hours (34-47 days)**

**Focus on Phase 1 first: 48-69 hours for core vertical slice!** 🎯
