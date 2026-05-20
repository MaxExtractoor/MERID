# MERID React File Structure Standards

## Overview

This document defines the file structure standards for the MERID React frontend, ensuring consistency, maintainability, and scalability across the codebase.

## Directory Structure

```
web/react/src/
├── components/          # Reusable UI components
│   ├── KalshiLoadingSkeleton.tsx
│   └── [component-name].tsx
├── hooks/              # Custom React hooks
│   ├── useApiData.ts
│   ├── useVisibility.ts
│   ├── usePolling.ts
│   ├── useDebounce.ts
│   ├── useThrottle.ts
│   ├── useKalshiData.ts
│   ├── useOperatorData.ts
│   └── useDebateData.ts
├── ui/                 # UI primitives and design system
│   ├── tokens.ts      # Design tokens (colors, spacing, typography)
│   ├── primitives/    # Consolidated UI primitives
│   │   ├── StatusIndicator.tsx
│   │   ├── Badge.tsx
│   │   ├── DataPanel.tsx
│   │   └── TimeSeriesChart.tsx
│   └── common.tsx     # Common UI components (ProgressBar, Skeleton)
├── views/              # Page-level components
│   ├── Overview.tsx
│   ├── OperatorDashboard.tsx
│   ├── [view-name].tsx
│   └── _legacy/       # Deprecated views (to be deleted)
├── config/             # Configuration files
│   └── constants.ts
├── context/            # React context providers
├── utils/              # Utility functions
├── services/           # API service layer
└── App.tsx            # Application entry point
```

## File Naming Conventions

### Components
- **PascalCase**: `KalshiLoadingSkeleton.tsx`, `StatusIndicator.tsx`
- Use descriptive names that indicate purpose
- Prefix with feature/domain if specific: `KalshiLoadingSkeleton`, `OperatorDashboard`

### Hooks
- **camelCase with `use` prefix**: `useVisibility.ts`, `useKalshiData.ts`
- Consolidated hooks use domain prefix: `useKalshiData`, `useOperatorData`, `useDebateData`
- Utility hooks: `useDebounce`, `useThrottle`, `useVisibility`

### Utilities
- **camelCase**: `validators.ts`, `logger.ts`
- Group related utilities: `kalshiUIConsistency.tsx`

### Configuration
- **camelCase**: `constants.ts`, `debateRiskConfig.ts`

## Component Size Guidelines

### Maximum File Sizes
- **Primitives (ui/primitives/)**: ≤ 300 lines
- **Components (components/)**: ≤ 400 lines
- **Views (views/)**: ≤ 500 lines
- **Hooks (hooks/)**: ≤ 300 lines

### Splitting Criteria
Split files when:
1. Component exceeds size limit
2. Component has multiple distinct responsibilities
3. File contains multiple exports that could be separated
4. Component has complex sub-components that could be extracted

### Example Split Structure
For a large view like `Settings.tsx` (953 lines):
```
views/
├── Settings/
│   ├── Settings.tsx          # Main component (≤ 200 lines)
│   ├── PreferencesTab.tsx    # Preferences section (≤ 200 lines)
│   ├── TradingSettingsTab.tsx # Trading settings (≤ 200 lines)
│   └── NotificationSettingsTab.tsx # Notification settings (≤ 200 lines)
```

## Component Organization

### Single Responsibility
Each component should have one clear responsibility:
- **Primitives**: Single UI element with configurable props
- **Components**: Reusable composition of primitives
- **Views**: Page-level layout and data orchestration

### Import Order
```typescript
// 1. React and external libraries
import React from 'react';
import { useState, useEffect } from 'react';

// 2. Internal imports (grouped by type)
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS } from '../config/constants';
import { StatusIndicator } from '../ui/primitives/StatusIndicator';

// 3. Types and interfaces
interface ComponentProps {
  // ...
}

// 4. Component implementation
export function Component() {
  // ...
}
```

