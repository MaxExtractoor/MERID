/**
 * Prediction Market types for the Predictions Panel
 *
 * Aligned with backend contract:
 * - REST: GET /api/v1/predictions/markets
 * - WS: prediction:price_changed, prediction:position_updated, prediction:resolved
 */

export type PredictionMarketType = 'BINARY' | 'CATEGORICAL' | 'SCALAR';
export type PredictionMarketStatus = 'OPEN' | 'CLOSED' | 'RESOLVED';
export type PredictionPosition = 'YES' | 'NO' | 'NONE';
export type PredictionOutcome = 'YES' | 'NO' | 'INVALID';
export type PredictionModelPrediction = 'YES' | 'NO' | 'UNCERTAIN';

export interface PredictionMarket {
  id: string;
  symbol: string;
  marketType: PredictionMarketType;
  question: string;
  endTime: string;
  status: PredictionMarketStatus;
  
  // Current market data
  yesPrice: number;
  noPrice: number;
  volume: number;
  liquidity: number;
  
  // Our position
  ourPosition: PredictionPosition;
  ourSize: number;
  ourAvgPrice: number;
  ourPnl: number;
  
  // Model confidence
  modelConfidence: number;
  modelPrediction: PredictionModelPrediction;
  lastUpdated: string;
}

export interface PredictionsResponse {
  markets: PredictionMarket[];
  meta: {
    total: number;
    open: number;
    closed: number;
    totalVolume: number;
    totalPnl: number;
  };
}

// WebSocket payload types
export interface PredictionPriceChangedPayload {
  type: 'prediction:price_changed';
  id: string;
  yesPrice: number;
  noPrice: number;
  volume: number;
  timestamp: string;
}

export interface PredictionPositionUpdatedPayload {
  type: 'prediction:position_updated';
  id: string;
  ourPosition: PredictionPosition;
  ourSize: number;
  ourAvgPrice: number;
  ourPnl: number;
  fillPrice: number;
  fillSize: number;
}

export interface PredictionResolvedPayload {
  type: 'prediction:resolved';
  id: string;
  outcome: PredictionOutcome;
  resolutionPrice: number;
  ourPnl: number;
  resolvedAt: string;
}

export type PredictionEvent =
  | PredictionPriceChangedPayload
  | PredictionPositionUpdatedPayload
  | PredictionResolvedPayload;
