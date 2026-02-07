import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_fonts/google_fonts.dart';

import 'models.dart';
import 'providers.dart';

class PrimeScreenApp extends StatelessWidget {
  const PrimeScreenApp({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: const Color(0xFF01040D),
      colorScheme: const ColorScheme.dark(
        primary: Color(0xFF34D399),
        secondary: Color(0xFFFB923C),
        surface: Color(0xFF0F172A),
      ),
      textTheme: GoogleFonts.spaceGroteskTextTheme(
        Theme.of(context).textTheme.apply(
              bodyColor: const Color(0xFFE2E8F0),
              displayColor: const Color(0xFFE2E8F0),
            ),
      ),
      useMaterial3: true,
    );

    return MaterialApp(
      title: 'MERID Prime Screen',
      debugShowCheckedModeBanner: false,
      theme: theme,
      home: const PrimeScreenShell(),
    );
  }
}

class _NarrativeSection extends ConsumerStatefulWidget {
  const _NarrativeSection({required this.detail});

  final DecisionDetail detail;

  @override
  ConsumerState<_NarrativeSection> createState() => _NarrativeSectionState();
}

class _NarrativeSectionState extends ConsumerState<_NarrativeSection> {
  bool _retrying = false;

  @override
  Widget build(BuildContext context) {
    final status = widget.detail.narrativeStatus.toLowerCase();
    final narrative = widget.detail.narrative;
    final actions = ref.read(primeScreenActionsProvider);

    Future<void> retry() async {
      setState(() => _retrying = true);
      try {
        final context = this.context;
        await actions.retryNarrative(widget.detail.decision.decisionId);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Explanation retry requested.')),
          );
        }
      } catch (error) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Retry failed: $error')),
          );
        }
      } finally {
        if (mounted) {
          setState(() => _retrying = false);
        }
      }
    }

    Widget content;
    switch (status) {
      case 'ready':
        content = Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.white10),
            color: const Color(0xFF0B1324),
          ),
          child: Text(
            narrative?.trim().isNotEmpty == true
                ? narrative!.trim()
                : 'Explanation unavailable.',
            style: Theme.of(context).textTheme.bodyMedium,
          ),
        );
        break;
      case 'failed':
        content = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: const [
                Icon(Icons.error_outline, color: Colors.amberAccent, size: 18),
                SizedBox(width: 8),
                Text('Explanation failed'),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                OutlinedButton.icon(
                  onPressed: _retrying ? null : retry,
                  icon: const Icon(Icons.refresh),
                  label: const Text('Retry explanation'),
                ),
                if (_retrying) ...[
                  const SizedBox(width: 12),
                  const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ],
              ],
            ),
          ],
        );
        break;
      default:
        content = Row(
          children: const [
            SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            SizedBox(width: 8),
            Text('Explanation is being generated…'),
          ],
        );
        break;
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Explanation', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        content,
      ],
    );
  }
}

void _showConnectionErrorSnack(
  BuildContext context, {
  required String source,
  String? detail,
}) {
  final messenger = ScaffoldMessenger.of(context);
  messenger.showSnackBar(
    SnackBar(
      backgroundColor: Colors.redAccent.shade200,
      content: Text(
        detail == null
            ? '$source connection lost. Check the backend.'
            : '$source error: $detail',
      ),
      duration: const Duration(seconds: 4),
    ),
  );
}

class _ConnectionStatusStrip extends StatelessWidget {
  const _ConnectionStatusStrip({
    required this.primeScreenHealth,
    required this.autonomyHealth,
  });

  final ConnectionHealth primeScreenHealth;
  final ConnectionHealth autonomyHealth;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 12,
      runSpacing: 8,
      children: [
        _ConnectionBadge(
          label: 'Prime Screen Feed',
          health: primeScreenHealth,
        ),
        _ConnectionBadge(
          label: 'Autonomy Feed',
          health: autonomyHealth,
        ),
      ],
    );
  }
}

class _ConnectionBadge extends StatelessWidget {
  const _ConnectionBadge({required this.label, required this.health});

  final String label;
  final ConnectionHealth health;

  @override
  Widget build(BuildContext context) {
    final (color, text) = switch (health.status) {
      ConnectionStatus.connecting => (Colors.blueGrey, 'Connecting'),
      ConnectionStatus.connected => (Colors.tealAccent, 'Connected'),
      ConnectionStatus.degraded => (Colors.amberAccent, 'Degraded'),
      ConnectionStatus.error => (Colors.redAccent, 'Error'),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.4)),
        color: color.withValues(alpha: 0.1),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            margin: const EdgeInsets.only(right: 8),
            decoration: BoxDecoration(
              color: color,
              shape: BoxShape.circle,
            ),
          ),
          Text(
            '$label · $text',
            style: Theme.of(context).textTheme.labelMedium,
          ),
          if (health.message != null &&
              health.status != ConnectionStatus.connected)
            Padding(
              padding: const EdgeInsets.only(left: 8),
              child: Text(
                health.message!,
                style: Theme.of(context)
                    .textTheme
                    .labelSmall
                    ?.copyWith(color: Colors.redAccent.shade100),
              ),
            ),
        ],
      ),
    );
  }
}

