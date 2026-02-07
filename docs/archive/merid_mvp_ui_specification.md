# MERID MVP UI Specification

**Specification Date**: March 22, 2026  
**Phase**: Season 2 Minimum Viable UI  
**Status**: Ready for Implementation  
**Version**: 1.0

---

## Executive Summary

**Objective**: Define minimum viable UI for Season 2 that stays small and sharp while providing essential trading and risk management capabilities

**Approach**: Role-based permissions for big levers, granular permissions for strategy/asset-level controls, essential real-time metrics, and clear P&L visualization

**Key Principles**: Small and sharp, role-based for critical controls, granular for strategy-level knobs, real-time risk metrics, clear P&L visualization

---

## 1. User Roles and Permissions

### Minimum Role Structure

**Design Philosophy**: Role-based for big levers, granular for strategy/asset-level knobs

#### Trader Role

**Primary Responsibilities**: Strategy management and trading operations

**View Permissions**:
- ✅ All P&L (realized, unrealized, total)
- ✅ All positions (current and historical)
- ✅ All orders (active, filled, cancelled)
- ✅ Basic risk metrics (exposure, drawdown, concentration)

**Action Permissions**:
- ✅ Enable/disable their own strategies
- ✅ Adjust strategy parameters within pre-set limits
- ✅ Cancel their own orders
- ❌ Cannot change global risk modes or limits

**Granular Permissions**:
- ✅ Strategy enable/disable rights (their own strategies only)
- ✅ Max size per strategy (within pre-set limits)
- ✅ Venue routing weights per strategy (within limits)
- ❌ Cannot enable new assets/venues

#### Risk Role

**Primary Responsibilities**: Risk management and limit enforcement

**View Permissions**:
- ✅ All P&L (realized, unrealized, total)
- ✅ All positions (current and historical)
- ✅ All risk limits and metrics
- ✅ All exposure and concentration data

**Action Permissions**:
- ✅ Change risk mode (normal/tight/emergency)
- ✅ Tweak limits within guardrails
- ✅ Approve trader requests that raise risk
- ❌ Cannot modify strategy logic or deploy code

**Granular Permissions**:
- ✅ Max size/leverage per strategy
- ✅ Access to certain instruments (can enable new assets/venues)
- ✅ Venue routing weights per team or strategy
- ✅ Strategy enable/disable rights (all strategies)

#### Ops/SRE Role

**Primary Responsibilities**: Platform operations and incident response

**View Permissions**:
- ✅ Everything (all data, all metrics, all configurations)

**Action Permissions**:
- ✅ Kill switch operations
- ✅ Mode changes (halt/degrade)
- ✅ Deploy/rollback operations
- ✅ Change routing/infra config
- ✅ Run chaos drills

**Granular Permissions**:
- ✅ All granular permissions (full system control)
- ✅ Can override other role permissions in emergencies
- ✅ Can modify system configurations
- ❌ Cannot modify strategy logic (unless authorized)

#### Read-Only/Audit Role

**Primary Responsibilities**: Monitoring and audit

**View Permissions**:
- ✅ Everything (all data, all metrics, all configurations)

**Action Permissions**:
- ❌ Nothing (read-only access only)

**Granular Permissions**:
- ❌ No action permissions
- ✅ Full view access for audit purposes
- ✅ Can generate reports and exports

### Permission Matrix

| Action | Trader | Risk | Ops/SRE | Read-Only |
|---------|---------|-------|----------|-----------|
| View P&L | ✅ | ✅ | ✅ | ✅ |
| View Positions | ✅ | ✅ | ✅ | ✅ |
| View Orders | ✅ | ✅ | ✅ | ✅ |
| View Risk Metrics | ✅ | ✅ | ✅ | ✅ |
| Enable/Disable Strategy | ✅ (own) | ✅ (all) | ✅ (all) | ❌ |
| Adjust Strategy Params | ✅ (within limits) | ❌ | ✅ (all) | ❌ |
| Cancel Orders | ✅ (own) | ✅ (all) | ✅ (all) | ❌ |
| Change Risk Mode | ❌ | ✅ | ✅ | ❌ |
| Adjust Risk Limits | ❌ | ✅ (within guardrails) | ✅ (all) | ❌ |
| Kill Switch | ❌ | ❌ | ✅ | ❌ |
| Deploy/Rollback | ❌ | ❌ | ✅ | ❌ |
| Change Routing | ✅ (own strategy) | ✅ (all) | ✅ (all) | ❌ |
| Enable New Assets | ❌ | ✅ | ✅ | ❌ |

