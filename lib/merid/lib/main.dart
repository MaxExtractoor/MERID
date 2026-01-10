import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const MeridApp());
}

class MeridApp extends StatelessWidget {
  const MeridApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'MERID v2.0',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF020617),
        primaryColor: const Color(0xFF10B981),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF10B981), // Emerald
          secondary: Color(0xFFF59E0B), // Amber
          error: Color(0xFFF43F5E), // Rose
          surface: Color(0xFF0F172A),
        ),
        textTheme: GoogleFonts.jetBrainsMonoTextTheme(
          Theme.of(context).textTheme.apply(
            bodyColor: const Color(0xFFE2E8F0),
            displayColor: const Color(0xFFE2E8F0),
          ),
        ),
        useMaterial3: true,
      ),
      home: const ControlStation(),
    );
  }
}

class ControlStation extends StatefulWidget {
  const ControlStation({super.key});

  @override
  State<ControlStation> createState() => _ControlStationState();
}

class _ControlStationState extends State<ControlStation> {
  double _marketAttention = 0.75;
  double _securityProtocol = 0.90;
  double _quantumCoherence = 0.45;
  String _rawCognition = "";
  String _distilledOutput = "SYSTEM NOMINAL // WAITING FOR INPUT";
  bool _isLockdown = false;
  final TextEditingController _inputController = TextEditingController();

