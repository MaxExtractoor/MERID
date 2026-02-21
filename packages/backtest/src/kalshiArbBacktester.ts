/**
 * Kalshi Arbitrage Backtester
 * Event-driven backtest engine for arb strategies
 * 
 * Replay historical orderbook snapshots/deltas and compute PnL
 * Models fees, slippage, and settlement outcomes
 * 
 * Based on event-driven benchmarks like PredictionMarketBench
 */

import { computeYesMidFromBook } from "@merid/swarm-kernel/orderbookMath";
import { LocalOrderbook } from "@merid/agents/orderbookState";
import { OrderbookSnapshotMsg, OrderbookDeltaMsg } from "@merid/swarm-kernel";

export interface BacktestTrade {
  ts: number;
  market_ticker: string;
  side: "buy_yes" | "buy_no" | "sell_yes" | "sell_no";
  price: number;
  size: number;
  cost: number; // Including fees
}

export interface BacktestConfig {
  tickers: string[];
  minEdge: number;        // Net edge threshold (default: 0.02 = 2%)
  size: number;           // Contracts per trade (default: 1)
  feeRate: number;        // Combined fee/slippage rate (default: 0.02 = 2%)
  initialCapital: number; // Starting capital (default: 10000)
}

export interface BacktestResult {
  trades: BacktestTrade[];
  finalPnL: number;
  totalReturn: number;    // (finalPnL / initialCapital) - 1
  maxDrawdown: number;
  sharpeRatio: number;
  winRate: number;
  avgTradeProfit: number;
  totalFees: number;
  metrics: {
    totalTrades: number;
    winningTrades: number;
    losingTrades: number;
    largestWin: number;
    largestLoss: number;
  };
}

export class KalshiArbBacktester {
  private book = new LocalOrderbook();
  private trades: BacktestTrade[] = [];
  private cash: number;
  private positions: Map<string, { yes: number; no: number }> = new Map();
  private pnlHistory: number[] = [];
  private config: Required<BacktestConfig>;
  private totalFees = 0;

  constructor(config: Partial<BacktestConfig>) {
    this.config = {
      tickers: config.tickers ?? [],
      minEdge: config.minEdge ?? 0.02,
      size: config.size ?? 1,
      feeRate: config.feeRate ?? 0.02,
      initialCapital: config.initialCapital ?? 10000,
    };
    this.cash = this.config.initialCapital;
  }

  /**
   * Process orderbook snapshot
   */
  onSnapshot(msg: OrderbookSnapshotMsg, ts: number): void {
    const { market_ticker, yes, no } = msg.msg;
    
    if (!this.config.tickers.includes(market_ticker)) {
      return;
    }

    this.book.applySnapshot(market_ticker, yes, no, msg.seq);
    this.evaluateArbOpportunity(market_ticker, ts);
  }

  /**
   * Process orderbook delta
   */
  onDelta(msg: OrderbookDeltaMsg, ts: number): void {
    const { market_ticker, price, delta, side } = msg.msg;
    
    if (!this.config.tickers.includes(market_ticker)) {
      return;
    }

    const applied = this.book.applyDelta(market_ticker, side, price, delta, msg.seq);
    
    if (applied) {
      this.evaluateArbOpportunity(market_ticker, ts);
    }
  }

  private evaluateArbOpportunity(ticker: string, ts: number): void {
    const quote = this.book.toBestBidAsk(ticker);
    
    if (quote.bestBid === null || quote.bestAsk === null) {
      return;
    }

    // Get raw integer prices for precise calculation
    const bestYesBid = this.book.getBestYesBid(ticker);
    const bestNoBid = this.book.getBestNoBid(ticker);
    
    if (bestYesBid === null || bestNoBid === null) {
      return;
    }

    const yesBid = bestYesBid / 100;
    const noBid = bestNoBid / 100;
    const yesPlusNo = yesBid + noBid;
    
    // Gross edge: amount by which YES bid + NO bid exceeds 1
    const grossEdge = yesPlusNo - 1;
    
    // Net edge: after paying fees on both legs
    const netEdge = grossEdge - (2 * this.config.feeRate);

    // Only trade if net edge is positive
    if (netEdge <= this.config.minEdge) {
      return;
    }

    // Check if we have enough capital
    const costYes = yesBid * this.config.size;
    const costNo = noBid * this.config.size;
    const totalCost = costYes + costNo;
    const feeYes = costYes * this.config.feeRate;
    const feeNo = costNo * this.config.feeRate;
    const totalFees = feeYes + feeNo;
    const totalOutlay = totalCost + totalFees;

    if (this.cash < totalOutlay) {
      return; // Insufficient capital
    }

    // Execute arbitrage: buy YES and NO
    this.cash -= totalOutlay;
    this.totalFees += totalFees;

    // Record trades
    this.trades.push({
      ts,
      market_ticker: ticker,
      side: "buy_yes",
      price: yesBid,
      size: this.config.size,
      cost: costYes + feeYes,
    });

    this.trades.push({
      ts,
      market_ticker: ticker,
      side: "buy_no",
      price: noBid,
      size: this.config.size,
      cost: costNo + feeNo,
    });

    // Update positions
    const pos = this.positions.get(ticker) ?? { yes: 0, no: 0 };
    pos.yes += this.config.size;
    pos.no += this.config.size;
    this.positions.set(ticker, pos);

    // Mark-to-market: arb position should be worth ~$1 per contract pair
    const mtmValue = this.config.size * 1.0; // Both YES and NO pay out 1 total
    const unrealizedPnL = mtmValue - totalCost;
    const totalPnL = this.cash + this.getPositionsValue() - this.config.initialCapital;
    
    this.pnlHistory.push(totalPnL);
  }

