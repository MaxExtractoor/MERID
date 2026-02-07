import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:merid/core/database.dart';
import 'package:merid/body_protocol/spine/message_bus.dart';

/// Market Data Service - Integrates with Binance and Polymarket
class MarketService {
  final MeridDatabase _db = MeridDatabase();
  final SpineMessageBus _bus = SpineMessageBus();

  // Credential proxy endpoints (would be configured via proxy in production)
  static const String _binanceApi = 'https://api.binance.com/api/v3';
  static const String _polymarketApi = 'https://clob.polymarket.com';

  /// Fetch price from Binance
  Future<double?> getBinancePrice(String symbol) async {
    try {
      final response = await http.get(
        Uri.parse('$_binanceApi/ticker/price?symbol=${symbol}USDT'),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final price = double.parse(data['price'] as String);

        // Cache market data
        await _db.cacheMarketData(
          source: 'binance',
          symbol: symbol,
          price: price,
        );

        return price;
      }
    } catch (e) {
      // Log error but don't throw
      _bus.send(BusMessage(
        sender: 'MARKET_SERVICE',
        busLevel: 'group',
        content: 'Binance API error: $e',
        timestamp: DateTime.now(),
        priority: BusPriority.high,
      ));
    }
    return null;
  }

  /// Fetch price from Polymarket (simplified - would use actual API)
  Future<double?> getPolymarketPrice(String marketId) async {
    final endpoint = Uri.parse('$_polymarketApi/markets/$marketId');
    try {
      // In production, this would call Polymarket API
      // For now, simulate with mock data
      await Future.delayed(const Duration(milliseconds: 200));

      // Log the intended endpoint so we exercise the configured base URL
      _bus.send(BusMessage(
        sender: 'MARKET_SERVICE',
        busLevel: 'group',
        content: 'Polymarket fetch (simulated)',
        timestamp: DateTime.now(),
        priority: BusPriority.normal,
        metadata: {
          'endpoint': endpoint.toString(),
          'market_id': marketId,
        },
      ));

      // Mock price (would be real API call)
      final price = 0.5 + (DateTime.now().millisecond % 100) / 1000.0;

      await _db.cacheMarketData(
        source: 'polymarket',
        symbol: marketId,
        price: price,
      );

      return price;
    } catch (e) {
      _bus.send(BusMessage(
        sender: 'MARKET_SERVICE',
        busLevel: 'group',
        content: 'Polymarket API error: $e',
        timestamp: DateTime.now(),
        priority: BusPriority.high,
      ));
    }
    return null;
  }

  /// Scan for time-gap exploits between Binance and Polymarket
  Future<MarketExploitResult> scanForExploits({
    required String symbol,
    required String marketId,
    int scenarios = 1000,
  }) async {
    final binancePrice = await getBinancePrice(symbol);
    final polymarketPrice = await getPolymarketPrice(marketId);

    if (binancePrice == null || polymarketPrice == null) {
      return MarketExploitResult(
        exploitDetected: false,
        timeGap: 0.0,
        potentialProfit: 0.0,
        confidence: 0.0,
        scenarios: scenarios,
        recommendation: 'Unable to fetch market data',
      );
    }

    // Calculate time gap (price divergence)
    final timeGap = (binancePrice - polymarketPrice).abs();
    final gapPercentage = (timeGap / binancePrice) * 100;

    // Simulate front-run scenarios
    final frontRunResults = _simulateFrontRun(
      binancePrice,
      polymarketPrice,
      scenarios: scenarios,
    );

    final exploitDetected =
        gapPercentage > 0.5 && frontRunResults.successRate > 0.6;
    final confidence =
        _calculateConfidence(gapPercentage, frontRunResults.successRate);

    final result = MarketExploitResult(
      exploitDetected: exploitDetected,
      timeGap: timeGap,
      gapPercentage: gapPercentage,
      potentialProfit: frontRunResults.avgProfit,
      confidence: confidence,
      scenarios: scenarios,
      successRate: frontRunResults.successRate,
      recommendation: exploitDetected
          ? 'Exploit detected - ADVISORY ONLY (no execution without approval)'
          : 'No significant exploit detected',
    );

    // Log to bus
    _bus.send(BusMessage(
      sender: 'MARKET_SERVICE',
      busLevel: exploitDetected ? 'governance' : 'group',
      content: result.recommendation,
      timestamp: DateTime.now(),
      priority: exploitDetected ? BusPriority.high : BusPriority.normal,
      metadata: result.toMap(),
    ));

    return result;
  }

  FrontRunSimulation _simulateFrontRun(
    double binancePrice,
    double polymarketPrice, {
    required int scenarios,
  }) {
    final profits = <double>[];
    int successes = 0;

    for (int i = 0; i < scenarios; i++) {
      // Simulate front-run attempt
      final slippage = (DateTime.now().millisecond % 50) / 1000.0;
      final profit = (binancePrice - polymarketPrice - slippage).abs();

      if (profit > 0.01) {
        successes++;
        profits.add(profit);
      }
    }

    final avgProfit = profits.isEmpty
        ? 0.0
        : profits.fold(0.0, (a, b) => a + b) / profits.length;

    return FrontRunSimulation(
      successRate: successes / scenarios,
      avgProfit: avgProfit,
      maxProfit:
          profits.isEmpty ? 0.0 : profits.reduce((a, b) => a > b ? a : b),
    );
  }

  double _calculateConfidence(double gapPercentage, double successRate) {
    // Confidence based on gap size and success rate
    final gapConfidence = (gapPercentage / 10.0).clamp(0.0, 1.0);
    return (gapConfidence * 0.6 + successRate * 0.4).clamp(0.0, 1.0);
  }

  /// Get historical market data
  Future<List<Map<String, dynamic>>> getHistoricalData(
    String symbol, {
    int limit = 100,
  }) async {
    return await _db.getMarketData(symbol, limit: limit);
  }
}

class MarketExploitResult {
  final bool exploitDetected;
  final double timeGap;
  final double? gapPercentage;
  final double potentialProfit;
  final double confidence;
  final int scenarios;
  final double? successRate;
  final String recommendation;

  MarketExploitResult({
    required this.exploitDetected,
    required this.timeGap,
    this.gapPercentage,
    required this.potentialProfit,
    required this.confidence,
    required this.scenarios,
    this.successRate,
    required this.recommendation,
  });

  Map<String, dynamic> toMap() {
    return {
      'exploit_detected': exploitDetected,
      'time_gap': timeGap,
      'gap_percentage': gapPercentage,
      'potential_profit': potentialProfit,
      'confidence': confidence,
      'scenarios': scenarios,
      'success_rate': successRate,
      'recommendation': recommendation,
    };
  }
}

class FrontRunSimulation {
  final double successRate;
  final double avgProfit;
  final double maxProfit;

  FrontRunSimulation({
    required this.successRate,
    required this.avgProfit,
    required this.maxProfit,
  });
}