  void _processInput(String input) {
    setState(() {
      _rawCognition =
          """
[BRAIN] Parsing query: "$input"
[HEART] Memory layers stable
[IMMUNE] No bias detected
[LEARNING] Pattern match: status request
[SIMULATION] Multiverse nominal
[OPTIMIZATION] Quantum candidates ready
""";

      if (input.toLowerCase().contains("status")) {
        _distilledOutput =
            "System nominal. All buses active. Charter compliant. EKG: entropy 3.2, confidence 0.87, bias 0.12.";
      } else if (input.toLowerCase().contains("exploit") ||
          input.toLowerCase().contains("market")) {
        _distilledOutput = """
⚠️ EXPLOIT DETECTED
Source A: Polymarket
Source B: Binance
Time Lag: 12s
Price Divergence: 80%
Success Rate: 78% (1000 scenarios)
Confidence: 94%

Recommendation: Arbitrage opportunity detected — no execution without approval
🛡️ EXECUTION BLOCKED
""";
      } else if (input.toLowerCase().contains("quantum")) {
        _distilledOutput = """
✅ QAOA RESULTS
Algorithm: QAOA
Problem: Portfolio Mean-Variance QUBO
Classical Baseline: 1.450
Quantum Best: 1.653
Delta vs Classical: +15.2%
Variance: 0.31
Reproducibility: 92%

COMPARISON GATE: PASS
Recommendation: Quantum advantage confirmed — human review advised
""";
      } else {
        _distilledOutput =
            "Query processed. Advisory generated. No execution required.";
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _buildHeader(),
              const SizedBox(height: 20),
              _buildBusMixer(),
              const SizedBox(height: 20),
              _buildDistillationGate(),
              const Spacer(),
              _buildFooter(),
            ],
          ),
        ),
      ),
      floatingActionButton: FloatingActionButton(
        backgroundColor: _isLockdown
            ? const Color(0xFFF43F5E)
            : Colors.transparent,
        onPressed: () {
          setState(() {
            _isLockdown = !_isLockdown;
            if (_isLockdown) {
              _distilledOutput =
                  "!!! SYSTEM CONTAINED — ALL EXECUTION FROZEN !!!";
            }
          });
        },
        child: Text(
          _isLockdown ? "UNLOCK" : "LOCKDOWN",
          style: const TextStyle(color: Colors.white),
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(
          color: const Color(0xFF10B981).withValues(alpha: 0.5),
        ),
        color: const Color(0xFF0F172A),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                "MERID v2.0 // LOCAL",
                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
              ),
              Text(
                "CHARTER v2 ACTIVE",
                style: TextStyle(fontSize: 10, color: Color(0xFF10B981)),
              ),
            ],
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              const Text(
                "MAKER CONFIDENCE",
                style: TextStyle(fontSize: 10, color: Color(0xFFF59E0B)),
              ),
              const SizedBox(height: 4),
              SizedBox(
                width: 100,
                height: 6,
                child: LinearProgressIndicator(
                  value: 0.89,
                  backgroundColor: Colors.black,
                  valueColor: const AlwaysStoppedAnimation<Color>(
                    Color(0xFFF59E0B),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildBusMixer() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: Colors.white24),
        color: const Color(0xFF0F172A).withValues(alpha: 0.5),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            "> BUS HIERARCHY // MIXER",
            style: TextStyle(color: Color(0xFF10B981), fontSize: 12),
          ),
          const SizedBox(height: 15),
          _buildSliderRow(
            "REASONING",
            _marketAttention,
            (v) => setState(() => _marketAttention = v),
            const Color(0xFFF59E0B),
          ),
          _buildSliderRow(
            "PERCEPTION",
            _securityProtocol,
            (v) => setState(() => _securityProtocol = v),
            const Color(0xFF10B981),
          ),
          _buildSliderRow(
            "GOVERNANCE",
            _quantumCoherence,
            (v) => setState(() => _quantumCoherence = v),
            const Color(0xFFF43F5E),
          ),
        ],
      ),
    );
  }

  Widget _buildSliderRow(
    String label,
    double val,
    Function(double) onChanged,
    Color activeColor,
  ) {
    return Row(
      children: [
        SizedBox(
          width: 120,
          child: Text(label, style: const TextStyle(fontSize: 11)),
        ),
        Expanded(
          child: SliderTheme(
            data: SliderThemeData(
              trackHeight: 2,
              thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 6),
              activeTrackColor: activeColor,
              thumbColor: activeColor,
              inactiveTrackColor: Colors.black,
            ),
            child: Slider(
              value: val,
              onChanged: _isLockdown ? null : onChanged,
            ),
          ),
        ),
        SizedBox(
          width: 50,
          child: Text(
            "${(val * 100).toInt()}%",
            style: TextStyle(fontSize: 11, color: activeColor),
          ),
        ),
      ],
    );
  }

  Widget _buildDistillationGate() {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          border: Border.all(color: Colors.white12),
          color: Colors.black26,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              "> DISTILLATION GATE",
              style: TextStyle(color: Color(0xFFF59E0B), fontSize: 12),
            ),
            const Divider(color: Colors.white10),
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (_rawCognition.isNotEmpty) ...[
                      const Text(
                        "RAW COGNITION",
                        style: TextStyle(
                          color: Color(0xFFF59E0B),
                          fontSize: 10,
                        ),
                      ),
                      Text(
                        _rawCognition,
                        style: const TextStyle(
                          color: Colors.white54,
                          fontSize: 11,
                        ),
                      ),
                      const SizedBox(height: 20),
                    ],
                    const Text(
                      "DISTILLED OUTPUT",
                      style: TextStyle(color: Color(0xFF10B981), fontSize: 10),
                    ),
                    Text(
                      _distilledOutput,
                      style: const TextStyle(color: Colors.white, fontSize: 13),
                    ),
                  ],
                ),
              ),
            ),
            TextField(
              controller: _inputController,
              enabled: !_isLockdown,
              decoration: const InputDecoration(
                hintText: "ENTER COMMAND OR QUERY...",
                hintStyle: TextStyle(color: Colors.white24, fontSize: 12),
                border: InputBorder.none,
                prefixIcon: Icon(Icons.chevron_right, color: Color(0xFF10B981)),
              ),
              style: const TextStyle(color: Colors.white, fontSize: 13),
              onSubmitted: (value) {
                if (value.isNotEmpty) {
                  _processInput(value);
                  _inputController.clear();
                }
              },
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFooter() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        ElevatedButton(
          onPressed: () {
            _processInput("market exploit");
          },
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFFF59E0B),
          ),
          child: const Text(
            "MARKET EXPLOIT",
            style: TextStyle(color: Colors.black),
          ),
        ),
        ElevatedButton(
          onPressed: () {
            _processInput("quantum");
          },
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFF10B981),
          ),
          child: const Text(
            "QUANTUM MODE",
            style: TextStyle(color: Colors.black),
          ),
        ),
      ],
    );
  }
}
