"""MERID Signals — Unified ingestion, processing, and feature extraction.

§1 Domain objects: InfoEvent, SentimentFeature, SentimentSpike
§2 Ingestion: XWorker, TelegramWorker, NewsWorker
§3 Processing: SentimentProcessor, spike detection
§4 Agents: SentimentAgent, NewsThesisAgent, TelegramOpsAgent
§5 Operator I/O: AlertRouter for Telegram + X outbound
"""
