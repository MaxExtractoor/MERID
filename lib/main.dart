import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;

import 'prime_screen/app.dart';

void main() {
  runApp(const ProviderScope(child: PrimeScreenApp()));
}

class _OracleFeed {
  const _OracleFeed({required this.name, this.price});

  final String name;
  final double? price;
}

class _OracleContext {
  const _OracleContext({required this.gap, required this.feeds});

  final double? gap;
  final Map<String, _OracleFeed> feeds;

  bool get hasData => feeds.isNotEmpty;
  String get displayGap =>
      gap == null ? "N/A" : "${(gap! * 100).toStringAsFixed(2)}%";

  Color get badgeColor {
    if (!hasData || gap == null) return const Color(0xFF94A3B8);
    final magnitude = gap!.abs() * 100;
    if (magnitude < 5) return const Color(0xFF10B981);
    if (magnitude < 15) return const Color(0xFFFBBF24);
    return const Color(0xFFF87171);
  }

  String get badgeLabel {
    if (!hasData || gap == null) return "ORACLE N/A";
    final magnitude = gap!.abs() * 100;
    if (magnitude < 5) return "ORACLE VERIFIED";
    if (magnitude < 15) return "ORACLE DRIFT";
    return "ORACLE DIVERGENT";
  }
}

class HeatmapSymbol {
  HeatmapSymbol({
    required this.symbol,
    required this.long,
    required this.short,
    required this.total,
  });

  final String symbol;
  final double long;
  final double short;
  final double total;

  factory HeatmapSymbol.fromJson(Map<String, dynamic> json) {
    return HeatmapSymbol(
      symbol: json['symbol']?.toString() ?? 'UNKNOWN',
      long: (json['long'] as num?)?.toDouble() ?? 0,
      short: (json['short'] as num?)?.toDouble() ?? 0,
      total: (json['total'] as num?)?.toDouble() ?? 0,
    );
  }
}

class HeatmapVenue {
  HeatmapVenue({required this.venue, required this.volume});

  final String venue;
  final double volume;

  factory HeatmapVenue.fromJson(Map<String, dynamic> json) {
    return HeatmapVenue(
      venue: json['venue']?.toString() ?? 'unknown',
      volume: (json['volume'] as num?)?.toDouble() ?? 0,
    );
  }
}

class HeatmapSnapshot {
  HeatmapSnapshot(
      {this.generatedAt,
      required this.symbols,
      required this.venues,
      this.arbitrage,
      this.liquidations = const []});

  final double? generatedAt;
  final List<HeatmapSymbol> symbols;
  final List<HeatmapVenue> venues;
  final Map<String, dynamic>? arbitrage;
  final List<Map<String, dynamic>> liquidations;

  factory HeatmapSnapshot.fromJson(Map<String, dynamic> json) {
    return HeatmapSnapshot(
      generatedAt: (json['generated_at'] as num?)?.toDouble(),
      symbols: (json['symbols'] as List<dynamic>? ?? [])
          .map((e) => HeatmapSymbol.fromJson(e as Map<String, dynamic>))
          .toList(),
      venues: (json['venues'] as List<dynamic>? ?? [])
          .map((e) => HeatmapVenue.fromJson(e as Map<String, dynamic>))
          .toList(),
      arbitrage: json['arbitrage'] as Map<String, dynamic>?,
      liquidations: (json['liquidations'] as List<dynamic>? ?? [])
          .map((e) => e as Map<String, dynamic>)
          .toList(),
    );
  }
}

class TickerEntry {
  TickerEntry({
    required this.symbol,
    this.venue,
    this.price,
    this.indexPrice,
    this.basis,
    this.basisPct,
    this.fundingRate,
    this.openInterest,
    this.volume24h,
  });

  final String symbol;
  final String? venue;
  final double? price;
  final double? indexPrice;
  final double? basis;
  final double? basisPct;
  final double? fundingRate;
  final double? openInterest;
  final double? volume24h;

  factory TickerEntry.fromJson(Map<String, dynamic> json) {
    return TickerEntry(
      symbol: json['symbol']?.toString() ?? 'N/A',
      venue: json['venue']?.toString(),
      price: (json['price'] as num?)?.toDouble(),
      indexPrice: (json['index_price'] as num?)?.toDouble(),
      basis: (json['basis'] as num?)?.toDouble(),
      basisPct: (json['basis_pct'] as num?)?.toDouble(),
      fundingRate: (json['funding_rate'] as num?)?.toDouble(),
      openInterest: (json['open_interest'] as num?)?.toDouble(),
      volume24h: (json['volume_24h'] as num?)?.toDouble(),
    );
  }
}

class FundingSnapshot {
  FundingSnapshot({
    required this.symbol,
    this.venue,
    this.fundingRate,
    this.estimatedApr,
  });

  final String symbol;
  final String? venue;
  final double? fundingRate;
  final double? estimatedApr;

  factory FundingSnapshot.fromJson(Map<String, dynamic> json) {
    return FundingSnapshot(
      symbol: json['symbol']?.toString() ?? 'N/A',
      venue: json['venue']?.toString(),
      fundingRate: (json['funding_rate'] as num?)?.toDouble(),
      estimatedApr: (json['estimated_apr'] as num?)?.toDouble(),
    );
  }
}

class TickerSnapshot {
  TickerSnapshot({
    this.generatedAt,
    required this.tickers,
    required this.mostPositiveFunding,
    required this.mostNegativeFunding,
  });

  final double? generatedAt;
  final List<TickerEntry> tickers;
  final List<FundingSnapshot> mostPositiveFunding;
  final List<FundingSnapshot> mostNegativeFunding;

