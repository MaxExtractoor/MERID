import React, { useState } from 'react';
import { Icon, type IconName } from '../ui/icons';
import ReconciliationDashboard from './ReconciliationDashboard';
import ExplainabilityAnalytics from './ExplainabilityAnalytics';
import AuditTrail from './AuditTrail';
import PerformanceDashboard from './PerformanceDashboard';

type TabType = 'reconciliation' | 'decisions' | 'audit' | 'performance';

interface TabConfig {
  id: TabType;
  label: string;
  icon: IconName;
  description: string;
  component: React.ComponentType<any>;
  badge?: number;
  color: string;
}

const UnifiedDashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('reconciliation');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [notifications, setNotifications] = useState<Array<{
    id: string;
    type: 'info' | 'warning' | 'error' | 'success';
    message: string;
    timestamp: number;
    read: boolean;
  }>>([]);
  const [showNotifications, setShowNotifications] = useState(false);

  const tabs: TabConfig[] = [
    {
      id: 'reconciliation',
      label: 'Reconciliation',
      icon: 'refresh',
      description: 'System reconciliation status and controls',
      component: ReconciliationDashboard,
      color: 'text-blue-400'
    },
    {
      id: 'decisions',
      label: 'Decision Analytics',
      icon: 'brain',
      description: 'AI decision tracking and performance metrics',
      component: ExplainabilityAnalytics,
      color: 'text-purple-400'
    },
    {
      id: 'audit',
      label: 'Audit Trail',
      icon: 'fileText',
      description: 'System audit logs and compliance tracking',
      component: AuditTrail,
      color: 'text-green-400'
    },
    {
      id: 'performance',
      label: 'Performance',
      icon: 'activity',
      description: 'System performance monitoring and optimization',
      component: PerformanceDashboard,
      color: 'text-amber-400'
    }
  ];

  const activeTabConfig = tabs.find(tab => tab.id === activeTab);


  const markNotificationAsRead = (id: string) => {
    setNotifications(prev => 
      prev.map(notif => 
        notif.id === id ? { ...notif, read: true } : notif
      )
    );
  };

  const clearNotifications = () => {
    setNotifications([]);
  };

  const getNotificationIcon = (type: string): IconName => {
    switch (type) {
      case 'error': return 'alertCircle';
      case 'warning': return 'alertTriangle';
      case 'success': return 'checkCircle';
      default: return 'info';
    }
  };

  const getNotificationColor = (type: string) => {
    switch (type) {
      case 'error': return 'text-red-400 bg-red-500/20 border-red-500';
      case 'warning': return 'text-amber-400 bg-amber-500/20 border-amber-500';
      case 'success': return 'text-green-400 bg-green-500/20 border-green-500';
      default: return 'text-blue-400 bg-blue-500/20 border-blue-500';
    }
  };

  const unreadCount = notifications.filter(n => !n.read).length;

  return (
    <div className="h-screen bg-slate-900 flex">
      {/* Sidebar */}
      <div className={`${sidebarCollapsed ? 'w-16' : 'w-64'} bg-slate-800 border-r border-slate-700 transition-all duration-300 flex flex-col`}>
        {/* Header */}
        <div className="p-4 border-b border-slate-700">
          <div className="flex items-center justify-between">
            {!sidebarCollapsed && (
              <div className="flex items-center gap-2">
                <Icon name="globe" size={20} className="w-5 h-5 text-blue-400" />
                <span className="text-lg font-bold text-white">MERID</span>
              </div>
            )}
            <button
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              className="p-1 rounded hover:bg-slate-700 transition-colors"
              title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              <Icon name="menu" size={16} className="w-4 h-4 text-slate-400" />
            </button>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-2">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
                activeTab === tab.id
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-400 hover:bg-slate-700 hover:text-white'
              }`}
              title={sidebarCollapsed ? tab.label : undefined}
            >
              <Icon name={tab.icon} size={16} className="w-4 h-4" />
              {!sidebarCollapsed && (
                <>
                  <span className="flex-1 text-left">{tab.label}</span>
                  {tab.badge && tab.badge > 0 && (
                    <span className="bg-red-500 text-white text-xs px-1.5 py-0.5 rounded-full">
                      {tab.badge}
                    </span>
                  )}
                </>
              )}
            </button>
          ))}
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-slate-700">
          {!sidebarCollapsed && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <div className="w-2 h-2 bg-green-400 rounded-full" />
                <span>System Online</span>
              </div>
              <div className="text-xs text-slate-500">
                Last updated: {new Date().toLocaleTimeString()}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <header className="bg-slate-800 border-b border-slate-700 px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              {activeTabConfig && (
                <>
                  <Icon name={activeTabConfig.icon} size={24} className={`w-6 h-6 ${activeTabConfig.color}`} />
                  <div>
                    <h1 className="text-xl font-bold text-white">{activeTabConfig.label}</h1>
                    <p className="text-sm text-slate-400">{activeTabConfig.description}</p>
                  </div>
                </>
              )}
            </div>

            <div className="flex items-center gap-3">
              {/* Auto Refresh Toggle */}
              <button
                onClick={() => setAutoRefresh(!autoRefresh)}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg transition-colors ${
                  autoRefresh 
                    ? 'bg-green-600 text-white' 
                    : 'bg-slate-700 text-slate-400'
                }`}
                title="Toggle auto refresh"
              >
                <Icon name="alert" size={14} className="w-3.5 h-3.5" />
                Auto Refresh
              </button>

              {/* Notifications */}
              <div className="relative">
                <button
                  className="relative p-2 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors"
                  title="Notifications"
                  onClick={() => setShowNotifications(!showNotifications)}
                >
                  <Icon name="bell" size={16} className="w-4 h-4 text-slate-300" />
                  {unreadCount > 0 && (
                    <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs w-5 h-5 rounded-full flex items-center justify-center">
                      {unreadCount}
                    </span>
                  )}
                </button>

                {/* Notifications Dropdown */}
                {showNotifications && notifications.length > 0 && (
                  <div className="absolute right-0 mt-2 w-80 bg-slate-800 border border-slate-700 rounded-lg shadow-lg z-50">
                    <div className="p-3 border-b border-slate-700 flex items-center justify-between">
                      <h3 className="text-sm font-semibold text-white">Notifications</h3>
                      <button
                        onClick={clearNotifications}
                        className="text-xs text-slate-400 hover:text-white transition-colors"
                      >
                        Clear All
                      </button>
                    </div>
                    <div className="max-h-96 overflow-y-auto">
                      {notifications.map((notification) => (
                        <div
                          key={notification.id}
                          className={`p-3 border-b border-slate-700 hover:bg-slate-700 transition-colors cursor-pointer ${
                            !notification.read ? 'bg-slate-700/50' : ''
                          }`}
                          onClick={() => markNotificationAsRead(notification.id)}
                        >
                          <div className="flex items-start gap-2">
                            <Icon 
                              name={getNotificationIcon(notification.type)} 
                              size={14} 
                              className={`w-3.5 h-3.5 mt-0.5 ${getNotificationColor(notification.type).split(' ')[0]}`} 
                            />
                            <div className="flex-1 min-w-0">
                              <p className={`text-sm ${!notification.read ? 'text-white' : 'text-slate-300'}`}>
                                {notification.message}
                              </p>
                              <p className="text-xs text-slate-500 mt-1">
                                {new Date(notification.timestamp).toLocaleString()}
                              </p>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* User Menu */}
              <button className="flex items-center gap-2 p-2 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors">
                <div className="w-6 h-6 bg-blue-500 rounded-full flex items-center justify-center">
                  <span className="text-xs text-white font-bold">O</span>
                </div>
                <span className="text-sm text-white">Operator</span>
                <Icon name="chevronDown" size={12} className="w-3 h-3 text-slate-400" />
              </button>
            </div>
          </div>
        </header>

        {/* Content Area */}
        <main className="flex-1 overflow-hidden">
          <div className="h-full p-6">
            {activeTabConfig && <activeTabConfig.component />}
          </div>
        </main>
      </div>
    </div>
  );
};

export default UnifiedDashboard;
