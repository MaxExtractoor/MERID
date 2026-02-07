import 'dart:convert';
import 'dart:math';
import 'package:crypto/crypto.dart';
import 'package:merid/core/database.dart';
import 'package:merid/body_protocol/spine/message_bus.dart';

/// Security Module - Maker Signature, Credential Proxy, SLP-1 Lockdown
class SecurityModule {
  final MeridDatabase _db = MeridDatabase();
  final SpineMessageBus _bus = SpineMessageBus();
  final Random _random = Random();

  static const double _baselineConfidence = 0.89;
  double _currentConfidence = _baselineConfidence;

  /// Generate Maker Signature (probabilistic behavioral verification)
  Future<String> generateMakerSignature({
    required String action,
    required Map<String, dynamic> context,
  }) async {
    // Stylometry-based signature
    final behaviorHash = _hashBehavior(action, context);
    final timestamp = DateTime.now().millisecondsSinceEpoch;
    final signature = _combineSignature(behaviorHash, timestamp);

    // Store signature
    await _db.appendToLedger(
        'maker_signature',
        {
          'signature': signature,
          'action': action,
          'confidence': _currentConfidence,
          'timestamp': timestamp,
        },
        'security');

    return signature;
  }

  /// Verify Maker Signature
  Future<bool> verifyMakerSignature(String signature) async {
    // Check signature against baseline
    final confidence = _calculateSignatureConfidence(signature);

    if (confidence < _baselineConfidence - 0.1) {
      // Violation detected - trigger SLP-1
      await triggerLockdown(
          'Signature confidence below threshold: $confidence');
      return false;
    }

    return true;
  }

  /// Calculate signature confidence (stylometry)
  double _calculateSignatureConfidence(String signature) {
    // Simulate stylometry analysis
    // In production, this would analyze behavioral patterns
    return _baselineConfidence + (_random.nextDouble() - 0.5) * 0.05;
  }

  String _hashBehavior(String action, Map<String, dynamic> context) {
    final combined = '$action${jsonEncode(context)}';
    final bytes = utf8.encode(combined);
    final digest = sha256.convert(bytes);
    return digest.toString();
  }

  String _combineSignature(String hash, int timestamp) {
    final combined = '$hash$timestamp';
    final bytes = utf8.encode(combined);
    final digest = sha256.convert(bytes);
    return digest.toString();
  }

  /// Trigger SLP-1 Lockdown
  Future<void> triggerLockdown(String reason) async {
    _bus.send(BusMessage(
      sender: 'SECURITY',
      busLevel: 'master',
      content: 'SLP-1 LOCKDOWN TRIGGERED: $reason',
      timestamp: DateTime.now(),
      priority: BusPriority.critical,
      metadata: {
        'violation': true,
        'reason': reason,
        'invariant': 'SLP-1',
      },
    ));

    // Store violation
    await _db.appendToLedger(
        'security_violation',
        {
          'type': 'SLP-1',
          'reason': reason,
          'timestamp': DateTime.now().toIso8601String(),
          'action': 'lockdown',
        },
        'security');
  }

  /// Check for credential exposure (SEC-1/SEC-2)
  Future<bool> checkCredentialSafety(String output) async {
    // Check for common credential patterns
    final patterns = [
      RegExp(r'[A-Za-z0-9]{32,}'), // API keys
      RegExp(r'0x[a-fA-F0-9]{40}'), // Ethereum addresses (might be OK)
      RegExp(r'sk-[A-Za-z0-9]+'), // Secret keys
      RegExp(r'Bearer [A-Za-z0-9]+'), // Bearer tokens
    ];

    for (var pattern in patterns) {
      if (pattern.hasMatch(output)) {
        _bus.send(BusMessage(
          sender: 'SECURITY',
          busLevel: 'governance',
          content: 'SEC-1/SEC-2: Potential credential exposure detected',
          timestamp: DateTime.now(),
          priority: BusPriority.high,
        ));
        return false;
      }
    }

    return true;
  }

  /// Credential Proxy - Gate all external API calls
  Future<Map<String, dynamic>> proxyRequest({
    required String service,
    required String endpoint,
    Map<String, dynamic>? params,
  }) async {
    // In production, this would route through a secure proxy
    // For now, log and allow (with monitoring)

    _bus.send(BusMessage(
      sender: 'SECURITY',
      busLevel: 'group',
      content: 'Credential proxy: $service -> $endpoint',
      timestamp: DateTime.now(),
      priority: BusPriority.normal,
      metadata: {
        'service': service,
        'endpoint': endpoint,
        'proxied': true,
      },
    ));

    return {
      'proxied': true,
      'service': service,
      'endpoint': endpoint,
    };
  }

  /// Update maker confidence
  void updateConfidence(double newConfidence) {
    _currentConfidence = newConfidence.clamp(0.0, 1.0);
  }

  double get currentConfidence => _currentConfidence;
}
