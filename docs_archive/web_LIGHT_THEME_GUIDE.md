# MERID Light Theme Implementation Guide

Complete guide for implementing light theme variations in the MERID trading dashboard with both CSS variables and React approaches.

## **🎨 Theme Strategy Overview**

### **Design Token Layer**
Implement a centralized design token system that supports both dark and light themes with smooth transitions.

### **Theme Toggle Requirements**
- **Persistent Preference**: Save user's theme choice
- **System Preference**: Respect OS-level theme settings
- **Smooth Transitions**: Animate theme changes
- **Accessibility**: High contrast ratios in both themes

---

## **🌓 CSS Variables Implementation**

### **Root Variables Setup**

```css
/* Light theme (default) */
:root {
  /* Background Colors */
  --bg-primary: #ffffff;
  --bg-secondary: #f8fafc;
  --bg-tertiary: #f1f5f9;
  --bg-elevated: #ffffff;
  --bg-hover: #f8fafc;
  
  /* Text Colors */
  --text-primary: #0f172a;
  --text-secondary: #64748b;
  --text-tertiary: #94a3b8;
  --text-muted: #94a3b8;
  
  /* Border Colors */
  --border-primary: #e2e8f0;
  --border-secondary: #cbd5e1;
  --border-tertiary: #f1f5f9;
  
  /* Accent Colors */
  --accent-primary: #2563eb;
  --accent-primary-hover: #1d4ed8;
  --accent-primary-light: #dbeafe;
  
  /* Status Colors */
  --success: #059669;
  --success-light: #d1fae5;
  --danger: #dc2626;
  --danger-light: #fee2e2;
  --warning: #d97706;
  --warning-light: #fef3c7;
  
  /* Chart Colors */
  --chart-line: #2563eb;
  --chart-grid: #e2e8f0;
  --chart-text: #64748b;
  
  /* Shadows */
  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
  --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1);
  
  /* Transitions */
  --transition-fast: 150ms ease;
  --transition-normal: 250ms ease;
  --transition-slow: 350ms ease;
}

/* Dark theme override */
[data-theme="dark"] {
  /* Background Colors */
  --bg-primary: #0a0a0a;
  --bg-secondary: #111111;
  --bg-tertiary: #1a1a1a;
  --bg-elevated: #1a1a1a;
  --bg-hover: #1f1f1f;
  
  /* Text Colors */
  --text-primary: #ffffff;
  --text-secondary: #a0a0a0;
  --text-tertiary: #666666;
  --text-muted: #666666;
  
  /* Border Colors */
  --border-primary: #2a2a2a;
  --border-secondary: #3a3a3a;
  --border-tertiary: #1a1a1a;
  
  /* Accent Colors */
  --accent-primary: #3b82f6;
  --accent-primary-hover: #2563eb;
  --accent-primary-light: #1e3a8a;
  
  /* Status Colors */
  --success: #10b981;
  --success-light: #064e3b;
  --danger: #ef4444;
  --danger-light: #991b1b;
  --warning: #f59e0b;
  --warning-light: #92400e;
  
  /* Chart Colors */
  --chart-line: #3b82f6;
  --chart-grid: #2a2a2a;
  --chart-text: #a0a0a0;
  
  /* Shadows */
  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.25);
  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.3);
  --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.4);
}
```

### **Component Styling with Variables**

```css
/* Base card component */
.card {
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-primary);
  border-radius: 0.75rem;
  padding: 1.5rem;
  box-shadow: var(--shadow-sm);
  transition: all var(--transition-normal);
}

.card:hover {
  border-color: var(--accent-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

/* Text styling */
h1, h2, h3, h4, h5, h6 {
  color: var(--text-primary);
}

.text-secondary {
  color: var(--text-secondary);
}

.text-muted {
  color: var(--text-muted);
}

/* Status indicators */
.status-online {
  color: var(--success);
  background-color: var(--success-light);
}

.status-offline {
  color: var(--danger);
  background-color: var(--danger-light);
}

/* Button styling */
.btn-primary {
  background-color: var(--accent-primary);
  color: white;
  border: 1px solid var(--accent-primary);
  transition: all var(--transition-fast);
}

.btn-primary:hover {
  background-color: var(--accent-primary-hover);
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

/* Form elements */
.form-input {
  background-color: var(--bg-elevated);
  border: 1px solid var(--border-primary);
  color: var(--text-primary);
  transition: all var(--transition-fast);
}

.form-input:focus {
  border-color: var(--accent-primary);
  box-shadow: 0 0 0 3px var(--accent-primary-light);
}

/* Chart styling */
.chart-container {
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-primary);
  border-radius: 0.75rem;
  padding: 1rem;
}

.chart-grid {
  stroke: var(--chart-grid);
}

.chart-text {
  fill: var(--chart-text);
}
```

