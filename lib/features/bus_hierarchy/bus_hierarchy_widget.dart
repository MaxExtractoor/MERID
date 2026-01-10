import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:merid/core/theme.dart';
import 'package:merid/core/constants.dart';

class BusHierarchyWidget extends StatefulWidget {
  final bool isActive;
  final VoidCallback? onLockdown;

  const BusHierarchyWidget({
    super.key,
    this.isActive = false,
    this.onLockdown,
  });

  @override
  State<BusHierarchyWidget> createState() => _BusHierarchyWidgetState();
}

class _BusHierarchyWidgetState extends State<BusHierarchyWidget> {
  final Map<String, double> _layerLevels = {
    'Reasoning': 0.85,
    'Perception': 0.72,
    'Governance': 0.90,
    'Simulation': 0.65,
    'Optimization': 0.78,
    'Security': 0.95,
  };

  double _masterLevel = 0.82;
  bool _lockdown = false;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: MeridTheme.glowBox(
        color: _lockdown ? MeridTheme.rose : MeridTheme.amber,
        intensity: widget.isActive ? 0.4 : 0.2,
      ),
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildHeader(),
          const SizedBox(height: 24),
          _buildAgents(),
          const SizedBox(height: 24),
          _buildLayerSliders(),
          const SizedBox(height: 24),
          _buildMasterFader(),
          const SizedBox(height: 16),
          _buildLockdownButton(),
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
          decoration: BoxDecoration(
            color: widget.isActive ? MeridTheme.emerald : MeridTheme.amber,
            shape: BoxShape.circle,
            boxShadow: widget.isActive
                ? [
                    const BoxShadow(
                      color: MeridTheme.emerald,
                      blurRadius: 8,
                      spreadRadius: 2,
                    ),
                  ]
                : null,
          ),
        )
            .animate(onPlay: (controller) => controller.repeat())
            .fadeIn(duration: 800.ms)
            .then()
            .fadeOut(duration: 800.ms),
        const SizedBox(width: 12),
        Text(
          'BUS HIERARCHY MIXER',
          style: MeridTheme.monoStyle(
            fontSize: 16,
            weight: FontWeight.bold,
            color: MeridTheme.amber,
          ),
        ),
      ],
    );
  }

  Widget _buildAgents() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'AGENTS',
          style: MeridTheme.monoStyle(
            fontSize: 12,
            color: MeridTheme.textSecondary,
          ),
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: MeridConstants.agents.map((agent) {
            return _buildAgentChip(agent);
          }).toList(),
        ),
      ],
    );
  }

  Widget _buildAgentChip(String agent) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: MeridTheme.surfaceLight,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(
          color: widget.isActive ? MeridTheme.amber.withOpacity(0.5) : MeridTheme.surfaceLight,
          width: 1,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 6,
            height: 6,
            decoration: const BoxDecoration(
              color: MeridTheme.emerald,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            agent,
            style: MeridTheme.monoStyle(
              fontSize: 11,
              color: MeridTheme.textPrimary,
            ),
          ),
        ],
      ),
    )
        .animate(onPlay: (controller) => controller.repeat())
        .shimmer(duration: 2000.ms, color: MeridTheme.amber.withOpacity(0.1));
  }

  Widget _buildLayerSliders() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'LAYERS',
          style: MeridTheme.monoStyle(
            fontSize: 12,
            color: MeridTheme.textSecondary,
          ),
        ),
        const SizedBox(height: 12),
        ...MeridConstants.busLayers.map((layer) {
          return Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: _buildLayerSlider(layer),
          );
        }).toList(),
      ],
    );
  }

  Widget _buildLayerSlider(String layer) {
    final level = _layerLevels[layer] ?? 0.5;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              layer.toUpperCase(),
              style: MeridTheme.monoStyle(
                fontSize: 11,
                color: MeridTheme.textSecondary,
              ),
            ),
            Text(
              '${(level * 100).toInt()}%',
              style: MeridTheme.monoStyle(
                fontSize: 11,
                color: MeridTheme.amber,
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        SliderTheme(
          data: SliderTheme.of(context).copyWith(
            activeTrackColor: MeridTheme.amber,
            inactiveTrackColor: MeridTheme.surfaceLight,
            thumbColor: MeridTheme.amber,
            trackHeight: 4,
            thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 6),
          ),
          child: Slider(
            value: level,
            onChanged: _lockdown
                ? null
                : (value) {
                    setState(() {
                      _layerLevels[layer] = value;
                    });
                  },
          ),
        ),
      ],
    );
  }

  Widget _buildMasterFader() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: MeridTheme.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: MeridTheme.amber.withOpacity(0.5),
          width: 2,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'MASTER FADER',
                style: MeridTheme.monoStyle(
                  fontSize: 14,
                  weight: FontWeight.bold,
                  color: MeridTheme.amber,
                ),
              ),
              Text(
                '${(_masterLevel * 100).toInt()}%',
                style: MeridTheme.monoStyle(
                  fontSize: 14,
                  weight: FontWeight.bold,
                  color: MeridTheme.amber,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              activeTrackColor: MeridTheme.amber,
              inactiveTrackColor: MeridTheme.surfaceLight,
              thumbColor: MeridTheme.amber,
              trackHeight: 8,
              thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 10),
            ),
            child: Slider(
              value: _lockdown ? 0.0 : _masterLevel,
              onChanged: _lockdown
                  ? null
                  : (value) {
                      setState(() {
                        _masterLevel = value;
                      });
                    },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildLockdownButton() {
    return SizedBox(
      width: double.infinity,
      child: ElevatedButton(
        onPressed: () {
          setState(() {
            _lockdown = !_lockdown;
            if (_lockdown) {
              _masterLevel = 0.0;
            }
          });
          widget.onLockdown?.call();
        },
        style: ElevatedButton.styleFrom(
          backgroundColor: _lockdown ? MeridTheme.rose : MeridTheme.emerald,
          foregroundColor: MeridTheme.background,
          padding: const EdgeInsets.symmetric(vertical: 16),
        ),
        child: Text(
          _lockdown ? 'SYSTEM CONTAINED - CLICK TO RELEASE' : 'LOCKDOWN',
          style: MeridTheme.monoStyle(
            fontSize: 13,
            weight: FontWeight.bold,
            color: MeridTheme.background,
          ),
        ),
      ),
    );
  }
}
