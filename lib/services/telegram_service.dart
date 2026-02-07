import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:merid/core/database.dart';
import 'package:merid/body_protocol/spine/message_bus.dart';

/// Telegram Bot Service for real-time alerts
class TelegramService {
  final MeridDatabase _db = MeridDatabase();
  final SpineMessageBus _bus = SpineMessageBus();

  // Telegram Bot API endpoint (would use credential proxy in production)
  static const String _botApiUrl = 'https://api.telegram.org/bot';
  static const String _botToken = 'YOUR_BOT_TOKEN'; // Would be from proxy
  static const String _wsUrl =
      'ws://localhost:8080/telegram'; // WebSocket for real-time

  WebSocketChannel? _channel;
  StreamSubscription? _subscription;

  /// Initialize Telegram bot connection
  Future<void> initialize() async {
    try {
      // Connect to WebSocket for real-time alerts
      _channel = WebSocketChannel.connect(Uri.parse(_wsUrl));

      _subscription = _channel!.stream.listen(
        (message) {
          _handleTelegramMessage(message);
        },
        onError: (error) {
          _bus.send(BusMessage(
            sender: 'TELEGRAM_SERVICE',
            busLevel: 'group',
            content: 'WebSocket error: $error',
            timestamp: DateTime.now(),
            priority: BusPriority.high,
          ));
        },
      );

      _bus.send(BusMessage(
        sender: 'TELEGRAM_SERVICE',
        busLevel: 'group',
        content: 'Telegram bot connected',
        timestamp: DateTime.now(),
        priority: BusPriority.normal,
      ));
    } catch (e) {
      // Fallback to polling if WebSocket fails
      _startPolling();
    }
  }

  /// Handle incoming Telegram message
  void _handleTelegramMessage(dynamic message) {
    try {
      final data = jsonDecode(message as String);
      final alert = TelegramAlert.fromJson(data);

      // Store alert (fire-and-forget)
      unawaited(_db.appendToLedger(
          'telegram_alert',
          {
            'message': alert.message,
            'type': alert.type,
            'timestamp': alert.timestamp.toIso8601String(),
          },
          'automation'));

      // Send to bus with appropriate priority
      _bus.send(BusMessage(
        sender: 'TELEGRAM_SERVICE',
        busLevel: alert.priority == 'high' ? 'governance' : 'group',
        content: alert.message,
        timestamp: alert.timestamp,
        priority:
            alert.priority == 'high' ? BusPriority.high : BusPriority.normal,
        metadata: {
          'type': alert.type,
          'source': 'telegram',
        },
      ));
    } catch (e) {
      // Handle parse error
    }
  }

  /// Send alert to Telegram channel
  Future<bool> sendAlert(String message, {String? chatId}) async {
    try {
      final url = Uri.parse('$_botApiUrl$_botToken/sendMessage');
      final response = await http.post(
        url,
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'chat_id': chatId ?? '@merid_alerts',
          'text': message,
          'parse_mode': 'Markdown',
        }),
      );

      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  /// Fetch recent messages (fallback polling)
  Future<List<TelegramAlert>> fetchMessages({int limit = 20}) async {
    try {
      final response = await http.get(
        Uri.parse('http://localhost:8080/telegram?limit=$limit'),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as List;
        return data.map((json) => TelegramAlert.fromJson(json)).toList();
      }
    } catch (e) {
      // Return empty list on error
    }
    return [];
  }

  /// Start polling for messages (fallback)
  void _startPolling() {
    Timer.periodic(const Duration(seconds: 5), (timer) async {
      final messages = await fetchMessages();
      for (var message in messages) {
        _handleTelegramMessage(jsonEncode(message.toJson()));
      }
    });
  }

  /// Send market divergence alert
  Future<void> sendMarketDivergenceAlert({
    required String symbol,
    required double binancePrice,
    required double polymarketPrice,
    required double gap,
  }) async {
    final message = '''
🚨 **Market Divergence Detected**

Symbol: $symbol
Binance: \$${binancePrice.toStringAsFixed(2)}
Polymarket: \$${polymarketPrice.toStringAsFixed(2)}
Gap: ${gap.toStringAsFixed(2)}% (${gap > 0.5 ? 'EXPLOIT' : 'normal'})

*Advisory only - no execution without approval*
''';

    await sendAlert(message);
  }

  void dispose() {
    _subscription?.cancel();
    _channel?.sink.close();
  }
}

class TelegramAlert {
  final String message;
  final String type;
  final DateTime timestamp;
  final String priority;

  TelegramAlert({
    required this.message,
    required this.type,
    required this.timestamp,
    this.priority = 'normal',
  });

  factory TelegramAlert.fromJson(Map<String, dynamic> json) {
    return TelegramAlert(
      message: json['message'] as String,
      type: json['type'] as String? ?? 'general',
      timestamp: DateTime.parse(json['timestamp'] as String),
      priority: json['priority'] as String? ?? 'normal',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'message': message,
      'type': type,
      'timestamp': timestamp.toIso8601String(),
      'priority': priority,
    };
  }
}
