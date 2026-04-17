import { useState } from "react";
import { RefreshCw } from 'lucide-react';
import { useApiData } from "../hooks/useApiData";
import { API_BASE_URL, API_ENDPOINTS, AUTH_TOKEN_KEY, DEFAULTS } from "../config/constants";
import { useLocalStorage } from "../hooks/useLocalStorage";
import ErrorAlert from "../components/ErrorAlert";
import { validateLeverage } from "../utils/validators";
import MetricCard from "../components/MetricCard";
import { useFeatureFlags, setKalshiOnly } from "../config/featureFlags";

interface UserPreferences {
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

interface TradingSettings {
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

interface NotificationSettings {
  emailAlerts: boolean;
  pushNotifications: boolean;
  tradingAlerts: boolean;
  riskAlerts: boolean;
  systemAlerts: boolean;
  priceAlerts: boolean;
  orderAlerts: boolean;
  dailySummary: boolean;
  weeklyReport: boolean;
}

interface UserProfile {
  id: string;
  email: string;
  accountType: string;
  createdAt: string;
}

export default function Settings() {
  const [activeTab, setActiveTab] = useState<"preferences" | "trading" | "notifications" | "risk" | "agents">("preferences");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const { kalshiOnly } = useFeatureFlags();

  // User preferences with local storage
  const [preferences, setPreferences] = useLocalStorage<UserPreferences>("user-preferences", {
    theme: "dark",
    language: "en",
    timezone: "UTC",
    dateFormat: "YYYY-MM-DD",
    numberFormat: "en-US",
    defaultPage: "overview",
    notifications: {
      email: true,
      push: true,
      trading: true,
      risk: true,
      system: true,
    },
  });

  // Trading settings with local storage
  const [tradingSettings, setTradingSettings] = useLocalStorage<TradingSettings>("trading-settings", {
    defaultOrderSize: 1000,
    maxLeverage: 3,
    stopLossPercent: 2,
    takeProfitPercent: 5,
    maxPositionSize: 100000,
    confirmOrders: true,
    showAdvancedOptions: false,
    autoRefresh: true,
    refreshInterval: 5000,
  });

  // Notification settings with local storage
  const [notificationSettings, setNotificationSettings] = useLocalStorage<NotificationSettings>("notification-settings", {
    emailAlerts: true,
    pushNotifications: true,
    tradingAlerts: true,
    riskAlerts: true,
    systemAlerts: true,
    priceAlerts: true,
    orderAlerts: true,
    dailySummary: true,
    weeklyReport: false,
  });

  // Fetch current user data
  const { data: userData, loading: profileLoading, error: profileError, refetch: refetchProfile } = useApiData<UserProfile>(API_ENDPOINTS.USER_PROFILE);

  if (profileLoading && !userData) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        <span className="ml-3 text-slate-400">Loading settings…</span>
      </div>
    );
  }

