/**
 * Kalshi Fee and Slippage Models
 * Realistic modeling for backtesting and estimation
 * 
 * Kalshi fees are price-dependent and differ for makers vs takers
 */

export type OrderSide = "maker" | "taker";
export type TradeSide = "buy" | "sell";

/**
 * Estimate Kalshi trading fee
 * 
 * Fees are higher near 0.5 (50/50 markets), lower for ITM/OTM
 * Makers pay reduced fees compared to takers
 * 
 * Based on Kalshi's tiered fee structure
 */
export function estimateKalshiFee(
  side: OrderSide,
  price: number, // 0-1 probability
  size: number
): number {
  // Clamp price to valid range
  price = Math.max(0.01, Math.min(0.99, price));

  // Base rate depends on how close to 0.5 (uncertainty)
  let baseRate: number;
  
  if (price >= 0.4 && price <= 0.6) {
    // Near 50/50: highest fees (max uncertainty)
    baseRate = 0.02; // 2%
  } else if (price >= 0.25 && price <= 0.75) {
    // Moderate odds: mid-tier fees
    baseRate = 0.015; // 1.5%
  } else {
    // Deep ITM/OTM: lowest fees
    baseRate = 0.01; // 1%
  }

  // Maker discount (typically 50% off taker fees)
  if (side === "maker") {
    baseRate *= 0.5;
  }

  return baseRate * size * price; // Fee in dollars
}

/**
 * Apply price impact / slippage based on size vs book depth
 * 
 * Models the effect of walking up/down the orderbook
 */
export function applySlippage(
  side: TradeSide,
  desiredPrice: number,
  size: number,
  topDepth: number
): number {
  if (topDepth <= 0) return desiredPrice;

  // Impact as percentage of desired price
  // Larger orders relative to depth have more impact
  const impactFactor = Math.min(size / topDepth, 1.0);
  const maxImpact = 0.01; // Max 1 cent impact
  const impact = maxImpact * impactFactor;

  // Buy orders pay higher, sell orders receive lower
  if (side === "buy") {
    return Math.min(0.99, desiredPrice + impact);
  } else {
    return Math.max(0.01, desiredPrice - impact);
  }
}

/**
 * Estimate total transaction cost for a trade
 * Includes both fees and slippage
 */
export function estimateTransactionCost(
  orderSide: OrderSide,
  tradeSide: TradeSide,
  price: number,
  size: number,
  depth: number
): { 
  effectivePrice: number; 
  fee: number; 
  slippage: number;
  totalCost: number;
} {
  // Apply slippage to get effective execution price
  const effectivePrice = applySlippage(tradeSide, price, size, depth);
  
  // Calculate fee on effective price
  const fee = estimateKalshiFee(orderSide, effectivePrice, size);
  
  // Slippage cost (difference from desired price)
  const slippageCost = Math.abs(effectivePrice - price) * size;
  
  // Total cost in dollars
  const baseCost = effectivePrice * size;
  const totalCost = baseCost + fee;

  return {
    effectivePrice,
    fee,
    slippage: slippageCost,
    totalCost,
  };
}

/**
 * Model maker-taker dynamics for limit orders
 * 
 * Returns expected fill probability and effective price
 */
export function modelLimitOrderFill(
  limitPrice: number,
  size: number,
  bestPrice: number,
  depth: number,
  volatility: number
): {
  fillProbability: number;
  expectedFillPrice: number;
  expectedWaitTime: number; // seconds
} {
  // Distance from best price (in cents)
  const distance = Math.abs(limitPrice - bestPrice) * 100;

  // Fill probability decreases with distance from best
  // and increases with volatility (more price movement)
  const baseFillProb = Math.exp(-distance / (volatility * 10 + 1));
  
  // Adjust for size vs depth (harder to fill large orders)
  const sizeAdjustment = Math.exp(-size / (depth + 1));
  const fillProbability = baseFillProb * sizeAdjustment;

  // Expected wait time (rough heuristic)
  // Closer to best price = faster fill
  const expectedWaitTime = distance * 5 + (size / depth) * 10;

  return {
    fillProbability: Math.min(fillProbability, 0.95), // Cap at 95%
    expectedFillPrice: limitPrice, // If filled, get limit price
    expectedWaitTime,
  };
}

/**
 * Net edge calculator accounting for all costs
 */
export function computeNetEdge(
  grossEdge: number,
  yesFee: number,
  noFee: number,
  yesSlippage: number,
  noSlippage: number
): number {
  return grossEdge - yesFee - noFee - yesSlippage - noSlippage;
}

/**
 * Break-even analysis: minimum edge required to be fee-positive
 */
export function minProfitableEdge(
  yesPrice: number,
  noPrice: number,
  size: number,
  orderSide: OrderSide = "taker"
): number {
  const yesFee = estimateKalshiFee(orderSide, yesPrice, size);
  const noFee = estimateKalshiFee(orderSide, noPrice, size);
  
  // Total fees as fraction of position cost
  const totalCost = (yesPrice + noPrice) * size;
  const totalFees = yesFee + noFee;
  
  return totalFees / size; // Minimum edge per contract
}
