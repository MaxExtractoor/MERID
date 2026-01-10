import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:merid/core/theme.dart';
import 'package:merid/services/llm_service.dart';
import 'package:merid/body_protocol/memory/memory_module.dart';
import 'package:merid/body_protocol/eyes/eyes_module.dart';

class DistillationGateWidget extends StatefulWidget {
  final Function(String, String)? onProcess;

  const DistillationGateWidget({
    super.key,
    this.onProcess,
  });

  @override
  State<DistillationGateWidget> createState() => _DistillationGateWidgetState();
}

class _DistillationGateWidgetState extends State<DistillationGateWidget> {
  final TextEditingController _inputController = TextEditingController();
  final LLMService _llmService = LLMService();
  final MemoryModule _memoryModule = MemoryModule();
  final EyesModule _eyesModule = EyesModule();

  String _rawCognition = '';
  String _distilledOutput = '';
  bool _showRaw = false;
  bool _processing = false;
  Map<String, dynamic> _ekgMetrics = {};

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: MeridTheme.glowBox(color: MeridTheme.amber, intensity: 0.3),
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildHeader(),
          const SizedBox(height: 20),
          _buildInputField(),
          const SizedBox(height: 20),
          if (_rawCognition.isNotEmpty) ...[
            _buildRawCognition(),
            const SizedBox(height: 16),
          ],
          if (_distilledOutput.isNotEmpty) ...[
            _buildDistilledOutput(),
            const SizedBox(height: 16),
          ],
          if (_ekgMetrics.isNotEmpty && _distilledOutput.isNotEmpty)
            _buildEKGMeter(),
        ],
      ),
    );
  }

  Widget _buildHeader() {
    return Row(
      children: [
        Container(
          width: 10,
          height: 10,
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
          'DISTILLATION GATE',
          style: MeridTheme.monoStyle(
            fontSize: 16,
            weight: FontWeight.bold,
            color: MeridTheme.amber,
          ),
        ),
        const Spacer(),
        if (_processing)
          const SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              valueColor: AlwaysStoppedAnimation<Color>(MeridTheme.amber),
            ),
          ),
      ],
    );
  }

  Widget _buildInputField() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'INPUT',
          style: MeridTheme.monoStyle(
            fontSize: 12,
            color: MeridTheme.textSecondary,
          ),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _inputController,
          style: MeridTheme.monoStyle(fontSize: 14),
          decoration: InputDecoration(
            hintText: 'Enter command or query...',
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
              borderSide: const BorderSide(color: MeridTheme.amber, width: 2),
            ),
          ),
          onSubmitted: _processInput,
        ),
      ],
    );
  }

  void _processInput(String input) async {
    if (input.trim().isEmpty) return;

    setState(() {
      _processing = true;
      _rawCognition = '';
      _distilledOutput = '';
    });

    try {
      // Process through Eyes module
      await _eyesModule.processInput(input);

      // Generate raw cognition via Brain + LLM
      final rawCognition = await _llmService.generateRawCognition(input);

      // Process through LLM for distilled output
      final llmResponse = await _llmService.process(input);

      // Get EKG metrics from Memory
      final ekgMetrics = await _memoryModule.getEKGMetrics();

      setState(() {
        _rawCognition = rawCognition;
        _distilledOutput = llmResponse.text;
        _ekgMetrics = ekgMetrics;
        _processing = false;
        _showRaw = false;
      });

      widget.onProcess?.call(_rawCognition, _distilledOutput);
    } catch (e) {
      setState(() {
        _distilledOutput = 'Error processing input: $e';
        _processing = false;
      });
    }
  }

  Widget _buildRawCognition() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InkWell(
          onTap: () {
            setState(() {
              _showRaw = !_showRaw;
            });
          },
          child: Row(
            children: [
              Icon(
                _showRaw
                    ? Icons.keyboard_arrow_down
                    : Icons.keyboard_arrow_right,
                color: MeridTheme.textSecondary,
                size: 16,
              ),
              const SizedBox(width: 8),
              Text(
                'RAW COGNITION (INTERNAL)',
                style: MeridTheme.monoStyle(
                  fontSize: 12,
                  color: MeridTheme.textSecondary,
                ),
              ),
            ],
          ),
        ),
        if (_showRaw) ...[
          const SizedBox(height: 8),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: MeridTheme.background,
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: MeridTheme.surfaceLight),
            ),
            child: Text(
              _rawCognition,
              style: MeridTheme.monoStyle(
                fontSize: 11,
                color: MeridTheme.textDim,
              ),
            ),
          ),
        ],
      ],
    );
  }

  Widget _buildDistilledOutput() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'DISTILLED OUTPUT',
          style: MeridTheme.monoStyle(
            fontSize: 12,
            weight: FontWeight.bold,
            color: MeridTheme.emerald,
          ),
        ),
        const SizedBox(height: 8),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: MeridTheme.surface,
            borderRadius: BorderRadius.circular(4),
            border: Border.all(
                color: MeridTheme.emerald.withValues(alpha: 0.5), width: 2),
            boxShadow: [
              BoxShadow(
                color: MeridTheme.emerald.withValues(alpha: 0.2),
                blurRadius: 12,
              ),
            ],
          ),
          child: Text(
            _distilledOutput,
            style: MeridTheme.monoStyle(
              fontSize: 13,
              color: MeridTheme.textPrimary,
            ),
          ),
        ).animate().fadeIn(duration: 400.ms).slideY(begin: 0.1, end: 0),
      ],
    );
  }

  Widget _buildEKGMeter() {
    if (_ekgMetrics.isEmpty) return const SizedBox.shrink();

    final entropy = (_ekgMetrics['entropy'] as num?)?.toDouble() ?? 0.0;
    final confidence = (_ekgMetrics['confidence'] as num?)?.toDouble() ?? 0.0;
    final bias = (_ekgMetrics['bias'] as num?)?.toDouble() ?? 0.0;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: MeridTheme.background,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: MeridTheme.surfaceLight),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'EKG METRICS',
            style: MeridTheme.monoStyle(
              fontSize: 12,
              color: MeridTheme.textSecondary,
            ),
          ),
          const SizedBox(height: 12),
          _buildEKGRow('Entropy', entropy, 5.0, MeridTheme.amber),
          const SizedBox(height: 8),
          _buildEKGRow('Confidence', confidence, 1.0, MeridTheme.emerald),
          const SizedBox(height: 8),
          _buildEKGRow('Bias', bias, 1.0, MeridTheme.rose),
        ],
      ),
    );
  }

  Widget _buildEKGRow(String label, double value, double max, Color color) {
    final percentage = value / max;
    return Row(
      children: [
        SizedBox(
          width: 80,
          child: Text(
            label,
            style: MeridTheme.monoStyle(
              fontSize: 11,
              color: MeridTheme.textSecondary,
            ),
          ),
        ),
        Expanded(
          child: Stack(
            children: [
              Container(
                height: 8,
                decoration: BoxDecoration(
                  color: MeridTheme.surfaceLight,
                  borderRadius: BorderRadius.circular(4),
                ),
              ),
              FractionallySizedBox(
                widthFactor: percentage.clamp(0.0, 1.0),
                child: Container(
                  height: 8,
                  decoration: BoxDecoration(
                    color: color,
                    borderRadius: BorderRadius.circular(4),
                    boxShadow: [
                      BoxShadow(
                        color: color.withValues(alpha: 0.5),
                        blurRadius: 4,
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: 12),
        SizedBox(
          width: 50,
          child: Text(
            value.toStringAsFixed(2),
            style: MeridTheme.monoStyle(
              fontSize: 11,
              color: color,
            ),
            textAlign: TextAlign.right,
          ),
        ),
      ],
    );
  }

  @override
  void dispose() {
    _inputController.dispose();
    super.dispose();
  }
}
