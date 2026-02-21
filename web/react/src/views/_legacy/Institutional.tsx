import { useState } from 'react';
import { Building2, Users, Shield, FileText, TrendingUp, RefreshCw, AlertCircle, CheckCircle, Clock } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';
import StubBanner from '../components/StubBanner';

interface Account {
  id: string;
  name: string;
  type: 'hedge_fund' | 'family_office' | 'corporate' | 'asset_manager';
  aum: number;
  pnl_ytd: number;
  status: 'active' | 'suspended' | 'pending';
  compliance_status: 'compliant' | 'review' | 'violation';
  last_activity: string;
}

interface ComplianceReport {
  id: string;
  type: 'trade' | 'risk' | 'audit' | 'regulatory';
  title: string;
  status: 'pending' | 'approved' | 'rejected';
  created_at: string;
  reviewed_by?: string;
  notes?: string;
}

interface AuditLog {
  id: string;
  timestamp: string;
  user: string;
  action: string;
  account: string;
  details: string;
  ip_address: string;
}

interface InstitutionalStats {
  total_accounts: number;
  total_aum: number;
  active_accounts: number;
  pending_compliance: number;
  ytd_performance: number;
  total_trades_today: number;
}

interface InstitutionalData {
  accounts: Account[];
  reports: ComplianceReport[];
  audit_logs: AuditLog[];
  stats: InstitutionalStats | null;
  source?: string;
}

