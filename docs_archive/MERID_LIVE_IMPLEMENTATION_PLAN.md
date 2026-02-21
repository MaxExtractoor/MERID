# 🚀 **MERID LIVE IMPLEMENTATION PLAN**
**Ruthless Prioritization for Phase 1 Readiness**  
**Strategy:** vfunction technical debt management approach

---

## 🎯 **BLOCKING EPIC: "Bring MERID Online: Streams, Agents, Oracles, Trading"**

### **Epic Overview**
**Goal:** Transform MERID from Phase 0 trial to live Phase 1 system with end-to-end data flow  
**Impact:** Unblocks live observability, real-time decision making, and governance operations  
**Risk if delayed:** Phase 1 cannot launch, no live data, no agent intelligence, no trading

---

## 📋 **TICKET BACKLOG BY CATEGORY**

### **🌊 Streams (5 NotImplemented)**
| Method | Impact on Live Phase 1 | Risk if Left As-Is | Test to Prove It Works |
|--------|------------------------|-------------------|------------------------|
| `BaseStream.stream_type()` | **BLOCKING** - Cannot identify stream types | No data ingestion possible | Stream returns correct type identifier |
| `BaseStream._connect()` | **BLOCKING** - Cannot connect to data sources | No live data flow | Connection established with health check |
| `BaseStream._disconnect()` | **MEDIUM** - Resource leaks | Memory/connection leaks | Clean disconnect without errors |
| `BaseStream._fetch_data()` | **BLOCKING** - Cannot retrieve data | No data to process | Data fetched and parsed correctly |
| `BaseStream._transform_to_events()` | **BLOCKING** - Cannot create events | No governance events | Events created with proper schema |

### **🤖 Agents (4 NotImplemented)**
| Method | Impact on Live Phase 1 | Risk if Left As-Is | Test to Prove It Works |
|--------|------------------------|-------------------|------------------------|
| `Agent.analyze()` | **BLOCKING** - No intelligence | No decision making | Agent analyzes data and returns insights |
| `Agent.vote()` | **BLOCKING** - No governance | No decisions recorded | Vote recorded with confidence and reasoning |
| `Agent.reflect()` | **MEDIUM** - No learning | Static intelligence | Learning state updated and persisted |
| `Agent.process_market_state()` | **MEDIUM** - Limited awareness | Poor decision quality | Market state processed correctly |

### **🔮 Oracles (3 NotImplemented)**
| Method | Impact on Live Phase 1 | Risk if Left As-Is | Test to Prove It Works |
|--------|------------------------|-------------------|------------------------|
| `BaseOracle._connect_impl()` | **BLOCKING** - No price data | No trading possible | Connection to price feed established |
| `BaseOracle._fetch_price_impl()` | **BLOCKING** - No prices | No valuation | Price returned with proper structure |
| `BaseOracle._disconnect_impl()` | **LOW** - Resource cleanup | Connection leaks | Clean disconnect without errors |

### **💰 Trading (2 NotImplemented)**
| Method | Impact on Live Phase 1 | Risk if Left As-Is | Test to Prove It Works |
|--------|------------------------|-------------------|------------------------|
| `TradingBase._fetch_markets_live()` | **BLOCKING** - No market data | No trading signals | Market data fetched and parsed |
| `TradingBase._fetch_funding_live()` | **MEDIUM** - Incomplete data | Poor trading decisions | Funding rates fetched correctly |

### **📊 Monitoring (4 NotImplemented)**
| Method | Impact on Live Phase 1 | Risk if Left As-Is | Test to Prove It Works |
|--------|------------------------|-------------------|------------------------|
| `LiquidationMonitor._fetch_nansen()` | **LOW** - Limited whale data | Missed opportunities | Whale signals fetched correctly |
| `LiquidationMonitor._fetch_arkham()` | **LOW** - Limited whale data | Missed opportunities | Whale signals fetched correctly |
| `PredictionMarkets.fetch_markets()` | **LOW** - No prediction data | Limited insights | Markets fetched with correct schema |
| `PredictionMarkets.fetch_market()` | **LOW** - No prediction data | Limited insights | Single market fetched correctly |

### **🏦 DeFi (2 NotImplemented)**
| Method | Impact on Live Phase 1 | Risk if Left As-Is | Test to Prove It Works |
|--------|------------------------|-------------------|------------------------|
| `Aave._execute_supply()` | **LOW** - No DeFi operations | Limited yield | Supply executed with mock transaction |
| `Aave._execute_withdraw()` | **LOW** - No DeFi operations | Limited yield | Withdraw executed with mock transaction |

---

## 🎯 **THIS WEEK: LIVE OBSERVABILITY VERTICAL SLICE**

### **Priority 1: One Concrete Stream End-to-End**
**Target:** `MarketDataStream` with mock WebSocket/Kafka source

**Implementation:**
```python
class MarketDataStream(BaseStream):
    def stream_type(self) -> str:
        return "market_data"
    
    async def _connect(self) -> bool:
        # Connect to mock WebSocket or Kafka
        # Implement health checks and backoff
        return True
    
    async def _fetch_data(self) -> Optional[object]:
        # Fetch market data from mock source
        # Implement rate limiting and error handling
        return mock_market_data
    
    async def _transform_to_events(self, data: object) -> List[EventEnvelope]:
        # Transform to governance events
        return [market_event]
```

**Health Checks & Metrics:**
- Messages per second counter
- Lag measurement (source to processing)
- Error count and rate
- Connection status monitoring
- Circuit breaker for failed connections

### **Priority 2: One Full Agent Implementation**
**Target:** `CryptoPredictionAgent` consuming market data