  factory TickerSnapshot.fromJson(Map<String, dynamic> json) {
    final funding = json['funding_extremes'] as Map<String, dynamic>? ?? {};
    return TickerSnapshot(
      generatedAt: (json['generated_at'] as num?)?.toDouble(),
      tickers: (json['tickers'] as List<dynamic>? ?? [])
          .map((e) => TickerEntry.fromJson(e as Map<String, dynamic>))
          .toList(),
      mostPositiveFunding: (funding['most_positive'] as List<dynamic>? ?? [])
          .map((e) => FundingSnapshot.fromJson(e as Map<String, dynamic>))
          .toList(),
      mostNegativeFunding: (funding['most_negative'] as List<dynamic>? ?? [])
          .map((e) => FundingSnapshot.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class AssistDriver {
  AssistDriver({required this.label, this.detail, this.impact});

  final String label;
  final String? detail;
  final String? impact;

  factory AssistDriver.fromJson(Map<String, dynamic> json) {
    return AssistDriver(
      label: json['label']?.toString() ?? 'driver',
      detail: json['detail']?.toString(),
      impact: json['impact']?.toString(),
    );
  }
}

class AssistSnapshot {
  AssistSnapshot({
    this.timestamp,
    this.market,
    this.selectedPlatform,
    required this.drivers,
    required this.riskFlags,
    required this.news,
    this.summary,
    this.confidence,
    this.suggestions = const [],
  });

  final double? timestamp;
  final String? market;
  final String? selectedPlatform;
  final List<AssistDriver> drivers;
  final List<Map<String, dynamic>> riskFlags;
  final List<Map<String, dynamic>> news;
  final String? summary;
  final double? confidence;
  final List<Map<String, dynamic>> suggestions;

  factory AssistSnapshot.fromJson(Map<String, dynamic> json) {
    return AssistSnapshot(
      timestamp: (json['timestamp'] as num?)?.toDouble(),
      market: json['market']?.toString(),
      selectedPlatform: json['selected_platform']?.toString(),
      drivers: (json['drivers'] as List<dynamic>? ?? [])
          .map((e) => AssistDriver.fromJson(e as Map<String, dynamic>))
          .toList(),
      riskFlags: (json['risk_flags'] as List<dynamic>? ?? [])
          .map((e) => (e as Map<String, dynamic>?) ?? {})
          .toList(),
      news: (json['news'] as List<dynamic>? ?? [])
          .map((e) => (e as Map<String, dynamic>?) ?? {})
          .toList(),
      summary: json['summary']?.toString(),
      confidence: (json['confidence'] as num?)?.toDouble(),
      suggestions: (json['suggestions'] as List<dynamic>? ?? [])
          .map((e) => (e as Map<String, dynamic>?) ?? {})
          .toList(),
    );
  }
}

class HoverCardData {
  HoverCardData({required this.label, this.value, this.detail});

  final String label;
  final dynamic value;
  final String? detail;

  factory HoverCardData.fromJson(Map<String, dynamic> json) {
    return HoverCardData(
      label: json['label']?.toString() ?? 'metric',
      value: json['value'],
      detail: json['detail']?.toString(),
    );
  }
}

class HoverMetadata {
  HoverMetadata({
    this.timestamp,
    this.market,
    this.oracleGap,
    required this.cards,
    required this.riskFlags,
  });

  final double? timestamp;
  final String? market;
  final double? oracleGap;
  final List<HoverCardData> cards;
  final List<Map<String, dynamic>> riskFlags;

  factory HoverMetadata.fromJson(Map<String, dynamic> json) {
    return HoverMetadata(
      timestamp: (json['timestamp'] as num?)?.toDouble(),
      market: json['market']?.toString(),
      oracleGap: (json['oracle_gap'] as num?)?.toDouble(),
      cards: (json['hover_cards'] as List<dynamic>? ?? [])
          .map((e) => HoverCardData.fromJson(e as Map<String, dynamic>))
          .toList(),
      riskFlags: (json['risk_flags'] as List<dynamic>? ?? [])
          .map((e) => e as Map<String, dynamic>)
          .toList(),
    );
  }
}

class LineageEvent {
  LineageEvent({
    required this.agentId,
    required this.role,
    required this.event,
    required this.timestamp,
    required this.score,
  });

  final String agentId;
  final String role;
  final String event;
  final double timestamp;
  final double score;

  factory LineageEvent.fromJson(Map<String, dynamic> json) {
    return LineageEvent(
      agentId: json['agent_id']?.toString() ?? '',
      role: json['role']?.toString() ?? 'agent',
      event: json['event']?.toString() ?? 'spawn',
      timestamp: (json['timestamp'] as num?)?.toDouble() ?? 0,
      score: (json['score'] as num?)?.toDouble() ?? 0,
    );
  }
}

class SwarmAgent {
  SwarmAgent({
    required this.agentId,
    required this.role,
    required this.expertise,
    required this.votes,
  });

  final String agentId;
  final String role;
  final double expertise;
  final int votes;

  factory SwarmAgent.fromJson(Map<String, dynamic> json) {
    return SwarmAgent(
      agentId: json['agent_id']?.toString() ?? '',
      role: json['role']?.toString() ?? 'agent',
      expertise: (json['expertise'] as num?)?.toDouble() ?? 0,
      votes: (json['votes'] as num?)?.toInt() ?? 0,
    );
  }
}

class SwarmSnapshot {
  SwarmSnapshot({
    required this.agents,
    required this.totalAgents,
    required this.activeAgents,
  });

  final List<SwarmAgent> agents;
  final int totalAgents;
  final int activeAgents;

  factory SwarmSnapshot.fromJson(Map<String, dynamic> json) {
    return SwarmSnapshot(
      agents: (json['agents'] as List<dynamic>? ?? [])
          .map((e) => SwarmAgent.fromJson(e as Map<String, dynamic>))
          .toList(),
      totalAgents: (json['total'] as num?)?.toInt() ?? 0,
      activeAgents: (json['active'] as num?)?.toInt() ?? 0,
    );
  }
}

class SwarmTreeNode {
  SwarmTreeNode({required this.agent}) : children = [];

  final SwarmAgent agent;
  final List<SwarmTreeNode> children;
}

class MARLMetrics {
  MARLMetrics({
    required this.status,
    required this.algorithm,
    required this.agents,
  });

  final String status;
  final String algorithm;
  final List<MARLAgentMetrics> agents;

  factory MARLMetrics.fromJson(Map<String, dynamic> json) {
    final metrics = json['metrics'] as Map<String, dynamic>? ?? {};
    return MARLMetrics(
      status: json['status']?.toString() ?? 'not_initialized',
      algorithm: metrics['algorithm']?.toString() ?? 'unknown',
      agents: (metrics['agents'] as List<dynamic>? ?? [])
          .map((e) => MARLAgentMetrics.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class MARLAgentMetrics {
  MARLAgentMetrics({
    required this.agentId,
    required this.epsilon,
    required this.totalReward,
    required this.episodeCount,
    required this.memorySize,
  });

  final String agentId;
  final double epsilon;
  final double totalReward;
  final int episodeCount;
  final int memorySize;

  factory MARLAgentMetrics.fromJson(Map<String, dynamic> json) {
    return MARLAgentMetrics(
      agentId: json['agent_id']?.toString() ?? '',
      epsilon: (json['epsilon'] as num?)?.toDouble() ?? 0,
      totalReward: (json['total_reward'] as num?)?.toDouble() ?? 0,
      episodeCount: (json['episode_count'] as num?)?.toInt() ?? 0,
      memorySize: (json['memory_size'] as num?)?.toInt() ?? 0,
    );
  }
}

class PSOMetrics {
  PSOMetrics({
    required this.status,
    required this.iteration,
    required this.globalBestFitness,
    required this.numParticles,
    required this.fitnessHistory,
    required this.diversityHistory,
  });

  final String status;
  final int iteration;
  final double globalBestFitness;
  final int numParticles;
  final List<double> fitnessHistory;
  final List<double> diversityHistory;

  factory PSOMetrics.fromJson(Map<String, dynamic> json) {
    final metrics = json['metrics'] as Map<String, dynamic>? ?? {};
    return PSOMetrics(
      status: json['status']?.toString() ?? 'not_initialized',
      iteration: (metrics['iteration'] as num?)?.toInt() ?? 0,
      globalBestFitness:
          (metrics['global_best_fitness'] as num?)?.toDouble() ?? 0,
      numParticles: (metrics['num_particles'] as num?)?.toInt() ?? 0,
      fitnessHistory: (metrics['fitness_history'] as List<dynamic>? ?? [])
          .map((e) => (e as num).toDouble())
          .toList(),
      diversityHistory: (metrics['diversity_history'] as List<dynamic>? ?? [])
          .map((e) => (e as num).toDouble())
          .toList(),
    );
  }
}

class SourceHealth {
  SourceHealth({
    required this.source,
    required this.srw,
    required this.successRate,
    required this.fallbackRate,
    required this.avgLatencyMs,
    required this.totalCalls,
  });

  final String source;
  final double srw;
  final double successRate;
  final double fallbackRate;
  final double avgLatencyMs;
  final int totalCalls;

  factory SourceHealth.fromJson(Map<String, dynamic> json) {
    return SourceHealth(
      source: json['source']?.toString() ?? '',
      srw: (json['srw'] as num?)?.toDouble() ?? 0,
      successRate: (json['success_rate'] as num?)?.toDouble() ?? 0,
      fallbackRate: (json['fallback_rate'] as num?)?.toDouble() ?? 0,
      avgLatencyMs: (json['avg_latency_ms'] as num?)?.toDouble() ?? 0,
      totalCalls: (json['total_calls'] as num?)?.toInt() ?? 0,
    );
  }
}

class AgentTrust {
  AgentTrust({
    required this.agentId,
    required this.trust,
    required this.accuracy,
    required this.totalVotes,
    required this.correctVotes,
  });

  final String agentId;
  final double trust;
  final double accuracy;
  final int totalVotes;
  final int correctVotes;

  factory AgentTrust.fromJson(Map<String, dynamic> json) {
    return AgentTrust(
      agentId: json['agent_id']?.toString() ?? '',
      trust: (json['trust'] as num?)?.toDouble() ?? 0,
      accuracy: (json['accuracy'] as num?)?.toDouble() ?? 0,
      totalVotes: (json['total_votes'] as num?)?.toInt() ?? 0,
      correctVotes: (json['correct_votes'] as num?)?.toInt() ?? 0,
    );
  }
}

class ConsensusHistory {
  ConsensusHistory({
    required this.market,
    required this.timestamp,
    required this.consensusScore,
    required this.confidence,
    required this.approved,
    required this.poisoningDetected,
    required this.degradedMode,
  });

  final String market;
  final double timestamp;
  final double consensusScore;
  final double confidence;
  final bool approved;
  final bool poisoningDetected;
  final bool degradedMode;

  factory ConsensusHistory.fromJson(Map<String, dynamic> json) {
    return ConsensusHistory(
      market: json['market']?.toString() ?? '',
      timestamp: (json['timestamp'] as num?)?.toDouble() ?? 0,
      consensusScore: (json['consensus_score'] as num?)?.toDouble() ?? 0,
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0,
      approved: json['approved'] as bool? ?? false,
      poisoningDetected: json['poisoning_detected'] as bool? ?? false,
      degradedMode: json['degraded_mode'] as bool? ?? false,
    );
  }
}

class HardeningStatus {
  HardeningStatus({
    required this.trustUpdatesFrozen,
    required this.poisoningAlertCount,
    required this.temporalProfilesTracked,
    required this.shadowDivergenceSuspected,
  });

  final bool trustUpdatesFrozen;
  final int poisoningAlertCount;
  final int temporalProfilesTracked;
  final bool shadowDivergenceSuspected;

  factory HardeningStatus.fromJson(Map<String, dynamic> json) {
    return HardeningStatus(
      trustUpdatesFrozen: json['trust_updates_frozen'] as bool? ?? false,
      poisoningAlertCount:
          (json['poisoning_alert_count'] as num?)?.toInt() ?? 0,
      temporalProfilesTracked:
          (json['temporal_profiles_tracked'] as num?)?.toInt() ?? 0,
      shadowDivergenceSuspected:
          json['shadow_divergence_suspected'] as bool? ?? false,
    );
  }
}

class _DecayContext {
  const _DecayContext({
    required this.decayed,
    required this.original,
    required this.display,
    required this.originalDisplay,
    required this.ageBlocks,
  });

  final double decayed;
  final double original;
  final String display;
  final String originalDisplay;
  final int? ageBlocks;
}

class _PlatformContext {
  const _PlatformContext({
    required this.platforms,
    required this.selected,
    required this.hybrid,
    required this.arbitrageGap,
  });

  final List<String> platforms;
  final String? selected;
  final bool hybrid;
  final double? arbitrageGap;

  bool get hasData => platforms.isNotEmpty || selected != null || hybrid;
}

class MeridApp extends StatelessWidget {
  const MeridApp({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: const Color(0xFF020617),
      primaryColor: const Color(0xFF10B981),
      colorScheme: const ColorScheme.dark(
        primary: Color(0xFF10B981),
        secondary: Color(0xFFF59E0B),
        error: Color(0xFFF43F5E),
        surface: Color(0xFF0F172A),
      ),
      textTheme: GoogleFonts.jetBrainsMonoTextTheme(
        Theme.of(context).textTheme.apply(
              bodyColor: const Color(0xFFE2E8F0),
              displayColor: const Color(0xFFE2E8F0),
            ),
      ),
      useMaterial3: true,
    );

    return MaterialApp(
      title: 'MERID v2.0',
      debugShowCheckedModeBanner: false,
      theme: theme,
      home: const ControlStation(),
    );
  }
}

class SimulationBlock {
  final int index;
  final String hash;
  final double timestamp;
  final String? miner;
  final List<SimulationResult> simulations;

  SimulationBlock({
    required this.index,
    required this.hash,
    required this.timestamp,
    required this.simulations,
    this.miner,
  });

  factory SimulationBlock.fromJson(Map<String, dynamic> json) {
    final sims = (json['simulations'] as List<dynamic>? ?? [])
        .map((e) => SimulationResult.fromJson(e as Map<String, dynamic>))
        .toList();
    return SimulationBlock(
      index: json['index'] as int,
      hash: json['hash'] as String,
      timestamp: (json['timestamp'] as num).toDouble(),
      miner: json['miner'] as String?,
      simulations: sims,
    );
  }
}

class SimulationResult {
  final String simId;
  final double confidence;
  final List<SimulationOutcome> outcomes;
  final Map<String, dynamic> data;

  SimulationResult({
    required this.simId,
    required this.confidence,
    required this.outcomes,
    required this.data,
  });

  factory SimulationResult.fromJson(Map<String, dynamic> json) {
    final outs = (json['outcomes'] as List<dynamic>? ?? [])
        .map((e) => SimulationOutcome.fromJson(e as Map<String, dynamic>))
        .toList();
    return SimulationResult(
      simId: json['sim_id'] as String,
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0,
      outcomes: outs,
      data: (json['data'] as Map<String, dynamic>? ?? {})
          .map((key, value) => MapEntry(key, value)),
    );
  }
}

class SimulationOutcome {
  final String outcome;
  final double weight;
  final double expectedValue;
  final String finalExplanation;

  SimulationOutcome({
    required this.outcome,
    required this.weight,
    required this.expectedValue,
    required this.finalExplanation,
  });

  factory SimulationOutcome.fromJson(Map<String, dynamic> json) {
    return SimulationOutcome(
      outcome: json['outcome'] as String,
      weight: (json['weight'] as num?)?.toDouble() ?? 0,
      expectedValue: (json['expected_value'] as num?)?.toDouble() ?? 0,
      finalExplanation: json['final_explanation'] as String? ?? '',
    );
  }
}

class TokenSnapshot {
  final double totalSupply;
  final Map<String, double> balances;

  TokenSnapshot({
    required this.totalSupply,
    required this.balances,
  });

  factory TokenSnapshot.fromJson(Map<String, dynamic> json) {
    final balancesRaw = json['balances'] as Map<String, dynamic>? ?? {};
    final parsed = balancesRaw.map(
      (key, value) => MapEntry(key, (value as num?)?.toDouble() ?? 0),
    );
    return TokenSnapshot(
      totalSupply: (json['total_supply'] as num?)?.toDouble() ?? 0,
      balances: parsed,
    );
  }
}

extension _FirstOrNull<T> on List<T> {
  T? get firstOrNull => isEmpty ? null : first;
}

class GamificationEntry {
  GamificationEntry({
    required this.user,
    required this.xp,
    this.tokenBalance,
  });

  final String user;
  final int xp;
  final double? tokenBalance;

  factory GamificationEntry.fromJson(Map<String, dynamic> json) {
    return GamificationEntry(
      user: json['user'] as String? ?? 'unknown',
      xp: json['xp'] is int
          ? json['xp'] as int
          : int.tryParse(json['xp']?.toString() ?? '0') ?? 0,
      tokenBalance: (json['token_balance'] as num?)?.toDouble(),
    );
  }
}

class ControlStation extends StatefulWidget {
  const ControlStation({super.key});

  @override
  State<ControlStation> createState() => _ControlStationState();
}

class _ControlStationState extends State<ControlStation> {
  String _rawCognition = "";
  String _distilledOutput = "SYSTEM NOMINAL // WAITING FOR INPUT";
  bool _isLockdown = false;
  final TextEditingController _inputController = TextEditingController();
  final TextEditingController _userHandleController =
      TextEditingController(text: "operator");
  final TextEditingController _walletController = TextEditingController();
  final TextEditingController _emailController = TextEditingController();
  final TextEditingController _telegramController = TextEditingController();
  final TextEditingController _xHandleController = TextEditingController();
  final TextEditingController _filterFocusController = TextEditingController();
  bool _isLoading = false;
  final TextEditingController _captchaController =
      TextEditingController(text: "dev-mode");
  final List<SimulationBlock> _recentBlocks = [];
  TokenSnapshot? _tokenSnapshot;
  List<GamificationEntry> _leaderboard = [];
  Timer? _simulationTimer;
  bool _simulationError = false;
  bool _isMining = false;
  bool _connectBusy = false;
  bool _filterBusy = false;
  String? _connectStatus;
  String? _filterStatus;
  double _filterRisk = 0.5;
  HeatmapSnapshot? _heatmapSnapshot;
  TickerSnapshot? _tickerSnapshot;
  AssistSnapshot? _assistSnapshot;
  HoverMetadata? _hoverMetadata;
  SwarmSnapshot? _swarmSnapshot;
  final List<LineageEvent> _lineageEvents = [];
  MARLMetrics? _marlMetrics;
  PSOMetrics? _psoMetrics;
  Map<String, SourceHealth> _sourceHealth = {};
  Map<String, AgentTrust> _agentTrust = {};
  List<ConsensusHistory> _consensusHistory = [];
  HardeningStatus? _hardeningStatus;

  static const String _apiBase = 'http://127.0.0.1:8000/api/v1';
  static const String _vpnHeaderName = 'X-VPN-STATUS';
  static const String _vpnHeaderValue = 'verified';

  Future<void> _queryOllama(String input) async {
    setState(() {
      _isLoading = true;
      _rawCognition = "";
      _distilledOutput = "Processing...";
    });

    final url = Uri.parse('http://localhost:11434/api/generate');
    final body =
        json.encode({"model": "gemma3:1b", "prompt": input, "stream": false});

    try {
      final response = await http
          .post(url, body: body, headers: {'Content-Type': 'application/json'});
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        setState(() {
          _rawCognition = data['response'] ?? "No response";
          _distilledOutput = _rawCognition.length > 400
              ? "${_rawCognition.substring(0, 400)}..."
              : _rawCognition;
        });
      } else {
        setState(() {
          _distilledOutput = "Error: ${response.statusCode}";
        });
      }
    } catch (e) {
      setState(() {
        _distilledOutput =
            "Connection failed. Is Ollama running with 'ollama serve'?";
      });
    } finally {
      setState(() => _isLoading = false);
    }
  }

  @override
  void initState() {
    super.initState();
    _startSimulationPolling();
    _fetchLeaderboard();
  }

  @override
  void dispose() {
    _simulationTimer?.cancel();
    _inputController.dispose();
    _userHandleController.dispose();
    _walletController.dispose();
    _emailController.dispose();
    _telegramController.dispose();
    _xHandleController.dispose();
    _filterFocusController.dispose();
    _captchaController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _buildHeader(),
              const SizedBox(height: 20),
              _buildBusMixer(),
              const SizedBox(height: 20),
              _buildSimulationPanel(),
              const SizedBox(height: 20),
              _buildDistillationGate(),
              const SizedBox(height: 20),
              _buildGamificationPanel(),
              const Spacer(),
              _buildFooter(),
            ],
          ),
        ),
      ),
      floatingActionButton: FloatingActionButton(
        backgroundColor:
            _isLockdown ? const Color(0xFFF43F5E) : const Color(0xFF10B981),
        onPressed: () {
          setState(() {
            _isLockdown = !_isLockdown;
            if (_isLockdown) {
              _distilledOutput =
                  "!!! SYSTEM CONTAINED — ALL EXECUTION FROZEN !!!";
            } else {
              _distilledOutput = "SYSTEM NOMINAL // WAITING FOR INPUT";
            }
          });
        },
        child: Text(_isLockdown ? "UNLOCK" : "LOCKDOWN",
            style: const TextStyle(color: Colors.white)),
      ),
    );
  }

  void _startSimulationPolling() {
    _fetchLatestBlock();
    _fetchTokenSnapshot();
    _fetchLeaderboard();
    _fetchHeatmap();
    _fetchTicker();
    _fetchAssist();
    _fetchHoverMetadata();
    _fetchSwarmSnapshot();
    _fetchLineageEvents();
    _fetchMARLMetrics();
    _fetchPSOMetrics();
    _fetchSourceHealth();
    _fetchAgentTrust();
    _fetchConsensusHistory();
    _fetchHardeningStatus();
    _simulationTimer?.cancel();
    _simulationTimer = Timer.periodic(const Duration(seconds: 20), (_) {
      _fetchLatestBlock();
      _fetchTokenSnapshot();
      _fetchLeaderboard();
      _fetchMARLMetrics();
      _fetchPSOMetrics();
      _fetchSourceHealth();
      _fetchAgentTrust();
      _fetchConsensusHistory();
      _fetchHardeningStatus();
    });
  }

  Future<void> _fetchLatestBlock() async {
    try {
      final response = await http.get(Uri.parse('$_apiBase/blocks/latest'));
      if (response.statusCode != 200) {
        setState(() => _simulationError = true);
        return;
      }
      final data = json.decode(response.body) as Map<String, dynamic>;
      final block = SimulationBlock.fromJson(data);
      setState(() {
        _simulationError = false;
        final exists = _recentBlocks.any((b) => b.index == block.index);
        if (!exists) {
          _recentBlocks.add(block);
          _recentBlocks.sort((a, b) => b.index.compareTo(a.index));
          if (_recentBlocks.length > 5) {
            _recentBlocks.removeLast();
          }
        }
      });
    } catch (_) {
      setState(() => _simulationError = true);
    }
  }

  Future<void> _fetchTokenSnapshot() async {
    try {
      final response = await http.get(Uri.parse('$_apiBase/tokens/balances'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      setState(() {
        _tokenSnapshot = TokenSnapshot.fromJson(data);
      });
    } catch (_) {
      // ignore silently for now
    }
  }

  Future<void> _triggerSimulationCycle() async {
    setState(() {
      _isMining = true;
    });
    try {
      final response = await http.post(
        Uri.parse('$_apiBase/mine'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({'premium': true, 'miner_id': 'flutter_dashboard'}),
      );
      if (response.statusCode != 200 && response.statusCode != 202) {
        _showSnack('Failed to trigger simulation (${response.statusCode})');
      } else {
        _showSnack('Simulation mining queued.');
      }
    } catch (e) {
      _showSnack('Error triggering simulation: $e');
    } finally {
      setState(() {
        _isMining = false;
      });
    }
  }

  void _showSnack(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  Future<void> _fetchLeaderboard() async {
    try {
      final response =
          await http.get(Uri.parse('$_apiBase/leaderboard?limit=10'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      final items = (data['items'] as List<dynamic>? ?? [])
          .map((e) => GamificationEntry.fromJson(e as Map<String, dynamic>))
          .toList();
      setState(() {
        _leaderboard = items;
      });
    } catch (_) {
      // ignore leaderboard failures for now
    }
  }

  Future<void> _fetchMARLMetrics() async {
    try {
      final response = await http.get(Uri.parse('$_apiBase/marl/metrics'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      setState(() {
        _marlMetrics = MARLMetrics.fromJson(data);
      });
    } catch (_) {
      // ignore errors
    }
  }

  Future<void> _fetchPSOMetrics() async {
    try {
      final response = await http.get(Uri.parse('$_apiBase/pso/metrics'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      setState(() {
        _psoMetrics = PSOMetrics.fromJson(data);
      });
    } catch (_) {
      // ignore errors
    }
  }

  Future<void> _fetchSourceHealth() async {
    try {
      final response =
          await http.get(Uri.parse('$_apiBase/observability/sources'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      final sources = (data['sources'] as Map<String, dynamic>? ?? {}).map((key,
              value) =>
          MapEntry(key, SourceHealth.fromJson(value as Map<String, dynamic>)));
      setState(() {
        _sourceHealth = sources;
      });
    } catch (_) {
      // ignore errors
    }
  }

  Future<void> _fetchAgentTrust() async {
    try {
      final response =
          await http.get(Uri.parse('$_apiBase/observability/agents/trust'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      final agents = (data['agents'] as Map<String, dynamic>? ?? {}).map((key,
              value) =>
          MapEntry(key, AgentTrust.fromJson(value as Map<String, dynamic>)));
      setState(() {
        _agentTrust = agents;
      });
    } catch (_) {
      // ignore errors
    }
  }

  Future<void> _fetchConsensusHistory() async {
    try {
      final response = await http
          .get(Uri.parse('$_apiBase/observability/consensus/history?limit=30'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      final history = (data['history'] as List<dynamic>? ?? [])
          .map((e) => ConsensusHistory.fromJson(e as Map<String, dynamic>))
          .toList();
      setState(() {
        _consensusHistory = history;
      });
    } catch (_) {
      // ignore errors
    }
  }

  Future<void> _fetchHardeningStatus() async {
    try {
      final response =
          await http.get(Uri.parse('$_apiBase/observability/hardening/status'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      setState(() {
        _hardeningStatus = HardeningStatus.fromJson(data);
      });
    } catch (_) {
      // ignore errors
    }
  }

  Future<void> _fetchHeatmap() async {
    try {
      final response = await http.get(Uri.parse('$_apiBase/heatmap?limit=40'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      setState(() {
        _heatmapSnapshot = HeatmapSnapshot.fromJson(data);
      });
    } catch (_) {
      // ignore errors
    }
  }

  Future<void> _fetchTicker() async {
    try {
      final response = await http.get(Uri.parse('$_apiBase/ticker?limit=25'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      setState(() {
        _tickerSnapshot = TickerSnapshot.fromJson(data);
      });
    } catch (_) {
      // ignore errors
    }
  }

  Future<void> _fetchAssist() async {
    try {
      final response = await http.get(Uri.parse('$_apiBase/assist'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      setState(() {
        _assistSnapshot = AssistSnapshot.fromJson(data);
      });
    } catch (_) {
      // ignore errors
    }
  }

  Future<void> _fetchHoverMetadata() async {
    try {
      final response = await http.get(Uri.parse('$_apiBase/hover'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      setState(() {
        _hoverMetadata = HoverMetadata.fromJson(data);
      });
    } catch (_) {
      // ignore errors
    }
  }

  Future<void> _fetchSwarmSnapshot() async {
    try {
      final response =
          await http.get(Uri.parse('$_apiBase/swarm/agents?limit=50'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      setState(() {
        _swarmSnapshot = SwarmSnapshot.fromJson(data);
      });
    } catch (_) {
      // ignore errors
    }
  }

  Future<void> _fetchLineageEvents() async {
    try {
      final response =
          await http.get(Uri.parse('$_apiBase/swarm/lineage?limit=100'));
      if (response.statusCode != 200) return;
      final data = json.decode(response.body) as Map<String, dynamic>;
      final events = (data['events'] as List<dynamic>? ?? [])
          .map((e) => LineageEvent.fromJson(e as Map<String, dynamic>))
          .toList();
      setState(() {
        _lineageEvents.clear();
        _lineageEvents.addAll(events);
      });
    } catch (_) {
      // ignore errors
    }
  }

  Future<void> _submitConnection() async {
    setState(() {
      _connectBusy = true;
      _connectStatus = null;
    });
    final captchaToken = _captchaController.text.trim().isEmpty
        ? null
        : _captchaController.text.trim();
    final payload = {
      "user_handle": _userHandleController.text.trim().isEmpty
          ? "operator"
          : _userHandleController.text.trim(),
      "wallet_address": _walletController.text.trim().isEmpty
          ? null
          : _walletController.text.trim(),
      "email": _emailController.text.trim().isEmpty
          ? null
          : _emailController.text.trim(),
      "telegram_handle": _telegramController.text.trim().isEmpty
          ? null
          : _telegramController.text.trim(),
      "x_handle": _xHandleController.text.trim().isEmpty
          ? null
          : _xHandleController.text.trim(),
      "captcha_token": captchaToken,
    };
    try {
      final response = await http.post(
        Uri.parse('$_apiBase/connect'),
        headers: {
          'Content-Type': 'application/json',
          _vpnHeaderName: _vpnHeaderValue,
        },
        body: json.encode(payload),
      );
      if (response.statusCode == 200) {
        final data = json.decode(response.body) as Map<String, dynamic>;
        setState(() {
          _connectStatus =
              "Connections updated. XP +${data['xp_awarded'] ?? 0}";
        });
        _fetchLeaderboard();
      } else {
        setState(() {
          _connectStatus = "Failed (${response.statusCode})";
        });
      }
    } catch (e) {
      setState(() {
        _connectStatus = "Error: $e";
      });
    } finally {
      setState(() {
        _connectBusy = false;
      });
    }
  }

  Future<void> _submitFilters() async {
    setState(() {
      _filterBusy = true;
      _filterStatus = null;
    });
    final captchaToken = _captchaController.text.trim().isEmpty
        ? null
        : _captchaController.text.trim();
    final payload = {
      "user_handle": _userHandleController.text.trim().isEmpty
          ? "operator"
          : _userHandleController.text.trim(),
      "filters": {
        "focus": _filterFocusController.text.trim(),
        "risk": _filterRisk.toStringAsFixed(2),
      },
      "captcha_token": captchaToken,
    };
    try {
      final response = await http.post(
        Uri.parse('$_apiBase/filters'),
        headers: {
          'Content-Type': 'application/json',
          _vpnHeaderName: _vpnHeaderValue,
        },
        body: json.encode(payload),
      );
      if (response.statusCode == 200) {
        final data = json.decode(response.body) as Map<String, dynamic>;
        setState(() {
          _filterStatus = "Filters saved. XP +${data['xp_awarded'] ?? 0}";
        });
        _fetchLeaderboard();
      } else {
        setState(() {
          _filterStatus = "Failed (${response.statusCode})";
        });
      }
    } catch (e) {
      setState(() {
        _filterStatus = "Error: $e";
      });
    } finally {
      setState(() {
        _filterBusy = false;
      });
    }
  }

  Widget _buildGamificationPanel() {
    return Card(
      elevation: 3,
      color: const Color(0xFF0F172A),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              "ENGAGEMENT & XP",
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            _buildLeaderboardList(),
            const SizedBox(height: 16),
            _buildConnectionForm(),
            const SizedBox(height: 16),
            _buildFilterForm(),
          ],
        ),
      ),
    );
  }

  Widget _buildLeaderboardList() {
    if (_leaderboard.isEmpty) {
      return const Text(
        "No XP activity yet. Connect accounts or save filters to earn XP.",
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("Leaderboard",
            style: TextStyle(fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        ..._leaderboard.take(5).map(
              (entry) => ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(entry.user),
                subtitle: entry.tokenBalance != null
                    ? Text(
                        "Token balance: ${entry.tokenBalance!.toStringAsFixed(2)}")
                    : const Text("Token data pending"),
                trailing: Text("${entry.xp} XP"),
              ),
            ),
      ],
    );
  }

  Widget _buildConnectionForm() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("Link Accounts",
            style: TextStyle(fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            SizedBox(
              width: 220,
              child: TextField(
                controller: _userHandleController,
                decoration: const InputDecoration(labelText: "User Handle"),
              ),
            ),
            SizedBox(
              width: 220,
              child: TextField(
                controller: _walletController,
                decoration: const InputDecoration(labelText: "Wallet (0x...)"),
              ),
            ),
            SizedBox(
              width: 220,
              child: TextField(
                controller: _emailController,
                decoration: const InputDecoration(labelText: "Email"),
              ),
            ),
            SizedBox(
              width: 220,
              child: TextField(
                controller: _telegramController,
                decoration:
                    const InputDecoration(labelText: "Telegram @handle"),
              ),
            ),
            SizedBox(
              width: 220,
              child: TextField(
                controller: _xHandleController,
                decoration: const InputDecoration(labelText: "X / Twitter"),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        ElevatedButton.icon(
          onPressed: _connectBusy ? null : _submitConnection,
          icon: _connectBusy
              ? const SizedBox(
                  height: 16,
                  width: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.link),
          label: const Text("Save Connections + Earn XP"),
        ),
        if (_connectStatus != null)
          Padding(
            padding: const EdgeInsets.only(top: 4.0),
            child: Text(
              _connectStatus!,
              style: const TextStyle(color: Colors.greenAccent),
            ),
          ),
      ],
    );
  }

  Widget _buildFilterForm() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text("Personalized Filters",
            style: TextStyle(fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        SizedBox(
          width: 320,
          child: TextField(
            controller: _filterFocusController,
            decoration: const InputDecoration(
              labelText: "Focus Tag (e.g. 'on-chain risk')",
            ),
          ),
        ),
        Row(
          children: [
            const Text("Risk Appetite"),
            Expanded(
              child: Slider(
                value: _filterRisk,
                onChanged: (value) => setState(() => _filterRisk = value),
              ),
            ),
            Text(_filterRisk.toStringAsFixed(2)),
          ],
        ),
        ElevatedButton.icon(
          onPressed: _filterBusy ? null : _submitFilters,
          icon: _filterBusy
              ? const SizedBox(
                  height: 16,
                  width: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.save),
          label: const Text("Save Filters + Earn XP"),
        ),
        if (_filterStatus != null)
          Padding(
            padding: const EdgeInsets.only(top: 4.0),
            child: Text(
              _filterStatus!,
              style: const TextStyle(color: Colors.greenAccent),
            ),
          ),
      ],
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(
          color: const Color(0xFF10B981).withValues(alpha: 0.5),
        ),
        color: const Color(0xFF0F172A),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text("MERID v2.0 // LOCAL",
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              Text("BRAIN: gemma3:1b",
                  style: TextStyle(fontSize: 10, color: Color(0xFF10B981))),
            ],
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              const Text("MAKER CONFIDENCE",
                  style: TextStyle(fontSize: 10, color: Color(0xFFF59E0B))),
              const SizedBox(height: 4),
              SizedBox(
                width: 100,
                height: 6,
                child: LinearProgressIndicator(
                  value: 0.89,
                  backgroundColor: Colors.black,
                  valueColor:
                      const AlwaysStoppedAnimation<Color>(Color(0xFFF59E0B)),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildBusMixer() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: Colors.white24),
        color: const Color(0xFF0F172A).withValues(alpha: 0.5),
      ),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text("> BUS HIERARCHY // MIXER",
              style: TextStyle(color: Color(0xFF10B981), fontSize: 12)),
          SizedBox(height: 15),
          Text("All buses active — governance enforced",
              style: TextStyle(fontSize: 11)),
        ],
      ),
    );
  }

  Widget _buildDistillationGate() {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          border: Border.all(color: Colors.white12),
          color: Colors.black26,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text("> DISTILLATION GATE",
                style: TextStyle(color: Color(0xFFF59E0B), fontSize: 12)),
            const Divider(color: Colors.white10),
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (_rawCognition.isNotEmpty) ...[
                      const Text("RAW COGNITION",
                          style: TextStyle(
                              color: Color(0xFFF59E0B), fontSize: 10)),
                      Text(_rawCognition,
                          style: const TextStyle(
                              color: Colors.white54, fontSize: 11)),
                      const SizedBox(height: 20),
                    ],
                    _buildIntelPanels(),
                    const SizedBox(height: 12),
                    const Text("DISTILLED OUTPUT",
                        style:
                            TextStyle(color: Color(0xFF10B981), fontSize: 10)),
                    Text(_distilledOutput,
                        style:
                            const TextStyle(color: Colors.white, fontSize: 13)),
                  ],
                ),
              ),
            ),
            if (_isLoading)
              const LinearProgressIndicator(color: Color(0xFFF59E0B)),
            TextField(
              controller: _inputController,
              enabled: !_isLockdown,
              decoration: const InputDecoration(
                hintText: "ENTER COMMAND OR QUERY...",
                hintStyle: TextStyle(color: Colors.white24, fontSize: 12),
                border: InputBorder.none,
                prefixIcon: Icon(Icons.chevron_right, color: Color(0xFF10B981)),
              ),
              style: const TextStyle(color: Colors.white, fontSize: 13),
              onSubmitted: (value) {
                if (value.isNotEmpty && !_isLockdown) {
                  _queryOllama(value);
                  _inputController.clear();
                }
              },
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFooter() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        ElevatedButton(
          onPressed: _isLockdown ? null : () => _queryOllama("Status Report"),
          child: const Text("STATUS REPORT"),
        ),
      ],
    );
  }

  Widget _buildSimulationPanel() {
    final latest = _recentBlocks.isNotEmpty ? _recentBlocks.first : null;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white12),
        color: const Color(0xFF020617),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                "> PROOF-OF-SIMULATION // SWARM LEDGER",
                style: TextStyle(color: Color(0xFF10B981), fontSize: 12),
              ),
              ElevatedButton(
                onPressed:
                    _isLockdown || _isMining ? null : _triggerSimulationCycle,
                child: Text(_isMining ? "MINING…" : "TRIGGER SIMULATION"),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (_simulationError)
            const Text(
              "STREAM OFFLINE // CHECK BACKEND",
              style: TextStyle(color: Color(0xFFF87171)),
            )
          else if (latest == null)
            const Text(
              "Awaiting first block...",
              style: TextStyle(color: Colors.white70),
            )
          else
            _buildLatestBlock(latest),
          const SizedBox(height: 12),
          _buildTokenEconomy(),
          const SizedBox(height: 12),
          _buildIntelStrip(),
          const SizedBox(height: 12),
          if (_recentBlocks.isNotEmpty) _buildRecentBlockList(),
        ],
      ),
    );
  }

  Widget _buildLatestBlock(SimulationBlock block) {
    final firstSim =
        block.simulations.isNotEmpty ? block.simulations.first : null;
    final oracle = _extractOracleContext(firstSim);
    final decay = _extractDecayContext(firstSim);
    final platform = _extractPlatformContext(firstSim);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          "LATEST BLOCK #${block.index} (${block.hash.substring(0, 8)}...)",
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 6),
        Text(
          "Miner: ${block.miner ?? 'dashboard'}   Confidence: ${(firstSim?.confidence ?? 0) * 100 ~/ 1}%",
          style: const TextStyle(color: Colors.white70, fontSize: 12),
        ),
        const SizedBox(height: 4),
        _buildDecayRow(decay),
        const SizedBox(height: 6),
        _buildOracleBadge(oracle),
        const SizedBox(height: 6),
        _buildPlatformBadges(platform),
        const SizedBox(height: 8),
        if (firstSim != null)
          _buildOutcomeChips(firstSim, oracle, decay, platform),
        const SizedBox(height: 12),
        _buildOraclePanel(oracle),
      ],
    );
  }

  Widget _buildOutcomeChips(SimulationResult sim, _OracleContext oracleContext,
      _DecayContext decayContext, _PlatformContext platformContext) {
    return Wrap(
      spacing: 8,
      runSpacing: 6,
      children: sim.outcomes
          .map(
            (o) => Chip(
              label: Text(
                "${o.outcome} ${(o.weight * 100).toStringAsFixed(1)}% | EV ${(o.expectedValue * 100).toStringAsFixed(1)}%\n"
                "Oracle gap: ${oracleContext.displayGap} • Decayed: ${decayContext.display}\n"
                "Platform: ${platformContext.selected ?? 'n/a'}",
              ),
            ),
          )
          .toList(),
    );
  }

  Widget _buildTokenEconomy() {
    if (_tokenSnapshot == null) {
      return const Text(
        "Loading token economy...",
        style: TextStyle(color: Colors.white54),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          "TOKEN ECONOMY",
          style: TextStyle(color: Color(0xFFF59E0B), fontSize: 12),
        ),
        const SizedBox(height: 4),
        Text(
          "Total Supply: ${_tokenSnapshot!.totalSupply.toStringAsFixed(2)} MRT",
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 4),
        Wrap(
          spacing: 8,
          children: _tokenSnapshot!.balances.entries
              .map(
                (entry) => Chip(
                  label:
                      Text("${entry.key}: ${entry.value.toStringAsFixed(2)}"),
                ),
              )
              .toList(),
        ),
      ],
    );
  }

  Widget _buildIntelPanels() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          "INTEL PANELS",
          style: TextStyle(color: Color(0xFF10B981), fontSize: 12),
        ),
        const SizedBox(height: 8),
        if (_heatmapSnapshot != null)
          Text(
            "Heatmap: ${_heatmapSnapshot!.liquidations.length} liquidations",
            style: const TextStyle(color: Colors.white70, fontSize: 11),
          ),
        if (_tickerSnapshot != null)
          Text(
            "Ticker: ${_tickerSnapshot!.tickers.length} tickers",
            style: const TextStyle(color: Colors.white70, fontSize: 11),
          ),
        if (_assistSnapshot != null)
          Text(
            "Assist: ${_assistSnapshot!.suggestions.length} suggestions",
            style: const TextStyle(color: Colors.white70, fontSize: 11),
          ),
      ],
    );
  }

  Widget _buildIntelStrip() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          "INTEL STRIP",
          style: TextStyle(color: Color(0xFF0EA5E9), fontSize: 12),
        ),
        const SizedBox(height: 8),
        if (_swarmSnapshot != null)
          Text(
            "Swarm: ${_swarmSnapshot!.activeAgents}/${_swarmSnapshot!.totalAgents} agents active",
            style: const TextStyle(color: Colors.white70, fontSize: 11),
          ),
        if (_lineageEvents.isNotEmpty)
          Text(
            "Lineage: ${_lineageEvents.length} events tracked",
            style: const TextStyle(color: Colors.white70, fontSize: 11),
          ),
        if (_marlMetrics != null)
          Text(
            "MARL: ${_marlMetrics!.status} (${_marlMetrics!.algorithm})",
            style: const TextStyle(color: Colors.white70, fontSize: 11),
          ),
        if (_psoMetrics != null)
          Text(
            "PSO: ${_psoMetrics!.status}",
            style: const TextStyle(color: Colors.white70, fontSize: 11),
          ),
        if (_sourceHealth.isNotEmpty)
          Text(
            "Sources: ${_sourceHealth.length} monitored",
            style: const TextStyle(color: Colors.white70, fontSize: 11),
          ),
        if (_agentTrust.isNotEmpty)
          Text(
            "Trust: ${_agentTrust.length} agents tracked",
            style: const TextStyle(color: Colors.white70, fontSize: 11),
          ),
        if (_consensusHistory.isNotEmpty)
          Text(
            "Consensus: ${_consensusHistory.length} history entries",
            style: const TextStyle(color: Colors.white70, fontSize: 11),
          ),
        if (_hardeningStatus != null)
          Text(
            "Hardening: ${_hardeningStatus!.poisoningAlertCount} alerts",
            style: const TextStyle(color: Colors.white70, fontSize: 11),
          ),
        if (_hoverMetadata != null)
          Text(
            "Hover: ${_hoverMetadata!.cards.length} cards",
            style: const TextStyle(color: Colors.white70, fontSize: 11),
          ),
      ],
    );
  }

  Widget _buildRecentBlockList() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          "RECENT BLOCKS",
          style: TextStyle(color: Colors.white70, fontSize: 12),
        ),
        const SizedBox(height: 8),
        ..._recentBlocks.map(
          (block) => Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(
              "#${block.index} — ${(block.simulations.firstOrNull?.confidence ?? 0) * 100 ~/ 1}% conf"
              " | decayed ${_extractDecayContext(block.simulations.firstOrNull).display}"
              " | gap ${_formatGap(_extractOracleContext(block.simulations.firstOrNull).gap)}"
              " // ${DateTime.fromMillisecondsSinceEpoch((block.timestamp * 1000).toInt()).toLocal()}",
              style: const TextStyle(color: Colors.white54, fontSize: 12),
            ),
          ),
        ),
      ],
    );
  }

