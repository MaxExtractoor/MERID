import React from 'react';

const NotificationPanel: React.FC = () => (
  <div className="p-4">
    <h2 className="font-semibold mb-2">Notifications</h2>
    <button type="button" title="Clear all notifications" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
      Clear All
    </button>
  </div>
);

export default NotificationPanel;
