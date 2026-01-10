import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:merid/core/theme.dart';
import 'package:merid/body_protocol/optimization/optimization_module.dart';

class QuantumSimScreen extends StatefulWidget {
  const QuantumSimScreen({super.key});

  @override
  State<QuantumSimScreen> createState() => _QuantumSimScreenState();
}

class _QuantumSimScreenState extends State<QuantumSimScreen> {
  final OptimizationModule _optimization = OptimizationModule();
  Map<String, dynamic>? _qaoaResults;
  Map<String, dynamic>? _vqeResults;
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
                      valueColor: AlwaysStoppedAnimation<Color>(MeridTheme.background),
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
    });

    await Future.delayed(const Duration(seconds: 2));

    final results = _optimization.runQuantumOptimization(
      algorithm: 'QAOA',
      problem: 'Portfolio Mean-Variance QUBO',
    );

    setState(() {
      _qaoaResults = results;
      _running = false;
    });
  }

  void _runVQE() async {
    setState(() {
      _running = true;
    });

    await Future.delayed(const Duration(milliseconds: 1500));

    final results = _optimization.runVQE(
      problem: 'CVaR Risk Minimization',
    );

    setState(() {
      _vqeResults = results;
      _running = false;
    });
  }

  Widget _buildQAOAResults() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: MeridTheme.glowBox(color: MeridTheme.emerald, intensity: 0.3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'QAOA RESULTS',
            style: MeridTheme.monoStyle(
              fontSize: 14,
              weight: FontWeight.bold,
              color: MeridTheme.emerald,
            ),
          ),
          const SizedBox(height: 16),
          _buildResultRow('Algorithm', _qaoaResults!['algorithm']),
          _buildResultRow('Problem', _qaoaResults!['problem']),
          _buildResultRow('Candidates Generated', _qaoaResults!['candidates_generated'].toString()),
          const Divider(color: MeridTheme.surfaceLight, height: 24),
          _buildResultRow('Classical Baseline', _qaoaResults!['classical_baseline'].toStringAsFixed(3)),
          _buildResultRow('Quantum Best', _qaoaResults!['quantum_best'].toStringAsFixed(3)),
          _buildResultRow('Delta vs Classical', '+${(_qaoaResults!['delta_vs_classical'] * 100).toStringAsFixed(1)}%', MeridTheme.emerald),
          _buildResultRow('Variance', _qaoaResults!['variance'].toStringAsFixed(3)),
          _buildResultRow('Sampling Entropy', _qaoaResults!['sampling_entropy'].toStringAsFixed(2)),
          _buildResultRow('Noise Estimate', _qaoaResults!['noise_estimate'].toStringAsFixed(3)),
          _buildResultRow('Reproducibility', '${(_qaoaResults!['reproducibility_score'] * 100).toStringAsFixed(0)}%'),
          const Divider(color: MeridTheme.surfaceLight, height: 24),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: MeridTheme.background,
              borderRadius: BorderRadius.circular(4),
              border: Border.all(
                color: _qaoaResults!['comparison_gate'].toString().contains('PASS')
                    ? MeridTheme.emerald
                    : MeridTheme.rose,
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
                  _qaoaResults!['comparison_gate'],
                  style: MeridTheme.monoStyle(
                    fontSize: 12,
                    color: _qaoaResults!['comparison_gate'].toString().contains('PASS')
                        ? MeridTheme.emerald
                        : MeridTheme.rose,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: MeridTheme.amber.withOpacity(0.1),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              _qaoaResults!['recommendation'],
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
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: MeridTheme.glowBox(color: MeridTheme.amber, intensity: 0.3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'VQE RESULTS',
            style: MeridTheme.monoStyle(
              fontSize: 14,
              weight: FontWeight.bold,
              color: MeridTheme.amber,
            ),
          ),
          const SizedBox(height: 16),
          _buildResultRow('Algorithm', _vqeResults!['algorithm']),
          _buildResultRow('Problem', _vqeResults!['problem']),
          _buildResultRow('Ground State Energy', _vqeResults!['ground_state_energy'].toStringAsFixed(3)),
          _buildResultRow('Variance', _vqeResults!['variance'].toStringAsFixed(3)),
          _buildResultRow('Convergence Iterations', _vqeResults!['convergence_iterations'].toString()),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: MeridTheme.amber.withOpacity(0.1),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              _vqeResults!['recommendation'],
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
                weight: valueColor != null ? FontWeight.bold : FontWeight.normal,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