class _DecisionOverrideControls extends ConsumerStatefulWidget {
  const _DecisionOverrideControls({required this.decision});

  final ConsensusDecision decision;

  @override
  ConsumerState<_DecisionOverrideControls> createState() =>
      _DecisionOverrideControlsState();
}

class _DecisionOverrideControlsState
    extends ConsumerState<_DecisionOverrideControls> {
  final TextEditingController _sizeController = TextEditingController();
  final TextEditingController _reasonController = TextEditingController();
  String _selectedAction = 'approve';
  bool _isSubmitting = false;

  @override
  void initState() {
    super.initState();
    _sizeController.text = widget.decision.size.toStringAsFixed(2);
  }

  @override
  void dispose() {
    _sizeController.dispose();
    _reasonController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final actions = ref.read(primeScreenActionsProvider);

    Future<void> submitOverride() async {
      if (_reasonController.text.trim().isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Provide a reason for override.')),
        );
        return;
      }

      double? parsedSize;
      if (_sizeController.text.trim().isNotEmpty) {
        parsedSize = double.tryParse(_sizeController.text.trim());
      }

      setState(() => _isSubmitting = true);
      try {
        final context = this.context;
        await actions.overrideIntent(
          IntentOverrideRequestPayload(
            decisionId: widget.decision.decisionId,
            action: _selectedAction,
            newSize: parsedSize,
            reason: _reasonController.text.trim(),
          ),
        );
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Override recorded.')),
          );
        }
        _reasonController.clear();
      } catch (error) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Override failed: $error')),
          );
        }
      } finally {
        if (mounted) {
          setState(() => _isSubmitting = false);
        }
      }
    }

    const actionOptions = [
      DropdownMenuItem(value: 'approve', child: Text('Approve')),
      DropdownMenuItem(value: 'reject', child: Text('Reject')),
      DropdownMenuItem(value: 'hold', child: Text('Hold')),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Override Controls',
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 8),
        DropdownButtonFormField<String>(
          initialValue: _selectedAction,
          decoration: const InputDecoration(labelText: 'Action'),
          items: actionOptions,
          onChanged: (value) {
            if (value != null) {
              setState(() => _selectedAction = value);
            }
          },
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _sizeController,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(
            labelText: 'New Size (optional)',
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _reasonController,
          maxLines: 2,
          decoration: const InputDecoration(
            labelText: 'Reason',
            hintText: 'Explain why you are overriding this decision',
          ),
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: _isSubmitting ? null : submitOverride,
          icon: _isSubmitting
              ? const SizedBox(
                  height: 16,
                  width: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.rule),
          label: const Text('Dispatch Override'),
        ),
      ],
    );
  }
}

class _BacktestPanel extends ConsumerStatefulWidget {
  const _BacktestPanel();

  @override
  ConsumerState<_BacktestPanel> createState() => _BacktestPanelState();
}

class _BacktestPanelState extends ConsumerState<_BacktestPanel> {
  final TextEditingController _nameController =
      TextEditingController(text: 'Operator Backtest');
  final TextEditingController _symbolsController =
      TextEditingController(text: 'BTC,ETH');
  final TextEditingController _startController =
      TextEditingController(text: '2024-01-01T00:00:00Z');
  final TextEditingController _endController =
      TextEditingController(text: '2024-01-07T00:00:00Z');
  final TextEditingController _riskController =
      TextEditingController(text: 'balanced');
  final TextEditingController _venuesController =
      TextEditingController(text: 'binance,okx');
  final TextEditingController _dataSourceController =
      TextEditingController(text: 'prod');
  final TextEditingController _slippageController =
      TextEditingController(text: 'standard');
  final TextEditingController _seedController =
      TextEditingController(text: '42');
  bool _submitting = false;
  String _mode = 'swarm';

  @override
  void dispose() {
    _nameController.dispose();
    _symbolsController.dispose();
    _startController.dispose();
    _endController.dispose();
    _riskController.dispose();
    _venuesController.dispose();
    _dataSourceController.dispose();
    _slippageController.dispose();
    _seedController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final actions = ref.read(primeScreenActionsProvider);
    final latestId = ref.watch(latestBacktestIdProvider);

    Future<void> submitBacktest() async {
      final seed = int.tryParse(_seedController.text.trim()) ?? 42;
      final symbols = _symbolsController.text
          .split(',')
          .map((e) => e.trim())
          .where((e) => e.isNotEmpty)
          .toList();
      final venues = _venuesController.text
          .split(',')
          .map((e) => e.trim())
          .where((e) => e.isNotEmpty)
          .toList();

      if (symbols.isEmpty || venues.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text('Provide at least one symbol and venue.')),
        );
        return;
      }

