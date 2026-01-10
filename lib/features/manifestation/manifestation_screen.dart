import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:merid/core/theme.dart';
import 'package:merid/body_protocol/simulation/simulation_module.dart';

class ManifestationScreen extends StatefulWidget {
  const ManifestationScreen({super.key});

  @override
  State<ManifestationScreen> createState() => _ManifestationScreenState();
}

class _ManifestationScreenState extends State<ManifestationScreen> {
  final SimulationModule _simulation = SimulationModule();
  final TextEditingController _hypothesisController = TextEditingController();
  Map<String, dynamic>? _manifestationResults;
  bool _simulating = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('MANIFESTATION SIMULATOR'),
        backgroundColor: MeridTheme.background,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _buildHeader(),
          const SizedBox(height: 24),
          _buildHypothesisInput(),
          const SizedBox(height: 16),
          _buildSimulateButton(),
          const SizedBox(height: 24),
          if (_manifestationResults != null) _buildResults(),
        ],
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: MeridTheme.glowBox(color: MeridTheme.emerald, intensity: 0.4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 12,
                height: 12,
                decoration: const BoxDecoration(
                  color: MeridTheme.emerald,
                  shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(
                      color: MeridTheme.emerald,
                      blurRadius: 8,
                      spreadRadius: 2,
                    ),
                  ],
                ),
              )
                  .animate(onPlay: (controller) => controller.repeat())
                  .fadeIn(duration: 1000.ms)
                  .then()
                  .fadeOut(duration: 1000.ms),
              const SizedBox(width: 12),
              Text(
                'MULTIVERSE HYPOTHESIS TESTING',
                style: MeridTheme.monoStyle(
                  fontSize: 18,
                  weight: FontWeight.bold,
                  color: MeridTheme.emerald,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            'Simulates "thoughts create reality" across 1000 parallel scenarios.',
            style: MeridTheme.monoStyle(
              fontSize: 12,
              color: MeridTheme.textSecondary,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Tests probability, timeline variance, and confidence intervals for hypothesis manifestation.',
            style: MeridTheme.monoStyle(
              fontSize: 12,
              color: MeridTheme.textSecondary,
            ),
          ),
          const SizedBox(height: 4),
          Container(
            margin: const EdgeInsets.only(top: 8),
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: MeridTheme.amber.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(4),
              border:
                  Border.all(color: MeridTheme.amber.withValues(alpha: 0.3)),
            ),
            child: Text(
              'Insights from "Source" treated as non-privileged hypotheses',
              style: MeridTheme.monoStyle(
                fontSize: 11,
                color: MeridTheme.amber,
                weight: FontWeight.bold,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildHypothesisInput() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'HYPOTHESIS',
          style: MeridTheme.monoStyle(
            fontSize: 12,
            color: MeridTheme.textSecondary,
          ),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _hypothesisController,
          style: MeridTheme.monoStyle(fontSize: 14),
          decoration: InputDecoration(
            hintText: 'e.g., BTC breaks 105K within 48h',
            hintStyle: MeridTheme.monoStyle(
              fontSize: 14,
              color: MeridTheme.textDim,
            ),
            filled: true,
            fillColor: MeridTheme.background,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(4),
              borderSide: const BorderSide(color: MeridTheme.surfaceLight),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(4),
              borderSide: const BorderSide(color: MeridTheme.surfaceLight),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(4),
              borderSide: const BorderSide(color: MeridTheme.emerald, width: 2),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildSimulateButton() {
    return ElevatedButton(
      onPressed: _simulating ? null : _runSimulation,
      style: ElevatedButton.styleFrom(
        backgroundColor: MeridTheme.emerald,
        padding: const EdgeInsets.symmetric(vertical: 16),
      ),
      child: _simulating
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
              'SIMULATE 1000 SCENARIOS',
              style: MeridTheme.monoStyle(
                fontSize: 13,
                weight: FontWeight.bold,
                color: MeridTheme.background,
              ),
            ),
    );
  }

  void _runSimulation() async {
    final hypothesis = _hypothesisController.text.trim();
    if (hypothesis.isEmpty) {
      _hypothesisController.text = 'BTC breaks \\105K within 48h';
      return;
    }

    setState(() {
      _simulating = true;
    });

    await Future.delayed(const Duration(seconds: 2));

    final results = _simulation.runMultiverseSimulation(
      hypothesis: hypothesis,
      scenarios: 1000,
    );

    setState(() {
      _manifestationResults = results;
      _simulating = false;
    });
  }

  Widget _buildResults() {
    final successRate = _manifestationResults!['success_rate'] as double;
    final isHighProbability = successRate > 0.75;

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: MeridTheme.glowBox(
        color: isHighProbability ? MeridTheme.emerald : MeridTheme.amber,
        intensity: 0.3,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                isHighProbability ? Icons.check_circle : Icons.info,
                color:
                    isHighProbability ? MeridTheme.emerald : MeridTheme.amber,
                size: 20,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  _manifestationResults!['hypothesis'].toString().toUpperCase(),
                  style: MeridTheme.monoStyle(
                    fontSize: 14,
                    weight: FontWeight.bold,
                    color: isHighProbability
                        ? MeridTheme.emerald
                        : MeridTheme.amber,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          _buildProgressBar(
            'Success Rate',
            successRate,
            isHighProbability ? MeridTheme.emerald : MeridTheme.amber,
          ),
          const SizedBox(height: 16),
          _buildResultRow('Scenarios Run',
              _manifestationResults!['scenarios_run'].toString()),
          _buildResultRow('Success Count',
              '${_manifestationResults!['success_count']}/${_manifestationResults!['scenarios_run']}'),
          _buildResultRow(
              'Success Rate',
              '${(successRate * 100).toStringAsFixed(1)}%',
              isHighProbability ? MeridTheme.emerald : MeridTheme.amber),
          _buildResultRow('Avg Timeline',
              '${_manifestationResults!['avg_timeline_hours'].toStringAsFixed(1)} hours'),
          _buildResultRow(
            'Confidence Interval',
            '[${(_manifestationResults!['confidence_interval'][0] * 100).toStringAsFixed(0)}% - ${(_manifestationResults!['confidence_interval'][1] * 100).toStringAsFixed(0)}%]',
          ),
          _buildResultRow('Multiverse Variance',
              _manifestationResults!['multiverse_variance'].toStringAsFixed(3)),
          const Divider(color: MeridTheme.surfaceLight, height: 24),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: isHighProbability
                  ? MeridTheme.emerald.withValues(alpha: 0.1)
                  : MeridTheme.amber.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              _manifestationResults!['recommendation'],
              style: MeridTheme.monoStyle(
                fontSize: 12,
                color: MeridTheme.textPrimary,
              ),
            ),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: MeridTheme.amber.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(4),
              border:
                  Border.all(color: MeridTheme.amber.withValues(alpha: 0.3)),
            ),
            child: Row(
              children: [
                const Icon(Icons.science, color: MeridTheme.amber, size: 16),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Simulation only - monitor real-world data for confirmation',
                    style: MeridTheme.monoStyle(
                      fontSize: 11,
                      color: MeridTheme.amber,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    ).animate().fadeIn(duration: 400.ms).slideY(begin: 0.1, end: 0);
  }

  Widget _buildProgressBar(String label, double value, Color color) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              label,
              style: MeridTheme.monoStyle(
                fontSize: 12,
                color: MeridTheme.textSecondary,
              ),
            ),
            Text(
              '${(value * 100).toStringAsFixed(1)}%',
              style: MeridTheme.monoStyle(
                fontSize: 12,
                weight: FontWeight.bold,
                color: color,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Stack(
          children: [
            Container(
              height: 12,
              decoration: BoxDecoration(
                color: MeridTheme.surfaceLight,
                borderRadius: BorderRadius.circular(6),
              ),
            ),
            FractionallySizedBox(
              widthFactor: value.clamp(0.0, 1.0),
              child: Container(
                height: 12,
                decoration: BoxDecoration(
                  color: color,
                  borderRadius: BorderRadius.circular(6),
                  boxShadow: [
                    BoxShadow(
                      color: color.withValues(alpha: 0.5),
                      blurRadius: 8,
                    ),
                  ],
                ),
              ).animate().scaleX(duration: 800.ms, curve: Curves.easeOut),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildResultRow(String label, String value, [Color? valueColor]) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 150,
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

  @override
  void dispose() {
    _hypothesisController.dispose();
    super.dispose();
  }
}