### **Theme Toggle Implementation**

```css
/* Theme toggle button */
.theme-toggle {
  position: relative;
  width: 60px;
  height: 30px;
  background-color: var(--bg-tertiary);
  border: 2px solid var(--border-primary);
  border-radius: 15px;
  cursor: pointer;
  transition: all var(--transition-normal);
}

.theme-toggle::after {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 20px;
  height: 20px;
  background-color: var(--accent-primary);
  border-radius: 50%;
  transition: all var(--transition-normal);
}

[data-theme="dark"] .theme-toggle::after {
  transform: translateX(30px);
  background-color: var(--warning);
}

/* Smooth theme transitions */
* {
  transition: 
    background-color var(--transition-normal),
    color var(--transition-normal),
    border-color var(--transition-normal);
}

/* Prevent transitions on theme toggle itself */
.theme-toggle,
.theme-toggle *,
.theme-toggle::before,
.theme-toggle::after {
  transition: none !important;
}
```

---

## **⚛️ React + Tailwind Implementation**

### **Tailwind Configuration**

```javascript
// tailwind.config.js
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  darkMode: 'class', // or 'media' for OS preference
  theme: {
    extend: {
      colors: {
        // Light theme colors (default)
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          900: '#1e3a8a',
        },
        // Semantic colors
        success: {
          50: '#d1fae5',
          500: '#059669',
          600: '#047857',
        },
        danger: {
          50: '#fee2e2',
          500: '#dc2626',
          600: '#b91c1c',
        },
        warning: {
          50: '#fef3c7',
          500: '#d97706',
          600: '#b45309',
        },
        // Dark theme specific
        dark: {
          primary: '#0a0a0a',
          secondary: '#111111',
          tertiary: '#1a1a1a',
          border: '#2a2a2a',
          text: {
            primary: '#ffffff',
            secondary: '#a0a0a0',
            tertiary: '#666666',
          }
        }
      },
      boxShadow: {
        'light': '0 1px 2px 0 rgb(0 0 0 / 0.05)',
        'medium': '0 4px 6px -1px rgb(0 0 0 / 0.1)',
        'large': '0 10px 15px -3px rgb(0 0 0 / 0.1)',
      }
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/typography'),
  ],
}
```

### **Theme Provider Hook**

```tsx
// hooks/useTheme.tsx
import React, { createContext, useContext, useState, useEffect } from 'react';

type Theme = 'light' | 'dark' | 'system';

interface ThemeContextType {
  theme: Theme;
  resolvedTheme: 'light' | 'dark';
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    // Check localStorage first
    const saved = localStorage.getItem('theme') as Theme;
    if (saved) return saved;
    
    // Check system preference
    if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'system';
    }
    
    return 'light';
  });

  const resolvedTheme = theme === 'system' 
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : theme;

  useEffect(() => {
    const root = document.documentElement;
    
    if (resolvedTheme === 'dark') {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
    
    localStorage.setItem('theme', theme);
  }, [theme, resolvedTheme]);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    
    const handleChange = () => {
      if (theme === 'system') {
        // Force re-render to update resolvedTheme
        setThemeState('system'); // This will trigger the effect above
      }
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, [theme]);

  const setTheme = (newTheme: Theme) => {
    setThemeState(newTheme);
  };

  const toggleTheme = () => {
    setTheme(resolvedTheme === 'dark' ? 'light' : 'dark');
  };

  return (
    <ThemeContext.Provider value={{ theme, resolvedTheme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
```

