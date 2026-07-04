/**
 * Settings View — User Settings
 */

import { useState } from 'react';
import { Settings as SettingsIcon, Users, Shield, Sliders, Bell, User } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Button } from '../ui';
import { API_BASE_URL } from '../config/constants';

const Settings = () => {
  const [activeTab, setActiveTab] = useState<'agents' | 'trading' | 'risk' | 'preferences' | 'notifications'>('agents');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      // Save settings based on active tab
      const endpoint = {
        agents: '/api/v1/agents/config',
        trading: '/api/v1/trading/config',
        risk: '/api/v1/risk/config',
        preferences: '/api/v1/user/preferences',
        notifications: '/api/v1/notifications/config',
      }[activeTab];

      await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
    } catch (err) {
      console.error('Failed to save settings:', err);
    } finally {
      setSaving(false);
    }
  };

  const tabs = [
    { id: 'agents' as const, label: 'Agents', icon: Users },
    { id: 'trading' as const, label: 'Trading', icon: Shield },
    { id: 'risk' as const, label: 'Risk', icon: Sliders },
    { id: 'preferences' as const, label: 'Preferences', icon: User },
    { id: 'notifications' as const, label: 'Notifications', icon: Bell },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <SettingsIcon className="w-8 h-8 text-slate-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Settings</h1>
            <p className="text-sm text-slate-400">User preferences and configuration</p>
          </div>
        </div>
        <Button onClick={handleSave} disabled={saving}>
          {saving ? 'Saving...' : 'Save Changes'}
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium ${
                activeTab === tab.id
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <Icon className="w-4 h-4" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab Content */}
      <Card>
        <CardHeader>
          <CardTitle className="capitalize">{activeTab} Settings</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-8 text-slate-400">
            <p className="text-sm">
              {activeTab} settings are wired to {`/api/v1/${activeTab}/config`}
            </p>
            <p className="text-sm mt-2">Configure {activeTab} settings here.</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default Settings;