export default function Institutional() {
  const [activeTab, setActiveTab] = useState<'accounts' | 'compliance' | 'audit'>('accounts');

  const { data: rawData, loading, error, rawResponse, refetch } = useApiData<InstitutionalData>(
    API_ENDPOINTS.INSTITUTIONAL_OVERVIEW,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.BACKGROUND },
  );
  const accounts = rawData?.accounts ?? [];
  const reports = rawData?.reports ?? [];
  const auditLogs = rawData?.audit_logs ?? [];
  const stats = rawData?.stats ?? null;

  const getAccountTypeLabel = (type: string) => {
    switch (type) {
      case 'hedge_fund': return 'Hedge Fund';
      case 'family_office': return 'Family Office';
      case 'corporate': return 'Corporate';
      case 'asset_manager': return 'Asset Manager';
      default: return type;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'text-green-400 bg-green-500/20';
      case 'suspended': return 'text-red-400 bg-red-500/20';
      case 'pending': return 'text-yellow-400 bg-yellow-500/20';
      default: return 'text-gray-400 bg-gray-500/20';
    }
  };

  const getComplianceColor = (status: string) => {
    switch (status) {
      case 'compliant': return 'text-green-400 bg-green-500/20';
      case 'review': return 'text-yellow-400 bg-yellow-500/20';
      case 'violation': return 'text-red-400 bg-red-500/20';
      default: return 'text-gray-400 bg-gray-500/20';
    }
  };

  const getReportStatusIcon = (status: string) => {
    switch (status) {
      case 'approved': return <CheckCircle className="w-5 h-5 text-green-400" />;
      case 'rejected': return <AlertCircle className="w-5 h-5 text-red-400" />;
      case 'pending': return <Clock className="w-5 h-5 text-yellow-400" />;
      default: return null;
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 animate-spin text-blue-500 mx-auto mb-2" />
          <p className="text-gray-400">Loading institutional dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <StubBanner data={rawResponse} />
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Building2 className="w-8 h-8 text-blue-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Institutional Dashboard</h1>
            <p className="text-sm text-gray-400">Multi-account management and compliance</p>
          </div>
        </div>
        <button type="button"
          onClick={() => refetch()}
          className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg flex items-center gap-2 transition-colors"
         title="fetch Institutional Data">
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-yellow-500" />
          <div>
            <p className="text-yellow-500 font-medium">Data unavailable</p>
            <p className="text-sm text-gray-400">{error?.message ?? 'Unknown error'}</p>
          </div>
        </div>
      )}

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Users className="w-4 h-4 text-blue-400" />
              <p className="text-xs text-gray-400">Total Accounts</p>
            </div>
            <p className="text-2xl font-bold text-white">{stats.total_accounts}</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp className="w-4 h-4 text-green-400" />
              <p className="text-xs text-gray-400">Total AUM</p>
            </div>
            <p className="text-2xl font-bold text-white">${(stats.total_aum / 1000000).toFixed(0)}M</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <CheckCircle className="w-4 h-4 text-emerald-400" />
              <p className="text-xs text-gray-400">Active</p>
            </div>
            <p className="text-2xl font-bold text-emerald-400">{stats.active_accounts}</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Shield className="w-4 h-4 text-yellow-400" />
              <p className="text-xs text-gray-400">Pending Review</p>
            </div>
            <p className="text-2xl font-bold text-yellow-400">{stats.pending_compliance}</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp className="w-4 h-4 text-cyan-400" />
              <p className="text-xs text-gray-400">YTD Performance</p>
            </div>
            <p className="text-2xl font-bold text-cyan-400">+{(stats.ytd_performance * 100).toFixed(1)}%</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <FileText className="w-4 h-4 text-purple-400" />
              <p className="text-xs text-gray-400">Trades Today</p>
            </div>
            <p className="text-2xl font-bold text-white">{stats.total_trades_today}</p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-slate-700">
        {(['accounts', 'compliance', 'audit'] as const).map(tab => (
          <button type="button"
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 font-medium transition-colors ${
              activeTab === tab
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {tab === 'accounts' ? 'Accounts' : tab === 'compliance' ? 'Compliance' : 'Audit Trail'}
          </button>
        ))}
      </div>

      {/* Accounts Tab */}
      {activeTab === 'accounts' && (
        <div className="space-y-4">
          {accounts.map(account => (
            <div key={account.id} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <Building2 className="w-6 h-6 text-blue-400" />
                    <h3 className="text-lg font-bold text-white">{account.name}</h3>
                    <span className={`px-3 py-1 rounded-full text-xs font-medium ${getStatusColor(account.status)}`}>
                      {account.status}
                    </span>
                    <span className={`px-3 py-1 rounded-full text-xs font-medium ${getComplianceColor(account.compliance_status)}`}>
                      {account.compliance_status}
                    </span>
                  </div>
                  <p className="text-sm text-gray-400">{getAccountTypeLabel(account.type)}</p>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div>
                  <p className="text-xs text-gray-400 mb-1">Assets Under Management</p>
                  <p className="text-lg font-bold text-white">${(account.aum / 1000000).toFixed(1)}M</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">YTD P&L</p>
                  <p className="text-lg font-bold text-green-400">+${(account.pnl_ytd / 1000000).toFixed(2)}M</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">YTD Return</p>
                  <p className="text-lg font-bold text-cyan-400">+{((account.pnl_ytd / account.aum) * 100).toFixed(2)}%</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">Last Activity</p>
                  <p className="text-sm text-gray-300">{new Date(account.last_activity).toLocaleString()}</p>
                </div>
              </div>

              <div className="flex gap-2">
                <button type="button" className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm transition-colors" title="View Details">
                  View Details
                </button>
                <button type="button" className="px-4 py-2 bg-slate-600 hover:bg-slate-700 text-white rounded-lg text-sm transition-colors" title="Generate Report">
                  Generate Report
                </button>
                <button type="button" className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-sm transition-colors" title="Manage Permissions">
                  Manage Permissions
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Compliance Tab */}
      {activeTab === 'compliance' && (
        <div className="space-y-4">
          {reports.map(report => (
            <div key={report.id} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    {getReportStatusIcon(report.status)}
                    <h3 className="text-lg font-bold text-white">{report.title}</h3>
                  </div>
                  <div className="flex items-center gap-4 text-sm text-gray-400">
                    <span>Type: {report.type}</span>
                    <span>Created: {new Date(report.created_at).toLocaleDateString()}</span>
                    {report.reviewed_by && <span>Reviewed by: {report.reviewed_by}</span>}
                  </div>
                </div>
                <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                  report.status === 'approved' ? 'text-green-400 bg-green-500/20' :
                  report.status === 'rejected' ? 'text-red-400 bg-red-500/20' :
                  'text-yellow-400 bg-yellow-500/20'
                }`}>
                  {report.status}
                </span>
              </div>

              {report.notes && (
                <div className="mb-4 p-3 bg-slate-900/50 rounded">
                  <p className="text-sm text-gray-300">{report.notes}</p>
                </div>
              )}

              <div className="flex gap-2">
                {report.status === 'pending' && (
                  <>
                    <button type="button" className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm transition-colors" title="Approve">
                      Approve
                    </button>
                    <button type="button" className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm transition-colors" title="Reject">
                      Reject
                    </button>
                  </>
                )}
                <button type="button" className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm transition-colors" title="View Full Report">
                  View Full Report
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Audit Trail Tab */}
      {activeTab === 'audit' && (
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-slate-700">
                <tr>
                  <th className="text-left p-4 text-sm font-medium text-gray-400">Timestamp</th>
                  <th className="text-left p-4 text-sm font-medium text-gray-400">User</th>
                  <th className="text-left p-4 text-sm font-medium text-gray-400">Action</th>
                  <th className="text-left p-4 text-sm font-medium text-gray-400">Account</th>
                  <th className="text-left p-4 text-sm font-medium text-gray-400">Details</th>
                  <th className="text-left p-4 text-sm font-medium text-gray-400">IP Address</th>
                </tr>
              </thead>
              <tbody>
                {auditLogs.map(log => (
                  <tr key={log.id} className="border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors">
                    <td className="p-4 text-sm text-gray-300">{new Date(log.timestamp).toLocaleString()}</td>
                    <td className="p-4 text-sm text-white">{log.user}</td>
                    <td className="p-4">
                      <span className="px-2 py-1 bg-blue-500/20 text-blue-400 text-xs rounded font-medium">
                        {log.action}
                      </span>
                    </td>
                    <td className="p-4 text-sm text-gray-300">{log.account}</td>
                    <td className="p-4 text-sm text-gray-300">{log.details}</td>
                    <td className="p-4 text-sm text-gray-400 font-mono">{log.ip_address}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
