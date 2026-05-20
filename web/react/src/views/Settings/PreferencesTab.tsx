/**
 * PreferencesTab - User preferences settings
 * 
 * User preferences section of Settings view.
 * 
 * Tier 4: Settings.tsx Split (953→4 files)
 */

import { useFeatureFlags, setKalshiOnly } from '../../config/featureFlags';
import type { UserPreferences } from './types';

interface PreferencesTabProps {
  preferences: UserPreferences;
  setPreferences: (prefs: UserPreferences) => void;
}

export function PreferencesTab({ preferences, setPreferences }: PreferencesTabProps) {
  const { kalshiOnly } = useFeatureFlags();

  return (
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
  );
}