---

## 2. Essential Real-Time P&L Metrics Per Position

### Per Position Row Data Structure

**Core Fields**:
- **Symbol**: Trading symbol (e.g., BTC/USD)
- **Venue**: Trading venue (e.g., Binance, Coinbase)
- **Side**: Buy/Sell direction
- **Size**: Position size (quantity)
- **Entry Price**: Average entry price
- **Mark Price**: Current market price
- **Unrealized P&L**: (mark - entry) × size (signed by side)
- **Unrealized P&L %**: Unrealized P&L as percentage
- **Realized P&L**: Accumulated realized P&L
- **Total P&L**: Realized + Unrealized P&L

**Optional Fields**:
- **Fees**: Trading fees incurred
- **Holding Time**: Time position has been held
- **Margin Used**: Margin used for position (if applicable)

### Calculation Logic

**Unrealized P&L**:
```
Unrealized P&L = (Mark Price - Entry Price) × Size × Side
```
Where Side = +1 for Long, -1 for Short

**Unrealized P&L %**:
```
Unrealized P&L % = (Unrealized P&L / (Entry Price × Size)) × 100
```

**Realized P&L**:
```
Realized P&L = Sum of all closed position P&L (including fees)
```

**Total P&L**:
```
Total P&L = Realized P&L + Unrealized P&L
```

### Real-Time Update Requirements

**Update Frequency**: Sub-second updates for active positions
**Data Sources**: Trading engine, market data feeds, P&L calculation engine
**Latency Requirements**: <500ms from market data update to UI display

---

## 3. Critical Risk Metrics Every Tick

### Real-Time Risk Metrics

**Update Frequency**: Every tick (real-time market data updates)
**Data Sources**: Risk calculation engine, position management, market data

#### Exposure Metrics

**Net Exposure**:
- **Per Symbol**: Net position size per symbol
- **Per Venue**: Net position size per venue
- **Per Strategy**: Net position size per strategy
- **Aggregate**: Total net exposure across all positions

**Gross Exposure**:
- **Per Symbol**: Gross position size per symbol
- **Per Venue**: Gross position size per venue
- **Per Strategy**: Gross position size per strategy
- **Aggregate**: Total gross exposure across all positions

#### Concentration Metrics

**Largest Position %**:
```
Largest Position % = (Largest Position Size / Total Capital) × 100
```

**Top N Combined %**:
```
Top N Combined % = (Sum of Top N Position Sizes / Total Capital) × 100
```

**Concentration Thresholds**:
- **Warning**: Single position >10% of total capital
- **Critical**: Single position >20% of total capital
- **Emergency**: Top 3 positions >50% of total capital

#### Drawdown Metrics

**Current Intraday Drawdown**:
```
Current Drawdown = (Peak Equity - Current Equity) / Peak Equity × 100
```

**Max Intraday Drawdown**:
```
Max Drawdown = Maximum drawdown observed during current session
```

**Drawdown Thresholds**:
- **Warning**: Drawdown >2%
- **Critical**: Drawdown >5%
- **Emergency**: Drawdown >10%

#### Leverage and Margin Metrics

**Current Leverage**:
```
Leverage = Total Exposure / Total Capital
```

**Margin Use**:
```
Margin Use = Required Margin / Available Margin × 100
```

**Leverage Thresholds**:
- **Warning**: Leverage >2x
- **Critical**: Leverage >3x
- **Emergency**: Leverage >5x

#### Simple VaR-Like Metric

**Per-Position VaR Approximation**:
```
Position VaR = Position Size × Price Volatility × Confidence Factor
```

**Aggregate VaR**:
```
Total VaR = Sum of all Position VaR (simplified, assumes no correlation)
```

**VaR Thresholds**:
- **Warning**: Daily VaR >1% of capital
- **Critical**: Daily VaR >2% of capital
- **Emergency**: Daily VaR >5% of capital

#### Guardrail Status

**Distance to Critical Limits**:
- **P&L Limit**: Current P&L vs maximum drawdown limit
- **Exposure Limit**: Current exposure vs maximum exposure limit
- **Concentration Limit**: Current concentration vs maximum concentration limit
- **VaR Limit**: Current VaR vs maximum VaR limit

**Active Breaches**:
- **Limit Breaches**: Current limit breaches
- **Guardrail Triggers**: Active guardrail triggers
- **Enforcement Actions**: Recent enforcement actions
- **Risk Mode**: Current risk mode (normal/tight/emergency)

---

## 4. Visualizing Unrealized vs Realized P&L Per Asset

