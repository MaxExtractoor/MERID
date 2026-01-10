import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:merid/core/theme.dart';
import 'package:merid/services/quantum_service.dart';

class QuantumSimScreen extends StatefulWidget {
  const QuantumSimScreen({super.key});

  @override
  State<QuantumSimScreen> createState() => _QuantumSimScreenState();
}

class _QuantumSimScreenState extends State<QuantumSimScreen> {
  final QuantumService _quantumService = QuantumService();
  QuantumResult? _qaoaResults;
  QuantumResult? _vqeResults;
  bool _running = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('QUANTUM SIMULATION // QAOA + VQE'),
        backgroundColor: MeridTheme.background,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _buildHeader(),
          const SizedBox(height: 24),
          _buildAlgorithmButtons(),
          const SizedBox(height: 24),
          if (_qaoaResults != null) _buildQAOAResults(),
          if (_vqeResults != null) ...[
            const SizedBox(height: 24),
            _buildVQEResults(),
          ],
        ],
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: MeridTheme.glowBox(color: MeridTheme.amber, intensity: 0.4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 12,
                height: 12,
                decoration: const BoxDecoration(
                  color: MeridTheme.amber,
                  shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(
                      color: MeridTheme.amber,
                      blurRadius: 8,
                      spreadRadius: 2,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              Text(
                'QUANTUM TOOLKIT',
                style: MeridTheme.monoStyle(
                  fontSize: 18,
                  weight: FontWeight.bold,
                  color: MeridTheme.amber,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            'Role: High-variance candidate generator (simulation only)',
            style: MeridTheme.monoStyle(
              fontSize: 12,
              color: MeridTheme.textSecondary,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Output: JSON with candidates/scores/uncertainty/variance/confidence intervals',
            style: MeridTheme.monoStyle(
              fontSize: 12,
              color: MeridTheme.textSecondary,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Comparison Gate: Quantum vs Classical (delta >0.1, variance <0.5)',
            style: MeridTheme.monoStyle(
              fontSize: 12,
              color: MeridTheme.textSecondary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAlgorithmButtons() {
    return Row(
      children: [
        Expanded(
          child: ElevatedButton(
            onPressed: _running ? null : _runQAOA,
            style: ElevatedButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 16),
            ),
            child: _running
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      valueColor:
                          AlwaysStoppedAnimation<Color>(MeridTheme.background),
                    ),
                  )
                : Text(
                    'RUN QAOA',
                    style: MeridTheme.monoStyle(
                      fontSize: 13,
                      weight: FontWeight.bold,
                      color: MeridTheme.background,
                    ),
                  ),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: OutlinedButton(
            onPressed: _running ? null : _runVQE,
            style: OutlinedButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 16),
            ),
            child: Text(
              'RUN VQE',
              style: MeridTheme.monoStyle(
                fontSize: 13,
                weight: FontWeight.bold,
                color: MeridTheme.amber,
              ),
            ),
          ),
        ),
      ],
    );
  }

  void _runQAOA() async {
    setState(() {
      _running = true;
      _qaoaResults = null;
    });

    try {
      // Example portfolio data
      final covariances = {
        'BTC': 0.15,
        'ETH': 0.12,
        'SOL': 0.18,
      };
      final expectedReturns = [0.08, 0.06, 0.10];
      
      final result = await _quantumService.runQAOA(
        covariances: covariances,
        expectedReturns: expectedReturns,
        riskAversion: 0.5,
        samples: 50,
      );

      setState(() {
        _qaoaResults = result;
        _running = false;
      });
    } catch (e) {
      setState(() {
        _running = false;
      });
      
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error: $e'),
            backgroundColor: MeridTheme.rose,
          ),
        );
      }
    }
  }

  void _runVQE() async {
    setState(() {
      _running = true;
      _vqeResults = null;
    });

    try {
      // Example returns data
      final returns = List.generate(100, (i) => 0.01 + (i % 20) * 0.001);
      
      final result = await _quantumService.runVQE(
        returns: returns,
        confidenceLevel: 0.95,
        samples: 50,
      );

      setState(() {
        _vqeResults = result;
        _running = false;
      });
    } catch (e) {
      setState(() {
        _running = false;
      });
      
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error: $e'),
            backgroundColor: MeridTheme.rose,
          ),
        );
      }
    }
  }

  Widget _buildQAOAResults() {
    final result = _qaoaResults!;
    final advantage = result.advantage;
    
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: MeridTheme.glowBox(
        color: advantage ? MeridTheme.emerald : MeridTheme.amber,
        intensity: 0.3,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'QAOA RESULTS',
            style: MeridTheme.monoStyle(
              fontSize: 14,
              weight: FontWeight.bold,
              color: advantage ? MeridTheme.emerald : MeridTheme.amber,
            ),
          ),
          const SizedBox(height: 16),
          _buildResultRow('Algorithm', result.algorithm),
          _buildResultRow('Problem Type', result.problemType),
          _buildResultRow('Samples', result.samples.toString()),
          const Divider(color: MeridTheme.surfaceLight, height: 24),
          _buildResultRow('Classical Cost',
              result.classicalCost.toStringAsFixed(4)),
          _buildResultRow('Quantum Cost',
              result.quantumCost.toStringAsFixed(4)),
          _buildResultRow(
              'Delta (Δ)',
              result.delta.toStringAsFixed(4),
              advantage ? MeridTheme.emerald : MeridTheme.textSecondary),
          _buildResultRow('Uncertainty',
              '${(result.uncertainty * 100).toStringAsFixed(1)}%'),
          _buildResultRow('Variance (σ²)',
              result.variance.toStringAsFixed(3)),
          const Divider(color: MeridTheme.surfaceLight, height: 24),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: MeridTheme.background,
              borderRadius: BorderRadius.circular(4),
              border: Border.all(
                color: advantage ? MeridTheme.emerald : MeridTheme.rose,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'COMPARISON GATE',
                  style: MeridTheme.monoStyle(
                    fontSize: 11,
                    weight: FontWeight.bold,
                    color: MeridTheme.textSecondary,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  result.comparisonSummary,
                  style: MeridTheme.monoStyle(
                    fontSize: 12,
                    color: advantage ? MeridTheme.emerald : MeridTheme.rose,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: MeridTheme.amber.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              advantage
                  ? 'Quantum advantage confirmed. Delta >0.1 and variance <0.5. Candidate approved for consideration.'
                  : 'No quantum advantage detected. Classical solution preferred.',
              style: MeridTheme.monoStyle(
                fontSize: 12,
                color: MeridTheme.textPrimary,
              ),
            ),
          ),
        ],
      ),
    ).animate().fadeIn(duration: 400.ms).slideY(begin: 0.1, end: 0);
  }

  Widget _buildVQEResults() {
    final result = _vqeResults!;
    final advantage = result.advantage;
    
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: MeridTheme.glowBox(
        color: advantage ? MeridTheme.emerald : MeridTheme.amber,
        intensity: 0.3,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'VQE RESULTS',
            style: MeridTheme.monoStyle(
              fontSize: 14,
              weight: FontWeight.bold,
              color: advantage ? MeridTheme.emerald : MeridTheme.amber,
            ),
          ),
          const SizedBox(height: 16),
          _buildResultRow('Algorithm', result.algorithm),
          _buildResultRow('Problem Type', result.problemType),
          _buildResultRow('Samples', result.samples.toString()),
          const Divider(color: MeridTheme.surfaceLight, height: 24),
          _buildResultRow('Classical CVaR',
              result.classicalCost.toStringAsFixed(4)),
          _buildResultRow('Quantum CVaR',
              result.quantumCost.toStringAsFixed(4)),
          _buildResultRow(
              'Delta (Δ)',
              result.delta.toStringAsFixed(4),
              advantage ? MeridTheme.emerald : MeridTheme.textSecondary),
          _buildResultRow('Uncertainty',
              '${(result.uncertainty * 100).toStringAsFixed(1)}%'),
          _buildResultRow('Variance (σ²)',
              result.variance.toStringAsFixed(3)),
          const Divider(color: MeridTheme.surfaceLight, height: 24),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: MeridTheme.background,
              borderRadius: BorderRadius.circular(4),
              border: Border.all(
                color: advantage ? MeridTheme.emerald : MeridTheme.rose,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'COMPARISON GATE',
                  style: MeridTheme.monoStyle(
                    fontSize: 11,
                    weight: FontWeight.bold,
                    color: MeridTheme.textSecondary,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  result.comparisonSummary,
                  style: MeridTheme.monoStyle(
                    fontSize: 12,
                    color: advantage ? MeridTheme.emerald : MeridTheme.rose,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: MeridTheme.amber.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              advantage
                  ? 'Quantum advantage confirmed for CVaR risk minimization. Lower tail risk detected.'
                  : 'No quantum advantage detected. Classical CVaR calculation preferred.',
              style: MeridTheme.monoStyle(
                fontSize: 12,
                color: MeridTheme.textPrimary,
              ),
            ),
          ),
        ],
      ),
    ).animate().fadeIn(duration: 400.ms).slideY(begin: 0.1, end: 0);
  }

  Widget _buildResultRow(String label, String value, [Color? valueColor]) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 180,
            child: Text(
              label,
              style: MeridTheme.monoStyle(
                fontSize: 12,
                color: MeridTheme.textSecondary,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: MeridTheme.monoStyle(
                fontSize: 12,
                color: valueColor ?? MeridTheme.textPrimary,
                weight:
                    valueColor != null ? FontWeight.bold : FontWeight.normal,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
