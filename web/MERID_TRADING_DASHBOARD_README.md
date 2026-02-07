# MERID Production-Grade Trading Dashboard

A comprehensive, enterprise-grade web UI for multi-venue algorithmic trading and portfolio management platform. Built with modern web technologies and designed for professional trading environments.

## 🎯 Overview

The MERID Trading Dashboard is a dark-themed, professional trading interface inspired by modern crypto trading terminals and quantitative research tools. It provides real-time market intelligence, advanced order management, agent monitoring, and comprehensive risk analytics.

## 🚀 Key Features

### **Core Dashboard Layout**
- **3-Column Responsive Design**: Optimized for 1920x1080 down to laptop widths
- **Sticky Top Command Bar**: Global search, environment toggle, notifications
- **Vertical Sidebar Navigation**: Collapsible sections with icons and labels
- **Real-time Updates**: Live data feeds with smooth animations

### **Main Screens**

#### **1. Overview Dashboard**
- Portfolio snapshot with equity, P&L, and sparkline charts
- Key metrics cards (win rate, Sharpe ratio, max drawdown, etc.)
- Live watchlist with price tick animations
- Multi-tab chart area (Price, P&L, Exposure, Predictions)

#### **2. Live Trading Screen**
- Advanced order ticket with market/limit/bracket orders
- Real-time position management with risk indicators
- Open orders and recent fills tracking
- Venue-specific order routing

#### **3. Bots/Agents Screen**
- Agent status monitoring with confidence scores
- Performance tracking and P&L contribution
- Detailed agent theses and recent trades
- Interactive confidence vs outcome charts

#### **4. Prediction Markets Screen**
- Polymarket and Kalshi integration
- Pinned markets with probability sparklines
- Real-time probability tracking
- Position management and P&L tracking

#### **5. Risk & Health Screen**
- Comprehensive system health monitoring
- Real-time risk indicators and alerts
- Margin and position limit tracking
- Multi-metric risk visualization

#### **6. API Dashboard Screen**
- Complete API status monitoring
- Performance metrics and error tracking
- Configuration completeness tracking
- Category-based health visualization

## 🛠️ Technology Stack

### **Frontend Technologies**
- **HTML5**: Semantic markup structure
- **Tailwind CSS**: Utility-first styling framework
- **Chart.js**: Interactive data visualization
- **Lucide Icons**: Professional icon library
- **Vanilla JavaScript**: No framework dependencies

### **Design System**
- **Dark Theme**: High-contrast professional interface
- **Color Coding**: Green (positive), Red (negative), Amber (warnings)
- **Typography**: Inter font family for optimal readability
- **Animations**: Smooth micro-interactions and transitions
- **Responsive**: Mobile-first adaptive design

## 📁 File Structure

```
web/templates/
├── merid_trading_dashboard.html          # Main dashboard
├── components/
│   ├── trading_screen.html               # Live trading interface
│   ├── bots_screen.html                  # Agent management
│   ├── prediction_markets_screen.html    # Prediction markets
│   ├── risk_screen.html                  # Risk & health monitoring
│   └── api_dashboard_screen.html         # API status dashboard
└── static/css/
    └── output.css                        # Compiled Tailwind CSS
```

## 🎨 UI Components

### **Reusable Elements**

#### **Metric Cards**
```html
<div class="metric-card p-4">
    <div class="text-sm text-gray-400 mb-1">Metric Name</div>
    <div class="text-2xl font-bold">Value</div>
    <div class="text-xs text-gray-400">Description</div>
</div>
```

#### **Status Badges**
```html
<span class="status-badge status-live">LIVE</span>
<span class="status-badge status-paper">PAPER</span>
<span class="status-badge status-dev">DEV</span>
```

#### **Risk Indicators**
```html
<span class="risk-indicator risk-low"></span>
<span class="risk-indicator risk-medium"></span>
<span class="risk-indicator risk-high"></span>
```

#### **Navigation Items**
```html
<a href="#" class="nav-item active flex items-center gap-3 px-3 py-2 text-sm">
    <i data-lucide="layout-dashboard" class="w-4 h-4"></i>
    <span>Overview</span>
</a>
```

### **Data Tables**
- Hover effects with background color changes
- Sortable columns with visual indicators
- Responsive design with horizontal scrolling
- Status indicators and action buttons

