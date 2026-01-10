import 'package:flutter/material.dart';
import 'package:merid/core/theme.dart';
import 'package:merid/core/constants.dart';

class CharterScreen extends StatelessWidget {
  const CharterScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('CHARTER v2.0 // IMMUTABLE'),
        backgroundColor: MeridTheme.background,
      ),
      body: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [
              MeridTheme.background,
              MeridTheme.surface.withValues(alpha: 0.3),
            ],
          ),
        ),
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _buildHeader(),
            const SizedBox(height: 24),
            _buildSection(
              title: 'PRIME DIRECTIVES',
              items: MeridConstants.charterPrinciples,
              color: MeridTheme.amber,
            ),
            const SizedBox(height: 24),
            _buildSection(
              title: 'INVARIANTS & SAFEGUARDS',
              items: MeridConstants.invariants,
              color: MeridTheme.emerald,
            ),
            const SizedBox(height: 24),
            _buildPhilosophy(),
          ],
        ),
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
                'MERID CHARTER v2.0',
                style: MeridTheme.monoStyle(
                  fontSize: 20,
                  weight: FontWeight.bold,
                  color: MeridTheme.amber,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Text(
            'IMMUTABLE GOVERNANCE LAYER',
            style: MeridTheme.monoStyle(
              fontSize: 12,
              color: MeridTheme.textSecondary,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'This Charter defines the unbreakable contract between human and machine. It governs all cognition, execution, and evolution. No component may bypass or modify these principles.',
            style: MeridTheme.monoStyle(
              fontSize: 13,
              color: MeridTheme.textPrimary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSection({
    required String title,
    required List<String> items,
    required Color color,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.1),
            border: Border(
              left: BorderSide(color: color, width: 3),
            ),
          ),
          child: Text(
            title,
            style: MeridTheme.monoStyle(
              fontSize: 14,
              weight: FontWeight.bold,
              color: color,
            ),
          ),
        ),
        const SizedBox(height: 12),
        ...items.asMap().entries.map((entry) {
          String item = entry.value;
          return Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  margin: const EdgeInsets.only(top: 6),
                  width: 6,
                  height: 6,
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.6),
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    item,
                    style: MeridTheme.monoStyle(
                      fontSize: 13,
                      color: MeridTheme.textPrimary,
                    ),
                  ),
                ),
              ],
            ),
          );
        }),
      ],
    );
  }

  Widget _buildPhilosophy() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: MeridTheme.glowBox(color: MeridTheme.emerald, intensity: 0.2),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'PHILOSOPHICAL FOUNDATION',
            style: MeridTheme.monoStyle(
              fontSize: 14,
              weight: FontWeight.bold,
              color: MeridTheme.emerald,
            ),
          ),
          const SizedBox(height: 16),
          _buildPhilosophyItem('Decision Organism',
              'MERID is a living system with anatomy, memory, health metrics, and capacity for perpetual evolution - not a static tool.'),
          _buildPhilosophyItem('Unrestricted Cognition / Constrained Execution',
              'Internal thought is completely free to explore any hypothesis, including taboo or adversarial scenarios. All actions are strictly gated by governance and human approval.'),
          _buildPhilosophyItem('Emotionless / Narrative-Immune',
              'Outputs are calm and evidence-based. Narratives are treated as hypotheses. Price and structure are truth; sentiment and prediction markets are advisory and decay over time.'),
          _buildPhilosophyItem('Anti-Manipulation / Pro-Human',
              'Rejects all forms of nudging, hidden stakeholders, and asymmetric information. Humans retain ultimate agency and control.'),
          _buildPhilosophyItem('Quantum-Ready & Sovereign',
              'Operates entirely offline/local. Quantum simulation for candidate generation. No cloud dependencies. Human primacy is absolute.'),
        ],
      ),
    );
  }

  Widget _buildPhilosophyItem(String title, String description) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title.toUpperCase(),
            style: MeridTheme.monoStyle(
              fontSize: 12,
              weight: FontWeight.bold,
              color: MeridTheme.amber,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            description,
            style: MeridTheme.monoStyle(
              fontSize: 12,
              color: MeridTheme.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}
