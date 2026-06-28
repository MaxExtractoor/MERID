/**
 * Settings View — User Settings
 */

import { Settings as SettingsIcon } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';

const Settings = () => {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <SettingsIcon className="w-8 h-8 text-slate-400" />
        <div>
          <h1 className="text-2xl font-bold text-white">Settings</h1>
          <p className="text-sm text-slate-400">User preferences and configuration</p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Settings View</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-8 text-slate-400">
            <p>Settings view coming soon</p>
            <p className="text-sm mt-2">This view will display user preferences and configuration options.</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default Settings;
