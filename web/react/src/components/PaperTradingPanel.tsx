import React from 'react';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { useApiData } from '../hooks/useApiData';

interface PaperTradingPanelProps {
  portfolioId: string;
}

const PaperTradingPanel = React.memo(function PaperTradingPanel({ portfolioId }: PaperTradingPanelProps) {
  const { loading, error } = useApiData<unknown>(API_ENDPOINTS.PAPER_TRADING_PORTFOLIO(portfolioId), {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
  });
  if (loading) return <div className="text-slate-400 text-sm">Loading...</div>;
  if (error) return <div className="text-red-400 text-sm">Error loading paper trading data.</div>;
  return <div className="p-4"><h2 className="font-semibold">Paper Trading</h2></div>;
});

PaperTradingPanel.displayName = 'PaperTradingPanel';
export default PaperTradingPanel;