      setState(() => _submitting = true);
      try {
        final context = this.context;
        final submission = await actions.submitBacktest(
          BacktestRequestPayload(
            name: _nameController.text.trim().isEmpty
                ? 'Operator Backtest'
                : _nameController.text.trim(),
            mode: _mode,
            symbols: symbols,
            start: _startController.text.trim(),
            end: _endController.text.trim(),
            riskProfile: _riskController.text.trim(),
            venues: venues,
            dataSource: _dataSourceController.text.trim(),
            slippageModel: _slippageController.text.trim(),
            seed: seed,
          ),
        );
        ref.read(latestBacktestIdProvider.notifier).state =
            submission.backtestId;
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Backtest queued: ${submission.backtestId}'),
            ),
          );
        }
      } catch (error) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Failed to submit backtest: $error')),
          );
        }
      } finally {
        if (mounted) {
          setState(() => _submitting = false);
        }
      }
    }

    final summaryAsync =
        latestId == null ? null : ref.watch(backtestSummaryProvider(latestId));
    final tradesAsync =
        latestId == null ? null : ref.watch(backtestTradesProvider(latestId));

    return _SidePanelCard(
      title: 'Backtests',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DropdownButtonFormField<String>(
            initialValue: _mode,
            decoration: const InputDecoration(labelText: 'Mode'),
            items: const [
              DropdownMenuItem(value: 'swarm', child: Text('Swarm')),
              DropdownMenuItem(value: 'solo', child: Text('Solo')),
            ],
            onChanged: (value) => setState(() => _mode = value ?? 'swarm'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _nameController,
            decoration: const InputDecoration(labelText: 'Name'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _symbolsController,
            decoration: const InputDecoration(
              labelText: 'Symbols (comma separated)',
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _startController,
                  decoration: const InputDecoration(labelText: 'Start ISO'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: TextField(
                  controller: _endController,
                  decoration: const InputDecoration(labelText: 'End ISO'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _riskController,
            decoration: const InputDecoration(labelText: 'Risk Profile'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _venuesController,
            decoration: const InputDecoration(labelText: 'Venues'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _dataSourceController,
            decoration: const InputDecoration(labelText: 'Data Source'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _slippageController,
            decoration: const InputDecoration(labelText: 'Slippage Model'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _seedController,
            decoration: const InputDecoration(labelText: 'Seed'),
            keyboardType: TextInputType.number,
          ),
          const SizedBox(height: 16),
          ElevatedButton.icon(
            onPressed: _submitting ? null : submitBacktest,
            icon: _submitting
                ? const SizedBox(
                    height: 16,
                    width: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.play_arrow_rounded),
            label: const Text('Run Backtest'),
          ),
          const SizedBox(height: 16),
          if (latestId != null) ...[
            Text(
              'Latest: $latestId',
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: 8),
            if (summaryAsync != null)
              summaryAsync.when(
                data: (summary) => Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Status: ${summary.status}'),
                    Text('Trades: ${summary.totalTrades}'),
                    if (summary.realizedPnl != null)
                      Text(
                        'PnL: ${summary.realizedPnl!.toStringAsFixed(2)}',
                      ),
                  ],
                ),
                loading: () => const LinearProgressIndicator(),
                error: (error, _) => Text('Summary error: $error'),
              ),
            const SizedBox(height: 8),
            if (tradesAsync != null)
              tradesAsync.when(
                data: (trades) => trades.isEmpty
                    ? const Text('No trades yet.')
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: trades
                            .take(3)
                            .map(
                              (trade) => Text(
                                  '${trade.symbol} ${trade.action} ${trade.size.toStringAsFixed(2)} @ ${trade.avgPrice.toStringAsFixed(1)}'),
                            )
                            .toList(),
                      ),
                loading: () => const LinearProgressIndicator(),
                error: (error, _) => Text('Trades error: $error'),
              ),
          ],
        ],
      ),
    );
  }
}

class PrimeScreenShell extends ConsumerWidget {
  const PrimeScreenShell({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final primeScreenAsync = ref.watch(primeScreenStateStreamProvider);
    final autonomyAsync = ref.watch(autonomyStateStreamProvider);
    final primeConn = ref.watch(primeScreenConnectionProvider);
    final autoConn = ref.watch(autonomyConnectionProvider);

    ref.listen<ConnectionHealth>(primeScreenConnectionProvider,
        (previous, next) {
      final prevStatus = previous?.status;
      if (next.status == ConnectionStatus.error &&
          prevStatus != ConnectionStatus.error) {
        _showConnectionErrorSnack(
          context,
          source: 'Prime Screen Feed',
          detail: next.message,
        );
      }
    });

    ref.listen<ConnectionHealth>(autonomyConnectionProvider, (previous, next) {
      final prevStatus = previous?.status;
      if (next.status == ConnectionStatus.error &&
          prevStatus != ConnectionStatus.error) {
        _showConnectionErrorSnack(
          context,
          source: 'Autonomy Feed',
          detail: next.message,
        );
      }
    });

    final latestState = primeScreenAsync.asData?.value;
    final autonomyState = autonomyAsync.asData?.value;

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _PrimeScreenHeader(
                timestamp: latestState?.timestamp,
                env: latestState?.env,
                symbolCount: latestState?.symbols.length ?? 0,
                decisionCount: latestState?.consensus.length ?? 0,
                autonomyState: autonomyState,
                stateLoading: primeScreenAsync.isLoading,
                autonomyLoading: autonomyAsync.isLoading,
              ),
              const SizedBox(height: 12),
              _ConnectionStatusStrip(
                primeScreenHealth: primeConn,
                autonomyHealth: autoConn,
              ),
              const SizedBox(height: 24),
              Expanded(
                child: primeScreenAsync.when(
                  data: (state) => LayoutBuilder(
                    builder: (context, constraints) {
                      return Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            flex: 2,
                            child: SingleChildScrollView(
                              padding: const EdgeInsets.only(bottom: 32),
                              child: _PrimeScreenDashboard(state: state),
                            ),
                          ),
                          const SizedBox(width: 24),
                          SizedBox(
                            width: 420,
                            child: SingleChildScrollView(
                              padding: const EdgeInsets.only(bottom: 32),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.stretch,
                                children: [
                                  const _DecisionDetailPanel(),
                                  const SizedBox(height: 24),
                                  const AutonomyControlPanel(),
                                  const SizedBox(height: 24),
                                  const _BacktestPanel(),
                                ],
                              ),
                            ),
                          ),
                        ],
                      );
                    },
                  ),
                  loading: () => const Center(
                    child: CircularProgressIndicator(),
                  ),
                  error: (error, _) => _PrimeScreenError(message: '$error'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PrimeScreenHeader extends StatelessWidget {
  const _PrimeScreenHeader({
    required this.timestamp,
    required this.env,
    required this.symbolCount,
    required this.decisionCount,
    required this.autonomyState,
    required this.stateLoading,
    required this.autonomyLoading,
  });

  final String? timestamp;
  final String? env;
  final int symbolCount;
  final int decisionCount;
  final AutonomyState? autonomyState;
  final bool stateLoading;
  final bool autonomyLoading;

  @override
  Widget build(BuildContext context) {
    final envLabel = (env ?? 'unknown').toUpperCase();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Prime Screen',
          style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                fontWeight: FontWeight.w700,
              ),
        ),
        const SizedBox(height: 4),
        Text(
          'State // Confidence // Exposure // Control',
          style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                color: Colors.blueGrey.shade300,
              ),
        ),
        const SizedBox(height: 16),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            _StatusChip(
              label: 'ENV',
              value: envLabel,
              isLoading: stateLoading && env == null,
            ),
            _StatusChip(
              label: 'SYMBOLS',
              value: symbolCount.toString(),
              isLoading: stateLoading && symbolCount == 0,
            ),
            _StatusChip(
              label: 'DECISIONS',
              value: decisionCount.toString(),
              isLoading: stateLoading && decisionCount == 0,
            ),
            _StatusChip(
              label: 'AUTONOMY',
              value: autonomyState == null
                  ? 'pending'
                  : '${autonomyState!.globalState.toUpperCase()} · ${autonomyState!.mode.toUpperCase()}',
              isLoading: autonomyLoading && autonomyState == null,
              tone: autonomyState == null
                  ? Colors.blueGrey
                  : _autonomyColor(autonomyState!.globalState),
            ),
            _StatusChip(
              label: 'UPDATED',
              value: timestamp ?? 'syncing…',
              isLoading: stateLoading && timestamp == null,
            ),
          ],
        ),
      ],
    );
  }

  static Color _autonomyColor(String state) {
    switch (state.toLowerCase()) {
      case 'halted':
        return Colors.redAccent;
      case 'supervised':
      case 'degraded':
        return Colors.amber;
      default:
        return Colors.tealAccent;
    }
  }
}

