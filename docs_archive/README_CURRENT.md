# MERID - Multi-Agent Trading System

## 🚀 Quick Start

```bash
# 1. Start Neo4j database
neo4j start

# 2. Start MERID backend
python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload

# 3. Open browser
http://localhost:8000
```

## 📊 Current Status (30% Complete)

**Working Features:**

- ✅ 54 cryptocurrency assets with real-time data
- ✅ Bloomberg-style market terminal
- ✅ Multi-source intelligence feed with sentiment analysis
- ✅ 100+ prediction markets from Polymarket

**In Development:**

- 🔄 Trading execution interface
- 🔄 Portfolio analytics dashboard
- 🔄 Risk monitoring interface

## 📁 Key Files

**Main Documentation:**

- `MASTER_DOCUMENTATION.md` - Complete system documentation
- `COMPREHENSIVE_GAP_ANALYSIS.md` - Detailed gap analysis
- `CURRENT_STATUS_AND_PRIORITIES.md` - Current priorities

**Configuration:**

- `.env` - Environment variables (Neo4j credentials, API keys)
- `requirements.txt` - Python dependencies

**Access Dashboard:**

- <http://localhost:8000>

## 🔗 Quick Links

- Dashboard: <http://localhost:8000>
- Market Terminal: <http://localhost:8000#dashboard>
- Intelligence Feed: <http://localhost:8000#intelligence>
- Prediction Markets: <http://localhost:8000#predictions>

## 📚 Documentation

All documentation has been consolidated into:

- `MASTER_DOCUMENTATION.md` - Single source of truth
- Old documentation archived in `docs_archive/`

## ⚙️ Environment Setup

```bash
# Required environment variables
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
TRADING_MODE=PAPER
```

## 🎯 Next Steps

1. Build Execution UI for order management
2. Build Portfolio UI for position tracking
3. Build Risk UI for risk monitoring
4. Wire up all 23 sidebar sections

See `CURRENT_STATUS_AND_PRIORITIES.md` for detailed roadmap.
