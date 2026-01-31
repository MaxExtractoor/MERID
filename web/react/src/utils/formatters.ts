// Data formatting utilities for MERID dashboard

export function formatCurrency(value: number, currency = "USD", digits?: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: digits ?? 2,
    maximumFractionDigits: digits ?? 2,
  }).format(value);
}

export function formatPercent(value: number, digits = 2): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatNumber(value: number, digits?: number): string {
  // If digits is specified, use fixed precision
  if (digits !== undefined) {
    return new Intl.NumberFormat("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(value);
  }
  
  // Otherwise, preserve natural decimal places (up to 3)
  const decimalPlaces = (value.toString().split(".")[1] || "").length;
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: Math.min(decimalPlaces, 3),
  }).format(value);
}

export function formatDateTime(iso: string | Date): string {
  const date = typeof iso === "string" ? new Date(iso) : iso;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export function formatDate(iso: string | Date, format?: string): string {
  const date = typeof iso === "string" ? new Date(iso) : iso;

  if (isNaN(date.getTime())) {
    return 'Invalid Date';
  }

  if (format === 'MM/DD/YYYY') {
    const month = (date.getMonth() + 1).toString().padStart(2, '0');
    const day = date.getDate().toString().padStart(2, '0');
    const year = date.getFullYear();
    return `${month}/${day}/${year}`;
  }

  if (format === 'readable') {
    return new Intl.DateTimeFormat("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    }).format(date);
  }

  if (format === 'relative') {
    const today = new Date();
    const isToday = date.getDate() === today.getDate() &&
      date.getMonth() === today.getMonth() &&
      date.getFullYear() === today.getFullYear();
    if (isToday) return 'Today';
  }

  // Default format: YYYY-MM-DD (ISO format, timezone-safe)
  const year = date.getFullYear();
  const month = (date.getMonth() + 1).toString().padStart(2, '0');
  const day = date.getDate().toString().padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function formatTime(iso: string | Date, format?: string, includeSeconds?: boolean): string {
  const date = typeof iso === "string" ? new Date(iso) : iso;
  // Use UTC methods to avoid timezone shifts
  const hours = date.getUTCHours();
  const minutes = date.getUTCMinutes();
  const secs = date.getUTCSeconds();

  const pad = (n: number) => n.toString().padStart(2, '0');

  if (format === '24h') {
    return `${pad(hours)}:${pad(minutes)}`;
  }

  // Default 12h format
  const period = hours >= 12 ? 'PM' : 'AM';
  const displayHours = hours % 12 || 12;
  let result = `${displayHours}:${pad(minutes)}`;
  if (includeSeconds) {
    result += `:${pad(secs)}`;
  }
  result += ` ${period}`;
  return result;
}

export function formatDuration(seconds: number, format?: string): string {
  const totalSeconds = Math.floor(seconds);
  const secs = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3600) % 24;
  const days = Math.floor(totalSeconds / 86400);

  if (format === 'verbose') {
    if (days > 0) {
      return `${days} days, ${hours} hours, ${minutes} minutes`;
    } else if (hours > 0) {
      return `${hours} hours, ${minutes} minutes`;
    } else if (minutes > 0) {
      return `${minutes} minutes, ${secs} seconds`;
    } else {
      return `${secs} seconds`;
    }
  }

  if (totalSeconds === 0) return '0s';

  if (days > 0) {
    return `${days}d ${hours}h ${minutes}m`;
  } else if (hours > 0) {
    return `${hours}h ${minutes}m ${secs}s`;
  } else if (minutes > 0) {
    return `${minutes}m ${secs}s`;
  } else {
    return `${secs}s`;
  }
}

export function formatFileSize(bytes: number, unitType?: string): string {
  const units = unitType === 'binary'
    ? ["B", "KiB", "MiB", "GiB", "TiB"]
    : ["B", "KB", "MB", "GB", "TB"];
  const divisor = unitType === 'binary' ? 1024 : 1024;
  let size = bytes;
  let unitIndex = 0;

  while (size >= divisor && unitIndex < units.length - 1) {
    size /= divisor;
    unitIndex++;
  }

  // For bytes, don't show decimal
  if (unitIndex === 0) {
    return `${Math.round(size)} ${units[unitIndex]}`;
  }

  return `${size.toFixed(1)} ${units[unitIndex]}`;
}

export function formatSymbol(symbol: string): string {
  // Normalize to BTC/USD format
  if (!symbol) return symbol;
  const clean = symbol.trim().toUpperCase();
  // If already has /, return as-is
  if (clean.includes('/')) return clean;
  // If has -, convert to /
  if (clean.includes('-')) return clean.replace('-', '/');
  // Otherwise, try to split into base/quote (assuming last 3-4 chars are quote)
  if (clean.length >= 6) {
    const quote = clean.slice(-3);
    const base = clean.slice(0, -3);
    return `${base}/${quote}`;
  }
  return clean;
}

export function formatSide(side: string): string {
  return side.charAt(0).toUpperCase() + side.slice(1).toLowerCase();
}

export function formatOrderType(type: string): string {
  return type.charAt(0).toUpperCase() + type.slice(1).toLowerCase();
}

export function formatOrderDetails(order: {
  symbol: string;
  side: string;
  size: number;
  price?: number;
  type: string;
}): string {
  const formattedSide = formatSide(order.side);
  const formattedSymbol = formatSymbol(order.symbol);
  const formattedType = formatOrderType(order.type);

  if (order.type.toLowerCase() === 'market' || order.price === undefined) {
    return `${formattedSide} ${order.size} ${formattedSymbol} at Market (${formattedType})`;
  }

  const formattedPrice = formatCurrency(order.price);
  return `${formattedSide} ${order.size} ${formattedSymbol} at ${formattedPrice} (${formattedType})`;
}

export function getDeltaColor(value: number): string {
  if (value > 0) return "text-green-500";
  if (value < 0) return "text-red-500";
  return "text-gray-500";
}

export function getDeltaIcon(value: number): string {
  if (value > 0) return "↑";
  if (value < 0) return "↓";
  return "→";
}

export interface DeltaFormatted {
  value: string;
  percent: string;
  color: string;
  icon: string;
}

export function formatDelta(value: number, baseline?: number, mode?: 'percent' | 'value'): DeltaFormatted {
  // Calculate actual delta
  let deltaValue: number;
  let deltaPercent: number;

  if (baseline !== undefined && baseline !== 0) {
    deltaValue = value - baseline;
    deltaPercent = (deltaValue / baseline) * 100;
  } else if (baseline === 0) {
    deltaValue = value;
    deltaPercent = value > 0 ? Infinity : value < 0 ? -Infinity : 0;
  } else {
    deltaValue = value;
    deltaPercent = value;
  }

  const color = getDeltaColor(deltaValue);
  const icon = getDeltaIcon(deltaValue);

  if (mode === 'percent') {
    const sign = deltaPercent >= 0 ? '+' : '';
    const percentStr = deltaPercent === Infinity || deltaPercent === -Infinity
      ? '∞%'
      : `${sign}${deltaPercent.toFixed(2)}%`;
    return {
      value: percentStr,
      percent: percentStr,
      color,
      icon,
    };
  }

  // For zero delta, show without sign
  if (deltaValue === 0) {
    return {
      value: formatCurrency(0),
      percent: '0.00%',
      color,
      icon,
    };
  }

  // When baseline is 0, don't show + sign for positive value
  if (baseline === 0 && deltaValue > 0) {
    return {
      value: formatCurrency(deltaValue),
      percent: '∞%',
      color,
      icon,
    };
  }

  const sign = deltaValue >= 0 ? '+' : '';
  // For negative values, formatCurrency adds the minus sign, so don't add another
  const valueStr = deltaValue < 0 
    ? formatCurrency(deltaValue)  // already includes minus
    : `${sign}${formatCurrency(deltaValue)}`;  // add plus for positive
  const percentStr = deltaPercent === Infinity || deltaPercent === -Infinity
    ? '∞%'
    : `${sign}${deltaPercent.toFixed(2)}%`;

  return {
    value: valueStr,
    percent: percentStr,
    color,
    icon,
  };
}

export function formatDeltaPercent(value: number, showIcon = true): string {
  const sign = value >= 0 ? "+" : "";
  const icon = showIcon ? getDeltaIcon(value) + " " : "";
  return `${icon}${sign}${formatPercent(value)}`;
}
