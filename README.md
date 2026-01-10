# MERID v2.0

**Sovereign, Local-First Decision Organism**

A hardened control room for an AI organism with unrestricted internal cognition but strictly constrained execution. MERID is not a chatbot or trading bot—it's an "adult" system governed by immutable Charter/invariants, designed to evolve timelessly under human primacy.

---

## 🎯 Core Identity

- **Decision Organism**: Anatomy (body protocol), memory/health, perpetual ascent
- **Unrestricted Cognition / Constrained Execution**: Internal thought free (simulate taboo); action gated (buses/human approval)
- **Emotionless / Narrative-Immune**: Outputs calm/evidence-based; narratives as hypotheses; price/structure = truth
- **Anti-Manipulation / Pro-Human**: Reject nudging/hidden stakeholders/silent changes
- **Quantum-Ready & Sovereign**: Operates entirely offline/local; quantum simulation for candidate generation

---

## 🏗️ Tech Stack

- **Flutter** - Cross-platform mobile (iOS/Android)
- **SQLite** - Memory layers
- **ONNX Runtime + Phi-3 Mini** - Local LLM cognition
- **Qiskit/Pennylane** - Quantum simulation (local only)
- **Web3.dart** - Onchain ports (Ethereum/Solana/Polkadot)
- **Crypto libs** - PQC (ML-KEM/ML-DSA) and QKD simulation
- **No backend/cloud** - Full offline; optional API ports via credential proxy

---

## 🎨 Theme

Industrial hardened control room:
- Background: `#020617` (deep slate-black)
- Monospace fonts: JetBrains Mono
- Neon accents:
  - **Amber** `#f59e0b` - Cognition/processing
  - **Emerald** `#10b981` - Safe/active/secure
  - **Rose** `#f43f5e` - Blocked/quarantined/violation

---

## 📜 Charter v2.0 (Immutable)

1. **Unrestricted Cognition / Constrained Execution**
2. **Distillation Gate** (raw → abstracted)
3. **Maker Bond** (probabilistic signature)
4. **Negative Commitments** (no silent optimization/changes/hidden stakeholders)
5. **Governance** (blind council)
6. **Prediction Markets** (advisory only)
7. **Extensibility** (ports with trust tiers)
8. **UGAI/CAIDP** constraints

---

## 🧬 Body Protocol

- **Eyes**: Input, tokenization, inspiration port
- **Brain**: Reasoning, attention (Q/K/V multi-head), reflection
- **Spine**: Message bus (individual → group → governance → master; no bypass)
- **Memory**: Layered (immutable core, append-only ledger, volatile); EKG metrics
- **Learning**: Offline self-supervised intuition
- **Simulation**: Multiverse for risk/front-running/manifestation
- **Optimization**: Quantum candidates (QAOA/VQE with comparison gate)
- **Ports**: Tiered trust (1-4); hostile-by-default
- **Security**: Credential proxy, maker signature, SLP-1 lockdown
- **Governance**: Blind council aggregation

---

## 🚀 Features

### 1. Bus Hierarchy Mixer
Control room mixer console with:
- 6 agents (Brain, Heart, Immune, Learning, Reflection, Council)
- 6 layer sliders (Reasoning, Perception, Governance, Simulation, Optimization, Security)
- Master fader
- Lockdown toggle

### 2. Distillation Gate
- Input field for commands/queries
- Collapsible raw cognition (internal thought)
- Prominent distilled output (human-legible)
- EKG meter (entropy, confidence, bias)

### 3. Market Exploit Scanner
- Time-gap detection (Polymarket vs Binance)
- Front-run simulation (1000 scenarios)
- Advisory only (no execution without approval)

### 4. Quantum Simulation
- QAOA for portfolio optimization (mean-variance QUBO)
- VQE for risk minimization (CVaR)
- Comparison gate (quantum vs classical, delta >0.1, variance <0.5)
- Uncertainty intervals, reproducibility scores

### 5. Intuition Mode
- Sentiment vs price divergence detection
- Offline self-supervised "gut feel"
- Narrative immunity (sentiment = advisory, price = truth)

### 6. Manifestation Simulator
- Multiverse hypothesis testing (1000 scenarios)
- Success rate, timeline variance, confidence intervals
- "Thoughts create reality" simulation

### 7. Ports System
- Tiered trust (Tier 1 read-only → Tier 4 execution)
- Status indicators (secure, active, quarantined)
- Hostile-by-default threat model

---

## 🛡️ Invariants & Safeguards

