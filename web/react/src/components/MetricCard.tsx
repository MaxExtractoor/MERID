import { formatCurrency, formatPercent, formatNumber } from "../utils/formatters";
import { STATUS_TYPES } from "../config/constants";

interface MetricCardProps {
  label: string;
  value: string | number;
  delta?: number;
  deltaPercent?: number;
  status?: keyof typeof STATUS_TYPES;
  trend?: "up" | "down" | "neutral";
  className?: string;
}

export default function MetricCard({
  label,
  value,
  delta,
  deltaPercent,
  status,
  trend,
  className = "",
}: MetricCardProps) {
  const getStatusColor = () => {
    switch (status) {
      case "GOOD":
      case "ONLINE":
        return "bg-green-500/10 text-green-500";
      case "WARNING":
      case "DEGRADED":
        return "bg-yellow-500/10 text-yellow-500";
      case "BAD":
      case "OFFLINE":
        return "bg-red-500/10 text-red-500";
      default:
        return "bg-slate-500/10 text-slate-500";
    }
  };

  const getBorderClass = () => {
    switch (status) {
      case "GOOD":
      case "ONLINE":
        return "border-green-500";
      case "WARNING":
      case "DEGRADED":
        return "border-yellow-500";
      case "BAD":
      case "OFFLINE":
        return "border-red-500";
      default:
        return "border-slate-500";
    }
  };

  const getStatusDot = () => {
    switch (status) {
      case "GOOD":
      case "ONLINE":
        return "bg-green-500";
      case "WARNING":
      case "DEGRADED":
        return "bg-yellow-500";
      case "BAD":
      case "OFFLINE":
        return "bg-red-500";
      default:
        return "bg-slate-500";
    }
  };

  const formatValue = () => {
    if (typeof value === "number") {
      if (label.toLowerCase().includes("currency") || label.toLowerCase().includes("p&l")) {
        return formatCurrency(value);
      }
      if (label.toLowerCase().includes("percent") || label.toLowerCase().includes("%")) {
        return formatPercent(value);
      }
      return formatNumber(value);
    }
    return value;
  };

  const getTrendIcon = () => {
    if (trend) {
      switch (trend) {
        case "up":
          return "↑";
        case "down":
          return "↓";
        default:
          return "→";
      }
    }
    if (delta !== undefined) {
      return delta > 0 ? "↑" : delta < 0 ? "↓" : "→";
    }
    return null;
  };

  const getDeltaColorClass = () => {
    if (delta !== undefined) {
      return delta > 0 ? "text-green-500" : delta < 0 ? "text-red-500" : "text-slate-500";
    }
    if (trend) {
      switch (trend) {
        case "up":
          return "text-green-500";
        case "down":
          return "text-red-500";
        default:
          return "text-slate-500";
      }
    }
    return "text-slate-500";
  };

  // Create delta text as single string with % and no extra spaces
  const getDeltaText = () => {
    if (delta !== undefined) {
      return `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`;
    }
    if (deltaPercent !== undefined) {
      return `${deltaPercent >= 0 ? "+" : ""}${deltaPercent.toFixed(2)}%`;
    }
    return null;
  };

  return (
    <div className={`metric-card ${getStatusColor()} ${getBorderClass()} ${className}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
          {label}
        </span>
        {status && (
          <div 
            data-testid="status-indicator"
            className={`w-2 h-2 rounded-full ${getStatusDot()}`}
            aria-label="status"
            role="img"
          />
        )}
      </div>
      
      <div className="flex items-baseline justify-between">
        <span className="text-2xl font-bold text-white">
          {formatValue()}
        </span>
        
        {(delta !== undefined || deltaPercent !== undefined || trend) && (
          <div className="flex items-center gap-1">
            {getTrendIcon() && (
              <span 
                className={`text-sm font-medium ${getDeltaColorClass()}`}
                aria-label="trend"
                role="img"
              >
                {getTrendIcon()}
              </span>
            )}
            
            {getDeltaText() && (
              <span className={`text-sm font-medium ${getDeltaColorClass()}`}>
                {getDeltaText()}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