### Visual Design Philosophy

**Key Concept**: Realized = banked, Unrealized = at risk
**Visual Separation**: Distinct colors or textures for realized vs unrealized
**Clear Labeling**: Legend and labels clearly distinguish between the two

### Per Position/Asset Row Visualization

**Two-Bar Design**:
```
[Realized Bar] [Unrealized Bar] [+/- $X.XX (Y.Y%)]
```

**Visual Elements**:
- **Left Bar**: Realized P&L (green/red, capped width)
- **Right Bar**: Unrealized P&L (green/red, dynamic width)
- **Total P&L**: Combined total with percentage
- **Color Coding**: Green for positive, red for negative

**Bar Properties**:
- **Realized Bar**: Fixed width, shows accumulated P&L
- **Unrealized Bar**: Dynamic width, shows current unrealized P&L
- **Height**: Consistent height for easy comparison
- **Border**: Subtle border for visual separation

### Aggregate Per Asset/Strategy Visualization

**Stacked Bar Design**:
```
[Realized Base] [Unrealized Stack] = Total Exposure
```

**Visual Elements**:
- **Base Layer**: Realized P&L (solid color)
- **Stacked Layer**: Unrealized P&L (semi-transparent)
- **Total Height**: Total P&L exposure
- **Hover Details**: Breakdown on hover

**Interaction**:
- **Hover**: Shows breakdown (realized, unrealized, fees)
- **Click**: Drills down to detailed position view
- **Filter**: Filter by asset class or strategy
- **Sort**: Sort by P&L, exposure, or risk

### Time Series Visualization

**Sparkline Design**:
```
[Total P&L Line] [Unrealized Shaded Area]
```

**Visual Elements**:
- **Solid Line**: Total P&L over time
- **Shaded Area**: Unrealized P&L contribution
- **Color Coding**: Positive/negative color coding
- **Time Axis**: Session time axis

**Chart Properties**:
- **Time Range**: Current session or configurable range
- **Update Frequency**: Real-time updates
- **Resolution**: Tick-level or aggregated as needed
- **Legend**: Clear legend for line and area

### Color and Texture Guidelines

