class GovernanceModule {
  bool _lockdownActive = false;
  final List<GovernanceDecision> _decisions = [];

  bool validateAction(String action, String actor) {
    if (_lockdownActive) {
      return false;
    }
    
    final decision = GovernanceDecision(
      action: action,
      actor: actor,
      timestamp: DateTime.now(),
      approved: _evaluateAction(action),
    );
    
    _decisions.add(decision);
    return decision.approved;
  }

  bool _evaluateAction(String action) {
    final executionActions = ['execute', 'trade', 'send', 'modify'];
    for (var execAction in executionActions) {
      if (action.toLowerCase().contains(execAction)) {
        return false;
      }
    }
    return true;
  }

  void activateLockdown() {
    _lockdownActive = true;
  }

  void deactivateLockdown() {
    _lockdownActive = false;
  }

  bool isLockdownActive() => _lockdownActive;

  List<GovernanceDecision> getRecentDecisions({int limit = 20}) {
    return _decisions.reversed.take(limit).toList();
  }

  Map<String, dynamic> getGovernanceStatus() {
    return {
      'lockdown_active': _lockdownActive,
      'total_decisions': _decisions.length,
      'approved_count': _decisions.where((d) => d.approved).length,
      'blocked_count': _decisions.where((d) => !d.approved).length,
    };
  }
}

class GovernanceDecision {
  final String action;
  final String actor;
  final DateTime timestamp;
  final bool approved;

  GovernanceDecision({
    required this.action,
    required this.actor,
    required this.timestamp,
    required this.approved,
  });
}
