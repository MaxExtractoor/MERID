/**
 * SignalLayerView — CQI bands, decay indicators, arb scanner, drift warnings.
 *
 * Tabs: CQI Dashboard | Arb Scanner | Signal Features | Decay Config
 * Sidebar: aggregate metrics + freshness indicators
 */

import React, { useState } from "react";
import { DEFAULTS, API_ENDPOINTS } from "../config/constants";
import { logUiError } from '../utils/logger';
import type { DecayConfig, SignalMetricsData, FeatureData, SignalFeaturesResponse } from "../types/api";
import {
  useSignalCQI,
  useSignalArbs,
  useSignalMetrics,
  useDecayConfigs,
  CQIDomain,
  ArbSignal,
} from "../hooks/useSignalLayer";

// ── Helpers ──────────────────────────────────────────────────────────

function bandColor(band: string): string {
  if (band === "good") return "text-emerald-400";
  if (band === "poor") return "text-red-400";
  return "text-amber-400";
}

function bandBg(band: string): string {
  if (band === "good") return "bg-emerald-900/30 border-emerald-700";
  if (band === "poor") return "bg-red-900/30 border-red-700";
  return "bg-amber-900/30 border-amber-700";
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function fmtAge(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

// ── CQI Card ─────────────────────────────────────────────────────────

function CQICard({ domain, cqi }: { domain: string; cqi: CQIDomain }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      data-testid="cqi-card"
      className={`border rounded-lg p-4 cursor-pointer transition-colors ${bandBg(cqi.band)}`}
      onClick={() => setExpanded(!expanded)}
     role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (() => setExpanded(!expanded))(); } }}>
      <div className="flex items-center justify-between mb-2">
        <span className="font-bold text-white capitalize text-lg">{domain}</span>
        <div className="flex items-center gap-2">
          <span className={`text-2xl font-bold ${bandColor(cqi.band)}`}>
            {pct(cqi.quality_index)}
          </span>
          <span className={`text-xs px-2 py-0.5 rounded uppercase font-bold ${bandColor(cqi.band)}`}>
            {cqi.band}
          </span>
        </div>
      </div>

      {/* Component bars */}
      <div className="grid grid-cols-4 gap-2 text-xs">
        {(["brier", "pnl", "drift", "decay"] as const).map((key) => (
          <div key={key}>
            <div className="text-slate-400 capitalize mb-1">{key}</div>
            <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${
                  cqi.components[key] > 0.65 ? "bg-emerald-500" :
                  cqi.components[key] > 0.35 ? "bg-amber-500" : "bg-red-500"
                }`}
                style={{ width: pct(cqi.components[key]) }}
              />
            </div>
            <div className="text-slate-500 mt-0.5">{pct(cqi.components[key])}</div>
          </div>
        ))}
      </div>

      {expanded && (
        <div className="mt-3 pt-3 border-t border-slate-700 text-xs text-slate-400">
          <div>Window: {cqi.window}</div>
          <div>Updated: {fmtAge(Date.now() / 1000 - cqi.timestamp)} ago</div>
          <div className="mt-1 text-slate-500">
            CQI = 0.30×Brier + 0.25×PnL + 0.20×Drift + 0.25×Decay
          </div>
        </div>
      )}
    </div>
  );
}

// ── Arb Signal Row ───────────────────────────────────────────────────

function ArbRow({ signal }: { signal: ArbSignal }) {
  return (
    <div
      data-testid="arb-signal-row"
      className={`flex items-center justify-between p-3 rounded border ${
        signal.is_actionable
          ? "border-emerald-700 bg-emerald-900/20"
          : "border-slate-700 bg-slate-800/50 opacity-60"
      }`}
    >
      <div className="flex items-center gap-3">
        <span className="font-bold text-white">{signal.symbol}</span>
        <span className={`text-xs px-1.5 py-0.5 rounded ${
          signal.arb_type === "pure_arb" ? "bg-emerald-900/50 text-emerald-400" :
          signal.arb_type === "stat_arb" ? "bg-blue-900/50 text-blue-400" :
          "bg-amber-900/50 text-amber-400"
        }`}>
          {signal.arb_type.replace("_", " ").toUpperCase()}
        </span>
        <span className="text-xs text-slate-500">{signal.domain}</span>
      </div>
      <div className="flex items-center gap-4 text-xs">
        <div>
          <span className="text-slate-400">Gross:</span>{" "}
          <span className="text-white font-mono">{signal.gross_edge_bps.toFixed(1)} bps</span>
        </div>
        <div>
          <span className="text-slate-400">Net:</span>{" "}
          <span className={`font-mono ${signal.net_edge_bps > 0 ? "text-emerald-400" : "text-red-400"}`}>
            {signal.net_edge_bps.toFixed(1)} bps
          </span>
        </div>
        <div>
          <span className="text-slate-400">Edge:</span>{" "}
          <span className="text-white font-mono">${signal.edge_usd.toFixed(2)}</span>
        </div>
        <div>
          <span className="text-slate-400">Age:</span>{" "}
          <span className="text-white">{fmtAge(signal.age_seconds)}</span>
        </div>
        <div>
          <span className="text-slate-400">Decay:</span>{" "}
          <span className={signal.decay_weight > 0.5 ? "text-emerald-400" : "text-red-400"}>
            {pct(signal.decay_weight)}
          </span>
        </div>
        <span className={`px-1.5 py-0.5 rounded text-xs ${
          signal.is_actionable ? "bg-emerald-600 text-white" : "bg-slate-700 text-slate-400"
        }`}>
          {signal.is_actionable ? "LIVE" : signal.status.toUpperCase()}
        </span>
      </div>
    </div>
  );
}

// ── Decay Config Table ───────────────────────────────────────────────

function DecayConfigTable({ configs }: { configs: Record<string, DecayConfig> }) {
  const entries = Object.entries(configs);
  if (!entries.length) return <div className="text-slate-500 text-sm" data-testid="decay-empty">No configs loaded</div>;
  return (
    <div data-testid="decay-config-table" className="overflow-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-slate-400 border-b border-slate-700">
            <th className="text-left py-2 px-3">Domain</th>
            <th className="text-right py-2 px-3">τ (half-power)</th>
            <th className="text-right py-2 px-3">Min Weight</th>
            <th className="text-right py-2 px-3">Max Age</th>
            <th className="text-right py-2 px-3">Refresh Boost</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([domain, cfg]) => (
            <tr key={domain} className="border-b border-slate-800 hover:bg-slate-800/50">
              <td className="py-2 px-3 text-white capitalize font-medium">{domain}</td>
              <td className="py-2 px-3 text-right font-mono">{fmtAge(cfg.tau_seconds)}</td>
              <td className="py-2 px-3 text-right font-mono">{pct(cfg.min_weight)}</td>
              <td className="py-2 px-3 text-right font-mono">{fmtAge(cfg.max_age_seconds)}</td>
              <td className="py-2 px-3 text-right font-mono">{cfg.refresh_boost}×</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Metrics Sidebar ──────────────────────────────────────────────────

function MetricsSidebar({ metrics }: { metrics: SignalMetricsData }) {
  if (!metrics) return null;
  const store = metrics.store || {};
  const arb = metrics.arb || {};
  const drift = metrics.drift || {};

  return (
    <div data-testid="signal-metrics" className="w-64 border-l border-slate-700 p-4 space-y-4 text-xs overflow-auto">
      <h3 className="font-bold text-white text-sm">Signal Metrics</h3>

      <div>
        <h4 className="text-slate-400 uppercase tracking-wider mb-1">Store</h4>
        <div className="space-y-1">
          <div className="flex justify-between"><span className="text-slate-500">Features</span><span className="text-white">{store.feature_snapshots ?? 0}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Snapshots</span><span className="text-white">{store.signal_snapshots ?? 0}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Arb Signals</span><span className="text-white">{store.arb_signals_total ?? 0}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">CQI Entries</span><span className="text-white">{store.cqi_entries ?? 0}</span></div>
        </div>
      </div>

      <div>
        <h4 className="text-slate-400 uppercase tracking-wider mb-1">Arb Engine</h4>
        <div className="space-y-1">
          <div className="flex justify-between"><span className="text-slate-500">Total Signals</span><span className="text-white">{arb.total_signals ?? 0}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Active</span><span className="text-emerald-400">{arb.active_signals ?? 0}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Symbols</span><span className="text-white">{arb.symbols_tracked ?? 0}</span></div>
        </div>
      </div>

      <div>
        <h4 className="text-slate-400 uppercase tracking-wider mb-1">Drift</h4>
        <div className="space-y-1">
          <div className="flex justify-between"><span className="text-slate-500">Domains</span><span className="text-white">{(drift.domains_tracked || []).length}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Outcomes</span><span className="text-white">{drift.total_outcomes ?? 0}</span></div>
        </div>
      </div>
    </div>
  );
}

// ── Main View ────────────────────────────────────────────────────────

type Tab = "cqi" | "arbs" | "features" | "decay";

export default function SignalLayerView() {
  const [activeTab, setActiveTab] = useState<Tab>("cqi");
  const [selectedSymbol, setSelectedSymbol] = useState("BTC");

  const { data: cqiData, loading: cqiLoading } = useSignalCQI();
  const { data: arbData, loading: arbLoading } = useSignalArbs();
  const { data: metricsData } = useSignalMetrics();
  const { data: decayConfigs } = useDecayConfigs();

  const cqiDomains = cqiData?.domains || {};
  const arbSignals = arbData?.signals || [];

  const tabs: { key: Tab; label: string }[] = [
    { key: "cqi", label: "📊 CQI Dashboard" },
    { key: "arbs", label: "⚡ Arb Scanner" },
    { key: "features", label: "🔬 Signal Features" },
    { key: "decay", label: "⏱️ Decay Config" },
  ];

  return (
    <div className="flex flex-col h-full bg-slate-900 text-slate-300">
      {/* Header */}
      <div className="border-b border-slate-700 px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold">Signal Layer</h1>
            <span className="text-xs text-slate-500">
              News · Social · Arbs · Drift · Decay
            </span>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <span>{Object.keys(cqiDomains).length} domains</span>
            <span>·</span>
            <span>{arbSignals.length} arb signals</span>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-4">
          {tabs.map((tab) => (
            <button type="button"
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                activeTab === tab.key
                  ? "bg-blue-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:text-white"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto flex">
        <div className="flex-1 p-4 overflow-auto">
          {cqiLoading && arbLoading ? (
            <div data-testid="signal-loading" className="text-slate-500 py-12 text-center">
              Loading signal data...
            </div>
          ) : activeTab === "cqi" ? (
            <div>
              <h2 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-3">
                Consensus Quality Index by Domain
              </h2>
              {Object.keys(cqiDomains).length === 0 ? (
                <div data-testid="cqi-empty" className="text-slate-500 py-8 text-center">
                  No CQI data. Trigger computation via POST /api/v1/signal-layer/compute-cqi.
                </div>
              ) : (
                <div className="grid gap-3" data-testid="cqi-grid">
                  {Object.entries(cqiDomains).map(([domain, cqi]) => (
                    <CQICard key={domain} domain={domain} cqi={cqi} />
                  ))}
                </div>
              )}
            </div>
          ) : activeTab === "arbs" ? (
            <div>
              <h2 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-3">
                Arb / Dislocation Signals
              </h2>
              {arbSignals.length === 0 ? (
                <div data-testid="arb-empty" className="text-slate-500 py-8 text-center">
                  No arb signals detected. Trigger scan via POST /api/v1/signal-layer/scan-arbs.
                </div>
              ) : (
                <div className="space-y-2" data-testid="arb-list">
                  {arbSignals.map((sig) => (
                    <ArbRow key={sig.signal_id} signal={sig} />
                  ))}
                </div>
              )}
            </div>
          ) : activeTab === "features" ? (
            <div>
              <h2 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-3">
                Signal Features
              </h2>
              <div className="flex items-center gap-2 mb-4">
                <span className="text-xs text-slate-500">Symbol:</span>
                {["BTC", "ETH", "SOL", "DOGE", "BONK"].map((sym) => (
                  <button type="button"
                    key={sym}
                    onClick={() => setSelectedSymbol(sym)}
                    className={`px-2 py-1 rounded text-xs ${
                      selectedSymbol === sym ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400"
                    }`}
                  >
                    {sym}
                  </button>
                ))}
              </div>
              <FeaturePanel symbol={selectedSymbol} />
            </div>
          ) : (
            <div>
              <h2 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-3">
                Decay Configuration by Domain
              </h2>
              <DecayConfigTable configs={decayConfigs as Record<string, DecayConfig>} />
            </div>
          )}
        </div>

        {/* Sidebar */}
        <MetricsSidebar metrics={metricsData as SignalMetricsData} />
      </div>
    </div>
  );
}

// ── Feature Panel (sub-component) ────────────────────────────────────

function FeaturePanel({ symbol }: { symbol: string }) {
  const { data, loading } = useSignalFeatures(symbol);

  if (loading || !data) return <div className="text-slate-500">Loading features for {symbol}...</div>;

  const sections = [
    { key: "news", label: "📰 News", data: data.news },
    { key: "social", label: "💬 Social", data: data.social },
    { key: "onchain", label: "⛓️ On-Chain", data: data.onchain },
  ];

  return (
    <div className="space-y-4" data-testid="feature-panel">
      {sections.map(({ key, label, data: sectionData }) => {
        if (!sectionData) return null;
        const features = sectionData.features || {};
        return (
          <div key={key} className="border border-slate-700 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="font-bold text-white text-sm">{label}</span>
              <div className="flex items-center gap-2 text-xs">
                <span className="text-slate-400">Freshness:</span>
                <span className={
                  sectionData.avg_freshness > 0.65 ? "text-emerald-400" :
                  sectionData.avg_freshness > 0.35 ? "text-amber-400" : "text-red-400"
                }>
                  {pct(sectionData.avg_freshness)}
                </span>
                <span className="text-slate-600">|</span>
                <span className="text-slate-400">Source: {sectionData.source}</span>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {Object.entries(features).map(([fname, fdata]: [string, FeatureData]) => (
                <div key={fname} className="flex items-center justify-between bg-slate-800/50 rounded px-2 py-1">
                  <span className="text-slate-400 truncate mr-2">{fname}</span>
                  <div className="flex items-center gap-1">
                    <span className="text-white font-mono">
                      {typeof fdata.value === "number" ? fdata.value.toFixed(4) : fdata.value}
                    </span>
                    <span className={`text-[10px] ${
                      fdata.decay_weight > 0.65 ? "text-emerald-500" :
                      fdata.decay_weight > 0.35 ? "text-amber-500" : "text-red-500"
                    }`}>
                      ({pct(fdata.decay_weight)})
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function useSignalFeatures(symbol: string) {
  const [data, setData] = React.useState<SignalFeaturesResponse | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch(API_ENDPOINTS.SIGNAL_LAYER_FEATURES(symbol));
        if (res.ok) setData(await res.json());
      } catch (err) { logUiError('SignalLayerView', 'Feature fetch failed', err); } finally {
        setLoading(false);
      }
    };
    fetchData();
    const id = setInterval(fetchData, DEFAULTS.POLLING_INTERVALS.SLOW);
    return () => clearInterval(id);
  }, [symbol]);

  return { data, loading };
}
