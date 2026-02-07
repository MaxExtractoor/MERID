import 'dart:convert';

import 'package:path/path.dart';
import 'package:sqflite/sqflite.dart';

class MeridDatabase {
  static final MeridDatabase _instance = MeridDatabase._internal();
  factory MeridDatabase() => _instance;
  MeridDatabase._internal();

  static Database? _database;

  Future<Database> get database async {
    if (_database != null) return _database!;
    _database = await _initDatabase();
    return _database!;
  }

  Future<Database> _initDatabase() async {
    final dbPath = await getDatabasesPath();
    final path = join(dbPath, 'merid.db');

    return await openDatabase(
      path,
      version: 1,
      onCreate: _onCreate,
    );
  }

  Future<void> _onCreate(Database db, int version) async {
    // Immutable Core Memory
    await db.execute('''
      CREATE TABLE immutable_core (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        value TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        signature TEXT
      )
    ''');

    // Append-Only Ledger
    await db.execute('''
      CREATE TABLE ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        layer TEXT NOT NULL,
        hash TEXT
      )
    ''');

    // Volatile Cache
    await db.execute('''
      CREATE TABLE volatile_cache (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        ttl INTEGER
      )
    ''');

    // EKG Metrics History
    await db.execute('''
      CREATE TABLE ekg_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entropy REAL NOT NULL,
        confidence REAL NOT NULL,
        bias REAL NOT NULL,
        evolution_score REAL NOT NULL,
        timestamp INTEGER NOT NULL
      )
    ''');

    // Message Bus Log
    await db.execute('''
      CREATE TABLE bus_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT NOT NULL,
        bus_level TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        priority TEXT NOT NULL,
        metadata TEXT
      )
    ''');

    // Port Status
    await db.execute('''
      CREATE TABLE ports (
        name TEXT PRIMARY KEY,
        tier INTEGER NOT NULL,
        status TEXT NOT NULL,
        last_check INTEGER,
        trust_score REAL
      )
    ''');

    // Maker Signature History
    await db.execute('''
      CREATE TABLE maker_signatures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signature_hash TEXT NOT NULL,
        confidence REAL NOT NULL,
        timestamp INTEGER NOT NULL,
        metadata TEXT
      )
    ''');

    // Market Data Cache
    await db.execute('''
      CREATE TABLE market_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        symbol TEXT NOT NULL,
        price REAL NOT NULL,
        timestamp INTEGER NOT NULL,
        metadata TEXT
      )
    ''');

    // Quantum Results Cache
    await db.execute('''
      CREATE TABLE quantum_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        algorithm TEXT NOT NULL,
        problem_type TEXT NOT NULL,
        result_json TEXT NOT NULL,
        uncertainty REAL NOT NULL,
        comparison_delta REAL,
        timestamp INTEGER NOT NULL
      )
    ''');
  }

  // Memory Operations
  Future<void> storeImmutable(String key, dynamic value,
      {String? signature}) async {
    final db = await database;
    await db.insert(
      'immutable_core',
      {
        'key': key,
        'value': value.toString(),
        'timestamp': DateTime.now().millisecondsSinceEpoch,
        'signature': signature,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<void> appendToLedger(String key, dynamic value, String layer) async {
    final db = await database;
    await db.insert('ledger', {
      'key': key,
      'value': value.toString(),
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'layer': layer,
      'hash': _hashValue(value.toString()),
    });
  }

  Future<void> cacheVolatile(String key, dynamic value, {int? ttl}) async {
    final db = await database;
    await db.insert(
      'volatile_cache',
      {
        'key': key,
        'value': value.toString(),
        'timestamp': DateTime.now().millisecondsSinceEpoch,
        'ttl': ttl,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<List<Map<String, dynamic>>> searchMemory(String query,
      {int limit = 10}) async {
    final db = await database;
    final results = await db.rawQuery('''
      SELECT * FROM (
        SELECT 'immutable' as source, key, value, timestamp FROM immutable_core
        UNION ALL
        SELECT 'ledger' as source, key, value, timestamp FROM ledger
      ) WHERE key LIKE ? OR value LIKE ?
      ORDER BY timestamp DESC
      LIMIT ?
    ''', ['%$query%', '%$query%', limit]);
    return results;
  }

  // EKG Metrics
  Future<void> recordEKGMetrics({
    required double entropy,
    required double confidence,
    required double bias,
    required double evolutionScore,
  }) async {
    final db = await database;
    await db.insert('ekg_metrics', {
      'entropy': entropy,
      'confidence': confidence,
      'bias': bias,
      'evolution_score': evolutionScore,
      'timestamp': DateTime.now().millisecondsSinceEpoch,
    });
  }

  Future<Map<String, dynamic>> getLatestEKGMetrics() async {
    final db = await database;
    final result = await db.query(
      'ekg_metrics',
      orderBy: 'timestamp DESC',
      limit: 1,
    );
    if (result.isEmpty) {
      return {
        'entropy': 0.0,
        'confidence': 0.0,
        'bias': 0.0,
        'evolution_score': 0.0,
      };
    }
    return result.first;
  }

  // Bus Messages
  Future<void> logBusMessage({
    required String sender,
    required String busLevel,
    required String content,
    required String priority,
    Map<String, dynamic>? metadata,
  }) async {
    final db = await database;
    await db.insert('bus_messages', {
      'sender': sender,
      'bus_level': busLevel,
      'content': content,
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'priority': priority,
      'metadata': metadata != null ? _mapToJson(metadata) : null,
    });
  }

  Future<List<Map<String, dynamic>>> getRecentBusMessages(
      {int limit = 50}) async {
    final db = await database;
    return await db.query(
      'bus_messages',
      orderBy: 'timestamp DESC',
      limit: limit,
    );
  }

  // Ports
  Future<void> updatePortStatus({
    required String name,
    required int tier,
    required String status,
    double? trustScore,
  }) async {
    final db = await database;
    await db.insert(
      'ports',
      {
        'name': name,
        'tier': tier,
        'status': status,
        'last_check': DateTime.now().millisecondsSinceEpoch,
        'trust_score': trustScore,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<List<Map<String, dynamic>>> getAllPorts() async {
    final db = await database;
    return await db.query('ports');
  }

  // Market Data
  Future<void> cacheMarketData({
    required String source,
    required String symbol,
    required double price,
    Map<String, dynamic>? metadata,
  }) async {
    final db = await database;
    await db.insert('market_data', {
      'source': source,
      'symbol': symbol,
      'price': price,
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'metadata': metadata != null ? _mapToJson(metadata) : null,
    });
  }

  Future<List<Map<String, dynamic>>> getMarketData(String symbol,
      {int limit = 100}) async {
    final db = await database;
    return await db.query(
      'market_data',
      where: 'symbol = ?',
      whereArgs: [symbol],
      orderBy: 'timestamp DESC',
      limit: limit,
    );
  }

  // Quantum Results
  Future<void> cacheQuantumResult({
    required String algorithm,
    required String problemType,
    required Map<String, dynamic> result,
    required double uncertainty,
    double? comparisonDelta,
  }) async {
    final db = await database;
    await db.insert('quantum_results', {
      'algorithm': algorithm,
      'problem_type': problemType,
      'result_json': _mapToJson(result),
      'uncertainty': uncertainty,
      'comparison_delta': comparisonDelta,
      'timestamp': DateTime.now().millisecondsSinceEpoch,
    });
  }

  String _hashValue(String value) {
    // Simple hash for demo - use crypto library in production
    return value.hashCode.toString();
  }

  String _mapToJson(Map<String, dynamic> map) {
    return jsonEncode(map);
  }
}
