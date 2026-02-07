import { useState } from "react";
import { useApiData } from "../hooks/useApiData";
import { useLocalStorage } from "../hooks/useLocalStorage";
import { validateLeverage } from "../utils/validators";
import MetricCard from "../components/MetricCard";

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

export default function Settings() {
  const [activeTab, setActiveTab] = useState<"preferences" | "trading" | "notifications" | "risk" | "agents">("preferences");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

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
  const { data: userData } = useApiData<any>("/api/v1/user/profile");

  const handleSave = async () => {
    setSaving(true);
    setSaveMessage(null);

    try {
      // Save to API
      const response = await fetch("/api/v1/user/settings", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("merid-access")}`,
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
      setTimeout(() => setSaveMessage(null), 3000);
    } catch (error) {
      setSaveMessage("Failed to save settings");
      setTimeout(() => setSaveMessage(null), 3000);
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
          <button
            onClick={handleReset}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg font-medium transition-colors"
          >
            Reset to Defaults
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors disabled:opacity-50"
          >
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
          <button
            onClick={() => setActiveTab("preferences")}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === "preferences"
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            User Preferences
          </button>
          <button
            onClick={() => setActiveTab("trading")}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === "trading"
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            Trading Settings
          </button>
          <button
            onClick={() => setActiveTab("notifications")}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === "notifications"
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            Notifications
          </button>
          <button
            onClick={() => setActiveTab("risk")}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === "risk"
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            Risk Parameters
          </button>
          <button
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
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label className="block text-sm font-medium text-slate-400 mb-2">Theme</label>
                <select
                  title="Select theme"
                  value={preferences.theme}
                  onChange={(e) => setPreferences({ ...preferences, theme: e.target.value as any })}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="light">Light</option>
                  <option value="dark">Dark</option>
                  <option value="auto">Auto</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-400 mb-2">Language</label>
                <select
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
                <label className="block text-sm font-medium text-slate-400 mb-2">Timezone</label>
                <select
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
                <label className="block text-sm font-medium text-slate-400 mb-2">Date Format</label>
                <select
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
                <label className="block text-sm font-medium text-slate-400 mb-2">Number Format</label>
                <select
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
                <label className="block text-sm font-medium text-slate-400 mb-2">Default Page</label>
                <select
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
                <input
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
                <input
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
                <input
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
                <input
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
                <input
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
                <label className="block text-sm font-medium text-slate-400 mb-2">Auto Refresh Interval (ms)</label>
                <select
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
                <input
                  type="checkbox"
                  checked={tradingSettings.confirmOrders}
                  onChange={(e) => setTradingSettings({ ...tradingSettings, confirmOrders: e.target.checked })}
                  className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                />
                <span className="text-white">Confirm orders before execution</span>
              </label>

              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={tradingSettings.showAdvancedOptions}
                  onChange={(e) => setTradingSettings({ ...tradingSettings, showAdvancedOptions: e.target.checked })}
                  className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                />
                <span className="text-white">Show advanced trading options</span>
              </label>

              <label className="flex items-center gap-3">
                <input
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
                  <input
                    type="checkbox"
                    checked={notificationSettings.emailAlerts}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, emailAlerts: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Email alerts</span>
                </label>

                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={notificationSettings.pushNotifications}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, pushNotifications: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Push notifications</span>
                </label>

                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={notificationSettings.tradingAlerts}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, tradingAlerts: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Trading alerts</span>
                </label>

                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={notificationSettings.riskAlerts}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, riskAlerts: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Risk alerts</span>
                </label>

                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={notificationSettings.systemAlerts}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, systemAlerts: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">System alerts</span>
                </label>

                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={notificationSettings.priceAlerts}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, priceAlerts: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Price alerts</span>
                </label>

                <label className="flex items-center gap-3">
                  <input
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
                  <input
                    type="checkbox"
                    checked={notificationSettings.dailySummary}
                    onChange={(e) => setNotificationSettings({ ...notificationSettings, dailySummary: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Daily summary</span>
                </label>

                <label className="flex items-center gap-3">
                  <input
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
                <input
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
                <input
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
                <input
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
                <input
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
                <input
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
                <input
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
                  <input
                    type="checkbox"
                    defaultChecked
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Enable automatic stop losses</span>
                </label>
                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    defaultChecked
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Enable position size limits</span>
                </label>
                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    defaultChecked
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Enable correlation checks</span>
                </label>
                <label className="flex items-center gap-3">
                  <input
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
                <input
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
                <input
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
                <input
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
                <input
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
                <input
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
                <input
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
                  <input
                    type="checkbox"
                    defaultChecked
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Enable swarm coordination</span>
                </label>
                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    defaultChecked
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Enable decision explainability</span>
                </label>
                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-white">Auto-restart failed agents</span>
                </label>
                <label className="flex items-center gap-3">
                  <input
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
