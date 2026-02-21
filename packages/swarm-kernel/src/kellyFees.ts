/**
 * Kelly Criterion with Kalshi Fee Models
 * Accounts for price-dependent maker/taker fees in position sizing
 */

/**
 * Estimate Kalshi taker fee rate based on price
 * 
 * Kalshi fees are price-dependent:
 * - Peak fees near 50¢ (0.5 probability)
 * - Lower fees at extremes (deep ITM/OTM)
 * 
 * Formula approximates: fee ≈ 0.0175 × P × (1-P) for taker
 * 
 * @param price - Market price (0-1)
 * @returns Fee rate as fraction of stake
 */
export function kalshiTakerFeeRate(price: number): number {
  const p = Math.max(0.01, Math.min(0.99, price));
  
  // Parabolic shape: highest at 0.5, lowest at extremes
  // Peak around 1.75¢ at 50¢, scales down to ~0.5¢ at extremes
  const base = 0.0175 * p * (1 - p);
  
  return base;
}

/**
 * Estimate Kalshi maker fee rate based on price
 * 
 * Maker fees are typically 50% of taker fees
 * 
 * @param price - Market price (0-1)
 * @returns Fee rate as fraction of stake
 */
export function kalshiMakerFeeRate(price: number): number {
  return kalshiTakerFeeRate(price) * 0.5;
}

/**
 * Get fee rate based on order side
 */
export function kalshiFeeRate(price: number, side: "taker" | "maker"): number {
  return side === "taker" 
    ? kalshiTakerFeeRate(price)
    : kalshiMakerFeeRate(price);
}

/**
 * Calculate full Kelly fraction with fees
 * 
 * For binary contract with subjective probability p and market price pm:
 * - Net edge = p - pm - fee(pm)
 * - Full Kelly fraction = netEdge / (pm × (1-pm))
 * 
 * @param pTrue - Your subjective probability (0-1)
 * @param marketPrice - Market price (0-1)
 * @param side - Maker or taker
 * @returns Kelly fraction (0-1)
 */
export function fullKellyWithFees(
  pTrue: number,
  marketPrice: number,
  side: "taker" | "maker" = "taker"
): number {
  const p = pTrue;
  const pm = marketPrice;
  
  // Fee as fraction of stake
  const feeRate = kalshiFeeRate(pm, side);
  
  // Net edge per $1 staked
  const netEdge = p - pm - feeRate;
  
  if (netEdge <= 0) return 0;
  
  // Kelly denominator for binary outcome
  const denom = pm * (1 - pm);
  if (denom < 1e-6) return 0;
  
  const fStar = netEdge / denom;
  
  return Math.max(0, Math.min(fStar, 1));
}

/**
 * Calculate fractional Kelly with fees
 * 
 * Applies conservative scaling (default: quarter Kelly)
 * 
 * @param bankroll - Available capital
 * @param pTrue - Your subjective probability
 * @param marketPrice - Market price
 * @param side - Maker or taker
 * @param fraction - Fraction of full Kelly (default: 0.25)
 * @returns Dollar size
 */
export function fractionalKellyWithFees(
  bankroll: number,
  pTrue: number,
  marketPrice: number,
  side: "taker" | "maker" = "taker",
  fraction: number = 0.25
): number {
  const fStar = fullKellyWithFees(pTrue, marketPrice, side);
  const fAdj = fStar * fraction;
  
  return bankroll * fAdj;
}

/**
 * Net expected value after fees
 * 
 * @param pTrue - Your subjective probability
 * @param marketPrice - Market price
 * @param size - Position size in dollars
 * @param side - Maker or taker
 * @returns Expected profit in dollars
 */
export function netEVAfterFees(
  pTrue: number,
  marketPrice: number,
  size: number,
  side: "taker" | "maker" = "taker"
): number {
  const feeRate = kalshiFeeRate(marketPrice, side);
  const fee = feeRate * size;
  
  // Expected payout - cost - fee
  const expectedPayout = pTrue * size;
  const cost = marketPrice * size;
  
  return expectedPayout - cost - fee;
}

/**
 * Check if trade is profitable after fees
 * 
 * @param pTrue - Your subjective probability
 * @param marketPrice - Market price
 * @param side - Maker or taker
 * @param minEdge - Minimum required edge (default: 0.01 = 1%)
 * @returns True if profitable
 */
export function isProfitableAfterFees(
  pTrue: number,
  marketPrice: number,
  side: "taker" | "maker" = "taker",
  minEdge: number = 0.01
): boolean {
  const feeRate = kalshiFeeRate(marketPrice, side);
  const netEdge = pTrue - marketPrice - feeRate;
  
  return netEdge > minEdge;
}

/**
 * Fee-to-profit ratio for trade analysis
 * 
 * @param grossEdge - Edge before fees
 * @param marketPrice - Market price
 * @param side - Maker or taker
 * @returns Ratio of fees to gross profit
 */
export function feeToGrossProfitRatio(
  grossEdge: number,
  marketPrice: number,
  side: "taker" | "maker" = "taker"
): number {
  const feeRate = kalshiFeeRate(marketPrice, side);
  
  if (grossEdge <= 0) return Infinity;
  
  return feeRate / grossEdge;
}

/**
 * Compare maker vs taker economics
 * 
 * @param pTrue - Your subjective probability
 * @param marketPrice - Market price
 * @returns Analysis of maker vs taker profitability
 */
export function compareMakerTaker(
  pTrue: number,
  marketPrice: number
): {
  taker: { netEdge: number; feeRate: number; profitable: boolean };
  maker: { netEdge: number; feeRate: number; profitable: boolean };
  makerAdvantage: number;
} {
  const takerFee = kalshiTakerFeeRate(marketPrice);
  const makerFee = kalshiMakerFeeRate(marketPrice);
  
  const takerNetEdge = pTrue - marketPrice - takerFee;
  const makerNetEdge = pTrue - marketPrice - makerFee;
  
  return {
    taker: {
      netEdge: takerNetEdge,
      feeRate: takerFee,
      profitable: takerNetEdge > 0,
    },
    maker: {
      netEdge: makerNetEdge,
      feeRate: makerFee,
      profitable: makerNetEdge > 0,
    },
    makerAdvantage: makerNetEdge - takerNetEdge,
  };
}