  _OracleContext _extractOracleContext(SimulationResult? sim) {
    final data = sim?.data ?? {};
    final gap = (data['oracle_gap'] as num?)?.toDouble();
    final snapshotRaw =
        (data['oracle_snapshot'] as Map<String, dynamic>?) ?? const {};
    final feeds = snapshotRaw.map((key, value) {
      final feed = value as Map<String, dynamic>? ?? {};
      return MapEntry(
        key,
        _OracleFeed(
          name: feed['name']?.toString() ?? key,
          price: (feed['price'] as num?)?.toDouble(),
        ),
      );
    });
    return _OracleContext(gap: gap, feeds: feeds);
  }

  _DecayContext _extractDecayContext(SimulationResult? sim) {
    final data = sim?.data ?? {};
    final decayMeta = data['decay'] as Map<String, dynamic>? ?? {};
    final original = (decayMeta['original_confidence'] as num?)?.toDouble() ??
        (sim?.confidence ?? 0) * 100;
    double decayedValue;
    if (sim?.data != null &&
        sim!.data.containsKey('decayed_confidence') &&
        sim.data['decayed_confidence'] is num) {
      decayedValue = (sim.data['decayed_confidence'] as num).toDouble() * 100;
    } else if (decayMeta['decayed_confidence'] is num) {
      decayedValue = (decayMeta['decayed_confidence'] as num).toDouble() * 100;
    } else {
      decayedValue = original;
    }
    final ageBlocks = (decayMeta['age_blocks'] as num?)?.toInt();
    return _DecayContext(
      decayed: decayedValue,
      original: original,
      display: "${decayedValue.toStringAsFixed(1)}%",
      originalDisplay: "${original.toStringAsFixed(1)}%",
      ageBlocks: ageBlocks,
    );
  }

