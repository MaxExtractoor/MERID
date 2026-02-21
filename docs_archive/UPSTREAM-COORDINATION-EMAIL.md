# 📧 Email Template: MERID Live Arbitrage Feed Integration

**To**: [Upstream Team Contact]
**Subject**: MERID Predictions Dashboard - Live Arbitrage Feed Integration Required

**Summary**: 
The MERID predictions dashboard, arbitrage agent, and experimentation framework are fully functional and tested against mock data. All `/api/v1/institutional/predictions/*` endpoints are wired, the UI renders without console errors, and the agent lab is computing calibration buckets and Brier scores per run. The only missing piece to move from "lab mode" to "real trading intelligence" is a live arbitrage feed behind the existing `/predictions/arbitrage` endpoint.

**Required Integration**:
- **Target Endpoint**: `/api/v1/institutional/predictions/arbitrage`
- **Schema**: Detailed arbitrage opportunity object (attached)
- **Freshness SLO**: 30 seconds during trading hours
- **Viability**: Minimum 1 opportunity with >0.05 spread and >$50k liquidity
- **Stability**: No breaking field changes without coordination

**Current Status**:
- ✅ All predictions endpoints functional with mock data
- ✅ Dashboard renders cleanly without errors
- ✅ Agent framework processes data correctly
- ✅ Experimentation framework validates statistical analysis
- ✅ Integration test script validates API contract

**Required Schema**:
```json
{
  "opportunities": [
    {
      "id": "string",
      "canonical_question": "string",
      "markets": {
        "venue_1": {
          "yes_price": 0.65,
          "no_price": 0.35,
          "liquidity": 150000.0,
          "fee_rate": 0.02,
          "last_updated": "2024-01-24T12:00:00Z"
        },
        "venue_2": {
          "yes_price": 0.62,
          "no_price": 0.38,
          "liquidity": 120000.0,
          "fee_rate": 0.025,
          "last_updated": "2024-01-24T12:00:00Z"
        }
      },
      "max_probability": 0.65,
      "min_probability": 0.62,
      "spread_probability": 0.03,
      "max_probability_venue": "venue_1",
      "min_probability_venue": "venue_2",
      "profit_potential": 15000.0,
      "confidence": 0.85,
      "category": "crypto",
      "timestamp": "2024-01-24T12:00:00Z"
    }
  ],
  "count": 1,
  "status": "success",
  "data_freshness": {
    "max_age_seconds": 30,
    "last_update": "2024-01-24T12:00:00Z"
  }
}
```

**Implementation Options**:
1. **Option A**: Enhance existing aggregator (`monitoring.prediction_analytics.get_arbitrage_opportunities`)
2. **Option B**: Create dedicated service (`services.arbitrage_feed.get_live_opportunities`)

**Next Steps**:
1. Please review the schema and confirm implementation approach
2. Wire live data to the specified endpoint
3. We'll validate integration using our test script
4. Once confirmed, we can immediately start production experiments

**Timeline**: Ready for immediate integration once live feed is available.

**Contact**: [Your Name] - [Your Contact Info]

---
**Attachment**: `docs/PREDICTIONS-PRODUCTION-CHECKLIST.md` - Complete deployment checklist
