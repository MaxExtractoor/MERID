# Kalshi 15m Agent Inventory

## Summary

This document inventories all agent classes in the MERID codebase and classifies them for the Kalshi 15-minute crypto trading profile (`MERID_PROFILE=kalshi_crypto_15m_v2`).

## Audit Scope

- **Venue**: Kalshi only
- **Markets**: 15-minute contracts for BTC, ETH, SOL, XRP, DOGE only
- **Profiles**: `kalshi_crypto_15m`, `kalshi_crypto_15m_v2`
- **Production agents**: Only signal/PM agents, risk sizing, and execution/order-router allowed

## Agent Classification Criteria

- **prod_15m_core**: Required for live 15m trading (signal, risk, execution only), sentiment-free, constrained to 15m BTC/ETH/SOL/XRP/DOGE
- **prod_15m_optional**: Monitoring/telemetry only, no order routing
- **research_only**: Experimental, sentiment, orchestration, RL, backtest-only, non-15m, non-crypto
- **remove**: Dead code, obsolete, duplicated functionality

---

## Agent Inventory Table

| agent_name | module_path | role | markets | classification | notes |
|------------|-------------|------|---------|----------------|-------|
| **KalshiTradingAgent** | merid/prediction/trading_agent.py | execution | Kalshi BTC/ETH/SOL/XRP/DOGE 15m | prod_15m_core | Main trading agent loaded from YAML config |
| **PortfolioRiskAgent** | merid/prediction/portfolio_risk_agent.py | risk | Kalshi BTC/ETH/SOL/XRP/DOGE 15m | prod_15m_core | Portfolio-level risk management |
| **Btc15mAgent** | merid/agents/btc_15m_agent.py | signal | Kalshi BTC 15m | prod_15m_core | BTC 15m signal generation |
| **Eth15mAgent** | merid/agents/eth_15m_agent.py | signal | Kalshi ETH 15m | prod_15m_core | ETH 15m signal generation |
| **Sol15mAgent** | merid/agents/sol_15m_agent.py | signal | Kalshi SOL 15m | prod_15m_core | SOL 15m signal generation |
| **Xrp15mAgent** | merid/agents/xrp_15m_agent.py | signal | Kalshi XRP 15m | prod_15m_core | XRP 15m signal generation |
| **Doge15mAgent** | merid/agents/doge_15m_agent.py | signal | Kalshi DOGE 15m | prod_15m_core | DOGE 15m signal generation |
| **MarketAnalystAgent** | agents/core/market_analyst.py | signal | generic | research_only | Legacy LLM mesh agent, not used in Kalshi 15m |
| **RiskAgent** | agents/core/risk_agent.py | risk | generic | research_only | Legacy LLM mesh agent, not used in Kalshi 15m |
| **SkepticAgent** | agents/core/skeptic_agent.py | orchestrator | generic | research_only | Legacy LLM mesh agent, not used in Kalshi 15m |
| **StrategyAgent** | agents/core/strategy_agent.py | orchestrator | generic | research_only | Legacy LLM mesh agent, not used in Kalshi 15m |
| **Skeptic** | agents/skeptic.py | orchestrator | generic | remove | Legacy registry agent, marked REFERENCE ONLY |
| **RiskAgent** (legacy) | agents/risk_agent.py | risk | generic | remove | Legacy registry agent, marked REFERENCE ONLY |
| **StrategyAgent** (legacy) | agents/strategy_agent.py | orchestrator | generic | remove | Legacy registry agent, marked REFERENCE ONLY |
| **BullAnalyst** | agents/manifest.py | signal | generic | research_only | LLM agent manifest, not used in Kalshi 15m |
| **BearAnalyst** | agents/manifest.py | signal | generic | research_only | LLM agent manifest, not used in Kalshi 15m |
| **RiskManager** | agents/manifest.py | risk | generic | research_only | LLM agent manifest, not used in Kalshi 15m |
| **ExecutionAgent** | agents/manifest.py | execution | generic | research_only | LLM agent manifest, not used in Kalshi 15m |
| **GovernanceAgent** | agents/manifest.py | governance | generic | research_only | LLM agent manifest, not used in Kalshi 15m |
| **CryptoSignalsAgent** | merid/agents/crypto_signals_agent.py | signal | generic | research_only | Generic crypto signal agent, not 15m-specific |
| **RiskManagerAgent** | merid/agents/risk_agents.py | risk | generic | research_only | Generic risk manager, not Kalshi 15m |
| **CapitalAllocatorAgent** | merid/agents/risk_agents.py | risk | generic | research_only | Generic capital allocator, not Kalshi 15m |
| **AnomalyDetectorAgent** | merid/agents/risk_agents.py | risk | generic | research_only | Generic anomaly detector, not Kalshi 15m |
| **StrategyDesignerAgent** | merid/agents/strategy.py | strategy | generic | research_only | Generic strategy designer, not Kalshi 15m |
| **ArbitrageAgent** | merid/agents/strategy.py | arbitrage | generic | research_only | Cross-venue arbitrage, not Kalshi-only |
| **ExecutionOptimizerAgent** | merid/agents/strategy.py | execution | generic | research_only | Generic execution optimizer, not Kalshi 15m |
| **AgentOrchestrator** | merid/agents/orchestrator.py | orchestrator | generic | research_only | Generic orchestrator, not used in Kalshi 15m |
| **HybridCanonicalAgent** | merid/agents/hybrid.py | signal | generic | research_only | Hybrid agent, not Kalshi 15m |
| **WiredPredictionMarketAgent** | merid/agents/wiring.py | signal | generic | research_only | Wired prediction market agent, not Kalshi 15m |
| **BandStrategyAgent** | merid/prediction/band_strategy_agent.py | signal | generic | research_only | Band strategy, not Kalshi 15m |
| **KalshiUniversalAgent** | merid/prediction/universal_agent.py | signal | generic | research_only | Universal agent, not 15m-specific |
| **CriticAgent** | merid/swarm/critic_agent.py | critic | generic | research_only | Swarm critic agent, not Kalshi 15m |
| **KalshiNewsAgent** | merid/publishing/kalshi_news_agent.py | publishing | Kalshi | prod_15m_optional | News publishing, read-only |
| **NewsIngestionAgent** | merid/sentiment/news_ingestion_agent.py | sentiment | generic | research_only | Sentiment/news agent, disabled for 15m |
| **GovernorAgent** | agents/governor_agent.py | governance | generic | research_only | LLM governor, not used in Kalshi 15m |
| **HardenedGovernorAgent** | agents/governor_agent_v2.py | governance | generic | research_only | LLM governor v2, not used in Kalshi 15m |
| **CryptoPredictionAgent** | agents/crypto_prediction_agent.py | signal | generic | research_only | Generic crypto prediction, not 15m-specific |
| **Btc15mMakerAgent** | agents/crypto_surface_agent_integration.py | market_maker | generic | research_only | Maker agent, not used in Kalshi 15m |
| **ScalperAgent** | agents/crypto_surface_agent_integration.py | scalping | generic | research_only | Scalper agent, not used in Kalshi 15m |
| **SignalFusionAgent** | agents/signal_fusion_agent.py | signal | generic | prod_15m_optional | Microstructure signal fusion (used by 15m agents) |
| **KalshiContinuousTrader** | merid/trading/kalshi_continuous_trader.py | execution | Kalshi | research_only | CT is legacy/research-only for kalshi_crypto_15m_v2 |

