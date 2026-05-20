import { useState } from "react";
import { RefreshCw } from '../ui/icons';
import { useApiData } from "../hooks/useApiData";
import { API_BASE_URL, API_ENDPOINTS, AUTH_TOKEN_KEY, DEFAULTS } from "../config/constants";
import { useLocalStorage } from "../hooks/useLocalStorage";
import ErrorAlert from "../components/ErrorAlert";
import MetricCard from "../components/MetricCard";
import { PreferencesTab } from './Settings/PreferencesTab';
import { TradingSettingsTab } from './Settings/TradingSettingsTab';
import { NotificationSettingsTab } from './Settings/NotificationSettingsTab';
import { RiskTab } from './Settings/RiskTab';
import { AgentsTab } from './Settings/AgentsTab';
import type { UserPreferences, TradingSettings, NotificationSettings, UserProfile } from './Settings/types';

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
        // weeklyReport removed - legacy feature not needed for 15m stack
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
        {activeTab === "preferences" && <PreferencesTab preferences={preferences} setPreferences={setPreferences} />}
        {activeTab === "trading" && <TradingSettingsTab tradingSettings={tradingSettings} setTradingSettings={setTradingSettings} />}
        {activeTab === "notifications" && <NotificationSettingsTab notificationSettings={notificationSettings} setNotificationSettings={setNotificationSettings} />}
        {activeTab === "risk" && <RiskTab />}
        {activeTab === "agents" && <AgentsTab />}
      </div>
    </div>
  );
}