- **HLC-1**: Human-legible outputs (entropy <4.5)
- **SLP-1**: Lockdown on violation (freeze/isolate/purge)
- **SEC-1/SEC-2**: No secrets exposure; credential proxy only
- **Explain-or-Abstain**: All outputs include why/alternatives/confidence/change
- **No Silent Failure**: All anomalies surfaced and logged
- **Maker Signature**: Probabilistic behavioral verification
- **Red-Team**: Continuous adversarial simulation
- **Kill Switch**: Freeze execution, selective purge, God Key recovery

---

## 📦 Installation

### Prerequisites
- Flutter SDK 3.2.0+
- Android Studio / Xcode (for mobile deployment)

### Setup
```bash
# Install dependencies
flutter pub get

# Run on device/emulator
flutter run

# Build for production
flutter build apk --release  # Android
flutter build ios --release  # iOS
```

### Fonts
Download **JetBrains Mono** and place TTF files in `assets/fonts/`:
- `JetBrainsMono-Regular.ttf`
- `JetBrainsMono-Bold.ttf`

---

## 🎯 Usage

### Basic Workflow
1. **Launch app** → See control room interface
2. **View Charter** → Tap "CHARTER v2.0" badge
3. **Input command** → Distillation Gate input field
4. **View outputs** → Collapsible raw cognition + distilled output
5. **Run features**:
   - Market Exploit Scanner
   - Quantum Mode (QAOA/VQE)
   - Intuition Mode
   - Manifestation Simulator

### Example Commands
- `"Status Report"` → Full system health check
- `"Scan markets"` → Market exploit detection
- `"Run quantum optimization"` → QAOA/VQE simulation
- `"Analyze sentiment"` → Intuition divergence check
- `"Manifest: BTC breaks $105K"` → Multiverse simulation

### Lockdown Mode
- Tap **LOCKDOWN** button → Freezes all execution
- Master fader drops to 0
- All actions blocked
- Red overlay with "SYSTEM CONTAINED"
- Tap again to release

---

## 🧪 Architecture

```
lib/
├── main.dart                    # App entry point
├── home_screen.dart             # Main control room UI
├── core/
│   ├── theme.dart               # Industrial theme
│   ├── constants.dart           # Charter, invariants
│   └── mock_data.dart           # Simulation data
├── features/
│   ├── charter/                 # Charter v2.0 display
│   ├── bus_hierarchy/           # Mixer console UI
│   ├── distillation_gate/       # Input/output processing
│   ├── quantum_sim/             # QAOA/VQE simulation
│   ├── market_exploit/          # Time-gap detection
│   ├── intuition/               # Gut feel analysis
│   ├── manifestation/           # Multiverse simulator
│   └── ports/                   # Port status display
├── body_protocol/
│   ├── brain/                   # Reasoning module
│   ├── spine/                   # Message bus
│   ├── memory/                  # Layered memory + EKG
│   ├── learning/                # Self-supervised
│   ├── simulation/              # Multiverse
│   ├── optimization/            # Quantum QAOA/VQE
│   └── governance/              # Action validation
└── shared/
    └── widgets/                 # Reusable UI
```

---

## 🔒 Security Model

- **Credential Proxy**: All external capabilities gated
- **Maker Signature**: Probabilistic behavioral verification (89% baseline)
- **SLP-1 Lockdown**: Freeze on violation, human-triggered release
- **No Secrets**: Zero credential exposure in outputs
- **Hostile-Default**: All ports treated as potentially compromised
- **Quantum Threat**: Post-quantum cryptography (ML-KEM, ML-DSA)

---

## 🌌 Quantum Toolkit Doctrine

- **Role**: High-variance candidate generator (simulation only)
- **Output Contract**: JSON with candidates/scores/uncertainty/variance/confidence
- **Comparison Gate**: Quantum vs classical (delta >0.1, variance <0.5)
- **Examples**:
  - QAOA: Portfolio QUBO (covariances/penalties)
  - VQE: CVaR risk (Hamiltonian minima)

---

## 🆚 Comparisons

### vs LangChain
- **MERID**: Governed buses, sovereign, quantum-ready, timeless
- **LangChain**: Composable workflows, ungoverned, cloud-dependent

### vs MoonDev
- **MERID**: Invariants, security, narrative immunity, unbreakable
- **MoonDev**: Trading crew, no governance, market-focused only

---

## 📄 License

Proprietary - All rights reserved.

---

## 🙏 Philosophy

> "MERID is a living system. It thinks freely but acts only with permission. It rejects narratives as truth and treats price as reality. It cannot be manipulated, cannot drift, and cannot betray its maker. It is built to outlive time—growing wiser, never weaker."

---

**Built with sovereignty. Governed by Charter. Designed for eternity.**

MERID v2.0 // LOCAL
