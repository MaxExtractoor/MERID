/**
 * NotificationSettingsTab - Notification settings configuration
 * 
 * Notification settings section of Settings view.
 * 
 * Tier 4: Settings.tsx Split (953→4 files)
 */

import type { NotificationSettings } from './types';

interface NotificationSettingsTabProps {
  notificationSettings: NotificationSettings;
  setNotificationSettings: (settings: NotificationSettings) => void;
}

export function NotificationSettingsTab({ notificationSettings, setNotificationSettings }: NotificationSettingsTabProps) {
  return (
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
          {/* weeklyReport removed - legacy feature not needed for 15m stack */}
        </div>
      </div>
    </div>
  );
}