### **Theme Toggle Component**

```tsx
// components/ThemeToggle.tsx
import { Sun, Moon } from 'lucide-react';
import { useTheme } from '../hooks/useTheme';

export default function ThemeToggle() {
  const { resolvedTheme, toggleTheme } = useTheme();

  return (
    <button
      onClick={toggleTheme}
      className="p-2 rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
      title={resolvedTheme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      {resolvedTheme === 'dark' ? (
        <Sun className="w-5 h-5 text-yellow-500" />
      ) : (
        <Moon className="w-5 h-5 text-blue-600" />
      )}
    </button>
  );
}
```

### **Responsive Theme-Aware Components**

```tsx
// components/Card.tsx
interface CardProps {
  children: React.ReactNode;
  className?: string;
}

export default function Card({ children, className = '' }: CardProps) {
  return (
    <div className={`
      bg-white dark:bg-gray-900 
      border border-gray-200 dark:border-gray-700 
      rounded-xl 
      p-6 
      shadow-sm dark:shadow-lg
      transition-all duration-200
      hover:shadow-md dark:hover:shadow-xl
      hover:border-blue-300 dark:hover:border-blue-600
      ${className}
    `}>
      {children}
    </div>
  );
}

// components/DataTable.tsx
interface DataTableProps {
  data: any[];
  columns: {
    key: string;
    label: string;
    render?: (value: any) => React.ReactNode;
  }[];
}

export default function DataTable({ data, columns }: DataTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 dark:border-gray-700">
            {columns.map((col) => (
              <th key={col.key} className="text-left py-3 px-4 font-medium text-gray-700 dark:text-gray-300">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, index) => (
            <tr 
              key={index} 
              className="border-b border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            >
              {columns.map((col) => (
                <td key={col.key} className="py-3 px-4 text-gray-900 dark:text-gray-100">
                  {col.render ? col.render(row[col.key]) : row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

### **Chart Theme Adaptation**

```tsx
// components/ChartContainer.tsx
import { useTheme } from '../hooks/useTheme';

interface ChartContainerProps {
  children: React.ReactNode;
}

export default function ChartContainer({ children }: ChartContainerProps) {
  const { resolvedTheme } = useTheme();

  const chartColors = {
    light: {
      grid: '#e2e8f0',
      text: '#64748b',
      line: '#2563eb',
    },
    dark: {
      grid: '#2a2a2a',
      text: '#a0a0a0',
      line: '#3b82f6',
    }
  };

  const colors = resolvedTheme === 'dark' ? chartColors.dark : chartColors.light;

  return (
    <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
      {React.cloneElement(children as React.ReactElement, {
        chartColors: colors
      })}
    </div>
  );
}

// Usage with Recharts
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const CustomChart = ({ data, chartColors }: { data: any[]; chartColors: any }) => (
  <ResponsiveContainer width="100%" height={300}>
    <LineChart data={data}>
      <CartesianGrid strokeDasharray="3 3" stroke={chartColors.grid} />
      <XAxis dataKey="name" stroke={chartColors.text} />
      <YAxis stroke={chartColors.text} />
      <Tooltip 
        contentStyle={{
          backgroundColor: resolvedTheme === 'dark' ? '#1f2937' : '#ffffff',
          border: `1px solid ${chartColors.grid}`,
          borderRadius: '8px',
          color: chartColors.text
        }}
      />
      <Line 
        type="monotone" 
        dataKey="value" 
        stroke={chartColors.line} 
        strokeWidth={2}
        dot={false}
      />
    </LineChart>
  </ResponsiveContainer>
);
```

---

## **🎨 Advanced Theme Features**

### **Theme-Aware Icons**

```tsx
// components/ThemeIcon.tsx
import { useTheme } from '../hooks/useTheme';

interface ThemeIconProps {
  lightIcon: React.ReactNode;
  darkIcon: React.ReactNode;
  className?: string;
}

export default function ThemeIcon({ lightIcon, darkIcon, className = '' }: ThemeIconProps) {
  const { resolvedTheme } = useTheme();

  return (
    <div className={className}>
      {resolvedTheme === 'dark' ? darkIcon : lightIcon}
    </div>
  );
}

