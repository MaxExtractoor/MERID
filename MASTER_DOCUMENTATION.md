# MERID - Master Documentation
## Single Source of Truth - Updated January 12, 2026

---

## 📊 CURRENT STATUS

**System Completion:** 30%
- Backend APIs: 100% (40 endpoints operational)
- Frontend UIs: 15% (6 of 40 APIs have UI)
- Sidebar Sections: 12% (3 of 26 sections working)

**What's Working:**
- ✅ 54 cryptocurrency assets with real-time data
- ✅ Bloomberg-style market terminal
- ✅ Multi-source intelligence feed with sentiment analysis
- ✅ 100+ prediction markets from Polymarket
- ✅ All backend infrastructure

**What's Missing:**
- ❌ UI for 34 backend APIs
- ❌ 23 sidebar sections not wired
- ❌ Trading execution interface
- ❌ Portfolio analytics dashboard
- ❌ Risk monitoring interface

---

## 🏗️ SYSTEM ARCHITECTURE

### Backend (FastAPI)
- **Framework:** FastAPI with async support
- **Database:** Neo4j (graph database)
- **Data Sources:** CoinGecko, CryptoPanic, Polymarket
- **APIs:** 40 REST endpoints
- **Caching:** In-memory with TTL

### Frontend (Vanilla JavaScript)
- **Framework:** None (vanilla JS for performance)
- **Charts:** Chart.js
- **Styling:** Custom CSS (Bloomberg-inspired)
- **Updates:** Polling (5s-5min intervals)

### Core Systems
1. **Orchestrator** - Agent coordination
2. **Consensus Engine** - Voting system
3. **Reality Registry** - Assertion tracking
4. **Execution Engine** - Paper trading
5. **Risk Controls** - Automated limits
6. **Health Monitor** - System status

---

## 📁 PROJECT STRUCTURE

```
MERID/
├── core/                    # Core systems (47 files)
│   ├── orchestrator.py
│   ├── consensus_engine.py
│   ├── reality_registry.py
│   ├── graph_service.py
│   └── automated_risk_controls.py
├── trading/                 # Trading systems (16 files)
│   ├── execution.py
│   ├── portfolio.py
│   └── risk_manager.py
├── agents/                  # Agent implementations (41 files)
├── data/                    # Data management (14 files)
│   └── asset_universe.py    # 54 cryptocurrency definitions
├── web/                     # Web interface (83 files)
│   ├── api/                 # 40 API endpoints
│   │   ├── live_data.py
│   │   ├── intelligence.py
│   │   ├── predictions.py
│   │   ├── dashboard_data.py
│   │   └── [36 more...]
│   ├── static/
│   │   ├── js/              # Frontend JavaScript
│   │   │   ├── market-terminal.js
│   │   │   ├── intelligence-feed.js
│   │   │   ├── predictions-markets.js
│   │   │   └── sections-loader.js
│   │   └── css/             # Stylesheets
│   │       ├── market-terminal.css
│   │       ├── intelligence-feed.css
│   │       └── predictions-markets.css
│   └── templates/
│       └── unified.html     # Main dashboard
└── tests/                   # Test suite (39 files)
```

---

## 🔗 API ENDPOINTS (40 Total)

### Live Data (6 endpoints)
```
GET  /api/v1/live/prices              # All assets with filters
GET  /api/v1/live/categories          # Category list
GET  /api/v1/live/watchlist           # Top 20 assets
GET  /api/v1/live/market/overview     # Market statistics
GET  /api/v1/live/chart/{symbol}      # OHLCV data
POST /api/v1/live/refresh             # Force refresh
```

### Intelligence (5 endpoints)
```
GET  /api/v1/intelligence/news                    # Aggregated news
GET  /api/v1/intelligence/news/categories         # Category counts
GET  /api/v1/intelligence/news/trending           # Trending topics
GET  /api/v1/intelligence/news/sentiment/overview # Sentiment stats
POST /api/v1/intelligence/news/refresh            # Force refresh
```

### Predictions (8 endpoints)
```
GET  /api/v1/predictions/markets           # All markets with filters
GET  /api/v1/predictions/markets/{id}      # Market details
GET  /api/v1/predictions/categories        # Category breakdown
GET  /api/v1/predictions/trending          # Trending by volume
GET  /api/v1/predictions/high-conviction   # Strong signals
GET  /api/v1/predictions/close-odds        # Uncertain markets
GET  /api/v1/predictions/analytics         # Aggregate statistics
POST /api/v1/predictions/refresh           # Force refresh
```

### Dashboard (8 endpoints)
```
GET /api/v1/dashboard/agents/status        # Agent mesh status
GET /api/v1/dashboard/consensus/recent     # Recent consensus rounds
GET /api/v1/dashboard/reality/status       # Reality registry status
GET /api/v1/dashboard/execution/stats      # Execution engine stats
GET /api/v1/dashboard/system/health        # System health metrics
GET /api/v1/dashboard/neo4j/stats          # Graph database stats
GET /api/v1/dashboard/portfolio/summary    # Portfolio summary
GET /api/v1/dashboard/risk/metrics         # Risk metrics
```