### **Charts**
- Real-time data updates
- Multiple chart types (line, bar, doughnut)
- Interactive tooltips and legends
- Responsive sizing

## 🔧 Configuration

### **Environment Setup**
1. Ensure Tailwind CSS is compiled and available
2. Add Chart.js and Lucide Icons CDN links
3. Configure API endpoints for real-time data

### **Customization Options**

#### **Color Scheme**
```css
:root {
    --bg-primary: #0a0a0a;
    --bg-secondary: #111111;
    --bg-tertiary: #1a1a1a;
    --success: #10b981;
    --danger: #ef4444;
    --warning: #f59e0b;
    --accent: #3b82f6;
}
```

#### **Typography**
```css
* {
    font-family: 'Inter', sans-serif;
}
```

#### **Animations**
```css
.metric-card:hover {
    border-color: var(--accent);
    box-shadow: 0 0 20px rgba(59, 130, 246, 0.1);
}
```

## 📊 Data Integration

### **API Endpoints**
The dashboard is designed to connect to various API endpoints:

#### **Market Data**
- `/api/v1/live/prices` - Real-time price feeds
- `/api/v1/live/predictions` - Prediction market data
- `/api/v1/production/status` - System status

#### **Trading Operations**
- Order placement and management
- Position tracking
- Account information
- Trade history

#### **Agent Management**
- Agent status and performance
- Confidence scores and decisions
- P&L contribution tracking

### **Real-time Updates**
```javascript
// Example: Real-time price updates
function startRealTimeUpdates() {
    setInterval(async () => {
        await loadAllData();
        updateUI();
    }, 5000);
}
```

## 🎯 Accessibility Features

### **WCAG 2.1 AA Compliance**
- Semantic HTML structure
- Proper ARIA labels and roles
- Keyboard navigation support
- Screen reader compatibility
- High contrast ratios

### **Form Accessibility**
- All form elements have proper labels
- Input fields have placeholder text
- Select elements have accessible names
- Buttons have discernible text or titles

## 🚀 Performance Optimization

### **Loading States**
- Skeleton loaders for initial data load
- Shimmer effects for content loading
- Progressive data rendering

### **Efficient Updates**
- Debounced real-time updates
- Optimized chart rendering
- Minimal DOM manipulation

### **Resource Management**
- Lazy loading for charts
- Efficient event listeners
- Memory leak prevention

## 📱 Responsive Design

### **Breakpoints**
- **Mobile**: < 768px
- **Tablet**: 768px - 1024px
- **Desktop**: 1024px - 1440px
- **Large Desktop**: > 1440px

### **Adaptive Layouts**
- Collapsible sidebar on mobile
- Horizontal scrolling for tables
- Responsive grid systems
- Touch-friendly interactions

## 🔒 Security Considerations

### **Data Protection**
- No sensitive data in frontend
- Secure API communication
- Input validation and sanitization
- XSS prevention measures

### **Authentication**
- Session management
- Role-based access control
- API key protection
- Secure token handling

## 🧪 Testing

### **Browser Compatibility**
- Chrome (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)

### **Device Testing**
- Desktop computers
- Tablets (iPad, Android)
- Mobile phones (iOS, Android)

## 📈 Monitoring & Analytics

### **Performance Metrics**
- Page load times
- API response times
- User interaction tracking
- Error rate monitoring

### **User Analytics**
- Screen usage patterns
- Feature adoption rates
- Session duration
- Conversion tracking

## 🔄 Future Enhancements

### **Planned Features**
- WebSocket real-time connections
- Advanced charting tools
- Custom dashboard layouts
- Mobile app version
- Multi-language support

### **Technical Improvements**
- React/Next.js migration option
- TypeScript implementation
- Advanced state management
- Component library extraction

## 📞 Support & Maintenance

### **Documentation**
- Comprehensive API documentation
- Component usage examples
- Troubleshooting guides
- Best practices

### **Maintenance**
- Regular security updates
- Performance optimization
- Browser compatibility updates
- Feature enhancements

---

## 🏆 Production Deployment

This dashboard is **production-ready** with:
- **Enterprise-grade reliability**
- **Professional trading interface**
- **Comprehensive monitoring**
- **Scalable architecture**
- **Security best practices**

**Ready for immediate deployment in professional trading environments!** 🚀

---

*Built with ❤️ for quantitative traders and portfolio managers*