// Usage
<ThemeIcon 
  lightIcon={<Sun className="w-5 h-5 text-yellow-500" />}
  darkIcon={<Moon className="w-5 h-5 text-blue-400" />}
/>
```

### **Dynamic Background Gradients**

```css
/* Gradient backgrounds that adapt to theme */
.gradient-bg {
  background: linear-gradient(135deg, var(--bg-primary) 0%, var(--bg-secondary) 100%);
}

.gradient-accent {
  background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-primary-hover) 100%);
}

[data-theme="dark"] .gradient-accent {
  background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-primary-light) 100%);
}
```

### **Theme-Aware Animations**

```css
/* Animations that change based on theme */
@keyframes pulse-glow {
  0%, 100% { box-shadow: 0 0 20px var(--accent-primary-light); }
  50% { box-shadow: 0 0 30px var(--accent-primary); }
}

[data-theme="dark"] @keyframes pulse-glow {
  0%, 100% { box-shadow: 0 0 20px var(--accent-primary); }
  50% { box-shadow: 0 0 40px var(--accent-primary); }
}

.pulse-glow {
  animation: pulse-glow 2s infinite;
}
```

---

## **🔧 Implementation Checklist**

### **✅ CSS Variables Approach**
- [ ] Define all color tokens in CSS variables
- [ ] Create dark theme overrides
- [ ] Implement smooth transitions
- [ ] Test theme switching
- [ ] Ensure accessibility contrast ratios

### **✅ React + Tailwind Approach**
- [ ] Configure Tailwind dark mode
- [ ] Create ThemeProvider context
- [ ] Implement useTheme hook
- [ ] Create theme-aware components
- [ ] Add theme toggle functionality

### **✅ Testing Requirements**
- [ ] Test theme persistence
- [ ] Test system preference detection
- [ ] Verify contrast ratios (WCAG AA)
- [ ] Test all components in both themes
- [ ] Check smooth transitions

### **✅ Performance Considerations**
- [ ] Use CSS transitions efficiently
- [ ] Avoid layout thrashing
- [ ] Optimize theme switching
- [ ] Test on mobile devices
- [ ] Monitor bundle size impact

---

## **🎯 Best Practices**

### **✅ DO:**
- Use semantic color names (success, danger, warning)
- Maintain consistent contrast ratios
- Test with real users
- Consider accessibility from the start
- Use system preference as default
- Implement smooth transitions

### **❌ DON'T:**
- Hard-code colors in components
- Ignore contrast requirements
- Skip accessibility testing
- Create jarring theme transitions
- Forget mobile considerations
- Over-complicate the theme system

---

## **📱 Mobile Theme Considerations**

### **iOS Safari Optimization**

```css
/* Prevent theme switching issues on iOS */
.theme-toggle {
  -webkit-appearance: none;
  appearance: none;
}

/* Ensure smooth transitions on iOS */
* {
  -webkit-transition: background-color 0.3s ease, color 0.3s ease;
  transition: background-color 0.3s ease, color 0.3s ease;
}
```

### **Android Chrome Optimization**

```css
/* Prevent theme flash on Android */
html {
  transition: none;
}

.theme-loaded * {
  transition: background-color 0.3s ease, color 0.3s ease;
}
```

---

## **🚀 Deployment Notes**

### **Bundle Size Optimization**

```javascript
// Dynamic theme loading
const loadTheme = async (theme: 'light' | 'dark') => {
  if (theme === 'dark') {
    await import('./themes/dark.css');
  } else {
    await import('./themes/light.css');
  }
};
```

### **Server-Side Rendering**

```javascript
// SSR theme detection
const getThemeSSR = (req) => {
  const userAgent = req.headers['user-agent'];
  const prefersDark = req.cookies?.theme === 'dark' || 
    req.headers['sec-ch-prefers-color-scheme'] === 'dark';
  
  return prefersDark ? 'dark' : 'light';
};
```

---

This comprehensive guide provides everything needed to implement professional light/dark theme support in the MERID trading dashboard, ensuring excellent user experience across all devices and preferences.
