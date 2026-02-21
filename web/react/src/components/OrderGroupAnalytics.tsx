/**
 * OrderGroupAnalytics.tsx — Order group utilization history chart.
 *
 * Provides:
 * - Line chart showing utilization % over time
 * - Multiple groups comparison
 * - Trigger events marking
 * - Interactive tooltips
 *
 * Usage:
 *   <OrderGroupAnalytics groupIds={['og-1', 'og-2']} />
 */

import React, { useMemo } from 'react';
import { TrendingUp, AlertCircle } from 'lucide-react';

interface UtilizationPoint {
  timestamp: string;
  utilization_pct: number;
  contracts_used: number;
  contracts_limit: number;
}

interface GroupHistory {
  order_group_id: string;
  name: string;
  status: 'active' | 'triggered' | 'canceled' | 'pending';
  history: UtilizationPoint[];
  trigger_events: Array<{
    timestamp: string;
    matched_contracts: number;
  }>;
}

interface OrderGroupAnalyticsProps {
  /** Group histories to display */
  histories: GroupHistory[];
  /** Time range in hours */
  hours?: number;
  /** Show trigger event markers */
  showTriggers?: boolean;
  /** Height of chart in pixels */
  height?: number;
}

/**
 * Order Group Utilization Analytics Chart
 *
 * Visualizes order group utilization over time with trigger events.
 */
