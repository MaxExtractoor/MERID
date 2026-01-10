import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:merid/core/theme.dart';
import 'package:merid/body_protocol/learning/learning_module.dart';

class IntuitionScreen extends StatefulWidget {
  const IntuitionScreen({super.key});

  @override
  State<IntuitionScreen> createState() => _IntuitionScreenState();
}

class _IntuitionScreenState extends State<IntuitionScreen> {
  final LearningModule _learning = LearningModule();
  Map<String, dynamic>? _intuitionResults;
  bool _analyzing = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('INTUITION MODE // GUT FEEL'),
        backgroundColor: MeridTheme.background,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _buildHeader(),
          const SizedBox(height: 24),
          _buildAnalyzeButton(),
          const SizedBox(height: 24),
          if (_intuitionResults != null) _buildResults(),
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
                'AI INTUITION',
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
            'Offline self-supervised learning (AlphaGo/V-JEPA style) for "gut feel" signal detection.',
            style: MeridTheme.monoStyle(
              fontSize: 12,
              color: MeridTheme.textSecondary,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Detects divergence between sentiment (narratives) and price action (truth).',
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
              color: MeridTheme.emerald.withOpacity(0.1),
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: MeridTheme.emerald.withOpacity(0.3)),
            ),
            child: Text(
              'Narratives = Hypotheses | Price = Truth | Sentiment = Advisory',
              style: MeridTheme.monoStyle(
                fontSize: 11,
                color: MeridTheme.emerald,
                weight: FontWeight.bold,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAnalyzeButton() {
    return ElevatedButton(
      onPressed: _analyzing ? null : _runAnalysis,
      style: ElevatedButton.styleFrom(
        padding: const EdgeInsets.symmetric(vertical: 16),
      ),
      child: _analyzing
          ? const SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor: AlwaysStoppedAnimation<Color>(MeridTheme.background),
              ),
            )
          : Text(
              'ANALYZE GUT FEEL',
              style: MeridTheme.monoStyle(
                fontSize: 13,
                weight: FontWeight.bold,
                color: MeridTheme.background,
              ),
            ),
    );
  }

  void _runAnalysis() async {
    setState(() {
      _analyzing = true;
    });

    await Future.delayed(const Duration(milliseconds: 1500));

    final results = _learning.getIntuitionSignal(
      marketData: 'BTC price + social sentiment',
    );

    setState(() {
      _intuitionResults = results;
      _analyzing = false;
    });
  }

  Widget _buildResults() {
    final isDivergence = _intuitionResults!['type'] == 'Sentiment Divergence';
    
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: MeridTheme.glowBox(
        color: isDivergence ? MeridTheme.amber : MeridTheme.emerald,
        intensity: 0.3,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                isDivergence ? Icons.warning_amber_rounded : Icons.check_circle,
                color: isDivergence ? MeridTheme.amber : MeridTheme.emerald,
                size: 20,
              ),
              const SizedBox(width: 8),
              Text(
                _intuitionResults!['type'].toString().toUpperCase(),
                style: MeridTheme.monoStyle(
                  fontSize: 14,
                  weight: FontWeight.bold,
                  color: isDivergence ? MeridTheme.amber : MeridTheme.emerald,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          _buildSignalIndicator(
            'Gut Feel Signal',
            _intuitionResults!['gut_feel_signal'],
            _intuitionResults!['gut_feel_signal'] == 'bearish' ? MeridTheme.rose : MeridTheme.emerald,
          ),
          const SizedBox(height: 12),
          _buildSignalIndicator(
            'Price Action',
            _intuitionResults!['price_action'],
            _intuitionResults!['price_action'] == 'bearish' ? MeridTheme.rose : MeridTheme.emerald,
          ),
          const SizedBox(height: 16),
          _buildResultRow('Divergence Magnitude', '${(_intuitionResults!['divergence_magnitude'] * 100).toStringAsFixed(0)}%', isDivergence ? MeridTheme.amber : null),
          _buildResultRow('Self-Supervised Confidence', '${(_intuitionResults!['self_supervised_confidence'] * 100).toStringAsFixed(0)}%'),
          _buildResultRow('Historical Accuracy', '${(_intuitionResults!['historical_accuracy'] * 100).toStringAsFixed(0)}%'),
          _buildResultRow('Patterns Indexed', _intuitionResults!['patterns_indexed'].toString()),
          const Divider(color: MeridTheme.surfaceLight, height: 24),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: isDivergence ? MeridTheme.amber.withOpacity(0.1) : MeridTheme.emerald.withOpacity(0.1),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              _intuitionResults!['recommendation'],
              style: MeridTheme.monoStyle(
                fontSize: 12,
                color: MeridTheme.textPrimary,
              ),
            ),
          ),
          if (isDivergence) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: MeridTheme.rose.withOpacity(0.1),
                borderRadius: BorderRadius.circular(4),
                border: Border.all(color: MeridTheme.rose.withOpacity(0.3)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.psychology, color: MeridTheme.rose, size: 16),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'NARRATIVE IMMUNITY: Sentiment treated as hypothesis, not truth',
                      style: MeridTheme.monoStyle(
                        fontSize: 11,
                        color: MeridTheme.rose,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    ).animate().fadeIn(duration: 400.ms).slideY(begin: 0.1, end: 0);
  }

  Widget _buildSignalIndicator(String label, String value, Color color) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Row(
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
            value.toUpperCase(),
            style: MeridTheme.monoStyle(
              fontSize: 12,
              weight: FontWeight.bold,
              color: color,
            ),
          ),
        ],
      ),
    );
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
