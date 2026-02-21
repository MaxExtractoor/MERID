/**
 * WiringStatusPanel — Connection status between MERID pipeline stages.
 *
 * Shows each stage-to-stage link with status indicator, data flow rate,
 * and service health from the system health endpoint.
 */

import React from "react";
import {
  ArrowRight,
  CheckCircle,
  AlertTriangle,
  XCircle,
  HelpCircle,
  Wifi,
  WifiOff,
  Server,
} from "lucide-react";
import type { WiringLink, StageStatus } from "../../hooks/useLoopOrchestration";

/* ── Status config ─────────────────────────────────────────────── */

const LINK_STATUS: Record<StageStatus, { color: string; bg: string; Icon: React.ElementType; label: string }> = {
  healthy: { color: "text-emerald-400", bg: "bg-emerald-900/20", Icon: CheckCircle, label: "Connected" },
  degraded: { color: "text-amber-400", bg: "bg-amber-900/20", Icon: AlertTriangle, label: "Degraded" },
  down: { color: "text-rose-400", bg: "bg-rose-900/20", Icon: XCircle, label: "Disconnected" },
  unknown: { color: "text-slate-400", bg: "bg-slate-800/40", Icon: HelpCircle, label: "Unknown" },
};

const STAGE_LABELS: Record<string, string> = {
  signal: "Signal",
  consensus: "Consensus",
  debate: "Debate",
  risk: "Risk",
  execution: "Execution",
  betting: "Betting",
};

/* ── Props ─────────────────────────────────────────────────────── */

interface WiringStatusPanelProps {
  wiring: WiringLink[];
  services?: Record<string, { status: string; last_check: number }>;
  className?: string;
}

/* ── Component ─────────────────────────────────────────────────── */

export default function WiringStatusPanel({
  wiring,
  services,
  className = "",
}: WiringStatusPanelProps) {
  const serviceEntries = Object.entries(services ?? {});

  return (
    <div className={`space-y-4 ${className}`}>
      {/* Stage-to-stage wiring links */}
      <div>
        <h4 className="text-xs font-semibold text-white mb-2 flex items-center gap-2">
          <Wifi className="w-3.5 h-3.5 text-blue-400" />
          Pipeline Wiring
        </h4>
        <div className="space-y-2">
          {wiring.map((link) => {
            const cfg = LINK_STATUS[link.status] ?? LINK_STATUS.unknown;
            const StatusIcon = cfg.Icon;
            return (
              <div
                key={`${link.from}-${link.to}`}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg border border-slate-700/40 ${cfg.bg}`}
              >
                <StatusIcon className={`w-3.5 h-3.5 ${cfg.color} flex-shrink-0`} />
                <span className="text-xs text-white font-medium min-w-[70px]">
                  {STAGE_LABELS[link.from] ?? link.from}
                </span>
                <ArrowRight className="w-3 h-3 text-slate-600 flex-shrink-0" />
                <span className="text-xs text-white font-medium min-w-[70px]">
                  {STAGE_LABELS[link.to] ?? link.to}
                </span>
                <span className={`text-[10px] ml-auto ${cfg.color}`}>{cfg.label}</span>
                {link.dataFlowRate > 0 && (
                  <span className="text-[10px] text-slate-500 font-mono">
                    {link.dataFlowRate}/s
                  </span>
                )}
              </div>
            );
          })}
          {wiring.length === 0 && (
            <div className="text-center py-4 text-slate-600 text-xs flex items-center justify-center gap-2">
              <WifiOff className="w-4 h-4" />
              No wiring data available
            </div>
          )}
        </div>
      </div>

      {/* Infrastructure services */}
      {serviceEntries.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-white mb-2 flex items-center gap-2">
            <Server className="w-3.5 h-3.5 text-cyan-400" />
            Infrastructure Services
          </h4>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {serviceEntries.map(([name, svc]) => {
              const isHealthy = svc.status === "healthy";
              return (
                <div
                  key={name}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg border ${
                    isHealthy
                      ? "border-emerald-500/20 bg-emerald-900/10"
                      : "border-rose-500/20 bg-rose-900/10"
                  }`}
                >
                  <div
                    className={`w-2 h-2 rounded-full ${
                      isHealthy ? "bg-emerald-400" : "bg-rose-400"
                    }`}
                  />
                  <span className="text-[10px] text-white capitalize">
                    {name.replace(/_/g, " ")}
                  </span>
                  <span
                    className={`text-[10px] ml-auto ${
                      isHealthy ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {svc.status}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