class _PrimeScreenDashboard extends ConsumerWidget {
  const _PrimeScreenDashboard({required this.state});

  final PrimeScreenState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectedId = ref.watch(selectedDecisionIdProvider);
    if (selectedId == null && state.consensus.isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (ref.read(selectedDecisionIdProvider) == null &&
            state.consensus.isNotEmpty) {
          ref.read(selectedDecisionIdProvider.notifier).state =
              state.consensus.first.decisionId;
        }
      });
    }

    final selectedDecision = _firstWhereOrNull(
          state.consensus,
          (decision) => decision.decisionId == selectedId,
        ) ??
        state.consensus.firstOrNull;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _SectionCard(
          title: 'System Pulse',
          child: Wrap(
            spacing: 16,
            runSpacing: 16,
            children: [
              _MetricTile(
                label: 'Agents Online',
                value: state.agents.length.toString(),
                accent: Colors.tealAccent,
              ),
              _MetricTile(
                label: 'Coverage',
                value: state.symbols.join(', '),
              ),
              _MetricTile(
                label: 'Consensus Queue',
                value: state.consensus.length.toString(),
                accent: Colors.orangeAccent,
              ),
              _MetricTile(
                label: 'News Signals',
                value: state.news.length.toString(),
              ),
            ],
          ),
        ),
        const SizedBox(height: 20),
        _SectionCard(
          title: 'Consensus Decisions',
          action: IconButton(
            onPressed: () => ref.invalidate(primeScreenStateStreamProvider),
            icon: const Icon(Icons.refresh_rounded),
            color: Colors.white,
          ),
          child: state.consensus.isEmpty
              ? const Text('No consensus decisions available.')
              : Column(
                  children: [
                    for (final decision in state.consensus)
                      _DecisionListRow(
                        decision: decision,
                        isSelected: decision == selectedDecision,
                        onTap: () => ref
                            .read(selectedDecisionIdProvider.notifier)
                            .state = decision.decisionId,
                      ),
                  ],
                ),
        ),
        if (state.news.isNotEmpty) ...[
          const SizedBox(height: 20),
          _SectionCard(
            title: 'Signal Stack',
            child: Column(
              children: state.news
                  .take(4)
                  .map((news) => _SignalTile(item: news))
                  .toList(),
            ),
          ),
        ],
        if (state.predictionMarkets.isNotEmpty) ...[
          const SizedBox(height: 20),
          _SectionCard(
            title: 'Prediction Markets',
            child: Wrap(
              spacing: 16,
              runSpacing: 16,
              children: state.predictionMarkets
                  .take(4)
                  .map((market) => _MarketBookTile(market: market))
                  .toList(),
            ),
          ),
        ],
        if (state.agents.isNotEmpty) ...[
          const SizedBox(height: 20),
          _SectionCard(
            title: 'Agent Health',
            child: Column(
              children: state.agents
                  .take(6)
                  .map((agent) => _AgentRow(agent: agent))
                  .toList(),
            ),
          ),
        ],
        const SizedBox(height: 24),
      ],
    );
  }
}

