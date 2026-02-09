"""MERID Signals — Unified ingestion, processing, and feature extraction.

§1 Domain objects: InfoEvent, SentimentFeature, SentimentSpike
§2 Ingestion: XWorker, TelegramWorker, NewsWorker
§3 Processing: SentimentProcessor, spike detection
§4 Agents: SentimentAgent, NewsThesisAgent, TelegramOpsAgent
§5 Operator I/O: AlertRouter for Telegram + X outbound

Signal Layer (decay-aware opportunity discovery):
§D1 Decay: DecayConfig, decay_weight(), DecayEnvelope, SignalSnapshot
§D2 Features: NewsFeatures, MacroFeatures, OnChainFeatures, SocialFeatures
§D3 Arbitrage: DislocationScanner, DislocationSignal, ArbPlan with TTL
§D4 Store: SignalStore (SQLite persistence)
§D5 Drift: DriftDetector, DomainDriftMetric, ConsensusQualityIndex
"""