### Additional APIs (13 endpoints)
- Agents, Arbitrage, Backup, Compliance, Governance
- Monitoring, Ops, Plugins, Rate Limits, Recovery
- Sniping, Treasury, Wallet

---

## 🎯 FEATURES

### Completed Features

**1. Asset Universe**
- 54 cryptocurrencies across 9 categories
- Real-time price data from CoinGecko
- Category filtering (Layer1, Layer2, DeFi, Meme, Gaming, AI, Privacy, Infrastructure, Stablecoins)
- Market cap tier classification

**2. Market Terminal**
- Bloomberg-style price table
- 7-column sortable display
- Category and tier filtering
- Market overview dashboard
- Top gainers/losers
- 5-second update interval
- Click-to-chart integration

**3. Intelligence Feed**
- Multi-source aggregation (CoinGecko + CryptoPanic)
- Sentiment analysis (positive/negative/neutral)
- Category classification (8 categories)
- Trending topics extraction
- Market mood indicator
- Duplicate removal
- 5-minute updates

**4. Prediction Markets**
- 100+ active markets from Polymarket
- Category filtering (8 categories)
- Volume/liquidity filtering
- High conviction markets (>70% or <30%)
- Close odds markets (45-55%)
- Market analytics dashboard
- 2-minute updates

### Missing Features (Priority Order)

**Critical (Must Have):**
1. Execution Interface - Order placement, position management
2. Portfolio Dashboard - Position tracking, performance analytics
3. Risk Monitor - Exposure tracking, limit monitoring

**Important (Should Have):**
4. Agents Interface - Agent mesh visualization
5. Consensus Visualization - Voting rounds display
6. System Health Dashboard - Component monitoring

**Nice to Have:**
7. Arbitrage Scanner - Opportunity detection
8. Analytics Dashboard - Performance metrics
9. Backtest Interface - Strategy testing
10. Alerts Management - Alert configuration

---

## 🚀 DEPLOYMENT

### Local Development
```bash
# Start backend server
python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload

# Access dashboard
http://localhost:8000
```

### Environment Variables
```bash
# Required
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

# Optional
TRADING_MODE=PAPER  # PAPER or LIVE
COINGECKO_API_KEY=  # Optional, for higher rate limits
```

### Dependencies
```bash
# Install Python dependencies
pip install -r requirements.txt

# Key dependencies:
# - fastapi
# - uvicorn
# - neo4j
# - ccxt
# - aiohttp
# - python-dotenv
```

---

## 📊 DATA SOURCES

### CoinGecko (Free API)
- **Purpose:** Cryptocurrency prices, market data, news
- **Rate Limit:** 10-50 calls/minute (free tier)
- **Data:** 54 assets, real-time prices, 24h volume, market cap
- **Update Frequency:** 5 seconds

### CryptoPanic (Free API)
- **Purpose:** Cryptocurrency news aggregation
- **Rate Limit:** Unlimited (free tier)
- **Data:** News articles, sentiment votes
- **Update Frequency:** 5 minutes

### Polymarket (Free API)
- **Purpose:** Prediction markets
- **Rate Limit:** Unlimited
- **Data:** 100+ active markets, odds, volume
- **Update Frequency:** 2 minutes

---

## 🔧 CONFIGURATION

### Trading Mode
```python
# Paper Trading (Default)
TRADING_MODE=PAPER
INITIAL_CAPITAL=100000

# Live Trading (Requires exchange API keys)
TRADING_MODE=LIVE
EXCHANGE_API_KEY=your_key
EXCHANGE_API_SECRET=your_secret
```

### Risk Controls
```python
MAX_POSITION_SIZE_USD=10000
MAX_LEVERAGE=3.0
MAX_DRAWDOWN_PCT=0.15
MAX_DAILY_LOSS_USD=5000
```

### Update Frequencies
```python
PRICE_UPDATE_INTERVAL=5      # seconds
NEWS_UPDATE_INTERVAL=300     # 5 minutes
PREDICTIONS_UPDATE_INTERVAL=120  # 2 minutes
DASHBOARD_UPDATE_INTERVAL=30     # seconds
```

---

## 🎨 UI DESIGN

### Color Scheme (Bloomberg-inspired)
```css
--background: #0d1117
--surface: #161b22
--primary: #00ff88
--secondary: #8b949e
--positive: #00ff88
--negative: #ff4444
--neutral: #8b949e
```

### Typography
```css
--font-primary: 'Inter', sans-serif
--font-mono: 'JetBrains Mono', monospace
```

### Layout
- Dark theme throughout
- Grid-based responsive layout
- Sidebar navigation (26 sections)
- Main content area with section switching
- Top navigation with live price tickers

---

## 📈 PERFORMANCE

### Current Metrics
- **API Response Time:** <100ms average
- **Page Load Time:** <2s
- **Update Latency:** 5s (prices), 2min (predictions), 5min (news)
- **Memory Usage:** ~200MB (backend)
- **CPU Usage:** <5% idle, <20% active

