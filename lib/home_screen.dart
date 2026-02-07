import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:merid/core/theme.dart';
import 'package:merid/core/constants.dart';
import 'package:merid/features/charter/charter_screen.dart';
import 'package:merid/features/bus_hierarchy/bus_hierarchy_widget.dart';
import 'package:merid/features/distillation_gate/distillation_gate_widget.dart';
import 'package:merid/features/ports/ports_widget.dart';
import 'package:merid/features/quantum_sim/quantum_sim_screen.dart';
import 'package:merid/features/market_exploit/market_exploit_screen.dart';
import 'package:merid/features/intuition/intuition_screen.dart';
import 'package:merid/features/manifestation/manifestation_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  bool _systemActive = false;
  bool _lockdown = false;
  final double _makerConfidence = 0.89;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [
              MeridTheme.background,
              _lockdown
                  ? MeridTheme.rose.withValues(alpha: 0.1)
                  : MeridTheme.surface.withValues(alpha: 0.3),
            ],
          ),
        ),
        child: Stack(
          children: [
            SafeArea(
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  _buildHeader(),
                  const SizedBox(height: 24),
                  BusHierarchyWidget(
                    isActive: _systemActive,
                    onLockdown: () {
                      setState(() {
                        _lockdown = !_lockdown;
                      });
                    },
                  ),
                  const SizedBox(height: 24),
                  DistillationGateWidget(
                    onProcess: (raw, distilled) {
                      setState(() {
                        _systemActive = true;
                      });
                      Future.delayed(const Duration(seconds: 3), () {
                        if (mounted) {
                          setState(() {
                            _systemActive = false;
                          });
                        }
                      });
                    },
                  ),
                  const SizedBox(height: 24),
                  _buildActionButtons(),
                  const SizedBox(height: 24),
                  const PortsWidget(),
                ],
              ),
            ),
            if (_lockdown) _buildLockdownOverlay(),
          ],
        ),
      ),
    );
  }

  Widget _buildLockdownOverlay() {
    return Container(
      color: MeridTheme.rose.withValues(alpha: 0.9),
      child: Center(
        child: Container(
          padding: const EdgeInsets.all(32),
          margin: const EdgeInsets.all(32),
          decoration: BoxDecoration(
            color: MeridTheme.background,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: MeridTheme.rose, width: 2),
            boxShadow: [
              BoxShadow(
                color: MeridTheme.rose.withValues(alpha: 0.5),
                blurRadius: 20,
                spreadRadius: 5,
              ),
            ],
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.lock,
                color: MeridTheme.rose,
                size: 48,
              ),
              const SizedBox(height: 16),
              Text(
                'SYSTEM CONTAINED',
                style: MeridTheme.monoStyle(
                  fontSize: 24,
                  weight: FontWeight.bold,
                  color: MeridTheme.rose,
                ),
              ),
              const SizedBox(height: 12),
              Text(
                'SLP-1 LOCKDOWN ACTIVE',
                style: MeridTheme.monoStyle(
                  fontSize: 14,
                  color: MeridTheme.textSecondary,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'All execution frozen. Governance gate requires human approval.',
                style: MeridTheme.monoStyle(
                  fontSize: 12,
                  color: MeridTheme.textSecondary,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              ElevatedButton(
                onPressed: () {
                  setState(() {
                    _lockdown = false;
                  });
                },
                style: ElevatedButton.styleFrom(
                  backgroundColor: MeridTheme.emerald,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 12,
                  ),
                ),
                child: Text(
                  'RELEASE LOCKDOWN',
                  style: MeridTheme.monoStyle(
                    fontSize: 12,
                    weight: FontWeight.bold,
                    color: MeridTheme.background,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: MeridTheme.glowBox(
        color: _lockdown ? MeridTheme.rose : MeridTheme.amber,
        intensity: 0.4,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                'MERID v${MeridConstants.version}',
                style: MeridTheme.monoStyle(
                  fontSize: 20,
                  weight: FontWeight.bold,
                  color: MeridTheme.textPrimary,
                ),
              ),
              const SizedBox(width: 8),
              Text(
                '// ${MeridConstants.mode}',
                style: MeridTheme.monoStyle(
                  fontSize: 20,
                  weight: FontWeight.bold,
                  color: MeridTheme.amber,
                ),
              ),
              const Spacer(),
              Container(
                width: 12,
                height: 12,
                decoration: BoxDecoration(
                  color: _lockdown
                      ? MeridTheme.rose
                      : (_systemActive ? MeridTheme.emerald : MeridTheme.amber),
                  shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(
                      color: _lockdown
                          ? MeridTheme.rose
                          : (_systemActive
                              ? MeridTheme.emerald
                              : MeridTheme.amber),
                      blurRadius: 8,
                      spreadRadius: 2,
                    ),
                  ],
                ),
              )
                  .animate(onPlay: (controller) => controller.repeat())
                  .fadeIn(duration: 800.ms)
                  .then()
                  .fadeOut(duration: 800.ms),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: InkWell(
                  onTap: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                          builder: (context) => const CharterScreen()),
                    );
                  },
                  child: Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: MeridTheme.surface,
                      borderRadius: BorderRadius.circular(4),
                      border: Border.all(
                          color: MeridTheme.emerald.withValues(alpha: 0.5)),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(Icons.shield,
                            color: MeridTheme.emerald, size: 16),
                        const SizedBox(width: 8),
                        Text(
                          'CHARTER v2.0',
                          style: MeridTheme.monoStyle(
                            fontSize: 12,
                            color: MeridTheme.emerald,
                            weight: FontWeight.bold,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: MeridTheme.surface,
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(
                      color: (_makerConfidence < 0.8
                              ? MeridTheme.amber
                              : MeridTheme.emerald)
                          .withValues(alpha: 0.5),
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'MAKER CONFIDENCE',
                        style: MeridTheme.monoStyle(
                          fontSize: 10,
                          color: MeridTheme.textSecondary,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          Expanded(
                            child: Stack(
                              children: [
                                Container(
                                  height: 6,
                                  decoration: BoxDecoration(
                                    color: MeridTheme.surfaceLight,
                                    borderRadius: BorderRadius.circular(3),
                                  ),
                                ),
                                FractionallySizedBox(
                                  widthFactor: _makerConfidence,
                                  child: Container(
                                    height: 6,
                                    decoration: BoxDecoration(
                                      color: _makerConfidence < 0.8
                                          ? MeridTheme.amber
                                          : MeridTheme.emerald,
                                      borderRadius: BorderRadius.circular(3),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(width: 8),
                          Text(
                            '${(_makerConfidence * 100).toInt()}%',
                            style: MeridTheme.monoStyle(
                              fontSize: 11,
                              color: _makerConfidence < 0.8
                                  ? MeridTheme.amber
                                  : MeridTheme.emerald,
                              weight: FontWeight.bold,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
          if (_lockdown) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: MeridTheme.rose.withValues(alpha: 0.2),
                borderRadius: BorderRadius.circular(4),
                border: Border.all(color: MeridTheme.rose),
              ),
              child: Row(
                children: [
                  const Icon(Icons.lock, color: MeridTheme.rose, size: 16),
                  const SizedBox(width: 8),
                  Text(
                    'SYSTEM CONTAINED - ALL EXECUTION FROZEN',
                    style: MeridTheme.monoStyle(
                      fontSize: 11,
                      color: MeridTheme.rose,
                      weight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildActionButtons() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'ACTIONS',
          style: MeridTheme.monoStyle(
            fontSize: 12,
            color: MeridTheme.textSecondary,
          ),
        ),
        const SizedBox(height: 12),
        GridView.count(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          crossAxisCount: 2,
          crossAxisSpacing: 12,
          mainAxisSpacing: 12,
          childAspectRatio: 2.5,
          children: [
            _buildActionButton(
              'Market Exploit',
              Icons.trending_up,
              MeridTheme.rose,
              () => Navigator.push(
                context,
                MaterialPageRoute(
                    builder: (context) => const MarketExploitScreen()),
              ),
            ),
            _buildActionButton(
              'Quantum Mode',
              Icons.psychology,
              MeridTheme.amber,
              () => Navigator.push(
                context,
                MaterialPageRoute(
                    builder: (context) => const QuantumSimScreen()),
              ),
            ),
            _buildActionButton(
              'Intuition',
              Icons.lightbulb,
              MeridTheme.amber,
              () => Navigator.push(
                context,
                MaterialPageRoute(
                    builder: (context) => const IntuitionScreen()),
              ),
            ),
            _buildActionButton(
              'Manifestation',
              Icons.auto_awesome,
              MeridTheme.emerald,
              () => Navigator.push(
                context,
                MaterialPageRoute(
                    builder: (context) => const ManifestationScreen()),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildActionButton(
      String label, IconData icon, Color color, VoidCallback onTap) {
    return InkWell(
      onTap: _lockdown ? null : onTap,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: MeridTheme.surface,
          borderRadius: BorderRadius.circular(4),
          border: Border.all(
            color: _lockdown
                ? MeridTheme.surfaceLight
                : color.withValues(alpha: 0.5),
          ),
        ),
        child: Row(
          children: [
            Icon(
              icon,
              color: _lockdown ? MeridTheme.textDim : color,
              size: 18,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                label,
                style: MeridTheme.monoStyle(
                  fontSize: 12,
                  color:
                      _lockdown ? MeridTheme.textDim : MeridTheme.textPrimary,
                  weight: FontWeight.bold,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
