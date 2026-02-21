/**
 * Orderbook Math Utilities
 * Helpers for computing bid/ask/mid from Kalshi orderbook format
 * 
 * Kalshi conventions:
 * - YES bids in yes[] (price int 0-100, quantity)
 * - NO bids in no[] (price int 0-100, quantity)
 * - YES ask = 1 - (best_no_bid_price / 100)
 * - NO ask = 1 - (best_yes_bid_price / 100)
 */

export interface BidAskMid {
  bestBid: number | null;  // Dollar probability (0-1)
  bestAsk: number | null;
  mid: number | null;
  spread: number | null;
}

/**
 * Compute best YES bid from YES price levels
 * Returns decimal probability (0-1)
 */
export function computeBestYesBid(yes: [number, number][]): number | null {
  if (!yes.length) return null;
  const prices = yes.filter(([_, qty]) => qty > 0).map(([p]) => p);
  if (!prices.length) return null;
  return Math.max(...prices) / 100;
}

/**
 * Compute best NO bid from NO price levels
 * Returns decimal probability (0-1)
 */
export function computeBestNoBid(no: [number, number][]): number | null {
  if (!no.length) return null;
  const prices = no.filter(([_, qty]) => qty > 0).map(([p]) => p);
  if (!prices.length) return null;
  return Math.max(...prices) / 100;
}

/**
 * Compute YES mid price from raw book arrays
 * 
 * Formula:
 * - bestBid = best YES bid price
 * - bestAsk = 1 - (best NO bid price)
 * - mid = (bestBid + bestAsk) / 2
 */
export function computeYesMidFromBook(
  yes: [number, number][],
  no: [number, number][]
): BidAskMid {
  const bestYesBid = computeBestYesBid(yes); // YES bid price (0–1)
  const bestNoBid = computeBestNoBid(no);   // NO bid price (0–1)

  if (bestYesBid === null || bestNoBid === null) {
    return { bestBid: null, bestAsk: null, mid: null, spread: null };
  }

  // YES ask implied from best NO bid: 1 - NO bid
  const bestBid = bestYesBid;
  const bestAsk = 1 - bestNoBid;
  const mid = (bestBid + bestAsk) / 2;
  const spread = bestAsk - bestBid;

  return { bestBid, bestAsk, mid, spread };
}

/**
 * Check if book has crossed quotes (arbitrage opportunity)
 * Returns edge amount if YES bid + NO bid > 1
 */
export function detectArbitrageEdge(
  yes: [number, number][],
  no: [number, number][]
): number {
  const yesBid = computeBestYesBid(yes);
  const noBid = computeBestNoBid(no);

  if (yesBid === null || noBid === null) {
    return 0;
  }

  // Arbitrage exists if YES bid + NO bid > 1
  // (can buy both YES and NO for less than 1 and guaranteed profit)
  const yesPlusNo = yesBid + noBid;
  return Math.max(0, yesPlusNo - 1);
}

/**
 * Compute orderbook depth at best levels
 */
export function computeDepth(
  yes: [number, number][],
  no: [number, number][]
): { bidDepth: number; askDepth: number; imbalance: number } {
  const bestYesBid = computeBestYesBid(yes);
  const bestNoBid = computeBestNoBid(no);

  if (bestYesBid === null || bestNoBid === null) {
    return { bidDepth: 0, askDepth: 0, imbalance: 0 };
  }

  // Find size at best levels
  const bestYesBidInt = Math.round(bestYesBid * 100);
  const bestNoBidInt = Math.round(bestNoBid * 100);

  const bidDepth = yes.find(([p]) => p === bestYesBidInt)?.[1] ?? 0;
  const askDepth = no.find(([p]) => p === bestNoBidInt)?.[1] ?? 0;

  const totalDepth = bidDepth + askDepth;
  const imbalance = totalDepth > 0 ? (bidDepth - askDepth) / totalDepth : 0;

  return { bidDepth, askDepth, imbalance };
}

/**
 * Convert Kalshi integer price to decimal probability
 */
export function intToProb(priceInt: number): number {
  return priceInt / 100;
}

/**
 * Convert decimal probability to Kalshi integer price
 */
export function probToInt(prob: number): number {
  return Math.round(prob * 100);
}