  if (profileError && !userData) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <ErrorAlert message="Failed to load user profile" onRetry={refetchProfile} />
      </div>
    );
  }

  const handleSave = async () => {
    setSaving(true);
    setSaveMessage(null);

    try {
      // Save to API
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.USER_SETTINGS}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem(AUTH_TOKEN_KEY)}`,
          "X-Session-ID": localStorage.getItem(AUTH_TOKEN_KEY) ?? "",
        },
        body: JSON.stringify({
          preferences,
          tradingSettings,
          notificationSettings,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to save settings");
      }

      setSaveMessage("Settings saved successfully!");
      setTimeout(() => setSaveMessage(null), DEFAULTS.POLLING_INTERVALS.FAST_REFRESH);
    } catch (error) {
      setSaveMessage("Failed to save settings");
      setTimeout(() => setSaveMessage(null), DEFAULTS.POLLING_INTERVALS.FAST_REFRESH);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    if (confirm("Are you sure you want to reset all settings to defaults?")) {
      setPreferences({
        theme: "dark",
        language: "en",
        timezone: "UTC",
        dateFormat: "YYYY-MM-DD",
        numberFormat: "en-US",
        defaultPage: "overview",
        notifications: {
          email: true,
          push: true,
          trading: true,
          risk: true,
          system: true,
        },
      });

      setTradingSettings({
        defaultOrderSize: 1000,
        maxLeverage: 3,
        stopLossPercent: 2,
        takeProfitPercent: 5,
        maxPositionSize: 100000,
        confirmOrders: true,
        showAdvancedOptions: false,
        autoRefresh: true,
        refreshInterval: 5000,
      });

      setNotificationSettings({
        emailAlerts: true,
        pushNotifications: true,
        tradingAlerts: true,
        riskAlerts: true,
        systemAlerts: true,
        priceAlerts: true,
        orderAlerts: true,
        dailySummary: true,
        weeklyReport: false,
      });
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <div className="flex items-center gap-4">
          {saveMessage && (
            <span className={`text-sm ${
              saveMessage.includes("success") ? "text-green-500" : "text-red-500"
            }`}>
              {saveMessage}
            </span>
          )}
          <button type="button"
            onClick={handleReset}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg font-medium transition-colors"
           title="Reset to Defaults">
            Reset to Defaults
          </button>
          <button type="button"
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors disabled:opacity-50"
           title="Save">
            {saving ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </div>

      {/* User Info */}
      {userData && (
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
          <h2 className="text-lg font-semibold text-white mb-4">User Information</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricCard
              label="User ID"
              value={userData.id}
              status="GOOD"
            />
            <MetricCard
              label="Email"
              value={userData.email}
              status="GOOD"
            />
            <MetricCard
              label="Account Type"
              value={userData.accountType}
              status="GOOD"
            />
            <MetricCard
              label="Member Since"
              value={new Date(userData.createdAt).toLocaleDateString()}
              status="GOOD"
            />
          </div>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-2">
        <div className="flex gap-2">
          <button type="button"
            onClick={() => setActiveTab("preferences")}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === "preferences"
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            User Preferences
          </button>
          <button type="button"
            onClick={() => setActiveTab("trading")}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === "trading"
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            Trading Settings
          </button>
          <button type="button"
            onClick={() => setActiveTab("notifications")}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === "notifications"
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            Notifications
          </button>
          <button type="button"
            onClick={() => setActiveTab("risk")}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === "risk"
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            Risk Parameters
          </button>
          <button type="button"
            onClick={() => setActiveTab("agents")}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === "agents"
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            Agent Config
          </button>
        </div>
      </div>

      {/* Tab Content */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        {/* User Preferences Tab */}
        {activeTab === "preferences" && (
          <div className="space-y-6">
            <h2 className="text-lg font-semibold text-white">User Preferences</h2>

            {/* UI Profile Mode */}
            <div className="p-4 bg-slate-800/50 rounded-xl border border-orange-500/30">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-orange-400">Kalshi-Only Mode</h3>
                  <p className="text-xs text-slate-400 mt-1">
                    Hide legacy crypto/research panels. Focus the UI on Kalshi live trading only.
                  </p>
                </div>
                <button type="button"
                  onClick={() => setKalshiOnly(!kalshiOnly)}
                  className={`relative w-11 h-6 rounded-full transition-colors ${
                    kalshiOnly ? 'bg-orange-500' : 'bg-slate-600'
                  }`}
                  title="Toggle Kalshi-only mode"
                >
                  <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${
                    kalshiOnly ? 'translate-x-5' : ''
                  }`} />
                </button>
              </div>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label htmlFor="pref-theme" className="block text-sm font-medium text-slate-400 mb-2">Theme</label>
                <select aria-label="Theme"
                  id="pref-theme"
                  name="theme"
                  title="Select theme"
                  value={preferences.theme}
                  onChange={(e) => setPreferences({ ...preferences, theme: e.target.value as UserPreferences['theme'] })}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="light">Light</option>
                  <option value="dark">Dark</option>
                  <option value="auto">Auto</option>
                </select>
              </div>

              <div>
                <label htmlFor="pref-language" className="block text-sm font-medium text-slate-400 mb-2">Language</label>
                <select aria-label="Language"
                  id="pref-language"
                  name="language"
                  title="Select language"
                  value={preferences.language}
                  onChange={(e) => setPreferences({ ...preferences, language: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="en">English</option>
                  <option value="es">Spanish</option>
                  <option value="fr">French</option>
                  <option value="de">German</option>
                </select>
              </div>

              <div>
                <label htmlFor="pref-timezone" className="block text-sm font-medium text-slate-400 mb-2">Timezone</label>
                <select aria-label="Timezone"
                  id="pref-timezone"
                  name="timezone"
                  title="Select timezone"
                  value={preferences.timezone}
                  onChange={(e) => setPreferences({ ...preferences, timezone: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="UTC">UTC</option>
                  <option value="America/New_York">Eastern Time</option>
                  <option value="America/Los_Angeles">Pacific Time</option>
                  <option value="Europe/London">London</option>
                  <option value="Asia/Tokyo">Tokyo</option>
                </select>
              </div>

              <div>
                <label htmlFor="pref-date-format" className="block text-sm font-medium text-slate-400 mb-2">Date Format</label>
                <select aria-label="Date Format"
                  id="pref-date-format"
                  name="dateFormat"
                  title="Select date format"
                  value={preferences.dateFormat}
                  onChange={(e) => setPreferences({ ...preferences, dateFormat: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="YYYY-MM-DD">YYYY-MM-DD</option>
                  <option value="MM/DD/YYYY">MM/DD/YYYY</option>
                  <option value="DD/MM/YYYY">DD/MM/YYYY</option>
                </select>
              </div>

              <div>
                <label htmlFor="pref-number-format" className="block text-sm font-medium text-slate-400 mb-2">Number Format</label>
                <select aria-label="Number Format"
                  id="pref-number-format"
                  name="numberFormat"
                  title="Select number format"
                  value={preferences.numberFormat}
                  onChange={(e) => setPreferences({ ...preferences, numberFormat: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="en-US">English (US)</option>
                  <option value="en-GB">English (UK)</option>
                  <option value="de-DE">German</option>
                  <option value="fr-FR">French</option>
                </select>
              </div>

              <div>
                <label htmlFor="pref-default-page" className="block text-sm font-medium text-slate-400 mb-2">Default Page</label>
                <select aria-label="Default Page"
                  id="pref-default-page"
                  name="defaultPage"
                  value={preferences.defaultPage}
                  onChange={(e) => setPreferences({ ...preferences, defaultPage: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="overview">Overview</option>
                  <option value="trading">Trading</option>
                  <option value="agents">Agents</option>
                  <option value="predictions">Predictions</option>
                  <option value="risk">Risk</option>
                </select>
              </div>
            </div>
          </div>
        )}

        {/* Trading Settings Tab */}
        {activeTab === "trading" && (
          <div className="space-y-6">
            <h2 className="text-lg font-semibold text-white">Trading Settings</h2>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label htmlFor="default-order-size" className="block text-sm font-medium text-slate-400 mb-2">Default Order Size</label>
                <input aria-label="Default Order Size"
                  id="default-order-size"
                  name="defaultOrderSize"
                  type="number"
                  title="Enter default order size"
                  placeholder="Default order size"
                  value={tradingSettings.defaultOrderSize}
                  onChange={(e) => setTradingSettings({ ...tradingSettings, defaultOrderSize: Number(e.target.value) })}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label htmlFor="max-leverage" className="block text-sm font-medium text-slate-400 mb-2">Max Leverage</label>
                <input aria-label="Max Leverage"
                  id="max-leverage"
                  name="maxLeverage"
                  type="number"
                  title="Enter maximum leverage"
                  placeholder="Max leverage"
                  value={tradingSettings.maxLeverage}
                  onChange={(e) => {
                    const value = Number(e.target.value);
                    const validation = validateLeverage(value);
                    if (validation.valid) {
                      setTradingSettings({ ...tradingSettings, maxLeverage: value });
                    }
                  }}
                  step="0.1"
                  min="1"
                  max="100"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label htmlFor="stop-loss" className="block text-sm font-medium text-slate-400 mb-2">Stop Loss (%)</label>
                <input aria-label="Stop Loss (%)"
                  id="stop-loss"
                  name="stopLoss"
                  type="number"
                  title="Enter stop loss percentage"
                  placeholder="Stop loss %"
                  value={tradingSettings.stopLossPercent}
                  onChange={(e) => setTradingSettings({ ...tradingSettings, stopLossPercent: Number(e.target.value) })}
                  step="0.1"
                  min="0"
                  max="100"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label htmlFor="take-profit" className="block text-sm font-medium text-slate-400 mb-2">Take Profit (%)</label>
                <input aria-label="Take Profit (%)"
                  id="take-profit"
                  name="takeProfit"
                  type="number"
                  title="Enter take profit percentage"
                  placeholder="Take profit %"
                  value={tradingSettings.takeProfitPercent}
                  onChange={(e) => setTradingSettings({ ...tradingSettings, takeProfitPercent: Number(e.target.value) })}
                  step="0.1"
                  min="0"
                  max="100"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label htmlFor="max-position-size" className="block text-sm font-medium text-slate-400 mb-2">Max Position Size</label>
                <input aria-label="Max Position Size"
                  id="max-position-size"
                  name="maxPositionSize"
                  type="number"
                  title="Enter maximum position size"
                  placeholder="Max position size"
                  value={tradingSettings.maxPositionSize}
                  onChange={(e) => setTradingSettings({ ...tradingSettings, maxPositionSize: Number(e.target.value) })}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label htmlFor="trading-refresh-interval" className="block text-sm font-medium text-slate-400 mb-2">Auto Refresh Interval (ms)</label>
                <select aria-label="Auto Refresh Interval (ms)"
                  id="trading-refresh-interval"
                  name="refreshInterval"
                  title="Select auto refresh interval"
                  value={tradingSettings.refreshInterval}
                  onChange={(e) => setTradingSettings({ ...tradingSettings, refreshInterval: Number(e.target.value) })}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                >
                  <option value={1000}>1 second</option>
                  <option value={5000}>5 seconds</option>
                  <option value={10000}>10 seconds</option>
                  <option value={30000}>30 seconds</option>
                </select>
              </div>
            </div>

            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input aria-label="Trading Settings"
                  id="confirm-orders"
                  name="confirmOrders"
                  type="checkbox"
                  checked={tradingSettings.confirmOrders}
                  onChange={(e) => setTradingSettings({ ...tradingSettings, confirmOrders: e.target.checked })}
                  className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                />
                <span className="text-white">Confirm orders before execution</span>
              </label>

              <label className="flex items-center gap-3">
                <input aria-label="Confirm orders before execution"
                  id="show-advanced-options"
                  name="showAdvancedOptions"
                  type="checkbox"
                  checked={tradingSettings.showAdvancedOptions}
                  onChange={(e) => setTradingSettings({ ...tradingSettings, showAdvancedOptions: e.target.checked })}
                  className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                />
                <span className="text-white">Show advanced trading options</span>
              </label>

              <label className="flex items-center gap-3">
                <input aria-label="Show advanced trading options"
                  id="auto-refresh"
                  name="autoRefresh"
                  type="checkbox"
                  checked={tradingSettings.autoRefresh}
                  onChange={(e) => setTradingSettings({ ...tradingSettings, autoRefresh: e.target.checked })}
                  className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                />
                <span className="text-white">Auto-refresh trading data</span>
              </label>
            </div>
          </div>
        )}

        {/* Notifications Tab */}
        {activeTab === "notifications" && (
          <div className="space-y-6">
            <h2 className="text-lg font-semibold text-white">Notification Settings</h2>
            
            <div className="space-y-4">
              <h3 className="text-md font-medium text-white">Alert Types</h3>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label className="flex items-center gap-3">
                  <input aria-label="Alert Types"
                    id="email-alerts"
                    name="emailAlerts"
                    type="checkbox"
                    checked={notificationSettings.emailAlerts}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, emailAlerts: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Email alerts</span>
                </label>

                <label className="flex items-center gap-3">
                  <input aria-label="Email alerts"
                    id="push-notifications"
                    name="pushNotifications"
                    type="checkbox"
                    checked={notificationSettings.pushNotifications}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, pushNotifications: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Push notifications</span>
                </label>

                <label className="flex items-center gap-3">
                  <input aria-label="Push notifications"
                    id="trading-alerts"
                    name="tradingAlerts"
                    type="checkbox"
                    checked={notificationSettings.tradingAlerts}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, tradingAlerts: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Trading alerts</span>
                </label>

                <label className="flex items-center gap-3">
                  <input aria-label="Trading alerts"
                    id="risk-alerts"
                    name="riskAlerts"
                    type="checkbox"
                    checked={notificationSettings.riskAlerts}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, riskAlerts: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Risk alerts</span>
                </label>

                <label className="flex items-center gap-3">
                  <input aria-label="Risk alerts"
                    id="system-alerts"
                    name="systemAlerts"
                    type="checkbox"
                    checked={notificationSettings.systemAlerts}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, systemAlerts: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">System alerts</span>
                </label>

                <label className="flex items-center gap-3">
                  <input aria-label="System alerts"
                    id="price-alerts"
                    name="priceAlerts"
                    type="checkbox"
                    checked={notificationSettings.priceAlerts}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, priceAlerts: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Price alerts</span>
                </label>

                <label className="flex items-center gap-3">
                  <input aria-label="Price alerts"
                    id="order-alerts"
                    name="orderAlerts"
                    type="checkbox"
                    checked={notificationSettings.orderAlerts}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, orderAlerts: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Order alerts</span>
                </label>
              </div>
            </div>

            <div className="space-y-4">
              <h3 className="text-md font-medium text-white">Reports</h3>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label className="flex items-center gap-3">
                  <input aria-label="Reports"
                    id="daily-summary"
                    name="dailySummary"
                    type="checkbox"
                    checked={notificationSettings.dailySummary}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, dailySummary: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Daily summary</span>
                </label>

                <label className="flex items-center gap-3">
                  <input aria-label="Daily summary"
                    id="weekly-report"
                    name="weeklyReport"
                    type="checkbox"
                    checked={notificationSettings.weeklyReport}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, weeklyReport: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Weekly report</span>
                </label>
              </div>
            </div>
          </div>
        )}

        {/* Risk Parameters Tab */}
        {activeTab === "risk" && (
          <div className="space-y-6">
            <h2 className="text-lg font-semibold text-white">Risk Management Parameters</h2>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label htmlFor="max-portfolio-risk" className="block text-sm font-medium text-slate-400 mb-2">Max Portfolio Risk (%)</label>
                <input aria-label="Max Portfolio Risk (%)"
                  id="max-portfolio-risk"
                  name="maxPortfolioRisk"
                  type="number"
                  min="1"
                  max="100"
                  defaultValue="25"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  placeholder="25"
                />
              </div>

              <div>
                <label htmlFor="max-position-size-risk" className="block text-sm font-medium text-slate-400 mb-2">Max Position Size (%)</label>
                <input aria-label="Max Position Size (%)"
                  id="max-position-size-risk"
                  name="maxPositionSizeRisk"
                  type="number"
                  min="1"
                  max="50"
                  defaultValue="10"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  placeholder="10"
                />
              </div>

              <div>
                <label htmlFor="stop-loss-default" className="block text-sm font-medium text-slate-400 mb-2">Stop Loss Default (%)</label>
                <input aria-label="Stop Loss Default (%)"
                  id="stop-loss-default"
                  name="stopLossDefault"
                  type="number"
                  min="1"
                  max="20"
                  step="0.5"
                  defaultValue="5"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  placeholder="5"
                />
              </div>

              <div>
                <label htmlFor="max-drawdown" className="block text-sm font-medium text-slate-400 mb-2">Max Drawdown Limit (%)</label>
                <input aria-label="Max Drawdown Limit (%)"
                  id="max-drawdown"
                  name="maxDrawdown"
                  type="number"
                  min="5"
                  max="50"
                  defaultValue="15"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  placeholder="15"
                />
              </div>

              <div>
                <label htmlFor="max-correlation" className="block text-sm font-medium text-slate-400 mb-2">Max Correlation</label>
                <input aria-label="Max Correlation"
                  id="max-correlation"
                  name="maxCorrelation"
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  defaultValue="0.7"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  placeholder="0.7"
                />
              </div>

              <div>
                <label htmlFor="var-confidence" className="block text-sm font-medium text-slate-400 mb-2">VaR Confidence Level (%)</label>
                <input aria-label="VaR Confidence Level (%)"
                  id="var-confidence"
                  name="varConfidence"
                  type="number"
                  min="90"
                  max="99"
                  defaultValue="95"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  placeholder="95"
                />
              </div>
            </div>

            <div className="space-y-4">
              <h3 className="text-md font-medium text-white">Risk Controls</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label className="flex items-center gap-3">
                  <input aria-label="Risk Controls"
                    id="auto-stop-losses"
                    name="autoStopLosses"
                    type="checkbox"
                    defaultChecked
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Enable automatic stop losses</span>
                </label>
                <label className="flex items-center gap-3">
                  <input aria-label="Enable automatic stop losses"
                    id="position-size-limits"
                    name="positionSizeLimits"
                    type="checkbox"
                    defaultChecked
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Enable position size limits</span>
                </label>
                <label className="flex items-center gap-3">
                  <input aria-label="Enable position size limits"
                    id="correlation-checks"
                    name="correlationChecks"
                    type="checkbox"
                    defaultChecked
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Enable correlation checks</span>
                </label>
                <label className="flex items-center gap-3">
                  <input aria-label="Enable correlation checks"
                    id="pause-high-volatility"
                    name="pauseHighVolatility"
                    type="checkbox"
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Pause trading on high volatility</span>
                </label>
              </div>
            </div>
          </div>
        )}

        {/* Agent Config Tab */}
        {activeTab === "agents" && (
          <div className="space-y-6">
            <h2 className="text-lg font-semibold text-white">Agent Configuration</h2>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label htmlFor="max-concurrent-agents" className="block text-sm font-medium text-slate-400 mb-2">Max Concurrent Agents</label>
                <input aria-label="Max Concurrent Agents"
                  id="max-concurrent-agents"
                  name="maxConcurrentAgents"
                  type="number"
                  min="1"
                  max="20"
                  defaultValue="5"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  placeholder="5"
                />
              </div>

              <div>
                <label htmlFor="agent-timeout" className="block text-sm font-medium text-slate-400 mb-2">Agent Timeout (seconds)</label>
                <input aria-label="Agent Timeout (seconds)"
                  id="agent-timeout"
                  name="agentTimeout"
                  type="number"
                  min="10"
                  max="300"
                  defaultValue="60"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  placeholder="60"
                />
              </div>

              <div>
                <label htmlFor="min-confidence" className="block text-sm font-medium text-slate-400 mb-2">Min Confidence Threshold</label>
                <input aria-label="Min Confidence Threshold"
                  id="min-confidence"
                  name="minConfidence"
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  defaultValue="0.6"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  placeholder="0.6"
                />
              </div>

              <div>
                <label htmlFor="consensus-threshold" className="block text-sm font-medium text-slate-400 mb-2">Consensus Threshold</label>
                <input aria-label="Consensus Threshold"
                  id="consensus-threshold"
                  name="consensusThreshold"
                  type="number"
                  min="0.5"
                  max="1"
                  step="0.05"
                  defaultValue="0.7"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  placeholder="0.7"
                />
              </div>

              <div>
                <label htmlFor="max-retries" className="block text-sm font-medium text-slate-400 mb-2">Max Retries</label>
                <input aria-label="Max Retries"
                  id="max-retries"
                  name="maxRetries"
                  type="number"
                  min="1"
                  max="10"
                  defaultValue="3"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  placeholder="3"
                />
              </div>

              <div>
                <label htmlFor="refresh-interval" className="block text-sm font-medium text-slate-400 mb-2">Refresh Interval (seconds)</label>
                <input aria-label="Refresh Interval (seconds)"
                  id="refresh-interval"
                  name="refreshInterval"
                  type="number"
                  min="5"
                  max="60"
                  defaultValue="10"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  placeholder="10"
                />
              </div>
            </div>

            <div className="space-y-4">
              <h3 className="text-md font-medium text-white">Agent Features</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label className="flex items-center gap-3">
                  <input aria-label="Agent Features"
                    id="swarm-coordination"
                    name="swarmCoordination"
                    type="checkbox"
                    defaultChecked
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Enable swarm coordination</span>
                </label>
                <label className="flex items-center gap-3">
                  <input aria-label="Enable swarm coordination"
                    id="decision-explainability"
                    name="decisionExplainability"
                    type="checkbox"
                    defaultChecked
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Enable decision explainability</span>
                </label>
                <label className="flex items-center gap-3">
                  <input aria-label="Enable decision explainability"
                    id="auto-restart-agents"
                    name="autoRestartAgents"
                    type="checkbox"
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Auto-restart failed agents</span>
                </label>
                <label className="flex items-center gap-3">
                  <input aria-label="Auto-restart failed agents"
                    id="log-agent-decisions"
                    name="logAgentDecisions"
                    type="checkbox"
                    defaultChecked
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Log all agent decisions</span>
                </label>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