---

## Reflection Subsystem Analysis

### Reflection Data Source

The reflection system loads 4364 reflections for 664 agents from `logs/agent_reflections_v2.json`.

### Agent IDs in Reflection Data

The reflection file contains two types of agent IDs:

1. **Legacy Mesh Agents** (from AgentMesh):
   - `strategy-agent-01`
   - `synthesizer-01`
   - `analyst-llama-01`
   - `skeptic-01`
   - `risk-agent-01`

2. **Historical KalshiTradingAgent Instances** (with unique hashes):
   - `kalshi-btc_15m_{hash}` (many instances with different hashes)
   - `kalshi-eth_15m_{hash}`
   - `kalshi-sol_15m_{hash}`
   - `kalshi-xrp_15m_{hash}`
   - `kalshi-doge_15m_{hash}`
   - `kalshi-btc_hourly_{hash}`
   - `kalshi-eth_hourly_{hash}`
   - `kalshi-sol_hourly_{hash}`
   - `kalshi-xrp_hourly_{hash}`
   - `kalshi-doge_hourly_{hash}`
   - `kalshi-sports_directional_{hash}`
   - `kalshi-kalshi_catch_all_{hash}`

### Reflection System Overlap with Classification

- **prod_15m_core agents**: The `kalshi-{asset}_15m_{hash}` agents are historical instances of KalshiTradingAgent, which is a prod_15m_core agent. However, the reflection data contains many historical instances with unique hashes, which is not necessary for production.
- **research_only agents**: The legacy mesh agents (strategy-agent-01, synthesizer-01, analyst-llama-01, skeptic-01, risk-agent-01) are research_only and should not be loaded in production.
- **non-15m/non-crypto agents**: The reflection data contains hourly, sports, and catch-all agents which are not relevant for 15m crypto trading.

### Reflection Policy Recommendation

For Kalshi 15m production profile, the reflection system should be **disabled completely** because:

1. The reflection data contains 664 agents, most of which are historical instances or research-only agents
2. The 15m Kalshi trading system does not use LLM-based reflection learning
3. Loading 4364 reflections for 664 agents at startup is unnecessary overhead
4. The reflection system is designed for LLM agents (mesh agents), not for the deterministic 15m Kalshi agents

---

## Production Agent Count

### Current State

- **Agent Grid YAML**: 5 active agents (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)
- **Agent Mesh**: 4 streaming agents (MarketAnalystAgent, RiskAgent, SkepticAgent, StrategyAgent)
- **Reflection System**: 664 agents loaded from historical data

### Desired State for kalshi_crypto_15m_v2

- **Agent Grid**: 5 active agents (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)
- **Agent Mesh**: DISABLED (not used in Kalshi 15m)
- **Reflection System**: DISABLED (not used in Kalshi 15m)
- **Total active agents**: 5 (Agent Grid) + 1 (PortfolioRiskAgent) = 6

---

## Startup Log Sequence (Desired)

```
[AGENT-GRID] Loading config from config/kalshi_agent_grid.yaml
[AGENT-GRID] 5 agents enabled: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
[AGENT-GRID] PortfolioRiskAgent initialized
[REFLECTION-SYSTEM] Reflection disabled for profile=kalshi_crypto_15m_v2 (prod)
[AGENT-MESH] AgentMesh skipped for profile=kalshi_crypto_15m_v2 (LLM agents not required)
[AGENT-REGISTRY-SUMMARY] total=6 (5 signal agents + 1 portfolio risk agent)
[PROFILE-VALIDATION] kalshi_crypto_15m_v2 profile validated
```
