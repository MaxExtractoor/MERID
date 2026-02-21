# MERID CSS Build Process

## Overview
This project uses Tailwind CSS v3 for styling with a production-ready build process.

## Setup
```bash
npm install
```

## Development
```bash
npm run dev
```
This starts Tailwind in watch mode, automatically rebuilding CSS when files change.

## Production Build
```bash
npm run build
```
This creates a minified production CSS file at `static/css/output.css`.

## Available Scripts
- `npm run dev` - Watch mode for development
- `npm run build` - Production build (minified)
- `npm run clean` - Remove built CSS file
- `npm run rebuild` - Clean and rebuild

## File Structure
- `static/css/input.css` - Source Tailwind CSS with custom components
- `static/css/output.css` - Built production CSS (minified)
- `tailwind.config.js` - Tailwind configuration
- `postcss.config.js` - PostCSS configuration

## Custom Components
The following custom components are available:
- `.glass-effect` - Glass morphism effect
- `.card` - Standard card component
- `.gradient-bg` - MERID gradient background
- `.status-online/offline/warning` - Status indicators
- `.loading` - Pulse animation
- `.metric-tile` - Metric display tiles
- `.health-pill` - Health status pills

## Production Usage
All HTML templates reference the built CSS file:
```html
<link href="/static/css/output.css" rel="stylesheet">
```

## Browser Compatibility
- **Safari 9+**: `-webkit-backdrop-filter` prefix included
- **Modern browsers**: Full CSS Grid and Flexbox support
- **IE 11**: Limited support (consider polyfills if needed)
