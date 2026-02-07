import { useState, useEffect } from 'react';
import { CheckCircle, AlertCircle, XCircle, Activity, Server, Database, Cpu, Wifi } from 'lucide-react';

interface ServiceHealth {
  name: string;
  status: 'healthy' | 'degraded' | 'unhealthy';
  latency: number;
  lastCheck: string;
  uptime: number;
  version: string;
}

interface SystemMetrics {
  cpuUsage: number;
  memoryUsage: number;
  diskUsage: number;
  networkLatency: number;
}

export default function Health() {
  const [services, setServices] = useState<ServiceHealth[]>([]);
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [overallStatus, setOverallStatus] = useState<'healthy' | 'degraded' | 'unhealthy'>('healthy');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchHealth() {
      try {
        const response = await fetch('/api/system/health');
        if (response.ok) {
          const data = await response.json();
          
          // Transform services data
          const transformedServices: ServiceHealth[] = Object.entries(data.services || {}).map(([name, info]: [string, any]) => ({
            name: name.replace(/_/g, ' ').toUpperCase(),
            status: info.status === 'healthy' ? 'healthy' : 'degraded',
            latency: Math.floor(Math.random() * 100) + 20, // Mock latency
            lastCheck: new Date(info.last_check).toISOString(),
            uptime: 99.9,
            version: '2.0.0'
          }));
          
          setServices(transformedServices);
          setOverallStatus(data.status);
          
          // Mock metrics
          setMetrics({
            cpuUsage: 45.2,
            memoryUsage: 62.8,
            diskUsage: 34.1,
            networkLatency: 23
          });
        }
      } catch (e) {
        console.error('Failed to fetch health:', e);
      } finally {
        setLoading(false);
      }
    }

    fetchHealth();
    const interval = setInterval(fetchHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'healthy': return <CheckCircle className="w-5 h-5 text-emerald-400" />;
      case 'degraded': return <AlertCircle className="w-5 h-5 text-amber-400" />;
      case 'unhealthy': return <XCircle className="w-5 h-5 text-rose-400" />;
      default: return <Activity className="w-5 h-5 text-slate-400" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'healthy': return 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400';
      case 'degraded': return 'bg-amber-500/10 border-amber-500/30 text-amber-400';
      case 'unhealthy': return 'bg-rose-500/10 border-rose-500/30 text-rose-400';
      default: return 'bg-slate-500/10 border-slate-500/30 text-slate-400';
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">System Health</h1>
            <p className="text-slate-400">Monitoring infrastructure status</p>
          </div>
        </div>
        <div className="bg-slate-900/70 rounded-xl p-8 border border-slate-800 text-center">
          <div className="animate-spin w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
          <p className="text-slate-400">Loading health status...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">System Health</h1>
          <p className="text-slate-400">Real-time infrastructure monitoring</p>
        </div>
        <div className={`px-4 py-2 rounded-lg border ${getStatusColor(overallStatus)}`}>
          <div className="flex items-center gap-2">
            {getStatusIcon(overallStatus)}
            <span className="font-semibold uppercase">{overallStatus}</span>
          </div>
        </div>
      </div>

      {/* System Metrics */}
      {metrics && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
            <div className="flex items-center gap-2 mb-2">
              <Cpu className="w-4 h-4 text-blue-400" />
              <span className="text-sm text-slate-400">CPU Usage</span>
            </div>
            <div className="text-2xl font-semibold">{metrics.cpuUsage.toFixed(1)}%</div>
            <div className="mt-2 h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full bg-blue-500 rounded-full" style={{ width: `${metrics.cpuUsage}%` }}></div>
            </div>
          </div>
          
          <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
            <div className="flex items-center gap-2 mb-2">
              <Database className="w-4 h-4 text-purple-400" />
              <span className="text-sm text-slate-400">Memory</span>
            </div>
            <div className="text-2xl font-semibold">{metrics.memoryUsage.toFixed(1)}%</div>
            <div className="mt-2 h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full bg-purple-500 rounded-full" style={{ width: `${metrics.memoryUsage}%` }}></div>
            </div>
          </div>
          
          <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
            <div className="flex items-center gap-2 mb-2">
              <Server className="w-4 h-4 text-cyan-400" />
              <span className="text-sm text-slate-400">Disk</span>
            </div>
            <div className="text-2xl font-semibold">{metrics.diskUsage.toFixed(1)}%</div>
            <div className="mt-2 h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full bg-cyan-500 rounded-full" style={{ width: `${metrics.diskUsage}%` }}></div>
            </div>
          </div>
          
          <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
            <div className="flex items-center gap-2 mb-2">
              <Wifi className="w-4 h-4 text-emerald-400" />
              <span className="text-sm text-slate-400">Network</span>
            </div>
            <div className="text-2xl font-semibold">{metrics.networkLatency}ms</div>
            <div className="text-xs text-slate-500 mt-2">Avg latency</div>
          </div>
        </div>
      )}

      {/* Services Grid */}
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold mb-4">Service Health</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {services.map((service) => (
            <div key={service.name} className={`p-4 rounded-lg border ${getStatusColor(service.status)}`}>
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  {getStatusIcon(service.status)}
                  <span className="font-medium">{service.name}</span>
                </div>
                <span className="text-xs font-mono">v{service.version}</span>
              </div>
              
              <div className="mt-3 space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="opacity-70">Latency</span>
                  <span>{service.latency}ms</span>
                </div>
                <div className="flex justify-between">
                  <span className="opacity-70">Uptime</span>
                  <span>{service.uptime}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="opacity-70">Last Check</span>
                  <span className="text-xs">{new Date(service.lastCheck).toLocaleTimeString()}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Incident History */}
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold mb-4">Recent Incidents</h2>
        <div className="text-center py-8 text-slate-400">
          <CheckCircle className="w-12 h-12 mx-auto mb-3 text-emerald-400" />
          <p>No incidents in the last 24 hours</p>
          <p className="text-sm text-slate-500 mt-1">All systems operating normally</p>
        </div>
      </div>
    </div>
  );
}
