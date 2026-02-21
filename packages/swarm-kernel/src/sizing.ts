/**
 * Position Sizing Utilities
 * Kelly criterion and risk-adjusted sizing for arbitrage and trading
 */

export interface ArbContext {
  netEdge: number;             // Net expected profit per $1 staked (after fees)
  winProb: number;             // Model-estimated probability of success
  capital: number;             // Total capital allocated to arb strategy
  maxMarketExposure: number;   // Per-market dollar limit
  maxVenueExposure: number;    // Per-venue dollar limit
  currentMarketExposure: number;
  currentVenueExposure: number;
}

export interface KellyResult {
  size: number;                // Recommended position size in dollars
  fraction: number;            // Kelly fraction (0-1)
  limitedBy: "kelly" | "market" | "venue" | "capital" | "none";
  reason?: string;
}

/**
 * Kelly criterion for binary outcome with position limits
 * 
 * Formula: f* = (bp - q) / b
 * Where:
 * - b = odds (for binary ~1)
 * - p = win probability
 * - q = 1 - p
 * 
 * Applies hard limits and caps at configurable fraction (default: 10%)
 */
export function kellySizeForBinary(ctx: ArbContext, maxFraction: number = 0.1): KellyResult {
  const { netEdge, winProb, capital, maxMarketExposure, maxVenueExposure, currentMarketExposure, currentVenueExposure } = ctx;

  // No edge = no position
  if (netEdge <= 0) {
    return {
      size: 0,
      fraction: 0,
      limitedBy: "none",
      reason: "No positive edge",
    };
  }

  // Kelly fraction: f* = (bp - q) / b
  // For binary payoff, b ≈ 1
  const p = winProb;
  const q = 1 - p;
  const b = 1;
  const fStar = (b * p - q) / b;

  // Cap at maxFraction (e.g., 10% = quarter Kelly at 0.25)
  const frac = Math.max(0, Math.min(fStar, maxFraction));
  
  // Initial size from Kelly
  let size = capital * frac;
  let limitedBy: "kelly" | "market" | "venue" | "capital" | "none" = "kelly";

  // Apply market exposure limit
  const remainingMarket = maxMarketExposure - currentMarketExposure;
  if (size > remainingMarket) {
    size = remainingMarket;
    limitedBy = "market";
  }

  // Apply venue exposure limit
  const remainingVenue = maxVenueExposure - currentVenueExposure;
  if (size > remainingVenue) {
    size = remainingVenue;
    limitedBy = "venue";
  }

  // Apply capital limit
  if (size > capital) {
    size = capital;
    limitedBy = "capital";
  }

  return {
    size: Math.max(0, size),
    fraction: frac,
    limitedBy,
  };
}

/**
 * Simplified Kelly for arbitrage where win probability is ~1
 * (structural arb with both legs filled)
 */
export function kellyForArbitrage(
  netEdge: number,
  capital: number,
  maxExposure: number,
  currentExposure: number,
  conservativeFactor: number = 0.25
): number {
  if (netEdge <= 0) return 0;

  // For arbitrage, winProb ≈ 1, so Kelly fraction ≈ netEdge
  // Apply conservative scaling (quarter Kelly by default)
  const kellyFrac = netEdge * conservativeFactor;
  let size = capital * kellyFrac;

  // Apply exposure limit
  const remaining = maxExposure - currentExposure;
  size = Math.min(size, remaining);

  return Math.max(0, size);
}

/**
 * Compute Kelly fraction for general binary bet
 */
export function kellyFraction(winProb: number, payoff: number, lossPenalty: number = 1): number {
  // f* = (p * payoff - (1-p) * penalty) / payoff
  const p = winProb;
  const q = 1 - p;
  const frac = (p * payoff - q * lossPenalty) / payoff;
  return Math.max(0, frac);
}

/**
 * Convert dollar size to contract count
 */
export function dollarsToContracts(dollarSize: number, price: number): number {
  if (price <= 0) return 0;
  return Math.floor(dollarSize / price);
}

/**
 * Convert contract count to dollar size
 */
export function contractsToDollars(contracts: number, price: number): number {
  return contracts * price;
}

/**
 * Compute maximum safe size given volatility and drawdown tolerance
 */
export function volatilityAdjustedSize(
  baseSize: number,
  volatility: number,
  targetVolatility: number,
  minSize: number = 1
): number {
  if (volatility <= 0 || targetVolatility <= 0) {
    return baseSize;
  }

  // Scale size inversely with volatility
  const scaleFactor = targetVolatility / volatility;
  const adjustedSize = baseSize * scaleFactor;

  return Math.max(minSize, adjustedSize);
}

/**
 * Risk parity sizing across multiple strategies
 */
export function riskParitySize(
  strategies: { expectedReturn: number; volatility: number }[],
  totalCapital: number
): number[] {
  // Allocate inversely proportional to volatility
  const invVols = strategies.map(s => 1 / (s.volatility || 1));
  const sumInvVols = invVols.reduce((sum, iv) => sum + iv, 0);
  
  return invVols.map(iv => (iv / sumInvVols) * totalCapital);
}
