# MERID React Components Guide

## Overview

This guide provides detailed information about all reusable React components in the MERID dashboard, including props, usage examples, and best practices.

## Table of Contents

- [MetricCard](#metriccard)
- [StatusIndicator](#statusindicator)
- [PriceTicker](#priceticker)
- [DataTableEnhanced](#datatableenhanced)
- [Best Practices](#best-practices)
- [Styling](#styling)
- [Accessibility](#accessibility)

---

## MetricCard

A compact KPI card component for displaying metrics with optional delta, trend, and status indicators.

### Props

```typescript
interface MetricCardProps {
  label: string;                    // Metric label
  value: string | number;          // Metric value
  delta?: number;                   // Optional delta value
  trend?: 'up' | 'down' | 'neutral'; // Trend direction
  status?: StatusType;              // Status indicator
  deltaPrecision?: number;         // Decimal precision for delta
  className?: string;              // Additional CSS classes
}
```

### Basic Usage

```typescript
<MetricCard
  label="Total P&L"
  value="$12,345.67"
  status="GOOD"
/>
```

### With Delta and Trend

```typescript
<MetricCard
  label="Daily Return"
  value="2.34%"
  delta={2.34}
  trend="up"
  status="GOOD"
  deltaPrecision={2}
/>
```

### Status Types

```typescript
type StatusType = 'GOOD' | 'WARNING' | 'BAD' | 'ONLINE' | 'DEGRADED' | 'OFFLINE';
```

### Styling

The component automatically applies status-based styling:

- **GOOD/ONLINE**: Green border and accent
- **WARNING/DEGRADED**: Yellow border and accent  
- **BAD/OFFLINE**: Red border and accent

### Custom Styling

```typescript
<MetricCard
  label="Custom Metric"
  value="123"
  className="bg-slate-800 border-slate-700"
/>
```

---

## StatusIndicator

A small inline status indicator with colors, icons, and optional text.

### Props

```typescript
interface StatusIndicatorProps {
  status: StatusType;              // Status type
  text?: string;                   // Optional custom text
  showText?: boolean;              // Whether to show text (default: true)
  tooltip?: string;                 // Tooltip text
  size?: 'small' | 'medium' | 'large'; // Size variant
  variant?: 'dot' | 'pill';        // Visual variant
}
```

### Basic Usage

```typescript
<StatusIndicator status="ONLINE" />
```

### With Custom Text

```typescript
<StatusIndicator
  status="DEGRADED"
  text="Slow Response"
  tooltip="API latency above 500ms"
/>
```

### Size Variants

```typescript
<StatusIndicator status="ONLINE" size="small" />
<StatusIndicator status="ONLINE" size="medium" />
<StatusIndicator status="ONLINE" size="large" />
```

### Variants

```typescript
// Dot variant (default)
<StatusIndicator status="ONLINE" variant="dot" />

// Pill variant
<StatusIndicator status="ONLINE" variant="pill" />
```

---

## PriceTicker

Real-time price display component with change indicators and optional volume/timestamp.

### Props

```typescript
interface PriceTickerData {
  symbol: string;      // Trading symbol
  last: number;         // Last price
  change: number;       // Price change
  changePercent: number; // Percentage change
  volume?: number;      // Trading volume
  timestamp: string;   // Last update timestamp
}

interface PriceTickerProps {
  data: PriceTickerData | null; // Price data
  loading?: boolean;    // Loading state
  error?: string;       // Error message
  showVolume?: boolean; // Show volume
  showTimestamp?: boolean; // Show timestamp
  size?: 'small' | 'medium' | 'large'; // Size variant
}
```

### Basic Usage

```typescript
<PriceTicker
  data={{
    symbol: 'BTC/USD',
    last: 45000,
    change: 500,
    changePercent: 1.12,
    timestamp: '2024-01-30T15:30:00Z',
  }}
/>
```

### With Volume and Timestamp

```typescript
<PriceTicker
  data={priceData}
  showVolume={true}
  showTimestamp={true}
  size="large"
/>
```

### Loading and Error States

```typescript
<PriceTicker
  data={null}
  loading={true}
/>

<PriceTicker
  data={null}
  error="Failed to load price data"
/>
```

### Animation

The component animates price changes with color transitions:

- **Positive changes**: Green flash
- **Negative changes**: Red flash
- **No change**: No animation

---

## DataTableEnhanced

A powerful data table component with sorting, filtering, pagination, and row selection.

### Props

```typescript
interface Column<T> {
  key: keyof T;                    // Data key
  label: string;                   // Column header
  sortable?: boolean;             // Enable sorting
  render?: (value: any, row: T) => React.ReactNode; // Custom renderer
}

interface DataTableEnhancedProps<T> {
  data: T[];                       // Table data
  columns: Column<T>[];            // Column definitions
  loading?: boolean;               // Loading state
  error?: string;                  // Error message
  filterable?: boolean;            // Enable search/filter
  selectable?: boolean;            // Enable row selection
  pageSize?: number;               // Page size
  onRowClick?: (row: T) => void;    // Row click handler
  onSelectionChange?: (selectedRows: T[]) => void; // Selection change handler
  rowClassName?: (row: T) => string; // Dynamic row styling
}
```

### Basic Usage

```typescript
<DataTableEnhanced
  data={positions}
  columns={[
    { key: 'symbol', label: 'Symbol', sortable: true },
    { key: 'size', label: 'Size', sortable: true },
    { key: 'pnl', label: 'P&L', sortable: true },
  ]}
/>
```

### With Custom Rendering

```typescript
<DataTableEnhanced
  data={positions}
  columns={[
    { key: 'symbol', label: 'Symbol', sortable: true },
    { 
      key: 'pnl', 
      label: 'P&L', 
      sortable: true,
      render: (value) => (
        <span className={value >= 0 ? 'text-green-500' : 'text-red-500'}>
          {formatCurrency(value)}
        </span>
      ),
    },
  ]}
/>
```

### With Filtering and Selection

```typescript
<DataTableEnhanced
  data={positions}
  columns={columns}
  filterable={true}
  selectable={true}
  onSelectionChange={(selected) => {
    console.log('Selected rows:', selected);
  }}
/>
```

### With Pagination

```typescript
<DataTableEnhanced
  data={largeDataset}
  columns={columns}
  pageSize={25}
/>
```

### With Row Styling

```typescript
<DataTableEnhanced
  data={positions}
  columns={columns}
  rowClassName={(row) => 
    row.pnl >= 0 ? 'bg-green-50' : 'bg-red-50'
  }
/>
```

### Empty, Loading, and Error States

```typescript
<DataTableEnhanced
  data={[]}
  columns={columns}
  loading={loading}
  error={error ? 'Failed to load data' : undefined}
/>
```

---

## Best Practices

### Performance

1. **Memoize expensive renderers**:
```typescript
const memoizedRenderer = useCallback((value) => {
  return <ExpensiveComponent value={value} />;
}, []);
```

2. **Use pagination for large datasets**:
```typescript
<DataTableEnhanced
  data={largeData}
  pageSize={25}
/>
```

3. **Debounce rapid updates**:
```typescript
const debouncedData = useMemo(() => {
  return debounce(data, 300);
}, [data]);
```

### Data Management

1. **Transform data at the hook level**:
```typescript
const { data } = useApiData('/api/v1/data', {
  transform: (response) => response.items.map(item => ({
    ...item,
    formattedDate: formatDate(item.timestamp),
  })),
});
```

2. **Use stable keys for lists**:
```typescript
{items.map(item => (
  <Row key={item.id} data={item} />
))}
```

### Error Handling

1. **Provide fallback UI**:
```typescript
<DataTableEnhanced
  data={data}
  error={error ? (
    <div className="text-red-500 p-4">
      Failed to load data: {error}
    </div>
  ) : undefined}
/>
```

2. **Handle loading states gracefully**:
```typescript
{loading ? (
  <div className="animate-pulse">
    <div className="h-4 bg-slate-700 rounded mb-2"></div>
    <div className="h-4 bg-slate-700 rounded w-3/4"></div>
  </div>
) : (
  <Component data={data} />
)}
```

---

## Styling

### Tailwind CSS Classes

All components use Tailwind CSS classes and support dark mode:

```typescript
// Dark mode compatible
<MetricCard
  className="bg-slate-900 border-slate-800 text-white"
/>

// Status colors automatically adapt to dark mode
<StatusIndicator status="GOOD" />
```

### Custom Themes

Components use CSS custom properties for theming:

```css
:root {
  --color-success: #10b981;
  --color-warning: #f59e0b;
  --color-error: #ef4444;
}

[data-theme="dark"] {
  --color-success: #34d399;
  --color-warning: #fbbf24;
  --color-error: #f87171;
}
```

---

## Accessibility

### ARIA Attributes

All components include proper ARIA attributes:

```typescript
// MetricCard
<div 
  role="region" 
  aria-label={`Metric: ${label}`}
  aria-describedby={`metric-${label}-value`}
>
  <div id={`metric-${label}-value`}>{value}</div>
</div>

// StatusIndicator
<div 
  role="img" 
  aria-label={`Status: ${status}`}
  title={tooltip}
>
  {/* indicator content */}
</div>
```

### Keyboard Navigation

- **DataTableEnhanced**: Full keyboard navigation with arrow keys and Enter/Space for selection
- **Interactive elements**: All buttons and controls are keyboard accessible
- **Focus management**: Proper focus indicators and trap modals

### Screen Reader Support

- **MetricCard**: Announces label, value, and status
- **PriceTicker**: Announces price, change, and trend
- **DataTableEnhanced**: Announces column headers and row content

### Color Contrast

All components meet WCAG AA contrast requirements:

- **Text**: Minimum 4.5:1 contrast ratio
- **UI elements**: Minimum 3:1 contrast ratio
- **Status indicators**: Both color and icon/text indicators

---

## Migration Guide

### From Basic Components

If you're migrating from basic HTML tables to DataTableEnhanced:

```typescript
// Before
<table>
  <thead>
    <tr>
      <th>Name</th>
      <th>Email</th>
    </tr>
  </thead>
  <tbody>
    {data.map(item => (
      <tr key={item.id}>
        <td>{item.name}</td>
        <td>{item.email}</td>
      </tr>
    ))}
  </tbody>
</table>

// After
<DataTableEnhanced
  data={data}
  columns={[
    { key: 'name', label: 'Name', sortable: true },
    { key: 'email', label: 'Email', sortable: false },
  ]}
  filterable={true}
  selectable={true}
/>
```

### Upgrading Components

When upgrading component versions, check for:

1. **Prop changes**: Review prop interfaces
2. **Default behavior**: Some defaults may have changed
3. **Styling**: CSS classes may have been updated
4. **Accessibility**: New ARIA attributes may be required

---

## Troubleshooting

### Common Issues

1. **DataTable not sorting**: Ensure `sortable: true` is set on the column
2. **Status colors not showing**: Check that status value matches expected enum
3. **PriceTicker not updating**: Verify WebSocket connection and data format
4. **MetricCard delta not appearing**: Ensure both `delta` and `trend` props are provided

### Debug Mode

Enable debug mode to see component internals:

```typescript
// In development
if (process.env.NODE_ENV === 'development') {
  console.log('Component props:', props);
  console.log('Component state:', state);
}
```

### Performance Issues

1. **Large datasets**: Use pagination and virtualization
2. **Frequent re-renders**: Memoize expensive operations
3. **Memory leaks**: Clean up timers and subscriptions in useEffect

---

## Examples Repository

For complete working examples, see the `/examples` directory:

- `/examples/trading-dashboard` - Full trading dashboard
- `/examples/data-tables` - Various table configurations
- `/examples/kpi-cards` - Metric card layouts
- `/examples/real-time-updates` - WebSocket integration
