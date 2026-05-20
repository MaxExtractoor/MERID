/**
 * Settings type definitions
 * 
 * Shared types for Settings view and its sub-components.
 * 
 * Tier 4: Settings.tsx Split (953→4 files)
 */

export interface UserPreferences {
  theme: "light" | "dark" | "auto";
  language: string;
  timezone: string;
  dateFormat: string;
  numberFormat: string;
  defaultPage: string;
  notifications: {
    email: boolean;
    push: boolean;
    trading: boolean;
    risk: boolean;
    system: boolean;
  };
}

export interface TradingSettings {
  defaultOrderSize: number;
  maxLeverage: number;
  stopLossPercent: number;
  takeProfitPercent: number;
  maxPositionSize: number;
  confirmOrders: boolean;
  showAdvancedOptions: boolean;
  autoRefresh: boolean;
  refreshInterval: number;
}

export interface NotificationSettings {
  emailAlerts: boolean;
  pushNotifications: boolean;
  tradingAlerts: boolean;
  riskAlerts: boolean;
  systemAlerts: boolean;
  priceAlerts: boolean;
  orderAlerts: boolean;
  dailySummary: boolean;
  // weeklyReport removed - legacy feature not needed for 15m stack
}

export interface UserProfile {
  id: string;
  email: string;
  accountType: string;
  createdAt: string;
}
