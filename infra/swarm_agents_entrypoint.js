#!/usr/bin/env node
/**
 * Swarm Agents Entrypoint
 * Initializes and runs all TypeScript swarm agents
 */

const { NATSEventBus } = require('./packages/swarm-kernel/dist/eventBus');
const { KXHarrisOrderbookAgent } = require('./packages/agents/dist/kxHarrisAgent');
const { KalshiMarketAnalysisAgent } = require('./packages/agents/dist/kalshiMarketAnalysisAgent');
const { HardLimitRiskAgent } = require('./packages/agents/dist/riskAgent');

async function main() {
  // Configuration from environment
  const eventBusUrl = process.env.EVENT_BUS_URL || 'nats://localhost:4222';
  const enableLiveTrading = process.env.ENABLE_LIVE_TRADING === 'true';
  const maxPositionSize = parseInt(process.env.MAX_POSITION_SIZE || '100', 10);
  const maxDailyLoss = parseFloat(process.env.MAX_DAILY_LOSS || '1000');

  console.log('[Swarm] Starting swarm agents');
  console.log(`[Swarm] Event Bus: ${eventBusUrl}`);
  console.log(`[Swarm] Live Trading: ${enableLiveTrading}`);
  console.log(`[Swarm] Max Position Size: ${maxPositionSize}`);
  console.log(`[Swarm] Max Daily Loss: ${maxDailyLoss}`);

  // Initialize event bus
  const eventBus = new NATSEventBus(eventBusUrl);
  await eventBus.connect();
  console.log('[Swarm] Connected to event bus');

  // Initialize agents
  const agents = [];

  // KX Harris orderbook agent
  const kxHarrisAgent = new KXHarrisOrderbookAgent(eventBus);
  agents.push({ name: 'KXHarrisOrderbook', agent: kxHarrisAgent });

  // Market analysis agent
  const marketAnalysisAgent = new KalshiMarketAnalysisAgent(eventBus, 'market-analysis-1');
  agents.push({ name: 'MarketAnalysis', agent: marketAnalysisAgent });

  // Risk management agent
  const riskAgent = new HardLimitRiskAgent(eventBus, {
    maxContractsPerMarket: maxPositionSize,
    maxNotionalPerMarket: maxPositionSize * 50,
    maxAssetExposure: maxPositionSize * 3,
    maxTotalNotional: 10000,
    maxDailyLoss: maxDailyLoss,
    maxLeverage: 3.0,
  });
  agents.push({ name: 'RiskManagement', agent: riskAgent });

  // Start all agents
  for (const { name, agent } of agents) {
    try {
      await agent.start();
      console.log(`[Swarm] Started agent: ${name}`);
    } catch (error) {
      console.error(`[Swarm] Failed to start agent ${name}:`, error);
      throw error;
    }
  }

  console.log(`[Swarm] All ${agents.length} agents running`);

  // Graceful shutdown
  const shutdown = async () => {
    console.log('[Swarm] Shutting down...');
    
    for (const { name, agent } of agents) {
      if (agent.stop) {
        try {
          await agent.stop();
          console.log(`[Swarm] Stopped agent: ${name}`);
        } catch (error) {
          console.error(`[Swarm] Error stopping agent ${name}:`, error);
        }
      }
    }

    await eventBus.disconnect();
    console.log('[Swarm] Disconnected from event bus');
    process.exit(0);
  };

  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);

  // Health monitoring
  setInterval(() => {
    console.log(`[Swarm] Health check: ${agents.length} agents running`);
  }, 60000);
}

main().catch((error) => {
  console.error('[Swarm] Fatal error:', error);
  process.exit(1);
});
