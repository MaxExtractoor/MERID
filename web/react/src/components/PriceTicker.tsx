import { useState, useEffect } from "react";
import { formatCurrency, formatPercent, getDeltaColor } from "../utils/formatters";

interface PriceData {
  symbol: string;
  last: number;
  change: number;
  changePercent: number;
  volume?: number;
  timestamp?: string;
}

interface PriceTickerProps {
  symbol: string;
  initialData?: PriceData;
  showVolume?: boolean;
  showTimestamp?: boolean;
  className?: string;
}

export default function PriceTicker({
  symbol,
  initialData,
  showVolume = false,
  showTimestamp = false,
  className = "",
}: PriceTickerProps) {
  const [priceData, setPriceData] = useState<PriceData>(
    initialData || {
      symbol,
      last: 0,
      change: 0,
      changePercent: 0,
    }
  );

  // Simulate price updates (in real app, this would come from WebSocket)
  useEffect(() => {
    if (!initialData) {
      // Mock data for demonstration
      const mockData: PriceData = {
        symbol,
        last: 42000 + Math.random() * 1000,
        change: (Math.random() - 0.5) * 500,
        changePercent: (Math.random() - 0.5) * 2,
        volume: Math.floor(Math.random() * 1000000),
        timestamp: new Date().toISOString(),
      };
      setPriceData(mockData);
    } else {
      // Update state when initialData prop changes
      setPriceData(initialData);
    }
  }, [symbol, initialData]);

  const deltaColor = getDeltaColor(priceData.change);
  const changeIcon = priceData.change >= 0 ? "↑" : "↓";

  return (
    <div className={`price-ticker ${className}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="font-mono text-sm font-medium text-slate-300">
            {symbol}
          </span>
          
          <span className="text-lg font-bold text-white">
            {formatCurrency(priceData.last)}
          </span>
          
          <div className={`flex items-center gap-1 ${deltaColor}`}>
            <span className="text-sm font-medium">{changeIcon}</span>
            <span className="text-sm font-medium">
              {priceData.change >= 0 ? "+" : ""}
              {formatCurrency(Math.abs(priceData.change))}
            </span>
            <span className="text-sm font-medium">
              ({priceData.changePercent >= 0 ? "+" : ""}
              {formatPercent(priceData.changePercent)})
            </span>
          </div>
        </div>
        
        <div className="flex items-center gap-4 text-sm text-slate-400">
          {showVolume && priceData.volume && (
            <span>Vol: {formatNumber(priceData.volume)}</span>
          )}
          
          {showTimestamp && priceData.timestamp && (
            <span>{formatTime(priceData.timestamp)}</span>
          )}
        </div>
      </div>
    </div>
  );
}

// Helper function for formatting time (import from formatters)
function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}
