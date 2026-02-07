import 'dart:async';
import 'dart:math' as math;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api.dart';
import 'models.dart';

const _primeScreenPollingInterval = Duration(seconds: 4);
const _autonomyPollingInterval = Duration(seconds: 6);
const _maxBackoffInterval = Duration(seconds: 30);

enum ConnectionStatus { connecting, connected, degraded, error }

class ConnectionHealth {
  const ConnectionHealth({required this.status, this.message});

  final ConnectionStatus status;
  final String? message;
}

final primeScreenApiBaseUrlProvider = Provider<String>((ref) {
  const envOverride =
      String.fromEnvironment('MERID_API_BASE', defaultValue: '');
  if (envOverride.isNotEmpty) {
    return envOverride;
  }
  return 'http://127.0.0.1:8000';
});

final primeScreenApiProvider = Provider<PrimeScreenApi>((ref) {
  final baseUrl = ref.watch(primeScreenApiBaseUrlProvider);
  return PrimeScreenApi(baseUrl: baseUrl);
});

final primeScreenConnectionProvider = StateProvider<ConnectionHealth>((ref) {
  return const ConnectionHealth(status: ConnectionStatus.connecting);
});

final autonomyConnectionProvider = StateProvider<ConnectionHealth>((ref) {
  return const ConnectionHealth(status: ConnectionStatus.connecting);
});

Stream<T> _createPollingStream<T>({
  required Ref ref,
  required Duration interval,
  required Future<T> Function() fetcher,
  required StateController<ConnectionHealth> connectionController,
}) {
  final controller = StreamController<T>();
  Timer? timer;
  var isFetching = false;
  var hasEmittedValue = false;
  var currentInterval = interval;
  var failureCount = 0;

  late Future<void> Function() emit;

  void scheduleNext() {
    if (controller.isClosed) return;
    timer?.cancel();
    timer = Timer(currentInterval, () => emit());
  }

  emit = () async {
    if (isFetching) return;
    isFetching = true;
    if (!hasEmittedValue) {
      connectionController.state =
          const ConnectionHealth(status: ConnectionStatus.connecting);
    }
    try {
      final value = await fetcher();
      if (!controller.isClosed) {
        controller.add(value);
        hasEmittedValue = true;
      }
      failureCount = 0;
      currentInterval = interval;
      connectionController.state =
          const ConnectionHealth(status: ConnectionStatus.connected);
    } catch (error, stackTrace) {
      failureCount += 1;
      final status = failureCount >= 3
          ? ConnectionStatus.error
          : ConnectionStatus.degraded;
      connectionController.state =
          ConnectionHealth(status: status, message: error.toString());
      final multiplier = math.pow(2, math.min(4, failureCount)).toDouble();
      final proposed = Duration(
        milliseconds: (interval.inMilliseconds * multiplier).round().clamp(
              interval.inMilliseconds,
              _maxBackoffInterval.inMilliseconds,
            ),
      );
      currentInterval = proposed;
      if (!hasEmittedValue && !controller.isClosed) {
        controller.addError(error, stackTrace);
      }
    } finally {
      isFetching = false;
      scheduleNext();
    }
  };

  controller.onListen = () {
    emit();
  };

  controller.onCancel = () {
    timer?.cancel();
  };

  ref.onDispose(() {
    timer?.cancel();
    controller.close();
  });

  return controller.stream;
}

final primeScreenStateStreamProvider =
    StreamProvider.autoDispose<PrimeScreenState>((ref) {
  final api = ref.watch(primeScreenApiProvider);
  return _createPollingStream(
    ref: ref,
    interval: _primeScreenPollingInterval,
    fetcher: api.getPrimeScreenState,
    connectionController: ref.read(primeScreenConnectionProvider.notifier),
  );
});

final autonomyStateStreamProvider =
    StreamProvider.autoDispose<AutonomyState>((ref) {
  final api = ref.watch(primeScreenApiProvider);
  return _createPollingStream(
    ref: ref,
    interval: _autonomyPollingInterval,
    fetcher: api.getAutonomyState,
    connectionController: ref.read(autonomyConnectionProvider.notifier),
  );
});

final autonomyLimitsProvider =
    FutureProvider.autoDispose<List<AutonomyPortfolio>>((ref) {
  final api = ref.watch(primeScreenApiProvider);
  return api.getAutonomyLimits();
});

final selectedDecisionIdProvider = StateProvider<String?>((ref) => null);

final decisionDetailProvider =
    FutureProvider.autoDispose.family<DecisionDetail, String>((ref, id) {
  final api = ref.watch(primeScreenApiProvider);
  return api.getDecision(id);
});

final backtestSummaryProvider =
    FutureProvider.autoDispose.family<BacktestSummary, String>((ref, id) {
  final api = ref.watch(primeScreenApiProvider);
  return api.getBacktest(id);
});

final backtestTradesProvider =
    FutureProvider.autoDispose.family<List<TradeRecord>, String>((ref, id) {
  final api = ref.watch(primeScreenApiProvider);
  return api.getBacktestTrades(id);
});

final latestBacktestIdProvider = StateProvider<String?>((ref) => null);

class PrimeScreenActions {
  PrimeScreenActions(this._ref, this._api);

  final Ref _ref;
  final PrimeScreenApi _api;

  Future<void> overrideIntent(IntentOverrideRequestPayload payload) async {
    await _api.postIntentOverride(payload);
    _ref.invalidate(primeScreenStateStreamProvider);
  }

  Future<BacktestSubmission> submitBacktest(
    BacktestRequestPayload payload,
  ) async {
    final submission = await _api.postBacktest(payload);
    return submission;
  }

  Future<DecisionDetail> retryNarrative(String decisionId) async {
    final detail = await _api.retryNarrative(decisionId);
    _ref.invalidate(decisionDetailProvider(decisionId));
    return detail;
  }

  Future<AutonomyState> updateAutonomyState(
    AutonomyStateUpdatePayload payload,
  ) async {
    final state = await _api.setAutonomyState(payload);
    _ref.invalidate(autonomyStateStreamProvider);
    return state;
  }

  Future<AutonomyPortfolio> updateAutonomyLimits(
    AutonomyLimitsUpdatePayload payload,
  ) async {
    final portfolio = await _api.setAutonomyLimits(payload);
    _ref.invalidate(autonomyLimitsProvider);
    return portfolio;
  }
}

final primeScreenActionsProvider = Provider<PrimeScreenActions>((ref) {
  final api = ref.watch(primeScreenApiProvider);
  return PrimeScreenActions(ref, api);
});