  _PlatformContext _extractPlatformContext(SimulationResult? sim) {
    final data = sim?.data ?? {};
    final platformsRaw = data['platforms'];
    final selected = data['selected_platform']?.toString();
    final hybrid = data['hybrid'] == true;
    final arbitrageGap = (data['arbitrage_gap'] as num?)?.toDouble();
    List<String> platforms = [];
    if (platformsRaw is List) {
      platforms = platformsRaw.map((e) => e.toString()).toList();
    } else if (selected != null) {
      platforms = [selected];
    }
    return _PlatformContext(
      platforms: platforms,
      selected: selected,
      hybrid: hybrid,
      arbitrageGap: arbitrageGap,
    );
  }

  Widget _buildOracleBadge(_OracleContext ctx) {
    final color = ctx.badgeColor;
    final label = ctx.badgeLabel;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: color.withValues(alpha: 0.2),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Text(
        "$label (${ctx.displayGap})",
        style:
            TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.bold),
      ),
    );
  }

  Widget _buildOraclePanel(_OracleContext ctx) {
    if (!ctx.hasData) {
      return Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: Colors.white12),
          color: Colors.black12,
        ),
        child: const Text(
          "Oracle anchor unavailable (legacy block).",
          style: TextStyle(color: Colors.white60, fontSize: 12),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.white12),
        color: Colors.black12,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            "CHAINLINK ANCHOR",
            style: TextStyle(color: Color(0xFF10B981), fontSize: 12),
          ),
          const SizedBox(height: 6),
          Text(
            "Reality gap: ${ctx.displayGap}",
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 6),
          ...ctx.feeds.entries.map(
            (entry) => Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Text(
                "${entry.value.name}: "
                "${entry.value.price != null ? "\$${entry.value.price!.toStringAsFixed(2)}" : "n/a"}",
                style: const TextStyle(color: Colors.white70, fontSize: 12),
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _formatGap(double? gap) {
    if (gap == null) return "N/A";
    return "${(gap * 100).toStringAsFixed(2)}%";
  }

  Widget _buildDecayRow(_DecayContext ctx) {
    return Row(
      children: [
        Text(
          "Decayed: ${ctx.display}",
          style: const TextStyle(color: Colors.white70, fontSize: 12),
        ),
        const SizedBox(width: 8),
        Text(
          "(orig ${ctx.originalDisplay}"
          "${ctx.ageBlocks != null ? ", age ${ctx.ageBlocks} blocks" : ""})",
          style: const TextStyle(color: Colors.white38, fontSize: 11),
        ),
      ],
    );
  }

  Widget _buildPlatformBadges(_PlatformContext ctx) {
    if (!ctx.hasData) {
      return const Text(
        "Platform: polymarket",
        style: TextStyle(color: Colors.white54, fontSize: 12),
      );
    }
    return Wrap(
      spacing: 8,
      runSpacing: 4,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        ...ctx.platforms.map(
          (platform) => Chip(
            label: Text(
              platform == ctx.selected ? "$platform (selected)" : platform,
            ),
          ),
        ),
        if (ctx.arbitrageGap != null)
          Text(
            "Arbitrage gap: ${(ctx.arbitrageGap! * 100).toStringAsFixed(2)}%",
            style: const TextStyle(color: Colors.white70, fontSize: 12),
          ),
      ],
    );
  }
}
