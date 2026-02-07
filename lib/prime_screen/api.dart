import 'package:dio/dio.dart';

import 'models.dart';

class PrimeScreenApiException implements Exception {
  PrimeScreenApiException(this.message, [this.statusCode]);

  final String message;
  final int? statusCode;

  factory PrimeScreenApiException.fromDio(DioException error) {
    final status = error.response?.statusCode;
    final data = error.response?.data;
    final detail = data is Map<String, dynamic> && data['detail'] is String
        ? data['detail'] as String
        : error.message ?? 'Prime Screen API error';
    return PrimeScreenApiException(detail, status);
  }

  @override
  String toString() =>
      'PrimeScreenApiException(statusCode=$statusCode, message=$message)';
}

class PrimeScreenApi {
  PrimeScreenApi({Dio? dio, String? baseUrl})
      : _dio = dio ??
            Dio(
              BaseOptions(
                baseUrl: _resolveBaseUrl(baseUrl),
                connectTimeout: const Duration(seconds: 5),
                receiveTimeout: const Duration(seconds: 10),
              ),
            );

  final Dio _dio;

  static const _primeScreenPath = '/api/v1/swarm/prime-screen';

  static String _resolveBaseUrl(String? override) {
    if (override != null && override.isNotEmpty) {
      return override;
    }
    const envOverride =
        String.fromEnvironment('MERID_API_BASE', defaultValue: '');
    if (envOverride.isNotEmpty) {
      return envOverride;
    }
    return 'http://127.0.0.1:8000';
  }

  Future<PrimeScreenState> getPrimeScreenState() async {
    try {
      final response = await _dio.get('$_primeScreenPath/state');
      return PrimeScreenState.fromJson(response.data);
    } on DioException catch (error) {
      throw PrimeScreenApiException.fromDio(error);
    }
  }

  Future<DecisionDetail> getDecision(String decisionId) async {
    try {
      final response = await _dio.get(
        '$_primeScreenPath/decisions/$decisionId',
      );
      return DecisionDetail.fromJson(response.data);
    } on DioException catch (error) {
      throw PrimeScreenApiException.fromDio(error);
    }
  }

  Future<DecisionDetail> retryNarrative(String decisionId) async {
    try {
      final response = await _dio.post(
        '$_primeScreenPath/decisions/$decisionId/narrative/retry',
      );
      return DecisionDetail.fromJson(response.data);
    } on DioException catch (error) {
      throw PrimeScreenApiException.fromDio(error);
    }
  }

  Future<Map<String, dynamic>> postIntentOverride(
    IntentOverrideRequestPayload payload,
  ) async {
    try {
      final response = await _dio.post(
        '$_primeScreenPath/intents/override',
        data: payload.toJson(),
      );
      return Map<String, dynamic>.from(response.data as Map);
    } on DioException catch (error) {
      throw PrimeScreenApiException.fromDio(error);
    }
  }

  Future<BacktestSubmission> postBacktest(
    BacktestRequestPayload payload,
  ) async {
    try {
      final response = await _dio.post(
        '$_primeScreenPath/backtests',
        data: payload.toJson(),
      );
      return BacktestSubmission.fromJson(response.data);
    } on DioException catch (error) {
      throw PrimeScreenApiException.fromDio(error);
    }
  }

  Future<BacktestSummary> getBacktest(String backtestId) async {
    try {
      final response = await _dio.get(
        '$_primeScreenPath/backtests/$backtestId',
      );
      return BacktestSummary.fromJson(response.data);
    } on DioException catch (error) {
      throw PrimeScreenApiException.fromDio(error);
    }
  }

  Future<List<TradeRecord>> getBacktestTrades(String backtestId) async {
    try {
      final response = await _dio.get(
        '$_primeScreenPath/backtests/$backtestId/trades',
      );
      final data = response.data as List<dynamic>;
      return data
          .map((item) => TradeRecord.fromJson(item as Map<String, dynamic>))
          .toList();
    } on DioException catch (error) {
      throw PrimeScreenApiException.fromDio(error);
    }
  }

  Future<AutonomyState> getAutonomyState() async {
    try {
      final response = await _dio.get('$_primeScreenPath/autonomy/state');
      return AutonomyState.fromJson(response.data);
    } on DioException catch (error) {
      throw PrimeScreenApiException.fromDio(error);
    }
  }

  Future<AutonomyState> setAutonomyState(
    AutonomyStateUpdatePayload payload,
  ) async {
    try {
      final response = await _dio.post(
        '$_primeScreenPath/autonomy/state',
        data: payload.toJson(),
      );
      return AutonomyState.fromJson(response.data);
    } on DioException catch (error) {
      throw PrimeScreenApiException.fromDio(error);
    }
  }

  Future<List<AutonomyPortfolio>> getAutonomyLimits() async {
    try {
      final response = await _dio.get('$_primeScreenPath/autonomy/limits');
      final data = response.data as List<dynamic>;
      return data
          .map((item) =>
              AutonomyPortfolio.fromJson(item as Map<String, dynamic>))
          .toList();
    } on DioException catch (error) {
      throw PrimeScreenApiException.fromDio(error);
    }
  }

  Future<AutonomyPortfolio> setAutonomyLimits(
    AutonomyLimitsUpdatePayload payload,
  ) async {
    try {
      final response = await _dio.post(
        '$_primeScreenPath/autonomy/limits',
        data: payload.toJson(),
      );
      return AutonomyPortfolio.fromJson(response.data);
    } on DioException catch (error) {
      throw PrimeScreenApiException.fromDio(error);
    }
  }
}