class _DecisionDetailPanel extends ConsumerWidget {
  const _DecisionDetailPanel();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectedId = ref.watch(selectedDecisionIdProvider);
    if (selectedId == null) {
      return const _SidePanelCard(
        title: 'Decision Detail',
        child: Text('Select a consensus decision to inspect.'),
      );
    }

    final detailAsync = ref.watch(decisionDetailProvider(selectedId));

    return detailAsync.when(
      data: (detail) => _SidePanelCard(
        title: 'Decision Detail',
        action: IconButton(
          tooltip: 'Refresh detail',
          onPressed: () => ref.invalidate(decisionDetailProvider(selectedId)),
          icon: const Icon(Icons.refresh),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _DecisionDetailBody(detail: detail),
            const SizedBox(height: 16),
            _DecisionOverrideControls(decision: detail.decision),
          ],
        ),
      ),
      loading: () => const _SidePanelCard(
        title: 'Decision Detail',
        child: Center(child: CircularProgressIndicator()),
      ),
      error: (error, _) => _SidePanelCard(
        title: 'Decision Detail',
        child: Text('Unable to load: $error'),
      ),
    );
  }
}

class _DecisionDetailBody extends StatelessWidget {
  const _DecisionDetailBody({required this.detail});

  final DecisionDetail detail;