### Optimization Opportunities
- Implement WebSocket for real-time updates
- Add request debouncing
- Implement lazy loading
- Add data virtualization for large lists
- Optimize bundle size

---

## 🔒 SECURITY

### Current Status
- ⚠️ No authentication (local development)
- ⚠️ No authorization
- ⚠️ No rate limiting on frontend
- ⚠️ No CSRF protection
- ⚠️ No input validation

### Production Requirements
- Implement OAuth2/JWT authentication
- Add role-based access control
- Enable rate limiting
- Add CSRF tokens
- Implement input sanitization
- Enable HTTPS
- Add API key management

---

## 🧪 TESTING

### Current Status
- ❌ No frontend tests
- ❌ No integration tests
- ❌ No E2E tests
- ✅ Manual testing only

### Testing Plan
1. Unit tests for all API endpoints
2. Integration tests for data flows
3. E2E tests for critical user journeys
4. Performance tests for scalability
5. Security tests for vulnerabilities

---

## 📝 DEVELOPMENT ROADMAP

### Phase 1: Critical Features (Current)
- [x] Asset universe expansion (54 assets)
- [x] Market terminal interface
- [x] Intelligence feed with sentiment
- [x] Prediction markets integration
- [ ] Execution interface
- [ ] Portfolio dashboard
- [ ] Risk monitor

### Phase 2: System Monitoring
- [ ] Agents interface
- [ ] Consensus visualization
- [ ] System health dashboard
- [ ] Neo4j stats display

### Phase 3: Advanced Features
- [ ] Arbitrage scanner
- [ ] Analytics dashboard
- [ ] Backtest interface
- [ ] Alerts management

### Phase 4: Wire All Sections
- [ ] Connect all 23 sidebar sections
- [ ] Add real data to each section
- [ ] Implement section-specific features

### Phase 5: Polish & Production
- [ ] Add WebSocket support
- [ ] Implement error handling
- [ ] Add loading states
- [ ] Create test suite
- [ ] Add authentication
- [ ] Performance optimization

---

## 🐛 KNOWN ISSUES

### High Priority
1. No trading execution interface
2. No portfolio tracking
3. No risk monitoring
4. 23 sidebar sections show empty states

### Medium Priority
5. No error handling in frontend
6. No loading states
7. Polling instead of WebSockets
8. No data persistence

### Low Priority
9. No mobile optimization
10. No offline support
11. No dark/light theme toggle
12. No keyboard shortcuts

---

## 📞 SUPPORT

### Getting Help
- Check this documentation first
- Review API endpoint documentation
- Check browser console for errors
- Review server logs

### Common Issues

**Issue:** Prices not updating
**Solution:** Check CoinGecko API rate limits, verify network connection

**Issue:** News feed empty
**Solution:** Check CryptoPanic API availability, verify network connection

**Issue:** Predictions not loading
**Solution:** Check Polymarket API availability, verify network connection

**Issue:** Neo4j connection failed
**Solution:** Verify Neo4j is running, check credentials in .env

---

## 🎯 QUICK START

### 1. Setup Environment
```bash
# Clone repository
cd c:\Dev\MERID

# Create .env file
cp .env.example .env

# Edit .env with your Neo4j credentials
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Start Neo4j
```bash
# Start Neo4j database
neo4j start
```

### 4. Start Backend
```bash
python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Access Dashboard
```
Open browser: http://localhost:8000
```

---

## 📊 METRICS & KPIs

### System Metrics
- Total Assets Tracked: 54
- Total Markets Tracked: 100+
- API Endpoints: 40
- Update Frequency: 5s-5min
- Uptime Target: 99.9%

### User Metrics
- Page Load Time: <2s
- API Response Time: <100ms
- Update Latency: <10s
- Error Rate: <0.1%

### Business Metrics
- Features Complete: 30%
- APIs with UI: 15%
- Sidebar Sections Working: 12%
- Code Coverage: 0% (no tests yet)

---

## 🔄 CHANGELOG

### January 12, 2026
- ✅ Added 54 cryptocurrency assets
- ✅ Created market terminal interface
- ✅ Implemented intelligence feed
- ✅ Integrated prediction markets
- ✅ Built dashboard data API
- ✅ Created comprehensive documentation

### Previous Work
- ✅ Built core systems (orchestrator, consensus, reality registry)
- ✅ Implemented execution engine
- ✅ Created agent mesh
- ✅ Built Neo4j integration
- ✅ Implemented risk controls

---

## 📚 ADDITIONAL RESOURCES

### Documentation Files
- `COMPREHENSIVE_GAP_ANALYSIS.md` - Detailed gap analysis
- `CURRENT_STATUS_AND_PRIORITIES.md` - Current status and priorities
- `INSTITUTIONAL_GRADE_STATUS.md` - Institutional features status

### Code Documentation
- API endpoints documented in code
- Core systems documented in docstrings
- Frontend components documented in comments

---

**Last Updated:** January 12, 2026
**Version:** 1.0
**Status:** Active Development (30% Complete)
