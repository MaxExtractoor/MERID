import React from 'react';

export interface TradeTableRow {
  trade_id: string;
  market: string;
  side: 'yes' | 'no';
  price_cents: number;
  quantity: number;
  timestamp: string;
}

const TradesTable: React.FC = () => (
  <div className="p-4">
    <h2 className="font-semibold mb-2">Trades</h2>
    <button type="button" title="Export trades to CSV" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
      Export
    </button>
  </div>
);

export default TradesTable;
