# 🚀 GitHub Issues Template for MERID Live Implementation

## Epic Issue
```markdown
# Epic: Bring MERID Online: Streams, Agents, Oracles, Trading

## Description
Transform MERID from Phase 0 trial to live Phase 1 system with end-to-end data flow

## Impact
- **BLOCKING** - Unblocks live observability, real-time decision making, and governance operations
- **Revenue** - Enables Phase 1 features and live trading capabilities
- **Risk** - Phase 1 cannot launch without this epic

## Acceptance Criteria
- [ ] One concrete stream processing end-to-end
- [ ] One full agent implementation
- [ ] One oracle path functional
- [ ] Vertical slice integration passing
- [ ] NotImplemented count reduced by 3

## Labels
`epic`, `phase-1`, `streams`, `agents`, `oracles`, `trading`, `high-priority`

## Timeline
- **Week 1:** Live observability vertical slice
- **Week 2:** Minimal trading loop
- **Ongoing:** Technical debt reduction

## Technical Debt Discipline
- 20-25% capacity per week to NotImplemented backlog
- No new NotImplemented methods unless directly unlocks Phase 1
- Weekly debt review and metrics tracking
```

## Individual Ticket Templates

### Stream Implementation Tickets
```markdown
# Implement [StreamName] - [stream_type()]

## Description
Implement the [StreamName] class with all required BaseStream methods

## Impact on Live Phase 1
**BLOCKING** - Cannot identify/stream [data type] without this

## Risk if Left As-Is
No [data type] ingestion possible, blocking Phase 1 operations

## Test to Prove It Works
- [ ] Stream returns correct type identifier via `stream_type()`
- [ ] Connection established with health checks
- [ ] Data fetched and parsed correctly
- [ ] Events created with proper schema
- [ ] Metrics captured (messages/sec, lag, error count)

## Implementation Details
- Implement all 5 BaseStream abstract methods
- Add health checks and backoff logic
- Include circuit breaker for failed connections
- Add comprehensive logging and metrics

## Labels
`stream`, `implementation`, `high-priority`, `phase-1`

## Acceptance Criteria
- [ ] All NotImplemented methods implemented
- [ ] Health checks functional
- [ ] Integration tests passing
- [ ] Metrics dashboard showing live data
```

### Agent Implementation Tickets
```markdown
# Implement [AgentName] - Full Agent Methods

## Description
Implement the [AgentName] class with complete intelligence capabilities

## Impact on Live Phase 1
**BLOCKING** - No [domain] intelligence without this agent

## Risk if Left As-Is
No decision making in [domain], poor governance outcomes

## Test to Prove It Works
- [ ] `analyze()` consumes stream data and returns insights
- [ ] `vote()` produces governance decision with confidence
- [ ] `reflect()` updates learning state and persists to DB
- [ ] Agent processes market state correctly
- [ ] Learning metrics captured and improving

## Implementation Details
- Implement all 4 core agent methods
- Add learning state persistence
- Include confidence scoring and reasoning
- Add performance metrics tracking

## Labels
`agent`, `implementation`, `high-priority`, `phase-1`, `intelligence`

## Acceptance Criteria
- [ ] All NotImplemented methods implemented
- [ ] Agent analyzes data and produces insights
- [ ] Voting mechanism functional with governance
- [ ] Learning state updating correctly
- [ ] Performance metrics captured
```

### Oracle Implementation Tickets
```markdown
# Implement [OracleName] - Price Feed Integration

## Description
Implement the [OracleName] class with price feed connectivity

## Impact on Live Phase 1
**BLOCKING** - No [data source] price data without this oracle

## Risk if Left As-Is
No real-time pricing, blocking trading and valuation

## Test to Prove It Works
- [ ] `_connect_impl()` establishes connection to [data source]
- [ ] `_fetch_price_impl()` returns typed OraclePrice struct
- [ ] Latency logging functional (<100ms target)
- [ ] Error handling and retry logic working
- [ ] Price data accuracy validated

## Implementation Details
- Implement 3 core oracle methods
- Add connection pooling and retry logic
- Include latency monitoring and alerts
- Add price validation and sanity checks

## Labels
`oracle`, `implementation`, `high-priority`, `phase-1`, `pricing`

## Acceptance Criteria
- [ ] All NotImplemented methods implemented
- [ ] Real-time price data flowing
- [ ] Latency under 100ms
- [ ] Error handling robust
- [ ] Price accuracy validated
```

### Trading Implementation Tickets
```markdown
# Implement [TradingName] - Market Data Fetching

## Description
Implement the [TradingName] class with live market data capabilities

## Impact on Live Phase 1
**BLOCKING** - No [venue] market data without this implementation

## Risk if Left As-Is
No trading signals from [venue], poor trading decisions

## Test to Prove It Works
- [ ] `_fetch_markets_live()` returns market snapshots
- [ ] `_fetch_funding_live()` returns funding rates
- [ ] Data parsing and validation working
- [ ] Rate limiting respected
- [ ] Error handling and recovery functional

## Implementation Details
- Implement 2 core trading methods
- Add rate limiting and error handling
- Include data validation and sanity checks
- Add market data caching

## Labels
`trading`, `implementation`, `medium-priority`, `phase-1`

## Acceptance Criteria
- [ ] All NotImplemented methods implemented
- [ ] Live market data flowing
- [ ] Data validation passing
- [ ] Rate limiting functional
- [ ] Error recovery working
```

## Project Board Setup

### Columns
- **Backlog** - All tickets ready to start
- **This Week** - Week 1 priorities (vertical slice)
- **Next Week** - Week 2 priorities (trading loop)
- **In Progress** - Currently being worked on
- **Review** - Ready for code review
- **Done** - Completed and tested

### Labels
- **Priority:** `high-priority`, `medium-priority`, `low-priority`
- **Component:** `streams`, `agents`, `oracles`, `trading`, `monitoring`, `defi`
- **Phase:** `phase-1`, `phase-0`
- **Type:** `implementation`, `testing`, `documentation`
- **Status:** `blocked`, `ready-for-review`, `needs-testing`

### Automation
- **Weekly Metrics:** NotImplemented count, test coverage, integration health
- **Debt Tracking:** Automatic NotImplemented count updates
- **Progress Reports:** Weekly epic progress summaries
- **Alerts:** When NotImplemented count increases

## Success Metrics

### Week 1 Success
- [ ] 1 stream processing end-to-end
- [ ] 1 agent fully implemented
- [ ] 1 oracle connected and functional
- [ ] Vertical slice integration passing
- [ ] NotImplemented count reduced by 3

### Week 2 Success
- [ ] Trading data fetching working
- [ ] Dry-run execution path complete
- [ ] "Can go live" checklist passed
- [ ] NotImplemented count reduced by 2
- [ ] Full trading loop tested

### Ongoing Success
- [ ] NotImplemented count decreasing weekly
- [ ] Integration tests passing
- [ ] Live metrics dashboard functional
- [ ] Technical debt under control (≤20% of capacity)
- [ ] No new NotImplemented methods added

## Ready to Paste into GitHub Repository

Copy these templates into your GitHub repository:
1. Create the epic issue
2. Create individual tickets using the templates
3. Set up project board with columns and labels
4. Configure automation for metrics tracking
5. Start with Week 1 priorities

This structure provides ruthless prioritization and clear success metrics for bringing MERID online! 🚀
