class MeridConstants {
  static const String version = '2.0.0';
  static const String mode = 'LOCAL';
  
  static const List<String> charterPrinciples = [
    'PRIME DIRECTIVE: Unrestricted Cognition / Constrained Execution',
    'DISTILLATION GATE: Raw internal thought → Human-legible abstraction',
    'MAKER BOND: Anti-manipulation, probabilistic identity, right to evolution',
    'NEGATIVE COMMITMENTS: No silent optimization/changes/hidden stakeholders',
    'GOVERNANCE: Blind council aggregation, prediction markets advisory only',
    'EXTENSIBILITY: Tiered ports (1=read, 2=ephemeral, 3=state, 4=execution)',
    'UGAI/CAIDP: Accountability constraints, human primacy, termination rights',
  ];
  
  static const List<String> invariants = [
    'HLC-1: Human-legible outputs (entropy <4.5, plain English)',
    'SLP-1: Lockdown on violation (freeze/isolate/purge/respawn)',
    'SEC-1/SEC-2: No secrets exposure, credential proxy only',
    'EXPLAIN-OR-ABSTAIN: All outputs include why/alternatives/confidence/change',
    'NO SILENT FAILURE: All anomalies surfaced and logged',
    'MAKER SIGNATURE: Probabilistic behavioral verification',
    'RED-TEAM: Continuous adversarial simulation',
    'SUPPLY CHAIN: Fingerprinting, pinning, rollback capability',
    'KILL SWITCH: Freeze execution, selective purge, God Key recovery',
    'QUANTUM RULES: Candidate generator only, uncertainty mandatory',
  ];
  
  static const List<String> agents = [
    'Brain',
    'Heart',
    'Immune',
    'Learning',
    'Reflection',
    'Council',
  ];
  
  static const List<String> busLayers = [
    'Reasoning',
    'Perception',
    'Governance',
    'Simulation',
    'Optimization',
    'Security',
  ];
  
  static const Map<String, int> portTiers = {
    'Local Memory': 1,
    'Simulation': 2,
    'Web Scraper': 4,
    'Quantum Port': 2,
    'Inspiration Port': 2,
    'Prediction Market': 3,
    'Blockchain Bridge': 4,
  };
  
  static const Map<String, String> portStatus = {
    'Local Memory': 'secure',
    'Simulation': 'secure',
    'Web Scraper': 'active',
    'Quantum Port': 'candidate_gen',
    'Inspiration Port': 'hypotheses',
    'Prediction Market': 'timing_exploit',
    'Blockchain Bridge': 'quarantined',
  };
}