  @override
  Widget build(BuildContext context) {
    final stats = detail.featuresSnapshot;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${detail.decision.symbol} · ${detail.decision.action.toUpperCase()}',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 4),
        Text(
          'Expected value ${detail.decision.expectedValue.toStringAsFixed(2)} · Risk ${detail.decision.riskScore.toStringAsFixed(2)}',
        ),
        const SizedBox(height: 16),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            _DetailMetric(
                label: 'Spot', value: stats.spotPrice.toStringAsFixed(2)),
            _DetailMetric(
              label: 'Funding',
              value: stats.fundingRate.toStringAsFixed(4),
            ),
            _DetailMetric(
              label: 'Orderbook',
              value: stats.orderbookImbalance.toStringAsFixed(2),
            ),
            _DetailMetric(
              label: 'Realized Vol',
              value: stats.realizedVol1h.toStringAsFixed(2),
            ),
          ],
        ),
        const SizedBox(height: 16),
        _NarrativeSection(detail: detail),
        const SizedBox(height: 16),
        if (detail.newsRefs.isNotEmpty) ...[
          Text('Referenced Signals',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            children:
                detail.newsRefs.map((id) => Chip(label: Text(id))).toList(),
          ),
          const SizedBox(height: 16),
        ],
        Text('Risk Actions', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        if (detail.riskActions.isEmpty)
          const Text('No risk interventions recorded.')
        else
          Column(
            children: detail.riskActions
                .map(
                  (action) => ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text(action.reason),
                    subtitle: Text(action.type),
                    trailing: Text(
                        '${action.before.toStringAsFixed(1)} → ${action.after.toStringAsFixed(1)}'),
                  ),
                )
                .toList(),
          ),
        const SizedBox(height: 16),
        Text('Orders', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        if (detail.orders.isEmpty)
          const Text('No orders have been created.')
        else
          Column(
            children: detail.orders
                .map(
                  (order) => Container(
                    margin: const EdgeInsets.symmetric(vertical: 4),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 8,
                    ),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.white12),
                    ),
                    child: Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(order.venue),
                              Text(order.state,
                                  style: Theme.of(context)
                                      .textTheme
                                      .bodySmall
                                      ?.copyWith(
                                          color: Colors.blueGrey.shade200)),
                            ],
                          ),
                        ),
                        if (order.avgFillPrice != null)
                          Text('@${order.avgFillPrice!.toStringAsFixed(2)}'),
                        const SizedBox(width: 8),
                        if (order.filledQty != null)
                          Text(order.filledQty!.toStringAsFixed(2)),
                      ],
                    ),
                  ),
                )
                .toList(),
          ),
      ],
    );
  }
}

class AutonomyControlPanel extends ConsumerStatefulWidget {
  const AutonomyControlPanel({super.key});

  @override
  ConsumerState<AutonomyControlPanel> createState() =>
      _AutonomyControlPanelState();
}

class _AutonomyControlPanelState extends ConsumerState<AutonomyControlPanel> {
  final TextEditingController _reasonController = TextEditingController();
  bool _updatingState = false;
  String? _selectedGlobalState;
  String? _selectedMode;
  String? _limitUpdatingId;

  @override
  void dispose() {
    _reasonController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final autonomyAsync = ref.watch(autonomyStateStreamProvider);
    final limitsAsync = ref.watch(autonomyLimitsProvider);
    final actions = ref.read(primeScreenActionsProvider);

    final autonomy = autonomyAsync.asData?.value;
    _selectedGlobalState ??= autonomy?.globalState;
    _selectedMode ??= autonomy?.mode;

    Future<void> submitState() async {
      if (_selectedGlobalState == null || _selectedMode == null) {
        return;
      }
      setState(() => _updatingState = true);
      try {
        final context = this.context;
        await actions.updateAutonomyState(
          AutonomyStateUpdatePayload(
            globalState: _selectedGlobalState,
            mode: _selectedMode,
            reason:
                _reasonController.text.isEmpty ? null : _reasonController.text,
            updatedBy: 'operator',
          ),
        );
        _reasonController.clear();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Autonomy state updated.')),
          );
        }
      } finally {
        if (mounted) {
          setState(() => _updatingState = false);
        }
      }
    }

    Future<void> togglePortfolio(AutonomyPortfolio portfolio) async {
      setState(() => _limitUpdatingId = portfolio.portfolioId);
      try {
        final context = this.context;
        await actions.updateAutonomyLimits(
          AutonomyLimitsUpdatePayload(
            portfolioId: portfolio.portfolioId,
            enabled: !portfolio.enabled,
          ),
        );
        ref.invalidate(autonomyLimitsProvider);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                '${portfolio.portfolioId} ${portfolio.enabled ? 'paused' : 'enabled'}',
              ),
            ),
          );
        }
      } finally {
        if (mounted) {
          setState(() => _limitUpdatingId = null);
        }
      }
    }

    return _SidePanelCard(
      title: 'Autonomy Control',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DropdownButtonFormField<String>(
            initialValue: _selectedGlobalState,
            decoration: const InputDecoration(labelText: 'Global State'),
            items: const [
              DropdownMenuItem(value: 'running', child: Text('Running')),
              DropdownMenuItem(value: 'halted', child: Text('Halted')),
              DropdownMenuItem(value: 'degraded', child: Text('Degraded')),
            ],
            onChanged: (value) => setState(() => _selectedGlobalState = value),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _selectedMode,
            decoration: const InputDecoration(labelText: 'Mode'),
            items: const [
              DropdownMenuItem(value: 'manual', child: Text('Manual')),
              DropdownMenuItem(value: 'supervised', child: Text('Supervised')),
              DropdownMenuItem(value: 'full', child: Text('Full Autonomy')),
            ],
            onChanged: (value) => setState(() => _selectedMode = value),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _reasonController,
            maxLines: 2,
            decoration: const InputDecoration(
              labelText: 'Operator Note',
              hintText: 'Reason for override or change',
            ),
          ),
          const SizedBox(height: 16),
          ElevatedButton.icon(
            onPressed: _updatingState ? null : submitState,
            icon: _updatingState
                ? const SizedBox(
                    height: 16,
                    width: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.radio_button_checked),
            label: const Text('Broadcast Autonomy Update'),
          ),
          const SizedBox(height: 24),
          Text(
            'Portfolio Limits',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 12),
          limitsAsync.when(
            data: (portfolios) => Column(
              children: portfolios
                  .map(
                    (portfolio) => _PortfolioLimitTile(
                      portfolio: portfolio,
                      isUpdating: _limitUpdatingId == portfolio.portfolioId,
                      onToggle: () => togglePortfolio(portfolio),
                    ),
                  )
                  .toList(),
            ),
            loading: () => const LinearProgressIndicator(),
            error: (error, _) => Text('Limits unavailable: $error'),
          ),
        ],
      ),
    );
  }
}

