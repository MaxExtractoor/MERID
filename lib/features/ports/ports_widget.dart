import 'package:flutter/material.dart';
import 'package:merid/core/theme.dart';
import 'package:merid/core/constants.dart';
import 'package:merid/core/database.dart';

class PortsWidget extends StatefulWidget {
  const PortsWidget({super.key});

  @override
  State<PortsWidget> createState() => _PortsWidgetState();
}

class _PortsWidgetState extends State<PortsWidget> {
  final MeridDatabase _db = MeridDatabase();
  List<Map<String, dynamic>> _ports = [];

  @override
  void initState() {
    super.initState();
    _loadPorts();
  }

  Future<void> _loadPorts() async {
    final ports = await _db.getAllPorts();
    if (ports.isEmpty) {
      // Initialize default ports
      for (var entry in MeridConstants.portTiers.entries) {
        await _db.updatePortStatus(
          name: entry.key,
          tier: entry.value,
          status: MeridConstants.portStatus[entry.key] ?? 'unknown',
        );
      }
      final updatedPorts = await _db.getAllPorts();
      setState(() {
        _ports = updatedPorts;
      });
    } else {
      setState(() {
        _ports = ports;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: MeridTheme.glowBox(color: MeridTheme.emerald, intensity: 0.3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildHeader(),
          const SizedBox(height: 16),
          if (_ports.isEmpty)
            const Center(
              child: CircularProgressIndicator(),
            )
          else
            ..._ports.map((port) {
              return Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: _buildPortItem(
                  port['name'] as String,
                  port['tier'] as int,
                  port['status'] as String,
                ),
              );
            }),
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
        ),
        const SizedBox(width: 12),
        Text(
          'PORTS',
          style: MeridTheme.monoStyle(
            fontSize: 16,
            weight: FontWeight.bold,
            color: MeridTheme.emerald,
          ),
        ),
      ],
    );
  }

  Widget _buildPortItem(String name, int tier, String status) {
    final statusColor = _getStatusColor(status);
    final tierColor = _getTierColor(tier);

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: MeridTheme.surface,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(
          color: statusColor.withValues(alpha: 0.5),
          width: 1,
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: statusColor,
              shape: BoxShape.circle,
              boxShadow: [
                BoxShadow(
                  color: statusColor.withValues(alpha: 0.5),
                  blurRadius: 4,
                ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  style: MeridTheme.monoStyle(
                    fontSize: 13,
                    color: MeridTheme.textPrimary,
                    weight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  _formatStatus(status),
                  style: MeridTheme.monoStyle(
                    fontSize: 11,
                    color: MeridTheme.textSecondary,
                  ),
                ),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: tierColor.withValues(alpha: 0.2),
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: tierColor.withValues(alpha: 0.5)),
            ),
            child: Text(
              'Tier $tier',
              style: MeridTheme.monoStyle(
                fontSize: 10,
                color: tierColor,
                weight: FontWeight.bold,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Color _getStatusColor(String status) {
    switch (status) {
      case 'secure':
        return MeridTheme.emerald;
      case 'active':
        return MeridTheme.amber;
      case 'quarantined':
        return MeridTheme.rose;
      case 'candidate_gen':
      case 'hypotheses':
      case 'timing_exploit':
        return MeridTheme.amber;
      default:
        return MeridTheme.textDim;
    }
  }

  Color _getTierColor(int tier) {
    switch (tier) {
      case 1:
        return MeridTheme.emerald;
      case 2:
        return MeridTheme.amber;
      case 3:
        return MeridTheme.amber;
      case 4:
        return MeridTheme.rose;
      default:
        return MeridTheme.textDim;
    }
  }

  String _formatStatus(String status) {
    switch (status) {
      case 'secure':
        return 'Secure (read-only)';
      case 'active':
        return 'Active (execution capable)';
      case 'quarantined':
        return 'Quarantined (hostile threat)';
      case 'candidate_gen':
        return 'Candidate generation';
      case 'hypotheses':
        return 'Hypothesis port';
      case 'timing_exploit':
        return 'Timing exploit detection';
      default:
        return status;
    }
  }
}
