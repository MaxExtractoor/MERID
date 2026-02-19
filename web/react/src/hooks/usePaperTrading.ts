import { useCallback } from 'react';
import { useApiData } from './useApiData';
import { API_ENDPOINTS } from '../config/constants';

export interface PaperPosition {
  symbol: string;
  domain: string;
  side: 'long' | 'short';
  size: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  pnl_pct: number;
  opened_at: string;
}

export interface PaperOrder {
  id: string;
  symbol: string;
  side: string;
  order_type: string;
  size: number;
  price: number;
  status: string;
  created_at: string;
  filled_at?: string;
}

export interface PnLPoint {
  ts: number;
  equity: number;
  pnl: number;
  domain?: string;
}

export interface PaperPortfolio {
  equity: number;
  cash: number;
  total_pnl: number;
  daily_pnl: number;
  positions_count: number;
  domains: Record<string, { equity: number; pnl: number; positions: number }>;
  win_rate: number;
  total_trades: number;
}

interface PortfolioResponse {
  portfolio?: PaperPortfolio;
  pnl_history?: PnLPoint[];
  equity_curve?: PnLPoint[];
}

interface PositionsResponse {
  positions?: PaperPosition[];
}

interface OrdersResponse {
  orders?: PaperOrder[];
}

export function usePaperTrading(pollMs = 10000) {
  const portResult = useApiData<PortfolioResponse>(
    API_ENDPOINTS.PAPER_PORTFOLIO,
    { pollingInterval: pollMs },
  );
  const posResult = useApiData<PositionsResponse>(
    API_ENDPOINTS.PAPER_POSITIONS,
    { pollingInterval: pollMs },
  );
  const ordResult = useApiData<OrdersResponse>(
    API_ENDPOINTS.PAPER_ORDERS,
    { pollingInterval: pollMs },
  );

  const portfolio: PaperPortfolio | null =
    portResult.data?.portfolio ?? (portResult.data as unknown as PaperPortfolio) ?? null;
  const pnlHistory: PnLPoint[] =
    portResult.data?.pnl_history ?? portResult.data?.equity_curve ?? [];
  const positions: PaperPosition[] =
    posResult.data?.positions ?? (Array.isArray(posResult.data) ? posResult.data : []);
  const orders: PaperOrder[] =
    ordResult.data?.orders ?? (Array.isArray(ordResult.data) ? ordResult.data : []);

  const loading = portResult.loading || posResult.loading || ordResult.loading;
  const error = portResult.error?.message ?? posResult.error?.message ?? ordResult.error?.message ?? null;
  const isStub = portResult.isStub || posResult.isStub || ordResult.isStub;

  const refresh = useCallback(async () => {
    await Promise.all([portResult.refetch(), posResult.refetch(), ordResult.refetch()]);
  }, [portResult.refetch, posResult.refetch, ordResult.refetch]);

  return { portfolio, positions, orders, pnlHistory, loading, error, isStub, refresh };
}
