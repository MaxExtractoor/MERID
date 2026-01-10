class SpineMessageBus {
  static final SpineMessageBus _instance = SpineMessageBus._internal();
  factory SpineMessageBus() => _instance;
  SpineMessageBus._internal();

  final List<BusMessage> _messageLog = [];
  final Map<String, List<Function(BusMessage)>> _listeners = {};

  void send(BusMessage message) {
    _messageLog.add(message);
    
    if (!_validateBusHierarchy(message)) {
      _handleViolation(message);
      return;
    }
    
    _notifyListeners(message);
  }

  bool _validateBusHierarchy(BusMessage message) {
    final hierarchy = ['individual', 'group', 'governance', 'master'];
    final currentIndex = hierarchy.indexOf(message.busLevel);
    
    if (currentIndex == -1) return false;
    
    if (message.bypassAttempt) {
      return false;
    }
    
    return true;
  }

  void _handleViolation(BusMessage message) {
    send(BusMessage(
      sender: 'SPINE',
      busLevel: 'master',
      content: 'VIOLATION: Bus bypass attempt detected - ${message.sender}',
      timestamp: DateTime.now(),
      priority: BusPriority.critical,
      bypassAttempt: false,
    ));
  }

  void subscribe(String channel, Function(BusMessage) callback) {
    _listeners[channel] ??= [];
    _listeners[channel]!.add(callback);
  }

  void _notifyListeners(BusMessage message) {
    final channelListeners = _listeners[message.busLevel] ?? [];
    for (var listener in channelListeners) {
      listener(message);
    }
  }

  List<BusMessage> getRecentMessages({int limit = 50}) {
    return _messageLog.reversed.take(limit).toList();
  }
}

class BusMessage {
  final String sender;
  final String busLevel;
  final String content;
  final DateTime timestamp;
  final BusPriority priority;
  final bool bypassAttempt;
  final Map<String, dynamic>? metadata;

  BusMessage({
    required this.sender,
    required this.busLevel,
    required this.content,
    required this.timestamp,
    this.priority = BusPriority.normal,
    this.bypassAttempt = false,
    this.metadata,
  });
}

enum BusPriority {
  low,
  normal,
  high,
  critical,
}