### Export Style
- Use named exports for components: `export function Component() {}`
- Use default exports only for page-level views
- Re-export from index files for cleaner imports

## Design Token Usage

### Required Tokens
Always use design tokens from `ui/tokens.ts`:
- **Colors**: `KALSHI_STATUS_COLORS`, `CHART_COLOR_SCHEMES`
- **Spacing**: `SPACING` tokens
- **Typography**: `TYPOGRAPHY` tokens
- **Sizes**: `SIZE_TOKENS`

### Example
```typescript
import { KALSHI_STATUS_COLORS, SPACING } from '../ui/tokens';

const colors = KALSHI_STATUS_COLORS.success;
const padding = SPACING.md;
```

## Hook Usage Guidelines

### Data Fetching
- Use `useApiData` for REST API calls
- Use `useKalshiData` for Kalshi-specific data
- Use `useOperatorData` for operator dashboard data
- Use `useDebateData` for debate system data

### Performance Hooks
- Use `useVisibility` for tab detection
- Use `usePolling` for intelligent polling with backoff
- Use `useDebounce` for input debouncing
- Use `useThrottle` for rate limiting

### WebSocket
- Use existing WebSocket hooks for real-time data
- Implement fallback to polling for WebSocket failures

## Code Splitting Strategy

### Route-Based Splitting
All views are lazy-loaded using React.lazy:
```typescript
const Overview = lazy(() => import('./views/Overview'));
```

### Component-Level Splitting
- Split large components into smaller sub-components
- Extract reusable logic into custom hooks
- Use dynamic imports for heavy dependencies

## Testing Standards

### File Location
Place test files alongside source files:
```
components/
├── StatusIndicator.tsx
└── __tests__/
    └── StatusIndicator.test.tsx
```

### Test Naming
- Use `.test.tsx` extension for React component tests
- Use `.test.ts` extension for hook/utility tests
- Follow pattern: `[ComponentName].test.tsx`

## Documentation Standards

### Component Documentation
Each component should include:
1. JSDoc comment describing purpose
2. Props interface with documentation
3. Usage example (if complex)
4. Tier information (if part of consolidation plan)

### Example
```typescript
/**
 * StatusIndicator - Unified status indicator component
 * 
 * Consolidates 5 indicator components into one configurable primitive:
 * - StatusIndicator (generic)
 * - DataFreshnessIndicator (with timestamp)
 * - StalenessIndicator (with staleness logic)
 * - OfflineIndicator (offline state)
 * - ConnectionStatusIndicator (connection state)
 * 
 * Tier 2: Indicator Consolidation (5 → 1)
 */
```

## Legacy Code Management

### _legacy Directory
Move deprecated components to `_legacy/` directory before deletion:
```
views/
├── _legacy/
│   ├── OrdersView.tsx
│   └── KalshiRiskScreen.tsx
```

### Deprecation Process
1. Mark component as legacy in comments
2. Move to `_legacy/` directory
3. Update imports to use new consolidated component
4. Delete after verification that no imports remain

## Success Criteria

### File Structure
- ✅ All new components follow naming conventions
- ✅ Component size guidelines respected
- ✅ Proper directory organization maintained
- ✅ Import order standardized

### Code Quality
- ✅ Design tokens used consistently
- ✅ Hooks used appropriately
- ✅ No hardcoded values (use tokens/constants)
- ✅ Proper documentation on all public APIs

### Maintainability
- ✅ Single responsibility principle followed
- ✅ Clear separation of concerns
- ✅ Reusable components extracted
- ✅ Test files co-located with source

## Migration Checklist

When refactoring existing code:
- [ ] Check file size against guidelines
- [ ] Identify split points if too large
- [ ] Update imports to use consolidated components
- [ ] Replace hardcoded values with design tokens
- [ ] Add documentation for public APIs
- [ ] Update or create test files
- [ ] Move deprecated code to `_legacy/`
- [ ] Verify no broken imports
- [ ] Update this document if patterns change
