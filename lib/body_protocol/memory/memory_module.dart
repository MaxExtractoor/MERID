import 'dart:math';
import 'package:merid/core/database.dart';

class MemoryModule {
  final MeridDatabase _db = MeridDatabase();
  final Random _random = Random();

  Future<void> storeImmutable(String key, dynamic value,
      {String? signature}) async {
    await _db.storeImmutable(key, value, signature: signature);
  }

  Future<void> appendToLedger(String key, dynamic value,
      {String layer = 'ledger'}) async {
    await _db.appendToLedger(key, value, layer);
  }

  Future<void> cacheVolatile(String key, dynamic value, {int? ttl}) async {
    await _db.cacheVolatile(key, value, ttl: ttl);
  }

  Future<Map<String, dynamic>> getEKGMetrics() async {
    final latest = await _db.getLatestEKGMetrics();

    // Calculate current metrics with some variance
    final entropy = (latest['entropy'] as double? ?? 3.2) +
        (_random.nextDouble() - 0.5) * 0.3;
    final confidence = (latest['confidence'] as double? ?? 0.85) +
        (_random.nextDouble() - 0.5) * 0.1;
    final bias = (latest['bias'] as double? ?? 0.1) +
        (_random.nextDouble() - 0.5) * 0.05;
    final evolutionScore = (latest['evolution_score'] as double? ?? 0.78) +
        (_random.nextDouble() - 0.5) * 0.1;

    // Record new metrics
    await _db.recordEKGMetrics(
      entropy: entropy.clamp(0.0, 10.0),
      confidence: confidence.clamp(0.0, 1.0),
      bias: bias.clamp(0.0, 1.0),
      evolutionScore: evolutionScore.clamp(0.0, 1.0),
    );

    // Get counts
    final immutableCount = await _db.searchMemory('', limit: 1000);

    return {
      'entropy': entropy.clamp(0.0, 10.0),
      'confidence': confidence.clamp(0.0, 1.0),
      'bias': bias.clamp(0.0, 1.0),
      'evolution_score': evolutionScore.clamp(0.0, 1.0),
      'immutable_entries': immutableCount.length,
      'ledger_entries': immutableCount.length, // Approximate
      'volatile_size_kb': 0.0, // Can be calculated from cache
      'timestamp': DateTime.now().millisecondsSinceEpoch,
    };
  }

  Future<List<MemoryEntry>> searchMemory(String query, {int limit = 10}) async {
    final results = await _db.searchMemory(query, limit: limit);
    return results
        .map((row) => MemoryEntry(
              key: row['key'] as String,
              value: row['value'] as String,
              timestamp:
                  DateTime.fromMillisecondsSinceEpoch(row['timestamp'] as int),
              layer: row['source'] == 'immutable'
                  ? MemoryLayer.immutable
                  : MemoryLayer.ledger,
            ))
        .toList();
  }

  Future<void> purgeVolatile() async {
    // Clear volatile cache entries older than 1 hour
    // Implementation would delete from database
  }
}

class MemoryEntry {
  final String key;
  final dynamic value;
  final DateTime timestamp;
  final MemoryLayer layer;

  MemoryEntry({
    required this.key,
    required this.value,
    required this.timestamp,
    required this.layer,
  });
}

enum MemoryLayer {
  immutable,
  ledger,
  volatile,
}
