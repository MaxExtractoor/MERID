# MERID React Dashboard

React implementation of the MERID trading dashboard with TypeScript and Tailwind CSS.

## Setup Instructions

```bash
# Create React app with TypeScript
npx create-react-app merid-ui --template typescript
cd merid-ui

# Install dependencies
npm install tailwindcss postcss autoprefixer
npm install @types/node
npm install recharts lucide-react
npm install axios

# Setup Tailwind CSS
npx tailwindcss init -p
```

## Tailwind Configuration

Update `tailwind.config.js`:

```javascript
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'merid': {
          50: '#f0f9ff',
          900: '#0c4a6e',
        }
      }
    },
  },
  plugins: [],
}
```

## Project Structure

```
src/
├── components/
│   ├── Sidebar.tsx
│   ├── TopBar.tsx
│   ├── MetricCard.tsx
│   ├── DataTable.tsx
│   └── ChartContainer.tsx
├── views/
│   ├── Overview.tsx
│   ├── Trading.tsx
│   ├── Agents.tsx
│   ├── Predictions.tsx
│   ├── Risk.tsx
│   └── ApiDashboard.tsx
├── hooks/
│   ├── useApiData.ts
│   ├── useWebSocket.ts
│   └── useTheme.ts
├── types/
│   ├── portfolio.ts
│   ├── trading.ts
│   └── api.ts
└── App.tsx
```

## Running the Application

```bash
npm start
```

The app will be available at http://localhost:3000
