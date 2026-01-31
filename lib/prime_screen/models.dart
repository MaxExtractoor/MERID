import 'dart:convert';

class PrimeScreenState {
  PrimeScreenState({
    required this.timestamp,
    required this.env,
    required this.symbols,
    required this.agents,
    required this.consensus,
    required this.news,
    required this.predictionMarkets,
  });

  final String timestamp;
  final String env;
  final List<String> symbols;
  final List<AgentState> agents;
  final List<ConsensusDecision> consensus;
  final List<NewsItem> news;
  final List<PredictionMarket> predictionMarkets;

  factory PrimeScreenState.fromJson(Map<String, dynamic> json) {
    return PrimeScreenState(
      timestamp: json['timestamp']?.toString() ?? '',
      env: json['env']?.toString() ?? 'unknown',
      symbols: (json['symbols'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
      agents: (json['agents'] as List<dynamic>? ?? [])
          .map((e) => AgentState.fromJson(e as Map<String, dynamic>))
          .toList(),
      consensus: (json['consensus'] as List<dynamic>? ?? [])
          .map((e) => ConsensusDecision.fromJson(e as Map<String, dynamic>))
          .toList(),
      news: (json['news'] as List<dynamic>? ?? [])
          .map((e) => NewsItem.fromJson(e as Map<String, dynamic>))
          .toList(),
      predictionMarkets: (json['prediction_markets'] as List<dynamic>? ?? [])
          .map((e) => PredictionMarket.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class AgentState {
  AgentState({
    required this.id,
    required this.name,
    required this.role,
    required this.instruments,
    required this.status,
    required this.pnl24h,
    this.position,
    this.currentIntent,
    required this.health,
  });

  final String id;
  final String name;
  final String role;
  final List<String> instruments;
  final String status;
  final double pnl24h;
  final Position? position;
  final Intent? currentIntent;
  final AgentHealth health;

  factory AgentState.fromJson(Map<String, dynamic> json) {
    return AgentState(
      id: json['id']?.toString() ?? '',
      name: json['name']?.toString() ?? 'agent',
      role: json['role']?.toString() ?? 'role',
      instruments: (json['instruments'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
      status: json['status']?.toString() ?? 'unknown',
      pnl24h: (json['pnl_24h'] as num?)?.toDouble() ?? 0,
      position: json['position'] == null
          ? null
          : Position.fromJson(json['position'] as Map<String, dynamic>),
      currentIntent: json['current_intent'] == null
          ? null
          : Intent.fromJson(json['current_intent'] as Map<String, dynamic>),
      health:
          AgentHealth.fromJson(json['health'] as Map<String, dynamic>? ?? {}),
    );
  }
}

class Position {
  Position({
    required this.symbol,
    required this.netQty,
    required this.avgEntry,
    required this.unrealizedPnl,
  });

  final String symbol;
  final double netQty;
  final double avgEntry;
  final double unrealizedPnl;

  factory Position.fromJson(Map<String, dynamic> json) {
    return Position(
      symbol: json['symbol']?.toString() ?? 'N/A',
      netQty: (json['net_qty'] as num?)?.toDouble() ?? 0,
      avgEntry: (json['avg_entry'] as num?)?.toDouble() ?? 0,
      unrealizedPnl: (json['unrealized_pnl'] as num?)?.toDouble() ?? 0,
    );
  }
}

class Intent {
  Intent({
    required this.symbol,
    required this.side,
    required this.size,
    required this.confidence,
    required this.timeHorizonSec,
    required this.predictedMoveBps,
  });

  final String symbol;
  final String side;
  final double size;
  final double confidence;
  final int timeHorizonSec;
  final double predictedMoveBps;

  factory Intent.fromJson(Map<String, dynamic> json) {
    return Intent(
      symbol: json['symbol']?.toString() ?? 'N/A',
      side: json['side']?.toString() ?? 'hold',
      size: (json['size'] as num?)?.toDouble() ?? 0,
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0,
      timeHorizonSec: (json['time_horizon_sec'] as num?)?.toInt() ?? 0,
      predictedMoveBps: (json['predicted_move_bps'] as num?)?.toDouble() ?? 0,
    );
  }
}

class AgentHealth {
  AgentHealth({required this.latencyMs, required this.errorRate1m});

  final double latencyMs;
  final double errorRate1m;

  factory AgentHealth.fromJson(Map<String, dynamic> json) {
    return AgentHealth(
      latencyMs: (json['latency_ms'] as num?)?.toDouble() ?? 0,
      errorRate1m: (json['error_rate_1m'] as num?)?.toDouble() ?? 0,
    );
  }
}

class ConsensusDecision {
  ConsensusDecision({
    required this.decisionId,
    required this.symbol,
    required this.action,
    required this.size,
    required this.score,
    required this.expectedValue,
    required this.riskScore,
    required this.state,
    required this.agentVotes,
  });

  final String decisionId;
  final String symbol;
  final String action;
  final double size;
  final double score;
  final double expectedValue;
  final double riskScore;
  final String state;
  final List<AgentVote> agentVotes;

  factory ConsensusDecision.fromJson(Map<String, dynamic> json) {
    return ConsensusDecision(
      decisionId: json['decision_id']?.toString() ?? '',
      symbol: json['symbol']?.toString() ?? 'N/A',
      action: json['action']?.toString() ?? 'hold',
      size: (json['size'] as num?)?.toDouble() ?? 0,
      score: (json['score'] as num?)?.toDouble() ?? 0,
      expectedValue: (json['expected_value'] as num?)?.toDouble() ?? 0,
      riskScore: (json['risk_score'] as num?)?.toDouble() ?? 0,
      state: json['state']?.toString() ?? 'proposed',
      agentVotes: (json['agent_votes'] as List<dynamic>? ?? [])
          .map((e) => AgentVote.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class AgentVote {
  AgentVote({
    required this.agentId,
    required this.vote,
    required this.weight,
    required this.confidence,
    this.reasonCode,
  });

  final String agentId;
  final String vote;
  final double weight;
  final double confidence;
  final String? reasonCode;

  factory AgentVote.fromJson(Map<String, dynamic> json) {
    return AgentVote(
      agentId: json['agent_id']?.toString() ?? '',
      vote: json['vote']?.toString() ?? 'hold',
      weight: (json['weight'] as num?)?.toDouble() ?? 0,
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0,
      reasonCode: json['reason_code']?.toString(),
    );
  }
}

class NewsItem {
  NewsItem({
    required this.id,
    required this.source,
    required this.headline,
    required this.publishedAt,
    required this.symbols,
    required this.sentiment,
    this.url,
    this.summary,
  });

  final String id;
  final String source;
  final String headline;
  final String publishedAt;
  final List<String> symbols;
  final double sentiment;
  final String? url;
  final String? summary;

  factory NewsItem.fromJson(Map<String, dynamic> json) {
    return NewsItem(
      id: json['id']?.toString() ?? '',
      source: json['source']?.toString() ?? 'news',
      headline: json['headline']?.toString() ?? 'headline',
      publishedAt: json['published_at']?.toString() ?? '',
      symbols: (json['symbols'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
      sentiment: (json['sentiment'] as num?)?.toDouble() ?? 0,
      url: json['url']?.toString(),
      summary: json['summary']?.toString(),
    );
  }
}

class PredictionMarket {
  PredictionMarket({
    required this.id,
    required this.label,
    required this.expiry,
    required this.houseProb,
    required this.agentBooks,
  });

  final String id;
  final String label;
  final String expiry;
  final double houseProb;
  final List<PredictionBook> agentBooks;

  factory PredictionMarket.fromJson(Map<String, dynamic> json) {
    return PredictionMarket(
      id: json['id']?.toString() ?? '',
      label: json['label']?.toString() ?? 'market',
      expiry: json['expiry']?.toString() ?? '',
      houseProb: (json['house_prob'] as num?)?.toDouble() ?? 0.5,
      agentBooks: (json['agent_books'] as List<dynamic>? ?? [])
          .map((e) => PredictionBook.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class PredictionBook {
  PredictionBook({
    required this.agentId,
    required this.bidProb,
    required this.askProb,
    required this.position,
  });

  final String agentId;
  final double bidProb;
  final double askProb;
  final double position;

  factory PredictionBook.fromJson(Map<String, dynamic> json) {
    return PredictionBook(
      agentId: json['agent_id']?.toString() ?? '',
      bidProb: (json['bid_prob'] as num?)?.toDouble() ?? 0,
      askProb: (json['ask_prob'] as num?)?.toDouble() ?? 0,
      position: (json['position'] as num?)?.toDouble() ?? 0,
    );
  }
}

class AutonomyState {
  AutonomyState({
    required this.globalState,
    required this.mode,
    required this.updatedAt,
    required this.updatedBy,
    this.reason,
  });

  final String globalState;
  final String mode;
  final String updatedAt;
  final String updatedBy;
  final String? reason;

  factory AutonomyState.fromJson(Map<String, dynamic> json) {
    return AutonomyState(
      globalState: json['global_state']?.toString() ?? 'running',
      mode: json['mode']?.toString() ?? 'full',
      updatedAt: json['updated_at']?.toString() ?? '',
      updatedBy: json['updated_by']?.toString() ?? 'system',
      reason: json['reason']?.toString(),
    );
  }
}

class AutonomyPortfolio {
  AutonomyPortfolio({
    required this.portfolioId,
    required this.enabled,
    required this.mandate,
    required this.maxNotional,
    required this.maxDailyLoss,
    required this.maxOpenOrders,
    required this.allowedSymbols,
    required this.allowedVenues,
    required this.allowedHours,
  });

  final String portfolioId;
  final bool enabled;
  final String mandate;
  final double maxNotional;
  final double maxDailyLoss;
  final int maxOpenOrders;
  final List<String> allowedSymbols;
  final List<String> allowedVenues;
  final String allowedHours;

  factory AutonomyPortfolio.fromJson(Map<String, dynamic> json) {
    return AutonomyPortfolio(
      portfolioId: json['portfolio_id']?.toString() ?? 'core',
      enabled: json['enabled'] as bool? ?? true,
      mandate: json['mandate']?.toString() ?? 'full',
      maxNotional: (json['max_notional'] as num?)?.toDouble() ?? 0,
      maxDailyLoss: (json['max_daily_loss'] as num?)?.toDouble() ?? 0,
      maxOpenOrders: (json['max_open_orders'] as num?)?.toInt() ?? 0,
      allowedSymbols: (json['allowed_symbols'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
      allowedVenues: (json['allowed_venues'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
      allowedHours: json['allowed_hours']?.toString() ?? '00:00-23:59',
    );
  }
}

class FeatureSnapshot {
  FeatureSnapshot({
    required this.spotPrice,
    required this.fundingRate,
    required this.orderbookImbalance,
    required this.realizedVol1h,
  });

  final double spotPrice;
  final double fundingRate;
  final double orderbookImbalance;
  final double realizedVol1h;

  factory FeatureSnapshot.fromJson(Map<String, dynamic> json) {
    return FeatureSnapshot(
      spotPrice: (json['spot_price'] as num?)?.toDouble() ?? 0,
      fundingRate: (json['funding_rate'] as num?)?.toDouble() ?? 0,
      orderbookImbalance:
          (json['orderbook_imbalance'] as num?)?.toDouble() ?? 0,
      realizedVol1h: (json['realized_vol_1h'] as num?)?.toDouble() ?? 0,
    );
  }
}

class RiskAction {
  RiskAction({
    required this.type,
    required this.before,
    required this.after,
    required this.reason,
  });

  final String type;
  final double before;
  final double after;
  final String reason;

  factory RiskAction.fromJson(Map<String, dynamic> json) {
    return RiskAction(
      type: json['type']?.toString() ?? 'adjustment',
      before: (json['before'] as num?)?.toDouble() ?? 0,
      after: (json['after'] as num?)?.toDouble() ?? 0,
      reason: json['reason']?.toString() ?? 'unknown',
    );
  }
}

class OrderRecord {
  OrderRecord({
    required this.orderId,
    required this.venue,
    required this.state,
    this.avgFillPrice,
    this.filledQty,
  });

  final String orderId;
  final String venue;
  final String state;
  final double? avgFillPrice;
  final double? filledQty;

  factory OrderRecord.fromJson(Map<String, dynamic> json) {
    return OrderRecord(
      orderId: json['order_id']?.toString() ?? '',
      venue: json['venue']?.toString() ?? 'venue',
      state: json['state']?.toString() ?? 'pending',
      avgFillPrice: (json['avg_fill_price'] as num?)?.toDouble(),
      filledQty: (json['filled_qty'] as num?)?.toDouble(),
    );
  }
}

class DecisionDetail {
  DecisionDetail({
    required this.decision,
    required this.featuresSnapshot,
    required this.newsRefs,
    required this.riskActions,
    required this.orders,
    this.realizedPnl,
    this.narrative,
    required this.narrativeStatus,
  });

  final ConsensusDecision decision;
  final FeatureSnapshot featuresSnapshot;
  final List<String> newsRefs;
  final List<RiskAction> riskActions;
  final List<OrderRecord> orders;
  final double? realizedPnl;
  final String? narrative;
  final String narrativeStatus;

  factory DecisionDetail.fromJson(Map<String, dynamic> json) {
    return DecisionDetail(
      decision:
          ConsensusDecision.fromJson(json['decision'] as Map<String, dynamic>),
      featuresSnapshot: FeatureSnapshot.fromJson(
          json['features_snapshot'] as Map<String, dynamic>? ?? {}),
      newsRefs: (json['news_refs'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
      riskActions: (json['risk_actions'] as List<dynamic>? ?? [])
          .map((e) => RiskAction.fromJson(e as Map<String, dynamic>))
          .toList(),
      orders: (json['orders'] as List<dynamic>? ?? [])
          .map((e) => OrderRecord.fromJson(e as Map<String, dynamic>))
          .toList(),
      realizedPnl: (json['realized_pnl'] as num?)?.toDouble(),
      narrative: json['narrative']?.toString(),
      narrativeStatus: json['narrative_status']?.toString() ?? 'pending',
    );
  }
}

class BacktestSubmission {
  BacktestSubmission({required this.backtestId});

  final String backtestId;

  factory BacktestSubmission.fromJson(Map<String, dynamic> json) {
    return BacktestSubmission(
      backtestId: json['backtest_id']?.toString() ?? '',
    );
  }
}

class BacktestSummary {
  BacktestSummary({
    required this.backtestId,
    required this.name,
    required this.mode,
    required this.symbols,
    required this.start,
    required this.end,
    required this.status,
    required this.totalTrades,
    this.realizedPnl,
  });

  final String backtestId;
  final String name;
  final String mode;
  final List<String> symbols;
  final String start;
  final String end;
  final String status;
  final int totalTrades;
  final double? realizedPnl;

  factory BacktestSummary.fromJson(Map<String, dynamic> json) {
    return BacktestSummary(
      backtestId: json['backtest_id']?.toString() ?? '',
      name: json['name']?.toString() ?? '',
      mode: json['mode']?.toString() ?? 'swarm',
      symbols: (json['symbols'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
      start: json['start']?.toString() ?? '',
      end: json['end']?.toString() ?? '',
      status: json['status']?.toString() ?? 'queued',
      totalTrades: (json['total_trades'] as num?)?.toInt() ?? 0,
      realizedPnl: (json['realized_pnl'] as num?)?.toDouble(),
    );
  }
}

class TradeRecord {
  TradeRecord({
    required this.tradeId,
    required this.decisionId,
    required this.symbol,
    required this.action,
    required this.size,
    required this.avgPrice,
    required this.filledAt,
    this.pnl,
  });

  final String tradeId;
  final String decisionId;
  final String symbol;
  final String action;
  final double size;
  final double avgPrice;
  final String filledAt;
  final double? pnl;

  factory TradeRecord.fromJson(Map<String, dynamic> json) {
    return TradeRecord(
      tradeId: json['trade_id']?.toString() ?? '',
      decisionId: json['decision_id']?.toString() ?? '',
      symbol: json['symbol']?.toString() ?? 'N/A',
      action: json['action']?.toString() ?? 'hold',
      size: (json['size'] as num?)?.toDouble() ?? 0,
      avgPrice: (json['avg_price'] as num?)?.toDouble() ?? 0,
      filledAt: json['filled_at']?.toString() ?? '',
      pnl: (json['pnl'] as num?)?.toDouble(),
    );
  }
}

List<T> decodeList<T>(
    String payload, T Function(Map<String, dynamic>) fromJson) {
  final data = jsonDecode(payload) as List<dynamic>;
  return data.map((e) => fromJson(e as Map<String, dynamic>)).toList();
}

class IntentOverrideRequestPayload {
  IntentOverrideRequestPayload({
    required this.decisionId,
    required this.action,
    this.newSize,
    required this.reason,
  });

  final String decisionId;
  final String action;
  final double? newSize;
  final String reason;

  Map<String, dynamic> toJson() => {
        'decision_id': decisionId,
        'action': action,
        if (newSize != null) 'new_size': newSize,
        'reason': reason,
      };
}

class BacktestRequestPayload {
  BacktestRequestPayload({
    required this.name,
    required this.mode,
    required this.symbols,
    required this.start,
    required this.end,
    required this.riskProfile,
    required this.venues,
    required this.dataSource,
    required this.slippageModel,
    required this.seed,
  });

  final String name;
  final String mode;
  final List<String> symbols;
  final String start;
  final String end;
  final String riskProfile;
  final List<String> venues;
  final String dataSource;
  final String slippageModel;
  final int seed;

  Map<String, dynamic> toJson() => {
        'name': name,
        'mode': mode,
        'symbols': symbols,
        'start': start,
        'end': end,
        'risk_profile': riskProfile,
        'venues': venues,
        'data_source': dataSource,
        'slippage_model': slippageModel,
        'seed': seed,
      };
}

class AutonomyStateUpdatePayload {
  AutonomyStateUpdatePayload(
      {this.globalState, this.mode, this.reason, this.updatedBy});

  final String? globalState;
  final String? mode;
  final String? reason;
  final String? updatedBy;

  Map<String, dynamic> toJson() => {
        if (globalState != null) 'global_state': globalState,
        if (mode != null) 'mode': mode,
        if (reason != null) 'reason': reason,
        if (updatedBy != null) 'updated_by': updatedBy,
      };
}

class AutonomyLimitsUpdatePayload {
  AutonomyLimitsUpdatePayload({
    required this.portfolioId,
    this.enabled,
    this.mandate,
    this.maxNotional,
    this.maxDailyLoss,
    this.maxOpenOrders,
    this.allowedSymbols,
    this.allowedVenues,
    this.allowedHours,
  });

  final String portfolioId;
  final bool? enabled;
  final String? mandate;
  final double? maxNotional;
  final double? maxDailyLoss;
  final int? maxOpenOrders;
  final List<String>? allowedSymbols;
  final List<String>? allowedVenues;
  final String? allowedHours;

  Map<String, dynamic> toJson() => {
        'portfolio_id': portfolioId,
        if (enabled != null) 'enabled': enabled,
        if (mandate != null) 'mandate': mandate,
        if (maxNotional != null) 'max_notional': maxNotional,
        if (maxDailyLoss != null) 'max_daily_loss': maxDailyLoss,
        if (maxOpenOrders != null) 'max_open_orders': maxOpenOrders,
        if (allowedSymbols != null) 'allowed_symbols': allowedSymbols,
        if (allowedVenues != null) 'allowed_venues': allowedVenues,
        if (allowedHours != null) 'allowed_hours': allowedHours,
      };
}