class _PortfolioLimitTile extends StatelessWidget {
  const _PortfolioLimitTile({
    required this.portfolio,
    required this.isUpdating,
    required this.onToggle,
  });

  final AutonomyPortfolio portfolio;
  final bool isUpdating;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  portfolio.portfolioId,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              Switch(
                value: portfolio.enabled,
                onChanged: (_) => onToggle(),
                activeThumbColor: Colors.tealAccent,
              ),
            ],
          ),
          Text('Mandate: ${portfolio.mandate}'),
          Text('Max Notional: ${portfolio.maxNotional.toStringAsFixed(0)}'),
          Text('Max Daily Loss: ${portfolio.maxDailyLoss.toStringAsFixed(0)}'),
          const SizedBox(height: 8),
          ElevatedButton(
            onPressed: isUpdating ? null : onToggle,
            child: isUpdating
                ? const SizedBox(
                    height: 16,
                    width: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : Text(
                    portfolio.enabled ? 'Pause Portfolio' : 'Enable Portfolio'),
          ),
        ],
      ),
    );
  }
}

class _SignalTile extends StatelessWidget {
  const _SignalTile({required this.item});

  final NewsItem item;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(item.headline),
      subtitle: Text('${item.source} · ${item.publishedAt}'),
      trailing: Text('${(item.sentiment * 100).toStringAsFixed(1)}%'),
    );
  }
}

class _MarketBookTile extends StatelessWidget {
  const _MarketBookTile({required this.market});

  final PredictionMarket market;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 220,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(market.label, style: Theme.of(context).textTheme.titleMedium),
          Text('Expiry ${market.expiry}',
              style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 8),
          LinearProgressIndicator(
            value: market.houseProb,
            backgroundColor: Colors.white12,
          ),
          const SizedBox(height: 6),
          Text('House ${market.houseProb.toStringAsFixed(2)}'),
        ],
      ),
    );
  }
}

class _SidePanelCard extends StatelessWidget {
  const _SidePanelCard({
    required this.title,
    required this.child,
    this.action,
  });

  final String title;
  final Widget child;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: Colors.white10),
        boxShadow: const [
          BoxShadow(
            color: Colors.black54,
            blurRadius: 24,
            offset: Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  title,
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ),
              if (action != null) action!,
            ],
          ),
          const SizedBox(height: 16),
          child,
        ],
      ),
    );
  }
}

class _DetailMetric extends StatelessWidget {
  const _DetailMetric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.labelSmall),
          Text(
            value,
            style: Theme.of(context).textTheme.titleMedium,
          ),
        ],
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({
    required this.label,
    required this.value,
    this.isLoading = false,
    this.tone,
  });

  final String label;
  final String value;
  final bool isLoading;
  final Color? tone;

  @override
  Widget build(BuildContext context) {
    final displayTone = tone ?? Colors.blueGrey;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      decoration: BoxDecoration(
        border: Border.all(color: displayTone.withValues(alpha: 0.4)),
        borderRadius: BorderRadius.circular(999),
        color: displayTone.withValues(alpha: 0.1),
      ),
      child: isLoading
          ? SizedBox(
              height: 16,
              width: 16,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: displayTone,
              ),
            )
          : RichText(
              text: TextSpan(
                children: [
                  TextSpan(
                    text: '$label ',
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                          color: Colors.blueGrey.shade300,
                          letterSpacing: 1.5,
                        ),
                  ),
                  TextSpan(
                    text: value,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                          color: Colors.white,
                        ),
                  ),
                ],
              ),
            ),
    );
  }
}