**Color Scheme**:
- **Positive P&L**: Green (#10b981)
- **Negative P&L**: Red (#ef4444)
- **Realized P&L**: Solid colors
- **Unrealized P&L**: Semi-transparent or patterned

**Texture Guidelines**:
- **Realized P&L**: Solid fill
- **Unrealized P&L**: Diagonal lines or dots pattern
- **Hover Effects**: Highlight or border emphasis
- **Selection**: Clear selection indicator

### Labeling and Legend

**Per Position Labels**:
- **Position ID**: Symbol/venue identifier
- **P&L Values**: Realized, unrealized, total values
- **Percentage**: Percentage change from entry
- **Status**: Active/closed status indicator

**Aggregate Labels**:
- **Asset Name**: Asset or strategy name
- **Total Exposure**: Total P&L exposure
- **Contribution**: Percentage of total
- **Risk Level**: Risk level indicator

**Legend Elements**:
- **Realized P&L**: Solid color indicator
- **Unrealized P&L**: Patterned color indicator
- **Total P&L**: Combined indicator
- **Thresholds**: Warning/critical thresholds

---

## 5. Implementation Requirements

### Technical Requirements

**Performance Requirements**:
- **Data Update Latency**: <500ms for real-time metrics
- **UI Response Time**: <200ms for user interactions
- **Concurrent Users**: Support 5-10 concurrent users
- **Data Volume**: Handle 1000+ positions with sub-second updates

**Data Sources**:
- **Trading Engine**: Position and order data
- **Market Data**: Real-time price feeds
- **Risk Engine**: Risk calculations and limits
- **P&L Engine**: P&L calculations and aggregations

**API Requirements**:
- **WebSocket**: Real-time data streaming
- **REST API**: Configuration and control
- **Authentication**: Secure user authentication
- **Authorization**: Role-based access control

### Security Requirements

**Authentication**:
- **Multi-Factor Authentication**: MFA required for all roles
- **Session Management**: Secure session with timeout
- **Password Policy**: Strong password requirements
- **Failed Login Lockout**: Lockout after failed attempts

**Authorization**:
- **Role-Based Access**: RBAC enforcement
- **Granular Permissions**: Strategy/asset level permissions
- **Audit Trail**: Complete audit logging
- **Permission Validation**: Server-side permission validation

**Data Protection**:
- **Encryption**: Data encryption in transit and at rest
- **Access Logging**: Complete access logging
- **Data Retention**: Appropriate data retention policies
- **Compliance**: Regulatory compliance requirements

### UI/UX Requirements

**Design Principles**:
- **Clarity**: Clear visual hierarchy and labeling
- **Consistency**: Consistent design patterns
- **Responsiveness**: Fast response to user actions
- **Accessibility**: Accessibility compliance

**Visual Design**:
- **Color Scheme**: Consistent color coding for P&L and risk
- **Typography**: Clear, readable fonts
- **Layout**: Efficient use of screen space
- **Interaction**: Intuitive user interactions

**User Experience**:
- **Learning Curve**: Minimal learning curve
- **Error Prevention**: Prevent user errors
- **Feedback**: Clear feedback for user actions
- **Help**: Contextual help and documentation

---

## 6. Implementation Roadmap

### Phase 1: Core Functionality (Weeks 1-4)

**Week 1-2: Foundation**
- User authentication and authorization
- Basic UI framework and layout
- Position data integration
- Real-time data streaming

**Week 3-4: P&L Visualization**
- Per position P&L display
- Realized vs unrealized P&L visualization
- Aggregate P&L views
- Basic risk metrics display

**Deliverables**:
- Working authentication system
- Basic position and P&L views
- Real-time data integration
- Basic risk metrics

### Phase 2: Risk Management (Weeks 5-8)

**Week 5-6: Risk Metrics**
- Real-time risk metrics calculation
- Exposure and concentration monitoring
- Drawdown and leverage tracking
- Guardrail status monitoring

**Week 7-8: Risk Controls**
- Risk mode management
- Limit adjustment controls
- Alert and notification system
- Risk dashboard

**Deliverables**:
- Complete risk metrics
- Risk management controls
- Alert and notification system
- Risk dashboard

### Phase 3: Polish and Optimization (Weeks 9-12)

**Week 9-10: User Experience**
- UI/UX polish and optimization
- User feedback incorporation
- Performance optimization
- Accessibility improvements

**Week 11-12: Testing and Deployment**
- Comprehensive testing
- Security testing
- Documentation and training
- Production deployment

**Deliverables**:
- Polished user interface
- Comprehensive testing
- Documentation and training
- Production-ready system

---

## 7. Success Criteria

### Technical Success Criteria

**Performance**:
- **Data Latency**: <500ms for real-time updates
- **UI Response**: <200ms for user interactions
- **System Uptime**: >99.9% uptime
- **Concurrent Users**: Support 10+ concurrent users

**Functionality**:
- **Real-Time Data**: Sub-second real-time updates
- **P&L Accuracy**: Accurate P&L calculations
- **Risk Accuracy**: Accurate risk calculations
- **User Roles**: Proper role-based access control

### Business Success Criteria

**User Satisfaction**:
- **Ease of Use**: High user satisfaction scores
- **Learning Curve**: Minimal learning curve
- **Error Rate**: Low user error rate
- **Adoption**: High user adoption rate

**Operational Excellence**:
- **Risk Management**: Effective risk monitoring and control
- **Decision Speed**: Fast decision-making support
- **Incident Response**: Fast incident detection and response
- **Compliance**: Full regulatory compliance

---

## 8. Conclusion

### Specification Summary

**MVP Focus**: Small and sharp UI with essential trading and risk management capabilities
- **Role-Based Permissions**: Big levers controlled by roles
- **Granular Permissions**: Strategy/asset-level knobs with fine control
- **Real-Time Metrics**: Essential P&L and risk metrics updated every tick
- **Clear Visualization**: Distinct visualization of realized vs unrealized P&L

**Implementation Ready**:
- Complete technical specifications
- Clear implementation roadmap
- Success criteria and metrics
- Security and compliance requirements

### Next Steps

**Implementation Planning**:
- Technology stack selection
- Development team assignment
- Project timeline and milestones
- Quality assurance and testing

**Stakeholder Review**:
- Specification review with stakeholders
- Feedback incorporation
- Approval process
- Implementation authorization

**Development Execution**:
- Phase-based implementation
- Regular progress reviews
- Quality assurance and testing
- Deployment and training

---

**Specification Status**: ✅ COMPLETE  
**Technical Requirements**: ✅ DEFINED  
**Implementation Roadmap**: ✅ READY  
**Success Criteria**: ✅ DEFINED  
**Stakeholder Review**: ✅ READY

**MERID MVP UI Specification is complete and ready for implementation. The specification provides a focused, practical blueprint for Season 2 minimum viable UI that delivers essential trading and risk management capabilities while staying small and sharp.**