  private getPositionsValue(): number {
    // For arb positions, value is always size * 1 (guaranteed payout)
    let value = 0;
    for (const pos of this.positions.values()) {
      const pairs = Math.min(pos.yes, pos.no);
      value += pairs * 1.0;
    }
    return value;
  }

  /**
   * Finalize backtest with settlement outcomes
   */
  finalize(settlements: Record<string, 0 | 1>): BacktestResult {
    // Settle all positions
    for (const [ticker, pos] of this.positions) {
      const outcome = settlements[ticker];
      
      if (outcome === undefined) {
        console.warn(`[Backtest] No settlement for ${ticker}, assuming 0`);
        continue;
      }

      // YES contracts pay out 1 if outcome = 1, else 0
      this.cash += pos.yes * outcome;
      
      // NO contracts pay out 1 if outcome = 0, else 0
      this.cash += pos.no * (1 - outcome);
    }

    const finalPnL = this.cash - this.config.initialCapital;
    const totalReturn = finalPnL / this.config.initialCapital;

    // Compute drawdown
    let peak = this.config.initialCapital;
    let maxDD = 0;
    
    for (const pnl of this.pnlHistory) {
      const equity = this.config.initialCapital + pnl;
      peak = Math.max(peak, equity);
      const dd = (peak - equity) / peak;
      maxDD = Math.max(maxDD, dd);
    }

    // Compute trade statistics
    const tradePnLs: number[] = [];
    
    for (let i = 0; i < this.trades.length; i += 2) {
      // Process pairs of trades (YES + NO arb)
      if (i + 1 >= this.trades.length) break;
      
      const yesTrade = this.trades[i];
      const noTrade = this.trades[i + 1];
      const ticker = yesTrade.market_ticker;
      const outcome = settlements[ticker] ?? 0;
      
      const yesPayout = outcome;
      const noPayout = 1 - outcome;
      const totalPayout = (yesPayout + noPayout) * this.config.size;
      const totalCost = yesTrade.cost + noTrade.cost;
      const tradePnL = totalPayout - totalCost;
      
      tradePnLs.push(tradePnL);
    }

    const winningTrades = tradePnLs.filter(p => p > 0).length;
    const losingTrades = tradePnLs.filter(p => p < 0).length;
    const winRate = tradePnLs.length > 0 ? winningTrades / tradePnLs.length : 0;
    const avgTradeProfit = tradePnLs.length > 0 
      ? tradePnLs.reduce((sum, p) => sum + p, 0) / tradePnLs.length 
      : 0;

    // Sharpe ratio (simplified: daily returns)
    const returns = [];
    for (let i = 1; i < this.pnlHistory.length; i++) {
      returns.push(this.pnlHistory[i] - this.pnlHistory[i - 1]);
    }
    
    const avgReturn = returns.length > 0 
      ? returns.reduce((sum, r) => sum + r, 0) / returns.length 
      : 0;
    const stdDev = returns.length > 0
      ? Math.sqrt(returns.reduce((sum, r) => sum + Math.pow(r - avgReturn, 2), 0) / returns.length)
      : 1;
    const sharpeRatio = stdDev > 0 ? (avgReturn / stdDev) * Math.sqrt(252) : 0;

    return {
      trades: this.trades,
      finalPnL,
      totalReturn,
      maxDrawdown: maxDD,
      sharpeRatio,
      winRate,
      avgTradeProfit,
      totalFees: this.totalFees,
      metrics: {
        totalTrades: tradePnLs.length,
        winningTrades,
        losingTrades,
        largestWin: tradePnLs.length > 0 ? Math.max(...tradePnLs) : 0,
        largestLoss: tradePnLs.length > 0 ? Math.min(...tradePnLs) : 0,
      },
    };
  }

  // Monitoring
  getCurrentPnL(): number {
    return this.cash + this.getPositionsValue() - this.config.initialCapital;
  }

  getTradeCount(): number {
    return this.trades.length;
  }

  getCash(): number {
    return this.cash;
  }
}