class _SectionCard extends StatelessWidget {
  const _SectionCard({
    required this.title,
    required this.child,
    this.action,
  });

  final String title;
  final Widget child;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: Colors.white10),
        boxShadow: const [
          BoxShadow(
            color: Colors.black54,
            blurRadius: 24,
            offset: Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  title,
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                ),
              ),
              if (action != null) action!,
            ],
          ),
          const SizedBox(height: 16),
          child,
        ],
      ),
    );
  }
}

class _MetricTile extends StatelessWidget {
  const _MetricTile({
    required this.label,
    required this.value,
    this.accent,
  });

  final String label;
  final String value;
  final Color? accent;

  @override
  Widget build(BuildContext context) {
    final borderColor = accent ?? Colors.white10;
    return Container(
      constraints: const BoxConstraints(minWidth: 180),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: borderColor.withValues(alpha: 0.4)),
        gradient: LinearGradient(
          colors: [
            Theme.of(context).colorScheme.surface,
            Theme.of(context).colorScheme.surface.withValues(alpha: 0.6),
          ],
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: Theme.of(context).textTheme.labelMedium,
          ),
          const SizedBox(height: 6),
          Text(
            value,
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
          ),
        ],
      ),
    );
  }
}

class _DecisionListRow extends StatelessWidget {
  const _DecisionListRow({
    required this.decision,
    required this.isSelected,
    required this.onTap,
  });

  final ConsensusDecision decision;
  final bool isSelected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final highlightColor =
        isSelected ? colorScheme.primary : Colors.transparent;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: highlightColor.withValues(alpha: isSelected ? 0.6 : 0.15),
            ),
            color: highlightColor.withValues(alpha: isSelected ? 0.08 : 0.02),
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      decision.symbol,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${decision.action.toUpperCase()} · Score ${decision.score.toStringAsFixed(2)}',
                      style: Theme.of(context)
                          .textTheme
                          .bodyMedium
                          ?.copyWith(color: Colors.blueGrey.shade200),
                    ),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                      '${decision.size.toStringAsFixed(2)} / ${decision.expectedValue.toStringAsFixed(2)}'),
                  Text(
                    'Risk ${decision.riskScore.toStringAsFixed(1)}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AgentRow extends StatelessWidget {
  const _AgentRow({required this.agent});

  final AgentState agent;

  @override
  Widget build(BuildContext context) {
    final health = agent.health;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(agent.name,
                    style: Theme.of(context).textTheme.titleMedium),
                Text(
                  '${agent.role} · ${agent.status}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
          _HealthPill(
            label: 'Latency',
            value: '${health.latencyMs.toStringAsFixed(0)}ms',
          ),
          const SizedBox(width: 12),
          _HealthPill(
            label: 'Errors',
            value: '${(health.errorRate1m * 100).toStringAsFixed(1)}%',
            tone:
                health.errorRate1m > 0.1 ? Colors.redAccent : Colors.tealAccent,
          ),
        ],
      ),
    );
  }
}

class _HealthPill extends StatelessWidget {
  const _HealthPill({
    required this.label,
    required this.value,
    this.tone = Colors.tealAccent,
  });

  final String label;
  final String value;
  final Color tone;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: tone.withValues(alpha: 0.1),
        border: Border.all(color: tone.withValues(alpha: 0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: Colors.blueGrey.shade200,
                ),
          ),
          Text(
            value,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Colors.white,
                  fontWeight: FontWeight.w600,
                ),
          ),
        ],
      ),
    );
  }
}

class _PrimeScreenError extends StatelessWidget {
  const _PrimeScreenError({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.error_outline, color: Colors.redAccent, size: 36),
          const SizedBox(height: 12),
          Text(
            'Prime Screen feed unavailable',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 6),
          Text(
            message,
            textAlign: TextAlign.center,
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: Colors.redAccent.shade100),
          ),
        ],
      ),
    );
  }
}

extension<T> on List<T> {
  T? get firstOrNull => isEmpty ? null : first;
}

T? _firstWhereOrNull<T>(Iterable<T> items, bool Function(T) test) {
  for (final item in items) {
    if (test(item)) {
      return item;
    }
  }
  return null;
}