export function OrderGroupAnalytics({
  histories,
  hours = 24,
  showTriggers = true,
  height = 200,
}: OrderGroupAnalyticsProps): JSX.Element {
  // Colors for different groups
  const groupColors = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899'];

  // Calculate chart dimensions
  const padding = { top: 20, right: 20, bottom: 30, left: 40 };
  const chartWidth = 600;
  const chartHeight = height;
  const innerWidth = chartWidth - padding.left - padding.right;
  const innerHeight = chartHeight - padding.top - padding.bottom;

  // Get time range
  const now = useMemo(() => new Date(), []);
  const startTime = useMemo(() => new Date(now.getTime() - hours * 60 * 60 * 1000), [now, hours]);

  // Filter and normalize data
  const normalizedData = useMemo(() => {
    return histories.map((group, idx) => {
      const filtered = group.history.filter(
        p => new Date(p.timestamp) >= startTime
      );
      return {
        ...group,
        color: groupColors[idx % groupColors.length],
        filtered,
      };
    });
  }, [histories, startTime, hours, groupColors]);

  // Calculate scales
  const maxUtilization = useMemo(() => {
    let max = 100;
    normalizedData.forEach(g => {
      g.filtered.forEach(p => {
        max = Math.max(max, p.utilization_pct);
      });
    });
    return Math.min(max + 10, 100);
  }, [normalizedData]);

  // Generate x-axis labels
  const timeLabels = useMemo(() => {
    const labels = [];
    const step = hours <= 6 ? 1 : hours <= 12 ? 2 : 4;
    const currentNow = new Date();
    for (let i = 0; i <= hours; i += step) {
      const t = new Date(currentNow.getTime() - (hours - i) * 60 * 60 * 1000);
      labels.push({
        offset: (i / hours) * innerWidth,
        label: t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      });
    }
    return labels;
  }, [hours, innerWidth]);

  // Generate y-axis labels
  const yLabels = useMemo(() => {
    const labels = [];
    for (let i = 0; i <= 5; i++) {
      labels.push({
        offset: innerHeight - (i / 5) * innerHeight,
        value: Math.round((maxUtilization / 5) * i),
      });
    }
    return labels;
  }, [innerHeight, maxUtilization]);

  // Generate path for each group
  const paths = useMemo(() => {
    return normalizedData.map(group => {
      if (group.filtered.length < 2) return null;

      const points = group.filtered.map(p => {
        const x =
          ((new Date(p.timestamp).getTime() - startTime.getTime()) /
            (hours * 60 * 60 * 1000)) *
          innerWidth;
        const y =
          innerHeight - (p.utilization_pct / maxUtilization) * innerHeight;
        return `${x},${y}`;
      });

      return {
        ...group,
        d: `M ${points.join(' L ')}`,
      };
    });
  }, [normalizedData, startTime, hours, innerWidth, innerHeight, maxUtilization]);

  // Trigger markers
  const triggerMarkers = useMemo(() => {
    if (!showTriggers) return [];

    const markers: Array<{
      x: number;
      y: number;
      group: GroupHistory;
      event: { timestamp: string; matched_contracts: number };
    }> = [];

    normalizedData.forEach(group => {
      group.trigger_events.forEach(event => {
        const eventTime = new Date(event.timestamp);
        if (eventTime >= startTime) {
          const x =
            ((eventTime.getTime() - startTime.getTime()) /
              (hours * 60 * 60 * 1000)) *
            innerWidth;
          const y = innerHeight; // At bottom
          markers.push({ x, y, group, event });
        }
      });
    });

    return markers;
  }, [normalizedData, startTime, hours, innerWidth, innerHeight, showTriggers]);

  if (histories.length === 0) {
    return (
      <div style={styles.emptyState}>
        <AlertCircle style={styles.emptyIcon} />
        <p>No utilization data available</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <TrendingUp style={styles.headerIcon} />
          <h3 style={styles.title}>Order Group Utilization</h3>
        </div>
        <span style={styles.subtitle}>{hours}h history</span>
      </div>

      {/* Legend */}
      <div style={styles.legend}>
        {normalizedData.map(group => (
          <div key={group.order_group_id} style={styles.legendItem}>
            <span
              style={{
                ...styles.legendColor,
                backgroundColor: group.color,
              }}
            />
            <span style={styles.legendLabel}>
              {group.name || group.order_group_id}
            </span>
            <span
              style={{
                ...styles.legendStatus,
                color: getStatusColor(group.status),
              }}
            >
              {group.status}
            </span>
          </div>
        ))}
      </div>

      {/* Chart */}
      <svg
        width="100%"
        height={chartHeight}
        viewBox={`0 0 ${chartWidth} ${chartHeight}`}
        style={styles.chart}
      >
        <g transform={`translate(${padding.left}, ${padding.top})`}>
          {/* Grid lines */}
          {yLabels.map((label, i) => (
            <line
              key={i}
              x1={0}
              x2={innerWidth}
              y1={label.offset}
              y2={label.offset}
              stroke="#e5e7eb"
              strokeDasharray="4,4"
            />
          ))}

          {/* Y-axis labels */}
          {yLabels.map((label, i) => (
            <text
              key={i}
              x={-8}
              y={label.offset + 4}
              textAnchor="end"
              fontSize={10}
              fill="#6b7280"
            >
              {label.value}%
            </text>
          ))}

          {/* X-axis labels */}
          {timeLabels.map((label, i) => (
            <text
              key={i}
              x={label.offset}
              y={innerHeight + 15}
              textAnchor="middle"
              fontSize={10}
              fill="#6b7280"
            >
              {label.label}
            </text>
          ))}

          {/* Lines */}
          {paths.map((path, idx) =>
            path ? (
              <path
                key={idx}
                d={path.d}
                fill="none"
                stroke={path.color}
                strokeWidth={2}
              />
            ) : null
          )}

          {/* Trigger markers */}
          {triggerMarkers.map((marker, idx) => (
            <g key={idx}>
              <line
                x1={marker.x}
                x2={marker.x}
                y1={0}
                y2={innerHeight}
                stroke="#ef4444"
                strokeDasharray="2,2"
                opacity={0.5}
              />
              <circle
                cx={marker.x}
                cy={marker.y}
                r={4}
                fill="#ef4444"
              />
              <text
                x={marker.x}
                y={marker.y + 12}
                textAnchor="middle"
                fontSize={8}
                fill="#ef4444"
              >
                Trigger
              </text>
            </g>
          ))}

          {/* 90% warning line */}
          <line
            x1={0}
            x2={innerWidth}
            y1={innerHeight - (90 / maxUtilization) * innerHeight}
            y2={innerHeight - (90 / maxUtilization) * innerHeight}
            stroke="#f59e0b"
            strokeDasharray="8,4"
          />
          <text
            x={innerWidth}
            y={innerHeight - (90 / maxUtilization) * innerHeight - 4}
            textAnchor="end"
            fontSize={9}
            fill="#f59e0b"
          >
            90% warning
          </text>

          {/* 100% limit line */}
          <line
            x1={0}
            x2={innerWidth}
            y1={innerHeight - (100 / maxUtilization) * innerHeight}
            y2={innerHeight - (100 / maxUtilization) * innerHeight}
            stroke="#ef4444"
            strokeDasharray="8,4"
          />
          <text
            x={innerWidth}
            y={innerHeight - (100 / maxUtilization) * innerHeight - 4}
            textAnchor="end"
            fontSize={9}
            fill="#ef4444"
          >
            100% limit
          </text>
        </g>
      </svg>

      {/* Stats */}
      <div style={styles.stats}>
        {normalizedData.map(group => {
          const latest = group.filtered[group.filtered.length - 1];
          const peak = Math.max(...group.filtered.map(p => p.utilization_pct));
          return (
            <div key={group.order_group_id} style={styles.statCard}>
              <div style={styles.statHeader}>
                <span style={styles.statName}>
                  {group.name || group.order_group_id}
                </span>
                <span
                  style={{
                    ...styles.statValue,
                    color: group.color,
                  }}
                >
                  {latest?.utilization_pct ?? 0}%
                </span>
              </div>
              <div style={styles.statDetails}>
                <span>Peak: {peak.toFixed(1)}%</span>
                <span>
                  {latest?.contracts_used ?? 0} / {latest?.contracts_limit ?? 0}{' '}
                  contracts
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function getStatusColor(status: string): string {
  switch (status) {
    case 'active':
      return '#22c55e';
    case 'triggered':
      return '#ef4444';
    case 'canceled':
      return '#6b7280';
    case 'pending':
      return '#f59e0b';
    default:
      return '#9ca3af';
  }
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    backgroundColor: '#ffffff',
    borderRadius: '8px',
    padding: '16px',
    boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)',
    fontFamily: 'system-ui, -apple-system, sans-serif',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '12px',
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  headerIcon: {
    width: 20,
    height: 20,
    color: '#3b82f6',
  },
  title: {
    margin: 0,
    fontSize: '16px',
    fontWeight: 600,
    color: '#111827',
  },
  subtitle: {
    fontSize: '12px',
    color: '#6b7280',
  },
  legend: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '12px',
    marginBottom: '16px',
  },
  legendItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    fontSize: '12px',
  },
  legendColor: {
    width: 12,
    height: 12,
    borderRadius: '50%',
  },
  legendLabel: {
    color: '#374151',
  },
  legendStatus: {
    fontSize: '10px',
    textTransform: 'uppercase',
    fontWeight: 600,
  },
  chart: {
    width: '100%',
  },
  stats: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
    gap: '12px',
    marginTop: '16px',
    paddingTop: '16px',
    borderTop: '1px solid #e5e7eb',
  },
  statCard: {
    padding: '10px',
    backgroundColor: '#f9fafb',
    borderRadius: '6px',
  },
  statHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '4px',
  },
  statName: {
    fontSize: '12px',
    fontWeight: 500,
    color: '#374151',
  },
  statValue: {
    fontSize: '14px',
    fontWeight: 700,
  },
  statDetails: {
    display: 'flex',
    flexDirection: 'column',
    gap: '2px',
    fontSize: '11px',
    color: '#6b7280',
  },
  emptyState: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: '32px',
    color: '#6b7280',
    fontSize: '14px',
  },
  emptyIcon: {
    width: 24,
    height: 24,
    marginBottom: '8px',
  },
};

export default OrderGroupAnalytics;