**Implementation:**
```python
class CryptoPredictionAgent(BaseAgent):
    async def analyze(self, market_state: Dict) -> Dict:
        # Consume stream data
        # Generate trading signals
        # Calculate confidence scores
        return {"signal": "buy", "confidence": 0.8, "reasoning": "..."}
    
    async def vote(self, proposal: Proposal) -> AgentVote:
        # Produce governance decision
        # Record vote with reasoning
        return AgentVote(vote="promote", confidence=0.7, reasoning="...")
    
    async def reflect(self, outcome: Outcome) -> None:
        # Log learning state to database
        # Update model parameters
        # Store performance metrics
```

### **Priority 3: One Oracle Path**
**Target:** `CoinGeckoOracle` for price feeds

**Implementation:**
```python
class CoinGeckoOracle(BaseOracle):
    async def _connect_impl(self) -> bool:
        # Connect to CoinGecko API
        # Test authentication
        return True
    
    async def _fetch_price_impl(self, symbol: str) -> Optional[OraclePrice]:
        # Fetch price with latency logging
        # Return typed OraclePrice struct
        return OraclePrice(symbol=symbol, price=45000.0, timestamp=now())
```

### **Vertical Slice Integration Test**
**Flow:** Stream → Oracle → Agent.analyze → Agent.vote → Decision persisted → Neo4j

**Success Criteria:**
1. Market data flows through stream
2. Oracle provides price data
3. Agent analyzes and votes
4. Decision persisted to database
5. Neo4j records governance action
6. All metrics captured

---

## 📅 **NEXT WEEK: MINIMAL TRADING LOOP**

### **Priority 1: Trading Data Fetching**
**Target:** One venue only (e.g., Binance)

**Implementation:**
```python
class BinanceTradingBase(TradingBase):
    async def _fetch_markets_live(self, limit: int) -> List[PerpMarketSnapshot]:
        # Fetch live market data from Binance
        # Parse and validate data
        return market_snapshots
    
    async def _fetch_funding_live(self, symbols: List[str]) -> List[FundingRateSnapshot]:
        # Fetch funding rates
        # Calculate funding opportunities
        return funding_snapshots
```

### **Priority 2: Dry-Run Execution Path**
**Target:** Order building and persistence without real trading

**Implementation:**
```python
class DryRunExecutor:
    async def build_order(self, signal: TradingSignal) -> Order:
        # Build order with safety checks
        # Generate unique order ID
        # Apply position sizing rules
        return order
    
    async def persist_order(self, order: Order) -> str:
        # Save to database/Neo4j
        # Log order details
        # Never hit real exchange
        return order_id
```

### **"Can Go Live" Checklist:**
- ✅ Exchange connectivity tested
- ✅ Idempotent order IDs working
- ✅ Safety limits enforced
- ✅ Circuit breakers active
- ✅ Order persistence verified
- ✅ Risk limits respected

---

## 📊 **TECHNICAL DEBT DISCIPLINE**

### **Capacity Allocation: 20-25% per week**
- **Week 1:** 20% capacity to NotImplemented backlog
- **Week 2:** 25% capacity to NotImplemented backlog
- **Ongoing:** Fixed 20% of all development time

### **Debt Prevention Rules:**
1. **New Feature Rule:** "Does this increase or decrease NotImplemented count?"
2. **Revenue Test:** Only increase debt if directly unlocks Phase 1 revenue
3. **Phase 1 Test:** Only increase debt if required for live operations
4. **Documentation Rule:** Every new method must have implementation plan

### **Weekly Debt Review:**
- **Monday:** Plan debt reduction targets
- **Wednesday:** Check progress against targets
- **Friday:** Review debt metrics and adjust next week
- **Metrics:** NotImplemented count, test coverage, integration health

---

## 🎯 **SUCCESS METRICS**

### **Week 1 Success:**
- [ ] 1 stream processing end-to-end
- [ ] 1 agent fully implemented
- [ ] 1 oracle connected and functional
- [ ] Vertical slice integration passing
- [ ] NotImplemented count reduced by 3

### **Week 2 Success:**
- [ ] Trading data fetching working
- [ ] Dry-run execution path complete
- [ ] "Can go live" checklist passed
- [ ] NotImplemented count reduced by 2
- [ ] Full trading loop tested

### **Ongoing Success:**
- [ ] NotImplemented count decreasing weekly
- [ ] Integration tests passing
- [ ] Live metrics dashboard functional
- [ ] Technical debt under control

---

## 🚀 **IMMEDIATE ACTION ITEMS**

### **Today:**
1. Create GitHub epic: "Bring MERID Online: Streams, Agents, Oracles, Trading"
2. Create 16 individual tickets with impact/risk/test criteria
3. Set up project board with columns: Backlog → This Week → Next Week → Done
4. Assign labels: streams, agents, oracles, trading, monitoring, defi

### **This Week:**
1. Implement MarketDataStream with health checks
2. Implement CryptoPredictionAgent with full methods
3. Implement CoinGeckoOracle with price fetching
4. Create vertical slice integration test
5. Reduce NotImplemented count by 3

### **Next Week:**
1. Implement Binance trading data fetching
2. Create dry-run execution path
3. Complete "Can go live" checklist
4. Reduce NotImplemented count by 2
5. Full trading loop integration test

---

## 🎯 **RUTHLESS PRIORITIZATION SUMMARY**

**Focus:** One vertical slice that makes MERID live  
**Scope:** Stream → Oracle → Agent → Decision → Persistence  
**Timeline:** 2 weeks for core functionality  
**Discipline:** 20-25% capacity to technical debt  
**Success:** Live observability and decision making

**Everything else can wait.** 🚀
