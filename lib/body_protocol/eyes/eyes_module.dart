import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:merid/core/database.dart';
import 'package:merid/body_protocol/spine/message_bus.dart';

class EyesModule {
  final MeridDatabase _db = MeridDatabase();
  final SpineMessageBus _bus = SpineMessageBus();

  /// Process input through tokenization and inspiration port
  Future<EyesOutput> processInput(String rawInput, {String? source}) async {
    // Tokenize input
    final tokens = _tokenize(rawInput);
    final hash = _hashInput(rawInput);

    // Check inspiration port for similar patterns
    final inspiration = await _checkInspirationPort(rawInput);

    // Store in volatile cache
    await _db.cacheVolatile('input_$hash', rawInput, ttl: 3600);

    // Send to bus
    _bus.send(BusMessage(
      sender: 'EYES',
      busLevel: 'individual',
      content: 'Input received: ${tokens.length} tokens',
      timestamp: DateTime.now(),
      priority: BusPriority.normal,
      metadata: {
        'hash': hash,
        'token_count': tokens.length,
        'source': source ?? 'direct',
        'inspiration_match': inspiration != null,
      },
    ));

    return EyesOutput(
      rawInput: rawInput,
      tokens: tokens,
      hash: hash,
      inspirationMatch: inspiration,
      timestamp: DateTime.now(),
    );
  }

  /// Tokenize input (simple whitespace-based, can be enhanced with NLP)
  List<String> _tokenize(String input) {
    return input
        .toLowerCase()
        .split(RegExp(r'\s+'))
        .where((token) => token.isNotEmpty)
        .toList();
  }

  /// Hash input for deduplication
  String _hashInput(String input) {
    final bytes = utf8.encode(input);
    final digest = sha256.convert(bytes);
    return digest.toString();
  }

  /// Check inspiration port for similar patterns
  Future<InspirationMatch?> _checkInspirationPort(String input) async {
    // Search memory for similar patterns
    final results = await _db.searchMemory(input, limit: 5);
    
    if (results.isEmpty) return null;

    // Simple similarity check (can be enhanced with embeddings)
    final tokens = _tokenize(input);
    for (var result in results) {
      final resultTokens = _tokenize(result['value'] as String);
      final similarity = _calculateSimilarity(tokens, resultTokens);
      
      if (similarity > 0.6) {
        return InspirationMatch(
          matchedValue: result['value'] as String,
          similarity: similarity,
          source: result['source'] as String,
        );
      }
    }

    return null;
  }

  /// Calculate token similarity (Jaccard index)
  double _calculateSimilarity(List<String> tokens1, List<String> tokens2) {
    final set1 = tokens1.toSet();
    final set2 = tokens2.toSet();
    final intersection = set1.intersection(set2).length;
    final union = set1.union(set2).length;
    return union > 0 ? intersection / union : 0.0;
  }

  /// Extract structured data from input
  Map<String, dynamic> extractStructured(String input) {
    final tokens = _tokenize(input);
    final structured = <String, dynamic>{
      'command': _extractCommand(tokens),
      'parameters': _extractParameters(tokens),
      'intent': _detectIntent(tokens),
    };
    return structured;
  }

  String _extractCommand(List<String> tokens) {
    if (tokens.isEmpty) return 'unknown';
    
    final commandKeywords = {
      'status': ['status', 'health', 'check'],
      'market': ['market', 'price', 'exploit', 'scan'],
      'quantum': ['quantum', 'qaoa', 'vqe', 'optimize'],
      'intuition': ['intuition', 'sentiment', 'feel', 'gut'],
      'manifestation': ['manifest', 'simulate', 'multiverse'],
    };

    for (var entry in commandKeywords.entries) {
      if (tokens.any((token) => entry.value.contains(token))) {
        return entry.key;
      }
    }

    return tokens.first;
  }

  Map<String, dynamic> _extractParameters(List<String> tokens) {
    final params = <String, dynamic>{};
    
    // Extract numbers
    final numbers = tokens
        .where((t) => RegExp(r'^\d+\.?\d*$').hasMatch(t))
        .map((t) => double.tryParse(t) ?? 0.0)
        .toList();
    if (numbers.isNotEmpty) {
      params['numbers'] = numbers;
    }

    // Extract symbols (crypto, stocks)
    final symbols = tokens
        .where((t) => RegExp(r'^[A-Z]{2,10}$').hasMatch(t.toUpperCase()))
        .toList();
    if (symbols.isNotEmpty) {
      params['symbols'] = symbols;
    }

    return params;
  }

  String _detectIntent(List<String> tokens) {
    final intentKeywords = {
      'query': ['what', 'how', 'why', 'when', 'where'],
      'command': ['run', 'execute', 'start', 'stop', 'scan'],
      'analysis': ['analyze', 'compare', 'evaluate', 'assess'],
    };

    for (var entry in intentKeywords.entries) {
      if (tokens.any((token) => entry.value.contains(token))) {
        return entry.key;
      }
    }

    return 'general';
  }
}

class EyesOutput {
  final String rawInput;
  final List<String> tokens;
  final String hash;
  final InspirationMatch? inspirationMatch;
  final DateTime timestamp;

  EyesOutput({
    required this.rawInput,
    required this.tokens,
    required this.hash,
    this.inspirationMatch,
    required this.timestamp,
  });
}

class InspirationMatch {
  final String matchedValue;
  final double similarity;
  final String source;

  InspirationMatch({
    required this.matchedValue,
    required this.similarity,
    required this.source,
  });
}

