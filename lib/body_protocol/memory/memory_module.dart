import 'dart:math';

class MemoryModule {
  final List<MemoryEntry> _immutableCore = [];
  final List<MemoryEntry> _appendOnlyLedger = [];
  final Map<String, dynamic> _volatileCache = {};
  
  final Random _random = Random();

  void storeImmutable(String key, dynamic value) {
    _immutableCore.add(MemoryEntry(
      key: key,
      value: value,
      timestamp: DateTime.now(),
      layer: MemoryLayer.immutable,
    ));
  }

  void appendToLedger(String key, dynamic value) {
    _appendOnlyLedger.add(MemoryEntry(
      key: key,
      value: value,
      timestamp: DateTime.now(),
      layer: MemoryLayer.ledger,
    ));
  }

  void cacheVolatile(String key, dynamic value) {
    _volatileCache[key] = value;
  }

  Map<String, dynamic> getEKGMetrics() {
    return {
      'entropy': 3.2 + _random.nextDouble() * 0.5,
      'confidence': 0.85 + _random.nextDouble() * 0.1,
      'bias': 0.1 + _random.nextDouble() * 0.1,
      'evolution_score': 0.78 + _random.nextDouble() * 0.15,
      'immutable_entries': _immutableCore.length,
      'ledger_entries': _appendOnlyLedger.length,
      'volatile_size_kb': _volatileCache.length * 0.5,
    };
  }

  List<MemoryEntry> searchMemory(String query, {int limit = 10}) {
    final allEntries = [..._immutableCore, ..._appendOnlyLedger];
    return allEntries
        .where((entry) => entry.key.contains(query) || entry.value.toString().contains(query))
        .take(limit)
        .toList();
  }

  void purgeVolatile() {
    _volatileCache.clear();
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
