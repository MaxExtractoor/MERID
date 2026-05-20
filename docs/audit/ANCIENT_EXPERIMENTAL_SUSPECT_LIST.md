# Ancient Experimental Agent Suspect List

## Summary

Based on the agent classification mapping in `merid/agents/agent_metadata.py`, the following agents are marked as `research_only` or `remove` and could be candidates for causing main loop hangs if they're still active.

## Priority 1: LLM Mesh Agents (llm_mesh_v1 tag)

These agents are tagged with `llm_mesh_v1` and are part of the AgentMesh (4 active streaming agents):

- **MarketAnalystAgent** - `agents.core.market_analyst`
- **RiskAgent** - `agents.core.risk_agent`
- **SkepticAgent** - `agents.core.skeptic_agent`
- **StrategyAgent** - `agents.core.strategy_agent`

**Risk**: These are actively used in the AgentMesh and could block if:
- LLM model calls timeout (Ollama timeout increased to 120s but could still hang)
- Reflection loading is slow
- AgentMesh initialization blocks

**Mitigation**: Already instrumented with timing logs in AgentMesh.initialize()

## Priority 2: Research-Only Agents with External Dependencies

These agents might have external dependencies (API calls, data feeds) that could block:

- **CryptoSignalsAgent** - Unknown dependencies
- **NewsIngestionAgent** - News feeds, external APIs
- **StrategyDesignerAgent** - Could have complex logic
- **ArbitrageAgent** - Cross-venue checks (dead in Kalshi-only mode)
- **ExecutionOptimizerAgent** - Could block on execution checks
- **AnomalyDetectorAgent** - Complex anomaly detection logic

## Priority 3: Governance/Control Agents

These agents might have blocking control logic:

- **GovernanceAgent** - Governance checks
- **GovernorAgent** - Governor logic
- **HardenedGovernorAgent** - Enhanced governor with additional checks
- **CriticAgent** - Could block on criticism logic

## Priority 4: Legacy/Deprecated Agents

These are marked for removal but might still be active:

- **Skeptic** - Legacy version (marked as "remove")
- **RiskAgent** - Legacy registry version (marked as "remove")
- **StrategyAgent** - Legacy registry version (marked as "remove")

## Classification Distribution

From `AGENT_CLASSIFICATION_MAP`:

### prod_15m_core (7 agents)
- KalshiTradingAgent
- PortfolioRiskAgent
- Btc15mAgent
- Eth15mAgent
- Sol15mAgent
- Xrp15mAgent
- Doge15mAgent

### prod_15m_optional (2 agents)
- KalshiNewsAgent
- SignalFusionAgent

### research_only (27 agents)
- MarketAnalystAgent
- RiskAgent
- SkepticAgent
- StrategyAgent
- BullAnalyst
- BearAnalyst
- RiskManager
- ExecutionAgent
- GovernanceAgent
- CryptoSignalsAgent
- RiskManagerAgent
- CapitalAllocatorAgent
- AnomalyDetectorAgent
- StrategyDesignerAgent
- ArbitrageAgent
- ExecutionOptimizerAgent
- AgentOrchestrator
- HybridCanonicalAgent
- WiredPredictionMarketAgent
- BandStrategyAgent
- KalshiUniversalAgent
- CriticAgent
- NewsIngestionAgent
- GovernorAgent
- HardenedGovernorAgent
- CryptoPredictionAgent
- Btc15mMakerAgent
- ScalperAgent

### remove (3 agents)
- Skeptic (legacy)
- RiskAgent (legacy registry version)
- StrategyAgent (legacy registry version)

## Recommended Actions

1. **Run the system** and check logs for `[MAIN-LOOP] entering step` lines to see which agents are actually being called
2. **Check for `[REFLECTION-TICK]` logs** to see which research_only agents are using reflection heavily
3. **Monitor AgentMesh initialization time** - if >5s, investigate which agent is blocking
4. **Check for `[BTC-LANE-MISSING-METHOD]` warnings** - this should now be logged instead of hanging
5. **Profile LLM model call times** - if Ollama calls are slow, increase timeout further or add caching

## Suspect Ranking for Main Loop Hang

Based on the investigation, the most likely culprits for main loop hangs are:

1. **Btc15mAgent** - Fixed: Missing `get_regime_signal()` method now handled defensively
2. **AgentMesh initialization** - Instrumented: Check logs for duration_ms
3. **Reflection loading** - Instrumented: Check logs for `[REFLECTION-TRACE]` duration_ms
4. **LLM Mesh agents** (MarketAnalystAgent, RiskAgent, SkepticAgent, StrategyAgent) - Monitor model call times
5. **Any research_only agent** with blocking external calls - Check `[REFLECTION-TICK]` logs

## Next Steps

The instrumentation is now in place. The user should:
1. Run the system
2. Capture logs around a stall
3. Look for the last `[MAIN-LOOP] entering step` line
4. Check the agent metadata in that line (classification, age_bucket, tag)
5. Cross-reference with this suspect list to prioritize investigation
